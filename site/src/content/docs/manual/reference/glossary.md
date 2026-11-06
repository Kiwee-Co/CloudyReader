---
title: Glossary
description: Definitions of the terms in the Cloudy Reader manual, from toss-up and stem to voice engine, rotation, and offline mode.
sidebar:
  order: 10
---

This glossary defines each term that the manual uses in a fixed sense. Every term has its own anchor, so other pages can link to it.

## Questions

### Answer line

The `ANSWER:` line of a question. The **Read answer line** checkbox makes the app speak it. See [Question format and reading order](/manual/reference/question-format/).

### Bonus

The follow-up question for the team that answered the toss-up.

### Category

The subject label of a question, such as EARTH SCIENCE. The app speaks it in title case.

### Choice

One of the four answers, W, X, Y, and Z, of a multiple-choice question.

### Choice letter

The letter W, X, Y, or Z before a choice. The app speaks the letter, pauses for 300 milliseconds, then speaks the choice.

### Moderator

The person who reads questions in a match.

### Multiple choice

A question format with four choices, W, X, Y, and Z.

### National Science Bowl

The U.S. Department of Energy competition whose questions Cloudy Reader reads aloud. Cloudy Reader is an independent project. See [About the project](/about/project/).

### Question

One National Science Bowl question as pasted: a header, a stem, choices if any, and an optional answer line.

### Round

A set of toss-ups and bonuses that are read in one match. A paste can hold a whole round.

### Short answer

A question format without choices.

### Stem

The question text before the choices.

### Toss-up

A question that any player may answer first.

## Reading and the window

### Checkbox

A box that you select or deselect. **Read answer line** and **Online lookups** are checkboxes.

### Error

A status message that starts with "Error:". The reading did not happen. See [Status messages](/manual/reference/status-messages/).

### Pop-up menu

A control that opens a list of values. **Voice** and **Rotation** are pop-up menus.

### Question box

The text area where you paste or type a question.

### Reading

One run of **Speak**: the spoken script and its audio.

### Spoken script

The words that the voice receives after the app converts the question. The **Spoken script** view shows them, without the pronunciation overrides. See [How a question becomes speech](/manual/concepts/how-reading-works/).

### Status bar

The bar at the bottom of the window. It shows the status message, the voice download progress, and a busy bar. See [Main window](/manual/reference/window/).

### Status message

A message in the status bar. Its tone is information, warning, or error.

### Warning

A status message that starts with "Warning:" or "_n_ warnings:". The reading goes on.

## Voices

### Grade

The mark that the **Voice** menu shows after the language of a voice. A Kokoro voice has a letter grade from the model, from A at the top to F+ at the bottom. A Piper voice has a quality label, such as `medium`. See [Voices and voice engines](/manual/concepts/voice-engines/).

### Kokoro

A voice engine whose voices show a letter grade in the **Voice** menu. It needs a Mac with Apple silicon.

### Piper

A voice engine whose voices have lower-case names in the **Voice** menu, such as `lessac`.

### Rotation

How **Speak** picks the voice for a reading. The **Rotation** menu sets it.

### Rotation mode

One of the six settings of the **Rotation** menu: **No rotation**, **Round robin**, **Random shuffle**, **US only (random shuffle)**, **Men only**, and **Women only**. See [Rotation modes](/manual/reference/voices/#rotation-modes).

### Speaker

The number in the **Speaker** box. The box appears only for a voice that has several speakers.

### Supported voices

The voices that the app downloads and checks. See [Voices and rotation modes](/manual/reference/voices/).

### Voice

One entry that you can choose in the **Voice** menu, such as "Heart (female)".

### Voice engine

The speech software that makes a set of voices, such as Piper or Kokoro. See [Voices and voice engines](/manual/concepts/voice-engines/).

## Pronunciation

### IPA

The International Phonetic Alphabet, a notation for speech sounds. The app turns a phonetic respelling into IPA, and the voice engine speaks the word from it.

### Lexicon

The built-in table of 553 hard science words with exact pronunciations. The app matches whole words and ignores case.

### Name detection

The step that finds formulas and chemical, gene, and protein names in a question.

### Name-detection model

The language model for science text that name detection uses. It is part of the app, runs on your Mac, and loads once after the app starts.

### OPSIN check

The local parse of a systematic chemical name. It uses no network, so it works offline.

### Override

An exact pronunciation for a word or phrase, written in IPA. A pronunciation guide, the lexicon, or a systematic chemical name can set it.

### Phonetic respelling

A pronunciation guide that spells the sounds of a word or phrase, such as `[KREBZ SY-kul]`.

### Pronunciation guide

Text in square brackets after a word or phrase that sets how the app says it. The three kinds are the phonetic respelling, the say-as guide, and the spell guide. See [Pronunciation guides](/manual/reference/pronunciation-guides/).

### Say-as guide

A pronunciation guide that gives the words to say in place of a printed expression, such as `[4 and two-sevenths]`.

### Spell guide

A pronunciation guide that gives the letters to say, such as `[F.A.D.]`.

## Network and privacy

### Name lookup

A request to PubChem or UniProt about a detected name. See [Privacy](/about/privacy/).

### Offline mode

A launch with `--offline` or with `CLOUDYREADER_OFFLINE=1`. The app then makes no name lookups and no voice download. See [Start in offline mode](/manual/tasks/work-offline/#start-in-offline-mode).

### Online lookups

The checkbox that allows name lookups. Clearing it is not offline mode: it stops the lookups but not the voice download.

### PubChem

An online chemistry database. A name lookup sends it a detected chemical name.

### UniProt

An online protein database. A name lookup sends it a detected protein or gene name.

### Voice download

The background download of missing supported voices at launch. See [Manage voices and storage](/manual/tasks/voices-and-storage/).

## Installation

### Ad-hoc signature

A code signature that uses no Apple Developer ID. Cloudy Reader is signed ad hoc and is not notarized. See [Security and code signing](/about/security/).

### Audio cache

The `cache/wav` folder in the data folder. It holds one WAV file for each distinct reading.

### Data folder

The folder where the app keeps its voices and caches: `~/Library/Application Support/cloudyreader`. See [Data folder](/manual/reference/files-and-settings/#data-folder).

### Gatekeeper

The macOS feature that checks an app when you open it. It blocks the first launch of Cloudy Reader until you approve the app. See [Approve the app](/manual/tasks/first-open/#approve-the-app).

### Intel-based Mac

A Mac with an Intel processor. Cloudy Reader does not run on it. See [Your Mac is not supported](/manual/troubleshooting/#your-mac-is-not-supported).

### Mac with Apple silicon

A Mac with an Apple chip, M1 or later. Cloudy Reader runs only on these Macs.

### macOS

The Mac operating system. Cloudy Reader needs a Mac with Apple silicon and macOS REL-MACOS-FLOOR or later. See [Check your Mac](/manual/getting-started/#check-your-mac).

### Notarized

Passed Apple's malware check for apps that are distributed outside the App Store. Cloudy Reader is not notarized.

### Quarantine flag

The attribute that macOS sets on a downloaded file. Gatekeeper blocks the first launch of a quarantined app.

### Self-test

The `--self-test` option. It reads a built-in sample question with the first Piper voice, with no window and no sound, and reports the result. See [Command line](/manual/reference/command-line/).

### SHA-256

A checksum algorithm. Compare the SHA-256 of your download with the published value to check that the file is intact. See [Download Cloudy Reader](/download/).

### System Settings

The macOS settings app. You approve a blocked Cloudy Reader under **Privacy & Security** there.

### Terminal

The macOS app where you type commands.
