---
title: "Offline and privacy"
description: "What stays on your Mac, what uses the network, how to work offline, and where the app stores files."
sidebar:
  order: 5
---
Speech runs on your Mac. This page lists the two cases where the app uses the network, what each one sends, and how to stop both.

The commands on this page are untested: CI does not run them.

## See what stays on your Mac

These steps run locally: parsing, name detection, the OPSIN name check, pronunciation rules, speech synthesis, and playback. The science (NER) model and the Java runtime for OPSIN are part of the app.

## See what uses the network

| Feature | Host | When it runs | What it sends |
| --- | --- | --- | --- |
| Name lookup | `pubchem.ncbi.nlm.nih.gov` | **Online lookups** is on and offline mode is off. A chemical name is not in the lexicon, not in the cache, and not parsed by OPSIN. | The name, in the URL path. |
| Name lookup | `rest.uniprot.org` | The same conditions, for a protein or gene name. | The name, as a query value. |
| Voice download | `huggingface.co`, then any HTTPS host that it redirects to | Pinned voice files are missing and offline mode is off. | A GET request for each missing file. |

No other code in the app opens a network connection.

### Know what a lookup sends

- The name only. Never the question text around it, and never a formula.
- A name that is empty, has non-printable characters, or is longer than 256 characters is not sent.
- Over HTTPS only. The app does not follow redirects.
- The app sets two request headers: `Accept: application/json` and `User-Agent: cloudyreader/<version>`. The HTTP library adds its standard headers.
- No account, no key, and no installation id.
- At most 5 requests per second.

The remote service sees your IP address and the time of the request, like any web request. For what the answers change, see [Pronunciation](/manual/pronunciation/).

### Know what a voice download sends

A plain GET request for each missing file, with `Accept-Encoding: identity` and `User-Agent: cloudyreader-prefetch/0.1`. The app follows at most 5 redirects and requires HTTPS on each. See [Voices and rotation](/manual/voices/).

### Know what Kokoro does

When the Kokoro engine loads, the app sets `HF_HUB_OFFLINE=1` in its own process. The speech library then never reaches for Hugging Face by itself. Only the download above uses that host.

## Work offline

Choose one way. The flag and the variable stop both the lookups and the voice download.

| Way | How |
| --- | --- |
| Command-line flag | Start the app with `--offline`. |
| Environment variable | Set `CLOUDYREADER_OFFLINE` to `1`, `true`, `yes`, or `on`, in any letter case. |
| Checkbox | Clear **Online lookups**. This stops the lookups only. The app remembers the choice. |

Quit the app, then start it with the flag:

```bash
open -a "Cloudy Reader" --args --offline
```

In offline mode:

- PubChem and UniProt receive no request. The lookup stage answers from the cache and from OPSIN.
- The voice download sends no request and creates no folder.
- Everything else works as usual. The self-test always runs in offline mode.

On a Mac with no network and no offline flag, a lookup fails and the reading continues. The app caches nothing for that name.

## Know what the app collects

The app has no telemetry, analytics, crash reporting, or update check. It sends no usage data. The only requests are the two above.

The app reads the clipboard text only when you ask it to paste. Use **Paste**, **Speak Clipboard**, or Cmd+V.

The app writes log lines for warnings to standard error. It does not save them to a file. Start the app from Terminal to read them:

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader"
```

## Find your files

The data folder is `~/Library/Application Support/cloudyreader`. Set `CLOUDYREADER_DATA_DIR` to use another folder. Finder hides Library. Choose Go > Go to Folder and paste the path.

| Item | Location | Content |
| --- | --- | --- |
| Piper voices | `voices/` | A `.onnx` file and a `.onnx.json` file per voice. A built app links them to its bundle. |
| Kokoro files | `models/kokoro/` | `config.json`, `kokoro-v1_0.safetensors`, and `voices/*.safetensors`. A built app links them to its bundle. |
| Audio cache | `cache/wav/` | One WAV file per distinct reading. The file name is a SHA-256 value. |
| Lookup cache | `cache/resolutions.sqlite` | The names you looked up, the kind and the status of each, the resolved name when a lookup found one, the ids, the source, and an expiry time. SQLite may add `-wal` and `-shm` files. |
| Download staging | `.prefetch/` | Partial downloads with the suffix `.part`. |
| Preferences | `~/Library/Preferences/com.cloudyreader.Cloudy Reader.plist` | Window position, voice, rotation mode, and the two checkboxes. |

### Clean up

- The audio cache holds audio of every question you read. It has no size limit and no cleanup. To remove it, quit the app and delete the `cache/wav` folder.
- The lookup cache removes expired rows when the app starts. To remove it all, quit the app and delete `cache/resolutions.sqlite` and its `-wal` and `-shm` files.
- A download run removes `.part` files that are older than 24 hours.
- To reset the preferences, quit the app and run `defaults delete "com.cloudyreader.Cloudy Reader"`.
- Deleting `voices/` or `models/` removes the voices only until the next start. At every start, a built app links its bundled voices again. The download fetches each other missing pinned file, unless offline mode is on.
