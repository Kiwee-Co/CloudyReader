---
layout: page
title: Troubleshooting
nav_group: Manual
nav_order: 7
permalink: /manual/troubleshooting/
description: Fixes for start-up problems, missing voices, error messages, silence, and slow readings.
---

Find your symptom, check the cause, and apply the fix. Quoted messages are the text that the app shows in its status bar.

The commands on this page are untested: CI does not run them.

## Collect facts first

Run these commands in Terminal. They help you and the maintainers.

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --version
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --self-test
sw_vers -productVersion
```

The app writes warnings to standard error and keeps no log file. Start the app from Terminal to see them:

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader"
```

## Fix start-up problems

### Finder says the app needs a newer macOS

**Cause.** The app declares a minimum macOS version in `LSMinimumSystemVersion`. The current build declares 26.2.

**Fix.** Update macOS. The build takes the floor from the newest bundled library, so a rebuild lowers it only if the libraries change. Read the declared value:

```bash
defaults read "/Applications/Cloudy Reader.app/Contents/Info" LSMinimumSystemVersion
```

### macOS blocks the app or calls it damaged

**Cause.** The app has an ad-hoc signature and no notarization. macOS blocks a quarantined copy at the first launch. A "damaged" message can also mean that a file inside the bundle changed.

**Fix.** Follow [Get started]({{ '/manual/getting-started/' | relative_url }}) to approve the app. To test the bundle, run:

```bash
codesign --verify --deep --strict --verbose=2 "/Applications/Cloudy Reader.app"
```

If the command fails, copy the app again from a clean source, or rebuild it.

### The icon is wrong or old

**Cause.** Finder and the Dock cache app icons. A rebuild with another `ICON=` value can keep the old picture. A source run shows the icon named in `assets/icons/default.txt`. The default is `cloud-atom`.

**Fix.** Touch the app so Finder reloads it. Log out and in if the old icon stays.

```bash
touch "/Applications/Cloudy Reader.app"
```

## Fix voice problems

### The status bar says "No voice is installed."

**Cause.** The `voices` folder has no complete Piper pair (`.onnx` plus `.onnx.json`), and no Kokoro voice is usable.

**Fix.**

1. Check offline mode. It blocks the download. Remove `--offline`, and unset `CLOUDYREADER_OFFLINE`.
2. Wait for "Downloading voices… N%" to finish. See [Voices and rotation]({{ '/manual/voices/' | relative_url }}).
3. In a source checkout, run `make voices`.
4. If you set `CLOUDYREADER_DATA_DIR`, check that you look in the right folder.

### The Voice menu says "Voices unavailable"

**Cause.** The app failed to list the voices. The status bar shows `Error:` with the reason.

**Fix.** Start the app from Terminal and read the warning lines. They show the Python error behind the message.

### Kokoro voices are missing from the menu

**Cause.** The Kokoro engine lists its voices only when it can run. The app checks these conditions in this order:

| Check | What fails | Fix |
| --- | --- | --- |
| Apple Silicon | Kokoro needs an Apple Silicon Mac (arm64) | Use a Mac with Apple Silicon. |
| Python packages | Kokoro backend packages missing: `mlx`, `mlx_audio`, `misaki`, or `en_core_web_sm` | Build the app with Kokoro, or run `make kokoro` in a source checkout. |
| Model files | Kokoro model file missing: `config.json` or `kokoro-v1_0.safetensors` in `models/kokoro` | Wait for the download, or run `make kokoro`. |
| Model hash | SHA256 mismatch: the app refuses to load the file | Delete the file and restart. The download fetches it again. |

The app does not show the reason. A developer can read it in a source checkout:

```bash
.venv/bin/python -I - <<'PY'
from cloudyreader.config import load_settings
from cloudyreader.engines.kokoro import KokoroEngine

engine = KokoroEngine(load_settings().models_dir)
print(engine.available(), engine.unavailable_reason)
PY
```

Set `CLOUDYREADER_DATA_DIR` first if you use another data folder. The check hashes the model file, so it takes a moment.

### A Kokoro voice shows "not installed"

**Cause.** The model file exists, but the file for that voice is missing.

**Fix.** Wait for the download, or run `make kokoro`.

### "Some voices could not be downloaded. They are tried again at the next start."

**Cause.** One or more files failed after up to 3 attempts. Typical reasons are no network, an HTTP error, a short download, or a SHA-256 mismatch.

**Fix.** Hover over the status bar to read the file names. Check your network. Then quit the app and start it again. The app downloads only the missing files.

### The download does not start

**Cause.** One of these cases applies:

- Offline mode is on.
- The pinned list `assets.lock.json` is missing or invalid.
- All voices are present already.
- The Mac cannot run Kokoro, so the app skips the Kokoro files.
- A present file has a different size. The download leaves it untouched. Delete the file to fetch it again.

## Fix reading problems

### "Paste a question first." or "Clipboard is empty."

**Cause.** The question box or the clipboard holds only blank text.

**Fix.** Paste a question. Copy the text again if the clipboard is empty.

### "Error: nothing to read"

**Cause.** The parser found no question. This happens when the paste holds only noise, such as a round title or a page footer.

**Fix.** Paste the question text itself.

### "Error: voice … is not installed" or "Error: unknown voice …"

**Cause.** The chosen voice file is gone, or the voice list is out of date.

**Fix.** Choose another voice. Restart the app to rebuild the list.

### "Error: TTS engine 'kokoro' is unavailable (voice kokoro:…)"

**Cause.** You chose a Kokoro voice, but the Kokoro engine cannot run now. See "Kokoro voices are missing from the menu".

**Fix.** Choose a Piper voice, or fix the Kokoro cause.

### A word sounds wrong

**Fix.** Read the warning in the status bar. Add a guide after the word. See [Pronunciation]({{ '/manual/pronunciation/' | relative_url }}).

### A reading is slow

**Cause.** One of these cases applies:

- The first reading waits for the science model to load in the background.
- The first Kokoro reading loads the Kokoro model.
- Every reading with a new systematic chemical name starts the Java runtime for OPSIN once per lookup batch. Names in the lookup cache skip OPSIN.
- After an update that changes the script or its pauses, a question that you heard before renders once more.

**Fix.** Wait. The app loads each model once per start. A repeated name or a repeated reading skips the slow step.

### A reading waits a moment when lookups are on

**Cause.** A lookup may use up to 2.5 seconds. In this version, the answers do not change the sound.

**Fix.** Clear **Online lookups**, or start with `--offline`. See [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}).

## Fix sound problems

### The status bar says "Playing" but you hear nothing

**Cause.** The app plays audio with `/usr/bin/afplay`. It uses the macOS output device and volume.

**Fix.** Check **System Settings > Sound > Output** and the volume. Test the player:

```bash
afplay /System/Library/Sounds/Ping.aiff
```

### "Error: cannot run /usr/bin/afplay: …"

**Cause.** The `afplay` program is missing or blocked.

**Fix.** Check that `/usr/bin/afplay` exists. It ships with macOS.

### "Error: WAV not found: …"

**Cause.** The cached audio file disappeared before playback.

**Fix.** Press **Speak** again. Do not delete the `cache/wav` folder while the app runs.

## Read the self-test failures

| Line on standard error | Cause | Fix |
| --- | --- | --- |
| `FAIL: no Piper voice installed` (exit code 2) | The `voices` folder has no complete Piper pair. | Install a Piper voice. |
| `FAIL: audio too short: …` | The sample produced less than 3 seconds of audio. | Check the voice file and read the warnings. |
| `FAIL: audio too quiet: …` | The peak is 0.01 or lower. | Check the voice file. |
| `FAIL: WAV missing: …` or `FAIL: WAV unreadable: …` | The sample produced no usable file. | Check disk space and the cache folder. |
| `FAIL: <error type>: <message>` | A step raised an error. A traceback is above. | Read the traceback. |

The line `entities  regex-only` is not a failure. It means the science model did not load, so the app finds fewer names. Reinstall the model with `make models` in a source checkout, or rebuild the app.

## Reset the app

- To reset the choices, quit the app and run `defaults delete "com.cloudyreader.Cloudy Reader"`. See [Settings and command line]({{ '/manual/settings-and-cli/' | relative_url }}).
- To free disk space, quit the app and delete `cache/wav` in the data folder.
- To start from nothing, quit the app and delete the data folder, `~/Library/Application Support/cloudyreader`. This removes downloaded voices and all caches. At the next start, a built app links its bundled voices again. The download then fetches each other missing pinned voice, unless offline mode is on.

## Report a problem

Open an issue at <https://github.com/Kiwee-Co/CloudyReader/issues>. Include the app version, your macOS version, the self-test report, and the warning lines from Terminal. Remove any text that you do not want to share.
