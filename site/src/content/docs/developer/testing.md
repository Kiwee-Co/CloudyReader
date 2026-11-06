---
title: Test and CI
description: 'The Cloudy Reader test gates, markers, and coverage floor, the CI jobs behind the required check, and the live smoke checks.'
sidebar:
  order: 3
---

The commit gate is `make ci`. It runs the repository guards, the lint check, the tests with a coverage floor, and the pre-commit hooks. On GitHub, the required status check `ci` passes only when seven jobs pass.

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

| Folder                      | Content                                                                                                                                  |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/`               | Parser, normalizer, formulas, units, fractions, respelling, lexicon, entities, voice engines, rotation, the download, and the CI checks. |
| `tests/unit/resolvers/`     | HTTP, cache, PubChem, UniProt, OPSIN, and the chain.                                                                                     |
| `tests/gui/`                | Qt tests with `pytest-qt`: the main window, the voice picker, widgets, tokens, names, the app, the icon, rotation, and the download.     |
| `tests/integration/`        | The pipeline with fakes, the command line and self-test, and corpus guards. Some need a voice and a model.                               |
| `tests/smoke/`              | Environment checks and the asset fetcher.                                                                                                |
| `tests/packaging/`          | The build script, the release step, and the bundle metadata and version.                                                                 |
| `tests/data/`               | Checks on the lexicon data.                                                                                                              |
| `tests/golden/`             | YAML files hold parse, spoken-script, and respelling cases, and ambiguous inputs. A `corpus/` folder holds TSV and text files.           |
| `tests/fixtures/questions/` | 63 sample questions that mirror real paste shapes.                                                                                       |

### Add a question fixture

1. Create `tests/fixtures/questions/NN-category-topic-kind.txt`. The existing names show the pattern, such as `01-earth-science-crustal-plates-mc.txt`. The file holds the pasted text only.
2. Add a case to `tests/golden/parse_cases.yaml`. Its `id` is the file name without `.txt`. `tests/unit/test_parser.py` fails when a numbered fixture has no case.

### Write GUI tests

- `tests/conftest.py` sets `QT_QPA_PLATFORM` to `offscreen` unless the shell sets it. `tests/gui/conftest.py` forces `offscreen`, so no window opens.
- In `tests/gui/`, an autouse fixture points the default `QSettings` at a temporary folder. No GUI test writes your preferences.
- The `make_window` fixture builds a `MainWindow` with `FakeReaderService`, `FakePlayer`, and `FakeClipboard`. It waits for the voice list.
- The fake service takes knobs: a delay, a gate, an error, warnings, and download events. Use the gate to hold a reading in flight.

## Run the live smoke checks

Two checks reach real hosts. They never run in CI. Run them on a machine with internet access, outside any sandbox that blocks the network.

| Command             | Checks                                                                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `make smoke-live`   | The PubChem and UniProt response shapes that the resolvers parse.                                                                           |
| `make smoke-voices` | The voice download. It asks for byte 0 of every pinned voice and Kokoro file, then fetches the small files and checks their SHA-256 values. |

The small files total about 0.55 MB. `make smoke-voices` prints file names, statuses, and sizes, never a URL or a host. It ends with a `== verdict ==` block. Its lines start with `HELD`, `PARTIAL`, `BROKEN`, or `NO DATA`, and the last line starts with `RESULT:`.

Both commands always exit 0, so read the verdict, not the exit code.

`make doctor ONLINE=1` also probes PubChem and UniProt. `make doctor VERIFY=1` re-hashes every asset.

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

The file `.github/workflows/ci.yml` defines the workflow `ci`. It has seven jobs. An eighth job, also named `ci`, is the gate. Branch protection requires only the gate job. The gate runs even when another job failed or was skipped, and it passes only when all seven jobs succeeded.

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
- **`test`** runs `make test` offline with `QT_QPA_PLATFORM=offscreen`. Then it writes the reports.
- **`docs`** checks the documentation site with `scripts/check_site.py`.
- **`lock`** runs `uv lock --check`. It fails when `uv.lock` does not match `pyproject.toml`.

<!-- needs-fact: the commands of the merged docs job are open (facts section 19); keep this bullet generic until they are fixed -->

The CI run installs no models and no voices. Tests marked `model` or `voice` never run there.

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

### Reports

The `test` job writes two reports and a summary:

- **Step summary.** `scripts/ci_summary.py` prints Markdown to the step summary. It shows on the summary page of the run. It lists the tests (passed, failed, errors, skipped, and time), up to 20 failing test ids, and the coverage. The coverage part shows the total and the 25 files with the lowest coverage.
- **Artifact.** The artifact `test-reports` holds `junit.xml` and `coverage.xml`. GitHub keeps it for 14 days. The upload and the summary run after a failure too, but not after a cancel.
- **Annotations.** Ruff, the guards, `actionlint`, and `zizmor` mark the failing line on the pull request.

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
