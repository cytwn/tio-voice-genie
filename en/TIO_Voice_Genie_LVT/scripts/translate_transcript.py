# -*- coding: utf-8 -*-
"""
逐字稿 → 雙語對照

跟「即時雙語字幕」的差別：
  即時版 = 邊聽邊翻（像現場口譯），快，但看不到後文，語序偶爾怪。
  這一支 = 先有完整逐字稿，再整份翻，模型看得到上下文，品質好很多。

吃三種輸入，會自己判斷：
  1. 錄音/影片檔  → 先轉逐字稿，再翻
  2. 逐字稿 .json（本工具組產生的）→ 直接翻
  3. 字幕 .srt    → 直接翻

用法：
  python translate_transcript.py 會議.mp3                       # 中文會議 → 中英對照
  python translate_transcript.py 逐字稿.json --to en            # 明確指定翻成英文
  python translate_transcript.py 演講.srt --to zh-TW            # 英文字幕 → 中英對照
  python translate_transcript.py 會議.mp3 --glossary 深耕計畫=Higher Education Sprout Project
"""
import os, sys, io, json, re, argparse, subprocess, time, logging, signal

if __name__ == "__main__":      # 被 import 時不要動 stdout，會互相關掉底層 buffer
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

from google import genai
from google.genai import types
from google.genai import errors as gerr

# 🔴 SDK 的英文警告（AFC…）是給開發者看的，同事看到會以為出錯了。只顯示真正的錯誤。
logging.getLogger("google_genai").setLevel(logging.ERROR)

MODEL = "gemini-3.5-flash"          # 純文字翻譯，便宜又夠好
BATCH = 25                          # 一次翻幾段（太多會漏段，太少會失去上下文）
RETRY = 4                           # 每批最多試幾次（含第一次）
NET_WAIT_STEP = 20                  # V1.38（待辦 20）：網路斷了（查不到伺服器位址）時，每幾秒再試一次
NET_WAIT_MAX = 300                  # 同一次斷網最多等幾秒；等滿還沒回來才停（已翻好的照樣存檔）
_net_waited = 0                     # 這一次斷網已經等了幾秒：任何一次呼叫成功、或伺服器有回應就歸零（整份共用，見 _retry）


def _permanent(exc):
    """
    這個錯誤重試有沒有意義？

    🔴 額度用完、金鑰失效、DNS 掛掉這幾種，重試一百次也一樣。
       V1.38：DNS 掛掉（＝網路斷了）_retry 會先等網路回來（最多 NET_WAIT_MAX 秒），等滿還沒回來才算在這裡。
       原本一律退避重試的後果：兩小時的逐字稿有 56 批、每批空轉 14 秒，
       接著補跑迴圈**逐段**再各試 14 秒 —— 1400 段就是 5 小時以上的空轉，
       而且畫面上看起來像在工作。這是 2026-09-10 稽核抓到的。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _live import diagnose
        return diagnose(exc)[0]        # need_human ＝ 人不介入就不會好
    except Exception:
        return False


def _net_down(exc):
    """V1.38（待辦 20）：網路斷了（查不到伺服器位址）——等網路回來就會好。判準住在 _live.net_down（跟「連不到網路」同一條）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _live import net_down
        return net_down(exc)
    except Exception:
        return False


def _retry(fn, **kw):
    """
    呼叫 API，失敗就退避重試。

    🔴 兩小時的逐字稿要翻幾十批。原本是裸呼叫，中間任何一次 503／429 就會
       讓整個程式死掉、一個檔案都不留 —— 而前面那些批次的錢已經花掉了。
    """
    import time
    global _net_waited
    last, k = None, 0
    while True:
        try:
            r = fn(**kw)
        except Exception as e:
            last = e
            if _net_waited and isinstance(e, gerr.APIError) and not _net_down(e):
                # V1.38 審查（#5）：伺服器有回應（503、429…）＝網路回來了，這一次斷網的等待歸零（見 transcribe_meeting._with_retry；
                #    第 2 輪：被判成網路斷了的錯誤頁不算、不說「繼續翻」）
                print(f"  ✓ The internet connection is back (waited {_net_waited} seconds)")
                _net_waited = 0
            if _net_down(e) and _net_waited < NET_WAIT_MAX:
                # V1.38（待辦 20）：網路斷了不再當成「重試也不會好」，先等網路回來（同一次斷網最多 NET_WAIT_MAX 秒，整份共用）
                if _net_waited == 0:
                    print(f"  ⚠ The internet connection is down, so waiting for it to come back: trying again every {NET_WAIT_STEP} seconds, for up to {NET_WAIT_MAX // 60} minutes")
                else:
                    print(f"  … The internet connection isn't back yet; trying again in {NET_WAIT_STEP} seconds (waited {_net_waited} seconds so far)")
                time.sleep(NET_WAIT_STEP)
                _net_waited += NET_WAIT_STEP
                continue
            if _permanent(e) or _net_down(e) or k == RETRY - 1:
                break              # 重試沒有意義（網路斷了的已經等滿），立刻交還給呼叫端
            wait = 2 ** k * 2      # 2, 4, 8 秒
            print(f"  ⚠ Connection trouble ({type(e).__name__}); trying again in {wait} seconds…")
            time.sleep(wait)
            k += 1
            continue
        if _net_waited:
            print(f"  ✓ The internet connection is back (waited {_net_waited} seconds); carrying on with the translation")
            _net_waited = 0
        return r
    raise last
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".wma", ".aac", ".flac", ".ogg", ".opus",
             ".mp4", ".mov", ".mkv", ".avi", ".webm"}

LANG_NAME = {
    "zh-TW": "臺灣繁體中文", "en": "English", "ja": "日本語",
    "ko": "한국어", "es": "español", "fr": "français", "de": "Deutsch",
}
# V1.30：畫面與檔頭「顯示用」的語言名稱。LANG_NAME 會放進翻譯提示詞，不能為了顯示去改它
# （英文版要把顯示改成英文，只換這一張；中文版兩張的字一樣，畫面不變）。
SHOW_NAME = {"zh-TW": "Traditional Chinese (Taiwan)", "en": "English", "ja": "Japanese"}


def show_name(code):
    """顯示用的語言名稱：有顯示名就用顯示名，其餘跟提示詞用同一個名字。"""
    return SHOW_NAME.get(code) or LANG_NAME.get(code, code)


def speaker_fallback(lang, n):
    """沒填講者名字時講者欄寫什麼：翻成英文 Speaker N、日文 話者N，其他（含中文）照舊「講者N」。

    🔴 翻成英文、日文時，講者欄原本一律是中文「講者1」（2026-09-14 純譯文版先改；
       2026-09-15 使用者決定 _對照.md／_對照表.md 也一起改，三份檔一致）。
    """
    base = (lang or "").replace("_", "-").split("-")[0].lower()
    if base == "en":
        return f"Speaker {n}"
    if base == "ja":
        return f"話者{n}"
    return f"Speaker {n}"


# ────────────────────────── 讀入 ──────────────────────────
def load_srt(path):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    segs = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->", block)
        start = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 +
                 int(m.group(3)) + int(m.group(4)) / 1000) if m else 0.0
        body = [l for l in lines if not l.strip().isdigit() and "-->" not in l]
        if body:
            segs.append({"speaker": "", "start": start, "text": " ".join(body)})
    return segs


def load_meta(path):
    """逐字稿 .json 的 meta（缺口清單等）。舊格式與 .srt 回 {}。

    🔴 2026-09-20 複查（major）：功能 4 原本把 meta 丟掉，於是一份「缺了 19 分鐘」的逐字稿翻成
       雙語對照之後，四個產出檔一個字都沒提不完整 —— 而那正是要寄給外賓的版本。
    """
    try:
        from json_to_md import load_transcript
        return load_transcript(path)[1]
    except Exception:
        return {}


def load_json(path):
    # 🔴 2026-09-20 起 .json 是 {"meta":…, "segments":[…]}（舊檔仍是純陣列），
    #    讀法統一走 json_to_md.load_transcript，不要各自再寫一份。
    try:
        from json_to_md import load_transcript
        d, _meta = load_transcript(path)
    except ImportError:
        d = json.load(io.open(path, encoding="utf-8"))
        d = d.get("segments") or [] if isinstance(d, dict) else d
    return [{"speaker": s.get("speaker", ""), "start": s.get("start", 0.0),
             "text": s.get("text") or s.get("raw") or ""} for s in d]


def from_audio(path, vocab, names, dest_dir=None, interim_out=None):
    """呼叫既有的逐字稿工具，產生 JSON 後讀進來。

    🔴 中繼逐字稿要寫在使用者指定的輸出位置，不能寫在錄音檔旁邊。
       會議錄音多半放在 OneDrive／Teams 錄影夾或單位共用磁碟，寫在那裡等於
       把機密會議的逐字稿丟進會自動同步、別人看得到的地方，而畫面上只說
       「檔案會出現在桌面」。唯讀的網路磁碟則會在錢已經花完之後才寫入失敗。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # 🔴 中繼稿的路徑一定要由呼叫端（選單）算好傳進來。
    #    自己用「音檔檔名 + _逐字稿.md」組的話，會跟功能 2 對同一個音檔
    #    產生的桌面檔名一模一樣，然後以 "w" 模式直接蓋掉 —— 同事手改了
    #    半天的逐字稿和 .json（功能 5 救援的唯一來源）就這樣沒了。
    #    這是 2026-09-10 稽核抓到的迴歸：把中繼稿從「錄音檔旁邊」改到
    #    「輸出目錄」是為了隱私，卻從側門把覆寫問題放了回來。
    dest_dir = dest_dir or os.path.dirname(path)
    out = interim_out or os.path.join(
        dest_dir, os.path.splitext(os.path.basename(path))[0] + "_transcript.md")
    cmd = [sys.executable, "-u", os.path.join(here, "transcribe_meeting.py"), path, "--out", out]
    if vocab:
        cmd += ["--vocab"] + vocab
    if names:
        cmd += ["--names"] + names
    print("▸ Transcribing first…")
    subprocess.run(cmd, check=True)
    js = os.path.splitext(out)[0] + ".json"
    if not os.path.exists(js):
        # 🔴 整份沒人講話時 transcribe_meeting 正常結束（離開碼 0）、但不產出逐字稿（2026-09-20 N3）。
        #    直接去讀會丟英文 FileNotFoundError 還叫人跑診斷（複查指出）。原因上面已經印了，這裡照實講。
        print("✗ No speech was recognised in this recording, so there is nothing to translate.")
        sys.exit(1)
    return load_json(js), out


def unescape(t):
    """模型有時會把換行寫成字面的 \\n，還原它。"""
    return (t or "").replace("\\n", "\n").replace("\\t", "\t").strip()


# 中文標點後直接斷；英文句點後要接大寫才斷。
# (?<![0-9]) 是為了不要把「1. A seed funding…」的編號跟內容拆開。
SENT_SPLIT = re.compile(r"(?<=[。！？!?])\s*|(?<![0-9].)(?<=[.;])\s+(?=[A-Z])")


def split_long(segs, max_chars=160):
    """
    有些逐字稿整段很長（演講沒停頓時 diarization 只切出一段），
    對照排版會變成左邊一大塊、右邊一大塊，很難看。
    這裡照句子切開，時間依字數比例分配。
    """
    out = []
    for s in segs:
        text = s["text"].strip()
        if len(text) <= max_chars:
            out.append(s); continue
        parts = [p.strip() for p in SENT_SPLIT.split(text) if p and p.strip()]
        if len(parts) <= 1:
            out.append(s); continue
        # 合併太短的句子，避免切太碎
        merged, buf = [], ""
        for p in parts:
            buf = (buf + " " + p).strip() if buf else p
            if len(buf) >= max_chars * 0.5:
                merged.append(buf); buf = ""
        if buf:
            if merged and len(buf) < max_chars * 0.25:
                merged[-1] += " " + buf
            else:
                merged.append(buf)
        span = (s.get("end") or s["start"] + len(text) * 0.15) - s["start"]
        total = sum(len(m) for m in merged) or 1
        acc = 0.0
        for m in merged:
            out.append({"speaker": s["speaker"],
                        "start": s["start"] + span * (acc / total),
                        "text": m})
            acc += len(m)
    return out


def detect_lang(segs):
    t = "".join(s["text"] for s in segs[:12])
    cjk = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
    return "zh-TW" if cjk > len(t) * 0.2 else "en"


# ────────────────────────── 翻譯 ──────────────────────────
def translate(client, segs, src_lang, tgt_lang, glossary, extra_note):
    tgt_name = LANG_NAME.get(tgt_lang, tgt_lang)
    src_name = LANG_NAME.get(src_lang, src_lang)

    gloss = ""
    if glossary:
        gloss = ("\n【固定譯名】以下詞彙必須照這樣翻，不可自由發揮：\n"
                 + "\n".join(f"  {k} → {v}" for k, v in glossary.items()))

    tw_note = ""
    if tgt_lang == "zh-TW":
        tw_note = ("\n【用詞】必須用臺灣的說法，不可用中國大陸用語："
                   "計畫(非計劃)、專案(非項目)、核銷(非報銷)、影片(非視頻)、"
                   "資訊(非信息)、軟體(非軟件)、網路(非網絡)、列印(非打印)、"
                   "使用者(非用戶)、品質(非質量)、螢幕(非屏幕)。")

    # 整份的前情提要，讓模型知道這在講什麼
    overview = " ".join(s["text"] for s in segs)[:1500]

    out = {}
    dead = None      # 遇到重試也沒用的錯誤就記在這裡
    for i in range(0, len(segs), BATCH):
        chunk = segs[i:i + BATCH]
        payload = [{"i": i + j, "text": s["text"]} for j, s in enumerate(chunk)]
        prompt = f"""你是專業的會議文件翻譯。把下面這份{src_name}逐字稿翻成{tgt_name}。

【這份文件在講什麼】（僅供你理解脈絡，不要翻譯這段）
{overview}
{gloss}{tw_note}{extra_note}

【規則】
- 逐段翻譯，回傳的段數與 i 必須跟輸入**完全一致**（共 {len(chunk)} 段）。
- 不可合併段落、不可拆段、不可增刪內容、不可加註解。
- 這是口語逐字稿，翻譯要通順自然，但不可改變原意，也不要美化成書面語。
- 專有名詞（單位名、計畫名、人名、職稱）前後必須一致。
- 若某段只是語助詞或無意義，就照實翻，不要留空。

【待翻譯】
{json.dumps(payload, ensure_ascii=False, indent=1)}"""

        schema = {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["i", "text"]}}
        # 🔴 刻意保留 temperature=0，不照官方「3.x 不要設 temperature」的建議（2026-09-19 A/B）：
        #    同一份 60 分鐘逐字稿盲評，拿掉後句子較自然，但**專有名詞前後不一致從 7 個變 14 個**、
        #    術語錯誤 9→43 —— 每 25 段一批各自翻，溫度 1.0 時每一批挑的譯名不一樣。
        #    這支的用途是給外賓的正式文件，使用者裁示品質（一致性）優先、「A/B 通過才改」→ 不改。
        #    （工具 2 對齊、工具 3 準確模式的翻譯 A/B 沒有變差，那兩處已拿掉 temperature。）
        try:
            r = _retry(client.models.generate_content,
                       model=MODEL, contents=prompt,
                       config=types.GenerateContentConfig(
                           response_mime_type="application/json",
                           response_schema=schema, temperature=0))
            for d in json.loads(r.text):
                out[d["i"]] = unescape(d["text"])
            print(f"  Translated {min(i+BATCH, len(segs))}/{len(segs)} paragraphs")
        except KeyboardInterrupt:
            # V1.38 審查（#4）：等網路回來的時候（或任何時候）按 Ctrl+C，已經翻好的照樣存檔（以前整份丟掉、一個檔都不留，
            #    前面幾批的錢白花）。一段都還沒翻好就照舊直接中斷（沒有東西可存）。
            if not out:
                raise
            signal.signal(signal.SIGINT, signal.SIG_IGN)     # 審查第 2 輪：檔案寫完之前再按 Ctrl+C 不要打斷（main() 寫完就恢復）
            print("\n  ⚠ Ctrl+C pressed: stopping here; what has already been translated will still be saved.")
            dead = KeyboardInterrupt()
            break
        except Exception as e:
            # 🔴 這一批放棄，但不要讓整份翻譯陪葬。
            #    前面幾批的錢已經花了，硬要中止等於把使用者付過的東西丟掉。
            print(f"  ✗ Batch {i // BATCH + 1} could not be translated ({type(e).__name__}); these paragraphs stay blank for now, and you will be told at the end which are missing")
            if _permanent(e) or _net_down(e):
                # 🔴 額度用完／金鑰失效這種，繼續跑只是把剩下每一批都撞一次牆。
                #    兩小時的逐字稿有 56 批，一批一批撞完要十幾分鐘，
                #    而畫面上看起來像在工作。立刻收手，把已翻好的存下來。
                # V1.38：網路斷了的已經在 _retry 等過（同一次斷網最多 NET_WAIT_MAX 秒）還沒回來，才會走到這裡。
                #    「已經翻好的部分還是會存檔」只在真的有翻好的時候講（審查 #2）。
                dead = e
                kept = "; what has already been translated will still be saved" if out else ""
                if _net_down(e):
                    print(f"  ✗ The internet connection didn't come back (waited {NET_WAIT_MAX // 60} minutes), so stopping here{kept}.")
                else:
                    print(f"  ✗ Retrying will not fix this error, so stopping here{kept}.")
                break

    missing = [j for j in range(len(segs)) if j not in out]
    if missing and not dead:
        # dead 為真時不要補跑：那是逐段重試，1400 段會空轉好幾小時。
        print(f"  ⚠ {len(missing)} paragraph(s) were not translated; trying them again…")
        for j in missing:
            try:
                r = _retry(client.models.generate_content,
                           model=MODEL,
                           contents=f"把這句{src_name}翻成{tgt_name}，只回譯文：\n{segs[j]['text']}",
                           config=types.GenerateContentConfig(temperature=0))
                out[j] = unescape(r.text)
            except KeyboardInterrupt:
                if not out:
                    raise
                signal.signal(signal.SIGINT, signal.SIG_IGN)     # 同上
                print("\n  ⚠ Ctrl+C pressed: stopping here; what has already been translated will still be saved.")
                dead = KeyboardInterrupt()
                break
            except Exception as e:
                if _net_down(e):
                    # V1.38 審查（#9）：_retry 已經等滿 NET_WAIT_MAX 網路還沒回來——剩下的一段一段撞只是空轉，不補了
                    print(f"  ✗ The internet connection didn't come back (waited {NET_WAIT_MAX // 60} minutes), so the rest will not be retried.")
                    break
    still = [j for j in range(len(segs)) if j not in out]
    if still:
        print(f"  ⚠ {len(still)} paragraph(s) still could not be translated; they will be marked in the files.")
    return [out.get(j, "") for j in range(len(segs))], dead


# ────────────────────────── 輸出 ──────────────────────────
def hhmmss(t):
    return f"{int(t//3600):02d}:{int(t%3600//60):02d}:{int(t%60):02d}"


def srt_ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def write_outputs(stem, segs, trans, names, src_lang, tgt_lang, title, want_srt=False, meta=None):
    # 🔴 退回值不能是原始標籤。模型給的是 spk:0／spk:1，而這份檔案正是
    #    要寄給外賓的那一份 —— 講者欄整排 spk:0 很難看。
    #    退回值跟著譯文語言：三份輸出檔用同一張對照，編號一定一致。
    try:
        from json_to_md import speaker_list, generic_names, GENERIC_NAME
        spks = [sp for sp in speaker_list(segs) if sp]            # 數字排序（V1.22 ②，見 speaker_key）
        nm = generic_names(spks, tgt_lang)                          # 切段時第 2 段起「Part 2 Speaker 1」（③）
        if not names:
            # 🔴 2026-09-25（V1.22 ④）：沒填名字時沿用功能 2 存在 .json 裡的名字。以前一律 Speaker N，
            #    功能 2 填過的「主席、秘書」到這裡就不見了，要再填一次。只沿用使用者真的填過的；
            #    「講者1」這種功能 2 自己給的預設名，照譯文語言換成 Speaker 1。
            for sp, v in ((meta or {}).get("speakers") or {}).items():
                if sp in nm and v and not GENERIC_NAME.fullmatch(str(v)):
                    nm[sp] = v
    except ImportError:          # 同 load_json：少了 json_to_md.py 也要產得出檔（翻譯的錢已經付了）
        spks = sorted({s["speaker"] for s in segs if s["speaker"]})
        nm = {sp: speaker_fallback(tgt_lang, i + 1) for i, sp in enumerate(spks)}
    nm.update(zip(spks, names))

    # 1) 對照 Markdown
    md = [f"# {title}", "",
          f"- Source: {show_name(src_lang)}  Translation: {show_name(tgt_lang)}",
          f"- Paragraphs: {len(segs)}  Created: {time.strftime('%Y-%m-%d %H:%M')}", "", "---", ""]
    gap = sum(1 for t in trans if not t)
    if gap:
        # 沒翻到的段落一定要在檔案裡看得見，不能只在當下的畫面講一次。
        md[3:3] = [f"- ⚠ {gap} paragraph(s) could not be translated; they are marked \"(not translated)\" in the text. You can keep this .md and run it again later."]
    # 🔴 逐字稿本身的缺口警語要跟著過來（複查 major）：字樣與 transcribe_meeting／json_to_md 一致，
    #    menu 才判得到。三份 .md 都要有 —— 同事可能只拿其中一份去用。
    try:
        from json_to_md import warn_lines, note_lines
        src_warn = warn_lines(meta or {}, bool((meta or {}).get("partial")))
        src_note = note_lines(meta or {})      # V1.36：ℹ️ 說明照樣帶過來，但不算缺口（見 json_to_md.note_lines）
    except Exception:
        src_warn, src_note = [], []
    # 🔴 2026-09-21 筆電第四輪驗收 P0／P3：警語是 `> …` 引言區塊，**後面一定要有一行空行**。
    #    少了那一行，緊接著的內容會被當成引言的 lazy continuation 吞進去：
    #      _對照表.md → 整張 6 列表格變成引言裡的一段純文字，渲染出的 <table> 從 1 變 0，
    #                   而那份檔的用途就是「貼進 Word / Excel」；
    #      _<語言>.md → 第一段的講者標頭被吞進引言的最後一個項目符號。
    #    只有「逐字稿有缺口、而且翻譯本身沒有漏段」時才會發生（漏段那條分支自己有補空行），
    #    剛好是最需要謹慎的那一份。三個出口以前三種寫法，現在統一用 warn_block。
    warn_block = src_warn + src_note + [""] if src_warn or src_note else []
    md[4:4] = warn_block
    for s, t in zip(segs, trans):
        who = f" {nm.get(s['speaker'], s['speaker'])}" if s["speaker"] else ""
        md += [f"**[{hhmmss(s['start'])}]{who}**", "", f"> {s['text']}", "",
               t or "(not translated)", ""]
    io.open(stem + "_bilingual.md", "w", encoding="utf-8").write("\n".join(md))

    # 2) 對照表格（貼進 Word / Excel 用）
    # 🔴 缺口警語與佔位字要進**每一個**輸出檔。只放在 _對照.md 的話，
    #    同事單獨拿 _對照表.md 或純譯文版去用，看到的是一份看似正常、
    #    只是「有些段落沒講話」的文件，完全沒有線索說它不完整。
    tb = []
    tb += warn_block          # 🔴 一定要帶那一行空行，否則整張表被引言吞掉（見上面 P0 的註解）
    if gap:
        tb += [f"> ⚠ {gap} paragraph(s) could not be translated; the translation column shows \"(not translated)\".", ""]
    tb += ["| Time | Speaker | Source | Translation |", "|---|---|---|---|"]
    for s, t in zip(segs, trans):
        esc = lambda x: x.replace("|", "\\|").replace("\n", " ")
        tb.append(f"| {hhmmss(s['start'])} | {nm.get(s['speaker'], s['speaker'])} | {esc(s['text'])} | {esc(t or '(not translated)')} |")
    io.open(stem + "_bilingual_table.md", "w", encoding="utf-8").write("\n".join(tb))

    # 3) 雙語字幕軌（預設不產生：單獨點開只會跳出空的播放器，一般用不到）
    if want_srt:
        srt = []
        for i, (s, t) in enumerate(zip(segs, trans), 1):
            end = segs[i]["start"] if i < len(segs) else s["start"] + 5
            srt += [str(i), f"{srt_ts(s['start'])} --> {srt_ts(end)}", s["text"], t, ""]
        io.open(stem + "_bilingual.srt", "w", encoding="utf-8").write("\n".join(srt))

    # 4) 只有譯文的純淨版
    only = [f"# {title} ({show_name(tgt_lang)})", ""]
    only += warn_block        # 🔴 同 P0：少一行空行，第一段講者標頭會被引言吃掉
    # 🔴 2026-09-21 筆電第四輪驗收「觀察」：這份是要寄給外賓的，警語卻整段只有中文 ——
    #    收件人看不懂＝對他而言警語等於不存在，第四輪 major 的目的就打折了。
    #    這裡只補一行固定英文摘要（使用者裁示）；上面的中文原文保留，menu 仍靠中文字樣判 ✅／⚠。
    if src_warn and not tgt_lang.startswith("zh"):
        only += ["> **Note:** This transcript is incomplete — part of the recording was not "
                 "transcribed. The note above lists the missing time ranges.", ""]
    if gap:
        # 這份是要寄給外賓的「乾淨版」。沒有原文可以對照，空白段落跟
        #「這位講者沒講話」在視覺上完全一樣 —— 一定要標。
        only += [f"> ⚠ {gap} paragraph(s) could not be translated; they are marked \"(not translated)\" in the text. Please check before sending.", ""]
    for s, t in zip(segs, trans):
        who = f" {nm.get(s['speaker'], s['speaker'])}" if s["speaker"] else ""
        only += [f"**[{hhmmss(s['start'])}]{who}**", "", t or "(not translated)", ""]
    io.open(stem + f"_{tgt_lang}.md", "w", encoding="utf-8").write("\n".join(only))

    # 5) 機器可讀
    # 🔴 2026-09-21 筆電第四輪驗收 P1（第五個落點）：這份以前是**純陣列、沒有 meta**。
    #    純陣列正是 load_transcript() 刻意支援的舊格式路徑，會回 meta={} →
    #    同事在功能 5 的選檔視窗誤選它（桌面上兩個檔名只差「_對照」三個字、就躺在隔壁），
    #    會拿到一份「警語全失、畫面打 ✅」、看起來完整正常的逐字稿。
    #    改成跟逐字稿同一種格式，並加上 kind 讓功能 5 認得出來擋下（兩層保險）。
    json.dump({"meta": {**(meta or {}),
                        "kind": "translation-pair",
                        "translated_from": src_lang, "translated_to": tgt_lang,
                        "translated_at": time.strftime("%Y-%m-%d %H:%M")},
               "segments": [{**s, "translation": t, "translated": bool(t)}
                            for s, t in zip(segs, trans)]},
              io.open(stem + "_bilingual.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    made = ["_bilingual.md", "_bilingual_table.md", f"_{tgt_lang}.md", "_bilingual.json"]
    if want_srt:
        made.insert(2, "_bilingual.srt")
    return [stem + x for x in made]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="audio/video file, transcript .json, or captions .srt")
    ap.add_argument("--to", default=None, help="language to translate into: zh-TW / en / ja (detected automatically by default)")
    ap.add_argument("--vocab", nargs="*", default=[], help="proper nouns (used when the input is an audio file)")
    ap.add_argument("--names", nargs="*", default=[], help="speaker names")
    ap.add_argument("--glossary", nargs="*", default=[],
                    help="fixed translations, written as Chinese=English (Chinese=Japanese when translating into Japanese); several allowed")
    ap.add_argument("--note", default="", help="extra context (e.g. This is the Research Office's Sprout Project meeting)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--interim-out", dest="interim_out", default=None,
                    help="when the input is an audio file, where to write the intermediate transcript (the menu passes in a path worked out so it will not overwrite an existing file)")
    ap.add_argument("--srt", action="store_true",
                    help="also create an .srt caption track (only needed if you want to add it to a video)")
    a = ap.parse_args()

    if not os.path.exists(a.input):
        print(f"✗ File not found: {a.input}"); sys.exit(1)

    import _apikey
    key = _apikey.for_script()         # 環境變數沒有就讀記住的那一組（2026-09-20 N6-3），都沒有就中文說明
    # 🔴 空字串也要擋（2026-09-20 筆電 ⚠-4）：變數存在但被清空時，拿空金鑰去連網
    #    只會得到「金鑰可能打錯」這種誤導訊息。見 _apikey.for_script 的說明。
    if not key:
        sys.exit(2)
    client = genai.Client(api_key=key)
    ext = os.path.splitext(a.input)[1].lower()
    base_out = None

    if ext in AUDIO_EXT:
        segs, base_out = from_audio(a.input, a.vocab, a.names,
                                    os.path.dirname(os.path.abspath(a.out))
                                    if a.out else None,
                                    a.interim_out)
        # 剛轉好的那份逐字稿如果有缺口，雙語對照也要標（複查 major）
        meta = load_meta(os.path.splitext(base_out)[0] + ".json")
    elif ext == ".json":
        segs, meta = load_json(a.input), load_meta(a.input)
        if '.partial.' in os.path.basename(a.input):
            meta = dict(meta, partial=True)      # 救回來的殘稿：三份輸出檔都要標
    elif ext == ".srt":
        segs, meta = load_srt(a.input), {}
    else:
        print(f"✗ Unsupported format {ext} (supported: audio/video, .json, .srt)"); sys.exit(1)

    if not segs:
        print("✗ No paragraphs were read"); sys.exit(1)

    n0 = len(segs)
    segs = split_long(segs)
    if len(segs) != n0:
        print(f"▸ Long paragraphs were split at sentence breaks: {n0} → {len(segs)} paragraphs")

    src = detect_lang(segs)
    tgt = a.to or ("en" if src == "zh-TW" else "zh-TW")
    print(f"▸ {len(segs)} paragraphs  {show_name(src)} → {show_name(tgt)}")

    glossary = {}
    orphan = [g for g in a.glossary if "=" not in g]
    if orphan:
        # 上游切壞了才會有這種碎片。靜默丟掉會讓「深耕計畫→Higher」看起來很正常。
        fmt = "Chinese=Japanese" if (tgt or "").replace("_", "-").split("-")[0].lower() == "ja" else "Chinese=English"
        print(f"  ⚠ Could not understand these, so they were skipped (fixed translations must be written as {fmt}): {orphan}")
    for g in a.glossary:
        if "=" in g:
            k, v = g.split("=", 1)
            glossary[k.strip()] = v.strip()
    if glossary:
        print(f"  {len(glossary)} fixed translation(s)")

    note = f"\n【補充脈絡】{a.note}" if a.note else ""
    print("▸ Translating…")
    trans, dead = translate(client, segs, src, tgt, glossary, note)

    stem = a.out or os.path.splitext(base_out or a.input)[0]
    title = os.path.basename(stem)
    ok_n = sum(1 for t in trans if t)
    # 🔴 輸入是音檔時，名字已經由 transcribe_meeting 套好、存在中繼稿的 meta 裡（切段時只套第 1 段，V1.22 ③）；
    #    這裡再照順序套一次，名字比第 1 段的人多時，多的會溢到第 2 段的講者身上。改成讀 meta 的。
    try:
        files = write_outputs(stem, segs, trans, [] if ext in AUDIO_EXT else a.names, src, tgt, title,
                              want_srt=a.srt, meta=meta)
    finally:
        if isinstance(dead, KeyboardInterrupt):
            signal.signal(signal.SIGINT, signal.default_int_handler)   # 檔案寫完（或寫檔出錯）都恢復 Ctrl+C（審查第 2、3 輪）

    # 🔴 一段都沒翻成功就**不是**完成。
    #    D2 把每批的例外都吞掉之後，額度用完也會照樣產出一份「全是
    #    （這段沒翻到）」的檔案，回傳碼還是 0 —— 選單看到檔案存在就印
    #    綠色 ✅，同事以為成功、把音檔再跑一次，付第二次轉錄費。
    #    2026-09-10 稽核抓到，這是 D2 自己造成的。
    if isinstance(dead, KeyboardInterrupt) and ok_n < len(trans):
        # V1.38 審查（#4）：按了 Ctrl+C、已經有翻好的段落（translate() 一段都沒翻好時照舊直接中斷）——存好了，照實講、回傳 1（沒有完成）。
        #    第 2 輪：Ctrl+C 剛好在全部翻完之後才到 → 照完成處理（往下走）
        print(f"\n⚠ Interrupted: of {len(trans)} paragraphs, {ok_n} were translated; the untranslated ones are marked in the files:")
        for f in files:
            print(f"   {f}")
        return 1
    if ok_n == 0:
        print("\n✗ Not a single paragraph was translated; the files produced contain no translation.")
        if dead is not None:
            _explain(dead)
        print("   Files already created (they contain the source text + markers showing what is missing):")
        for f in files:
            print(f"   {f}")
        return 1
    if ok_n < len(trans):
        print(f"\n⚠ Partly done: {len(trans) - ok_n} of {len(trans)} paragraphs were not translated; they are all marked in the files.")
    else:
        # 🔴 2026-09-21 筆電第四輪驗收 P2：這裡本來**無條件**印「✅ 完成」，只看「翻譯有沒有漏段」，
        #    不看「來源逐字稿完不完整」。經選單跑還有 menu 那層的 ⚠ 收尾，但**直接用命令列跑這支**
        #    時畫面上只有 ✅、一個字都沒提不完整。比照 json_to_md.py 的收尾，把來源警語納入判斷。
        try:
            from json_to_md import warn_lines
            src_warn = warn_lines(meta or {}, bool((meta or {}).get("partial")))
        except Exception:
            src_warn = []
        if src_warn:
            # V1.26（C1）：主控台不吃 Markdown，原本的 ** 會原樣印成星號
            print("\n⚠ The translation is finished, but the original transcript was already incomplete (the reasons are also in the header of the output files):")
            for line in src_warn:
                if line.startswith("> - "):
                    print(f"   ⚠ {line[4:]}")
            print("   Before sending anything out, check the missing time ranges listed in the header. Output files:")
        else:
            print("\n✅ Done:")
    for f in files:
        print(f"   {f}")
    return 0


def _explain(exc):
    """
    把例外翻成同事看得懂的中文。

    🔴 _live.diagnose() 本來只接在三支即時字幕上，功能 2／4 遇到額度用完或
       金鑰失效時只會噴英文 traceback —— 而那正是最需要看懂的兩個情況。
    """
    # 🔴 只有「API 呼叫的例外」才交給 diagnose。
    #    CalledProcessError 的訊息裡包含完整命令列（含檔名），使用者的檔名
    #    只要出現 429／401／403 就會被誤判成「額度用完」「金鑰有問題」。
    need, title, hint = False, "", ""
    if not isinstance(exc, subprocess.SubprocessError):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _live import diagnose, net_down, NET_DOWN_TITLE
            need, title, hint = diagnose(exc)
            if not need and net_down(exc):
                # V1.38 審查第 2 輪：「網路無法連線」那三種（10050／10051／10065）diagnose 不算要人介入，但走到這裡已經等滿
                #    NET_WAIT_MAX 網路還沒回來——照「連不到網路」講，不要印英文技術錯誤叫人跑診斷
                need, title, hint = True, NET_DOWN_TITLE, "The internet connection didn't come back.\n      → Run the translation again once the network is working"
        except Exception:
            pass
    print()
    if need:
        print(f"  \u2717 {title}")
        print(f"      {hint}")
    else:
        print(f"  ✗ An error occurred: {type(exc).__name__}: {exc}")
        print("      If this makes no sense, double-click 6_Diagnostics.bat and send a screenshot of the whole window.")
    return 1

if __name__ == "__main__":
    try:
        _code = main() or 0
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        _code = 1
    except SystemExit as e:
        # 🔴 不要寫成 `e.code or 1`：那會把 sys.exit(0)（成功）也變成 1。
        #    目前程式裡的 sys.exit 都不是 0（1，或沒有金鑰時的 2），所以還沒出事，但這是留給未來的陷阱。
        _code = 1 if e.code is None else e.code
    except Exception as _e:
        _code = _explain(_e)
    sys.exit(_code)
