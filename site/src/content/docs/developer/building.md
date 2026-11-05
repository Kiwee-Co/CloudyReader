---
title: 'Build the app'
description: 'Set up a checkout, run the make targets, work offline, and build the ad-hoc signed Cloudy Reader.app.'
sidebar:
  order: 11
---

This page covers a source checkout: the setup, every `make` target, offline builds, and `make app`.

The commands on this page are untested: CI does not run them.

## Check the prerequisites

| Tool | Why | Notes |
| --- | --- | --- |
| macOS on Apple Silicon | `make app` builds an arm64 bundle and refuses other CPUs. | On other Macs, the code falls back to Piper alone. CI does not test that. |
| Python 3.12 | The project pins `>=3.12,<3.13`. | `.python-version` holds `3.12`. |
| [uv](https://docs.astral.sh/uv/) | Manages the environment and the lock file. | `brew install uv`. CI uses uv 0.9.28. |
| GNU Make | Runs the targets. | The Makefile also works with the Make 3.81 that macOS ships. |
| Xcode command line tools | `make app` needs `codesign`. | `xcode-select --install`. |

## Set up a checkout

```bash
git clone https://github.com/Kiwee-Co/CloudyReader.git
cd CloudyReader
make setup
make doctor
```

`make setup` runs three steps. Each step records a stamp in `.cache/stamps/`, so a second run skips finished steps:

1. `deps` runs `uv sync --frozen --inexact`. This builds `.venv` from `uv.lock`.
2. `models` fetches the scispaCy model `en_ner_craft_md` and installs it into `.venv`. The lock file does not hold it.
3. `voices` fetches the five Piper voices into `.data/voices`.

`make doctor` prints one line per item and the exact fix for each missing one. It exits 1 when a required item is missing. It changes nothing.

Every download goes through `scripts/fetch_assets.py`. The script reads `assets.lock.json`. It saves each file in a new temporary folder and checks the size and the SHA-256 value. Only then does it move the file into place.

## Know the targets

Run `make help` to print this list with the variables.

| Target | What it does |
| --- | --- |
| `setup` | `deps`, then `models`, then `voices`. Skips finished steps. |
| `deps` | Sync `.venv` to `uv.lock`. |
| `lock` | Re-resolve `uv.lock` from `pyproject.toml`. Needs the network unless `OFFLINE=1`. |
| `models` | Fetch the scispaCy model and install it into `.venv`. |
| `voices` | Fetch the Piper voices listed in `VOICES` into `.data/voices`. |
| `kokoro` | Apple Silicon only. Sync the `kokoro` extra and fetch the pinned Kokoro files. |
| `doctor` | Read-only health report. |
| `run` | Start the app. |
| `test` | Run the gate tests with the coverage floor. |
| `test-fast` | Run the quick tests. No models, no network. |
| `check` | `ruff check` and `ruff format --check`. |
| `fmt` | `ruff format` and `ruff check --fix`. |
| `precommit` | `pre-commit run -a`, or print how to install it. |
| `ci` | The commit gate: `check`, then `test`, then `precommit`. |
| `app` | Build `dist/Cloudy Reader.app`. |
| `icons` | Regenerate the four icon candidates and `assets/icons/preview.png`. |
| `open-icons` | Open `assets/icons/preview.png`. |
| `samples` | Extract NSB sample PDFs to `.data/samples`. Needs `pdftotext` and a source folder: run `CLOUDYREADER_SAMPLES_SRC=<pdf folder> make samples`. Without a source, it exits with status 2 and a message. |
| `smoke-live` | Live PubChem and UniProt check. Never part of `ci`. |
| `smoke-voices` | Live check of the voice download, about 0.55 MB. Never part of `ci`. |
| `clean` | Remove caches and build artifacts. Never touches `.data/` or `.venv/`. |
| `clean-app` | Remove only `dist/Cloudy Reader.app` and `build/`. |
| `clean-all` | `clean`, plus `.venv` and `.cache`. Needs `CONFIRM=yes`. Never touches `.data/`. |

`run`, `test`, `test-fast`, `samples`, `smoke-live`, and `app` set `CLOUDYREADER_DATA_DIR` to `.data` in the checkout. `make run` does not enable offline mode in the app. It only keeps `uv` off the network.

## Override the variables

Pass a variable on the command line, as in `make voices VOICES="en_US-amy-medium"`.

| Variable | Default | Effect |
| --- | --- | --- |
| `UV` | `uv` | The uv executable. |
| `COV_MIN` | `75` | The coverage floor for `make test`, in percent. |
| `VOICES` | The five pinned Piper ids | The Piper voices for `make voices`. Ids come from `assets.lock.json`. |
| `OFFLINE` | `0` | `1` makes uv use `--offline` and makes the fetcher refuse downloads. |
| `CONFIRM` | `no` | `yes` lets `clean-all` delete `.venv` and `.cache`. |
| `ONLINE` | `0` | `1` makes `make doctor` also check PubChem and UniProt. |
| `VERIFY` | `0` | `1` makes `make doctor` check the SHA-256 value of each asset. |
| `APP_NAME` | `Cloudy Reader` | The bundle name for `make app`. |
| `ICON` | Empty | An icon folder under `assets/icons/`. Empty reads `assets/icons/default.txt`. |
| `KOKORO` | `auto` | `auto`, `0`, or `1`. Whether `make app` bundles Kokoro. |
| `OUT` | `dist` | The output folder for `make app`. |

## Work offline

`run`, `test`, `test-fast`, `check`, and `fmt` never use the network. They call `uv run --frozen --offline`.

For `setup`, `deps`, `models`, `voices`, `kokoro`, and `lock`, add `OFFLINE=1`. Then uv uses only its cache in `.cache/uv`. The fetcher accepts only files that are already in `.data`. Warm the cache once with the network on.

```bash
make setup            # network on, once
make setup OFFLINE=1  # later, no network
```

The script `scripts/build_app.sh` never uses the network. It runs PyInstaller with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. The prerequisites of `make app` use the network only when their stamps are stale. Pass `OFFLINE=1` to forbid that.

## Lock the dependencies safely

`UV_INDEX_URL` and `UV_DEFAULT_INDEX` in your shell can rewrite `uv.lock`. The lock then points every package at a private index. CI and other contributors cannot install from it. Clear both variables when you lock, and name the public index:

```bash
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --default-index https://pypi.org/simple
```

Check the diff of `uv.lock` before you commit. Every `registry` URL must name `https://pypi.org/simple`. CI also fails when the lock names a host other than `pypi.org`, `files.pythonhosted.org`, or `github.com`.

## Run the app from source

```bash
make run
```

For options, call the environment directly. The `--self-test` option needs no window:

```bash
CLOUDYREADER_DATA_DIR=.data .venv/bin/python -m cloudyreader --self-test
```

See [Settings and command line](/manual/settings-and-cli/) for every option.

## Add the Kokoro engine

```bash
make kokoro
```

The target stops with an error on a Mac that is not arm64. It syncs the `kokoro` extra. The extra holds `mlx`, `mlx-audio`, `misaki`, `en-core-web-sm`, `espeakng-loader`, `phonemizer-fork`, and `num2words`. Then the target fetches the Kokoro files from `assets.lock.json`. The files total about 342 MB.

## Build the app

```bash
make setup   # voices must exist in .data/voices
make app
```

`make app` first runs `deps`, `models`, and the `packaging` dependency group. Then `scripts/build_app.sh` does the work. It stops at the first error.

1. **Preflight.** It needs macOS, arm64, a valid `APP_NAME`, `.venv`, `codesign`, the scispaCy model, PyInstaller, and at least one Piper voice in `.data/voices`.
2. **Inputs.** It picks the icon from `ICON` or `assets/icons/default.txt`. It decides about Kokoro. `auto` bundles Kokoro only when the extra is installed and every pinned file has its pinned size. `1` demands it. `0` skips it.
3. **PyInstaller.** It builds a one-folder bundle from `packaging/CloudyReader.spec` in `build/dist/`. The entry point is `packaging/launcher.py`.
4. **Assets.** It copies the Piper voices, the Kokoro folder (if used), and `assets.lock.json` into `Contents/Resources/assets`.
5. **Info.plist check.** It lints the file. It requires an existing icon, a version, and `LSMinimumSystemVersion`.
6. **Ad-hoc signing.** It runs `codesign --force --deep -s -`. This uses no Developer ID and skips notarization.
7. **Install.** It moves a previous `dist/Cloudy Reader.app` into `build/trash.*`. It deletes nothing. Then it moves the new app into `dist/` and runs `codesign --verify --deep --strict`.
8. **Self-test, twice.** It runs the bundle with `--self-test`, offline and headless, against a fresh data folder. The second run exercises the links from the first.
9. **Summary.** It prints the size, the voices, the Kokoro state, and the largest components.

Each self-test run has a time limit of `SELFTEST_TIMEOUT` seconds. The default is 300. Logs go to `build/selftest-1.log` and `build/selftest-2.log`. `make clean-app` frees `build/` and the app in `dist/`.

### Know what the bundle holds

| Item | Value |
| --- | --- |
| Bundle identifier | `com.cloudyreader.CloudyReader` |
| Version keys | The `version` from `pyproject.toml` |
| `LSMinimumSystemVersion` | The newest macOS minimum among the bundled binaries, never below 11.0. `packaging/min_macos.py` reads the Mach-O load commands. |
| `LSApplicationCategoryType` | `public.app-category.education` |
| Copyright | `Copyright © 2026 the Cloudy Reader authors.` |
| Architecture | arm64 |

The spec excludes `scispacy`, `sklearn`, and `nmslib` because the model loads without them. Without Kokoro, it also excludes `mlx`, `mlx_audio`, `misaki`, and `scipy`.

### Choose an icon

Four candidates live in `assets/icons/`: `cloud-atom`, `cloud-book`, `cloud-voice`, and `cloud-wave`. The file `assets/icons/default.txt` names the default, `cloud-atom`.

```bash
ICON=cloud-wave make app
```

`make icons` regenerates the candidates and the preview image.

## Fix build errors

| Message starts with | Fix |
| --- | --- |
| `build_app: error: no .venv` | Run `make deps`. |
| `no Piper voice (.onnx + .onnx.json) in …` | Run `make voices`. |
| `scispaCy model en_ner_craft_md is not installed` | Run `make models`. |
| `codesign not found` | Run `xcode-select --install`. |
| `KOKORO=1 but …` | Run `make kokoro`, or build with `KOKORO=auto` or `KOKORO=0`. |
| `self-test run … timed out` | Read `build/selftest-N.log`. Raise `SELFTEST_TIMEOUT` on a slow Mac. |
