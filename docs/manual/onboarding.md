---
layout: page
title: Onboarding guide
nav_group: Manual
nav_order: 0
permalink: /manual/onboarding/
description: Download, install, approve the app once, wait for the voices, and hear your first question, in five steps.
---

Cloudy Reader reads National Science Bowl questions aloud on your Mac. This guide is the short version of [Get started]({{ '/manual/getting-started/' | relative_url }}).

Cloudy Reader needs a Mac with Apple silicon and macOS 26.2 or later. Apple silicon means an M1 chip or later; **Apple menu > About This Mac** shows yours.

If macOS asks for an administrator's name and password, ask the person who manages the Mac.

1. [Download the zip]({{ site.repo_url }}/releases/tag/v0.0.1) (459 MB).
2. Double-click the zip unless your browser unzipped it. Drag **Cloudy Reader** onto **Applications** before you open it.
3. Approve the app. The app is signed ad hoc and is not notarized, so macOS asks you to approve the [first launch]({{ '/manual/getting-started/#open-the-app-for-the-first-time' | relative_url }}) once. Approve only a copy that matches the SHA-256 on the [release page]({{ site.repo_url }}/releases/tag/v0.0.1).
   - Open Cloudy Reader. macOS warns that it cannot verify the app. Close the warning dialog, and do not move the app to the Trash.
   - Choose **Apple menu > System Settings**, click **Privacy & Security**, and scroll to **Security**.
   - Click **Open Anyway**. Confirm with your password or Touch ID.
   - Open the app again and click **Open**.
4. Keep the window open and the Mac online. The app downloads its voices, which read questions aloud, about 0.66 GB. The first voice usually arrives in under a minute. The **Voice** menu then shows it, and **Speak** is no longer dimmed while the rest downloads. If no voice arrives, see [No voice is installed]({{ '/manual/troubleshooting/#the-status-bar-says-no-voice-is-installed' | relative_url }}).
5. Copy this toss-up:

   ```text
   TOSS-UP
   2) EARTH SCIENCE Multiple Choice The source of energy for the movements of
   crustal plates is currently thought to be the result of:
   W) tidal motion that produces a net westward movement of landmasses
   X) the pulling apart of the poles resulting from the Earth’s rotation
   Y) convection currents produced within the mantle
   Z) remnant magnetism
   ```

   Click the question box, press Command-V, then press Command-Return or click **Speak**. The status bar shows "Preparing…", then "Playing _n_ s.", and you hear the question.

## Next steps

- [Use the app]({{ '/manual/using-the-app/' | relative_url }})
- [Troubleshooting]({{ '/manual/troubleshooting/' | relative_url }})
