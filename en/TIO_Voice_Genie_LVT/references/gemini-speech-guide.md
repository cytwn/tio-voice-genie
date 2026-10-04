# TIO Voice Genie handbook (measured)

> Created 2026-09-03. **Every "measured" number in this file was measured on a real PC with real API calls**,
> not copied from the official docs and not guessed. Where the official docs and our measurements disagree, this file goes with the measurements and says so.
> Read this before you start; do not call the API from memory.

---

## 0. One-minute summary

| What you want to do | Which model | How to call it |
|---|---|---|
| Meeting recording → transcript | `gemini-3.5-transcribe` | `generate_content` or `interactions.create` |
| Live captions during a meeting | `gemini-3.5-transcribe-live` | Live API (websocket) |
| Voice assistant (listens, looks things up, speaks) | `gemini-3.1-flash-live-preview` | Live API (websocket) |
| Live interpretation captions | `gemini-3.5-live-translate-preview` | Live API (websocket) |

🔴 **Do not use `gemini-2.5-flash-native-audio-*` for a Chinese voice assistant**: in our tests it rejects `cmn-TW` outright
(websocket close code 1007 "Unsupported language code").

---

## 1. 🔴 The most important rule: the Traditional Chinese trap

**Measured rule (the `generate_content` and `interactions` paths behave the same):**

> As soon as you turn on `diarization` (speaker separation) **or** `word_timestamp` (word-level timestamps),
> the model **ignores the `cmn-Hant-TW` language code and outputs Simplified Chinese**.
> Only with both turned off does `cmn-Hant-TW` take effect and give Traditional Chinese.

This is not a configuration mistake; it is how the model behaves. The official language table **has no Taiwan Traditional Chinese option at all**
(only `cmn-Hans-CN` Simplified and `yue-Hant-HK` Cantonese), yet `cmn-Hant-TW` **does work when you actually pass it in**;
it is just overridden by diarization / word_timestamp.

### Full compatibility matrix (all 24 combinations tested)

| mode | diarization | word_timestamp | custom_vocabulary | Result |
|---|---|---|---|---|
| SMART | ✗ | ✗ | ✓ | ✅ **Traditional**, filler words removed, automatic paragraphs ← best single pass |
| VERBATIM | ✗ | ✗ | ✓ | ✅ Traditional, word for word |
| not set | ✗ | ✗ | ✓ | ✅ Traditional |
| any | ✓ | — | ✗ | ❌ Simplified, but with speaker labels |
| any | — | ✓ | ✗ | ❌ Simplified, but with word-level timestamps |
| SMART | ✓ | — | — | 🚫 400 `SMART is incompatible with diarization` |
| SMART | — | ✓ | — | 🚫 400 `SMART is incompatible with word timestamps` |
| — | ✓ | — | ✓ | 🚫 400 `custom_vocabulary is incompatible with diarization` |
| — | — | ✓ | ✓ | 🚫 400 `custom_vocabulary is incompatible with word timestamps` |

Other measured limits:
- `system_instruction` is **not supported at all** by `gemini-3.5-transcribe` → 400 `Developer instruction is not enabled for this model`.
- Asking for "please output Traditional Chinese" in a plain-text prompt **does not work**; the output is still Simplified.
- `adaptation_phrases` has the same restrictions as `custom_vocabulary` (the error messages all say custom_vocabulary).

### The fix: two passes + alignment

What `scripts/transcribe_meeting.py` does:

1. Pass 1: `VERBATIM + diarization + word_timestamp` → gets the speakers and the timeline (Simplified; used only as a skeleton)
2. Pass 2: `SMART + custom_vocabulary + language_codes=["cmn-Hant-TW", "en-US"]` → gets clean Traditional Chinese body text (**produced by the model itself, not a translation**)
   - `en-US` was added in V1.22: English speech in a Chinese meeting used to come out of neither pass; with it, the English comes back and the body text is still Traditional Chinese. The cost: the Chinese is no longer word-for-word identical (about 98.4% the same on an A/B run of the same recording; the differences go both ways)
3. The program splits the pass 2 text into numbered short sentences; `gemini-3.5-flash` **only answers which sentence each paragraph starts at**, and the program cuts the text out unchanged
   - 🔴 The old approach had the model retype the whole body text paragraph by paragraph: when the two passes did not quite match, thinking used up the whole 65,536 budget → the JSON was cut off → zero output for the whole file (measured 2026-09-11: 62,911 thinking tokens); turning thinking down made it add about 20% extra text of its own
   - The new approach outputs only numbers: it cannot change any wording, cannot mix in the Simplified skeleton, and is never cut off however long the text is; if the answer is bad, or the alignment call itself fails (the server stays busy until the retries run out, 400, 429, network down), the break points are estimated in proportion to character counts, and the text is still complete

4. **Re-transcribe (step 4, added 2026-09-20)**: using the pass 1 skeleton as a reference, find speech that is missing from the body text and cut that short stretch out of the original audio
   (with an extra 0.25 s on each side), run pass 2 on it again on its own, put the result back in place and mark it [re-transcribed] in the transcript
   - It catches **two kinds** (`_lost_segments`): `none` = the whole segment matches nothing in the body text (the recovered text is **inserted** as a new paragraph);
     `part` = it matches, but has far fewer characters than the skeleton (the demo file's "10月31號嗎？" ("31 October?") is this kind; the recovered text **replaces** that paragraph's text)
   - 🔴 Root cause: **when `SMART` + `cmn-Hant-TW` + `custom_vocabulary` are used together, pass 2 silently tidies away whole sentences**. The bundled demo file (9 sentences) gave only 6 sentences 7 times in a row, with no warning at all in the file header. Item-by-item experiments on a desktop PC (2 runs per setting, consistent results): removing the proper nouns, keeping only one term, giving no language code, switching to `VERBATIM`, swapping in unrelated terms: with each of these five changes all 9 sentences were there; pass 1 heard all 9 sentences every time; the three dropped stretches, cut out and transcribed on their own (same settings), could all be transcribed as well. **Changing the settings only swaps in another combination that can trigger it; it is not a cure.** (These experiments were done before V1.22, when pass 2 was given only `cmn-Hant-TW`. Since V1.22 the language codes are `["cmn-Hant-TW", "en-US"]`, and the item-by-item experiments have not been repeated with the new setting. With either setting, step 4 uses the skeleton to look for dropped speech, and anything it cannot recover is listed in the file header.)
   - The gap is only 8–9 seconds, so none of the existing checks catch it, and the old version still showed ✅: end-of-part coverage `COVER_GAP` 30 seconds,
     a whole stretch mid-part with no sentences `HOLE_GAP` 180 seconds, body text far longer than the skeleton (`PASS_RATIO` 4 times **and** `PASS_SURPLUS` 2,000 characters more),
     body text repeating itself (`LOOP_RATIO` 10%, `LOOP_CHARS` 500 characters)
   - Re-transcribe calls are **not retried**: on server busy (503), an unstable network, or a quota or key problem, the remaining re-transcriptions are stopped and this is reported truthfully in the file header. Re-transcription is only an add-on; it is not worth holding up a part's results, already paid for but not yet saved, for another 35 minutes
   - A recovered paragraph is **put back at its position in the skeleton**; do not re-sort by `start`: in long recordings the skeleton's timestamps are not guaranteed to be monotonic (measured: "row 0 at 1:40:45, the next 104 rows starting from 1:25:33"), and sorting moves the opening remarks to the end of the transcript
   - Spots that cannot be recovered (empty even when transcribed on their own, cannot be matched, the call failed, server busy, over the limit of 20 per part) are listed one by one in the file header, **each with its own reason**; anything that was never tried must not be reported as "re-transcribing it on its own did not bring it back either"

> Why not use a Simplified-to-Traditional converter such as OpenCC? Because pass 2 gets the model's native Traditional Chinese output,
> so the wording (計畫 rather than 計劃 for "plan", 影片 rather than 視頻 for "video") is Taiwanese to begin with, which is more accurate than converting characters.
> And `custom_vocabulary` also **fixes homophone errors along the way**: in our tests it corrected "會計師" ("accountant") back to "會計室" ("Accounting Office"),
> and "計劃" back to "計畫" (two spellings of "plan").

---

## 2. Two API paths (completely different shapes; do not copy between them)

### A. `generate_content` (native Python SDK types; recommended)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
part = types.Part.from_bytes(data=open("a.wav","rb").read(), mime_type="audio/wav")

r = client.models.generate_content(
    model="gemini-3.5-transcribe", contents=[part],
    config=types.GenerateContentConfig(
        audio_transcription_config=types.AudioTranscriptionConfig(
            mode=types.AudioTranscriptionConfigMode.SMART,   # upper-case enum
            language_codes=["cmn-Hant-TW"],
            custom_vocabulary=["深耕計畫", "研發處"],   # "Sprout Project", "Research Office"
        )))
```

🔴 **The result is not in `r.text`.** The transcription is in a dedicated `audio_transcription` part:

```python
for p in r.candidates[0].content.parts:
    at = p.audio_transcription        # ← here
    at.text            # the text
    at.speaker_label   # measured: 'spk:0' / 'spk:1' (the official docs say spk_1; do not hard-code it)
    at.words           # [WordInfo(word, start_offset='1.200s', end_offset='1.6s')]
    at.finished        # when streaming, tells interim from final
```
Without diarization the whole result is **one** part; only with it on is the result **split into segments**, each with a `speaker_label`.

### B. `interactions.create` (the path the official docs use)

The parameters are **nested and lower-case**, completely different from A:

```python
client.interactions.create(
    model="gemini-3.5-transcribe",
    input=[{"type": "audio", "uri": f.uri, "mime_type": f.mime_type}],
    generation_config={"transcription_config": {
        "language_codes": ["cmn-Hant-TW"],
        "mode": {"type": "verbatim",            # or simply the string "smart"
                 "diarization_mode": "speaker",
                 "timestamp_granularities": ["word"]},
        "custom_vocabulary": ["深耕計畫"],
    }})
```
Response: `it.output_text` is the full text; `it.steps[0]["content"][0]["annotations"]` holds the word-by-word entries
`{text, speaker, start_offset, end_offset, start_index, end_index}`.

> Mapping: `SMART`↔`"smart"`, `VERBATIM`↔`{"type":"verbatim"}`,
> `diarization=True`↔`diarization_mode:"speaker"`, `word_timestamp=True`↔`timestamp_granularities:["word"]`.
> **Copying parameter names from one side to the other always fails.**

---

## 3. Live API (live captions / voice assistant)

### Audio format (get it wrong and you get silence or garbage, with no error)
- **Sending**: 16000 Hz, 16-bit, **mono**, raw PCM (**no WAV header**),
  `mime_type="audio/pcm;rate=16000"`
- **Receiving**: 24000 Hz, 16-bit, mono
- Send with `session.send_realtime_input(audio=types.Blob(...))`; at the end send `audio_stream_end=True`

### The two kinds of live caption message (under `msg.server_content`)
| Field | Meaning | Measured delay |
|---|---|---|
| `interim_input_transcription` | Interim captions: grow word by word and keep being rewritten | about **1 second** |
| `input_transcription` | Final text; will not change again | **only arrives when a pause in speech is detected**, not at a fixed rhythm |

Measured: a 47.5-second audio file (with pauses between sentences) → 95 interim messages, 3 final.

🔴 **Do not use `input_transcription` to decide when text is final.** It fires only when "the speaker stops",
not every ten-odd seconds. For content that runs without a break, such as talks, videos and online meetings, we measured **only 1 message in 7 minutes**,
and the timestamp becomes "when it was received" instead of "when it was said" (7 minutes of speech all stamped 01:08).
The right way is to cut sentences yourself from the interim text at punctuation (`SentenceGate`; see the section '"Fast vs accurate" in live translation: where to add the delay' below).
`live_caption.py` and `live_bilingual_hq.py` both work this way now.

🔴 **In Live mode `diarization=True` has no effect**: in our tests `speaker_label` was always `None`.
Live captions **cannot tell speakers apart**; that can only be filled in afterwards through the file transcription path.

🔴 **In Live mode, if `mode` is not set, the output is always Simplified.** You must explicitly set
`mode=SMART` + `language_codes=["cmn-Hant-TW"]`.

### Voice assistant settings
```python
cfg = types.LiveConnectConfig(
    response_modalities=["AUDIO"],          # only one value allowed; two values give 1007
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")),
        language_code="cmn-TW"),            # ← native-audio models reject this
    system_instruction="...",
    tools=[...],
    input_audio_transcription=types.AudioTranscriptionConfig(),   # pass an object, not True
    output_audio_transcription=types.AudioTranscriptionConfig(),
    session_resumption=types.SessionResumptionConfig(),
)
```
Voices that worked in our tests (`gemini-3.1-flash-live-preview` + `cmn-TW`):
Puck / Charon / Kore / Aoede all give clean Traditional Chinese. **Charon has the cleanest sentence breaks.**

### Tool calls (the core of a voice assistant)
```python
async for msg in session.receive():
    if msg.tool_call:
        for fc in msg.tool_call.function_calls:
            result = MY_FUNCS[fc.name](**(fc.args or {}))
            await session.send_tool_response(function_responses=[
                types.FunctionResponse(id=fc.id, name=fc.name, response=result)])
```
🔴 **Tool names cannot be in Chinese**: `Invalid function name. Must start with a letter` (1007 disconnect).
Use English function names; the `description` and the parameter descriptions can be in Chinese.

### Live bilingual captions (source + translation together)

Use `gemini-3.5-live-translate-preview`. It was built for **simultaneous interpretation**,
so a single connection returns two kinds of text at once; that is where the bilingual captions come from:

| Field | Content |
|---|---|
| `input_transcription` | What it **hears** (the source, e.g. English) |
| `output_transcription` | What it **translates it into** (the translation, e.g. Chinese) |

```python
cfg = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    translation_config=types.TranslationConfig(
        target_language_code="zh-TW",       # ← see the red note below
        echo_target_language=False),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)
```

🔴 **This model's language codes are not interchangeable with the transcription model's** (measured):

| target_language_code | Result |
|---|---|
| `zh-TW` | ✅ **Traditional + Taiwanese wording** ("大家早安" rather than "大家早上好"; both mean "good morning, everyone") ← use this |
| `zh` | ❌ Simplified |
| `cmn-Hant-TW` | 🚫 **1007 disconnect** (the transcription model accepts this; the translation model does not) |

🔴 **`echo_target_language` does not mean "return the source text"**: it controls "whether to generate **audio** for the target language"
(that is, the simultaneous interpreter's voice). Bilingual **text** captions come from the two transcription fields above and have nothing to do with it.

🔴 **This model occasionally returns 1007 "Request contains an invalid argument", and it has nothing to do with the parameters.**
Measured with the same settings: failed the first time, succeeded the second. **You must write automatic reconnection**,
otherwise you will mistake it for a parameter error (I made that mistake twice).
Note also: a successful connection does not mean it works; **this error is only raised when you send audio**, so testing only the connect step will not reveal it.

🔴 **Traditional characters ≠ Taiwanese wording.** In our tests the translations contained Mainland usages such as 計劃, 項目 and 報銷 ("plan", "project", "reimbursement"): the characters were Traditional but the words were wrong.
`live_bilingual.py` has a `TW_TERMS` table for post-processing, but it **only holds words that cannot be misread**
(視頻→影片 "video", 軟件→軟體 "software", 網絡→網路 "network", 信息→資訊 "information", 報銷→核銷 "reimbursement"…).
`項目`, `計劃`, `程序`, `質量` and `登錄` ("project/item", "plan", "program/procedure", "quality/mass", "log in/register") are **never replaced as strings**; they are left to the prompt. For the reason, see the collateral-damage case in the next section.

Delay: about 1–2 seconds each for the source and the translation, and **the two are not in sync** (the translation is often 1 second late or 1 second early),
so when saving, pair them by nearest time; do not assume they alternate one for one.
The model sends only one or two words at a time; you have to collect them into sentences yourself (see the `Buffer` class) for them to look like captions.


### "Fast vs accurate" in live translation: where to add the delay

The user asked: could the live captions be delayed by 3–4 seconds, so that they are shown only once the word order is complete?
**Answer: delaying the "display" does not help; what needs delaying is the "translation".**

`gemini-3.5-live-translate-preview` translates while it listens, so the text is fixed the moment it is produced
("增加了國際合作率 15%今年", word for word "increased international cooperation rate 15% this year"). Showing it later just means seeing the same bad translation later.

The right way (`scripts/live_bilingual_hq.py`):
1. Use `gemini-3.5-transcribe-live` only to get the **source text** (good quality)
2. Decide yourself when a sentence is final → `SentenceGate` (lives in `scripts/_live.py`, the only copy in the whole project)
3. Send only whole sentences to `gemini-3.5-flash-lite` for translation

🔴 `SentenceGate` used to exist only in the hq script, and `live_caption.py` had not caught up: same model,
same problem, yet feature 1 still had to wait for the server's final text. It was moved into `_live.py` precisely so that there is never again a second copy that can drift.

**Rules for deciding that a sentence is final**:
- A. The interim text has end-of-sentence punctuation **and new words have appeared after it** → the model has moved on to the next sentence, so the previous one will not change again
- B. The interim text has not changed for more than `settle` seconds (the speaker paused)
- C. If more than max_chars have built up, cut there first; do not let it drag on forever

🔴 **Do not also feed `input_transcription` (final) to the gate.** It is a different version of the string,
not the same as the interim text, so it is judged a "new paragraph" and the same content is sent again (in our tests: duplicates and text out of order).
Feed it only `interim_input_transcription`.

**Measured translation model delay** (the same English sentence, 4 runs each):

| Model | Average | Success rate |
|---|---|---|
| `gemini-3.5-flash-lite` | **0.73s** | 4/4 |
| `gemini-3.1-flash-lite` | 0.74s | 4/4 |
| `gemini-3.5-flash` | 2.00s (peak 5.3s; can return 503) | 4/4 |
| `gemini-2.5-flash-lite` | — | 404, withdrawn |

→ Use lite: the translation quality is no worse (even more concise). Measured end-to-end delay: **0.80 seconds on average**
(from the sentence becoming final to the translation being printed), plus about **2–3 seconds** waiting for the speaker to finish.

🔴 **`max_output_tokens=400` cuts short sentences off** ("大家早安。" "Good morning, everyone." came out as "大家早。", with 安 missing): do not set it.

🔴 **The Taiwanese wording replacement table must not be greedy.** It used to contain `項目→專案` (Mainland → Taiwanese word for "project"), which wrongly turned
"項目會議", the translation of "research assessment session", into "專案會議" ("project meeting").
Keep only words that cannot mean anything else in Taiwan (視頻/軟件/網絡/屏幕/信息…: "video/software/network/screen/information"),
and leave `項目` ("item/project"), `計劃` (as a verb, "to plan"), `程序` (as in 程序正義, "procedural justice"), `質量` (physics: "mass") and `登錄` (law: "registration")
entirely to the prompt, with no string replacement.

🔴 **When translating into Japanese / English, write the prompt in the target language** (measured 2026-09-11, flash-lite + temperature 0 + MINIMAL;
from 2026-09-19 the translation in feature 3 Accurate mode no longer uses temperature=0 (see §4), so the figures below were measured before that change).
The prompt used to be entirely in Chinese, with only the three characters "日本語" ("Japanese") in Japanese, and the model was pulled along by the prompt's language: in two rounds of experiments translating into Japanese,
15 of 300 sentences (about 5%) came out entirely in Chinese or as a straight copy of the source. A Japanese frame brought this down to about 1%, but it still occasionally copied the Chinese source sentence back,
or even replied with "Chinese source sentence + ---> + Japanese" side by side. So two more checks were added; if one fails, the question is asked once more with an annotated prompt (if the retry is also wrong, the first answer is used):
① the whole sentence is not in the target language (no kana, no Japanese-only characters, at least 2 Han characters)  ② the translation copies a whole stretch of the source (8 identical Han characters in a row).
② was only added during a later review: side-by-side answers contain kana, so ① cannot see them; together, over three rounds of 1753 real translations, the two checks caught 12,
all of them genuine copies or whole sentences in Chinese, with 0 false alarms. Known trade-off: Japanese written only in kanji, with no Japanese-only characters (会議 "meeting", 東京大学 "University of Tokyo"), is taken as Chinese by ①,
at the cost of one extra request. The prompt for translating into zh-TW was not changed at all.
The fourth round called the product's translation function directly and measured the translations finally displayed with methods unrelated to the product (Chinese function words, copying of the source): 284 sentences, 0 with Chinese mixed in,
0 invented; the sentence copied most often (speaker speaking Chinese, translated into Japanese) was run 30 times: 5 times the first answer was a copy, and after the retry all were clean Japanese.

🔴 **For a continuation sentence, send only the one previous sentence as context** (currently applied only to ja / en). A "continuation sentence" = the previous sentence has no end-of-sentence punctuation: usually SentenceGate
cut it by force, though it can also be half a sentence sent while the speaker paused. With the two previous sentences, the model merged content from the earlier one into the translation: for "with experienced
principal investigators.", 7 times out of 8 it added "今年度" (this year), which only the earlier sentence had, and added "導入し、" ("introducing…,") on its own
to force several sentences into one (the old Chinese frame also added "導入" ("introduce") 8/8); the very first version even invented, 8/8, the "15%" that only appeared in the earlier context
(6 times "引き上げる" ("raise"), 2 times "削減" ("cut"): opposite meanings). With only the one previous sentence, all of these were 0/8.
🔴 Both checks look only at the text and **cannot tell whether the content is right**: an error like inventing a number from the earlier context can only be caught by comparing with the source.

🔴 **Do not replace `sys.stdout` at module top level.** `live_bilingual_hq.py` used to do
`sys.stdout = TextIOWrapper(...)` at top level; when it was imported for unit tests,
the old and new wrappers closed each other's underlying buffer → `ValueError: I/O operation on closed file`.
It now replaces it only inside `if __name__ == "__main__":`.


#### 🔴 Interim text "goes back and rewrites": the sentence splitter must not track progress by position in the raw string

On a real run of an 8-minute YouTube video, **38 of 145 sentences (26%) were duplicates**,
and **the English source itself was duplicated** (not a translation problem). Two patterns:

**Pattern 1: the model rewrites words it has already produced.**
```
interim(t1): ...came out of one message. No editing software,
interim(t2): ...came out of one message, no editing software, nothing manual.
                                       ↑ ↑ full stop became a comma, "No" became "no"
```
Using `text.startswith(already_sent_raw_string)` to decide "does it continue" → the match fails
→ misjudged as a new paragraph → cursor reset to zero → **the whole paragraph is sent again**.

**Pattern 2: the interim text jumps back and forth between a long and a short sentence.**
```
interim: <whole opening passage>    → sent
interim: And at                     → prefix does not match → reset
interim: <whole opening passage> And at the end...  → does not match again → the whole opening passage is sent again
```
Measured: the same opening passage appeared three times, at 00:15 / 00:16 / 00:17.

**Two fixes (both are needed; neither works without the other):**

1. **The cursor now counts "normalised characters"**: strip punctuation and spaces and lower-case the text before comparing.
   Rewritten punctuation then cannot hurt it. Whether the text continues is now decided by "common prefix ≥ 75% of the length already sent".
   ⚠️ When it is judged a new paragraph, **the unsent remainder of the old paragraph must be sent first**, otherwise words are lost.
2. **Whole-session de-duplication safety net**: keep the normalised text of everything sent in the session, and check before sending:
   whole sentence already said → drop it; beginning already said → send only the tail that has not been said.
   ⚠️ Only "the leftover scrap after the prefix is cut off" is dropped; normal short sentences (the single word "請", "please") must be kept,
   otherwise de-duplication loses words (my first version did).

#### 🔴 A wording table in the prompt that is too aggressive backfires

The translation prompt used to say "專案(非項目)" ("專案, not 項目": the Taiwanese word for "project"), and the model then translated
`today's session on research assessment` as "研究評鑑的**專案**會議" ("research assessment **project** meeting"):
a session is not a project at all; the prompt dragged it there.
After it was changed to "請用臺灣的中文用語習慣（例如 影片而非視頻…）。用詞要自然，不要硬套。" ("Please follow Taiwanese Chinese usage (e.g. 影片 rather than 視頻 for "video"…). Keep the wording natural; do not force it."),
it was correctly translated as "研究評量說明會" ("research assessment briefing").

> General rule: neither the **string replacement table** nor the **wording table in the prompt** may be greedy.
> List only words whose meaning is fixed and cannot mislead; leave words with several meanings to the model's own judgement.


#### 🔴 The de-duplication safety net deleted real content (round 2, 2026-09-04)

The first version of de-duplication **joined the whole session's normalised text into one big string with no separators**, `self.said`,
then did substring matching with `sn in self.said` / `sn[:k] in self.said`, with a threshold of only **8 normalised characters**.
8 characters of English have no discriminating power at all, so it deleted real content (found by taking an earlier output of the same video as ground truth and comparing word by word):

| Deleted content | Cause of the false match |
|---|---|
| `software.` whole sentence vanished | another sentence 55 seconds earlier contained software (exactly 8 characters) |
| `I'll break down ` cut off | `I'll break down what` had been said 38 seconds earlier |
| `to use.` whole sentence vanished | same kind |

**Fix**:
- Store **the last 8 outputs, each kept separately** (`deque`), and match on **whole-sentence equality** rather than substrings.
- Prefix trimming compares only with the **previous output** (`sn[:k] == prev[-k:]`), not with the whole session.
- Threshold 8 → **24** normalised characters. The measured duplication pattern was a whole 96-character passage sent again, far above the threshold.

#### 🔴🔴 Methodology lesson: do not use "output that has already been filtered" to test "whether the filter deleted anything by mistake"

The first time I verified it, I re-ran the de-duplication rules on **the caption file it had produced**, got "0 false matches" and declared it fine.
**That is circular reasoning**: the deleted content is not in that file at all, so of course the test cannot find it.

The right way (the one the agent used): take **another, independent output from the same input** as ground truth
(here there happened to be `1.md`, produced by the old version 12 minutes earlier) and do a word-by-word diff.
The differences are what was deleted. All three losses showed up this way, and they can be reproduced bit for bit.

> General rule: to verify "whether a step lost anything", always compare with **a version that did not go through that step**;
> checking only its own output is not enough.

#### max_chars: decide it from real data, not by feel

From the reference file we rebuilt **266 complete sentences**: median 62, mean 69, **longest 218** characters.

| Threshold | Sentences that would be cut by force |
|---|---|
| 140 (original value) | **30 sentences (11%)** ← matches the measured 5/44 exactly |
| 180 | 6 sentences (2%) |
| 200 | 3 sentences (1%) |
| **240** | **0 sentences** ✅ |

Changed to 240, and when a cut is forced it **looks for a clause boundary first** (comma/semicolon/colon), falling back to a space only if there is none.
Also, a "this is a fragment cut by force" flag is passed to the translation model, so that it does not translate `month.` on its own as "個月" ("month(s)"),
or `five-year projections.` as "五年預測" ("five-year forecast").

### Interruptions (barge-in)
When `server_content.interrupted == True`, **you must clear the queue of audio not yet played yourself**,
otherwise the user has already cut in while the speakers are still saying the previous sentence.

---


## 🔴 Appendix: recording length limits for file transcription (there are two, and the stricter one applies)

**This section was corrected on 2026-09-16**: it used to say only "65.4 minutes", worked out by dividing `inputTokenLimit = 98,304`
by the measured 25.04 tokens/second. The arithmetic is right, but **that is not the only limit**, and not the strictest one.

| Situation | Limit | Source | What happens if you go over |
|---|---|---|---|
| **diarization or word_timestamp on** | **30 min** | stated in the official Limitations | 🔴 **no error**, and the whole file is billed; the official docs do not say what happens to the part beyond the limit, and our tests have not confirmed a single case of truncation (see the correction below) |
| neither of those two features on | **1 hour** | stated in the official Limitations | 400, visible |
| (early estimate) | ~~65.4 min~~ | 98,304 ÷ 25.04 tok/s | an overestimate; in our tests 60.6 min was already rejected |

Official wording (`https://ai.google.dev/gemini-api/docs/transcribe.md.txt`, taken from the raw markdown, not a rewritten version):

> **Audio duration:** Standard unary requests support audio files up to 1 hour.
> Audio processing is limited to 30 minutes when features like speaker diarization
> or word-level timestamps are enabled.

The token conversion is still useful (for estimating cost), but **do not use it to judge the length limit**:

| Recording length | tokens | Accepted? |
|---|---|---|
| 30 min | 45,072 | ✅ the real limit with speaker separation on |
| 60 min | 90,144 | ✅ the officially stated limit (speaker separation off) |
| 65 min | 97,656 | ❌ enough tokens, but over the official 1 hour |
| 70 min | 105,168 | ❌ over both limits |
| 120 min | 180,288 | ❌ |

If you go over, you get:
```
400 INVALID_ARGUMENT
The input token count exceeds the maximum number of tokens allowed 98304.
```
**There is no other sign, and no automatic fallback.** University meetings often run to two hours, so you are sure to hit this.

`transcribe_meeting.py` has automatic splitting built in (`MAX_CHUNK_SEC = 28*60`):

1. `ffmpeg silencedetect` finds the silent points
2. Cut at the silence closest to the target cut point **within the 5 minutes before it**, so as not to cut through a sentence (cut by force only if none is found)
3. Each part runs its own two passes + alignment, and its timeline is then shifted by the part's start offset

🔴 **What really limits it is not this token limit but another item in the official Limitations**:
"Audio processing is limited to 30 minutes when features like speaker diarization or
word-level timestamps are enabled." pass1 turns both on, so it is subject to this 30-minute limit.
Going over gives **no error, and the whole file is billed**; the official docs do not say what happens to the part beyond the limit, and our own tests have not confirmed a single case of truncation either.

🔴 **Correction 2026-09-16**: this used to say "checked a real 2:56:47 meeting: with 45-minute parts, each of the first three parts broke off
at minute 30, covering only 73.8%". **That conclusion was wrong and has been overturned.** Those numbers were calculated from the old version's timestamps,
and the old version's timestamps were themselves broken (10 giant sentences of over 1,000 characters, the longest 6,771 characters, with the same passage repeated at the start and the end):
the content was in fact inside the giant sentences, just with the wrong times. Only by cutting those time ranges out and transcribing them on their own did we confirm that the real faults were two others
(a whole stretch mid-part not recognised, and the body text repeating in a loop): the looping **happened with both** 45-minute and 28-minute parts,
and holes mid-part have so far only been seen in 28-minute parts, so part length is not the root cause.

🔴 **Speaker numbers cannot be kept consistent across parts**: each part is recognised separately, so `spk:0` in part 1 is not guaranteed to be `spk:0` in part 2.
The output file header now carries a warning. Keeping them consistent across parts would mean matching times or voiceprints yourself; this has not been done.

> I measured `inputTokenLimit: 98304` with ListModels on day one, but did not wire it into the tool,
> and it only blew up when the user ran a real meeting recording. **Wire a measured limit into the program there and then; do not just write it in your notes.**

---


### 🔴 WordInfo's start_offset / end_offset can be None

Short audio files do not show it, but long recordings (measured: 2 hours 57 minutes) do:
```
AttributeError: 'NoneType' object has no attribute 'rstrip'
  float(w[-1].end_offset.rstrip("s"))
```
Do not assume every word has a start and end time. `transcribe_meeting.py` now uses `_off()` / `_span()`:
they skip words without timestamps one by one, return `None` if none have them, and then fall back to "right after the previous paragraph".

### 🔴 Long jobs must ensure "a failed part does not affect the whole job"

A three-hour recording is split into 4 parts; part 1 finishes (money already spent), part 2 crashes → the old version threw out the whole traceback,
and **all the results already paid for were lost**. To the user, that is "I paid and got nothing".

The fix:
- Each part is wrapped in `try/except`; a failure is only recorded and does not stop the job, and the other parts carry on.
- Each time a **whole part** succeeds, the accumulated results are written to `*.partial.json`, so if the job dies partway, the parts already fully finished are kept.
  🔴 In practice, this mostly saves something only for recordings longer than `MAX_CHUNK_SEC` (28 minutes by default) that are split into several parts: up to 28 minutes it is
  one single part, and the file is first written only after pass 1 + pass 2 + alignment **+ re-transcription** (step 4, added 2026-09-20, see §1) are all done,
  so if it dies **in the middle of recognition** there is nothing, and the whole file has to be transcribed again. Re-transcription comes before the file is written, so it also counts towards this window;
  that is exactly why re-transcription "does not retry, and stops when the server is busy" (retrying at every spot could add up to 35 minutes of waiting per part).
  But if something goes wrong only after that part has fully finished (the file is locked while `.md` is being written, the disk is full, the window is closed at that moment), a single part leaves this file too;
  so neither the documents nor the messages may state as an absolute that "a single part never leaves one" (scenario G, found in testing in the fourth review round on 2026-09-15).
  The interruption message (`transcribe_meeting._interrupted()`) therefore has to depend on whether this file actually exists,
  and must not be written as if it were always true (2026-09-15 R3-4: the same point was scattered across four places: the program, the menu, the README and the handbook).
- The output file header clearly lists **which time ranges are missing**, instead of quietly producing a transcript that looks complete.
- Only `exit(1)` when every part has failed.

> General rule: whenever a single job may run for tens of minutes and costs money, you cannot use "raise all the way up" error handling.

---

## 4. Cost (measured + official pricing)

Measured: **audio = 25.04 tokens/second** (47.5 seconds → 1189 audio tokens).
→ a 1-hour meeting ≈ **90,100 tokens**.

| Model | Input (audio) | Output (text) | Input cost for 1 hour |
|---|---|---|---|
| `gemini-3.5-transcribe` | $2.00 / 1M | $12.00 / 1M | **US$0.18** |
| `gemini-3.5-transcribe-live` | $3.50 / 1M | $21.00 / 1M | **US$0.32** |

- A one-hour meeting with the two-pass design ≈ input $0.36 + output about $0.25 ≈ **US$0.6 (about NT$20)**
- One hour of live captions ≈ **US$0.5 (about NT$17)**
- Measured full two-pass transcription of 47.5 seconds: 2,380 audio tokens + 929 alignment tokens = **US$0.0048**
- 🔴 The estimates above **do not include re-transcription** (step 4, added 2026-09-20): each spot recovered is one extra `gemini-3.5-transcribe` call,
  up to 20 per part, and the clips cut out are usually only a few seconds long (measured: the demo file recovered 3 spots, adding 564 audio tokens to the whole file ≈ US$0.001).
  A normal recording recovers a handful of spots (single figures), adding less than 1%; it only rises noticeably when the model drops many sentences, and the program counts it in the audio tokens shown on screen.
- Alignment in feature 2 (`gemini-3.5-flash`, thinking LOW / MINIMAL): measured 1,036 tokens for a 2-minute recording → about 30,000 tokens per hour, about US$0.05.
  🔴 It shoots up when the pass 2 text gets stuck in a loop (2026-09-19, a 63-minute synthetic recording: 147,000 alignment tokens, US$0.22).
- 🔴 `gemini-3.5-transcribe` responses **report only input tokens**; `gemini-3.5-transcribe-live` reports **no** usage_metadata **at all**
  (measured 2026-09-19). The output cost of these two models can only be estimated with the official "175 text tokens per minute"; the bill is what counts.
- Feature 4 (`translate_transcript.py`, `gemini-3.5-flash`, measured 2026-09-19 with a 60.6-minute transcript):
  in 22,531 / out 14,786 / **thoughts 37,711** → US$0.51 (NT$16); thinking tokens were about 2.5 times the translation.
  A comparison with thinking_level=low was also run: thoughts 0, US$0.18 (NT$6), but in a blind review (8 reviewers × 175 paragraphs) minor errors went 105 → 260,
  and inconsistent proper nouns 7 → 10 (errors that changed the meaning: 0 on both sides) → the user ruled **not to adopt it**; quality comes first.
- 🔴 temperature (2026-09-19 A/B; the official 3.5 guide recommends **not setting it** for 3.x models and using the default 1.0):
  temperature=0 **has been removed** from feature 2's alignment and from feature 3's Accurate mode translation (alignment: 6 runs gave identical results; translation: a blind review of 34 sentences found no difference in quality, and serious errors went 2→0);
  **feature 4 deliberately keeps temperature=0**: without it the sentences read more naturally, but each batch of 25 paragraphs is translated separately and each batch picks different translations for names,
  so inconsistent proper nouns went 7 → 14 and terminology errors 9 → 43, which is not acceptable in a formal document for foreign guests.

### 🔴 4.1 The simultaneous interpretation model costs 4 times as much (first test 2026-09-18, full measurement 2026-09-19)

`gemini-3.5-live-translate-preview` (the **Fast mode** of the bilingual captions, and the voice translation in feature 6)
**cannot be estimated from the table above**. Its `response_modalities` is `["AUDIO"]`: **the output is speech**,
and speech output is billed **by audio length** (25 tokens per second, as many as the input). Feature 1's output price is also $21.00/1M,
but it outputs text, only about $0.004 a minute; this model outputs speech at $0.0315 a minute: **the cost is in the amount of output, not the unit price**.

| | Official unit price | Measured usage (09-19, 10 minutes) | 1 hour |
|---|---|---|---|
| Input (audio) | $3.50 / 1M | 25.0 tokens/s (14,975 ÷ 599 s) | US$0.315 |
| Output (**audio**) | $21.00 / 1M | 25.0 tokens/s (output = input) | US$1.89 |
| Total | | | **US$2.20 (about NT$70.6)** |

The official pricing page also notes "at 25 tokens/second, about $0.0368/minute" = US$2.21/hour, which matches our measurement.
(The first test on 09-18 measured only 20 seconds and got 23.8 tokens/second, US$2.1 (about NT$66); it has been superseded by this one.)

🔴 **Measurement trap**: the Live API's `usage_metadata` is the usage of **each individual message**, not a running total.
The first time we measured, we read only the last one, got 25 tokens and converted that into "NT$3 per hour": **an undercount by a factor of 20**.
You must add up every message (the measurement script on the development side does exactly this).

🔴 The good news, the other way round: speech is billed the moment it is generated on the server, so **playing it (`--speak`)
costs nothing extra**. The old version received it and threw it away, which is like buying something and not using it.

### 🔴 4.2 Chinese target language codes: zh-TW and zh-Hant are equivalent (2026-09-18, 3 tests each)

The official language table gives Traditional Chinese as `zh-Hant`; the program uses `zh-TW`. Measured with the same 49-second English meeting script:

| Target language code | Connection | Script | Opening sentence |
|---|---|---|---|
| `zh-TW` | ✅ 3/3 | Traditional (0 Simplified characters) | 大家早安 ("good morning, everyone") |
| `zh-Hant` | ✅ 3/3 | Traditional (0 Simplified characters) | 大家早安 ("good morning, everyone") |
| `zh-Hant-TW` | ❌ 1007 | — | — |
| `cmn-Hant-TW` | ❌ 1007 | — | — |
| `zh` (control) | ✅ | **Simplified** | 大家早上好 ("good morning, everyone", Mainland wording) |

The differences between the two outputs (e.g. "謝謝您" "thank you" vs "謝謝大家" "thank you, everyone") swapped over between the three runs: that is **sampling noise, not a systematic difference**.
→ **Keep `zh-TW`**: do not change it without a measured benefit; the current `TW_STYLE_INSTRUCTION`
and the after-the-fact replacements were all verified with it. (Results of 3 tests each; the verification script is not included.)

🔴 Note that this is **not the same** as for the transcription model: the transcription model accepts `cmn-Hant-TW`, but this translation model gives 1007 if you pass it that.

🔴 The free tier is **really free** (nothing is charged), but see the next section for the price you pay.

---

## 5. 🔴 Data governance: the free tier must not be used to record real university meetings

Official terms, verbatim (ai.google.dev/gemini-api/terms):

- Free tier: "Google uses the content you submit to the Services and any generated responses
  to provide, improve, and develop Google products and services", and
  "**human reviewers may read, annotate, and process your API input and output**",
  with the explicit warning "**Do not submit sensitive, confidential, or personal information to the Unpaid Services**".
- Paid tier: "Google **doesn't use** your prompts ... or responses to improve our products";
  records are kept only for a short time, to detect abuse.

**Conclusion: for meetings involving personnel matters, funding, review comments or students' personal data, you must first enable the paid tier on a Google Cloud billing project
before using it.** The free tier is only suitable for testing with public content or test audio files.

---

## 6. Other pitfalls found in testing

| Symptom | Cause | Fix |
|---|---|---|
| `r.text` is `None`, with a warning about non-text parts | The transcription is in the `audio_transcription` part | Use `candidates[0].content.parts[i].audio_transcription` |
| 1007 `Unsupported language code 'cmn-TW'` | A native-audio model was used | Switch to `gemini-3.1-flash-live-preview` |
| 1007 `Invalid function name` | Tool name in Chinese | Give the function an English name |
| 1007 (when asking for TEXT output) | native-audio models only support `["AUDIO"]` | Switch model, or ask only for AUDIO |
| Chinese input comes out garbled | Windows stdin defaults to CP950 | `sys.stdin.reconfigure(encoding="utf-8")` |
| No log visible when running in the background | Python stdout is fully buffered | `python -u` or `TextIOWrapper(..., line_buffering=True)` |
| Meeting sound is not recorded | Only the microphone was recorded | On Windows, use `pyaudiowpatch`'s WASAPI loopback (see below) |
| Stereo Mix records silence | That device is disabled | Do not use it; use WASAPI loopback instead |
| After turning on `--speak`, the translation gets more and more garbled | The translated voice is recorded back through loopback, so the model is translating itself | Play it on a **different** device (see 6.1) |
| `--source mic --speak`: after the speaker stops, the same sentence keeps repeating without stopping | The interpretation comes out of the speakers and the microphone records it back in; the silence gate never sees quiet, so audio keeps being sent and charged (a user ran into it on 2026-09-28; simulated with the real Google service: still repeating after 60 seconds) | Wear headphones and play the interpretation to them; the program can't prevent it, so the menu and the start screen can only warn |
| Interpretation and test sound are silent the whole time, yet at the end the number of seconds sent is still reported (the old version's wording was "played N seconds") | It matched a DirectSound device: PortAudio's DirectSound is silent with blocking writes, and reports no error | Always resolve to MME (see 6.2) |

### 🔴 6.1 The feedback loop when playing the translated voice (2026-09-18)

WASAPI loopback records "whatever the **system default playback device** is playing". If the translated voice is also sent to that device,
it is immediately recorded back, translated again and played again, and every loop burns tokens.
`--source system` / `both` therefore **requires** `--speak-device` to name a different device.

🔴 Matching names is not enough: "Microsoft Sound Mapper - Output" and "Primary Sound Driver" are
**adapters that follow the default**; the names look like other devices, but the sound still goes to the default one.
`_live.is_default_like()` deals with exactly this kind (`_DEFAULT_ALIASES`).

The same physical speaker appears once each under MME / DirectSound / WASAPI (on the test PC, 10 entries were really only 3 devices),
and MME cuts names to 31 characters, so **"is this the same device" comparisons** use the first 25 characters of the name, ignoring case
(`_live.same_device` / `is_default_like`; the menu's list de-duplication does the same).

🔴 But "**which device to open**" must not be looked up by name: that path has to use the audio endpoint ID; see 6.2 below for why.

### 🔴 6.2 DirectSound with blocking writes gives no sound at all, and no error (2026-09-20)

Tested on a laptop: when the interpreter voice in feature 6 was routed to a device whose full name is longer than 31 characters ("1 - KONKA LCDTV (AMD High Definition Audio Device)"),
**the test sound did not play and the interpretation was silent the whole time, yet the screen still printed "about 87 seconds of translated voice played in total"**. Reproduced on two computers, with 5 devices in all.

| Playback method | Result |
|---|---|
| PortAudio 19.7 DirectSound + blocking write (`RawOutputStream.write`) | **No sound at all; no exception, no error code** |
| Same DirectSound device index, using a callback instead (`sd.play`) | Sound |
| MME + blocking write | Sound |
| WASAPI | Will not open (24kHz → `Invalid sample rate`) |

- 🔴 **"Try opening each device" does not catch it**: DirectSound opens and accepts writes, it just makes no sound. The safeguard in 6.1 above is completely useless against this symptom; only actually measuring the loopback shows it.
- 🔴 **A successful write ≠ sound**: `played_bytes` adds up as long as `write()` raises no exception, which is why the screen said "played N seconds". It now says "**sent** about N seconds to the playback device": this number only proves the audio was sent, not that it could be heard.
- **Why it matched DirectSound**: MME cuts device names to 31 characters, so "find the device by its full name" can only match DirectSound or WASAPI (their names are complete). The old version compared "the start of the description" and happened to match MME; it broke once this was changed to full-name matching.

**Fix: always resolve playback to MME, and match by the Windows audio endpoint ID, not by name.**

```python
# winmm: waveOut index w → audio endpoint ID ({0.0.0.00000000}.{guid})
import ctypes
from ctypes import wintypes
winmm = ctypes.WinDLL("winmm")
winmm.waveOutMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
winmm.waveOutMessage.restype = wintypes.UINT
DRV_QUERYFUNCTIONINSTANCEID     = 0x0811
DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0812

def endpoint_id(w):                       # w = waveOut index (0…waveOutGetNumDevs()-1)
    size = wintypes.ULONG(0)
    if winmm.waveOutMessage(ctypes.c_void_p(w), DRV_QUERYFUNCTIONINSTANCEIDSIZE,
                            ctypes.byref(size), None) or not size.value:
        return None                       # only 0 means success (MMSYSERR_NOERROR)
    buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
    if winmm.waveOutMessage(ctypes.c_void_p(w), DRV_QUERYFUNCTIONINSTANCEID,
                            buf, ctypes.c_void_p(size.value)):
        return None
    return buf.value                      # e.g. {0.0.0.00000000}.{921eb87d-…}
```

(For the implementation, see `mme_endpoint_map()` in `scripts/_live.py`; it also compares PortAudio's MME list with winmm's waveOut list name by name, device by device, and throws the whole table away if they do not match.)

- PortAudio's MME playback list order = the "Sound Mapper" first, then `waveOut` 0…n−1; indexes are matched on that basis.
- 🔴 If even one device in the mapping does not match (different count, different name), **the whole table is thrown away and it returns empty**; do not guess. If nothing is found, say so plainly ("Could not find the playback device for this audio endpoint"); **never quietly switch to another device**: two TVs of the same model have identical first 31 characters, so a wrong guess plays to the other TV, or plays back into the device being recorded and causes feedback.
- The device lists (`--list-devices`, feature 6 options 2/3) never list DirectSound either: picking one means silence. Tested on a desktop PC: before the change, that list had 3 DirectSound devices, and a test sound on any of them measured 0.
- The endpoint ID is only used to find the device; **what is shown on screen has to use the full name from the registry separately** (`_audioroute.endpoint_name()`), otherwise the user sees MME's cut-off name.

### Recording what the PC is playing ("computer audio") on Windows (essential for online meetings)
`sounddevice` 0.5.6's `WasapiSettings` **has no** `loopback` parameter, so it cannot do this.
Use `pyaudiowpatch` (a Windows fork of PyAudio) instead:

```python
import pyaudiowpatch as pa
with pa.PyAudio() as p:
    wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
    out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    lb = next(d for d in p.get_loopback_device_info_generator() if out["name"] in d["name"])
    stream = p.open(format=pa.paInt16, channels=lb["maxInputChannels"],
                    rate=int(lb["defaultSampleRate"]), input=True,
                    input_device_index=lb["index"])
```
Tested on a real PC and it works (48000 Hz / 2ch); you have to downsample to 16 kHz mono yourself before sending it to the API.

### asyncio on Windows
The Live API uses websockets. `WindowsSelectorEventLoopPolicy` makes **Ctrl+C take effect only when a timeout is reached**;
the default Proactor loop, on the other hand, can interrupt immediately. Unless you run into a compatibility problem, **do not** change the policy by hand.

---

## 7. Official claims vs measured reality (checked on the day of publication)

| Claim in news / docs | Measured |
|---|---|
| Supports 85 languages | Counting the official table myself = **81 unique BCP-47 codes**; **Taiwan Traditional Chinese is not in the table** (for Chinese there are only `cmn-Hans-CN` Simplified and `yue-Hant-HK` Cantonese), but `cmn-Hant-TW` can be passed in and works in our tests |
| Up to 3 speakers | The official docs say **up to 8**, with a note that "attribution for 3 or more speakers is experimental"; the press release's "3" was most likely a misreading of that note |
| Automatic filler-word removal, smart formatting | ✅ True, but only with `mode=SMART`, and it cannot be combined with speakers/timestamps |
| WER 2.6% / 4.0% | Not found in the official docs; these figures appear only in the press release |
| Model metadata `thinking: true` | The official model card says Thinking "Not supported": the two contradict each other; unresolved |
| The official docs' examples show speaker labels `spk_1` / `spk_2` | In our tests `generate_content` returns **`spk:0` / `spk:1`** (colon, counting from 0). **Do not hard-code string comparisons** |

---

## 8. Versions

- `google-genai` **2.22.0** (released 2026-09-02); `custom_vocabulary` needs ≥2.13.0,
  flat `language_codes` needs ≥2.15.0, the `VERBATIM/SMART` enum needs ≥2.19.0
- `pyaudiowpatch` 0.2.12.8, `sounddevice` 0.5.6, Python 3.13
- Model versions: `gemini-3.5-transcribe` = `3.5-transcribe-08-2026`;
  `gemini-3.5-transcribe-live` = `3.5-transcribe-live-08-2026`
