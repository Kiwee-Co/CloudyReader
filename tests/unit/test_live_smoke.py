"""scripts/live_smoke.py: probe list, output lines, raw dumps, and the verdict, on canned servers.

No live calls: respx answers both hosts and the OPSIN jar is faked.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
import sys
from pathlib import Path

import httpx
import pytest
import respx

from cloudyreader.config import load_settings
from cloudyreader.models import Resolution
from cloudyreader.resolvers.opsin import OpsinResolver
from cloudyreader.resolvers.pubchem import PubChemResolver

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_smoke.py"
PUBCHEM_HOST = "pubchem.ncbi.nlm.nih.gov"
UNIPROT_HOST = "rest.uniprot.org"

PUBCHEM_ROWS = {
    "aspirin": {"CID": 2244, "MolecularFormula": "C9H8O4", "IUPACName": "2-acetyloxybenzoic acid"},
    "acetone": {"CID": 180, "MolecularFormula": "C3H6O", "IUPACName": "propan-2-one"},
    "sodium chloride": {"CID": 5234, "MolecularFormula": "ClNa", "IUPACName": "sodium chloride"},
}
PUBCHEM_NOT_FOUND = {"Fault": {"Code": "PUGREST.NotFound", "Message": "No CID found"}}
UNIPROT_ENTRIES = {
    "hemoglobin": ("P69905", "Hemoglobin subunit alpha", "HBA1"),
    "insulin": ("P01308", "Insulin", "INS"),
    "BRCA1": ("P38398", "Breast cancer type 1 susceptibility protein", "BRCA1"),
    "p53": ("P04637", "Cellular tumor antigen p53", "TP53"),
    "amylase": ("P04745", "Alpha-amylase 1", "AMY1A"),
}
# Every response shape the resolvers read, with the number of probes that must show it.
SHAPES = [
    ("pubchem", "PropertyTable.Properties[0].CID", "3/3"),
    ("pubchem", "PropertyTable.Properties[0].IUPACName", "3/3"),
    ("pubchem", "PropertyTable.Properties[0].MolecularFormula", "3/3"),
    ("uniprot", "results[0].primaryAccession", "5/5"),
    ("uniprot", "results[0].proteinDescription.recommendedName.fullName.value", "5/5"),
    ("uniprot", "results[0].genes[0].geneName.value", "5/5"),
]


def uniprot_entry(accession: str, protein: str, gene: str | None) -> dict:
    entry = {
        "entryType": "UniProtKB reviewed (Swiss-Prot)",
        "primaryAccession": accession,
        "proteinDescription": {"recommendedName": {"fullName": {"value": protein}}},
    }
    if gene:
        entry["genes"] = [{"geneName": {"value": gene}}]
    return entry


def pubchem_word(request: httpx.Request) -> str:
    return request.url.path.split("/name/", 1)[1].rsplit("/property/", 1)[0]


def pubchem_answer(request: httpx.Request) -> httpx.Response:
    row = PUBCHEM_ROWS.get(pubchem_word(request))
    if row is None:
        return httpx.Response(404, json=PUBCHEM_NOT_FOUND)
    return httpx.Response(200, json={"PropertyTable": {"Properties": [row]}})


def uniprot_answer(request: httpx.Request) -> httpx.Response:
    entry = UNIPROT_ENTRIES.get(request.url.params["query"])
    return httpx.Response(200, json={"results": [uniprot_entry(*entry)] if entry else []})


def offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("blocked", request=request)


class Server:
    """Both hosts behind one object: a test bends an answer by replacing a handler."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.requests: list[httpx.Request] = []
        self.pubchem = pubchem_answer
        self.uniprot = uniprot_answer
        router.route(host=PUBCHEM_HOST).mock(side_effect=lambda r: self._serve(self.pubchem, r))
        router.route(host=UNIPROT_HOST).mock(side_effect=lambda r: self._serve(self.uniprot, r))

    def _serve(self, handler, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return handler(request)


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("live_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "live_smoke", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server():
    with respx.mock(assert_all_called=False) as router:
        yield Server(router)


@pytest.fixture(autouse=True)
def fake_opsin(monkeypatch: pytest.MonkeyPatch):
    def resolve_batch(self, names, *, timeout_s=20.0):
        smiles = {"smiles": "CC(CO)C"}
        return {n: Resolution(n, "iupac", "CC(CO)C", smiles, "opsin", "ok") for n in names}

    monkeypatch.setattr(OpsinResolver, "resolve_batch", resolve_batch)


@pytest.fixture
def run(smoke, server, capsys):
    def go(**settings) -> tuple[int, str]:
        # A high rate keeps the real throttle from sleeping between the canned answers.
        merged = {"max_rps": 1000.0} | settings
        code = smoke.main(settings=dataclasses.replace(load_settings({}), **merged))
        return code, capsys.readouterr().out

    return go


def probe_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(("pass", "FAIL"))]


def verdict(out: str, label: str) -> str:
    """The verdict line that mentions `label`, whitespace squeezed."""
    for line in out.splitlines():
        if label in line and line.split()[0] in {"HELD", "PARTIAL", "BROKEN", "NO"}:
            return " ".join(line.split())
    raise AssertionError(f"no verdict line for {label!r} in:\n{out}")


def squeezed(out: str) -> str:
    return re.sub(r"\s", "", out)


def test_probe_list_covers_the_brief_with_two_nonsense_words(smoke):
    wanted = {
        ("pubchem", "aspirin"),
        ("pubchem", "acetone"),
        ("pubchem", "sodium chloride"),
        ("opsin", "2-methylpropan-1-ol"),
        ("uniprot", "hemoglobin"),
        ("uniprot", "insulin"),
        ("uniprot", "BRCA1"),
        ("uniprot", "p53"),
        ("uniprot", "amylase"),
    }
    probes = smoke.PROBES
    assert {(p.service, p.query) for p in probes if p.expect == "ok"} == wanted
    assert sorted(p.service for p in probes if p.expect == "not_found") == ["pubchem", "uniprot"]


def test_one_line_per_probe_with_query_kind_status_canonical_ids_and_ms(run):
    code, out = run()
    lines = probe_lines(out)
    assert code == 0
    assert len(lines) == 11
    assert re.fullmatch(
        r"pass\s+pubchem\s+'aspirin'\s+kind=chemical status=ok canonical='2-acetyloxybenzoic acid' "
        r"ids=\{'cid': '2244', 'formula': 'C9H8O4'\} \d+ ms",
        lines[0],
    )
    assert re.fullmatch(
        r"pass\s+opsin\s+'2-methylpropan-1-ol'\s+kind=iupac status=ok canonical='CC\(CO\)C' "
        r"ids=\{'smiles': 'CC\(CO\)C'\} \d+ ms",
        lines[3],
    )


def test_gene_probe_asks_for_a_gene_and_unknown_words_are_not_found(run):
    _, out = run()
    assert re.search(r"pass\s+uniprot\s+'BRCA1'\s+kind=gene status=ok canonical='BRCA1' ", out)
    assert re.search(
        r"pass\s+pubchem\s+'\w+'\s+kind=chemical status=not_found canonical=None ", out
    )
    assert re.search(r"pass\s+uniprot\s+'\w+'\s+kind=protein status=not_found canonical=None ", out)


def test_a_healthy_run_holds_every_check(run):
    code, out = run()
    assert code == 0
    assert "FAIL" not in out
    for state in ("PARTIAL", "BROKEN", "NO DATA"):
        assert state not in out
    assert "RESULT: every check held" in out


@pytest.mark.parametrize(("scope", "path", "count"), SHAPES)
def test_expected_response_shapes_are_checked_one_by_one(run, scope, path, count):
    _, out = run()
    assert verdict(out, path) == f"HELD {scope} {path} {count}"


def test_unknown_word_behaviour_of_both_services_is_checked(run):
    _, out = run()
    assert verdict(out, "HTTP 404") == "HELD pubchem unknown name answers HTTP 404 1/1"
    assert verdict(out, "results []") == (
        "HELD uniprot unknown query answers HTTP 200 and results [] 1/1"
    )


def test_not_found_probes_dump_the_raw_start_of_the_response(run):
    _, out = run()
    assert re.search(r"GET https://pubchem\.\S+/xq\w+/property/\S+ -> HTTP 404", out)
    assert "PUGREST.NotFound" in out
    assert re.search(r"GET https://rest\.uniprot\.org/uniprotkb/search\?\S+ -> HTTP 200", out)
    assert '{"results":[]}' in squeezed(out)


def test_raw_dump_stops_after_300_characters(run, server):
    server.pubchem = lambda request: httpx.Response(500, text="x" * 299 + "AB" + "y" * 700)
    _, out = run()
    assert "x" * 299 + "A" in out
    assert "x" * 299 + "AB" not in out
    assert "HTTP 500" in out


def test_shape_mismatch_is_broken_and_the_raw_body_shows_why(run, server):
    server.uniprot = lambda request: httpx.Response(200, json={"data": [{"id": "P1"}]})
    _, out = run()
    assert re.search(r"FAIL\s+uniprot\s+'insulin'\s+kind=protein status=error ", out)
    assert '{"data":[{"id":"P1"}]}' in squeezed(out)
    words = "hemoglobin, insulin, BRCA1, p53, amylase"
    assert verdict(out, "primaryAccession") == (
        f"BROKEN uniprot results[0].primaryAccession 0/5 fails: {words}"
    )
    assert "did not hold" in out


def test_partial_shape_names_the_probes_that_lack_it(run, server):
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == "insulin":
            return httpx.Response(200, json={"results": [uniprot_entry("P01308", "Insulin", None)]})
        return uniprot_answer(request)

    server.uniprot = answer
    _, out = run()
    assert verdict(out, "geneName.value") == (
        "PARTIAL uniprot results[0].genes[0].geneName.value 4/5 fails: insulin"
    )
    assert re.search(r"pass\s+uniprot\s+'insulin'\s+kind=protein status=ok ", out)


def test_html_body_with_status_200_is_an_error_not_a_crash(run, server):
    server.pubchem = lambda request: httpx.Response(200, text="<html>maintenance</html>")
    code, out = run()
    assert code == 0
    assert re.search(r"FAIL\s+pubchem\s+'aspirin'\s+kind=chemical status=error ", out)
    assert "<html>maintenance</html>" in out
    assert verdict(out, "IUPACName").startswith("BROKEN pubchem")


def test_offline_run_reports_no_data_and_still_exits_zero(run, server):
    server.pubchem = server.uniprot = offline
    code, out = run()
    assert code == 0
    assert re.search(r"FAIL\s+pubchem\s+'aspirin'\s+kind=chemical status=offline ", out)
    assert "(no HTTP response recorded)" in out
    assert verdict(out, "IUPACName").startswith("NO DATA pubchem")
    assert verdict(out, "primaryAccession").startswith("NO DATA uniprot")
    assert verdict(out, "lookup_budget_s").startswith("NO DATA latency")  # nothing to time
    assert "RESULT: no HTTP response at all" in out
    assert re.search(r"pass\s+opsin\s+'2-methylpropan-1-ol'", out)


def test_crashing_resolver_is_reported_and_the_run_goes_on(run, monkeypatch):
    def boom(self, name, **kwargs):
        raise RuntimeError("boom\nsecond line")

    monkeypatch.setattr(PubChemResolver, "resolve", boom)
    code, out = run()
    assert code == 0
    assert re.search(r"FAIL\s+pubchem\s+'aspirin'\s+CRASH RuntimeError: boom second line ", out)
    assert re.search(r"pass\s+uniprot\s+'insulin'", out)
    assert len(probe_lines(out)) == 11


def test_latency_is_checked_against_the_lookup_budget(run):
    _, out = run()
    assert re.fullmatch(
        r"HELD latency each lookup within lookup_budget_s \(2500 ms\); "
        r"median \d+ ms, max \d+ ms 10/10",
        verdict(out, "lookup_budget_s"),
    )
    _, slow = run(lookup_budget_s=1e-9)
    assert verdict(slow, "lookup_budget_s").startswith("BROKEN latency")


def test_only_probe_words_leave_the_machine_over_https(run, server, smoke):
    run()
    words = {p.query for p in smoke.PROBES}
    assert len(server.requests) == 10
    for request in server.requests:
        assert request.url.scheme == "https"
        assert request.method == "GET"
        assert not request.content
        assert not {"authorization", "cookie"} & set(request.headers)
        pubchem = request.url.host == PUBCHEM_HOST
        assert (pubchem_word(request) if pubchem else request.url.params["query"]) in words


def test_contacted_hosts_are_listed_in_the_verdict(run):
    _, out = run()
    assert f"contacted: {PUBCHEM_HOST} x4, {UNIPROT_HOST} x6; non-HTTPS requests: 0" in out


def test_only_the_two_not_found_probes_dump_in_a_healthy_run(run):
    _, out = run()
    assert out.count("GET https://pubchem.") == 1
    assert out.count("GET https://rest.uniprot.org/") == 1


def test_empty_body_is_dumped_as_empty(run, server):
    server.pubchem = lambda request: httpx.Response(500, content=b"")
    _, out = run()
    assert "| (empty body)" in out


def test_control_characters_in_a_body_cannot_reach_the_terminal(run, server):
    server.pubchem = lambda request: httpx.Response(500, content=b"\x1b[31mRED\x00\x07 text")
    _, out = run()
    assert "RED" in out
    assert not {"\x1b", "\x00", "\x07"} & set(out)


def test_default_settings_come_from_defaults_not_from_the_environment(smoke, server, monkeypatch):
    # CLOUDYREADER_OFFLINE must not be able to turn the live test into an offline one.
    asked = []
    fast = dataclasses.replace(load_settings({}), max_rps=1000.0)

    def load(env=None):
        asked.append(env)
        return fast

    monkeypatch.setattr(smoke, "load_settings", load)
    assert smoke.main() == 0
    assert asked == [{}]


def test_contacted_line_counts_requests_that_are_not_https(smoke):
    exchanges = (
        smoke.Exchange("https://pubchem.ncbi.nlm.nih.gov/a", 200, "{}"),
        smoke.Exchange("http://pubchem.ncbi.nlm.nih.gov/b", 200, "{}"),
    )
    result = smoke.Result(smoke.PROBES[0], None, "", 1.0, exchanges)
    line = smoke.contacted_line([result])
    assert line == "contacted: pubchem.ncbi.nlm.nih.gov x2; non-HTTPS requests: 1"


def test_unknown_name_answered_with_anything_but_404_breaks_that_check(run, server):
    def answer(request: httpx.Request) -> httpx.Response:
        if pubchem_word(request) in PUBCHEM_ROWS:
            return pubchem_answer(request)
        return httpx.Response(200, json={"PropertyTable": {"Properties": []}})

    server.pubchem = answer
    _, out = run()
    assert verdict(out, "HTTP 404").startswith("BROKEN pubchem unknown name answers HTTP 404 0/1")
    assert re.search(r"FAIL\s+pubchem\s+'xqzvwplkjt'\s+kind=chemical status=error ", out)


def test_unknown_query_that_finds_a_hit_breaks_that_check(run, server):
    hit = {"results": [uniprot_entry("P12345", "Some protein", "SOME1")]}
    server.uniprot = lambda request: httpx.Response(200, json=hit)
    _, out = run()
    expected = "BROKEN uniprot unknown query answers HTTP 200 and results [] 0/1"
    assert verdict(out, "results []").startswith(expected)
    assert re.search(r"FAIL\s+uniprot\s+'qzjxkvwpmt'\s+kind=protein status=ok ", out)


def test_an_empty_string_is_not_a_value(run, server):
    def answer(request: httpx.Request) -> httpx.Response:
        if pubchem_word(request) != "acetone":
            return pubchem_answer(request)
        row = PUBCHEM_ROWS["acetone"] | {"IUPACName": ""}
        return httpx.Response(200, json={"PropertyTable": {"Properties": [row]}})

    server.pubchem = answer
    _, out = run()
    assert verdict(out, "IUPACName") == (
        "PARTIAL pubchem PropertyTable.Properties[0].IUPACName 2/3 fails: acetone"
    )
    assert re.search(r"pass\s+pubchem\s+'acetone'\s+kind=chemical status=ok canonical=None ", out)


def test_http_client_is_built_from_the_settings_budgets(smoke, server, monkeypatch):
    # PubChem bans clients above 5 requests per second: the script must follow Settings.max_rps.
    built = []
    real = smoke.HttpClient

    def spy(**kwargs):
        built.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(smoke, "HttpClient", spy)
    settings = dataclasses.replace(load_settings({}), max_rps=1000.0, http_timeout_s=1.5)
    assert smoke.main(settings=settings) == 0
    assert (built[0]["max_rps"], built[0]["timeout_s"]) == (1000.0, 1.5)


def test_timed_out_lookups_break_the_latency_check(run, server):
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    server.pubchem = server.uniprot = slow
    code, out = run()
    assert code == 0
    assert re.search(r"FAIL\s+pubchem\s+'aspirin'\s+kind=chemical status=timeout ", out)
    assert verdict(out, "lookup_budget_s").startswith("BROKEN latency")
