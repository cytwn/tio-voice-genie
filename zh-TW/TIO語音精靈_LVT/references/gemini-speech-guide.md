# TIO語音精靈 手冊（實測版）

> 建立 2026-09-03。**本檔所有「實測」數字都是在本機用真實 API 呼叫量出來的**，
> 不是抄官方文件、也不是推測。官方文件與實測衝突時，本檔以實測為準並註明。
> 動手前先讀這份，不要憑印象呼叫。

---

## 0. 一分鐘結論

| 你要做的事 | 用哪個模型 | 怎麼呼叫 |
|---|---|---|
| 會議錄音檔 → 逐字稿 | `gemini-3.5-transcribe` | `generate_content` 或 `interactions.create` |
| 會議進行中即時字幕 | `gemini-3.5-transcribe-live` | Live API（websocket） |
| 語音助理（會聽會查會講） | `gemini-3.1-flash-live-preview` | Live API（websocket） |
| 即時口譯字幕 | `gemini-3.5-live-translate-preview` | Live API（websocket） |

🔴 **不要用 `gemini-2.5-flash-native-audio-*` 做中文語音助理**——實測它直接拒絕 `cmn-TW`
（websocket 關閉碼 1007「Unsupported language code」）。

---

## 1. 🔴 最重要的一條：繁體字陷阱

**實測規則（`generate_content` 與 `interactions` 兩條路徑行為一致）：**

> 只要打開 `diarization`（分講者）**或** `word_timestamp`（詞時戳），
> 模型就會**忽略 `cmn-Hant-TW` 語言碼，輸出簡體中文**。
> 兩個都關掉，`cmn-Hant-TW` 才生效、才出繁體。

這不是設定錯誤，是模型行為。官方語言表裡**根本沒有臺灣繁中**這個選項
（只有 `cmn-Hans-CN` 簡體、`yue-Hant-HK` 粵語），但 `cmn-Hant-TW` **實際傳進去有效**——
只是會被 diarization / word_timestamp 蓋掉。

### 完整相容性矩陣（24 組窮舉實測）

| mode | diarization | word_timestamp | custom_vocabulary | 結果 |
|---|---|---|---|---|
| SMART | ✗ | ✗ | ✓ | ✅ **繁體**、去贅字、自動分段 ← 最佳單趟 |
| VERBATIM | ✗ | ✗ | ✓ | ✅ 繁體、逐字照抄 |
| 未設 | ✗ | ✗ | ✓ | ✅ 繁體 |
| 任何 | ✓ | — | ✗ | ❌ 簡體，但有講者標籤 |
| 任何 | — | ✓ | ✗ | ❌ 簡體，但有詞級時間戳 |
| SMART | ✓ | — | — | 🚫 400 `SMART is incompatible with diarization` |
| SMART | — | ✓ | — | 🚫 400 `SMART is incompatible with word timestamps` |
| — | ✓ | — | ✓ | 🚫 400 `custom_vocabulary is incompatible with diarization` |
| — | — | ✓ | ✓ | 🚫 400 `custom_vocabulary is incompatible with word timestamps` |

其他實測限制：
- `system_instruction` 對 `gemini-3.5-transcribe` **完全不支援** → 400 `Developer instruction is not enabled for this model`。
- 用純文字 prompt 要求「請輸出繁體」**無效**，照樣簡體。
- `adaptation_phrases` 與 `custom_vocabulary` 共用同一組限制（錯誤訊息都寫 custom_vocabulary）。

### 解法：兩趟 + 對齊

`scripts/transcribe_meeting.py` 的做法：

1. 第 1 趟 `VERBATIM + diarization + word_timestamp` → 拿講者與時間軸（簡體，只當骨架）
2. 第 2 趟 `SMART + custom_vocabulary + language_codes=["cmn-Hant-TW", "en-US"]` → 拿乾淨繁體正文（**模型自己產的，不是翻譯**）
   - `en-US` 是 V1.22 加的：中文會議裡的英文發言原本兩趟都轉不出來，加了之後英文轉得出來、正文仍是繁體；代價是中文不再一字不變（同一段錄音 A/B 約 98.4% 相同，差異有好有壞）
3. 程式把第 2 趟的正文切成編號小句，`gemini-3.5-flash` **只回答每一段從第幾句開始**，文字由程式原封不動剪下來
   - 🔴 舊做法讓模型逐段重打整份正文：兩趟內容對不太上時，思考會吃光 65,536 的額度 → JSON 被截斷 → 整份零產出（2026-09-11 實測思考 62,911 token）；把思考調低又會自己多加約兩成字
   - 新做法輸出只有數字：不可能改字、不可能混入簡體骨架、再長也不會截斷；答壞了、或對齊這一步的呼叫本身失敗（伺服器忙到重試用完、400、429、網路斷線），就按字數比例估斷點，文字仍完整

4. **補轉（2026-09-20 加的第 4 步）**：拿第 1 趟的骨架當對照，找出正文裡不見的話，把那一小段原音剪出來
   （前後各多 0.25 秒）單獨再跑一次第 2 趟，補回原位並在逐字稿標〔補轉〕
   - 抓**兩種**（`_lost_segments`）：`none`＝整段對不到正文（補回來是**插入**一段新的）；
     `part`＝對到了但字數比骨架少很多（示範檔的「10月31號嗎？」就是這種，補回來是**替換**那一段的 text）
   - 🔴 病根：**`SMART` ＋ `cmn-Hant-TW` ＋ `custom_vocabulary` 三個一起用時，第 2 趟會安靜地整理掉整句**。內附示範檔（9 句）連續 7 次都只出 6 句，檔頭沒有任何警語。桌機逐項實驗（每組 2 次、結果固定）：拿掉專有名詞、只留一個詞、不給語言碼、改 `VERBATIM`、換成不相干的詞——五種改法都 9 句全在；第 1 趟每次都聽到 9 句；丟掉的三段剪出來單獨轉（同樣設定）也都轉得出來。**換設定只是換一個會觸發的組合，不是根治。**（這組實驗是 V1.22 之前、第 2 趟只給 `cmn-Hant-TW` 時做的；V1.22 起語言碼是 `["cmn-Hant-TW", "en-US"]`，新設定下沒有重做逐項實驗。不管哪一種設定，第 4 步都會拿骨架去找丟掉的話，補不回來的照實列進檔頭。）
   - 缺口只有 8～9 秒，既有的檢查一條都碰不到，所以舊版照樣打 ✅：段尾覆蓋 `COVER_GAP` 30 秒、
     段中整片沒句子 `HOLE_GAP` 180 秒、正文遠多於骨架（`PASS_RATIO` 4 倍**而且**多出 `PASS_SURPLUS` 2,000 字）、
     正文自我重複（`LOOP_RATIO` 10%、`LOOP_CHARS` 500 字）
   - 補轉呼叫**不重試**：遇到伺服器忙（503）、網路不穩、額度或金鑰問題就停掉後面的補轉，照實列進檔頭。補轉只是附加功能，不值得為它把一段已經付費、還沒存檔的結果多拖 35 分鐘
   - 補回來的整段**插回骨架的位置**，不可以照 `start` 重新排序：長錄音的骨架時戳不保證單調（實測有「第 0 列 1:40:45、後面 104 列從 1:25:33 開始」），一排序就把開場白搬到逐字稿最後
   - 補不回來的（單獨轉也空、對不起來、呼叫失敗、伺服器忙、超過每段 20 處的上限）逐條列進檔頭，**各自寫明原因**——沒試過的不可以寫成「補轉也沒補回來」

> 為什麼不用 OpenCC 之類的簡轉繁工具？因為第 2 趟拿到的是模型原生的繁體輸出，
> 用詞（計畫／計劃、影片／視頻）本來就是臺灣的，比字元轉換準。
> 而且 `custom_vocabulary` 還會**順便修正同音錯字**——實測把「會計師」修回「會計室」、
> 「計劃」修回「計畫」。

---

## 2. 兩條 API 路徑（形狀完全不同，不能互抄）

### A. `generate_content`（Python SDK 原生型別，推薦）

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
part = types.Part.from_bytes(data=open("a.wav","rb").read(), mime_type="audio/wav")

r = client.models.generate_content(
    model="gemini-3.5-transcribe", contents=[part],
    config=types.GenerateContentConfig(
        audio_transcription_config=types.AudioTranscriptionConfig(
            mode=types.AudioTranscriptionConfigMode.SMART,   # 大寫 enum
            language_codes=["cmn-Hant-TW"],
            custom_vocabulary=["深耕計畫", "研發處"],
        )))
```

🔴 **結果不在 `r.text`**。轉錄裝在專屬的 `audio_transcription` part 裡：

```python
for p in r.candidates[0].content.parts:
    at = p.audio_transcription        # ← 這裡
    at.text            # 文字
    at.speaker_label   # 實測是 'spk:0' / 'spk:1'（官方文件寫 spk_1，別寫死）
    at.words           # [WordInfo(word, start_offset='1.200s', end_offset='1.6s')]
    at.finished        # 串流時區分暫定/定稿
```
不開 diarization 時整段是**一個** part；開了才會**逐段切開**、每段帶 `speaker_label`。

### B. `interactions.create`（官方文件用這條）

參數形狀是**巢狀小寫**，跟 A 完全不一樣：

```python
client.interactions.create(
    model="gemini-3.5-transcribe",
    input=[{"type": "audio", "uri": f.uri, "mime_type": f.mime_type}],
    generation_config={"transcription_config": {
        "language_codes": ["cmn-Hant-TW"],
        "mode": {"type": "verbatim",            # 或直接字串 "smart"
                 "diarization_mode": "speaker",
                 "timestamp_granularities": ["word"]},
        "custom_vocabulary": ["深耕計畫"],
    }})
```
回應：`it.output_text` 是全文；`it.steps[0]["content"][0]["annotations"]` 是逐字
`{text, speaker, start_offset, end_offset, start_index, end_index}`。

> 對照表：`SMART`↔`"smart"`、`VERBATIM`↔`{"type":"verbatim"}`、
> `diarization=True`↔`diarization_mode:"speaker"`、`word_timestamp=True`↔`timestamp_granularities:["word"]`。
> **兩邊的參數名互抄一定失敗。**

---

## 3. Live API（即時字幕／語音助理）

### 音訊規格（錯了會靜音或亂碼，不會報錯）
- **送出**：16000 Hz、16-bit、**單聲道**、raw PCM（**不含 WAV 標頭**），
  `mime_type="audio/pcm;rate=16000"`
- **收回**：24000 Hz、16-bit、單聲道
- 送出用 `session.send_realtime_input(audio=types.Blob(...))`；結束送 `audio_stream_end=True`

### 即時字幕的兩種訊息（`msg.server_content` 底下）
| 欄位 | 意義 | 實測延遲 |
|---|---|---|
| `interim_input_transcription` | 暫定字幕，逐字長出來、會一直改寫 | 約 **1 秒** |
| `input_transcription` | 定稿，不會再改 | **要偵測到講者停頓才來**，不是固定節奏 |

實測 47.5 秒音檔（句子之間有停頓）→ 95 則 interim、3 則 final。

🔴 **不要拿 `input_transcription` 當定稿時機。** 它是「講者停下來」才觸發的，
不是每隔十幾秒一次。演講、影片、線上會議這種一路講不停的內容，實測 **7 分鐘只吐 1 則**，
而且時間戳會變成「收到的時刻」而不是「講的時刻」（整段 7 分鐘的話全標成 01:08）。
正解是自己從 interim 按標點切句（`SentenceGate`，見下面「即時翻譯的『快 vs 準』——延遲要加在哪裡」那一節）。
`live_caption.py` 與 `live_bilingual_hq.py` 現在都走這條。

🔴 **Live 模式下 `diarization=True` 沒有作用**——實測 `speaker_label` 全是 `None`。
即時字幕**分不出講者**，只能事後用檔案轉錄那條路補。

🔴 **Live 模式不設 `mode` 一律出簡體**。必須明寫
`mode=SMART` + `language_codes=["cmn-Hant-TW"]`。

### 語音助理設定
```python
cfg = types.LiveConnectConfig(
    response_modalities=["AUDIO"],          # 只能填一個值，填兩個會 1007
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")),
        language_code="cmn-TW"),            # ← native-audio 模型會拒絕這個
    system_instruction="...",
    tools=[...],
    input_audio_transcription=types.AudioTranscriptionConfig(),   # 傳物件，不是 True
    output_audio_transcription=types.AudioTranscriptionConfig(),
    session_resumption=types.SessionResumptionConfig(),
)
```
實測可用聲音（`gemini-3.1-flash-live-preview` + `cmn-TW`）：
Puck / Charon / Kore / Aoede 都出漂亮繁體。**Charon 斷句最乾淨**。

### 工具呼叫（語音助理的核心）
```python
async for msg in session.receive():
    if msg.tool_call:
        for fc in msg.tool_call.function_calls:
            result = MY_FUNCS[fc.name](**(fc.args or {}))
            await session.send_tool_response(function_responses=[
                types.FunctionResponse(id=fc.id, name=fc.name, response=result)])
```
🔴 **工具名稱不能用中文**：`Invalid function name. Must start with a letter`（1007 斷線）。
函式名用英文，`description` 和參數說明可以用中文。

### 即時雙語字幕（原文 + 翻譯同時出）

用 `gemini-3.5-live-translate-preview`。它本來是做**同步口譯**的，
所以一條連線就同時回兩種文字——這就是雙語字幕的來源：

| 欄位 | 內容 |
|---|---|
| `input_transcription` | 它**聽到**什麼（原文，例：英文） |
| `output_transcription` | 它**翻成**什麼（譯文，例：中文） |

```python
cfg = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    translation_config=types.TranslationConfig(
        target_language_code="zh-TW",       # ← 見下方紅字
        echo_target_language=False),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)
```

🔴 **這個模型的語言碼跟轉錄模型不通用**（實測）：

| target_language_code | 結果 |
|---|---|
| `zh-TW` | ✅ **繁體 + 台灣用語**（「大家早安」而非「大家早上好」）← 用這個 |
| `zh` | ❌ 簡體 |
| `cmn-Hant-TW` | 🚫 **1007 斷線**（轉錄模型吃這個，翻譯模型不吃） |

🔴 **`echo_target_language` 不是「回傳原文」**——它控制的是「要不要為目標語言產生**音訊**」
（等於同步口譯的語音）。雙語**文字**字幕靠的是上面兩個 transcription 欄位，跟它無關。

🔴 **這個模型偶發 1007「Request contains an invalid argument」，且與參數無關**。
實測同一組設定：第一次失敗、第二次成功。**必須寫自動重連**，
否則會誤判成參數錯誤（我就誤判了兩次）。
另注意：連線建立成功不代表可用——**送音訊時才會拋這個錯**，所以只測 connect 驗不出來。

🔴 **繁體字 ≠ 台灣用詞**。實測譯文出現「計劃／項目／報銷」等大陸慣用語，字是繁體但詞不對。
`live_bilingual.py` 有一張 `TW_TERMS` 對照表做後處理，但**只放不可能誤判的詞**
（視頻→影片、軟件→軟體、網絡→網路、信息→資訊、報銷→核銷…）。
`項目`、`計劃`、`程序`、`質量`、`登錄` 一律**不做字串替換**、交給提示詞——理由見下一節的誤傷案例。

延遲：原文與譯文各約 1～2 秒，且**兩者不同步**（譯文常晚 1 秒或早 1 秒），
所以存檔時要依時間就近配對，不能假設一來一往。
模型一次只吐一兩個詞，要自己攢成句子（看 `Buffer` 類別）才像字幕。


### 即時翻譯的「快 vs 準」——延遲要加在哪裡

使用者問：能不能把即時字幕延後 3–4 秒，等語序完整再顯示？
**答案：延後「顯示」沒有用，要延後的是「翻譯」。**

`gemini-3.5-live-translate-preview` 是邊聽邊翻，文字產生的當下就已經定型
（「增加了國際合作率 15%今年」）。晚點顯示只是晚點看到同一句爛翻譯。

正解（`scripts/live_bilingual_hq.py`）：
1. 只用 `gemini-3.5-transcribe-live` 拿**原文**（品質好）
2. 自己判斷句子何時定案 → `SentenceGate`（住在 `scripts/_live.py`，全專案唯一一份）
3. 整句才丟 `gemini-3.5-flash-lite` 翻

🔴 `SentenceGate` 原本只長在 hq 這一支，`live_caption.py` 沒跟上 —— 同一個模型、
同一個毛病，功能 1 卻要苦等伺服器定稿。搬進 `_live.py` 就是為了不要再有第二份會漂移的複本。

**判斷句子定案的規則**：
- A. interim 裡出現句尾標點，而且**後面又長出新字** → 模型已講到下一句，前句不會再改
- B. interim 超過 `settle` 秒沒變（講者停頓）
- C. 累積超過 max_chars 先斷，不要無限拖

🔴 **不要把 `input_transcription`（final）也餵給 gate**。它是另一版字串，
跟 interim 不同，會被判成「新段落」而把同一段內容重送一次（實測出現重複與亂序）。
只餵 `interim_input_transcription`。

**翻譯模型延遲實測**（同一句英文，各跑 4 次）：

| 模型 | 平均 | 成功率 |
|---|---|---|
| `gemini-3.5-flash-lite` | **0.73s** | 4/4 |
| `gemini-3.1-flash-lite` | 0.74s | 4/4 |
| `gemini-3.5-flash` | 2.00s（尖峰 5.3s，會回 503） | 4/4 |
| `gemini-2.5-flash-lite` | — | 404 已下架 |

→ 用 lite，譯文品質沒有差（甚至更簡潔）。端到端延遲實測 **平均 0.80 秒**
（從句子定案到譯文印出），加上等講者講完約 **2～3 秒**。

🔴 **`max_output_tokens=400` 會讓短句被截斷**（「大家早安。」變成「大家早。」）——不要設。

🔴 **台灣用語替換表不能貪心**。原本放了 `項目→專案`，結果把
「research assessment session」譯出的「項目會議」誤傷成「專案會議」。
只保留在臺灣不可能有別的意思的詞（視頻/軟件/網絡/屏幕/信息…），
`項目`、`計劃`（動詞）、`程序`（程序正義）、`質量`（物理）、`登錄`（法律）
一律交給提示詞處理，不做字串替換。

🔴 **翻成日文／英文時，提示詞要用目標語言寫**（2026-09-11 實測，flash-lite＋溫度 0＋MINIMAL；
2026-09-19 起工具 3 準確模式的翻譯已拿掉 temperature=0（見 §4），下面這組數字是在那之前量的）。
原本整段提示詞是中文，只有「日本語」三個字是日文，模型會被提示詞的語言拉走：翻成日文兩輪實驗
300 句裡有 15 句（約 5%）整句變成中文或原文照抄。改成日文框架降到約 1%，但仍會偶爾把中文原句照抄回來，
甚至回「中文原句＋--->＋日文」並列。所以再加兩道檢查，錯了就換加註的提示詞補問一次（補問也不對就用第一次的）：
① 整句不是目標語言（沒有假名、沒有日文專用字、漢字 ≥2）　② 譯文裡整段抄了原文（連續 8 個漢字相同）。
② 是複查才補上的——並列的回答有假名，① 看不出來；兩道合起來在三輪 1753 筆真實譯文裡抓到的 12 筆
全是真的照抄或整句中文、0 誤抓。已知取捨：沒有日文專用字的純漢字日文（会議、東京大学）會被 ① 當成中文，
代價是多問一次。翻成 zh-TW 的提示詞一個字都沒改。
第四輪直接呼叫產品的翻譯函式、用跟產品無關的量法（中文虛字、照抄原文）量最後顯示的譯文：284 句 0 混入、
0 捏造；最常照抄的那句（講者說中文、翻日文）跑 30 次，有 5 次第一個答案照抄，補問後全部是乾淨的日文。

🔴 **接續句前文只帶上一句**（目前只套在 ja／en）。「接續句」＝上一句沒有句尾標點：多半是 SentenceGate
硬切，也可能是講者停頓時送出的半句。帶前兩句時，模型會把更前面那句的內容併進譯文：「with experienced
principal investigators.」8 次裡 7 次多出更前面那句才有的「今年度」（this year），還自己補上「導入し、」
把幾句硬接成一句（舊中文框架也 8/8 補出「導入」）；最早的寫法甚至 8/8 捏造出前文才有的「15%」
（6 次「引き上げる」、2 次「削減」，意思相反）。只帶上一句後都是 0/8。
🔴 兩道檢查都只看文字，**看不出內容對不對**——捏造前文數字這種錯，只有對照原文才抓得到。

🔴 **模組頂層不要換 `sys.stdout`**。`live_bilingual_hq.py` 原本在頂層就
`sys.stdout = TextIOWrapper(...)`，被 import 做單元測試時，
新舊 wrapper 互相關閉底層 buffer → `ValueError: I/O operation on closed file`。
改成 `if __name__ == "__main__":` 內才換。


#### 🔴 interim 會「回頭改寫」——斷句器不能用原字串位置記進度

實跑一支 8 分鐘的 YouTube 影片，**145 句裡有 38 句（26%）是重複的**，
而且**英文原文本身就重複**（不是翻譯的問題）。兩種樣態：

**樣態一：模型改寫已出現的字。**
```
interim(t1): ...came out of one message. No editing software,
interim(t2): ...came out of one message, no editing software, nothing manual.
                                     ↑句號變逗號  ↑No 變小寫
```
用 `text.startswith(已送出的原字串)` 判斷「接不接得上」→ 比對失敗
→ 誤判成新段落 → 游標歸零 → **整段重送**。

**樣態二：interim 在長句與短句之間來回跳。**
```
interim: <整段開場白>          → 送出
interim: And at                → 前綴對不上 → 重置
interim: <整段開場白> And at the end...  → 又對不上 → 整段開場白再送一次
```
實測同一段開場白在 00:15 / 00:16 / 00:17 出現三次。

**兩道修法（都要，缺一不可）：**

1. **游標改記「正規化後的字數」**——去標點、去空白、轉小寫再比。
   標點被改寫就傷不到。接不接得上改用「共同前綴 ≥ 已送出長度的 75%」判斷。
   ⚠️ 判定成新段落時，**舊段落沒送出的殘句要先補送**，否則會掉字。
2. **整場去重保險**——保留整場已送出的正規化文字，送出前檢查：
   整句講過 → 丟掉；開頭講過 → 只送沒講過的尾巴。
   ⚠️ 只有「截掉前綴後剩下的殘渣」才丟；正常的短句（單字「請」）要留著，
   否則會為了去重而掉字（我第一版就掉了）。

#### 🔴 提示詞的用語對照表列太積極會反噬

原本在翻譯提示裡寫「專案(非項目)」，結果模型把
`today's session on research assessment` 翻成「研究評鑑的**專案**會議」——
session 根本不是專案，是提示詞把它硬拉過去的。
改成「請用臺灣的中文用語習慣（例如 影片而非視頻…）。用詞要自然，不要硬套。」
之後就正確翻成「研究評量說明會」。

> 通則：**字串替換表**和**提示詞對照表**都不能貪心。
> 只列詞義固定、不可能誤導的；一詞多義的交給模型自己判斷。


#### 🔴 去重保險把真實內容刪掉了（第二輪，2026-09-04）

第一版去重把整場的正規化文字**串成一坨沒有分隔的字串** `self.said`，
再用 `sn in self.said` / `sn[:k] in self.said` 做子字串比對，門檻只有 **8 個正規化字元**。
英文 8 個字元毫無鑑別度，結果刪掉真實內容（拿同一支影片的前一次輸出當基準真相，逐字比對找出）：

| 被刪內容 | 誤判來源 |
|---|---|
| `software.` 整句消失 | 55 秒前另一句裡有 software（剛好 8 字元） |
| `I'll break down ` 被截掉 | 38 秒前講過 `I'll break down what` |
| `to use.` 整句消失 | 同類 |

**修法**：
- 改存**最近 8 則各自獨立的輸出**（`deque`），比對用**整句相等**而非子字串。
- 前綴截除只跟**上一則**比（`sn[:k] == prev[-k:]`），不跟整場比。
- 門檻 8 → **24** 個正規化字元。實測重複的樣態是 96 字元整段重送，遠高於門檻。

#### 🔴🔴 方法論教訓：不要拿「已經被過濾過的輸出」去測「過濾器有沒有誤刪」

我第一次驗證時，把去重規則重跑在**產出的字幕檔**上，得到「0 誤判」就宣告沒問題。
**這是循環論證**——被刪掉的內容根本不在那個檔案裡，當然測不出來。

正確做法（代理人用的）：拿**同一份輸入的另一次獨立輸出**當基準真相
（這裡剛好有 12 分鐘前用舊版跑的 `1.md`），做逐字 diff。
差異就是被刪掉的東西。三處遺失全部因此現形，而且能逐位元重現。

> 通則：驗證「某個步驟有沒有丟東西」，一定要跟**沒經過那個步驟的版本**比，
> 不能只檢查它自己的輸出。

#### max_chars：用真實語料決定，不要憑感覺

從基準檔重組出 **266 個完整句子**：中位數 62、平均 69、**最長 218** 字。

| 門檻 | 會被硬切的句子 |
|---|---|
| 140（原值） | **30 句（11%）** ← 正好對上實測的 5/44 |
| 180 | 6 句（2%） |
| 200 | 3 句（1%） |
| **240** | **0 句** ✅ |

改成 240，並且硬切時**優先找子句邊界**（逗號/分號/冒號），沒有才退回找空白。
另外把「這是被迫切開的碎片」旗標傳給翻譯模型，它才不會把 `month.` 單獨翻成「個月」、
把 `five-year projections.` 翻成「五年預測」。

### 打斷（barge-in）
`server_content.interrupted == True` 時，**必須自己清空還沒播完的音訊佇列**，
否則使用者已經插話了、喇叭還在講上一句。

---


## 🔴 附：檔案轉錄的錄音長度上限（兩條，取比較嚴的那一條）

**這一節在 2026-09-16 修正過**：原本只寫「65.4 分鐘」，那是拿 `inputTokenLimit = 98,304`
除以實測的 25.04 token/秒推算的。算式沒錯，但**那不是唯一的限制**，而且不是最嚴的。

| 情況 | 上限 | 依據 | 超過會怎樣 |
|---|---|---|---|
| **開 diarization 或 word_timestamp** | **30 分** | 官方 Limitations 明文 | 🔴 **不報錯**、照整份計費；超過的部分會怎樣官方沒寫，實測沒有確認過任何一次截斷（見下方更正） |
| 不開那兩個功能 | **1 小時** | 官方 Limitations 明文 | 400，看得到 |
| （早期推算值） | ~~65.4 分~~ | 98,304 ÷ 25.04 tok/秒 | 高估了，實測 60.6 分就被擋 |

官方原文（`https://ai.google.dev/gemini-api/docs/transcribe.md.txt`，抓原始 markdown 不是改寫版）：

> **Audio duration:** Standard unary requests support audio files up to 1 hour.
> Audio processing is limited to 30 minutes when features like speaker diarization
> or word-level timestamps are enabled.

token 換算仍然有用（估成本用），但**不要拿來當長度上限的判準**：

| 錄音長度 | tokens | 能不能過 |
|---|---|---|
| 30 分 | 45,072 | ✅ 開分講者時的實際上限 |
| 60 分 | 90,144 | ✅ 官方明文上限（不開分講者） |
| 65 分 | 97,656 | ❌ token 夠，但超過官方的 1 小時 |
| 70 分 | 105,168 | ❌ 兩條都超過 |
| 120 分 | 180,288 | ❌ |

超過就是：
```
400 INVALID_ARGUMENT
The input token count exceeds the maximum number of tokens allowed 98304.
```
**沒有其他徵兆，也不會自動降級。** 校務會議動輒兩小時，一定會踩到。

`transcribe_meeting.py` 已內建自動分段（`MAX_CHUNK_SEC = 28*60`）：

1. `ffmpeg silencedetect` 找靜音點
2. 在目標切點**前 5 分鐘內**挑最接近的靜音處下刀，避免切斷句子（找不到才硬切）
3. 每段各自跑兩趟＋對齊，時間軸再加上該段起點偏移

🔴 **真正卡住的不是這條 token 上限，是官方 Limitations 的另一條**——
「Audio processing is limited to 30 minutes when features like speaker diarization or
word-level timestamps are enabled.」pass1 兩個都開，所以受這條 30 分鐘的限制。
超過時**不報錯、照整份計費**；超過的部分會怎樣官方沒寫，我們實測也沒有確認過任何一次截斷。

🔴 **2026-09-16 更正**：原本這裡寫「查證一份 2:56:47 的真實會議，切 45 分鐘時前三段各在
第 30 分鐘斷掉、只涵蓋 73.8%」——**那個結論是錯的，已推翻**。那組數字是拿舊版的時戳算的，
而舊版的時戳本身壞掉（10 句超過 1,000 字的巨句，最長 6,771 字，開頭與結尾是同一段話重複）：
內容其實在巨句裡，只是時間標錯。把那些時段剪出來單獨轉才確認，真正的故障是另外兩種
（段中整片沒辨識到、正文迴圈重複）：迴圈重複在 45 分鐘與 28 分鐘**都發生過**，
段中空洞目前只在 28 分鐘的段遇過——分段長度不是病根。

🔴 **講者編號無法跨段一致**——每段是獨立辨識的，第 1 段的 `spk:0` 不保證是第 2 段的 `spk:0`。
輸出檔頭已加警語。要跨段一致得自己比對時間或聲紋，目前沒做。

> 這條我在第一天 ListModels 就量到 `inputTokenLimit: 98304`，卻沒接進工具，
> 直到使用者拿真實會議錄音來跑才炸。**量到的限制要當場接進程式，不要只寫在筆記裡。**

---


### 🔴 WordInfo 的 start_offset / end_offset 可能是 None

短音檔測不出來，長錄音（實測 2 小時 57 分）就會出現：
```
AttributeError: 'NoneType' object has no attribute 'rstrip'
  float(w[-1].end_offset.rstrip("s"))
```
不要假設每個詞都有起訖時間。`transcribe_meeting.py` 改用 `_off()` / `_span()`：
逐一跳過沒有時間戳的詞，全都沒有就回 `None`，再退回「接在上一段之後」。

### 🔴 長工作必須「單段失敗不影響全局」

三小時的錄音切成 4 段，第 1 段跑完（已經花錢）、第 2 段崩潰 → 舊版整個 traceback 出去，
**前面付費跑完的結果全部丟掉**。這在使用者眼中就是「錢花了、什麼都沒拿到」。

改法：
- 每段包在 `try/except` 裡，失敗只記錄不中斷，其餘段落繼續。
- 每**整段**成功就把累積結果寫到 `*.partial.json`，中途掛掉時已經整段跑完的部分留得住。
  🔴 實務上多半只有超過 `MAX_CHUNK_SEC`（預設 28 分鐘）、被切成多段的錄音留得住：28 分鐘以內是
  一整段，要等第 1 趟＋第 2 趟＋對齊**＋補轉**（2026-09-20 加的第 4 步，見 §1）全部做完才會寫第一次，
  **辨識中途**掛掉什麼都沒有、只能整份重轉。補轉排在寫檔之前，所以它也要算進這段空窗——
  這正是補轉「不重試、遇到伺服器忙就停」的原因（每處都重試的話，一段最多會多空等 35 分鐘）。
  但那一段全部跑完之後才出事（寫 `.md` 時檔案被鎖住、磁碟滿、此刻關視窗）的話，單段一樣會留下這個檔——
  所以文件與訊息都不可以寫成「單段一定不會留」的絕對句（2026-09-15 第四輪複查實測到場景 G）。
  中斷訊息（`transcribe_meeting._interrupted()`）因此要照這個檔實際在不在講話，
  不可以寫成無條件成立（2026-09-15 R3-4：同一件事散在程式、選單、README、手冊四處）。
- 輸出檔頭明列**缺了哪些時段**，而不是安靜地產生一份看起來完整的稿子。
- 全部段落都失敗才 `exit(1)`。

> 通則：只要單次工作可能跑幾十分鐘又要花錢，就不能用「一路 raise 到底」的錯誤處理。

---

## 4. 成本（實測 + 官方定價）

實測：**音訊 = 25.04 token/秒**（47.5 秒 → 1189 audio tokens）。
→ 1 小時會議 ≈ **90,100 tokens**。

| 模型 | 輸入（音訊） | 輸出（文字） | 1 小時輸入費 |
|---|---|---|---|
| `gemini-3.5-transcribe` | $2.00 / 1M | $12.00 / 1M | **US$0.18** |
| `gemini-3.5-transcribe-live` | $3.50 / 1M | $21.00 / 1M | **US$0.32** |

- 兩趟設計的一小時會議 ≈ 輸入 $0.36 + 輸出約 $0.25 ≈ **US$0.6（約 NT$20）**
- 即時字幕一小時 ≈ **US$0.5（約 NT$17）**
- 實測 47.5 秒的完整兩趟轉錄：2,380 audio tokens + 929 對齊 tokens = **US$0.0048**
- 🔴 上面的估算**不含補轉**（2026-09-20 加的第 4 步）：每補一處就是一次額外的 `gemini-3.5-transcribe` 呼叫，
  每段最多 20 處，剪出來的片段通常只有幾秒（實測示範檔補 3 處、整份多 564 audio tokens ≈ US$0.001）。
  正常錄音補個位數處、多不到 1%；模型大量丟句時才會明顯增加，程式有把它計進畫面上的語音 token。
- 工具 2 的對齊（`gemini-3.5-flash`，思考 LOW／MINIMAL）：2 分鐘錄音實測 1,036 tokens → 每小時約 3 萬 tokens、約 US$0.05。
  🔴 第 2 趟正文陷入迴圈時會暴增（2026-09-19 一份 63 分鐘合成錄音：對齊 14.7 萬 tokens、US$0.22）。
- 🔴 `gemini-3.5-transcribe` 的回應**只回報輸入 token**；`gemini-3.5-transcribe-live` **完全不回報** usage_metadata
  （2026-09-19 實測）。這兩個模型的輸出費只能用官方「每分鐘 175 個文字 token」估，實際以帳單為準。
- 工具 4（`translate_transcript.py`，`gemini-3.5-flash`，2026-09-19 用 60.6 分鐘逐字稿實測）：
  in 22,531／out 14,786／**thoughts 37,711** → US$0.51（NT$16）；思考 token 約是譯文的 2.5 倍。
  另做過 thinking_level=low 對照：thoughts 0、US$0.18（NT$6），但盲評（8 位 × 175 段）小錯 105 → 260、
  專有名詞不一致 7 → 10 個（改變原意的錯誤兩邊都 0）→ 使用者裁示**不採用**，品質優先。
- 🔴 temperature（2026-09-19 A/B，官方 3.5 指南建議 3.x 模型**不要設**、用預設 1.0）：
  工具 2 對齊、工具 3 準確模式的翻譯**已拿掉** temperature=0（對齊 6 次結果完全相同；翻譯 34 句盲評不分軒輊、重大錯誤 2→0）；
  **工具 4 刻意保留 temperature=0**——拿掉後句子較自然，但每 25 段一批各自翻、每批挑的譯名不同，
  專有名詞不一致 7 → 14 個、術語錯誤 9 → 43，給外賓的正式文件不能接受。

### 🔴 4.1 同步口譯模型貴 4 倍（2026-09-18 初測、2026-09-19 完整實測）

`gemini-3.5-live-translate-preview`（雙語字幕的**快速模式**、以及工具 6 的語音翻譯）
**不能比照上表估**。它的 `response_modalities` 是 `["AUDIO"]`——**輸出是語音**，
而語音輸出是**按音訊長度**計 token（每秒 25 個，跟輸入一樣多）。工具 1 的輸出單價同樣是 $21.00/1M，
但它輸出的是文字，每分鐘只要約 $0.004；這裡輸出的是語音，每分鐘 $0.0315——**貴在輸出量，不在單價**。

| | 官方單價 | 實測用量（09-19，10 分鐘） | 1 小時 |
|---|---|---|---|
| 輸入（音訊） | $3.50 / 1M | 25.0 token/秒（14,975 ÷ 599 秒） | US$0.315 |
| 輸出（**音訊**） | $21.00 / 1M | 25.0 token/秒（輸出＝輸入） | US$1.89 |
| 合計 | | | **US$2.20（約 NT$70.6）** |

官方定價頁另註明「以 25 token/秒計，約 $0.0368/分鐘」＝ US$2.21/小時，與實測相符。
（09-18 初測只量 20 秒、得到 23.8 token/秒、US$2.1（約 NT$66），已被這次取代。）

🔴 **量法陷阱**：Live API 的 `usage_metadata` 是**每一則訊息**的用量，不是累計值。
第一次量的時候只讀最後一筆，拿到 25 token，換算成「一小時 NT$3」——**少算 20 倍**。
一定要把每一則加起來（開發端的量測腳本就是這樣寫的）。

🔴 反過來的好消息：語音在伺服器端生成的當下就計費了，所以**把它播出來（`--speak`）
不會多花任何錢**。舊版是收下來就丟掉，等於買了不用。

### 🔴 4.2 中文目標語言碼：zh-TW 與 zh-Hant 等價（2026-09-18 各測 3 次）

官方語言表寫繁中是 `zh-Hant`，程式用的是 `zh-TW`。拿同一段 49 秒英文會議稿實測：

| 目標語言碼 | 連線 | 字體 | 開頭第一句 |
|---|---|---|---|
| `zh-TW` | ✅ 3/3 | 繁體（簡體字 0） | 大家早安 |
| `zh-Hant` | ✅ 3/3 | 繁體（簡體字 0） | 大家早安 |
| `zh-Hant-TW` | ❌ 1007 | — | — |
| `cmn-Hant-TW` | ❌ 1007 | — | — |
| `zh`（對照組） | ✅ | **簡體** | 大家早上好 |

兩者輸出差異（例如「謝謝您」vs「謝謝大家」）在三次之間互換過，是**取樣雜訊，不是系統性差別**。
→ **維持 `zh-TW`**：沒有實測到的好處就不要改，現行的 `TW_STYLE_INSTRUCTION`
與事後替換都是以它驗過的。（各測 3 次的實測結果，驗證腳本未隨附。）

🔴 注意這跟轉錄模型**不通用**：轉錄模型吃 `cmn-Hant-TW`，這個翻譯模型給它會 1007。

🔴 免費層是**真的免費**（不扣款），但代價見下一節。

---

## 5. 🔴 資料治理：免費層不能用來錄真實校務會議

官方條款原文（ai.google.dev/gemini-api/terms）：

- 免費層：「Google uses the content you submit to the Services and any generated responses
  to provide, improve, and develop Google products and services」，且
  「**human reviewers may read, annotate, and process your API input and output**」，
  並明文警告「**Do not submit sensitive, confidential, or personal information to the Unpaid Services**」。
- 付費層：「Google **doesn't use** your prompts ... or responses to improve our products」，
  只為偵測濫用而短期保留紀錄。

**結論：涉及人事、經費、審查意見、學生個資的會議，一定要先在 Google Cloud 帳單專案上
開通付費層再用。** 免費層只適合拿公開內容或測試音檔做驗證。

---

## 6. 其他實測到的坑

| 症狀 | 原因 | 解法 |
|---|---|---|
| `r.text` 是 `None`，警告 non-text parts | 轉錄在 `audio_transcription` part | 走 `candidates[0].content.parts[i].audio_transcription` |
| 1007 `Unsupported language code 'cmn-TW'` | 用了 native-audio 模型 | 改 `gemini-3.1-flash-live-preview` |
| 1007 `Invalid function name` | 工具名用中文 | 函式名改英文 |
| 1007（要求 TEXT 輸出） | native-audio 模型只支援 `["AUDIO"]` | 換模型或只要 AUDIO |
| 中文輸入變亂碼 | Windows stdin 預設 CP950 | `sys.stdin.reconfigure(encoding="utf-8")` |
| 背景執行看不到 log | Python stdout 全緩衝 | `python -u` 或 `TextIOWrapper(..., line_buffering=True)` |
| 錄不到會議聲音 | 只錄了麥克風 | Windows 用 `pyaudiowpatch` 的 WASAPI loopback（見下） |
| 立體聲混音錄到靜音 | 該裝置被停用 | 別用它，改 WASAPI loopback |
| 開了 `--speak` 之後翻譯越翻越亂 | 翻譯語音被 loopback 錄回去，模型在翻自己 | 播到**別顆**裝置（見 6.1） |
| `--source mic --speak`：講者講完之後一直重複同一句、停不下來 | 口譯從喇叭出來、被麥克風錄回去；靜音閘門等不到安靜，一直在送、一直在計費（2026-09-28 使用者實際遇到，真 Google 模擬：60 秒以上停不下來） | 戴耳機、口譯播到耳機；程式擋不住，選單與開場只能警告 |
| 口譯與試聽音全程無聲，結束卻照報送出的秒數（舊版的字樣是「播出 N 秒」） | 對到了 DirectSound：PortAudio 的 DirectSound 用阻塞寫入時無聲、也不報錯 | 一律解析到 MME（見 6.2） |

### 🔴 6.1 播放翻譯語音的回授迴圈（2026-09-18）

WASAPI loopback 錄的是「**系統預設播放裝置**正在播什麼」。把翻譯語音也送到那一顆，
它會立刻被錄回去、再翻一次、再播一次——而且每一圈都在燒 token。
`--source system`／`both` 因此**強制**要 `--speak-device` 指定另一顆裝置。

🔴 名稱比對不夠：「Microsoft 音效對應表 - Output」「主要音效驅動程式」是
**跟著預設走的轉接器**，名字看起來像別顆，聲音還是送到預設那顆。
`_live.is_default_like()` 專門處理這一類（`_DEFAULT_ALIASES`）。

同一顆實體喇叭在 MME／DirectSound／WASAPI 下會各出現一次（這台實測 10 筆其實只有 3 顆），
而且 MME 會把名稱截成 31 個字——**「是不是同一顆」這種比對**取名稱前 25 個字、忽略大小寫
（`_live.same_device`／`is_default_like`，選單的清單去重也是）。

🔴 但「**要開哪一顆**」不可以用名稱找：那條路要用音訊端點 ID，理由見下面的 6.2。

### 🔴 6.2 DirectSound 用阻塞寫入完全沒聲音、而且不報錯（2026-09-20）

筆電實測：功能 6 的口譯路線選到完整名稱超過 31 字的裝置（「1 - KONKA LCDTV (AMD High Definition Audio Device)」），
**試聽音沒出來、口譯全程無聲，畫面卻照印「翻譯語音共播出約 87 秒」**。兩台電腦、共 5 顆裝置都重現。

| 播放方式 | 結果 |
|---|---|
| PortAudio 19.7 DirectSound ＋ 阻塞寫入（`RawOutputStream.write`） | **完全無聲；不丟例外、不回錯誤碼** |
| 同一顆 DirectSound 編號改用 callback（`sd.play`） | 有聲 |
| MME ＋ 阻塞寫入 | 有聲 |
| WASAPI | 開不起來（24kHz → `Invalid sample rate`） |

- 🔴 **「逐顆開開看」測不出來**：DirectSound 開得起來、也寫得進去，只是沒有聲音。6.1 上面那道保險對這個症狀完全無效，只有實際量 loopback 才看得出來。
- 🔴 **寫入成功 ≠ 有聲音**：`played_bytes` 只要 `write()` 沒丟例外就累加，所以畫面才會說「播出 N 秒」。現在改口說「**送出**約 N 秒到播放裝置」——這個數字只證明送出去了，不證明聽得到。
- **為什麼會對到 DirectSound**：MME 會把裝置名稱截成 31 個字，所以「用完整名稱找裝置」只會對到 DirectSound 或 WASAPI（它們的名稱是完整的）。舊版用「描述比開頭」剛好對到 MME，改成完整名稱比對之後就壞了。

**修法：播放一律解析到 MME，而且用 Windows 的音訊端點 ID 去對，不要用名稱。**

```python
# winmm：waveOut 編號 w → 音訊端點 ID（{0.0.0.00000000}.{guid}）
import ctypes
from ctypes import wintypes
winmm = ctypes.WinDLL("winmm")
winmm.waveOutMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
winmm.waveOutMessage.restype = wintypes.UINT
DRV_QUERYFUNCTIONINSTANCEID     = 0x0811
DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0812

def endpoint_id(w):                       # w＝waveOut 編號（0…waveOutGetNumDevs()-1）
    size = wintypes.ULONG(0)
    if winmm.waveOutMessage(ctypes.c_void_p(w), DRV_QUERYFUNCTIONINSTANCEIDSIZE,
                            ctypes.byref(size), None) or not size.value:
        return None                       # 回 0 才是成功（MMSYSERR_NOERROR）
    buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
    if winmm.waveOutMessage(ctypes.c_void_p(w), DRV_QUERYFUNCTIONINSTANCEID,
                            buf, ctypes.c_void_p(size.value)):
        return None
    return buf.value                      # 例：{0.0.0.00000000}.{921eb87d-…}
```

（實作見 `scripts/_live.py` 的 `mme_endpoint_map()`；它還會把 PortAudio 的 MME 清單與 winmm 的 waveOut 清單逐顆比名稱，對不上就整張作廢。）

- PortAudio 的 MME 播放清單順序＝「音效對應表」排最前面，後面接 `waveOut` 0…n−1，據此對編號。
- 🔴 對照表只要有一顆對不上（數量不同、名稱不同）就**整張作廢、回空**，不要猜；查不到就明講「找不到這個音訊端點對應的播放裝置」，**不可以默默改用別顆**——兩台同型號電視的前 31 字一模一樣，猜錯就是播到另一台，或播回正在被側錄的那顆造成回授。
- 裝置清單（`--list-devices`、功能 6 選 2／3）也一律不列 DirectSound：挑到就是無聲。桌機實測修改前那份清單有 3 顆 DirectSound，挑到任何一顆試聽都是 0。
- 端點 ID 只拿來找裝置；**畫面顯示要另外用登錄檔的完整名稱**（`_audioroute.endpoint_name()`），不然使用者看到的是 MME 的半截名稱。

### Windows 錄「電腦播出來的聲音」（線上會議必備）
`sounddevice` 0.5.6 的 `WasapiSettings` **沒有** `loopback` 參數，做不到。
改用 `pyaudiowpatch`（PyAudio 的 Windows 分支）：

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
本機實測可用（48000 Hz / 2ch），需自行降頻到 16 kHz 單聲道再送 API。

### asyncio on Windows
Live API 用 websocket。`WindowsSelectorEventLoopPolicy` 會讓 **Ctrl+C 延遲到逾時才生效**；
預設的 Proactor loop 反而能立刻中斷。除非遇到相容問題，**不要**手動改 policy。

---

## 7. 官方說法 vs 實測落差（發稿當天核對）

| 新聞/文件說法 | 實測 |
|---|---|
| 支援 85 種語言 | 我自己數官方表格＝**81 個唯一 BCP-47 碼**；**表上沒有臺灣繁中**（中文只有 `cmn-Hans-CN` 簡體與 `yue-Hant-HK` 粵語），但 `cmn-Hant-TW` 傳得進去且實測有效 |
| 最多 3 位說話者 | 官方文件寫**最多 8 位**，但註明「3 位以上的歸屬判定屬實驗性」——新聞稿的「3 位」應是誤讀了這個註記 |
| 自動去贅字、智慧排版 | ✅ 屬實，但只在 `mode=SMART`，且與講者/時間戳互斥 |
| WER 2.6% / 4.0% | 官方文件查無此數字，只在新聞稿出現 |
| 模型 metadata `thinking: true` | 官方模型卡寫 Thinking「Not supported」——兩邊矛盾，未解 |
| 官方文件範例的講者標籤是 `spk_1`／`spk_2` | 實測 `generate_content` 回的是 **`spk:0`／`spk:1`**（冒號、從 0 起算）。**不要寫死字串比對** |

---

## 8. 版本

- `google-genai` **2.22.0**（2026-09-02 發布）；`custom_vocabulary` 需 ≥2.13.0、
  扁平 `language_codes` 需 ≥2.15.0、`VERBATIM/SMART` enum 需 ≥2.19.0
- `pyaudiowpatch` 0.2.12.8、`sounddevice` 0.5.6、Python 3.13
- 模型版本：`gemini-3.5-transcribe` = `3.5-transcribe-08-2026`；
  `gemini-3.5-transcribe-live` = `3.5-transcribe-live-08-2026`
