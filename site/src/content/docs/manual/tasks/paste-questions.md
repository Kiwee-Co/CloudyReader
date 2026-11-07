---
title: Paste questions from a PDF or web page
description: 'Copy questions from a PDF or a web page into Cloudy Reader, read several at once, and fix common paste problems.'
sidebar:
  order: 3
---

Use this page when your practice questions are in a PDF or on a web page. You copy the text, paste it into Cloudy Reader, and check what the app understood.

## Copy a question from a PDF

1. In your PDF viewer, select one question. Start at the header, `TOSS-UP` or `BONUS`, and end after the `ANSWER:` line.
2. Press Command-C.
3. Press Command-Tab to switch to Cloudy Reader.
4. Click the question box, press Command-A to select its text, and press Command-V.
5. Press Command-Return.

The status bar shows "Preparing…", then "Playing _n_ s." You hear the question. The app does not read the answer line unless **Read answer line** is selected.

You do not need to clean up the text first. The app removes rule lines, round titles such as `ROUND ROBIN 2`, page footers such as `PAGE 4`, and omission notes. It joins lines that the PDF wrapped. It also joins a word that a line break split at a hyphen, and it keeps the hyphen in compounds such as `half-life`. For the full list, see [Question format and reading order](/manual/reference/question-format/).

:::tip
To check the words before you listen, read the **Spoken script** view under the question box. It fills as you paste, and pasting never starts a reading.
:::

Copy from a web page the same way. The question box holds plain text, so fonts, colors, and images do not come along. Formulas copy in different forms, and the app reads them alike: `SO4 2-`, `SO₄²⁻`, and `SO42-` all become "S O four two minus", and `H 2 O` becomes "H two O".

## Paste several questions at once

You can paste one question or many. The app reads them in order.

1. In your PDF or web page, select several questions in one drag. Include each header, such as `TOSS-UP` or `BONUS`, and each number.
2. Press Command-C.
3. In Cloudy Reader, click the question box and press Command-V.
4. Press Command-Return.

Command-V inserts the text at the cursor, so you can paste one question after another. To replace the text in the box, press Command-A first.

This sample holds a toss-up and a bonus. Paste it to try the steps:

```text
TOSS-UP
2) PHYSICS Short Answer A cart moves 90 meters in 6 seconds at a constant speed. What is its speed in m/s?
ANSWER: 15

BONUS
2) PHYSICS Short Answer What is the kinetic energy, in joules, of a 2 kg cart that moves at 3 m/s?
ANSWER: 9
```

You hear "Toss-up number two." before the first question and "Bonus number two." before the second. The app leaves 1.5 seconds of silence between two questions. With **Read answer line** selected, each answer follows its question after a pause of 5 seconds.

Rotation picks one voice for each reading, so a paste with several questions is read in one voice. The app prepares the whole paste before it plays any sound. Paste a few questions at a time to hear the first one sooner. **Stop** ends the whole reading, and **Repeat** plays it again from the first question.

## Check what the app understood

The **Spoken script** view under the question box shows the words that the voice receives. These words are the [spoken script](/manual/reference/glossary/#spoken-script). A word that has a [pronunciation guide](/manual/reference/glossary/#pronunciation-guide) appears as printed, and the voice gets its sounds separately.

1. Paste a question into the question box.
2. Read the **Spoken script** view. It fills about 150 milliseconds after the last change.
3. Compare the script with the question.
4. Press **Speak** to hear the question. The view then shows the final script.

The view shows a preview while you type. The preview skips name detection and online lookups, so the wording of a chemical name can change when you press **Speak**. For a text of more than 20,000 characters, the view shows its placeholder until you press **Speak**.

For example, paste this question:

```text
TOSS-UP
1) CHEMISTRY Multiple Choice Which gas forms when sodium bicarbonate, NaHCO3, reacts with acetic acid?
W) Oxygen
X) Hydrogen
Y) Carbon dioxide
Z) Nitrogen
ANSWER: Y) CARBON DIOXIDE
```

The view shows:

```text
Toss-up number one. Chemistry. Multiple choice. Which gas forms when sodium bicarbonate, N A H C O three, reacts with acetic acid? W. Oxygen X. Hydrogen Y. Carbon dioxide Z. Nitrogen
```

A correct script shows these things:

- It starts with the header words, such as "Toss-up number one.", then the category and "Multiple choice." or "Short answer."
- Each choice starts with its letter: "W.", "X.", "Y.", and "Z."
- Formulas, units, and symbols appear as words. `NaHCO3` becomes "N A H C O three".
- The answer appears only when **Read answer line** is selected. For the sample, the script then ends with "Answer. Y. Carbon Dioxide."

If the script is wrong, fix the text in the question box and press **Speak** again. Press **Stop** first if the reading is still playing. If a word sounds wrong, see [Pronunciation guides](/manual/reference/pronunciation-guides/).

## Fix common paste problems

This table lists what you see, why it happens, and what to do.

| Symptom                                               | Cause                                                                                       | Fix                                                                                 |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| The status bar shows "Paste a question first."        | The question box is empty or holds only blank text.                                         | Paste or type a question, then press **Speak**.                                     |
| The status bar shows "Error: nothing to read"         | The paste has no question, for example only a round title, a page footer, or a bare header. | Copy the question itself, from its header to its last choice or answer line.        |
| The script keeps `W)`, `X)`, and `Y)` in the question | One of the four choices W, X, Y, and Z is missing, so the app does not split the choices.   | Copy the question again with all four choices, or type the missing choice.          |
| You do not hear "Toss-up number" before the question  | The paste has no header or no number.                                                       | Add a line with `TOSS-UP` or `BONUS` and a number such as `3)` before the question. |
| A symbol from the PDF is missing in the script        | The PDF stores the symbol as a private character. The app maps only °, θ, −, √, and →.      | Type the missing symbol in the question box.                                        |

## Related

- [Question format and reading order](/manual/reference/question-format/)
- [Pronunciation guides](/manual/reference/pronunciation-guides/)
- [Pronunciation examples](/manual/reference/pronunciation-examples/)
- [Troubleshooting](/manual/troubleshooting/)
