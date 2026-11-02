"""PubChemResolver: name -> compound through PUG REST, parsed defensively."""

from __future__ import annotations

import logging
import time

import httpx
import pytest
import respx

from cloudyreader.models import Resolution
from cloudyreader.resolvers.http import MAX_QUERY_CHARS, HttpClient
from cloudyreader.resolvers.pubchem import PubChemResolver

HOST = "pubchem.ncbi.nlm.nih.gov"
PATH = "/rest/pug/compound/name/{}/property/IUPACName,MolecularFormula/JSON"
ASPIRIN = {
    "PropertyTable": {
        "Properties": [
            {"CID": 2244, "MolecularFormula": "C9H8O4", "IUPACName": "2-acetyloxybenzoic acid"}
        ]
    }
}
NOT_FOUND = {"Fault": {"Code": "PUGREST.NotFound", "Message": "No CID found"}}
LOGGER = "cloudyreader.resolvers.pubchem"


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def pubchem(router) -> PubChemResolver:
    return PubChemResolver(HttpClient(timeout_s=4.0, max_rps=1000.0, sleep=lambda _: None))


@pytest.fixture
def route(router):
    return router.route(host=HOST).respond(200, json=ASPIRIN)


def failed(query: str, status: str) -> Resolution:
    return Resolution(query, "chemical", None, {}, "pubchem", status)


def test_hit_carries_cid_formula_and_the_canonical_name(pubchem, route):
    assert pubchem.resolve("aspirin") == Resolution(
        "aspirin",
        "chemical",
        "2-acetyloxybenzoic acid",
        {"cid": "2244", "formula": "C9H8O4"},
        "pubchem",
        "ok",
    )


def test_asks_the_documented_endpoint_over_https(pubchem, route):
    pubchem.resolve("aspirin")
    request = route.calls.last.request
    assert request.url.scheme == "https"
    assert request.url.host == HOST
    assert request.url.raw_path == PATH.format("aspirin").encode()
    assert request.method == "GET"


@pytest.mark.parametrize(
    ("name", "segment"),
    [
        ("1,2-dichloroethane", "1%2C2-dichloroethane"),
        ("N/A", "N%2FA"),
        ("acetic acid", "acetic%20acid"),
        ("(E)-but-2-ene", "%28E%29-but-2-ene"),
        ("2-methyl-1-(propan-2-yl)benzene", "2-methyl-1-%28propan-2-yl%29benzene"),
        ("a?b#c", "a%3Fb%23c"),
    ],
)
def test_name_stays_one_encoded_path_segment(pubchem, route, name, segment):
    pubchem.resolve(name)
    assert route.calls.last.request.url.raw_path == PATH.format(segment).encode()


def test_whitespace_in_the_name_is_normalized_before_it_is_sent(pubchem, route):
    pubchem.resolve("  acetic \n acid ")
    assert route.calls.last.request.url.raw_path == PATH.format("acetic%20acid").encode()


def test_sends_nothing_but_the_name(pubchem, route):
    pubchem.resolve("aspirin")
    request = route.calls.last.request
    assert request.content == b""
    assert request.url.query == b""
    assert "cookie" not in request.headers
    assert "referer" not in request.headers


def test_404_is_not_found(pubchem, router):
    router.route(host=HOST).respond(404, json=NOT_FOUND)
    assert pubchem.resolve("zzzzz") == failed("zzzzz", "not_found")


def test_first_property_wins_when_a_name_matches_several_compounds(pubchem, router):
    rows = [{"CID": 5793, "IUPACName": "glucose"}, {"CID": 107526, "IUPACName": "other"}]
    router.route(host=HOST).respond(200, json={"PropertyTable": {"Properties": rows}})
    result = pubchem.resolve("glucose")
    assert result.ids == {"cid": "5793"}
    assert result.canonical == "glucose"


def test_compound_without_an_iupac_name_is_still_a_hit(pubchem, router):
    body = {"PropertyTable": {"Properties": [{"CID": "962", "MolecularFormula": "H2O"}]}}
    router.route(host=HOST).respond(200, json=body)
    assert pubchem.resolve("water") == Resolution(
        "water", "chemical", None, {"cid": "962", "formula": "H2O"}, "pubchem", "ok"
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "oops",
        {"PropertyTable": {}},
        {"PropertyTable": {"Properties": []}},
        {"PropertyTable": {"Properties": [{}]}},
        {"PropertyTable": {"Properties": [{"IUPACName": "x"}]}},
        {"PropertyTable": {"Properties": [{"CID": None}]}},
        {"PropertyTable": {"Properties": ["not a row"]}},
        {"PropertyTable": {"Properties": {"CID": 1}}},
    ],
)
def test_unexpected_shape_is_an_error_not_a_miss(pubchem, router, caplog, body):
    # A miss is cached for a day; a changed API must not poison the cache with false misses.
    router.route(host=HOST).respond(200, json=body)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert pubchem.resolve("aspirin") == failed("aspirin", "error")
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_shape_warning_names_keys_and_leaks_no_values(pubchem, router, caplog):
    router.route(host=HOST).respond(200, json={"Surprise": "secret-value"})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        pubchem.resolve("aspirin")
    assert "Surprise" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.parametrize(
    ("effect", "status"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "offline"),
        (httpx.RemoteProtocolError("bad"), "error"),
    ],
)
def test_transport_failures_become_statuses(pubchem, router, effect, status):
    router.route(host=HOST).mock(side_effect=effect)
    assert pubchem.resolve("aspirin") == failed("aspirin", status)


@pytest.mark.parametrize("code", [429, 503])
def test_busy_server_is_an_error_after_two_retries(pubchem, router, code):
    busy = router.route(host=HOST).respond(code)
    assert pubchem.resolve("aspirin") == failed("aspirin", "error")
    assert busy.call_count == 3


def test_server_error_is_an_error(pubchem, router):
    router.route(host=HOST).respond(500, json={"Fault": {"Code": "PUGREST.ServerError"}})
    assert pubchem.resolve("aspirin") == failed("aspirin", "error")


@pytest.mark.parametrize("name", ["", "   ", "\n", "a" * (MAX_QUERY_CHARS + 1), "bad\x00name"])
def test_a_name_that_must_not_be_sent_is_not_found_without_a_request(pubchem, route, name):
    assert pubchem.resolve(name) == failed(name, "not_found")
    assert route.call_count == 0


def test_deadline_reaches_the_http_layer(pubchem, route):
    pubchem.resolve("aspirin", deadline=time.monotonic() + 1.0)
    timeout = route.calls.last.request.extensions["timeout"]["read"]
    assert 0 < timeout <= 1.0


def test_resolution_never_replaces_the_text_it_was_asked_about():
    # R5: the canonical name is metadata. The query keeps the surface text, so no caller can
    # swap "NaHCO3" for a name that gives the answer away.
    with respx.mock() as mock:
        mock.route(host=HOST).respond(
            200,
            json={
                "PropertyTable": {
                    "Properties": [{"CID": 516892, "IUPACName": "sodium hydrogen carbonate"}]
                }
            },
        )
        result = PubChemResolver(HttpClient(timeout_s=4.0, max_rps=1000.0)).resolve("NaHCO3")
    assert result.query == "NaHCO3"
    assert result.canonical == "sodium hydrogen carbonate"
