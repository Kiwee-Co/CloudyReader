---
title: Onboarding guide
description: Download, install, approve the app once, wait for the voices, and hear your first question, in five steps.
sidebar:
  order: 0
---

Cloudy Reader reads National Science Bowl questions aloud on your Mac. This guide is the short version of [Get started](/manual/getting-started/).

Cloudy Reader needs a Mac with Apple silicon and macOS 26.2 or later. Apple silicon means an M1 chip or later; **Apple menu > About This Mac** shows yours.

If macOS asks for an administrator's name and password, ask the person who manages the Mac.

1. [Download the disk image](/download/) (432 MB).
2. Double-click the disk image unless your browser opened it. Drag **Cloudy Reader** onto **Applications** before you open it. Eject the disk image.
3. Approve the app. The app is signed ad hoc and is not notarized, so macOS asks you to approve the [first launch](/manual/tasks/first-open/) once. Approve only a copy that matches the SHA-256 on [Download Cloudy Reader](/download/).
   - Open Cloudy Reader. macOS warns that it cannot verify the app. Close the warning dialog, and do not move the app to the Trash.
   - Choose **Apple menu > System Settings**, click **Privacy & Security**, and scroll to **Security**.
   - Click **Open Anyway**. Confirm with your password or Touch ID.
   - Open the app again and click **Open**.
4. Keep the window open and the Mac online. The app downloads its voices, which read questions aloud, about 3.05 GB. A Mac with English system voices can speak at once with a **macOS** voice. The first downloaded voice usually arrives in under a minute, and the **Voice** menu then shows it. If no voice arrives, see [No voice is installed](/manual/troubleshooting/#no-voice-is-installed).
5. Copy this toss-up:

   ```text wrap
   TOSS-UP
   1) CHEMISTRY Multiple Choice Which gas forms when sodium bicarbonate, NaHCO3, reacts with acetic acid?
   W) Oxygen
   X) Hydrogen
   Y) Carbon dioxide
   Z) Nitrogen
   ANSWER: Y) CARBON DIOXIDE
   ```

   Click the question box, press Command-V, then press Command-Return or click **Speak**. The status bar shows "Preparing…", then "Playing _n_ s.", and you hear the question.

[Download Cloudy Reader](/download/) also offers a zip.

## Use AirPods or other Bluetooth headphones

Cloudy Reader plays through the sound output that macOS has set. To hear it in your AirPods and send the sound to another app too, such as a video call:

- **BlackHole + Multi-Output Device** (recommended, free): put **BlackHole 2ch** and your AirPods in one Multi-Output Device, and never make the AirPods the primary device.
- **Loopback** by Rogue Amoeba: an alternative that the project has not tested.
- **Automatic Ear Detection**: turn it off if the sound stops when you take the AirPods off.

[Route sound with AirPods and BlackHole](/manual/tasks/route-sound-with-airpods/) has the steps.

## Next steps

- [Your first week](/manual/first-week/)
- [Troubleshooting](/manual/troubleshooting/)
