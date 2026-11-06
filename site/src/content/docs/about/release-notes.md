---
title: 'Release notes'
description: 'What each Cloudy Reader release changed, with its requirements and known limits, newest first.'
sidebar:
  order: 5
---

This page records what each Cloudy Reader release changed, with its requirements and known limits. The newest release comes first.

## Version 0.0.1

Released November 5, 2026. Version 0.0.1 was the first public release.

### Requirements

Version 0.0.1 needs a Mac with Apple silicon and macOS 26.2 or later. See [Check your Mac](/manual/getting-started/#check-your-mac) for disk space and the network.

### Download

Get the file from [Download Cloudy Reader](/download/) or from the [GitHub release for version 0.0.1](https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.1). The file holds the app and no voice files.

### What is in this release

- Voice download: Cloudy Reader holds no voice files, and the app downloads the voices in the background at the first launch.
- 33 voices: 5 Piper voices and 28 Kokoro voices, in US and UK English. The menu lists the best voices first inside each engine, Kokoro before Piper.
- Start voice: after the first download, the app starts on the best installed voice until you choose one.
- Voice rotation: six modes, **No rotation**, **Round robin**, **Random shuffle**, **US only (random shuffle)**, **Men only**, and **Women only**. See [Rotation modes](/manual/reference/voices/#rotation-modes).
- Pauses: 0.3 seconds of exact silence after each choice letter. The app cuts the voice's own silence there, so the pause lasts about 0.3 to 0.4 seconds. It also inserts 0.7 seconds after the stem when choices follow.
- Lexicon: a built-in table of hard science words with exact pronunciations.
- Formulas: spelled as letters and number words.
- Fractions: read as words, so `1/7` is "one seventh" and `2½` is "two and one half". They work in the stem, the choices, the answer line, and say-as guide words.
- Splits: a split of 100 into multiples of 5 reads as a pair, so `50/50` is "fifty-fifty" and `60/40` is "sixty-forty".
- Not fractions: a slash in `m/s`, `√10/5`, `1.5/2`, or `3/9/2024` is not read as a fraction.
- OPSIN check: the app checks systematic chemical names on your Mac, with no network.
- Name lookups: PubChem and UniProt lookups are on by default, and their answers never change the sound. Deselect **Online lookups** or use [offline mode](/manual/reference/glossary/#offline-mode) to turn them off. See [Privacy](/about/privacy/).
- Offline mode: start the app with `--offline` to stop the lookups and the voice download. See [Work offline](/manual/tasks/work-offline/).

## Known limits

These limits apply to version 0.0.1:

- The app runs on a Mac with Apple silicon only. There is no build for an Intel-based Mac.
- The app is [signed ad hoc](/manual/reference/glossary/#ad-hoc-signature) and is not [notarized](/manual/reference/glossary/#notarized), so the first launch needs a one-time approval. See [Open the app the first time](/manual/tasks/first-open/).
- The first launch downloads about 0.66 GB of voices.
- The genders of the five Piper voices are a guess that nobody has checked by ear, and **Men only** and **Women only** use them.
- Some voices add their own silence around each line, so some pauses run longer than others. See [Why pauses differ between voices](/manual/concepts/voice-engines/#why-pauses-differ-between-voices).
- A failed voice download does not resume. The next start downloads the missing files again from the beginning.
- Offline mode shows no message when it skips the voice download.
- The window has no speed control and no volume control. The app has no export command, no way to add words to the lexicon, and no voice manager.
- The pronunciation rules are written for English.
- The question box takes plain text, so the app cannot read an image of a question.
- Some written forms keep a slash or a dash, and a Piper voice then says it as written. See [Known limits](/manual/concepts/how-reading-works/#known-limits).

## Full changelog

The repository holds the full list of changes in [`CHANGELOG.md`](https://github.com/Kiwee-Co/CloudyReader/blob/main/CHANGELOG.md). The [GitHub release for version 0.0.1](https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.1) holds the download, and [Get started](/manual/getting-started/) walks you through the first launch.
