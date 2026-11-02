"""ChainResolver: routing, cache, OPSIN batching, offline, the budget, and what is never sent."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import respx

import cloudyreader.resolvers.chain as chain_module
from cloudyreader.config import Settings
from cloudyreader.models import EntitySpan, Resolution
from cloudyreader.resolvers.cache import ResolutionCache
from cloudyreader.resolvers.chain import ChainResolver, looks_iupac
from cloudyreader.resolvers.http import MAX_QUERY_CHARS, HttpClient
from cloudyreader.resolvers.pubchem import PubChemResolver
from cloudyreader.resolvers.uniprot import UniProtResolver

ROOT = Path(__file__).resolve().parents[3]
PUBCHEM = "pubchem.ncbi.nlm.nih.gov"
UNIPROT = "rest.uniprot.org"
LOGGER = "cloudyreader.resolvers.chain"
CAFFEINE = Resolution(
    "caffeine",
    "chemical",
    "1,3,7-trimethylpurine-2,6-dione",
    {"cid": "2519", "formula": "C8H10N4O2"},
    "pubchem",
    "ok",
)


def span(text: str, label="chemical") -> EntitySpan:
    return EntitySpan(0, len(text), text, label, "ner")


class Backend:
    """A fake PubChem and UniProt that records every request it gets."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.compounds = {
            "caffeine": (2519, "C8H10N4O2", "1,3,7-trimethylpurine-2,6-dione"),
            "glucose": (5793, "C6H12O6", "(2R,3S,4R,5R)-2,3,4,5,6-pentahydroxyhexanal"),
            "aspirin": (2244, "C9H8O4", "2-acetyloxybenzoic acid"),
            "nahco3": (516892, "CHNaO3", "sodium hydrogen carbonate"),
            "n/a": (1, "X", "slash"),
            "acetic acid (glacial)": (176, "C2H4O2", "acetic acid"),
        }
        self.proteins = {"brca1": "P38398", "insulin": "P01308", "p53": "P04637"}
        self.requests: list[httpx.Request] = []
        self.gates: dict[str, threading.Event] = {}  # a name's answer waits for its gate
        self.delay_s = 0.0
        # A status code or an error that answers every request instead of the tables.
        self.fault: int | Exception | None = None
        router.route(host=PUBCHEM).mock(side_effect=self._pubchem)
        router.route(host=UNIPROT).mock(side_effect=self._uniprot)

    def count(self, host: str | None = None) -> int:
        return len([r for r in self.requests if host in (None, r.url.host)])

    def _answer(self, request: httpx.Request, name: str) -> httpx.Response | None:
        self.requests.append(request)
        if name in self.gates:
            self.gates[name].wait(10)
        time.sleep(self.delay_s)
        if isinstance(self.fault, Exception):
            raise self.fault
        return None if self.fault is None else httpx.Response(self.fault)

    def _pubchem(self, request: httpx.Request) -> httpx.Response:
        name = unquote(request.url.raw_path.decode().split("/")[5])
        if (fault := self._answer(request, name)) is not None:
            return fault
        record = self.compounds.get(name.casefold())
        if record is None:
            return httpx.Response(404, json={"Fault": {"Code": "PUGREST.NotFound"}})
        cid, formula, iupac = record
        row = {"CID": cid, "MolecularFormula": formula, "IUPACName": iupac}
        return httpx.Response(200, json={"PropertyTable": {"Properties": [row]}})

    def _uniprot(self, request: httpx.Request) -> httpx.Response:
        name = request.url.params["query"]
        if (fault := self._answer(request, name)) is not None:
            return fault
        accession = self.proteins.get(name.casefold())
        hits = [] if accession is None else [{"primaryAccession": accession}]
        return httpx.Response(200, json={"results": hits})


class FakeOpsin:
    """OpsinResolver stand-in: parses the names in `known` (name -> SMILES), records each batch."""

    def __init__(self, known: dict[str, str] | None = None) -> None:
        self.known = known or {}
        self.batches: list[list[str]] = []
        self.timeouts: list[float] = []
        self.error: Exception | None = None

    def resolve_batch(
        self, names: Sequence[str], *, timeout_s: float = 20.0
    ) -> dict[str, Resolution]:
        self.batches.append(list(names))
        self.timeouts.append(timeout_s)
        if self.error is not None:
            raise self.error
        return {n: self._one(n) for n in names}

    def _one(self, name: str) -> Resolution:
        if name in self.known:
            return Resolution(
                name, "iupac", self.known[name], {"smiles": self.known[name]}, "opsin", "ok"
            )
        return Resolution(name, "iupac", None, {}, "opsin", "not_found")


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def backend(router) -> Backend:
    return Backend(router)


@pytest.fixture
def cache(tmp_path: Path) -> ResolutionCache:
    return ResolutionCache(tmp_path / "resolutions.sqlite3")


@pytest.fixture
def opsin() -> FakeOpsin:
    return FakeOpsin()


@pytest.fixture
def build(tmp_path, backend, cache, opsin):
    def make(*, skip=None, offline=False, budget=2.5):
        settings = Settings(
            tmp_path, tmp_path, tmp_path, tmp_path, lookup_budget_s=budget, offline=offline
        )
        http = HttpClient(timeout_s=4.0, max_rps=1000.0, sleep=lambda _: None)
        return ChainResolver(
            cache=cache,
            opsin=opsin,
            pubchem=PubChemResolver(http),
            uniprot=UniProtResolver(http),
            settings=settings,
            skip=skip,
        )

    return make


@pytest.fixture
def chain(build) -> ChainResolver:
    return build()


@pytest.mark.parametrize(
    "name",
    [
        "2-methylpropan-1-ol",
        "1,2-dichloroethane",
        "N,N-dimethylformamide",
        "trans-2-butene",
        "(E)-but-2-ene",
        "ethanoic acid",
        "propanone",
        "cyclohexene",
        "3-methylpentane",
        "ethyl ethanoate",
        "methanol",
        "benzene",
        "phenol",
        "ethylene glycol",
    ],
)
def test_systematic_looking_names_are_sent_to_opsin(name):
    assert looks_iupac(name)


# OPSIN answers `ok` for element words and trivial names too (lead, tin, water, glucose), so
# `ok` proves a name parses, not that it is systematic. Only systematic-looking names may go in.
@pytest.mark.parametrize(
    "name",
    [
        *["lead", "tin", "iron", "gold", "zinc", "water", "glucose", "sodium bicarbonate"],
        *["caffeine", "aspirin", "ATP", "sodium chloride", "insulin", "methionine"],
        *["baking soda", "sugar", "salt", "acid"],
    ],
)
def test_element_words_and_common_names_skip_the_jvm(name):
    assert not looks_iupac(name)


def test_nothing_to_resolve_gives_nothing_and_touches_nothing(chain, backend, opsin):
    assert chain.resolve_many([], timeout_s=1.0) == {}
    assert backend.count() == 0
    assert opsin.batches == []


def test_chemical_goes_to_pubchem(chain, backend):
    result = chain.resolve_many([span("caffeine")], timeout_s=2.0)
    assert result == {"caffeine": CAFFEINE}
    assert (backend.count(PUBCHEM), backend.count(UNIPROT)) == (1, 0)


@pytest.mark.parametrize("label", ["protein", "gene"])
def test_protein_and_gene_go_to_uniprot_with_their_own_kind(chain, backend, label):
    result = chain.resolve_many([span("BRCA1", label)], timeout_s=2.0)
    assert result["BRCA1"].kind == label
    assert result["BRCA1"].ids == {"accession": "P38398"}
    assert result["BRCA1"].source == "uniprot"
    assert (backend.count(PUBCHEM), backend.count(UNIPROT)) == (0, 1)


@pytest.mark.parametrize("label", ["formula", "other"])
def test_formulas_and_other_entities_are_never_looked_up(chain, backend, opsin, label):
    assert chain.resolve_many([span("NaHCO3", label), span("H2O", label)], timeout_s=2.0) == {}
    assert backend.count() == 0
    assert opsin.batches == []


def test_lexicon_skip_means_no_lookup_and_no_entry(build, backend):
    seen: list[str] = []

    def skip(text: str) -> bool:
        seen.append(text)
        return text == "caffeine"

    result = build(skip=skip).resolve_many([span(" caffeine "), span("aspirin")], timeout_s=2.0)
    assert set(result) == {"aspirin"}
    assert seen == ["caffeine", "aspirin"]
    assert backend.count() == 1


def test_same_text_is_looked_up_once_whatever_its_case(chain, backend):
    result = chain.resolve_many(
        [span("Caffeine"), span("caffeine"), span("CAFFEINE")], timeout_s=2.0
    )
    assert backend.count() == 1
    assert {k: v.query for k, v in result.items()} == {
        "Caffeine": "Caffeine",
        "caffeine": "caffeine",
        "CAFFEINE": "CAFFEINE",
    }
    assert {v.canonical for v in result.values()} == {CAFFEINE.canonical}


def test_first_label_wins_for_a_text_that_is_two_kinds_of_entity(chain, backend):
    result = chain.resolve_many(
        [span("insulin", "chemical"), span("insulin", "protein")], timeout_s=2.0
    )
    assert result["insulin"].kind == "chemical"
    assert (backend.count(PUBCHEM), backend.count(UNIPROT)) == (1, 0)


def test_an_ignored_label_does_not_claim_the_text(chain, backend):
    result = chain.resolve_many(
        [span("insulin", "other"), span("insulin", "protein")], timeout_s=2.0
    )
    assert result["insulin"].kind == "protein"


def test_surface_text_is_never_replaced_by_a_resolved_name(chain, backend):
    # R5: a resolution only tells HOW to say a token. The key and `query` stay the pasted text,
    # so "NaHCO3" can never turn into the name that gives the answer away.
    result = chain.resolve_many([span("NaHCO3")], timeout_s=2.0)
    assert set(result) == {"NaHCO3"}
    assert result["NaHCO3"].query == "NaHCO3"
    assert result["NaHCO3"].canonical == "sodium hydrogen carbonate"
    assert "baking soda" not in repr(result)


def test_second_call_is_answered_from_the_cache(chain, backend):
    chain.resolve_many([span("caffeine")], timeout_s=2.0)
    again = chain.resolve_many([span("caffeine")], timeout_s=2.0)
    assert backend.count() == 1
    assert again["caffeine"] == Resolution(
        "caffeine", "chemical", CAFFEINE.canonical, CAFFEINE.ids, "cache", "ok"
    )


def test_cache_hit_keeps_the_callers_spelling(chain, backend):
    chain.resolve_many([span("Caffeine")], timeout_s=2.0)
    again = chain.resolve_many([span("CAFFEINE")], timeout_s=2.0)
    assert backend.count() == 1
    assert again["CAFFEINE"].query == "CAFFEINE"
    assert again["CAFFEINE"].source == "cache"


def test_a_miss_is_cached_too(chain, backend):
    first = chain.resolve_many([span("zzzzz")], timeout_s=2.0)
    second = chain.resolve_many([span("zzzzz")], timeout_s=2.0)
    assert first["zzzzz"].status == "not_found"
    assert (second["zzzzz"].status, second["zzzzz"].source) == ("not_found", "cache")
    assert backend.count() == 1


def test_cache_keeps_chemical_and_protein_apart(chain, backend):
    chain.resolve_many([span("insulin", "chemical")], timeout_s=2.0)
    result = chain.resolve_many([span("insulin", "protein")], timeout_s=2.0)
    assert result["insulin"].kind == "protein"
    assert result["insulin"].status == "ok"
    assert (backend.count(PUBCHEM), backend.count(UNIPROT)) == (1, 1)


@pytest.mark.parametrize(
    ("fault", "status"),
    [
        (503, "error"),
        (500, "error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "offline"),
    ],
)
def test_failures_are_reported_and_never_cached(chain, backend, fault, status):
    backend.fault = fault
    first = chain.resolve_many([span("caffeine")], timeout_s=2.0)
    assert (first["caffeine"].status, first["caffeine"].source) == (status, "pubchem")
    backend.fault = None
    second = chain.resolve_many([span("caffeine")], timeout_s=2.0)
    assert second["caffeine"] == CAFFEINE


def test_a_lookup_that_blows_up_is_an_error_and_spares_the_others(chain, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("bug in the resolver")

    monkeypatch.setattr(PubChemResolver, "resolve", boom)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        result = chain.resolve_many([span("caffeine"), span("BRCA1", "gene")], timeout_s=2.0)
    assert result["caffeine"].status == "error"
    assert result["BRCA1"].status == "ok"
    assert "bug in the resolver" in caplog.text


@pytest.mark.parametrize("text", ["", "   ", "\n", "a" * (MAX_QUERY_CHARS + 1), "bad\x00name"])
def test_an_entity_that_must_not_be_sent_gets_no_entry_and_no_request(chain, backend, text):
    assert chain.resolve_many([span(text), span(text, "protein")], timeout_s=2.0) == {}
    assert backend.count() == 0


def test_opsin_gets_one_batch_with_only_the_systematic_names(chain, backend, opsin):
    opsin.known = {"2-methylpropan-1-ol": "CC(C)CO", "1,2-dichloroethane": "ClCCCl"}
    spans = [span("2-methylpropan-1-ol"), span("caffeine"), span("1,2-dichloroethane")]
    result = chain.resolve_many(spans, timeout_s=2.0)
    assert opsin.batches == [["2-methylpropan-1-ol", "1,2-dichloroethane"]]
    assert result["2-methylpropan-1-ol"] == Resolution(
        "2-methylpropan-1-ol", "iupac", "CC(C)CO", {"smiles": "CC(C)CO"}, "opsin", "ok"
    )
    assert result["caffeine"] == CAFFEINE
    assert backend.count(PUBCHEM) == 1  # a name OPSIN parsed never leaves the machine


def test_no_systematic_name_means_no_jvm_start(chain, opsin):
    chain.resolve_many([span("caffeine"), span("BRCA1", "gene")], timeout_s=2.0)
    assert opsin.batches == []


def test_element_words_and_common_names_never_reach_opsin(chain, backend, opsin):
    words = ["lead", "tin", "iron", "gold", "zinc", "water", "glucose", "sodium bicarbonate"]
    chain.resolve_many([span(w) for w in words], timeout_s=2.0)
    assert opsin.batches == []
    assert backend.count(PUBCHEM) == len(words)


def test_opsin_only_sees_chemicals(chain, opsin):
    chain.resolve_many([span("3-methylpentane", "other"), span("p53-3", "protein")], timeout_s=2.0)
    assert opsin.batches == []


def test_name_opsin_cannot_parse_falls_back_to_pubchem(chain, backend, opsin):
    backend.compounds["2-methylpropan-1-ol"] = (6560, "C4H10O", "2-methylpropan-1-ol")
    result = chain.resolve_many([span("2-methylpropan-1-ol")], timeout_s=2.0)
    assert opsin.batches == [["2-methylpropan-1-ol"]]
    assert (result["2-methylpropan-1-ol"].source, result["2-methylpropan-1-ol"].kind) == (
        "pubchem",
        "chemical",
    )
    assert backend.count(PUBCHEM) == 1


def test_name_nobody_knows_is_not_found(chain, backend):
    result = chain.resolve_many([span("2-methyl-nonexistan-9-ol")], timeout_s=2.0)
    assert result["2-methyl-nonexistan-9-ol"].status == "not_found"
    assert result["2-methyl-nonexistan-9-ol"].kind == "chemical"


@pytest.mark.parametrize("answer", ["nothing", "timeout", "error"])
def test_opsin_without_a_parse_falls_back_to_pubchem(chain, backend, opsin, monkeypatch, answer):
    def reply(names, *, timeout_s=20.0):
        if answer == "nothing":
            return {}
        return {n: Resolution(n, "iupac", None, {}, "opsin", answer) for n in names}

    monkeypatch.setattr(opsin, "resolve_batch", reply)
    result = chain.resolve_many([span("propanone")], timeout_s=2.0)
    assert result["propanone"].status == "not_found"
    assert backend.count(PUBCHEM) == 1


def test_zero_budget_does_not_start_the_jvm(chain, opsin):
    chain.resolve_many([span("2-methylpropan-1-ol")], timeout_s=0)
    assert opsin.batches == []


def test_skip_wins_over_a_cached_answer(build, backend):
    build().resolve_many([span("caffeine")], timeout_s=2.0)
    assert build(skip=lambda text: True).resolve_many([span("caffeine")], timeout_s=2.0) == {}


def test_a_crashing_opsin_falls_back_to_pubchem(chain, backend, opsin, caplog):
    opsin.error = RuntimeError("jvm exploded")
    backend.compounds["propanone"] = (180, "C3H6O", "propan-2-one")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = chain.resolve_many([span("propanone")], timeout_s=2.0)
    assert result["propanone"].status == "ok"
    assert "jvm exploded" in caplog.text


def test_opsin_answers_are_cached(chain, backend, opsin):
    opsin.known = {"2-methylpropan-1-ol": "CC(C)CO"}
    chain.resolve_many([span("2-methylpropan-1-ol")], timeout_s=2.0)
    again = chain.resolve_many([span("2-methylpropan-1-ol")], timeout_s=2.0)
    assert len(opsin.batches) == 1
    assert (again["2-methylpropan-1-ol"].source, again["2-methylpropan-1-ol"].kind) == (
        "cache",
        "iupac",
    )


def test_opsin_is_given_what_is_left_of_the_budget(chain, opsin):
    chain.resolve_many([span("2-methylpropan-1-ol")], timeout_s=1.5)
    assert 0 < opsin.timeouts[0] <= 1.5


def test_pubchem_does_not_wait_for_a_slow_opsin(chain, backend, opsin, monkeypatch):
    release = threading.Event()
    real = opsin.resolve_batch

    def slow(names, *, timeout_s=20.0):
        release.wait(5)
        return real(names, timeout_s=timeout_s)

    monkeypatch.setattr(opsin, "resolve_batch", slow)
    start = time.monotonic()
    try:
        result = chain.resolve_many([span("2-methylpropan-1-ol"), span("caffeine")], timeout_s=0.5)
    finally:
        release.set()
    assert result["caffeine"] == CAFFEINE
    assert result["2-methylpropan-1-ol"].status == "timeout"
    assert result["2-methylpropan-1-ol"].source == "opsin"
    assert time.monotonic() - start < 2.0


def test_offline_makes_no_request_and_says_so(build, backend):
    result = build(offline=True).resolve_many(
        [span("caffeine"), span("BRCA1", "gene"), span("insulin", "protein")], timeout_s=2.0
    )
    assert backend.count() == 0
    assert {k: v.status for k, v in result.items()} == {
        "caffeine": "offline",
        "BRCA1": "offline",
        "insulin": "offline",
    }
    assert result["caffeine"].kind == "chemical"
    assert result["BRCA1"].kind == "gene"


def test_offline_results_are_not_cached(build, backend, cache):
    build(offline=True).resolve_many([span("caffeine")], timeout_s=2.0)
    assert build().resolve_many([span("caffeine")], timeout_s=2.0)["caffeine"] == CAFFEINE


def test_offline_still_serves_the_cache(build, backend, cache):
    build().resolve_many([span("caffeine")], timeout_s=2.0)
    backend.requests.clear()
    result = build(offline=True).resolve_many([span("caffeine")], timeout_s=2.0)
    assert result["caffeine"].source == "cache"
    assert backend.count() == 0


def test_offline_still_runs_opsin_because_it_is_local(build, backend, opsin):
    opsin.known = {"2-methylpropan-1-ol": "CC(C)CO"}
    result = build(offline=True).resolve_many(
        [span("2-methylpropan-1-ol"), span("3-methylpentane")], timeout_s=2.0
    )
    assert result["2-methylpropan-1-ol"].status == "ok"
    assert result["3-methylpentane"].status == "offline"
    assert backend.count() == 0


def test_budget_cuts_the_slow_lookup_and_keeps_the_fast_one(build, backend, cache, caplog):
    gate = backend.gates["slowpoke"] = threading.Event()
    start = time.monotonic()
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER):
            result = build().resolve_many([span("caffeine"), span("slowpoke")], timeout_s=0.5)
        elapsed = time.monotonic() - start
    finally:
        gate.set()
    assert "1 of 2 lookups timed out" in caplog.text
    assert result["caffeine"] == CAFFEINE
    assert (result["slowpoke"].status, result["slowpoke"].source) == ("timeout", "pubchem")
    assert elapsed < 2.0
    time.sleep(0.2)  # the late answer must not reach the cache
    assert cache.get("chemical:slowpoke") is None


def test_default_budget_comes_from_the_settings(build, backend):
    gate = backend.gates["slowpoke"] = threading.Event()
    start = time.monotonic()
    try:
        result = build(budget=0.3).resolve_many([span("slowpoke")])
        elapsed = time.monotonic() - start
    finally:
        gate.set()
    assert result["slowpoke"].status == "timeout"
    assert elapsed < 2.0


def test_zero_budget_sends_nothing_but_still_serves_the_cache(build, backend):
    build().resolve_many([span("caffeine")], timeout_s=2.0)
    backend.requests.clear()
    result = build().resolve_many(
        [span("caffeine"), span("aspirin"), span("BRCA1", "gene")], timeout_s=0
    )
    assert result["caffeine"].source == "cache"
    assert (result["aspirin"].status, result["BRCA1"].status) == ("timeout", "timeout")
    assert backend.count() == 0


def test_lookups_run_concurrently(build, backend):
    backend.delay_s = 0.5
    names = ["caffeine", "glucose", "aspirin", "BRCA1"]
    spans = [span(n, "gene" if n == "BRCA1" else "chemical") for n in names]
    start = time.monotonic()
    result = build().resolve_many(spans, timeout_s=5.0)
    assert time.monotonic() - start < 1.5  # one after another would take 2 s
    assert {r.status for r in result.values()} == {"ok"}


def test_calls_from_several_threads_share_one_chain_safely(chain, backend):
    results: list[dict[str, Resolution]] = []
    errors: list[Exception] = []

    def work(name: str) -> None:
        try:
            results.append(chain.resolve_many([span(name)], timeout_s=5.0))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=work, args=(n,)) for n in ["caffeine", "glucose", "aspirin"] * 3
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(results) == 9
    assert all(r.status == "ok" for batch in results for r in batch.values())


def test_every_request_is_https_and_carries_only_the_entity(chain, backend):
    spans = [span("N/A"), span("acetic acid (glacial)"), span("BRCA1", "gene"), span("caffeine")]
    chain.resolve_many(spans, timeout_s=2.0)
    assert backend.count() == 4
    for request in backend.requests:
        assert request.url.scheme == "https"
        assert request.content == b""
        assert "cookie" not in request.headers
    sent = {
        unquote(r.url.raw_path.decode().split("/")[5])
        for r in backend.requests
        if r.url.host == PUBCHEM
    }
    assert sent == {"N/A", "acetic acid (glacial)", "caffeine"}
    uniprot = next(r for r in backend.requests if r.url.host == UNIPROT)
    assert uniprot.url.params["query"] == "BRCA1"
    assert uniprot.url.params["size"] == "1"


def test_names_with_slash_space_and_parentheses_stay_one_path_segment(chain, backend):
    chain.resolve_many([span("N/A"), span("acetic acid (glacial)")], timeout_s=2.0)
    paths = sorted(r.url.raw_path.decode().split("/property")[0] for r in backend.requests)
    assert paths == [
        "/rest/pug/compound/name/N%2FA",
        "/rest/pug/compound/name/acetic%20acid%20%28glacial%29",
    ]


class HungLookup:
    """Stands in for PubChemResolver and UniProtResolver: each lookup blocks until `release`."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started: list[str] = []

    def resolve(self, name: str, **kwargs) -> Resolution:
        self.started.append(name)
        self.release.wait(10)
        return Resolution(name, "chemical", None, {}, "pubchem", "not_found")


class RecordingLookup:
    """Answers at once and records the keyword arguments of every lookup."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def resolve(self, name: str, **kwargs) -> Resolution:
        self.calls.append((name, kwargs))
        return Resolution(name, "chemical", None, {}, "pubchem", "not_found")


def hung_chain(tmp_path: Path, cache, opsin) -> tuple[ChainResolver, HungLookup]:
    hung = HungLookup()
    settings = Settings(tmp_path, tmp_path, tmp_path, tmp_path)
    chain = ChainResolver(cache=cache, opsin=opsin, pubchem=hung, uniprot=hung, settings=settings)
    return chain, hung


def lookup_threads() -> set[threading.Thread]:
    return {t for t in threading.enumerate() if t.name.startswith("cloudyreader-lookup")}


def test_a_hung_lookup_cannot_hold_resolve_many_past_the_budget(tmp_path, cache, opsin):
    chain, hung = hung_chain(tmp_path, cache, opsin)
    start = time.monotonic()
    try:
        result = chain.resolve_many([span("caffeine")], timeout_s=0.3)
        elapsed = time.monotonic() - start
        workers = lookup_threads()
    finally:
        hung.release.set()
    assert result["caffeine"].status == "timeout"
    assert elapsed < 1.5
    assert workers
    assert all(t.daemon for t in workers)  # a daemon never keeps the process alive


def test_workers_leave_when_the_call_ends(chain, backend):
    before = lookup_threads()
    chain.resolve_many([span("caffeine"), span("aspirin")], timeout_s=2.0)
    give_up = time.monotonic() + 2.0
    while lookup_threads() - before and time.monotonic() < give_up:
        time.sleep(0.01)
    assert lookup_threads() - before == set()


def test_lookups_that_never_started_are_cancelled_when_the_budget_ends(
    tmp_path, cache, opsin, monkeypatch
):
    monkeypatch.setattr(chain_module, "_MAX_WORKERS", 1)
    chain, hung = hung_chain(tmp_path, cache, opsin)
    try:
        result = chain.resolve_many([span("alpha"), span("beta"), span("gamma")], timeout_s=0.3)
    finally:
        hung.release.set()
    time.sleep(0.2)  # the freed worker must not pick up what was cancelled
    assert hung.started == ["alpha"]
    assert {r.status for r in result.values()} == {"timeout"}


def test_the_deadline_reaches_every_lookup(tmp_path, cache, opsin):
    lookup = RecordingLookup()
    settings = Settings(tmp_path, tmp_path, tmp_path, tmp_path)
    chain = ChainResolver(
        cache=cache, opsin=opsin, pubchem=lookup, uniprot=lookup, settings=settings
    )
    before = time.monotonic()
    chain.resolve_many([span("caffeine"), span("BRCA1", "gene")], timeout_s=5.0)
    after = time.monotonic()
    deadlines = [kwargs["deadline"] for _, kwargs in lookup.calls]
    assert len(deadlines) == 2
    assert all(before + 5.0 <= deadline <= after + 5.0 for deadline in deadlines)


def test_close_cancels_the_tasks_that_have_not_started():
    pool = chain_module._DaemonPool(1)
    started, gate, ran = threading.Event(), threading.Event(), []

    def block() -> bool:
        started.set()
        return gate.wait(10)

    running = pool.submit(block)
    assert started.wait(5)  # `close` must find the first task running, not waiting
    queued = pool.submit(ran.append, "never")
    pool.close()
    assert queued.cancelled()
    gate.set()
    assert running.result(timeout=5) is True
    assert ran == []


def test_a_worker_skips_a_task_cancelled_while_it_waited():
    pool = chain_module._DaemonPool(1)
    gate, ran = threading.Event(), []
    first = pool.submit(gate.wait, 10)
    queued = pool.submit(ran.append, "cancelled")
    last = pool.submit(ran.append, "last")
    assert queued.cancel()  # the only worker is busy with `first`, so `queued` is still waiting
    gate.set()
    last.result(timeout=5)
    pool.close()
    assert (first.result(), ran) == (True, ["last"])


def test_opsin_is_not_started_once_the_budget_is_spent(chain, opsin):
    # A worker can reach the OPSIN batch after the deadline; it must not start a JVM then.
    job = chain_module._Job("chemical", "propanone", ("propanone",))
    assert chain._run_opsin([job], deadline=time.monotonic() - 1.0) == {}
    assert opsin.batches == []


def test_a_bug_in_a_worker_surfaces_instead_of_timing_out(chain, monkeypatch):
    def boom(*args):
        raise RuntimeError("bug in a worker")

    monkeypatch.setattr(ChainResolver, "_resolve", boom)
    with pytest.raises(RuntimeError, match="bug in a worker"):
        chain.resolve_many([span("caffeine")], timeout_s=2.0)


# A child process that leaves a lookup hung for good and then reaches the end of its script.
HANG_AT_EXIT = """
import json, sys, threading, time
from pathlib import Path

from cloudyreader.config import Settings
from cloudyreader.models import EntitySpan
from cloudyreader.resolvers.cache import ResolutionCache
from cloudyreader.resolvers.chain import ChainResolver


class Hung:
    def resolve(self, name, **kwargs):
        threading.Event().wait()  # never set: this lookup hangs for good


class NoOpsin:
    def resolve_batch(self, names, *, timeout_s=20.0):
        return {}


tmp = Path(sys.argv[1])
chain = ChainResolver(
    cache=ResolutionCache(tmp / "cache.sqlite3"),
    opsin=NoOpsin(),
    pubchem=Hung(),
    uniprot=Hung(),
    settings=Settings(tmp, tmp, tmp, tmp),
)
spans = [EntitySpan(0, 8, "caffeine", "chemical", "ner")]
status = chain.resolve_many(spans, timeout_s=0.2)["caffeine"].status
print(json.dumps({"status": status, "returned_at": time.time()}), flush=True)
"""


def test_a_hung_lookup_cannot_delay_interpreter_exit(tmp_path):
    # A hung worker used to keep the process alive after the window closed. `timeout` turns
    # that hang into a failure instead of a stuck test run.
    proc = subprocess.run(
        [sys.executable, "-c", HANG_AT_EXIT, str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    ended_at = time.time()
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["status"] == "timeout"
    assert ended_at - report["returned_at"] < 1.0


@pytest.mark.java
@pytest.mark.slow
def test_real_opsin_answers_a_systematic_name_without_a_request(tmp_path, backend, cache):
    from cloudyreader.resolvers.opsin import OpsinResolver

    http = HttpClient(timeout_s=4.0, max_rps=1000.0)
    chain = ChainResolver(
        cache=cache,
        opsin=OpsinResolver(),
        pubchem=PubChemResolver(http),
        uniprot=UniProtResolver(http),
        settings=Settings(tmp_path, tmp_path, tmp_path, tmp_path),
    )
    name = "2-methylpropan-1-ol"
    result = chain.resolve_many([span(name)], timeout_s=20.0)[name]
    assert (result.kind, result.status, result.source) == ("iupac", "ok", "opsin")
    assert backend.count() == 0
