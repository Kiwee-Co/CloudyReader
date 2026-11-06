---
layout: default
title: Cloudy Reader
description: Paste a National Science Bowl question and hear it read aloud on your Mac, with clear speech for formulas, units, and pronunciation guides.
---
{%- assign manual_start = site.pages | where: "nav_group", "Manual" | sort: "nav_order" | first -%}

## Download

**[Download Cloudy Reader 0.0.1 for macOS]({{ site.repo_url }}/releases/latest)**

- Needs an Apple Silicon Mac with macOS 26.2 or later. The download is 459 MB.
- The app downloads its voices (about 0.66 GB) the first time it opens.
- Check the SHA-256 on the release page before you open the app.
- [Get started]({{ manual_start.url | default: '/manual/getting-started/' | relative_url }}) covers the first launch and the one-time approval in System Settings.

# Start here

Cloudy Reader is a macOS app for Apple Silicon. Paste a National Science Bowl question, and it reads the question aloud. It spells out chemical formulas, says units and powers of ten in words, and follows the pronunciation guides printed in brackets. The voices run on your Mac.

| You paste             | You hear                                                 |
| --------------------- | -------------------------------------------------------- |
| `NaHCO3`              | "N A H C O three"                                        |
| `5 m/s`               | "5 meters per second"                                    |
| `2 H2 + O2 → 2 H2O`   | "2 H two plus O two yields 2 H two O"                    |
| `1.6 × 10^-19 C`      | "one point six times ten to the minus nineteen coulombs" |
| `Pharynx [FAR-ingks]` | "Pharynx", said as /ˈfæɹɪŋks/                            |

## Quick start

1. Download the app above, then move `Cloudy Reader.app` to `/Applications`.
2. Open it. [Get started]({{ manual_start.url | default: '/manual/getting-started/' | relative_url }}) explains the first launch and the voice download.
3. Paste a question, choose a voice, and press **Speak** (<kbd>Cmd</kbd>+<kbd>Return</kbd>).

Once the voices are on your Mac, reading works offline. With **Online lookups** on, the app can send a detected chemical, protein, or gene name to PubChem or UniProt, never the whole question. Start the app with `--offline` to turn off all network use. [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}) has the details.

{% for group in site.nav_groups -%}
{%- assign group_pages = site.pages | where: "nav_group", group | sort: "nav_order" -%}
{%- if group_pages.size > 0 %}
## {{ group }}

{% for item in group_pages -%}
- [{{ item.title }}]({{ item.url | relative_url }}){% if item.description %}: {{ item.description }}{% endif %}
{% endfor %}
{%- endif %}
{%- endfor %}

{% include site-note.html %}
