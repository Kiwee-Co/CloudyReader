---
title: Use VoiceOver and the keyboard
description: 'Use Cloudy Reader with VoiceOver and the keyboard alone: tab order, control names, announcements, and shortcuts.'
sidebar:
  order: 8
---

Use Cloudy Reader without a pointer or without sight. This page lists the tab order, the control names, what the app announces, and the keys for every reading action. The names, the order, and the announcements come from the app. The project has not tested them with VoiceOver on a Mac.

## Move through the window

Press Tab to move focus forward and Shift-Tab to move back. Tab leaves the question box and does not type a tab character. After the **Speak** button, Tab returns to the question box. The table lists the controls in tab order.

| Control                       | Accessible name  |
| ----------------------------- | ---------------- |
| Question box                  | Question         |
| **Spoken script** button      | Spoken script    |
| **Spoken script** view        | Spoken script    |
| **Voice** menu                | Voice            |
| **Speaker** box               | Speaker          |
| **Rotation** menu             | Voice rotation   |
| **Read answer line** checkbox | Read answer line |
| **Online lookups** checkbox   | Online lookups   |
| **Repeat** button             | Repeat           |
| **Stop** button               | Stop             |
| **Speak** button              | Speak            |

Details about these controls:

- The **Speaker** box appears only for a voice with more than one speaker.
- Tab skips a dimmed control. It also skips the **Spoken script** view while the view is hidden.
- Space selects or deselects a focused checkbox, and it shows or hides the **Spoken script** view when its button has focus.
- The question box and the **Spoken script** view use their placeholder text as the description.
- The **Voice** menu has the description "Choose the voice that reads the question." The **Speaker** box has the description "Choose a speaker of this voice." followed by the range of speaker numbers.
- Each row of the open **Voice** menu has a spoken form, such as "Heart, American English, female. Kokoro, Grade A." A dimmed row adds "Not available:" and its reason. The closed menu shows the written label.
- The headings in the **Voice** menu are section headers, not choices. VoiceOver reads each heading as the engine name followed by "voices".
- The **Spoken script** button has the description "Show or hide the text that is spoken".
- The question box and the **Spoken script** view show a two-tone focus ring: a thin contrast line, then a thicker ring in the accent color. The contrast line is dark in light appearance and light in dark appearance. Every other control, including the **Spoken script** button, draws the macOS focus ring.
- The **Spoken script** view is open at every start. It is read-only. It holds a preview of the words that the voice receives while you type, and the final script after a reading.
- The About panel has no buttons. VoiceOver reads its icon, name, version, and description in that order. Press Escape or Command-W to close it.

## Hear what the app is doing

The app shows its state as text in the status bar. It announces errors, warnings, and some information messages to assistive technology. It opens no dialog for a warning or an error.

| Tone                    | Announced                          | Examples                                                                         |
| ----------------------- | ---------------------------------- | -------------------------------------------------------------------------------- |
| Error                   | Yes, at once, every time           | "Error: nothing to read"                                                         |
| Warning                 | Yes, politely, once while it shows | "Warning: _text_" and "No voice is installed." when no download runs or it ended |
| Information (announced) | Yes, politely, once while it shows | "Voices downloaded." and "No voice is installed." while a download runs          |
| Information (all other) | No                                 | "Preparing…" and "Playing _n_ s."                                                |

Assistive technology sees the status bar as one element. Its name is the current message, with "Warning:" or "Error:" in front unless the text already starts with "Warning:", "_n_ warnings:", or "Error:". For an error, the name holds the first line and the description holds the full text. A warning or an error also shows a line icon before its text: a triangle for a warning and a circle for an error. VoiceOver skips the icon, and color is never the only cue.

The status bar holds two bars, and only one shows at a time. The busy bar has the name "Preparing" and the description "A reading is being prepared." The download bar has the name "Downloading" followed by the engine, such as "Downloading Kokoro", and the description "Voice download progress."

The app does not announce the download progress. When the download ends, the status bar shows "Voices downloaded." or a warning when some files fail, and the app announces it. The status bar shows the result only when it has no other message. To check the download, see [Check which voices are installed](/manual/tasks/voices-and-storage/#check-which-voices-are-installed).

## Run every reading action from the keyboard

Every command in the **Reading** menu has a shortcut. Shortcuts work while Cloudy Reader is the active app.

| Action     | Keys                            | Available when                                        |
| ---------- | ------------------------------- | ----------------------------------------------------- |
| **Speak**  | Command-Return or Command-Enter | A voice is selected and no reading is in preparation  |
| **Repeat** | Command-R                       | A reading has played and no reading is in preparation |
| **Stop**   | Command-Period (.)              | Audio is playing                                      |

A shortcut does nothing while its command is dimmed. The question box has focus when the app opens. To read a copied question from the keyboard:

1. Copy the question text in another app.
2. Press Command-Tab to switch to Cloudy Reader.
3. If the focus ring is not around the question box, press Tab until it is.
4. Press Command-A, then Command-V. The box then holds the copied question.
5. Press Command-Return.
6. Press Command-Period (.) to stop the sound, or Command-R to hear the reading again.

The status bar shows "Preparing…", then "Playing _n_ s." [Keyboard shortcuts](/manual/reference/keyboard-shortcuts/) lists every shortcut in the app.

## Check appearance and window size

- The window follows light and dark appearance, the macOS setting Increase contrast, and the system accent color. It repaints when any of them changes.
- The app draws the card around the question box and the panel around the **Spoken script** view. With Increase contrast on, the panel also gets an outline. The other controls use the native macOS look.
- The gray placeholder text, the gray information message, and the **Spoken script** text keep a contrast ratio of at least 4.5:1 in every appearance.
- Text uses the macOS system font. It is 15 points in the question box and 13 in the other controls. It is 12 points in the status bar and the **Spoken script** view, and 11 in the **Voice** menu headings. The app has no text size setting.
- With the macOS setting Reduce Motion on, the app hides the moving busy bar in the status bar. The message "Preparing…" still shows that a reading is being prepared. The app checks the setting at start and each time it becomes the active app.
- The window can shrink to 560 by 480. **Window > Zoom** switches between the maximized and the normal window.

## Work around the known limits

- The app announces a warning or the download result once. To read it again, read the status bar.
- The app does not announce other information, such as "Preparing…" and "Playing _n_ s." Read the status bar to see it.
- The app does not announce changes to the **Spoken script** view while you type. Move focus to the view to read it.
- To move to buttons, checkboxes, and pop-up menus with Tab, turn on **Keyboard navigation** in **System Settings > Keyboard**.
- The app has no speed control and no volume control. It plays at the macOS output volume.

## Related

- [Keyboard shortcuts](/manual/reference/keyboard-shortcuts/)
- [Main window](/manual/reference/window/)
- [Status messages](/manual/reference/status-messages/)
