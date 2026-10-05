# -*- coding: utf-8 -*-
"""
即時雙語字幕【準確模式】

跟 live_bilingual.py（快速模式）的差別在**翻譯的時機**：

  快速模式：用同步口譯模型，它邊聽邊翻。延遲約 1 秒，但語序常卡住
            （「增加了國際合作率 15%今年」）——因為翻的當下還沒聽到後面。

  準確模式：只用轉錄模型拿原文，自己判斷「這句講完了」，
            整句才丟給文字模型翻。延遲多幾秒，但語序是正常中文。

判斷「講完了」的方法：
  轉錄模型的 interim 字幕約 1 秒就到，而且會累積、改寫。
  當 interim 裡出現句號/問號，而且**後面又長出新的字**，
  代表模型已經講到下一句了 → 前面那句幾乎不可能再改 → 可以送翻譯。
  （另有逾時保底：講者停頓超過 settle 秒也送出。）
"""
import os, sys, io, re, asyncio, argparse, time, queue, threading, signal, logging

if __name__ == "__main__":          # 被 import 時不要動 stdout，否則會互相關閉
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

# 🔴 2026-09-20 筆電實測（P0）：Windows 11 的智慧型應用程式控制（Smart App Control）會擋下剛裝好、
#    還沒有雲端信譽的未簽章 DLL，scipy 的 _ufuncs_cxx.pyd 就中過（CodeIntegrity 事件 3118／3077）。
#    舊版在這裡直接丟英文 ImportError: DLL load failed，同事看到的是一整段 traceback，
#    而 6_診斷.bat 同時說 scipy OK。改成中文說明＋離開碼 2（同「沒有金鑰」那條路）。
#    🔴 同一件事的落點：live_caption.py／live_bilingual.py／live_bilingual_hq.py 各一份、
#    以及 _selfcheck.py 的 IMPORT_CHECK（診斷那邊要一起判得出來），改字要一起改。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 🔴 2026-09-22（S1）：_blockhint 是 P2 引進的硬相依，而這一行就排在 _need() 上面 ——
#    _need() 的存在目的正是「不要讓同事看到英文 traceback」，它自己卻可能先炸。
#    少了這個檔＝解壓不完整，講清楚並以離開碼 2 收場（同「沒有金鑰」那條路）。
#    ⛔ 不在這裡放備援關鍵字清單：那等於把 P2 剛收斂掉的四份拷貝又長回來。
try:
    from _blockhint import classify, BLOCKED, MISSING     # noqa: E402
except ImportError:
    print("\n  ✗ The program file scripts\\_blockhint.py is missing; this tool's files are incomplete.")
    print("     → Please extract the whole folder again, or double-click 3_Install.bat again.")
    print("     → To find out what else is missing, double-click 6_Diagnostics.bat and look at the [Files] section.")
    raise SystemExit(2)

_NEED_SEEN = set()


def _need(what, fn):
    """匯入一個會載入原生 DLL 的套件；被擋或壞掉時給中文說明，不要讓同事看到英文 traceback。

    🔴 2026-09-20 筆電實測（P0）：Windows 11 的智慧型應用程式控制會擋下剛裝好、還沒有雲端信譽的未簽章 DLL
       （CodeIntegrity 事件 3118／3077，scipy 的 _ufuncs_cxx.pyd 中過），而 6_診斷.bat 同時說 OK。
    🔴 複查指出：只保護 scipy 不夠 —— numpy 與 google-genai 同樣載原生元件，任何一個被擋，
       畫面一樣會是英文 traceback。所以三個都走這一支。
    🔴 「被擋」與「根本沒裝」要分開講：沒裝就叫他重跑安裝檔，等幾分鐘沒有用。
    """
    # 🔴 2026-09-21 筆電實測：冷啟時 scipy 要 27~38 秒、google-genai 要 10 秒，這段期間畫面
    #    完全沒有變化（menu.run() 又已經先印了「進行中」），使用者以為當掉了。先報名稱再載入、
    #    載完補耗時，讓人看得出來卡在哪一顆。熱啟時每顆都是 0.x 秒，不會洗版。
    #    google-genai 會被要兩次（genai 與 types），第二次是現成的，不要重印一行。
    _show = what not in _NEED_SEEN
    _NEED_SEEN.add(what)
    if _show:
        print(f"  · {what}…", end="", flush=True)
    _t0 = time.time()
    try:
        _r = fn()
        if _show:
            print(f" ✓ {time.time() - _t0:.1f} s")
        return _r
    except ImportError as e:
        msg = str(e)
        # 🔴 2026-09-22（P2）：判斷改由 _blockhint.classify() 統一負責。
        #    原本這裡、另外兩支腳本、_selfcheck.py 各有一份關鍵字清單，已經漂到不一致。
        blocked = classify(msg) == BLOCKED
        print(f"\n  ✗ {what} could not be loaded: {msg}")
        if blocked:
            print("     Windows \"Smart App Control\" may be temporarily blocking a package that was just installed; it usually lets it through by itself within a few minutes.")
            print("     Please wait a moment and try again.")
            # 🔴 2026-09-22（S7）：關鍵字含 "blocked by"／"0x800704ec"，而那也涵蓋
            #    **群組原則封鎖**（英文正是 "blocked by group policy"）—— 那是永久的。
            #    只叫人「稍等」會讓被單位政策鎖住的機器一直空等，給一條退路。
            print("     If it is still the same after more than 10 minutes, it is not a temporary block (your organisation's IT policy may be locking it),")
            print("     so please take a screenshot of this screen and contact your organisation's IT staff.")
        elif classify(msg) == MISSING:
            print("     This package is not installed on this PC → please double-click 3_Install.bat again.")
        else:
            print("     This package is installed but cannot be loaded (wrong version or damaged files) → please double-click 3_Install.bat again.")
        print("     If it keeps failing, double-click 6_Diagnostics.bat and send a screenshot of the whole window.")
        raise SystemExit(2)


np = _need("Numeric computing component (numpy)", lambda: __import__("numpy"))
resample_poly = _need("Audio processing component (scipy)",
                      lambda: __import__("scipy.signal", fromlist=["resample_poly"]).resample_poly)

genai = _need("Google connection component (google-genai)",
              lambda: __import__("google.genai", fromlist=["genai"]))
types = _need("Google connection component (google-genai)",
              lambda: __import__("google.genai.types", fromlist=["types"]))

# 🔴 翻譯器呼叫 generate_content 時 SDK 會印英文警告（AFC…），同事看到會以為出錯了。
logging.getLogger("google_genai").setLevel(logging.ERROR)

ASR_MODEL = "gemini-3.5-transcribe-live"
MT_MODEL = "gemini-3.5-flash-lite"   # 實測 0.73s／句；flash 要 2~5s 且會 503
# V1.38（10-05 X7h）：翻一句最多等幾秒。平常一句 0.5～1.3 秒；Google 偶爾一次呼叫卡住 50 秒以上（X7h 實測 51 秒），
#    後面每一句都排在它後面一起卡住、字幕整個停住。等不到就放棄這一次、重試（translate_line 最多三次）。
MT_TIMEOUT = 12
LATE_MT = "(not translated by the time it stopped)"      # V1.38（X7h）：收尾時翻譯還沒回來的句子，譯文欄寫這個（原文照樣存）
try:      # 連線層的單次逾時：卡住的那一次直接放棄、不留著佔背景執行緒（收尾時最多再等它 MT_TIMEOUT 秒）。套件不支援就只靠 translate_line 的總時限
    _MT_HTTP = {"http_options": types.HttpOptions(timeout=MT_TIMEOUT * 1000)}
    types.GenerateContentConfig(**_MT_HTTP)
except Exception:
    _MT_HTTP = {}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _live import (Reconnect, DropWatch, SentenceGate, SilenceGate,     # noqa: E402
                   on_console_close, open_live, quiet_async_noise, mix_lanes, MIX_GRACE, SENT_CLOSE,
                   RotateWhenQuiet, capture_mic, capture_loopback, font_hint, source_line,
                   note_caption, start_level_watch, gate_floor, rotate_opts, Leveler, final_extend,
                   join_capture, keep_open, forget_open, close_open, number_fixes, long_interim)
# 🔴 SentenceGate（切句，吃文字）與 SilenceGate（靜音閘門，吃音訊）名字只差兩個字母，
#    而本檔的區域變數 `gate` 早就是 SentenceGate。靜音閘門一律叫 `silence_gate`，不要混。

TARGET_SR = 16000
CHUNK_MS = 100
ROTATE_GRACE = 3.0       # 輪替時等最後一句定稿的寬限秒數
SESSION_SOFT_LIMIT = 8 * 60

DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"
SRC_C, TGT_C, YEL = "\033[38;5;250m", "\033[36m", "\033[33m"

# 🔴 給 menu.py 判讀用的固定標記，不是給人看的說明文字。
#    使用者在「等聲音來源開好」那段期間按 Ctrl+C 取消時，這一行會原封不動印在 stdout 上
#    （純 ASCII、自己一行、不帶顏色碼），父行程用子字串比對就分得出「使用者自己取消」與「出錯了」。
#    為什麼不用離開碼：見下面取消分支裡的說明（從選單進來時 130 會被吃成 0）。
#    三支 live 腳本用同一個字串，改的時候三支要一起改（開發端的 test_r2_live_review.py ⑧ 會比對，該檔不隨附）。

LANG_NAME = {"zh-TW": "臺灣繁體中文", "en": "English", "ja": "日本語"}
# V1.30：開場圖例「顯示用」的語言名稱。LANG_NAME 的 zh-TW 會放進翻譯提示詞，不能為了顯示去改它
# （英文版要把顯示改成英文，只換這一張；中文版兩張的字一樣，畫面不變）。
SHOW_NAME = {"zh-TW": "Traditional Chinese (Taiwan)", "en": "English", "ja": "Japanese"}

# 🔴 只放「在臺灣幾乎不可能有別的意思」的詞。
# 刻意不放的：項目(→專案 會把「項目會議」誤傷)、計劃(在臺灣當動詞是對的)、通過、同行、數據、
#             程序(程序正義是正確用法)、質量(物理的質量)、登錄(法律用語)、菜單。
# 那些交給提示詞去處理，不要硬換。
# 🔴 這張表跟 live_bilingual.py 的那張必須一模一樣（開發端的 test_to_tw_scope.py 會比，該檔不隨附）。
TW_TERMS = {
    # 🔴 多字詞放前面：替換是照順序做的，「視頻會議」要先變「視訊會議」，不能被後面的「視頻→影片」搶走。
    "視頻會議": "視訊會議", "視頻通話": "視訊通話", "視頻": "影片", "音頻": "音訊",
    # 🔴「互聯網絡」要排在「互聯網」與「網絡」之前，不然會多一個字：先被「網絡」換成「互聯網路」，
    #    再被「互聯網」換成「網際網路路」（2026-09-15 複查 R2-1 實測：中國互聯網絡信息中心 → 中國網際網路路資訊中心）。
    "軟件": "軟體", "硬件": "硬體", "互聯網絡": "網際網路", "互聯網": "網際網路", "網絡": "網路",
    "屏幕": "螢幕", "鼠標": "滑鼠", "打印": "列印", "激光": "雷射",
    # 🔴「在線服務器」要排在「服務器」之前：先換「服務器」會把「在線服務」拆掉，只剩沒換完的「在線伺服器」。
    "信息": "資訊", "數據庫": "資料庫", "在線服務器": "線上伺服器", "服務器": "伺服器", "文件夾": "資料夾",
    "用戶": "使用者", "報銷": "核銷", "硬盤": "硬碟", "U盤": "隨身碟",
    "筆記本電腦": "筆記型電腦", "智能手機": "智慧型手機", "移動設備": "行動裝置",
    "郵箱": "信箱", "鏈接": "連結", "反饋": "回饋", "缺省": "預設",
    "博客": "部落格", "搜索引擎": "搜尋引擎",
    # 刻意不放（會誤傷別的詞）：內存(體內存在)、高清(提高清潔度)、光標(曝光標準)、短信(簡短信件)
    # 「在線」單獨不能換（「現在線上」會被誤傷），只換確定的組合
    "在線平台": "線上平台", "在線課程": "線上課程", "在線會議": "線上會議", "在線報名": "線上報名",
    "在線申請": "線上申請", "在線表單": "線上表單", "在線學習": "線上學習", "在線教學": "線上教學",
    "在線服務": "線上服務", "在線繳費": "線上繳費", "在線門戶": "線上入口網站",
}


def _quiet_remove(p):
    """刪暫存檔，刪不掉就算了——不要為了清檔案讓程式爆掉。"""
    try:
        os.remove(p)
    except Exception:
        pass


def need_ffmpeg():
    """
    🔴 ffmpeg 不在就先擋下來，不要讓使用者看到英文 traceback。

    安裝精靈刻意容忍 ffmpeg 裝失敗（記一筆失敗然後繼續），所以真的會有人在
    沒有 ffmpeg 的情況下走到這裡。另外 winget 剛裝好時，舊視窗的 PATH 還是
    舊的，也會找不到 —— 那種情況只要開新視窗就好，訊息要講清楚。
    """
    from shutil import which
    if which("ffmpeg") and which("ffprobe"):
        return True
    print("\n  ⚠ ffmpeg was not found on this PC (it is required to process audio)")
    print("     → If you have only just installed it: close this window and double-click 4_Start.bat again")
    print("       (a newly installed program is only found in a newly opened window)")
    print("     → If it still can't be found: run 3_Install.bat again")
    print("     → To check: double-click 6_Diagnostics.bat and look at the [ffmpeg] line")
    return False


def to_tw(t):
    for a, b in TW_TERMS.items():
        t = t.replace(a, b)
    return t


# ─────────────── 翻譯：提示詞組裝＋譯文語言檢查（模組層級，可用假 client 離線測試）───────────────
# 🔴 2026-09-11 稽核：準確模式翻日文，9 句有 2 句譯成中文。原因是提示詞整段中文
#    （指令、前文標頭、切斷／接續提示、句子標頭），只有「日本語」三個字是日文，
#    flash-lite＋MINIMAL＋溫度 0 會被提示詞的語言拉走。真實 API 對照（同句同參數）：
#    中文框架 ja 語言錯 7/216 → 日文框架 2/216；en 兩者都是 0/88。
# 🔴 換框架還不能歸零：講者說中文、翻日文時，偶爾把中文原句照抄回來（第三輪 V3 首輪 3/216：
#    2 次整句中文、1 次「中文原句＋--->＋日文」並列）。所以再加兩道檢查，錯了就換加註的提示詞補問一次：
#    ① mt_wrong_lang：整句不是目標語言　② echoes_source：譯文裡整段抄了原文（連續 8 個漢字相同）。
#    ② 是複查才補上的：並列的回答有假名，① 會當成正常日文放過（原本寫的「補問後 0/216」是 ① 自己量自己）。
#    兩道合起來在三輪 1753 筆真實譯文裡抓到的 12 筆全是真的照抄或整句中文，0 誤抓。
# 🔴 zh 開頭（zh-TW 等）、cmn、yue 與選單以外的語言碼：提示詞一個字都沒改，也不檢查、不補問。
#    zh-TW 是同事最常用的路；開發端的 scripts/test_mt_prompt.py 會驗逐字相同（該檔不隨附）。
# 🔴 溫度 0 不保證每次輸出一樣（同一提示詞跑 4 次，24/29 個出現不同輸出）：抽測幾次沒錯≠修好了。
_SENT_END = (".", "!", "?", "。", "！", "？")

_MT_FRAME = {
    "zh": {     # 原本 translator() 裡的中文框架，逐字未改（改它＝改 zh-TW）
        "head": "把這一句翻成{name}。只回譯文，不要加任何說明或引號。",
        "ctx": "\n前文（僅供理解脈絡，不要翻譯）：\n",
        # 🔴 這一句是「很長的句子被迫切成兩半」的其中一半。不講清楚的話，
        #    模型會把 "month." 單獨翻成「個月」、"five-year projections." 翻成「五年預測」。
        "frag": ("\n\n⚠ 這段話還沒講完就被切斷了，後面還有。"
                 "請翻成一個「未完成、後面還會接下去」的句子，不要硬加句號收尾。"),
        "cont": ("\n\n⚠ 上一句被切斷了，這一句是它的**後半段**。"
                 "請當成接續來翻，翻出來要能直接接在前一句後面，"
                 "不要當成獨立句子，也不要重複前半段的內容。"),
        "retry": "",            # zh 不檢查、不補問，用不到
        "tail": "\n\n要翻譯的句子：\n",
    },
    # ja／en：都是實測過的原文（實驗腳本在 dev/exp_hq_lang/，會打真實 API），要改請先重跑實測
    "ja": {
        "head": ("次の文を日本語に訳してください。訳文だけを返し、説明や引用符は付けないでください。"
                 "必ず日本語で書いてください。"),
        "ctx": "\n前の文（文脈を理解するためだけのもの。訳さないこと）：\n",
        "frag": ("\n\n⚠ この文は途中で切れていて、後に続きがあります。"
                 "「まだ終わっていない、後に続く」文として訳し、無理に句点で終わらせないでください。"),
        # 🔴 最早的寫法「前の文にそのままつながるように訳し…」實測會把前文內容併進譯文：
        #    "with experienced principal investigators." 8/8 次捏造出前文才有的「15%」
        #    （6 次「引き上げる」、2 次「削減」，意思相反）。所以明講「只譯這一句、不要把前文的數字名字補進來」。
        "cont": ("\n\n⚠ 前の文は途中で切れていて、この文はその後半です。"
                 "訳すのは「訳す文」に書かれている内容だけにしてください。"
                 "前の文の内容（数字や名前も含む）を訳文に足さないでください。"
                 "前の文の訳のすぐ後ろにつながる形（文の途中から始まる形）で訳し、"
                 "独立した文にしないでください。"),
        "retry": ("\n\n（注意：前回の答えは日本語になっていませんでした。"
                  "中国語や英語の原文をそのまま返さず、必ず日本語に訳してください。）"),
        "tail": "\n\n訳す文：\n",
    },
    "en": {
        "head": ("Translate the following sentence into English. "
                 "Reply with the translation only, with no explanations or quotation marks."),
        "ctx": "\nPrevious sentences (for context only; do not translate them):\n",
        "frag": ("\n\n⚠ This sentence was cut off and continues later. Translate it as an unfinished "
                 "sentence that will be continued; do not force a full stop at the end."),
        "cont": ("\n\n⚠ The previous sentence was cut off, and this is its second half. Translate it so "
                 "that it follows on directly from the previous sentence, not as a standalone sentence, "
                 "and do not repeat the first half."),
        "retry": ("\n\n(Important: your previous answer was not in English. "
                  "Do not return the original text; reply in English only.)"),
        "tail": "\n\nSentence to translate:\n",
    },
}

# 🔴 這裡只列「詞義固定、不會誤導」的對照（只有 zh-TW 會加）。
#    原本寫了「專案(非項目)」，結果模型把 session 也翻成「專案會議」——
#    提示詞列得太積極，反而會把不相干的字硬拉過去。
_TW_NOTE = ("\n請用臺灣的中文用語習慣（例如 影片而非視頻、資訊而非信息、"
            "軟體而非軟件、核銷而非報銷）。用詞要自然，不要硬套。")


def _lang_base(target):
    """語言碼的主標籤：ja-JP／ja_JP／JA → ja；zh-TW → zh。"""
    return (target or "").replace("_", "-").split("-")[0].lower()


def is_zh_target(target):
    """譯文是中文（zh…、cmn…、yue…）才做臺灣用語替換；沒給語言碼照舊替換。

    🔴 英文、日文譯文裡剛好出現 TW_TERMS 的漢字時，換掉就改掉了原意（2026-09-14 使用者核准修正）。
       live_bilingual.py 有同一條規則，兩邊要一起改。
    """
    base = _lang_base(target)
    return not base or base in ("zh", "cmn", "yue")


def _mt_frame(target):
    """回傳 (框架, 放進指示句的語言名稱)。只有 ja、en 換框架，其餘沿用原本的中文框架。"""
    base = _lang_base(target)
    if base in ("ja", "en"):
        return _MT_FRAME[base], ""
    # 🔴 選單以外的語言碼（ko、fr…）刻意維持原樣：別的框架沒有實測過，不動它。
    return _MT_FRAME["zh"], LANG_NAME.get(target, target)


def build_mt_prompt(target, s, ctx, frag=False, retry=False):
    """組一句的翻譯提示詞。純字串、不連網。

    target：--target　s：要翻的句子　ctx：之前送翻過的原文
    frag：SentenceGate 硬切出來的前半句　retry：譯文語言不對時補問用的加註版
    """
    p, name = _mt_frame(target)
    # 🔴 先剝掉收引號／收括號再看有沒有句尾標點：斷句器會把「…kill switch."」「他說：「好。」」整句連引號送出，
    #    不剝的話這種完整句會被當成被切斷，下一句就被當接續去翻（2026-09-19 審查）。
    cont = not frag and bool(ctx) and not ctx[-1].rstrip().rstrip(SENT_CLOSE).endswith(_SENT_END)
    # 🔴 ja／en 的「接續句」（上一句沒有句尾標點：多半是 SentenceGate 硬切，也可能是講者停頓時送出的
    #    半句），前文只帶上一句。帶兩句的話，模型會把更前面那句的內容併進譯文：
    #    "with experienced principal investigators." 8 次裡 7 次多出更前面那句才有的「今年度」（this year），
    #    還自己補上「導入し、」把幾句硬接成一句（舊中文框架也 8/8 補出「導入」）；
    #    只帶上一句後兩者都 0/8（2026-09-11 第三輪實驗）。
    #    zh 框架維持原本的「前兩句」——zh-TW 一個字都不能變。
    use = ctx[-1:] if (cont and p is not _MT_FRAME["zh"]) else ctx[-2:]
    hint = (p["ctx"] + "\n".join(use)) if ctx else ""
    if frag:
        hint += p["frag"]
    elif cont:
        hint += p["cont"]
    tw = _TW_NOTE if target == "zh-TW" else ""
    note = p["retry"] if retry else ""
    return p["head"].format(name=name) + tw + hint + note + p["tail"] + s


# ── 譯文語言檢查：只抓「整句變成中文／原文照抄」，不評翻譯好壞，也看不出捏造的內容 ──
_KANA = re.compile("[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fd-\u30ff"
                   "\u31f0-\u31ff\uff66-\uff9d]")          # 刻意不含 ・(30FB) 與 ー(30FC)
_HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN = re.compile("[A-Za-z\u00c0-\u024f]")
# 「10月」「15日」「第1回」：中日文寫法一樣，判斷不了，先拿掉再數漢字
_NUM_UNIT = re.compile("[0-9０-９]+[ 　]*"
                       "[年月日時分秒回号號件名人位個个円元点點歳岁週周期次章条條項项]")


def _ja_only_kanji(ch):
    """日文新字體專用字（価 関 対 発 続 奨 応…）：Shift-JIS 編得出來，Big5 與 GB2312 都編不出來。

    🔴 用編碼表判斷，不要手列：手列時的「伝」「捗」實測 Big5 也有。
    """
    try:
        ch.encode("cp932")
    except UnicodeEncodeError:
        return False
    for enc in ("cp950", "gb2312"):
        try:
            ch.encode(enc)
            return False
        except UnicodeEncodeError:
            pass
    return True


def mt_wrong_lang(target, text):
    """譯文「明顯不是目標語言」才回 True（→ 補問一次）。

    ja：沒有假名、沒有「々」、沒有日文專用字，而且漢字 ≥2（先扣掉「數字＋單位」）→ 當成中文；
        沒有假名也沒有漢字、英文字母 ≥8 → 當成英文原文照抄。
    en：漢字＋假名 ≥2，而且不少於英文字母的一半 → 當成中文／日文。
    其他（含 zh-TW）一律 False。誤抓的代價只是多問一次（約 0.7 秒），補問不對就用回第一次的答案。
    已知誤抓：沒有日文專用字的純漢字日文（会議、東京大学、以上。）會被當成中文——多問一次，
    補問若回了帶假名的另一種譯法，會換成那一個（一樣是日文）。
    🔴 不要用「GB2312 編得出、Big5 編不出＝簡體」判日文：日文新字體會被當成簡體。
    """
    base = _lang_base(target)
    if not text or base not in ("ja", "en"):
        return False
    body = _NUM_UNIT.sub("", text)
    han = _HAN.findall(body)
    if base == "ja":
        if _KANA.search(text) or "々" in text or any(_ja_only_kanji(c) for c in han):
            return False
        return len(han) >= 2 or (not han and len(_LATIN.findall(text)) >= 8)
    cjk = len(han) + len(_KANA.findall(body))
    return cjk >= 2 and cjk * 2 >= len(_LATIN.findall(text))


_HAN_RUN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_ECHO_MIN = 8


def _han_grams(text, n):
    """text 裡所有「連續 n 個漢字」的片段（先扣掉「數字＋單位」，標點會把漢字串切開）。"""
    grams = set()
    for run in _HAN_RUN.findall(_NUM_UNIT.sub("", text)):
        for i in range(len(run) - n + 1):
            grams.add(run[i:i + n])
    return grams


def echoes_source(target, text, src):
    """譯文裡整段抄了原文（連續 8 個以上漢字跟原文相同）→ True（→ 補問一次）。

    🔴 mt_wrong_lang 看不到這種：模型回「中文原句＋--->＋日文」時有假名，會被當成正常的日文
       （2026-09-11 複查抓到，第三輪 V3 有 1/216 次）。只看 ja／en；原文沒有漢字（英文演講）時永遠 False。
       門檻 8：三輪 1753 筆真實譯文觸發 12 筆，全是真的照抄或整句中文，0 誤抓；
       正常日文譯文跟中文原文最長只共用 5 個字左右（例如「10月31」「会計室」）。
    """
    if _lang_base(target) not in ("ja", "en"):
        return False
    grams = _han_grams(src, _ECHO_MIN)
    return bool(grams) and bool(grams & _han_grams(text, _ECHO_MIN))


def _mt_request(client, prompt):
    """呼叫翻譯模型；獨立出來是為了能塞假 client 離線測試。

    🔴 不設 temperature（2026-09-19 拿掉原本的 0）：官方 3.5 指南要求 3.x 模型把 temperature／top_p／top_k
       從請求整個拿掉，低於 1.0 可能跳針或變差；拿掉前用同一批 34 句做過譯文盲評（不分軒輊，重大錯誤 2→0）。
    """
    return client.models.generate_content(
        model=MT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL),
            **_MT_HTTP))


async def translate_line(client, target, s, ctx, frag, pause=asyncio.sleep, stats=None):
    """翻一句，回傳要顯示的譯文（三次都失敗時是「（翻譯失敗 …）」）。pause 只給測試換掉用。
    stats（dict）給了的話，三次都失敗時 stats["failed"] 加 1（V1.38 審查第 4 輪：收尾照實講有幾句沒有譯文、不打 ✅）。"""
    prompt = build_mt_prompt(target, s, ctx, frag)
    # 這些模型偶發 ServerError／連線問題，重試就好（實測過）
    g, err = "", None
    for attempt in range(3):
        try:
            # V1.38（X7h）：總時限是保險（連線層的單次逾時沒生效時，也不會一句卡住、後面全部跟著停）
            r = await asyncio.wait_for(asyncio.to_thread(_mt_request, client, prompt), MT_TIMEOUT + 3)
            g = (r.text or "").strip()
            if g:
                break
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:60]}"
            await pause(0.4 * (attempt + 1))
    if not g:
        if stats is not None:
            stats["failed"] = stats.get("failed", 0) + 1
        return f"(translation failed: {err})"      # 🔴 程式自己組的中文，不可以拿去做語言檢查
    try:
        bad = mt_wrong_lang(target, g) or echoes_source(target, g, s)
    except Exception:
        bad = False     # 🔴 檢查本身出錯就當沒問題：翻譯工作一死，之後再也不會有字幕
    if not bad:
        return g
    # 用同一份提示詞重問，多半還是會被同樣的框架帶偏，所以補問要換「加註版」提示詞。
    # 只補問一次、不做三次重試：最壞情況只多一次呼叫的延遲。
    g2, ok2 = "", False
    try:
        r = await asyncio.wait_for(asyncio.to_thread(
            _mt_request, client, build_mt_prompt(target, s, ctx, frag, retry=True)), MT_TIMEOUT + 3)
        g2 = (r.text or "").strip()
        ok2 = bool(g2) and not mt_wrong_lang(target, g2) and not echoes_source(target, g2, s)
    except Exception:
        pass
    # 補問的答案也不對（或失敗）就用第一次的：語言錯、照抄原文的情形不會比改版前差。
    # （判準誤抓的純漢字日文例外：補問若回了帶假名的另一種譯法，會換成那一個——一樣是日文）
    return g2 if ok2 else g


def late_rows(pending, q):
    """V1.38（X7h）：收尾時還沒翻好的句子＝正在翻的那一句（pending）＋佇列裡還沒輪到的，照原本的先後。只拿出來、不翻。"""
    rows = list(pending)
    while True:
        try:
            rows.append(q.get_nowait())
        except asyncio.QueueEmpty:
            return rows


# ───────────────────────── 音訊來源 ─────────────────────────
class AudioSource:
    def __init__(self, source, path=None):
        self.source, self.path = source, path
        self.eof = False
        self.q = queue.Queue(maxsize=200)      # 輸出（已混音）
        self.drop = DropWatch(chunk_ms=CHUNK_MS)
        self.stop = threading.Event()
        self._lanes = {}
        self._failed = set()
        self._ready = set()          # 已經開好、開始收音的來源
        self._wanted = []            # 這次要開的來源
        self.live = False            # 主流程確認至少一路可用之後才設 True（見 wait_ready）
        self.mic_raw = False         # 完整收音（--mic-raw）：繞過 Windows 降噪，擴音器的聲音也收
        self.mic_device = None       # 指定麥克風（--mic-device）；None＝跟著 Windows 預設
        self.devices = {}            # 每一路目前實際在用的裝置名稱（寫進檔頭，見 _live.source_line）
        self.threads = []            # V1.32：麥克風／電腦聲音的收音執行緒（收尾時等它們關好串流，見 close）

    # 🔴 2026-09-22：兩路都改用 _live 的看門狗版本（三支即時程式共用）——裝置掉了、預設換了會自動接回。
    #    舊版只在開頭開一次，耳麥插頭鬆 3 秒整場就沒字幕（會議實測 14:25:12），見 _live.capture_mic 的說明。
    def _wasapi_loopback(self, lane='system'):
        capture_loopback(self, lane, CHUNK_MS)

    def _mic(self, lane='mic'):
        capture_mic(self, lane, CHUNK_MS, raw=self.mic_raw, device=self.mic_device)

    def _file(self, lane='file'):
        import atexit
        import subprocess, wave, tempfile
        wav = self.path
        # 🔴 .wav 不等於「單聲道 16-bit」。立體聲的 .wav 直接讀，會被當成
        #    兩倍長的單聲道流：聲音全亂、辨識全錯，而且照樣送去 API 扣錢。
        #    2026-09-10 稽核抓到。規格不符就一律交給 ffmpeg 轉一次。
        need_conv = not wav.lower().endswith(".wav")
        if not need_conv:
            try:
                with wave.open(wav, "rb") as _w:
                    need_conv = (_w.getnchannels() != 1 or _w.getsampwidth() != 2)
            except Exception:
                need_conv = True       # 讀不開就交給 ffmpeg，它容錯好得多
        if need_conv:
            wav = os.path.join(tempfile.gettempdir(), f"hq_{abs(hash(self.path)) % 10**8}.wav")
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", self.path,
                            "-ar", str(TARGET_SR), "-ac", "1", "-c:a", "pcm_s16le", wav], check=True)
            # 🔴 這是整場會議的完整聲音，未加密躺在 %TEMP%。用完要刪，
            #    不然解除安裝之後它還在，而且沒有人知道它在那裡。
            atexit.register(_quiet_remove, wav)
            on_console_close(lambda: _quiet_remove(wav))   # 視窗被關掉時 atexit 不會跑
        try:
            wf = wave.open(wav, "rb"); sr = wf.getframerate()
            self._ready.add(lane)
            print(f"{DIM}  Source file: {os.path.basename(self.path)}, {wf.getnframes()/sr:.0f} seconds{RESET}")
            fpc = int(sr * CHUNK_MS / 1000)
            while not self.stop.is_set():
                d = wf.readframes(fpc)
                if not d:
                    break
                self._push(np.frombuffer(d, dtype=np.int16).astype(np.float32), sr, lane)
                time.sleep(CHUNK_MS / 1000)
            wf.close()
        finally:
            # 🔴 同 live_bilingual.py：atexit 在中斷／強制關閉時不一定跑得到。
            if wav != self.path:
                _quiet_remove(wav)
        # 🔴 最後一塊通常不滿 100ms，混音器（_live.mix_lanes）要等這一路閒置超過 MIX_GRACE 秒
        #    才補零送出。太早設 eof，feed 看到「佇列空＋eof」就收尾，檔尾那一小段送不出去。
        self.stop.wait(MIX_GRACE + 0.2)
        self.eof = True

    # ── 來源啟動失敗時的中文說明（不要讓使用者看到英文 traceback）──
    _WHY = {
        "mic": ("No microphone found",
                "This PC has no usable recording device, or Windows is blocking access to the microphone.\n      → Check: Settings → Privacy & security → Microphone, and make sure desktop apps are allowed to access it.\n      → Or plug in a USB microphone and restart this program."),
        "system": ("Can't capture the computer audio",
                   "No WASAPI loopback device found.\n      → Check whether the speakers have been disabled (Settings → System → Sound)."),
        "file": ("Can't read this audio/video file", "The file may be damaged, or ffmpeg is not installed."),
    }

    def _guard(self, fn, lane):
        """包住擷取函式：失敗只警告這一路，不要拖垮整個程式。"""
        try:
            fn(lane)
        except Exception as e:
            title, hint = self._WHY.get(lane, (f"The \"{lane}\" source failed to start", ""))
            print(f"\n{YEL}  ⚠ {title}{RESET}")
            if hint:
                print(f"{DIM}      {hint}{RESET}")
            print(f"{DIM}      (Technical details: {type(e).__name__}: {str(e)[:90]}){RESET}")
            self._failed.add(lane)
            self._lanes.pop(lane, None)      # 從混音器移除，不然會一直等它
            names = {"system": "computer audio", "mic": "microphone", "file": "audio/video file"}
            alive = [k for k in self._lanes]
            # 🔴 只有另一路「真的開好了」（在 self._ready 裡）才敢說仍會用它繼續。舊版拿「還留在
            #    _lanes 裡」當成可用：選 both 而兩路一前一後失敗時（loopback 立刻失敗、麥克風 0.3 秒後
            #    才失敗），第一路失敗的當下就印「仍會用「麥克風」繼續，字幕照常運作。」，緊接著又印
            #    「沒有任何可用的聲音來源。」，兩句互相矛盾（2026-09-15 第二輪複查 T2-1）。
            #    還在啟動中就先不下結論，交給 wait_ready 之後的主流程講最後的結果。
            ready = [k for k in alive if k in self._ready]
            if ready:
                # 🔴 2026-09-22：不再說「字幕照常運作」——那句在兩路同時斷掉時是錯的（C 段重現）。
                print(f"{YEL}      For now, sound is captured only from the {names.get(ready[0], ready[0])}.{RESET}\n")
            elif alive:
                print(f"{DIM}      The other source ({names.get(alive[0], alive[0])}) is still starting; waiting to see how it goes before deciding.{RESET}\n")
            elif self.live:
                print(f"{YEL}      No usable audio source is left, so the captions will stop here; please press Ctrl+C to stop (everything recognised so far has been saved).{RESET}\n")
            else:
                print(f"{YEL}      No usable audio source.{RESET}\n")

    def _push(self, mono, sr, lane="main"):
        """把某一路音訊放進它自己的軌道（還沒混音）。"""
        if sr != TARGET_SR:
            g = np.gcd(sr, TARGET_SR)
            mono = resample_poly(mono, TARGET_SR // g, sr // g)
        try:
            self._lanes[lane].put_nowait(np.asarray(mono, dtype=np.float32))
        except (queue.Full, KeyError):
            pass

    def _mixer(self):
        """逐取樣相加才是真混音；共用一個 queue 會變成交錯，音訊量還會加倍。

        🔴 實作在 _live.mix_lanes（三支即時程式共用）。2026-09-19 筆電實測抓到舊寫法在
           兩路都持續送資料、只是到達時間錯開時仍會交錯（B1），細節見那裡的說明。
        """
        mix_lanes(self, int(TARGET_SR * CHUNK_MS / 1000))

    def start(self):
        keep_open(self)            # V1.33：第一行就登記——下面開執行緒做到一半出錯時，已經開的收音也要被 close_open() 關到
        if self.source == "file":
            self._wanted = ["file"]
            self._lanes["file"] = queue.Queue(maxsize=100)
            # V1.33：記下來，close() 要等它刪掉 %TEMP% 的轉檔暫存錄音（見 close）
            self._file_th = threading.Thread(target=self._guard, args=(self._file, "file"), daemon=True)
            self._file_th.start()
        else:
            targets = []
            if self.source in ("system", "both"):
                targets.append(("system", self._wasapi_loopback))
            if self.source in ("mic", "both"):
                targets.append(("mic", self._mic))
            self._wanted = [name for name, _ in targets]
            for name, _ in targets:
                self._lanes[name] = queue.Queue(maxsize=100)
            for name, fn in targets:
                th = threading.Thread(target=self._guard, args=(fn, name), daemon=True)
                th.start()
                self.threads.append(th)
        self._mix_th = threading.Thread(target=self._mixer, daemon=True)
        self._mix_th.start()

    def wait_ready(self, timeout=8.0, abort=None):
        """等每一路來源開好或宣告失敗（最多 timeout 秒），回傳還活著的來源名稱。

        🔴 沒有任何來源時不能開始：舊版照樣連線、在桌面寫出空的 .md／.txt，還顯示「✅ 共 0 段字幕」
           （2026-09-14 驗收抓到：這台沒接麥克風、選「只收麥克風」就是這樣）。
           開得慢的來源（大檔案要先用 ffmpeg 轉）超過 timeout 也不算失敗，照樣繼續。
        🔴 abort：任何有 is_set() 的旗標（run() 傳的是 SIGINT 會設起來的 stop_all）。這裡是
           time.sleep 迴圈、沒有 await，asyncio 的取消送不進來，等待期間按 Ctrl+C 會整個被吞掉
           （2026-09-15 第二輪複查 R2-4）。所以每 0.1 秒自己看一次旗標，命中就回空清單，
           由呼叫端負責收尾（不連線、不建檔）。
        """
        t0 = time.time()
        while (time.time() - t0 < timeout
               and not (abort is not None and abort.is_set())
               and any(k not in self._ready and k not in self._failed for k in self._wanted)):
            time.sleep(0.1)
        if abort is not None and abort.is_set():
            return []
        return [k for k in self._wanted if k in self._lanes]

    def close(self):
        forget_open(self)          # V1.33（見 _live.close_open）
        self.stop.set()
        # 🔴 等混音器把收尾那一波「丟掉了約…秒」講完：它是守護執行緒，不等的話那一行會印在總結後面，
        #    或行程結束前來不及印（2026-09-19 審查）。混音器每 10ms 看一次停止旗標，很快就會結束。
        th = getattr(self, "_mix_th", None)
        # V1.33：is_alive()＝start() 做到一半出錯、混音器還沒開時不 join（會丟 RuntimeError，下面的 join_capture 就被跳過）
        if th is not None and th is not threading.current_thread() and th.is_alive():
            th.join(0.5)
        # V1.32：等收音執行緒把串流關好再結束（不等會跟程式結束時的 Pa_Terminate 撞在一起，見 _live.join_capture）
        join_capture(self.threads)
        # V1.33：影音檔來源也等讀檔執行緒收尾（最多 0.5 秒），讓它自己的 finally 刪掉 %TEMP% 的轉檔暫存錄音。
        #    不等的話程式先結束，atexit 刪不掉（檔案還開著，WinError 32），要到解除安裝才清（V1.33 審查；V1.32 就有）
        ft = getattr(self, "_file_th", None)
        if ft is not None and ft is not threading.current_thread() and ft.is_alive():
            ft.join(0.5)


# ─────────────────── 從 interim 抓出「已經定案」的句子 ───────────────────


# ─────────────────────────── 輸出 ───────────────────────────
class Out:
    def __init__(self, stem, tgt, source=""):
        self.stem, self.tgt, self.source = stem, tgt, source
        self.t0 = time.time()
        self.rows = []           # (秒, 原文, 譯文)
        self.turns = []          # V1.35：每一句原文是第幾回合講的（跟 rows 一一對應；見 _live.SentenceGate.cur_turn）
        self.finals = []         # V1.35（待辦 9）：這一場收到的 Google 定稿 (收到的秒, 文字)（只拿來在存檔前更正原文的數字）
        self.num_pairs = []      # 存檔時更正的數字 [(舊, 新)]（收尾畫面照實講）
        self.late = 0            # V1.38（X7h）：收尾時翻譯還沒回來、譯文標成 LATE_MT 的句數（.md 檔頭照實講）
        self.failed = 0          # V1.38 審查第 4 輪：翻譯三次都失敗（「（翻譯失敗 …）」）的句數（.md 檔頭照實講）
        self.nomt = set()        # 沒有譯文的列（結束時還沒翻好／翻譯失敗）：存檔時不在那幾列加「這句譯文是更正前翻的」
        self.live = open(stem + ".txt", "w", encoding="utf-8", buffering=1)
        self.live.write(f"# Bilingual captions (Accurate mode) {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        + (f"# {source}\n" if source else "") + "\n")

    @staticmethod
    def ts(t):
        return f"{int(t//60):02d}:{int(t%60):02d}"

    @staticmethod
    def srt_ts(t):
        h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int((s%1)*1000):03d}"

    def add(self, t, src, tgt, lag, turn=None):
        note_caption()              # 收音狀態只在「一陣子沒有新字幕」時才印（見 _live.start_level_watch）
        if is_zh_target(self.tgt):
            tgt = to_tw(tgt)        # 大陸慣用語 → 台灣用語（只有中文譯文才換）
        self.rows.append((t, src, tgt))
        self.turns.append(turn)
        self.live.write(f"[{self.ts(t)}] {src}\n[{self.ts(t)}] {tgt}\n\n")
        print(f"{SRC_C}[{self.ts(t)}] {src}{RESET}")
        print(f"{TGT_C}          {tgt}{RESET}" + (f"  {DIM}(+{lag:.1f}s){RESET}" if lag is not None else "") + "\n")   # 沒有譯文的列不印延遲

    def save(self, want_srt=False):
        try:
            self.live.close()
        except Exception:
            pass
        # V1.35（待辦 9）：原文用定稿更正「字一樣、只有數字不同」的地方（見 _live.number_fixes）。譯文是當下照舊數字翻的，
        #    不重翻（收尾時再連網，網路不通就存不出檔），改在那句譯文下面註明；出錯就整個不改。
        try:
            fixes = {k: (new, pairs) for k, new, pairs in number_fixes(
                [(t, s, u) for (t, s, _g), u in zip(self.rows, self.turns)], self.finals)}
        except Exception:
            fixes = {}
        md = ["# Bilingual captions (Accurate mode)", "",
              f"- Created: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        if self.source:
            md.append(f"- {self.source}")
        md.append(f"- Sentences: {len(self.rows)}")
        if self.late:
            md.append(f"- ⚠ {self.late} sentence(s) had no translation back yet when it stopped (the translation never responded); the original text is saved, and the translation shows \"{LATE_MT}\"")
        if self.failed:
            md.append(f"- ⚠ {self.failed} sentence(s) could not be translated (all three tries failed); the original text is saved, and the translation shows \"(translation failed: …)\"")
        for _k, (_new, pairs) in sorted(fixes.items()):
            self.num_pairs += pairs
        if fixes:
            md.append(f"- {len(self.num_pairs)} number(s) in the source text were corrected using Google's final text ({', '.join(f'{a} → {b}' for a, b in self.num_pairs[:5])}{'…' if len(self.num_pairs) > 5 else ''}); the translations of those sentences were made before the correction, as noted under each of them; "
                      + ("the .txt backup and the .srt subtitle track keep what was shown on screen" if want_srt else "the .txt backup keeps what was shown on screen"))
        md += ["", "---", ""]
        srt = []
        for i, (t, s, g) in enumerate(self.rows, 1):
            # 🔴 V1.35 審查：.srt 用畫面上的原文（沒更正）——同一格字幕裡原文一個數字、譯文另一個數字，比兩邊一致更糟
            srt_s = s
            gm = g                   # .md 的譯文（更正過數字的句子多一行註明）
            if i - 1 in fixes:
                s, pairs = fixes[i - 1]
                note = ", ".join(f"{a} → {b}" for a, b in pairs)
                if i - 1 not in self.nomt:      # 沒有譯文的列不加「這句譯文是更正前翻的」（審查第 4 輪）
                    gm = f"{g}\n\n[The number(s) in the source were corrected using Google's final text ({note}); this translation was made before the correction, so go by the numbers in the source]"
            md += [f"**[{self.ts(t)}]**", "", f"> {s}", "", gm, ""]
            end = self.rows[i][0] if i < len(self.rows) else t + 5
            srt += [str(i), f"{self.srt_ts(t)} --> {self.srt_ts(end)}", srt_s, g, ""]
        open(self.stem + ".md", "w", encoding="utf-8").write("\n".join(md))
        # 預設不產生 .srt（字幕軌，單獨點開只會跳出空播放器）
        if want_srt:
            open(self.stem + ".srt", "w", encoding="utf-8").write("\n".join(srt))
        return len(self.rows)


# ─────────────────────────── 主流程 ───────────────────────────
async def run(a):
    import _apikey
    key = _apikey.for_script()         # 環境變數沒有就讀記住的那一組（2026-09-20 N6-3），都沒有就中文說明
    # 🔴 空字串也要擋（2026-09-20 筆電 ⚠-4）：變數存在但被清空時，拿空金鑰去連網
    #    只會得到「金鑰可能打錯」這種誤導訊息。見 _apikey.for_script 的說明。
    if not key:
        return 2
    client = genai.Client(api_key=key)
    tgt_name = SHOW_NAME.get(a.target) or LANG_NAME.get(a.target, a.target)   # 只拿來顯示（V1.30）

    # 🔴 SIGINT 的處理函式要在 src.start() 之前就登記好，等來源開好的期間 Ctrl+C 才有用
    #    （同 live_caption.py；2026-09-15 第二輪複查 R2-4）。
    # 🔴 Ctrl+C 時不要把英文 traceback 倒給使用者看（見 _live.quiet_async_noise）
    quiet_async_noise()
    stop_all = asyncio.Event()
    # 🔴 2026-09-21 使用者指示：按下 Ctrl+C 之後還要收尾幾秒，畫面若毫無回應，使用者會以為當掉、
    #    一直按。比照 live_bilingual.py（功能 3「快」／功能 6）已經驗過的那一套，每按一次都回一句話。
    #    🔴 不可以在訊號處理函式裡直接 print：剛好撞上字幕正在輸出時會 reentrant call 出錯，
    #    交給事件迴圈代印；迴圈已經結束時（收尾最後階段）就安靜略過。
    loop, presses, started = asyncio.get_running_loop(), [0], [False]
    waiting, saved = [0], [False]   # V1.38 審查第 4 輪：收尾時還有幾句在等翻譯／檔案存好了沒（第二次按 Ctrl+C 的提示照實講）

    def _notice(n):
        if not started[0]:
            return            # 還沒開始錄音：下面的取消分支自己會講「已取消」，這裡講收尾會前後矛盾
        if n == 1:
            # 🔴 2026-09-22（P7）：原本寫「約 5～15 秒」，與實際差太多，使用者會以為當掉。
            #    實測（3 次，且都是「講話中途中斷、翻譯佇列還有積壓」的最不利情境）：
            #    Ctrl+C 到完全收尾 **3.0 秒**，與功能 1 相同。改成與另外兩支一致的 3～5 秒。
            print(f"\n{DIM}  Ctrl+C received, wrapping up (waiting for the last few sentences to be translated, then saving), about 3–5 seconds…{RESET}")
        elif saved[0]:
            print(f"{DIM}  The files are all saved; closing now, please wait a few more seconds.{RESET}")
        elif waiting[0]:
            # V1.38 審查第 4 輪：還有句子在等翻譯時，按 X 這幾句連原文都不會存（.txt 是翻好才寫）——不要叫人按 X
            print(f"{DIM}  Still waiting for the last {waiting[0]} translation(s); any that don't arrive will still have their original text saved. If you click the X in the top-right corner of the window now, these sentences won't be saved at all, not even the original text.{RESET}")
        else:
            # 🔴 要講代價：按 X 會跳過整理 .md（收尾就在做這件事），而且選單在同一個視窗、會一起關掉
            print(f"{DIM}  Still wrapping up, please wait a few more seconds. You can also end it now with the X in the top-right corner of the window, but the tidied-up .md won't be produced (the word-for-word .txt is still there), and the menu will close as well.{RESET}")

    def _on_sigint(*_):
        presses[0] += 1
        stop_all.set()
        try:
            loop.call_soon_threadsafe(_notice, presses[0])
        except Exception:
            pass

    signal.signal(signal.SIGINT, _on_sigint)

    src = AudioSource(a.source, a.file)
    src.mic_raw, src.mic_device = a.mic_raw, a.mic_device
    print(f"{BOLD}▸ Starting audio capture ({a.source}){RESET}")
    src.start()
    alive = src.wait_ready(abort=stop_all)
    if stop_all.is_set():
        # 還沒開始錄就按 Ctrl+C：不連線、不建檔。
        # 🔴 離開碼 130（＝128＋SIGINT）只有「自己下指令跑這支腳本」時看得到，從 menu.py 進來看不到：
        #    真主控台按 Ctrl+C 時 Windows 會把 CTRL_C_EVENT 送給同一個 console 裡的每個行程，父行程
        #    menu.py 的 subprocess.run 自己也會收到、丟出 KeyboardInterrupt，被 menu.run() 的
        #    `except KeyboardInterrupt: return 0` 接走 —— 傳給 report_live 的是 0，不是 130
        #    （2026-09-15 第三輪對抗式複查 R2-4 用真主控台實測）。rc=2「沒有聲音來源」那條沒有這個問題，
        #    因為那時沒人按 Ctrl+C，父行程不會被打斷。130 仍然保留給「直接執行這支腳本」的情境。
        #    🔴 選單那邊是怎麼分辨「取消」與「出錯」的：menu.report_live 看的是
        #    「rc == menu.CANCEL_RC(130)」或「menu 自己也被 Ctrl+C 打斷的旗標」。
        #    不要在這裡印機器用的標記字串給它讀：menu.run() 沒有接管子行程的 stdout，
        #    也不該接（Windows 匿名管線只有 4KB，沒人讀就會卡死子行程），所以標記只會原封不動
        #    印在使用者畫面上，對非技術使用者就是一行看不懂的代號（2026-09-15 第四輪複查抓到）。
        src.close()
        print(f"\n{YEL}  ✗ Cancelled (Ctrl+C): recording did not start and no files were created.{RESET}")
        return 130
    if not alive:
        # 🔴 沒有任何聲音來源就不要連線、不要建檔，也不要說 ✅（同 live_caption.py）。
        src.close()
        print(f"\n{YEL}  ✗ No usable audio source: recording did not start and no files were created.{RESET}")
        return 2
    src.live = True
    started[0] = True          # 🔴 錄音真的開始了，Ctrl+C 才要講「正在收尾」（見 _notice）

    stem = a.out or time.strftime("Bilingual_%Y%m%d_%H%M")
    out = Out(stem, a.target, source_line(a.source, src))
    if a.source != "file":
        start_level_watch(src)       # P1：開場印一次收音狀態，之後一陣子沒字幕才再印

    mt_q = asyncio.Queue()
    pending = []     # V1.38（X7h）：正在翻的那一句（收尾時翻譯還沒回來的話，原文照樣存；見 late_rows）
    mt_stats = {"failed": 0}    # V1.38 審查第 4 輪：翻譯三次都失敗的句數（收尾照實講、不打 ✅）
    loop = asyncio.get_running_loop()
    # V1.35：最後一欄＝這一句是第幾回合講的（見 _live.SentenceGate.cur_turn；存檔前更正數字只認那一回合的定稿）
    gate = SentenceGate(lambda s, frag=False: loop.call_soon_threadsafe(
        mt_q.put_nowait, (time.time() - out.t0, s, time.time(), frag, gate.cur_turn)),
        settle=a.settle)

    print(f"{BOLD}▸ Accurate mode: waits for each full sentence before translating (source: {ASR_MODEL} / translation: {MT_MODEL}){RESET}")
    print(f"{DIM}  grey = source  blue = translation ({tgt_name})  figure in brackets = delay from the end of the sentence to its translation{RESET}")
    print(f"{DIM}  Ctrl+C to stop{RESET}")
    print(f"{DIM}  {font_hint()}{RESET}\n")

    async def translator():
        """整句翻譯。帶前兩句當上下文，讓代名詞與術語連貫（ja／en 的接續句只帶上一句，見 build_mt_prompt）。

        提示詞組裝、重試、譯文語言與原文回聲檢查都在模組層級的 translate_line()（可用假 client 離線測）。
        """
        ctx = []
        while True:
            t, s, born, frag, turn = await mt_q.get()
            pending[:] = [(t, s, born, frag, turn)]
            f0 = mt_stats["failed"]
            g = await translate_line(client, a.target, s, ctx, frag, stats=mt_stats)
            pending.clear()
            ctx.append(s)
            out.add(t, s, g, time.time() - born, turn)
            if mt_stats["failed"] != f0:
                out.nomt.add(len(out.rows) - 1)
            mt_q.task_done()

    async def ticker():
        # 講者停頓時，把還沒湊成一句的字送出去，不要卡住。
        # 🔴 這個工作一死，從此不會再有任何定稿，而且**沒有人會發現**
        #    （例外沒人取回，只會在垃圾回收時噴一段英文 traceback）。
        #    所以它必須自己撐住，出錯只講一次中文，繼續跑。
        warned = False
        while True:
            await asyncio.sleep(0.3)
            try:
                gate.tick()
            except Exception as e:
                if not warned:
                    warned = True
                    print(f"\n{YEL}  ⚠ Something went wrong with sentence splitting, so captions may be a little slower ({type(e).__name__}); recording and saving are not affected{RESET}")

    tr_task = asyncio.create_task(translator())
    tk_task = asyncio.create_task(ticker())

    # 🔴 講者說中文時一定要指定繁體。Live 轉錄不指定語言碼就出簡體（live_caption.py 早就
    #    寫死 cmn-Hant-TW），這裡原本只在有傳 --source-lang 時才設 —— 選單從來不傳，
    #    於是「聽中文演講、翻成英文／日文」時原文整段都是簡體
    #    （2026-09-11 實戰測試：兩輪各 18、19 個簡體字）。
    #    翻成繁體中文時講者說的是外語，維持不指定（使用者實際用過、正常）；
    #    翻成其他語言時講者說中文，指定 cmn-Hant-TW。
    #    🔴 已知例外：混合會議現場有人講中文、又選翻成繁體中文時，原文會是簡體（2026-09-19 筆電 R4，
    #       交接報告 M2，手冊 FAQ「字幕出現簡體字」②）。要改成一律帶 cmn-Hant-TW，先實測英文轉錄會不會變差。
    src_lang = a.source_lang or (None if a.target == "zh-TW" else "cmn-Hant-TW")
    cfg = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            mode=types.AudioTranscriptionConfigMode.SMART,
            language_codes=[src_lang] if src_lang else None),
    )

    # 🔴 2026-09-22（P5）：累加跨連線的靜音壓制總量，收尾時報給使用者
    #    （SilenceGate.held_seconds 原本定義了卻無人使用）。
    held_total = [0.0]
    rc = Reconnect()
    # V1.26 B1：只收電腦聲音時，送給 Google 的那一份先放大（見 _live.Leveler；同一個轉錄模型，實測在 live_caption）。
    leveler = Leveler() if a.source == "system" else None
    open_turn = [False]      # V1.35：這一回合已經有暫定稿、還沒等到定稿（見下面換線時補的佔位定稿）
    while not stop_all.is_set():
        seg0 = time.time()
        # V1.35（複查 R1'）：上一條連線的最後一回合沒等到定稿就斷了 → 補一則空的定稿佔住它的回合編號（同 live_caption）
        if open_turn[0]:
            out.finals.append((time.time() - out.t0, ""))
            gate.turn = len(out.finals)
            open_turn[0] = False
        try:
            # 🔴 握手走 open_live（有時限、Ctrl+C 叫得動）——見 _live.open_live 的說明。
            async with open_live(
                    client.aio.live.connect(model=ASR_MODEL, config=cfg),
                    stop_all) as session:
                rc.ok()          # 連上了，重置失敗計數

                # 🔴 2026-09-22（P5）：閘門移到 feed() 外面（仍是每條連線一個，行為不變）。
                #    feed() 會被 cancel（伺服器斷線時正是如此），統計寫在它裡面會被跳過。
                silence_gate = SilenceGate(enabled=a.source != "file",
                                           floor=gate_floor(a.source))   # V1.23 B：只收電腦聲音時下限放寬

                async def feed():
                    # 8 分鐘到了之後等講者停頓再換線（2026-09-20 N5，見 _live.RotateWhenQuiet）
                    # V1.25：麥克風、兩者都要漸進；看「實際」開起來的收音方式（完整收音開不起來會退回一般收音）
                    rot = RotateWhenQuiet(seg0, SESSION_SOFT_LIMIT, idle=a.source != "file",
                                          **rotate_opts(a.source, getattr(src, "mic_raw_active", a.mic_raw)))
                    # 🔴 2026-09-21：持續安靜就不要再餵模型（見 _live.SilenceGate）。
                    #    實測：靜音 3 分鐘時，沒有這道閘門的話會送出 1800 塊空白音訊，
                    #    而模型吃到連續靜音會退化成填充詞迴圈（原文欄自己重複、停不下來），
                    #    同時持續計費。有閘門的對照組只送 29 塊、且完全沒有跳針。
                    #    檔案來源不啟用：檔案讀完就 eof，沒有「一直錄空氣」的問題。
                    #    （閘門本身建在上一層，見該處說明）
                    while not stop_all.is_set():
                        try:
                            pcm = src.q.get_nowait()
                        except queue.Empty:
                            if src.eof:
                                await asyncio.sleep(a.settle + 2)
                                gate.tick()
                                await mt_q.join()
                                stop_all.set()
                            elif rot.due():      # 佇列空了才問：有積壓時先送完（見 _live.RotateWhenQuiet）
                                break
                            await asyncio.sleep(0.02)
                            continue
                        for blk in silence_gate.feed(pcm):
                            await session.send_realtime_input(audio=types.Blob(
                                data=leveler.apply(blk) if leveler else blk, mime_type=f"audio/pcm;rate={TARGET_SR}"))
                        # 🔴 rot.saw() 要在閘門之外、每一塊都呼叫：8 分鐘換線是靠它累積
                        #    音量高點與安靜塊數，被閘門擋掉的塊也必須算進去，否則判斷失準。
                        rot.saw(pcm)
                        if rot.due():
                            break

                async def read():
                    turn = ""        # 這一回合最新的暫定稿：定稿來的時候拿它對齊（V1.26 B2）
                    turn_long = False   # 這一回合出現過 4 字以上的暫定稿沒有（V1.35）
                    async for msg in session.receive():
                        # 🔴 go_away 一定要在 server_content 之前檢查：
                        #    GoAway 是 protobuf oneof 的另一個分支，它的
                        #    server_content 是 None，寫在 `if not sc: continue`
                        #    後面就永遠不會執行（官方範例也是第一層就檢查）。
                        if getattr(msg, "go_away", None) is not None:
                            print(f"\n{DIM}(The server asked for a new connection; reconnecting automatically){RESET}")
                            return
                        sc = msg.server_content
                        if not sc:
                            continue
                        it = getattr(sc, "interim_input_transcription", None)
                        if it and it.text:
                            turn = it.text
                            turn_long = turn_long or long_interim(it.text)   # V1.35：見 _live.final_extend 的 short_ok
                            open_turn[0] = True
                            gate.feed(it.text)
                        # 🔴 不把 input_transcription 整句餵進去：它是另一版字串，
                        #    會讓 gate 誤判成新段落而重複輸出（實測踩過）
                        # V1.26 B2：只拿它比暫定稿多出來的句尾接回去（見 _live.final_extend；同 live_caption）
                        ft = getattr(sc, "input_transcription", None)
                        if ft and ft.text:
                            # V1.35（待辦 9）：存檔前拿來更正原文的數字；記收到的時間（只認時間最近的那則）
                            out.finals.append((time.time() - out.t0, ft.text))
                            open_turn[0] = False
                        if ft and ft.text and turn:
                            ext = final_extend(turn, ft.text, short_ok=not turn_long)
                            if ext:
                                gate.feed(ext)
                            turn, turn_long = "", False
                            gate.turn_done()       # V1.29 ①：這一回合結束了，手上的短殘字不必再多等（同 live_caption）
                        if ft and ft.text:
                            gate.final_check(ft.text)    # V1.36（待辦 13）：只有定稿有的那句補送一行（同 live_caption）
                            gate.turn = len(out.finals)    # V1.35：之後餵進來的暫定稿屬於下一則定稿那一回合

                f = asyncio.create_task(feed()); r = asyncio.create_task(read())
                done, pend = await asyncio.wait({f, r}, return_when=asyncio.FIRST_COMPLETED)
                # 輪替時給 read 一點寬限，否則每 8 分鐘會掉最後一句（見 live_caption 註解）
                if f in done and r in pend:
                    await asyncio.wait({r}, timeout=ROTATE_GRACE)
                for x in pend:
                    x.cancel()
                held_total[0] += silence_gate.held_seconds     # P5：累加跨連線的壓制總量
                # 🔴 一定要把工作裡的例外撈出來重拋。
                #    asyncio 的工作出例外時，沒人取回就會由 asyncio 自己把**英文
                #    traceback** 倒在畫面上（同事看到會直接關掉視窗），而下面那個
                #    except 根本看不到它 —— Reconnect 的退避、中文說明、連續失敗
                #    升級警告全部形同虛設。實測 1008 斷線後接著 6 分鐘零字幕。
                # 🔴 兩個工作可能**同時**出例外。每一個都要取回來
                #    （呼叫 .exception() 就算取回），但只 raise 第一個。
                #    只 raise 不取回，另一個照樣會在垃圾回收時噴英文 traceback。
                errs = [t.exception() for t in (f, r)
                        if t.done() and not t.cancelled() and t.exception()]
                # feed 先結束＝這是我們自己排定的 8 分鐘輪替。讀取端這時候被伺服器
                # 關掉是正常的，不可以當成連線失敗去嚇使用者（但例外已經取回了）。
                rotating = f in done and time.time() - seg0 >= SESSION_SOFT_LIMIT
                if errs and not rotating:
                    raise errs[0]
        except Exception as e:
            if stop_all.is_set():
                break
            await asyncio.sleep(rc.failed(e))

    try:
        gate.flush()
    except Exception:
        pass
    # 🔴 V1.29 審查：gate 送出是 call_soon_threadsafe 排進事件迴圈的，flush 回來時那一句還沒進 mt_q。
    #    Python 3.12 起 wait_for 直接執行 join()，佇列是空的就立刻回來 → 翻譯工作被取消、最後一句沒存到
    #    （檔案來源：檔尾最後一句是「謝謝」這種短殘字時整句不見）。先讓出一次，讓排好的那一句真的進佇列。
    await asyncio.sleep(0)
    # V1.38 審查第 4 輪：平常最後一句 1 秒內就翻完；3 秒還沒好（翻譯卡住）就照實講還有幾句、最多再等多久（總共 15 秒，跟以前一樣）
    waiting[0] = len(pending) + mt_q.qsize()
    join_t = asyncio.ensure_future(mt_q.join())
    done, _ = await asyncio.wait({join_t}, timeout=3)
    if not done:
        waiting[0] = len(pending) + mt_q.qsize()
        print(f"{DIM}  {waiting[0]} sentence(s) still waiting for translation; waiting up to 12 more seconds. Any that don't arrive will still have their original text saved, with the translation marked \"{LATE_MT}\"{RESET}")
        await asyncio.wait({join_t}, timeout=12)
    join_t.cancel()
    waiting[0] = 0                  # 等完了（拿到或放棄）：接下來是存檔，第二次 Ctrl+C 照原本的說法
    tr_task.cancel(); tk_task.cancel()
    # V1.38（10-05 X7h）：等不到翻譯的句子（Google 那一次呼叫卡住，後面的都排在它後面）原文照樣存、譯文標 LATE_MT，收尾照實講。
    #    以前整句連原文一起丟掉、畫面還打 ✅（X7h 實測卡 51 秒，最後 7 句沒存；斷網模擬重現：16 句只存 5 句）。
    late = late_rows(pending, mt_q)
    for t, s, _born, _frag, turn in late:
        out.add(t, s, LATE_MT, None, turn)          # 沒有譯文：不印延遲
        out.nomt.add(len(out.rows) - 1)
    out.late, out.failed = len(late), mt_stats["failed"]
    src.close()
    n = out.save(want_srt=a.srt)
    saved[0] = True
    print(f"\n\n{'✅' if n and not (late or out.failed) else '⚠'} Total: {n} sentences" + ("" if n else " (nothing was recognised during the whole session; please check that the audio source actually had sound)"))
    if late:
        print(f"{YEL}   {len(late)} of them had no translation back yet when it stopped (the translation never responded): the original text is saved, and the translation shows \"{LATE_MT}\"{RESET}")
    if out.failed:
        print(f"{YEL}   {out.failed} of them could not be translated (all three tries failed): the original text is saved, and the translation shows \"(translation failed: …)\"{RESET}")
    if out.num_pairs:
        print(f"{DIM}   While saving, {len(out.num_pairs)} number(s) in the source text were corrected using Google's final text ({', '.join(f'{x} → {y}' for x, y in out.num_pairs[:3])}{'…' if len(out.num_pairs) > 3 else ''}; the translations were made before the correction, as noted in the .md; what was shown on screen is kept in the .txt{' and the .srt' if a.srt else ''}){RESET}")
    if held_total[0] >= 1:
        # P5：讓使用者看得到靜音閘門真的有在省。1 秒以下不印，避免短測試洗版。
        print(f"{DIM}   Skipped {held_total[0]:.0f} seconds of unnecessary uploading during quiet periods{RESET}")
    print(f"   {stem}.md\n   {stem}.txt")
    if a.srt:
        print(f"   {stem}.srt")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["system", "mic", "both", "file"], default="system")
    ap.add_argument("--file", default=None)
    ap.add_argument("--target", default="zh-TW", help="What to translate into: zh-TW / en / ja")
    ap.add_argument("--source-lang", default=None, help="Hint for the source language, e.g. en-US")
    ap.add_argument("--settle", type=float, default=1.2,
                    help="How many seconds the speaker must pause before the sentence counts as finished (default 1.2)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--srt", action="store_true", help="Also create an .srt caption track")
    ap.add_argument("--mic-raw", action="store_true",
                    help="use full capture for the microphone (bypasses Windows noise suppression; loudspeakers in the room are picked up too)")
    ap.add_argument("--mic-device", default=None,
                    help="which microphone to use (the name must match what Windows shows); leave it out to follow the Windows default, which switches automatically when a headset is plugged in or out")
    a = ap.parse_args()
    code = 0
    try:
        code = asyncio.run(run(a)) or 0
    except KeyboardInterrupt:
        pass
    finally:
        close_open()               # V1.33：沒預期的錯誤跳出來時，也要先把收音關好再結束（見 _live.close_open）
    sys.exit(code)                 # 沒有聲音來源＝2；選單看離開碼才知道不是成功


if __name__ == "__main__":
    main()
