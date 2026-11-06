---
layout: default
title: Cloudy Reader manual
description: Manual for Cloudy Reader, which reads National Science Bowl questions aloud on your Mac. Start with the onboarding guide.
---
{%- assign manual_start = site.pages | where: "nav_group", "Manual" | sort: "nav_order" | first -%}

# Cloudy Reader manual

**New here? Follow the [onboarding guide]({{ manual_start.url | default: '/manual/onboarding/' | relative_url }}).** Five steps take you from the download to your first question.

## Download

**[Download Cloudy Reader 0.0.1 for macOS]({{ site.repo_url }}/releases/tag/v0.0.1)**

Needs a Mac with Apple silicon and macOS 26.2 or later. The download is 459 MB, and the app downloads its voices, about 0.66 GB, the first time it opens.

## What you hear

Cloudy Reader is a macOS app for Apple silicon. Paste a National Science Bowl question, and it reads the question aloud. It says formulas, units, and fractions in words, and it follows the pronunciation guides printed in brackets.

| You paste                    | You hear                                                 |
| ---------------------------- | -------------------------------------------------------- |
| `C6H12O6`                    | "C six H twelve O six"                                   |
| `5 m/s`                      | "5 meters per second"                                    |
| `1.6 × 10^-19 C`             | "one point six times ten to the minus nineteen coulombs" |
| `2 1/2`                      | "two and one half"                                       |
| `Krebs cycle [KREBZ SY-kul]` | "Krebs cycle", said as /ˈkɹɛbz ˈsaɪkəl/                  |

## What stays on your Mac

- Voices and reading run on your Mac, and the audio never leaves it.
- **Online lookups** is on by default. It can send one detected chemical, protein, or gene name at a time to PubChem or UniProt, never the text around it, and you can deselect it.
- The app has no telemetry, analytics, crash reports, or update checks.

[Offline and privacy]({{ '/manual/offline-and-privacy/' | relative_url }}) lists every network use and how to turn it off.

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
