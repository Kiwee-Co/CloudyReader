---
layout: page
title: Pronunciation
nav_group: Manual
nav_order: 4
permalink: /manual/pronunciation/
description: How Cloudy Reader turns formulas, units, symbols, and names into speech, and how to fix a word.
---

Cloudy Reader changes how a word sounds. It never changes which word is said. The app spells the formula `NaHCO3` as "N A H C O three". It never swaps in "baking soda". Every stage on this page follows that rule: lookups and the lexicon pick sounds, not words.

## Follow the stages

| Step                | What the app does                                                                                                                         | Network                  |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| 1. Clean and parse  | Fixes PDF leftovers. Finds the header, number, category, format, stem, choices, and answer. Takes bracket guides out of the text.         | No                       |
| 2. Detect names     | Marks formulas, chemical names, genes, and proteins in the stem and the choices. It marks the answer too when **Read answer line** is on. | No                       |
| 3. Look up names    | Asks OPSIN on your Mac about systematic names. Asks PubChem and UniProt about other names.                                                | PubChem and UniProt only |
| 4. Build the script | Applies guides, then units and symbols, then fractions, then formulas and notation, then the lexicon.                                     | No                       |
| 5. Speak            | The voice engine turns the script and the pronunciation overrides into audio.                                                             | No                       |

The **Spoken script** view shows the words that step 4 builds. Step 4 also sets the silent pause after each part of a question. See [Use the app]({{ '/manual/using-the-app/' | relative_url }}) for the view and the pause table.

## Know what the parser cleans

Pasted text from PDFs and web pages is messy. The parser handles these cases:

- A header such as `TOSS-UP` or `BONUS`, and a number such as `12)`.
- A category in capitals, or in title case before a printed format label. It also fixes a category glued to its label, as in `ENERGYMultiple Choice`.
- The labels `Multiple Choice` and `Short Answer`.
- Choices marked `W)`, `X)`, `Y)`, and `Z)`. It also accepts `W.`, `W:`, lower case, and choices on one line. Stem initials such as `W. H. Bragg` are not choices.
- The `ANSWER:` line, and the typo `ANWER:`.
- Hard-wrapped lines. It rejoins a word that a hyphen split. It keeps real compounds such as `half-life`.
- Rule lines, round titles such as `ROUND ROBIN 2`, page footers such as `PAGE 4`, and omission notes.
- Invisible characters, math-italic letters, and private-use glyphs from PDF symbol fonts.

## Hear formulas, units, and symbols

The unit stage runs first. The fraction stage runs second. The formula stage runs third. Plain numbers stay as digits, and the voice reads them. The app turns digits into words inside fractions, formulas, exponents, scientific notation, isotope names, gene symbols, and the header number.

| In the question   | In the spoken script                           |
| ----------------- | ---------------------------------------------- |
| `H2O`             | H two O                                        |
| `NaCl`            | N A C L                                        |
| `C6H12O6`         | C six H twelve O six                           |
| `Ca(OH)2`         | C A open parenthesis O H close parenthesis two |
| `Fe3+`            | F E three plus                                 |
| `SO4 2-`          | S O four two minus                             |
| `2H2 + O2 → 2H2O` | two H two plus O two yields two H two O        |
| `Cu(s)`           | C U solid                                      |
| `[H+]`            | H plus                                         |
| `6.02 × 10^23`    | six point oh two times ten to the twenty-third |
| `x^2`             | x squared                                      |
| `5 m/s`           | 5 meters per second                            |
| `37 °C`           | 37 degrees Celsius                             |
| `890 kJ/mol`      | 890 kilojoules per mole                        |
| `1 eV`            | 1 electron volt                                |
| `ATP`             | A T P                                          |
| `α-helix`         | alpha-helix                                    |
| `x ≤ 5`           | x is less than or equal to 5                   |
| `√144`            | square root of 144                             |

The examples come from the project's tests for the unit stage and the formula stage. The full script runs both stages, so spacing can differ.

Know these rules:

- **The app spells elements and never names them.** `Na` is "N A". The element table has all 118 symbols. A symbol must be real before the app spells it.
- **Detection is careful.** A token needs a digit count, a charge, or two or more symbols with mixed case, as in `NaCl`.
- **Words that are also symbols stay words.** Examples: `As`, `He said`, `In`, `No`, `I`, `US`, `Be`, and `At`. Next to a reaction arrow or a plus sign, the app spells them.
- **Arrows and state symbols become words.** `→` is "yields". `⇌` is "is in equilibrium with". After a formula, `(aq)`, `(s)`, `(l)`, and `(g)` are "aqueous", "solid", "liquid", and "gas".
- **Spaced PDF subscripts close up.** `H 2 O` and `Ca(OH) 2` read as `H2O` and `Ca(OH)2` when every token is an element or a digit.
- **The app repairs flattened exponents** when the shape is clear. `4.56 × 1011` reads as "four point five six times ten to the eleventh". A range such as `pH 10–12` stays a range.
- **Isotopes keep the m.** `technetium-99m` is "technetium ninety-nine m", never "99 meters".
- **The app speaks currency.** `$16.50` is "16 dollars 50 cents".
- **The app repairs minus signs.** An en dash or hyphen between algebra terms, as in `2x – 6y`, becomes "minus". A range between plain numbers, as in `5–10 grams`, stays a range.

### Hear fractions

The app reads a written fraction the way a moderator says it. A voice would read the raw slash as "slash" or drop it.

| In the question | In the spoken script         |
| --------------- | ---------------------------- |
| `1/7`           | one seventh                  |
| `3/9`           | three ninths                 |
| `5/8`           | five eighths                 |
| `2/51`          | two fifty-firsts             |
| `1/2`           | one half                     |
| `3/2`           | three halves                 |
| `3/4`           | three quarters               |
| `2/4`           | two fourths                  |
| `1/360`         | one over three hundred sixty |
| `50/50`         | fifty-fifty                  |
| `2 1/2`         | two and one half             |
| `2½`            | two and one half             |
| `-3/7`          | minus three sevenths         |

Know these rules:

- **Halves and quarters.** `1/2` is "one half" and `3/2` is "three halves". Only `1/4` and `3/4` say "quarter". Other counts of fourths say "fourths": `9/4` is "nine fourths".
- **Other denominators.** The numbers 3 to 99, 100, and 1000 give an ordinal such as "ninths". Any other denominator says "over": `5/1` is "five over one".
- **A glued ordinal suffix.** The suffix drops: `1/7th` and `2/3rds` read as "one seventh" and "two thirds". It also forces the ordinal for a large denominator: `1/360th` is "one three-hundred-sixtieth".
- **Splits.** A fraction whose parts are multiples of 5 and add up to 100 reads as a pair. `50/50` is "fifty-fifty", and `60/40` is "sixty-forty". `51/49` stays a fraction.
- **Mixed numbers use "and".** `2 1/2` and `2-1/2` are "two and one half". After a whole number, an improper fraction stays two numbers: `2 3/2` is "2 three halves".
- **Fraction glyphs read as fractions.** `½`, `¼`, `¾`, and the other glyphs from U+2150 to U+215E read as fractions. The fraction slash `⁄` and the division slash `∕` work like `/`.
- **A minus sign says "minus".** A hyphen, minus sign, or en dash directly before a fraction reads as "minus", as before a plain number.
- **Where it works.** The stem, the choices, the answer line when **Read answer line** is on, and the words of a say-as guide. A say-as guide for the whole expression still wins: `4 2/7 [4 and two-sevenths]` speaks the guide's words.

The app decides what is a fraction on the text as you pasted it, before the unit stage changes anything. It leaves a slash alone when the text is not a plain fraction of whole numbers:

- **A letter beside the slash.** `m/s`, `mol/L`, `and/or`, `t1/2`, `x/2`, and `1/x` stay. A letter that touches the denominator keeps the slash too: `1/2bh` and `4/3πr3`. The unit stage still reads `m/s` as "meters per second".
- **A root sign, a Greek letter, or a superscript on the left.** `√10/5`, `π2/6`, and `mv²/2` stay.
- **A decimal point or a thousands comma.** `1.5/2`, `1/2.5`, and `1,000/3` stay.
- **A second slash.** The date `3/9/2024` and the chain `1/2/3` stay.
- **A leading zero.** `01/02` stays.
- **Spaces around the slash.** `3 / 4` stays. The unit stage reads it as "3 over 4".
- **A number of more than nine digits.** It stays.

### Hear acronyms and gene symbols

The app spells these 37 initialisms by letter:

| Group                    | Initialisms                                                                                   |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| Biochemistry             | DNA, RNA, ATP, ADP, AMP, GMP, CMP, UMP, GTP, GDP, CTP, UTP, NAD, NADH, NADP, NADPH, FAD, FADH |
| Other science terms      | HIV, PCR, UV, IR, DC, AC, LED, LCD, CFC                                                       |
| Technology and medicine  | GPS, MRI, EKG, ECG, CPU                                                                       |
| Organizations and places | USA, UK, UN, EU, DOE                                                                          |

NASA and LASER are words, so they are not on the list.

Gene symbols follow the same idea, with number words. `TP53` is "T P fifty-three". `BRCA1` is "B R C A one". `p53` is "p fifty-three". The app also spells a fixed list of letter-only gene symbols, such as `CFTR`, `MYC`, and `KRAS`.

## Use guides in brackets

A guide is text in square brackets after the word it describes. Some questions carry guides. The app takes each guide out of the text and uses it. There are three kinds.

| Kind                | Example in the question      | What the app does                                                                                           |
| ------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Phonetic respelling | `Krebs cycle [KREBZ SY-kul]` | Speaks "Krebs cycle" with the sounds of the guide.                                                          |
| Say-as              | `4 2/7 [4 and two-sevenths]` | Speaks the guide's words in place of the expression. `[yields]` after an arrow reads the arrow as "yields". |
| Spell               | `FAD [F.A.D.]`               | Speaks the letters: "F A D". `[H-E-2-S-1]` is "H E two S one".                                              |

The forms `(read as: …)` and `(pronounced: …)` work like brackets. The app accepts a trailing `Read as: …` as well. The app drops a bracket that holds a moderator note. Example: `[NOTE: STUDENTS MUST GIVE BOTH ANSWERS]`.

### Write a phonetic guide

- Join syllables with hyphens. Write the stressed syllable in capitals. Separate the words of a name with a space.
- The first capital syllable of a word gets the main stress. Later ones get a lighter stress.
- A guide with several syllables and no lowercase letters gives no stress information. The app speaks the word plain and shows a warning.
- For "pi-KAHN or PEE-kan", the app speaks the first variant.
- Guides that work in the project's tests: `FAR-ingks`, `KREBZ SY-kul`, `i-SOF-uh-guhs`, `TRAY-kee-uh`, and `nye-DAIR-ee-uh`.

If the rules cannot place every part of a guide, the app speaks the printed word plain and shows a warning. It never guesses.

## Hear hard words and chemical names

- **The lexicon.** A built-in table holds more than 500 hard science words with an exact pronunciation.
- **Lexicon examples.** `abiotic`, `acetaldehyde`, `allele`, `amylase`, `asthenosphere`, `avogadro`, `bacteriophage`, `basalt`, and `batholith`.
- **Matching.** The app matches whole words and ignores case.
- **Systematic names.** The app builds the sound of a name such as `2-methylpropan-1-ol` from locants and morphemes. A table of about 150 morphemes supplies the parts. The result carries one main stress.
- **Unknown parts.** If any part is unknown, the engine speaks the name as written.
- **Name check.** A systematic name gets this treatment only after OPSIN parses it. OPSIN runs on your Mac in a bundled Java runtime, so this step works offline.

## Know how name lookups work

Lookups need a network, except for the OPSIN check. They are on by default. Turn them off with the **Online lookups** checkbox, the `--offline` flag, or `CLOUDYREADER_OFFLINE=1`.

| Question                     | Answer                                                                                                                                                                     |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What gets looked up?         | Names marked chemical, protein, or gene. Never formulas, and never text around a name.                                                                                     |
| What is skipped?             | A name the lexicon already knows. A name that is empty, has non-printable characters, or is longer than 256 characters.                                                    |
| How often?                   | Once per unique name in a reading.                                                                                                                                         |
| Which service?               | A systematic-looking chemical name goes to OPSIN first. A chemical that OPSIN cannot parse, or that is not systematic, goes to PubChem. A protein or gene goes to UniProt. |
| How long may it take?        | 2.5 seconds for the whole reading. One request may take up to 4 seconds, within what is left of the budget.                                                                |
| How fast?                    | At most 5 requests per second. After HTTP 429 or 503, the app retries up to twice, after 0.5 and 1 second, if time is left.                                                |
| What if time runs out?       | The app counts unfinished lookups as "timeout" and drops late answers. The reading goes on.                                                                                |
| Does the app store anything? | Yes. It caches found names for 30 days and names not found for 1 day. It never caches timeouts, offline results, or errors.                                                |
| What do the answers change?  | See the note below.                                                                                                                                                        |

**What the answers change.** In this version, only the local OPSIN result changes what you hear. The app fetches PubChem and UniProt answers, caches them, and attaches them to the reading. The script builder ignores them. A lookup therefore adds network traffic. When the services are slow, it adds up to 2.5 seconds of waiting. It does not change the sound. See [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}) for what leaves your Mac.

## Read pronunciation warnings

When the app cannot honor something, the status bar shows a warning, and the reading goes on. The full text is in the tooltip.

| Warning starts with                                                           | What it means                                                                                      |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `Guide [` … `] dropped:`                                                      | The word that the guide describes is not in the text.                                              |
| `No pronunciation for respelling`                                             | The rules could not place the guide. The app speaks the word plain.                                |
| `Pronunciation for` … `dropped`                                               | The IPA held punctuation, which would cause a pause.                                               |
| `piper: dropped IPA symbol`                                                   | The Piper voice has no such sound. The app keeps the rest.                                         |
| `piper: override` …                                                           | The override had no usable symbols, or its word was not in the segment.                            |
| `Kokoro: could not pronounce`                                                 | Kokoro could not turn the word into sounds. It skipped the word, so the voice says nothing for it. |
| `Kokoro: dropped`, `Kokoro: no usable phonemes`, `Kokoro: override surface`   | The Kokoro engine could not use an override.                                                       |
| `entity detection failed`, `name lookup failed`, `pronunciation check failed` | A stage that only refines the speech failed. The reading continues without it.                     |

## Fix a word that sounds wrong

Add a guide to the pasted text, right after the word. This question comes from the project's test files:

```text
In eukaryotic cells, the reactions of the Krebs cycle [KREBZ SY-kul]
take place in which part of the mitochondrion?
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
