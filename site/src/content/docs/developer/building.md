---
title: Build from source
description: 'Set up a source checkout of Cloudy Reader, run the make targets, and build the app or the release zip on a Mac with Apple silicon.'
sidebar:
  order: 1
---

This page covers a source checkout: the setup, every `make` target, offline builds, the app bundle, and the release zip. To use the app without building it, see [Download Cloudy Reader](/download/).

## Prerequisites

Every item except the last is required to set up and build.

- **A Mac with Apple silicon.** `make kokoro`, `make app`, and `make release` stop on any other CPU.
- **Python 3.12.** The project pins `>=3.12,<3.13`. The file `.python-version` holds `3.12`.
- **uv.** It manages the environment and the lock file. Install it with `brew install uv`. CI uses uv 0.9.28.
- **GNU Make.** The Makefile also works with the Make 3.81 that macOS ships.
- **Xcode command line tools.** `make app` and `make release` call `codesign`. Install the tools with `xcode-select --install`.
- **pre-commit, ShellCheck, Prettier, and markdownlint.** `make precommit` and `make ci` run them as hooks from your `PATH`.

Install the four hook tools once. The `npm` command needs Node:

```bash
uv tool install pre-commit
uv tool install shellcheck-py
npm install --global prettier markdownlint-cli
```

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
3. `voices` fetches the Piper voices in `VOICES` into `.data/voices`.

A target that you name on the command line, such as `make deps`, always runs again.

`make doctor` prints one line per item: `ok`, `info`, or `MISS`. A `MISS` line carries the exact fix. The target exits 1 when a required item is missing, and it changes nothing. It checks:

- The CPU, macOS, uv, and the Python in `.venv`.
- The Java runtime and the jar for OPSIN, the bundled espeak-ng, and `afplay`.
- The model files, the voice files, and, on Apple silicon, the Kokoro files and package.

Every model and voice download goes through `scripts/fetch_assets.py`, which reads `assets.lock.json`. It saves each file in a fresh temporary folder and checks the size and the SHA-256 value. Only then does it move the file into place.

## Make targets

Run `make help` to print the targets and the variables.

Seven targets set `CLOUDYREADER_DATA_DIR` to `.data` in the checkout: `run`, `test`, `test-fast`, `samples`, `smoke-live`, `app`, and `release`. `make run` does not enable offline mode in the app. It only keeps `uv` off the network.

### Set up and run

These targets prepare the checkout and start the app.

| Target   | What it does                                                                      |
| -------- | --------------------------------------------------------------------------------- |
| `setup`  | Run `deps`, `models`, and `voices`. Skip finished steps.                          |
| `deps`   | Sync `.venv` to `uv.lock`.                                                        |
| `lock`   | Re-resolve `uv.lock` from `pyproject.toml`. Needs the network unless `OFFLINE=1`. |
| `models` | Fetch the scispaCy model and install it into `.venv`.                             |
| `voices` | Fetch the Piper voices in `VOICES` into `.data/voices`.                           |
| `kokoro` | Apple silicon only. Sync the `kokoro` extra and fetch the pinned Kokoro files.    |
| `doctor` | Print a read-only health report.                                                  |
| `run`    | Start the app.                                                                    |

### Test and check

These targets run the gates. [Test and CI](/developer/testing/) explains what each gate checks.

| Target      | What it does                                                                         |
| ----------- | ------------------------------------------------------------------------------------ |
| `test`      | Run the gate tests with the coverage floor.                                          |
| `test-fast` | Run the quick tests. No models, no network.                                          |
| `check`     | Run `ruff check` and `ruff format --check`.                                          |
| `fmt`       | Run `ruff format` and `ruff check --fix`.                                            |
| `precommit` | Run `pre-commit run -a`, or print how to install it.                                 |
| `guards`    | Run the policy guards: vendor domain, lock hosts, disk paths, and workflow triggers. |
| `ci`        | Run the commit gate: `guards`, `check`, `test`, then `precommit`.                    |

`precommit` needs `shellcheck`, `prettier`, and `markdownlint` on your `PATH`. `guards` needs only `python3` and `git`.

### Build

These targets build the app and the icon files.

| Target       | What it does                                                                                |
| ------------ | ------------------------------------------------------------------------------------------- |
| `app`        | Build `dist/Cloudy Reader.app`, ad-hoc signed. Takes `BUNDLE_VOICES`, `KOKORO`, and `ICON`. |
| `release`    | Build the lean app and zip it with its SHA-256 in `dist/`. Takes `VERSION`. Never uploads.  |
| `icons`      | Regenerate the four icon candidates and `assets/icons/preview.png`.                         |
| `open-icons` | Open `assets/icons/preview.png`.                                                            |

### Live checks and samples

These targets need the network or files that you supply.

| Target         | What it does                                                                            |
| -------------- | --------------------------------------------------------------------------------------- |
| `samples`      | Extract sample-question PDFs to `.data/samples`. Needs `pdftotext` and a source folder. |
| `smoke-live`   | Check PubChem and UniProt live. Never part of `ci`.                                     |
| `smoke-voices` | Check the voice download live, about 0.55 MB. Never part of `ci`.                       |

Pass the source folder to `samples` in the environment:

```bash
CLOUDYREADER_SAMPLES_SRC=<pdf folder> make samples
```

Without a source, `make samples` exits with status 2 and a message.

### Clean up

These targets remove generated files.

| Target      | What it does                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------------ |
| `clean`     | Remove caches and build artifacts, including `dist/` and `build/`. Never touches `.data/` or `.venv/`. |
| `clean-app` | Remove only `dist/Cloudy Reader.app` and `build/`.                                                     |
| `clean-all` | Run `clean`, then remove `.venv` and `.cache`. Needs `CONFIRM=yes`. Never touches `.data/`.            |

## Variables

Pass a variable on the command line, as in `make voices VOICES="en_US-amy-medium"`. `make help` prints the variables with their defaults.

| Variable        | Default                       | Effect                                                                               |
| --------------- | ----------------------------- | ------------------------------------------------------------------------------------ |
| `UV`            | `uv`                          | The uv executable.                                                                   |
| `COV_MIN`       | `75`                          | The coverage floor for `make test`, in percent.                                      |
| `VOICES`        | The pinned Piper ids          | The Piper ids for `make voices` and `make doctor`. Ids come from `assets.lock.json`. |
| `OFFLINE`       | `0`                           | `1` makes uv use `--offline` and makes the fetcher refuse downloads.                 |
| `CONFIRM`       | `no`                          | `yes` lets `clean-all` delete `.venv` and `.cache`.                                  |
| `ONLINE`        | `0`                           | `1` makes `make doctor` also check that PubChem and UniProt answer.                  |
| `VERIFY`        | `0`                           | `1` makes `make doctor` check the SHA-256 value of each asset.                       |
| `APP_NAME`      | `Cloudy Reader`               | The bundle name for `make app` and `make release`.                                   |
| `ICON`          | Empty                         | An icon folder under `assets/icons/`. Empty reads `assets/icons/default.txt`.        |
| `KOKORO`        | `auto`                        | `auto`, `0`, or `1`. Whether `make app` bundles Kokoro.                              |
| `BUNDLE_VOICES` | `1`                           | `1` bundles the voices and the engine models. `0` builds a lean app.                 |
| `OUT`           | `dist`                        | The output folder for `make app` and `make release`.                                 |
| `VERSION`       | `version` in `pyproject.toml` | The version that `make release` checks and puts in the zip name.                     |

`scripts/build_app.sh` also reads `SELFTEST_TIMEOUT` from the environment. It is the time limit of each self-test run in whole seconds, and it defaults to 300:

```bash
SELFTEST_TIMEOUT=600 make app
```

## Work offline

`run`, `test`, `test-fast`, `check`, and `fmt` never use the network. They call `uv run --frozen --offline`.

For `setup`, `deps`, `models`, `voices`, `kokoro`, and `lock`, add `OFFLINE=1`. Then uv uses only its cache in `.cache/uv`. The fetcher accepts only files that are already in `.data`. Warm the cache once with the network on.

```bash
make setup            # network on, once
make setup OFFLINE=1  # later, no network
```

The script `scripts/build_app.sh` never uses the network. It runs PyInstaller with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. The prerequisites of `make app` use the network only when their stamps are stale. Pass `OFFLINE=1` to forbid that. `make release` passes `OFFLINE=1` to `make app` itself.

## Lock the dependencies safely

`UV_INDEX_URL` and `UV_DEFAULT_INDEX` in your shell can rewrite `uv.lock`. The lock then points every package at a private index. CI and other contributors cannot install from it. Clear both variables when you lock, and name the public index:

```bash
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --default-index https://pypi.org/simple
```

Check the diff of `uv.lock` before you commit. Every `registry` URL must name `https://pypi.org/simple`. CI also fails when the lock names a host other than `pypi.org`, `files.pythonhosted.org`, or `github.com`. It fails too when `uv lock --check` finds the lock out of date.

## Run from source

```bash
make run
```

`make run` takes no options. To pass an option, run the module from `.venv` yourself. This example runs the self-test, which needs no window:

```bash
CLOUDYREADER_DATA_DIR=.data .venv/bin/python -m cloudyreader --self-test
```

See [Command line](/manual/reference/command-line/) for every option.

### Source run and release app

A source run and the release app differ in these ways:

| Item               | Source run                                                                         | Release app                                                    |
| ------------------ | ---------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Data folder        | `make run` uses `.data` in the checkout.                                           | `~/Library/Application Support/cloudyreader`                   |
| Version            | `dev`, when the package metadata is missing.                                       | The bundled package metadata.                                  |
| Voices             | The files from `make voices` and `make kokoro`. The app downloads what is missing. | None are bundled. The app downloads every missing pinned file. |
| `assets.lock.json` | The copy in the checkout.                                                          | The copy in the bundle.                                        |
| Kokoro             | Needs `make kokoro`.                                                               | Always included (`KOKORO=1`).                                  |
| scispaCy model     | Needs `make models`. Without it, name detection uses regular expressions only.     | Bundled.                                                       |
| macOS minimum      | None in `Info.plist`. The installed wheels decide.                                 | `LSMinimumSystemVersion`, computed at build time.              |

`CLOUDYREADER_DATA_DIR` overrides the data folder in both. A plain `python -m cloudyreader` uses the folder in the right column.

## Add the Kokoro voice engine

The app always registers the Piper voice engine. It registers the Kokoro voice engine only on Apple silicon.

```bash
make kokoro
```

The target stops with an error on a Mac that is not arm64. It syncs the `kokoro` extra. The extra holds `mlx`, `mlx-audio`, `misaki`, `en-core-web-sm`, `espeakng-loader`, `phonemizer-fork`, and `num2words`. Then the target fetches the Kokoro files from `assets.lock.json`.

## Build the app

```bash
make setup   # the voices must exist in .data/voices
make app
```

`make app` builds a self-contained app: it copies the Piper voices and, when Kokoro is included, the Kokoro model folder into the bundle. Pass `BUNDLE_VOICES=0` for a lean app, which holds no voice and downloads them at first launch.

`make app` first runs `deps`, `models`, and the `packaging` dependency group. Then `scripts/build_app.sh` does the work. It stops at the first error.

1. **Preflight.** It needs macOS, arm64, a valid `APP_NAME`, a whole-number `SELFTEST_TIMEOUT`, `.venv`, `codesign`, the scispaCy model, PyInstaller, and at least one Piper voice in `.data/voices`.
2. **Inputs.** It picks the icon from `ICON` or `assets/icons/default.txt`. It checks `BUNDLE_VOICES`. It decides about Kokoro: `auto` bundles it only when the extra is installed and every pinned file has its pinned size. `1` demands it. `0` skips it.
3. **PyInstaller.** It builds a one-folder bundle from `packaging/CloudyReader.spec` in `build/dist/`. The entry point is `packaging/launcher.py`. The log is `build/pyinstaller.log`.
4. **Assets.** It copies `assets.lock.json` into `Contents/Resources/assets`. With `BUNDLE_VOICES=1` it also copies the Piper voices and the Kokoro folder, if used.
5. **Info.plist check.** It lints the file. It requires an existing icon, a version, and `LSMinimumSystemVersion`.
6. **Voice audit.** With `BUNDLE_VOICES=0`, the build fails when the bundle holds a voice or model file. Piper's own `piper/hebrew/nakdimon.onnx` and `piper/tashkeel/model.onnx` are allowed.
7. **Ad-hoc signing.** It runs `codesign --force --deep -s -`. This uses no Developer ID and skips notarization.
8. **Install.** It moves a previous `dist/Cloudy Reader.app` into `build/trash.*`. It deletes nothing. Then it moves the app into `dist/` and runs `codesign --verify --deep --strict`.
9. **Self-test.** It runs the bundle with `--self-test`, offline and headless, twice on one data folder. With `BUNDLE_VOICES=0`, it links the host's voices and Kokoro model into that folder first. It then runs a third time on an empty folder. That run must exit 2 with `FAIL: no Piper voice installed` and no traceback.
10. **Summary.** It prints the size, the voices, the Kokoro state, and the ten largest components.

Each self-test run has a time limit of `SELFTEST_TIMEOUT` seconds. Logs go to `build/selftest-1.log` and `build/selftest-2.log`. With `BUNDLE_VOICES=0`, the third run logs to `build/selftest-no-voice.log`. `make clean-app` frees `build/` and the app in `dist/`.

### What the bundle holds

The bundle carries these values:

| Item                        | Value                                                                                    |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| Bundle identifier           | `com.cloudyreader.CloudyReader`                                                          |
| Version keys                | `CFBundleShortVersionString` and `CFBundleVersion` hold `version` from `pyproject.toml`. |
| `LSMinimumSystemVersion`    | The newest macOS minimum among the bundled binaries, never below 11.0.                   |
| `LSApplicationCategoryType` | `public.app-category.education`                                                          |
| Copyright                   | `Copyright © 2026 the Cloudy Reader authors.`                                            |
| Architecture                | arm64                                                                                    |

`packaging/min_macos.py` reads the Mach-O load commands of the bundled files. The spec excludes `scispacy`, `sklearn`, and `nmslib` because the model loads without them. Without Kokoro, it also excludes `mlx`, `mlx_audio`, `misaki`, and `scipy`.

### Choose an icon

Four candidates live in `assets/icons/`: `cloud-atom`, `cloud-book`, `cloud-voice`, and `cloud-wave`. The file `assets/icons/default.txt` names the default, `cloud-atom`.

```bash
ICON=cloud-wave make app
```

`make icons` regenerates the candidates and the preview image. `make release` always uses `cloud-atom`.

## Build the release zip

`make release` builds the zip that a GitHub release carries. The zip holds a lean app: no voice files and no engine models. The app downloads them at first launch. `make release` never uploads anything.

Set the version in every place that [Change the version](/developer/contributing/#change-the-version) lists. Then run the sync step, so that `.venv` knows the version, and build. This example builds version REL-VERSION:

```bash
make .cache/stamps/packaging kokoro
make release VERSION=REL-VERSION
```

The sync step needs the network and the public package index. `VERSION` defaults to `version` in `pyproject.toml`.

`make release` runs three commands in order:

1. `scripts/build_app.sh release-preflight` makes two checks. `VERSION` must look like `1.2.3`. The `cloudyreader` package metadata in `.venv` must say `VERSION`, because PyInstaller bundles that metadata and the About box and `--version` read it. On a mismatch the build stops and names the sync step.
2. `make app BUNDLE_VOICES=0 OFFLINE=1 ICON=cloud-atom KOKORO=1` builds the lean app with every check from [Build the app](#build-the-app).
3. `scripts/build_app.sh release` zips the app and checks the zip.

The last command works in this order:

- It moves an older zip and checksum with the same names into `build/trash.*`.
- `ditto -c -k --keepParent --norsrc --noextattr` makes the zip. The command fails when the zip holds `__MACOSX`, `.DS_Store`, or `._` files.
- It writes the SHA-256 beside the zip and checks the zip against it.
- It extracts the zip and checks the extracted copy. The copy must pass `codesign --verify --deep --strict`, carry `VERSION` in `CFBundleShortVersionString`, print `Cloudy Reader <VERSION>` for `--version`, pass the voice audit, and pass the self-test.

The release step leaves these files in `dist/`:

- `Cloudy-Reader-<VERSION>-macos-arm64.zip`. Spaces in `APP_NAME` become hyphens.
- `Cloudy-Reader-<VERSION>-macos-arm64.zip.sha256`. It holds the hash, two spaces, and the file name.
- `Cloudy Reader.app`, the lean app.

The `.sha256` file names the zip without a folder. [Download Cloudy Reader](/download/) shows how to check a download.

The app in the zip is ad-hoc signed and not notarized. See [Security and code signing](/about/security/) for what that means for users.

## Fix build errors

The script prints `build_app: error:` before each message. The table lists the text after it.

| Message starts with                               | Fix                                                                                      |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `no .venv`                                        | Run `make deps`.                                                                         |
| `no Piper voice (.onnx + .onnx.json) in`          | Run `make voices`.                                                                       |
| `scispaCy model en_ner_craft_md is not installed` | Run `make models`.                                                                       |
| `codesign not found`                              | Run `xcode-select --install`.                                                            |
| `KOKORO=1 but`                                    | Run `make kokoro`. For `make app`, you can pass `KOKORO=auto` or `KOKORO=0` instead.     |
| `selftest-1 timed out after`                      | Read the log that the message names in `build/`. Raise `SELFTEST_TIMEOUT` on a slow Mac. |
| `self-test run 1 exited`                          | Read `build/selftest-1.log`. Run 2 uses `build/selftest-2.log`.                          |
| `voice binaries in the bundle`                    | A lean bundle holds a voice or model file. The message lists the paths.                  |
| `VERSION must look like`                          | Pass three numbers, such as `VERSION=1.2.3`.                                             |
| `the build venv's cloudyreader metadata says`     | Run the sync step, then run `make release` again.                                        |
| `the app says version`                            | `VERSION` and the version in `pyproject.toml` differ. Make them match.                   |
| `the extracted copy's --version prints`           | The bundled metadata is stale. Run the sync step, then run `make release` again.         |
