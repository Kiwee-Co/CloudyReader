---
title: Use VoiceOver and the keyboard
description: 'Use Cloudy Reader with VoiceOver and the keyboard alone: tab order, control names, announcements, and shortcuts.'
sidebar:
  order: 8
---

Use Cloudy Reader without a pointer or without sight. This page lists the tab order, the control names, what the app announces, and the keys for every reading action. The names, the order, and the announcements come from the app. The project has not tested them with VoiceOver on a Mac.

## Move through the window

Press Tab to move focus forward and Shift-Tab to move back. Tab leaves the question box and does not type a tab character. The table lists the controls in tab order.

| Control                       | Accessible name  |
| ----------------------------- | ---------------- |
| Question box                  | Question         |
| **Voice** menu                | Voice            |
| **Speaker** box               | Speaker          |
| **Rotation** menu             | Voice rotation   |
| **Read answer line** checkbox | Read answer line |
| **Online lookups** checkbox   | Online lookups   |
| **Paste** button              | Paste            |
| **Speak Clipboard** button    | Speak Clipboard  |
| **Repeat** button             | Repeat           |
| **Stop** button               | Stop             |
| **Speak** button              | Speak            |
| **Spoken script** button      | Spoken script    |
| **Spoken script** view        | Spoken script    |

Details about these controls:

- The **Speaker** box appears only for a voice with more than one speaker.
- Space selects or deselects a focused checkbox, and it opens or closes the **Spoken script** view when its button has focus.
- The **Voice** menu has the description "Choose the voice that reads the question." The **Speaker** box has the description "Choose a speaker of this voice."
- The headings in the **Voice** menu are section headers, not choices. VoiceOver reads each heading as the engine name followed by "voices".
- The **Spoken script** button has the description "Show or hide the text that is spoken".
- The question box and the **Spoken script** view show a two-tone focus ring: a thin contrast line, then a thicker ring in the accent color. The contrast line is dark in light appearance and light in dark appearance. Every other control, including the **Spoken script** button, draws the macOS focus ring.
- The **Spoken script** view is closed at every start. It is read-only and holds the words of the last reading.

## Hear what the app is doing

The app shows its state as text in the status bar. It announces errors, warnings, and the result of a voice download to assistive technology. It opens no dialog for a warning or an error.

| Tone                          | Announced                          | Examples                                       |
| ----------------------------- | ---------------------------------- | ---------------------------------------------- |
| Error                         | Yes, at once, every time           | "Error: nothing to read"                       |
| Warning                       | Yes, politely, once while it shows | "Warning: _text_" and "No voice is installed." |
| Information (download result) | Yes, politely, once while it shows | "Voices downloaded."                           |
| Information (all other)       | No                                 | "Preparing…" and "Playing _n_ s."              |

Assistive technology sees the status bar as one element named by the current message. For an error, the name holds the first line and the description holds the full text. A warning or an error also shows a system icon before its text, so color is never the only cue.

The status bar holds two bars, and only one shows at a time. The busy bar has the description "A reading is being prepared." The download bar has the description "Voice download progress."

The app does not announce the download progress. When the download ends, the status bar shows "Voices downloaded." or a warning when some files fail, and the app announces it. The status bar shows the result only when it has no other message. To check the download, see [Check which voices are installed](/manual/tasks/voices-and-storage/#check-which-voices-are-installed).

## Run every reading action from the keyboard

Every command in the **Reading** menu has a shortcut. Shortcuts work while Cloudy Reader is the active app.

| Action              | Keys                            | Available when                                        |
| ------------------- | ------------------------------- | ----------------------------------------------------- |
| **Speak**           | Command-Return or Command-Enter | A voice is selected and no reading is in preparation  |
| **Speak Clipboard** | Command-Shift-V                 | A voice is selected and no reading is in preparation  |
| **Repeat**          | Command-R                       | A reading has played and no reading is in preparation |
| **Stop**            | Command-Period (.)              | Audio is playing                                      |

A shortcut does nothing while its command is dimmed. To read a copied question from the keyboard:

1. Copy the question text in another app.
2. Press Command-Tab to switch to Cloudy Reader.
3. Press Command-Shift-V. The app pastes the clipboard and speaks it.
4. Press Command-Period (.) to stop the sound, or Command-R to hear the reading again.

The status bar shows "Preparing…", then "Playing _n_ s." [Keyboard shortcuts](/manual/reference/keyboard-shortcuts/) lists every shortcut in the app.

## Check appearance and window size

- The window follows light and dark appearance and the system accent color. It repaints when either changes.
- The app draws the card around the question box and the panel around the **Spoken script** view. The other controls use the native macOS look.
- The gray placeholder text keeps a contrast ratio of at least 4.5:1 in both appearances.
- Text uses the macOS system font. It is 15 points in the question box, 13 in the other controls, and 12 in the status bar and the **Spoken script** view. The app has no text size setting.
- With the macOS setting Reduce Motion on, the app hides the moving busy bar in the status bar. The message "Preparing…" still shows that a reading is being prepared. The app checks the setting at start and each time it becomes the active app.
- The window can shrink to 560 by 480. **Window > Zoom** switches between the maximized and the normal window.

## Work around the known limits

- The app announces a warning or the download result once. To read it again, read the status bar.
- The app does not announce other information, such as "Preparing…" and "Playing _n_ s." Read the status bar to see it.
- To move to buttons, checkboxes, and pop-up menus with Tab, turn on **Keyboard navigation** in **System Settings > Keyboard**.
- The app has no speed control and no volume control. It plays at the macOS output volume.

## Related

- [Keyboard shortcuts](/manual/reference/keyboard-shortcuts/)
- [Main window](/manual/reference/window/)
- [Status messages](/manual/reference/status-messages/)
