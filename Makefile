# cloudyreader build helper. `make` lists targets and overridable variables.
.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
ifeq ($(MAKE_VERSION),3.81)
# macOS ships GNU Make 3.81: it ignores .SHELLFLAGS but honors flags inside SHELL.
SHELL := /bin/bash -eu -o pipefail
endif
.DELETE_ON_ERROR:

## uv executable
UV ?= uv
## coverage floor in percent for `make test`
COV_MIN ?= 75
## Piper voices for `make voices` (ids from assets.lock.json)
VOICES ?= en_US-lessac-medium en_US-amy-medium en_US-ryan-medium en_GB-alan-medium en_GB-jenny_dioco-medium
## 1 = never touch the network (uv --offline, downloads refused)
OFFLINE ?= 0
## yes = let `make clean-all` delete .venv and .cache
CONFIRM ?= no
## 1 = `make doctor` also checks PubChem and UniProt reachability
ONLINE ?= 0
## 1 = `make doctor` also checks each asset's SHA256
VERIFY ?= 0
## app bundle name for `make app`
APP_NAME ?= Cloudy Reader
## icon candidate for `make app` (empty: build_app.sh reads assets/icons/default.txt)
ICON ?=
## bundle the Kokoro engine in `make app`: auto, 0 or 1
KOKORO ?= auto
## output dir for `make app`
OUT ?= dist

export UV_CACHE_DIR := $(CURDIR)/.cache/uv
STAMPS := .cache/stamps
UV_NET = $(if $(filter 1,$(OFFLINE)),--offline)
# run, test, test-fast, check and fmt never touch the network.
UV_RUN = $(UV) run --frozen --offline
# -I: isolated mode for Python that reads downloads; bytecode goes to .cache/pycache.
PYTHON = python -I -X pycache_prefix=$(CURDIR)/.cache/pycache
# Stdlib-only fetcher: SHA256-checks every asset in assets.lock.json before use.
FETCH = $(UV) run --no-project --offline python -I scripts/fetch_assets.py
FETCH_NET = $(if $(filter 1,$(OFFLINE)),--offline)
GATE_MARKERS = not model and not voice and not network and not java
FAST_MARKERS = not slow and not network and not model and not voice and not java

run test test-fast samples smoke-live app: export CLOUDYREADER_DATA_DIR := $(CURDIR)/.data

# doctor UV ONLINE VERIFY VOICE...: read-only checks; exit 1 when a required item is missing.
define DOCTOR_SH
set -u -o pipefail
uvbin=$$1; online=$$2; verify=$$3; shift 3
miss=0
ok() { printf '  ok    %-11s %s\n' "$$1" "$$2"; }
info() { printf '  info  %-11s %s\n' "$$1" "$$2"; }
need() { printf '  MISS  %-11s %s\n        fix: %s\n' "$$1" "$$2" "$$3"; miss=1; }
py=.venv/bin/python
pyq() { [ -x "$$py" ] && "$$py" -I -c "$$1" 2>/dev/null; }
assets() { if [ -x "$$py" ]; then "$$py" -I scripts/fetch_assets.py "$$@"; else python3 -I scripts/fetch_assets.py "$$@"; fi; }
echo "cloudyreader doctor: read-only, installs nothing"
arch=$$(uname -m)
if [ "$$arch" = arm64 ]; then ok arch "arm64 (Kokoro/MLX capable)"; else info arch "$$arch: Kokoro/MLX needs arm64; Piper still works"; fi
if [ "$$(uname -s)" = Darwin ]; then ok macos "$$(sw_vers -productVersion)"; else need macos "$$(uname -s)" "run cloudyreader on macOS"; fi
if command -v "$$uvbin" >/dev/null 2>&1; then ok uv "$$("$$uvbin" --version)"; else need uv "$$uvbin not found" "brew install uv"; fi
want=$$(cat .python-version)
have=$$(pyq 'import platform; print(platform.python_version())' || true)
case "$$have" in
  "$$want".*) ok python "$$have in .venv" ;;
  "") need python ".venv missing or broken" "make deps" ;;
  *) need python "$$have in .venv, want $$want" "make clean-all CONFIRM=yes && make setup" ;;
esac
jre=$$(pyq 'import jdk4py; print(jdk4py.JAVA)' || true)
if [ -n "$$jre" ] && [ -x "$$jre" ]; then ok opsin-jre "jdk4py: $$("$$jre" -version 2>&1 | head -1)"
elif command -v java >/dev/null 2>&1 && java -version >/dev/null 2>&1; then info opsin-jre "jdk4py missing; system java: $$(java -version 2>&1 | head -1)"
else need opsin-jre "no JRE for OPSIN" "make deps (bundled jdk4py JRE), or: brew install openjdk"; fi
jar=$$(pyq 'import pathlib, py2opsin; print(next(pathlib.Path(py2opsin.__file__).parent.glob("opsin-cli-*.jar")).name)' || true)
if [ -n "$$jar" ]; then ok opsin-jar "$$jar"; else need opsin-jar "py2opsin OPSIN jar missing" "make deps"; fi
esp=$$(pyq 'import piper.espeakbridge as b; from piper.phonemize_espeak import ESPEAK_DATA_DIR as d; print(b.__file__, d)' || true)
if [ -n "$$esp" ]; then ok espeak-ng "bundled in piper-tts: $$esp"; else need espeak-ng "piper-tts espeakbridge missing" "make deps (system fallback: brew install espeak-ng)"; fi
if command -v afplay >/dev/null 2>&1; then ok afplay "$$(command -v afplay)"; else need afplay "not found" "afplay ships with macOS; no brew package exists"; fi
mode=--check; how="present, sizes match assets.lock.json"
if [ "$$verify" = 1 ]; then mode=--verify; how="present, SHA256 verified"; fi
if out=$$(assets "$$mode" --group models 2>&1); then ok models "$$how"; else need models "$$(grep -v '^ok' <<< "$$out" | head -3 | tr '\n' ' ')" "make models"; fi
if out=$$(assets "$$mode" --group voices --voices "$$@" 2>&1); then ok voices "$$# voice(s) $$how"; else need voices "$$(grep -v '^ok' <<< "$$out" | head -3 | tr '\n' ' ')" "make voices"; fi
if pyq 'import importlib.util, sys; sys.exit(importlib.util.find_spec("en_ner_craft_md") is None)'; then ok model-pkg "en_ner_craft_md installed in .venv"; else need model-pkg "en_ner_craft_md not installed" "make models"; fi
if [ "$$arch" = arm64 ]; then
  if out=$$(assets "$$mode" --group kokoro 2>&1); then ok kokoro "$$(grep -c '^ok' <<< "$$out") file(s) $$how"; else info kokoro "optional engine assets incomplete: make kokoro"; fi
  if pyq 'import importlib.util, sys; sys.exit(importlib.util.find_spec("mlx_audio") is None)'; then ok kokoro-pkg "mlx-audio installed"; else info kokoro-pkg "mlx-audio not installed (optional kokoro extra, pending)"; fi
fi
if command -v pdftotext >/dev/null 2>&1; then ok pdftotext "$$(command -v pdftotext)"; else info pdftotext "optional, for make samples: brew install poppler"; fi
if command -v pre-commit >/dev/null 2>&1; then ok pre-commit "$$(pre-commit --version)"; else info pre-commit "optional, not installed: brew install pre-commit"; fi
if [ "$$online" = 1 ]; then
  for pair in "pubchem|https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/water/cids/TXT" "uniprot|https://rest.uniprot.org/uniprotkb/search?query=insulin&size=1&fields=accession&format=tsv"; do
    code=$$(curl -s -o /dev/null --max-time 10 -w '%{http_code}' "$${pair#*|}" || true)
    if [ "$$code" = 200 ]; then ok "$${pair%%|*}" "reachable (HTTP 200)"; else info "$${pair%%|*}" "unreachable (HTTP $$code); lookups must degrade"; fi
  done
fi
if [ "$$miss" = 0 ]; then echo "doctor: all required items present"; else echo "doctor: required item(s) missing; run the fix lines above"; fi
exit "$$miss"
endef
export DOCTOR_SH

# Literal in-project paths only; never .data/, .venv/ or the rest of .cache/.
define CLEAN_CMDS
if [ -e .pytest_cache ]; then rm -r .pytest_cache; fi
if [ -e .ruff_cache ]; then rm -r .ruff_cache; fi
if [ -e .coverage ]; then rm .coverage; fi
if [ -e htmlcov ]; then rm -r htmlcov; fi
if [ -e dist ]; then rm -r dist; fi
if [ -e .cache/pycache ]; then rm -r .cache/pycache; fi
if [ -e cloudyreader/__pycache__ ]; then rm -r cloudyreader/__pycache__; fi
if [ -e tests/__pycache__ ]; then rm -r tests/__pycache__; fi
if [ -e tests/smoke/__pycache__ ]; then rm -r tests/smoke/__pycache__; fi
if [ -e scripts/__pycache__ ]; then rm -r scripts/__pycache__; fi
endef

# Literal paths: the default bundle only, whatever APP_NAME or OUT say.
define CLEAN_APP_CMDS
if [ -e "dist/Cloudy Reader.app" ]; then rm -r "dist/Cloudy Reader.app"; fi
if [ -e build ]; then rm -r build; fi
endef

.PHONY: help setup deps lock models voices kokoro doctor run test test-fast check fmt precommit \
        ci app icons open-icons samples smoke-live clean clean-app clean-all FORCE

help: ## Show targets and overridable variables
	@echo "usage: make <target> [VAR=value ...]"
	@echo
	@echo "targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-z][a-z-]*:.*## / {printf "  %-11s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "variables:"
	@awk '/^## / {doc = substr($$0, 4); next} /^[A-Z_]+ [?]=/ {val = substr($$0, index($$0, "?=") + 2); sub(/^ +/, "", val); printf "  %-9s %s (default: %s)\n", $$1, doc, (val == "" ? "empty" : val)} {doc = ""}' $(MAKEFILE_LIST)

setup: $(STAMPS)/deps $(STAMPS)/models $(STAMPS)/voices ## deps + models + voices, idempotent via .cache/stamps/

# A target named on the command line always re-runs; `make setup` uses the stamps.
ifneq ($(filter deps,$(MAKECMDGOALS)),)
$(STAMPS)/deps: FORCE
endif
ifneq ($(filter models,$(MAKECMDGOALS)),)
$(STAMPS)/models: FORCE
endif
ifneq ($(filter voices,$(MAKECMDGOALS)),)
$(STAMPS)/voices: FORCE
endif

deps: $(STAMPS)/deps ## Sync .venv to uv.lock (uv sync --frozen --inexact)

# --inexact keeps the scispaCy model that `make models` installs outside uv.lock.
$(STAMPS)/deps: pyproject.toml uv.lock
	$(UV) sync --frozen --inexact $(UV_NET)
	@mkdir -p $(@D) && touch $@

lock: ## Re-resolve uv.lock from pyproject.toml (network unless OFFLINE=1)
	$(UV) lock $(UV_NET)

models: $(STAMPS)/models ## scispaCy model via scripts/fetch_assets.py, then install into .venv

$(STAMPS)/models: $(STAMPS)/deps assets.lock.json scripts/fetch_assets.py
	$(FETCH) --group models $(FETCH_NET)
	$(UV) pip install $(UV_NET) --python .venv/bin/python --no-deps $$($(FETCH) --group models --paths)
	@mkdir -p $(@D) && touch $@

voices: $(STAMPS)/voices ## Piper voices via scripts/fetch_assets.py into .data/voices

$(STAMPS)/voices: $(STAMPS)/deps assets.lock.json scripts/fetch_assets.py
	$(FETCH) --group voices --voices $(VOICES) $(FETCH_NET)
	@mkdir -p $(@D) && touch $@

kokoro: ## Kokoro assets (arm64 only) via scripts/fetch_assets.py into .data/models/kokoro
	@if [ "$$(uname -m)" != arm64 ]; then echo "kokoro: needs Apple Silicon (arm64), found $$(uname -m)" >&2; exit 1; fi
	$(FETCH) --group kokoro $(FETCH_NET)

doctor: ## Read-only health report; exit 1 with the exact fix when a required item is missing
	@bash -c "$$DOCTOR_SH" doctor "$(UV)" "$(ONLINE)" "$(VERIFY)" $(VOICES)

run: ## Launch the app (uv run python -m cloudyreader), offline
	$(UV_RUN) $(PYTHON) -m cloudyreader

test: ## Gate: tests not marked model/voice/network/java, coverage floor COV_MIN
	$(UV_RUN) $(PYTHON) -m pytest -m "$(GATE_MARKERS)" --cov=cloudyreader --cov-report=term-missing --cov-fail-under=$(COV_MIN)

test-fast: ## Tests not marked slow/network/model/voice/java: no models, no network
	$(UV_RUN) $(PYTHON) -m pytest -q -m "$(FAST_MARKERS)"

check: ## ruff check + ruff format --check
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

fmt: ## ruff format + ruff check --fix
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .

precommit: ## pre-commit run -a, or print how to install pre-commit
	@if command -v pre-commit >/dev/null 2>&1; then pre-commit run -a; else echo "pre-commit not installed: brew install pre-commit (or: uv tool install pre-commit)"; fi

ci: ## Commit gate: check, then test, then precommit
	$(MAKE) --no-print-directory check
	$(MAKE) --no-print-directory test
	$(MAKE) --no-print-directory precommit

app: $(STAMPS)/deps $(STAMPS)/models $(STAMPS)/packaging ## Build dist/Cloudy Reader.app (self-contained, ad-hoc signed); ICON=<name> KOKORO=auto|0|1
	@case "$(KOKORO)" in auto|0|1) ;; *) echo "KOKORO must be auto, 0 or 1 (got '$(KOKORO)')" >&2; exit 1 ;; esac
	@if [ -f scripts/build_app.sh ]; then APP_NAME="$(APP_NAME)" ICON="$(ICON)" KOKORO="$(KOKORO)" OUT="$(OUT)" bash scripts/build_app.sh; else echo "pending: scripts/build_app.sh (pkg agent) not written yet; it builds \"$(OUT)/$(APP_NAME).app\""; fi

# After models, so two uv processes never write .venv at once under make -j.
$(STAMPS)/packaging: $(STAMPS)/models pyproject.toml uv.lock
	$(UV) sync --frozen --inexact --group packaging $(UV_NET)
	@mkdir -p $(@D) && touch $@

icons: ## Regenerate the 4 icon candidates and assets/icons/preview.png
	@if [ -f scripts/make_icons.py ]; then $(UV_RUN) $(PYTHON) scripts/make_icons.py; else echo "pending: scripts/make_icons.py (icons agent) not written yet"; fi

open-icons: ## Open assets/icons/preview.png
	@if [ -f assets/icons/preview.png ]; then open assets/icons/preview.png; else echo "assets/icons/preview.png missing: run make icons"; fi

samples: ## Extract NSB sample PDFs to .data/samples (scripts/extract_samples.py; needs pdftotext)
	@if [ -f scripts/extract_samples.py ]; then $(UV_RUN) $(PYTHON) scripts/extract_samples.py; else echo "pending: scripts/extract_samples.py (corpus agent) not written yet"; fi

smoke-live: ## Live PubChem + UniProt check (scripts/live_smoke.py); never in ci
	@echo "smoke-live needs internet access to PubChem and UniProt: run it OUTSIDE the agent sandbox."
	@if [ -f scripts/live_smoke.py ]; then $(UV_RUN) $(PYTHON) scripts/live_smoke.py; else echo "pending: scripts/live_smoke.py (s3o-opsin) not written yet"; fi

clean: clean-app ## Remove caches and build artifacts (runs clean-app); never .data/ or .venv/
	$(CLEAN_CMDS)

clean-app: ## Remove only "dist/Cloudy Reader.app" and build/
	$(CLEAN_APP_CMDS)

clean-all: ## clean, plus .venv and .cache; needs CONFIRM=yes; never .data/
	@echo "clean-all removes: .pytest_cache .ruff_cache .coverage htmlcov dist build .venv .cache"
	@if [ -d .cache ]; then echo "  .cache holds: $$(ls -A .cache | tr '\n' ' ')"; fi
	@if [ "$(CONFIRM)" != yes ]; then echo "refusing: re-run as 'make clean-all CONFIRM=yes'" >&2; exit 1; fi
	$(CLEAN_APP_CMDS)
	$(CLEAN_CMDS)
	if [ -e .venv ]; then rm -r .venv; fi
	if [ -e .cache ]; then rm -r .cache; fi

FORCE:
