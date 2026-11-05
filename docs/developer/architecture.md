---
layout: page
title: Architecture
nav_group: Developer
nav_order: 12
permalink: /developer/architecture/
description: How one pasted question becomes sound, and which module owns each step.
---

Cloudy Reader is a Python 3.12 package with a Qt window. One call, `Pipeline.prepare`, turns a paste into a `Reading`: the spoken script and a WAV file. Every stage is injected, so a test can swap any stage for a fake.

The commands on this page are untested: CI does not run them.

## Follow one reading

{% include figure.html src="pipeline.svg" alt="A pasted question moves through the parser, entity detection, and name lookups. Lookups try a local cache and OPSIN first. PubChem or UniProt over the network come last, unless you work offline. Next come the normalizer, respelling to IPA, a Piper or Kokoro voice, the WAV cache, and the afplay player. Voice files download once at start, unless you work offline. Everything else runs on the Mac." caption="From pasted text to sound. Boxes with a dashed blue border use the network." %}

The diagram runs left to right across the top row. It then runs right to left across the middle row and down to the player. A dashed arrow joins the voice download to the voice. The legend marks boxes that run on the Mac and boxes that use HTTPS.

`Pipeline.prepare(raw, voice_key, opts)` runs these steps in order:

1. **Guard.** Blank text raises `ValueError("nothing to read")`. The voice is looked up first, so a wrong key fails before any lookup.
2. **Parse.** `QuestionParser.parse` returns `Question` objects. It also takes bracket guides out of the stem and the choices and keeps them as `Respelling` objects. No question raises `ValueError("nothing to read")`.
3. **Detect.** `SciEntityDetector.detect` scans each stem and each choice. It scans the answer only when `read_answer` is on. It returns `EntitySpan` objects.
4. **Resolve.** `ChainResolver.resolve_many` looks up the first span of each unique text within `lookup_budget_s`. The pipeline uses the online resolver when `opts.online_lookups` is true and `settings.offline` is false. Otherwise it uses the offline twin: cache and OPSIN only.
5. **Normalize.** `ScriptNormalizer.to_script` builds a `SpokenScript`: segments, pauses, pronunciation overrides, and warnings. It makes one segment each for the header, the category, the format, the stem, and the answer. A choice makes two segments: its letter and its text. The letter segment carries its own pause, so the inserted silence does not depend on how a voice reads the period.
6. **Synthesize.** `TtsService.synthesize` returns an `Audio` from the WAV cache or from the engine.
7. **Collect notes.** The pipeline merges three lists: the normalizer warnings, the engine warnings from the last synthesis, and the engine's pre-check of the script. It removes duplicates and returns the `Reading`.

Detection, resolution, and the engine pre-check only refine the speech. If one fails, `_best_effort` logs a warning and adds the note `<stage> failed (<ErrorType>); continuing without it`. The reading goes on.

### Keep rule R5

The code states rule R5 in several modules: a resolution decides how a token is said, never which token is said. The pipeline hands resolutions to the normalizer only. It never reads a resolved name and never edits the questions or the script. The lexicon, the formula stage, and the normalizer follow the same rule.

## Map the modules

| Module | Role |
| --- | --- |
| `__main__.py` | The entry point. Parses the flags, runs the self-test, links bundled assets, builds the service, and starts the window. |
| `config.py` | `Settings` and `load_settings`. Reads `CLOUDYREADER_DATA_DIR` and `CLOUDYREADER_OFFLINE`. |
| `models.py` | The shared dataclasses and protocols. One module owns them. Everyone else imports. |
| `parser.py` | `QuestionParser` and `extract_guides`. Line- and regex-based. It never fails hard on odd input. |
| `entities.py` | `SciEntityDetector`: the scispaCy CRAFT model plus regexes for formulas, IUPAC-like names, gene symbols, enzymes, and proteins. |
| `resolvers/` | `chain.py` (`ChainResolver`), `opsin.py`, `pubchem.py`, `uniprot.py`, `http.py` (`HttpClient`), and `cache.py` (`ResolutionCache`). |
| `lexicon.py` | `Lexicon`: the token to IPA table, and IUPAC names built from morphemes. |
| `respell.py` | NSB respelling to IPA, driven by `data/respelling_rules.json`. |
| `units.py` | Number words, units, symbols, and the text preparation that both stages share. |
| `formulas.py` | Formulas, ions, scientific notation, exponents, ratios, and acronyms. |
| `spoken_fractions.py` | Fractions, mixed numbers, and fraction glyphs to words. `mark_fractions` runs before the unit stage, `say_marked` after it, and `speak_fractions` runs both for a say-as guide. |
| `normalize.py` | `ScriptNormalizer`: builds the segments, applies guides, and calls units, fractions, formulas, and the lexicon. |
| `tts.py` | `TtsService`: the engine registry and the content-addressed WAV cache. |
| `engines/` | `piper.py`, `kokoro.py`, and `misaki_ipa.py` (the IPA to misaki phoneme map). |
| `engines/padding.py` | `trim_letter_padding`: cuts a voice's own silence next to a choice letter, so the pause after a letter lasts about the same in every voice. |
| `voices.py` | Scans installed Piper voices. It also holds a catalog downloader, `VoiceManager`, that no app code calls. |
| `voice_meta.py` | Gender and accent of English voices, for rotation. Also the voice listing order: `ENGINE_ORDER` and `voice_sort_key`. |
| `rotation.py` | `RotationMode` and `VoiceRotator`. |
| `prefetch.py` | `VoicePrefetch`: the background voice download. |
| `frozen.py` | Support for a PyInstaller bundle: finds `Contents/Resources` and links bundled assets. |
| `audio.py` | `AfplayPlayer`: playback through `/usr/bin/afplay`. |
| `pipeline.py` | `Pipeline` and `build_default_service`. |
| `gui/` | `app.py`, `main_window.py`, `voice_picker.py`, `widgets.py`, `tokens.py`, `names.py`, and `fake_service.py`. |
| `data/` | The JSON tables. See below. |

## Know the data contracts

`models.py` defines these types:

| Type | Holds |
| --- | --- |
| `Question` | Kind, number, category, format, stem, choices, answer, raw text, and the guides found in the stem. |
| `Respelling` | A guide: the printed `surface`, the guide text, and a `kind` of `phonetic`, `spoken`, or `spell`. |
| `EntitySpan` | A detected name: offsets, text, a label, and a source of `ner` or `regex`. |
| `Resolution` | The answer to a lookup: kind, canonical name, ids, source, and a status of `ok`, `not_found`, `timeout`, `offline`, or `error`. |
| `Override` | An exact pronunciation: a `surface`, neutral General American IPA, and a source of `respelling`, `lexicon`, or `iupac`. |
| `Segment` | Text, a pause after it in milliseconds, and its overrides. |
| `SpokenScript` | Segments and warnings. `text()` joins the segment text. |
| `VoiceInfo` | Key, engine, name, language, quality, speaker count, installed flag, and path. |
| `RenderOptions` | `read_answer`, `speed`, `online_lookups`, and `speaker_id`. |
| `Audio` | The WAV path, sample rate, duration, and a cache-hit flag. |
| `Reading` | Questions, script, entities, resolutions, audio, and warnings. |

The protocols `Parser`, `EntityDetector`, `Resolver`, `Normalizer`, `TtsEngine`, `AudioPlayer`, and `ReaderService` describe what each part needs from the others.

## Know how pronunciation reaches the voice

An `Override` carries neutral IPA. The stress mark sits before the stressed syllable. There are no length marks. A stressed NURSE vowel is `ɜɹ`. Each engine converts the IPA.

- **Piper.** `to_piper_layout` moves stress marks to the espeak layout and adds the long vowels. `_usable_ipa` keeps only symbols in the voice's phoneme map and warns about the rest. The engine swaps each whole-word surface for an inline `[[ipa]]` block, longest surface first. Sentence marks move inside the block, because Piper drops punctuation after a block.
- **Kokoro.** `ipa_to_misaki` maps the IPA to the phoneme alphabet of Kokoro-82M. The engine marks each surface as `[surface](/phonemes/)`. A symbol outside the model vocabulary is rejected with a warning.

## Know the engines

| | Piper | Kokoro |
| --- | --- | --- |
| Class | `PiperEngine` | `KokoroEngine` |
| `available()` | The `piper` package is installed. | Apple Silicon, backend packages present, and model files with the pinned SHA-256 value. |
| `voices()` | Every `.onnx` plus `.onnx.json` pair in the voices folder. | 28 voices, each with its published grade. |
| Output | 16-bit mono WAV at the voice's sample rate. | 16-bit mono WAV at 24,000 Hz. |
| Version string | `piper-tts-<version>+r<render revision>` | `kokoro-82m@<revision>+misaki-ipa-2` |

Both engines write the pause after a segment as exact silence in the WAV file. That silence does not depend on the voice.

A voice can add its own silence around a line. Kokoro wraps each line in about 0.4 s of near silence, and Piper in a few milliseconds. Both engines call `trim_letter_padding` in `engines/padding.py` to cut that silence next to a choice letter.

`TtsService.voices()` sets the order of the **Voice** menu. Engines follow `ENGINE_ORDER` in `voice_meta.py`, Kokoro first and Piper last. Inside an engine, the best grade or tier comes first, then the name.

The voice picker selects the first installed voice when no saved voice applies.

`build_default_service` always registers Piper. It registers Kokoro only when `platform.machine()` is `arm64` and the module imports. Bump `_RENDER_REVISION` in `engines/piper.py` when rendering changes, so old cached WAV files stop matching.

## Know the WAV cache

`TtsService` keeps one WAV per distinct request in `cache/wav`. The file name is the SHA-256 value of a JSON object. The object holds the segments with their pauses and overrides, the voice key, the speed, the speaker, and the engine version. For Piper, the version also holds a fingerprint of the voice files, so a replaced voice renders again. Options that only shape the script are not in the key.

A change to the segments, including a pause length, gives a new file name. The app then renders the question again.

On a miss, the service writes to a temporary file in the same folder. Then it moves the file into place with `os.replace`. A reader never sees a half-written file. Nothing prunes the folder.

## Know the threads

| Thread | Started by | Work |
| --- | --- | --- |
| UI thread | Qt | The window, the signals, and a 150 ms poll that detects the end of playback. |
| One worker | `MainWindow`, a `QThreadPool` limited to one thread | `service.voices()` and `service.prepare(...)`, one call at a time. |
| `cloudyreader-prefetch` | `MainWindow._start_prefetch` | `VoicePrefetch.run`. A daemon thread that reports by queued signals. |
| `cloudyreader-preload` | `Pipeline.__init__` | Calls `detector.preload()` and ends. |
| `entities-preload` | `SciEntityDetector.preload` | Loads the NER model. `detect` waits for it. |
| `cloudyreader-lookup-N` | `ChainResolver` | Up to 16 daemon workers for one round of lookups. |

`AfplayPlayer` starts `afplay` as a child process, not as a thread. The process plays one clip. `stop` sends terminate, waits 2 seconds, then kills.

Locks guard the shared state. `_SYNTH_LOCK` in `engines/piper.py` covers Piper, because espeak keeps process-wide state. `TtsService._lock` covers the cache. The Kokoro backend holds one lock. The entity detector holds two: `_start_lock` guards the model start, and `_infer_lock` serializes inference.

## Know the window

`MainWindow(service, player, *, settings=None, clipboard=None, rotator=None, parent=None)` takes every collaborator as an argument, so tests pass fakes. The file `gui/fake_service.py` holds `FakeReaderService`, `FakePlayer`, and `FakeClipboard`. They do no synthesis, no network, and no audio. The tests set `QT_QPA_PLATFORM=offscreen`.

- **Layout.** The values live in `gui/tokens.py`, the only GUI file with raw numbers.
- **Rotation.** `_start` asks the `VoiceRotator` for a voice after every guard has passed. A pick replaces the voice key and clears the speaker. An empty pool keeps the picker voice and shows a warning.
- **Download.** After the first voice list, the window starts one daemon thread. The thread calls the service's `prefetch_voices(progress, cancel)`. A service without that hook gets no thread and no progress widgets.
- **Shutdown.** `closeEvent` sets the cancel event, saves the geometry, and stops playback. The window stops playback again at `aboutToQuit`, because `afplay` outlives the app.

## Know the data files

| File in `cloudyreader/data/` | Used by |
| --- | --- |
| `elements.json` | `units.py` and `formulas.py`: the 118 symbols and how to spell them. |
| `units.json` | `units.py` and `parser.py`: unit names with singular, plural, and aliases. |
| `symbols.json` | `units.py` and `formulas.py`: Greek letters, operators, arrows, exponent phrases, and number templates. |
| `ions_and_groups.json` | `formulas.py`: its keys supply the all-capital formulas that the app may spell without a digit. |
| `pronunciations.json` | `lexicon.py`: hard words with a respelling and IPA. |
| `iupac_morphemes.json` | `lexicon.py`: IUPAC name parts with a kind, a respelling, and IPA. |
| `respelling_rules.json` | `respell.py`: grapheme to IPA rules. |

## Change common things

| To change | Edit |
| --- | --- |
| A unit name or alias | `data/units.json` |
| A spoken symbol | `data/symbols.json` |
| A hard word | `data/pronunciations.json` (respelling and IPA) |
| An IUPAC name part | `data/iupac_morphemes.json` |
| A respelling sound | `data/respelling_rules.json` |
| An ion or group | `data/ions_and_groups.json` |
| An initialism spelled by letter | `_ACRONYMS` in `formulas.py` (the only list) |
| A gene symbol without a digit | `_KNOWN_GENES` in `entities.py` and `_GENE_SYMBOLS` in `formulas.py` |
| A pause length | The `*_MS` constants in `normalize.py` |
| A pinned voice | `assets.lock.json`, `PIPER_GENDERS` in `voice_meta.py` (for rotation), and `VOICES` in the `Makefile` |
| A new TTS engine | Implement `TtsEngine`, then register it in `_engines` in `pipeline.py` |

Run `make test` after each change.

## Preview a script without audio

The normalizer needs no voice, model, or network. This prints the words that a reading would speak:

```bash
.venv/bin/python -I - <<'PY'
from cloudyreader.models import RenderOptions
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import parse

paste = "TOSS-UP\n3) CHEMISTRY Short Answer Name the compound H2O."
script = ScriptNormalizer().to_script(parse(paste), {}, RenderOptions())
print(script.text())
PY
```

Expected output (untested):

```text
Toss-up number three. Chemistry. Short answer. Name the compound H two O.
```

## Run the whole pipeline from Python

This needs a voice in the data folder. Run `make voices` first.

```bash
CLOUDYREADER_DATA_DIR=.data .venv/bin/python -I - <<'PY'
from cloudyreader.config import load_settings
from cloudyreader.models import RenderOptions
from cloudyreader.pipeline import build_default_service

service = build_default_service(load_settings())
voice = next(v for v in service.voices() if v.installed)
paste = "TOSS-UP\n3) CHEMISTRY Short Answer Name the compound H2O."
reading = service.prepare(paste, voice.key, RenderOptions(online_lookups=False))
print(reading.script.text())
print(reading.audio.wav_path, reading.warnings)
PY
```

The script prints the spoken words, the path of the WAV file, and the tuple of warnings. It plays no sound. Play the file with `afplay` if you want to hear it.
