---
title: Build from source
description: 'Set up a source checkout of Cloudy Reader, run the make targets, and build the app, the release zip, or the disk image on a Mac with Apple silicon.'
sidebar:
  order: 1
---

This page covers a source checkout: the setup, every `make` target, offline builds, the app bundle, and the release zip and disk image. To use the app without building it, see [Download Cloudy Reader](/download/).

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

The targets `models`, `voices`, and `kokoro` fetch the files that `assets.lock.json` lists with `scripts/fetch_assets.py`. The script saves each file in a fresh temporary folder and checks the size and the SHA-256 value. Only then does it move the file into place.

## Make targets

Run `make help` to print the targets and the variables.

Nine targets set `CLOUDYREADER_DATA_DIR` to `.data` in the checkout: `run`, `test`, `test-fast`, `samples`, `smoke-live`, `app`, `release`, `pin-engine`, and `smoke-engines`. `make run` does not enable offline mode in the app. It only keeps `uv` off the network.

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

These targets build the app, the release files, and the icon files.

| Target       | What it does                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `app`        | Build `dist/Cloudy Reader.app`, ad-hoc signed. Takes `BUNDLE_VOICES`, `KOKORO`, `ENGINES`, `START_QUESTIONS`, and `ICON`. |
| `release`    | Build the lean app, then its zip and disk image with SHA-256 files in `dist/`. Takes `VERSION`. Never uploads.            |
| `icons`      | Regenerate the four icon candidates and `assets/icons/preview.png`.                                                       |
| `open-icons` | Open `assets/icons/preview.png`.                                                                                          |

### Live checks and samples

These targets need the network, installed engine files, or files that you supply.

| Target          | What it does                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------ |
| `samples`       | Extract sample-question PDFs to `.data/samples`. Needs `pdftotext` and a source folder.          |
| `smoke-live`    | Check PubChem and UniProt live. Never part of `ci`.                                              |
| `smoke-voices`  | Check the voice download live, about 0.55 MB. Never part of `ci`.                                |
| `pin-engine`    | Pin `ENGINE` in `assets.lock.json` and install its files. Needs the network. Never part of `ci`. |
| `smoke-engines` | Check each installed engine voice with test speech. Needs no network. Never part of `ci`.        |

The two engine targets belong to one workflow. [Test the engines by hand](/developer/testing/#test-the-engines-by-hand) shows the steps.

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

| Variable          | Default                       | Effect                                                                                                                                                              |
| ----------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `UV`              | `uv`                          | The uv executable.                                                                                                                                                  |
| `COV_MIN`         | `75`                          | The coverage floor for `make test`, in percent.                                                                                                                     |
| `VOICES`          | The pinned Piper ids          | The Piper ids for `make voices` and `make doctor`. Ids come from `assets.lock.json`.                                                                                |
| `OFFLINE`         | `0`                           | `1` makes uv use `--offline` and makes the fetcher refuse downloads.                                                                                                |
| `CONFIRM`         | `no`                          | `yes` lets `clean-all` delete `.venv` and `.cache`.                                                                                                                 |
| `ONLINE`          | `0`                           | `1` makes `make doctor` also check that PubChem and UniProt answer.                                                                                                 |
| `VERIFY`          | `0`                           | `1` makes `make doctor` check the SHA-256 value of each asset.                                                                                                      |
| `APP_NAME`        | `Cloudy Reader`               | The bundle name for `make app` and `make release`.                                                                                                                  |
| `ICON`            | Empty                         | An icon folder under `assets/icons/`. Empty reads `assets/icons/default.txt`.                                                                                       |
| `KOKORO`          | `auto`                        | `auto`, `0`, or `1`. Whether `make app` bundles Kokoro.                                                                                                             |
| `ENGINES`         | `auto`                        | `auto`, `0`, or `1`. Whether `make app` bundles the optional engines.                                                                                               |
| `BUNDLE_VOICES`   | `1`                           | `1` bundles the voices and the Kokoro model. `0` builds a lean app.                                                                                                 |
| `START_QUESTIONS` | `1`                           | `1` copies the test-fixture questions into the app, which shows one random question in the empty question box at start. `0` copies none. `make release` forces `0`. |
| `OUT`             | `dist`                        | The output folder for `make app` and `make release`.                                                                                                                |
| `ENGINE`          | Empty                         | `chatterbox_turbo` or `qwen3_tts`. The engine that `make pin-engine` pins.                                                                                          |
| `VERSION`         | `version` in `pyproject.toml` | The version that `make release` checks and puts in the zip name.                                                                                                    |

`scripts/build_app.sh` also reads two time limits from the environment. `SELFTEST_TIMEOUT` is the limit of each self-test run in whole seconds, and it defaults to 300. `PROBE_TIMEOUT` is the limit of the engine probe in seconds, and it defaults to 120. This example raises the self-test limit:

```bash
SELFTEST_TIMEOUT=600 make app
```

## Work offline

`test`, `test-fast`, `check`, and `fmt` never use the network. They call `uv run --frozen --offline`.

`make run` calls the same command, so `uv` stays off the network. The app that it starts can still do name lookups and download missing voices. Turn on the offline mode of the app with the option `--offline` or the variable `CLOUDYREADER_OFFLINE=1`. [Command line](/manual/reference/command-line/) describes both.

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

| Item               | Source run                                                                         | Release app                                                                         |
| ------------------ | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Data folder        | `make run` uses `.data` in the checkout.                                           | `~/Library/Application Support/cloudyreader`                                        |
| Version            | `dev`, when the package metadata is missing.                                       | The bundled package metadata.                                                       |
| Voices             | The files from `make voices` and `make kokoro`. The app downloads what is missing. | None are bundled. The app downloads every missing pinned file.                      |
| `assets.lock.json` | The copy in the checkout.                                                          | The copy in the bundle.                                                             |
| Kokoro             | Needs `make kokoro`.                                                               | Always included (`KOKORO=1`).                                                       |
| Optional engines   | Need the `kokoro` extra and the files that `make pin-engine` installs.             | The code ships when the build includes the engines (`ENGINES`). The files download. |
| scispaCy model     | Needs `make models`. Without it, name detection uses regular expressions only.     | Bundled.                                                                            |
| macOS minimum      | None in `Info.plist`. The installed wheels decide.                                 | `LSMinimumSystemVersion`, computed at build time.                                   |

`CLOUDYREADER_DATA_DIR` overrides the data folder in both. A plain `python -m cloudyreader` uses the folder in the right column.

## Add the Kokoro voice engine

The app always registers the Piper voice engine. It registers the Kokoro voice engine only on Apple silicon.

```bash
make kokoro
```

The target stops with an error on a Mac that is not arm64. It syncs the `kokoro` extra. The extra holds `mlx`, `mlx-audio`, `misaki`, `en-core-web-sm`, `espeakng-loader`, `phonemizer-fork`, and `num2words`. Then the target fetches the Kokoro files from `assets.lock.json`.

## Add the optional engines

Two more voice engines are optional: `chatterbox_turbo` and `qwen3_tts`. They share the `kokoro` extra. They need Apple silicon, `mlx`, `mlx_audio`, and `transformers`, so `make kokoro` installs their packages too.

An engine has no voice until `assets.lock.json` pins its files. This command pins the files of one engine and installs them in `.data/models/chatterbox_turbo/`:

```bash
make pin-engine ENGINE=chatterbox_turbo
```

The target needs the network. Set `ENGINE` to `chatterbox_turbo` or `qwen3_tts`. [Test the engines by hand](/developer/testing/#test-the-engines-by-hand) shows what the target prints and how to check the result.

## Build the app

```bash
make setup   # the voices must exist in .data/voices
make app
```

`make app` builds a self-contained app: it copies the Piper voices and, when Kokoro is included, the Kokoro model folder into the bundle. Pass `BUNDLE_VOICES=0` for a lean app, which holds no voice and downloads them at first launch. By default it also copies the test-fixture questions, so the app shows one in the empty question box at start. That makes it a dev build. Pass `START_QUESTIONS=0` to leave them out.

`make app` first runs `deps`, `models`, and the `packaging` dependency group. Then `scripts/build_app.sh` does the work. It stops at the first error.

1. **Preflight.** It needs macOS, arm64, a valid `APP_NAME`, a whole-number `SELFTEST_TIMEOUT`, `.venv`, `codesign`, the scispaCy model, PyInstaller, and at least one Piper voice in `.data/voices`.
2. **Inputs.** It picks the icon from `ICON` or `assets/icons/default.txt`. It checks `BUNDLE_VOICES` and `START_QUESTIONS`. It decides about Kokoro: `auto` bundles it only when the extra is installed and every pinned file has its pinned size. `1` demands it. `0` skips it. It then decides about the optional engines: `auto` tries them only with Kokoro, and only when `assets.lock.json` pins engine files. `1` demands them and needs `KOKORO=1`. `0` skips them.
3. **PyInstaller.** It builds a one-folder bundle from `packaging/CloudyReader.spec` in `build/dist/`. The entry point is `packaging/launcher.py`. The log is `build/pyinstaller.log`. The script prints that log without two known harmless warnings and says how many it hid. With `START_QUESTIONS=1`, the spec adds the test-fixture questions as `Contents/Resources/start_questions`.
4. **Engine probe.** When the build includes the engines, the script runs the staged bundle once with `CLOUDYREADER_PROBE=engines`, offline. The launcher hands that run to `cloudyreader/engines/bundle_probe.py`. The probe asks each engine's `supported()`, imports the packages that the engines need, and finds the decoder file that the Qwen3-TTS gate reads. It prints one `ok` or `FAIL` line for each check, loads no weights, and exits 1 when a check fails. After a failed probe, `ENGINES=auto` rebuilds the bundle without the engines, and `ENGINES=1` stops the build. The probe has a time limit of `PROBE_TIMEOUT` seconds, and its output goes to `build/engines-probe.log`.
5. **Assets.** It copies `assets.lock.json` into `Contents/Resources/assets`. With `BUNDLE_VOICES=1` it also copies the Piper voices and the Kokoro folder, if used.
6. **Info.plist check.** It lints the file. It requires an existing icon, a version, and `LSMinimumSystemVersion`.
7. **Voice audit.** With `BUNDLE_VOICES=0`, the build fails when the bundle holds a voice or model file. Piper's own `piper/hebrew/nakdimon.onnx` and `piper/tashkeel/model.onnx` are allowed.
8. **Ad-hoc signing.** It runs `codesign --force --deep -s -`. This uses no Developer ID and skips notarization.
9. **Install.** It moves a previous `dist/Cloudy Reader.app` into `build/trash.*`. It deletes nothing. Then it moves the app into `dist/` and runs `codesign --verify --deep --strict`.
10. **Self-test.** It runs the bundle with `--self-test`, offline and headless, twice on one data folder. A lean build (`BUNDLE_VOICES=0`) adds two steps. First, it links the host's voices and Kokoro model folder, if the host has one, into that folder. Then it runs a third time on an empty folder. The third run must exit 2 with `FAIL: no Piper voice installed` and no traceback.
11. **Summary.** It prints the size, the voices, the Kokoro state, the engine state, the start-question state, and the ten largest components. When the build includes the engines, it also lists the engine folders and their sizes.

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

With the engines, the spec also collects their two modules, their `mlx_audio` model packages, the `transformers` tokenizer code that they load by name, and `tokenizers`. Weights never ship: they download.

A build with `START_QUESTIONS=1` also holds the test-fixture questions in `Contents/Resources/start_questions`. A release holds none.

### Choose an icon

Four candidates live in `assets/icons/`: `cloud-atom`, `cloud-book`, `cloud-voice`, and `cloud-wave`. The file `assets/icons/default.txt` names the default, `cloud-atom`.

```bash
ICON=cloud-wave make app
```

`make icons` regenerates the candidates and the preview image. `make release` always uses `cloud-atom`.

## Build the release zip

`make release` builds the files that a GitHub release carries: a zip and a disk image, each with a SHA-256 file. Both hold the same lean app: no voice files, no Kokoro model, and no test-fixture question. The app downloads them at first launch. `make release` never uploads anything.

Set the version in every place that [Change the version](/developer/contributing/#change-the-version) lists. Then run the sync step, so that `.venv` knows the version, and build. This example builds version 0.0.2:

```bash
make .cache/stamps/packaging kokoro
make release VERSION=0.0.2
```

The sync step needs the network and the public package index. `VERSION` defaults to `version` in `pyproject.toml`.

`make release` runs three commands in order:

1. `scripts/build_app.sh release-preflight` makes three checks. `VERSION` must look like `1.2.3`. The `cloudyreader` package metadata in `.venv` must say `VERSION`, because PyInstaller bundles that metadata and the About box and `--version` read it. `hdiutil` and `diskutil` must be on the `PATH`, because the disk image needs them. A metadata mismatch stops the build and names the sync step.
2. `make app` with `BUNDLE_VOICES=0 OFFLINE=1 ICON=cloud-atom KOKORO=1 START_QUESTIONS=0` and the `ENGINES` value of the recipe builds the lean app with every check from [Build the app](#build-the-app).
3. `scripts/build_app.sh release` zips the app, builds the disk image, and checks both.

The recipe sets `ENGINES` to `auto`, so a release bundles the engines only when `assets.lock.json` pins their files and the engine probe passes. It sets `START_QUESTIONS` to `0`, so a release never holds the test-fixture questions. A value for either variable on your command line does not change the recipe.

The last command works in this order:

- It moves an older zip, disk image, and checksums with the same names into `build/trash.*`.
- `ditto -c -k --keepParent --norsrc --noextattr` makes the zip. The command fails when the zip holds `__MACOSX`, `.DS_Store`, or `._` files.
- It writes the SHA-256 beside the zip and checks the zip against it.
- It extracts the zip and checks the extracted copy. The copy must pass `codesign --verify --deep --strict`, carry `VERSION` in `CFBundleShortVersionString`, print `Cloudy Reader <VERSION>` for `--version`, pass the voice audit, pass the start-question audit, and pass the self-test.
- It builds the disk image from that extracted copy, writes the SHA-256 beside the image, and checks the image against it. Then it runs the checks that [Build the disk image](#build-the-disk-image) lists.

The release step leaves these files in `dist/`:

- `Cloudy-Reader-<VERSION>-macos-arm64.zip`. Spaces in `APP_NAME` become hyphens.
- `Cloudy-Reader-<VERSION>-macos-arm64.zip.sha256`. It holds the hash, two spaces, and the file name.
- `Cloudy-Reader-<VERSION>-macos-arm64.dmg`, the disk image.
- `Cloudy-Reader-<VERSION>-macos-arm64.dmg.sha256`. It has the same layout as the zip checksum.
- `Cloudy Reader.app`, the lean app.

Each `.sha256` file names its file without a folder. [Download Cloudy Reader](/download/) shows how to check a download.

The app in the zip and the app in the disk image are ad-hoc signed and not notarized. Nothing signs the disk image itself. See [Security and code signing](/about/security/) for what that means for users.

### Build the disk image

The disk image is a read-only APFS image, compressed with lzfse (`ULFO`). Its volume is named `Cloudy Reader`, with no version. The build makes one of two images:

- **Styled.** `packaging/dmg_layout.py` sets the window when `dmgbuild` is in the build venv. The window is 640 by 400 points in icon view, with no toolbar, sidebar, path bar, status bar, or tab bar. The app icon sits at the left, centered 176 points from the left edge and 190 points from the top. The `Applications` link sits at the right, centered 464 points from the left edge and 190 points from the top. A white arrow joins them on a flat `#7A63D6` background. The icons are 128 points, and the labels under them are 13 points.
- **Plain.** The volume has no window layout. The build says `release: <name> is plain: dmgbuild is not in the build venv (make .cache/stamps/packaging)`.

`dmgbuild` and its two libraries, `ds-store` and `mac-alias`, belong to the `packaging` dependency group, so the sync step installs them. They are build tools and never ship in the app.

The volume holds `Cloudy Reader.app`, an `Applications` link to `/Applications`, and the hidden volume icon `.VolumeIcon.icns`, which is the icon of the app. A styled image also holds `.DS_Store` and `.background.tiff`. The check fails on any other entry.

The plain image comes from `diskutil image create from` on macOS 26 or later. On an earlier macOS version, it comes from `hdiutil create -fs APFS -format ULFO`. The macOS version decides first, because `diskutil image create from --help` can answer on a macOS version that has no such verb. The plain image from `hdiutil` has no custom volume icon. A release needs both `hdiutil` and `diskutil`. `dmgbuild` drives `hdiutil` flags that macOS 27 deprecates, so a later macOS version may break the styled path. The plain image stays the fallback.

The app in the image is a copy of the app that the build extracted from the zip. `ditto --norsrc --noextattr` makes the copy, so it carries no resource forks and no extended attributes.

The build checks the image in this order:

1. `hdiutil verify` accepts the image.
2. The build attaches the image read-only and hidden.
3. The volume name is `Cloudy Reader`. The volume holds an `Applications` link to `/Applications` and no entry beyond those named above.
4. The app in the image passes `codesign --verify --deep --strict`.
5. The app prints `Cloudy Reader <VERSION>` for `--version`.
6. The voice audit passes.
7. One digest over every file, folder mode, and link of the app equals the digest of the app in the zip.
8. The build ejects the image, however the checks end. It ejects only a device that `diskutil info` confirms is a disk image.

`scripts/build_app.sh figures VERSION FILE` writes key=value lines to `FILE`, among them `APP_BYTES`, `ZIP_BYTES`, `SHA256`, `DMG_BYTES`, and `DMG_SHA256`. `APP_BYTES` sums the regular files of the app in `dist/`. The command writes the file only after the zip and the disk image each match their `.sha256` file.

## Fix build errors

The script prints `build_app: error:` before each message. The table lists the text after it.

| Message starts with                               | Fix                                                                                                                                                      |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no .venv`                                        | Run `make deps`.                                                                                                                                         |
| `no Piper voice (.onnx + .onnx.json) in`          | Run `make voices`.                                                                                                                                       |
| `scispaCy model en_ner_craft_md is not installed` | Run `make models`.                                                                                                                                       |
| `codesign not found`                              | Run `xcode-select --install`.                                                                                                                            |
| `KOKORO=1 but`                                    | Run `make kokoro`. For `make app`, you can pass `KOKORO=auto` or `KOKORO=0` instead.                                                                     |
| `ENGINES=1 needs KOKORO=1`                        | Pass `KOKORO=1`, or use `ENGINES=auto` or `ENGINES=0`.                                                                                                   |
| `ENGINES=1 but the engine probe failed`           | Read `build/engines-probe.log`. Use `ENGINES=auto` to build without the engines.                                                                         |
| `START_QUESTIONS must be`                         | Pass `START_QUESTIONS=0` or `START_QUESTIONS=1`.                                                                                                         |
| `selftest-1 timed out after`                      | Read the log that the message names in `build/`. Raise `SELFTEST_TIMEOUT` on a slow Mac.                                                                 |
| `self-test run 1 exited`                          | Read `build/selftest-1.log`. Run 2 uses `build/selftest-2.log`.                                                                                          |
| `voice binaries in the bundle`                    | A lean bundle holds a voice or model file. The message lists the paths.                                                                                  |
| `test-fixture questions in the bundle`            | A release bundle holds the test-fixture questions. The message lists the paths. Build the release with `make release`, which forces `START_QUESTIONS=0`. |
| `VERSION must look like`                          | Pass three numbers, such as `VERSION=1.2.3`.                                                                                                             |
| `the build venv's cloudyreader metadata says`     | Run the sync step, then run `make release` again.                                                                                                        |
| `hdiutil not found` or `diskutil not found`       | Both tools ship with macOS. Check your `PATH`.                                                                                                           |
| `the app says version`                            | `VERSION` and the version in `pyproject.toml` differ. Make them match.                                                                                   |
| `the extracted copy's --version prints`           | The bundled metadata is stale. Run the sync step, then run `make release` again.                                                                         |
| `could not make` or `dmgbuild could not make`     | Read `build/dmg-create.log`. The message names the disk image.                                                                                           |
