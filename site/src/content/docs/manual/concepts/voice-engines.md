---
title: 'Voices and voice engines'
description: 'What the voice engines in Cloudy Reader are, what grades and quality labels mean, and how to choose a voice for practice.'
sidebar:
  order: 2
---

A voice engine is the speech software that makes a set of voices, such as Piper or Kokoro. [Voices and rotation modes](/manual/reference/voices/) lists every engine and every voice.

## What a voice engine is

Each voice in the **Voice** menu belongs to one voice engine. The engine turns the spoken script and its exact pronunciations into audio, and the voice sets how that audio sounds.

The menu groups the voices under one heading for each engine. The headings are labels, not choices.

## How the engines differ

The engines run on your Mac. The table compares them.

| Aspect           | Piper                                     | Kokoro                                            | Chatterbox Turbo                  | Qwen3-TTS                                    |
| ---------------- | ----------------------------------------- | ------------------------------------------------- | --------------------------------- | -------------------------------------------- |
| Name in the menu | A lowercase file name, such as `lessac`   | A name with a gender, such as `Heart (female)`    | `Chatterbox Turbo (built-in)`     | A name with a gender, such as `Aiden (male)` |
| Quality label    | A tier from the voice's own configuration | A letter grade from the model's `VOICES.md`       | No grade; the label shows `4-bit` | No grade; the label shows `8-bit`            |
| Files on disk    | 63.2 MB for each voice                    | 327.1 MB for the model and 0.52 MB for each voice | 0.42 GB                           | 1.97 GB                                      |
| Sample rate (Hz) | 22,050 for the supported voices           | 24,000                                            | 24,000                            | 24,000                                       |

Together, the Piper and Kokoro voice files take 0.66 GB, and the first launch downloads them first. Chatterbox Turbo and Qwen3-TTS download after them, each in its own group. See [Manage voices and storage](/manual/tasks/voices-and-storage/) for the download steps.

The first Kokoro reading after the app starts also loads the Kokoro model. The status bar shows only "Preparing…" while it loads.

Measurements on a Mac with an M2 Ultra chip and 192 GB of memory found these peak memory values:

- About 2.3 GB in a process that loaded only the name-detection model.
- About 2.5 GB in a session after a reading with a Piper voice.
- About 3.0 GB in the same session after a later reading with a Kokoro voice.

The measurements covered only Piper and Kokoro, ran the app's code without the window, and did not include the installed app. The values are not requirements, and the project states no minimum.

## Chatterbox Turbo

Chatterbox Turbo has one built-in voice, `Chatterbox Turbo (built-in)`. It runs on your Mac from an MLX build by mlx-community, and it does not clone a voice. See [Licenses and credits](/about/licenses/) for its license.

The menu label reads `(en, 4-bit)`. The language code `en` names English with no region, and `4-bit` names the 4-bit MLX build of the model.

The voice has no gender label, so no rotation mode picks it.

## Qwen3-TTS

Qwen3-TTS has two preset voices, `Aiden (male)` and `Ryan (male)`. It runs on your Mac from an MLX build by mlx-community, and it does not clone a voice. See [Licenses and credits](/about/licenses/) for its license.

The menu labels read `(en-US, 8-bit)` for Aiden and `(en, 8-bit)` for Ryan, and `8-bit` names the 8-bit MLX build. Ryan's label names no region, so the **US only (random shuffle)** mode includes Aiden and skips Ryan.

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

## What grades and quality labels mean

Each Kokoro voice has a letter grade, and the menu lists the best grade first. The grades come from the model's `VOICES.md` file. The app shows each grade in the menu, and it does not test or change a grade.

A Piper voice shows the quality tier from its own configuration file: `x_low`, `low`, `medium`, or `high`. The supported Piper voices are all `medium`.

Inside an engine, the menu lists the best grade or tier first, then voices with the same grade by name. A voice without a grade comes last.

The Chatterbox Turbo and Qwen3-TTS voices have no grade, so the menu sorts them by name. Their labels show the build, such as `4-bit`, in place of a grade.

A grade or tier is a label from the voice's source files. It does not tell you which voice is clearest in your room or for your listeners.

## Accents and genders

The pronunciation rules are written for English. The label of each voice shows its language code: `en-US` for American English and `en-GB` for British English. The label `en` names English with no region.

A Kokoro id such as `af_heart` holds the same facts. The first letter is `a` for `en-US` and `b` for `en-GB`. The second letter is `f` for female and `m` for male.

The genders are labels from the voice data. Kokoro names show the label, as in `Heart (female)`, and the menu shows none for a Piper voice. Rotation uses the Piper labels, which nobody has checked by ear.

Qwen3-TTS names show `(male)` for Aiden and Ryan. Chatterbox Turbo has no gender label, so no rotation mode picks it.

[Voices and rotation modes](/manual/reference/voices/) lists the accent and gender label of every voice. See [Rotation modes](/manual/reference/voices/#rotation-modes) for how each mode uses the labels.

## Why pauses differ between voices

The app puts exact silence between the parts of a question, and the amount is the same for every voice. It inserts 700 milliseconds after the stem when choices follow, 300 milliseconds after a choice letter, and 400 milliseconds after a choice.

Some voices also add their own near silence before and after a line. A Kokoro voice adds about 0.4 seconds on each side, and a Piper voice adds less.

The app cuts the near silence around every part that a Chatterbox Turbo or Qwen3-TTS voice says. It keeps up to 0.05 seconds before the speech and up to 0.08 seconds after it.

After a choice letter, the app cuts the voice's own silence in every voice, so that pause lasts about 0.3 to 0.4 seconds.

After the stem and after a choice, a Piper or Kokoro voice keeps its own silence. A Kokoro voice therefore pauses about 0.8 seconds longer there than the inserted silence. A Chatterbox Turbo or Qwen3-TTS voice pauses at most about 0.13 seconds longer than the inserted silence.

Sometimes a Chatterbox Turbo or Qwen3-TTS voice fails to say a short part alone, such as a single hard word. The app then keeps some of the voice's own silence after that part, so that pause can be longer. A choice letter on its own is not such a part: these voices play a short recording of it.

To hear the difference, read the same question with one voice from each engine and listen after the stem. See [Hear a sample question](/manual/getting-started/#hear-a-sample-question) for a question to use, and [Question format and reading order](/manual/reference/question-format/) for every pause.

## Choosing a voice for practice

No grade or tier decides which voice is best for you. Try two or three voices with the same question and choose by ear. These facts help you narrow the choice:

- Start voice: the app starts on the first voice in the menu until you choose a voice.
- Pauses: after the stem and after each choice, a Kokoro voice pauses longer than a Piper, Chatterbox Turbo, or Qwen3-TTS voice does.
- Speed: after the first reading, a Piper voice rendered 17 to 44 seconds of audio in 0.2 to 0.6 seconds. A Kokoro voice rendered 32 seconds of audio in about 1.6 seconds. These single runs used the app's code on a Mac with an M2 Ultra chip, so treat the times as approximate.
- Accent: choose a voice labeled `en-US` for an American accent and `en-GB` for a British accent.
- Variety: choose a rotation mode to hear a different voice for each reading. See [Practice with voice rotation](/manual/tutorials/voice-rotation/).

[Voices and rotation modes](/manual/reference/voices/) lists every voice with its grade.

## Related

- [Voices and rotation modes](/manual/reference/voices/)
- [Practice with voice rotation](/manual/tutorials/voice-rotation/)
- [Question format and reading order](/manual/reference/question-format/)
