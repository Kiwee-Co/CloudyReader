"""Map General American IPA to the phoneme alphabet Kokoro-82M was trained on (misaki).

Override.ipa uses the espeak-ng en-us symbol set. Kokoro's US voices expect misaki phonemes:
diphthongs as single letters (eɪ -> A), U+0261 instead of ASCII g, and the stress mark placed
directly before the vowel. Anything the model cannot encode is returned, never dropped silently.
"""

from __future__ import annotations

import re

# Every symbol in the pinned model's config.json "vocab" (mlx-community/Kokoro-82M-bf16 @ a71e4d38).
# The model silently skips any other character, so callers must never see one.
MODEL_VOCAB = frozenset(
    ';:,.!?—…"()“” ̃ʣʥʦʨᵝꭧAIOQSTWYᵊ'
    "abcdefhijklmnopqrstuvwxyzɑɐɒ\xe6βɔɕ\xe7ɖ\xf0ʤ"
    "əɚɛɜɟɡɥɨɪʝɯɰŋɳ"
    "ɲɴ\xf8ɸθœɹɾɻʁɽʂʃʈʧ"
    "ʊʋʌɣɤχʎʒʔˈˌːʰʲ"
    "↓→↗↘ᵻ"
)

# Sentence punctuation is in the vocab, but inside one word's pronunciation it would make a pause.
PAUSE_PUNCTUATION = frozenset(';:,!?—…"()“”')

# misaki's vowel letters; a stress mark must sit right before one of them.
VOWELS = "AIOQWYaiuæɑɒɔəɛɜɪʊʌᵻ"

_TIES = str.maketrans("", "", "͜͡")
_SYLLABIC = re.compile("(\\S)̩")  # n̩ -> ᵊn, as misaki's espeak fallback does
_CHAR_FIXES = str.maketrans({"g": "ɡ", "r": "ɹ", "ɫ": "l"})
# Order matters: longer sequences first, diphthongs before bare e/o.
_SEQUENCES = (
    ("ɜːɹ", "ɜɹ"),
    ("ɜː", "ɜɹ"),
    ("eɪ", "A"),
    ("aɪ", "I"),
    ("oʊ", "O"),
    ("aʊ", "W"),
    ("ɔɪ", "Y"),
    ("dʒ", "ʤ"),
    ("tʃ", "ʧ"),
    ("ɪə", "iə"),
    ("ɝ", "ɜɹ"),
    ("ɚ", "əɹ"),
    ("oːɹ", "ɔɹ"),
    ("oɹ", "ɔɹ"),
    ("eɹ", "ɛɹ"),
    ("ɹɹ", "ɹ"),
)
_SINGLES = str.maketrans(
    {"ɾ": "T", "ɐ": "ə", "x": "k", "ç": "k", "ɬ": "l", "e": "A", "o": "O", "̃": None}
)
_DROPPED = str.maketrans("", "", "ːˑ.")
_STRESS = re.compile(f"([ˈˌ])([^{VOWELS}\\s]+)")


def ipa_to_misaki(ipa: str) -> tuple[str, list[str]]:
    """Return (misaki phonemes, rejected symbols). Rejected symbols are removed from the result."""
    ps = _SYLLABIC.sub("ᵊ\\1", ipa.translate(_TIES)).translate(_CHAR_FIXES)
    for old, new in _SEQUENCES:
        ps = ps.replace(old, new)
    ps = " ".join(ps.translate(_SINGLES).translate(_DROPPED).split())
    ps = _STRESS.sub("\\2\\1", ps)
    rejected: list[str] = []
    kept: list[str] = []
    for ch in ps:
        if ch in PAUSE_PUNCTUATION or ch not in MODEL_VOCAB:
            if ch not in rejected:
                rejected.append(ch)
        else:
            kept.append(ch)
    return " ".join("".join(kept).split()), rejected
