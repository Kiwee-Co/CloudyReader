"""Voice rotation: which installed voice reads next, per mode. UI thread only; never raises."""

from __future__ import annotations

import logging
import random
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from cloudyreader.voice_meta import VoiceProfile, profile_of

if TYPE_CHECKING:
    from cloudyreader.models import VoiceInfo

log = logging.getLogger(__name__)


class RotationMode(StrEnum):
    """Menu order. The value is the id the window stores in its settings."""

    NONE = "none"
    ROUND_ROBIN = "round_robin"
    SHUFFLE = "shuffle"
    US_SHUFFLE = "us_shuffle"
    MEN_SHUFFLE = "men_shuffle"
    WOMEN_SHUFFLE = "women_shuffle"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def parse(cls, value: object) -> RotationMode:
        """The mode whose id is `value`; NONE for None, junk, or a non-string."""
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                pass
        return cls.NONE


_LABELS = {
    RotationMode.NONE: "No rotation",
    RotationMode.ROUND_ROBIN: "Round robin",
    RotationMode.SHUFFLE: "Random shuffle",
    RotationMode.US_SHUFFLE: "US only (random shuffle)",
    RotationMode.MEN_SHUFFLE: "Men only",
    RotationMode.WOMEN_SHUFFLE: "Women only",
}


def _fits(mode: RotationMode, profile: VoiceProfile) -> bool:
    if mode is RotationMode.US_SHUFFLE:
        return profile.accent == "en-US"
    if mode is RotationMode.MEN_SHUFFLE:
        return profile.gender == "male"
    if mode is RotationMode.WOMEN_SHUFFLE:
        return profile.gender == "female"
    return True


class VoiceRotator:
    """Picks the voice for the next reading. The deck and last pick live in memory only."""

    def __init__(
        self, mode: RotationMode = RotationMode.NONE, *, rng: random.Random | None = None
    ) -> None:
        self._mode = RotationMode.parse(mode)
        self._rng = rng if rng is not None else random.Random()
        self._deck: list[str] = []  # keys still to deal this cycle, next one first
        self._last_key: str | None = None

    @property
    def mode(self) -> RotationMode:
        return self._mode

    @property
    def last_key(self) -> str | None:
        return self._last_key

    def set_mode(self, mode: RotationMode) -> None:
        """Drops the deck. Keeps the last pick, so the next deck does not open with it."""
        self._mode = RotationMode.parse(mode)
        self._deck = []

    def pool(self, voices: Sequence[VoiceInfo]) -> list[VoiceInfo]:
        """Installed single-speaker voices with a known profile that fit the mode, in list order.

        A repeated key counts once. NONE, ROUND_ROBIN and SHUFFLE keep every such voice.
        """
        try:
            candidates = list(voices)
        except TypeError:  # None or another non-iterable: no voices
            return []
        pool: list[VoiceInfo] = []
        seen: set[str] = set()
        for voice in candidates:
            profile = profile_of(voice)
            if (
                profile is None
                or not getattr(voice, "installed", False)
                or getattr(voice, "num_speakers", None) != 1
                or not _fits(self._mode, profile)
                or voice.key in seen
            ):
                continue
            seen.add(voice.key)
            pool.append(voice)
        return pool

    def next_voice(self, voices: Sequence[VoiceInfo]) -> VoiceInfo | None:
        """The voice for the next reading. None: mode NONE or an empty pool (use the picker)."""
        if self._mode is RotationMode.NONE:
            return None
        pool = self.pool(voices)
        if not pool:
            log.debug("rotation %s: no installed voice fits", self._mode)
            return None
        if self._mode is RotationMode.ROUND_ROBIN:
            picked = self._after_last(pool)
        else:
            picked = self._deal(pool)
        self._last_key = picked.key
        log.debug("rotation %s: %s", self._mode, picked.key)
        return picked

    def _after_last(self, pool: list[VoiceInfo]) -> VoiceInfo:
        keys = [voice.key for voice in pool]
        if self._last_key in keys:
            return pool[(keys.index(self._last_key) + 1) % len(pool)]
        return pool[0]  # nothing picked yet, or the last voice left the pool

    def _deal(self, pool: list[VoiceInfo]) -> VoiceInfo:
        by_key = {voice.key: voice for voice in pool}
        self._deck = [key for key in self._deck if key in by_key]  # voices that left drop out
        if not self._deck:
            self._deck = list(by_key)
            self._rng.shuffle(self._deck)
            if len(self._deck) > 1 and self._deck[0] == self._last_key:
                slot = self._rng.randrange(1, len(self._deck))  # never the same voice twice
                self._deck[0], self._deck[slot] = self._deck[slot], self._deck[0]
        return by_key[self._deck.pop(0)]
