---
layout: page
title: Pronunciation
nav_group: Manual
nav_order: 4
permalink: /manual/pronunciation/
description: How Cloudy Reader turns formulas, units, symbols, and names into speech, and how to fix a word.
---

Cloudy Reader changes how a word sounds. It never changes which word is said. The formula `NaHCO3` is spelled "N A H C O three". It is never swapped for "baking soda". The same rule holds for every stage on this page: lookups and the lexicon pick sounds, not words.

## Follow the stages

| Step | What the app does | Network |
| --- | --- | --- |
| 1. Clean and parse | Fixes PDF leftovers, finds the header, number, category, format, stem, choices, and answer, and takes bracket guides out of the text. | No |
| 2. Detect names | Marks formulas, chemical names, genes, and proteins in the stem and the choices. It marks the answer too when **Read answer line** is on. | No |
| 3. Look up names | Asks OPSIN on your Mac about systematic names. Asks PubChem and UniProt about other names. | PubChem and UniProt only |
| 4. Build the script | Applies guides, then units and symbols, then formulas and notation, then the lexicon. | No |
| 5. Speak | The voice engine turns the script and the pronunciation overrides into audio. | No |

The **Spoken script** view shows the result of step 4. See [Use the app]({{ '/manual/using-the-app/' | relative_url }}).

## Know what the parser cleans

Pasted text from PDFs and web pages is messy. The parser handles these cases:

- A header such as `TOSS-UP` or `BONUS`, and a number such as `12)`.
- A category in capitals, or in title case before a printed format label. It also fixes a category glued to its label, as in `ENERGYMultiple Choice`.
- The labels `Multiple Choice` and `Short Answer`.
- Choices marked `W)`, `X)`, `Y)`, `Z)`. It also accepts `W.`, `W:`, lower case, and choices on one line. Stem initials such as `W. H. Bragg` are not choices.
- The `ANSWER:` line, and the typo `ANWER:`.
- Hard-wrapped lines. It rejoins a word that a hyphen split, and it keeps real compounds such as `half-life`.
- Rule lines, round titles such as `ROUND ROBIN 2`, page footers such as `PAGE 4`, and omission notes.
- Invisible characters, math-italic letters, and private-use glyphs from PDF symbol fonts.

## Hear formulas, units, and symbols

The unit stage runs first. The formula stage runs second. Plain numbers stay as digits, and the voice reads them. Only the header number, formulas, scientific notation, isotopes, and currency become words.

| In the question | In the spoken script |
| --- | --- |
| `H2O` | H two O |
| `NaCl` | N A C L |
| `C6H12O6` | C six H twelve O six |
| `Ca(OH)2` | C A open parenthesis O H close parenthesis two |
| `Fe3+` | F E three plus |
| `SO4 2-` | S O four two minus |
| `2H2 + O2 → 2H2O` | two H two plus O two yields two H two O |
| `Cu(s)` | C U solid |
| `[H+]` | H plus |
| `6.02 × 10^23` | six point oh two times ten to the twenty-third |
| `x^2` | x squared |
| `5 m/s` | 5 meters per second |
| `37 °C` | 37 degrees Celsius |
| `890 kJ/mol` | 890 kilojoules per mole |
| `1 eV` | 1 electron volt |
| `ATP` | A T P |
| `α-helix` | alpha-helix |
| `x ≤ 5` | x is less than or equal to 5 |
| `√144` | square root of 144 |

The examples come from the project's tests for the unit stage and the formula stage. The full script runs both stages, so spacing can differ.

Know these rules:

- **Elements are spelled, never named.** `Na` is "N A". The element table has all 118 symbols, and a symbol must be real before the app spells it.
- **Detection is careful.** A token needs a digit count, a charge, or two or more symbols with mixed case, as in `NaCl`. Words that are also symbols stay words: `As`, `He said`, `In`, `No`, `I`, `US`, `Be`, and `At`. Next to a reaction arrow or a plus sign, they are spelled.
- **Arrows and state symbols become words.** `→` is "yields". `⇌` is "is in equilibrium with". `(aq)`, `(s)`, `(l)`, and `(g)` after a formula are "aqueous", "solid", "liquid", and "gas".
- **Spaced PDF subscripts close up.** `H 2 O` and `Ca(OH) 2` read as `H2O` and `Ca(OH)2` when every token is an element or a digit.
- **Flattened exponents are repaired** when the shape is clear. `4.56 × 1011` reads as 4.56 times ten to the eleventh. A range such as `pH 10–12` stays a range.
- **Isotopes keep the m.** `technetium-99m` is "technetium ninety-nine m", never "99 meters".
- **Currency is spoken.** `$16.50` is "16 dollars 50 cents".
- **Acronyms are spelled by letter.** The list includes DNA, RNA, ATP, ADP, AMP, NAD, NADH, NADP, NADPH, FAD, HIV, PCR, UV, IR, LED, GPS, MRI, CPU, USA, UK, UN, EU, and DOE. Gene symbols such as TP53 and BRCA1 are spelled with number words ("T P fifty-three"). NASA and LASER are words, so they are not on the list.
- **Minus signs are repaired.** An en dash or hyphen between terms in algebra, as in `2x – 6y`, becomes "minus". A range between plain numbers, as in `5–10 grams`, stays a range.

## Use guides in brackets

A guide is text in square brackets after the word it describes. NSB moderators see guides in the printed question. The app takes each guide out of the text and uses it. There are three kinds.

| Kind | Example in the question | What the app does |
| --- | --- | --- |
| Phonetic respelling | `Krebs cycle [KREBZ SY-kul]` | Speaks "Krebs cycle" with the sounds of the guide. |
| Say-as | `4 2/7 [4 and two-sevenths]` | Speaks the guide's words in place of the expression. `[yields]` after an arrow reads the arrow as "yields". |
| Spell | `FAD [F.A.D.]` | Speaks the letters: "F A D". `[H-E-2-S-1]` is "H E two S one". |

The forms `(read as: …)` and `(pronounced: …)` work like brackets. A trailing `Read as: …` is accepted as well. Brackets that hold a moderator note, such as `[NOTE: STUDENTS MUST GIVE BOTH ANSWERS]`, are dropped and not spoken.

### Write a phonetic guide

- Join syllables with hyphens. Write the stressed syllable in capitals. Separate the words of a name with a space.
- The first capital syllable of a word gets the main stress. Later ones get a lighter stress.
- A guide with several syllables and no lowercase is ignored, because it was likely upper-cased by the paste.
- For "pi-KAHN or PEE-kan", the first variant is spoken.
- Guides that work in the project's tests: `FAR-ingks`, `KREBZ SY-kul`, `i-SOF-uh-guhs`, `TRAY-kee-uh`, and `nye-DAIR-ee-uh`.

If the rules cannot place every part of a guide, the app speaks the printed word plain and shows a warning. It never guesses.

## Hear hard words and chemical names

- **The lexicon.** A built-in table holds more than 500 hard science words with an exact pronunciation, for example `abiotic`, `acetaldehyde`, `allele`, `amylase`, `asthenosphere`, `avogadro`, `bacteriophage`, `basalt`, and `batholith`. The app matches whole words and ignores case.
- **Systematic names.** The app builds the sound of a name such as `2-methylpropan-1-ol` from locants and morphemes. A table of about 150 morphemes supplies the parts. The result carries one main stress. If any part is unknown, the engine speaks the name as written.
- **Name check.** A systematic name gets this treatment only after OPSIN parses it. OPSIN runs on your Mac in a bundled Java runtime, so this step works offline.

## Know how name lookups work

Lookups need a network, except for the OPSIN check. They are on by default. Turn them off with the **Online lookups** checkbox, the `--offline` flag, or `CLOUDYREADER_OFFLINE=1`.

| Question | Answer |
| --- | --- |
| What gets looked up? | Names marked chemical, protein, or gene. Never formulas, and never text around a name. |
| What is skipped? | A name the lexicon already knows. A name that is empty, holds control characters, or is longer than 256 characters. |
| How often? | Once per unique name in a reading. |
| Which service? | A systematic-looking chemical name goes to OPSIN first. If OPSIN fails, or the name is not systematic, a chemical goes to PubChem. A protein or gene goes to UniProt. |
| How long may it take? | 2.5 seconds for the whole reading. One request may take up to 4 seconds, within what is left of the budget. |
| How fast? | At most 5 requests per second. After HTTP 429 or 503, the app retries up to twice, after 0.5 and 1 second, if time is left. |
| What if time runs out? | The unfinished lookups count as "timeout", and late answers are dropped. The reading goes on. |
| Is anything stored? | Yes. Found names are cached for 30 days and not-found names for 1 day. Timeouts, offline results, and errors are never cached. |
| What do the answers change? | See the note below. |

**What the answers change.** In this version, only the local OPSIN result changes what you hear. PubChem and UniProt answers are fetched, cached, and attached to the reading. The script builder ignores them. A lookup therefore adds network traffic and, when the services are slow, up to 2.5 seconds of waiting. It does not change the sound. See [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}) for what leaves your Mac.

## Read pronunciation warnings

When something cannot be honored, the status bar shows a warning and the reading goes on. The full text is in the tooltip.

| Warning starts with | What it means |
| --- | --- |
| `Guide [` … `] dropped:` | The word that the guide describes is not in the text. |
| `No pronunciation for respelling` | The rules could not place the guide. The word is spoken plain. |
| `Pronunciation for` … `dropped` | The IPA held punctuation, which would cause a pause. |
| `piper: dropped IPA symbol` | The Piper voice has no such sound. The app keeps the rest. |
| `piper: override` … | The override had no usable symbols, or its word was not in the segment. |
| `Kokoro: could not pronounce` | Kokoro could not turn the word into sounds. It skipped the word, so it is spoken as nothing. |
| `Kokoro: dropped`, `Kokoro: no usable phonemes`, `Kokoro: override surface` | The Kokoro engine could not use an override. |
| `entity detection failed`, `name lookup failed`, `pronunciation check failed` | A stage that only refines the speech failed. The reading continues without it. |

## Fix a word that sounds wrong

Add a guide to the pasted text, right after the word:

```text
Name the cycle that follows glycolysis in the mitochondrion. Krebs cycle [KREBZ SY-kul]
```

Rules of thumb:

1. Put the guide directly after the printed word, with a space before the bracket.
2. Write the sounds with plain English spellings, such as `ee`, `oh`, `oo`, `uh`, and `eye`.
3. Capitalize only the stressed syllable.
4. Check the **Spoken script** view and the status bar for warnings.

## Know the limits

- The pronunciation rules target American English. The engines have English voices only.
- The app has no user dictionary file in this version. Use guides in the text.
- The app reads text. It cannot read an image of a question.
- A voice engine may still mispronounce a word that has no entry and no guide.
