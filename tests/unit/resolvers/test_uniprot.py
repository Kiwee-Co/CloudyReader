"""UniProtResolver: protein or gene name -> accession through the UniProtKB search endpoint.

The response fixtures follow the field names the resolver reads (primaryAccession,
proteinDescription..., genes[].geneName.value). Those names were written from memory because the
docs were unreachable; scripts/live_smoke.py checks them against the live API.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest
import respx

from cloudyreader.models import Resolution
from cloudyreader.resolvers.http import MAX_QUERY_CHARS, HttpClient
from cloudyreader.resolvers.uniprot import UniProtResolver

HOST = "rest.uniprot.org"
BRCA1 = {
    "results": [
        {
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "primaryAccession": "P38398",
            "proteinDescription": {
                "recommendedName": {
                    "fullName": {"value": "Breast cancer type 1 susceptibility protein"}
                }
            },
            "genes": [{"geneName": {"value": "BRCA1"}}],
        }
    ]
}
LOGGER = "cloudyreader.resolvers.uniprot"


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def uniprot(router) -> UniProtResolver:
    return UniProtResolver(HttpClient(timeout_s=4.0, max_rps=1000.0, sleep=lambda _: None))


@pytest.fixture
def route(router):
    return router.route(host=HOST).respond(200, json=BRCA1)


def failed(query: str, status: str, kind: str = "protein") -> Resolution:
    return Resolution(query, kind, None, {}, "uniprot", status)


def test_hit_carries_the_accession_and_the_names(uniprot, route):
    assert uniprot.resolve("BRCA1") == Resolution(
        "BRCA1",
        "protein",
        "Breast cancer type 1 susceptibility protein",
        {"accession": "P38398", "gene": "BRCA1"},
        "uniprot",
        "ok",
    )


def test_kind_follows_the_caller_and_gene_prefers_the_gene_name(uniprot, route):
    result = uniprot.resolve("BRCA1", kind="gene")
    assert result.kind == "gene"
    assert result.canonical == "BRCA1"
    assert result.ids["accession"] == "P38398"


def test_asks_the_search_endpoint_for_one_hit_over_https(uniprot, route):
    uniprot.resolve("BRCA1")
    request = route.calls.last.request
    assert request.url.scheme == "https"
    assert request.url.host == HOST
    assert request.url.path == "/uniprotkb/search"
    assert dict(request.url.params) == {
        "query": "BRCA1",
        "fields": "accession,protein_name,gene_names",
        "format": "json",
        "size": "1",
    }


@pytest.mark.parametrize(
    ("name", "wire"),
    [
        ("tumor necrosis factor", "query=tumor+necrosis+factor&"),
        ("Ca2+/calmodulin kinase", "query=Ca2%2B%2Fcalmodulin+kinase&"),
        ("kinase (EC 2.7.11.1)", "query=kinase+%28EC+2.7.11.1%29&"),
        ("a&size=500", "query=a%26size%3D500&"),
    ],
)
def test_name_is_encoded_as_one_query_value(uniprot, route, name, wire):
    uniprot.resolve(name)
    request = route.calls.last.request
    assert wire in request.url.raw_path.decode()
    assert request.url.params["size"] == "1"


def test_sends_nothing_but_the_name(uniprot, route):
    uniprot.resolve("BRCA1")
    request = route.calls.last.request
    assert request.content == b""
    assert "cookie" not in request.headers


def test_no_result_is_not_found(uniprot, router):
    router.route(host=HOST).respond(200, json={"results": []})
    assert uniprot.resolve("zzzzz") == failed("zzzzz", "not_found")


def test_404_is_not_found(uniprot, router):
    router.route(host=HOST).respond(404, json={})
    assert uniprot.resolve("zzzzz") == failed("zzzzz", "not_found")


def test_hit_without_name_fields_is_still_a_hit(uniprot, router):
    router.route(host=HOST).respond(200, json={"results": [{"primaryAccession": "P01308"}]})
    assert uniprot.resolve("insulin") == Resolution(
        "insulin", "protein", None, {"accession": "P01308"}, "uniprot", "ok"
    )


def test_protein_name_falls_back_to_the_gene_name(uniprot, router):
    hit = {"primaryAccession": "P04637", "genes": [{"geneName": {"value": "TP53"}}]}
    router.route(host=HOST).respond(200, json={"results": [hit]})
    assert uniprot.resolve("p53").canonical == "TP53"


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "oops",
        {"results": None},
        {"results": {"primaryAccession": "P1"}},
        {"results": ["not a hit"]},
        {"results": [{}]},
        {"results": [{"primaryAccession": None}]},
        {"results": [{"primaryAccession": ""}]},
        {"results": [{"primaryAccession": 12345}]},
        {"error": "bad query"},
    ],
)
def test_unexpected_shape_is_an_error_not_a_miss(uniprot, router, caplog, body):
    # A miss is cached for a day; a changed API must not poison the cache with false misses.
    router.route(host=HOST).respond(200, json=body)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert uniprot.resolve("BRCA1") == failed("BRCA1", "error")
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_shape_warning_names_keys_and_leaks_no_values(uniprot, router, caplog):
    router.route(host=HOST).respond(200, json={"Surprise": "secret-value"})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        uniprot.resolve("BRCA1")
    assert "Surprise" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.parametrize(
    ("effect", "status"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "offline"),
        (httpx.RemoteProtocolError("bad"), "error"),
    ],
)
def test_transport_failures_become_statuses(uniprot, router, effect, status):
    router.route(host=HOST).mock(side_effect=effect)
    assert uniprot.resolve("BRCA1") == failed("BRCA1", status)


@pytest.mark.parametrize("code", [429, 503])
def test_busy_server_is_an_error_after_two_retries(uniprot, router, code):
    busy = router.route(host=HOST).respond(code)
    assert uniprot.resolve("BRCA1") == failed("BRCA1", "error")
    assert busy.call_count == 3


def test_bad_query_syntax_is_an_error(uniprot, router):
    router.route(host=HOST).respond(400, json={"messages": ["invalid query"]})
    assert uniprot.resolve("a:b") == failed("a:b", "error")


@pytest.mark.parametrize("name", ["", "   ", "\n", "a" * (MAX_QUERY_CHARS + 1), "bad\x00name"])
def test_a_name_that_must_not_be_sent_is_not_found_without_a_request(uniprot, route, name):
    assert uniprot.resolve(name) == failed(name, "not_found")
    assert route.call_count == 0


def test_failures_keep_the_requested_kind(uniprot, router):
    router.route(host=HOST).respond(200, json={"results": []})
    assert uniprot.resolve("BRCA1", kind="gene") == failed("BRCA1", "not_found", kind="gene")


def test_deadline_reaches_the_http_layer(uniprot, route):
    uniprot.resolve("BRCA1", deadline=time.monotonic() + 1.0)
    assert 0 < route.calls.last.request.extensions["timeout"]["read"] <= 1.0
