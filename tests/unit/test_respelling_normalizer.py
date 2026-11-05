"""P6b: a respelling Override carries its guide's text for the engines that take no IPA."""

from __future__ import annotations

import re

import pytest

from cloudyreader.models import Choice, Question, RenderOptions, Resolution, Respelling
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import parse

DEFAULT = RenderOptions()
READ = RenderOptions(read_answer=True)
PHARYNX = Respelling("Pharynx", "FAR-ingks")
IUPAC_NAME = "2-methylpropan-1-ol"
PASTE = (
    "TOSS-UP 8) LIFE SCIENCE Multiple Choice Which structure closes over the trachea "
    "[TRAY-kee-uh] during swallowing?\n"
    "W) Epiglottis [ep-uh-GLOT-is]\n"
    "X) Alveolus [al-VEE-uh-lus]\n"
    "Y) Diaphragm [DY-uh-fram]\n"
    "Z) Bronchus [BRONG-kus]\n"
    "ANSWER: W) EPIGLOTTIS [ep-uh-GLOT-is]\n"
)
GUIDES = {
    "trachea": "TRAY-kee-uh",
    "Epiglottis": "ep-uh-GLOT-is",
    "Alveolus": "al-VEE-uh-lus",
    "Diaphragm": "DY-uh-fram",
    "Bronchus": "BRONG-kus",
}


def question(
    stem: str,
    *,
    choices: tuple[Choice, ...] = (),
    answer: str | None = None,
    respellings: tuple[Respelling, ...] = (),
) -> Question:
    return Question(None, None, None, None, stem, choices, answer, "", respellings)


def fake_stages() -> ScriptNormalizer:
    """The bundled lexicon; identity formula and unit stages; IPA = the respelling in <>."""
    return ScriptNormalizer(
        speak_formulas=lambda t: t, speak_units=lambda t: t, to_ipa=lambda r: f"<{r}>"
    )


def whole_word(surface: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(surface)}(?!\w)", text) is not None


@pytest.mark.parametrize(
    ("q", "opts", "surface", "respelling"),
    [
        pytest.param(
            question("The Pharynx here.", respellings=(PHARYNX,)),
            DEFAULT,
            "Pharynx",
            "FAR-ingks",
            id="stem",
        ),
        pytest.param(
            question(
                "Pick.",
                choices=(
                    Choice("W", "Pharynx", (PHARYNX,)),
                    Choice("X", "b"),
                    Choice("Y", "c"),
                    Choice("Z", "d"),
                ),
            ),
            DEFAULT,
            "Pharynx",
            "FAR-ingks",
            id="choice",
        ),
        pytest.param(
            question("Q?", answer="PHARYNX [FAR-ingks]"),
            READ,
            "Pharynx",
            "FAR-ingks",
            id="shouted-answer",
        ),
        pytest.param(
            question(
                "The Krebs cycle runs.", respellings=(Respelling("Krebs cycle", "KREBZ SY-kul"),)
            ),
            DEFAULT,
            "Krebs cycle",
            "KREBZ SY-kul",
            id="multi-word",
        ),
    ],
)
def test_normalizer_carries_the_guide_respelling(q, opts, surface, respelling):
    script = fake_stages().to_script([q], {}, opts)

    (segment,) = [seg for seg in script.segments if seg.overrides]
    (override,) = segment.overrides

    assert (override.surface, override.ipa, override.source) == (
        surface,
        f"<{respelling}>",
        "respelling",
    )
    assert override.respelling == respelling  # as printed: the engine lowercases it
    assert whole_word(surface, segment.text) and respelling not in segment.text


def test_lexicon_and_iupac_overrides_have_no_respelling():
    res = {IUPAC_NAME: Resolution(IUPAC_NAME, "iupac", None, {}, "opsin", "ok")}
    q = question(f"The asthenosphere, {IUPAC_NAME} and the Pharynx.", respellings=(PHARYNX,))

    (segment,) = fake_stages().to_script([q], res, DEFAULT).segments

    assert sorted((o.source, o.surface, o.respelling) for o in segment.overrides) == [
        ("iupac", IUPAC_NAME, ""),
        ("lexicon", "asthenosphere", ""),
        ("respelling", "Pharynx", "FAR-ingks"),
    ]


def test_a_reading_keeps_the_printed_words_and_carries_each_respelling():
    script = ScriptNormalizer().to_script(parse(PASTE), {}, READ)  # every stage real

    respelled = [
        (seg, o) for seg in script.segments for o in seg.overrides if o.source == "respelling"
    ]

    assert sorted(o.surface for _, o in respelled) == sorted([*GUIDES, "Epiglottis"])  # + answer
    for seg, o in respelled:
        assert whole_word(o.surface, seg.text), seg.text  # the printed word is what the text says
        assert o.respelling == GUIDES[o.surface], o.surface
        assert o.ipa
    others = [o for seg in script.segments for o in seg.overrides if o.source != "respelling"]
    assert all(o.respelling == "" for o in others)
    assert not any(guide in script.text() for guide in GUIDES.values())
    assert script.warnings == ()
