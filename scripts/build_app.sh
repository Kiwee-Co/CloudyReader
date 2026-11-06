#!/usr/bin/env bash
# Builds "Cloudy Reader.app" (Python, all dependencies, the scispaCy model, the OPSIN JRE, the
# Piper voices, Kokoro when available), ad-hoc signed for Apple Silicon. Never uses the network.
#
# Why PyInstaller 6 (one-folder BUNDLE, packaging/CloudyReader.spec), not py2app:
# - The spike (packaging/probe_app.py) ran frozen on the first build: PySide6 window, Piper with
#   onnxruntime and espeak-ng-data, scispaCy en_ner_craft_md, OPSIN on jdk4py's JRE, sqlite3, httpx.
# - collect_all() picks up spaCy's compiled modules that import each other from C, plus package
#   data and dist-info metadata; pyinstaller-hooks-contrib already covers onnxruntime and Qt.
# - jdk4py's java and dylibs land in Contents/Frameworks with their rpaths intact, so the JRE
#   survives `codesign --deep` and still starts.
# - The bootloader runs Python in-process: the Dock process is Contents/MacOS/<name> and the main
#   bundle resolves to com.cloudyreader.CloudyReader (probe check "identity").
# - One folder, not one file: nothing unpacks to a temp dir on each launch.
#
# BUNDLE_VOICES=0 builds the lean bundle of a release: no voice and no Kokoro model inside (the app
# downloads them at first launch), only assets.lock.json; an audit then proves it.
# START_QUESTIONS=1 copies the test-fixture questions into the bundle, so a dev app shows one at
# start (make app passes 1); 0, the default here and what make release passes, copies none.
# `build_app.sh release VERSION` (make release) zips the dist bundle, makes its DMG, checks both.
# `build_app.sh figures VERSION FILE` writes the sizes and SHA-256s a publish step reads.
#
# Env inputs: APP_NAME, ICON, KOKORO=auto|0|1, ENGINES=auto|0|1, BUNDLE_VOICES=1|0,
# START_QUESTIONS=0|1, OUT, CLOUDYREADER_DATA_DIR (asset source, default .data),
# ENTRY=auto|app|probe, SELFTEST_TIMEOUT and PROBE_TIMEOUT (s).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
APP_NAME=${APP_NAME:-Cloudy Reader}
ICON=${ICON:-}
KOKORO=${KOKORO:-auto}
ENGINES=${ENGINES:-auto}
BUNDLE_VOICES=${BUNDLE_VOICES:-1}
START_QUESTIONS=${START_QUESTIONS:-0}
OUT=${OUT:-dist}
DATA=${CLOUDYREADER_DATA_DIR:-$ROOT/.data}
ENTRY=${ENTRY:-auto}
SELFTEST_TIMEOUT=${SELFTEST_TIMEOUT:-300}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-120}
UV=${UV:-uv}
DISKUTIL=${DISKUTIL:-diskutil}
HDIUTIL=${HDIUTIL:-hdiutil}
export UV_CACHE_DIR=${UV_CACHE_DIR:-$ROOT/.cache/uv}

say() { printf 'build_app: %s\n' "$*"; }
die() {
  printf 'build_app: error: %s\n' "$*" >&2
  exit 1
}

# A new empty folder build/<prefix>.XXXXXX; prints its path.
fresh_dir() {
  mkdir -p -- "$ROOT/build"
  mktemp -d "$ROOT/build/$1.XXXXXX"
}

# Moves one file or folder from $ROOT/dist or $ROOT/build into a fresh build/trash.XXXXXX/:
# a same-volume rename, never a delete. A symlink moves itself, not its target.
move_aside() {
  local target=$1 name parent real trash
  name=$(basename -- "$target")
  case $name in '' | . | ..) die "refusing to move '$target'" ;; esac
  if [[ ! -e $target && ! -L $target ]]; then return 0; fi
  parent=$(cd -- "$(dirname -- "$target")" && pwd -P) || die "cannot resolve '$target'"
  real="$parent/$name"
  case $real in
    "$ROOT/dist/"* | "$ROOT/build/"*) ;;
    *) die "refusing to move outside $ROOT/dist and $ROOT/build: $real (move it yourself)" ;;
  esac
  trash=$(fresh_dir trash)
  mv -- "$real" "$trash/"
  say "moved the previous $name to ${trash#"$ROOT"/}/ (make clean-app frees build/)"
}

# APFS clone when possible (instant, no extra disk), else a plain copy.
copy_into() {
  cp -c -R -p -- "$1" "$2" 2>/dev/null || cp -R -p -- "$1" "$2"
}

now() { "$PY" -I -c 'import time; print(f"{time.time():.2f}")'; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.1f", b - a }'; }

preflight() {
  local name_re='^[A-Za-z0-9][A-Za-z0-9 ._-]*$'
  [[ $(uname -s) == Darwin ]] || die "macOS only, found $(uname -s)"
  [[ $(uname -m) == arm64 ]] || die "needs Apple Silicon (arm64), found $(uname -m)"
  [[ $APP_NAME =~ $name_re ]] || die "APP_NAME '$APP_NAME': use letters, digits, space, . _ -"
  [[ $SELFTEST_TIMEOUT =~ ^[0-9]+$ ]] || die "SELFTEST_TIMEOUT must be whole seconds"
  PY=$ROOT/.venv/bin/python
  [[ -x $PY ]] || die "no .venv: run 'make deps'"
  SPEC=$ROOT/packaging/CloudyReader.spec
  [[ -f $SPEC ]] || die "missing $SPEC"
  command -v codesign >/dev/null || die "codesign not found: run 'xcode-select --install'"
  "$PY" -I -c 'import importlib.util as u, sys; sys.exit(u.find_spec("en_ner_craft_md") is None)' ||
    die "scispaCy model en_ner_craft_md is not installed (run: make models)"
  "$PY" -I -c 'import PyInstaller' 2>/dev/null ||
    die "PyInstaller is not in .venv (run: make app, which syncs the packaging group)"
  PYI=("$UV" run --project "$ROOT" --frozen --offline pyinstaller)
  find_voices
}

# Piper voices to bundle: each .onnx that has its .onnx.json.
find_voices() {
  local onnx
  VOICES=()
  for onnx in "$DATA"/voices/*.onnx; do
    if [[ -f $onnx && -f $onnx.json ]]; then VOICES+=("$onnx"); fi
  done
  [[ ${#VOICES[@]} -gt 0 ]] || die "no Piper voice (.onnx + .onnx.json) in $DATA/voices (run: make voices)"
}

# Every Kokoro file in assets.lock.json is present in $DATA with its pinned size.
kokoro_assets_complete() {
  "$PY" -I - "$ROOT/assets.lock.json" "$DATA" <<'EOF'
import json, sys
from pathlib import Path

lock, data = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
want = [a for a in lock["assets"] if a["group"] == "kokoro"]
paths = [(data / Path(a["dest"]).relative_to(".data") / a["name"], a["size"]) for a in want]
sys.exit(0 if want and all(p.is_file() and p.stat().st_size == n for p, n in paths) else 1)
EOF
}

# assets.lock.json pins at least one engine's weights (scripts/pin_engine_assets.py writes them).
engines_pinned() {
  "$PY" -I - "$ROOT/assets.lock.json" <<'EOF'
import json, sys
from pathlib import Path

groups = {a["group"] for a in json.loads(Path(sys.argv[1]).read_text())["assets"]}
sys.exit(0 if groups & {"chatterbox_turbo", "qwen3_tts"} else 1)
EOF
}

# mlx-audio imports, and misaki's spaCy model is installed (misaki loads it at first use).
kokoro_extra_installed() {
  "$PY" -I -c 'import importlib.util as u, sys, mlx_audio
sys.exit(any(u.find_spec(m) is None for m in ("misaki", "en_core_web_sm")))' >/dev/null 2>&1
}

resolve_inputs() {
  local main_py=$ROOT/cloudyreader/__main__.py
  case $ENTRY in
    auto) if [[ -f $main_py ]] && grep -q -- '--self-test' "$main_py"; then ENTRY=app; else ENTRY=probe; fi ;;
    app) [[ -f $main_py ]] || die "ENTRY=app needs cloudyreader/__main__.py" ;;
    probe) ;;
    *) die "ENTRY must be auto, app or probe, got '$ENTRY'" ;;
  esac
  if [[ $ENTRY == app ]]; then ENTRY_SCRIPT=$ROOT/packaging/launcher.py; else ENTRY_SCRIPT=$ROOT/packaging/probe_app.py; fi
  resolve_icon
  resolve_kokoro
  resolve_engines
  resolve_bundle_voices
  resolve_start_questions
  resolve_out
  STAGE_APP=$ROOT/build/dist/$APP_NAME.app
}

# OUT, made absolute (relative to the repo root), and the bundle path inside it.
resolve_out() {
  if [[ $OUT != /* ]]; then OUT=$ROOT/$OUT; fi
  mkdir -p -- "$OUT"
  OUT=$(cd -- "$OUT" && pwd -P)
  FINAL_APP=$OUT/$APP_NAME.app
}

resolve_bundle_voices() {
  case $BUNDLE_VOICES in
    0 | 1) ;;
    *) die "BUNDLE_VOICES must be 0 or 1, got '$BUNDLE_VOICES'" ;;
  esac
}

resolve_start_questions() {
  case $START_QUESTIONS in
    0 | 1) ;;
    *) die "START_QUESTIONS must be 0 or 1, got '$START_QUESTIONS'" ;;
  esac
}

# ICON (a folder under assets/icons/, else the name in default.txt) -> ICON_PATH; empty means
# PyInstaller's default icon.
resolve_icon() {
  local icon_name=$ICON icon_re='^[A-Za-z0-9_-][A-Za-z0-9._-]*$'
  if [[ -z $icon_name && -f $ROOT/assets/icons/default.txt ]]; then
    icon_name=$(head -n 1 "$ROOT/assets/icons/default.txt" | tr -d '[:space:]')
  fi
  ICON_PATH=
  if [[ -z $icon_name ]]; then
    say "warning: no ICON and no assets/icons/default.txt: using PyInstaller's default icon"
  elif [[ ! $icon_name =~ $icon_re ]]; then
    die "ICON '$icon_name' must be a folder name under assets/icons/"
  elif [[ -f $ROOT/assets/icons/$icon_name/AppIcon.icns ]]; then
    ICON_PATH=$ROOT/assets/icons/$icon_name/AppIcon.icns
  else
    say "warning: assets/icons/$icon_name/AppIcon.icns is missing: using PyInstaller's default icon"
  fi
}

# KOKORO=auto|0|1 -> 0|1. auto includes Kokoro only when the extra and every pinned file exist.
resolve_kokoro() {
  KOKORO_DIR=$DATA/models/kokoro
  case $KOKORO in
    auto)
      KOKORO=0
      if [[ ! -d $KOKORO_DIR ]]; then
        say "kokoro: no $KOKORO_DIR: building without Kokoro"
      elif ! kokoro_extra_installed; then
        say "kokoro: mlx-audio, misaki or en_core_web_sm missing (run: make kokoro): building without Kokoro"
      elif ! kokoro_assets_complete; then
        say "warning: $KOKORO_DIR does not match assets.lock.json (run: make kokoro): building without Kokoro"
      else
        KOKORO=1
      fi
      ;;
    1)
      [[ -d $KOKORO_DIR ]] || die "KOKORO=1 but $KOKORO_DIR is missing (run: make kokoro)"
      kokoro_assets_complete || die "KOKORO=1 but $KOKORO_DIR does not match assets.lock.json (run: make kokoro)"
      kokoro_extra_installed || die "KOKORO=1 but mlx-audio, misaki or en_core_web_sm is missing from .venv (run: make kokoro)"
      ;;
    0) ;;
    *) die "KOKORO must be auto, 0 or 1, got '$KOKORO'" ;;
  esac
}

# ENGINES=auto|0|1 -> BUILD_ENGINES (0|1) for the first build. auto tries the engines only with
# Kokoro (they ride its extra) and with weights pinned in the lock (without, the app never offers
# them); build_staged then keeps them only if the probe passes.
resolve_engines() {
  case $ENGINES in
    auto)
      BUILD_ENGINES=0
      if [[ $KOKORO != 1 ]]; then
        say "engines: not tried: they ride the kokoro extra (KOKORO=0)"
      elif ! engines_pinned; then
        say "engines: not tried: assets.lock.json pins no engine weights (make pin-engine)"
      else
        BUILD_ENGINES=1
      fi
      ;;
    1)
      [[ $KOKORO == 1 ]] || die "ENGINES=1 needs KOKORO=1: the engines ride the kokoro extra"
      BUILD_ENGINES=1
      ;;
    0) BUILD_ENGINES=0 ;;
    *) die "ENGINES must be auto, 0 or 1, got '$ENGINES'" ;;
  esac
}

# PyInstaller warnings that are expected and harmless on macOS, matched exactly after the
# timestamp. Every other line of PyInstaller's output, warning or error, still prints.
BENIGN_WARNINGS=(
  # filelock imports filelock._windows on every OS; its WinDLL("ntdll") runs only on Windows.
  "WARNING: Library ntdll required via ctypes not found"
  # transformers' import_utils probes CUDA with CDLL("libcudart.so"); macOS has no CUDA.
  "WARNING: Library libcudart.so required via ctypes not found"
)

# Prints the PyInstaller log $1 without the BENIGN_WARNINGS lines, then how many it hid.
show_pyinstaller_log() {
  BENIGN=$(printf '%s\n' "${BENIGN_WARNINGS[@]}") awk -v path="${1#"$ROOT"/}" '
    BEGIN {
      n = split(ENVIRON["BENIGN"], lines, "\n")
      for (i = 1; i <= n; i++) if (lines[i] != "") known[lines[i]] = 1
    }
    { msg = $0; sub(/^[0-9]+ /, "", msg) }
    msg in known { hidden++; next }
    { print }
    END {
      if (hidden) printf "build_app: %d known-benign PyInstaller warnings hidden; full log: %s\n", hidden, path
    }
  ' "$1"
}

build_bundle() {
  local t0 log=$ROOT/build/pyinstaller.log rc=0
  t0=$(now)
  mkdir -p -- "$ROOT/build" # a fresh clone has none until the first build
  say "PyInstaller $("${PYI[@]}" --version)" \
    "(entry: $ENTRY, kokoro: $KOKORO, engines: ${BUILD_ENGINES:-0})"
  # PyInstaller imports modules to scan them. The HF flags stop any import-time Hub download; the
  # other two mute transformers' notice that PyTorch is absent (only its tokenizers are used).
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    TRANSFORMERS_VERBOSITY=error TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    PYINSTALLER_CONFIG_DIR=$ROOT/build/pyinstaller-config \
    CR_ENTRY=$ENTRY_SCRIPT CR_APP_NAME=$APP_NAME CR_ICON=$ICON_PATH CR_KOKORO=$KOKORO \
    CR_ENGINES=${BUILD_ENGINES:-0} CR_START_QUESTIONS=$START_QUESTIONS \
    "${PYI[@]}" --noconfirm --log-level WARN --distpath "$ROOT/build/dist" \
    --workpath "$ROOT/build/work" "$SPEC" >"$log" 2>&1 || rc=$?
  show_pyinstaller_log "$log"
  ((rc == 0)) || die "PyInstaller exited $rc (log: build/pyinstaller.log)"
  [[ -x $STAGE_APP/Contents/MacOS/$APP_NAME ]] || die "PyInstaller made no $STAGE_APP"
  PYI_SECONDS=$(since "$t0")
}

# Runs the staged bundle's engine import probe (packaging/launcher.py hands it to
# cloudyreader/engines/bundle_probe.py), offline. On failure prints only the failing imports.
probe_engines() {
  local log=$ROOT/build/engines-probe.log pid rc=0 ticks=0 line
  CLOUDYREADER_PROBE=engines CLOUDYREADER_OFFLINE=1 HF_HUB_OFFLINE=1 \
    "$STAGE_APP/Contents/MacOS/$APP_NAME" >"$log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if ((ticks >= PROBE_TIMEOUT * 10)); then
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" || true
      say "engines: the probe timed out after ${PROBE_TIMEOUT}s (full output: build/engines-probe.log)"
      return 1
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$pid" || rc=$?
  if ((rc == 0)); then return 0; fi
  say "engines: the probe exited $rc; failing imports (full output: build/engines-probe.log):"
  while IFS= read -r line; do say "  $line"; done < <(grep '^FAIL ' "$log" || true)
  return 1
}

# The staged bundle: with the engines first when BUILD_ENGINES=1, kept only if the probe passes.
# Then ENGINES=auto rebuilds without them and ENGINES=1 stops the build.
build_staged() {
  build_bundle
  ((BUILD_ENGINES)) || return 0
  if probe_engines; then
    say "engines: the probe passed: engines stay in"
    return 0
  fi
  [[ $ENGINES == auto ]] || die "ENGINES=1 but the engine probe failed (log: build/engines-probe.log)"
  say "engines: the probe failed (above): rebuilding without them"
  BUILD_ENGINES=0
  build_bundle
}

# The engines' own folders under a bundle's Contents ($1) with their sizes, then their sum. Not
# transformers or tokenizers: Kokoro's mlx-audio ships them in every build. Symlinks count nothing.
engine_growth() {
  local contents=$1 dir bytes total=0 rows=() row
  while IFS= read -r -d '' dir; do
    bytes=$(find "$dir" -type f -exec stat -f %z {} + | awk '{ s += $1 } END { print s + 0 }')
    total=$((total + bytes))
    rows+=("$(awk -v b="$bytes" -v p="${dir#"$contents"/}" 'BEGIN { printf "%7.1f MB  %s", b / 1e6, p }')")
  done < <(find "$contents" -type d \( -name chatterbox_turbo -o -name qwen3_tts \) -prune -print0 |
    sort -z)
  say "engine folders: $(awk -v b="$total" 'BEGIN { printf "%.1f MB", b / 1e6 }') in ${#rows[@]} folders"
  if ((${#rows[@]})); then
    for row in "${rows[@]}"; do say "  $row"; done
  fi
}

# The lock always ships: the downloader reads it. Voices and the Kokoro model only with
# BUNDLE_VOICES=1; a lean bundle gets them at first launch.
add_assets() {
  local assets=$STAGE_APP/Contents/Resources/assets onnx
  mkdir -p -- "$assets"
  copy_into "$ROOT/assets.lock.json" "$assets/"
  [[ $BUNDLE_VOICES == 1 ]] || return 0
  mkdir -p -- "$assets/voices"
  for onnx in "${VOICES[@]}"; do
    copy_into "$onnx" "$assets/voices/"
    copy_into "$onnx.json" "$assets/voices/"
  done
  if [[ $KOKORO == 1 ]]; then
    mkdir -p -- "$assets/models"
    copy_into "$KOKORO_DIR" "$assets/models/"
  fi
}

# Piper's own package models, not voices: the Hebrew and Arabic diacritizers, which only voices
# of those languages load. Any other .onnx in a lean bundle fails the audit.
NOT_VOICES=(
  "Contents/Resources/piper/hebrew/nakdimon.onnx"
  "Contents/Resources/piper/tashkeel/model.onnx"
)

# Fails unless the bundle $1 is lean: no voices or models folder under assets, no .onnx.json, no
# .onnx outside NOT_VOICES, no .safetensors under an assets or models folder.
audit_voices() {
  local app=$1 path rel found=()
  for rel in Contents/Resources/assets/voices Contents/Resources/assets/models; do
    if [[ -e $app/$rel || -L $app/$rel ]]; then found+=("$rel"); fi
  done
  while IFS= read -r -d '' path; do
    rel=${path#"$app"/}
    case $rel in
      *.onnx.json) found+=("$rel") ;;
      *.onnx) [[ " ${NOT_VOICES[*]} " == *" $rel "* ]] || found+=("$rel") ;;
      */assets/*.safetensors | */models/*.safetensors) found+=("$rel") ;;
    esac
  done < <(find "$app" \( -type f -o -type l \) \( -name '*.onnx' -o -name '*.onnx.json' \
    -o -name '*.safetensors' \) -print0)
  if ((${#found[@]})); then
    die "voice binaries in the bundle (BUNDLE_VOICES=0 must ship none): $(printf '%s ' "${found[@]}")"
  fi
  say "voice audit: no voice binary in the bundle"
}

# Fails when the bundle $1 carries the test-fixture questions of a START_QUESTIONS=1 dev build.
audit_start_questions() {
  local app=$1 rel found=()
  for rel in Contents/Resources/start_questions Contents/Frameworks/start_questions; do
    if [[ -e $app/$rel || -L $app/$rel ]]; then found+=("$rel"); fi
  done
  if ((${#found[@]})); then
    die "test-fixture questions in the bundle (a release ships none): $(printf '%s ' "${found[@]}")"
  fi
  say "start-question audit: no test-fixture question in the bundle"
}

# Stops the build when the Info.plist is invalid or does not name the chosen icon.
check_bundle() {
  local plist=$STAGE_APP/Contents/Info.plist icon version macos
  plutil -lint -s "$plist" || die "PyInstaller wrote an invalid $plist"
  icon=$(plutil -extract CFBundleIconFile raw -o - "$plist" 2>/dev/null) ||
    die "Info.plist names no CFBundleIconFile"
  [[ -f $STAGE_APP/Contents/Resources/$icon ]] || die "the Info.plist icon is not in Contents/Resources: $icon"
  if [[ -n $ICON_PATH ]] && ! cmp -s -- "$ICON_PATH" "$STAGE_APP/Contents/Resources/$icon"; then
    die "Contents/Resources/$icon differs from $ICON_PATH"
  fi
  version=$(plutil -extract CFBundleShortVersionString raw -o - "$plist") || die "no CFBundleShortVersionString"
  macos=$(plutil -extract LSMinimumSystemVersion raw -o - "$plist") || die "no LSMinimumSystemVersion"
  say "Info.plist: version $version, macOS $macos or later, icon $icon"
}

sign_bundle() {
  local log=$ROOT/build/codesign.log
  # Ad-hoc: the app is not distributed, so no Developer ID and no notarization.
  if ! codesign --force --deep -s - "$STAGE_APP" >"$log" 2>&1; then
    tail -n 20 "$log" >&2
    die "codesign failed (log: build/codesign.log)"
  fi
}

install_bundle() {
  move_aside "$FINAL_APP"
  mv -- "$STAGE_APP" "$FINAL_APP"
  local log=$ROOT/build/codesign-verify.log
  if ! codesign --verify --deep --strict --verbose=2 "$FINAL_APP" >"$log" 2>&1; then
    cat "$log" >&2
    die "codesign --verify --deep --strict failed"
  fi
}

# Runs bundle $2 headless and offline on data folder $3 with the arguments after it, within
# SELFTEST_TIMEOUT. Sets BUNDLE_RC; the output goes to build/$1.log.
run_bundle() {
  local label=$1 app=$2 data=$3 pid ticks=0
  shift 3
  BUNDLE_RC=0
  CLOUDYREADER_DATA_DIR=$data CLOUDYREADER_OFFLINE=1 QT_QPA_PLATFORM=offscreen \
    "$app/Contents/MacOS/$APP_NAME" "$@" >"$ROOT/build/$label.log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if ((ticks >= SELFTEST_TIMEOUT * 10)); then
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" || true
      die "$label timed out after ${SELFTEST_TIMEOUT}s (log: build/$label.log)"
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$pid" || BUNDLE_RC=$?
}

# --self-test of bundle $2 on data folder $3: SELFTEST_RC, and the output in build/selftest-$1.log.
run_self_test() {
  run_bundle "selftest-$1" "$2" "$3" --self-test
  SELFTEST_RC=$BUNDLE_RC
}

# Runs the bundle headless with --self-test against this build's own data folder, offline.
self_test() {
  local run=$1 log=$ROOT/build/selftest-$1.log t0
  t0=$(now)
  run_self_test "$run" "$FINAL_APP" "$SELFTEST_DATA"
  SELFTEST_SECONDS[run]=$(since "$t0")
  if ((SELFTEST_RC != 0)); then
    tail -n 20 "$log" >&2
    die "self-test run $run exited $SELFTEST_RC (log: build/selftest-$run.log)"
  fi
  local detail
  # The app reports "voices/entities/audio" lines; the probe one JSON line.
  detail=$(grep -E '^(voices|entities|audio) ' "$log" | tr -s ' ' | paste -s -d ';' - || true)
  say "self-test run $run: ok in ${SELFTEST_SECONDS[run]}s: ${detail:-$(tail -n 1 "$log" | cut -c 1-160)}"
}

# A lean bundle carries no voice: give the self-test's data folder $1 the build host's voices and
# Kokoro model, as links. The app reads them where its download would have put them.
seed_selftest_data() {
  local data=$1 onnx
  mkdir -p -- "$data/voices"
  for onnx in "${VOICES[@]}"; do
    ln -s -- "$onnx" "$data/voices/"
    ln -s -- "$onnx.json" "$data/voices/"
  done
  if [[ -d $KOKORO_DIR ]]; then
    mkdir -p -- "$data/models"
    ln -s -- "$KOKORO_DIR" "$data/models/kokoro"
  fi
}

# A lean bundle on an empty data folder must give the documented "no voice installed" result:
# exit 2 and the FAIL line, with no traceback.
self_test_no_voice() {
  local app=$1 log=$ROOT/build/selftest-no-voice.log empty
  empty=$(fresh_dir selftest-empty)
  run_self_test no-voice "$app" "$empty"
  if ((SELFTEST_RC != 2)); then
    die "self-test on an empty data folder exited $SELFTEST_RC, expected 2 (no voice installed) (log: build/selftest-no-voice.log)"
  fi
  if grep -q 'Traceback (most recent call last)' "$log"; then
    die "self-test on an empty data folder printed a traceback (log: build/selftest-no-voice.log)"
  fi
  grep -q '^FAIL: no Piper voice installed$' "$log" ||
    die "self-test on an empty data folder did not print 'FAIL: no Piper voice installed' (log: build/selftest-no-voice.log)"
  say "self-test run 3 (empty data folder): no voice installed, exit 2, as documented"
}

summary() {
  local onnx names=()
  for onnx in "${VOICES[@]}"; do names+=("$(basename -- "$onnx" .onnx)"); done
  say "built: $FINAL_APP"
  say "size: $(du -sh -- "$FINAL_APP" | cut -f 1), PyInstaller ${PYI_SECONDS}s, total ${SECONDS}s"
  if [[ ${BUILD_ENGINES:-0} == 1 ]]; then engine_growth "$FINAL_APP/Contents"; fi
  say "entry: $ENTRY ($(basename -- "$ENTRY_SCRIPT")), icon: ${ICON_PATH:-PyInstaller default}"
  say "voices from $DATA/voices: ${names[*]}"
  say "voices and Kokoro model: $([[ $BUNDLE_VOICES == 1 ]] && echo "bundled" || echo "not bundled, downloaded at first launch")"
  say "kokoro: $([[ $KOKORO == 1 ]] && echo "included" || echo "not included")"
  say "engines: $([[ ${BUILD_ENGINES:-0} == 1 ]] && echo "included (the probe passed)" || echo "not included")"
  say "start questions: $([[ $START_QUESTIONS == 1 ]] && echo "bundled (a dev build)" || echo "not bundled")"
  say "self-test wall time: first ${SELFTEST_SECONDS[1]}s, second ${SELFTEST_SECONDS[2]}s"
  say "largest components (MB):"
  du -sk -- "$FINAL_APP"/Contents/Frameworks/* "$FINAL_APP"/Contents/Resources/* |
    sort -rn | head -n 10 | awk -F '\t' -v p="$FINAL_APP/Contents/" '
      { s = $2; if (index(s, p) == 1) s = substr(s, length(p) + 1); printf "  %7.1f  %s\n", $1 / 1024, s }'
}

main() {
  SECONDS=0
  SELFTEST_SECONDS=()
  preflight
  resolve_inputs
  build_staged
  add_assets
  check_bundle
  if [[ $BUNDLE_VOICES == 0 ]]; then audit_voices "$STAGE_APP"; fi
  sign_bundle
  install_bundle
  say "codesign: ad-hoc signature verified (--deep --strict)"
  # Both runs share one fresh folder: the second exercises links that already exist.
  SELFTEST_DATA=$(fresh_dir selftest-data)
  if [[ $BUNDLE_VOICES == 0 ]]; then seed_selftest_data "$SELFTEST_DATA"; fi
  self_test 1
  self_test 2
  if [[ $BUNDLE_VOICES == 0 ]]; then self_test_no_voice "$FINAL_APP"; fi
  summary
}

# A release file's name for version $1: the zip, or with $2=dmg the DMG.
release_name() { printf '%s-%s-macos-arm64.%s' "${APP_NAME// /-}" "$1" "${2:-zip}"; }

# A file's SHA-256 beside it, as `<hash>  <file name>`: shasum's own format, the name only.
write_checksum() {
  local file=$1
  (cd -- "$(dirname -- "$file")" && shasum -a 256 "$(basename -- "$file")") >"$file.sha256"
}

# Fails closed when app $1 carries a path of this build host (home, user name, build tree, data
# folder, their volume) in a raw file, zip member, PKG entry or decompressed PYZ module, or when it
# reads no PYZ module of Contents/MacOS/<APP_NAME>. Prints each file and count, never the match.
path_gate() {
  local app=$1 python=${PY:-$ROOT/.venv/bin/python} rc=0
  [[ -x $python ]] || python=$(command -v python3) # any Python reads files; a PKG needs PyInstaller
  "$python" -I - "$app" "$APP_NAME" "$HOME" "${USER:-$(id -un)}" "$ROOT" "$DATA" <<'EOF' || rc=$?
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

app, exe_name, home, user = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/"), sys.argv[4]
needles = set()
for place in (sys.argv[5], sys.argv[6]):  # the build tree and the data folder, links resolved
    resolved = Path(place).resolve()
    needles |= {str(resolved), str(resolved).removeprefix("/private")}  # /tmp is /private/tmp
    if len(resolved.parts) > 2 and resolved.parts[1] == "Volumes":
        needles.add(str(Path(*resolved.parts[:3])))  # the whole external volume
if home.count("/") >= 2:  # a real home folder; never "/" or ""
    needles.add(home)
if len(user) >= 4:  # a shorter user name would match by chance
    needles.add(user)
longest_first = sorted(needles, key=len, reverse=True)
pattern = re.compile(b"|".join(re.escape(n.encode()) for n in longest_first), re.IGNORECASE)
COOKIE = b"MEI\x0c\x0b\x0a\x0b\x0e"  # PyInstaller's CArchive cookie
EXE = os.path.join("Contents", "MacOS", exe_name)  # its PKG holds the PYZ the gate must read
found = 0
current = "the app"


def scan(data, where):
    global found
    hits = len(pattern.findall(data))
    if hits:
        print(f"build_app: path gate: {where}: {hits} hit(s)", flush=True)
        found += hits


def scan_pkg(path, rel):
    """Scans each PKG entry and each module of every PYZ in it; returns the modules read."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    from PyInstaller.loader.pyimod01_archive import PYZ_ITEM_NSPKG

    pkg = CArchiveReader(path)
    modules = 0
    for name, (*_, typecode) in pkg.toc.items():
        data = pkg.extract(name)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"PKG entry {name} gave no bytes")  # unread is not clean
        scan(bytes(data), f"{rel}!PKG:{name}")
        if typecode == "z" or bytes(data[:4]) == b"PYZ\0":
            with tempfile.NamedTemporaryFile(suffix=".pyz") as pyz_file:
                pyz_file.write(data)
                pyz_file.flush()
                pyz = ZlibArchiveReader(pyz_file.name)
                for module, (kind, *_) in pyz.toc.items():
                    raw = pyz.extract(module, raw=True)
                    if raw is None and kind == PYZ_ITEM_NSPKG:
                        continue  # a namespace package holds no data by design
                    if not isinstance(raw, (bytes, bytearray)):
                        raise TypeError(f"PYZ entry {module} gave no bytes")
                    scan(bytes(raw), f"{rel}!PYZ:{module}")
                    modules += 1
    return modules


def scan_app():
    """Scans every file of the app; returns the PYZ modules read from the executable's PKG."""
    global current
    read = 0
    for folder, _, names in os.walk(app):
        for name in sorted(names):
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            rel = current = os.path.relpath(path, app)
            with open(path, "rb") as fh:
                data = fh.read()
            scan(data, rel)
            if data[:4] == b"PK\x03\x04":
                with zipfile.ZipFile(path) as archive:
                    for member in archive.namelist():
                        scan(archive.read(member), f"{rel}!{member}")
            if COOKIE in data:
                modules = scan_pkg(path, rel)
                if rel == EXE:
                    read = modules
    return read


try:
    read = scan_app()
except (Exception, SystemExit) as exc:  # an archive the gate cannot read proves nothing
    print(f"build_app: path gate: cannot scan {current} ({type(exc).__name__}):",
          "the scan does not cover the app")
    sys.exit(2)
if not read:
    print(f"build_app: path gate: read no PYZ module in the PKG of {EXE}:",
          "the scan does not cover the app")
if found:
    print(f"build_app: path gate: {found} hit(s)")
elif read:
    print(f"build_app: path gate: no build host path in the app ({read} PYZ module(s) read)")
sys.exit(1 if found else 0 if read else 2)
EOF
  case $rc in
    0) ;;
    1) die "the app carries this build host's paths (above): it must not ship" ;;
    *) die "the path gate cannot prove the app clean (above): it must not ship" ;;
  esac
}

# Fails when a zip holds macOS clutter: __MACOSX, .DS_Store or AppleDouble ._ files.
check_zip_clean() {
  local clutter
  clutter=$(zipinfo -1 "$1" | grep -E '(^|/)(__MACOSX|\.DS_Store|\._)' || true)
  [[ -z $clutter ]] || die "$(basename -- "$1") holds macOS clutter: $(head -n 5 <<<"$clutter" | tr '\n' ' ')"
}

# diskutil image (macOS 26 and later) is the supported tool; older macOS has only hdiutil's verbs.
# The version decides first: the macOS 15 runner answered `image create from --help` with status 0
# and then had no such verb, so the probe alone chose a tool that could not make the image.
has_diskutil_image() {
  local major
  major=$(sw_vers -productVersion 2>/dev/null) || major=0
  major=${major%%.*}
  [[ $major =~ ^[0-9]+$ ]] && ((major >= 26)) && "$DISKUTIL" image create from --help >/dev/null 2>&1
}

# A read-only APFS image $2, lzfse-compressed (ULFO), of folder $1, its volume named $3. ULFO beat
# UDZO, ULMO and HFS+ on the v0.0.1 app: 429 MB, made in 7 s, checked in 2 s when opened.
create_dmg() {
  local stage=$1 dmg=$2 volume=$3 log=$ROOT/build/dmg-create.log
  if has_diskutil_image; then
    "$DISKUTIL" image create from --format ULFO --volumeName "$volume" "$stage" "$dmg" >"$log" 2>&1
  else
    say "release: $(basename -- "$dmg") made with hdiutil (this macOS has no diskutil image)"
    "$HDIUTIL" create -srcfolder "$stage" -volname "$volume" -fs APFS -format ULFO "$dmg" \
      >"$log" 2>&1
  fi || {
    tail -n 20 "$log" >&2
    die "could not make $(basename -- "$dmg") (log: build/dmg-create.log)"
  }
}

# The release DMG $2 of app $1, its volume named "<APP_NAME>". With dmgbuild in the build venv,
# packaging/dmg_layout.py styles the window (docs-ia's spec section 7). dmgbuild still drives
# hdiutil, whose create, attach and convert flags macOS 27 deprecates: a later macOS may break that
# path, and the plain image (diskutil image, hdiutil before it) stays the fallback.
make_dmg() {
  local app=$1 dmg=$2 stage icon name
  local custom_icon=0000000000000000040000000000000000000000000000000000000000000000
  name=$(basename -- "$dmg")
  stage=$(fresh_dir dmg-stage)
  ditto --norsrc --noextattr "$app" "$stage/$APP_NAME.app" # as in the zip: no forks, no xattrs
  icon=$(plutil -extract CFBundleIconFile raw -o - "$app/Contents/Info.plist" 2>/dev/null) || icon=
  icon=$app/Contents/Resources/${icon%.icns}.icns
  [[ -f $icon ]] || icon=
  PY=${PY:-$ROOT/.venv/bin/python}
  if "$PY" -I -c 'import dmgbuild' >/dev/null 2>&1; then
    "$PY" -I "$ROOT/packaging/dmg_layout.py" "$stage/$APP_NAME.app" "$dmg" "$icon" \
      >"$ROOT/build/dmg-create.log" 2>&1 || die "dmgbuild could not make $name (log: build/dmg-create.log)"
    say "release: $name: the window styled by dmgbuild"
    return
  fi
  say "release: $name is plain: dmgbuild is not in the build venv (make .cache/stamps/packaging)"
  # The app's icon as the volume icon: the FinderInfo custom-icon flag; diskutil keeps it, hdiutil
  # drops it (a cosmetic loss on macOS before diskutil image).
  ln -s /Applications "$stage/Applications"
  if [[ -n $icon ]]; then
    cp -- "$icon" "$stage/.VolumeIcon.icns"
    xattr -wx com.apple.FinderInfo "$custom_icon" "$stage"
  fi
  create_dmg "$stage" "$dmg" "$APP_NAME"
}

# One SHA-256 over a tree's files (content and mode), folders (mode) and links (target): two trees
# with the same digest hold the same app.
tree_digest() {
  (
    cd -- "$1" && {
      find . -type f -exec shasum -a 256 {} +
      find . \( -type f -o -type d \) -exec stat -f '%Lp %N' {} +
      find . -type l -exec stat -f '%N -> %Y' {} +
    } | LC_ALL=C sort | shasum -a 256 | cut -d ' ' -f 1
  )
}

# Ejects the image check_dmg attached, if any; the EXIT trap runs it however the checks end. Only
# a device that image_device confirmed reaches here, so the forced detach can hit nothing else.
eject_dmg() {
  if [[ -n ${DMG_DEVICE:-} ]]; then
    "$DISKUTIL" eject "$DMG_DEVICE" >/dev/null 2>&1 ||
      "$HDIUTIL" detach -force "$DMG_DEVICE" >/dev/null 2>&1 || true
    DMG_DEVICE=
  fi
}

# The whole-disk device in attach output $1, once diskutil confirms that it is a disk image.
image_device() {
  local device bus
  device=$(awk '/^\/dev\/disk[0-9]+[[:space:]]/ { print $1; exit }' <<<"$1")
  [[ -n $device ]] || return 1
  bus=$("$DISKUTIL" info -plist "$device" | plutil -extract BusProtocol raw -o - - 2>/dev/null) ||
    return 1
  [[ $bus == "Disk Image" ]] || return 1
  printf '%s\n' "$device"
}

# The mounted volume $1 of DMG $2: named "<APP_NAME>", holding only the app, an Applications link
# to /Applications, the volume icon, and dmgbuild's window layout and art when styled.
check_volume() {
  local mnt=$1 name=$2 entry volume
  while IFS= read -r -d '' entry; do
    case ${entry##*/} in
      "$APP_NAME.app" | Applications | .VolumeIcon.icns | .DS_Store | .background.tiff) ;;
      *) die "$name: unexpected ${entry##*/} on its volume" ;;
    esac
  done < <(find "$mnt" -mindepth 1 -maxdepth 1 -print0)
  [[ -L $mnt/Applications && $(readlink "$mnt/Applications") == /Applications ]] ||
    die "$name: no Applications link to /Applications on its volume"
  volume=$("$DISKUTIL" info -plist "$mnt" | plutil -extract VolumeName raw -o - -) || volume=
  [[ $volume == "$APP_NAME" ]] || die "$name: its volume is named '$volume', not '$APP_NAME'"
  say "release: $name: verified; volume $volume holds the app and an Applications link"
}

# hdiutil verify on DMG $1. Under load it can fail with EAGAIN ("Resource temporarily unavailable"),
# locally and on the macos-15 runner: that error alone gets a retry, 3 tries in all.
verify_dmg() {
  local dmg=$1 name log=$ROOT/build/dmg-verify.log try=1
  name=$(basename -- "$dmg")
  until "$HDIUTIL" verify "$dmg" >"$log" 2>&1; do
    if ((try == 3)) || ! grep -q 'Resource temporarily unavailable' "$log"; then
      tail -n 20 "$log" >&2
      die "$name: hdiutil verify failed (log: build/dmg-verify.log)"
    fi
    try=$((try + 1))
    say "release: $name: hdiutil verify hit EAGAIN (Resource temporarily unavailable);" \
      "try $try of 3 in 2 s"
    sleep 2
  done
}

# hdiutil verify on DMG $1, then mounts it read-only and unbrowsed at a fresh folder for
# check_volume; its app must pass codesign, print version $3 (data folder $4), pass the voice
# audit, and match the zip's copy $2. The volume is ejected however the checks end.
check_dmg() {
  local dmg=$1 copy=$2 version=$3 data=$4 name mnt out app printed
  name=$(basename -- "$dmg")
  verify_dmg "$dmg"
  mnt=$(fresh_dir dmg-mount)
  trap eject_dmg EXIT
  trap 'exit 130' INT TERM
  if has_diskutil_image; then
    out=$("$DISKUTIL" image attach --readOnly --nobrowse --mountPoint "$mnt" "$dmg" 2>&1)
  else
    out=$("$HDIUTIL" attach -readonly -nobrowse -noverify -mountpoint "$mnt" "$dmg" 2>&1)
  fi || die "$name: cannot attach it: $out"
  DMG_DEVICE=$(image_device "$out") ||
    die "$name: attached at $mnt, but no disk-image device was confirmed; eject it by hand: $out"
  check_volume "$mnt" "$name"
  app=$mnt/$APP_NAME.app
  if ! codesign --verify --deep --strict "$app" >"$ROOT/build/dmg-codesign.log" 2>&1; then
    tail -n 20 "$ROOT/build/dmg-codesign.log" >&2
    die "$name: codesign --verify --deep --strict failed on its app"
  fi
  run_bundle dmg-version "$app" "$data" --version
  printed=$(tail -n 1 "$ROOT/build/dmg-version.log")
  [[ $BUNDLE_RC == 0 && $printed == "$APP_NAME $version" ]] ||
    die "$name: its app's --version printed '$printed' (exit $BUNDLE_RC), not '$APP_NAME $version'"
  audit_voices "$app"
  [[ $(tree_digest "$app") == "$(tree_digest "$copy")" ]] ||
    die "$name: its app differs from the zip's copy"
  eject_dmg
  trap - EXIT INT TERM
  say "release: $name: its app passes codesign, --version and the voice audit," \
    "and matches the zip's copy"
}

# make release, before it builds: VERSION is well formed, and the build venv's own cloudyreader
# metadata already says VERSION. PyInstaller bundles that dist-info, and the About box and
# --version read it, so a stale venv would ship "Version 0.1.0" inside a 0.0.1 zip.
release_preflight() {
  local version=${1:-} have
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must look like 1.2.3, got '$version'"
  PY=$ROOT/.venv/bin/python
  have=$("$PY" -I -c 'import importlib.metadata as m; print(m.version("cloudyreader"))' 2>/dev/null) ||
    have=none
  [[ $have == "$version" ]] || die "the build venv's cloudyreader metadata says $have, not $version:" \
    "run the sync step first (online, public PyPI: make .cache/stamps/packaging kokoro)"
  # The Python's install path ships inside the app (PyInstaller bundles its sysconfig data).
  local prefix
  prefix=$("$PY" -I -c 'import sys; print(sys.base_prefix)' 2>/dev/null) || prefix=
  case ${prefix:-$HOME}/ in
    "${HOME%/}"/*)
      die "the build venv's Python lives under your home folder, and its path would ship" \
        "inside the app: build in a venv made from a Python outside \$HOME" \
        "(UV_PYTHON_INSTALL_DIR=/tmp/cloudyreader-uv-python uv python install 3.12.12)"
      ;;
  esac
  local tool
  for tool in "$HDIUTIL" "$DISKUTIL"; do
    command -v "$tool" >/dev/null || die "$tool not found: the release DMG needs it"
  done
  say "release: the build venv's cloudyreader metadata says $version"
}

# make release VERSION: zips the lean dist bundle with its SHA-256 (moving older ones aside), then
# checks the zip itself: unzipped, it must pass codesign, carry VERSION in its Info.plist and its
# --version, pass the voice and start-question audits and the seeded self-test. Then the DMG of
# that very copy, checked by check_dmg. Never uploads anything.
release_main() {
  local version=${1:-} name zip dmg check app plist shown size data printed
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must look like 1.2.3, got '$version'"
  resolve_out
  [[ -d $FINAL_APP ]] || die "no $FINAL_APP: make release builds it first"
  find_voices
  KOKORO_DIR=$DATA/models/kokoro
  name=$(release_name "$version")
  zip=$OUT/$name
  dmg=$OUT/$(release_name "$version" dmg)
  move_aside "$zip"
  move_aside "$zip.sha256"
  move_aside "$dmg"
  move_aside "$dmg.sha256"
  path_gate "$FINAL_APP"
  # --norsrc --noextattr: without them ditto adds an AppleDouble ._ file per extended attribute.
  ditto -c -k --keepParent --norsrc --noextattr "$FINAL_APP" "$zip"
  check_zip_clean "$zip"
  write_checksum "$zip"
  (cd -- "$OUT" && shasum -a 256 -c -s "$name.sha256") || die "$name does not match $name.sha256"

  check=$(fresh_dir release-check)
  ditto -x -k "$zip" "$check"
  app=$check/$APP_NAME.app
  if ! codesign --verify --deep --strict "$app" >"$ROOT/build/release-codesign.log" 2>&1; then
    tail -n 20 "$ROOT/build/release-codesign.log" >&2
    die "codesign --verify --deep --strict failed on the extracted copy"
  fi
  plist=$app/Contents/Info.plist
  shown=$(plutil -extract CFBundleShortVersionString raw -o - "$plist") || die "no version in $plist"
  [[ $shown == "$version" ]] ||
    die "the app says version $shown, not $version: bump pyproject.toml or pass VERSION=$shown"
  say "release: $name: version $shown, macOS $(plutil -extract LSMinimumSystemVersion raw -o - "$plist") or later"
  data=$(fresh_dir selftest-release)
  seed_selftest_data "$data"
  # The About box and --version read the bundled metadata, which the Info.plist does not show.
  run_bundle release-version "$app" "$data" --version
  ((BUNDLE_RC == 0)) || die "the extracted copy's --version exited $BUNDLE_RC (log: build/release-version.log)"
  printed=$(tail -n 1 "$ROOT/build/release-version.log")
  [[ $printed == "$APP_NAME $version" ]] ||
    die "the extracted copy's --version prints '$printed', not '$APP_NAME $version':" \
      "its bundled metadata is stale; run the sync step first, then make release again"
  say "release: the extracted copy's --version prints $printed"
  audit_voices "$app"
  audit_start_questions "$app"
  run_self_test release "$app" "$data"
  ((SELFTEST_RC == 0)) || die "the extracted copy's self-test exited $SELFTEST_RC (log: build/selftest-release.log)"
  say "release: the extracted copy passes codesign, the voice audit and the self-test"
  make_dmg "$app" "$dmg"
  write_checksum "$dmg"
  (cd -- "$OUT" && shasum -a 256 -c -s "$(basename -- "$dmg").sha256") ||
    die "$(basename -- "$dmg") does not match its .sha256"
  check_dmg "$dmg" "$app" "$version" "$data"
  size=$(awk -v b="$(stat -f %z "$zip")" 'BEGIN { printf "%.1f", b / 1e6 }')
  say "release: $zip ($size MB), SHA-256 in $name.sha256; nothing was uploaded"
  size=$(awk -v b="$(stat -f %z "$dmg")" 'BEGIN { printf "%.1f", b / 1e6 }')
  say "release: $dmg ($size MB), SHA-256 in $(basename -- "$dmg").sha256; nothing was uploaded"
}

# Bytes this release downloads at first launch: the dist app's own plan probe on its bundled lock
# and an empty data folder, offline. A group the build lacks is left out (the app never offers
# it); when this Mac skips a group the app holds (no room), the figure would undercount: stop.
download_bytes() {
  local data
  data=$(fresh_dir figures-data)
  CLOUDYREADER_PROBE=plan run_bundle figures-plan "$FINAL_APP" "$data"
  grep '^plan: ' "$ROOT/build/figures-plan.log" >&2 || true
  ((BUNDLE_RC != 3)) || die "this Mac's plan skips a group the app holds (above), so" \
    "DOWNLOAD_BYTES would undercount: build on a Mac with room for every group"
  ((BUNDLE_RC == 0)) || die "the app's plan probe exited $BUNDLE_RC (log: build/figures-plan.log)"
  tail -n 1 "$ROOT/build/figures-plan.log"
}

# The figures a publish step reads for version $1, written to $2 only once the zip and the DMG
# each match their .sha256: six KEY=value lines. APP_BYTES sums the dist app's regular files;
# DOWNLOAD_BYTES is the dist app's own first-launch plan (download_bytes).
release_figures() {
  local version=${1:-} out=${2:-} file sha bytes app_bytes download figures=()
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must look like 1.2.3, got '$version'"
  [[ -n $out ]] || die "usage: build_app.sh figures VERSION FILE"
  resolve_out
  [[ -d $FINAL_APP ]] || die "no $FINAL_APP: run make release first"
  for file in "$OUT/$(release_name "$version")" "$OUT/$(release_name "$version" dmg)"; do
    [[ -f $file && -f $file.sha256 ]] || die "no $file or its .sha256: run make release first"
    sha=$(shasum -a 256 "$file" | cut -d ' ' -f 1)
    [[ $sha == "$(cut -d ' ' -f 1 "$file.sha256")" ]] ||
      die "$(basename -- "$file") does not match its .sha256"
    bytes=$(stat -f %z "$file")
    figures+=("$bytes" "$sha")
  done
  app_bytes=$(find "$FINAL_APP" -type f -exec stat -f %z {} + |
    awk '{ s += $1 } END { printf "%.0f", s }')
  download=$(download_bytes) || exit 1
  [[ $download =~ ^[1-9][0-9]*$ ]] ||
    die "the first-launch plan downloads nothing ('$download'): check the app's assets.lock.json"
  printf 'APP_BYTES=%s\nZIP_BYTES=%s\nSHA256=%s\nDMG_BYTES=%s\nDMG_SHA256=%s\nDOWNLOAD_BYTES=%s\n' \
    "$app_bytes" "${figures[@]}" "$download" >"$out"
  say "release: figures for $version in $out"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  case ${1:-} in
    release-preflight) release_preflight "${2:-}" ;;
    release) release_main "${2:-}" ;;
    figures) release_figures "${2:-}" "${3:-}" ;;
    *) main "$@" ;;
  esac
fi
