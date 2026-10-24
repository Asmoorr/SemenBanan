from __future__ import annotations

from semen_banan.audio.composers import select_composer
from semen_banan.audio.encoding import encode_voice
from semen_banan.audio.mixing import backing_tracks, mix_tracks
from semen_banan.audio.models import AudioRequest, ComposerKind
from semen_banan.audio.rendering import render_piano


class AudioPipeline:
    """This pipeline runs only inside the disposable worker process."""

    def generate(self, request: AudioRequest) -> tuple[bytes, int]:
        kind = ComposerKind.NANOMAESTRO if request.use_nano else ComposerKind.SCORE
        notes = select_composer(kind).compose(request.score, seed=request.seed)
        piano, duration = render_piano(notes, request.score["tempo"])
        if request.arrangement is not None:
            drums, speech = backing_tracks(
                request.score["tempo"],
                len(request.score["chords"]) * 4,
                request.arrangement,
            )
            piano, duration = mix_tracks(piano, drums, speech)
        return encode_voice(piano), duration
