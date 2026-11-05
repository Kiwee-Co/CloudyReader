"""Real-world oracle: the NSB sample rounds cached by scripts/extract_samples.py (.data/samples).

Read from 241 rounds (pdftotext -layout; its default mode scrambled 571 of 11267 stems):
 1. Label: "N) EARTH SCIENCE Multiple Choice <stem>" (sets 1-8) or "N) Math – Short Answer <stem>"
    (EN DASH, Title Case, sets 9-16; the stem may start on the next line). 22 category spellings;
    formats also "Multiple choice", "MultipleChoice"; 50 labels carry a star ("*1)").
 2. TOSS-UP and BONUS both number from 1. Rounds hold 25+25, 23+23 or 15+15 pairs. A round title
    ("ROUND 10A", "ROUND ROBIN 2") opens each file. Blank lines split header, label, ANSWER.
 3. Choices: one per line, "W)" to "Z)". ANSWER: "ANSWER:" 11278, "Answer:" 16, "ANSWER :" 1,
    "ANSWER W) 3" 2, a bare "ANSWER:" with the text on the next line 30; may wrap;
    "(ACCEPT: ..)" 1194, "(DO NOT ACCEPT: ..)" 137, "[NOTE: ..]" and "[must give ..]" notes.
 4. Guides: 1998 respellings in 208 files: "[..]" 1748, "(PRONOUNCED: ..)" 7, "(read as: ..)" 243.
    CAPS stress in 1837, none in 148 ([jool] [tork] [saks] [ort]); macron vowels ō/Ō; digits,
    "[F.A.D.]", "[H-E-2-S-1]", stray spaces "[FYE- lum]", wraps "[SINK-row-<nl>lum]" (70).
 5. Brackets that are not guides: [He]2s1 cores, [Co(NH3)6]3+, intervals "(–10, 5]", spoken math
    "g(1) [g of 1]" (256: say the bracket, not the expression), moderator notes (12).
 6. Noise: ~20 page-footer shapes ("Middle School Round 1 Page 3", "PAGE 4", bare "3"), rules of
    "~", "*" and "_", stacked-fraction scraps between header and label ("BONUS / 4! / 3) MATH").
 7. Traps: 189 stem lines start "1) a square is.." (look like labels); U+2013 is both the category
    dash and a minus; math italics U+1D465, private-use U+F0E0/U+F8EB, U+FFFD; flattened scripts
    ("4.56 × 1011", "H 2 O", "CM3", "60º").
Tools: scripts/corpus_report.py (per-round report), tests/golden/corpus/* (guide oracle).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import os
import random
import re
import subprocess
import sys
import wave
from array import array
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from cloudyreader.models import Fmt, RenderOptions

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / ".data" / "samples"
GOLDEN = ROOT / "tests" / "golden" / "corpus"

# Measured 2026-11-01 on 241 rounds. Ratchet them up as the parser improves; never lower them.
MIN_PARSE_RATE = 0.995  # complete questions / expected (measured 99.92%)
MAX_PHANTOM_RATE = 0.002  # parsed questions without an answer / parsed (measured 0.03%)
MIN_WXYZ_RATE = 0.998  # multiple choice with exactly W, X, Y, Z (measured 99.91%)
MIN_GUIDE_RATE = 0.98  # respellings of every form the parser extracts (measured 99.1%)
MIN_IPA_RATE = 0.88  # corpus respellings that to_ipa places (measured 88.6%)


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


extract_samples = _load_script("extract_samples")
corpus_report = _load_script("corpus_report")

needs_corpus = pytest.mark.skipif(
    not (SAMPLES.is_dir() and any(SAMPLES.rglob("*.txt"))),
    reason=f"no corpus at {SAMPLES}: run `CLOUDYREADER_SAMPLES_SRC=DIR make samples`",
)


# ----------------------------------------------------------------------------- extractor (fast)


def _fake_pdftotext(monkeypatch, *, stdout=b"  ROUND 1   \n\n\n\nTOSS-UP  \n", code=0, err=b""):
    monkeypatch.setattr(extract_samples.shutil, "which", lambda name: "/fake/pdftotext")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr=err)

    monkeypatch.setattr(extract_samples.subprocess, "run", fake_run)
    return calls


def _fake_corpus(root: Path) -> Path:
    src = root / "src"
    for rel in ("Set-1/a.pdf", "Set-2/b.PDF", "Set-2/notes.md"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(b"%PDF fake")
    return src


def test_tidy_collapses_layout_padding_and_blank_runs():
    raw = "      ROUND 1     \n\n\n\nTOSS-UP\n1)   MATH   Short  Answer\n\n\n"

    assert extract_samples.tidy(raw) == "ROUND 1\n\nTOSS-UP\n1) MATH Short Answer\n"


def test_extract_mirrors_the_tree_and_never_writes_under_the_source(tmp_path, monkeypatch, capsys):
    calls = _fake_pdftotext(monkeypatch)
    src, dst = _fake_corpus(tmp_path), tmp_path / "dst"
    before = sorted(src.rglob("*"))

    code = extract_samples.run(src, dst)

    assert code == 0
    assert "ok=2 failed=0 skipped=0" in capsys.readouterr().out
    assert sorted(src.rglob("*")) == before
    assert (dst / "Set-1" / "a.txt").read_text() == "ROUND 1\n\nTOSS-UP\n"
    assert (dst / "Set-2" / "b.txt").exists()
    assert not (dst / "Set-2" / "notes.txt").exists()
    cmd = calls[0]
    assert cmd[0] == "/fake/pdftotext" and "-layout" in cmd and cmd[-1] == "-"


def test_extract_skips_fresh_outputs_and_redoes_stale_or_forced_ones(tmp_path, monkeypatch, capsys):
    calls = _fake_pdftotext(monkeypatch)
    src, dst = _fake_corpus(tmp_path), tmp_path / "dst"
    extract_samples.run(src, dst)
    capsys.readouterr()

    extract_samples.run(src, dst)
    assert "ok=0 failed=0 skipped=2" in capsys.readouterr().out

    stale = src / "Set-1" / "a.pdf"
    os.utime(stale, (stale.stat().st_atime, (dst / "Set-1" / "a.txt").stat().st_mtime + 10))
    extract_samples.run(src, dst)
    assert "ok=1 failed=0 skipped=1" in capsys.readouterr().out

    extract_samples.run(src, dst, force=True)
    assert "ok=2 failed=0 skipped=0" in capsys.readouterr().out
    assert len(calls) == 2 + 1 + 2


def test_extract_reports_a_failing_pdf_and_leaves_no_output(tmp_path, monkeypatch, capsys):
    _fake_pdftotext(monkeypatch, stdout=b"", code=1, err=b"Syntax Error: bad xref")
    src, dst = _fake_corpus(tmp_path), tmp_path / "dst"

    code = extract_samples.run(src, dst)

    captured = capsys.readouterr()
    assert code == 1
    assert "ok=0 failed=2 skipped=0" in captured.out
    assert "FAILED Set-1/a.pdf: Syntax Error: bad xref" in captured.err
    assert not list(dst.rglob("*.txt")) if dst.exists() else True


def test_extract_refuses_to_write_inside_the_read_only_source(tmp_path, monkeypatch, capsys):
    calls = _fake_pdftotext(monkeypatch)
    src = _fake_corpus(tmp_path)

    for dst in (src, src / "cache"):
        assert extract_samples.run(src, dst) == 2

    assert "refusing to write under the read-only source" in capsys.readouterr().err
    assert not calls and not (src / "cache").exists()


def test_extract_without_pdftotext_says_how_to_install_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(extract_samples.shutil, "which", lambda name: None)

    assert extract_samples.run(_fake_corpus(tmp_path), tmp_path / "dst") == 2
    assert "brew install poppler" in capsys.readouterr().err


def _record_run(monkeypatch):
    """Stand in for run(): keep the source main() hands it, extract nothing."""
    seen: list[Path] = []

    def fake_run(src, dst, force=False):
        seen.append(src)
        return 0

    monkeypatch.setattr(extract_samples, "run", fake_run)
    return seen


def test_main_without_a_source_exits_2_and_names_the_env_variable(monkeypatch, capsys):
    seen = _record_run(monkeypatch)
    monkeypatch.delenv("CLOUDYREADER_SAMPLES_SRC", raising=False)

    with pytest.raises(SystemExit) as exc:
        extract_samples.main([])

    err = capsys.readouterr().err
    assert exc.value.code == 2 and not seen
    assert "CLOUDYREADER_SAMPLES_SRC" in err and "--src DIR" in err
    assert "/Volumes/" not in err and "/Users/" not in err


def test_main_takes_the_source_from_the_env_variable(tmp_path, monkeypatch):
    seen = _record_run(monkeypatch)
    monkeypatch.setenv("CLOUDYREADER_SAMPLES_SRC", str(tmp_path / "pdfs"))

    assert extract_samples.main([]) == 0
    assert seen == [tmp_path / "pdfs"]


def test_main_src_option_beats_the_env_variable(tmp_path, monkeypatch):
    seen = _record_run(monkeypatch)
    monkeypatch.setenv("CLOUDYREADER_SAMPLES_SRC", str(tmp_path / "env"))

    assert extract_samples.main(["--src", str(tmp_path / "cli")]) == 0
    assert seen == [tmp_path / "cli"]


def test_extractor_hardcodes_no_disk_path():
    text = (ROOT / "scripts" / "extract_samples.py").read_text(encoding="utf-8")

    assert "/Volumes/" not in text and "/Users/" not in text


# --------------------------------------------------------------------------- harvest (fast)


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("FAR-ingks", "respelling"),
        ("jool", "respelling"),
        ("FYE- lum", "respelling"),
        ("SEE -zee- um", "respelling"),
        ("tek-NEE-shee-um 99 M", "respelling"),
        ("my-OH-sis one", "respelling"),
        ("F.A.D.", "respelling"),
        ("A. U. N. P’s", "respelling"),
        ("hōe-MOH-loh-gehs", "respelling"),
        ("H-E-2-S-1", "respelling"),
        ("He", "group"),
        ("Co(NH3)6", "group"),
        ("–10, 5", "group"),
        ("1", "group"),
        ("g of 1", "spoken"),
        ("4 and two-sevenths", "spoken"),
        ("Mg, S, O, 4, dot, 7, H, 2, O", "spoken"),
        ("yields", "spoken"),
        ("Oh two-minus", "spoken"),
        ("must give both answers", "note"),
        ("NOTE: STUDENTS MUST GIVE BOTH ANSWERS", "note"),
        ("See http://example.org/a.pdf", "note"),
    ],
)
def test_classify_tells_a_guide_from_the_brackets_that_are_not_guides(body, kind):
    assert corpus_report.classify(corpus_report.squash(body)) == kind


def test_harvest_joins_a_guide_wrapped_after_a_hyphen_and_keeps_the_line():
    text = "1) EARTH SCIENCE Short Answer The Synchrotron [SINK-row-\ntron] is\nANSWER: X"

    (guide,) = corpus_report.harvest(text, "Set", "r.txt")

    assert (guide.surface, guide.text, guide.wrapped, guide.line) == (
        "Synchrotron",
        "SINK-row-tron",
        True,
        1,
    )


def test_harvest_reads_the_parenthesized_forms_and_the_square_one():
    text = (
        "W) cotyledon (PRONOUNCED: KOT-ill-ee-don)\n"
        "X) fovea (read as: FOE-vee-ah)\n"
        "Y) 6! (read as: 4 factorial divided by 6 factorial)\n"
        "Z) Pharynx [FAR-ingks]\n"
    )

    found = [(g.form, g.kind, g.surface, g.text) for g in corpus_report.harvest(text, "S", "f")]

    assert found == [
        ("pronounced", "respelling", "cotyledon", "KOT-ill-ee-don"),
        ("read-as", "respelling", "fovea", "FOE-vee-ah"),
        ("read-as", "spoken", "6!", "4 factorial divided by 6 factorial"),
        ("square", "respelling", "Pharynx", "FAR-ingks"),
    ]


def test_a_hyphenated_pair_of_words_takes_both_printed_words_as_its_surface():
    text = "of glyceraldehyde 3-phosphate [glis-uh-RAL-duh-hyd 3 FOS-fayt]?"

    (guide,) = corpus_report.harvest(text, "S", "f")

    assert guide.surface == "glyceraldehyde 3-phosphate"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ROUND 1\nTOSS-UP\n1) MATH Short Answer 2+2?\nANSWER: 4\nBONUS\n1) ...\nANSWER: 5\n", 2),
        ("TOSS- UP\n1) x\nANSWER: 4\n", 1),
        ("1) MATH Short Answer 2+2?\nAnswer: 4\n2) MATH Short Answer 3+3?\nANSWER W) 6\n", 2),
        ("Energy is the capacity to do work.\n", 0),
    ],
)
def test_expected_questions_counts_headers_else_answer_lines(text, expected):
    assert corpus_report.expected_questions(text) == expected


def test_style_labels_name_the_notation_traits():
    labels = corpus_report.style_labels

    assert "stress: 1 CAPS syllable(s)" in labels("i-SOF-uh-guhs")
    assert "stress: none, all lowercase" in labels("jool")
    assert "stress: Title case only (Tee-o-door)" in labels("Tee-o-door")
    assert "stray space at hyphen (FYE- lum)" in labels("FYE- lum")
    assert labels("F.A.D.") == ["dotted letters (F.A.D.)"]


# ----------------------------------------------------------------------- report tool (fast)


def _q(**fields):
    base = dict(
        kind="toss-up",
        number=1,
        category="MATH",
        fmt=Fmt.SHORT_ANSWER,
        stem="What is 2 plus 2?",
        choices=(),
        answer="4",
        respellings=(),
    )
    return SimpleNamespace(**{**base, **fields})


def _choices(count):
    return tuple(SimpleNamespace(letter="WXYZ"[i], text="x", respellings=()) for i in range(count))


class _FakeParser:
    def __init__(self, questions=(), error=None):
        self.questions, self.error = questions, error

    def parse(self, text):
        if self.error:
            raise self.error
        return list(self.questions)


def test_parse_round_scores_each_defect_once():
    guide = corpus_report.Guide("Pharynx", "FAR-ingks", "square", "respelling", False, "S", "f", 3)
    seen = SimpleNamespace(surface="Pharynx", respelling="far-INGKS")
    questions = [
        _q(fmt=Fmt.MULTIPLE_CHOICE, choices=_choices(4)),
        _q(fmt=Fmt.MULTIPLE_CHOICE, choices=_choices(3), respellings=(seen,)),
        _q(kind=None, category=None, stem="", answer=None),
        _q(stem="Say [this]"),
    ]
    text = "TOSS-UP\n1) x\nANSWER: 1\nBONUS\n1) y\nANSWER: 2\n"

    stats, notes, missed = corpus_report.parse_round("S/f", text, [guide], _FakeParser(questions))

    assert (stats.expected, stats.found, stats.complete) == (2, 4, 2)
    assert (stats.no_category, stats.no_stem, stats.no_answer) == (1, 1, 1)
    assert (stats.bad_choices, stats.residue, stats.guides_found) == (1, 1, 1)
    assert (stats.guides_expected, stats.guides_missed, missed) == (1, 0, [])
    assert notes == ["S/f #1: ...Say [this]..."] and stats.problems


def test_parse_round_names_a_missed_guide_and_survives_a_crashing_parser():
    guide = corpus_report.Guide("jool", "jool", "square", "respelling", False, "S", "f", 7)

    stats, _, missed = corpus_report.parse_round("S/f", "TOSS-UP\n", [guide], _FakeParser())
    crashed, notes, _ = corpus_report.parse_round(
        "S/f", "TOSS-UP\n", [], _FakeParser(error=RuntimeError("boom"))
    )
    bare, _, _ = corpus_report.parse_round("S/f", "TOSS-UP\n", [guide], None)

    assert (stats.guides_missed, missed) == (1, [guide]) and stats.missed_forms == {"square": 1}
    assert crashed.crashed and notes == ["S/f: parser raised RuntimeError: boom"]
    assert bare.found is None and bare.expected == 1


ROUND = (
    "ROUND 1\n\nTOSS-UP\n\n1) LIFE SCIENCE Multiple Choice Which is NOT part of the\nrespiratory"
    " system?\nW) Pharynx [FAR-ingks]\nX) Larynx [LAR-ingks]\nY) Esophagus [i-SOF-uh-guhs]\n"
    "Z) Trachea [TRAY-kee-uh]\nANSWER: Y) ESOPHAGUS\n\nBONUS\n\n"
    "1) MATH Short Answer Find g(1) [g of 1] when g(a) = 3a.\nANSWER: 3 [qq-zz]\n"
)


def test_report_run_prints_the_table_and_writes_the_golden_files(tmp_path, capsys):
    (tmp_path / "samples" / "Set-1").mkdir(parents=True)
    (tmp_path / "samples" / "Set-1" / "r1.txt").write_text(ROUND)
    golden = tmp_path / "golden"

    corpus_report.run(tmp_path / "samples", problems_only=False, golden=golden)

    out = capsys.readouterr().out
    assert "Set-1/r1.txt" in out and "1 rounds; expected 2," in out
    assert "to_ipa coverage:" in out and "guides harvested:" in out
    rows = (golden / "respellings.tsv").read_text().splitlines()
    assert rows[0] == "word\trespelling\tset\tfile\tline"
    assert "Pharynx\tFAR-ingks\tSet-1\tr1.txt\t7" in rows
    assert "g(1)\tg of 1\tSet-1\tr1.txt\t15" in (golden / "spoken_forms.tsv").read_text()
    notation = (golden / "notation.txt").read_text()
    assert "## respelling traits" in notation and "## NOT respellings" in notation


def test_report_never_fails_without_a_corpus(tmp_path, capsys):
    assert corpus_report.main(["--samples", str(tmp_path / "missing")]) == 0
    assert "run scripts/extract_samples.py first" in capsys.readouterr().out


def test_report_can_hide_the_clean_rounds(tmp_path, monkeypatch, capsys):
    parser_module = pytest.importorskip("cloudyreader.parser")
    monkeypatch.setattr(parser_module, "QuestionParser", lambda: _FakeParser([_q()]))
    (tmp_path / "Set-1").mkdir()
    (tmp_path / "Set-1" / "clean.txt").write_text("TOSS-UP\n1) x\nANSWER: 1\n")
    (tmp_path / "Set-1" / "short.txt").write_text("TOSS-UP\nANSWER: 1\nBONUS\nANSWER: 2\n")

    assert corpus_report.main(["--samples", str(tmp_path), "--problems-only"]) == 0

    out = capsys.readouterr().out
    assert "Set-1/short.txt" in out and "Set-1/clean.txt" not in out


def test_parse_round_survives_a_question_shape_it_does_not_know():
    stats, notes, _ = corpus_report.parse_round(
        "S/f", "TOSS-UP\n", [], _FakeParser([SimpleNamespace()])
    )

    assert stats.crashed and stats.found == 1
    assert notes[0].startswith("S/f: scoring raised AttributeError")


def test_report_survives_a_parser_that_fails_to_import_and_a_to_ipa_that_raises(
    tmp_path, monkeypatch, capsys
):
    broken = ModuleType("cloudyreader.parser")

    def explode(name):
        raise SyntaxError("half-edited parser.py")

    broken.__getattr__ = explode
    monkeypatch.setitem(sys.modules, "cloudyreader.parser", broken)
    respell = pytest.importorskip("cloudyreader.respell")
    monkeypatch.setattr(respell, "to_ipa", explode)
    (tmp_path / "Set-1").mkdir()
    (tmp_path / "Set-1" / "r1.txt").write_text(ROUND)

    assert corpus_report.main(["--samples", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "cloudyreader.parser failed to import (SyntaxError: half-edited parser.py)" in out
    assert "to_ipa coverage: 0/5 guides placed" in out


# ------------------------------------------------------------------- respelling oracle (fast)


def test_the_golden_respellings_are_placed_by_to_ipa_and_never_crash_it():
    respell = pytest.importorskip("cloudyreader.respell")
    rows = [line.split("\t") for line in (GOLDEN / "respellings.tsv").read_text().splitlines()[1:]]
    assert len(rows) > 1000

    placed = sum(respell.to_ipa(row[1]) is not None for row in rows)

    assert placed / len(rows) >= MIN_IPA_RATE, f"{placed}/{len(rows)} placed"


# Hand-labeled for the entity detector, written without running it. Rows: id, text, entity, label,
# occurrence (n-th substring match, left to right), note; an empty entity marks a negative text.
GOLD_HEADER = "id\ttext\tentity\tlabel\toccurrence\tnote"
GOLD_LABELS = {"chemical", "formula", "protein", "gene", "skip"}
GOLD_ID = re.compile(r"[^/:]+/[^:]+:\d+#(?:stem|[WXYZ]|answer)")


def _gold_rows() -> list[list[str]]:
    lines = (GOLDEN / "entities.tsv").read_text(encoding="utf-8").split("\n")
    assert lines[0] == GOLD_HEADER and lines[-1] == ""
    return [line.split("\t") for line in lines[1:-1]]


def _gold_span(text: str, entity: str, occurrence: int) -> tuple[int, int]:
    pos = -1
    for _ in range(occurrence):
        pos = text.find(entity, pos + 1)
        assert pos >= 0, f"{entity!r} x{occurrence} not in {text!r}"
    return pos, pos + len(entity)


def test_the_entity_gold_set_is_well_formed_and_balanced():
    rows = _gold_rows()
    texts: dict[str, str] = {}
    by_id: dict[str, list[list[str]]] = {}
    for row in rows:
        assert len(row) == 6, row
        id_, text, entity, label, occurrence, _note = row
        assert GOLD_ID.fullmatch(id_) and text and texts.setdefault(id_, text) == text, id_
        assert (entity == "") == (label == "") == (occurrence == ""), row
        assert label == "" or label in GOLD_LABELS, row
        by_id.setdefault(id_, []).append(row)
    spans = 0
    for id_, group in by_id.items():
        if group[0][2] == "":
            assert len(group) == 1, f"{id_}: a negative text has exactly one row"
            continue
        taken: list[tuple[int, int]] = []
        for _id, text, entity, label, occurrence, _note in group:
            assert occurrence.isdigit() and int(occurrence) >= 1, (id_, entity)
            start, end = _gold_span(text, entity, int(occurrence))
            if label != "skip":
                assert all(end <= s or start >= e for s, e in taken), f"{id_}: {entity!r} overlaps"
                taken.append((start, end))
                spans += 1
        keys = [(r[2], r[4]) for r in group]
        assert len(keys) == len(set(keys)), f"{id_}: duplicate entity row"
    labels = {r[3] for r in rows}
    negatives = [i for i, g in by_id.items() if g[0][2] == ""]
    spaced = {r[0] for r in rows if r[5] == "spaced" and r[3] == "formula"}
    assert len(by_id) >= 40 and len(negatives) >= 10 and len(spaced) >= 4 and spans >= 60
    assert GOLD_LABELS <= labels and len({i.split("/")[0] for i in by_id}) >= 8


# ------------------------------------------------------------------------ real corpus (slow)


@pytest.fixture(scope="module")
def rounds():
    found = corpus_report.load_rounds(SAMPLES)
    return [r for r in found if corpus_report.expected_questions(r[2])]


@pytest.fixture(scope="module")
def parser_module():
    return pytest.importorskip("cloudyreader.parser", reason="cloudyreader.parser not written yet")


@pytest.fixture(scope="module")
def scored(rounds, parser_module):
    parser = parser_module.QuestionParser()
    out = []
    for set_name, file_name, text in rounds:
        guides = corpus_report.harvest(text, set_name, file_name)
        name = f"{set_name}/{file_name}"
        out.append((*corpus_report.parse_round(name, text, guides, parser), guides))
    return out


@pytest.fixture(scope="module")
def parsed(rounds, parser_module):
    parser = parser_module.QuestionParser()
    return {f"{s}/{f}": parser.parse(text) for s, f, text in rounds}


@pytest.fixture(scope="module")
def spoken(parsed):
    normalize = pytest.importorskip("cloudyreader.normalize", reason="normalize not written yet")
    normalizer = normalize.ScriptNormalizer()
    opts = RenderOptions()
    return [
        (name, q, normalizer.to_script([q], {}, opts).text())
        for name, questions in parsed.items()
        for q in questions
    ]


@pytest.mark.slow
@needs_corpus
def test_no_round_crashes_the_parser(scored):
    assert [stats.name for stats, *_ in scored if stats.crashed] == []


@pytest.mark.slow
@needs_corpus
def test_parse_rate_on_real_rounds(scored):
    expected = sum(stats.expected for stats, *_ in scored)
    complete = sum(stats.complete for stats, *_ in scored)
    worst = sorted((s for s, *_ in scored), key=lambda s: s.complete / s.expected)[:3]

    assert complete / expected >= MIN_PARSE_RATE, (
        f"{complete}/{expected} complete; worst: "
        + ", ".join(f"{s.name} {s.complete}/{s.expected}" for s in worst)
    )


@pytest.mark.slow
@needs_corpus
def test_phantom_questions_stay_rare(scored):
    found = sum(stats.found for stats, *_ in scored)
    phantom = sum(stats.no_answer for stats, *_ in scored)

    assert phantom / found <= MAX_PHANTOM_RATE, f"{phantom} of {found} parsed lack an ANSWER"


@pytest.mark.slow
@needs_corpus
def test_multiple_choice_has_w_x_y_z(parsed):
    mc = [q for qs in parsed.values() for q in qs if q.fmt is Fmt.MULTIPLE_CHOICE]
    good = [q for q in mc if "".join(c.letter for c in q.choices) == "WXYZ"]

    assert len(mc) > 4000
    assert len(good) / len(mc) >= MIN_WXYZ_RATE, f"{len(good)}/{len(mc)} have W, X, Y, Z"


@pytest.mark.slow
@needs_corpus
def test_respellings_of_every_form_are_extracted_from_the_text(scored):
    wanted = sum(g.kind == "respelling" for *_, guides in scored for g in guides)
    missed = [g for _, _, missed, _ in scored for g in missed]

    assert wanted > 1900
    assert 1 - len(missed) / wanted >= MIN_GUIDE_RATE, f"{len(missed)} of {wanted} guides missed"


@pytest.mark.slow
@needs_corpus
def test_spoken_script_never_holds_a_bracket_or_an_answer_marker(spoken):
    leaks = [
        (name, q.number, hit.group())
        for name, q, text in spoken
        if (hit := re.search(r"[\[\]]|ANSWER", text))
    ]

    assert leaks == [], f"{len(leaks)} scripts leak, first: {leaks[:3]}"


@pytest.mark.slow
@needs_corpus
def test_spoken_script_holds_no_page_footer(spoken):
    footer = re.compile(r"\bPage \d+|\bPAGE \d+|~{3,}")
    leaks = [(name, q.number) for name, q, text in spoken if footer.search(text)]

    assert leaks == []


@pytest.mark.slow
@needs_corpus
def test_spoken_script_holds_no_private_use_or_replacement_glyph(spoken):
    junk = re.compile("[\ue000-\uf8ff\ufffd]")
    leaks = [(name, q.number) for name, q, text in spoken if junk.search(text)]

    assert leaks == []


def _answer_probe(answer: str) -> str | None:
    """The first accepted answer, as lowercase words, when it is long enough to spot in speech."""
    core = re.sub(r"^[WXYZ]\)\s*", "", answer.strip())
    core = re.split(r"\s*(?:\(|;|\bOR\b|\bAND\b)", core)[0].strip(" .").lower()
    return core if re.fullmatch(r"[a-z][a-z -]{5,}", core) else None


@pytest.mark.slow
@needs_corpus
def test_r2_an_answer_is_spoken_only_when_asked_for(parsed):
    normalize = pytest.importorskip("cloudyreader.normalize", reason="normalize not written yet")
    normalizer = normalize.ScriptNormalizer()
    quiet, loud = RenderOptions(), RenderOptions(read_answer=True)
    leaks, silent, probed = [], [], 0
    for name, questions in parsed.items():
        for q in questions:
            probe = _answer_probe(q.answer or "")
            visible = " ".join([q.stem, q.category or "", *(c.text for c in q.choices)]).lower()
            if probe is None or probe in visible:
                continue
            probed += 1
            if probe in normalizer.to_script([q], {}, quiet).text().lower():
                leaks.append((name, q.number, probe))
            if "answer." not in normalizer.to_script([q], {}, loud).text().lower():
                silent.append((name, q.number))

    assert probed > 1000
    assert leaks == [], f"answer spoken by default: {leaks[:3]}"
    assert silent == [], f"read_answer did not speak the answer: {silent[:3]}"


@pytest.mark.voice
@pytest.mark.slow
@needs_corpus
def test_eight_random_questions_become_audible_speech_end_to_end(tmp_path, parsed):
    pipeline = pytest.importorskip("cloudyreader.pipeline", reason="pipeline not written yet")
    config = pytest.importorskip("cloudyreader.config")
    env = {"CLOUDYREADER_DATA_DIR": str(ROOT / ".data"), "CLOUDYREADER_OFFLINE": "1"}
    settings = dataclasses.replace(config.load_settings(env), cache_dir=tmp_path / "cache")
    settings.cache_dir.mkdir()
    service = pipeline.build_default_service(settings)
    voices = [v for v in service.voices() if v.engine == "piper" and v.installed]
    if not voices:
        pytest.skip("no installed Piper voice in .data/voices: run `make voices`")
    pool = [
        q
        for name in sorted(parsed)
        for q in parsed[name]
        if q.kind and q.category and q.stem and q.answer and 40 < len(q.raw) < 600
    ]
    picked = random.Random(20261101).sample(pool, 8)

    reading = service.prepare(
        "\n\n".join(q.raw for q in picked), voices[0].key, RenderOptions(online_lookups=False)
    )

    with wave.open(str(reading.audio.wav_path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth()) == (1, 2)
        rate, frames = wav.getframerate(), wav.readframes(wav.getnframes())
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    duration, chars = len(samples) / rate, len(reading.script.text())
    probe = samples[::50]
    rms = math.sqrt(sum(s * s for s in probe) / len(probe))
    assert len(reading.questions) == 8
    assert chars / 40 <= duration <= chars / 4, f"{duration:.1f}s for {chars} spoken chars"
    assert abs(duration - reading.audio.duration_s) < 0.5
    assert max(map(abs, samples)) > 3000 and rms > 200, "audio is (near) silent"
