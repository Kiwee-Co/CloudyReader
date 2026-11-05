---
title: "Settings and command line"
description: "Every command-line option, environment variable, and saved preference of Cloudy Reader."
sidebar:
  order: 6
---
This page lists every option the app reads. The app has no settings window. Its choices live in the window, in two environment variables, and in three command-line options, plus `-h` and `--help`.

The commands on this page are untested: CI does not run them.

## Start the app with options

A built app keeps its program inside the bundle. Run it by path, or pass options through `open`:

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --version
open -a "Cloudy Reader" --args --offline
```

`open --args` has no effect if the app is already running. Quit it first.

From a source checkout, after `make setup`:

```bash
CLOUDYREADER_DATA_DIR=.data .venv/bin/python -m cloudyreader --offline
```

`make run` starts the app with `CLOUDYREADER_DATA_DIR` set to `.data`. It passes no options.

## Use the command-line options

| Option | Effect |
| --- | --- |
| `--offline` | Same as `CLOUDYREADER_OFFLINE=1`. No lookup requests and no voice download. |
| `--self-test` | Reads a built-in sample with the first Piper voice. No window, no sound. Forces offline mode. |
| `--version` | Prints `Cloudy Reader` and the version, then exits. |
| `-h`, `--help` | Prints the usage text, then exits. |
| Any other argument | Goes to Qt untouched. Example: `-style fusion`. |

The app does not accept abbreviations. `--off` is not `--offline`: Qt receives it.

### Read the self-test report

The self-test builds a fresh offline service with an empty cache. It reads a sample question from the first installed Piper voice, then checks the WAV file.

| Report line | Content |
| --- | --- |
| First line | `Cloudy Reader <version> self-test` |
| `python` | The Python version. |
| `packages` | The versions of `piper-tts`, `spacy`, `scispacy`, `pyside6-essentials`, `py2opsin`, and `httpx`. A package without metadata shows `n/a`. |
| `voices` | How many voices the app found, and the voice it uses. With no Piper voice: `<n> found, no Piper voice`. |
| `entities` | `ner` if the science model tagged a probe sentence. `regex-only` if it did not. `unknown` if the service cannot say. |
| `audio` | The length of the audio and its peak, from 0 to 1 of full scale. |
| `wall` | The total time. |
| Last line | `PASS` on success. |

The check fails when the audio is shorter than 3.0 seconds or the peak is 0.01 or lower. A failure prints `FAIL: <reason>` on standard error.

| Exit code | Meaning |
| --- | --- |
| 0 | The self-test passed. |
| 1 | The self-test failed or raised an error. |
| 2 | No Piper voice is installed. |

## Set environment variables

| Variable | Read by | Effect | Default |
| --- | --- | --- | --- |
| `CLOUDYREADER_DATA_DIR` | The app | The data folder. A leading `~` expands. A relative path becomes absolute when the app starts. An empty or blank value is ignored. | `~/Library/Application Support/cloudyreader` |
| `CLOUDYREADER_OFFLINE` | The app | Offline mode. These values turn it on: `1`, `true`, `yes`, `on`, in any letter case. Any other value leaves it off. | Off |
| `HF_HUB_OFFLINE` | Set by the app | The app sets it to `1` when the Kokoro engine loads. You do not set it. | Not set |
| `QT_QPA_PLATFORM` | Qt | `offscreen` runs without a window. The tests and the build self-test use it. | Qt default |
| `OFFLINE` | `scripts/fetch_assets.py` | `1` makes the asset fetcher refuse downloads. | `0` |
| `CLOUDYREADER_SAMPLES_SRC` | `scripts/extract_samples.py` | The folder of sample PDFs. | None |

Build variables such as `KOKORO` and `ICON` are on [Build the app](/developer/building/).

## Know the built-in limits

The app does not read these values from the environment or from a file.

| Limit | Value |
| --- | --- |
| Total time for the name lookups of one reading | 2.5 seconds |
| Time for one lookup request | 4 seconds, within what is left of the total |
| Lookup request rate | 5 per second |
| Lookup cache life | 30 days for a found name, 1 day for a name not found |
| Longest name that a lookup may send | 256 characters |
| Download tries per file | 3, with waits of 2 and then 4 seconds between them |
| Age at which a leftover partial download is removed | 24 hours |
| Speaking speed | 1.0. The window has no speed control. |

## Know the saved preferences

The app saves these keys with Qt's `QSettings`. The organization name is `CloudyReader`. The application name is `Cloudy Reader`. On macOS, Qt stores them in `~/Library/Preferences/com.cloudyreader.Cloudy Reader.plist`. Read the values:

```bash
defaults read "com.cloudyreader.Cloudy Reader"
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `voice` | Text | Empty | The key of the voice you last chose, such as `piper:en_US-lessac-medium` or `kokoro:af_heart`. |
| `voice_rotation` | Text | `none` | The rotation mode: `none`, `round_robin`, `shuffle`, `us_shuffle`, `men_shuffle`, or `women_shuffle`. An unknown value reads as `none` and stays in the file. |
| `read_answer` | Boolean | `false` | The **Read answer line** checkbox. |
| `online_lookups` | Boolean | `true` | The **Online lookups** checkbox. |
| `geometry` | Binary | None | The window size and position. The app writes it when the window closes. |

The app writes the checkbox, voice, and rotation keys at once when you change them. It does not write them while it restores them at start.

To reset every key, quit the app and run `defaults delete "com.cloudyreader.Cloudy Reader"`.

## Find the folders

The data folder holds the voices, the models, and the caches. See [Offline and privacy](/manual/offline-and-privacy/) for the full list.
