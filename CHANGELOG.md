# Changelog

All notable changes to Cloudy Reader are recorded in this file, which follows Keep a Changelog and Semantic Versioning.

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
- Offline OPSIN check of systematic chemical names.
- Optional PubChem and UniProt lookups, on by default. Their answers never change the sound.
- Offline mode: `--offline` or `CLOUDYREADER_OFFLINE=1` stops the lookups and the voice download.
- The manual at <https://cloudyreader.com>.

[0.0.1]: https://github.com/Kiwee-Co/CloudyReader/releases/tag/v0.0.1
