---
title: 'Voices and voice engines'
description: 'What the voice engines in Cloudy Reader are, what the grade, tier, and precision of a voice mean, and how to choose a voice for practice.'
sidebar:
  order: 2
---

A voice engine is the speech software that makes a set of voices, such as Piper or Kokoro. [Voices and rotation modes](/manual/reference/voices/) lists every engine and every voice.

## What a voice engine is

Each voice in the **Voice** menu belongs to one voice engine. The engine turns the spoken script and its exact pronunciations into audio, and the voice sets how that audio sounds.

The menu groups the voices under one heading for each engine. The headings are labels, not choices. Four engines run models that the app downloads: Kokoro, Chatterbox Turbo, Qwen3-TTS, and Piper. The fifth engine, macOS, speaks with the voices that your Mac already has.

## How the engines differ

The four engines that the app downloads run on your Mac. The table compares them. The [macOS voices](#macos-voices) come from the system, so the table leaves them out.

| Aspect               | Piper                                       | Kokoro                                                  | Chatterbox Turbo                 | Qwen3-TTS                        |
| -------------------- | ------------------------------------------- | ------------------------------------------------------- | -------------------------------- | -------------------------------- |
| Name in the label    | A file name with capitals, such as `Lessac` | A name, such as `Heart`                                 | `Built-in`                       | A name, such as `Aiden`          |
| Quality in the label | A tier from the voice's own configuration   | The grade, such as `Grade A`                            | `4-bit`                          | `8-bit`                          |
| Rank in the menu     | The best tier first                         | A letter grade from the model's `VOICES.md`, best first | No grade; the menu sorts by name | No grade; the menu sorts by name |
| Files on disk        | 63.2 MB for each voice                      | 327.1 MB for the model and 0.52 MB for each voice       | 0.42 GB                          | 1.97 GB                          |
| Sample rate (Hz)     | 22,050 for the supported voices             | 24,000                                                  | 24,000                           | 24,000                           |

Together, the Piper and Kokoro voice files take 0.66 GB, and the first launch downloads them first. Chatterbox Turbo and Qwen3-TTS download after them, each in its own group. See [Manage voices and storage](/manual/tasks/voices-and-storage/) for the download steps.

The first Kokoro reading after the app starts also loads the Kokoro model. The status bar shows only "Preparing…" while it loads.

Measurements on a Mac with an M2 Ultra chip and 192 GB of memory found these peak memory values:

- About 2.3 GB in a process that loaded only the name-detection model.
- About 2.5 GB in a session after a reading with a Piper voice.
- About 3.0 GB in the same session after a later reading with a Kokoro voice.

The measurements covered only Piper and Kokoro, ran the app's code without the window, and did not include the installed app. The values are not requirements, and the project states no minimum.

## Chatterbox Turbo

Chatterbox Turbo has one built-in voice. Its label reads `Built-in · Chatterbox Turbo · 4-bit`. It runs on your Mac from an MLX build by mlx-community, and it does not clone a voice. See [Licenses and credits](/about/licenses/) for its license.

The label shows no accent, because the language code `en` names English with no region. `4-bit` names the 4-bit MLX build of the model.

The voice has no gender label, so no rotation mode picks it.

## Qwen3-TTS

Qwen3-TTS has two preset voices, `Aiden` and `Ryan`. It runs on your Mac from an MLX build by mlx-community, and it does not clone a voice. See [Licenses and credits](/about/licenses/) for its license.

The menu labels read `Aiden (US, male) · Qwen3-TTS · 8-bit` and `Ryan (male) · Qwen3-TTS · 8-bit`, and `8-bit` names the 8-bit MLX build. Ryan's label names no region, so the **US only (random shuffle)** mode includes Aiden and skips Ryan.

The app reads the `mlx-audio` decoder before it downloads Qwen3-TTS. If the decoder is not one the app can use, the Qwen3-TTS voices stay dimmed with the reason `waiting for a Qwen3 decoder fix`. The download does not start.

A short check runs before the first reading with Qwen3-TTS. If it fails, that reading stops with the error `Error: waiting for a Qwen3 decoder fix (the decoder window check failed)`. Later readings fail at once until you quit the app.

## What Chatterbox Turbo and Qwen3-TTS share

- No IPA: neither engine takes IPA. Each says a respelled word from its respelling, and a lexicon word or a checked chemical name as printed. The status bar warning counts the lexicon words and the checked names. See [Hard words and chemical names](/manual/concepts/how-reading-works/#hard-words-and-chemical-names).
- First use: the first reading with an engine loads it. The status bar shows `Preparing… loading Chatterbox Turbo (first use only)` or `Preparing… loading Qwen3-TTS (first use only)`.
- Same sound: the same text with the same voice sounds the same each time.
- Length: one reading holds at most 8,000 characters. A longer text gets an error that names the engine and the count.

## Switching between engines

Chatterbox Turbo and Qwen3-TTS share memory slots. On a Mac with less than 24 [GiB](/manual/reference/files-and-settings/#built-in-limits) of memory, at most one of them stays loaded. The first reading after you switch from one to the other reloads the engine.

A Mac with 24 GiB or more keeps both loaded. The limit counts only these two engines.

## macOS voices

The macOS voices are the voices that your Mac already has. The app asks macOS for its English voices when it starts, and it lists them under the **macOS** heading, after the other engines. These voices need no download, and the engine uses no network, so you can read with one while the other voices download.

The app leaves out the novelty voices, such as Albert, Bubbles, and Cellos, and every voice in another language. A row shows the tier of the voice as its quality: `Premium`, `Enhanced`, or `Standard`. A voice with no tier in its macOS name is `Standard`, and the menu lists the best tier first.

To add a voice, open **System Settings** and search for Spoken Content. Add the voice there, and then quit and open Cloudy Reader again. The app reads the list once, when it starts, so a voice that you add appears at the next start.

A macOS voice takes no IPA. The app says a respelled word from its respelling, and a lexicon word or a checked chemical name as printed. The status bar warns that macOS cannot take IPA and names the words. See [Hard words and chemical names](/manual/concepts/how-reading-works/#hard-words-and-chemical-names).

The app reads the whole question in one run of the `say` command that comes with macOS. A macOS voice reads at its own rate, which follows the speaking rate in System Settings. The app knows the gender of some macOS voices by name. The other voices show no gender and do not rotate: see [Which voices rotate](/manual/reference/voices/#which-voices-rotate).

## What grades, tiers, and precision mean

A voice label ends with the quality of the voice: a grade, a tier, or the format of its model. Kokoro shows its published grade, as in `Grade A`. Piper and macOS show their tier, and the menu lists the best tier first. Chatterbox Turbo and Qwen3-TTS show the precision of the model, which does not rank a voice. [Voices and rotation modes](/manual/reference/voices/#voice-labels) explains every part of a label.

Each Kokoro voice has a letter grade, and the menu lists the best grade first. The grades come from the model's `VOICES.md` file. The label shows the grade, as in `Grade A`, and a tooltip on the row says "Published grade A". The app does not test or change a grade.

A Piper voice shows the quality tier from its own configuration file: `x_low`, `low`, `medium`, or `high`. The supported Piper voices are all `medium`.

A macOS voice shows its tier, which macOS names: `Premium`, `Enhanced`, or `Standard`.

Inside an engine, the menu lists the best grade or tier first, then voices with the same grade by name. A voice without a grade comes last.

The Chatterbox Turbo and Qwen3-TTS voices have no grade, so the menu sorts them by name. Their precision is the build, `4-bit` or `8-bit`.

A grade or tier is a label from the voice's source files. It does not tell you which voice is clearest in your room or for your listeners.

## Accents and genders

The pronunciation rules are written for English. The label of each voice shows its accent when the language code has a region. `en-US` shows US for American English, and `en-GB` shows UK for British English. The language code `en` names English with no region, and its label shows no accent.

A Kokoro id such as `af_heart` holds the same facts. The first letter is `a` for `en-US` and `b` for `en-GB`. The second letter is `f` for female and `m` for male.

The genders are labels from the voice data. A label shows the gender of a Kokoro voice from its id. For a Piper, Qwen3-TTS, or macOS voice, the app uses a list of names, and nobody has checked that list by ear. Rotation uses the same labels.

Chatterbox Turbo has no gender label, so no rotation mode picks it, and its label shows no brackets. A macOS voice that is not on the list shows no gender and never rotates.

[Voices and rotation modes](/manual/reference/voices/) lists the accent and gender label of every voice. See [Rotation modes](/manual/reference/voices/#rotation-modes) for how each mode uses the labels.

## Why pauses differ between voices

The app puts exact silence between the parts of a question, and the amount is the same for every voice. It inserts 700 milliseconds after the stem when choices follow, 300 milliseconds after a choice letter, and 400 milliseconds after a choice.

Some voices also add their own near silence before and after a line. A Kokoro voice adds about 0.4 seconds on each side, and a Piper voice adds less.

The app cuts the near silence around every part that a Chatterbox Turbo or Qwen3-TTS voice says. It keeps up to 0.05 seconds before the speech and up to 0.08 seconds after it.

After a choice letter, the app cuts the voice's own silence. This holds for every Piper, Kokoro, Chatterbox Turbo, and Qwen3-TTS voice, so that pause lasts about 0.3 to 0.4 seconds.

After the stem and after a choice, a Piper or Kokoro voice keeps its own silence. A Kokoro voice therefore pauses about 0.8 seconds longer there than the inserted silence. A Chatterbox Turbo or Qwen3-TTS voice pauses at most about 0.13 seconds longer than the inserted silence.

Sometimes a Chatterbox Turbo or Qwen3-TTS voice fails to say a short part alone, such as a single hard word. The app then keeps some of the voice's own silence after that part, so that pause can be longer. A choice letter on its own is not such a part: these voices play a short recording of it.

A macOS voice reads the whole script in one run. The app puts each pause into the text as a silence of that length, and it cuts none of the voice's own silence.

To hear the difference, read the same question with one voice from each engine and listen after the stem. See [Hear a sample question](/manual/getting-started/#hear-a-sample-question) for a question to use, and [Question format and reading order](/manual/reference/question-format/) for every pause.

## Choosing a voice for practice

No grade or tier decides which voice is best for you. Try two or three voices with the same question and choose by ear. These facts help you narrow the choice:

- Start voice: the app starts on the first installed voice in the menu until you choose a voice.
- No download: a macOS voice works from the first launch, before the other voices arrive.
- Pauses: after the stem and after each choice, a Kokoro voice pauses longer than a Piper, Chatterbox Turbo, or Qwen3-TTS voice does.
- Speed: after the first reading, a Piper voice rendered 17 to 44 seconds of audio in 0.2 to 0.6 seconds. A Kokoro voice rendered 32 seconds of audio in about 1.6 seconds. These single runs used the app's code on a Mac with an M2 Ultra chip, so treat the times as approximate.
- Accent: choose a voice labeled US for an American accent and UK for a British accent.
- Variety: choose a rotation mode to hear a different voice for each reading. See [Practice with voice rotation](/manual/tutorials/voice-rotation/).

[Voices and rotation modes](/manual/reference/voices/) lists every voice with its grade.

## Related

- [Voices and rotation modes](/manual/reference/voices/)
- [Practice with voice rotation](/manual/tutorials/voice-rotation/)
- [Question format and reading order](/manual/reference/question-format/)
