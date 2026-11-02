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
## Piper voices for `make voices`, space-separated
VOICES ?= en_US-lessac-medium en_US-amy-medium en_US-ryan-medium en_GB-alan-medium
## 1 = never touch the network (uv --offline, downloads refused)
OFFLINE ?= 0
## yes = let `make clean-all` delete .venv and .cache
CONFIRM ?= no
## 1 = `make doctor` also checks PubChem and UniProt reachability
ONLINE ?= 0

export UV_CACHE_DIR := $(CURDIR)/.cache/uv
STAMPS := .cache/stamps
UV_NET = $(if $(filter 1,$(OFFLINE)),--offline)
# run, test, test-fast, check and fmt never touch the network.
UV_RUN = $(UV) run --frozen --offline
# -I: isolated mode for Python that reads downloaded files; bytecode goes to .cache/pycache.
PYTHON = python -I -X pycache_prefix=$(CURDIR)/.cache/pycache

# Pinned downloads: official host + SHA256, verified before anything uses them.
MODEL_VERSION := 0.5.4
MODEL_BASE := https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v$(MODEL_VERSION)
MODELS := en_ner_craft_md
MODEL_ARCHIVES := $(foreach m,$(MODELS),.data/models/$(m)/$(m)-$(MODEL_VERSION).tar.gz)
SHA256_en_ner_craft_md-0.5.4.tar.gz := 63ddbc8320c968e419148e4c10dad595cc601aadc6f35187a1340d147f706ab7
# Verified alternates: MODELS := en_ner_bc5cdr_md en_ner_jnlpba_md swaps in this pair.
SHA256_en_ner_bc5cdr_md-0.5.4.tar.gz := ffc73130a710edf851206199720cb2c744a043e032f5da6ba4bb36863deca778
SHA256_en_ner_jnlpba_md-0.5.4.tar.gz := 9a6f59629c1aa0d43643d3e0f786016766149b2ef622d4d7a08808c4a6d9cb11
# rhasspy/piper-voices at the commit (main, 2026-11-01) whose files matched the host's LFS SHA256.
VOICE_BASE := https://huggingface.co/rhasspy/piper-voices/resolve/b4e358ffcb232591bf73a540e70f7de528e4174a
SHA256_en_US-lessac-medium.onnx := 5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f
SHA256_en_US-lessac-medium.onnx.json := efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0
SHA256_en_US-amy-medium.onnx := b3a6e47b57b8c7fbe6a0ce2518161a50f59a9cdd8a50835c02cb02bdd6206c18
SHA256_en_US-amy-medium.onnx.json := 95a23eb4d42909d38df73bb9ac7f45f597dbfcde2d1bf9526fdeaf5466977d77
SHA256_en_US-ryan-medium.onnx := abf4c274862564ed647ba0d2c47f8ee7c9b717d27bdad9219100eb310db4047a
SHA256_en_US-ryan-medium.onnx.json := 44034c056cb15681b2ad494307c7f3f2e4499d1253c700c711fa0a4607ffe78d
SHA256_en_GB-alan-medium.onnx := 0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330
SHA256_en_GB-alan-medium.onnx.json := c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e
SHA256_en_GB-jenny_dioco-medium.onnx := 469c630d209e139dd392a66bf4abde4ab86390a0269c1e47b4e5d7ce81526b01
SHA256_en_GB-jenny_dioco-medium.onnx.json := a9a7a93a317c9a3cb6563e37eb057df9ef09c06188a8a4341b0fcb58cba54dd4
VOICE_FILES := $(foreach v,$(VOICES),.data/voices/$(v).onnx .data/voices/$(v).onnx.json)
# $(call voice_url,FILE) for FILE = <lang>_<REGION>-<name>-<quality>.onnx[.json]
voice_url = $(VOICE_BASE)/$(call voice_dir,$(subst -, ,$(firstword $(subst ., ,$(1)))))/$(1)
voice_dir = $(firstword $(subst _, ,$(word 1,$(1))))/$(word 1,$(1))/$(word 2,$(1))/$(word 3,$(1))

# fetch URL DEST SHA256 KIND OFFLINE: download into a new empty temp dir, verify, move, record.
# KIND=model needs a pin and a new or empty DEST dir; KIND=voice warns when no pin exists.
define FETCH_SH
set -euo pipefail
url=$$1; dest=$$2; pin=$$3; kind=$$4; offline=$$5
name=$$(basename "$$dest"); dir=$$(dirname "$$dest")
if [ "$$offline" = 1 ]; then echo "OFFLINE=1: $$dest is missing; re-run online" >&2; exit 1; fi
if [ "$$kind" = model ]; then
  [ -n "$$pin" ] || { echo "refusing $$name: no SHA256 pin in the Makefile" >&2; exit 1; }
  if [ -d "$$dir" ] && [ -n "$$(ls -A "$$dir")" ]; then echo "refusing: $$dir must be new and empty" >&2; exit 1; fi
fi
tmp=$$(mktemp -d "$${TMPDIR:-/tmp}/cloudyreader-dl.XXXXXX")
curl -fsSL --proto '=https' --tlsv1.2 --retry 3 -o "$$tmp/$$name" "$$url"
sum=$$(shasum -a 256 "$$tmp/$$name" | cut -d' ' -f1)
if [ -n "$$pin" ] && [ "$$sum" != "$$pin" ]; then echo "SHA256 mismatch for $$url: got $$sum, want $$pin (file left in $$tmp)" >&2; exit 1; fi
[ -n "$$pin" ] || echo "warning: no SHA256 pin for $$name; recorded $$sum (pin it as SHA256_$$name)" >&2
mkdir -p "$$dir"
mv "$$tmp/$$name" "$$dest"
rmdir "$$tmp"
[ -e .data/downloads.tsv ] || printf 'utc_time\turl\tsha256\tpath\n' > .data/downloads.tsv
printf '%s\t%s\t%s\t%s\n' "$$(date -u +%FT%TZ)" "$$url" "$$sum" "$$dest" >> .data/downloads.tsv
echo "fetched $$dest sha256=$$sum"
endef
export FETCH_SH

# doctor UV ONLINE VOICE...: read-only checks; exit 1 when a required item is missing.
define DOCTOR_SH
set -u -o pipefail
uvbin=$$1; online=$$2; shift 2
miss=0
ok() { printf '  ok    %-11s %s\n' "$$1" "$$2"; }
info() { printf '  info  %-11s %s\n' "$$1" "$$2"; }
need() { printf '  MISS  %-11s %s\n        fix: %s\n' "$$1" "$$2" "$$3"; miss=1; }
py=.venv/bin/python
pyq() { [ -x "$$py" ] && "$$py" -I -c "$$1" 2>/dev/null; }
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
if pyq 'import importlib.util, sys; sys.exit(importlib.util.find_spec("en_ner_craft_md") is None)'; then ok model "en_ner_craft_md installed"; else need model "en_ner_craft_md not installed" "make models"; fi
for v in "$$@"; do
  if [ -s ".data/voices/$$v.onnx" ] && [ -s ".data/voices/$$v.onnx.json" ]; then ok voice "$$v"; else need voice "$$v missing" "make voices"; fi
done
if command -v pre-commit >/dev/null 2>&1; then ok pre-commit "$$(pre-commit --version)"; else info pre-commit "optional, not installed: brew install pre-commit"; fi
info kokoro "pending kokoro-spike result"
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
if [ -e build ]; then rm -r build; fi
if [ -e dist ]; then rm -r dist; fi
if [ -e .cache/pycache ]; then rm -r .cache/pycache; fi
if [ -e cloudyreader/__pycache__ ]; then rm -r cloudyreader/__pycache__; fi
if [ -e tests/__pycache__ ]; then rm -r tests/__pycache__; fi
if [ -e tests/smoke/__pycache__ ]; then rm -r tests/smoke/__pycache__; fi
endef

.PHONY: help setup deps lock models voices kokoro doctor run test test-fast check fmt precommit \
        ci app clean clean-all FORCE

help: ## Show targets and overridable variables
	@echo "usage: make <target> [VAR=value ...]"
	@echo
	@echo "targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-z][a-z-]*:.*## / {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "variables:"
	@awk '/^## / {doc = substr($$0, 4); next} /^[A-Z_]+ [?]= / {split($$0, kv, " [?]= "); printf "  %-8s %s (default: %s)\n", kv[1], doc, kv[2]} {doc = ""}' $(MAKEFILE_LIST)

setup: $(STAMPS)/deps $(STAMPS)/models $(STAMPS)/voices ## deps + models + voices, idempotent via .cache/stamps/

deps: $(STAMPS)/deps ## Sync .venv to uv.lock (uv sync --frozen --inexact)
ifneq ($(filter deps,$(MAKECMDGOALS)),)
$(STAMPS)/deps: FORCE
endif
# --inexact keeps the scispaCy model that `make models` installs outside uv.lock.
$(STAMPS)/deps: pyproject.toml uv.lock
	$(UV) sync --frozen --inexact $(UV_NET)
	@mkdir -p $(@D) && touch $@

lock: ## Re-resolve uv.lock from pyproject.toml (network unless OFFLINE=1)
	$(UV) lock $(UV_NET)

models: $(STAMPS)/models ## scispaCy model: pinned official URL, SHA256 check, install into .venv

$(STAMPS)/models: $(STAMPS)/deps $(MODEL_ARCHIVES)
	$(UV) pip install $(UV_NET) --python .venv/bin/python --no-deps $(MODEL_ARCHIVES)
	@mkdir -p $(@D) && touch $@

.data/models/%.tar.gz:
	bash -c "$$FETCH_SH" fetch "$(MODEL_BASE)/$(notdir $@)" $@ "$(SHA256_$(notdir $@))" model "$(OFFLINE)"

voices: $(VOICE_FILES) ## Piper voices into .data/voices; skips existing; VOICES=... overrides

$(STAMPS)/voices: $(VOICE_FILES)
	@mkdir -p $(@D) && touch $@

.data/voices/%.onnx:
	bash -c "$$FETCH_SH" fetch "$(call voice_url,$(notdir $@))" $@ "$(SHA256_$(notdir $@))" voice "$(OFFLINE)"

.data/voices/%.onnx.json:
	bash -c "$$FETCH_SH" fetch "$(call voice_url,$(notdir $@))" $@ "$(SHA256_$(notdir $@))" voice "$(OFFLINE)"

kokoro: ## Kokoro/MLX-Audio engine, Apple Silicon only (stub: pending kokoro-spike)
	@if [ "$$(uname -m)" != arm64 ]; then echo "kokoro: needs Apple Silicon (arm64), found $$(uname -m)" >&2; exit 1; fi
	@echo "pending kokoro-spike result"

doctor: ## Read-only health report; exit 1 with the exact fix when a required item is missing
	@bash -c "$$DOCTOR_SH" doctor "$(UV)" "$(ONLINE)" $(VOICES)

run: ## Launch the app (uv run python -m cloudyreader), offline
	$(UV_RUN) $(PYTHON) -m cloudyreader

test: ## All tests with coverage floor COV_MIN, offline
	$(UV_RUN) $(PYTHON) -m pytest --cov=cloudyreader --cov-report=term-missing --cov-fail-under=$(COV_MIN)

test-fast: ## Tests not marked slow or network: no models, no network
	$(UV_RUN) $(PYTHON) -m pytest -q -m "not slow and not network"

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

app: ## Build dist/cloudyreader.app via scripts/build_app.sh (stream E), else print pending
	@if [ -f scripts/build_app.sh ]; then bash scripts/build_app.sh; else echo "pending: scripts/build_app.sh (stream E) not written yet"; fi

clean: ## Remove caches and build artifacts; never .data/ or .venv/
	$(CLEAN_CMDS)

clean-all: ## clean, plus .venv and .cache; needs CONFIRM=yes; never .data/
	@echo "clean-all removes: .pytest_cache .ruff_cache .coverage htmlcov build dist __pycache__ .venv .cache"
	@if [ -d .cache ]; then echo "  .cache holds: $$(ls -A .cache | tr '\n' ' ')"; fi
	@if [ "$(CONFIRM)" != yes ]; then echo "refusing: re-run as 'make clean-all CONFIRM=yes'" >&2; exit 1; fi
	$(CLEAN_CMDS)
	if [ -e .venv ]; then rm -r .venv; fi
	if [ -e .cache ]; then rm -r .cache; fi

FORCE:
