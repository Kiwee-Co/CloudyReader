---
title: 'Licenses and credits'
description: 'The Apache-2.0 license of Cloudy Reader, the licenses of the components it bundles, and the sources of the voices and models it downloads.'
sidebar:
  order: 3
---

This page lists the license of Cloudy Reader, the licenses of its main components, and the sources of its voices and models. This page is not legal advice.

## Cloudy Reader

Cloudy Reader is licensed under the [Apache License 2.0](https://github.com/Kiwee-Co/CloudyReader/blob/main/LICENSE). The `LICENSE` file in the repository holds the terms. The app's copyright line reads "Copyright © 2026 the Cloudy Reader authors."

The release also bundles GPL components, including `piper-tts`, `jdk4py`, and `phonemizer-fork`. Distributing the app is subject to the licenses of those components.

## Bundled components

The tables list the main components of the app, with the license that each package's metadata names for the version in the release. The app also contains smaller supporting libraries, such as those that spaCy depends on, and each keeps its own license.

### GPL components

These components carry a GPL license. The Source column links the PyPI release page of the exact version, which lists the source distribution. PyPI lists no source distribution for `jdk4py`, so its link opens the project.

| Component         | Version  | License                             | Role                                             | Source                                                                           |
| ----------------- | -------- | ----------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------- |
| `piper-tts`       | 1.8.0    | GPL-3.0-or-later                    | Piper voice engine, with espeak-ng phonemization | [piper-tts 1.8.0 on PyPI](https://pypi.org/project/piper-tts/1.8.0/)             |
| `phonemizer-fork` | 3.3.2    | GPLv3 or later (package classifier) | Phonemization for Kokoro                         | [phonemizer-fork 3.3.2 on PyPI](https://pypi.org/project/phonemizer-fork/3.3.2/) |
| `jdk4py`          | 25.0.2.1 | GPL v2 (package classifier)         | Java runtime that runs OPSIN                     | [jdk4py on GitHub](https://github.com/activeviam/jdk4py)                         |

The `jdk4py` runtime reports itself as `OpenJDK Runtime Environment Temurin-25.0.2+10`. Its `legal/java.base` folder holds the GNU GPL version 2 and an `ASSEMBLY_EXCEPTION` file.

[PyInstaller](https://pyinstaller.org) 6.22.3 builds the app. Its license is GPLv2-or-later with a build exception.

### LGPL components

These components carry an LGPL license. The `num2words` link opens the PyPI release page, which lists the source distribution. PyPI lists no source distribution for the Qt for Python packages, so that link opens the project's source repository.

| Component                            | Version | License                                       | Role                             | Source                                                                       |
| ------------------------------------ | ------- | --------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------- |
| `PySide6-Essentials` and `shiboken6` | 6.12.0  | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | The window                       | [Qt for Python repository](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| `num2words`                          | 0.5.14  | LGPL                                          | Installed with the Kokoro engine | [num2words 0.5.14 on PyPI](https://pypi.org/project/num2words/0.5.14/)       |

<!-- needs-fact: exact source URLs (tags) at the bundled version for jdk4py 25.0.2.1, PySide6-Essentials and shiboken6 6.12.0, and piper-tts 1.8.0; the facts sheet marks tag URLs as not checked -->

### Components under other licenses

The table lists the other main components in alphabetical order.

| Component         | Version | License            | Role                                              |
| ----------------- | ------- | ------------------ | ------------------------------------------------- |
| `click`           | 8.5.0   | BSD-3-Clause       | Command-line toolkit that spaCy imports           |
| `en_core_web_sm`  | 3.7.1   | MIT                | English language model for the Kokoro engine      |
| `en_ner_craft_md` | 0.5.4   | CC BY-SA 3.0       | Scientific name-detection model, trained on CRAFT |
| `httpx`           | 0.28.1  | BSD-3-Clause       | HTTP client for lookups and downloads             |
| `inflect`         | 7.6.0   | MIT                | Declared dependency of the app                    |
| `misaki`          | 0.9.4   | Apache License 2.0 | Phoneme markup for Kokoro                         |
| `mlx`             | 0.32.4  | MIT                | Runs Kokoro on Apple silicon                      |
| `mlx-audio`       | 0.6.3   | MIT                | Kokoro model code                                 |
| `numpy`           | 1.26.4  | BSD                | Audio arrays in the voice engines                 |
| `onnxruntime`     | 1.31.1  | MIT                | Runs Piper voices                                 |
| `py2opsin`        | 1.2.0   | MIT                | Python wrapper that runs the OPSIN parser         |
| `scipy`           | 1.17.1  | BSD                | Needed by mlx-audio                               |
| `spacy`           | 3.7.5   | MIT                | Runtime for the name-detection model              |
| `thinc`           | 8.2.5   | MIT                | Part of the spaCy stack                           |
| `transformers`    | 5.22.1  | Apache License 2.0 | Bundled with the Kokoro engine                    |

<!-- needs-fact: license of OPSIN 2.9.0 (the jar inside py2opsin holds no OPSIN license block) and of the espeak-ng library inside espeakng-loader 0.2.4; both stay off this page until the owner confirms them -->

## Voices and models

Cloudy Reader does not include voice files. At the first launch the app downloads them from Hugging Face repositories, each pinned to one revision:

- [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) at `b4e358ffcb232591bf73a540e70f7de528e4174a` holds the Piper voices.
- [mlx-community/Kokoro-82M-bf16](https://huggingface.co/mlx-community/Kokoro-82M-bf16) at `a71e4d38b236d968966a2002c4c895dbd12b1c3c` holds the Kokoro model and its voices.

The voice files and the Kokoro model are third-party works. They are not part of the Cloudy Reader source, and they keep the terms of their publishers. Read the model card of each repository for those terms.

The name-detection model `en_ner_craft_md` 0.5.4 ships inside the app. It is the scispaCy CRAFT model, and its license is CC BY-SA 3.0.

<!-- needs-fact: license on each Piper voice model card and on the Kokoro-82M-bf16 model card; the facts sheet marks both as not checked -->

## Online services

The app can send requests to PubChem, UniProt, and Hugging Face. Each service applies its own terms. See [Privacy](/about/privacy/#what-uses-the-network) for what each request contains.

- [PubChem](https://pubchem.ncbi.nlm.nih.gov) answers name lookups for chemical names.
- [UniProt](https://www.uniprot.org) answers name lookups for protein and gene names.
- [Hugging Face](https://huggingface.co) hosts the pinned voice files.

## Credits

Cloudy Reader builds on the work of these projects and data sources:

- [Piper](https://github.com/OHF-voice/piper1-gpl) and its voices, [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices): speech for the Piper voices.
- [Kokoro-82M](https://huggingface.co/mlx-community/Kokoro-82M-bf16), converted for MLX: the Kokoro model and its voices. The voice grades come from the model's `VOICES.md` file.
- [MLX](https://github.com/ml-explore/mlx) and [mlx-audio](https://github.com/Blaizzy/mlx-audio): they run Kokoro on Apple silicon.
- [OPSIN](https://github.com/dan2097/opsin), through [py2opsin](https://github.com/JacksonBurns/py2opsin): the check of systematic chemical names.
- [scispaCy](https://allenai.github.io/scispacy/): the name-detection model, trained on CRAFT.
- [PubChem](https://pubchem.ncbi.nlm.nih.gov) and [UniProt](https://www.uniprot.org): the name lookups.
- [Hugging Face](https://huggingface.co): hosting for the voice files.
