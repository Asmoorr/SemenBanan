from __future__ import annotations


class BotError(Exception):
    """A user-readable error that never includes credential-bearing URLs."""
