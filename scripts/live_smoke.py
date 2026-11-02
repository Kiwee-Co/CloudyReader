"""Live smoke test for the entity resolvers. Run it yourself, outside the agent sandbox.

Usage: uv run python -I scripts/live_smoke.py
Sends only the probe words below, over HTTPS, to PubChem and UniProt; OPSIN runs locally.
Prints one line per probe, the raw start of every response that was not ok, and a verdict on the
response shapes the resolvers assume. Always exits 0: read the verdict, not the exit status.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from cloudyreader.config import Settings, load_settings
from cloudyreader.models import Resolution
from cloudyreader.resolvers.http import HttpClient, dig
from cloudyreader.resolvers.opsin import OpsinResolver
from cloudyreader.resolvers.pubchem import PubChemResolver
from cloudyreader.resolvers.uniprot import UniProtResolver

RAW_CHARS = 300


@dataclass(frozen=True)
class Probe:
    service: Literal["pubchem", "opsin", "uniprot"]
    query: str
    expect: Literal["ok", "not_found"] = "ok"
    kind: Literal["protein", "gene"] = "protein"  # UniProt only: the label the caller would give


PROBES = (
    Probe("pubchem", "aspirin"),
    Probe("pubchem", "acetone"),
    Probe("pubchem", "sodium chloride"),
    Probe("opsin", "2-methylpropan-1-ol"),
    Probe("uniprot", "hemoglobin"),
    Probe("uniprot", "insulin"),
    Probe("uniprot", "BRCA1", kind="gene"),
    Probe("uniprot", "p53"),
    Probe("uniprot", "amylase"),
    # Letter soup that is no compound and no protein: the not_found path of each service.
    Probe("pubchem", "xqzvwplkjt", expect="not_found"),
    Probe("uniprot", "qzjxkvwpmt", expect="not_found"),
)


@dataclass(frozen=True)
class Exchange:
    """One HTTP response exactly as the server sent it."""

    url: str
    status: int
    body: str

    def parsed(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError:
            return None


class Recorder:
    """httpx response hook. The resolvers keep only what they parse; this keeps the raw reply."""

    def __init__(self) -> None:
        self.exchanges: list[Exchange] = []

    def __call__(self, response: httpx.Response) -> None:
        response.read()  # httpx runs hooks before it reads the body
        self.exchanges.append(Exchange(str(response.url), response.status_code, response.text))


@dataclass(frozen=True)
class Result:
    probe: Probe
    resolution: Resolution | None  # None: the resolver raised
    crash: str
    ms: float
    exchanges: tuple[Exchange, ...]

    @property
    def passed(self) -> bool:
        return self.resolution is not None and self.resolution.status == self.probe.expect


def run_probe(probe: Probe, resolve: Callable[[Probe], Resolution], recorder: Recorder) -> Result:
    recorder.exchanges.clear()
    resolution, crash = None, ""
    start = time.perf_counter()
    try:
        resolution = resolve(probe)
    except Exception as exc:  # a smoke test reports a crashing resolver and carries on
        crash = " ".join(f"{type(exc).__name__}: {exc}".split())  # keeps it on one line
    ms = (time.perf_counter() - start) * 1000
    return Result(probe, resolution, crash, ms, tuple(recorder.exchanges))


def probe_line(r: Result) -> str:
    head = f"{'pass' if r.passed else 'FAIL'}  {r.probe.service:<7} {r.probe.query!r:<22}"
    if r.resolution is None:
        return f"{head} CRASH {r.crash} {r.ms:.0f} ms"
    res = r.resolution
    return (
        f"{head} kind={res.kind} status={res.status} canonical={res.canonical!r} "
        f"ids={dict(res.ids)} {r.ms:.0f} ms"
    )


def printable(text: str) -> str:
    """Keep a hostile or binary body from steering the terminal."""
    return "".join(ch if ch.isprintable() or ch in "\n\r\t" else "?" for ch in text)


def raw_dump(r: Result) -> list[str]:
    if not r.exchanges:
        return ["      (no HTTP response recorded)"]
    lines = []
    for ex in r.exchanges:
        lines.append(f"      GET {ex.url} -> HTTP {ex.status}, first {RAW_CHARS} characters:")
        body = printable(ex.body[:RAW_CHARS]).splitlines() or ["(empty body)"]
        lines.extend(f"      | {line}" for line in body)
    return lines


@dataclass(frozen=True)
class Check:
    """One assumption the resolvers make about a response, judged on the probes it applies to."""

    scope: str
    label: str
    holds: Callable[[Exchange], bool]
    expect: Literal["ok", "not_found"] = "ok"


def shape_check(scope: str, *path: str | int) -> Check:
    label = "".join(f"[{step}]" if isinstance(step, int) else f".{step}" for step in path)

    def holds(ex: Exchange) -> bool:
        value = dig(ex.parsed(), *path)
        return isinstance(value, int | str) and value != ""

    return Check(scope, label.lstrip("."), holds)


CHECKS = (
    shape_check("pubchem", "PropertyTable", "Properties", 0, "CID"),
    shape_check("pubchem", "PropertyTable", "Properties", 0, "IUPACName"),
    shape_check("pubchem", "PropertyTable", "Properties", 0, "MolecularFormula"),
    Check("pubchem", "unknown name answers HTTP 404", lambda ex: ex.status == 404, "not_found"),
    shape_check("uniprot", "results", 0, "primaryAccession"),
    shape_check(
        "uniprot", "results", 0, "proteinDescription", "recommendedName", "fullName", "value"
    ),
    shape_check("uniprot", "results", 0, "genes", 0, "geneName", "value"),
    Check(
        "uniprot",
        "unknown query answers HTTP 200 and results []",
        lambda ex: ex.status == 200 and dig(ex.parsed(), "results") == [],
        "not_found",
    ),
)


def verdict_state(held: int, broken: int, total: int) -> str:
    """HELD: all true. PARTIAL: some. BROKEN: none, but answers came. NO DATA: no answer at all."""
    if held == total:
        return "HELD"
    if held:
        return "PARTIAL"
    return "BROKEN" if broken else "NO DATA"


def verdict_line(scope: str, label: str, outcomes: Mapping[str, bool | None]) -> str:
    """`outcomes` maps a probe word to True (held), False (did not), or None (no response)."""
    held = sum(1 for ok in outcomes.values() if ok)
    broken = sum(1 for ok in outcomes.values() if ok is False)
    state = verdict_state(held, broken, len(outcomes))
    fails = [query for query, ok in outcomes.items() if not ok]
    tail = f"  fails: {', '.join(fails)}" if fails else ""
    return f"{state:<8} {scope:<8} {label}  {held}/{len(outcomes)}{tail}"


def judge(check: Check, results: Sequence[Result]) -> str:
    outcomes = {
        r.probe.query: any(check.holds(ex) for ex in r.exchanges) if r.exchanges else None
        for r in results
        if (r.probe.service, r.probe.expect) == (check.scope, check.expect)
    }
    return verdict_line(check.scope, check.label, outcomes)


def within_budget(r: Result, budget_ms: float) -> bool | None:
    if r.resolution is not None and r.resolution.status == "timeout":
        return False  # the request itself ran out of time
    return r.ms <= budget_ms if r.exchanges else None  # a refused connection says nothing of speed


def latency_line(results: Sequence[Result], budget_ms: float) -> str:
    network = [r for r in results if r.probe.service != "opsin"]  # OPSIN is a local JVM start
    outcomes = {r.probe.query: within_budget(r, budget_ms) for r in network}
    times = [r.ms for r in network if outcomes[r.probe.query] is not None]
    stats = (
        f"median {statistics.median(times):.0f} ms, max {max(times):.0f} ms"
        if times
        else "no response to time"
    )
    label = f"each lookup within lookup_budget_s ({budget_ms:.0f} ms); {stats}"
    return verdict_line("latency", label, outcomes)


def contacted_line(results: Sequence[Result]) -> str:
    urls = [urlsplit(ex.url) for r in results for ex in r.exchanges]
    hosts = ", ".join(f"{host} x{n}" for host, n in Counter(u.hostname for u in urls).items())
    plain = sum(1 for u in urls if u.scheme != "https")
    return f"contacted: {hosts or 'nobody'}; non-HTTPS requests: {plain}"


def verdict(results: Sequence[Result], settings: Settings) -> list[str]:
    statuses = {r.probe.query: r.passed for r in results}
    checks = [
        *(judge(check, results) for check in CHECKS),
        verdict_line("probes", "answered with the expected status", statuses),
        latency_line(results, settings.lookup_budget_s * 1000),
    ]
    bad = sum(1 for line in checks if not line.startswith("HELD"))
    summary = "RESULT: every check held."
    if not any(r.exchanges for r in results):
        summary = "RESULT: no HTTP response at all. Check network, proxy and sandbox, then rerun."
    elif bad:
        summary = f"RESULT: {bad} of {len(checks)} checks did not hold. Paste this whole output."
    return [contacted_line(results), *checks, summary]


def main(*, settings: Settings | None = None) -> int:
    if settings is None:
        settings = load_settings({})  # defaults only: CLOUDYREADER_OFFLINE must not skip this test
    print(f"cloudyreader live smoke: {len(PROBES)} probes; only the probe words leave this machine")
    recorder = Recorder()
    results: list[Result] = []
    with httpx.Client(event_hooks={"response": [recorder]}) as client:
        http = HttpClient(
            timeout_s=settings.http_timeout_s, max_rps=settings.max_rps, client=client
        )
        pubchem, uniprot, opsin = PubChemResolver(http), UniProtResolver(http), OpsinResolver()
        resolvers: dict[str, Callable[[Probe], Resolution]] = {
            "pubchem": lambda p: pubchem.resolve(p.query),
            "uniprot": lambda p: uniprot.resolve(p.query, kind=p.kind),
            "opsin": lambda p: opsin.resolve_batch([p.query])[p.query],
        }
        for probe in PROBES:
            result = run_probe(probe, resolvers[probe.service], recorder)
            results.append(result)
            print(probe_line(result), flush=True)
            if result.resolution is None or result.resolution.status != "ok":
                print("\n".join(raw_dump(result)), flush=True)
    print("\n== verdict ==")
    print("\n".join(verdict(results, settings)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
