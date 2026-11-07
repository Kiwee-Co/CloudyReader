---
title: 'Security and code signing'
description: 'How Cloudy Reader is signed, why macOS asks you to approve it, how to check the download, and how voice and engine downloads are verified.'
sidebar:
  order: 2
---

Cloudy Reader is [signed ad hoc](/manual/reference/glossary/#ad-hoc-signature) and is not [notarized](/manual/reference/glossary/#notarized), so macOS asks you to approve the first launch. This page explains what that means, how to check the download and the app, and what the app does on your Mac.

## How the app is signed

The build signs the app ad hoc with `codesign --force --deep -s -`. An ad-hoc signature uses no Apple Developer ID, and the app is not notarized. Notarization is Apple's malware check for apps that are distributed outside the App Store.

The signature records the files of the app. If a file changes after signing, `codesign --verify` fails. The signature shows that the files are unchanged since signing, and it does not show who made them.

macOS marks a file that you download as quarantined. [Gatekeeper](/manual/reference/glossary/#gatekeeper), the part of macOS that checks downloaded apps, blocks the first launch of a quarantined app that is not notarized. Its dialog says it cannot verify the app, and the wording differs between macOS versions.

Approving the app is your decision. [Approve the app](/manual/tasks/first-open/#approve-the-app) lists the steps.

:::caution
Removing the [quarantine flag](/manual/reference/glossary/#quarantine-flag), `com.apple.quarantine`, skips the Gatekeeper check for that app. Do it only for an app you trust, and never against the policy of a managed Mac. See [Remove the quarantine flag](/manual/tasks/first-open/#remove-the-quarantine-flag).
:::

Before you approve the app, you can:

- Read the source in the [public repository](https://github.com/Kiwee-Co/CloudyReader), which is licensed under the Apache License 2.0.
- Compare the SHA-256 of your download with the value on [Download Cloudy Reader](/download/#check-the-download).
- Verify the signature of the installed app.
- Read what the app sends and stores in [Privacy](/about/privacy/).
- Build the app yourself with [Build from source](/developer/building/).

## Check your download

Compare the SHA-256 of your download with the value on [Download Cloudy Reader](/download/#check-the-download). That page holds the file name, the size, and the checksum command.

A match shows that your copy is the file whose SHA-256 is published there. It does not show who built the file.

Any other result means the file is damaged or changed. Download Cloudy Reader again, or see [The checksum does not match](/manual/troubleshooting/#the-checksum-does-not-match).

## Check the app signature

Run this command in Terminal after you move the app to Applications:

```bash
codesign --verify --deep --strict --verbose=2 "/Applications/Cloudy Reader.app"
```

With `--verbose=2`, the command prints a `--prepared:` line and a `--validated:` line for each nested file. It then prints two closing lines and exits with status 0:

```text
/Applications/Cloudy Reader.app: valid on disk
/Applications/Cloudy Reader.app: satisfies its Designated Requirement
```

Run `echo $?` right after the command to read the status. A file that differs from what was signed gives the message `a sealed resource is missing or invalid`. A `file modified:` line shows its path, and the status is 1.

If the check fails, download Cloudy Reader again and install the app again. Do not edit files inside the app, because any change breaks the signature.

To see the kind of signature, run `codesign -dv "/Applications/Cloudy Reader.app"`. It reports `Signature=adhoc` and `TeamIdentifier=not set`.

The bundle identifier is `com.cloudyreader.CloudyReader`, and the executable is `Contents/MacOS/Cloudy Reader`.

## How voice downloads are protected

A list bundled in the app pins every voice file and every engine file by URL, size, and SHA-256. The download follows these rules:

- Transport: HTTPS only. The app follows at most five redirects, and each one must use HTTPS with a host.
- Pinned list: the list gives each file's URL, group, size, and SHA-256. One unsafe or malformed entry rejects the whole list, and then nothing downloads.
- File types: Piper and Kokoro files end in `.onnx`, `.json`, `.safetensors`, or `.txt`, and engine files end in `.safetensors`, `.json`, or `.txt`. Every group refuses `.pt`, `.pth`, `.pkl`, `.pickle`, `.ckpt`, and `.bin` files, because a pickle file can run code when a program loads it.
- Status and length: HTTP status 200, a `Content-Length` equal to the pinned size, and no more bytes than that size.
- Content: the exact byte count and the pinned SHA-256.
- Staging: each file downloads to a private `.prefetch` folder in the data folder, and moves into place only after every check passes.
- Retries: three tries for each file, with waits of 2 and 4 seconds, after a network error, HTTP 429, HTTP 5xx, or a short read. A SHA-256 mismatch, a wrong length, or HTTP 404 is not retried.
- Existing files: a file that is present with a different size is never overwritten.
- App bundle: the app refuses to write into any folder inside an app bundle.
- Cleanup: the app removes leftover `.part` files older than 24 hours when a download starts.
- Log: the error text of a failed download masks every URL, because a redirect target can carry a signed token.

These checks run when a file downloads. Afterward, the app counts a file as installed when it is a regular file of the pinned size.

It does not hash a Piper voice file again. It hashes the Kokoro configuration and model files when it lists voices, once for each launch.

### Engine files

The files of Chatterbox Turbo and Qwen3-TTS go through the same download checks, and they get these checks too:

- Commit-pinned addresses: the address of each engine file names one 40-character commit. A Chatterbox Turbo or Qwen3-TTS file goes under `models/<engine>/`, with at most one sub-folder.
- Disk check: before each engine group, the free disk space must hold the missing bytes times 1.1 plus 1 [GiB](/manual/reference/files-and-settings/#built-in-limits), and the models folder must be writable. If either check fails, the app skips the group. The check runs when the app plans the download and again when the group starts.
- Re-hash before the first load: the app checks every pinned file against its SHA-256 value before an engine first loads, and each launch hashes an unchanged file once. A mismatch stops that reading with an error that starts `Error: damaged: SHA-256 mismatch for`. Later readings with the engine fail at once until you quit the app or the file changes.
- Pickle files: the app refuses a pickle suffix at download. A damage check, which reads only file properties and runs whenever the app lists voices, also marks a pickle-capable file in an engine folder as damaged.
- Other damage: the same check marks an engine as damaged for a symlink, an unpinned `.safetensors` file, a pinned path that is not a file, or a file of the wrong size.

A file that fails the property check dims the engine's voices with the reason `damaged: <detail>` when the app lists voices. A SHA-256 mismatch does not dim them at that point, because the app hashes a file only when the engine first loads. An engine loads only files on your Mac: see [How the voice engines stay offline](/about/privacy/#how-the-voice-engines-stay-offline).

## What the app can access

The app touches these parts of your Mac:

- Files: the data folder `~/Library/Application Support/cloudyreader`, the preferences file `~/Library/Preferences/com.cloudyreader.Cloudy Reader.plist`, and temporary files in the system temporary folder. See [Files, settings, and limits](/manual/reference/files-and-settings/).
- Clipboard: the app reads the clipboard only when you paste into its window, with Command-V or **Edit > Paste**. It never reads the clipboard on its own.
- Sound: the app starts `/usr/bin/afplay` as a child process to play a reading, and stops it when you click **Stop**.
- Speech: the app starts `/usr/bin/say` as a child process once at launch, to list the macOS voices, and again for each reading with a macOS voice. It passes an argument list, not a shell command, and the environment `PATH=/usr/bin:/bin`. The spoken script goes in on standard input, and `say` writes a WAV file to a private temporary folder. The app deletes the folder after the reading, and it ends `say` when the run goes past its time budget.
- Java: the app starts its bundled Java runtime for the OPSIN check. It ends the runtime when the check finishes or runs past its time budget.
- Network: see [Privacy](/about/privacy/) for what the app sends and when.

The build signs the app with no entitlements file and sets no usage-description key in its Info.plist.

## Report a vulnerability

Report a security vulnerability privately, and do not post it in a public issue. Use the private vulnerability reporting of the repository on GitHub: open the **Security** tab of the repository and click **Report a vulnerability**. See [Report a security issue](/manual/get-help/#report-a-security-issue) for what to include.
