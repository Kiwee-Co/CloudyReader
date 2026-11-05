---
title: "Test and CI"
description: "The test gates, the markers, the coverage floor, the live smoke checks, and the CI workflow."
sidebar:
  order: 13
---
The commit gate is `make ci`. It runs the lint check, the tests with a coverage floor, and the pre-commit hooks. The required status check `ci` runs the same command.

The commands on this page are untested: CI does not run them.

## Run the gates

| Command | What it runs |
| --- | --- |
| `make check` | `ruff check .` and `ruff format --check .` |
| `make test` | The gate tests with coverage. It fails below the floor of 75 percent. |
| `make test-fast` | The quick tests, with no coverage report. No models, no network. |
| `make precommit` | `pre-commit run -a`. If `pre-commit` is missing, it prints how to install it and exits 0. |
| `make ci` | `check`, then `test`, then `precommit`. |
| `make fmt` | `ruff format .` and `ruff check --fix .` |

`make test` runs the equivalent of this command. The Makefile adds `python -I` and a bytecode folder:

```bash
uv run --frozen --offline python -m pytest \
  -m "not model and not voice and not network and not java" \
  --cov=cloudyreader --cov-report=term-missing --cov-fail-under=75
```

Change the floor with `make test COV_MIN=80`. The default lives in the `Makefile`.

## Use the markers

`pyproject.toml` declares five markers. The setting `--strict-markers` makes pytest fail on an unknown marker.

| Marker | The test needs | Created by |
| --- | --- | --- |
| `model` | The scispaCy model | `make models` |
| `voice` | A Piper voice | `make voices` |
| `network` | Internet access | Your network |
| `java` | A JVM, because it starts OPSIN | `make deps` (the bundled `jdk4py`) |
| `slow` | More than about a second | Nothing |

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

| Folder | Content |
| --- | --- |
| `tests/unit/` | Parser, normalizer, formulas, units, respelling, lexicon, entities, engines, TTS service, voices, rotation, voice profiles, download, config, audio, and the bundle helpers. `tests/unit/resolvers/` covers HTTP, cache, PubChem, UniProt, OPSIN, and the chain. |
| `tests/gui/` | Qt tests with `pytest-qt`: the main window, the voice picker, widgets, tokens, names, the app, the icon, rotation, and the download. |
| `tests/integration/` | The pipeline with fakes, the command line and self-test, and corpus guards. Some need a voice and a model. |
| `tests/smoke/` | Environment checks and the asset fetcher. |
| `tests/packaging/` | The build script and the bundle metadata. |
| `tests/data/` | Checks on the lexicon data. |
| `tests/golden/` | Golden cases. YAML files hold parse, spoken-script, respelling, and ambiguous cases. A `corpus/` folder holds TSV and text files. |
| `tests/fixtures/questions/` | 63 sample questions that mirror real paste shapes. |

To add a question fixture, create `tests/fixtures/questions/NN-category-topic-kind.txt`. The existing names show the pattern. One example is `01-earth-science-crustal-plates-mc.txt`. Each file holds the pasted text only.

### Write GUI tests

- `tests/conftest.py` and `tests/gui/conftest.py` set `QT_QPA_PLATFORM=offscreen`, so no window opens.
- A fixture points the default `QSettings` at a temporary folder. No test writes your preferences.
- The `make_window` fixture builds a `MainWindow` with `FakeReaderService`, `FakePlayer`, and `FakeClipboard`. It waits for the voice list.
- The fake service takes knobs: a delay, a gate, an error, warnings, and download events. Use the gate to hold a reading in flight.

## Run the live smoke checks

Two checks reach real hosts. They never run in CI. Run them outside any sandbox.

| Command | Checks |
| --- | --- |
| `make smoke-live` | The PubChem and UniProt response shapes that the resolvers parse. |
| `make smoke-voices` | The voice download. It asks for byte 0 of every pinned voice and Kokoro file. Then it fetches the small files (about 0.55 MB) and checks their SHA-256 values. It prints file names, statuses, and sizes, never a URL. It always exits 0, so read the verdict, not the exit code. |

`make doctor ONLINE=1` also probes PubChem and UniProt. `make doctor VERIFY=1` re-hashes every asset.

## Read the lint rules

`pyproject.toml` configures Ruff: line length 100, target `py312`, and rules `E`, `F`, `I`, `B`, and `UP`. Ruff skips `.cache` and `.data`. The file `.pre-commit-config.yaml` has two local hooks: `ruff check --fix` and `ruff format`. Both call `.venv/bin/ruff`, so run `make deps` before `pre-commit`.

## Read the CI workflow

The file `.github/workflows/ci.yml` defines the workflow `ci` with one job, `ci`.

| Item | Value |
| --- | --- |
| Triggers | A pull request to `main`, a push to `main`, and a manual run |
| Runner | `macos-15`, which is arm64 |
| Time limits | 25 minutes for the job and 15 minutes for the gate step |
| Permissions | `contents: read` |
| Concurrency | A new run cancels the older run of the same workflow and ref |
| Job environment | `UV_MANAGED_PYTHON=1` and `UV_NO_PROGRESS=1` |
| Tools | `uv` 0.9.28 and `pre-commit` 4.7.0 |

The job runs these 8 steps in order:

1. Check out the code. The workflow pins each action by commit SHA.
2. Scan the tracked files for a forbidden domain name. The step fails and lists the file and line of each hit.
3. Check the hosts in `uv.lock`. The step fails if the lock names a host other than `pypi.org`, `files.pythonhosted.org`, or `github.com`.
4. Set up `uv` with a cache keyed on `uv.lock`. The cache sits in `.cache/uv`, the folder that the Makefile uses.
5. Print the toolchain versions.
6. Install the locked dependencies with `uv sync --frozen`, then print the Python version.
7. Install `pre-commit` with `uv tool install`.
8. Run `make ci`. The step fails first if `pre-commit` is not on the `PATH`.

The CI run installs no models and no voices. Tests marked `model` or `voice` never run there.

## Update the documentation figures

The script `scripts/make_doc_snapshots.py` draws the SVG figures in `docs/assets/img` from the live window. Its docstring gives the exact command. Run it after a change to the window, then review the changed SVG files.
