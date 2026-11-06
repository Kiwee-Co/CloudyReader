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
# `build_app.sh release VERSION` (make release) zips the dist bundle and checks the zip itself.
#
# Env inputs: APP_NAME, ICON, KOKORO=auto|0|1, BUNDLE_VOICES=1|0, OUT, CLOUDYREADER_DATA_DIR (asset
# source, default .data), ENTRY=auto|app|probe, SELFTEST_TIMEOUT (s).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
APP_NAME=${APP_NAME:-Cloudy Reader}
ICON=${ICON:-}
KOKORO=${KOKORO:-auto}
BUNDLE_VOICES=${BUNDLE_VOICES:-1}
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
  resolve_bundle_voices
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
  mkdir -p -- "$ROOT/build" # a fresh clone has none until the first build
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
  say "entry: $ENTRY ($(basename -- "$ENTRY_SCRIPT")), icon: ${ICON_PATH:-PyInstaller default}"
  say "voices from $DATA/voices: ${names[*]}"
  say "voices and Kokoro model: $([[ $BUNDLE_VOICES == 1 ]] && echo "bundled" || echo "not bundled, downloaded at first launch")"
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

# The release zip's file name for version $1.
release_name() { printf '%s-%s-macos-arm64.zip' "${APP_NAME// /-}" "$1"; }

# The zip's SHA-256 beside it, as `<hash>  <file name>`: shasum's own format, the name only.
write_checksum() {
  local zip=$1
  (cd -- "$(dirname -- "$zip")" && shasum -a 256 "$(basename -- "$zip")") >"$zip.sha256"
}

# Fails when a zip holds macOS clutter: __MACOSX, .DS_Store or AppleDouble ._ files.
check_zip_clean() {
  local clutter
  clutter=$(zipinfo -1 "$1" | grep -E '(^|/)(__MACOSX|\.DS_Store|\._)' || true)
  [[ -z $clutter ]] || die "$(basename -- "$1") holds macOS clutter: $(head -n 5 <<<"$clutter" | tr '\n' ' ')"
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
  say "release: the build venv's cloudyreader metadata says $version"
}

# make release VERSION: zips the lean dist bundle with its SHA-256 (moving older ones aside), then
# checks the zip itself: unzipped, it must pass codesign, carry VERSION in its Info.plist and its
# --version, pass the voice audit and the seeded self-test. Never uploads anything.
release_main() {
  local version=${1:-} name zip check app plist shown size data printed
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must look like 1.2.3, got '$version'"
  resolve_out
  [[ -d $FINAL_APP ]] || die "no $FINAL_APP: make release builds it first"
  find_voices
  KOKORO_DIR=$DATA/models/kokoro
  name=$(release_name "$version")
  zip=$OUT/$name
  move_aside "$zip"
  move_aside "$zip.sha256"
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
  run_self_test release "$app" "$data"
  ((SELFTEST_RC == 0)) || die "the extracted copy's self-test exited $SELFTEST_RC (log: build/selftest-release.log)"
  say "release: the extracted copy passes codesign, the voice audit and the self-test"
  size=$(awk -v b="$(stat -f %z "$zip")" 'BEGIN { printf "%.1f", b / 1e6 }')
  say "release: $zip ($size MB), SHA-256 in $name.sha256; nothing was uploaded"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  case ${1:-} in
    release-preflight) release_preflight "${2:-}" ;;
    release) release_main "${2:-}" ;;
    *) main "$@" ;;
  esac
fi
