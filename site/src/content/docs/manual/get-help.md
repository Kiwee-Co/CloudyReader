---
title: Get help
description: 'How to get help with Cloudy Reader: collect the version, macOS, and self-test details, then report a problem on GitHub.'
sidebar:
  order: 3
---

Use this page when the manual does not solve your problem. It shows what to collect, where to report a problem, and how to report a security issue in private.

## Check the manual first

Many problems have a known fix.

- Search this site for the exact text from the status bar.
- Read [Troubleshooting](/manual/troubleshooting/) for fixes by symptom.
- Read [Status messages](/manual/reference/status-messages/) for what each message means.
- Read [Frequently asked questions](/manual/faq/) for short answers.

## Collect details

A report with these details lets the project reproduce your problem.

1. The app version. Choose **Cloudy Reader > About Cloudy Reader**. The box shows the version, such as "Version REL-VERSION". <!-- needs-fact: owner checklist: About lives in the application menu -->
2. The macOS version and the chip. Choose **Apple menu > About This Mac**.
3. The self-test report. See [Run the self-test](#run-the-self-test).
4. The lines the app prints in Terminal. See [Read the lines the app prints](#read-the-lines-the-app-prints).
5. The exact text in the status bar, the voice, the rotation mode, and the steps that cause the problem.

### Run the self-test

The self-test reads a built-in sample with the first installed Piper voice. It opens no window and plays no sound.

1. Open Terminal from **Applications > Utilities**.

2. Run this command. If you installed the app in another folder, change the path.

   ```bash
   "/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader" --self-test
   ```

3. Copy everything Terminal prints, including any error text above the report. The report ends with `PASS` or with a line that starts with `FAIL:`.

The exit code is 0 when the test passes, 1 when it fails, and 2 when no Piper voice is installed. To read it, run `echo $?` right after the test. With no Piper voice, the report also prints `FAIL: no Piper voice installed`. See [Command line](/manual/reference/command-line/) for every option and exit code.

### Read the lines the app prints

The app keeps no log file. It prints warnings to standard error, which Terminal shows when you start the app from Terminal.

1. Quit Cloudy Reader with Command-Q.

2. Run this command in Terminal:

   ```bash
   "/Applications/Cloudy Reader.app/Contents/MacOS/Cloudy Reader"
   ```

3. Repeat the steps that cause the problem, then copy the lines that appear in Terminal.

## Report a problem

1. Open the [issues page on GitHub](https://github.com/Kiwee-Co/CloudyReader/issues) and search for your message.
2. If an issue matches, add your details to it. If none matches, choose **New issue**. You need a free GitHub account.
3. Write a title that names the symptom.
4. Paste the details you collected, and say what you expected to happen.
5. Remove any text you do not want to share, then choose **Submit new issue**.

:::caution
An issue is public. Anyone can read it, so leave out names, school details, and question text that you do not want to share.
:::

To ask a question, open an issue in the same way and say in the title that it is a question.

## Report a security issue

A security issue is a flaw that lets someone read or change your files, run code, or send data from your Mac without your action. Report it in private. Do not open a public issue.

1. Open the [private report form on GitHub](https://github.com/Kiwee-Co/CloudyReader/security/advisories/new). <!-- needs-fact: owner enables private vulnerability reporting -->
2. Describe the flaw, the app version, your macOS version, and the steps that show it.
3. Leave out real personal data.

The approval prompt that macOS shows at the first launch is not a flaw. The app is signed ad hoc and is not notarized. See [Open the app the first time](/manual/tasks/first-open/) and [Security and code signing](/about/security/).

## Allow time for a reply

The project does not promise a response time. Add details to your existing issue instead of opening another one.
