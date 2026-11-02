"""AfplayPlayer: state machine over a fake `subprocess.Popen`; no real audio ever plays."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

from cloudyreader.audio import AFPLAY, AfplayPlayer, AudioError
from cloudyreader.models import Audio

RATE = 22050


class FakeProc:
    """Stands in for the `Popen` of afplay: alive until it ends, is terminated or is killed."""

    def __init__(self, args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.returncode: int | None = None
        self.calls: list[str] = []
        self.ignore_terminate = False

    @property
    def alive(self) -> bool:
        return self.returncode is None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.calls.append("terminate")
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.calls.append("kill")
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append(f"wait({timeout})")
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode


@pytest.fixture
def procs(monkeypatch) -> list[FakeProc]:
    """Every process the player starts. Patches `subprocess.Popen`, so nothing real can run."""
    started: list[FakeProc] = []

    def fake_popen(args, **kwargs) -> FakeProc:
        time.sleep(0.001)  # widens the window a missing lock would leave open
        proc = FakeProc(args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return started


def write_wav(path: Path, *, seconds: float = 0.1) -> Audio:
    frames = int(RATE * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(b"\x00\x00" * frames)
    return Audio(path, RATE, frames / RATE, False)


@pytest.fixture
def audio(tmp_path: Path) -> Audio:
    return write_wav(tmp_path / "clip.wav")


def test_a_new_player_is_idle_and_has_nothing_to_replay(procs):
    player = AfplayPlayer()

    assert player.is_playing is False
    assert player.replay() is False
    assert procs == []


def test_play_runs_afplay_on_the_wav_without_a_shell(procs, audio):
    AfplayPlayer().play(audio)

    (proc,) = procs
    assert AFPLAY == "/usr/bin/afplay"
    assert proc.args == [AFPLAY, str(audio.wav_path)]
    assert not proc.kwargs.get("shell")


def test_play_does_not_wait_for_the_clip(procs, audio):
    AfplayPlayer().play(audio)

    assert procs[0].calls == []
    assert procs[0].alive


def test_play_hands_afplay_an_absolute_path_so_a_leading_dash_is_no_option(
    procs, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "-v.wav")

    AfplayPlayer().play(Audio(Path("-v.wav"), RATE, 0.1, False))

    assert procs[0].args == [AFPLAY, str(tmp_path / "-v.wav")]


def test_is_playing_follows_the_process(procs, audio):
    player = AfplayPlayer()
    player.play(audio)

    assert player.is_playing is True

    procs[0].returncode = 0  # the clip ended on its own

    assert player.is_playing is False


def test_stop_terminates_then_waits_up_to_two_seconds(procs, audio):
    player = AfplayPlayer()
    player.play(audio)

    player.stop()

    assert procs[0].calls == ["terminate", "wait(2)"]
    assert player.is_playing is False


def test_stop_kills_only_when_terminate_hangs(procs, audio):
    player = AfplayPlayer()
    player.play(audio)
    procs[0].ignore_terminate = True

    player.stop()

    assert procs[0].calls == ["terminate", "wait(2)", "kill", "wait(2)"]
    assert player.is_playing is False


def test_stop_sends_no_signal_to_a_clip_that_already_ended(procs, audio):
    player = AfplayPlayer()
    player.play(audio)
    procs[0].returncode = 0

    player.stop()

    assert procs[0].calls == []


def test_stop_while_idle_is_harmless(procs):
    player = AfplayPlayer()

    player.stop()
    player.stop()

    assert procs == [] and player.is_playing is False


def test_play_stops_the_running_clip_before_starting_the_next(procs, audio):
    player = AfplayPlayer()
    player.play(audio)

    player.play(audio)

    first, second = procs
    assert first.calls == ["terminate", "wait(2)"] and not first.alive
    assert second.alive and player.is_playing is True


def test_replay_plays_the_last_audio_again(procs, audio):
    player = AfplayPlayer()
    player.play(audio)
    procs[0].returncode = 0

    assert player.replay() is True

    assert len(procs) == 2
    assert procs[1].args == procs[0].args
    assert player.is_playing is True


def test_replay_works_after_stop(procs, audio):
    player = AfplayPlayer()
    player.play(audio)
    player.stop()

    assert player.replay() is True
    assert len(procs) == 2 and procs[1].alive


def test_replay_replays_the_most_recent_audio(procs, tmp_path):
    first = write_wav(tmp_path / "a.wav")
    second = write_wav(tmp_path / "b.wav")
    player = AfplayPlayer()
    player.play(first)
    player.play(second)

    player.replay()

    assert procs[-1].args == [AFPLAY, str(second.wav_path)]


def test_replay_while_playing_restarts_the_clip(procs, audio):
    player = AfplayPlayer()
    player.play(audio)

    assert player.replay() is True

    assert not procs[0].alive and procs[1].alive


def test_a_missing_wav_raises_a_clear_error_and_leaves_the_running_clip_alone(
    procs, audio, tmp_path
):
    player = AfplayPlayer()
    player.play(audio)

    with pytest.raises(FileNotFoundError, match="ghost.wav"):
        player.play(Audio(tmp_path / "ghost.wav", RATE, 1.0, False))

    assert len(procs) == 1 and procs[0].alive and procs[0].calls == []
    assert player.replay() is True  # the clip that did play, not the missing one
    assert procs[-1].args == [AFPLAY, str(audio.wav_path)]


def test_a_failed_first_play_leaves_nothing_to_replay(procs, tmp_path):
    player = AfplayPlayer()

    with pytest.raises(FileNotFoundError):
        player.play(Audio(tmp_path / "ghost.wav", RATE, 1.0, False))

    assert player.replay() is False
    assert player.is_playing is False
    assert procs == []


def test_afplay_that_cannot_start_is_reported_clearly(monkeypatch, audio):
    def refuse(args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", AFPLAY)

    monkeypatch.setattr(subprocess, "Popen", refuse)
    player = AfplayPlayer()

    with pytest.raises(AudioError, match="afplay"):
        player.play(audio)

    assert player.replay() is False
    assert player.is_playing is False


def test_concurrent_plays_never_leave_two_clips_running(procs, audio):
    player = AfplayPlayer()
    threads = [threading.Thread(target=player.play, args=(audio,)) for _ in range(20)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(procs) == 20
    assert sum(proc.alive for proc in procs) == 1
    assert player.is_playing is True


def test_audio_error_is_a_runtime_error():
    assert issubclass(AudioError, RuntimeError)


@pytest.mark.skipif(sys.platform != "darwin", reason="afplay ships with macOS only")
def test_afplay_exists_where_the_app_runs():
    assert Path(AFPLAY).is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="afinfo ships with macOS only")
def test_coreaudio_reads_the_wav_format_the_engines_write(tmp_path):
    clip = write_wav(tmp_path / "clip.wav")

    result = subprocess.run(
        ["/usr/bin/afinfo", str(clip.wav_path)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "22050 Hz" in result.stdout and "Int16" in result.stdout
