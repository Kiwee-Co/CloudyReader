---
layout: page
title: FAQ
nav_group: Manual
nav_order: 8
permalink: /manual/faq/
description: Short answers to common questions about Cloudy Reader.
---

## What does Cloudy Reader do?

It reads US DOE National Science Bowl questions aloud on your Mac. You paste the text, choose a voice, and press **Speak**. The voices run on your Mac. The app also turns formulas, units, and symbols into words, so a voice can say them.

## Which Macs run it?

The built app needs a Mac with Apple Silicon. The current build also needs macOS 26.2 or later. See [Get started]({{ '/manual/getting-started/' | relative_url }}).

From a source checkout, the code falls back to Piper voices alone on a Mac that is not Apple Silicon. The project's CI runs on Apple Silicon only. Playback uses the macOS program `afplay`, so the app does not run on Windows or Linux.

## Does it work without a network?

Yes. Reading needs no network. Only two features use one: name lookups and the download of missing voices. Offline mode stops both. See [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}).

## Does it send my questions anywhere?

No. A lookup sends one chemical, protein, or gene name at a time, and never the text around it. The app has no telemetry, analytics, crash reporting, or update check.

## Do online lookups change what I hear?

Not in this version. Only the local OPSIN check can change how a chemical name sounds. The PubChem and UniProt answers are cached and attached to the reading, but the script builder ignores them. Clear **Online lookups** if you want to avoid the network traffic and the wait of up to 2.5 seconds. See [Pronunciation]({{ '/manual/pronunciation/' | relative_url }}).

## Which voice should I use?

Try a few. The Kokoro voices carry a letter grade from the model's `VOICES.md`: `af_heart` is A, `af_bella` is A-, and `bf_emma` is B-. The project has not graded the Piper voices. The grades do not say which voice suits your room or your ears. See [Voices and rotation]({{ '/manual/voices/' | relative_url }}).

## Can I change the speaking speed?

No. The window has no speed control. Every reading uses a speed of 1.0.

## Can I save the audio as a file?

The app has no export command. It keeps each reading as a WAV file in the `cache/wav` folder of the data folder. The file name is a hash, so look for the newest file by date. The cache has no size limit, so clean it from time to time.

## Can I add my own voices?

You can add Piper voices. Copy the `.onnx` file and the `.onnx.json` file into the `voices` folder and restart the app. A hand-added voice never rotates. The app offers no other Kokoro voices than the 28 pinned ones. See [Voices and rotation]({{ '/manual/voices/' | relative_url }}).

## Does it read languages other than English?

No. The voices and the pronunciation rules target English. The app lists a Piper voice in another language if its files are in the `voices` folder, but the rules are not made for it.

## Why does the answer come after a long pause?

The app waits 5 seconds before the answer, so a moderator or a team has time to think. Turn off **Read answer line** to skip the answer. See [Use the app]({{ '/manual/using-the-app/' | relative_url }}).

## Can I read a whole round at once?

Yes. Paste the round into the box. The app reads each question in order and leaves 1.5 seconds between questions.

## Can I read a PDF directly?

No. Copy the text from the PDF and paste it. The parser repairs hard wraps, page footers, round titles, and other PDF leftovers.

## How do I fix a word that sounds wrong?

Add a bracket guide after the word, such as `Krebs cycle [KREBZ SY-kul]`. See [Pronunciation]({{ '/manual/pronunciation/' | relative_url }}).

## Why is there no Help menu?

The menu would hold only **About**. macOS moves **About** into the application menu and hides the empty Help menu.

## How do I stop a voice download?

Close the window. The download stops at its next data chunk. Offline mode prevents a download from starting.

## How do I find the app version?

Choose **About Cloudy Reader**, or run the program with `--version`.

## Is the app signed or notarized?

The build signs the app ad hoc. It uses no Apple Developer ID, and Apple has not notarized the app. A downloaded copy needs your approval in System Settings > Privacy & Security. See [Get started]({{ '/manual/getting-started/' | relative_url }}).

## What is the license?

The license is not yet chosen. The repository has no `LICENSE` file.

## How do I report a bug or change the code?

Open an issue on the [GitHub repository](https://github.com/Kiwee-Co/CloudyReader). To change code, read [Contribute]({{ '/developer/contributing/' | relative_url }}).
