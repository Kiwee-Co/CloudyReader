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
- The **Spoken script** button has the description "Show or hide the text that is spoken" and draws the macOS focus ring when it has focus.
- The **Spoken script** view is closed at every start. It is read-only and holds the words of the last reading.

## Hear what the app is doing

The app shows its state as text in the status bar. It announces errors to assistive technology and nothing else. It opens no dialog for a warning or an error.

| Tone        | Announced    | Examples                                       |
| ----------- | ------------ | ---------------------------------------------- |
| Error       | Yes, at once | "Error: nothing to read"                       |
| Warning     | No           | "Warning: _text_" and "No voice is installed." |
| Information | No           | "Preparing…" and "Playing _n_ s."              |

Assistive technology sees the status bar as one element named by the current message. For an error, the name holds the first line and the description holds the full text. A warning or an error also shows a system icon before its text, so color is never the only cue.

The app announces neither the voice download nor its end. To check the download, see [Check which voices are installed](/manual/tasks/voices-and-storage/#check-which-voices-are-installed).

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

- The window uses the native macOS look. It follows light and dark appearance and switches when the system does.
- The gray placeholder text keeps a contrast ratio of at least 4.5:1 in both appearances.
- Text uses the macOS system font at 13 points, and at 12 points in the status bar and the **Spoken script** view. The app has no text size setting.
- The window can shrink to 560 by 480. **Window > Zoom** switches between the maximized and the normal window.

## Work around the known limits

- The app announces errors only. Warnings and information messages show only in the status bar.
- The app has no speed control and no volume control. It plays at the macOS output volume.

## Related

- [Keyboard shortcuts](/manual/reference/keyboard-shortcuts/)
- [Main window](/manual/reference/window/)
- [Status messages](/manual/reference/status-messages/)
