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
# Env inputs: APP_NAME, ICON, KOKORO=auto|0|1, OUT, CLOUDYREADER_DATA_DIR (asset source, default
# .data), ENTRY=auto|app|probe, SELFTEST_TIMEOUT (s).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
APP_NAME=${APP_NAME:-Cloudy Reader}
ICON=${ICON:-}
KOKORO=${KOKORO:-auto}
OUT=${OUT:-dist}
DATA=${CLOUDYREADER_DATA_DIR:-$ROOT/.data}
ENTRY=${ENTRY:-auto}
SELFTEST_TIMEOUT=${SELFTEST_TIMEOUT:-300}
UV=${UV:-uv}
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

  if [[ $OUT != /* ]]; then OUT=$ROOT/$OUT; fi
  mkdir -p -- "$OUT"
  OUT=$(cd -- "$OUT" && pwd -P)
  STAGE_APP=$ROOT/build/dist/$APP_NAME.app
  FINAL_APP=$OUT/$APP_NAME.app
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
  say "PyInstaller $("${PYI[@]}" --version) (entry: $ENTRY, kokoro: $KOKORO)"
  # PyInstaller imports modules to scan them. The HF flags stop any import-time Hub download; the
  # other two mute transformers' notice that PyTorch is absent (only its tokenizers are used).
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    TRANSFORMERS_VERBOSITY=error TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    PYINSTALLER_CONFIG_DIR=$ROOT/build/pyinstaller-config \
    CR_ENTRY=$ENTRY_SCRIPT CR_APP_NAME=$APP_NAME CR_ICON=$ICON_PATH CR_KOKORO=$KOKORO \
    "${PYI[@]}" --noconfirm --log-level WARN --distpath "$ROOT/build/dist" \
    --workpath "$ROOT/build/work" "$SPEC" >"$log" 2>&1 || rc=$?
  show_pyinstaller_log "$log"
  ((rc == 0)) || die "PyInstaller exited $rc (log: build/pyinstaller.log)"
  [[ -x $STAGE_APP/Contents/MacOS/$APP_NAME ]] || die "PyInstaller made no $STAGE_APP"
  PYI_SECONDS=$(since "$t0")
}

add_assets() {
  local assets=$STAGE_APP/Contents/Resources/assets onnx
  mkdir -p -- "$assets/voices"
  for onnx in "${VOICES[@]}"; do
    copy_into "$onnx" "$assets/voices/"
    copy_into "$onnx.json" "$assets/voices/"
  done
  if [[ $KOKORO == 1 ]]; then
    mkdir -p -- "$assets/models"
    copy_into "$KOKORO_DIR" "$assets/models/"
  fi
  copy_into "$ROOT/assets.lock.json" "$assets/"
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

# Runs the bundle headless with --self-test against this build's own data folder, offline.
self_test() {
  local run=$1 log=$ROOT/build/selftest-$1.log t0 pid rc=0 ticks=0
  t0=$(now)
  CLOUDYREADER_DATA_DIR=$SELFTEST_DATA CLOUDYREADER_OFFLINE=1 QT_QPA_PLATFORM=offscreen \
    "$FINAL_APP/Contents/MacOS/$APP_NAME" --self-test >"$log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if ((ticks >= SELFTEST_TIMEOUT * 10)); then
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" || true
      die "self-test run $run timed out after ${SELFTEST_TIMEOUT}s (log: build/selftest-$run.log)"
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$pid" || rc=$?
  SELFTEST_SECONDS[run]=$(since "$t0")
  if ((rc != 0)); then
    tail -n 20 "$log" >&2
    die "self-test run $run exited $rc (log: build/selftest-$run.log)"
  fi
  local detail
  # The app reports "voices/entities/audio" lines; the probe one JSON line.
  detail=$(grep -E '^(voices|entities|audio) ' "$log" | tr -s ' ' | paste -s -d ';' - || true)
  say "self-test run $run: ok in ${SELFTEST_SECONDS[run]}s: ${detail:-$(tail -n 1 "$log" | cut -c 1-160)}"
}

summary() {
  local onnx names=()
  for onnx in "${VOICES[@]}"; do names+=("$(basename -- "$onnx" .onnx)"); done
  say "built: $FINAL_APP"
  say "size: $(du -sh -- "$FINAL_APP" | cut -f 1), PyInstaller ${PYI_SECONDS}s, total ${SECONDS}s"
  say "entry: $ENTRY ($(basename -- "$ENTRY_SCRIPT")), icon: ${ICON_PATH:-PyInstaller default}"
  say "voices from $DATA/voices: ${names[*]}"
  say "kokoro: $([[ $KOKORO == 1 ]] && echo "included" || echo "not included")"
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
  build_bundle
  add_assets
  check_bundle
  sign_bundle
  install_bundle
  say "codesign: ad-hoc signature verified (--deep --strict)"
  # Both runs share one fresh folder: the second exercises links that already exist.
  SELFTEST_DATA=$(fresh_dir selftest-data)
  self_test 1
  self_test 2
  summary
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
