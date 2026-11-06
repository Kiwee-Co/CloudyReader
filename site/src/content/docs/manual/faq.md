---
title: Frequently asked questions
description: 'Short answers to common questions about Cloudy Reader: Macs, privacy, voices, speed, PDFs, updates, and licenses.'
sidebar:
  label: FAQ
  order: 2
---

Each answer is short and links to the page that covers the topic in full.

## What does Cloudy Reader do?

It reads National Science Bowl questions aloud on your Mac, using voices that run on the Mac. The app says formulas, units, and fractions in words, so a voice can read them. Start with [Get started](/manual/getting-started/).

## Is it an official National Science Bowl tool?

No. Cloudy Reader is an [independent project](/about/project/). It is not affiliated with, endorsed by, or sponsored by the U.S. Department of Energy or the National Science Bowl.

## Which Macs run it?

Cloudy Reader needs a Mac with Apple silicon and macOS REL-MACOS-FLOOR or later. Intel-based Macs are not supported. See [Check your Mac](/manual/getting-started/#check-your-mac).

## Does it cost anything?

Cloudy Reader asks for no payment, account, or license key. Its source code is open under the Apache License 2.0. See [Licenses and credits](/about/licenses/).

## Does it work without a network?

Yes, once the first launch has downloaded the voices. Name lookups and the voice download need a network, and offline mode stops both. See [Work offline](/manual/tasks/work-offline/).

## Does it send my questions anywhere?

The app never sends the text of a question. While **Online lookups** is selected, the default, it sends one detected chemical, protein, or gene name at a time to PubChem or UniProt. It has no telemetry, analytics, crash reporting, or update check; [Privacy](/about/privacy/) lists every network use.

## Do online lookups change what I hear?

No: only the local OPSIN check can change how a chemical name sounds, and the app ignores the PubChem and UniProt answers. A lookup adds network traffic and up to 2.5 seconds of waiting, so deselect **Online lookups** to avoid both. See [How a question becomes speech](/manual/concepts/how-reading-works/).

## Which voice should I use?

Start with the first voice in the **Voice** menu and try others. Each voice shows a quality label in the menu, and a label does not say which voice suits your room or your ears. See [Voices and voice engines](/manual/concepts/voice-engines/).

## Can I change the speaking speed?

No: the window has no speed control, and every reading uses the voice's normal speed (1.0). See [Main window](/manual/reference/window/).

## Can I save the audio as a file?

The app has no export command, but it keeps each reading as a WAV file in the `cache/wav` folder of the data folder. The file name is a hash, so sort the folder by date to find the newest reading. See [Data folder](/manual/reference/files-and-settings/#data-folder) for the path.

## Can I add my own voices?

You can add Piper voices: copy a voice's `.onnx` and `.onnx.json` files into the `voices` folder of the data folder, then restart the app. A voice you add this way never rotates. See [Add a Piper voice](/manual/tasks/voices-and-storage/#add-a-piper-voice).

## Does it read other languages?

No: the pronunciation rules are written for English. A Piper voice in another language appears in the **Voice** menu if its files are in the `voices` folder, but it never rotates. See [Voices and voice engines](/manual/concepts/voice-engines/).

## Why is there a pause before the answer?

With **Read answer line** selected, the app waits 5 seconds before it says the answer, which gives you time to answer first. Deselect the checkbox to skip the answer. See [Practice on your own](/manual/tasks/practice-alone/).

## Can I read a whole round at once?

Yes: paste the whole round into the question box, and the app reads each question in order with 1.5 seconds between questions. It ignores round titles, page footers, and rule lines. See [Paste questions from a PDF or web page](/manual/tasks/paste-questions/).

## Can I read a PDF directly?

No: copy the text from the PDF and paste it into the question box. The app repairs hard wraps, page footers, and other PDF leftovers. See [Paste questions from a PDF or web page](/manual/tasks/paste-questions/).

## Can it read images or drawn equations?

No: the question box takes text only, and the app has no image recognition. Copy the text instead, or type a formula in plain characters, such as `H2O` or `x^2`. See [Question format and reading order](/manual/reference/question-format/).

## How do I fix a word that sounds wrong?

Add a pronunciation guide in square brackets right after the word, such as `Krebs cycle [KREBZ SY-kul]`. The guide sets how the app says the word. Follow [Fix a mispronounced word](/manual/tutorials/fix-a-word/).

## Why does macOS block the app the first time?

<!-- needs-fact: owner checklist (plan 8.3): the first-open approval flow in System Settings -->

The app is signed ad hoc and is not notarized, so macOS asks you to approve it the first time. You approve it once, in System Settings. See [Open the app the first time](/manual/tasks/first-open/).

## Can I use it on a school-managed Mac?

That depends on your administrator, because the app is signed ad hoc and is not notarized, and a managed Mac can block such an app. [Privacy](/about/privacy/) lists the network hosts that the app contacts, and [Security and code signing](/about/security/) explains the signature.

## How much disk space and memory does it use?

Cloudy Reader needs REL-DISK-TOTAL of free disk space, and the audio cache has no size limit. [Check your Mac](/manual/getting-started/#check-your-mac) lists the requirements, and [Voices and voice engines](/manual/concepts/voice-engines/) covers memory. See [Free disk space](/manual/tasks/voices-and-storage/#free-disk-space) to clear the cache.

## How do I update or uninstall it?

The app has no update check, so look for a later version on the [releases page](https://github.com/Kiwee-Co/CloudyReader/releases), then replace the app in **Applications**. To uninstall, move the app to the Trash; the voices, caches, and preferences stay until you delete them. See [Install, update, and uninstall](/manual/tasks/install/).

## Why is there no Help menu?

<!-- needs-fact: owner checklist (plan 8.3): macOS moves About to the application menu and hides the empty Help menu -->

The app's Help menu holds only **About Cloudy Reader**, so macOS moves that item into the application menu and hides the empty Help menu. The app has no command that opens this manual. See [Main window](/manual/reference/window/).

## How do I find the version?

<!-- needs-fact: owner checklist (plan 8.3): About Cloudy Reader sits in the Cloudy Reader menu on the real app -->

Choose **Cloudy Reader > About Cloudy Reader** to see "Version REL-VERSION". In Terminal, `--version` prints "Cloudy Reader REL-VERSION":

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --version
```

See [Install, update, and uninstall](/manual/tasks/install/).

## What is the license?

The source code of Cloudy Reader is licensed under the Apache License 2.0. The app also bundles and downloads third-party components, including GPL components, that keep their own licenses. See [Licenses and credits](/about/licenses/).

## How do I report a problem?

Open an issue on [GitHub](https://github.com/Kiwee-Co/CloudyReader/issues) and include your version, your macOS version, and the self-test report. [Get help](/manual/get-help/) lists what to collect and how to report a security issue.
