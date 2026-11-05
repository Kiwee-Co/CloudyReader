---
title: "Get started"
description: "Requirements, install, first launch, and your first reading."
sidebar:
  order: 1
---
Cloudy Reader reads National Science Bowl questions aloud on your Mac. This page takes you from a built app to your first reading.

The commands on this page are untested: CI does not run them.

## Check the requirements

| Item | You need |
| --- | --- |
| Mac | Apple Silicon (arm64). The app is built for arm64 only. |
| macOS | 26.2 or later. This is the floor of the current build. |
| Sound | A working output device. The app plays audio with `/usr/bin/afplay`. |
| Disk space | About 63 MB for each Piper voice. About 342 MB for the Kokoro model and its 28 voices. |
| Network | Optional. Reading works offline. Name lookups and voice downloads need it. |

The build writes the oldest macOS version that loads every bundled file into `LSMinimumSystemVersion`. The value can change when the bundled libraries change. Read the value from your copy of the app:

```bash
defaults read "/Applications/Cloudy Reader.app/Contents/Info" LSMinimumSystemVersion
```

## Get the app

Build the app from source with `make app`. Follow [Build the app](/developer/building/). The build writes `dist/Cloudy Reader.app`. If someone gave you a built copy, go to the next step.

## Install the app

1. Copy `Cloudy Reader.app` to `/Applications`.
2. Open it from `/Applications`.

Copy the app before the first launch. On every start the app links its bundled voices and models into your data folder, `~/Library/Application Support/cloudyreader`. The links point into the app. If you move the app later, the next start repairs the links.

## Open the app for the first time

The build signs the app ad hoc. An ad-hoc signature uses no Apple Developer ID, and the app is not notarized. macOS reacts in two ways:

| How the app reached your Mac | What macOS does |
| --- | --- |
| You built it on this Mac. | The app opens normally. No download flag is set. |
| You downloaded it, or received it by AirDrop or chat. | macOS flags the file as quarantined. Gatekeeper blocks the first launch and says it cannot verify the app. |

This table describes macOS, not Cloudy Reader. The dialog wording differs between macOS versions.

To approve a blocked app:

1. Open the app once, then close the warning dialog.
2. Open **System Settings > Privacy & Security**.
3. Scroll to **Security**. Find the message about Cloudy Reader.
4. Click **Open Anyway**. Confirm with your password or Touch ID.
5. Open the app again and click **Open**.

Approve only an app that you built or that comes from a source you trust.

To check that nobody changed the bundle, verify its signature. Exit code 0 means the files match the signature:

```bash
codesign --verify --deep --strict --verbose=2 "/Applications/Cloudy Reader.app"
```

Do not edit files inside the bundle. Any change breaks the signature. The voice download refuses to write inside an app bundle.

## Know what the first start does

- The status bar shows "Loading voices…" while the app lists voices. The list can take a second because the app checks the Kokoro model file.
- The science model (NER) loads in the background. Your first reading waits for it. Later readings start faster.
- If voices are missing, the status bar shows "Downloading voices… N%". You can read with any voice that is already installed. See [Voices and rotation](/manual/voices/).

## Read your first question

1. Copy this sample question:

   ```text
   TOSS-UP
   2) EARTH SCIENCE Multiple Choice The source of energy for the movements of
   crustal plates is currently thought to be the result of:
   W) tidal motion that produces a net westward movement of landmasses
   X) the pulling apart of the poles resulting from the Earth’s rotation
   Y) convection currents produced within the mantle
   Z) remnant magnetism
   ```

2. Click the question box and press Cmd+V. Or click **Paste**.
3. Choose a voice in **Voice**.
4. Press **Speak** or Cmd+Return.
5. Listen. Then open **Spoken script** to read the words that were spoken.

The spoken script starts like this: "Toss-up number two. Earth Science. Multiple choice. The source of energy for the movements of crustal plates is currently thought to be the result of: W. tidal motion that produces a net westward movement of landmasses X. …"

## Check the install

The self-test reads a built-in sample with the first Piper voice. It opens no window and plays no sound. It forces offline mode.

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --self-test
```

The report looks like this. Values differ on your Mac:

```text
Cloudy Reader <version> self-test
python    <version>
packages  piper-tts <version>, spacy <version>, ...
voices    <count> found, using piper:<voice>
entities  ner
audio     <seconds> s, peak <0 to 1>
wall      <seconds> s
PASS
```

| Result | Exit code |
| --- | --- |
| The last line is `PASS`. | 0 |
| The self-test fails or raises an error. A line starting `FAIL:` appears on standard error. | 1 |
| No Piper voice is installed. The line `FAIL: no Piper voice installed` appears on standard error. | 2 |

The line `entities  regex-only` means the science model did not load. Reading still works, but the app finds fewer names. See [Troubleshooting](/manual/troubleshooting/).

## Next steps

- Learn the window: [Use the app](/manual/using-the-app/).
- Pick voices and rotation: [Voices and rotation](/manual/voices/).
- Fix a word that sounds wrong: [Pronunciation](/manual/pronunciation/).
- Work without a network: [Offline and privacy](/manual/offline-and-privacy/).
