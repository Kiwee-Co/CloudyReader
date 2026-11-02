"""Resolver chain: lexicon skip -> cache -> OPSIN batch -> PubChem / UniProt, under one budget.

Only entity strings are looked up, never the text around them. A resolution decides HOW a token is
spoken. Results stay keyed by the pasted text and nothing here swaps in a resolved name (R5).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, wait
from dataclasses import dataclass, replace
from queue import Empty, SimpleQueue
from typing import Any, Literal, Protocol

from cloudyreader.config import Settings
from cloudyreader.models import EntitySpan, Resolution
from cloudyreader.resolvers.cache import ResolutionCache
from cloudyreader.resolvers.http import FailureStatus, clean_query
from cloudyreader.resolvers.pubchem import PubChemResolver
from cloudyreader.resolvers.uniprot import UniProtResolver

log = logging.getLogger(__name__)

_MAX_WORKERS = 16
_LOOKUP_LABELS = frozenset({"chemical", "protein", "gene"})
_Label = Literal["chemical", "protein", "gene"]

# A cheap hint that a name is systematic. A miss only sends the name to PubChem instead of OPSIN.
_STEM = r"(?:meth|eth|prop|but|pent|hex|hept|oct|non|dec|cyclo|benz|phen)"
_ENDING = r"(?:ane|ene|yne|yl|ol|al|one|oic acid|oate|amine|amide|nitrile|ide)"
_SYSTEMATIC = re.compile(rf"\d|{_STEM}\w*{_ENDING}\b", re.IGNORECASE)


def looks_iupac(name: str) -> bool:
    """True when `name` has locants or systematic stems, so OPSIN is worth a JVM start."""
    return _SYSTEMATIC.search(name) is not None


class BatchNameResolver(Protocol):
    """What the chain needs from `OpsinResolver`: one local call for a batch of names."""

    def resolve_batch(
        self, names: Sequence[str], *, timeout_s: float = ...
    ) -> dict[str, Resolution]: ...


class _DaemonPool:
    """Worker threads that are daemons, so a hung lookup never keeps the process alive.

    ThreadPoolExecutor joins its workers in an atexit hook, daemon or not: after the window
    closed, one lookup stuck in DNS would hold the process until its socket timeout.
    """

    def __init__(self, workers: int) -> None:
        self._workers = workers
        self._tasks: SimpleQueue[tuple[Future, Callable[..., Any], tuple] | None] = SimpleQueue()
        for n in range(workers):
            name = f"cloudyreader-lookup-{n}"
            threading.Thread(target=self._work, name=name, daemon=True).start()

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        future: Future = Future()
        self._tasks.put((future, fn, args))
        return future

    def close(self) -> None:
        """Cancel what has not started and let idle workers leave. Running tasks finish alone."""
        while True:
            try:
                task = self._tasks.get_nowait()
            except Empty:
                break
            task[0].cancel()
        for _ in range(self._workers):
            self._tasks.put(None)

    def _work(self) -> None:
        while (task := self._tasks.get()) is not None:
            future, fn, args = task
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as exc:
                future.set_exception(exc)


@dataclass(frozen=True)
class _Job:
    """One lookup. Every pasted spelling in `surfaces` shares its answer."""

    label: _Label
    text: str
    surfaces: tuple[str, ...]

    @property
    def key(self) -> str:
        # The label is part of the key: "insulin" as a chemical and as a protein are different asks.
        return f"{self.label}:{self.text}"

    @property
    def source(self) -> str:
        return "pubchem" if self.label == "chemical" else "uniprot"

    def failed(self, status: FailureStatus, source: str | None = None) -> Resolution:
        return Resolution(self.text, self.label, None, {}, source or self.source, status)


class ChainResolver:
    """Resolve entity spans without ever blocking longer than the budget.

    Spans labelled formula or other, spans the lexicon skips, and strings that must not be sent
    (blank, control characters, overlong) get no entry in the result. Offline, the cache and OPSIN
    still answer: both are local. Lookups run on daemon threads, so a hung one cannot delay exit.
    """

    def __init__(
        self,
        *,
        cache: ResolutionCache,
        opsin: BatchNameResolver,
        pubchem: PubChemResolver,
        uniprot: UniProtResolver,
        settings: Settings,
        skip: Callable[[str], bool] | None = None,
    ) -> None:
        self._cache = cache
        self._opsin = opsin
        self._pubchem = pubchem
        self._uniprot = uniprot
        self._settings = settings
        self._skip = skip

    def resolve_many(
        self, spans: Sequence[EntitySpan], *, timeout_s: float | None = None
    ) -> dict[str, Resolution]:
        """Results keyed by `span.text`. `timeout_s` is the total budget (default: the settings').

        Past the budget a lookup becomes `timeout` and its late answer is dropped. When one text
        carries two lookup labels, the first span decides. Timeout, offline and error results are
        never cached.
        """
        budget = self._settings.lookup_budget_s if timeout_s is None else timeout_s
        deadline = time.monotonic() + max(budget, 0.0)
        found: dict[_Job, Resolution] = {}
        todo: list[_Job] = []
        for job in self._plan(spans):
            hit = self._cache.get(job.key)
            if hit is None:
                todo.append(job)
            else:
                found[job] = replace(hit, source="cache")
        if todo:
            fresh = self._look_up(todo, deadline)
            for job, resolution in fresh.items():
                self._cache.put(job.key, resolution)
            found.update(fresh)
        return {
            surface: replace(resolution, query=surface)
            for job, resolution in found.items()
            for surface in job.surfaces
        }

    def _plan(self, spans: Sequence[EntitySpan]) -> list[_Job]:
        claimed: set[str] = set()
        jobs: dict[tuple[str, str], _Job] = {}
        for span in spans:
            if span.label not in _LOOKUP_LABELS or span.text in claimed:
                continue
            claimed.add(span.text)
            text = clean_query(span.text)
            if text is None or (self._skip is not None and self._skip(text)):
                continue
            key = (span.label, text.casefold())
            job = jobs.get(key) or _Job(span.label, text, ())
            jobs[key] = replace(job, surfaces=(*job.surfaces, span.text))
        return list(jobs.values())

    def _look_up(self, jobs: list[_Job], deadline: float) -> dict[_Job, Resolution]:
        systematic = {j for j in jobs if j.label == "chemical" and looks_iupac(j.text)}
        batch: Future[dict[_Job, Resolution]] | None = None
        pool = _DaemonPool(min(_MAX_WORKERS, len(jobs) + 1))
        try:
            if systematic:
                # Submitted before the jobs that wait on it, so a worker always takes it first.
                batch = pool.submit(self._run_opsin, [j for j in jobs if j in systematic], deadline)
            futures = {
                job: pool.submit(self._resolve, job, batch if job in systematic else None, deadline)
                for job in jobs
            }
            done, _ = wait(futures.values(), timeout=max(deadline - time.monotonic(), 0.0))
        finally:
            pool.close()
        opsin_running = batch is not None and not batch.done()
        found: dict[_Job, Resolution] = {}
        for job, future in futures.items():
            if future in done:
                found[job] = future.result()
            else:
                source = "opsin" if opsin_running and job in systematic else None
                found[job] = job.failed("timeout", source)
        late = sum(1 for future in futures.values() if future not in done)
        if late:
            log.info("lookup budget spent: %d of %d lookups timed out", late, len(jobs))
        return found

    def _resolve(
        self, job: _Job, batch: Future[dict[_Job, Resolution]] | None, deadline: float
    ) -> Resolution:
        """OPSIN's answer when it parsed the name, else PubChem or UniProt."""
        if batch is not None:
            parsed = batch.result().get(job)
            if parsed is not None:
                return parsed
        if self._settings.offline:
            return job.failed("offline")
        return self._query(job, deadline)

    def _run_opsin(self, jobs: list[_Job], deadline: float) -> dict[_Job, Resolution]:
        """The jobs OPSIN parsed. The rest go on to PubChem."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {}
        try:
            answers = self._opsin.resolve_batch([j.text for j in jobs], timeout_s=remaining)
        except Exception:
            log.warning("OPSIN batch failed, asking PubChem instead", exc_info=True)
            return {}
        return {j: a for j in jobs if (a := answers.get(j.text)) is not None and a.status == "ok"}

    def _query(self, job: _Job, deadline: float) -> Resolution:
        try:
            if job.label == "chemical":
                return self._pubchem.resolve(job.text, deadline=deadline)
            return self._uniprot.resolve(job.text, kind=job.label, deadline=deadline)
        except Exception:
            log.exception("%s lookup failed unexpectedly", job.source)
            return job.failed("error")
