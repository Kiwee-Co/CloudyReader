"""ResolutionCache: TTLs, key normalization, what is never stored, threads, and bad files."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

import pytest

from cloudyreader.models import Resolution
from cloudyreader.resolvers.cache import ResolutionCache

DAY = 86_400
LOGGER = "cloudyreader.resolvers.cache"


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def hit(query: str = "aspirin") -> Resolution:
    ids = {"cid": "2244", "formula": "C9H8O4"}
    return Resolution(query, "chemical", "2-acetyloxybenzoic acid", ids, "pubchem", "ok")


def miss(query: str = "zzzz") -> Resolution:
    return Resolution(query, "chemical", None, {}, "pubchem", "not_found")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "resolutions.sqlite3"


@pytest.fixture
def cache(db: Path, clock: Clock) -> ResolutionCache:
    return ResolutionCache(db, clock=clock)


def row_count(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM resolutions").fetchone()[0]


def test_get_unknown_key_is_none(cache):
    assert cache.get("nothing") is None


def test_roundtrip_keeps_every_field(cache):
    cache.put("chemical:aspirin", hit())
    assert cache.get("chemical:aspirin") == hit()


def test_roundtrip_of_a_miss(cache):
    cache.put("chemical:zzzz", miss())
    assert cache.get("chemical:zzzz") == miss()


def test_creates_missing_parent_directories(db, clock):
    ResolutionCache(db, clock=clock).put("k", hit())
    assert db.exists()


@pytest.mark.parametrize("probe", ["aspirin", "ASPIRIN", "  Aspirin\t", "aSpIrIn \n"])
def test_keys_are_stripped_and_casefolded(cache, probe):
    cache.put("  ASPIRIN ", hit())
    assert cache.get(probe) == hit()


def test_casefold_not_lower(cache):
    cache.put("Straße", hit())
    assert cache.get("STRASSE") == hit()


def test_second_put_replaces_the_first(cache):
    cache.put("k", miss())
    cache.put("k", hit())
    assert cache.get("k") == hit()


def test_default_ttls_are_30_days_for_hits_and_1_day_for_misses(db, clock):
    cache = ResolutionCache(db, clock=clock)
    cache.put("hit", hit())
    cache.put("miss", miss())
    clock.now += DAY - 1
    assert cache.get("miss") is not None
    clock.now += 1
    assert cache.get("miss") is None
    assert cache.get("hit") is not None
    clock.now += 29 * DAY - 1
    assert cache.get("hit") is not None
    clock.now += 1
    assert cache.get("hit") is None


def test_ttls_are_configurable(db, clock):
    cache = ResolutionCache(db, hit_ttl_s=10, miss_ttl_s=5, clock=clock)
    cache.put("hit", hit())
    cache.put("miss", miss())
    clock.now += 5
    assert cache.get("miss") is None
    assert cache.get("hit") is not None
    clock.now += 5
    assert cache.get("hit") is None


def test_expired_row_is_deleted_on_read(db, clock):
    cache = ResolutionCache(db, miss_ttl_s=5, clock=clock)
    cache.put("miss", miss())
    clock.now += 5
    assert cache.get("miss") is None
    assert row_count(db) == 0


def test_expired_rows_are_purged_when_the_cache_opens(db, clock):
    ResolutionCache(db, miss_ttl_s=5, clock=clock).put("miss", miss())
    clock.now += 5
    ResolutionCache(db, miss_ttl_s=5, clock=clock)
    assert row_count(db) == 0


@pytest.mark.parametrize("status", ["timeout", "offline", "error"])
def test_transient_failures_are_never_stored(db, cache, status):
    cache.put("k", Resolution("q", "chemical", None, {}, "pubchem", status))
    assert cache.get("k") is None
    assert row_count(db) == 0


def test_transient_failure_does_not_evict_a_good_entry(cache):
    cache.put("k", hit())
    cache.put("k", Resolution("q", "chemical", None, {}, "pubchem", "timeout"))
    assert cache.get("k") == hit()


def test_entries_survive_a_new_instance(db, clock):
    ResolutionCache(db, clock=clock).put("k", hit())
    assert ResolutionCache(db, clock=clock).get("k") == hit()


def test_database_uses_wal(db, cache):
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_many_threads_share_one_cache(cache):
    errors: list[Exception] = []

    def work(worker: int) -> None:
        try:
            for i in range(60):
                key = f"w{worker}-{i}"
                cache.put(key, hit(key))
                assert cache.get(key) == hit(key)
                cache.get("shared")
                cache.put("shared", miss())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert cache.get("w7-59") == hit("w7-59")


def test_two_instances_share_one_file_without_lock_errors(db, clock):
    first, second = ResolutionCache(db, clock=clock), ResolutionCache(db, clock=clock)
    errors: list[Exception] = []

    def work(cache: ResolutionCache, prefix: str) -> None:
        try:
            for i in range(60):
                cache.put(f"{prefix}{i}", hit(prefix))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=work, args=(first, "a")),
        threading.Thread(target=work, args=(second, "b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert row_count(db) == 120


def test_row_that_cannot_be_decoded_is_a_miss_and_is_dropped(db, cache):
    cache.put("k", hit())
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE resolutions SET ids = 'not json'")
    assert cache.get("k") is None
    assert row_count(db) == 0


def test_unwritable_location_disables_the_cache_with_a_warning(tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        cache = ResolutionCache(blocker / "resolutions.sqlite3")
    cache.put("k", hit())
    assert cache.get("k") is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_garbage_file_disables_the_cache_instead_of_raising(db, caplog):
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database" * 100)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        cache = ResolutionCache(db)
    cache.put("k", hit())
    assert cache.get("k") is None
    assert caplog.records


def test_close_makes_later_calls_harmless(cache):
    cache.put("k", hit())
    cache.close()
    assert cache.get("k") is None
    cache.put("k", hit())


def test_ids_that_are_not_an_object_are_a_miss_and_are_dropped(db, cache):
    cache.put("k", hit())
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE resolutions SET ids = '[1, 2]'")
    assert cache.get("k") is None
    assert row_count(db) == 0


def test_a_table_dropped_behind_its_back_degrades_to_misses_with_warnings(db, cache, caplog):
    cache.put("k", hit())
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE resolutions")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert cache.get("k") is None
        cache.put("k", hit())
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.WARNING]
