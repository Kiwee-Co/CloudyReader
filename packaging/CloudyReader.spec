# PyInstaller spec for "Cloudy Reader.app" (one-folder BUNDLE, arm64, ad-hoc signed later).
# scripts/build_app.sh drives it through env vars: CR_ENTRY (script), CR_APP_NAME, CR_ICON
# (an .icns path or empty for PyInstaller's default), CR_KOKORO (1 = bundle mlx-audio), CR_ENGINES,
# CR_START_QUESTIONS (1 = bundle the test-fixture questions: a dev build, never a release).
import os
import runpy
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 (PyInstaller injects SPECPATH)
APP_NAME = os.environ.get("CR_APP_NAME", "Cloudy Reader")
ENTRY = os.environ.get("CR_ENTRY", str(ROOT / "packaging" / "launcher.py"))
ICON = os.environ.get("CR_ICON") or None
KOKORO = os.environ.get("CR_KOKORO") == "1"
# Chatterbox Turbo and Qwen3-TTS ride the kokoro extra, so CR_ENGINES=1 counts only with Kokoro.
ENGINES = KOKORO and os.environ.get("CR_ENGINES") == "1"
START_QUESTIONS = os.environ.get("CR_START_QUESTIONS") == "1"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
COPYRIGHT = "Copyright © 2026 the Cloudy Reader authors."
MIN_MACOS_FLOOR = "11.0"  # PyInstaller's arm64 bootloader; a collected binary may need newer
min_macos = runpy.run_path(str(ROOT / "packaging" / "min_macos.py"))["min_macos"]

# Compiled spaCy/thinc extensions import each other from C, invisible to the import scan;
# the rest carry data (models, espeak-ng-data, the JRE, the OPSIN jar) or dist-info metadata.
# onnxruntime is left to its contrib hook: collect_all would add its model-export tools, which
# import Hugging Face transformers, torch and friends.
COLLECT_ALL = [
    "cloudyreader", "spacy", "thinc", "srsly", "cymem", "preshed", "blis", "murmurhash",
    "catalogue", "confection", "wasabi", "langcodes", "en_ner_craft_md", "piper",
    "jdk4py", "py2opsin", "inflect",
]
if KOKORO:
    # misaki's English G2P: espeak fallback via phonemizer, whose deps load JSON data at import.
    COLLECT_ALL += [
        "en_core_web_sm", "espeakng_loader", "phonemizer", "num2words", "segments", "csvw",
        "language_tags", "dlinfo",
    ]

# The NER model loads without scispacy (no registry entries in its config), so neither it nor its
# sklearn/nmslib stack ships (scipy only with Kokoro: mlx-audio needs it). Test-only packages never ship.
EXCLUDES = [
    "scispacy", "sklearn", "nmslib", "threadpoolctl",
    "onnxruntime.transformers", "onnxruntime.quantization", "onnxruntime.tools",
    "pytest", "_pytest", "pytestqt", "pytest_cov", "pytest_mock", "respx", "coverage", "ruff",
    "tkinter", "_tkinter", "IPython", "matplotlib",
    # Windows only: elsewhere it raises ImportError, which dateutil.tz catches. It loads user32.
    "dateutil.tz.win",
    # The DMG tools build the release image from the packaging group; they never ship in the app.
    "dmgbuild", "ds_store", "mac_alias",
]
if not KOKORO:
    EXCLUDES += ["mlx", "mlx_audio", "misaki", "scipy"]

# collect_all imports what it collects. Skipped: test suites, catalogue's backport for Python < 3.8
# (imports the absent zipp) and piper's training code (imports the absent torch).
SKIP_SUBMODULES = ("catalogue._importlib_metadata", "piper.train")


def _collectable(name: str) -> bool:
    skipped = any(name == skip or name.startswith(f"{skip}.") for skip in SKIP_SUBMODULES)
    return ".tests" not in name and not name.endswith(".tests") and not skipped


datas, binaries, hiddenimports = [], [], []
for package in COLLECT_ALL:
    d, b, h = collect_all(package, filter_submodules=_collectable)
    datas += d
    binaries += b
    hiddenimports += h

if KOKORO:
    # Kokoro + English only. Importing every mlx-audio/misaki submodule (collect_all) drags in
    # the other TTS/STT models, and some of them fetch weights from the Hugging Face Hub.
    d, b, h = collect_all("mlx", exclude_datas=["include/**"])
    datas += d + collect_data_files("misaki") + copy_metadata("mlx-audio") + copy_metadata("misaki")
    binaries += b
    hiddenimports += h + collect_submodules("mlx_audio.tts.models.kokoro")
    hiddenimports += ["mlx_audio.tts.utils", "misaki.en", "misaki.espeak"]
if ENGINES:
    # The two engines (engine_catalog imports them by name), their mlx-audio models and the
    # transformers tokenizer code they load by name; the metadata is what transformers checks at
    # import. Weights never ship: they download.
    hiddenimports += ["cloudyreader.engines.chatterbox_turbo", "cloudyreader.engines.qwen3_tts"]
    for package in (
        "mlx_audio.tts.models.chatterbox_turbo", "mlx_audio.tts.models.qwen3_tts",
        "transformers.models.auto", "transformers.models.qwen2", "transformers.models.gpt2",
    ):
        hiddenimports += collect_submodules(package)
    d, b, h = collect_all("tokenizers")
    datas += d
    binaries += b
    hiddenimports += h
    for dist in (
        "transformers", "tokenizers", "huggingface-hub", "safetensors", "regex", "packaging",
        "tqdm", "numpy", "pyyaml", "filelock",
    ):
        datas += copy_metadata(dist)
if START_QUESTIONS:
    # The app shows one of these in its empty question box at start; cloudyreader/start_question.py
    # reads them from Contents/Resources/start_questions, laid out as tests/fixtures is.
    fixtures = ROOT / "tests" / "fixtures"
    datas += [
        (str(path), "start_questions/questions")
        for path in sorted((fixtures / "questions").glob("*.txt"))
    ]
    datas.append((str(fixtures / "tossup_earth_science.txt"), "start_questions"))
a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
    # Override hooks for upstream ones whose hidden imports name modules gone from the lock.
    hookspath=[str(ROOT / "packaging" / "hooks")],
    # mlx-audio finds its model types by listing its own package folder: ship that as files too.
    module_collection_mode={"mlx_audio": "pyz+py"} if KOKORO else {},
    noarchive=False,
)
# pip's install-source record names the build tree or download folder as a file:// URL: never ship.
a.datas = [entry for entry in a.datas if not entry[0].endswith(".dist-info/direct_url.json")]
# The oldest macOS that loads every collected binary: wheel tags can understate it.
MIN_MACOS = min_macos((src for _, src, _ in a.binaries + a.datas), floor=MIN_MACOS_FLOOR)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    debug=False,
    strip=False,
    upx=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name=f"{APP_NAME}.app",
    icon=ICON,
    bundle_identifier="com.cloudyreader.CloudyReader",
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHumanReadableCopyright": COPYRIGHT,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.education",
    },
)
