"""HttpClient: HTTPS only, encoding, retries, rate limit, and the deadline that bounds both."""

from __future__ import annotations

import threading

import httpx
import pytest
import respx

from cloudyreader.resolvers.http import (
    MAX_QUERY_CHARS,
    HttpBusy,
    HttpClient,
    HttpError,
    HttpNotFound,
    HttpTimeout,
    HttpUnreachable,
    clean_query,
    dig,
    failure_status,
    quote_segment,
    shape,
)

URL = "https://api.example.org/v1/thing"


class FakeTime:
    """A clock that only moves when `sleep` is called, so no test waits for real."""

    def __init__(self, *, advance: bool = True) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []
        self._advance = advance

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self._advance:
            self.t += seconds


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def time_():
    return FakeTime()


@pytest.fixture
def make(time_):
    def build(**kwargs) -> HttpClient:
        kwargs.setdefault("timeout_s", 4.0)
        kwargs.setdefault("max_rps", 1000.0)  # spacing of 1 ms: invisible unless a test cares
        return HttpClient(clock=time_.clock, sleep=time_.sleep, **kwargs)

    return build


def test_every_failure_is_an_http_error():
    for error in (HttpTimeout, HttpBusy, HttpNotFound, HttpUnreachable):
        assert issubclass(error, HttpError)


def test_get_json_returns_the_parsed_body(router, make):
    router.get(URL).respond(200, json={"a": [1, 2]})
    assert make().get_json(URL) == {"a": [1, 2]}


def test_params_are_encoded_on_the_wire(router, make):
    route = router.get(URL).respond(200, json={})
    make().get_json(URL, {"query": "a b&c=d/(x)", "fields": "accession,protein_name"})
    raw = route.calls.last.request.url.raw_path
    assert raw == b"/v1/thing?query=a+b%26c%3Dd%2F%28x%29&fields=accession%2Cprotein_name"


def test_sends_a_json_accept_header_and_names_the_app(router, make):
    route = router.get(URL).respond(200, json={})
    make().get_json(URL)
    headers = route.calls.last.request.headers
    assert headers["accept"] == "application/json"
    assert headers["user-agent"].startswith("cloudyreader/")


def test_404_raises_not_found(router, make):
    router.get(URL).respond(404, json={"Fault": {"Code": "PUGREST.NotFound"}})
    with pytest.raises(HttpNotFound):
        make().get_json(URL)


@pytest.mark.parametrize(
    "error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout]
)
def test_any_httpx_timeout_raises_http_timeout(router, make, error):
    router.get(URL).mock(side_effect=error("slow"))
    with pytest.raises(HttpTimeout):
        make().get_json(URL)


def test_connection_failure_raises_unreachable(router, make):
    router.get(URL).mock(side_effect=httpx.ConnectError("no route to host"))
    with pytest.raises(HttpUnreachable):
        make().get_json(URL)


def test_other_transport_failure_is_a_plain_http_error(router, make):
    router.get(URL).mock(side_effect=httpx.RemoteProtocolError("garbage"))
    with pytest.raises(HttpError) as info:
        make().get_json(URL)
    assert type(info.value) is HttpError


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 500, 502, 504])
def test_other_statuses_fail_once_without_retry(router, make, time_, status):
    route = router.get(URL).respond(status, headers={"Location": "http://api.example.org/"})
    with pytest.raises(HttpError) as info:
        make().get_json(URL)
    assert type(info.value) is HttpError
    assert route.call_count == 1
    assert time_.sleeps == []


@pytest.mark.parametrize("status", [429, 503])
def test_busy_server_is_retried_after_a_backoff(router, make, time_, status):
    route = router.get(URL)
    route.side_effect = [httpx.Response(status), httpx.Response(200, json={"ok": True})]
    assert make().get_json(URL) == {"ok": True}
    assert route.call_count == 2
    assert time_.sleeps == [0.5]


@pytest.mark.parametrize("status", [429, 503])
def test_busy_server_gets_two_retries_then_http_busy(router, make, time_, status):
    route = router.get(URL).respond(status)
    with pytest.raises(HttpBusy):
        make().get_json(URL)
    assert route.call_count == 3
    assert time_.sleeps == [0.5, 1.0]


def test_busy_then_not_found_is_not_found(router, make):
    router.get(URL).side_effect = [httpx.Response(503), httpx.Response(404)]
    with pytest.raises(HttpNotFound):
        make().get_json(URL)


def test_non_json_body_is_an_error(router, make):
    router.get(URL).respond(200, text="<html>maintenance</html>")
    with pytest.raises(HttpError):
        make().get_json(URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.org/v1/thing",
        "HTTP://api.example.org/v1/thing",
        "ftp://api.example.org/v1/thing",
        "file:///etc/passwd",
        "//api.example.org/v1/thing",
        "api.example.org/v1/thing",
    ],
)
def test_anything_but_https_is_refused_before_any_request(router, make, url):
    route = router.route().respond(200, json={})
    with pytest.raises(ValueError, match="HTTPS"):
        make().get_json(url)
    assert route.call_count == 0


def test_https_scheme_is_case_insensitive(router, make):
    router.get(URL).respond(200, json={"ok": True})
    assert make().get_json(URL.replace("https", "HTTPS")) == {"ok": True}


def test_redirects_are_never_followed(router, make):
    plain = router.get("http://api.example.org/v1/thing").respond(200, json={"leak": True})
    router.get(URL).respond(302, headers={"Location": "http://api.example.org/v1/thing"})
    with pytest.raises(HttpError):
        make().get_json(URL)
    assert plain.call_count == 0


def test_an_injected_client_is_used_and_not_closed(time_):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"via": "injected"})

    injected = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(timeout_s=4.0, client=injected, clock=time_.clock, sleep=time_.sleep)
    assert http.get_json(URL) == {"via": "injected"}
    http.close()
    assert not injected.is_closed
    assert seen[0].extensions["timeout"]["read"] == 4.0


def test_the_configured_timeout_wins_over_the_injected_client(router, time_):
    route = router.get(URL).respond(200, json={})
    slow = httpx.Client(timeout=99.0)
    HttpClient(timeout_s=1.5, client=slow, clock=time_.clock).get_json(URL)
    assert route.calls.last.request.extensions["timeout"]["read"] == 1.5


@pytest.mark.parametrize("kwargs", [{"timeout_s": 0}, {"timeout_s": -1}, {"max_rps": 0}])
def test_constructor_rejects_nonsense(kwargs):
    with pytest.raises(ValueError):
        HttpClient(**({"timeout_s": 4.0} | kwargs))


def test_requests_start_at_least_one_interval_apart(router, make, time_):
    router.get(URL).respond(200, json={})
    http = make(max_rps=5.0)
    for _ in range(3):
        http.get_json(URL)
    assert time_.sleeps == pytest.approx([0.2, 0.2])


def test_threads_never_share_a_rate_limit_slot(router):
    route = router.get(URL).respond(200, json={})
    frozen = FakeTime(advance=False)  # every thread competes for a slot at the same instant
    http = HttpClient(timeout_s=4.0, max_rps=5.0, clock=frozen.clock, sleep=frozen.sleep)
    threads = [threading.Thread(target=http.get_json, args=(URL,)) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert route.call_count == 20
    assert sorted(frozen.sleeps) == pytest.approx([0.2 * n for n in range(1, 20)])


def test_a_spent_deadline_sends_nothing(router, make, time_):
    route = router.get(URL).respond(200, json={})
    with pytest.raises(HttpTimeout):
        make().get_json(URL, deadline=time_.t)
    assert route.call_count == 0


def test_deadline_caps_the_request_timeout(router, make, time_):
    route = router.get(URL).respond(200, json={})
    make().get_json(URL, deadline=time_.t + 1.5)
    assert route.calls.last.request.extensions["timeout"]["read"] == pytest.approx(1.5)


def test_a_deadline_far_away_leaves_the_timeout_alone(router, make, time_):
    route = router.get(URL).respond(200, json={})
    make().get_json(URL, deadline=time_.t + 60)
    assert route.calls.last.request.extensions["timeout"]["read"] == 4.0


def test_backoff_that_would_cross_the_deadline_gives_up_without_sleeping(router, make, time_):
    route = router.get(URL).respond(503)
    with pytest.raises(HttpTimeout):
        make().get_json(URL, deadline=time_.t + 0.4)
    assert route.call_count == 1
    assert time_.sleeps == []


def test_rate_limit_slot_after_the_deadline_gives_up_without_a_request(router, make, time_):
    route = router.get(URL).respond(200, json={})
    http = make(max_rps=1.0)
    http.get_json(URL, deadline=time_.t + 0.5)
    with pytest.raises(HttpTimeout):
        http.get_json(URL, deadline=time_.t + 0.5)
    assert route.call_count == 1


def test_rate_limit_slot_at_the_deadline_is_refused_without_sleeping(router, make, time_):
    router.get(URL).respond(200, json={})
    http = make(max_rps=1.0)
    http.get_json(URL)
    with pytest.raises(HttpTimeout):
        http.get_json(URL, deadline=time_.t + 1.0)  # the next slot opens exactly at the deadline
    assert time_.sleeps == []


def test_oversleeping_past_the_deadline_sends_nothing(router):
    route = router.get(URL).respond(200, json={})
    late = FakeTime()

    def oversleep(seconds: float) -> None:
        late.sleeps.append(seconds)
        late.t += seconds * 3

    http = HttpClient(timeout_s=4.0, max_rps=1.0, clock=late.clock, sleep=oversleep)
    http.get_json(URL)
    with pytest.raises(HttpTimeout):
        http.get_json(URL, deadline=late.t + 1.5)  # slot at 1.0 is in time, the sleep ends at 3.0
    assert route.call_count == 1


def test_close_closes_the_client_it_made(router):
    http = HttpClient(timeout_s=4.0)
    http.close()
    with pytest.raises(RuntimeError, match="closed"):
        http.get_json(URL)


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("aspirin", "aspirin"),
        ("1,2-dichloroethane", "1%2C2-dichloroethane"),
        ("N/A", "N%2FA"),
        ("acetic acid", "acetic%20acid"),
        ("(E)-but-2-ene", "%28E%29-but-2-ene"),
        ("a?b#c%d", "a%3Fb%23c%25d"),
        ("α-pinene", "%CE%B1-pinene"),
        ("a+b", "a%2Bb"),
    ],
)
def test_quote_segment_encodes_everything_that_could_end_a_segment(name, encoded):
    assert quote_segment(name) == encoded


def test_quoted_segment_reaches_the_wire_as_one_segment(router, make):
    route = router.route(host="api.example.org").respond(200, json={})
    make().get_json(f"https://api.example.org/name/{quote_segment('a/b c(d)')}/property")
    assert route.calls.last.request.url.raw_path == b"/name/a%2Fb%20c%28d%29/property"


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (HttpNotFound("x"), "not_found"),
        (HttpTimeout("x"), "timeout"),
        (HttpUnreachable("x"), "offline"),
        (HttpBusy("x"), "error"),
        (HttpError("x"), "error"),
    ],
)
def test_failure_status_maps_each_error_to_a_resolution_status(exc, status):
    assert failure_status(exc) == status


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("aspirin", "aspirin"),
        ("  aspirin\t", "aspirin"),
        ("acetic\n  acid", "acetic acid"),
        ("acetic\u00a0acid", "acetic acid"),
        ("a" * MAX_QUERY_CHARS, "a" * MAX_QUERY_CHARS),
    ],
)
def test_clean_query_normalizes_whitespace(raw, cleaned):
    assert clean_query(raw) == cleaned


@pytest.mark.parametrize(
    "raw", ["", "   ", "\n\t", "a" * (MAX_QUERY_CHARS + 1), "bad\x00name", "zero\u200bwidth"]
)
def test_clean_query_refuses_what_must_not_be_sent(raw):
    assert clean_query(raw) is None


def test_dig_walks_dicts_and_lists():
    data = {"a": [{"b": 1}, {"b": 2}]}
    assert dig(data, "a", 1, "b") == 2


@pytest.mark.parametrize("path", [("x",), ("a", 5), ("a", "b"), ("a", 0, "b", "c"), ("a", 0, "zz")])
def test_dig_gives_none_for_any_missing_or_mistyped_step(path):
    assert dig({"a": [{"b": 1}]}, *path) is None


def test_dig_of_nothing_is_none():
    assert dig(None, "a") is None


def test_shape_names_the_top_level_keys_but_not_the_values():
    assert shape({"b": "secret", "a": 1}) == "dict with keys ['a', 'b']"
    assert shape([1, 2]) == "list"
    assert shape(None) == "NoneType"
