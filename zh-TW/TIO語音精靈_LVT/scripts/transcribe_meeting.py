# -*- coding: utf-8 -*-
"""
會議錄音 → 繁體中文逐字稿（含講者、時間軸）    gemini-3.5-transcribe

【為什麼要跑兩趟？】這是實測出來的模型行為，不是猜的：
  只要打開 diarization（分講者）或 word_timestamp（詞時戳），
  模型就會忽略 cmn-Hant-TW 語言碼，輸出變成簡體，也不能再帶 custom_vocabulary。
  關掉這兩個才會出繁體。兩者無法在同一次呼叫中兼得。
所以：
  第 1 趟 verbatim + 分講者 + 詞時戳 → 拿「誰在講、第幾秒」（簡體，只當骨架）
  第 2 趟 smart + 自訂詞彙 + cmn-Hant-TW／en-US → 拿「乾淨的繁體正文」（模型自己產的，非翻譯；
        加 en-US 是 V1.22 起：只給中文時，中文會議裡的英文發言會整段消失，見 pass2_clean）
  第 3 步 程式把第 2 趟的繁體正文切成編號小句，文字模型只回答「每段從第幾句開始」，
        文字由程式原封不動剪下來（不可能改字，也不可能混進簡體骨架）

用法：
  python transcribe_meeting.py 會議錄音.m4a
  python transcribe_meeting.py 錄音.mp3 --vocab 深耕計畫 研發處 會計室 --names 處長 秘書
"""
import atexit, os, sys, io, re, json, argparse, subprocess, tempfile, time, logging, socket, difflib

if __name__ == "__main__":      # 被 import 時不要動 stdout，會互相關掉底層 buffer
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

from google import genai
from google.genai import errors as gerr
from google.genai import types

try:
    # 講者排序與預設名字，功能 2／4／5 與選單共用這一份（V1.22；見 json_to_md.speaker_key 的說明）
    from json_to_md import speaker_list, generic_names, speaker_part
except ImportError:
    print("\n  ✗ 少了程式檔 scripts\\json_to_md.py，這套工具的檔案不完整。")
    print("     → 請重新解壓縮整個資料夾，或重新點兩下 3_安裝.bat。")
    raise SystemExit(2)

# 🔴 SDK 會在畫面上印一段英文警告「Direct use of automatic function calling (AFC)…」，
#    同事看到會以為出錯了（2026-09-11 實戰測試）。那是給開發者看的，對轉檔毫無影響。
logging.getLogger("google_genai").setLevel(logging.ERROR)

TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
ALIGN_MODEL = "gemini-3.5-flash"
MAX_INLINE = 15 * 1024 * 1024
UPLOAD_TAG = "meeting-caption-tool"   # 上傳時掛的名字；清理只認這個，不碰同一把金鑰底下別人的檔
SWEEP_CLOUD_AGE = 6 * 3600            # 自己的上傳超過這麼久還在 → 一定是上次沒刪乾淨的
SWEEP_TEMP_AGE = 12 * 3600            # %TEMP% 暫存同理（太新的可能是另一個視窗正在轉）
COVER_GAP = 30                        # 逐字稿結尾距錄音結尾超過這麼多秒 → 檔頭與畫面標「可能不完整」
# 🔴 逐段檢查用比較寬的門檻：切點刻意挑在靜音處，每一段的尾巴天生帶一小段安靜，
#    沿用 30 秒會對完整的逐字稿發假警報。真正值得報的段尾缺口遠大於這個值。
CHUNK_GAP = 120
# ── 逐段完整性檢查的三個門檻（2026-09-16 訂，全部用 11 段真實資料校準）────────────
# 病根：既有的 CHUNK_GAP 只比「這一段的時戳有沒有走到段尾」。實測 2:56:47 的會議發現
# 兩種故障它完全看不到 —— 一種是時戳走到段尾、但中間整片沒有句子（內容消失），
# 另一種是時間軸看起來滿的、正文卻在自我重複（內容灌水）。三個門檻各管一個維度。
#
# 🔴 這三個數字都是從實測資料推的，不要憑感覺調。誤報比漏報更糟：警告一旦常態出現，
#    使用者就學會忽略它，等於三支偵測器一起失效。
HOLE_GAP = 180        # 段內相鄰句子的間隔超過這麼多秒 → 中間可能被跳過了。
#                       實測良性上界 57.7 秒、故障下界 348.1 秒，兩側各留 3.1 倍／1.9 倍餘裕。
PASS_RATIO = 4.0      # 正文字數是骨架字數的幾倍以上算異常（要跟 PASS_SURPLUS 同時成立）。
PASS_SURPLUS = 2000   # 而且要多出這麼多字才算 —— 短段落的倍數天生不穩，絕對量要擋在倍數前面。
#                       實測 11 段的比值：非故障最高 1.69、故障 10.85，門檻 4.0 兩邊各有 2.4／2.7 倍餘裕。
LOOP_WIN = 8          # 用幾個字的滑動視窗量重複
LOOP_RATIO = 0.10     # 重複視窗佔比超過這麼多 → 正文可能陷入迴圈
LOOP_CHARS = 500      # 而且重複的字數要有這麼多（短逐字稿本來就有「好，謝謝」這種高頻短語）
#                       實測乾淨 9 段最高 0.93%（重複最多 99 字），故障兩段 50.7%／90.8%
#                       （重複 5,483／11,977 字）—— 中間空了 55 倍，門檻很好訂。
SPLIT_CHARS = 160                     # 一段正文超過這麼多字就照句子切開（一個人長篇獨白時骨架只有一段）
# ── 「有聲音、逐字稿卻沒有這段」（V1.22 ①，見 _voiced_holes）────────────
VOICE_HOLE = 10.0          # 有聲音、卻沒有任何段落涵蓋的連續秒數超過這麼多 → 列進檔頭（外賓那段英文 18 秒）
VOICE_FRAME = 0.1          # 量音量的一格（秒）
VOICE_BRIDGE = 3.5         # 兩段有聲音中間的停頓短於這麼多秒，當成同一段話
# 🔴 V1.36（待辦 18 A）：原本 1.5 秒。2026-10-03 在真實素材挖 30 秒的洞：輪流發言的換人停頓 1.5～3.1 秒，把漏掉的
#    22～24 秒來回對話切成 4～5 段、每段 <10 秒 → 一則都不報（meeting4 三種音質、西語廣播）。改 3.5 秒＝蓋過實測最長的換人停頓。
#    筆電 13 份功能 2 真實輸出重算：完整的逐字稿（meeting4 四種格式、plong、短句）照樣 0 則；新報的都查得到原因——
#    英文併進前一位中文講者的段落（電話音質）、兩人同時開講漏掉的外賓英文（crosstalk，待辦 15 那例）、long_mix 漏掉的
#    2 分多鐘；長會議 31 分那 22 則零碎的併成 4 則涵蓋正確的大段（逐字稿真的跳過 18 分鐘）。
# 🔴 V1.36 審查第二輪（合成反例＋同一批 13 份真實輸出重算，則數完全相同）：3.5 秒會把停頓裡零星幾聲（各 0.2 秒）接成一段，
#    完整的逐字稿被報「這 10 秒有聲音」→ 下面 VOICE_DENSE；換人停頓真的超過 3.5 秒（3.6～5.9 秒）時，整串 45 秒的對話漏掉
#    還是不報 → 下面 VOICE_SUM。兩條一起：零星聲響 4 例全擋、慢節奏換人 5 例全抓。
VOICE_DENSE = 0.10         # 接成一段的洞裡，實際有聲音的格子至少要佔這麼多才報
VOICE_DENSE_REL = 0.5      # 而且至少要有「逐字稿有蓋到的時段」有聲比例的這麼多倍
# 🔴 V1.36 審查第四輪：會議中間休息、會後收東西時每 2.5～4 秒一聲（每聲 0.15～0.4 秒），3.5 秒會把它們接成一段、有聲 10～16%
#    → 照 10% 會報（5 分鐘休息 4 次共 13 則；V1.35 0 則）。直接提高到 20% 又會漏掉真的漏段（西語廣播 12 秒的洞 21/30 → 10/30）。
#    改成跟著這份錄音走：講話密的會議門檻跟著提高、零星聲響過不了；廣播這種本來就稀的維持 10%。
VOICE_SUM = 6.0           # 逐字稿沒蓋到的時間裡，任一 VOICE_SUM_WIN 秒內有聲音的格子加起來到這麼多秒也報（中間停多久都接得起來）
VOICE_SUM_WIN = 30.0
# 🔴 V1.36 審查第三輪：第二輪的 VOICE_SUM 沒有範圍，整段沒蓋到的時間一起加——休息 5 分鐘、平均每 8 秒一聲杯子椅子（每聲 0.15～0.4 秒）
#    也加得過 6 秒 → 整段 299 秒被報，還跟「中間 5 分鐘沒有辨識到任何話」那句矛盾（15 分鐘休息、會後收東西同樣）。改成 30 秒內加起來。
VOICE_ABOVE_FLOOR = 12.0   # 比這份錄音自己的底噪（最安靜的 10%）大這麼多 dB 才算「有聲音」
# 🔴 V1.36（待辦 18 B）：整份錄音幾乎沒有安靜的時候、講話又沒比背景大多少（配樂墊底、廣播轉播），「最安靜的 10%」本身
#    就是聲音 → 門檻被墊高，偵測器只聽得到特別大聲的部分（德語廣播挖 12 秒的洞 30 個只抓到 2 個）。不另做語音偵測（要加套件）：
#    看不準時在檔頭加一行 ℹ️ 照實講（只是說明這道檢查的能力，不算缺口、不影響 ✅；見 _voice_note）。
#    審查第二輪：第一版用「最安靜 10% 比 −40 dBFS 大聲、有聲格子不到一半」——跟錄音音量有關（德語廣播整份調小 12 dB 就不講了，
#    抓到率一樣差），偵測其實正常的配樂會議、法語廣播也會講。改成兩個跟音量無關的比值，兩條同時成立才講：
#    最大聲 1% 比最安靜 10% 大多少 dB（德語廣播 13.1、安靜耳機錄音 14.4；西語 14.7、法語 18.9、配樂會議 19.1、BBC 33.5、
#    一般會議 60 以上）、≥10 秒的有聲段落蓋住全長幾成（德語 14%、耳機 0%；西語 87%、配樂會議 86%、法語 100%）。
NOISY_RANGE = 18.0         # 最大聲的 1% 比最安靜的 10% 大不到這麼多 dB
NOISY_COVER = 0.5          # 而且 ≥ VOICE_HOLE 秒的有聲段落蓋住不到全長的這個比例
# ── V1.35（待辦 10）：長篇多語錄音的三個缺口 ─────────────────────────
# 🔴 2026-10-03 V1.34 全線實測 X10（66 分鐘：會議＋英／法／德／西語廣播＋長會議，自動切 3 段）：第 1 段第 1 趟整段跳過 7 分鐘
#    英法語廣播，產生一段 108.8→551.8 秒、只有兩句中文的段落 → 上面那道「有聲音卻沒有字」以為整段都有涵蓋，檔頭一句也沒報；
#    第 2 趟正文自己排成 1～11 號清單，「7.」「11.」被原字剪進逐字稿；對齊錯位，同一時間範圍出現兩套內容。
#    門檻用筆電歷來 48 份功能 2 逐字稿校準：正常的段落重疊最多 1.2 秒（X10 那份 361 秒）；超過 60 秒的段落只出現在 X10。
SPARSE_LONG = 60.0         # 段落超過這麼多秒才看字數密度
SPARSE_CPS = 1.0           # 每秒不到這麼多個字（英數字＋中文字）＝幾乎沒字（一般講話中文約每秒 4 字）
SPARSE_EDGE = 15.0         # 這種段落只算頭尾各這麼多秒有涵蓋，中間交給「有聲音卻沒有字」那道檢查
OVERLAP_MIN = 10.0         # 下一段開始得比前面最晚的結束還早這麼多秒以上 → 檔頭列「時間互相重疊或倒退」
# 🔴 暫存檔名與雲端上傳都掛「電腦名稱#行程編號」：這支程式當機、視窗被關、被工作管理員結束時，
#    下一次轉檔一開始就能認出「留下它的那個行程已經不在了」而立刻清掉，不必等 6／12 小時
#    （2026-09-14 驗收：轉到一半關視窗，整場錄音留在雲端和 %TEMP% 好幾個小時）。
#    🔴 但「認得出行程還活著」只能加速清理，不能取代年齡上限：Windows 會回收行程編號，當機留下的
#    整場錄音一旦編號被別的長壽行程拿去用，就會被誤判成「還在轉」而永遠不清——比舊版還糟。
#    所以 _stale 是「死了立刻清，太舊也一定清」，6／12 小時的年齡保底永遠有效。
_HOST = socket.gethostname()
_TEMP_FILES = []                      # 這次跑產生的暫存檔（視窗被關掉時要立刻刪）
_CLOUD_FILES = []                     # 這次上傳到雲端的檔名（同上）
RETRY_WAITS = (15, 30, 60)            # 伺服器忙（503）時的重試間隔（秒）
NET_WAIT_STEP = 20                     # V1.38（待辦 20）：網路斷了（查不到伺服器位址）時，每幾秒再試一次
NET_WAIT_MAX = 300                     # 同一次斷網最多等幾秒；等滿還沒回來才停（之後的段落不再各等一次）
_net_waited = 0                        # 這一次斷網已經等了幾秒：任何一次呼叫成功、或伺服器有回應就歸零（整份共用，見 _with_retry）
ATC = types.AudioTranscriptionConfig
MODE = types.AudioTranscriptionConfigMode

# 🔴 兩條上限，取比較嚴的那一條：
#    ① 官方明文：不開那兩個功能時，單次請求上限是 **1 小時**（不是我們早期用
#       98,304 tokens ÷ 25.04 tok/秒 推算的 65.4 分鐘 —— 算式沒錯，但那不是唯一的限制）。
#       2026-09-16 另一個 session 實測 60.6 分鐘就被擋，與官方的 1 小時吻合。超過是 400，看得到。
#    ② 官方 Limitations 明文：「Audio processing is limited to 30 minutes when features
#       like speaker diarization or word-level timestamps are enabled.」
#       pass1_skeleton() 兩個都開，所以真正的上限是 30 分鐘。
#    🔴 ② 這條**不會報錯**：整份收下、照整份計費。超過的部分會怎樣官方沒寫；
#       早期以為「只轉出前 30 分鐘」，至今沒有確認過任何一次（見下方更正）。
#    留 2 分鐘安全邊際切 28 分鐘一段。
#
#    🔴 2026-09-16 更正：這裡原本寫「查證一份 2:56:47 的會議，切 45 分鐘時前三段各在
#       第 30 分鐘斷掉、只涵蓋 73.8%、少 43 分鐘」——**那個結論是錯的，已推翻**。
#       那組數字是拿舊版的時戳算的，而舊版的時戳本身壞掉（10 句超過 1,000 字的巨句，
#       最長 6,771 字、開頭與結尾是同一段話重複），內容其實在巨句裡、只是時間標錯。
#       把可疑時段剪出來單獨轉才確認：真正的故障是「段中整片沒辨識到」與「正文迴圈重複」；
#       迴圈重複在 45 分鐘與 28 分鐘**都發生過**（段中空洞目前只在 28 分鐘的段遇過）——
#       分段長度不是病根，所以這個常數維持 28 沒動。
#       那兩種故障各由 _chunk_holes／_pass_gap／_loop_gap 負責偵測。
MAX_CHUNK_SEC = 28 * 60
_DEFAULT_CHUNK_SEC = MAX_CHUNK_SEC    # main() 每次都從這個值起算，避免同一行程跑第二次時沿用上一次的 --max-chunk-min
# 🔴 這次轉檔的中途存檔路徑（main() 算出檔名時填進來），給 Ctrl+C 的說明用：
#    中斷時要照「這個檔到底有沒有落地」講話，不能無條件叫使用者去找它。見 _interrupted()。
_PART_JSON = None




def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
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
    print("\n  \u26a0 這台電腦找不到 ffmpeg（處理音訊一定要用它）")
    print("     → 如果你剛剛才裝好：關掉這個視窗，重新點一次 4_開始使用.bat")
    print("       （新裝的程式要開新視窗才找得到）")
    print("     → 如果一直都找不到：重跑一次 3_安裝.bat")
    print("     → 想確認的話：點兩下 6_診斷.bat，看 [ffmpeg] 那一行")
    return False


def _upload_name():
    """雲端上傳掛的名字：工具名＋電腦名稱#行程編號（清理時認得出是誰留下的、還在不在）。"""
    return f"{UPLOAD_TAG} {_HOST}#{os.getpid()}"


def _pid_alive(pid):
    """這個行程編號現在還活著嗎？看不出來（權限）就當活著，寧可留著也不要誤刪別人正在轉的檔。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError, OverflowError):
        return True
    # 🔴 行程編號是 32 位元不帶正負號的數字。檔名被亂改成 gs_chunk_0_600_p4294967296.wav 這種時，
    #    ctypes 塞不進 DWORD 會丟 ctypes.ArgumentError（不是 OSError），_sweep_leftovers 接不住，
    #    整支程式在轉檔還沒開始就結束。超出範圍的編號不可能對應到任何行程 → 當成不存在。
    if not 0 < pid < 2 ** 32:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return k32.GetLastError() == 5               # ERROR_ACCESS_DENIED：存在但看不到 → 當活著
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == 259                 # STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _owner(display_name):
    """雲端檔的名字是不是本工具掛的；是的話回傳 (電腦名稱, 行程編號)，舊版沒掛編號就回 (None, None)。"""
    dn = display_name or ""
    if dn == UPLOAD_TAG:
        return True, None, None
    if not dn.startswith(UPLOAD_TAG + " "):
        return False, None, None
    m = re.fullmatch(r"(.+)#(\d+)", dn[len(UPLOAD_TAG) + 1:])
    return (True, m.group(1), int(m.group(2))) if m else (True, None, None)


def _stale(mine_host, pid, age, max_age):
    """
    該不該清：留下它的行程在這台電腦而且已經不在了 → 立刻清；否則照年齡，夠舊就清。

    🔴 年齡是保底、不可以被跳過。Windows 會回收行程編號：當機留下的整場錄音，編號若剛好被別的
       長壽行程（例如開著一整天的瀏覽器）拿去用，「活著就不清」會讓它永遠留在雲端和 %TEMP%，
       比舊版「12 小時後一定清」還糟。所以死了立刻清、太舊也一定清，兩條規則同時成立。
    """
    if pid is not None and mine_host == _HOST and not _pid_alive(pid):
        return True
    return age >= max_age


def to_wav16k(src):
    out = os.path.join(tempfile.gettempdir(), f"gs_{abs(hash(src)) % 10**8}_p{os.getpid()}_16k.wav")
    _TEMP_FILES.append(out)
    try:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # 🔴 檔案損毀、0 bytes、還沒下載完、或副檔名對但其實不是音訊檔，
        #    都會走到這裡。原本 check=True 直接噴十幾行英文 traceback。
        tail = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        print(f"\n  \u2717 這個檔案讀不出聲音：{os.path.basename(src)}")
        print("      可能是檔案損毀、還沒下載完，或它其實不是音訊／影片檔。")
        if tail:
            print(f"      （ffmpeg 說：{tail[-1][:110]}）")
        raise SystemExit(1)
    return out


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        # ffprobe 讀不到長度（檔案壞了、或根本不是音訊）。不要噴 traceback。
        print(f"\n  \u2717 讀不到這個檔案的長度：{os.path.basename(path)}")
        print("      檔案可能損毀，或它其實不是音訊／影片檔。")
        raise SystemExit(1)


def hhmmss(t):
    return f"{int(t//3600):02d}:{int(t%3600//60):02d}:{int(t%60):02d}"


def _mins(sec):
    """單段上限顯示用的分鐘數。🔴 2026-09-20 筆電實測 N6-2：`--max-chunk-min 0.5` 時原本用 // 60 印成「0 分鐘」。"""
    return f"{sec / 60:g}"


def find_silences(wav, thresh_db=-35, min_sil=0.5):
    """用 ffmpeg 找靜音區間，回傳每段靜音的中點（秒）。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", wav,
         "-af", f"silencedetect=noise={thresh_db}dB:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    log = r.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", log)]
    return [(s + e) / 2 for s, e in zip(starts, ends)]


def plan_chunks(wav, dur):
    """把長錄音切成 <= MAX_CHUNK_SEC 的區段，盡量切在靜音處（不要切斷句子）。"""
    if dur <= MAX_CHUNK_SEC:
        return [(0.0, dur)]
    sil = find_silences(wav)
    bounds, t = [0.0], 0.0
    while dur - t > MAX_CHUNK_SEC:
        target = t + MAX_CHUNK_SEC
        # 在目標點前 5 分鐘內找最接近的靜音，找不到就硬切
        cand = [s for s in sil if target - 300 <= s <= target]
        cut = max(cand) if cand else target
        bounds.append(cut)
        t = cut
    # 🔴 2026-09-20 筆電實測 N3：找不到靜音、長度又只比「上限 × k」多一點時，會切出極短的尾段
    #    （180.0107 秒、上限 1 分鐘 → 第 4 段只有 10.7 毫秒）。模型對它回空內容，舊版當掉後誤報
    #    「1/4 段失敗、逐字稿不完整」還建議整份重轉。尾段短於上限的 1/10（最多 60 秒）就併回前一段：
    #    預設上限 28 分鐘時，併完最多 29 分鐘，仍在官方 30 分鐘的處理上限內。
    # 🔴 併完的那一段不可以超過官方 30 分鐘（開分講者時只處理 30 分、超過也不報錯）：--max-chunk-min 29.5 時
    #    尾段 50 秒一併就是 30 分 20 秒（2026-09-20 複查指出）。所以用「併完的實際長度」判斷，不只看尾段多短。
    if (len(bounds) > 1 and dur - bounds[-1] < min(60.0, MAX_CHUNK_SEC / 10)
            and dur - bounds[-2] <= 30 * 60):
        bounds.pop()
    bounds.append(dur)
    return list(zip(bounds[:-1], bounds[1:]))


def cut_audio(wav, start, end):
    out = os.path.join(tempfile.gettempdir(),
                       f"gs_chunk_{int(start)}_{int(end)}_p{os.getpid()}.wav")
    _TEMP_FILES.append(out)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", wav, "-ss", str(start), "-to", str(end),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out], check=True)
    return out


def _drop_remote(client, name):
    """把上傳到 Files API 的音訊刪掉。刪不掉也不要吵使用者。"""
    try:
        client.files.delete(name=name)
    except Exception:
        pass
    if name in _CLOUD_FILES:
        _CLOUD_FILES.remove(name)


def load_audio(client, wav):
    data = open(wav, "rb").read()
    if len(data) <= MAX_INLINE:
        return types.Part.from_bytes(data=data, mime_type="audio/wav")
    f = _with_retry("上傳錄音", lambda: client.files.upload(
        file=wav, config=types.UploadFileConfig(display_name=_upload_name())))
    # 🔴 上傳上去的是整段會議的原始聲音。不刪的話它會留在 Google 伺服器上
    #    （官方預設保留 48 小時），而使用者完全不知情。用完一定要刪。
    _CLOUD_FILES.append(f.name)
    atexit.register(_drop_remote, client, f.name)
    while f.state.name == "PROCESSING":
        time.sleep(2)
        # V1.38 審查（#6）：查處理狀態也是一次連網，網路斷了一樣要等網路回來（原本裸呼叫：斷一下就整份停）
        f = _with_retry("上傳錄音", lambda: client.files.get(name=f.name))
    return f


def _off(v):
    """'12.300s' → 12.3。
    🔴 實測長錄音會出現 start_offset / end_offset 是 None 的詞，
       直接 .rstrip() 會 AttributeError，讓整個工作崩掉。"""
    if v is None:
        return None
    try:
        return float(str(v).rstrip("s"))
    except (TypeError, ValueError):
        return None


def _span(words, limit=None):
    """取這一段的起訖秒數；跳過沒有時間戳的詞，全都沒有就回 (None, None)。

    🔴 2026-09-16：長音檔的詞時戳會嚴重失真。實測 2,760 秒的音檔回傳最大 end_offset
       = 82,975 秒（30 倍），另一支 2,700 秒的回 62,986 秒，兩支都重現。
       這種值一路寫進 start/end 的後果不只是檔頭時間亂掉 ——
       skel_end 會被撐成天文數字，`dur - skel_end` 變負數，
       **涵蓋率警語會全部失效**，跟沒做那道檢查一樣。
       所以給 limit（這一段本身的長度）：超過就當作沒有時戳，
       讓下游走「接在上一段後面」的保底路徑。
    """
    start = end = None
    for w in words or []:
        s = _off(getattr(w, "start_offset", None))
        if s is not None:
            start = s
            break
    for w in reversed(words or []):
        e = _off(getattr(w, "end_offset", None))
        if e is not None:
            end = e
            break
    if limit is not None:
        # 留 1 秒容差：正常情況下最後一個詞的結束時間可能略超過切點
        if start is not None and start > limit + 1:
            start = None
        if end is not None and end > limit + 1:
            end = None
    return start, end


def _parts(r):
    """模型回應裡的 parts。
    🔴 2026-09-20 筆電實測 N3：沒人講話（整段音樂）或極短的片段，模型會回空內容。舊版直接走訪
       `r.candidates[0].content.parts`，丟 `TypeError: 'NoneType' object is not iterable`，被當成
       「這一段失敗」，還叫使用者去跑診斷。空內容就是「這一段沒有辨識到任何話」，不是錯誤。
       桌機實測（純音樂 60 秒、純靜音 60 秒、10.7 毫秒片段，兩趟都測）：真的沒人講話時，回應一律是
       1 個候選、finish_reason＝STOP、content 在、parts 是 None。
    🔴 只有「正常結束（STOP）卻沒有內容」才算沒人講話。沒有候選（提示被擋）、prompt_feedback 有 block_reason、
       或 SAFETY／RECITATION／OTHER 這類異常結束，都要當成這一段失敗 —— 不然會被說成「沒人講話」，
       原因講錯，舊版至少還會列成失敗（2026-09-20 複查指出）。"""
    c = (getattr(r, "candidates", None) or [None])[0]
    content = getattr(c, "content", None) if c is not None else None
    parts = list(getattr(content, "parts", None) or [])
    if parts:
        return parts
    pf = getattr(r, "prompt_feedback", None)
    block = getattr(pf, "block_reason", None) if pf is not None else None
    fr = getattr(c, "finish_reason", None) if c is not None else None
    fr = getattr(fr, "name", None) or (str(fr).rsplit(".", 1)[-1] if fr is not None else None)
    if c is None or block or fr not in (None, "STOP"):
        why = (f"被擋下（{getattr(block, 'name', block)}）" if block else
               "沒有回傳任何結果（通常是被擋下）" if c is None else f"異常結束（{fr}）")
        raise RuntimeError(f"模型對這段錄音{why}，不是沒人講話")
    return []


def _fix_timestamps(segs, limit=None):
    """字很多、時間卻幾乎是 0 的段（時戳失真）→ 依這一段錄音自己的語速估出結束時間。

    🔴 2026-09-20 筆電實測 N4：4 分鐘的電台檔整檔轉，最後一段有 171 字，時戳卻是 204.0／204.0
       （同一段用切段模式轉是 203.8–240.0）。段尾檢查據此判「錄音 00:03:24 之後沒有辨識到任何話」，
       選單印 ⚠，使用者會以為缺內容而重轉、重複付費。
       判準：實字 ≥ 10、而且每秒超過 25 字（人講不了那麼快）。估法：同一段裡其他正常段落的平均語速
       （算不出來時：中文每秒 5 字、拼音文字每秒 13 個字母），不超過下一段的開頭、也不超過這一段錄音的長度。
       估出來的是「照平均語速大概講到這裡」，不是保證的下限：講得比平均快的人會被估長一點，
       所以只有「真的缺一大段」（遠超過這點誤差）時段尾檢查才會報。
    🔴 備援語速不可以中英文共用每秒 5 字：英文一個字母算一個實字，一秒講 12～15 個，照中文算會把英文估長
       約 3 倍，蓋掉真的段尾缺口（2026-09-20 複查指出）。
    """
    good_n = good_t = 0.0
    for s in segs:
        n, d = len(_real_raw(s.get("raw"))), float(s["end"]) - float(s["start"])
        if n >= 10 and d >= 1.0 and n / d <= 25:
            good_n, good_t = good_n + n, good_t + d
    if good_t >= 5.0:
        rate = good_n / good_t
    else:
        allraw = "".join(_real_raw(s.get("raw")) for s in segs)
        rate = 13.0 if allraw and sum(ch.isascii() for ch in allraw) > len(allraw) / 2 else 5.0
    for k, s in enumerate(segs):
        n, st = len(_real_raw(s.get("raw"))), float(s["start"])
        if n < 10 or float(s["end"]) - st >= n / 25:
            continue
        bound = next((float(x["start"]) for x in segs[k + 1:] if float(x["start"]) > st), None)
        if bound is None:
            bound = float(limit) if limit else st + n / rate
        s["end"] = max(st, min(st + n / rate, bound))
    return segs


def _real_raw(t):
    """骨架（簡體）的實字：只留文字與數字。"""
    return "".join(ch for ch in (t or "") if ch.isalnum())


def pass1_skeleton(client, src, limit=None):
    """講者 + 時間軸。輸出必為簡體，只當骨架用。

    limit＝這一段音訊的長度（秒）。實測長音檔的詞時戳會失真到 30 倍，
    交給 _span() 當合理性上界用，詳見那邊的說明。
    """
    r = _with_retry("第 1 趟轉錄", lambda: client.models.generate_content(
        model=TRANSCRIBE_MODEL, contents=[src],
        config=types.GenerateContentConfig(audio_transcription_config=ATC(
            mode=MODE.VERBATIM, diarization=True, word_timestamp=True,
            language_codes=["cmn-Hant-TW"]))))
    segs = []
    prev_end = 0.0
    for p in _parts(r):
        at = getattr(p, "audio_transcription", None)
        if not at or not at.text:
            continue
        st, en = _span(at.words, limit)
        # 沒有時間戳就接在上一段後面，至少維持順序，不要讓整批壞掉
        st = prev_end if st is None else st
        # 🔴 2026-09-16：原本只在 en 是 None 時回填，en 是個「比 st 還小的真實值」時會原樣放行。
        #    實測一份 45 分鐘分段的逐字稿有 4 列結束早於開始，最誇張的一列早了 30 分 14 秒、
        #    還掛著 3,797 字正文 —— 那種列會讓所有以時戳為量尺的檢查算出負數的區間。
        #    模型偶爾就是會回一個倒退的 end，這裡把它抬到 st，讓「結束不早於開始」成為不變量。
        en = st if en is None else max(st, en)
        prev_end = max(prev_end, en)
        segs.append({"speaker": at.speaker_label or "spk:0",
                     "start": st, "end": en, "raw": at.text,
                     "tl": _timeline(at.words)})     # 只在記憶體裡用（切長段時內插時間），不寫進檔
    return _fix_timestamps(segs, limit), r.usage_metadata


def _timeline(words):
    """骨架每個詞的（字數比例, 開始秒數），給 _split_long 內插時間用。沒有詞時戳就回 None（退回按比例）。"""
    pts, pos = [], 0
    total = sum(len(getattr(w, "word", None) or "") for w in words or []) or 0
    for k, w in enumerate(words or []):
        t = _off(getattr(w, "start_offset", None))
        if t is not None:
            ratio = pos / total if total else k / max(1, len(words))
            pts.append((min(1.0, ratio), t))
        pos += len(getattr(w, "word", None) or "")
    return pts or None


def _at_ratio(tl, r, st, en):
    """正文第 r 成的位置對應到第幾秒：有詞時戳就照時戳內插，沒有就照字數比例。"""
    if not tl:
        return st + (en - st) * r
    prev = (0.0, st)
    for ratio, t in tl:
        if ratio >= r:
            span = ratio - prev[0]
            return prev[1] + (t - prev[1]) * ((r - prev[0]) / span if span > 0 else 1.0)
        prev = (ratio, t)
    return prev[1] + (en - prev[1]) * ((r - prev[0]) / (1.0 - prev[0]) if prev[0] < 1.0 else 1.0)


def _split_long(segs, max_chars=None):
    """
    一位講者一口氣講很久時，骨架只有一段、正文兩三千字擠成一團（2026-09-14 驗收：8 分鐘獨白＝一段 1,959 字）。
    照句子切成不超過 max_chars 字的小段：文字一字不改、講者不變，每小段的時間依骨架的詞時戳內插
    （沒有詞時戳就照字數比例）。順便把只在記憶體用的 tl 拿掉，不讓它寫進 .json。
    """
    max_chars = SPLIT_CHARS if max_chars is None else max_chars
    out = []
    for s in segs:
        tl = s.pop("tl", None)
        text = s.get("text") or ""
        if len(text) <= max_chars:
            out.append(s)
            continue
        pieces, cur = [], ""
        for u in _units(text):
            if cur and len(cur) + len(u) > max_chars:
                pieces.append(cur)
                cur = u
            else:
                cur += u
        if cur:
            if pieces and len(cur.strip()) < max_chars // 4:
                pieces[-1] += cur                      # 尾巴太短就併回上一段，不要孤零零一句
            else:
                pieces.append(cur)
        if len(pieces) < 2:
            out.append(s)
            continue
        st = float(s.get("start") or 0)
        en = float(s.get("end") or s.get("start") or 0)
        offs, acc = [], 0
        for p in pieces:
            offs.append(acc)
            acc += len(p)
        times, last = [], st
        for o in offs:
            t = max(last, min(en, _at_ratio(tl, o / max(1, len(text)), st, en)))
            times.append(t)
            last = t
        for k, p in enumerate(pieces):
            piece = dict(s)
            if k:
                # 🔴 raw 是整段的簡體骨架（一口氣講 8 分鐘時可達兩千字）。每一片都複製一份，
                #    .json 與 partial.json 會被同一段簡體文字灌成好幾倍大。只有第一片留著就夠了
                #    （json_to_md／translate_transcript 只在沒有 text 時才回頭看 raw，這裡每片都有 text）。
                piece.pop("raw", None)
            piece["text"] = p.strip()
            piece["start"] = times[k]
            piece["end"] = times[k + 1] if k + 1 < len(pieces) else en
            out.append(piece)
    return out


def _chunk_holes(chunk_spans):
    """段的中間整片沒有句子 → 那段可能被模型跳過了。

    為什麼需要它：_coverage_gaps 只比「這一段的時戳有沒有走到段尾」。實測一段
    0:55:55–1:23:54 的錄音，句子從 1:05:15 直接跳到 1:19:27（中間 14.2 分鐘一句都沒有），
    但它的最後一句落在 1:23:49、離段尾只差 5 秒 —— 段尾檢查完全過關，零警告。
    把那 14.2 分鐘剪出來單獨轉，內容是滿的，所以不是沒人講話。

    輸入 [(段號, 段起點, 段終點, [(句子起, 句子迄), ...]), ...]，時間都是「段內相對秒數」。

    🔴 一定要先排序再比，不可以照檔案順序兩兩相減：實測有一段的第 0 列時戳是 1:40:45，
       而它後面 104 列是從 1:25:33 開始 —— 照順序算會生出一個 15 分鐘的假洞。
    🔴 用「跑動最大 end」而不是「前一句的 end」：句子會互相重疊，也會有一個巨句蓋住整段，
       用前一句比會把被包住的句子當成洞。
    🔴 段首與段尾不看 —— 切點刻意挑在靜音處，那裡天生安靜，歸 _coverage_gaps 管。
    """
    gaps = []
    for idx, cs, ce, spans in (chunk_spans or []):
        pairs = []
        for st, en in (spans or []):
            try:
                st = float(st)
                en = float(en)
            except (TypeError, ValueError):
                continue        # 壞掉的時戳跳過就好，不要讓檢查程式自己炸掉
            pairs.append((st, max(st, en)))
        if len(pairs) < 2:
            continue
        pairs.sort()
        cov = None
        for st, en in pairs:
            if cov is not None and st - cov > HOLE_GAP:
                a, b = cs + cov, cs + st
                gaps.append(
                    f"第 {idx} 段的中間，{hhmmss(a)} 到 {hhmmss(b)}（約 {(b - a) / 60:.0f} 分鐘）"
                    f"沒有辨識到任何話：可能是那段沒人講話，也可能是模型跳過了。"
                    f"把錄音的 {hhmmss(a)} 到 {hhmmss(b)} 剪出來單獨轉一次就知道了 ——"
                    f"轉得出內容就是被跳過了，真的沒人講話的話結果會是空的")
            cov = en if cov is None else max(cov, en)
    return gaps


def _pass_gap(chunk_txt):
    """正文遠多於骨架 → 第 1 趟塌掉了，第 2 趟多出來的那些內容沒有時間軸可以掛。

    實測一段：骨架 1,294 字、正文 14,045 字（10.85 倍）。那一段的正文後來被驗出是
    一個精確的 13 句循環重複了 6 次 —— 也就是多出來的字不是內容，是模型在空轉。

    輸入 [(段號, 段起點, 段終點, 骨架字數, 正文字數), ...]。

    🔴 兩個條件要同時成立，而且絕對量要擋在倍數前面：短段落的倍數天生不穩
       （骨架 80 字、正文 400 字就是 5 倍，但只差 320 字，那很可能只是正常的潤稿）。
    🔴 max(n_raw, 1) 是為了讓「骨架一個字都沒有」（最嚴重的情況）必定觸發而不是除以零。
    🔴 只抓「正文 >> 骨架」這一個方向。反向（正文比骨架少）在實測裡，故障段是 0.79、
       而乾淨段落在 0.79–1.11，兩者完全重疊 —— 訂任何反向門檻都只是憑感覺。
    """
    gaps = []
    for idx, cs, ce, n_raw, n_text in (chunk_txt or []):
        try:
            n_raw = int(n_raw or 0)
            n_text = int(n_text or 0)
        except (TypeError, ValueError):
            continue
        if n_text - n_raw < PASS_SURPLUS:
            continue
        if n_text < PASS_RATIO * max(n_raw, 1):
            continue
        gaps.append(
            f"第 {idx} 段（{hhmmss(cs)}–{hhmmss(ce)}）的兩趟結果對不起來："
            f"第 1 趟（分講者＋時間軸）只辨識出 {n_raw:,} 字，第 2 趟（正文）卻有 {n_text:,} 字，"
            f"差了 {n_text / max(n_raw, 1):.1f} 倍。這一段的時間軸和講者可能大範圍錯位，"
            f"正文也可能有憑空多出來的內容。建議把這一整段剪成兩三小段分別轉一次再對照 ——"
            f"不是只補尾巴，是整段都要重來")
    return gaps


def _loop_gap(chunk_loop):
    """第 2 趟正文自我重複 → 同一批話被反覆輸出，看起來像講了很多次。

    這是最危險的一種，因為時間軸是滿的、畫面會照印 ✅。實測兩段中招：
    一段 12,009 字裡有 5,483 字是重複的（50.7%），另一段 14,045 字裡有 11,977 字（90.8%）。
    要拿逐字稿當會議紀錄的人會把同一句話當成真的講了十幾次去引用。

    輸入 [(段號, 段起點, 段終點, 正文), ...]。

    🔴 一定要吃 align() **之前**的正文。迴圈文字流過 align 與 _split_long 之後，
       會被切成幾十列、每列長度正常，外觀完全看不出來。
    🔴 要整段一起算，不可以改成滑動區間平均：迴圈的週期約 1,000 字，
       用 1,000 字的視窗去量最壞區間反而只有 0.9%，比乾淨段還低。
    🔴 兩個條件同時成立才報。逐字稿本來就有「好，謝謝」「對對對」這種高頻短語，
       只看比例會對短段落誤報。
    """
    gaps = []
    for idx, cs, ce, text in (chunk_loop or []):
        body = "".join(ch for ch in str(text or "") if ch.isalnum())
        if len(body) <= LOOP_WIN:
            continue
        wins = [body[i:i + LOOP_WIN] for i in range(len(body) - LOOP_WIN)]
        if not wins:
            continue
        dup = len(wins) - len(set(wins))
        ratio = dup / len(wins)
        if ratio < LOOP_RATIO or dup < LOOP_CHARS:
            continue
        # 找一段最常出現的文字當樣本，讓使用者一眼認出是哪句話在跳針
        counts = {}
        for w in wins:
            counts[w] = counts.get(w, 0) + 1
        worst, times = max(counts.items(), key=lambda kv: kv[1])
        gaps.append(
            f"第 {idx} 段（{hhmmss(cs)}–{hhmmss(ce)}）的正文有大量重複："
            f"約 {ratio * 100:.0f}% 的內容是重覆出現的（{dup:,} 字），"
            f"例如「{worst}」出現了 {times} 次。"
            f"重複的部分不是真的講了那麼多次，不要照字引用。"
            f"這一段建議剪成兩三小段分別轉一次再對照")
    return gaps


_VOICE_DB = [None, None]      # [(路徑, 大小, 修改時間), dB 陣列]：_voiced_holes 與 _voice_note 讀同一份錄音只讀一次


def _voice_db(wav):
    """16k 單聲道 wav → 每 VOICE_FRAME 秒一格的音量（dB，numpy 陣列；沒有內容＝空陣列）。"""
    import wave
    import numpy as np
    key = (wav, os.path.getsize(wav), os.path.getmtime(wav))
    if _VOICE_DB[0] != key:
        rms = []
        with wave.open(wav, "rb") as w:
            n = int(w.getframerate() * VOICE_FRAME)
            while True:
                b = w.readframes(n * 600)                  # 一次讀 60 秒，三小時的會議也不必整份放進記憶體
                if not b:
                    break
                x = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
                k = len(x) // n
                if k:
                    rms.append(np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1)))
        _VOICE_DB[:] = [key, 20 * np.log10(np.maximum(np.concatenate(rms), 1e-9)) if rms else np.zeros(0)]
    return _VOICE_DB[1]


def _voice_runs(db):
    """(每一格有沒有聲音, 有聲音的格子接成的段落 [(起, 迄)])。
    🔴 門檻跟著這份錄音自己的底噪走（最安靜的 10% 再加 VOICE_ABOVE_FLOOR，最低 −60 dBFS），不用固定 dB：會議室底噪差很多。
    停頓不超過 VOICE_BRIDGE 秒算同一段話。"""
    import numpy as np
    mask = db > max(float(np.percentile(db, 10)) + VOICE_ABOVE_FLOOR, -60.0)
    runs, st, last = [], None, None
    for j in np.flatnonzero(mask):
        t = j * VOICE_FRAME
        if st is not None and t - last > VOICE_BRIDGE:
            runs.append((st, last + VOICE_FRAME))
            st = None
        st = t if st is None else st
        last = t
    if st is not None:
        runs.append((st, last + VOICE_FRAME))
    return mask, runs


def _voice_note(wav):
    """V1.36（待辦 18 B）：這份錄音「有聲音卻沒有字」那道檢查看不準時，回傳一句說明；看得準回 None。
    檔頭寫成 ℹ️ 一行、存在 .json 的 meta["notes"]——只是說明這道檢查的能力，不算缺口、不影響 ✅（審查第二輪：
    第一版放進缺口清單，整份明明什麼都沒列，檔頭卻寫「可能不完整」、畫面打 ⚠）。條件見 NOISY_RANGE 上面的說明。"""
    import numpy as np
    db = _voice_db(wav)
    if not len(db):
        return None
    _mask, runs = _voice_runs(db)
    spread = float(np.percentile(db, 99) - np.percentile(db, 10))
    long_share = sum(b - a for a, b in runs if b - a >= VOICE_HOLE) / (len(db) * VOICE_FRAME)
    if spread < NOISY_RANGE and long_share < NOISY_COVER:
        return (f"這份錄音幾乎沒有安靜的時候（最大聲和最安靜的時段只差約 {spread:.0f} dB，例如一直有背景音樂、轉播或很大的雜音），"
                f"「錄音裡有聲音、逐字稿卻沒有標到的時段」這項檢查看不準：沒有列出來的地方也可能漏了話，重要的段落請對照錄音抽查")
    return None


def _voiced_holes(arg):
    """錄音裡有聲音、逐字稿卻沒有任何段落涵蓋的時段（V1.22 ①）。回傳要寫進檔頭的警語。

    🔴 2026-09-25 自製會議實測：中文會議裡外賓講的 18 秒英文兩趟都沒轉出來（4/4 次一字不差），檔頭沒有任何警語。
       上面幾道檢查看的都是第 1 趟的時戳，而第 1 趟根本沒聽到那段 —— 結構上不可能抓到。
       這一道直接看錄音本身：用音量找出「有聲音」的時段，扣掉逐字稿段落涵蓋的時間，剩下夠長的就列出來。
    🔴 音樂、掌聲、影片的背景音也是「有聲音、沒有字」，警語要照實講有這些可能。
    V1.36：①有聲段落（停頓 ≤ VOICE_BRIDGE 接成一段）沒被蓋到的連續 VOICE_HOLE 秒以上、而且裡面實際有聲音的格子
    ≥ VOICE_DENSE，也 ≥ 逐字稿有蓋到的時段有聲比例 × VOICE_DENSE_REL；②逐字稿沒蓋到的時間裡，任一 VOICE_SUM_WIN 秒內有聲音的格子加起來 ≥ VOICE_SUM 秒（中間停多久都接得起來）。
    兩條報到的都列，重疊的併成一段（審查第三輪：原本②跟①重疊就整段不列，①只蓋到前面一小段時，後面漏掉的幾句沒列出來）。
    arg＝(16k 單聲道 wav, 全部段落（已接回整段時間軸）, 失敗段的 [(起, 迄)]：失敗的段另有警語，不重複報)
    """
    import numpy as np
    wav, segs, skip = arg
    db = _voice_db(wav)
    if not len(db):
        return []
    mask, runs = _voice_runs(db)
    cover = [(float(a), float(b)) for a, b in skip]
    for s in segs:
        if s.get("text") == OMITTED:
            continue
        a, b = float(s.get("start") or 0), float(s.get("end") or s.get("start") or 0)
        # V1.35（待辦 10）：很長卻幾乎沒字的段落，只算頭尾各 SPARSE_EDGE 秒有涵蓋（見 SPARSE_LONG 上面的說明）
        if b - a > SPARSE_LONG and sum(ch.isalnum() for ch in str(s.get("text") or "")) < (b - a) * SPARSE_CPS:
            cover += [(a, a + SPARSE_EDGE), (b - SPARSE_EDGE, b)]
        else:
            cover.append((a, b))
    # ① 的有聲比例門檻跟著這份錄音走（見 VOICE_DENSE_REL）：逐字稿有蓋到的時段裡，有聲音的格子佔幾成
    seg = np.zeros(len(mask), bool)
    for a, b in cover[len(skip):]:
        seg[int(round(a / VOICE_FRAME)):int(round(b / VOICE_FRAME))] = True
    dense = max(VOICE_DENSE, VOICE_DENSE_REL * float(mask[seg].mean())) if seg.any() else VOICE_DENSE
    cover.sort()
    holes, k = [], 0
    for a, b in runs:
        while k < len(cover) and cover[k][1] <= a:
            k += 1
        t, j = a, k
        while j < len(cover) and cover[j][0] < b:
            if cover[j][0] - t >= VOICE_HOLE:
                holes.append((t, cover[j][0]))
            t, j = max(t, cover[j][1]), j + 1
        if b - t >= VOICE_HOLE:
            holes.append((t, b))
    # ①：洞裡實際有聲音的格子要夠（停頓裡零星幾聲被接成一段的不算）
    holes = [(x, y) for x, y in holes
             if mask[int(round(x / VOICE_FRAME)):int(round(y / VOICE_FRAME))].mean() >= dense]
    # ②：逐字稿沒蓋到的每一段時間（含開頭、結尾）裡，任一 VOICE_SUM_WIN 秒內有聲音的格子加起來夠多也報——
    #    報落在這種視窗裡的第一聲到最後一聲（中間空超過 VOICE_SUM_WIN 秒就分開報）
    w, need = int(round(VOICE_SUM_WIN / VOICE_FRAME)), int(round(VOICE_SUM / VOICE_FRAME))
    dur, t = len(db) * VOICE_FRAME, 0.0
    for a, b in cover + [(dur, dur)]:
        if a > t:
            i, j = int(round(t / VOICE_FRAME)), int(round(min(a, dur) / VOICE_FRAME))
            m = mask[i:j]
            cs = np.concatenate([[0], np.cumsum(m)])
            st = np.arange(max(len(m) - w, 0) + 1)                       # 視窗起點（比視窗短的時段＝整段一個視窗）
            ok = np.zeros(len(m), int)
            ok[st[cs[np.minimum(st + w, len(m))] - cs[st] >= need]] = 1   # 夠密的視窗起點
            co = np.concatenate([[0], np.cumsum(ok)])
            v = np.arange(len(m))
            idx = np.flatnonzero(m & (co[v + 1] - co[np.maximum(v + 1 - w, 0)] > 0))   # 有聲音、又落在夠密的視窗裡
            for g in np.split(idx, np.flatnonzero(np.diff(idx) > w) + 1) if len(idx) else []:
                holes.append(((i + g[0]) * VOICE_FRAME, (i + g[-1] + 1) * VOICE_FRAME))
        t = max(t, b)
    out = []
    for x, y in sorted(holes):                    # ①②重疊的併成一段
        if out and x <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], y))
        else:
            out.append((x, y))
    return [f"{hhmmss(x)}–{hhmmss(y)} 這 {int(y - x)} 秒的錄音裡有聲音，逐字稿卻沒有標到這段時間："
            f"可能是外語、音樂、掌聲或雜音，也可能是話沒轉出來、或被併到前後段（那一帶的講者與時間可能不對）。"
            f"請對照錄音聽一下這段" for x, y in out]


def _overlap_gaps(segs):
    """段落時間互相重疊或倒退（V1.35，待辦 10）。回傳要寫進檔頭的警語。
    照順序走一遍：下一段開始得比前面最晚的結束還早 OVERLAP_MIN 秒以上就記下來，相鄰的併成一個範圍。
    🔴 2026-10-03 X10：體育廣播的字被放到會議那幾段的時間上（同一時間範圍兩套內容、時間倒退 3 處），檔頭沒有任何警語。"""
    rng, end = [], None
    for s in segs:
        if s.get("text") == OMITTED:
            continue
        a = float(s.get("start") or 0)
        b = float(s.get("end") or a)
        if end is not None and a < end - OVERLAP_MIN:
            if rng and a <= rng[-1][1]:
                rng[-1][1] = max(rng[-1][1], b, end)
            else:
                rng.append([a, max(b, end)])
        end = b if end is None else max(end, b)
    return [f"{hhmmss(x)}–{hhmmss(y)} 這一帶有段落的時間互相重疊或倒退（可能是同一段時間放了兩套內容，或時間標錯了）："
            f"那一帶的講者、時間與內容的對應可能不對，請對照錄音聽一下" for x, y in rng]


def _coverage_gaps(dur, skel_end, out_end, chunk_cov=None, n_chunks=None, tail=True):
    """
    逐字稿有沒有漏掉內容。回傳要寫進檔頭與畫面的警語（空清單＝沒問題）。

    🔴 2026-09-14 驗收：9.5 分鐘錄音的逐字稿少了最後 96 秒，檔頭仍寫「長度 00:09:30」、畫面照樣 ✅。
       第 1 趟（骨架）有辨識到、整理後的正文卻沒有 → 正文被精簡掉（同一段話大量重複時會這樣）；
       第 1 趟就沒辨識到 → 錄音後段可能是靜音、音樂、雜音或壞掉。兩種都要講清楚。

    🔴 兩種缺口是各自獨立的，會同時發生（中段被整理掉、尾段又沒辨識到）。原本寫成 if／elif，
       只報得出前面那一條，使用者照著檢查完就以為沒事了。兩條都要回。

    🔴 2026-09-16：上面兩條都只看得到「整份的尾巴」，看不到「中間的洞」。
       main() 的 skel_end 是 max(所有段)，只要最後一段完整，指標就被撐到錄音結尾。
       所以要另外逐段檢查：chunk_cov = [(段號, 段起點, 段終點, 該段骨架最後時戳), ...]，
       只放**成功跑完**的段（失敗的段另有失敗清單負責）。

    🔴 這一支只量得到「段的尾巴」。同日查證一份 2:56:47 的會議還發現另外兩種故障，
       它結構上看不到，分別由 _chunk_holes 與 _pass_gap／_loop_gap 負責：
         · 時戳走到段尾、但中間整片沒有句子（實測有一段中間空了 14.2 分鐘，這裡完全過關）
         · 時間軸看起來是滿的、正文卻在自我重複（實測一段 12,009 字裡有 5,483 字是重複的）
       🔴 不要把「這一支沒報」當成「這一段沒問題」。
    """
    gaps = []
    if tail:
        if dur - skel_end > COVER_GAP:
            gaps.append(f"錄音 {hhmmss(skel_end)} 之後沒有辨識到任何話（錄音長 {hhmmss(dur)}）："
                        f"後段可能是靜音、音樂、雜音，或檔案本身有問題")
        if skel_end - out_end > COVER_GAP:
            gaps.append(f"{hhmmss(out_end)} 之後的內容在整理成正文時被略去了（第 1 趟辨識到 {hhmmss(skel_end)}）："
                        f"同一段話大量重複時會這樣；需要那一段的話，請把它另外剪出來再轉一次")
    for idx, cs, ce, seg_end in (chunk_cov or []):
        # 🔴 最後一段的尾巴由上面第一條負責，不重複報。
        #    判準用「段號是不是最後一段」，不可以用 ce 跟 dur 比時間 ——
        #    最後一段短於 COVER_GAP 時，會把倒數第二段也一起誤放行。
        if n_chunks is not None and idx >= n_chunks:
            continue
        miss = ce - seg_end
        # 🔴 門檻比 COVER_GAP 大很多：切點刻意挑在靜音處，每一段的尾巴天生帶著一小段安靜，
        #    用 30 秒去量會對完整的逐字稿發假警報。
        if miss <= CHUNK_GAP:
            continue
        howmuch = f"約 {miss / 60:.0f} 分鐘" if miss >= 90 else f"約 {int(miss)} 秒"
        # 🔴 2026-09-16 改掉舊文案：它寫「可能是這一段太長、超過 30 分鐘的處理長度」，
        #    但實測觸發這條的那一段只有 28 分鐘、根本沒碰到那個上限，等於教使用者往錯的方向查。
        #    這裡不再猜原因 —— 給一個他自己就能驗證的做法比猜測有用。
        gaps.append(f"第 {idx} 段（{hhmmss(cs)}–{hhmmss(ce)}）只辨識到 {hhmmss(seg_end)}，"
                    f"這一段的後面{howmuch}沒有內容："
                    f"可能是那段沒人講話，也可能是模型沒辨識到。"
                    f"把錄音的 {hhmmss(seg_end)} 到 {hhmmss(ce)} 剪出來單獨轉一次就知道了 ——"
                    f"轉得出內容就是被跳過了，真的沒人講話的話結果會是空的")
    return gaps


def pass2_clean(client, src, vocab, retry=True):
    """乾淨的繁體正文（模型原生輸出，非翻譯）。retry=False：伺服器忙也不重試（補轉用，見 _recover_lost）。

    🔴 2026-09-25（V1.22 ①）：語言碼只給 cmn-Hant-TW 時，中文會議裡外賓講的英文會**整段消失**
       （自製 3 分鐘會議：18 秒英文，4/4 次一字不差地不見，檔頭沒有任何警語）。
       對照實驗只改這一個變因：加上 en-US 之後英文完整出現，中文仍是繁體（簡體字 0 個）。
       🔴 代價要照實記：中文**不是**一字不變。中廣新聞 4 分鐘 A/B 98.4% 一字不差，差的 19 處有好有壞
       （人名「標槍」→「北口臻花」變好、「改換門庭」→「門亭」變差、語助詞多刪一些）；自製會議一句
       「下一次會議」→「這一次會議」（2/2 次）。判斷是：英文整段消失比這種零星差異嚴重，所以加。
       第 1 趟（分講者）不管給不給語言碼都聽不到那段英文（實測兩種），所以只改這裡；
       那段英文會被對齊到前後段，講者與時間可能不對 —— 由 _voiced_holes 在檔頭提醒去聽。
    """
    cfg = ATC(mode=MODE.SMART, language_codes=["cmn-Hant-TW", "en-US"])
    if vocab:
        cfg.custom_vocabulary = vocab
    call = lambda: client.models.generate_content(          # noqa: E731
        model=TRANSCRIBE_MODEL, contents=[src],
        config=types.GenerateContentConfig(audio_transcription_config=cfg))
    r = _with_retry("第 2 趟轉錄", call) if retry else call()
    txt = []
    for p in _parts(r):
        at = getattr(p, "audio_transcription", None)
        if at and at.text:
            txt.append(at.text)
        elif getattr(p, "text", None) and not at:
            txt.append(p.text)
    return "\n".join(txt).strip(), r.usage_metadata


def _transient(exc):
    """伺服器暫時忙不過來（5xx）或網路閃斷 —— 等一下再試就會好的那種。"""
    if _permanent(exc):
        return False                    # 額度用完、金鑰失效、DNS 掛掉：重試也一樣
    if isinstance(exc, gerr.ServerError):
        return True
    if isinstance(exc, gerr.ClientError):
        return False                    # 4xx：參數或權限問題，重試也一樣
    mod = (type(exc).__module__ or "").split(".")[0]
    return (isinstance(exc, (ConnectionError, TimeoutError))
            or mod in ("httpx", "httpcore", "requests", "urllib3")
            or "timed out" in str(exc).lower())


def _with_retry(what, fn):
    """
    🔴 伺服器忙（503「This model is currently experiencing high demand」）時，generate_content 在 SDK
       預設下**完全不重試**（google-genai 2.22：沒設 retry_options 時 retry_args 回傳「只試 1 次」），
       一次 503 整份錄音就失敗了（2026-09-11 實測遇過）。例外：files.upload 傳送分塊時，SDK 另有一段
       寫死的重試（_api_client._upload_fd：回應沒帶 x-goog-upload-status 標頭就等 1、2、4 秒重送，最多 3 次）。
       這裡補一層：等久一點再試，
       並用中文告訴使用者現在在等什麼。額度用完、參數錯誤這種重試也不會好的，不重試。
    🔴 V1.38（下一版待辦 20）：網路斷了（查不到伺服器位址，_live.net_down）另外處理：每 NET_WAIT_STEP 秒再試，
       同一次斷網最多等 NET_WAIT_MAX 秒，畫面講清楚在等網路、網路回來時也講一聲。「已經等了多久」整份共用
       （_net_waited）：任何一次呼叫成功就歸零；一直沒回來，等滿之後的呼叫不再各等一次（段落迴圈接著就停）。
       V1.38 審查（#5）：伺服器有回應（APIError：503、429…）也歸零——那證明網路回來了；不歸零的話，斷 280 秒、回一次 503、
       再斷一下，就會被說成「網路一直沒有回來（等了 5 分鐘）」而停掉整份。ReadError 這類不算（證明不了網路回來了）。
       等網路的訊息不預告「等不到會怎樣」（#2、#9）：段落迴圈會停、對齊會改用估算，各自在那裡講。
       2026-10-04 實測：Wi-Fi 斷約 40 秒，第 2 趟先 ReadError（照常重試），重試時變成 getaddrinfo failed，
       以前被當成「重試也不會好」→ 整份停下、沒有產出；其實 40 秒後網路就回來了。
    """
    global _net_waited
    waits = tuple(RETRY_WAITS)
    k = 0
    while True:
        try:
            r = fn()
        except Exception as e:
            if _net_waited and isinstance(e, gerr.APIError) and not _net_down(e):
                # 審查第 2 輪：①本身就被判成網路斷了的錯誤頁（例如代理回的 502 內文有 DNS 字樣）不算回來，不然每輪都歸零、永遠等不完
                #    ②不說「繼續」：同一個錯誤可能接著就讓工作停下（例如額度用完）
                print(f"  ✓ 網路回來了（等了 {_net_waited} 秒）")
                _net_waited = 0
            if _net_down(e):
                if _net_waited >= NET_WAIT_MAX:
                    raise
                if _net_waited == 0:
                    print(f"  ⚠ {what}：網路斷了，先等網路回來：每 {NET_WAIT_STEP} 秒再試一次，"
                          f"最多等 {NET_WAIT_MAX // 60} 分鐘")
                else:
                    print(f"  … 網路還沒回來，{NET_WAIT_STEP} 秒後再試（已經等了 {_net_waited} 秒）")
                time.sleep(NET_WAIT_STEP)
                _net_waited += NET_WAIT_STEP
                continue
            if k == len(waits) or not _transient(e):
                raise
            why = "伺服器目前很忙" if isinstance(e, gerr.ServerError) else "網路連線不穩"
            print(f"  ⚠ {what}：{why}（{type(e).__name__}），{waits[k]} 秒後再試"
                  f"（第 {k + 1} 次，最多 {len(waits)} 次）")
            time.sleep(waits[k])
            k += 1
            continue
        if _net_waited:
            print(f"  ✓ 網路回來了（等了 {_net_waited} 秒），繼續")
            _net_waited = 0
        return r


def _sweep_leftovers(client, cloud_age=None, temp_age=None):
    """
    清掉上一次沒刪乾淨的暫存。

    🔴 上傳的錄音和 %TEMP% 的暫存，原本只在「程式正常結束」時刪。當機、斷電、從工作管理員
       結束，兩個都會留下：雲端那份最多留 48 小時，本機那份（整場會議的原始聲音）永遠留著
       （2026-09-11 實測）。所以每次開始轉檔前，先清掉**夠舊**的——太新的可能是另一個視窗
       正在轉的，不能碰。雲端只刪掛了本工具名字的檔：同一把金鑰底下可能有別的程式的檔案。
    """
    cloud_age = SWEEP_CLOUD_AGE if cloud_age is None else cloud_age
    temp_age = SWEEP_TEMP_AGE if temp_age is None else temp_age
    now, n_cloud, n_temp = time.time(), 0, 0
    try:
        for fo in client.files.list():
            mine, host, pid = _owner(getattr(fo, "display_name", None))
            # 🔴 「pid 等於自己就跳過」要連電腦名稱一起比：別台電腦留下的舊檔，編號剛好等於本機
            #    這一次的 pid 時（幾萬分之一，但錄音一留就是 48 小時），會被誤認成「自己正在用」而永遠不清。
            if not mine or (pid == os.getpid() and host == _HOST):
                continue
            ct = getattr(fo, "create_time", None)
            age = (now - ct.timestamp()) if ct is not None else 0
            if _stale(host, pid, age, cloud_age):
                _drop_remote(client, fo.name)
                n_cloud += 1
    except Exception:
        pass                            # 清不到就算了，不能因此擋住轉檔
    tmp = tempfile.gettempdir()
    try:
        names = os.listdir(tmp)
    except OSError:
        names = []
    for name in names:
        low = name.lower()
        if not ((low.startswith("gs_chunk_") and low.endswith(".wav"))
                or (low.startswith("gs_") and low.endswith("_16k.wav"))):
            continue
        p = os.path.join(tmp, name)
        m = re.search(r"_p(\d+)(?:_16k)?\.wav$", low)
        pid = int(m.group(1)) if m else None
        if pid == os.getpid():
            continue
        try:
            if os.path.isfile(p) and _stale(_HOST if pid is not None else None, pid,
                                            now - os.path.getmtime(p), temp_age):
                os.remove(p)
                n_temp += 1
        except OSError:
            pass
    if n_cloud or n_temp:
        print(f"  （清掉上次沒刪乾淨的暫存：雲端 {n_cloud} 份、本機 {n_temp} 份）")
    return n_cloud, n_temp


# 對齊時把繁體正文切成的最小單位：到這些標點為止算一小句（標點跟著前一句）。
_CUT = set("。！？；，、…!?;,\n")


# V1.35（待辦 10）：只剩「11.」這種清單編號的碎片（見 _units 最後一段）。
# ⛔ 不要把正文行首的「1. 2. 3.」拿掉：V1.35 第一版這樣做，實測標準素材 f245 講者說的是「第一項，…第二項，…第三項，…」，
#    第 2 趟把它排成 1. 2. 3.，拿掉之後「第幾項」整個不見（V1.34 至少還留著編號）。行政會議很常這樣講，比 X10 多一個「7.」更糟。
#    要治本是叫第 2 趟照講者原話、不要自己編號（改提示詞要另外實測，列下一版待辦）。
_LONE_MARK = re.compile(r"\s*\d{1,3}[.、)）]\s*")


def _units(text):
    """把繁體正文切成一小句一小句。🔴 每一句一字不改，全部接起來必須等於原文。"""
    units, cur = [], []
    for k, ch in enumerate(text):
        cur.append(ch)
        # 🔴 半形句點只在「後面是空白或結尾」時才算句尾：英文正文靠「. 」分句（沒有這條，
        #    整段英文只切得出一句，換人講話的位置無從表達），但「3.5」中間的點不能切。
        if ch in _CUT or (ch == "." and (k + 1 == len(text) or text[k + 1].isspace())):
            units.append("".join(cur))
            cur = []
    if cur:
        units.append("".join(cur))
    out = []
    for u in units:                     # 只有空白的碎片併到前一句，不要讓模型看到空項
        if out and not u.strip():
            out[-1] += u
        else:
            out.append(u)
    # V1.35（待辦 10）：只剩「11.」這種清單編號的碎片，併到下一句（一字不改），不讓它自己變成一段
    #    🔴 V1.35 審查：只併「在行首」的（前面沒有句子，或前一句以換行結尾）——句子中間單獨一句「12.」可能是別人的回答，
    #       併進下一句，換人的位置就沒了。
    merged = []
    for u in out:
        if merged and _LONE_MARK.fullmatch(merged[-1]) and (len(merged) == 1 or merged[-2].endswith("\n")):
            merged[-1] += u
        else:
            merged.append(u)
    return merged


def _proportional(segs, n):
    """保底：模型的回答不能用時，按骨架每段的字數比例分配。文字一定完整、一定是繁體，只是斷點用估的。"""
    lens = [max(1, len((s.get("raw") or "").strip())) for s in segs]
    total, acc, starts = sum(lens), 0, []
    for ln in lens:
        starts.append(min(n, round(acc / total * n)))
        acc += ln
    return starts


def _pairs(segs, starts, n):
    """
    模型的答案 → [[段號, 起點], …]：只留有內容的段，起點一段比一段大，第一段從 0 開始。
    沒回答、-1、超出範圍、倒退的，都當成「這段在正文裡沒有對應的內容」。
    兩段搶同一個起點時一定有一段是空的：讓骨架比較長的那段拿走（語助詞通常很短）。
    """
    pairs, prev = [], -1
    for i, x in enumerate(starts):
        try:
            x = int(x)
        except (TypeError, ValueError):
            continue
        if x < 0 or x >= n or x < prev:
            continue
        if x == prev:
            j = pairs[-1][0]
            if len((segs[i].get("raw") or "").strip()) > len((segs[j].get("raw") or "").strip()):
                pairs[-1][0] = i
            continue
        pairs.append([i, x])
        prev = x
    if pairs:
        pairs[0][1] = 0                  # 第一段之前的字不能丟
    return pairs


# 補回「每一段在正文裡都找不到」的講者時，放在那一段的說明文字（見 main）
OMITTED = "（整理後的逐字稿略去了這段）"


class _Usage:
    """把對齊的幾次呼叫加總起來（思考用掉的 token 也照輸出計費，要算進去）。"""

    def __init__(self):
        self.prompt_token_count = 0
        self.candidates_token_count = 0
        self.estimated = False           # 講者斷點改用估算（見 align）

    def add(self, u):
        if u is None:
            return
        self.prompt_token_count += u.prompt_token_count or 0
        self.candidates_token_count += ((u.candidates_token_count or 0)
                                        + (getattr(u, "thoughts_token_count", 0) or 0))


def align(client, segs, clean_text):
    """
    把第 2 趟的繁體正文，切回第 1 趟的講者段落。

    🔴 舊做法讓模型「把整份正文逐段重打一次」。兩趟內容對不太上時（精簡模式會刪掉重複
       與語助詞），模型會一直想，把 65,536 的額度全部用在思考上，JSON 在第 3,968 個字元
       被截斷 → 整份錄音零產出（2026-09-11 實測：思考吃掉 62,911 token）。把思考調低雖然
       跑得完，卻會自己多加約兩成的字 —— 只要讓模型重打，就有機會改到字。

    新做法：程式先把正文切成編號的小句，模型**只回答每一段從第幾句開始**（只有數字），
    文字由程式從正文原封不動剪下來。所以：
      · 不可能多字、少字、改字，也不可能混進簡體骨架的字
      · 輸出只有數字，再長的會議也不會被截斷
      · 模型答壞了、或對齊這一步的呼叫本身失敗（伺服器忙到重試用完、400、429、網路斷線），
        就按比例估斷點 —— 文字仍然完整，這一段不會因為對齊失敗而作廢
    正文裡找不到對應內容的骨架段（通常是被精簡模式刪掉的語助詞）整段拿掉，
    不用簡體骨架去填：下游看到空白段會退回顯示骨架，那就會冒出簡體字。

    🔴 「沒有內容的段」要讓模型明講（回 -1）。第一版叫模型用「起點跟前一段相同」表示，程式卻是
       把「前一段」切成空的 —— 兩邊說法相反，每一個被刪掉的「嗯」都可能讓前一位講者的話記到
       說「嗯」的人名下（2026-09-11 稽核抓到）。模型仍然回了相同的起點時，由 _pairs 讓骨架
       比較長的那段拿走正文（語助詞通常很短）。
    """
    usage = _Usage()
    units = _units(clean_text or "")
    if not segs or not units:
        if segs:
            print("  （這一段沒有辨識到任何話）")
        return [], usage
    n = len(units)
    listing = "\n".join(f"[{k}] {u.strip()}" for k, u in enumerate(units))
    skeleton = "\n".join(f"段{i}（{s['speaker']}）：{(s.get('raw') or '').strip()}"
                         for i, s in enumerate(segs))
    prompt = f"""這是同一段會議錄音的兩種辨識結果。

【A】分好講者的段落（簡體，只用來判斷「哪裡換人講話」）：
{skeleton}

【B】乾淨的繁體正文，已經切成編號的小句：
{listing}

任務：【B】的小句要依序分給【A】的 {len(segs)} 段。請回答【A】每一段「從【B】的第幾句開始」。

規則：
- 只回數字，不要寫任何文字。【A】的每一段都要回答（i 從 0 到 {len(segs) - 1}）。
- 在【B】裡找不到對應內容的段（通常是被刪掉的語助詞，例如「嗯」「對」），start 填 -1。
- 其餘各段的起點要一段比一段大（不能相同、不能倒退）；第一個有內容的段從 0 開始。
- 起點是【B】的編號，範圍 0～{n - 1}。"""
    schema = {"type": "array", "items": {"type": "object",
              "properties": {"i": {"type": "integer"}, "start": {"type": "integer"}},
              "required": ["i", "start"]}}
    got, why = None, ""
    # 先用少量思考；答壞了（被截斷、JSON 壞掉）再用最少思考試一次。
    # 呼叫本身失敗（丟出例外）就不換思考程度再試：伺服器忙、額度、網路、參數錯誤都跟思考程度無關，
    # 而且 503 在 _with_retry 裡已經等過 15＋30＋60 秒，再試一輪只會讓同事再多等將近兩分鐘。
    # 🔴 不設 temperature（2026-09-19 拿掉原本的 0）：官方 3.5 指南要求 3.x 模型把 temperature／top_p／top_k
    #    從請求整個拿掉，低於 1.0 可能跳針或變差；拿掉前做過同一份輸入的對齊 A/B（溫度 0／不設各 3 次，19 段結果完全相同）。
    for level in (types.ThinkingLevel.LOW, types.ThinkingLevel.MINIMAL):
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=level))
        try:
            r = _with_retry("對齊", lambda: client.models.generate_content(
                model=ALIGN_MODEL, contents=prompt, config=cfg))
        except Exception as e:
            # 🔴 對齊呼叫本身失敗也不能讓這一段作廢：兩趟轉錄已經付過錢、繁體正文就在手上，
            #    按比例估斷點照樣產出完整文字（2026-09-11 使用者決定）。
            #    只接 Exception：Ctrl+C 的 KeyboardInterrupt 不是 Exception，照樣往外傳、中斷整個工作。
            #    失敗的呼叫沒有回應，也就沒有 usage 可加；前一次答壞的回應已經加過了。
            tech = (" ".join(str(x) for x in (e.code, e.status) if x)
                    if isinstance(e, gerr.APIError) else "") or type(e).__name__
            label = _reason(e)
            why = f"對齊時出錯：{label}（{tech}）" if label else f"對齊時出錯：{tech}"
            break
        usage.add(r.usage_metadata)
        fr = r.candidates[0].finish_reason if r.candidates else None
        if fr is not None and getattr(fr, "name", str(fr)) != "STOP":
            why = f"模型沒有正常結束（{getattr(fr, 'name', fr)}）"
            continue
        try:
            got = {int(d["i"]): int(d["start"]) for d in json.loads(r.text)}
            break
        except (ValueError, TypeError, KeyError) as e:
            why = f"回答格式不對（{type(e).__name__}）"
    pairs = _pairs(segs, [got.get(i) for i in range(len(segs))], n) if got is not None else []
    if not pairs:
        if got is not None:
            why = "模型給的斷點都不能用"
        print(f"  ⚠ 講者分段改用估算（{why}）；文字內容完整，只是換人講話的位置可能差一兩句")
        usage.estimated = True           # 斷點是估的：_recover_lost 不拿每段字數去判斷「少了一截」
        p = _proportional(segs, n)
        pairs = [[i, p[i]] for i in range(len(segs))
                 if p[i] < (p[i + 1] if i + 1 < len(segs) else n)]
    out = []
    for k, (i, a) in enumerate(pairs):
        b = pairs[k + 1][1] if k + 1 < len(pairs) else n
        text = "".join(units[a:b]).strip()
        if text:
            s = dict(segs[i])
            s["text"] = text
            s["_skel"] = i               # 對到骨架第幾段（只在記憶體用，_recover_lost 會拿掉）
            out.append(s)
    return out, usage


# ── 第 2 趟漏掉的話：偵測＋補轉（2026-09-20 筆電實測 N2）──────────────────────────────
# 🔴 內附示範檔（兩人各講三輪、共 9 句）整檔轉，7 次都只出 6 句、檔頭卻沒有警語、畫面打 ✅。
#    桌機逐項實驗（各 2 次、結果固定）：只有「SMART＋cmn-Hant-TW＋這三個專有名詞」一起用時第 2 趟丟 3 句；
#    拿掉專有名詞、只留一個詞、不給語言碼、改 VERBATIM、換成不相干的詞都 9 句全在；第 1 趟每次 9 句都聽到。
#    也就是模型在某些設定組合下會安靜地整理掉整句 —— 換掉某個設定只是換一個會觸發的組合，不是根治。
#    根治的做法：拿第 1 趟（骨架）當對照，找出「骨架有、正文沒有」的段，把那一小段剪出來單獨再轉一次
#    （丟掉的三段單獨轉，同樣的設定三段都轉得出來），補回原來的位置並標〔補轉〕；補不回來就在檔頭與畫面講。
#    舊的三道檢查（段尾 30 秒、段中 180 秒、正文遠多於骨架）量的是別的維度，8～9 秒的缺口一條都碰不到。
RECOVER_MIN = 6          # 骨架那段的「實字」少於這麼多不管（「好」「對」「嗯嗯」本來就會被整理掉）
RECOVER_MAX = 20         # 一段錄音最多補轉幾處（每處多一次付費呼叫）；超過的列進警語
RECOVER_PAD = 0.25       # 剪片段時前後各多留幾秒
_FILLER = set("呃嗯啊哦喔欸诶唉")
# 補不回來的原因 → 檔頭警語怎麼講（_recover_lost 回傳的第 5 欄）。要照實講：沒試過的不可以說「補轉也沒補回來」。
_LOST_WHY = {
    "empty": "單獨補轉也轉不出內容",
    "mismatch": "單獨補轉的結果跟正文對不起來，沒有替換",
    "failed": "單獨補轉那一次失敗了",
    "busy": "補轉時伺服器很忙（或額度、金鑰有問題），這一處沒有補轉",
    "net": "補轉時網路斷了，這一處沒有補轉",                       # V1.38 審查（#7）
    "skipped": "這一段要補轉的地方超過 {n} 處，這一處沒有補轉",
}


def _real(t):
    """「實字」：只留文字與數字、去掉語助詞。骨架是簡體、正文是繁體，兩邊只能比字數，不能逐字比。"""
    return "".join(ch for ch in (t or "") if ch.isalnum() and ch not in _FILLER)


def _present(needle, hay):
    """needle 的內容是不是已經在 hay 裡（兩邊都是繁體正文）。

    短的（實字少於 12）要整串出現才算：「10月31號嗎」不能因為別句有「10月31號了」就算數。
    長的看連續 4 字以上的相同片段蓋掉幾成，八成五以上才算 —— 門檻訂低會把「真的漏掉的話」
    當成「別處已經有了」，那就是安靜地又丟一次。
    """
    a, b = _real(needle), _real(hay)
    if not a:
        return True
    if len(a) < 12:
        return a in b
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(x.size for x in m.get_matching_blocks() if x.size >= 4) >= 0.85 * len(a)


def _lost_segments(skel, aligned, estimated=False):
    """第 1 趟聽到、正文裡卻沒有（或少了一大截）的骨架段：[(骨架編號, 'none'｜'part')]。

    none＝對齊時這段整段對不到正文；part＝對到了，但字數比骨架少很多（示範檔「10月31號嗎？」就是這樣
    從一段的開頭消失的）。講者斷點改用估算時，每段分到幾個字本來就是估的，不拿來判斷 part。
    """
    got = {}
    for s in aligned:
        i = s.get("_skel")
        if i is not None:
            got[i] = got.get(i, "") + (s.get("text") or "")
    out = []
    for i, s in enumerate(skel):
        raw = _real(s.get("raw"))
        if len(raw) < RECOVER_MIN or len(set(raw)) < 4:
            continue
        if i not in got:
            out.append((i, "none"))
        elif not estimated:
            txt = _real(got[i])
            if len(raw) - len(txt) >= RECOVER_MIN and len(txt) < 0.8 * len(raw):
                out.append((i, "part"))
    return out


def _recover_lost(client, cwav, skel, aligned, vocab, clen, estimated=False, tag=""):
    """把 _lost_segments 找到的段剪出來單獨跑第 2 趟，補回 aligned。

    回傳 (新的 aligned, 補回幾處, [(起, 迄, 講者, 'none'｜'part', 原因)] 補不回來的, 多用的音訊 token)。
    原因是 _LOST_WHY 的鍵，檔頭警語照它講。
    🔴 這一支在每段的 try 裡面、而且這一段的錢已經付完了：任何一處補轉失敗都只能記成「補不回來」，
       絕不可以把例外往外丟 —— 那會讓整段已經完成的逐字稿被標成失敗丟掉。只接 Exception：
       Ctrl+C 照樣往外傳。
    🔴 補轉回來的文字要先確認正文別處沒有：模型也可能只是把那段話併到隔壁講者的段落裡了，
       這時再補一次就變成同一句出現兩次。
    🔴 補轉不重試；遇到伺服器忙、網路不穩、額度用完、金鑰失效就停掉後面的補轉（2026-09-20 複查重現）：
       原本每一處都走 _with_retry 的 15＋30＋60 秒，503 時一段最多空等 35 分鐘（20 處 × 105 秒），
       而這一段已經付費的結果要等補轉完才存檔，同事以為當掉、關掉視窗就全丟了。補轉只是附加，照實列進檔頭就好。
    """
    lost = _lost_segments(skel, aligned, estimated)
    by_i = {s.get("_skel"): s for s in aligned if s.get("_skel") is not None}
    if not lost:
        for s in aligned:
            s.pop("_skel", None)
        return aligned, 0, [], 0
    # 超過 RECOVER_MAX 時，名額先給「整段不見」的、再給「少一截」的（少一截常是口吃重複被整理掉，不是真的漏；
    # 2026-09-20 複查指出照時間排會讓它先把名額用掉）。補轉本身仍照時間順序做。
    pick = set(sorted(range(len(lost)), key=lambda k: lost[k][1] != "none")[:RECOVER_MAX])
    print(f"▸ {tag}第 1 趟有、整理後的正文裡沒有（或少了一截）的話有 {len(lost)} 處，剪出來單獨再轉一次")
    added, fixed, missing, tok, halt = [], 0, [], 0, None
    for k, (i, kind) in enumerate(lost):
        s = skel[i]
        st, en = float(s.get("start") or 0), float(s.get("end") or s.get("start") or 0)
        if halt or k not in pick:
            missing.append((st, en, s.get("speaker"), kind, halt or "skipped"))
            continue
        cw = None
        try:
            a, b = max(0.0, st - RECOVER_PAD), min(clen, en + RECOVER_PAD)
            if b - a < 0.5:
                raise ValueError("片段太短")
            cw = cut_audio(cwav, a, b)
            txt, u = pass2_clean(client, load_audio(client, cw), vocab, retry=False)
            tok += getattr(u, "prompt_token_count", 0) or 0
        except Exception as e:                 # noqa: BLE001 —— 補不回來就照實講，不能讓整段作廢
            if _transient(e) or _permanent(e):
                # V1.38：網路斷了另外講（補轉照舊不重試、不等網路：見 pass2_clean 的 retry=False）；檔頭的原因也要對（審查 #7）
                halt = "net" if _net_down(e) else "busy"
                why = ("網路斷了" if _net_down(e) else
                       "伺服器很忙或網路不穩" if _transient(e) else "遇到重試也不會好的錯誤")
                print(f"  ⚠ 補轉時{why}（{type(e).__name__}），剩下的不補了，會列在檔頭")
            else:
                print(f"  ⚠ {hhmmss(st)} 那一段補轉失敗（{type(e).__name__}），會列在檔頭")
            missing.append((st, en, s.get("speaker"), kind, halt or "failed"))
            continue
        finally:
            if cw and cw != cwav:
                _quiet_remove(cw)
        others = "".join(x.get("text") or "" for x in aligned + [x for _, x in added] if x is not by_i.get(i))
        if kind == "none":
            if len(_real(txt)) < RECOVER_MIN // 2:
                missing.append((st, en, s.get("speaker"), kind, "empty"))    # 單獨轉也轉不出來
            elif _present(txt, others):
                pass                                                   # 別處已經有了：是併到隔壁段，不是漏掉
            else:
                seg = {k: v for k, v in s.items() if k not in ("tl", "_skel")}
                seg.update(text=txt.strip(), recovered=True)
                added.append((i, seg))
                fixed += 1
            continue
        cur = by_i[i]
        have, new = _real(cur.get("text")), _real(txt)
        if len(new) - len(have) < RECOVER_MIN:
            continue                                                   # 單獨轉也一樣長：原本就沒少
        sm = difflib.SequenceMatcher(None, new, have, autojunk=False)
        extra = "".join(new[i1:i2] for op, i1, i2, _j1, _j2 in sm.get_opcodes() if op in ("delete", "replace"))
        if not _present(cur.get("text"), txt):
            missing.append((st, en, s.get("speaker"), kind, "mismatch"))  # 對不起來，不亂換
        elif _present(extra, others):
            pass                                                       # 多出來的是隔壁段的話（剪片段時沾到的）
        else:
            cur["text"], cur["recovered"] = txt.strip(), True
            fixed += 1
    # 補回的整段插回骨架裡的位置：放在「對到的骨架編號比它大」的第一段前面。
    # 🔴 不可以照 start 重新排序：骨架時戳不一定單調（實測第 0 列 1:40:45、後面 104 列從 1:25:33 開始，
    #    見 _chunk_holes），一排序開場白就被搬到最後（2026-09-20 複查指出）。沒有補回整段時順序完全不動。
    out = list(aligned)
    for i, seg in sorted(added, key=lambda x: x[0]):
        out.insert(next((k for k, x in enumerate(out) if x.get("_skel") is not None and x["_skel"] > i),
                        len(out)), seg)
    for s in out:
        s.pop("_skel", None)
    if fixed:
        print(f"  補回 {fixed} 處（內文標〔補轉〕）")
    return out, fixed, missing, tok


def main():
    global MAX_CHUNK_SEC          # 🔴 要在任何一處用到 MAX_CHUNK_SEC 之前宣告，否則 SyntaxError

    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--vocab", nargs="*", default=[], help="專有名詞（繁體），最多 1000 個")
    ap.add_argument("--names", nargs="*", default=[], help="講者真名，依出現順序")
    ap.add_argument("--out", default=None)
    # 🔴 default 不可以寫死數字：2026-09-16 踩過 —— 常數改成 28 分鐘，這裡還留著 45.0，
    #    下面又無條件覆寫，結果「改了等於沒改」；而守著它的兩條斷言只看模組常數與原始碼字串，
    #    所以全綠、完全沒抓到。default=None ＋ 只有真的傳了才覆寫 → 常數是唯一真相源。
    ap.add_argument("--max-chunk-min", type=float, default=None,
                    help=f"每段最長幾分鐘（開分講者時模型只處理 30 分，"
                         f"預設 {int(MAX_CHUNK_SEC // 60)} 留餘裕；測試用）")
    a = ap.parse_args()

    # 🔴 每次進 main() 都要先回到預設值，不可以沿用上一次執行留下的值。
    #    舊版是 `MAX_CHUNK_SEC = a.max_chunk_min * 60`＋default=45.0，那個 default 其實
    #    順便扮演了「每次重設」的角色；改成「只有傳了才覆寫」之後這個效果就沒了，
    #    同一個行程裡跑第二次（測試就是這樣跑的）會繼承上一次的 --max-chunk-min。
    MAX_CHUNK_SEC = _DEFAULT_CHUNK_SEC
    if a.max_chunk_min:
        # 🔴 保持 int：後面有 isinstance 檢查與 f"{MAX_CHUNK_SEC // 60}" 的顯示，float 會印成「28.0 分鐘」
        MAX_CHUNK_SEC = int(a.max_chunk_min * 60)
        # 🔴 這個旗標是使用者可覆寫的，但官方限制擺在那裡：開分講者時音訊處理限 30 分鐘，
        #    超過也不報錯。讓人一句話都沒有就把自己設到官方上限之外，不合理。
        if MAX_CHUNK_SEC > 30 * 60:
            print(f"  ⚠ 你指定的單段長度 {a.max_chunk_min:g} 分鐘超過模型的處理上限。\n"
                  f"    Google 官方文件寫明：開「分講者＋時間軸」時，每次只處理 30 分鐘的音訊；"
                  f"超過的部分會怎樣官方沒寫，也不會報錯。\n    建議 28 分鐘以下。仍照你指定的值執行。")

    import _apikey
    key = _apikey.for_script()         # 環境變數沒有就讀記住的那一組（N6-3），都沒有就中文說明
    # 🔴 空字串也要擋（2026-09-20 筆電 ⚠-4）：變數存在但被清空時，拿空金鑰去連網
    #    只會得到「金鑰可能打錯」這種誤導訊息。見 _apikey.for_script 的說明。
    if not key:
        sys.exit(2)
    client = genai.Client(api_key=key)
    _sweep_leftovers(client)
    _hook_close(client)

    print(f"▸ 轉檔 {os.path.basename(a.audio)}")
    if not need_ffmpeg():
        return 1
    wav = to_wav16k(a.audio)
    # 🔴 整場會議的 16kHz WAV 用完要刪。分段檔和 .partial.json 都有清，只有這個
    #    沒清 —— 三小時的會議會在 %TEMP% 永遠留下數百 MB。
    if wav != a.audio:
        atexit.register(_quiet_remove, wav)
    dur = duration(wav)
    print(f"  長度 {hhmmss(dur)}")

    chunks = plan_chunks(wav, dur)
    if len(chunks) > 1:
        print(f"  ⚠ 單段上限 {_mins(MAX_CHUNK_SEC)} 分鐘（開分講者時模型只處理 30 分，這裡留安全邊際），\n"
          f"    自動切成 {len(chunks)} 段處理")
        for i, (s, e) in enumerate(chunks, 1):
            print(f"     第 {i} 段 {hhmmss(s)} – {hhmmss(e)}")

    out = a.out or os.path.splitext(a.audio)[0] + "_逐字稿.md"
    part_json = os.path.splitext(out)[0] + ".partial.json"
    global _PART_JSON
    _PART_JSON = part_json           # Ctrl+C 的說明要看這個檔有沒有真的存在

    segs, tok_audio, tok_align, failed = [], 0, 0, []
    first_seen = {}           # 講者標籤 → 他在骨架裡第一次開口的那段（見迴圈後的「補回」）
    last_err = None
    skel_end = 0.0            # 第 1 趟辨識到的最後一秒（含分段偏移），量逐字稿有沒有缺尾用
    chunk_cov = []            # 每段 (段號, 起點, 終點, 該段骨架最後時戳)，量中間段有沒有缺口用
    # 🔴 下面三個量的是 chunk_cov 看不到的維度。三個都必須在 align() **之前**取值：
    #    align() 會把在正文裡對不到內容的骨架整段丟掉，_split_long() 又會把續片的 raw 拿掉，
    #    迴圈文字流過這兩道之後會被洗成「幾十列、每列長度正常」，外觀完全看不出問題。
    chunk_spans = []          # 每段 (段號, 起點, 終點, [(句子起, 句子迄), ...])，量段中間的洞
    chunk_txt = []            # 每段 (段號, 起點, 終點, 骨架字數, 正文字數)，量兩趟產出量落差
    chunk_loop = []           # 每段 (段號, 起點, 終點, 正文)，量正文自我重複
    n_recovered = 0           # 第 2 趟漏掉、單獨補轉回來的處數（見 _recover_lost）
    lost_all = []             # 補不回來的 (段號, 起, 迄, 講者標籤, 'none'｜'part', 原因)，列進檔頭警語
    for i, (cs, ce) in enumerate(chunks, 1):
        tag = f"[{i}/{len(chunks)}] " if len(chunks) > 1 else ""
        cwav = src = None
        try:
            cwav = wav if len(chunks) == 1 else cut_audio(wav, cs, ce)
            src = load_audio(client, cwav)

            print(f"▸ {tag}第 1 趟：分講者＋時間軸")
            # 傳這一段的長度當時戳上界：長音檔的詞時戳實測會失真到 30 倍，
            # 不擋的話 skel_end 被撐成天文數字，涵蓋率警語會整組失效（見 _span）
            cseg, u1 = pass1_skeleton(client, src, limit=ce - cs)
            print(f"▸ {tag}第 2 趟：繁體正文＋專有名詞")
            clean, u2 = pass2_clean(client, src, a.vocab)
            print(f"▸ {tag}對齊中")
            skel = cseg
            seg_end = cs + max((float(s.get("end") or s.get("start") or 0)
                                for s in skel), default=0.0)
            skel_end = max(skel_end, seg_end)
            chunk_cov.append((i, cs, ce, seg_end))
            # 🔴 這三行落在 per-chunk 的 try 裡面，一旦拋例外，下面的 except 會把這一段
            #    **已經付過錢、內容完好**的轉錄整段標成失敗丟掉 —— 那就成了「加了檢查反而弄丟內容」。
            #    所以一律寫成不可能拋例外的形式：只用 .get()，字串一律 (x or "")，不做型別假設。
            chunk_spans.append((i, cs, ce,
                                [(s.get("start"), s.get("end")) for s in skel]))
            chunk_txt.append((i, cs, ce,
                              sum(len((s.get("raw") or "").strip()) for s in skel),
                              len((clean or "").strip())))
            chunk_loop.append((i, cs, ce, clean or ""))
            cseg, u3 = align(client, cseg, clean)
            # 第 1 趟有、正文沒有的話：剪出來單獨補轉（見 _recover_lost；它自己不會丟例外）
            cseg, n_rec, lost, tok_rec = _recover_lost(client, cwav, skel, cseg, a.vocab, ce - cs,
                                                       getattr(u3, "estimated", False), tag)
            n_recovered += n_rec
            # 🔴 2026-09-25（V1.22 ③）：模型每一段各自分講者，第 2 段的 spk:0 跟第 1 段的 spk:0 不是同一個人。
            #    以前兩段共用標籤、名字也共用，自製會議切 2 分鐘一段實測：第 2 段外賓的英文發言被記成「主席」、
            #    秘書的報告記成「外賓」。第 2 段起在標籤前加段號（c2:spk:0），名字另外給（見迴圈後）。
            #    放在補轉、_split_long 之後：那兩步都在這一段裡面對照第 1 趟的標籤，要用原本的。
            lab = (lambda sp: sp) if i == 1 else (lambda sp, _i=i: f"c{_i}:{sp}" if sp else sp)
            lost_all += [(i, cs + st, cs + en, lab(sp), kind, why) for st, en, sp, kind, why in lost]
            tok_audio += tok_rec
            cseg = _split_long(cseg)         # 長獨白照句子切段（順便拿掉只在記憶體用的 tl）

            for s in cseg:                   # 把時間軸接回整段錄音
                s["start"] += cs
                s["end"] = (s.get("end") or 0) + cs
                s["chunk"] = i
                s["speaker"] = lab(s["speaker"])
            segs += cseg
            for s in skel:
                sp = lab(s["speaker"])
                if sp not in first_seen:
                    first_seen[sp] = dict({k: v for k, v in s.items() if k != "tl"}, speaker=sp,
                                          start=s["start"] + cs,
                                          end=(s.get("end") or 0) + cs, chunk=i)
            tok_audio += (u1.prompt_token_count or 0) + (u2.prompt_token_count or 0)
            tok_align += (u3.prompt_token_count or 0) + (u3.candidates_token_count or 0)

            # 🔴 三小時的錄音跑到一半掛掉，不可以把前面已經花錢跑完的段落丟掉。
            #    每段做完就先落地，下次可以接著跑。
            json.dump(segs, io.open(part_json, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            why = _reason(e)
            err = f"{why}（{err}）" if why else err
            failed.append((i, cs, ce, err))
            last_err = e
            print(f"  ✗ {tag}這一段失敗：{err}")
            if _permanent(e) or _net_down(e):
                # 🔴 額度用完／金鑰失效這種，剩下的段落一定也會失敗。
                #    三小時的錄音有幾十段，一段一段撞完只是浪費時間，
                #    而且畫面上看起來像在工作。已完成的段落已經落地了。
                # V1.38：網路斷了的已經在 _with_retry 等過（同一次斷網最多 NET_WAIT_MAX 秒）還沒回來，才會走到這裡
                #    （_net_down 另外列：網址查到了、卻沒有路可走的那幾種斷法不算 _permanent）。
                # V1.38 審查：「已完成的段落已存檔」只在真的有完成的段落時才講（#2：28 分鐘以內只有一段，停下來就什麼都沒有）；
                #    後面沒跑的段落也列進失敗清單（#1）：檔頭才會列出缺哪些時段，不會被說成「有聲音卻沒有字、可能是音樂或掌聲」。
                kept = "；已完成的段落已存檔" if segs else ""
                if _net_down(e):
                    print(f"    （網路一直沒有回來（等了 {NET_WAIT_MAX // 60} 分鐘），先停下來{kept}）")
                else:
                    print(f"    （這個錯誤重試也不會好，停下來{kept}）")
                failed += [(j, s0, s1, "沒有轉，因為在前面那段就停下來了") for j, (s0, s1) in enumerate(chunks[i:], i + 1)]
                break
            print(f"    （其餘段落繼續跑，已完成的不會丟掉）")
        finally:
            # 🔴 這一段的上傳用完就刪，不要等整份轉完：三小時的會議切成 4 段，
            #    原本 4 份原始錄音會一直留在雲端直到程式結束（被強制結束就是 48 小時）。
            if isinstance(src, types.File):
                _drop_remote(client, src.name)
            if cwav and cwav != wav:
                try:
                    os.remove(cwav)
                except OSError:
                    pass

    if not segs and not failed:
        # 🔴 2026-09-20 筆電實測 N3：整段音樂、沒人講話的錄音，舊版（模型回空內容就當掉）會印「每一段都失敗了」
        #    加英文 TypeError，還叫使用者跑診斷。沒有任何一段失敗 —— 就是沒有人講話，要照實講。
        print("\n⚠ 整份錄音都沒有辨識到有人講話，所以沒有產出逐字稿。")
        print("   可能是音樂、靜音、雜音，或錄音的音量太小；可以先用播放器聽聽看裡面有沒有人聲。")
        print(f"   語音 {tok_audio:,} tok ≈ US${tok_audio / 1e6 * 2.00:.4f}")
        # 每段做完都會寫中途存檔（這時內容是 []）。不清的話桌面會多一個空的 .partial.json，
        # 說明書把它講成「已經轉完的部分」（2026-09-20 複查指出）
        _quiet_remove(part_json)
        sys.exit(0)
    if not segs:
        # V1.38 審查第 3 輪：這一次寫的中途存檔是空的（[]）——不清的話 _explain 會叫人用功能 5 去救一個空檔。
        #    第 4 輪：只清「內容是空的」：這一次第 1 段就失敗時根本沒寫過，桌面上那份是上一次中斷留下、付過錢的，不能刪
        try:
            with io.open(part_json, encoding="utf-8") as fp:
                empty = json.load(fp) == []
        except Exception:
            empty = False
        if empty:
            _quiet_remove(part_json)
        n_ok = len(chunks) - len(failed)       # V1.38 審查第 2 輪：停下之後沒跑的段落已經列進 failed，不用再強制當成全部失敗
        print("\n✗ 每一段都失敗了，沒有產出。" if not n_ok else
              f"\n✗ 有 {len(failed)} 段失敗，其他跑完的段落沒有辨識到有人講話，沒有產出。")
        # 🔴 這裡一定要給中文診斷。per-chunk 的 except 把例外吞掉了，
        #    __main__ 的 _explain 永遠跑不到 —— 而額度用完、金鑰失效
        #    正是最需要看懂的兩種情況。2026-09-10 稽核抓到。
        if last_err is not None:
            _explain(last_err)
        print("\n   各段的錯誤訊息：")
        for i, cs, ce, err in failed:
            print(f"   第 {i} 段 {hhmmss(cs)}–{hhmmss(ce)}：{err}")
        sys.exit(1)

    # 🔴 一位講者的每一段在整理後的正文裡都找不到（例如整場只說了「嗯」「對」）時，他會從輸出
    #    消失；轉檔前就照開口順序填好的名字（--names）會整排往前錯位，組長的發言被記到秘書名下
    #    （2026-09-11 稽核抓到）。補回他第一次開口的那段並註明被略去，名字才對得上；
    #    功能 4 的翻譯檔、json_to_md 讀的是同一份 JSON，也跟著一致。
    present = {s["speaker"] for s in segs}
    for sp, ph in first_seen.items():
        if sp in present:
            continue
        ph = dict(ph, text=OMITTED)
        k = next((k for k, s in enumerate(segs)
                  if (s.get("chunk", 0), s["start"]) > (ph["chunk"], ph["start"])), len(segs))
        segs.insert(k, ph)

    spks = speaker_list(segs)            # 數字排序（V1.22 ②：字串排序在 11 位以上講者時會把名字整排錯位）
    print(f"  合計 {len(segs)} 段、{len(spks)} 個講者標籤")
    # 🔴 補回的佔位段（text＝OMITTED）本身沒有正文，不可以拿來當「正文寫到哪裡」：
    #    整場只說「嗯」的人剛好在最後開口時，他的佔位段會把 out_end 撐到錄音尾巴，
    #    把「正文被略去」的警語整個遮掉。只看真的有正文的段。
    out_end = max((float(s.get("end") or s.get("start") or 0)
                   for s in segs if s.get("text") != OMITTED), default=0.0)
    # 🔴 有整段失敗時，「整份尾巴」那兩條不要報（檔頭已經另外列了缺的時段，會重複又互相打架），
    #    但**成功跑完的那幾段各自的缺口仍然要講** —— 原本寫成 gaps = [] if failed else ...，
    #    只要有任何一段失敗，逐段警語就整組被吃掉。
    gaps = _coverage_gaps(dur, skel_end, out_end, chunk_cov, len(chunks), tail=not failed)
    # 🔴 這裡在迴圈外，所有段都跑完、錢也都花完了。偵測器自己有 bug 的話，
    #    沒有這層保護就會讓 main() 在最後一刻死掉，.md 與 .json 永遠寫不出來 ——
    #    整場錄音的錢照付、產出全沒有。檢查程式壞掉的代價絕不可以是吃掉已完成的逐字稿。
    # 🔴 三支量的是不同維度（時間／產出量／重複），同一段可能同時中好幾條，
    #    不可以合併也不可以擇一報。
    # V1.34：出錯時寫明是哪一項沒檢查到——各項各自包 try，其他項照常（桌機 09-29 回報四之 5）
    for _name, _fn, _arg in (("段落中間整片沒轉到", _chunk_holes, chunk_spans),
                             ("整理後的正文異常變多", _pass_gap, chunk_txt),
                             ("同一批話重複出現", _loop_gap, chunk_loop),
                             ("有聲音卻沒有字的時段", _voiced_holes,
                              (wav, segs, [(cs, ce) for _i, cs, ce, _e in failed])),
                             ("段落時間互相重疊或倒退", _overlap_gaps, segs)):         # V1.35（待辦 10）
        try:
            gaps += _fn(_arg)
        except Exception as _e:
            gaps.append(f"完整性檢查裡「{_name}」這一項本身出錯（{type(_e).__name__}），"
                        f"這一項沒檢查到（其他各項各自獨立檢查）；內容請自己抽查一下")
    # V1.36（待辦 18 B）：「有聲音卻沒有字」那一項看不準時的說明——ℹ️，不放進缺口清單、不影響 ✅（見 _voice_note）。
    #    算不出來就不寫：它只是說明；同一份錄音讀不動的話，上面那一項已經會報「本身出錯」。
    try:
        notes = [n for n in [_voice_note(wav)] if n]
    except Exception:
        notes = []
    # 使用者是在轉檔前照「開口順序」填的名字，只對得上第 1 段（V1.22 ③）；第 2 段起一律「第2段講者1」這種寫法
    names = generic_names(spks)
    names.update(zip([sp for sp in spks if speaker_part(sp) == 1], a.names))
    # 🔴 第 2 趟漏掉、單獨補轉也補不回來的話（2026-09-20 N2）：8～9 秒的缺口碰不到上面任何一道門檻，
    #    不列在這裡就會照樣印 ✅。
    for _idx, st, en, sp, kind, why in sorted(lost_all, key=lambda x: x[1]):
        gaps.append(f"{hhmmss(st)}–{hhmmss(en)}（{names.get(sp, sp)}）第 1 趟有辨識到講話，整理後的正文裡卻"
                    f"{'沒有這段' if kind == 'none' else '少了一截'}，"
                    f"{_LOST_WHY.get(why, '單獨補轉也沒補回來').format(n=RECOVER_MAX)}。"
                    f"把錄音的 {hhmmss(st)} 到 {hhmmss(en)} 剪出來單獨轉一次就知道了")

    md = ["# 會議逐字稿", "",
          f"- 音檔：`{os.path.basename(a.audio)}`",
          # 🔴 V1.22 ③：切段時每段各自分講者，4 個人會變成 9 個標籤——寫「講者：9 位」會讓人以為真的有 9 個人
          f"- 長度：{hhmmss(dur)}　" + (f"講者標籤：{len(spks)} 個（每段分開算，同一個人可能重複）"
                                       if len(chunks) > 1 else f"講者：{len(spks)} 位"),
          f"- 產生：{time.strftime('%Y-%m-%d %H:%M')}"]
    if len(chunks) > 1:
        md += ["",
               # 🔴 2026-09-19 原本寫「超過模型單次上限」：但切段門檻是 MAX_CHUNK_SEC（預設 28 分、
               #    使用者還能調更低），官方上限是 30 分 → 28～30 分的錄音會被說成超過模型上限，不是事實。
               f"> ⚠️ 這份錄音超過單段上限（{_mins(MAX_CHUNK_SEC)} 分鐘），已切成 {len(chunks)} 段分別辨識。",
               # 🔴 V1.22 ③：以前寫「講者編號是每一段各自判斷的」，畫面上卻是名字（使用者填的「主席」）—— 看起來很確定，其實張冠李戴
               "> **講者是每一段各自判斷的**，跨段認不出是不是同一個人：第 2 段起標成「第2段講者1」這種寫法"
               + ("，你填的講者名字只套用在第 1 段" if a.names else "") + "。",
               "> 要統一名字，可以用功能 5（逐字稿重新排版）看著每位講者的第一句重新命名。"]
    if failed:
        # 🔴 同一事實兩個落點：menu.do_transcribe 轉檔完會讀這份檔的檔頭，決定畫面要印 ✅ 還是 ⚠，
        #    它比對的就是下面這行的「段辨識失敗，這份逐字稿並不完整」與 if gaps 那行的
        #    「**這份逐字稿可能不完整**」。這兩段字改了，menu.py 那邊的字串一定要跟著改，
        #    否則畫面會安靜地永遠印 ✅。（menu.py 有對應註解；開發端的 test_r3_menu_translate_docs.py（該檔不隨附）
        #    有一條把 menu 用的字串抽出來、確認它還出現在這支的原始碼裡。）
        md += ["",
               f"> 🔴 **有 {len(failed)} 段辨識失敗，這份逐字稿並不完整**，缺少下列時段："]
        for i, cs, ce, err in failed:
            md.append(f"> - 第 {i} 段 {hhmmss(cs)} – {hhmmss(ce)}　（{err}）")
        md.append("> 　要補齊的話，最簡單的方式是把同一個檔案再轉一次"
                  "（透過選單的「影音檔轉逐字稿」）。"
                  "這樣會整份重轉、不是只補缺的段落，會重複花費已完成段落的費用，"
                  "但操作上不需要任何技術背景。")
    if gaps:
        # 🔴 標題不要再寫「（辨識結果只到 …）」：那個括號填的是 out_end，但下面兩種條列各自帶
        #    自己的時間（骨架缺尾寫 skel_end、正文被略去寫 out_end），兩個時間常常對不起來，
        #    同一段警語自己打自己。條列本來就講得清楚，標題只留一句。
        # 🔴 「**這份逐字稿可能不完整**」是 menu.do_transcribe 判 ✅／⚠ 的標記字串之一
        #    （見上面 if failed 那段的註解）。改字要兩邊一起改。
        md += ["", "> ⚠️ **這份逐字稿可能不完整**："]
        md += [f"> - {g}" for g in gaps]
    # 🔴 這裡要報的是「內文實際標了幾個〔補轉〕」，不是 _recover_lost 回來幾筆：
    #    兩筆補轉併進同一段時（_recover_lost 會接在既有段落後面），n_recovered 會比標記數多，
    #    功能 5 用 json_to_md 重排一次就變成另一個數字。兩邊都改用同一個算法。
    n_marked = sum(1 for s in segs if s.get("recovered"))
    if n_marked:
        md += ["", f"> ℹ️ 有 {n_marked} 處是第 2 趟整理時漏掉、再從原音單獨補轉回來的（內文標〔補轉〕）："
                   "講者與時間取自第 1 趟，建議對照錄音核對一下。"]
    md += [x for n in notes for x in ("", f"> ℹ️ {n}")]          # V1.36（待辦 18 B）
    md += ["", "---", ""]

    last_chunk = None
    for s in segs:
        if len(chunks) > 1 and s.get("chunk") != last_chunk:
            last_chunk = s["chunk"]
            md += [f"### 〔第 {last_chunk} 段〕", ""]
        md.append(f"**[{hhmmss(s['start'])}] {names[s['speaker']]}**" + ("　〔補轉〕" if s.get("recovered") else ""))
        md.append("")
        md.append(s["text"])
        md.append("")

    io.open(out, "w", encoding="utf-8").write("\n".join(md))
    # 🔴 2026-09-20 筆電全流程檢測（⚠-12）：.json 以前只存段落陣列，所以用功能 5 重新排版一次
    #    （只是想改個講者名字），檔頭那段「⚠️ 這份逐字稿可能不完整」就整個不見了，畫面還打 ✅ ——
    #    使用者因此可能把一份「有 19 分鐘沒有內容」的逐字稿當成完整的發出去。
    #    改成連同 meta 一起存；json_to_md.py 照它重印同樣的警語。
    #    🔴 舊檔（純陣列）一定要照樣讀得動：讀的那一端統一走 json_to_md.load_transcript()。
    json.dump({"meta": {"audio": os.path.basename(a.audio), "duration": dur,
                        "generated": time.strftime("%Y-%m-%d %H:%M"),
                        "chunks": len(chunks), "chunk_limit_sec": MAX_CHUNK_SEC,
                        "speakers": {sp: names[sp] for sp in spks},
                        "incomplete": bool(gaps or failed),
                        "gaps": list(gaps),
                        "notes": notes,                   # V1.36：ℹ️ 說明（不算缺口；json_to_md.note_lines 照印）
                        "failed": [[i, cs, ce, err] for i, cs, ce, err in failed],
                        "recovered": n_marked},
               "segments": segs},
              io.open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    try:
        os.remove(part_json)           # 全部寫完了，中途存檔可以清掉
    except OSError:
        pass

    print(f"\n{'⚠' if (failed or gaps) else '✅'} {out}")
    for g in gaps:
        print(f"   ⚠ 這份逐字稿可能不完整：{g}")
    for n in notes:
        print(f"   ℹ {n}")
    if n_marked:
        print(f"   ℹ 有 {n_marked} 處第 2 趟漏掉的話已從原音補轉回來（內文標〔補轉〕），建議核對一下")
    if failed:
        print(f"   🔴 {len(failed)}/{len(chunks)} 段失敗，逐字稿不完整（檔頭有列出缺哪些時段）：")
        for i, cs, ce, err in failed:
            print(f"      第 {i} 段 {hhmmss(cs)}–{hhmmss(ce)}：{err}")
    print(f"   語音 {tok_audio:,} tok（每段兩趟）≈ US${tok_audio / 1e6 * 2.00:.4f}　"
          f"對齊 {tok_align:,} tok")


def _hook_close(client):
    """視窗被關掉時先刪本機暫存、再刪雲端上傳（見 _live.on_console_close）。掛不上也不能擋住轉檔。"""
    def emergency():
        for p in list(_TEMP_FILES):
            _quiet_remove(p)
        for name in list(_CLOUD_FILES):
            _drop_remote(client, name)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _live import on_console_close
        return on_console_close(emergency)
    except Exception:
        return False


def _diag(exc):
    """_live.diagnose() 的包裝：回傳 (要不要人處理, 標題, 怎麼辦)；載入失敗就當成判讀不出來。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _live import diagnose
        return diagnose(exc)
    except Exception:
        return (False, "", "")


def _permanent(exc):
    """這個錯誤重試有沒有意義？額度用完、金鑰失效、DNS 掛掉都沒有。
    V1.38：DNS 掛掉（＝網路斷了）仍算在這裡，但 _with_retry 會先等網路回來（最多 NET_WAIT_MAX 秒），等滿還沒回來才走到這裡。"""
    return _diag(exc)[0]


def _net_down(exc):
    """V1.38（待辦 20）：網路斷了（查不到伺服器位址）——等網路回來就會好。判準住在 _live.net_down（跟「連不到網路」同一條）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _live import net_down
        return net_down(exc)
    except Exception:
        return False


def _reason(exc):
    """失敗原因的中文短標，放在英文技術細節前面（畫面上、逐字稿檔頭都會列出）。"""
    if isinstance(exc, subprocess.SubprocessError):
        return ""
    if isinstance(exc, gerr.ServerError):
        return "Google 伺服器太忙"
    if _transient(exc):
        return "網路連線中斷"
    return _diag(exc)[1]


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
    if isinstance(exc, gerr.ServerError):
        # 🔴 503「伺服器很忙」重試用完之後，原本只印英文 JSON，還叫同事去跑 6_診斷.bat——
        #    那裡查不出 Google 那邊太忙（2026-09-11 稽核抓到）。
        need, title, hint = (True, "Google 的伺服器目前太忙",
                             "這不是你的電腦或金鑰的問題。\n"
                             "      → 過 10～30 分鐘再轉一次")
    elif not isinstance(exc, subprocess.SubprocessError):
        if _transient(exc):
            need, title, hint = (True, "網路連線中途斷掉了",
                                 "→ 確認網路穩定後再轉一次\n"
                                 "      → 一直這樣的話，可能是公司／學校的網路擋住了，換手機熱點試試")
        else:
            need, title, hint = _diag(exc)
    print()
    if need:
        print(f"  \u2717 {title}")
        print(f"      {hint}")
    else:
        print(f"  \u2717 發生錯誤：{type(exc).__name__}: {exc}")
        print("      看不懂的話，點兩下 6_診斷.bat 並把整個視窗截圖回報。")
    # 🔴 2026-09-20 筆電全流程檢測（⚠-7）：兩趟辨識、對齊、補轉都做完、錢也付了，卻在寫 .md 時出錯
    #    （例如 --out 指到資料夾）——中途存檔其實還在，但畫面一個字都沒提，使用者只好整份重轉。
    if _PART_JSON and os.path.exists(_PART_JSON):
        print(f"\n      ℹ 已經轉好的部分還留著：{_PART_JSON}")
        print("        回選單用「5 逐字稿重新排版」選這個檔，就能把它變成逐字稿（不用再付一次錢）。")
    return 1


def _interrupted():
    """
    Ctrl+C／關視窗時，依「這次到底有沒有整段轉完」講實話。

    🔴 不可以無條件說「已經轉好的部分會留在中途存檔」：那個檔只在每一段
       （最長 MAX_CHUNK_SEC，預設 28 分鐘）的第 1 趟＋第 2 趟＋對齊＋補轉**全部**做完之後
       才落地一次（main() 迴圈裡唯一的 json.dump(segs, ...)）。28 分鐘以內的錄音只有
       一段，中斷時那個檔根本不存在，照著去找只是白忙一場（2026-09-15 R3-4 稽核抓到）。
       程式當下知道自己切成幾段、已經完成幾段，所以這裡講得出精確的話。

    🔴 同一件事的其他落點，改字要一起改：
       · 5_使用說明（功能操作）.md 的 FAQ「轉檔到一半關掉視窗」那一列
       · README.md 工具 5（逐字稿重新排版）那一節
       · references/gemini-speech-guide.md「長工作必須單段失敗不影響全局」那一節
       · menu.py do_json_to_md() 的開場白（工具 5 的兩種用途）
    """
    print()
    if _PART_JSON and os.path.exists(_PART_JSON):
        print("  已中斷。已經整段轉完的部分留在：")
        print(f"    {_PART_JSON}")
        print("  用選單的 5「逐字稿重新排版」選這個檔，就能把已經轉完的段落做成逐字稿；")
        print("  沒轉到的時段要補，就整份再轉一次。")
    else:
        print("  已中斷。這次還沒有任何一段轉完，沒有東西可以救，請整份重轉。")
        print(f"  （超過 {_mins(MAX_CHUNK_SEC)} 分鐘的錄音才會切成多段，每一整段做完才會存一次中途存檔；")
        print("    這次還沒走到那一步，所以旁邊不會有 .partial.json。）")


if __name__ == "__main__":
    # 🔴 要把 main() 的回傳碼傳出去，否則失敗時 exit code 仍是 0，
    #    選單那邊就分不出成功或失敗。
    try:
        _code = main() or 0
    except KeyboardInterrupt:
        _interrupted()
        _code = 1
    except SystemExit as e:
        # 🔴 不要寫成 `e.code or 1`：那會把 sys.exit(0)（成功）也變成 1。
        #    目前程式裡的 sys.exit 全都是 1，所以還沒出事，但這是留給未來的陷阱。
        _code = 1 if e.code is None else e.code
    except Exception as _e:
        _code = _explain(_e)
    sys.exit(_code)
