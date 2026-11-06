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

| Aspect           | Piper                                     | Kokoro                                            |
| ---------------- | ----------------------------------------- | ------------------------------------------------- |
| Name in the menu | A lowercase file name, such as `lessac`   | A name with a gender, such as `Heart (female)`    |
| Quality label    | A tier from the voice's own configuration | A letter grade from the model's `VOICES.md`       |
| Files on disk    | 63.2 MB for each voice                    | 327.1 MB for the model and 0.52 MB for each voice |
| Sample rate (Hz) | 22,050 for the supported voices           | 24,000                                            |

Together, the voice files take REL-VOICES-SIZE, and the first launch downloads them. The first Kokoro reading after the app starts also loads the Kokoro model. The status bar shows only "Preparing…" while it loads.

In the project's tests on a Mac with an M2 Ultra chip, peak memory use was about 2.3 GB with only the name-detection model loaded. It was about 2.5 GB after a reading with a Piper voice, and about 3.0 GB after a reading with a Kokoro voice in the same session.

The tests ran the app's code without the window, and the installed app was not measured. These numbers are test results, not requirements, and the project states no minimum.

## What grades and quality labels mean

Each Kokoro voice has a letter grade, and the menu lists the best grade first. The grades come from the model's `VOICES.md` file. The app shows each grade in the menu, and it does not test or change a grade.

A Piper voice shows the quality tier from its own configuration file: `x_low`, `low`, `medium`, or `high`. The supported Piper voices are all `medium`.

Inside an engine, the menu lists the best grade or tier first, then voices with the same grade by name. A voice without a grade comes last.

A grade or tier is a label from the voice's source files. It does not tell you which voice is clearest in your room or for your listeners.

## Accents and genders

The pronunciation rules are written for English. The label of each voice shows its language code: `en-US` for American English and `en-GB` for British English.

A Kokoro id such as `af_heart` holds the same facts. The first letter is `a` for `en-US` and `b` for `en-GB`. The second letter is `f` for female and `m` for male.

The genders are labels from the voice data. Kokoro names show the label, as in `Heart (female)`, and the menu shows none for a Piper voice. Rotation uses the Piper labels, which nobody has checked by ear.

[Voices and rotation modes](/manual/reference/voices/) lists the accent and gender label of every voice. See [Rotation modes](/manual/reference/voices/#rotation-modes) for how each mode uses the labels.

## Why pauses differ between voices

The app puts exact silence between the parts of a question, and the amount is the same for every voice. It inserts 700 milliseconds after the stem when choices follow, 300 milliseconds after a choice letter, and 400 milliseconds after a choice.

Each voice also adds its own near silence before and after a line. A Kokoro voice adds about 0.4 seconds on each side, and a Piper voice adds less.

After a choice letter, the app cuts the voice's own silence, so that pause lasts about 0.3 to 0.4 seconds in every voice. After the stem and after a choice, the app keeps the voice's own silence. A Kokoro voice therefore pauses about 0.8 seconds longer there than the inserted silence.

To hear the difference, read the same question with one voice from each engine and listen after the stem. See [Hear a sample question](/manual/getting-started/#hear-a-sample-question) for a question to use, and [Question format and reading order](/manual/reference/question-format/) for every pause.

## Choosing a voice for practice

No grade or tier decides which voice is best for you. Try two or three voices with the same question and choose by ear. These facts help you narrow the choice:

- Start voice: the app starts on the first voice in the menu until you choose a voice.
- Pauses: after the stem and after each choice, a Piper voice pauses closer to the inserted silence than a Kokoro voice does.
- Speed: after the first reading, a Piper reading took 0.2 to 0.6 seconds to render on the project's test Mac. A Kokoro reading took about 1.6 seconds.
- Accent: choose a voice labeled `en-US` for an American accent and `en-GB` for a British accent.
- Variety: choose a rotation mode to hear a different voice for each reading. See [Practice with voice rotation](/manual/tutorials/voice-rotation/).

[Voices and rotation modes](/manual/reference/voices/) lists every voice with its grade.

## Related

- [Voices and rotation modes](/manual/reference/voices/)
- [Practice with voice rotation](/manual/tutorials/voice-rotation/)
- [Question format and reading order](/manual/reference/question-format/)
