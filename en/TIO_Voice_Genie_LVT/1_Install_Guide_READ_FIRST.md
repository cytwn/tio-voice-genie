# Installation guide

> **The files in the folder are numbered. Just work through them in number order.**
>
> | File | When to use it |
> |---|---|
> | `1_Install_Guide` | This document. Read it first |
> | `2_Get_API_Key_and_Billing` | **You must do this the first time**, about 10 minutes |
> | `3_Install.bat` | Double-click it and it installs everything by itself |
> | `4_Start.bat` | Opens the menu. **Normally you just double-click the "TIO Voice Genie" shortcut on your desktop** (the shortcut runs this file); only double-click this one directly if there's no shortcut on the desktop |
> | `5_User_Guide` | How each feature works; look things up any time |
> | `6_Diagnostics.bat` | Run it when something goes wrong, then send a screenshot of the window |
> | `7_Uninstall.bat` | When you don't want the tool any more |
> | `8_Rescue_Undeletable_Folder.bat` | Only when the folder won't delete |

This is a tool that **turns meeting audio into text**. The folder you received is called `TIO_Voice_Genie_LVT`.
The program has no hard-coded paths, so it runs from the C: drive, the D: drive, the desktop or anywhere else.

---

## What your PC needs

| Item | Version | Notes |
|---|---|---|
| **Windows** | 10 / 11 | For now it is **Windows only**: recording "computer audio" (what the PC is playing) uses a Windows-only technology (WASAPI), so it can't work on a Mac |
| **Python** | 3.12 or newer | **Fine if you don't have it**: when `3_Install.bat` finds it missing, it installs it for you (it installs 3.13) |
| **Internet connection** | — | It connects to Google's servers, so it can't work offline |
| **A Gemini API key** | — | You get your own; see `2_Get_API_Key_and_Billing` for how |

ffmpeg and the Python packages are handled automatically by the installer, so you don't need to install them yourself.

---

## Installation steps

1. **Unzip** the zip file anywhere on your PC (don't click the files while they're still inside the zip)
2. **First read `2_Get_API_Key_and_Billing.md`** and get your API key ready
   (it's fine to skip this for now: you can leave that field blank during installation and add the key later)
3. **Double-click `3_Install.bat`**
   - **Never installed Python? That's fine**: it installs Python for you (under your own user account,
     so no administrator rights are needed), then carries on by itself, so you don't have to double-click again
   - Next an **installer window** opens. It first lists "what this will do" on your PC,
     and nothing happens until you press "I agree, start installing". A progress bar shows how it's going
   - You can paste your key straight in, or leave it blank to skip it (it asks again the first time you actually use the tool)
4. When it's finished, a "**TIO Voice Genie**" shortcut appears on your desktop; double-click it to use the tool
   (if no shortcut appears on the desktop, that's fine: just double-click `4_Start.bat` in the folder, which does the same thing)

You never have to type a command. It's all double-clicks.

---

## 🔴 When Windows says it's "unsafe" and won't let it run

**Your PC isn't broken, and the tool doesn't have a virus.**

When a zip file is **downloaded** from email, Teams or cloud storage, Windows quietly attaches a "this came from the internet" mark to it.
When you unzip it, the mark is **copied onto the files inside**. We tested this by unzipping with WinRAR:
the mark is copied only onto the 6 "**executable**" files:

```
3_Install.bat   4_Start.bat   6_Diagnostics.bat   7_Uninstall.bat   8_Rescue_Undeletable_Folder.bat   scripts\rescue.ps1
```

Of those, the 5 `.bat` files happen to be exactly the files you would ever double-click (`rescue.ps1` is never double-clicked; `8_Rescue_Undeletable_Folder.bat` runs it). So the symptom is:
**"Install, Start and Uninstall are all blocked, but the guides open just fine"**.

### What to do: just click "Run" once

1. Double-click `3_Install.bat` → a warning pops up (usually titled "Open File - Security Warning")
2. Click **"Run"**
   (if it's a blue "Windows protected your PC" screen, first click "**More info**", then "**Run anyway**")
3. As soon as the installer starts, **the first thing it does is clear this mark from the whole folder**.
   You'll see that step on the consent page: **Unblock N file(s) in this folder marked "from the internet"**

**The warning only appears for that very first click** (at that point the program hasn't even started, so it can't prevent it). After that,
`4_Start.bat` and `7_Uninstall.bat` won't ask again.

### To avoid even the first warning: unblock it first (mouse only, 10 seconds)

**Not unzipped yet**:

1. **Right-click** the zip file you downloaded → "**Properties**"
2. If there's a line at the very bottom saying "Security: This file came from another computer…", **tick** "**Unblock**"
3. Click "**OK**"
4. **Only then unzip it**

**Already unzipped**:

1. In the folder, **right-click** `3_Install.bat` → "**Properties**" → again, **tick** "**Unblock**"
2. Click "**OK**"
3. Double-click `3_Install.bat`. The installer's first step clears the mark from the other files as well

🔴 Going back and ticking it on the **zip** after you've already unzipped it doesn't help (the mark was copied onto every file long before):
tick it on `3_Install.bat` instead, or delete the folder and unzip it again.

If the Properties window has **no** "Unblock" box to tick, that file never had the mark: just unzip the zip, or just double-click `3_Install.bat`.

### If the warning window has **no** button at all that lets it run

First check which of these the message mentions:

- **"Smart App Control"** (Windows 11's protection feature, set to "On", i.e. enforcement mode): the `.bat` is simply blocked when you click it,
  with no "Run anyway" to press, but **you can fix it yourself** (tested on a laptop, 2026-09-19):
  **delete the folder you already unzipped** → right-click the zip → "Properties" → tick "**Unblock**" → "OK" →
  **unzip it again**, then double-click `3_Install.bat`.
- **"administrator" or "Group Policy"**: this PC is locked down by your organisation's IT policy, and you can't get around it yourself.
  **Take a screenshot of that window** and report it together with the `6_Diagnostics.bat` screen (see "When you're stuck" below for how to report).

---

## A new version has arrived — how do I update?

**Just unzip the new zip into the same place, over the old one.** Your transcripts and caption files are on the desktop,
so they won't be touched. Then **double-click `3_Install.bat` once more**.

Unzipping only overwrites files with the same name; it **doesn't delete files left over from the old version**. So if you installed an earlier version,
the folder may end up with old and new side by side, for example `安裝.bat` (an older version's "Install") and `3_Install.bat`.
When the installer spots this, it lists those files and asks whether to clean them up while it's at it. **Just leave that ticked**.

> Even simpler: delete the whole old folder before updating, then unzip the new one. Same result, and it's the cleanest way.
> (The files you produced are on the desktop, not in this folder.)

### 🔴 Updating from an old version: the folder and shortcut have been renamed

This tool is now called **"TIO Voice Genie"**, and the folder and desktop shortcut have been renamed to match.
So after you unzip the new version, your PC will have **the old and new copies side by side**:

| | Old names you may have | New name |
|---|---|---|
| Folder | `會議字幕工具` / `TIO-會議字幕工具` ("Meeting Caption Tool") | `TIO_Voice_Genie_LVT` |
| Desktop shortcut | 會議字幕工具 / TIO-會議字幕工具 ("Meeting Caption Tool") | TIO Voice Genie |

**You don't need to delete the old shortcut yourself**: when you run the new version's `3_Install.bat`, it detects the old one and removes it.
**You can simply delete the old folder**, but check two things before you do:

1. Your transcripts, captions and bilingual documents are all on the **desktop**, not in this folder, so deleting the folder won't touch them
2. Run the new version's `3_Install.bat` once first, and make sure the new version opens normally

> If you want to clear everything out in one go, including the API key, **first** run `7_Uninstall.bat` in the old folder,
> then unzip the new version and run the new `3_Install.bat` to set up the key again.
> If you only want the new name, you don't need to do this: just delete the old folder.

---

## 🔴 To record real meetings, turn on the paid tier first

The free tier **doesn't charge you**, but it has two problems:

1. **Data governance**: Google uses free-tier content to improve its products, **human reviewers may read it**,
   and Google explicitly warns against sending confidential information. University meetings discuss personnel, budgets and review comments, so this alone rules it out.
2. **The quotas are no longer published**: Google no longer publishes the free tier's actual quotas. It just tells you to sign in at
   [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) and look for yourself,
   and notes that "specified rate limits are not guaranteed". **Nobody can work out in advance whether the free tier will last a whole meeting**,
   and running out of quota halfway through can't be prevented.

> **One more thing the participants need to know**: when you make a transcript, the recording is **uploaded to Google's servers** to be processed.
> That is how this kind of API works, and there's no way around it. This tool actively asks for it to be deleted once processing is over,
> but please tell the participants beforehand that "the recording leaves this PC".
> If you close the window halfway through a transcription, the program first deletes the temporary recording on your PC and the copy in the cloud before it exits.
> Anything it had no time to delete because the PC crashed or lost power is cleared automatically at the start of the next transcription (the cloud copy expires automatically within 48 hours at the latest).

For how to turn it on and how much to top up, `2_Get_API_Key_and_Billing` has step-by-step instructions.

Two things people often trip over:

- The daily quota resets at **midnight US Pacific time** (≈ 3–4 pm in Taiwan), not at midnight Taiwan time
- The quota belongs to the **project**, not the key. If one project hands out several keys to different people,
  everyone shares one quota and you crowd each other out. **Please create your own project with your own Google account**

**The costs are billed to your own Google account**; this tool does not handle any payments.

---

## When you're stuck: double-click `6_Diagnostics.bat`

If any step fails, or the program won't open, **double-click `6_Diagnostics.bat` and take a screenshot of the whole window**,
then report it. It lists this PC's Python, packages, ffmpeg,
API key and desktop path, and whether all the files are there, so it's clear at a glance where things are stuck, with no back-and-forth guessing.

**How to report**: open an issue on GitHub, or email cylab.contact@gmail.com. Issues page: https://github.com/cytwn/tio-voice-genie/issues
Issues are public, so anyone can read them: the desktop path in the screenshot shows your Windows user name, so cover it before posting, or send it by email instead.

### Common installation problems

| What happens | Why | What to do |
|---|---|---|
| Clicking a `.bat` brings up a "Security Warning" saying it's unsafe | The zip was downloaded from the internet, and Windows put a "from the internet" mark on every `.bat` inside | Just click "Run" once; the installer then clears the whole package. See the section "When Windows says it's 'unsafe'" above |
| It says "Python is not installed" | This PC has no Python | `3_Install.bat` installs it automatically and carries on; just wait for it |
| pip install fails with `SSLError` / `certificate` | **The company network is intercepting HTTPS**, and Python doesn't recognise the certificate the firewall swaps in | The installer automatically retries using the Windows certificate store. If that still doesn't work, **run the installation once over your phone's hotspot** (quickest), or press the on-screen button "I understand the risk – skip the certificate check and retry" |
| ffmpeg fails to install | winget isn't installed, or its version is too old | Download it from [ffmpeg.org](https://ffmpeg.org), unzip it and add the bin folder to the system PATH |
| The microphone / computer audio can't be recorded | There's no audio device, or Windows privacy settings are blocking the microphone | Settings → Privacy & security → Microphone, and make sure "Let desktop apps access your microphone" is on |
| It still asks me to paste a key when I start | You skipped the key during installation, or Google said the key you pasted doesn't work (the last page of the installer says why) | Just paste it once as the screen asks; there's no need to restart your PC. To change it later, choose **9 "API key settings"** in the menu |
| No window appears during installation, only a black text screen | This PC's Python doesn't have tkinter (rare) | Just answer the questions in the black window. ⚠ The text version **doesn't create a desktop shortcut** and **has no automatic SSL retry**, so open the tool with `4_Start.bat` directly |
| No shortcut appears on the desktop | On some company PCs, the antivirus (Controlled folder access) or Group Policy doesn't let programs write to the desktop | **It makes no difference to using the tool**: just double-click `4_Start.bat` in the folder. If you want a shortcut, right-click that file → Send to → Desktop (create shortcut) |
| It says "ffmpeg was not found" when converting a file | It has only just been installed, and the old window still has the old PATH | Close the window and double-click `4_Start.bat` again |
| Right after installing, features 1/3/6 say "Audio processing component (scipy) could not be loaded" | Windows 11's **Smart App Control** first blocks newly installed components that don't have a cloud reputation yet (seen on one laptop in testing, 2026-09-20) | Just **wait a few minutes and try again**; it usually lets them through on its own. To check, double-click `6_Diagnostics.bat` and see whether those lines say `BLOCKED` or `OK`; wait until they're back to `OK` before using it. Feature 5 (rebuild) doesn't go online or use those components, so you can still use it meanwhile |
| After you press Enter the screen sits still for tens of seconds, as if it has frozen | It hasn't frozen: it's **loading the speech components**. They're large, and if they haven't been used for a while they have to be read back in from disk | The screen shows the progress item by item (`· Audio processing component (scipy)… ✓ 27.2 s`); as long as you can see that, all is well. **Warming it up before the meeting avoids this**; see the next section |

---

## 🔥 Warm it up before the meeting (strongly recommended, saves about 30 seconds)

**Before the meeting, double-click `6_Diagnostics.bat`, look it over and close it, then double-click `4_Start.bat`.**

Why it works (tested on one laptop, 2026-09-21):

| Situation | Wait after pressing Enter |
|---|---|
| Not used for a long time, opened straight away | **30–45 seconds** |
| `6_Diagnostics.bat` run first | **about 3 seconds** |

`6_Diagnostics.bat` really loads those large speech components once, which warms things up for you; after that, features 1/3/6 start quickly.
**As a bonus, you can see whether Smart App Control is blocking anything right now** (those lines show `BLOCKED` instead of `OK`).

> The warm-up only lasts a while (in testing it still worked after 8 minutes), so do it **shortly before the meeting**, not the day before.

---

## Don't want it any more? Double-click `7_Uninstall.bat`

A window opens and lists everything that can be removed, item by item, for **you to tick yourself**. Anything you don't tick is left completely alone.

- Ticked by default: the **API key**, the temporary meeting recordings (if any are left), the desktop shortcut, the Python packages only this tool uses, and the sound-output record left by interpreter mode (feature 6)
- Not ticked by default (other programs may use them too; if you tick one, you get one more warning): `numpy`/`scipy`,
  ffmpeg, Python itself, the program folder
- The two package items only list **what is really still installed on this PC**; anything already removed doesn't appear again and can't be ticked
- Before you press "Start removing", it shows you the **full list of actions it will actually carry out** so you can check them

🔴 **The transcripts and caption files you made are always kept**. The uninstaller doesn't touch them.

> ⚠️ **Before the PC changes hands, goes back to your organisation or goes in for repair, be sure to run the uninstaller once to remove the API key.**
> The key is as good as the username and password of your Google account. Leaving it on the PC is like handing your account to the next person.

**If the folder won't delete** (Windows says "You'll need to provide administrator permission to delete this folder"): it's almost never a permissions problem.
**The most common cause is that the folder is open in File Explorer** (this has really happened). Just close that window.
If that doesn't work, restart the PC and then delete it. Only if it still won't go, double-click `8_Rescue_Undeletable_Folder.bat`:
it prints the owner, the permissions and which program is using the folder, so you can just send a screenshot of it.

---

## The very short version (just tell me what to click)

> 1. Unzip it and put it anywhere
> 2. Read `2_Get_API_Key_and_Billing`, then go to aistudio.google.com/apikey to get a key and turn on billing
> 3. Double-click `3_Install.bat` and answer the questions that come up
> 4. From then on, always double-click "TIO Voice Genie" on your desktop (or `4_Start.bat`)
> 5. When you don't want it any more, double-click `7_Uninstall.bat`

---

## Terms of use and disclaimer

1. This tool is developed independently by CY KUO as an individual and provided free of charge under the MIT License. It does not represent any institution or organisation. The full licence is in the `LICENSE` file in this folder.
2. Speech recognition and translation are produced by Google Gemini and may mishear, miss words or mistranslate. Transcripts are drafts; review them before using them as official records.
3. When you use the tool, audio is sent to Google's servers for processing (these may be outside your country), and the data is handled under Google's terms of service. For meetings involving personal or confidential information, turn on the paid tier first (see `2_Get_API_Key_and_Billing`).
4. Usage fees are calculated by Google based on usage and charged to your own Google account; this tool does not handle any payments. We recommend setting a monthly spend cap in Google AI Studio.
5. Before recording or transcribing, make sure you comply with the applicable laws and your organisation's rules, and tell the participants in advance.
6. The developer provides this tool under the MIT License without any warranty. Use it at your own discretion and risk; the developer is not liable for any damages.
7. Google, Gemini, Windows, Teams and other names are trademarks of their respective owners. This tool is not affiliated with, sponsored by or endorsed by these companies.

---

**TIO Voice Genie** · Developer: CY KUO · Licence: MIT License (full text in the `LICENSE` file in the folder)
