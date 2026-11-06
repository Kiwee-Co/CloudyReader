"""Packaging: every build carries the letter clips where the frozen app reads them."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudyreader.engines.letter_clips import FOLDER, MANIFEST
from tests.packaging.test_build_app import bash_fn
from tests.packaging.test_build_engines import spec
from tests.packaging.test_release import bundle, root  # noqa: F401 (root: a fixture)

ROOT = Path(__file__).resolve().parents[2]
CLIPS = ROOT / "cloudyreader" / "engines" / FOLDER
BUNDLED = f"cloudyreader/engines/{FOLDER}"  # under Contents/Resources: letter_clips.clips_dir()


def clip_files() -> list[Path]:
    return sorted(path for path in CLIPS.rglob("*") if path.is_file())


@pytest.mark.parametrize(
    "env",
    [
        {},  # a lean dev build
        {"CR_KOKORO": "1"},
        {"CR_KOKORO": "1", "CR_ENGINES": "1"},  # a release build
    ],
)
def test_every_build_ships_each_clip_and_the_manifest(monkeypatch, env):
    seen = spec(monkeypatch, **env)

    shipped = [entry for entry in seen["Analysis"]["datas"] if entry[1].startswith(BUNDLED)]
    want = [(str(path), path.parent.relative_to(ROOT).as_posix()) for path in clip_files()]
    assert shipped == want
    assert len(want) == 13 and (str(CLIPS / MANIFEST), BUNDLED) in want  # 12 clips, 1 manifest
    assert all(not dest.startswith("/") for _, dest in want)  # no build path inside the app


def test_the_voice_audit_passes_a_bundle_with_the_clips(root):  # noqa: F811
    rels = [f"Contents/Resources/{path.relative_to(ROOT).as_posix()}" for path in clip_files()]

    result = bash_fn(root, 'audit_voices "$1"', str(bundle(root, *rels)))

    assert result.returncode == 0, result.stderr
