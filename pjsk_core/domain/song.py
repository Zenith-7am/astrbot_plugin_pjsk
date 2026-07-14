"""Song value object — a track entity in Project SEKAI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Song:
    """A song in Project SEKAI.

    id is the internal PJSK song id.
    title_ja, title_cn, title_en cover the three display title forms.
    aliases is a JSON-encoded list of alternative search names.
    """

    id: int
    title_ja: str
    title_cn: str
    title_en: str
    aliases: str
