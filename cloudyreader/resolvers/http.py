"""Shared HTTPS JSON client: rate limit, bounded retries, and a deadline for the caller's budget."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx

from cloudyreader import __version__

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 256
FailureStatus = Literal["not_found", "timeout", "offline", "error"]
_BUSY_STATUSES = frozenset({429, 503})
_MAX_RETRIES = 2
_BACKOFF_BASE_S = 0.5  # waits 0.5 s, then 1 s, before giving up
_HEADERS = {"Accept": "application/json", "User-Agent": f"cloudyreader/{__version__}"}


class HttpError(Exception):
    """Every failure `HttpClient.get_json` reports. Messages carry the host, never the query."""


class HttpTimeout(HttpError):
    """The request, or the caller's deadline, ran out of time."""


class HttpBusy(HttpError):
    """429 or 503 on every try."""


class HttpNotFound(HttpError):
    """404: the server answered and has nothing for the query."""


class HttpUnreachable(HttpError):
    """No connection: no network, DNS failure, or connection refused."""


def quote_segment(value: str) -> str:
    """Percent-encode one URL path segment: `/`, `?`, `#`, spaces and parentheses stay inside it."""
    return quote(value, safe="")


def clean_query(text: str) -> str | None:
    """The entity string a lookup may send, or None when it must not leave the machine.

    Whitespace collapses to single spaces. Empty, control-character and overlong strings are
    refused: an entity is a short name, so a long one means something else was captured.
    """
    query = " ".join(text.split())
    if not query or len(query) > MAX_QUERY_CHARS or not query.isprintable():
        return None
    return query


def dig(data: Any, *path: str | int) -> Any:
    """`data[path[0]][path[1]]...`, or None when a step is missing or has the wrong type."""
    for step in path:
        try:
            data = data[step]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def shape(data: Any) -> str:
    """What to log about a response we cannot parse: its keys, never its values."""
    if isinstance(data, dict):
        return f"dict with keys {sorted(map(str, data))[:8]}"
    return type(data).__name__


def failure_status(exc: HttpError) -> FailureStatus:
    """The Resolution status that a failed request stands for."""
    if isinstance(exc, HttpNotFound):
        return "not_found"
    if isinstance(exc, HttpTimeout):
        return "timeout"
    if isinstance(exc, HttpUnreachable):
        return "offline"
    return "error"


class _Throttle:
    """Token bucket with one token: request starts are at least 1/max_rps apart.

    No burst on purpose: PubChem allows 5 requests per second and may block clients above that.
    """

    def __init__(self, max_rps: float, clock: Callable[[], float], sleep: Callable[[float], None]):
        self._interval = 1.0 / max_rps
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self, deadline: float | None) -> None:
        # Reserving the slot under the lock and sleeping outside it keeps waiters in order.
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            if deadline is not None and start >= deadline:
                raise HttpTimeout("no rate-limit slot before the deadline")
            self._next_start = start + self._interval
        if start > now:
            self._sleep(start - now)


class HttpClient:
    """GET JSON over HTTPS. `deadline` is an absolute value of `clock` (default `time.monotonic`).

    The deadline caps the rate-limit wait, each request, and the backoff, so a caller's total
    budget bounds the work and not just the wait for it.
    """

    def __init__(
        self,
        *,
        timeout_s: float,
        max_rps: float = 5.0,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s}")
        if max_rps <= 0:
            raise ValueError(f"max_rps must be positive, got {max_rps}")
        self._timeout_s = timeout_s
        self._clock = clock
        self._sleep = sleep
        self._throttle = _Throttle(max_rps, clock, sleep)
        self._owns_client = client is None
        self._client = httpx.Client() if client is None else client

    def get_json(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        *,
        deadline: float | None = None,
    ) -> Any:
        """Return the parsed JSON body. Raises ValueError for a non-HTTPS URL, else an HttpError."""
        parts = urlsplit(url)
        if parts.scheme.lower() != "https":
            raise ValueError(f"HTTPS only, refusing scheme {parts.scheme!r}")
        host = parts.hostname
        attempt = 0
        while True:
            self._throttle.wait(deadline)
            response = self._send(url, params, deadline, host)
            if response.status_code not in _BUSY_STATUSES:
                return _body(response, host)
            if attempt == _MAX_RETRIES:
                raise HttpBusy(f"HTTP {response.status_code} from {host} on every try")
            delay = _BACKOFF_BASE_S * 2**attempt
            if deadline is not None and self._clock() + delay >= deadline:
                raise HttpTimeout(f"HTTP {response.status_code} from {host} and no time to retry")
            log.debug("HTTP %s from %s, retry in %.1fs", response.status_code, host, delay)
            self._sleep(delay)
            attempt += 1

    def _send(
        self, url: str, params: Mapping[str, str] | None, deadline: float | None, host: str | None
    ) -> httpx.Response:
        timeout = self._timeout_s
        if deadline is not None:
            timeout = min(timeout, deadline - self._clock())
            if timeout <= 0:
                raise HttpTimeout("deadline passed before the request")
        # Per request, because an injected client may carry another timeout or follow redirects.
        try:
            return self._client.get(
                url, params=params, headers=_HEADERS, timeout=timeout, follow_redirects=False
            )
        except httpx.TimeoutException as exc:
            raise HttpTimeout(f"{host} did not answer within {timeout:.1f}s") from exc
        except httpx.ConnectError as exc:
            raise HttpUnreachable(f"cannot connect to {host}") from exc
        except httpx.HTTPError as exc:
            raise HttpError(f"{type(exc).__name__} talking to {host}") from exc

    def close(self) -> None:
        """Close the httpx client unless the caller injected it."""
        if self._owns_client:
            self._client.close()


def _body(response: httpx.Response, host: str | None) -> Any:
    if response.status_code == 404:
        raise HttpNotFound(f"nothing found at {host}")
    if not response.is_success:
        raise HttpError(f"HTTP {response.status_code} from {host}")
    try:
        return response.json()
    except ValueError as exc:
        raise HttpError(f"{host} sent a body that is not JSON") from exc
