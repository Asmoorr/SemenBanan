from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from semen_banan.audio.jobs import AudioJobRunner
from semen_banan.audio.models import Arrangement, AudioResult, Score
from semen_banan.audio.validation import parse_arrangement, parse_score
from semen_banan.conversation.ports import Gateway
from semen_banan.errors import BotError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MusicReply:
    audio: AudioResult
    description: str


@dataclass(frozen=True, slots=True)
class MusicOptions:
    use_nano: bool
    solo: bool
    speech: bool
    drums: bool

    @classmethod
    def from_text(cls, text: str) -> MusicOptions:
        return cls(
            use_nano=bool(
                re.search(
                    r"\b(?:nano(?:maestro)?|наномаэстро|наномаестро|локальн\w*)\b", text, re.I
                )
            ),
            solo=bool(re.search(r"только\s+(?:на\s+)?(?:пианино|роял[ье])", text, re.I)),
            speech=not bool(re.search(r"без\s+(?:речи|голоса|слов)", text, re.I)),
            drums=not bool(re.search(r"без\s+(?:барабанов|ударных)", text, re.I)),
        )


class MusicGenerator:
    def __init__(self, gateway: Gateway, audio: AudioJobRunner, timeout: float) -> None:
        self.gateway = gateway
        self.audio = audio
        self.timeout = timeout

    async def generate(
        self,
        context: list[dict[str, str]],
        current: dict[str, str],
        style_requests: list[str] | None = None,
    ) -> MusicReply:
        options = MusicOptions.from_text(current["text"])
        score = await self._compose(context, current)
        arrangement = None
        if not options.solo:
            arrangement = await self._arrange(context, current, style_requests)
            if not options.speech:
                arrangement["speech"] = []
            if not options.drums:
                arrangement["drums"] = []
        try:
            audio = await self.audio.render(
                score, options.use_nano, arrangement, timeout=self.timeout
            )
        except RuntimeError as exc:
            raise BotError(str(exc)) from exc
        parts = ["пианино"]
        if arrangement is not None:
            if arrangement["drums"]:
                parts.append("барабаны")
            if arrangement["speech"]:
                parts.append("речь")
        if options.use_nano:
            parts.append("NanoMaestro")
        return MusicReply(audio, "[Семён записал: " + ", ".join(parts) + "]")

    async def _compose(self, context: list[dict[str, str]], current: dict[str, str]) -> Score:
        for attempt in range(2):
            content = await self.gateway.compose(context, current)
            try:
                return parse_score(content)
            except ValueError:
                if attempt:
                    raise BotError("Модель дважды вернула неверные ноты.") from None
        raise AssertionError("Unreachable composition retry state")

    async def _arrange(
        self,
        context: list[dict[str, str]],
        current: dict[str, str],
        style_requests: list[str] | None,
    ) -> Arrangement:
        correction = None
        for attempt in range(2):
            content = await self.gateway.arrange(
                context,
                current,
                style_requests=style_requests,
                correction=correction,
            )
            try:
                return parse_arrangement(content)
            except RuntimeError as exc:
                LOG.warning("%s", exc)
                if attempt:
                    raise BotError(str(exc)) from exc
                correction = {"error": str(exc), "previous_json": content}
        raise AssertionError("Unreachable arrangement retry state")
