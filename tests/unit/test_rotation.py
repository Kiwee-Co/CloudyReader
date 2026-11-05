"""VoiceRotator: pools per mode, round robin, shuffled deck (seeded), mode ids and labels."""

from __future__ import annotations

import itertools
import random
import subprocess
import sys
from pathlib import Path

import pytest

from cloudyreader.engines.kokoro import VOICE_GRADES
from cloudyreader.models import VoiceInfo
from cloudyreader.rotation import RotationMode, VoiceRotator

ROOT = Path(__file__).resolve().parents[2]
PIPER_IDS = (
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-ryan-medium",
    "en_GB-alan-medium",
    "en_GB-jenny_dioco-medium",
)
ROTATING = [mode for mode in RotationMode if mode is not RotationMode.NONE]


def voice(
    key: str, language: str = "en-US", *, installed: bool = True, speakers: int = 1
) -> VoiceInfo:
    return VoiceInfo(key, key.partition(":")[0], key, language, "medium", speakers, installed)


def piper(vid: str, **kwargs) -> VoiceInfo:
    return voice(f"piper:{vid}", vid.split("-")[0].replace("_", "-"), **kwargs)


def kokoro(vid: str, **kwargs) -> VoiceInfo:
    return voice(f"kokoro:{vid}", "en-US" if vid[0] == "a" else "en-GB", **kwargs)


def keys(voices) -> list[str]:
    return [v.key for v in voices]


def picks(rotator: VoiceRotator, voices, count: int) -> list[str]:
    return [rotator.next_voice(voices).key for _ in range(count)]


ALL = tuple(piper(vid) for vid in PIPER_IDS) + tuple(kokoro(vid) for vid in VOICE_GRADES)
HEART, BELLA, EMMA, MICHAEL, GEORGE = (
    kokoro(vid) for vid in ("af_heart", "af_bella", "bf_emma", "am_michael", "bm_george")
)
FOUR = [HEART, BELLA, EMMA, MICHAEL]
EXCLUDED = [
    piper("en_US-amy-medium", installed=False),
    voice("piper:en_US-libritts-high", speakers=904),
    kokoro("am_adam", speakers=2),
    voice("piper:en_US-joe-medium"),  # no gender on file
    voice("kokoro:jf_alpha", "ja-JP"),  # not English
    voice("kokoro:zf_xiaobei"),
]


# --- RotationMode -------------------------------------------------------------------------------


def test_mode_ids_labels_and_order_are_frozen():
    assert [(m.name, m.value, m.label) for m in RotationMode] == [
        ("NONE", "none", "No rotation"),
        ("ROUND_ROBIN", "round_robin", "Round robin"),
        ("SHUFFLE", "shuffle", "Random shuffle"),
        ("US_SHUFFLE", "us_shuffle", "US only (random shuffle)"),
        ("MEN_SHUFFLE", "men_shuffle", "Men only"),
        ("WOMEN_SHUFFLE", "women_shuffle", "Women only"),
    ]


def test_a_mode_is_its_id_string():
    # The window stores str(mode) in QSettings and reads it back through parse().
    assert str(RotationMode.US_SHUFFLE) == "us_shuffle"
    assert RotationMode.MEN_SHUFFLE == "men_shuffle"


@pytest.mark.parametrize("mode", list(RotationMode))
def test_parse_reads_every_id_and_member(mode):
    assert RotationMode.parse(mode.value) is mode
    assert RotationMode.parse(mode) is mode


@pytest.mark.parametrize(
    "junk",
    [None, "", "Shuffle", " shuffle", "random", "No rotation", 0, 1, 2.5, True, b"shuffle"]
    + [["shuffle"], {"mode": "shuffle"}, object()],
)
def test_parse_junk_gives_none(junk):
    assert RotationMode.parse(junk) is RotationMode.NONE


# --- pool -----------------------------------------------------------------------------------------


def test_mode_none_never_picks():
    rotator = VoiceRotator(rng=random.Random(1))

    assert rotator.mode is RotationMode.NONE
    assert rotator.next_voice(ALL) is None
    assert rotator.last_key is None


@pytest.mark.parametrize("mode", ROTATING)
def test_an_empty_pool_gives_none(mode):
    rotator = VoiceRotator(mode, rng=random.Random(1))

    assert rotator.next_voice([]) is None
    assert rotator.next_voice([kokoro("af_heart", installed=False)]) is None
    assert rotator.last_key is None


def test_pool_keeps_installed_single_speaker_voices_with_a_known_gender():
    lessac = piper("en_US-lessac-medium")

    pool = VoiceRotator(RotationMode.SHUFFLE).pool([*EXCLUDED[:3], lessac, *EXCLUDED[3:], HEART])

    assert pool == [lessac, HEART]


@pytest.mark.parametrize("mode", list(RotationMode))
def test_uninstalled_multi_speaker_and_unknown_voices_are_out_of_every_mode(mode):
    assert VoiceRotator(mode).pool(EXCLUDED) == []


def test_pool_keeps_list_order_and_counts_a_repeated_key_once():
    later_heart = VoiceInfo(HEART.key, "kokoro", "Heart again", "en-US", "A", 1, True)

    pool = VoiceRotator(RotationMode.SHUFFLE).pool([EMMA, HEART, MICHAEL, later_heart, BELLA])

    assert pool == [EMMA, HEART, MICHAEL, BELLA]


@pytest.mark.parametrize(
    ("mode", "size"),
    [
        (RotationMode.NONE, 33),
        (RotationMode.ROUND_ROBIN, 33),
        (RotationMode.SHUFFLE, 33),
        (RotationMode.US_SHUFFLE, 23),
        (RotationMode.MEN_SHUFFLE, 15),
        (RotationMode.WOMEN_SHUFFLE, 18),
    ],
)
def test_pool_sizes_with_all_33_voices_installed(mode, size):
    assert len(ALL) == 33
    assert len(VoiceRotator(mode).pool(ALL)) == size


def test_filtered_pools_hold_the_right_voices():
    def pool_keys(mode: RotationMode) -> set[str]:
        return set(keys(VoiceRotator(mode).pool(ALL)))

    kokoro_men = {f"kokoro:{vid}" for vid in VOICE_GRADES if vid[1] == "m"}
    kokoro_women = {f"kokoro:{vid}" for vid in VOICE_GRADES if vid[1] == "f"}

    assert pool_keys(RotationMode.US_SHUFFLE) == {v.key for v in ALL if v.language == "en-US"}
    assert pool_keys(RotationMode.MEN_SHUFFLE) == kokoro_men | {
        "piper:en_US-ryan-medium",
        "piper:en_GB-alan-medium",
    }
    assert pool_keys(RotationMode.WOMEN_SHUFFLE) == kokoro_women | {
        "piper:en_US-lessac-medium",
        "piper:en_US-amy-medium",
        "piper:en_GB-jenny_dioco-medium",
    }


@pytest.mark.parametrize("mode", list(RotationMode))
@pytest.mark.parametrize(
    "odd",
    [None, 42, [None], [object()], "kokoro:af_heart", ["kokoro:af_heart"]],
    ids=["none", "int", "list-of-none", "list-of-object", "str", "list-of-str"],
)
def test_odd_input_never_raises(mode, odd):
    rotator = VoiceRotator(mode, rng=random.Random(0))

    assert rotator.pool(odd) == []
    assert rotator.next_voice(odd) is None


def test_junk_modes_read_as_none():
    rotator = VoiceRotator("loud", rng=random.Random(0))
    assert rotator.mode is RotationMode.NONE

    rotator.set_mode(RotationMode.SHUFFLE)
    rotator.set_mode(None)

    assert rotator.mode is RotationMode.NONE


# --- round robin --------------------------------------------------------------------------------


def test_round_robin_follows_list_order_and_wraps():
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)

    assert picks(rotator, [HEART, EMMA, MICHAEL], 7) == keys([HEART, EMMA, MICHAEL] * 2 + [HEART])
    assert rotator.last_key == HEART.key


def test_round_robin_skips_a_voice_that_left():
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)
    rotator.next_voice(FOUR)  # Heart

    assert rotator.next_voice([HEART, kokoro("af_bella", installed=False), EMMA]) is EMMA


def test_round_robin_restarts_at_the_first_voice_when_the_last_one_left():
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)
    picks(rotator, FOUR, 2)  # Heart, Bella

    assert rotator.next_voice([HEART, EMMA, MICHAEL]) is HEART


def test_round_robin_picks_a_new_voice_listed_after_the_last_one():
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)
    rotator.next_voice([HEART, EMMA])  # Heart

    assert rotator.next_voice([HEART, GEORGE, EMMA]) is GEORGE


def test_round_robin_returns_the_latest_voice_object():
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)
    rotator.next_voice([HEART, EMMA])
    fresh_emma = VoiceInfo(EMMA.key, "kokoro", "Emma (female)", "en-GB", "B-", 1, True)

    assert rotator.next_voice([HEART, fresh_emma]) is fresh_emma


def test_round_robin_with_one_voice_repeats_it():
    assert picks(VoiceRotator(RotationMode.ROUND_ROBIN), [HEART], 3) == [HEART.key] * 3


# --- shuffle --------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [3, 4, 33])
def test_shuffle_deals_each_voice_once_per_cycle_and_never_repeats_across_rebuilds(size):
    voices = ALL[:size]
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(size))

    dealt = picks(rotator, voices, 200 * size)

    cycles = [dealt[start : start + size] for start in range(0, len(dealt), size)]
    assert all(sorted(cycle) == sorted(keys(voices)) for cycle in cycles)
    assert all(a != b for a, b in itertools.pairwise(dealt))
    assert len({tuple(cycle) for cycle in cycles}) > 1  # really shuffled, not list order


def test_shuffle_is_reproducible_with_a_seeded_rng():
    first = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(42))
    second = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(42))

    assert picks(first, ALL, 66) == picks(second, ALL, 66)


def test_shuffle_without_an_rng_still_deals_every_voice():
    rotator = VoiceRotator(RotationMode.SHUFFLE)
    assert sorted(picks(rotator, FOUR, 4)) == sorted(keys(FOUR))


def test_shuffle_with_one_voice_repeats_it():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(5))
    assert picks(rotator, [HEART], 4) == [HEART.key] * 4


def test_shuffle_with_two_voices_alternates():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(5))

    dealt = picks(rotator, [HEART, GEORGE], 40)

    assert all(a != b for a, b in itertools.pairwise(dealt))
    assert set(dealt) == {HEART.key, GEORGE.key}


def test_shuffle_drops_a_voice_that_left_from_the_deck():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(11))
    first = rotator.next_voice(FOUR)
    gone = next(v for v in FOUR if v is not first)  # still in the deck
    rest = [v for v in FOUR if v is not gone]

    finish = picks(rotator, rest, 2)

    assert gone.key not in finish
    assert sorted([first.key, *finish]) == sorted(keys(rest))


def test_shuffle_deals_a_new_voice_from_the_next_deck():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(3))
    three = [HEART, EMMA, MICHAEL]
    grown = [*three, GEORGE]

    first = rotator.next_voice(three)
    finish = picks(rotator, grown, 2)  # George joined mid-cycle
    next_deck = picks(rotator, grown, 4)

    assert sorted([first.key, *finish]) == sorted(keys(three))
    assert sorted(next_deck) == sorted(keys(grown))


@pytest.mark.parametrize(
    ("mode", "allowed"),
    [
        (RotationMode.US_SHUFFLE, {HEART.key, BELLA.key, MICHAEL.key}),
        (RotationMode.MEN_SHUFFLE, {MICHAEL.key, GEORGE.key}),
        (RotationMode.WOMEN_SHUFFLE, {HEART.key, BELLA.key, EMMA.key}),
    ],
)
def test_filtered_shuffles_deal_only_their_pool(mode, allowed):
    rotator = VoiceRotator(mode, rng=random.Random(9))

    dealt = picks(rotator, [*FOUR, GEORGE], 30)

    assert set(dealt) == allowed
    assert all(a != b for a, b in itertools.pairwise(dealt))


# --- set_mode -------------------------------------------------------------------------------------


def test_set_mode_drops_the_deck_and_keeps_the_last_key():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(8))
    last = picks(rotator, ALL, 10)[-1]

    rotator.set_mode(RotationMode.SHUFFLE)
    kept = rotator.last_key
    fresh = picks(rotator, ALL, 33)

    assert (rotator.mode, kept) == (RotationMode.SHUFFLE, last)
    assert sorted(fresh) == sorted(keys(ALL))  # a whole new deck, not the 23 voices left over
    assert fresh[0] != last


def test_round_robin_after_a_shuffle_continues_after_the_last_pick():
    rotator = VoiceRotator(RotationMode.SHUFFLE, rng=random.Random(2))
    last = rotator.next_voice(FOUR)

    rotator.set_mode(RotationMode.ROUND_ROBIN)

    assert rotator.last_key == last.key
    assert rotator.next_voice(FOUR) is FOUR[(FOUR.index(last) + 1) % len(FOUR)]


def test_an_empty_pool_keeps_the_last_key():
    rotator = VoiceRotator(RotationMode.MEN_SHUFFLE, rng=random.Random(4))
    rotator.next_voice([MICHAEL])

    assert rotator.next_voice([HEART, EMMA]) is None
    assert rotator.last_key == MICHAEL.key


def test_importing_rotation_loads_only_the_stdlib():
    # The GUI imports it at start-up: no Qt, httpx, engines, or pipeline.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "before = set(sys.modules)\n"
        "import cloudyreader.rotation\n"
        "new = {name.partition('.')[0] for name in set(sys.modules) - before}\n"
        "foreign = sorted(new - set(sys.stdlib_module_names) - {'cloudyreader'})\n"
        "assert not foreign, foreign\n"
        "ours = {name for name in sys.modules if name.startswith('cloudyreader.')}\n"
        "allowed = {'cloudyreader.rotation', 'cloudyreader.voice_meta', 'cloudyreader.models'}\n"
        "assert ours <= allowed, sorted(ours)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
