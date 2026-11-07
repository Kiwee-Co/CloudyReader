---
title: Test and CI
description: 'The Cloudy Reader test gates, markers, and coverage floor, the CI jobs and their gate, the live smoke checks, and the engine tests.'
sidebar:
  order: 3
---

The commit gate is `make ci`. It runs the repository guards, the lint check, the tests with a coverage floor, and the pre-commit hooks. On GitHub, the `ci` workflow ends with a gate job that passes only when the seven jobs pass.

## Run the gates

Each command below is a `make` target.

| Command          | What it runs                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `make check`     | `ruff check .` and `ruff format --check .`                                                            |
| `make test`      | The gate tests with coverage. It fails below the floor of 75 percent.                                 |
| `make test-fast` | The quick tests, with no coverage report. No models, no network.                                      |
| `make guards`    | The policy guards: the vendor domain, the `uv.lock` hosts, machine disk paths, and workflow triggers. |
| `make precommit` | `pre-commit run -a`. If `pre-commit` is missing, it prints how to install it and exits 0.             |
| `make ci`        | `guards`, then `check`, then `test`, then `precommit`.                                                |
| `make fmt`       | `ruff format .` and `ruff check --fix .`                                                              |

The hooks `shellcheck`, `prettier`, and `markdownlint` run tools from your `PATH`. A hook fails when its tool is missing. [Build from source](/developer/building/#prerequisites) lists the install commands.

The `env` block at the top of `.github/workflows/ci.yml` pins the versions of ShellCheck, `actionlint`, `zizmor`, Prettier, and markdownlint that CI installs. Install the same versions to get the same results.

`make test` runs the equivalent of this command. The Makefile adds `python -I` and a bytecode folder:

```bash
uv run --frozen --offline python -m pytest \
  -m "not model and not voice and not network and not java" \
  --cov=cloudyreader --cov-report=term-missing --cov-fail-under=75
```

Change the floor with `make test COV_MIN=80`. The default lives in the `Makefile`.

### Run the gate as CI does

CI installs the default dependencies only. The `test` job runs `uv sync --frozen`, so the `kokoro` extra is not there: no `mlx` and no `mlx-audio`. `make kokoro` adds the extra to your `.venv`, so a local `make test` can see packages that CI does not.

A test that needs one of those packages skips when the package is missing, or it runs against a stand-in module. Before you push a change to the engines or the packaging, run `make test` in a checkout that has the default dependencies only. Set it up with `make setup`, and do not run `make kokoro`.

## Use the markers

`pyproject.toml` declares five markers. The setting `--strict-markers` makes pytest fail on an unknown marker.

| Marker    | Marks a test that                   | Setup                                            |
| --------- | ----------------------------------- | ------------------------------------------------ |
| `model`   | needs the scispaCy model            | `make models`                                    |
| `voice`   | needs a Piper voice                 | `make voices`                                    |
| `network` | needs internet access               | A network connection                             |
| `java`    | starts a JVM, because it runs OPSIN | `make deps`, which installs the bundled `jdk4py` |
| `slow`    | takes more than about a second      | Nothing                                          |

- `make test` excludes `model`, `voice`, `network`, and `java`. It includes `slow`.
- `make test-fast` also excludes `slow`.
- The tests in `tests/engines_real/` carry `model` and `slow`, so `make test` skips them.
- No target runs the full suite. After `make setup`, run the marked tests with `-m "model or voice or java"`.

```bash
uv run --frozen --offline python -I -m pytest -m "model or voice or java" -q
```

Run one file or one test the same way, as in these examples:

```bash
uv run --frozen --offline python -I -m pytest tests/unit/test_rotation.py -q
uv run --frozen --offline python -I -m pytest tests/unit/test_parser.py -k "answer" -q
```

## Test layout

Each folder under `tests/` holds one kind of test.

| Folder                      | Content                                                                                                                                                                                                                                                                             |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/`               | Parser, normalizer, formulas, units, fractions, respelling, lexicon, entities, voice engines, voice labels and order, rotation, the download, the CI checks, and the pin and smoke scripts.                                                                                         |
| `tests/unit/resolvers/`     | HTTP, cache, PubChem, UniProt, OPSIN, and the chain.                                                                                                                                                                                                                                |
| `tests/gui/`                | Qt tests with `pytest-qt`: the main window, the voice picker and its labels, the status bar, the live **Spoken script**, the About panel, widgets, tokens, theme, names, the app, the icon, rotation, the download, the engine rows, and the golden images in `tests/gui/goldens/`. |
| `tests/integration/`        | The pipeline with fakes, the command line and self-test, and corpus guards. Some need a voice and a model.                                                                                                                                                                          |
| `tests/smoke/`              | Environment checks and the asset fetcher.                                                                                                                                                                                                                                           |
| `tests/packaging/`          | The build script, the engine switch and its probe, the engine targets, the release step, and the bundle metadata and version.                                                                                                                                                       |
| `tests/data/`               | Checks on the lexicon data.                                                                                                                                                                                                                                                         |
| `tests/golden/`             | YAML files hold parse, spoken-script, and respelling cases, and ambiguous inputs. A `corpus/` folder holds TSV and text files.                                                                                                                                                      |
| `tests/fixtures/questions/` | 63 sample questions that mirror real paste shapes.                                                                                                                                                                                                                                  |
| `tests/engines_real/`       | Run by hand on installed engine files: each engine voice renders a letter and a sentence.                                                                                                                                                                                           |

### Add a question fixture

1. Create `tests/fixtures/questions/NN-category-topic-kind.txt`. The existing names show the pattern, such as `01-earth-science-crustal-plates-mc.txt`. The file holds the pasted text only.
2. Add a case to `tests/golden/parse_cases.yaml`. Its `id` is the file name without `.txt`. `tests/unit/test_parser.py` fails when a numbered fixture has no case.

### Write GUI tests

- `tests/conftest.py` sets `QT_QPA_PLATFORM` to `offscreen` unless the shell sets it. `tests/gui/conftest.py` forces `offscreen`, so no window opens.
- In `tests/gui/`, an autouse fixture points the default `QSettings` at a temporary folder. No GUI test writes your preferences.
- The `make_window` fixture builds a `MainWindow` with `FakeReaderService` and `FakePlayer`. It waits for the voice list.
- The fake service takes knobs: a delay, a gate, an error, warnings, download events, and a gate or an error for the live **Spoken script**. Use the gate to hold a reading in flight. A closing window waits for its worker, so `make_window` opens every gate before it closes the window.
- The golden images in `tests/gui/goldens/` cover the cards, the focus ring, and the status glyphs at 2x. Each has four appearances: light and dark, with standard and increased contrast. A golden passes when at most 1 percent of its pixels differ by more than 8 levels. After a change that moves pixels on purpose, run `CLOUDYREADER_UPDATE_GOLDENS=1 uv run --frozen --offline python -I -m pytest tests/gui/test_goldens.py tests/gui/test_status_glyph.py`, then look at the changed PNG files.

### Write engine tests

The two optional engines take their parts as arguments, so a test can run without weights and without MLX:

- `ChatterboxTurboEngine(settings, backend, pinned=..., assess=..., slot=...)` and `Qwen3TtsEngine` take a `TextBackend` that turns one chunk of text into audio, the `Pinned` files, and an `assess` function. `Qwen3TtsEngine` also takes a `decoder` function for the decoder gate. A test passes fakes.
- A test of `MlxChatterboxBackend` or `MlxQwenBackend` puts fake `mlx.core` and `mlx_audio.tts.utils` modules into `sys.modules`.
- Real audio comes only from the by-hand workflow in [Test the engines by hand](#test-the-engines-by-hand).

`MacosEngine(say=..., popen=...)` takes the path of `say` and a `popen` function. Its tests in `tests/unit/test_macos_engine.py` run over a fake `subprocess.Popen` and the recorded listing in `tests/fixtures/say/voices.txt`, so no gate test runs the real `say`. One slow test runs it when you set `CR_LIVE_SAY=1` on a Mac.

A test that needs `mlx` or `mlx_audio` itself skips when `find_spec` finds the package missing.

## Run the live smoke checks

Two checks reach real hosts. They never run in CI. Run them on a machine with internet access, outside any sandbox that blocks the network.

| Command             | Checks                                                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `make smoke-live`   | The PubChem and UniProt response shapes that the resolvers parse.                                                                          |
| `make smoke-voices` | The voice download. It asks for byte 0 of every file that the app downloads, then fetches the small files and checks their SHA-256 values. |

The small files total about 0.55 MB. `make smoke-voices` prints file names, statuses, and sizes, never a URL or a host. It ends with a `== verdict ==` block. Its lines start with `HELD`, `PARTIAL`, `BROKEN`, or `NO DATA`, and the last line starts with `RESULT:`.

Both commands always exit 0, so read the verdict, not the exit code.

`make doctor ONLINE=1` also probes PubChem and UniProt. `make doctor VERIFY=1` re-hashes every asset.

## Test the engines by hand

Two `make` targets and one test folder set up and check the optional engines on real files. CI runs none of them, and `make ci` runs none of them. The engine ids are `chatterbox_turbo` and `qwen3_tts`. The smoke test and the real-engine tests need a Mac with Apple silicon and the packages that `make kokoro` installs.

### Pin an engine's files

Pin one engine at a time. The target needs the network. It also needs free disk space of the download size times 1.1, plus 1 GiB:

```bash
make pin-engine ENGINE=chatterbox_turbo
make pin-engine ENGINE=qwen3_tts
```

The target runs `scripts/pin_engine_assets.py ENGINE --write --install`. The script does these steps:

1. It resolves the revision `main` to a commit through the Hugging Face model API. Run the script yourself with `--rev` to pin another branch, tag, or commit.
2. It lists the repository and keeps the `.safetensors`, `.json`, and `.txt` files that have safe names and sit at most one folder deep.
3. It downloads each kept file from its commit-pinned URL into a temporary folder under `.data`.
4. It checks each size and SHA-256 value against the LFS record and against the expected files in `SPECS` in `cloudyreader/engine_catalog.py`.
5. It replaces the entries of that engine in `assets.lock.json`, and it moves the files into `.data/models/<engine>/`.

The script prints names, statuses, sizes, and hashes. The `ok` and `DRIFT` lines show the first 12 characters of a hash. The JSON lines under `lock` show each entry with its full SHA-256 and without its URL. The script never prints a URL, a host, or a token. Each line starts with a status, except the JSON lines under `lock`:

| Status      | Meaning                                                                                              |
| ----------- | ---------------------------------------------------------------------------------------------------- |
| `pin`       | The engine, the repository, the revision, and the commit that the revision resolves to.              |
| `skipped`   | A file that the pin leaves out, with the reason, such as `not a data file` or `hidden file`.         |
| `SKIPPED`   | A file that can run code when it loads, such as `.pt`, `.bin`, or `.py`. The pin never keeps it.     |
| `new`       | A file that the pin keeps but that `SPECS` does not list.                                            |
| `DRIFT`     | A difference from `SPECS`: a missing file, another size, or another SHA-256 value. It stops the pin. |
| `ok`        | A downloaded file, with its size and the first 12 characters of its SHA-256 value.                   |
| `lock`      | The lock entries that the pin made, and their total size.                                            |
| `wrote`     | The lock now holds the entries of the engine. The `make` target always passes `--write`.             |
| `installed` | A file that the pin moved into `.data/models/<engine>/`.                                             |
| `kept`      | A file that was already there with the same size and SHA-256 value.                                  |
| `stale`     | A file in the engine folder that the pin does not list. Move it out of the folder.                   |

A pin that stops while it lists, downloads, or checks changes nothing. `assets.lock.json` and the installed files stay as they were, and the script removes its temporary folder. The script writes the lock before it installs the files.

### Fix a failed pin

The script prints `pin_engine_assets:` before each error message and exits 1. The messages call `SPECS` the research table. Each row of this table holds a part of a message and its fix:

| The message holds                           | Fix                                                                                                             |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `network error: <class>`                    | The pin could not reach the host. Check the network, any VPN, and any proxy. Then run the pin again.            |
| `model API: HTTP <status>`                  | Run the pin again after a few minutes. A status 404 or 401 means the repository moved or is gated.              |
| `difference(s) from the research table`     | The repository changed after `SPECS` was written. Update `SPECS` in `engine_catalog.py`. The pin wrote nothing. |
| `SHA-256 does not match the LFS oid`        | The download is bad, or the file changed. Run the pin again.                                                    |
| `not enough disk space`                     | Free space on the volume that holds `.data`. Then run the pin again.                                            |
| `is not in the json.dumps(indent=2) layout` | Someone edited `assets.lock.json` by hand. Restore it from git. The pin wrote nothing.                          |
| `nothing installed`                         | The lock changed, but no file moved. Remove the cause that the message names, then run the same pin again.      |

### Smoke test the installed files

```bash
make smoke-engines
```

The script `scripts/live_smoke_engines.py` makes no network call, and it prints no URL. For each installed engine voice it loads the model from a cold start. The first call loads the model and says `Ready.` Its line starts with `load`. After that call, the script renders the 12 short units of one multiple-choice question: the header, the category, the format, the stem, four letters, and four choices. Then it renders four fixed sentences. One sentence holds hyphenated respellings, and one holds the same respellings with the hyphens removed. The audio goes to a temporary folder.

Each render prints one line with its audio length, wall time, real-time factor (RTF), and sample peak. A unit's line shows `alone` when the engine said the text by itself, even on a later try. It shows `fallback` when the engine needed the retry with three copies of the text. The line also counts the render calls, as `1 try` or `2 tries`.

A render line and a verdict line start with one of these states:

- `HELD`: the render has a plausible length and audible sound.
- `BROKEN`: the render did not hold. The line names the reason: `too short`, `too long` (a runaway), `silent`, or `failed: <error>`.
- `NO DATA`: the engine cannot run here. The line names the reason, such as `no files pinned in assets.lock.json` or `waiting for a Qwen3 decoder fix`.

The run ends with a `== verdict ==` block. It holds one line for each engine voice, or one line that says why an engine did not run. The last line starts with `RESULT:`. The script always exits 0, so read that line, not the exit code.

### Run the real-engine tests

No `make` target runs the tests in `tests/engines_real/`. They carry the markers `model` and `slow`, so `make test` skips them. Run them by hand, as in this example:

```bash
CLOUDYREADER_DATA_DIR="$PWD/.data" uv run --frozen --offline python -I -m pytest -m model tests/engines_real -v
```

A test skips when the engine module or the downloaded files are missing, or when the Mac has no Apple silicon. The skip reason names what is missing, and a skip is not a pass. For each installed engine, one test checks that it lists its voices. Another test renders the letter `W.` and one sentence with each voice. Each rendering must be 24 kHz mono audio with a length in range and audible sound.

### Commit the lock

After a pin, `git status --short` lists only `assets.lock.json` as modified. Commit that file. Never commit anything under `.data/`. The commit that adds the pins also changes the `ENGINES` value of the `release` recipe. [Build the release zip](/developer/building/#build-the-release-zip) explains why.

Two tests check the engine entries of the lock once it holds any: `test_the_real_lock_pins_nothing_or_matches_the_specs` in `tests/unit/test_engine_catalog.py`, and `test_real_lock_engine_entries_validate_when_present` in `tests/unit/test_prefetch.py`. They check each pinned size and, where `SPECS` has one, each SHA-256 value.

## Lint rules

`pyproject.toml` configures Ruff: line length 100, target `py312`, and rules `E`, `F`, `I`, `B`, and `UP`. Ruff skips `.cache` and `.data`. The two Ruff hooks in `.pre-commit-config.yaml` call `.venv/bin/ruff`, so run `make deps` before `pre-commit`.

## Pre-commit hooks

The file `.pre-commit-config.yaml` holds local hooks only. No hook clones a repository. The two Ruff hooks rewrite files. Every other hook only reads and reports. A hook that skips files lists them in its `exclude:` key.

| Hook                                    | What it flags                                                   |
| --------------------------------------- | --------------------------------------------------------------- |
| `ruff-check` and `ruff-format`          | Python files that Ruff would change. The hooks rewrite them.    |
| `trailing-whitespace` and `end-of-file` | Trailing spaces or tabs, and a text file with no final newline. |
| `merge-conflict`                        | Merge-conflict markers.                                         |
| `private-key`                           | A private-key block.                                            |
| `vendor-domain`                         | The vendor's own domain, in any letter case.                    |
| `disk-paths`                            | A path on the disk of one machine, such as a home folder.       |
| `shellcheck`                            | ShellCheck findings in shell scripts.                           |
| `prettier`                              | Markdown, YAML, and JSON that `prettier --check` rejects.       |
| `markdownlint`                          | Markdown that `markdownlint` rejects.                           |

The `prettier` and `markdownlint` hooks select `.md` files. They do not select `.mdx` files, so run both tools yourself on an `.mdx` page.

## Format ratchet

The `prettier` and `markdownlint` hooks check files against `.prettierrc` and `.markdownlint.json`. Each hook has an `exclude:` key in `.pre-commit-config.yaml`. These two lists are the baseline: they name the files that fail the check.

- A hook skips a file on its list.
- A hook checks every other file. A file that is clean must stay clean.
- To bring a file under the check, format it with `prettier --write` or `markdownlint --fix`. Then delete its entry from the list.
- `tests/unit/test_ci_precommit.py` keeps the lists honest. Every entry must name a tracked file, and a file known to be clean must never be on a list.
- When every file passes, delete the `exclude:` keys. The test accepts a hook without a list.
- `.prettierignore` keeps tool-written data out of Prettier: `assets.lock.json`, `cloudyreader/data/*.json`, and `tests/golden/*.yaml`.

## CI workflow

The file `.github/workflows/ci.yml` defines the workflow `ci`. It has seven jobs. An eighth job, also named `ci`, is the gate. The gate runs even when another job failed or was skipped, and it passes only when all seven jobs succeeded.

| Item               | Value                                                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Triggers           | A pull request, a push to `main`, and a manual run                                                                        |
| Runners and limits | `macos-15` for `test`, 20 minutes. `ubuntu-24.04` for the rest: 10 minutes each, and 5 minutes for `guards` and the gate. |
| Permissions        | `contents: read`. No job widens it.                                                                                       |
| Concurrency        | A later push to a pull request cancels its older run. A run on `main` always finishes.                                    |
| Actions            | Pinned by commit SHA. Every checkout drops the token.                                                                     |
| Tools              | `uv` 0.9.28 and `pre-commit` 4.7.0. The `env` block pins the other tools.                                                 |
| Job environment    | `UV_MANAGED_PYTHON=1` and `UV_NO_PROGRESS=1` in every job that uses `uv`                                                  |

### The seven jobs

- **`guards`** runs `make guards`. The script `scripts/ci_guards.py` checks four rules. No tracked file names the vendor's own domain. `uv.lock` names public hosts only. No tracked file holds a machine disk path. No workflow uses the privileged `pull_request_target` trigger. A finding prints as `path:line: [guard] problem`. On GitHub it also becomes an error annotation.
- **`lint`** installs only the `dev` group, so it needs no app dependencies. It runs `ruff check` and `ruff format --check`, a strict YAML parse of the files under `.github` (`scripts/ci_yaml.py`), ShellCheck, `actionlint`, and `zizmor`. `zizmor` runs offline and reports only findings of medium severity or higher. That threshold leaves out one Low finding: the `format` job installs its two npm tools without a lockfile.
- **`pre-commit`** runs every hook except `prettier` and `markdownlint`.
- **`format`** installs Prettier and markdownlint with `npm`, without install scripts. Then it runs the `prettier` and `markdownlint` hooks.
- **`test`** runs `make test` offline with `QT_QPA_PLATFORM=offscreen`. Then it prints the step summary and the failure annotations, and it uploads the reports.
- **`docs`** checks the documentation site with `scripts/check_site.py`.
- **`lock`** runs `uv lock --check`. It fails when `uv.lock` does not match `pyproject.toml`.

The CI run installs no models, no voices, and no `kokoro` extra. Tests marked `model` or `voice` never run there.

### Workflow rules

`tests/unit/test_ci_workflows.py` reads `ci.yml` as data and fails when an edit breaks one of these rules:

- The jobs are the seven above plus `ci`, and each job id equals its visible name.
- The triggers are a push to `main`, `pull_request`, and `workflow_dispatch`, with no path filters.
- The default permissions are `contents: read`, and no job widens them.
- Every job has a timeout and a pinned runner image. No runner uses a `-latest` label, and `test` runs on `macos-15`.
- Every `uses:` line names a full commit SHA and carries a version note.
- No `run` block holds a `${{` expression. The file holds no `secrets.`, no privileged trigger, and no write to `GITHUB_ENV` or `GITHUB_PATH`.
- Every checkout drops the token.
- Every tool pin is an exact version, and every `setup-uv` step pins the same uv version.
- Every `uvx` and `uv tool install` command pins the Python from `.python-version`, so uv fetches no second interpreter.
- No inline `zizmor: ignore` comment hides a finding.
- The `Summarize the run` step runs `scripts/ci_summary.py` twice. Only the Markdown goes to the step summary. The `--annotate` run prints to standard output only.

### Reports

The `test` job writes two reports, a summary, and annotations:

- **Step summary.** `scripts/ci_summary.py` prints Markdown to the step summary. It shows on the summary page of the run. It lists the tests (passed, failed, errors, skipped, and time), up to 20 failing test ids, and the coverage. The coverage part shows the total and the 25 files with the lowest coverage.
- **Artifact.** The artifact `test-reports` holds `junit.xml` and `coverage.xml`. GitHub keeps it for 14 days. The upload and the summary run after a failure too, but not after a cancel.
- **Annotations.** Ruff, the guards, `actionlint`, and `zizmor` mark the failing line on the pull request. The `test` job adds annotations of its own. See [Read the test annotations](#read-the-test-annotations).

### Read the test annotations

The step `Summarize the run` runs `scripts/ci_summary.py` a second time with `--annotate`. That run prints GitHub workflow commands instead of Markdown:

- One error for each failed test, at most 10, then one notice that counts the rest.
- One error when the JUnit report is missing or holds no tests.
- One error when coverage is under the floor. The floor is `COV_MIN`, read from the environment first and then from the `Makefile`.

A clean run prints nothing. A test annotation reads `<test id>: <first line of the failure message>`, and the script cuts that first line to 300 characters. The annotation points at the last frame of the traceback that lies inside the repository. It never names a file from `.venv`, `.cache`, or outside the repository. A check-run annotation shows without a login, so a failure names its tests.

The usage is `python3 scripts/ci_summary.py --junit PATH --coverage PATH [--top N] [--annotate [--floor P]]`. The script exits 0, except 2 on a usage error. A missing or unreadable report never fails the step.

### Run a job yourself

These commands run the checks of each job on your Mac.

| Job                       | Run it with                                                                   |
| ------------------------- | ----------------------------------------------------------------------------- |
| `guards`                  | `make guards`                                                                 |
| `lint`                    | `make check` for Ruff, then `make precommit` for ShellCheck                   |
| `pre-commit` and `format` | `make precommit`                                                              |
| `test`                    | `make test`                                                                   |
| `docs`                    | See [Edit the documentation](/developer/contributing/#edit-the-documentation) |
| `lock`                    | `uv lock --check`                                                             |

Run the YAML parse with `.venv/bin/python scripts/ci_yaml.py`. No `make` target runs `actionlint` or `zizmor`.

The command `make ci` runs `guards`, `check`, `test`, and `precommit`. It does not run `docs`, `lock`, or the CI-only lint steps.
