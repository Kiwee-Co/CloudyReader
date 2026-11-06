---
title: 'Release notes'
description: 'What each Cloudy Reader release changed, with its requirements and known limits, newest first.'
sidebar:
  order: 5
---

This page records what each Cloudy Reader release changed, with its requirements and known limits. The newest release comes first.

## Version 0.0.2

Released November 6, 2026. Version 0.0.2 adds two voice engines, a disk image, and pronunciation fixes.

### Requirements for 0.0.2

Version 0.0.2 needs a Mac with Apple silicon and macOS 26.2 or later. See [Check your Mac](/manual/getting-started/#check-your-mac) for disk space and the network.

### Download 0.0.2

Get the files from [Download Cloudy Reader](/download/). Neither file holds voices or engines.

### What is in 0.0.2

- Disk image: Cloudy Reader comes as a disk image and as a zip, and both hold the same app. See [Install, update, and uninstall](/manual/tasks/install/).
- Voice engines: Chatterbox Turbo adds one built-in voice, and Qwen3-TTS adds the voices Aiden and Ryan. Neither engine clones a voice. See [Voices and voice engines](/manual/concepts/voice-engines/).
- Voice order: the menu lists Kokoro, Chatterbox Turbo, Qwen3-TTS, then Piper. Chatterbox Turbo and Qwen3-TTS have no grade, so their voices sort by name.
- Window look: the question sits in a card, and the spoken script sits in its own panel. Only one progress bar shows at a time, and VoiceOver announces warnings and `Voices downloaded.` as well as errors. See [Main window](/manual/reference/window/).
- Engine downloads: the first launch downloads the Piper voices, the Kokoro voices, Chatterbox Turbo, and Qwen3-TTS in turn, with one status label for each group. A group's voices appear in the menu when its download ends.
- Disk check: before Chatterbox Turbo and before Qwen3-TTS, the app checks the free disk space and skips the engine if it does not fit.
- Resume: a retry in the same run resumes a partial file.
- Dimmed voices: a voice that cannot run yet shows dimmed, with its reason in the menu. See [Voices and rotation modes](/manual/reference/voices/).
- First use: the first reading with Chatterbox Turbo or Qwen3-TTS loads the engine. The status bar shows `Preparing… loading Chatterbox Turbo (first use only)` or the same text with Qwen3-TTS.
- Saved voice: a saved voice that is not ready at start gives way to another voice, and a note in the status bar says so.
- Rotation: Chatterbox Turbo has no gender label, so no rotation mode picks it. **US only (random shuffle)** adds Aiden, and **Men only** adds Aiden and Ryan.
- Offline guard: an engine loads only files on your Mac and never contacts the network itself. See [How the voice engines stay offline](/about/privacy/#how-the-voice-engines-stay-offline).
- Pinned engine files: each engine file has a commit-pinned address and a SHA-256 value. The app checks the SHA-256 again before the first load and refuses pickle files. See [Engine files](/about/security/#engine-files).
- No IPA: Chatterbox Turbo and Qwen3-TTS take no IPA. Each says a respelled word from its respelling, and a lexicon word or a checked chemical name as printed. The status bar warning counts the lexicon words and the checked names. See [Hard words and chemical names](/manual/concepts/how-reading-works/#hard-words-and-chemical-names).
- Ranges: `5–10 grams` reads as "5 to 10 grams". A hyphen or a spaced dash reads as a range only before a unit, a percent sign, or a noun such as `pages`. See [Pronunciation examples](/manual/reference/pronunciation-examples/).
- Comparisons: `x<3` reads as "x is less than 3", and `x>=3` reads as "x is greater than or equal to 3".
- Function names: `sin θ` reads as "sine theta", and `40sin(30°)` reads as "40 sine(30 degrees)". The `cos`, `tan`, and `ln` function names read as words too.
- Logarithms: `log3 10` reads as "log base 3 of 10". A number glued to `log` with no argument stays whole, so `log100 = 2` reads as "log 100 equals 2".
- Units after "a" or "an": the unit is singular, so `a 2 kg cart` reads as "a 2 kilogram cart".
- Say-as guides: a say-as guide after an expression that starts with a function name covers the whole expression.

### Known limits in 0.0.2

These limits apply to version 0.0.2:

- The app runs on a Mac with Apple silicon only. There is no build for an Intel-based Mac.
- The app is [signed ad hoc](/manual/reference/glossary/#ad-hoc-signature) and is not [notarized](/manual/reference/glossary/#notarized), so the first launch needs a one-time approval. See [Open the app the first time](/manual/tasks/first-open/).
- The first launch downloads the voices and both engines. See [Manage voices and storage](/manual/tasks/voices-and-storage/) for the size.
- On a fresh install, a failed first download shows no warning, because the status bar already holds "No voice is installed." The next start tries the missing files again. See [No voice is installed](/manual/troubleshooting/#no-voice-is-installed).
- The genders of the five Piper voices are a guess that nobody has checked by ear, and **Men only** and **Women only** use them.
- Some voices add their own silence around each line, so some pauses run longer than others. See [Why pauses differ between voices](/manual/concepts/voice-engines/#why-pauses-differ-between-voices).
- A failed file starts again from the beginning at the next start. A retry in the same run resumes a partial file.
- Offline mode shows no status bar message when it skips the voice download. A dimmed row in the **Voice** menu can show the reason `offline: not downloaded`.
- On a Mac with less than 24 [GiB](/manual/reference/files-and-settings/#built-in-limits) of memory, at most one of Chatterbox Turbo and Qwen3-TTS stays loaded. Switching between them reloads the engine.
- One reading holds at most 8,000 characters with Chatterbox Turbo or Qwen3-TTS.
- An engine can fail to say a short part, such as a choice letter. The status bar then shows `<engine> could not say '<part>'; try another voice`.
- The window has no speed control and no volume control. The app has no export command, no way to add words to the lexicon, and no voice manager.
- The pronunciation rules are written for English.
- The question box takes plain text, so the app cannot read an image of a question.
- Some written forms keep a slash or a dash, and a Piper voice then says it as written. See [Known limits](/manual/concepts/how-reading-works/#known-limits).

## Version 0.0.1

Released November 5, 2026. Version 0.0.1 was the first public release.

### Requirements for 0.0.1

Version 0.0.1 needs a Mac with Apple silicon and macOS 26.2 or later. See [Check your Mac](/manual/getting-started/#check-your-mac) for disk space and the network.

### Download 0.0.1

Get the file from [Download Cloudy Reader](/download/) or from the [GitHub release for version 0.0.1](https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.1). The file holds the app and no voice files.

### What is in 0.0.1

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

### Known limits in 0.0.1

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

The repository holds the full list of changes in [`CHANGELOG.md`](https://github.com/Kiwee-Co/CloudyReader/blob/main/CHANGELOG.md). Each version has a release page on GitHub, with its downloads. See [all releases on GitHub](https://github.com/Kiwee-Co/CloudyReader/releases). [Get started](/manual/getting-started/) walks you through the first launch.
