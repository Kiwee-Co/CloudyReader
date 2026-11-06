---
title: Documentation style guide
description: 'The style guide for the Cloudy Reader documentation: voice, terminology, formatting, page types, figures, and checks.'
sidebar:
  order: 5
---

This guide governs every page of the Cloudy Reader documentation. When this guide and an older page disagree, this guide wins. Read [Edit the documentation](/developer/contributing/#edit-the-documentation) for the tools and the folder layout.

## Voice and tone

- Write in a professional, calm, concise voice, as a knowledgeable colleague and not as a salesperson.
- Use the second person ("you"). Call the project "the project", never `we`.
- Write steps in the imperative. Give one action per step, and one sentence per action when possible.
- Use the present tense and the active voice. Do not use the future tense for app behavior: write `The app reads`, not `The app will read`.
- Use US English spelling and punctuation, the serial comma, and double quotation marks.
- Keep sentences to 25 words or fewer, and keep procedure steps to 20 words or fewer.
- Write no marketing language, no emoji, no exclamation marks, and no rhetorical questions outside the FAQ.
- Use inclusive language. Write "they" for an unknown person, and avoid ableist idioms such as `blind to` or `crazy`. Describe the rotation gender labels as labels from the voice data.
- Describe the shipped version in the present tense. Do not write `currently`, `in this version`, `the current build`, `for now`, `soon`, or `new`. The footer states the version, and the release notes say what changed.
- Never claim that the app's reading is official, correct by definition, or how a moderator must read.

## Terminology

Use the canonical term. Do not use the banned variants in prose. A banned variant may appear in quoted UI text, quoted error text, and code. Where an entry says so, it may also appear on developer pages.

### Questions and the competition

- **question**: One National Science Bowl question as pasted: header, stem, choices if any, and an optional answer line. Do not use `item`, `problem`, or `prompt`.
- **toss-up**: A question any player may answer first. Do not use `tossup`, `toss up`, or `Tossup` in mid-sentence.
- **bonus**: The follow-up question for the team that answered the toss-up. Do not use `Bonus` in mid-sentence or `bonus round`.
- **stem**: The question text before the choices. Do not use `body`, `question text` for the stem, or `prompt`.
- **choice**: One of the four answers W, X, Y, and Z of a multiple-choice question. Do not use `option`, `answer choice`, or `alternative`.
- **choice letter**: W, X, Y, or Z. Do not use `option letter`.
- **multiple choice, short answer**: The two question formats. Hyphenate them as adjectives, as in "a multiple-choice question". Do not use `MC` or `SA`.
- **category**: The subject label, such as EARTH SCIENCE. Do not use `subject` or `topic`.
- **answer line**: The `ANSWER:` line of a question, and the **Read answer line** option. Do not use `answer key` or `solution`.
- **round**: A set of toss-ups and bonuses read in one match. Do not use `packet` for a round.
- **moderator**: The person who reads questions in a match. Do not use `reader`, which is ambiguous with the app, `host`, or `announcer`.

### Reading and voices

- **reading**: One run of **Speak**: the spoken script and its audio. Do not use `playback`, which means the sound playing, `utterance`, or `job`.
- **spoken script**: The words the voice receives after conversion, shown in the **Spoken script** view. Do not use `transcript`, `normalized text`, or `TTS text`.
- **voice**: One entry you can choose in the **Voice** menu, such as "lessac (en-US, medium)". Do not use `speaker`, `narrator`, or `model`.
- **speaker**: The number in the **Speaker** box of a voice with several speakers. Do not use `voice ID`.
- **voice engine** (**engine** after the first use): The speech software that makes a set of voices, such as Piper. The page Voices and rotation modes lists every engine. Do not use `library`, `TTS library`, `TTS engine` (except in quoted error text), `backend`, or `synthesizer`.
- **supported voices**: The voices the app downloads and checks at first launch. [Voices and rotation modes](/manual/reference/voices/) lists them. Do not use `built-in voices` or `bundled voices`. Use `pinned voices` on developer pages only.
- **rotation**, **rotation mode**: How **Speak** picks the next voice. The six modes use their exact menu labels. Do not use `voice cycling`, or `shuffle mode` as a generic term.

### Pronunciation

- **pronunciation guide** (**guide** after the first use): Text in square brackets after a word that sets how the app says it. Do not use `bracket hint`, `annotation`, `hint`, or `respelling` for all kinds.
- **phonetic respelling**: A guide kind, as in `[KREBZ SY-kul]`. Do not use `phonetic guide` or `respelling guide`.
- **say-as guide**: A guide kind, as in `[4 and two-sevenths]`. Do not use `spoken guide`, or `Say-as` capitalized in mid-sentence.
- **spell guide**: A guide kind, as in `[F.A.D.]`. Do not use `spelling guide`.
- **lexicon**: The built-in table of hard science words with exact pronunciations. Do not use `dictionary` or `word list`.
- **name detection**: The step that finds formulas and chemical, gene, and protein names. Do not use `NER` or `entity detection` on user pages.
- **name-detection model**: The scientific language model that name detection loads. Do not use `science model`, `NER model`, or `scispaCy model` on user pages.

### Network, files, and offline use

- **name lookup** (**lookup** after the first use): A request to PubChem or UniProt about a detected name. Do not use `query`, `API call`, `resolution`, or `online check`.
- **OPSIN check**: The local parse of a systematic chemical name. It uses no network. Do not use `OPSIN lookup`.
- **offline mode**: `--offline` or `CLOUDYREADER_OFFLINE=1`, which stop the lookups and the voice download. Do not use `airplane mode` or `offline setting`.
- **Online lookups**: The option that allows lookups. Clearing it is not offline mode. Do not use `online mode`.
- **voice download**: The background download, at launch, of the files that the supported voices need. Do not use `prefetch`, `sync`, or `update`.
- **data folder**: `~/Library/Application Support/cloudyreader`. Do not use `data directory`, `app data`, or `support folder`.
- **audio cache**: The `cache/wav` folder. Do not use `WAV cache` on user pages.
- **self-test**: `--self-test`. Do not use `selftest`, `self test`, or `diagnostic`.

### The window

- **status bar**: The bar at the bottom of the window. Do not use `status line`, `footer`, or `message bar`.
- **status message**: A message in the status bar. Its tone is information, warning, or error. Do not use `notification` or `toast`.
- **warning**: A status message that starts with "Warning:" or "_n_ warnings:". The reading goes on. Do not use `alert`.
- **error**: A status message that starts with "Error:". The reading did not happen. Do not use `failure message`.
- **question box**: The text area where you paste. Do not use `text field`, `input area`, `editor`, or `text box`.
- **pop-up menu**: The **Voice** and **Rotation** controls. Do not use `dropdown`, `drop-down`, `combo box`, or `picker`.
- **checkbox**: **Read answer line** and **Online lookups**. Do not use `check box`, `toggle`, or `tick box`.

### The product, the Mac, and organizations

- **Cloudy Reader**, **the app**: The product. Write "the app" after the first mention on a page. Do not use `CloudyReader` (except the repository name), `cloudyreader` (except identifiers), `the program`, or `the tool`.
- **Mac with Apple silicon**: A Mac with an Apple chip. Do not use `Apple Silicon`, `M1 Mac`, or `ARM Mac`.
- **Intel-based Mac**: A Mac with an Intel processor. `Intel Mac` is acceptable in tables only.
- **macOS**: The operating system. Write it by number, as in "macOS REL-MACOS-FLOOR or later". Do not use `Mac OS`, `OS X`, `OSX`, or `MacOS`.
- **System Settings**: The macOS settings app. Do not use `System Preferences`.
- **Terminal**: The macOS app. Write "in Terminal". Do not use `the terminal`, `command prompt`, or `shell` on user pages.
- **National Science Bowl**: Spell it out on first use on every page. Do not use `NSB` or `Science Bowl`.
- **U.S. Department of Energy**: Spell it out. Do not use `DOE` or `US DOE`.
- **SHA-256**: The checksum algorithm. Do not use `SHA256`, or `sha256` outside code.
- **ad-hoc signature**, **signed ad hoc**: Hyphenate before a noun only. Do not use `adhoc` or `ad hoc signature`.
- **notarized**: Apple's malware check for apps distributed outside the App Store. Do not use `notarised` or `certified`.
- **quarantine flag**: The attribute macOS sets on downloaded files. Do not use `quarantine bit` or `quarantine attribute` on user pages.

### Verbs for the interface

Click a button. Choose a menu item or a pop-up menu value. Select or deselect a checkbox. Press a key. Type or paste text. Never write `hit`, `tap`, `click on`, `check`, or `uncheck` for these actions.

## Formatting

### UI labels, menus, and keys

- Write a UI label exactly as the app shows it, in bold, without a trailing colon: **Voice**, **Rotation**, **Read answer line**, **Online lookups**, **Paste**, **Speak Clipboard**, **Repeat**, **Stop**, **Speak**, **Spoken script**.
- Write a menu path in bold, with " > " between levels: **Reading > Speak**, **System Settings > Privacy & Security**.
- The rotation modes are UI labels: **No rotation**, **Round robin**, **Random shuffle**, **US only (random shuffle)**, **Men only**, **Women only**.
- Quote a status message exactly in prose, with the app's ellipsis character (…). Write variables in italics, as in "Playing _n_ s." Do not bold or code-format a status message.
- In text and steps, spell key names and join them with hyphens, as Mac documentation does: Command-Return, Command-Shift-V, Command-R, Command-Period (.), Command-W, Command-Q. Never write `Cmd`, `Cmd+`, or a bare `⌘` in prose.
- Only the keyboard shortcuts page shows glyphs. It adds a **Tooltip shows** column with the glyphs inside `kbd` elements, because the app prints those glyphs in its tooltips and in the question box placeholder. macOS draws the native menus and may show a different Return glyph, so do not describe the glyphs of the menus. The words column comes first, so screen readers read the words first.

### Code, paths, numbers, units, and dates

- Use code spans for commands, options, environment variables, file names, paths, preference keys, pasted-text examples, and exact Terminal output: `--offline`, `~/Library/Application Support/cloudyreader`.
- Use `bash` code blocks for commands, with no `$` prompt and one command per line. Use `text` code blocks for output and sample questions. Make every command copyable as written, and quote paths with spaces: `"/Applications/Cloudy Reader.app"`.
- Pair a path with the Finder way to reach it: **Go > Go to Folder**.
- Spell out the numbers zero to nine in prose. Use numerals for 10 and above, for measurements, versions, keys, and table cells, and when a sentence mixes counts: "3 toss-ups and 12 bonuses".
- Put a space between a number and its unit symbol. Write sizes in decimal units, as Finder shows them: "12.5 MB", "1.4 GB". Spell out time in prose: "5 seconds", "300 milliseconds". Tables may use "s" and "ms".
- Say "about" for approximate values: "about 40 MB". Do not round a value differently on different pages. Take each value from the code or from the release build.
- Write a version as "version 1.2.3". Write the tag `v1.2.3` only in code or URLs. Write macOS by number only, never by its marketing name, as in "macOS REL-MACOS-FLOOR or later".
- Write dates as "March 3, 2027" in prose. Use ISO dates only in the changelog.

### Asides

Use the Markdown syntax, such as `:::note`. The four types are:

| Type      | Use for                                                                      | Example                                                  |
| --------- | ---------------------------------------------------------------------------- | -------------------------------------------------------- |
| `note`    | Context the reader may skip without harm                                     | The dialog wording differs between macOS versions.       |
| `tip`     | A faster or better optional way                                              | Command-Shift-V pastes and speaks in one step.           |
| `caution` | A security trade-off, data loss, or a confusing failure                      | Removing the quarantine flag skips the Gatekeeper check. |
| `danger`  | Disabling a macOS protection for all apps, or deleting data with no recovery | Expected on no page. Ask the editor first.               |

The limits:

- Use at most 2 asides on a tutorial or task page and at most 3 on any other page. Use none on a cheat sheet.
- Never put two asides in a row. Never put an aside inside a table or a step list item.
- Write at most 3 sentences in an aside, and keep the default title.

### Tables

- Write an intro sentence before every table.
- Write sentence-case headers. Make the first column the lookup key.
- Use two to five columns on user pages, and four or fewer on tutorial and task pages, which phones read.
- Leave no cell empty: write "None". Put no line break or list inside a cell. Merge no cells.
- Put units in the header, not in every cell: "Size (MB)".
- Split a table of more than 15 rows, unless it is a catalog or a cheat sheet.
- Use no tables in tutorials, except "You paste, You hear" pairs.

### Headings

- Use exactly one H1 per page: the front matter `title`. Never write `#` in the body.
- Write headings in sentence case, with no final punctuation and no code, links, or quotation marks.
- Use H2 for sections and H3 for subsections. Use no H4.
- Start tutorial and task headings with an imperative verb: "Approve the app". Write reference and concept headings as noun phrases: "Rotation modes". Only the FAQ and the troubleshooting symptoms use question or statement headings.
- Never start a heading with `Know`. Never use `Introduction` or `Overview` as a heading.
- Do not rename a heading that another page links to. The site checker reports a broken anchor.

### Links

- Name the destination page title or the task in the link text, as in `[Work offline](/manual/tasks/work-offline/)`. Never use `here`, `this page`, `click here`, or a bare URL as link text.
- Write internal links as root-relative paths with a trailing slash and no host: `/manual/reference/voices/`.
- Use `https://` for external links. The allowed hosts are `github.com`, the upstream projects and services that the licenses page lists, PubChem, UniProt, and Hugging Face.
- Link a term on its first use on a page, at most once per section, and never in a heading.
- Link a glossary term on its first use only where the reader may not know it: toss-up, stem, pronunciation guide, voice engine, and offline mode.

### Front matter and descriptions

- `title`: at most 60 characters, in sentence case. Add `sidebar.label` only when a short label helps.
- `description`: one sentence of at most 160 characters, unique on the site. Start with a verb or a noun, never with `This page`.
- `sidebar.order`: the position of the page in its group, from 1.
- `template: splash` belongs on the landing page and the 404 page only. `pagefind: false` belongs on the 404 page only.
- File type: use `.md` by default. Use `.mdx` only when the page imports a component, such as `Figure`, `Steps`, `Card`, `LinkCard`, `LinkButton`, or `FileTree`. In `.mdx`, keep `{`, `}`, and `<` inside code spans, or escape them.

Description patterns by page type:

- Tutorial: `Learn to <outcome>, in about <N> minutes.`
- Task: `<Verb> <object>, <condition or result>.`
- Reference: `Every <thing> in Cloudy Reader, <what each entry tells you>.`
- Concept: `How <thing> works, and <what it means for you>.`

## Page types

Each page type has a skeleton. Keep the order of its sections. A cheat sheet holds no aside and no figure, and it prints on one page.

### Tutorial

```text
---
title: <Verb phrase>
description: Learn to <outcome>, in about <N> minutes.
sidebar:
  order: <n>
---

<One sentence: what you will do. One sentence: the result.> This tutorial takes about <N> minutes.

## Before you start
<What you need, with links. Omit when it is only "Cloudy Reader with a voice".>

## <Verb phrase for step group 1>
<Steps> … then one checkpoint sentence: "The status bar shows …"

## <Verb phrase for step group 2>

## What you learned
<3 to 5 bullets>

## Next steps
<2 or 3 links>
```

### Task

```text
---
title: <Verb phrase>
description: <Verb> <object>, <condition or result>.
sidebar:
  order: <n>
---

<One or two sentences: when you need this.>

## <Verb phrase>
<Steps> … then the result: "The window opens."

## <Verb phrase for an alternative or a follow-up>

## Related
<At most 4 links. Optional.>
```

### Reference

```text
---
title: <Noun phrase>
description: Every <thing> in Cloudy Reader, <what each entry tells you>.
sidebar:
  order: <n>
---

<One sentence: what the page lists.>

## <Noun group>
<Intro sentence.>
<Table>
```

### Concept

```text
---
title: <Noun phrase or "How …">
description: How <thing> works, and <what it means for you>.
sidebar:
  order: <n>
---

<The key idea in two sentences.>

## <Aspect>
<Paragraphs of 3 to 5 sentences. One figure where it helps.>

## Related
```

### Troubleshooting entry

```text
### <Symptom in plain words>

The status bar shows "<exact message>". <or the exact dialog text>

**Cause.** <One to three sentences.>

**Fix.** <Steps or one paragraph, with links.>
```

### FAQ entry

An FAQ entry is an H2 question, then an answer of at most three sentences. End the answer in a link where a page owns the topic.

## Figures

- Use the `Figure` component with both renderings: `<Figure src="x-light.svg" dark="x-dark.svg" alt="…" caption="…" />`. Add `frame="window"` to a window snapshot, and `wide` to a diagram that is wider than a phone screen.
- Name a figure file `<subject>[-<state>]-<light|dark>.svg`, in lowercase with hyphens.
- Write alt text of one or two sentences and at most 250 characters. Start with the object: "The Voice menu open…". Name the state that matters, such as the selected voice or the status text. Never write `image of` or `screenshot of`. Do not repeat the caption.
- For a callout figure, the alt text describes the window. A numbered legend under the figure, an ordered list, carries the meaning. The markers are hidden from assistive technology.
- Write a caption of one sentence that ends with a period and says what to notice.
- Convey no meaning by color alone.
- Place a figure after the paragraph that introduces it, never as the first element of a page.
- Draw the app figures from the live window with `scripts/make_doc_snapshots.py`. Put no caption inside an image, and use no motion.
- Never redraw macOS system UI, such as Gatekeeper or Finder, as app UI. Use steps, a schematic diagram, or real screenshots.

## Checks

Run these checks before you push:

1. Build the site and run `python3 scripts/check_site.py site/dist`. [Edit the documentation](/developer/contributing/#edit-the-documentation) lists the commands.
2. Run `markdownlint` and `prettier --check` on the page.
3. Search the page for the banned words and variants below.
4. Check that the description has 160 characters or fewer and is unique.
5. Check the headings: one H1, sentence case, no skipped level, and no H4.
6. Check that every figure has both renderings, alt text, and a caption.
7. Check every number, string, and command against the code.

### Banned words

Outside code, quoted UI text, and quoted error text, these must not appear:

- Filler and marketing: `simply`, `just` as filler, `easy`, `easily`, `effortless`, `seamless`, `powerful`, `robust`, `intuitive`, `best-in-class`, `amazing`, `cutting-edge`, `state-of-the-art`, `leverage`, `utilize`, `please`, `obviously`, `of course`, `basically`, `actually`, `very`, and `really`.
- Time-bound words: `currently`, `at the moment`, `for now`, `in this version`, `the current build`, `soon`, `coming soon`, `new` for a feature, and `latest` except the GitHub page name.
- Process text: `untested`, `CI does not run them`, `TODO`, `TBD`, `FIXME`, and `filled in at publish time`.
- Latin abbreviations: `e.g.`, `i.e.`, `etc.`, `via`, `vs.`, and `cf.`.
- Headings that start with `Know`, and the headings `Introduction` and `Overview`.
- Every banned variant in the terminology lists above.
