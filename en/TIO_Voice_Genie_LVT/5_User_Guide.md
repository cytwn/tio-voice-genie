# TIO Voice Genie — User guide (how each feature works)

## How do I start?

Once installation is finished, there is a shortcut on your desktop called **"TIO Voice Genie"**.

**Just double-click it with the left mouse button.** You don't have to type any commands.

> Can't find it on the desktop? Just go into the folder you unzipped and double-click `4_Start.bat`; it does the same thing.

A black window opens, looking like this:

```
  TIO Voice Genie
  ════════════════════════════════════════════

  1  Live meeting captions    – see captions while the meeting runs
  2  Recording to transcript  – turn a recorded file into text
  3  Live bilingual captions  – source + translation together (Chinese, English, Japanese)
  4  Transcript to bilingual  – translate the whole file, far better than live
  5  Rebuild a transcript     – redo from .json / rename speakers, free
  6  Live voice translation   – hear only the interpreter, not the original (interpreter mode)
  9  API key settings         – change the key, check it works, clear the saved one
  0  Close

Type a number and press Enter:
```

**All you do is type one number and press Enter.** After that it asks you one thing at a time; just answer as you go.

---

## First time? Try feature "2" first (you can try it without a recording of your own)

Press `2` → in the file picker that opens, find `data\meeting_16k_mono.wav` in this folder
(a built-in demo recording: two people speaking Chinese, 47 seconds) → Open → keep pressing Enter until the end.

That way you can see what the result looks like before you have a recording of your own. When it finishes, it asks whether you want to open the file;
press `1` and it opens automatically.

---

## 1️⃣ Live meeting captions

**When to use it:** during a meeting, when you want to see captions as it goes.

**How to do it:**

1. Double-click the desktop icon → press `1` → Enter
2. It asks which sound to record:
   - Press `1` = **Online meeting** (Teams / Google Meet / Zoom)
     → it records "the sound coming out of the computer's speakers", so it picks up everything the other side says
     → 🔴 Strictly speaking, it records the **Windows default playback device**. The meeting app's speaker must be set to the same device: the new Teams (tested on one laptop,
       2026-09-19) has no "system default" option, so go into Teams' device settings and pick the device that is currently the Windows default by hand; if you pick a different one, the other side's voices won't be recorded for the whole meeting
       (the "Audio source: …" line on screen at the start shows which device is being recorded)
   - Press `2` = **In-person meeting** (everyone is in the same meeting room)
     → it records the microphone. If the computer has **two or more** microphones, it asks "Which microphone?" (if there is only one, it doesn't ask):
       choose `1` (or just press Enter) = **Let the program choose**: it follows the Windows default, and switches over if you unplug or plug in a headset midway;
       any other number = **Only use that one**: if it is unplugged, it waits for it to be plugged back in.
       For meetings with several people, **don't use a headset** (it is designed to sit right by the mouth): if you have an external conference microphone, choose it as the one to use; if not, use the **laptop's built-in microphone array**,
       and once you have chosen, check with the "Sound check" on screen that it really picks up sound.
       Next it asks "Does any of the sound in the room come from loudspeakers (speakers) and also need captions?": normally press `1`;
       press `2` only if you need to pick up sound from loudspeakers (full capture; there is no guarantee it will be picked up; see "How to set up a hybrid meeting" below)
   - Press `3` = Both (you are in an online meeting and also want your own voice picked up)
     → it also asks "Which microphone?". If you chose **Only use that one**, unplugging the headset stops only the **microphone** feed;
       the computer audio still gets captions (once the headset is unplugged, the sound plays from the laptop speakers instead, and the program switches to recording those speakers)
3. It asks for **proper nouns** → type terms like "深耕計畫 研發處 會計室" (Higher Education Sprout Project, Office of Research and Development, Accounting Office), with a single space between them, written the way they should appear in the transcript
   (this step matters: it makes a big difference to accuracy. If you don't want to, just press Enter to skip it)
4. It asks what the meeting is called → type anything, or just press Enter
5. Press Enter to start

**Once it starts, you will see:**
- **Grey text** = still being recognised; it keeps jumping about and correcting itself → this is normal, don't worry about it
- **White text** = final sentences. **Each sentence is locked as soon as it is finished**; you don't have to pause

**How do I stop when the meeting ends?**
In that black window, press **Ctrl + C** (hold down the Ctrl key, then press C).

**The files are saved to your desktop**, two at a time:
- `.md` — for people to read; you can copy it straight into Word
- `.txt` — **a backup**. If the computer crashes or the program gets closed, the captions are all still in this file

> ⚠️ Live captions **cannot tell who is speaking** (this is a current Google limitation).
> If you need it to show "the Director said", "the Secretary said", use feature 2 below.

---

## 2️⃣ Recording to transcript ⭐ Most used

**When to use it:** the meeting has already been recorded (a phone recording, a Teams recording or a pocket voice recorder all work),
and you want to turn it into text with speakers and times.

**How to do it:**

1. Double-click the desktop icon → press `2` → Enter
2. **A file picker opens** → find your recording and click "Open"
   (mp3, m4a, wav, even an mp4 video file all work; it handles them itself)
3. It asks for **proper nouns** → type terms like "深耕計畫 研發處 會計室 教學組長" (Higher Education Sprout Project, Office of Research and Development, Accounting Office, Teaching Section Chief)
4. It asks for **speaker names** → type them in the order of "who speaks first", for example "Chair Wang, Ms Li" (separate the names with commas, so a name can contain spaces, such as a full name; if no name contains a space, spaces work too)
   (if you don't know, just press Enter and they become "Speaker 1", "Speaker 2"; recordings over 28 minutes are split into parts, and the names only apply to part 1; see below)
5. Wait for it to finish

**How long does it take?** About 1–3 minutes for an hour of recording.

**When it finishes, it asks whether you want to open the file**; press `1` and it opens automatically. The file is on your desktop and looks like this:

```
**[00:00:00] Director**

Alright, let's start today's Office of Research and Development meeting. The first item is the midterm report for the Higher Education Sprout Project.

**[00:00:09] Secretary**

Let me just add something: the deadline for expense reimbursement has already been extended to 31 October.
```

> ℹ️ Sometimes a sentence's heading has an extra **[re-transcribed]** after it (if you run the bundled demo file, the Secretary's line may get one):
> that sentence was missed when the text was tidied up, so the program cut that short stretch out of the original audio, transcribed it again on its own and put it back; the file header also gains a line saying how many there are.
> The speaker and time come from the first recognition pass, so it is worth checking them against the recording. If a sentence cannot be recovered, the header says "This transcript may be incomplete" and lists the time range.

> ℹ️ **If someone in the meeting speaks English** (for example a visiting guest's speech): the English stays in the transcript as spoken. But the speaker-separation pass often fails to hear English in a Chinese meeting,
> so **the speaker and time for that stretch may be wrong** (it often gets merged into the previous speaker's paragraph), and the header will say
> "there is sound in these N seconds of the recording, but the transcript does not cover this time"; please listen to that part of the recording.
> (Tested with a home-made test meeting on 2026-09-25: in this situation the old version quietly dropped the whole English passage and wrote nothing in the header.)

> 💡 **Proper nouns really do help.** In testing, if you leave them blank it hears 會計室 (Accounting Office) as 會計師 (accountant),
> and writes 深耕計畫 (Sprout Project) with the wrong character, as 深耕計劃. Fill them in and it corrects this automatically.
> We recommend always entering: `深耕計畫 研發處 教務處 會計室 教學組長 核銷 期中報告` (Sprout Project, Office of Research and Development, Office of Academic Affairs, Accounting Office, Teaching Section Chief, reimbursement, midterm report)

### Recordings over 28 minutes are split into parts automatically

Google's official documentation states that with "speaker separation + timestamps" switched on, **the model only processes 30 minutes of audio at a time**.
So the program splits long recordings into parts of 28 minutes or less, leaving a little safety margin.

> ⚠️ But **shorter parts don't mean nothing can go wrong**. Testing with long recordings turned up two problems: **a whole stretch in the middle of a part not recognised**
> (seen in 28-minute parts), or **the text flooded with the same handful of sentences, over and over** (seen in both 45-minute and 28-minute parts) —
> so what really catches problems is the checks below, not the length of the parts.

You will see two things:

- The screen says "⚠ Single-part limit: 28 minutes (…); splitting into N parts automatically"
- Each part works out its speakers on its own, so it can't tell whether a speaker in one part is the same person as in another: from part 2 on, speakers are written like "**Part 2 Speaker 1**";
  the speaker names you enter before transcribing **apply to part 1 only** (the old version applied them by number to every part, so part 2 could end up with the wrong names).
  To make the names consistent, use feature 5: look at each speaker's first line and rename them (you can give the same person the same name in different parts)

> 🔴 **If a part is missing content or something unusual happens, the file header and the screen flag it** (saying which part, what the problem is,
> and which part it suggests you cut out and transcribe again on its own). The program checks six things: whether a whole stretch in the middle of a part was not recognised,
> whether the amount of output from the two recognition passes disagrees badly, whether the text is heavily repeated, whether something the first recognition pass heard
> has gone missing from the tidied-up text (missing lines are first cut out and re-transcribed on their own, marked [re-transcribed]; only those that can't be recovered are listed),
> **stretches where the recording has sound but the transcript does not cover that time** (reported when there is sound for more than 10 seconds in a row, or at least 6 seconds of sound in total within any 30 seconds of the uncovered time; music and applause get listed too — a quick listen tells you),
> and **whether the times of the paragraphs overlap or go backwards** (when two sets of content are placed on the same stretch of time, speakers and times around there may not match).
>
> ⚠️ But **no flag doesn't guarantee there is no problem**. Known blind spots: very short gaps (under 10 seconds in a row and under 6 seconds in total within any 30 seconds),
> very quiet speech (close to the background noise), a whole stretch covered by one very long segment with a normal amount of text (a segment over 1 minute with almost no text still has its middle checked),
> and a recording that is noisy from start to finish, with speech hardly louder than the background (for example background music or a broadcast running throughout;
> when the program judges that this check can't see well, the header adds an ℹ️ line saying "This recording is almost never quiet…", which is only a note, not a gap).
> For important meetings, spot-check anyway.

> ⚠️ **Long transcripts made before 2026-09-16 should be transcribed again.** The old version had none of the checks described above,
> so when something went wrong it said nothing at all. In a real test with a 2 hour 57 minute meeting: in one part, 14 minutes in the middle were not recognised at all,
> and in another part nine tenths of the text was the same handful of sentences repeating (the same 13 sentences looped 6 times) — neither produced any warning.
> Transcribing again works the same as the first time: press `2` → pick the same recording, then **check the file header for warnings**.

---

## 3️⃣ Live bilingual captions ⭐ For talks in another language, or foreign-language captions for a Chinese talk

**When to use it:** watching an English online seminar, an overseas university's information session or an English YouTube video,
when you want to **see the English original and the Chinese translation at the same time**. It is also the one to use when you are listening to a Chinese talk and need English or Japanese captions.

**How to do it:**

1. Double-click the desktop icon → press `3` → Enter
2. It asks where the sound is coming from:
   - Press `1` = **Computer audio** (YouTube, online seminars)
   - Press `2` = Microphone (a guest is giving a talk in the room) → it also asks "Does any of the sound in the room come from loudspeakers (speakers) and also need captions?"; normally press `1`
   - Press `3` = **Both** (hybrid meeting: in person + online)
     → it asks "Which microphone?" (same as feature 1). If you chose **Only use that one**, unplugging the headset stops only the **microphone** feed;
       the computer audio still gets captions
   - Press `4` = **Saved audio/video file** ← you pick the file; no other sound is recorded
3. **It asks "Fast or accurate?"**
   - Press `1` **Accurate** (recommended): waits until the whole sentence is finished before translating; about 2–3 seconds behind; the translation's word order is natural
   - Press `2` **Fast**: translates while listening; about 1 second behind, but the word order is sometimes awkward
4. It asks which language to translate into → press `1` Traditional Chinese (Taiwan), `2` Japanese, `3` English
5. Press Enter to start

**The screen looks like this:**

```
[00:02] Thank you for joining today's session on research assessment.
        謝謝大家參加今天的研究評估會議。

[00:22] First, a seed funding scheme for cross-disciplinary projects.
        第一，建立一個種子基金計畫，用於跨學科專案。
```

Grey is the source and blue is the translation, and they **appear together**;
the delay depends on which mode you chose in the previous step: about 2–3 seconds with "Accurate", about 1 second with "Fast".

> ⚠️ **With "Computer audio", it records every sound the Windows default playback device is playing at the time.**
> Close any unrelated videos and music before you start, or they will get mixed in.
> In an online meeting, the meeting app's speaker must be set to this same device too (in the new Teams you have to pick it by hand; see the notes for feature 1;
> the "Audio source: …" line on screen at the start shows which device is being recorded).
> To avoid this problem, use option `4` (read the audio/video file directly).

**What's the difference between "Fast" and "Accurate"?** Actual output for the same English sentence:

| | Fast (translates while listening) | Accurate (translates each whole sentence) |
|---|---|---|
| | 我們大學已經增加了國際合作率 **15%今年**。 (word for word: "our university has increased international collaboration rate **15% this year**") | 本校的國際合作率**今年**提升了 15%。 (word for word: "our university's international collaboration rate **this year** rose 15%") |
| Delay | about 1 second | about 2–3 seconds |

> 💡 The word-order problem in "Fast" mode is not caused by showing the text too early: the model translates as it listens, and starts translating before it has heard the second half of the sentence.
> "Accurate" mode waits until the whole sentence is finished before sending it for translation, so the word order is normal.
> For the **best quality** (if you can wait), use feature 4.

> 🔴 **When the microphone picks up a speaker talking in Chinese and you want it translated into English, choose "Accurate".** Tested on a laptop on 2026-09-19: in this situation "Fast" mode
> is very unreliable. Sometimes a whole passage gets no captions at all: in the tests, only 0%–19% of what was said appeared in the captions, while "Accurate" mode with the same microphone got 78%–97% (very few test runs, so treat these as rough figures).
> Reading the built-in sample file, or recording a news broadcast playing on the computer, works normally; but saving what the microphone recorded to a file and reading that is just as unreliable. Feature 6 uses "Fast" mode, so the same applies there.

> ⏱️ In "Fast" mode, a line of source text only appears after a sentence-ending punctuation mark such as a full stop or question mark, a 2.5-second pause, or once 90 characters have built up.
> When people speak Chinese, the transcribed sentences mostly use commas, so during continuous speech the source text may appear 20 seconds or more late — that's down to how it is displayed, not the model being slow.


---

## 🏢 How to set up a hybrid meeting (in person + online)

> 🔴 **Rewritten after testing on 2026-09-22.** The old version suggested "first pick up the meeting-room speakers with a microphone", which did not hold up in testing:
> - **A microphone barely picks up sound coming out of speakers**: Windows' sound processing treats it as noise and removes it.
>   A meeting recording played through laptop speakers gave **0 recognised sentences**; a phone speaker 2 metres away, also **0 sentences**.
> - The same built-in laptop microphone recognised a **real person** speaking without trouble, even standing 3 metres away.
>
> Conclusion: **take the online participants' voices straight from the computer**; don't let them come out of speakers first and then pick them up again with a microphone.
> Turning the speaker volume up doesn't help either — the sound is removed at the microphone end.

### Option 1 (recommended): the caption computer joins the online meeting too, and you choose "Both"

- The caption computer **joins the same meeting** in a browser or the meeting app (**mute** its own microphone in the meeting app, so the room's sound isn't sent to the online meeting a second time)
- In TIO choose **`3` Both**: the online participants' voices come straight from the computer (digitally, never through the air), and the people speaking in the room are picked up by the microphone
- To project the captions: extend this computer's screen to the projector
- If "the same sentence appears twice", the speaker sound is being picked up by the microphone again — use headphones, or turn the speakers down

### Option 2 (the most reliable, but you need the equipment): run a cable straight from the meeting-room sound system

- The **recording output** of the meeting-room mixer or conference unit (REC OUT, AUX, PROGRAM OUT) → a **USB audio interface** → set it as the default microphone in Windows → in TIO choose **`2` Microphone**
- ⚠ Take the feed from "before echo cancellation"; **don't** plug it into the laptop's headset jack (a line-level signal is too strong and will distort). If in doubt, ask the meeting room's AV staff to help

### Option 3 (a fallback, no guarantees): all you can do is pick up the loudspeakers with a microphone

- Choose **`2` Microphone**, and when it asks "Does any of the sound in the room come from loudspeakers (speakers) and also need captions?", choose **`2` (full capture)**: it bypasses Windows noise suppression
- Tested: a meeting recording played through laptop speakers gave 0 sentences with normal capture → 4 sentences with full capture (the original has 7); **a small phone speaker 2 metres away gave 0 sentences either way**
- So it can only be a fallback; always do a dry run in the room before the real meeting

### Which microphone to use for the people speaking in the room

- **A headset lying on the table is not reliable for people further away**: in testing, with a real person standing 3 metres away, the laptop's built-in microphone got it right both times; the headset lying on the table got a whole sentence wrong once out of two
  - 🔴 This test compared only **two**: the laptop's built-in microphone array and a 3.5 mm headset lying on the table. **No external/USB conference microphone was tested**,
    so you **can't** conclude that "built-in beats an external conference microphone" — those are made precisely to "sit on the table and pick up everyone around it", so if you have one connected, use it first
  - Not sure which is better: once it starts, look at the "Sound check" on screen; if it shows "sound received" while someone is speaking, you're fine; if it shows "sound is weak", try another one
- A headset should be **worn on the head** by one person; don't put it on the table as a meeting microphone

### 🔴 Once it has started, don't unplug or plug in the headset

- If the headset plug works loose or is pulled out, the program **reconnects automatically**, and the screen shows "⚠ Microphone disconnected…" → "✓ Microphone reconnected"; but there are no captions for the few seconds it was disconnected
- The **interpreter voice** in feature 6 also reconnects automatically: the screen shows "⚠ Interpreter voice cut out…" → "✓ Interpreter voice reconnected". When the interpretation plays through speakers, it cuts out briefly, for at most about 2–3 seconds
  (unplugging or plugging in the headset makes it cut out briefly even if the speakers themselves weren't unplugged); when it plays through headphones, it waits until the headphones are plugged back in and comes back about 1 second after that
- To change the headset or speakers, the safest way is to press Ctrl + C to stop first, then start again (the captions are saved as two files)

### The "🎚 Sound check" lines on screen

About 6 seconds after it starts, they appear once and tell you **whether sound is reaching the program, and whether there will be captions**:

```
  🎚 Sound check (is sound reaching the program)
     Microphone:     ▮▮▮▮▮▯▯▯  sound received (-45 dB, captions will come through)
     Computer audio: ▯▯▯▯▯▯▯▯  the PC is hardly playing anything right now (-95 dB, no sound means no captions)
```

| What you see | What it means | What to do |
|---|---|---|
| **sound received** | Loud enough to be recognised | Nothing |
| **sound is weak** | Captions may miss words or be inaccurate | Microphone: move it closer to whoever is speaking, or use a different microphone; computer audio: turn the playback volume up (see below) |
| **almost no sound** | There won't be any captions | Check the microphone, and whether the headset plug has worked loose |
| **the PC is hardly playing anything right now** | The computer isn't playing any sound (the online meeting isn't on, or the sound is going to different speakers) | Make sure the online meeting's sound is playing from this computer |
| **no data received** | The device may have been unplugged | Plug it back in; the program reconnects automatically |

- More bars = louder; the dB in brackets is for technical staff, and useful when you send in a screenshot
- After that it only appears again **when there have been no new captions for over 30 seconds** (if there are still none, once every 2 minutes, so it won't flood the screen), with one more line of diagnosis:
  at least one source shows "sound received" → the problem is more likely the network or recognition; only "sound is weak" → turn the volume up or move the microphone closer first; no sound coming in → check the audio capture first
  (in **Both** mode, if one source shows "sound received" and the other is weak or silent, it names that source and covers both cases: if the people speaking
  are on that source, deal with its sound first (move the microphone closer, check it isn't muted, or turn the playback volume up); if they are on the other source,
  the problem is more likely the network or recognition)
  (in Fast mode, if the sound is loud enough but there are still no captions, it also suggests switching to Accurate mode: for some languages or content, Fast mode gives only the translated voice and no text)
- **When the computer audio has been weak for 20 seconds in a row**, it shows a yellow "⚠ Computer audio keeps coming in weak" once, naming the playback device
  (it warns you even while captions are still coming through in fits and starts): turn that device's volume up (the speaker icon at the bottom right of the taskbar), or turn up the volume
  of the meeting app/video player itself. TIO records the sound **after** the volume setting is applied, so if playback is too quiet, the captions will miss words
- The caption file's header also records which kind of capture and which microphone were used for that session, which helps when you track down a problem later

### 🔴 Always do a dry run before the real meeting

**Where to put the microphone is not something you can work out on paper — you have to test it in the room.** We suggest:

1. In **the meeting room you will actually use**, with **the computer and microphone you will actually use**
2. Get one or two colleagues: one speaking in the room, one speaking online
3. Run the captions for **10 minutes**; that's enough

Check these four things:

| Check | If it fails |
|---|---|
| Is what the people in the room say being recognised? | Move the microphone towards whoever is speaking, or switch to a USB conference microphone; don't use a headset lying on the table |
| **Is what the online participants say being recognised?** | Switch to option 1 (the caption computer joins the meeting too, and you choose "Both"). **Turning up the speaker volume doesn't help** |
| Does the same sentence appear twice? | That's echo: use headphones on the caption computer, or turn its speakers down |
| Is the caption text big enough? | In the caption window, press Ctrl + "+" to enlarge it (you can press it repeatedly), and Ctrl + "-" to shrink it. The further away people sit, the bigger it needs to be: the character height (in millimetres) should be about "distance to the furthest seat (in metres) × 9" |

> 💡 While you're at it, work out the **proper nouns** you use often (unit names, project names, the titles of regular attendees),
> so you can type them straight in at the real meeting; it makes a big difference to accuracy.


---

## 4️⃣ Transcript to bilingual ⭐ Use this for documents overseas guests will read

**When to use it:**
- Chinese meeting minutes that an international partner needs to read → translate into English
- A recording of an overseas conference → translate into Chinese
- You need a formal Chinese–English bilingual document

**How is it different from feature 3 (Live bilingual captions)?**

| | Feature 3, live captions | Feature 4, this one |
|---|---|---|
| When to use it | Watching as you listen | Producing a document afterwards |
| How it translates | As it listens, like a live interpreter | The whole file together, so it can see the context |
| Quality | Word order occasionally odd | **Much better** |
| Speed | Live | You have to wait a little |

**How to do it:**

1. Double-click the desktop icon → press `4` → Enter
2. **Pick a file**: a recording, a video, a transcript `.json` or a captions `.srt` all work
3. Choose what to translate into (Decide automatically / Traditional Chinese (Taiwan) / English / Japanese)
4. **Fixed translations** (optional, but strongly recommended): write them as `深耕計畫=Higher Education Sprout Project` (when translating into Japanese, `深耕計畫=高等教育深耕計画`, i.e. the Japanese name),
   with a semicolon `;` between pairs (spaces inside a translation are fine).
   That way proper nouns are translated the same way throughout, not one way here and another way there
5. The background of this document (optional): for example "Research Office meeting on the Sprout Project"; the model then translates more aptly
6. **Proper nouns** (optional; only asked when you pick an audio file): give it unit names, project names and people's names first; it makes a big difference to accuracy
7. **Speaker names** (optional): if you fill them in, the speaker column in the finished document says "Director", "Secretary",
   instead of "Speaker 1", "Speaker 2" (when translating into English, speakers you haven't named are written as Speaker 1; in Japanese, as 話者1, Japanese for "Speaker 1").
   If you pick a `.json`, it first prints each speaker's first line so you can match names to voices;
   if you **already filled in names** for that transcript in feature 2, just press Enter to keep those names; no need to type them again.
   If you pick an audio file, it hasn't been transcribed yet and doesn't know how many speakers there are, so type them "in the order they first speak"; if you're not sure, just press Enter
8. Wait for it to finish

**It produces four kinds of file** (on the desktop, all starting with the same file name):

| File | What it's for |
|---|---|
| `_bilingual.md` | A paragraph of source, then a paragraph of translation, for people to read |
| `_bilingual_table.md` | A table (time / speaker / source / translation), **easy to paste into Word or Excel** |
| `_en.md` (or `_zh-TW.md`, `_ja.md`) | A clean version with the translation only |
| `_bilingual.json` | Machine format; useful later if you want to rebuild the layout or translate into another language |

**The actual output looks like this:**

```
**[00:00:00] Director**

> 好，那我們今天的研發處會議就開始了。第一個案子是深耕計畫的期中報告。

Alright, let's start today's Office of Research and Development meeting.
The first item is the midterm report for the Higher Education Sprout Project.
```

("Office of Research and Development" and "Higher Education Sprout Project"
were set with "Fixed translations"; without them, the model translates them however it likes.)

---

## 5️⃣ Rebuild a transcript ⭐ Your lifeline when something goes wrong

Every time feature 2 finishes, besides the `.md` for people to read, it leaves a `.json` with the same name next to it.
That `.json` holds the raw data (the time, speaker and text of each paragraph). This feature rebuilds it into an `.md`.

**It runs entirely on this computer: no internet, no API calls, no cost at all, and it takes a few seconds.**

**When to use it:**

| Situation | Without this feature | With it |
|---|---|---|
| You are transcribing a three-hour recording and halfway through the computer crashes / you close the window by mistake | Transcribe the whole thing again, paying once more in money and time | Pick the `.partial.json` next to it and rescue the part that was already transcribed |
| The speaker names were entered wrongly ("Director" and "Secretary" the wrong way round) | Transcribe the whole thing again | Enter them again: sorted in 10 seconds |
| The `.md` was deleted or overwritten by mistake | Transcribe the whole thing again | Just rebuild it |

**How to do it:**

1. Double-click the desktop icon → press `5` → Enter
2. **Pick a file**: the `.json` produced by feature 2 (or the `.partial.json` left behind when it was interrupted)
3. It first tells you "This file has N paragraph(s) and N speaker(s).", and also prints **each speaker's first line**,
   so you can work out who is who
4. Enter the speaker names (you can just press Enter to skip: if names were filled in back in feature 2, those names are kept; otherwise it uses "Speaker 1, Speaker 2")
5. A few seconds later the `.md` appears on your desktop

> ⚠️ For recordings over 28 minutes, feature 2 **split them into several parts** and recognised each part separately.
> (Google's official documentation states that the "speaker separation + timestamps" mode only processes 30 minutes of audio at a time,
> so the program leaves a safety margin and splits at 28 minutes.)
> Each part works out its speakers on its own, and from part 2 on, speakers are listed like "Part 2 Speaker 1" (kept apart from part 1).
> The first lines printed in step 3 help you tell people apart: for the same person in different parts, enter the same name.
> (In long transcripts made before 2026-09-25, "Speaker 1" in one part is not guaranteed to be the same person as in another, and there is no way to tell them apart here.)

---

## 6️⃣ Live voice translation ⭐ Like interpreter headphones: you just listen to the translation

**When to use it**: a visiting speaker's talk, an international online meeting, a foreign-language video with no subtitles —
when you want to **hear it in Chinese**, rather than keep staring at the captions.

Bilingual captions still run on screen as usual, and everything is saved at the end as usual — the voice is an extra, not a replacement for the captions.

### 🔴 When recording "Computer audio", you must choose two routes

This is the easiest thing to get confused about in this mode, so here is why, first:

Recording "Computer audio" means capturing **whatever the system's default playback device is playing**.
So "I don't want to hear the original audio" **can't be solved by muting** — mute it, and you switch off the recording source as well.
The only way is to send the two sounds along two different routes:

| | Where it goes | Can you hear it? |
|---|---|---|
| **① Original audio** (the meeting sound) | A digital output/HDMI with nothing connected, headphones that are plugged in but that you won't wear, or a virtual audio cable | **No** (the program only uses it for recording) |
| **② Interpreter voice** | Speakers, or the headphones you are wearing | **Yes** |

That way, during the meeting you **only hear the translation**, and the two sounds never overlap; the interpreter voice also can't be recorded back in
and leave the model translating what it has just said itself (that would snowball into a mess, and every round costs money).

The program automatically switches Windows' sound output to ①, and **switches it back automatically when it ends**.
If it crashes or is force-closed partway through, it switches back automatically the next time it starts, so on the Windows side you are not left with "no sound"
(if the "default communication device" was set separately, that is switched back too; the meeting app's speaker you have to change back yourself — see below).

> 🔴 **Only you know** which route is the one you "can't hear" — whether there is a cable in the optical port, whether the headphones are on your head:
> Windows can't tell, and the program won't guess. So you choose both routes yourself, and once you've chosen, it plays one beep on each so you can check on the spot;
> if you got them the wrong way round, you can choose again straight away.

| Audio source | Rule |
|---|---|
| Computer audio | You must choose two routes (see the table above); once chosen, a listening test checks them |
| Microphone | Please wear headphones, and in the menu choose those headphones for the interpretation (it plays a test beep once you've chosen; if the computer has only one usable playback device, it doesn't ask). If you choose speakers, the microphone will record the interpretation back in: the model keeps repeating the same sentence and doesn't stop, and you are charged the whole time. The program can't prevent it |
| Saved audio/video file | This problem doesn't arise. The file is read directly, so the original audio is never played at all, and you only hear the translation anyway; it still asks where to play the interpretation (unless there is only one playback device) |

### How to use it

1. Press `6` in the menu
2. Choose the audio source
3. If you chose "Computer audio", set the two routes in turn:
   **① Which route should the original audio (the meeting sound) take?** (the one you can't hear) → **② Where do you want to hear the interpreter voice?** (the one you can hear)
4. Listening test: the program plays one beep on each route. You should **not hear** the first beep, and you **should hear** the second;
   if that's not what happened, choose "No, choose both routes again"
5. If you chose "Microphone" or "Saved audio/video file", it asks instead **Where do you want to hear the interpreter voice?**: choose the headphones you are wearing (the list marks the current default),
   and once you've chosen, it plays a test beep so you can check; if you didn't hear it, choose "No, choose again".
   (If the computer has only one usable playback device, it doesn't ask, and the interpretation comes straight out of that device)
6. Choose the language to translate into
7. Press Enter to start

> **Meeting apps need setting separately**: Teams/Zoom/Webex have their own speaker settings, which don't necessarily follow Windows.
> **With the new Teams, before you start, always go into Teams' device settings and set the speaker to the ① device** — its speaker list has no
> "system default" option, so it doesn't follow the program's switch (tested 2026-09-19); if you don't set it, the original audio never reaches ①, nothing is captured, and there is no translation.
> Zoom/Webex: if the routes are switched but you can still hear the original audio, go into that app's audio settings and **set the speaker to the ① device directly**.
> Chrome (Google Meet/YouTube) follows the system, so you don't need to do anything.
> 🔴 **When you finish (or stop partway), remember to change it back**: the program switches Windows back to your original speakers, but it can't change the meeting app.
> If you set the Teams/Zoom/Webex speaker to ① as described above, change it back yourself to the one you normally listen on, or you won't hear anything in your next meeting.

> **Don't turn the volume of the ① device down to 0**: on some computers the captured volume drops along with it.
> In testing, 8% still translated normally, so there's no need to turn it up; this is just a precaution.

> **What if there is only one sound output?** Plugging in headphones usually adds a second route (headphones as ①, speakers as ②, and don't wear the headphones; on 2026-09-19 this worked with wired headphones
> on one laptop; Bluetooth hasn't been tested yet; on some computers the speakers and headphones are the same output, so plugging them in adds nothing);
> or install a virtual audio cable (for example the free VB-CABLE): it is a route you can never hear, used just for the original audio.

### Things you may run into

- **The voice is a little behind the screen**: that's normal; simultaneous interpretation always lags about 1–2 seconds behind the speaker
- **When the speaker talks too fast, the voice skips a few sentences**: the program would rather skip than let your ears fall further and further behind;
  **the captions are complete**, so just read the saved file afterwards; at the end, the screen tells you how many seconds were skipped
- **The voice flips between male and female**: this is a limitation of the model itself (Google's official documentation says so too); the voice may change after a long pause
- **It switches to a new connection every 8 minutes**: the captions aren't affected, but the voice may cut off mid-sentence
- **Very unreliable when a speaker talks into the microphone and you translate into English**: sometimes a whole passage doesn't get translated (see the note on "Fast" mode under feature 3).
  In this situation, switching to feature 3, choosing "Accurate" and reading the captions is more reliable

### Only "Fast mode" has a voice

Feature 3's "Accurate mode" translates with a text model, so there is no voice to play.
Feature 6 always uses Fast mode (that is, Google's simultaneous-interpretation model).

---

## 💰 How much does it cost?

### What a one-hour meeting costs

| Feature | Per hour |
|---|---|
| 1 Live meeting captions | about **NT$17** |
| 2 Recording to transcript | about **NT$20** |
| 3 Live bilingual captions (**Accurate mode**) | about **NT$18** |
| 3 Live bilingual captions (**Fast mode**) | about **NT$71** |
| 4 Transcript to bilingual | about **NT$16** (per hour of transcript) |
| 5 Rebuild a transcript | **NT$0** (no internet) |
| 6 Live voice translation | about **NT$71** (the same connection as feature 3's Fast mode; the voice is not charged extra) |

> 🔴 **Feature 3's Fast mode costs about 4 times as much as Accurate mode**, which is the opposite of what you might expect.
> Fast mode uses Google's "simultaneous interpretation" model, which **always produces translated speech**, and speech output is priced
> at 8 times the rate of text; Accurate mode runs text-only transcription + translation, so it is cheap.
> **In most cases you should choose Accurate mode anyway** (the translation's word order is better too); you only need Fast mode if you want the immediacy of simultaneous interpretation,
> or want to use feature 6 to listen to the interpreter voice.

### Which model each feature uses, and how it is charged

US dollars are converted at **1 USD = 32 TWD**. Unit prices are taken from Google's official pricing page (checked 2026-09-18).

| Feature | Model used | Input price | Output price | Per hour |
|---|---|---|---|---|
| **1** Live meeting captions | `gemini-3.5-transcribe-live` | $3.50/1M ($0.005/min) | $21.00/1M ($0.004/min · **text**) | US$0.54 = NT$17 |
| **2** Recording to transcript | `gemini-3.5-transcribe` (**two passes**)<br>+ `gemini-3.5-flash` (alignment) | $2.00/1M ($0.003/min)<br>+ $1.50/1M | $12.00/1M ($0.002/min · text)<br>+ $9.00/1M | about US$0.62 = NT$20 |
| **3 accurate** Bilingual captions · Accurate | `gemini-3.5-transcribe-live`<br>+ `gemini-3.5-flash-lite` (translation) | Same as feature 1<br>+ $0.30/1M | Same as feature 1<br>+ $2.50/1M | about US$0.57 = NT$18 |
| **3 fast** Bilingual captions · Fast | `gemini-3.5-live-translate-preview` | $3.50/1M ($0.0053/min) | **$21.00/1M ($0.0315/min · audio)** | **US$2.21 = NT$71** |
| **4** Transcript to bilingual | `gemini-3.5-flash` | $1.50/1M | $9.00/1M (**including thinking**) | about US$0.51 = NT$16 |
| **5** Rebuild a transcript | **No model is called** | — | — | **NT$0** |
| **6** Live voice translation | `gemini-3.5-live-translate-preview` | Same as 3 fast | Same as 3 fast | **US$2.21 = NT$71** |

**Four points that help you read this table:**

1. **What makes it expensive is whether the output is text or audio**, not the model name. Both are $21.00/1M, but for feature 1, which outputs text, the **output fee** is only US$0.004×60 = US$0.24 an hour, while for feature 3 fast, which outputs audio, the **output fee** is US$0.0315×60 = US$1.89 an hour (add the input fee and you get the table's US$0.54 and US$2.21).
2. **Feature 2 runs two passes** (the first gets the speaker timeline, the second the Traditional Chinese text), so the unit prices are multiplied by 2; after the two passes, `flash` also aligns the two results, which usually adds about NT$1–2 an hour.
3. **Feature 6 costs no more than feature 3 fast**. That connection is producing translated speech anyway, and it is already being billed; feature 6 just plays it.
4. **Most of feature 4's cost goes on the model's "thinking"**: the model thinks it through before translating, the thinking uses about 2.5 times as many tokens as the translation, and it is billed at the output price too.

> The translation part of feature 3 accurate (`flash-lite`) in the table is an **estimate**: an hour of talk is only a small amount of text, so its share is under 5%.
> Feature 4 was **measured on 2026-09-19** (a 60-minute transcript was actually translated once); feature 2's alignment was measured on short recordings and then scaled up.
> The other figures are taken from the effective per-minute prices on the official pricing page.

---

## 💳 Free vs paid: check this before you record a real meeting

> ⚠️ **This matters: it affects both your wallet and the security of your data. Don't skip it.**

The API key you have just created is **on the free tier by default**. The differences between the free and paid tiers:

| | Free tier | Paid tier (Tier 1 and above) |
|---|---|---|
| Cost | No charge | Pay for what you use; about NT$20 for a one-hour meeting |
| **Is your recording used for training?** | **Yes** | No |
| **Could human reviewers read it?** | **Possibly** | No |

**How to check which tier you are on:**
1. Go to `aistudio.google.com` → **Get API key** on the left
2. Find the project your key belongs to; next to it, it shows **Free** or **Paid**
3. If it says Free, click **Set up Billing** and link a credit card, and it becomes the paid tier

### 🔴 Bottom line: to record real meetings, turn on the paid tier

This isn't a "recommendation"; it's **a precondition for using this tool**. Three reasons:

**① Your data is used for training, and human reviewers may read it** (the table above)
University meetings deal with personnel, budgets, review comments and students' personal data; this alone is enough to rule out the free tier.

**② Google no longer publishes the free tier's quotas**
The official rate-limits page now has **no per-model quota table at all**, just one sentence telling you to look in AI Studio yourself:

> "Rate limits depend on a variety of factors (such as your usage tier) and can be
> viewed in Google AI Studio."
> — [ai.google.dev/gemini-api/docs/rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) (checked 2026-09-08; the page says it was last updated on 2026-09-02)

So **nobody can tell you how many hours of meetings the free tier can handle in a day** — including me. The only way to know your own quota is to sign in to
[aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) with your own account and look.

The same page also says:

> "Specified rate limits are not guaranteed and actual capacity may vary."
> (In other words: the published quotas are not guaranteed, and the real capacity may be different)

Finding out halfway through a meeting that the quota has run out is not something you can calculate in advance and avoid.

**③ The daily quota doesn't reset at midnight Taiwan time**

> "Requests per day (RPD) quotas reset at midnight Pacific time."

Midnight US Pacific time ≈ **3–4 pm Taiwan time** (depending on US daylight saving time). Use up the quota in a morning meeting,
and it doesn't come back until that afternoon; a long afternoon meeting may find the quota suddenly resetting or running out partway through.

> ⚠️ One more easy trap: **the quota belongs to the "project", not to the "key".**
> If you issue several keys under one project and hand them out to colleagues, everyone shares one quota and you crowd each other out.
> Everyone should create their own project with **their own Google account**.

**If you haven't checked, and you are still on the free tier:**
- ✅ Fine to use: public lectures, open information sessions, your own test recordings
- ❌ **Upgrade to the paid tier first**: meetings about personnel, budgets or review comments, and meetings with personal data


## What if something goes wrong?

| What happens | What to do |
|---|---|
| You double-click it, a window flashes up and disappears, and then the menu appears | That's normal. `4_Start.bat` opens a separate "TIO" window for the menu, and its own window closes straight away |
| The menu hits an error | The program stops and shows the reason and technical details; take a screenshot of the whole window, then double-click `6_Diagnostics.bat` and send a screenshot of that too |
| The menu doesn't appear; the window shows an error message in English and stops at "Press any key to continue" | The program files are incomplete or damaged (for example, unzipping didn't finish, or antivirus software quarantined a file). Unzip again, then double-click `3_Install.bat`; if it's still the same, take a screenshot of this window and send it together with the `6_Diagnostics.bat` screen |
| No captions appear at all | Check that the computer is actually playing sound; for an online meeting, remember to choose `1`, not `2`. The meeting app's speaker must be set to the **Windows default playback device** (tested on one laptop, 2026-09-19: the new Teams has no "system default" option, so pick the same device by hand in Teams' device settings); the "Audio source: …" line on screen at the start shows which device is being recorded. Feature 6 with "Computer audio" is the exception: the meeting app's speaker must be set to **the ① device** you chose in the menu (see the feature 6 instructions), not the usual Windows default |
| You chose the microphone, and the program says "No usable audio source" and stops, with no files | This computer has no microphone connected, or Windows privacy settings are blocking it (Settings → Privacy & security → Microphone). Connect a microphone and start again |
| The transcript header says "This transcript may be incomplete" | There are six possible causes: ① nothing was recognised in the later part of the recording (silence, music, noise) ② the same words were repeated heavily and were dropped when the text was tidied up ③ **a problem in one part** (a whole stretch at the end or in the middle of that part not recognised, the results of the two recognition passes not matching, or the text flooded with the same handful of sentences, over and over) ④ a sentence the first recognition pass heard is missing from the tidied-up text, and re-transcribing it on its own didn't bring it back (the header gives the time range and the speaker) ⑤ **the recording has sound, but the transcript doesn't cover that time** (over 10 seconds in a row, or at least 6 seconds in total within any 30 seconds; typically English spoken in a Chinese meeting, music or applause; the header gives the time range; when the recording is noisy from start to finish and speech is hardly louder than the background, this check can't see well, and the header adds an ℹ️ note that does not count as a gap) ⑥ **the times of the paragraphs overlap or go backwards** (typical of very long recordings that mix several languages; the header gives the time range — listen to that stretch against the recording). For ① and ②, and when the end of a part has no content, the header says which minute recognition got up to; in the other cases, the header says which part and which time range has the problem. If you need that part, cut it out separately and transcribe it again (for ②, ③ and ④ the header also suggests how to cut it) |
| You closed the window halfway through a transcription | Before it exits, the program first deletes the temporary recording on your computer and the copy in the cloud. Recordings **over 28 minutes** are split into several parts automatically, and the parts already fully transcribed are kept in `.partial.json`, which feature 5 can rescue; **recordings of 28 minutes or less are processed as one part**, which is only saved once both recognition passes, the alignment and the re-transcription for that part are all done, so if you close it **while recognition is still running**, no `.partial.json` is left and you have to transcribe the whole thing again; but if something goes wrong only after that part has fully finished (for example, the file can't be written), it is still left, so have a quick look on the desktop for this file first |
| The network drops partway through transcribing or translating | When the connection is completely down (a Wi-Fi outage, say), the program waits for the network to come back: it tries again every 20 seconds, for up to 5 minutes, and carries on as soon as it returns (the screen says "The internet connection is back"); if the network is merely unstable and drops for a moment, it just retries a few times as before. If it is still down after 5 minutes: **transcribing** stops — for a recording over 28 minutes, the parts already fully transcribed still become a transcript (the header lists the missing parts); a recording of 28 minutes or less (or one that stops in its first part) produces nothing, so transcribe the whole thing again once the network is working. The exceptions: if it drops at the speaker-segmentation step, the program switches to an estimate and still finishes; if it drops while re-transcribing missed passages, those are skipped and listed in the header. **Translating** stops, and what has been translated is still saved, with the untranslated paragraphs marked (the same happens if you press Ctrl+C while it is waiting; if nothing has been translated yet, Ctrl+C leaves no file). When the input to translate is a recording, the transcribing and translating steps can each wait up to 5 minutes |
| The same sentence appears twice | Echo in a hybrid meeting: the meeting computer's speakers and microphone are picking each other up; switch to headphones |
| The people in the room are picked up, but not the people online | The online participants have to be taken straight from the computer: the caption computer joins the meeting too, and you choose "Both" (see "Option 1" in the hybrid meeting section above). Turning up the speaker volume doesn't help |
| The caption text is too small | In the caption window, press Ctrl + "+" to enlarge it (you can press it repeatedly) and Ctrl + "-" to shrink it; there's a reminder of this on screen at the start too (Ctrl + 0 is the official "reset font size" key, but it clashes with the Going Natural (自然輸入法) Chinese input method, so we don't teach it) |
| The captions suddenly stop (the headset plug came loose, or it was unplugged and plugged back in) | The program reconnects automatically and shows "✓ Microphone reconnected"; if that never appears, press Ctrl + C to stop and start again (all the captions so far have been saved) |
| Chinese text shows up as boxes or garbled characters | Open it with "Windows Terminal" instead (search the taskbar for "Terminal"); the older black Command Prompt window handles Chinese fonts poorly |
| The captions show Simplified Chinese characters | Most cases have been dealt with; **two remain**: ① with feature 3 on "Fast", or with feature 6, when Chinese is being translated into another language, the **source** line on top is occasionally a whole block of Simplified Chinese (roughly once in three sessions); the translation is unaffected. This has been tested over 29 connections: whether Google is told to use Traditional characters for the source, or even the opposite, Simplified, the model ignores it — it's not a setting that's wrong, it simply can't be changed. ② with feature 3 on "Accurate" and "Translate into Traditional Chinese (Taiwan)", when the speaker is speaking Chinese (for example, people speaking Chinese in the room at a hybrid meeting), the source comes out in Simplified Chinese (seen once in testing, 2026-09-19); the translation is still in Traditional Chinese, it just amounts to rewriting the Chinese. If you really need that source text: paste the `.txt` into any Simplified-to-Traditional converter website; in case ① you can also switch to feature 3's "Accurate" mode (in Accurate mode the source comes from a different model, which uses Traditional characters as instructed; feature 6 has no "Accurate" mode to switch to)|
| You choose "Microphone" with headphones plugged in: which microphone does it pick up? | On some computers (for example laptops where the headphones and microphone share one jack, i.e. a combined headset jack), plugging in headphones automatically switches to the **microphone on the headphones**, and it only switches back to the computer's microphone when you unplug them (tested on one laptop, 2026-09-19). If the headphones are plugged in but not worn and you choose "Microphone", it picks up the headset microphone hanging to one side — unplug the headphones, or go to "Settings → System → Sound → Input" and switch back to the computer's microphone. At the start, the screen shows which one it is using (the "Microphone: …" line) |
| A passage in the transcript just says "(this passage was left out of the tidied-up transcript)" | Usually that speaker said nothing but "mm" and "right" the whole meeting, and it was left out when the text was tidied up. The line is kept so that the speaker names you entered in advance don't all shift out of line |
| There's no shortcut on the desktop | Some organisations' computers don't let programs write to the desktop; this **makes no difference to using it**. Just double-click `4_Start.bat` in the folder; if you want a shortcut, right-click `4_Start.bat` → Send to → Desktop (create shortcut) |
| When you paste the key, the screen shows a row of `*` | That's normal: it stops the key sitting on the screen in plain text. After you press Enter, it shows a confirmation that reveals only the start and end, like "Received: AQ.Ab…xyz9 (53 characters)", and then checks with Google whether the key works |
| The key was pasted wrong, has expired, or you want to change it | Choose **9 "API key settings"** in the menu: you can change to a new key, check whether the current one works, or clear the key saved on this PC (for shared PCs, or before handing the PC back) |
| The screen says "There's a problem with the API key" | For live captions, first press Ctrl+C to stop; then go back to the menu and choose **9** to check the key or change it. When a transcription or translation doesn't succeed, the menu checks with Google once by itself, and if it confirms the key is bad, it asks you straight away whether you want to change it |
| Feature 6 is running, but there's no interpreter voice at all from the headphones/speakers | First check that the line at the top of the screen, "🔊 The interpreter voice will play from '…'", names the device you're wearing or listening to right now. If it doesn't, go back to the menu, run feature 6 again and pick the right device at "Where do you want to hear the interpreter voice?"; if it does, turn that device's volume up, or check with the speaker icon at the bottom right of Windows that it isn't muted. At the end, the screen says it "sent about N seconds of audio to '…' in total" — that is how much was **sent into the device**, which doesn't guarantee you could hear it, so a number on this line doesn't mean the device is fine |
| Feature 6 with the microphone: after the speaker stops, the captions keep repeating the same sentence without stopping | The interpreter voice is coming out of the speakers and the microphone is recording it back in, so the model keeps translating its own voice, and you are charged the whole time. Press Ctrl+C to stop first; then put on headphones, choose the headphones you're wearing at "Where do you want to hear the interpreter voice?", and start again |
| No sound from the speakers after using feature 6 | Finishing normally, pressing Ctrl+C and clicking the window's X all switch back to your original speakers automatically. If it crashes or is closed from Task Manager, **it switches back automatically when you return to the menu (or the next time you open the menu)**; if you can't wait, click the speaker icon at the bottom right and pick your original speakers yourself. If you set the meeting app's (Teams/Zoom/Webex) speaker to ① as described, the program can't change that, so change it back yourself |
| Feature 6 (or feature 3 on "Fast") keeps running after you press Ctrl+C | It first shows "Ctrl+C received, wrapping up", and takes about 3–5 seconds to save the files before it ends. You can also end it at that point with the X in the top-right corner of the window, but the tidied-up `.md` won't be produced (the word-for-word `.txt` is still there), and the menu closes as well; feature 6's sound output still switches back automatically |
| You want to know what's wrong | Double-click `6_Diagnostics.bat`: it lists whether Python, the packages, ffmpeg, the key and the files are all there; take a screenshot of the whole window and report it (see "When you're stuck" in "1_Install_Guide_READ_FIRST.md" for how to report) |
| Anything else | Take a screenshot of the complete error screen and report it (see "When you're stuck" in "1_Install_Guide_READ_FIRST.md" for how to report) |

---

## Don't want it any more? How to remove it

Double-click **`7_Uninstall.bat`** in the folder. A window opens and lists everything that can be removed, item by item,
and **you tick the ones you want removed**. Anything you don't tick is left completely alone.

Ticked for you by default (these all belong to this tool only, so removing them is safe):

- ✅ **Your Gemini API key** — this is the most important one. The key is as good as your account password,
  so always remove it before the computer changes hands, goes back to your organisation, or goes in for repair
- ✅ Temporary meeting recordings (the raw audio of whole meetings in `%TEMP%`, left behind only when the program is force-closed; if there are none, it can't be ticked)
- ✅ The desktop shortcut
- ✅ The Python packages only this tool uses (`google-genai`, `sounddevice`, `PyAudioWPatch`; any that are no longer installed aren't listed)
- ✅ The sound-output record left by interpreter mode (feature 6) (`%LOCALAPPDATA%\TIO-Meeting-Genie`; it only notes "which device to switch the sound output back to after interpreting";
  if the last interpreting session didn't end normally, it first switches the sound output back to the original device, then deletes the record)

**Not** ticked by default (other programs may well use them too, so ticking them could break something else):

- ⬜ `numpy`, `scipy` (very common general-purpose packages)
- ⬜ ffmpeg (often used by video editors and downloaders too)
- ⬜ Python itself (the highest risk)
- ⬜ This whole program folder

If you tick any of these, another confirmation window pops up to explain the risk. Before you press "Start removing",
it also shows you a list of **every single action it is actually going to carry out**.

> 🔴 **The transcripts, captions and bilingual documents you made are never deleted.**
> Those `.md` / `.txt` / `.json` files on your desktop are your data, and the uninstaller doesn't go anywhere near them.

**If Python has already been removed**, `7_Uninstall.bat` tells you the three things left to do by hand:
delete the folder, delete the environment variable `GEMINI_API_KEY` (search the Start menu for "environment variables"), and delete the desktop shortcut.

### 🔴 Installation says "certificate error" and the packages won't install

If the error message mentions `SSLError`, `certificate` or `Could not fetch URL https://pypi.org/...`,
it means **your company or campus firewall or antivirus is intercepting HTTPS**; Python doesn't recognise the certificate it swaps in,
so it can't reach the package server. **You didn't do anything wrong, and the program isn't broken.**

The Setup Wizard automatically retries once using the "Windows certificate store" (which holds the root certificates IT installed).
If that still doesn't work, the screen gives you three options straight away:

| Option | Details |
|---|---|
| ① **Install again on a different network** ⭐ | Turn on your phone's hotspot and run `3_Install.bat` once. If the office network only blocks package downloads, you can use the tool there as usual once it is installed; if "Certificate intercepted" appears while you use it, the connection to Google is blocked too: ask IT to allow `generativelanguage.googleapis.com` |
| ② Ask IT to add these to the allowlist | `pypi.org` and `files.pythonhosted.org` |
| ③ Skip the certificate check | There's a button on screen; it first explains the trade-off and asks you to confirm |

**We suggest trying ① first**: it's the quickest and cleanest — the packages only need installing once, and after that there's no need to connect to PyPI again.

---

### 🔴 What to do if the folder won't delete

Sometimes Windows says "You'll need to provide administrator permission to delete this folder".
**This is almost never really a permissions problem**: something still has hold of files inside it. Deal with it in this order:

1. ⭐ **Close any File Explorer window that has this folder open** (including its subfolders), and all of this
   tool's black windows, then delete it again
   → the case that actually happened was exactly this: the folder was open in the user's own window, so it couldn't be deleted
2. Still no good → **restart the computer, and delete it as the very first thing after it starts**
   (this step is also a diagnosis: if it deletes after a restart, it was only locked before, not a permissions problem)
3. Still no good → double-click **`8_Rescue_Undeletable_Folder.bat`** in the folder

`8_Rescue_Undeletable_Folder.bat` first **only checks and deletes nothing**, and tells you who the owner is, whether you have permission,
and which program is using it. It asks you separately before it does anything. It only touches this one folder.

> ⚠ Advice online may tell you to change permissions with `takeown` / `icacls`. If this folder is in OneDrive,
> doing that can affect other synced files, **so please don't**.

---

*Technical details and known pitfalls are in `references\gemini-speech-guide.md`.*
*For sharing/installation instructions, see `1_Install_Guide_READ_FIRST.md`.*

---

**TIO Voice Genie**  Developer: CY KUO  Licence: MIT License (full text in `LICENSE`)  Terms of use and disclaimer: see the last section of "1_Install_Guide_READ_FIRST.md"

The transcripts and caption files you produce with this tool are your own data, and have nothing to do with the licence;
speech recognition is provided by the Google Gemini API, and its costs and terms follow Google's rules.
