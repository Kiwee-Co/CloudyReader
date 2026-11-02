"""Report how cloudyreader copes with the real NSB corpus in .data/samples; it never fails.

Usage: python -I scripts/corpus_report.py [--samples DIR] [--problems-only] [--write-golden DIR]
The respelling harvest here also writes tests/golden/corpus/*, so the report and those oracle
files cannot drift apart. Imports of cloudyreader stages are lazy: a missing one is named.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / ".data" / "samples"
DEFAULT_GOLDEN = ROOT / "tests" / "golden" / "corpus"

_HEADER = re.compile(r"^\W*(?:toss[\s-]*up|bonus)\W*$", re.IGNORECASE)
_ANSWER = re.compile(r"^\s*answer\s*(?::|(?=[WXYZ]\)))", re.IGNORECASE)
# Page footers, rules and header words that must never reach a spoken stem or choice.
_RESIDUE = re.compile(
    r"[\[\]]|ANSWER|TOSS-?\s?UP|\bBONUS\b|\bPAGE\s*\d|\bPage\s*\d|~{3,}|\*{3,}|_{3,}",
)

_SQUARE = re.compile(r"\[([^\[\]]{1,160})\]")
_PAREN = re.compile(r"\((pronounced|read as)\s*:?\s*([^()]{1,160})\)", re.IGNORECASE)
_BARE_READ_AS = re.compile(r"(?<!\()\bRead as:\s*(.+)", re.IGNORECASE)
_NOTE = re.compile(r"\s*(?:note\b|must\b|accept\b)|http|www\.", re.IGNORECASE)
_DOTTED = re.compile(r"(?:[A-Za-z]\.\s?)+[A-Za-z]?(?:[’']s)?")
_ELEMENT_LIKE = re.compile(r"[A-Z][a-z]?")
# Letters include the macron vowels (ō) some guides use, so \w minus digits and underscore.
_TOKEN = re.compile(r"(?:[^\W_]|[’'.])+(?:[- ]+(?:[^\W_]|[’'.])+)*")
_SINGLE_WORD = re.compile(r"[^\W\d_]+(?:[’'][^\W\d_]+)?")
# Everyday words that appear in spoken-math brackets ("g of 1") and never in a respelling.
_SPOKEN_WORDS = frozenset(
    "and of the to over equals plus minus times squared cubed power star sub inverse root "
    "fraction numerator denominator negative with is a by per point half percent degrees "
    "theta sine cosine tangent yields prime".split()
)
# Math words that can sit inside a hyphenated spoken token ("two-minus").
_MATH_WORDS = frozenset("plus minus over times squared cubed equals power".split())
_VOWELS = re.compile(r"[aeiouy]+")
_CONSONANTS = re.compile(r"[bcdfghjklmnpqrstvwxz]+")


@dataclass(frozen=True)
class Guide:
    """One bracketed or parenthesized aid found in a round, with where it sits."""

    surface: str
    text: str  # whitespace squashed, hyphen-wraps joined
    form: str  # "square" | "pronounced" | "read-as" | "read-as-bare"
    kind: str  # "respelling" | "spoken" | "note" | "group"
    wrapped: bool
    set: str
    file: str
    line: int


def squash(raw: str) -> str:
    """Join a guide wrapped after a hyphen without a space; collapse every other run."""
    return " ".join(re.sub(r"-[ \t]*\n[ \t]*", "-", raw).split())


def tighten(text: str) -> str:
    """Drop the stray spaces around hyphens ("FYE- lum") that PDF wraps leave behind."""
    return re.sub(r"\s*-\s*", "-", text)


def classify(text: str) -> str:
    """Sort a squashed bracket body into respelling / spoken / note / group."""
    tight = tighten(text)
    tokens = tight.split()
    if _NOTE.match(text) or "http" in text.lower() or "www." in text.lower():
        return "note"
    if len(tokens) >= 2 and _SPOKEN_WORDS & {t.lower() for t in tokens}:
        return "spoken"
    if _MATH_WORDS & set(re.split(r"[-\s]+", tight.lower())):
        return "spoken"
    if len(tokens) >= 3 and "," in tight:
        return "spoken"
    if tight.lower() == "yields":
        return "spoken"
    if _DOTTED.fullmatch(tight):
        return "respelling"
    if _ELEMENT_LIKE.fullmatch(tight) or re.search(r"[()+=*/^%]|[A-Za-z]\d|\d[A-Za-z]", tight):
        return "group"
    if re.fullmatch(r"\d+", tight):
        return "group"
    if _TOKEN.fullmatch(tight) and ("-" in tight or _SINGLE_WORD.fullmatch(tight)):
        return "respelling"
    if len(tokens) >= 2 and not any(char.isdigit() for char in tight):
        return "spoken"
    return "group"


def surface_of(prefix: str, text: str) -> str:
    """The printed word(s) a guide follows; one word per hyphenated token of a multi-word guide."""
    hyphenated = sum("-" in token for token in tighten(text).split())
    surface = " ".join(prefix.split()[-max(1, hyphenated) :]).strip(",;:.\"'“”‘’*")
    # Keep the parentheses of "g(1)"; drop only an unmatched one such as the "(" of "(pH".
    if surface.startswith("(") and ")" not in surface:
        surface = surface[1:]
    if surface.endswith(")") and "(" not in surface:
        surface = surface[:-1]
    return surface


def harvest(text: str, set_name: str, file_name: str) -> list[Guide]:
    """Every square-bracket and (pronounced|read as: ...) guide in one round's text."""
    found: list[Guide] = []

    def add(match: re.Match[str], body: str, form: str) -> None:
        squashed = squash(body)
        kind = classify(squashed)
        if form == "pronounced" and kind != "note":
            kind = "respelling"
        found.append(
            Guide(
                surface_of(text[max(0, match.start() - 200) : match.start()], squashed),
                squashed,
                form,
                kind,
                "\n" in body,
                set_name,
                file_name,
                text.count("\n", 0, match.start()) + 1,
            )
        )

    for match in _SQUARE.finditer(text):
        add(match, match.group(1), "square")
    for match in _PAREN.finditer(text):
        form = "pronounced" if match.group(1).lower() == "pronounced" else "read-as"
        add(match, match.group(2), form)
    for match in _BARE_READ_AS.finditer(text):
        squashed = squash(match.group(1))
        found.append(
            Guide(
                surface_of(text[max(0, match.start() - 200) : match.start()], squashed),
                squashed,
                "read-as-bare",
                "spoken",
                False,
                set_name,
                file_name,
                text.count("\n", 0, match.start()) + 1,
            )
        )
    return sorted(found, key=lambda g: g.line)


def load_rounds(samples: Path) -> list[tuple[str, str, str]]:
    """(set, file, text) for every cached round, sorted."""
    return [
        (path.parent.name, path.name, path.read_text(encoding="utf-8"))
        for path in sorted(samples.rglob("*.txt"))
    ]


def expected_questions(text: str) -> int:
    """TOSS-UP/BONUS header lines (each opens one question), else ANSWER lines."""
    lines = text.splitlines()
    headers = sum(bool(_HEADER.match(line)) for line in lines)
    return headers or sum(bool(_ANSWER.match(line)) for line in lines)


def style_labels(text: str) -> list[str]:
    """Notation traits of one respelling, for the counts in notation.txt."""
    tight = tighten(text)
    if _DOTTED.fullmatch(tight):
        return ["dotted letters (F.A.D.)"]
    tokens = tight.split()
    syllables = [s for token in tokens for s in re.split(r"[-.]", token) if s.isalpha()]
    long = [s for s in syllables if len(s) > 1]
    caps = [s for s in long if s.isupper()]
    labels = ["hyphenated" if "-" in tight else "single token"]
    if len(tokens) > 1:
        labels.append("multi-word (space)")
    if syllables and not long:
        labels.append("spelled letters (K-A-T)")
    elif not caps and any(s[0].isupper() for s in long):
        labels.append("stress: Title case only (Tee-o-door)")
    elif not caps:
        labels.append("stress: none, all lowercase")
    elif len(caps) == len(long) and len(caps) > 1:
        labels.append("stress: every syllable CAPS")
    else:
        labels.append(f"stress: {min(len(caps), 3)}{'+' if len(caps) > 2 else ''} CAPS syllable(s)")
    if any(char.isdigit() for char in tight):
        labels.append("has digit")
    if re.search(r"[’']", tight):
        labels.append("has apostrophe")
    if re.search(r"\s-|-\s", text):
        labels.append("stray space at hyphen (FYE- lum)")
    return labels


def _top(counter: Counter[str], limit: int) -> str:
    return " ".join(f"{key}:{count}" for key, count in counter.most_common(limit))


def notation_report(guides: Iterable[Guide]) -> list[str]:
    guides = list(guides)
    resp = [g for g in guides if g.kind == "respelling"]
    files = {(g.set, g.file) for g in resp}
    lines = [
        "# NSB respelling notation actually used in the sample corpus (generated by",
        "# scripts/corpus_report.py --write-golden; do not edit by hand).",
        f"guides: {len(guides)} bracketed/parenthesized groups; {len(resp)} are pronunciation",
        f"respellings, in {len(files)} round files. Other kinds are listed at the end.",
        "",
        "## kind x form (counts)",
    ]
    for (kind, form), count in sorted(Counter((g.kind, g.form) for g in guides).items()):
        lines.append(f"{kind:11s} {form:13s} {count}")
    lines += ["", "## respelling traits (a guide can have several)"]
    traits: Counter[str] = Counter()
    for guide in resp:
        traits.update(style_labels(guide.text))
    lines += [f"{count:6d} {label}" for label, count in traits.most_common()]
    lines.append(f"{sum(g.wrapped for g in resp):6d} guide wrapped over two lines after a hyphen")
    body = "".join(tighten(g.text) for g in resp)
    chars = Counter(char for char in body if not char.isalpha())
    lines += ["", "## non-letter characters inside respellings", _top(chars, 20)]
    accented = Counter(char for char in body if char.isalpha() and not char.isascii())
    lines += ["", "## non-ASCII letters inside respellings (macron vowels: ōe = long o)"]
    lines.append(_top(accented, 10))
    syllables = Counter(
        s.lower() for g in resp for s in re.split(r"[-\s.]+", tighten(g.text)) if s.isalpha()
    )
    lines += ["", "## most frequent syllables (lowercased)", _top(syllables, 70)]
    vowels = Counter(run for s in syllables.elements() for run in _VOWELS.findall(s))
    lines += ["", "## vowel-letter runs (every spelling a rule table must place)"]
    lines.append(_top(vowels, 60))
    consonants = Counter(run for s in syllables.elements() for run in _CONSONANTS.findall(s))
    lines += ["", "## consonant-letter runs", _top(consonants, 60)]
    lines += ["", "## examples per trait"]
    shown: set[str] = set()
    for guide in resp:
        for label in style_labels(guide.text):
            if label not in shown:
                shown.add(label)
                lines.append(f"{label}: {guide.surface} [{guide.text}] ({guide.set}/{guide.file})")
    lines += ["", "## NOT respellings (must not be spoken as a pronunciation)"]
    for kind, note in (
        ("spoken", "how to say the expression before it (read it instead of the expression)"),
        ("note", "moderator instructions, never read aloud"),
        ("group", "chemistry/maths grouping such as [He]2s1, [Co(NH3)6]3+, [1]"),
    ):
        picks = [g for g in guides if g.kind == kind]
        lines.append(f"{kind} ({len(picks)}): {note}")
        lines += [f"    {g.surface} [{g.text}]  {g.set}/{g.file}:{g.line}" for g in picks[:6]]
    return lines


def write_golden(guides: list[Guide], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = ["word\trespelling\tset\tfile\tline"]
    rows += [
        f"{g.surface}\t{g.text}\t{g.set}\t{g.file}\t{g.line}"
        for g in guides
        if g.kind == "respelling"
    ]
    (out_dir / "respellings.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    spoken = ["expression\tspoken\tset\tfile\tline"]
    spoken += [
        f"{g.surface}\t{g.text}\t{g.set}\t{g.file}\t{g.line}" for g in guides if g.kind == "spoken"
    ]
    (out_dir / "spoken_forms.tsv").write_text("\n".join(spoken) + "\n", encoding="utf-8")
    (out_dir / "notation.txt").write_text(
        "\n".join(notation_report(guides)) + "\n", encoding="utf-8"
    )


@dataclass
class RoundStats:
    name: str
    expected: int
    found: int | None = None
    complete: int = 0
    no_category: int = 0
    no_stem: int = 0
    no_answer: int = 0
    bad_choices: int = 0
    guides_found: int = 0
    guides_expected: int = 0
    guides_missed: int = 0
    missed_forms: Counter[str] = field(default_factory=Counter)
    residue: int = 0
    crashed: bool = False

    @property
    def problems(self) -> bool:
        counts = (self.no_category, self.no_stem, self.no_answer, self.bad_choices)
        return (
            self.crashed
            or self.found != self.expected
            or any(counts)
            or bool(self.guides_missed or self.residue)
        )


def parse_round(
    name: str, text: str, guides: list[Guide], parser: object | None
) -> tuple[RoundStats, list[str], list[Guide]]:
    """Score one round; returns its stats, residue/crash notes and the guides the parser missed."""
    stats = RoundStats(name, expected_questions(text))
    stats.guides_expected = sum(g.kind == "respelling" for g in guides)
    notes: list[str] = []
    if parser is None:
        return stats, notes, []
    try:
        questions = parser.parse(text)  # type: ignore[attr-defined]
    except Exception as exc:  # a report must survive any parser bug
        stats.crashed = True
        notes.append(f"{name}: parser raised {type(exc).__name__}: {exc}")
        return stats, notes, []
    stats.found = len(questions)
    seen: set[str] = set()
    try:
        for q in questions:
            stats.no_category += q.category is None
            stats.no_stem += not q.stem.strip()
            stats.no_answer += not (q.answer or "").strip()
            # Fmt is a str Enum, so the value compares without importing the contracts module.
            wrong = len(q.choices) != 4 and (q.fmt == "multiple-choice" or bool(q.choices))
            stats.bad_choices += wrong
            stats.complete += bool(
                q.kind and q.category and q.stem.strip() and (q.answer or "").strip() and not wrong
            )
            found_here = list(q.respellings) + [r for c in q.choices for r in c.respellings]
            stats.guides_found += len(found_here)
            seen.update(tighten(r.respelling).lower() for r in found_here)
            for chunk in [q.stem, *(c.text for c in q.choices)]:
                hit = _RESIDUE.search(chunk)
                if hit:
                    stats.residue += 1
                    around = chunk[max(0, hit.start() - 25) : hit.end() + 25]
                    notes.append(f"{name} #{q.number}: ...{around}...")
                    break
    except Exception as exc:  # a Question shape the report does not know
        stats.crashed = True
        notes.append(f"{name}: scoring raised {type(exc).__name__}: {exc}")
    missed = [g for g in guides if g.kind == "respelling" and tighten(g.text).lower() not in seen]
    stats.guides_missed = len(missed)
    stats.missed_forms.update(g.form for g in missed)
    return stats, notes, missed


def _print_table(rows: list[RoundStats]) -> None:
    head = f"{'round':44s} {'exp':>4s} {'found':>5s} {'ok':>4s} {'noCat':>5s} {'noStm':>5s}"
    print(head + f" {'noAns':>5s} {'badMC':>5s} {'guides f/e/miss':>16s} {'resid':>5s}")
    for s in rows:
        found = "-" if s.found is None else str(s.found)
        guides = f"{s.guides_found}/{s.guides_expected}/{s.guides_missed}"
        print(
            f"{s.name:44.44s} {s.expected:4d} {found:>5s} {s.complete:4d} {s.no_category:5d} "
            f"{s.no_stem:5d} {s.no_answer:5d} {s.bad_choices:5d} {guides:>16s} {s.residue:5d}"
            f"{' CRASH' if s.crashed else ''}"
        )


def _safe_ipa(to_ipa: Callable[[str], str | None], text: str) -> str | None:
    try:
        return to_ipa(text)
    except Exception:  # a raising to_ipa counts as "not placed"; the contract says None
        return None


def _ipa_coverage(guides: list[Guide]) -> None:
    try:
        from cloudyreader.respell import to_ipa  # lazy: another stream owns it
    except Exception as exc:  # same reason as the parser import
        print(f"\nto_ipa coverage: skipped (cloudyreader.respell: {type(exc).__name__}: {exc})")
        return
    texts = Counter(g.text for g in guides if g.kind == "respelling")
    failed = {text: n for text, n in texts.items() if _safe_ipa(to_ipa, text) is None}
    total, bad = sum(texts.values()), sum(failed.values())
    print(f"\nto_ipa coverage: {total - bad}/{total} guides placed ({len(failed)} distinct fail)")
    for text, count in sorted(failed.items(), key=lambda kv: -kv[1])[:25]:
        print(f"    {count:3d}x [{text}]")


def run(samples: Path, problems_only: bool, golden: Path | None) -> None:
    if not samples.is_dir():
        print(f"no corpus at {samples}: run scripts/extract_samples.py first")
        return
    parser: object | None = None
    try:
        from cloudyreader.parser import QuestionParser  # lazy: it may not exist yet

        parser = QuestionParser()
    except Exception as exc:  # mid-edit parsers raise SyntaxError, not only ImportError
        print(f"cloudyreader.parser failed to import ({type(exc).__name__}: {exc}): expected only")
    rows: list[RoundStats] = []
    all_guides: list[Guide] = []
    notes: list[str] = []
    missed: list[Guide] = []
    for set_name, file_name, text in load_rounds(samples):
        guides = harvest(text, set_name, file_name)
        all_guides += guides
        stats, round_notes, round_missed = parse_round(
            f"{set_name}/{file_name}", text, guides, parser
        )
        rows.append(stats)
        notes += round_notes
        missed += round_missed
    _print_table([s for s in rows if s.problems or not problems_only])
    expected = sum(s.expected for s in rows)
    complete = sum(s.complete for s in rows)
    rate = f"{100 * complete / expected:.1f}%" if expected else "n/a"
    found = sum(s.found or 0 for s in rows)
    print(f"\n{len(rows)} rounds; expected {expected}, found {found}, complete {complete} = {rate}")
    for label, attr in (
        ("missing category", "no_category"),
        ("missing stem", "no_stem"),
        ("missing answer", "no_answer"),
        ("multiple choice != 4 choices", "bad_choices"),
        ("respellings missed", "guides_missed"),
        ("questions with residue", "residue"),
    ):
        print(f"{label:30s} {sum(getattr(s, attr) for s in rows)}")
    print(f"respellings missed by form: {dict(Counter(g.form for g in missed))}")
    print(f"guides harvested: {dict(Counter(g.kind for g in all_guides))}")
    for title, items in (
        ("residue / crash examples", notes),
        ("missed respelling examples", [f"{g.set}/{g.file}:{g.line} [{g.text}]" for g in missed]),
    ):
        if items:
            print(f"\n{title} (first 12 of {len(items)}):")
            print("\n".join(f"    {item}" for item in items[:12]))
    _ipa_coverage(all_guides)
    if golden is not None:
        write_golden(all_guides, golden)
        print(f"\nwrote respellings.tsv, spoken_forms.tsv, notation.txt to {golden}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report parser/normalizer fit on the NSB corpus.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--problems-only", action="store_true", help="hide clean rounds")
    parser.add_argument(
        "--write-golden",
        nargs="?",
        type=Path,
        const=DEFAULT_GOLDEN,
        help="regenerate the respelling oracle files (default tests/golden/corpus)",
    )
    args = parser.parse_args(argv)
    run(args.samples, args.problems_only, args.write_golden)
    return 0


if __name__ == "__main__":
    sys.exit(main())
