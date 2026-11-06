---
title: 'Voices and voice engines'
description: 'What the Piper and Kokoro voice engines are, what grades and quality labels mean, and how to choose a voice for practice.'
sidebar:
  order: 2
---

A voice engine is the speech software that makes a set of voices. Cloudy Reader has two engines, Piper and Kokoro, and together they provide 33 voices.

## What a voice engine is

Each voice in the **Voice** menu belongs to one voice engine. The engine turns the spoken script and its exact pronunciations into audio, and the voice sets how that audio sounds.

The menu groups the voices under the headings **Kokoro** and **Piper**. The headings are labels, not choices, and the menu lists Kokoro first.

## How the two engines differ

Both engines run on your Mac. The table compares what Cloudy Reader ships for each engine.

| Aspect                  | Piper                                                            | Kokoro                                                    |
| ----------------------- | ---------------------------------------------------------------- | --------------------------------------------------------- |
| Voices in the app       | 5                                                                | 28                                                        |
| American English voices | 3                                                                | 20                                                        |
| British English voices  | 2                                                                | 8                                                         |
| Name in the menu        | A lowercase file name, such as `lessac`                          | A name with a gender, such as `Heart (female)`            |
| Quality label           | A tier from the voice's own configuration; all five are `medium` | A letter grade from the model's `VOICES.md`, from A to F+ |
| Files on disk           | 63.2 MB for each voice                                           | 327.1 MB for the model and 0.52 MB for each voice         |
| First-launch download   | 10 files, 316.0 MB                                               | 30 files, 341.7 MB                                        |

The first Kokoro reading after the app starts also loads the Kokoro model. The status bar shows only "Preparing…" while it loads.

## What grades and quality labels mean

Each Kokoro voice has a letter grade from A to F+. The grades come from the model's `VOICES.md` file. The app shows each grade in the menu and sorts by it, and it does not test or change a grade.

A Piper voice shows the quality tier from its own configuration file: `x_low`, `low`, `medium`, or `high`. All five Piper voices in the app are `medium`.

Inside an engine, the menu lists the best grade or tier first, then voices with the same grade by name. A voice without a grade comes last. The Kokoro list starts with Heart (A), Bella (A-), Emma (B-), and Nicole (B-).

A grade or tier is a label from the voice's source files. It does not tell you which voice is clearest in your room or for your listeners.

## Accents and genders

The label of each voice shows its language code: `en-US` for American English and `en-GB` for British English. A Kokoro voice id holds the same facts. The first letter `a` means `en-US` and `b` means `en-GB`, and the second letter `f` or `m` means female or male.

The genders are labels from the voice data. Kokoro names show the label, as in `Heart (female)`, and the menu shows none for a Piper voice. Rotation uses five Piper labels that nobody has checked by ear.

| Accent and gender label | Piper voices       | Kokoro voices |
| ----------------------- | ------------------ | ------------- |
| US female               | 2: `lessac`, `amy` | 11            |
| US male                 | 1: `ryan`          | 9             |
| UK female               | 1: `jenny_dioco`   | 4             |
| UK male                 | 1: `alan`          | 4             |

With all 33 voices installed, **US only (random shuffle)** draws from 23 voices, **Men only** from 15, and **Women only** from 18. See [Rotation modes](/manual/reference/voices/#rotation-modes) for the exact rules.

## Why pauses differ between voices

The app puts exact silence between the parts of a question, and the amount is the same for every voice. It inserts 700 milliseconds after the stem when choices follow, 300 milliseconds after a choice letter, and 400 milliseconds after a choice.

Each voice also adds its own near silence before and after a line. A Kokoro voice adds about 0.4 seconds on each side, and a Piper voice adds less.

After a choice letter, the app cuts the voice's own silence, so that pause lasts about 0.3 to 0.4 seconds in every voice. After the stem and after a choice, the app keeps the voice's own silence. A Kokoro voice therefore pauses about 0.8 seconds longer there than the inserted silence.

To hear the difference, read the same question with one voice from each engine and listen after the stem. See [Hear a sample question](/manual/getting-started/#hear-a-sample-question) for a question to use, and [Question format and reading order](/manual/reference/question-format/) for every pause.

## Choosing a voice for practice

No grade or tier decides which voice is best for you. Try two or three voices with the same question and choose by ear. These facts help you narrow the choice:

- Start voice: the app starts on the first installed voice in the menu until you choose a voice. With all 33 voices installed, that voice is Heart (female).
- Pauses: after the stem and after each choice, a Piper voice pauses closer to the inserted silence than a Kokoro voice does.
- Speed: on the project's test Mac, a Piper reading took 0.2 to 0.6 seconds to render and a Kokoro reading about 1.6 seconds, after the first reading.
- Accent: choose a voice labeled `en-US` for an American accent and `en-GB` for a British accent.
- Variety: choose a rotation mode to hear a different voice for each reading. See [Practice with voice rotation](/manual/tutorials/voice-rotation/).

[Voices and rotation modes](/manual/reference/voices/) lists all 33 voices with their grades.

## Related

- [Voices and rotation modes](/manual/reference/voices/)
- [Practice with voice rotation](/manual/tutorials/voice-rotation/)
- [Question format and reading order](/manual/reference/question-format/)
