---
layout: default
title: Cloudy Reader
description: Paste a National Science Bowl question and hear it read aloud on your Mac, with clear speech for formulas, units, and pronunciation guides.
---
{%- assign manual_start = site.pages | where: "nav_group", "Manual" | sort: "nav_order" | first -%}

# Start here

Cloudy Reader is a macOS app for Apple Silicon. Paste a National Science Bowl question, and it reads the question aloud. It spells out chemical formulas, says units and powers of ten in words, and follows the pronunciation guides printed in brackets. The voices run on your Mac.

| You paste | You hear |
| --- | --- |
| `NaHCO3` | "N A H C O three" |
| `5 m/s` | "5 meters per second" |
| `2 H2 + O2 → 2 H2O` | "2 H two plus O two yields 2 H two O" |
| `1.6 × 10^-19 C` | "one point six times ten to the minus nineteen coulombs" |
| `Pharynx [FAR-ingks]` | "Pharynx", said as /ˈfæɹɪŋks/ |

## Quick start

1. Build the app with `make app`, as [Build the app]({{ '/developer/building/' | relative_url }}) describes, or use a built copy that someone gave you.
2. Copy `Cloudy Reader.app` to `/Applications` and open it. [Get started]({{ manual_start.url | default: '/manual/getting-started/' | relative_url }}) explains the first launch.
3. Paste a question, choose a voice, and press **Speak** (<kbd>Cmd</kbd>+<kbd>Return</kbd>).

Reading works offline. With **Online lookups** on, the app can send a detected chemical, protein, or gene name to PubChem or UniProt, never the whole question. Start the app with `--offline` to turn off all network use. [Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}) has the details.

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
