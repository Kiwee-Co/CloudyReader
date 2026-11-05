"""Voice padding at the choice-letter pause, cut so that pause sounds alike in every voice.

Kokoro wraps every line in about 0.4 s of near silence, Piper in a few ms. A choice letter is its
own segment, so that padding would lengthen LETTER_PAUSE_MS on both sides of it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np

from cloudyreader.models import Segment
from cloudyreader.normalize import LETTER_PAUSE_MS

WINDOW_S = 0.010  # levels are compared in 10 ms windows
FLOOR_DB = -45.0  # a window this far under the segment's loudest window is padding
PAD_S = 0.030  # kept next to the sound, so a soft onset or decay is never cut
_LETTER = re.compile(r"[WXYZ]\.")


def audible_span(samples: np.ndarray, rate: int) -> tuple[int, int]:
    """Start and end of the sound in `samples` (any dtype), each widened by PAD_S.

    A window is sound when its RMS is within FLOOR_DB of the loudest window. All silence is kept
    whole: without sound there is no padding to tell apart.
    """
    count = len(samples)
    if count == 0:
        return 0, 0
    window = max(1, round(rate * WINDOW_S))
    starts = np.arange(0, count, window)
    x = np.asarray(samples, dtype=np.float64)  # squared in int16, full scale would overflow
    energy = np.add.reduceat(x * x, starts) / np.diff(np.append(starts, count))
    loudest = energy.max()
    if loudest == 0.0:
        return 0, count
    sound = np.flatnonzero(energy >= loudest * 10 ** (FLOOR_DB / 10))
    pad = round(rate * PAD_S)
    return max(0, int(starts[sound[0]]) - pad), min(count, int(starts[sound[-1]]) + window + pad)


def is_choice_letter(segment: Segment) -> bool:
    """A choice letter with its text next: "W." and LETTER_PAUSE_MS, as the normalizer writes it."""
    return segment.pause_after_ms == LETTER_PAUSE_MS and _LETTER.fullmatch(segment.text) is not None


def trim_letter_padding(
    segments: Sequence[Segment], speech: Sequence[np.ndarray], rate: int
) -> list[np.ndarray]:
    """`speech`, one array per segment, with the padding cut after each choice letter and before
    its text. Every other edge keeps the voice's own padding."""
    out = list(speech)
    for i in range(len(segments) - 1):
        if is_choice_letter(segments[i]):
            out[i] = out[i][: audible_span(out[i], rate)[1]]
            out[i + 1] = out[i + 1][audible_span(out[i + 1], rate)[0] :]
    return out
