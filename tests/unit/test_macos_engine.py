"""macOS engine: the `say` listing, the exact argv, stdin, timeouts, cancel, temp files and
failures, all over a fake `subprocess.Popen`. No test here runs the real `say` except the live
one, which needs CR_LIVE_SAY=1 on a Mac."""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import subprocess
import sys
import threading
import wave
from array import array
from pathlib import Path

import pytest

from cloudyreader import engine_catalog, prefetch
from cloudyreader.config import Settings
from cloudyreader.engines import macos
from cloudyreader.engines.macos import (
    DEFAULT_WPM,
    ENV,
    KEY,
    LIST_TIMEOUT_S,
    NOVELTY,
    SAMPLE_RATE,
    MacosEngine,
    SystemVoice,
    parse_listing,
    say_text,
)
from cloudyreader.engines.mlxkit import EngineError, EngineUnavailable
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.normalize import LETTER_PAUSE_MS, ScriptNormalizer
from cloudyreader.parser import QuestionParser
from cloudyreader.tts import TtsService

ROOT = Path(__file__).resolve().parents[2]
# `say --voice=?` on macOS 27.0, verbatim: 184 voices, none of them Enhanced or Premium.
LISTING = (ROOT / "tests" / "fixtures" / "say" / "voices.txt").read_text(encoding="utf-8")
OPTS = RenderOptions()
SAY = "/usr/bin/say"
# 0.5 s of a loud square wave: say's output as the fakes write it.
SPEECH = b"\x10\x27\xf0\xd8" * (SAMPLE_RATE // 4)


def line(name: str, locale: str, sample: str = "Hello!") -> str:
    """One listing line in say's own columns: name to 19, a space, locale to 8, then ` # `."""
    return f"{name:<19} {locale:<8} # {sample}"


# Voices this Mac does not have, in the listing's columns (test_line_matches_the_real_columns).
TIERS = "\n".join(
    [
        line("Ava (Premium)", "en_US", "Hello! My name is Ava."),
        line("Samantha (Enhanced)", "en_US", "Hello! My name is Samantha."),
        line("Daniel (Enhanced)", "en_GB", "Hello! My name is Daniel."),
        line("Lee (Premium)", "en_AU", "Hello! My name is Lee."),
        line("Fiona (Enhanced)", "en-scotland", "Hello! My name is Fiona."),
        line("Anna (Premium)", "de_DE", "Hallo! Ich heiße Anna."),
    ]
)
# The English voices of LISTING that are not novelty voices, in listing order.
OFFERED = [
    "Daniel",
    "Eddy (English (UK))",
    "Eddy (English (US))",
    "Flo (English (UK))",
    "Flo (English (US))",
    "Fred",
    "Grandma (English (UK))",
    "Grandma (English (US))",
    "Grandpa (English (UK))",
    "Grandpa (English (US))",
    "Junior",
    "Karen",
    "Kathy",
    "Moira",
    "Ralph",
    "Reed (English (UK))",
    "Reed (English (US))",
    "Rishi",
    "Rocko (English (UK))",
    "Rocko (English (US))",
    "Samantha",
    "Sandy (English (UK))",
    "Sandy (English (US))",
    "Shelley (English (UK))",
    "Shelley (English (US))",
    "Tessa",
]


def voice(name: str, *, language: str = "en-US", tier: str = "Standard") -> VoiceInfo:
    base = name.partition(" (")[0]
    return VoiceInfo(f"{KEY}:{name}", KEY, base, language, tier, 1, True)


SAMANTHA = voice("Samantha")
SCRIPT = SpokenScript((Segment("Which gas do plants take in?", 700), Segment("W.", 300)))


# --- a fake say ----------------------------------------------------------------------------------


class FakeProc:
    """The Popen of one say run: answers the listing, or writes the WAV the argv names."""

    def __init__(self, say: FakeSay, argv: list[str], kwargs: dict) -> None:
        self.say = say
        self.args = argv
        self.kwargs = kwargs
        self.returncode: int | None = None
        self.input: bytes | None = None
        self.timeouts: list[float | None] = []
        self.killed = threading.Event()
        self.folder_mode: int | None = None

    def output(self) -> Path | None:
        found = [a.partition("=")[2] for a in self.args if a.startswith("--output-file=")]
        return Path(found[0]) if found else None

    def communicate(self, input=None, timeout=None):
        self.timeouts.append(timeout)
        if self.input is None:
            self.input = input
        if self.killed.is_set():
            self.returncode = -9
            return b"", b""
        if "--voice=?" in self.args:
            self.returncode = self.say.list_code
            return self.say.listing.encode("utf-8"), self.say.list_stderr
        if self.say.hang:
            self.say.started.set()
            if self.say.hang == "timeout":
                raise subprocess.TimeoutExpired(self.args, timeout)
            assert self.killed.wait(5), "nothing killed the hanging say"
            self.returncode = -9
            return b"", b""
        self.returncode = self.say.code
        out = self.output()
        if out is not None:
            self.folder_mode = stat.S_IMODE(out.parent.stat().st_mode)
            if self.say.write:
                with wave.open(str(out), "wb") as wav:
                    wav.setnchannels(self.say.channels)
                    wav.setsampwidth(2)
                    wav.setframerate(self.say.rate)
                    wav.writeframes(self.say.frames)
        return b"", self.say.stderr

    def kill(self) -> None:
        self.say.kills += 1
        self.killed.set()

    def wait(self, timeout=None) -> int:
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


class FakeSay:
    """Stands in for subprocess.Popen: every say run is recorded, nothing real ever runs."""

    def __init__(self, listing: str = LISTING, **behavior) -> None:
        self.listing = listing
        self.list_code = behavior.get("list_code", 0)
        self.list_stderr = behavior.get("list_stderr", b"")
        self.frames = behavior.get("frames", SPEECH)
        self.code = behavior.get("code", 0)
        self.stderr = behavior.get("stderr", b"")
        self.rate = behavior.get("rate", SAMPLE_RATE)
        self.channels = behavior.get("channels", 1)
        self.write = behavior.get("write", True)
        self.hang = behavior.get("hang", False)
        self.started = threading.Event()
        self.kills = 0
        self.procs: list[FakeProc] = []

    def __call__(self, argv, **kwargs) -> FakeProc:
        proc = FakeProc(self, list(argv), kwargs)
        self.procs.append(proc)
        return proc

    @property
    def synths(self) -> list[FakeProc]:
        return [p for p in self.procs if "--voice=?" not in p.args]


@pytest.fixture
def mac(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")


def engine(say: FakeSay, path: str = SAY) -> MacosEngine:
    made = MacosEngine(say=path, popen=say)
    made.available = lambda: True  # the real check stats /usr/bin/say
    return made


def synthesize(made: MacosEngine, out: Path, script: SpokenScript = SCRIPT, **opts):
    return made.synthesize(script, SAMANTHA, RenderOptions(**opts), out)


# --- the listing -------------------------------------------------------------------------------


def test_line_matches_the_real_columns():
    real = LISTING.splitlines()

    assert line("Albert", "en_US", "Hello! My name is Albert.") in real
    assert line("Flo (English (UK))", "en_GB", "Hello! My name is Flo.") in real
    assert line("Majed", "ar_001", "مرحبًا! اسمي ماجد.") in real


def test_parse_reads_every_voice_of_the_real_listing():
    voices = parse_listing(LISTING)

    assert len(voices) == len(LISTING.splitlines()) == 184
    by_name = {v.name: v.locale for v in voices}
    assert by_name["Bad News"] == "en_US"  # a two-word name
    assert by_name["Eddy (German (Germany))"] == "de_DE"  # past the name column
    assert by_name["Majed"] == "ar_001"
    assert by_name["Amélie"] == "fr_CA"


def test_tier_base_name_and_language_come_from_the_listed_name():
    tiers = {v.name: (v.base, v.tier, v.language) for v in parse_listing(TIERS)}

    assert tiers == {
        "Ava (Premium)": ("Ava", "Premium", "en-US"),
        "Samantha (Enhanced)": ("Samantha", "Enhanced", "en-US"),
        "Daniel (Enhanced)": ("Daniel", "Enhanced", "en-GB"),
        "Lee (Premium)": ("Lee", "Premium", "en-AU"),
        "Fiona (Enhanced)": ("Fiona", "Enhanced", "en-scotland"),
        "Anna (Premium)": ("Anna", "Premium", "de-DE"),
    }
    eddy = SystemVoice("Eddy (English (US))", "en_US")
    assert (eddy.base, eddy.tier, eddy.language) == ("Eddy", "Standard", "en-US")


@pytest.mark.parametrize(
    "junk",
    ["", "   ", "no locale here", "Samantha en_US no hash", "# only a comment", "Samantha # x"],
)
def test_a_line_without_name_locale_and_hash_is_skipped(junk):
    assert parse_listing(f"{junk}\n{line('Samantha', 'en_US')}") == [
        SystemVoice("Samantha", "en_US")
    ]


def test_voices_are_the_english_voices_without_the_novelty_ones(mac):
    voices = engine(FakeSay()).voices()

    assert [v.key for v in voices] == [f"macos:{name}" for name in OFFERED]
    assert {v.name for v in voices}.isdisjoint(NOVELTY)
    assert {(v.engine, v.quality, v.num_speakers, v.installed) for v in voices} == {
        ("macos", "Standard", 1, True)
    }
    rows = {v.key: v for v in voices}
    assert (rows["macos:Daniel"].name, rows["macos:Daniel"].language) == ("Daniel", "en-GB")
    assert (rows["macos:Eddy (English (US))"].name, rows["macos:Karen"].language) == (
        "Eddy",
        "en-AU",
    )
    assert all(v.path is None and v.reason == "" for v in voices)


def test_every_novelty_voice_of_the_brief_is_skipped():
    assert {
        "Albert",
        "Bad News",
        "Bahh",
        "Bells",
        "Boing",
        "Bubbles",
        "Cellos",
        "Good News",
        "Jester",
        "Organ",
        "Superstar",
        "Trinoids",
        "Whisper",
        "Wobble",
        "Zarvox",
    } == NOVELTY
    listed = {v.name for v in parse_listing(LISTING)}
    assert NOVELTY <= listed  # every one is on a real Mac, so the filter is what hides them


def test_enhanced_and_premium_voices_list_with_their_tier(mac):
    voices = engine(FakeSay(TIERS)).voices()

    assert [(v.key, v.name, v.quality, v.language) for v in voices] == [
        ("macos:Ava (Premium)", "Ava", "Premium", "en-US"),
        ("macos:Samantha (Enhanced)", "Samantha", "Enhanced", "en-US"),
        ("macos:Daniel (Enhanced)", "Daniel", "Enhanced", "en-GB"),
        ("macos:Lee (Premium)", "Lee", "Premium", "en-AU"),
        ("macos:Fiona (Enhanced)", "Fiona", "Enhanced", "en-scotland"),
    ]


def test_the_listing_runs_once_with_the_exact_argv_and_a_minimal_environment(mac):
    say = FakeSay()
    made = engine(say)

    first, again = made.voices(), made.voices()

    assert first == again
    (proc,) = say.procs
    assert proc.args == [SAY, "--voice=?"]
    assert proc.kwargs["env"] == {"PATH": "/usr/bin:/bin"} == ENV
    assert proc.kwargs.get("shell", False) is False
    assert proc.timeouts == [LIST_TIMEOUT_S]


def test_a_failed_listing_raises_once_then_lists_nothing(mac):
    say = FakeSay(list_code=1, list_stderr=b"speech is broken\n")
    made = engine(say)

    with pytest.raises(EngineError, match=r"^say failed \(exit 1\): speech is broken$"):
        made.voices()
    assert made.voices() == []
    assert len(say.procs) == 1  # never again: every reading would wait for it


# --- availability ------------------------------------------------------------------------------


def test_available_needs_macos_and_an_executable_say(monkeypatch, tmp_path):
    fake = tmp_path / "say"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "platform", "darwin")

    missing = MacosEngine(say=tmp_path / "absent", popen=FakeSay())
    assert missing.available() is False
    assert missing.unavailable_reason == f"{tmp_path / 'absent'} not found"
    fake.chmod(0o700)
    assert MacosEngine(say=fake, popen=FakeSay()).available() is True

    monkeypatch.setattr(sys, "platform", "linux")
    elsewhere = MacosEngine(say=fake, popen=FakeSay())
    assert elsewhere.available() is False
    assert elsewhere.unavailable_reason == "macOS voices need macOS"


def test_a_missing_say_hides_the_engine_and_refuses_to_speak(mac, tmp_path):
    say = FakeSay()
    made = MacosEngine(say=tmp_path / "absent", popen=say)

    assert TtsService([made], tmp_path / "cache").voices() == []
    with pytest.raises(EngineUnavailable, match="absent not found"):
        made.synthesize(SCRIPT, SAMANTHA, OPTS, tmp_path / "out.wav")
    assert say.procs == []


def test_say_vanishing_after_the_check_is_engine_unavailable(mac, tmp_path):
    def gone(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    made = engine(FakeSay())
    made._popen = gone

    with pytest.raises(EngineUnavailable, match=r"^cannot run /usr/bin/say: "):
        made.voices()


# --- synthesis: argv, stdin, environment -------------------------------------------------------


def test_synthesis_argv_is_exact_and_carries_no_text(mac, tmp_path):
    say = FakeSay()

    synthesize(engine(say), tmp_path / "out.wav")

    (proc,) = say.synths
    out = proc.output()
    assert out is not None and out.name == "speech.wav"
    assert proc.args == [
        SAY,
        "--voice=Samantha",
        f"--output-file={out}",
        "--file-format=WAVE",
        "--data-format=LEI16@24000",
        "--input-file=-",
    ]
    assert proc.kwargs["env"] == {"PATH": "/usr/bin:/bin"}
    assert proc.kwargs.get("shell", False) is False
    assert proc.kwargs["stdin"] == subprocess.PIPE
    assert all("plants" not in arg for arg in proc.args)
    assert proc.input == b"Which gas do plants take in? [[slnc 700]] W. [[slnc 300]]"


def test_text_that_starts_with_a_dash_stays_on_stdin(mac, tmp_path):
    say = FakeSay()
    script = SpokenScript((Segment("-v Zarvox --output-file=/tmp/x -5 degrees", 0),))

    synthesize(engine(say), tmp_path / "out.wav", script)

    (proc,) = say.synths
    assert proc.args[1] == "--voice=Samantha"
    assert not any("Zarvox" in arg or "/tmp/x" in arg for arg in proc.args)
    assert proc.input == b"-v Zarvox --output-file=/tmp/x -5 degrees."


def test_pasted_embedded_commands_are_broken_so_say_reads_them_as_text(mac, tmp_path):
    script = SpokenScript((Segment("Read [[rate 900]] fast ]] and [[[slnc 9000]]]", 400),))

    text, _ = say_text(script)

    assert text == "Read [rate 900] fast ] and [slnc 9000]. [[slnc 400]]"
    assert text.count("[[") == text.count("]]") == 1  # only the engine's own pause


def test_each_segment_ends_as_a_sentence_and_pauses_become_slnc():
    script = SpokenScript(
        (
            Segment("Multiple choice.", 500),
            Segment("W.", 300),
            Segment("tidal motion of the Earth’s crust", 400),
            Segment("X.", 300),
            Segment("a question?", 0),
            Segment("“quoted”", 0),
        )
    )

    text, warnings = say_text(script)

    assert text == (
        "Multiple choice. [[slnc 500]] W. [[slnc 300]] tidal motion of the Earth’s crust. "
        "[[slnc 400]] X. [[slnc 300]] a question? “quoted”."
    )
    assert warnings == []


def test_each_choice_letter_reaches_say_with_its_pause_before_its_text():
    # Joined to its text ("Z. remnant magnetism"), Eddy, Grandpa, Rocko and Sandy (US) read "zero";
    # with the letter's [[slnc]] between them, all 26 English voices said W, X, Y, Z by name.
    raw = ROOT / "tests" / "fixtures" / "questions" / "01-earth-science-crustal-plates-mc.txt"
    questions = QuestionParser().parse(raw.read_text(encoding="utf-8"))
    script = ScriptNormalizer().to_script(questions, {}, OPTS)

    text, _ = say_text(script)

    for letter, words in [("W", "tidal motion"), ("X", "the pulling"), ("Y", "convection")]:
        assert f" {letter}. [[slnc {LETTER_PAUSE_MS}]] {words}" in text
    assert text.endswith(f" Z. [[slnc {LETTER_PAUSE_MS}]] remnant magnetism. [[slnc 400]]")


def test_overrides_say_their_respelling_and_ipa_only_words_are_reported():
    pharynx = Override("Pharynx", "ˈfæɹɪŋks", "respelling", respelling="FAR-ingks")
    trachea = Override("Trachea", "ˈtɹeɪkiə", "lexicon")
    script = SpokenScript((Segment("Pharynx and Trachea", 0, (pharynx, trachea)),))

    text, warnings = say_text(script)

    assert text == "far-ingks and Trachea."
    assert warnings == ["macOS cannot take IPA: 1 hard word uses the printed spelling (Trachea)"]
    made = MacosEngine(say=SAY, popen=FakeSay())
    assert made.script_warnings(script, SAMANTHA) == tuple(warnings)


@pytest.mark.parametrize(
    ("speed", "rate"), [(1.0, None), (2.0, "--rate=350"), (0.8, "--rate=140"), (3.0, "--rate=350")]
)
def test_speed_one_keeps_the_voice_rate_and_others_scale_175_wpm(mac, tmp_path, speed, rate):
    say = FakeSay()
    made = engine(say)

    synthesize(made, tmp_path / "out.wav", speed=speed)

    rates = [arg for arg in say.synths[0].args if arg.startswith("--rate")]
    assert rates == ([] if rate is None else [rate])
    assert DEFAULT_WPM == 175
    clamped = [w for w in made.last_warnings if "clamped" in w]
    assert clamped == (["macOS: speed 3 clamped to 2"] if speed == 3.0 else [])


@pytest.mark.parametrize("speed", [0.0, -1.0, float("nan"), float("inf")])
def test_a_speed_that_is_not_a_positive_number_is_refused(mac, tmp_path, speed):
    say = FakeSay()

    with pytest.raises(ValueError, match="speed must be a positive number"):
        synthesize(engine(say), tmp_path / "out.wav", speed=speed)
    assert say.synths == []


def test_a_speaker_id_is_ignored_with_a_note(mac, tmp_path):
    made = engine(FakeSay())

    synthesize(made, tmp_path / "out.wav", speaker_id=2)

    assert made.last_warnings == ["macOS: speaker 2 ignored; each voice has one speaker"]


@pytest.mark.parametrize(
    "stranger",
    [
        voice("Nobody"),  # never listed: say would read it with the default voice
        voice("Zarvox"),  # listed, but a novelty voice
        voice("Alice", language="it-IT"),  # listed, but not English
        dataclasses.replace(SAMANTHA, engine="piper"),
        dataclasses.replace(SAMANTHA, key="piper:Samantha"),
    ],
    ids=["unlisted", "novelty", "italian", "engine", "key"],
)
def test_only_an_enumerated_voice_is_ever_passed_to_say(mac, tmp_path, stranger):
    say = FakeSay()

    with pytest.raises(ValueError, match=r"^not a macOS voice: "):
        engine(say).synthesize(SCRIPT, stranger, OPTS, tmp_path / "out.wav")
    assert say.synths == []


# --- synthesis: the WAV and the temporary folder ------------------------------------------------


def test_the_wav_is_24_khz_16_bit_mono_and_audio_matches_it(mac, tmp_path):
    out = tmp_path / "out.wav"

    audio = synthesize(engine(FakeSay()), out)

    with wave.open(str(out), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24_000)
        frames = wav.readframes(wav.getnframes())
    assert frames == SPEECH
    assert (audio.wav_path, audio.sample_rate, audio.cache_hit) == (out, 24_000, False)
    assert audio.duration_s == pytest.approx(0.5)


def test_the_temporary_folder_is_private_and_removed_after_success(mac, tmp_path):
    say = FakeSay()

    synthesize(engine(say), tmp_path / "out.wav")

    (proc,) = say.synths
    assert proc.folder_mode == 0o700
    assert not proc.output().parent.exists()


@pytest.mark.parametrize(
    ("behavior", "message"),
    [
        ({"code": 1, "stderr": b"Opening output file failed: wht?\n"}, r"exit 1\): Opening output"),
        ({"code": 3}, r"^say failed \(exit 3\)$"),
        ({"frames": b""}, "produced no sound"),
        ({"frames": b"\x00\x00" * 4800}, "produced no sound"),  # digital silence: no speech
        ({"write": False}, "no readable audio"),
        ({"rate": 22_050}, "expected mono 16-bit 24000 Hz"),
        ({"channels": 2, "frames": SPEECH * 2}, "expected mono 16-bit 24000 Hz"),
    ],
    ids=["exit-1", "exit-3", "empty", "silent", "no-file", "rate", "stereo"],
)
def test_a_failed_render_raises_engine_error_and_removes_the_folder(
    mac, tmp_path, behavior, message
):
    say = FakeSay(**behavior)
    out = tmp_path / "out.wav"

    with pytest.raises(EngineError, match=message):
        synthesize(engine(say), out)

    (proc,) = say.synths
    assert not proc.output().parent.exists()
    assert not out.exists()


def test_a_render_past_its_timeout_is_killed_and_reported(mac, tmp_path, monkeypatch):
    say = FakeSay(hang="timeout")
    monkeypatch.setattr(macos, "SYNTH_TIMEOUT_S", 7.0)
    monkeypatch.setattr(macos, "SYNTH_S_PER_CHAR", 0.5)
    script = SpokenScript((Segment("W.", 0),))  # "W." on stdin: 2 characters

    with pytest.raises(EngineError, match=r"^macOS speech took longer than 8 s$"):
        synthesize(engine(say), tmp_path / "out.wav", script)

    (proc,) = say.synths
    assert proc.timeouts[0] == pytest.approx(8.0)
    assert say.kills == 1
    assert not proc.output().parent.exists()


def test_cancel_kills_the_running_say_and_the_reading_fails(mac, tmp_path):
    say = FakeSay(hang=True)
    made = engine(say)
    made.voices()  # the listing has run; only the render hangs
    failure: list[BaseException] = []

    def read() -> None:
        try:
            synthesize(made, tmp_path / "out.wav")
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(target=read)
    worker.start()
    assert say.started.wait(5)
    made.cancel()
    worker.join(5)

    assert not worker.is_alive()
    assert say.kills == 1
    assert len(failure) == 1 and isinstance(failure[0], EngineError)
    assert str(failure[0]) == "macOS speech was cancelled"
    assert not say.synths[0].output().parent.exists()
    made.cancel()  # nothing runs now: a no-op
    assert say.kills == 1


def test_an_interrupted_render_kills_its_child(mac, tmp_path):
    say = FakeSay()

    def interrupt(input=None, timeout=None):
        raise KeyboardInterrupt

    made = engine(say)
    made.voices()
    original = say.__call__

    def popen(argv, **kwargs):
        proc = original(argv, **kwargs)
        proc.communicate = interrupt
        return proc

    made._popen = popen
    with pytest.raises(KeyboardInterrupt):
        synthesize(made, tmp_path / "out.wav")

    assert say.kills == 1
    assert not say.synths[0].output().parent.exists()


# --- no download -------------------------------------------------------------------------------


def test_the_macos_engine_adds_no_download_and_no_lock_entry(tmp_path):
    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    settings = Settings(*(tmp_path / name for name in ("data", "cache", "voices", "models")))

    assert {asset["group"] for asset in lock["assets"]} <= set(prefetch.GROUPS)
    assert not any("macos" in json.dumps(asset).lower() for asset in lock["assets"])
    assert KEY not in prefetch.GROUPS and KEY not in prefetch.FETCHED
    assert KEY not in engine_catalog.SPECS
    assert engine_catalog.pinned(settings, KEY) == engine_catalog.Pinned((), "")
    # The first-launch plan, every group ready and room to spare: the lock alone sets its size.
    plan = prefetch.VoicePrefetch(
        settings,
        lock_path=ROOT / "assets.lock.json",
        ready=dict.fromkeys(prefetch.FETCHED, lambda: None),
        free_bytes=lambda _path: 1 << 60,
    ).plan()
    assert {asset.group for asset in plan.assets} <= set(prefetch.FETCHED)
    fetched = [asset for asset in lock["assets"] if asset["group"] in prefetch.FETCHED]
    assert plan.total_bytes == sum(asset["size"] for asset in fetched)


def test_the_macos_engine_needs_no_settings_and_no_files(mac):
    made = engine(FakeSay())

    assert not hasattr(made, "placeholder_voices")  # never a dimmed "not downloaded" row
    assert not hasattr(made, "load_hint")
    assert made.version.startswith("macos-say@")


# --- live --------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("CR_LIVE_SAY") != "1" or sys.platform != "darwin",
    reason="runs the real /usr/bin/say: set CR_LIVE_SAY=1 on a Mac",
)
def test_live_say_lists_english_voices_and_reads_a_choice(tmp_path):
    made = MacosEngine(say="/usr/bin/say")
    assert made.available()

    voices = made.voices()
    assert voices and all(v.language.startswith("en") for v in voices)
    picked = next((v for v in voices if v.name == "Samantha"), voices[0])
    script = SpokenScript((Segment("W.", 300), Segment("tidal motion", 0)))
    audio = made.synthesize(script, picked, OPTS, tmp_path / "live.wav")

    with wave.open(str(audio.wav_path), "rb") as wav:
        samples = array("h", wav.readframes(wav.getnframes()))  # little-endian, as on every Mac
        assert (wav.getnchannels(), wav.getframerate()) == (1, 24_000)
    assert audio.duration_s > 0.5 and max(map(abs, samples)) > 300
