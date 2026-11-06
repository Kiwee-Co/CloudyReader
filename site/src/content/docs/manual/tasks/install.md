---
title: Install, update, and uninstall
description: 'Install Cloudy Reader on one or several Macs, update it to a new version, and remove it with its voices and settings.'
sidebar:
  order: 1
---

Use this page to put Cloudy Reader on one or several Macs, to install a new version, and to remove the app with its files. If this is your first install, start with [Get started](/manual/getting-started/).

## Install the app

Cloudy Reader comes as one zip file. It holds the app and no voices. The unzipped app takes REL-APP-SIZE on disk. The app downloads its voices at the first launch.

Cloudy Reader needs a Mac with Apple silicon and macOS REL-MACOS-FLOOR or later. See [Check your Mac](/manual/getting-started/#check-your-mac) for the disk space and the network connection that the first launch needs.

1. Download the zip and check its SHA-256. See [Download Cloudy Reader](/download/).
2. Double-click the zip in Finder to unzip it. The file `Cloudy Reader.app` appears.
3. Drag **Cloudy Reader** to **Applications** in the Finder sidebar. Do this before you open the app. The commands in this manual use `/Applications/Cloudy Reader.app`.
4. Open Cloudy Reader from the **Applications** folder. macOS blocks the first launch, so follow [Open the app the first time](/manual/tasks/first-open/).

Cloudy Reader is in the **Applications** folder. Keep the zip if you plan to install the app on another Mac.

## Install on several Macs

Every Mac must meet the requirements in [Check your Mac](/manual/getting-started/#check-your-mac), and every Mac runs its own first launch.

The app is one bundle, `Cloudy Reader.app`, with the bundle identifier `com.cloudyreader.CloudyReader`. Administrators can read how the app is signed in [Security and code signing](/about/security/) and what it sends in [Privacy](/about/privacy/).

To save download time, download the zip once and copy it to the other Macs. Copy the zip, not the app. The SHA-256 describes the zip, so each Mac can check its own copy.

1. Download the zip on one Mac and check its SHA-256.
2. Copy the zip to each other Mac, for example with a USB drive or AirDrop.
3. On each Mac, check the SHA-256 again, unzip the file, and move the app to **Applications**.
4. On each Mac, approve the app. See [Open the app the first time](/manual/tasks/first-open/).

Each Mac downloads the voices at its first launch. To skip that download, copy the voices from a Mac where they work. See [Manage voices and storage](/manual/tasks/voices-and-storage/).

On a Mac that a school or an employer manages, ask the administrator to approve the app. See [If Open Anyway is missing](/manual/tasks/first-open/#if-open-anyway-is-missing).

## Update to a new version

Cloudy Reader has no update check. Look for a new version on [Cloudy Reader releases on GitHub](https://github.com/Kiwee-Co/CloudyReader/releases). The [Release notes](/about/release-notes/) list what each version changed.

1. Quit Cloudy Reader. Press Command-Q.
2. Download the zip of the new version and check its SHA-256.
3. Move the old **Cloudy Reader** from the **Applications** folder to the Trash.
4. Double-click the zip in Finder, then move the new **Cloudy Reader** to **Applications**.
5. Open the app and approve it as before. See [Open the app the first time](/manual/tasks/first-open/).

An update replaces only the app. Your voices, caches, and saved choices stay in the data folder and the preferences file. At every launch, the voice download fetches the files that are missing, unless offline mode is on.

To confirm the version, see [Check the installed version](#check-the-installed-version).

## Check the installed version

Choose **Cloudy Reader > About Cloudy Reader**. The box shows the version, such as "Version REL-VERSION". Click **OK** to close the box.

In Terminal, run this command to print the app name and the version, such as `Cloudy Reader REL-VERSION`:

```bash
"/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --version
```

## Uninstall the app

Cloudy Reader writes its own files in three places, and it removes its temporary files after use. Remove the three places to take the app off the Mac:

- The app: `/Applications/Cloudy Reader.app`, which takes REL-APP-SIZE on disk.
- The data folder: `~/Library/Application Support/cloudyreader`, which holds the voices and the caches, including the audio of each reading.
- The preferences file: `~/Library/Preferences/com.cloudyreader.Cloudy Reader.plist`, which holds your saved choices.

1. Quit Cloudy Reader.
2. Move `Cloudy Reader.app` from the **Applications** folder to the Trash.
3. In Finder, choose **Go > Go to Folder**. Type `~/Library/Application Support` and press Return.
4. Move the `cloudyreader` folder to the Trash.
5. Run this command in Terminal to remove the saved choices:

   ```bash
   defaults delete "com.cloudyreader.Cloudy Reader"
   ```

6. Empty the Trash.

The app, its voices, and its saved choices are gone. If you chose another location for the data folder, move that folder to the Trash instead. See [Data folder](/manual/reference/files-and-settings/#data-folder).

:::tip
Keep the `cloudyreader` folder if you plan to install the app again. The voices stay, and the next install skips the download.
:::

To keep the app, see [Free disk space](/manual/tasks/voices-and-storage/#free-disk-space) or [Reset the app](/manual/tasks/voices-and-storage/#reset-the-app) instead.

## Related

- [Get started](/manual/getting-started/)
- [Open the app the first time](/manual/tasks/first-open/)
- [Manage voices and storage](/manual/tasks/voices-and-storage/)
- [Files, settings, and limits](/manual/reference/files-and-settings/)
