# Changelog

All notable changes to Cloudy Reader are recorded in this file, which follows Keep a Changelog and Semantic Versioning.

<!-- markdownlint-disable MD024 -->

## [0.0.3] - 2026-11-06

### Added

- `make release` stops when the app carries a folder path of the build machine. The check reads raw files, zip entries, entries of the packed app archive, the packed Python modules, and link targets.
- `make release` refuses a build Python under the home folder, because its path would ship inside the app.
- The macOS system voices: the Voice menu lists the English voices installed on your Mac, without the novelty voices, under a macOS heading after the other engines. Nothing downloads.

### Changed

- `make release` runs `hdiutil verify` up to 3 times, and only an EAGAIN failure gets a retry. A failure prints the last 20 lines of the log.
- A run from the checkout, or from a dev build made with `make app`, shows one random test-fixture question at start, never the one shown at the last start. A release build starts empty.
- The window has a new look: the Spoken script sits under the question and fills as you add text.
- The Voice menu shows the engine and the precision of every voice.
- A new About panel, in the style of macOS, opens from the app menu.
- The status bar draws its warning and error icons as lines.

### Removed

- The Paste and Speak Clipboard buttons, and the Speak Clipboard command.

### Fixed

- The choice letters W, X, Y and Z are now said by name on Qwen3-TTS (Ryan, Aiden) and Chatterbox Turbo, not read as words like "way" or "see". Each letter plays a checked recording made with the same voice.

## [0.0.2] - 2026-11-06

### Added

- Two voice engines: Chatterbox Turbo adds one built-in voice, and Qwen3-TTS adds Aiden and Ryan. Both run on your Mac, and neither clones a voice.
- A disk image installer beside the zip. Each installer has a `.sha256` file with its checksum.
- The first launch also downloads the two engines, after the Piper and Kokoro voices. Each engine file has a commit-pinned address and a SHA-256 value.
- A free-disk-space check before each engine. A skipped engine shows `<engine> not downloaded: <reason>` in the status bar.
- The app checks the SHA-256 again before the first load of an engine file. It refuses pickle files, and an engine loads only files on your Mac.
- Voice menu order: Kokoro, Chatterbox Turbo, Qwen3-TTS, then Piper. The two new engines have no grade, so their voices sort by name.
- A voice that cannot run yet shows dimmed, with its reason in the row, such as `not downloaded yet` or `offline: not downloaded`.
- The first reading with an engine shows `Preparing… loading Chatterbox Turbo (first use only)`.
- A saved voice that is not ready at start gives way to another voice, and a note in the status bar says so.
- Rotation: Chatterbox Turbo has no gender label and never rotates. US only adds Aiden, and Men only adds Aiden and Ryan.
- A new window look: the question sits in a rounded card, and the spoken script sits in its own panel. Only one progress bar shows at a time.
- VoiceOver announces warnings and `Voices downloaded.` as well as errors.
- The busy bar hides during a download and when Reduce Motion is on. The window repaints live when the system light or dark mode or the accent color changes.
- The manual at <https://cloudyreader.com> is rebuilt on Astro Starlight.

### Fixed

- A tight en dash between two ascending numbers reads as "to": `5–10 grams` is "5 to 10 grams". A hyphen or a spaced dash reads as "to" only before a unit, a percent sign, or a noun such as `pages`.
- `x<3` reads as "x is less than 3", and `x>=3` reads as "x is greater than or equal to 3".
- Function names read as words, never spelled: `sin θ` is "sine theta", and `40sin(30°)` is "40 sine(30 degrees)". The word table also covers `cos`, `tan`, `ln`, and more.
- `log3 10` reads as "log base 3 of 10". A number glued to `log` with no argument stays whole, so `log100 = 2` is "log 100 equals 2".
- A unit after "a" or "an" is singular: `a 2 kg cart` is "a 2 kilogram cart".
- A say-as guide after an expression that starts with a function name covers the whole expression.
- A fresh clone builds the app: the build folder exists before the first PyInstaller log.

## [0.0.1] - 2026-11-05

### Added

- First public release.
- Text-to-speech reading of National Science Bowl questions on Apple Silicon Macs.
- 33 voices: 5 from Piper and 28 from Kokoro.
- Voice order: best voices first inside each engine, Kokoro before Piper. A new install starts on the best installed voice.
- Background download of the voices at first launch. The release holds no voice files.
- Six voice rotation modes: No rotation, Round robin, Random shuffle, US only (random shuffle), Men only, and Women only.
- 0.3 s of exact silence inserted after each choice letter. The app cuts a voice's own silence there, so the pause lasts about 0.3 to 0.4 s.
- 0.7 s of exact silence inserted after the stem when choices follow.
- A built-in lexicon of hard science words.
- Formulas spelled as letters and number words.
- Fractions read as words: 1/7 is "one seventh", 3/9 is "three ninths", 3/4 is "three quarters".
- Mixed numbers and fraction glyphs read as words: 2 1/2 and 2½ are "two and one half".
- A split of 100 into multiples of 5 reads as a pair: 50/50 is "fifty-fifty", 60/40 is "sixty-forty".
- Fractions work in the stem, the choices, the answer line, and say-as guide words.
- Slashes in m/s, √10/5, 1.5/2, and 3/9/2024 are not read as fractions.
- Offline OPSIN check of systematic chemical names.
- Optional PubChem and UniProt lookups, on by default. Their answers never change the sound.
- Offline mode: `--offline` or `CLOUDYREADER_OFFLINE=1` stops the lookups and the voice download.
- The manual at <https://cloudyreader.com>.

[0.0.3]: https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.3
[0.0.2]: https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.2
[0.0.1]: https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.1
