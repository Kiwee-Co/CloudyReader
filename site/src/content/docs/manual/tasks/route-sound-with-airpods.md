---
title: Route sound with AirPods and BlackHole
description: Send the sound of Cloudy Reader to your AirPods and to another app, with BlackHole and a Multi-Output Device or with Loopback.
sidebar:
  order: 9
---

Cloudy Reader plays its readings through the sound output that macOS has set. Use this page to hear them in your AirPods while another app, such as a video call, receives the same sound. Connect the AirPods before you start.

## Use BlackHole and a Multi-Output Device (recommended)

[BlackHole](https://github.com/ExistentialAudio/BlackHole) is a free virtual audio device. Install its 2-channel version, **BlackHole 2ch**, and then follow these steps.

1. Open **Audio MIDI Setup** in the **Utilities** folder. Click **+** and choose **Create Multi-Output Device**.
2. Select the **Use** checkbox for **BlackHole 2ch** and your AirPods.
3. As a precaution in case the AirPods disconnect, also select **Use** for the built-in speakers or a wired headset.
4. In the **Primary Device** pop-up menu, choose the built-in speakers or **BlackHole 2ch**, never the AirPods.
5. Select the **Drift Correction** checkbox (shown as **Sync** on macOS 27) for every device except the primary device.
6. Choose **System Settings > Sound > Output** and select the Multi-Output Device.
7. In the app that receives the sound, choose **BlackHole 2ch** as the input or microphone.

Leave Cloudy Reader on the system output. It has no output setting of its own, so its readings reach **BlackHole 2ch** and your AirPods. The AirPods microphone runs at a lower sample rate, so the AirPods must never be the primary device.

macOS has no volume control for a Multi-Output Device. Set the volume of each device in **Audio MIDI Setup**, and mute the built-in speakers there to hear only the AirPods. If the AirPods disconnect, reconnect them and check that **System Settings > Sound > Output** still shows the Multi-Output Device.

## Use Loopback instead

Loopback by Rogue Amoeba is an alternative. In Loopback, set your AirPods as the monitor output. The project has not tested it.

## Turn off Automatic Ear Detection

Automatic Ear Detection stops the sound when you take the AirPods off. To turn it off, wear the connected AirPods, click their name in the **System Settings** sidebar, and turn off **Automatic Ear Detection**. If you do not see the switch, click **Audio & Routing** first. On AirPods Max, the switch is **Automatic Head Detection**.

## Related

- [Run a team practice](/manual/tasks/team-practice/)
- [You hear nothing](/manual/troubleshooting/#you-hear-nothing)
