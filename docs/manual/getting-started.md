---
layout: page
title: Get started
nav_group: Manual
nav_order: 1
permalink: /manual/getting-started/
description: Requirements, install, first launch, and your first reading.
---

Cloudy Reader reads National Science Bowl questions aloud on your Mac. This page takes you from the download to your first reading.

The commands on this page are untested: CI does not run them.

## Download the app

The release is a zip of 459 MB. It holds the app and no voices. The app downloads its voices the first time it opens. Check the [requirements](#check-the-requirements) first.

1. Open the [latest release page]({{ site.repo_url }}/releases/latest). Or use the direct link for version 0.0.1: [Cloudy-Reader-0.0.1-macos-arm64.zip]({{ site.repo_url }}/releases/download/v0.0.1/Cloudy-Reader-0.0.1-macos-arm64.zip).
2. Copy the hash from the Checksum section of the release page. Copy only the 64 characters after `SHA256`.
3. In Terminal, go to the folder that holds the zip. Replace the placeholder with the hash and run:

   ```bash
   echo "<SHA-256 from the release page>  Cloudy-Reader-0.0.1-macos-arm64.zip" | shasum -a 256 -c
   ```

   The output must read `Cloudy-Reader-0.0.1-macos-arm64.zip: OK`. Any other output means a damaged download: download the zip again.

4. Unzip the file: double-click it in Finder.
5. Move `Cloudy Reader.app` to `/Applications` before you open it.
6. Open the app for the first time. See [Open the app for the first time](#open-the-app-for-the-first-time).

## Check the requirements

| Item       | You need                                                                                                                 |
| ---------- | ------------------------------------------------------------------------------------------------------------------------ |
| Mac        | Apple Silicon (arm64). The app is built for arm64 only.                                                                  |
| macOS      | 26.2 or later. This is the floor of the current build.                                                                   |
| Sound      | A working output device. The app plays audio with `/usr/bin/afplay`.                                                     |
| Disk space | About 1.1 GB for the app and about 0.66 GB for the voices. The zip is 459 MB.                                            |
| Network    | Needed for the first launch, when the app downloads its voices. After that, reading works offline. Name lookups need it. |

The build writes the oldest macOS version that loads every bundled file into `LSMinimumSystemVersion`. The value can change when the bundled libraries change. Read the value from your copy of the app:

```bash
defaults read "/Applications/Cloudy Reader.app/Contents/Info" LSMinimumSystemVersion
```

## Open the app for the first time

The build signs the app ad hoc. An ad-hoc signature uses no Apple Developer ID, and the app is not notarized. macOS reacts in two ways:

| How the app reached your Mac                          | What macOS does                                                                                            |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| You built it on this Mac.                             | The app opens normally. No download flag is set.                                                           |
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
- The release holds no voices, so the download starts right after the voice list loads. The status bar shows "Downloading voices… N%". Until the first Piper voice lands, the Voice menu stays dimmed and the status bar says "No voice is installed." Then **Speak** works while the rest downloads.
- The download is about 0.66 GB: the 5 Piper voices first (about 316 MB), then Kokoro (about 342 MB). Keep the Mac online until it ends. The app tries a failed file again at the next start.
- With no network, no voice installs. Start the app again with a network. See [Voices and rotation]({{ '/manual/voices/' | relative_url }}).

## Read your first question

Wait until the first voice installs and the Voice menu is active.

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

The self-test reads a built-in sample with the first Piper voice. It opens no window and plays no sound. It forces offline mode. It needs an installed Piper voice, so on a new install wait for the first voice to land.

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

| Result                                                                                            | Exit code |
| ------------------------------------------------------------------------------------------------- | --------- |
| The last line is `PASS`.                                                                          | 0         |
| The self-test fails or raises an error. A line starting `FAIL:` appears on standard error.        | 1         |
| No Piper voice is installed. The line `FAIL: no Piper voice installed` appears on standard error. | 2         |

The line `entities  regex-only` means the science model did not load. Reading still works, but the app finds fewer names. See [Troubleshooting]({{ '/manual/troubleshooting/' | relative_url }}).

## Build the app from source

Developers can build the app instead of downloading it. Follow [Build the app]({{ '/developer/building/' | relative_url }}). The build writes `dist/Cloudy Reader.app`. Copy it to `/Applications`. A source build carries the voices it was built with and links them into your data folder, `~/Library/Application Support/cloudyreader`, at each start.

## Next steps

- Learn the window: [Use the app]({{ '/manual/using-the-app/' | relative_url }}).
- Pick voices and rotation: [Voices and rotation]({{ '/manual/voices/' | relative_url }}).
- Fix a word that sounds wrong: [Pronunciation]({{ '/manual/pronunciation/' | relative_url }}).
- Work without a network: [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}).
