---
layout: page
title: Test and CI
nav_group: Developer
nav_order: 13
permalink: /developer/testing/
description: The test gates, the markers, the coverage floor, the live smoke checks, and the CI workflow.
---

The commit gate is `make ci`. It runs the repo guards, the lint check, the tests with a coverage floor, and the pre-commit hooks. On GitHub, the required status check `ci` passes only when seven jobs pass.

The commands on this page are untested: CI does not run them.

## Run the gates

| Command          | What it runs                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `make check`     | `ruff check .` and `ruff format --check .`                                                            |
| `make test`      | The gate tests with coverage. It fails below the floor of 75 percent.                                 |
| `make test-fast` | The quick tests, with no coverage report. No models, no network.                                      |
| `make guards`    | The policy guards: the vendor domain, the `uv.lock` hosts, machine disk paths, and workflow triggers. |
| `make precommit` | `pre-commit run -a`. If `pre-commit` is missing, it prints how to install it and exits 0.             |
| `make ci`        | `guards`, then `check`, then `test`, then `precommit`.                                                |
| `make fmt`       | `ruff format .` and `ruff check --fix .`                                                              |

The hooks `shellcheck`, `prettier`, and `markdownlint` run tools from your `PATH`. A hook fails when its tool is missing. Install the tools once:

```bash
uv tool install shellcheck-py
npm install --global prettier markdownlint-cli
```

The `env` block of `.github/workflows/ci.yml` pins the versions that CI uses. Use the same versions to get the same results.

`make test` runs the equivalent of this command. The Makefile adds `python -I` and a bytecode folder:

```bash
uv run --frozen --offline python -m pytest \
  -m "not model and not voice and not network and not java" \
  --cov=cloudyreader --cov-report=term-missing --cov-fail-under=75
```

Change the floor with `make test COV_MIN=80`. The default lives in the `Makefile`.

## Use the markers

`pyproject.toml` declares five markers. The setting `--strict-markers` makes pytest fail on an unknown marker.

| Marker    | The test needs                 | Created by                         |
| --------- | ------------------------------ | ---------------------------------- |
| `model`   | The scispaCy model             | `make models`                      |
| `voice`   | A Piper voice                  | `make voices`                      |
| `network` | Internet access                | Your network                       |
| `java`    | A JVM, because it starts OPSIN | `make deps` (the bundled `jdk4py`) |
| `slow`    | More than about a second       | Nothing                            |

- `make test` excludes `model`, `voice`, `network`, and `java`. It includes `slow`.
- `make test-fast` also excludes `slow`.
- No target runs the full suite. After `make setup`, run the marked tests with `-m "model or voice or java"`.

```bash
uv run --frozen --offline python -I -m pytest -m "model or voice or java" -q
```

Run one file or one test the same way:

```bash
uv run --frozen --offline python -I -m pytest tests/unit/test_rotation.py -q
uv run --frozen --offline python -I -m pytest tests/unit/test_parser.py -k "answer" -q
```

## Know the test layout

| Folder                      | Content                                                                                                                                                                                                                                                                                       |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/`               | Parser, normalizer, formulas, units, respelling, lexicon, entities, engines, TTS service, voices, rotation, voice profiles, download, config, audio, the bundle helpers, and the CI scripts and workflow. `tests/unit/resolvers/` covers HTTP, cache, PubChem, UniProt, OPSIN, and the chain. |
| `tests/gui/`                | Qt tests with `pytest-qt`: the main window, the voice picker, widgets, tokens, names, the app, the icon, rotation, and the download.                                                                                                                                                          |
| `tests/integration/`        | The pipeline with fakes, the command line and self-test, and corpus guards. Some need a voice and a model.                                                                                                                                                                                    |
| `tests/smoke/`              | Environment checks and the asset fetcher.                                                                                                                                                                                                                                                     |
| `tests/packaging/`          | The build script and the bundle metadata.                                                                                                                                                                                                                                                     |
| `tests/data/`               | Checks on the lexicon data.                                                                                                                                                                                                                                                                   |
| `tests/golden/`             | Golden cases. YAML files hold parse, spoken-script, respelling, and ambiguous cases. A `corpus/` folder holds TSV and text files.                                                                                                                                                             |
| `tests/fixtures/questions/` | 63 sample questions that mirror real paste shapes.                                                                                                                                                                                                                                            |

To add a question fixture, create `tests/fixtures/questions/NN-category-topic-kind.txt`. The existing names show the pattern. One example is `01-earth-science-crustal-plates-mc.txt`. Each file holds the pasted text only.

### Write GUI tests

- `tests/conftest.py` and `tests/gui/conftest.py` set `QT_QPA_PLATFORM=offscreen`, so no window opens.
- A fixture points the default `QSettings` at a temporary folder. No test writes your preferences.
- The `make_window` fixture builds a `MainWindow` with `FakeReaderService`, `FakePlayer`, and `FakeClipboard`. It waits for the voice list.
- The fake service takes knobs: a delay, a gate, an error, warnings, and download events. Use the gate to hold a reading in flight.

## Run the live smoke checks

Two checks reach real hosts. They never run in CI. Run them outside any sandbox.

| Command             | Checks                                                                                                                                                                                                                                                                            |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make smoke-live`   | The PubChem and UniProt response shapes that the resolvers parse.                                                                                                                                                                                                                 |
| `make smoke-voices` | The voice download. It asks for byte 0 of every pinned voice and Kokoro file. Then it fetches the small files (about 0.55 MB) and checks their SHA-256 values. It prints file names, statuses, and sizes, never a URL. It always exits 0, so read the verdict, not the exit code. |

`make doctor ONLINE=1` also probes PubChem and UniProt. `make doctor VERIFY=1` re-hashes every asset.

## Read the lint rules

`pyproject.toml` configures Ruff: line length 100, target `py312`, and rules `E`, `F`, `I`, `B`, and `UP`. Ruff skips `.cache` and `.data`. The two Ruff hooks in `.pre-commit-config.yaml` call `.venv/bin/ruff`, so run `make deps` before `pre-commit`.

## Read the pre-commit hooks

The file `.pre-commit-config.yaml` holds local hooks only. No hook clones a repository. The two Ruff hooks rewrite files. Every other hook only reads and reports.

| Hook                                    | What it flags                                                                                                                        |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `ruff-check` and `ruff-format`          | Python files that Ruff would change. The hooks rewrite them.                                                                         |
| `trailing-whitespace` and `end-of-file` | Trailing spaces or tabs, and a text file with no final newline. Fixtures, golden data, a font licence, and `docs/CNAME` are skipped. |
| `merge-conflict`                        | Merge-conflict markers.                                                                                                              |
| `private-key`                           | A private-key block.                                                                                                                 |
| `vendor-domain`                         | The vendor's own domain, in any letter case.                                                                                         |
| `disk-paths`                            | A path on the disk of one machine, such as a home folder. One corpus test is skipped.                                                |
| `shellcheck`                            | ShellCheck findings in shell scripts.                                                                                                |
| `prettier`                              | Markdown, YAML, and JSON that `prettier --check` rejects.                                                                            |
| `markdownlint`                          | Markdown that `markdownlint` rejects.                                                                                                |

## Know the format ratchet

The `prettier` and `markdownlint` hooks check files against `.prettierrc` and `.markdownlint.json`. Each hook has an `exclude:` list in `.pre-commit-config.yaml`. These two lists are the baseline. They name the files that fail today.

- A hook skips a file on its list.
- A hook checks every other file. A file that is clean today must stay clean.
- To bring a file under the check, format it with `prettier --write` or `markdownlint --fix`. Then delete its entry from the list.
- `tests/unit/test_ci_precommit.py` keeps the lists honest. Every entry must name a tracked file, and a file known to be clean must never be on a list.
- A planned reformat commit deletes both lists.
- `.prettierignore` keeps tool-written data out of Prettier: `assets.lock.json`, `cloudyreader/data/*.json`, and `tests/golden/*.yaml`.

## Read the CI workflow

The file `.github/workflows/ci.yml` defines the workflow `ci`. It has seven jobs. An eighth job, also named `ci`, is the gate. Branch protection requires only the gate job. It runs even when another job failed or was skipped. It passes only when all seven jobs succeeded.

| Item               | Value                                                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Triggers           | A pull request, a push to `main`, and a manual run                                                                        |
| Runners and limits | `macos-15` for `test`, 20 minutes. `ubuntu-24.04` for the rest: 10 minutes each, and 5 minutes for `guards` and the gate. |
| Permissions        | `contents: read`. No job widens it.                                                                                       |
| Concurrency        | A new push cancels the older run of a pull request. A run on `main` always finishes.                                      |
| Actions            | Pinned by commit SHA. Every checkout drops the token.                                                                     |
| Tools              | `uv` 0.9.28 and `pre-commit` 4.7.0. The `env` block pins the other tools.                                                 |
| Job environment    | `UV_MANAGED_PYTHON=1` and `UV_NO_PROGRESS=1` in every job that uses `uv`                                                  |

The seven jobs:

- **`guards`** runs `make guards`. The script `scripts/ci_guards.py` checks four rules. No tracked file names the vendor's own domain. `uv.lock` names public hosts only. No tracked file holds a machine disk path. No workflow uses the `pull_request_target` trigger. A finding prints as `path:line: [guard] problem`. On GitHub it also becomes an error annotation.
- **`lint`** installs only the `dev` group, so it needs no app dependencies. It runs `ruff check` and `ruff format --check`, a strict YAML parse of the files under `.github` (`scripts/ci_yaml.py`), ShellCheck, `actionlint`, and `zizmor` in offline mode.
- **`pre-commit`** runs every hook except `prettier` and `markdownlint`.
- **`format`** installs Prettier and markdownlint with `npm`, without install scripts. Then it runs the `prettier` and `markdownlint` hooks.
- **`test`** runs `make test` offline with `QT_QPA_PLATFORM=offscreen`. Then it writes the reports.
- **`docs`** runs `python3 scripts/check_site.py docs`. Then it builds the site with Jekyll. Nothing deploys: GitHub builds Pages from `main`.
- **`lock`** runs `uv lock --check`. It fails when `uv.lock` does not match `pyproject.toml`.

The CI run installs no models and no voices. Tests marked `model` or `voice` never run there.

### Find the reports

The `test` job writes two reports and a summary:

- **Step summary.** `scripts/ci_summary.py` prints Markdown to the step summary. It shows on the summary page of the run. It lists the tests (passed, failed, errors, skipped, and time), up to 20 failing test ids, and the coverage. The coverage part shows the total and the 25 files with the lowest coverage.
- **Artifact.** The artifact `test-reports` holds `junit.xml` and `coverage.xml`. GitHub keeps it for 14 days. The upload and the summary run after a failure too, but not after a cancel.
- **Annotations.** `ruff check` and the guards mark the failing line on the pull request.

### Run a job yourself

| Job                       | Run it with                                                                                                                   |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `guards`                  | `make guards`                                                                                                                 |
| `lint`                    | `make check` runs Ruff. `shellcheck` runs inside `make precommit`. The YAML parse, `actionlint`, and `zizmor` run only in CI. |
| `pre-commit` and `format` | `make precommit`                                                                                                              |
| `test`                    | `make test`                                                                                                                   |
| `docs`                    | `python3 scripts/check_site.py docs`                                                                                          |
| `lock`                    | `uv lock --check`                                                                                                             |

The command `make ci` runs `guards`, `check`, `test`, and `precommit`. It does not run `docs`, `lock`, or the CI-only lint steps.

## Update the documentation figures

The script `scripts/make_doc_snapshots.py` draws the SVG figures in `docs/assets/img` from the live window. Its docstring gives the exact command. Run it after a change to the window, then review the changed SVG files.
