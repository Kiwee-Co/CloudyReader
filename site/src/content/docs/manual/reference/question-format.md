---
title: Question format and reading order
description: The question text Cloudy Reader understands, what it cleans up, the order it reads each part in, and the pause after each part.
sidebar:
  order: 7
---

This page lists the question text the app understands, what it cleans up, the order it reads each part in, and every pause.

## Parts of a question

The parser looks for these parts. A question needs a stem or choices, and the app drops one that has neither.

| Part           | What the parser accepts                                                                                                                                                                                                                                                                                                    |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Header         | `TOSS-UP`, `TOSSUP`, `TOSS UP`, or `BONUS`. In capitals it always counts. In another letter case it counts only alone on its line or before a number.                                                                                                                                                                      |
| Number         | `N)`, or `N.` followed by a space, with 1 to 4 digits and an optional `*` in front. A bare number counts only before a format label.                                                                                                                                                                                       |
| Category       | Capital words before the format label, as in `EARTH SCIENCE Multiple Choice`. After a header or number, title-case words before the label count, and so does a known category word followed by a dash. A category glued to its label, as in `ENERGYMultiple Choice`, is split.                                             |
| Format         | `Multiple Choice` or `Short Answer`, in any letter case, hyphenated as in `multiple-choice`, or glued as in `ShortAnswer`. The misspelling `Mutliple Choice` also counts.                                                                                                                                                  |
| Stem           | The question text before the choices.                                                                                                                                                                                                                                                                                      |
| Choice markers | `W)`, `X)`, `Y)`, and `Z)`. The markers `W.` and `W:` work when a space follows. Capital, lower-case, and mixed-case markers work, and the choices can share one line.                                                                                                                                                     |
| Choice order   | The last `W` that is followed by `X`, `Y`, and `Z` in order starts the choices. Stem initials such as `W. H. Bragg` do not count. Four `)` markers at line starts in swapped order, as in `W Y X Z`, are read in the printed order. A wrong first label among such markers, as in `Y X Y Z`, becomes `W`.                  |
| Answer line    | A line that starts with the word answer and a colon, in any letter case, as in `ANSWER:` or `Answer:`. The misspelling `ANWER:` also counts, and so does `ANSWER` in capitals with no colon. The app also finds `ANSWER:` and `Answer:` inside a line, but not `Short Answer:`. Every line after it belongs to the answer. |

A paste needs none of the optional parts. The text `Which gas is released when NaHCO3 reacts with acetic acid?` alone becomes the spoken script `Which gas is released when N A H C O three reacts with acetic acid?`.

## What the app cleans up

The app cleans the pasted text before it looks for the parts.

| Pasted text            | What the app does                                                                                                                                                                                                          |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Invisible characters   | Removes byte-order marks, zero-width characters, and soft hyphens.                                                                                                                                                         |
| Math-italic letters    | Turns them into plain letters.                                                                                                                                                                                             |
| PDF symbol-font glyphs | Turns five glyphs into `°`, `θ`, `−`, `√`, and `→`. Every other private-use glyph and the replacement character `U+FFFD` become a space.                                                                                   |
| Rule lines             | Drops a line made of three or more `~`, `*`, `_`, or `=`, or of five or more `-`.                                                                                                                                          |
| Round titles           | Drops lines such as `ROUND ROBIN 2`, `Middle School`, and `High School`.                                                                                                                                                   |
| Page footers           | Drops lines such as `PAGE 4`.                                                                                                                                                                                              |
| Omission notes         | Drops a note that a toss-up or bonus was omitted, removed, or deleted.                                                                                                                                                     |
| Hard wraps             | Joins wrapped lines. Rejoins a word split by a hyphen, unless the part before the hyphen is `half`, `self`, `well`, `high`, `low`, `long`, `short`, `cross`, `first`, `second`, `third`, or a number word from one to ten. |

## Reading order and pauses

The app speaks the parts in the order of this table. It skips a part that the paste does not have, and it inserts each pause as exact silence.

| Part          | What is spoken                                                                                                                         | Pause after (ms)                        |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Header        | `Toss-up number two.`, `Bonus number twelve.`, or `Question number one.` With no number: `Toss-up.` or `Bonus.` With neither, nothing. | 400                                     |
| Category      | The category in title case, such as `Earth Science.`                                                                                   | 300                                     |
| Format        | `Multiple choice.` or `Short answer.`                                                                                                  | 500                                     |
| Stem          | The question text.                                                                                                                     | 700 when choices follow, otherwise 0    |
| Choice letter | `W.`, `X.`, `Y.`, or `Z.`                                                                                                              | 300, or 400 when the choice has no text |
| Choice text   | The text of the choice.                                                                                                                | 400                                     |
| Answer line   | `Answer.` and the answer text, only when **Read answer line** is on.                                                                   | 0                                       |

With **Read answer line** on, the pause before `Answer.` is 5 seconds. It replaces the pause after the last part. Between two questions the pause is 1.5 seconds, and it replaces the last pause of the question before.

### Example with one question

This paste is a sample question written for this manual.

```text
TOSS-UP
1) CHEMISTRY Multiple Choice Which gas forms when sodium bicarbonate, NaHCO3, reacts with acetic acid?
W) Oxygen
X) Hydrogen
Y) Carbon dioxide
Z) Nitrogen
ANSWER: Y) CARBON DIOXIDE
```

With **Read answer line** off, the app speaks these segments, each followed by its pause.

| Spoken text                                                                        | Pause after (ms) |
| ---------------------------------------------------------------------------------- | ---------------- |
| Toss-up number one.                                                                | 400              |
| Chemistry.                                                                         | 300              |
| Multiple choice.                                                                   | 500              |
| Which gas forms when sodium bicarbonate, N A H C O three, reacts with acetic acid? | 700              |
| W.                                                                                 | 300              |
| Oxygen                                                                             | 400              |
| X.                                                                                 | 300              |
| Hydrogen                                                                           | 400              |
| Y.                                                                                 | 300              |
| Carbon dioxide                                                                     | 400              |
| Z.                                                                                 | 300              |
| Nitrogen                                                                           | 400              |

With **Read answer line** on, the pause after "Nitrogen" is 5 seconds, and the script ends with "Answer. Y. Carbon Dioxide."

### Voice padding

Some voices add their own silence around each line. The app trims that silence beside a choice letter, so the pause after a letter is about 0.3 to 0.4 seconds. The other pauses keep the voice's own silence. See [Voices and voice engines](/manual/concepts/voice-engines/) for how voices differ.

## The answer line

The app speaks the answer line only when **Read answer line** is on. It then speaks the primary answer and drops the judge notes.

| In the answer line                                                                                                                                                                                     | What the app does                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| A note that starts with `(ACCEPT`, `(ALSO ACCEPT`, `(DO NOT ACCEPT`, `(PROMPT`, `(DO NOT PROMPT`, `(SOLUTION`, `(NOTE`, `(MUST`, `(STUDENT`, or `(STUDENTS`, or one of those words followed by a colon | Drops it and everything after it, in any letter case.                      |
| A bracketed note such as `[NOTE …]`, `[MUST …]`, `[DO NOT …]`, `[ACCEPT …]`, `[PROMPT …]`, `[STUDENT …]`, or `[STUDENTS …]`                                                                            | Drops it.                                                                  |
| A choice marker `x)`, `X.`, or `X:` at the start                                                                                                                                                       | Turns it into `X.`, so `Answer: x) 4` is read `Answer. X. 4.`              |
| An answer in capitals                                                                                                                                                                                  | Title-cases each word, so `Y) CARBON DIOXIDE` is read `Y. Carbon Dioxide.` |
| No final period                                                                                                                                                                                        | Adds `.`                                                                   |

## Several questions in one paste

A paste can hold one question or a whole round. The app reads the questions in the order you pasted them, with 1.5 seconds between them.

The app starts the next question at each header. It also starts one at a numbered line that carries a format label. A numbered line can start the next question after a question that already has its choices or its answer line.

This paste holds a toss-up and a bonus.

```text
TOSS-UP
2) PHYSICS Short Answer A cart moves 90 meters in 6 seconds at a constant speed. What is its speed in m/s?
ANSWER: 15

BONUS
2) PHYSICS Short Answer What is the kinetic energy, in joules, of a 2 kg cart that moves at 3 m/s?
ANSWER: 9
```

With **Read answer line** off, the spoken script is the text below. The pause after the toss-up stem is 1.5 seconds.

```text
Toss-up number two. Physics. Short answer. A cart moves 90 meters in 6 seconds at a constant speed. What is its speed in meters per second? Bonus number two. Physics. Short answer. What is the kinetic energy, in joules, of a 2 kilogram cart that moves at 3 meters per second?
```

With **Read answer line** on, the script adds `Answer. 15.` and `Answer. 9.`. Each follows a pause of 5 seconds after its stem, and 1.5 seconds follows `Answer. 15.`.

## Limits

The parser has these limits.

| Limit                    | What happens                                                                                                                                                                                                                                                                                         |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Four choices             | All four letters `W`, `X`, `Y`, and `Z` must be present. With three choices the app does not split the choices, and it reads the markers as text.                                                                                                                                                    |
| Category without a label | Without a printed format label, capital words count as the category only when each one is a known category word: `BIOLOGY`, `CHEMISTRY`, `PHYSICS`, `MATH`, `MATHEMATICS`, `ENERGY`, `EARTH`, `SPACE`, `SCIENCE`, `SCIENCES`, `GENERAL`, `LIFE`, `PHYSICAL`, `AND`, `&`, `COMPUTER`, or `ASTRONOMY`. |
| Plain text               | The question box takes plain text only.                                                                                                                                                                                                                                                              |
| Nothing to read          | A paste with no stem and no choices shows "Error: nothing to read" in the status bar. A bare `TOSS-UP` and a paste of only round titles and page footers do the same. See [The app finds nothing to read](/manual/troubleshooting/#the-app-finds-nothing-to-read).                                   |
| Length                   | The app sets no limit on the length of a paste. A voice can limit the length of one reading. See [Built-in limits](/manual/reference/files-and-settings/#built-in-limits).                                                                                                                           |

For the steps to paste from a PDF, see [Paste questions from a PDF or web page](/manual/tasks/paste-questions/). For how the app says formulas and symbols, see [Pronunciation examples](/manual/reference/pronunciation-examples/).
