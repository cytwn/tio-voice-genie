# TIO Voice Genie

Uses Google's **Gemini 3.5 Transcribe / Live API** for five jobs: live meeting captions,
recording (audio or video) → Traditional Chinese transcript, live bilingual captions, transcript → bilingual document, and live voice translation (interpreter mode),
plus a purely local transcript rebuild. All of them have been tested end to end on a real PC.

Ordinary users start by double-clicking `4_Start.bat`. They see an English menu and never have to type a command.
The `python scripts/xxx.py` commands below are for people who want to use the command line directly, or plug the tools into their own workflow.

> 🔴 Before you start, read [`references/gemini-speech-guide.md`](references/gemini-speech-guide.md).
> It lists the pitfalls we have already hit, especially two: the **Traditional Chinese trap** and **the free tier must not be used to record real meetings**.

---

## Installing and uninstalling

**Ordinary users**: double-click `3_Install.bat`. On a PC without Python, a dialog box first explains the situation and asks for consent; once Python has been installed automatically, setup **carries straight on** (no need to close the window and run it again).
Next the **Setup Wizard window** opens. It first lists what it will do on your PC ("Before installing: what this will do"; usually four things, one or two more if files from an older version or "from the internet" marks are found),
and does nothing until you press "I agree, start installing". There is a progress bar and a step-by-step log, and if something fails it shows the real error message.
When it finishes, there is a "TIO Voice Genie" shortcut on the desktop; double-click it to start.

> A Python without tkinter (very rare) automatically falls back to the text version, `scripts/setup.py`.
> ⚠ **It is not quite the same**: the text version does not create a desktop shortcut, does not clean up files left by older versions, and has no automatic SSL/truststore retry.

**Don't want it any more**: double-click `7_Uninstall.bat`. The Uninstall Wizard opens, and you tick each item you want removed:

| Item | Default | Why |
|---|---|---|
| Gemini API key (environment variable) | ✅ ticked | As good as your account password; always remove it before the PC changes hands |
| Temporary meeting recordings (raw audio of whole meetings in `%TEMP%`) | ✅ ticked (if any are left) | Left behind only when the program is force-closed; clear them before the PC changes hands (can't be ticked if there are none) |
| Desktop shortcut | ✅ ticked | Belongs to this tool only |
| `google-genai` / `sounddevice` / `PyAudioWPatch` | ✅ ticked | Only this tool uses them (ones that are no longer installed can't be ticked) |
| The sound-output record of interpreter mode (`%LOCALAPPDATA%\TIO-Meeting-Genie`) | ✅ ticked | Only feature 6 leaves it; if the record shows the sound output has not been switched back yet, it is first switched back to the original device, then the record is deleted |
| `numpy` / `scipy` | ⬜ not ticked | General-purpose packages that other programs are quite likely to use too (ones that are no longer installed can't be ticked) |
| ffmpeg | ⬜ not ticked | A general-purpose tool that video editors and the like often use too |
| Python itself | ⬜ not ticked | Highest risk; removing it may break other software |
| Program folder | ⬜ not ticked | If ticked, it is deleted after the window closes |

Ticking a risky item brings up one more confirmation. Before you press "Start removing", it lists **every command it will actually run**.

🔴 **The transcripts, captions and bilingual documents you produced are always kept**: not a single line of code in the uninstaller
scans for them or deletes them.

**Manual installation** (for development/debugging):
```bash
pip install -r requirements.txt
```
You also need `ffmpeg` on the PATH. Put the API key in the environment variable `GEMINI_API_KEY`.

**Windows only**: recording "computer audio" (what the PC is playing) uses WASAPI, which only exists on Windows, so it can't work on Mac/Linux.

Want to share this toolkit with someone else? See [`1_Install_Guide_READ_FIRST.md`](1_Install_Guide_READ_FIRST.md).

---

## The six features

### 1. Live meeting captions
Captions appear live while the meeting is running. When it ends, it automatically saves an `.md` (for people to read) and a `.txt` (a live backup).

```bash
python scripts/live_caption.py --source system --vocab 深耕計畫 研發處   # proper nouns as they should appear in the transcript
```
- `--source system`: records **computer audio** (Teams / Meet / Zoom) ← use this for online meetings
- `--source mic`: records the microphone ← use this in a physical meeting room
- `--source both`: a mix of the two

Grey text = interim captions (they appear after about 1 second and keep being corrected); white text = final text.
Final text comes from `SentenceGate` (`scripts/_live.py`), which splits the interim text into sentences at punctuation by itself, **locking one sentence at a time**.
When the model moves on to a new paragraph, the old paragraph's not-yet-final text is sent out first (fixed 2026-09-19: before that, if the model changed paragraph before a single sentence had been split off,
the whole paragraph disappeared).
The server's `input_transcription` is deliberately not used: it only arrives once a pause by the speaker is detected,
so during a continuous talk it can take over a minute and then deliver one big block (tested: 7 minutes produced only 1 paragraph).
**Live mode can't tell speakers apart** (tested: the Live API's diarization doesn't work). To label speakers, use feature 2.

It produces two files:
- `.md`: created when you end normally with Ctrl+C; this is the one for people to read
- `.txt`: **written the moment each piece of final text arrives**. If the program crashes, the PC freezes or the program is force-closed,
  the captions for the whole meeting are still in this file (tested: after the program was killed, no `.md` was produced, but the `.txt` was intact).

> An `.srt` (subtitle track) is **not produced** by default: opened on its own it just brings up an empty player, and most people never need it.
> If you really do want to put it on a video, just add the `--srt` option.

### 2. Recording (audio or video) → Traditional Chinese transcript (with speakers and timestamps)

```bash
python scripts/transcribe_meeting.py meeting_recording.m4a \
    --vocab 深耕計畫 研發處 會計室 教學組長 \
    --names "Chair Wang" "Ms Li"
```
It produces `meeting_recording_transcript.md` (+ a `.json` with the same name):

```
**[00:00:00] Director**
Right, let's begin today's Research Office meeting. The first item is the interim report on the Sprout Project.

**[00:00:09] Secretary**
Let me add something here: the deadline for clearing expenses has been extended to 31 October.
```
(A sentence that was missed when the text was tidied up, and was then re-transcribed on its own from the original audio, gets an extra "[re-transcribed]" after its heading; see 5_User_Guide for details.)

`--vocab` really helps: in testing it corrected 「會計師」 (accountant) back to 「會計室」 (Accounting Office), and 「計劃」 back to 「計畫」 (the spelling of "project" used in official names).
Feed in the names of units, projects and people first, and the accuracy is much better.

Recordings longer than **28 minutes** are automatically split into parts (`MAX_CHUNK_SEC = 28 * 60`).
🔴 The limit is not the 65 minutes you get from the token count, but what the official Limitations section says:
"with speaker diarization or word-level timestamps turned on, audio processing is limited to 30 minutes".
Go over it and **there is no error, and the whole file is billed**. The official docs don't say what happens to the part beyond the limit,
and in our own tests we have never once confirmed a cut-off where "only the first 30 minutes were transcribed".
The other limit is the officially stated "at most 1 hour per request" (without speaker separation):
the 65.4 minutes in earlier documentation was worked back from the token limit and **overestimated it**; in testing, 60.6 minutes was already rejected.
The documentation and the on-screen messages must both match the program's actual thresholds.
If one part fails, the other parts are not affected, and the header of the output file lists which time ranges are missing.

### 3. Live bilingual captions

```bash
python scripts/live_bilingual.py --source system --target zh-TW        # Fast mode: translates as it listens, ~1s delay
python scripts/live_bilingual_hq.py --source system --target zh-TW     # Accurate mode: waits for whole sentences, ~2-3s delay
```
When you listen to a talk/video, the source and the translation are shown together (`--target` takes zh-TW, ja or en, the same three choices as in the menu). In Fast mode the word order occasionally jams up
(the model starts translating before it has heard the whole sentence). Accurate mode waits until the sentence is finished before sending it for translation, so the word order is normal but the delay is longer.
`--source system` (computer audio) / `mic` (microphone) / **`both` (a mix of the two, for in-person + online meetings)** /
`file` (reads an audio/video file directly, so no other sound gets recorded).

> `both` is **a true mix that adds the two signals sample by sample**. Early versions had the two sources share one queue, so the result was
> "[mic 100ms][system 100ms]…" interleaved, with double the amount of audio, and recognition went haywire.
> 🔴 Testing on a laptop on 2026-09-19 caught another case: when both lanes **keep sending data but arrive at staggered times** (a muted headset keeps sending, and so does a Teams call),
> the old code still interleaved them (80 seconds were sent as 117.8 seconds, and the lane with the speech had 1 blank block in every 3). Mixing now lives in `_live.mix_lanes` (shared by all three scripts),
> which waits until every lane that is sending has a full block before adding them together.

### 4. Transcript to bilingual

```bash
python scripts/translate_transcript.py meeting.mp3 --to en \
    --glossary 深耕計畫="Higher Education Sprout Project"
```
Takes an audio/video file, a `.json` transcript or an `.srt` subtitle file, and gives the whole thing to a text model to translate (it can see the context,
so the quality is far better than live translation). It outputs four files: the bilingual md, the bilingual table (can be pasted into Word/Excel), a translation-only version and the bilingual json.
`--glossary` locks in fixed translations for proper nouns (the example maps the Chinese project name to its English name); add `--srt` if you want a bilingual srt subtitle track.

### 5. Rebuild a transcript (purely local, free)

```bash
python scripts/json_to_md.py meeting_recording_transcript.json --names "Chair Wang" "Ms Li"
python scripts/json_to_md.py meeting_recording_transcript.partial.json      # rescue an interrupted transcription (usually only multi-part recordings leave one)
```
Every time, feature 2 leaves a `.json` with the same name next to the `.md` (the raw paragraph data). This script rebuilds it into an `.md`,
with **no API call and no cost**. Two situations: when a recording **longer than 28 minutes**, automatically split into parts, crashes halfway through, the parts
already fully transcribed are kept in `*.partial.json`, and this script rescues them (**a recording of 28 minutes or less is processed as one part**, and is only saved once
that part's two recognition passes, alignment and re-transcription are all done, so a crash **in the middle of recognition** leaves no `*.partial.json` and the whole thing has to be transcribed again; but if something goes wrong only after that part has fully finished, the file is still left, so have a look on the desktop for it first);
and when the speaker names were wrong or you want to redo the layout, you don't have to re-transcribe the whole recording. In multi-part recordings the speakers are numbered separately for each part,
and the header of the output file says so.

### 6. Live voice translation (interpreter mode)

```bash
python scripts/live_bilingual.py --source mic --target zh-TW --speak
python scripts/live_bilingual.py --source system --speak --speak-device "Headphones"
python scripts/live_bilingual.py --list-devices          # first see which playback devices there are
```
It uses **the same connection as feature 3's Fast mode**: `gemini-3.5-live-translate-preview` has
`response_modalities` set to `["AUDIO"]` anyway, so the translated speech was always being sent back; older versions simply threw it away after reading the text.
`--speak` just routes it to the speakers/headphones, and **costs not a penny more** (the speech is billed when the server generates it).

🔴 **Feedback loop**: `--source system`/`both` captures whatever the **system default playback device** is playing.
If the translation is also sent to that device, it is instantly recorded back in, translated again and played again, snowballing into a mess and burning money all the while.
So with these two sources you **must** use `--speak-device` to choose a different device (usually headphones);
choosing the default device is blocked outright (exit code 2).
**Adapters that follow the default are blocked too**, such as "Microsoft Sound Mapper" and "Primary Sound Driver":
going by the name alone, they look like a different device, but the sound still goes to the default device.

`--source mic` only warns, it doesn't block: the program can't tell whether the microphone picks up the speakers, so wear headphones yourself.
If it does, the model keeps translating its own voice over and over without stopping, and you are charged the whole time (seen in real use on 2026-09-28 and reproduced with the real Google service).
`--source file` doesn't have this problem.

Other behaviour: the playback queue holds at most 6 seconds, and when it overflows it **drops the oldest audio** (better to lose half a sentence than let your ears fall further and further behind).
At the end it reports how many seconds were **sent to the playback device** (not "how many seconds were heard": being written to the device doesn't mean there was any sound;
see 6.2 in `references/gemini-speech-guide.md`) and how many seconds were skipped.
If the playback device can't be opened, it only warns, and the captions keep running.

---


## Cost

Measured: audio = **25 tokens/second**, so a one-hour meeting is about 90,000 tokens.

Official unit prices are from ai.google.dev/gemini-api/docs/pricing (checked 2026-09-18). NT$ amounts are converted at 1 USD = 32 TWD.
Feature 4, and feature 2's alignment step, were measured on 2026-09-19. The `gemini-3.5-transcribe`/`transcribe-live` API does not report output tokens, so that part of the table is Google's official estimate.

| Feature | Model | Input | Output | 1 hour |
|---|---|---|---|---|
| 1 Live captions | `gemini-3.5-transcribe-live` | $3.50/1M ($0.005/min) | $21.00/1M ($0.004/min · text) | US$0.54 (NT$17) |
| 2 Transcript (**two passes**) | `gemini-3.5-transcribe` + `3.5-flash` (alignment) | $2.00/1M ($0.003/min) + $1.50/1M | $12.00/1M ($0.002/min · text) + $9.00/1M | ~US$0.62 (NT$20) |
| 3 Bilingual captions · **Accurate** | `transcribe-live` + `3.5-flash-lite` | +$0.30/1M | +$2.50/1M | ~US$0.57 (NT$18) |
| 3 Bilingual captions · **Fast** | `gemini-3.5-live-translate-preview` | $3.50/1M ($0.0053/min) | **$21.00/1M ($0.0315/min · audio)** | **US$2.21 (NT$71)** |
| 4 Transcript to bilingual | `gemini-3.5-flash` | $1.50/1M | $9.00/1M (including thinking) | ~US$0.51 (NT$16) |
| 5 Rebuild a transcript | no model call | — | — | **0** |
| 6 Live voice translation | `gemini-3.5-live-translate-preview` | same as 3 Fast | same as 3 Fast | **US$2.21 (NT$71)** |

🔴 **What makes it expensive is whether the output is text or audio, not the model name.** Feature 1 and feature 3 Fast both have an output price of
$21.00/1M, but the first outputs text ($0.004/min) and the second outputs audio ($0.0315/min): an 8× difference.

> 🔴 **Fast mode costs 4 times as much as Accurate mode.** What decides it is `response_modalities`, not the model name:
> `gemini-3.5-live-translate-preview` is `["AUDIO"]`, so **its output is speech**, and speech output
> costs $0.0315 a minute while text costs only $0.004. Both have the same per-million-token price of $21.00, so the unit price alone won't tell you.
> Accurate mode runs text-only transcription + translation, so it is cheap.
>
> Actual measured values: a full test with a 10-minute audio file on 2026-09-19 gave **25.0 tokens/second** each for input and output (14,975 / 599 seconds),
> US$2.20 an hour (about NT$70.6), matching Google's official 25 tokens/second (an early measurement of only 20 seconds gave 23.8 and has been superseded by this one). Method: add up every single `usage_metadata`.
> 🔴 `usage_metadata` is the usage of **each individual message**, not a running total; reading only the last one undercounts by a factor of 20.
>
> Put the other way round: the speech is generated and billed anyway, so **feature 6 playing it out loud costs nothing extra**.

🔴 **The free tier doesn't charge you, but Google's terms state plainly that free-tier content is used to improve its products,
may be read by human reviewers, and they warn against sending confidential information.**
For meetings involving personnel, budgets or students' personal data, turn on the paid tier before using the tool.

**The quotas can no longer be looked up either** (checked 2026-09-08): the official rate-limits page has removed its per-model
quota table and now tells users to sign in to AI Studio and look for themselves, noting
"Specified rate limits are not guaranteed and actual capacity may vary."
So **do not write free-tier RPM/RPD figures in any document**: they can't be looked up, and they aren't guaranteed.

Other quota behaviour seen in testing:
- RPD resets at **midnight US Pacific time** (3–4 pm in Taiwan)
- Quotas belong to the **project**, not the key; several keys in the same project share one quota
- Preview models (this tool's Fast mode uses `gemini-3.5-live-translate-preview`) have tighter quotas

---

## Files

```
1_Install_Guide_READ_FIRST.md      Where the other person starts when you share the tool
2_Get_API_Key_and_Billing.md       Step-by-step guide: get a Gemini API key + turn on billing
3_Install.bat                      Double-click to install (Setup Wizard window: consent page + progress bar)
4_Start.bat                        Double-click to open the English menu (ordinary users start here)
5_User_Guide.md                    The user manual (plain-language version)
6_Diagnostics.bat                  Double-click for an environment diagnostics report (for remote help; ask the person for a screenshot)
7_Uninstall.bat                    Double-click to uninstall (tick what to remove, item by item)
8_Rescue_Undeletable_Folder.bat    Only when the folder won't delete (prints the owner, permissions and what is using it)
README.md                          This file
requirements.txt                   List of Python packages
assets/
  TIO Voice Genie.ico              Icon for the desktop shortcut
scripts/
  setup_gui.py                     Setup Wizard (consent page, progress bar, desktop shortcut, key)
  uninstall_gui.py                 Uninstall Wizard (tick items, preview commands, progress)
  setup.py                         Text-mode setup (fallback when there is no tkinter)
  rescue.ps1                       Diagnostic script called by 8_Rescue_Undeletable_Folder.bat
  menu.py                          The English menu itself (called by 4_Start.bat)
  live_caption.py                  Live meeting captions
  transcribe_meeting.py            Recording (audio or video) → Traditional Chinese transcript (with automatic splitting and fault tolerance)
  live_bilingual.py                Live bilingual captions · Fast mode (translates as it listens)
  live_bilingual_hq.py             Live bilingual captions · Accurate mode (waits for whole sentences, normal word order)
  translate_transcript.py          Transcript/subtitles → bilingual document
  json_to_md.py                    Transcript .json → .md (purely local; rescues interrupted transcriptions / renames speakers)
  _winpath.py                      Desktop path and shortcut creation (finds the desktop even when OneDrive redirects it)
  _ui.py                           Shared window layout (scrollable; buttons never fall off the screen)
  _live.py                         Reconnect back-off, dropped-audio detection, SentenceGate sentence splitter (shared by three scripts)
  _audioroute.py                   Feature 6's two routes: switch/restore the system default playback device
  _apikey.py                       API key: read, masked display, connection check, remember/clear
  _selfcheck.py                    Package check for 6_Diagnostics.bat (a missing package doesn't crash the whole check)
  _blockhint.py                    Three-way ImportError classification: blocked / not installed / broken (shared by four places, deliberately no dependencies)
references/
  gemini-speech-guide.md           🔴 Tool handbook: pitfalls, compatibility matrix, parameter shapes, costs
data/
  meeting_16k_mono.wav             47-second test recording of a two-person meeting in Chinese
```

---

## Licence and author

| | |
|---|---|
| **Name** | TIO Voice Genie |
| **Developer** | CY KUO |
| **Licence** | MIT License — full text in [`LICENSE`](LICENSE) |

The MIT License means anyone may freely use, modify and distribute this tool (including for commercial purposes);
the only condition is that the copyright notice and licence text are kept when it is distributed. This software comes with no warranty of any kind.

> The transcripts, captions and bilingual documents you produce with this tool are **your own data**, and have nothing to do with this licence.
> The speech recognition service is provided by the Google Gemini API. Its costs and terms of use follow Google's rules,
> and are separate from this tool's licence.

### Terms of use and disclaimer

1. This tool is developed independently by CY KUO as an individual and provided free of charge under the MIT License. It does not represent any institution or organisation. The full licence is in [`LICENSE`](LICENSE).
2. Speech recognition and translation are produced by Google Gemini and may mishear, miss words or mistranslate. Transcripts are drafts; review them before using them as official records.
3. When you use the tool, audio is sent to Google's servers for processing (these may be outside your country), and the data is handled under Google's terms of service. For meetings involving personal or confidential information, turn on the paid tier first.
4. Usage fees are calculated by Google based on usage and charged to your own Google account; this tool does not handle any payments. We recommend setting a monthly spend cap in Google AI Studio.
5. Before recording or transcribing, make sure you comply with the applicable laws and your organisation's rules, and tell the participants in advance.
6. The developer provides this tool under the MIT License without any warranty. Use it at your own discretion and risk; the developer is not liable for any damages.
7. Google, Gemini, Windows, Teams and other names are trademarks of their respective owners. This tool is not affiliated with, sponsored by or endorsed by these companies.
