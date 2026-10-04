# -*- coding: utf-8 -*-
"""
會議即時字幕（Gemini 3.5 Transcribe Live）

可以錄兩種聲音：
  --source system  電腦播出來的聲音（Teams / Meet / Zoom / YouTube）← 線上會議用這個
  --source mic     麥克風（實體會議室用這個）
  --source both    兩個混在一起（你在線上會議中同時要收自己的麥克風）

用法：
  python live_caption.py --source system
  python live_caption.py --source mic --vocab 深耕計畫 研發處
  python live_caption.py --source system --out 校務會議
按 Ctrl+C 結束，會自動存成 .md（給人讀）與 .txt（即時備份）。
"""
import os, sys, io, asyncio, argparse, time, queue, threading, signal, shutil

if __name__ == "__main__":      # 被 import 時不要動 stdout，會互相關掉底層 buffer
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

MODEL = "gemini-3.5-transcribe-live"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _live import (Reconnect, DropWatch, SentenceGate, SilenceGate,   # noqa: E402
                   open_live, quiet_async_noise, mix_lanes, RotateWhenQuiet,
                   capture_mic, capture_loopback, font_hint, source_line,
                   note_caption, start_level_watch, fit_tail, CLR_LINE, gate_floor, rotate_opts,
                   Leveler, final_extend, repair_boundary_dups, join_capture,
                   keep_open, forget_open, close_open, number_fixes, long_interim)
# 🔴 SentenceGate（切句，吃文字）與 SilenceGate（靜音閘門，吃音訊）名字只差兩個字母，
#    而本檔的區域變數 `gate` 早就是 SentenceGate。靜音閘門一律叫 `silence_gate`，不要混。

TARGET_SR = 16000          # Live API 要求的輸入取樣率
CHUNK_MS = 100
ROTATE_GRACE = 3.0       # 輪替時等最後一句定稿的寬限秒數
SESSION_SOFT_LIMIT = 8 * 60   # 保守值：超過就換一條連線，避免被伺服器切斷

DIM, RESET, BOLD, CYAN = "\033[2m", "\033[0m", "\033[1m", "\033[36m"
YEL = "\033[33m"

# 🔴 給 menu.py 判讀用的固定標記，不是給人看的說明文字。
#    使用者在「等聲音來源開好」那段期間按 Ctrl+C 取消時，這一行會原封不動印在 stdout 上
#    （純 ASCII、自己一行、不帶顏色碼），父行程用子字串比對就分得出「使用者自己取消」與「出錯了」。
#    為什麼不用離開碼：見下面取消分支裡的說明（從選單進來時 130 會被吃成 0）。
#    三支 live 腳本用同一個字串，改的時候三支要一起改（開發端的 test_r2_live_review.py ⑧ 會比對，該檔不隨附）。


# ─────────────────────────── 音訊擷取 ───────────────────────────
class AudioSource:
    """把系統聲音 / 麥克風統一轉成 16kHz 單聲道 int16，丟進 queue。"""

    def __init__(self, source: str):
        self.source = source
        self.q = queue.Queue(maxsize=200)      # 輸出（已混音）
        self.drop = DropWatch(chunk_ms=CHUNK_MS)
        self.stop = threading.Event()
        self.threads = []
        # 🔴 每個來源有自己的軌道。舊版兩個來源共用一個 queue，變成
        #    「[麥克風100ms][系統100ms][麥克風100ms]…」交錯而不是混音，
        #    而且送出的音訊量是實際時間的兩倍 → 辨識結果一定亂。
        self._lanes = {}
        self._failed = set()
        self._ready = set()          # 已經開好、開始收音的來源
        self._wanted = []            # 這次要開的來源
        self.live = False            # 主流程確認至少一路可用之後才設 True（見 wait_ready）
        self.mic_raw = False         # 完整收音（--mic-raw）：繞過 Windows 降噪，擴音器的聲音也收
        self.mic_device = None       # 指定麥克風（--mic-device）；None＝跟著 Windows 預設
        self.devices = {}            # 每一路目前實際在用的裝置名稱（寫進檔頭，見 _live.source_line）

    # 🔴 2026-09-22：兩路都改用 _live 的看門狗版本（三支即時程式共用）——裝置掉了、預設換了會自動接回。
    #    舊版只在開頭開一次，耳麥插頭鬆 3 秒整場就沒字幕（會議實測 14:25:12），見 _live.capture_mic 的說明。
    def _wasapi_loopback(self, lane='system'):
        capture_loopback(self, lane, CHUNK_MS)

    def _mic(self, lane='mic'):
        capture_mic(self, lane, CHUNK_MS, raw=self.mic_raw, device=self.mic_device)

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
            print(f"{CLR_LINE}\n{YEL}  ⚠ {title}{RESET}")
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

    def _push(self, mono_float, sr, lane="main"):
        """把某一路的音訊放進它自己的軌道（還沒混音）。"""
        if sr != TARGET_SR:
            g = np.gcd(sr, TARGET_SR)
            mono_float = resample_poly(mono_float, TARGET_SR // g, sr // g)
        try:
            self._lanes[lane].put_nowait(np.asarray(mono_float, dtype=np.float32))
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


# ─────────────────────────── 字幕輸出 ───────────────────────────
class Transcript:
    """邊收邊寫檔：程式被強制中止也不會弄丟整場會議的字幕。"""

    def __init__(self, stem, source=""):
        self.finals = []          # (起秒, 文字)
        self.turns = []           # V1.35：每一行是第幾回合講的（跟 finals 一一對應；見 _live.SentenceGate.cur_turn）
        self.final_texts = []     # V1.29 ②：這一場收到的 Google 定稿 (收到的秒, 文字)（只拿來在存檔前修重複、更正數字）
        self.dup_fixed = 0        # 存檔時修了幾處（收尾畫面照實講）
        self.num_pairs = []       # V1.35（待辦 9）：存檔時照定稿更正的數字 [(舊, 新)]（收尾畫面照實講）
        self.t0 = time.time()
        self.stem, self.source = stem, source
        self.live = open(stem + ".txt", "w", encoding="utf-8", buffering=1)
        self.live.write(f"# Live captions {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        + (f"# {source}\n" if source else "") + "\n")

    def add_final(self, text, turn=None):
        note_caption()            # 收音狀態只在「一陣子沒有新字幕」時才印（見 _live.start_level_watch）
        t = time.time() - self.t0
        self.finals.append((t, text))
        self.turns.append(turn)
        self.live.write(f"[{int(t//60):02d}:{int(t%60):02d}] {text}\n")   # 立刻落地

    def save(self, stem=None, want_srt=False):
        stem = stem or self.stem
        try:
            self.live.close()
        except Exception:
            pass
        # V1.29 ②：.md／.srt 用修過的版本（見 _live.repair_boundary_dups）；.txt 是逐段落地的備援檔，維持畫面上看到的原樣。
        #    修的過程出任何錯都退回原本的行，存檔一定要存得出來。
        try:
            # V1.35：每行帶著回合一起修（兩行併成一行跟著上一行），數字更正只認那一回合的定稿
            rows, self.dup_fixed = repair_boundary_dups([(t, s, k) for (t, s), k in zip(self.finals, self.turns)],
                                                        [f for _t, f in self.final_texts])
        except Exception:
            rows, self.dup_fixed = list(self.finals), 0
        # V1.35（待辦 9）：再用定稿更正「字一樣、只有數字不同」的行（見 _live.number_fixes）；出錯就不改。
        try:
            fixes = number_fixes(rows, self.final_texts)
        except Exception:
            fixes = []
        rows = [(r[0], r[1]) for r in rows]
        marks = {}                # V1.35 審查：.md 在改過的那一行後面註明改了什麼，使用者才能逐句對錄音
        for k, new, pairs in fixes:
            rows[k] = (rows[k][0], new)
            self.num_pairs += pairs
            marks[k] = ", ".join(f"{a} → {b}" for a, b in pairs)
        md = ["# Live meeting captions", "",
              f"- Created: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        if self.source:
            md.append(f"- {self.source}")
        md.append(f"- Length: about {int((time.time()-self.t0)//60)} minutes")
        if fixes:
            md.append(f"- {len(self.num_pairs)} number(s) were corrected using Google's final text ({', '.join(f'{a} → {b}' for a, b in self.num_pairs[:5])}{'…' if len(self.num_pairs) > 5 else ''}; each corrected sentence is marked); the .txt backup keeps what was shown on screen")
        md.append("")
        srt = []
        for i, (t, txt) in enumerate(rows, 1):
            note = f"  [number(s) corrected using Google's final text: {marks[i - 1]}]" if i - 1 in marks else ""
            md.append(f"**[{int(t//60):02d}:{int(t%60):02d}]** {txt}{note}")
            md.append("")
            end = rows[i][0] if i < len(rows) else t + 5
            srt += [str(i), f"{_srt(t)} --> {_srt(end)}", txt, ""]
        open(stem + ".md", "w", encoding="utf-8").write("\n".join(md))
        # .srt 是「字幕軌」，只有要掛在影片上才用得到。一般人點開只會跳出
        # 空的播放器，很困惑，所以預設不產生（要的話加 --srt）。
        if want_srt:
            open(stem + ".srt", "w", encoding="utf-8").write("\n".join(srt))
            return stem + ".md", stem + ".srt"
        return stem + ".md", None



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


def _srt(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s%1)*1000):03d}"


# ─────────────────────────── 主流程 ───────────────────────────
async def run(args):
    import _apikey
    key = _apikey.for_script()         # 環境變數沒有就讀記住的那一組（2026-09-20 N6-3），都沒有就中文說明
    # 🔴 空字串也要擋（2026-09-20 筆電 ⚠-4）：變數存在但被清空時，拿空金鑰去連網
    #    只會得到「金鑰可能打錯」這種誤導訊息。見 _apikey.for_script 的說明。
    if not key:
        return 2
    client = genai.Client(api_key=key)
    atc = types.AudioTranscriptionConfig(
        mode=types.AudioTranscriptionConfigMode.SMART,   # ← 不設會變簡體
        language_codes=["cmn-Hant-TW"],
    )
    if args.vocab:
        atc.custom_vocabulary = args.vocab
    cfg = types.LiveConnectConfig(response_modalities=["TEXT"],
                                  input_audio_transcription=atc)

    # 🔴 SIGINT 的處理函式要在 src.start() 之前就登記好，等來源開好的期間 Ctrl+C 才有用。
    #    舊版是等 wait_ready 跑完才登記：那段是 time.sleep 迴圈、沒有 await，而 asyncio 的 Runner
    #    第一次收到 SIGINT 只做 main_task.cancel()，取消要到下一個 await 才送達 —— 等於按下去被吞掉，
    #    等待照樣跑完、建出只有檔頭的 .txt、離開碼還是 0（2026-09-15 第二輪複查 R2-4；
    #    第 2 項把這個視窗從 0.8 秒拉到最多 8 秒，更容易踩到）。
    # 🔴 Ctrl+C 時不要把英文 traceback 倒給使用者看（見 _live.quiet_async_noise）
    quiet_async_noise()
    stop_all = asyncio.Event()

    # 🔴 2026-09-21 使用者指示：按下 Ctrl+C 之後還要收尾幾秒，畫面若毫無回應，使用者會以為當掉、
    #    一直按。比照 live_bilingual.py（功能 3「快」／功能 6）已經驗過的那一套，每按一次都回一句話。
    #    🔴 不可以在訊號處理函式裡直接 print：剛好撞上字幕正在輸出時會 reentrant call 出錯，
    #    交給事件迴圈代印；迴圈已經結束時（收尾最後階段）就安靜略過。
    loop, presses, started = asyncio.get_running_loop(), [0], [False]

    def _notice(n):
        if not started[0]:
            return            # 還沒開始錄音：下面的取消分支自己會講「已取消」，這裡講收尾會前後矛盾
        if n == 1:
            print(f"{CLR_LINE}\n{DIM}  Ctrl+C received, wrapping up (waiting for the last sentence, then saving), about 3–5 seconds…{RESET}")
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

    src = AudioSource(args.source)
    src.mic_raw, src.mic_device = args.mic_raw, args.mic_device
    print(f"{BOLD}▸ Starting audio capture ({args.source}){RESET}")
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
        # 🔴 沒有任何聲音來源就不要連線、不要建檔，也不要說 ✅（2026-09-14 驗收抓到）。
        src.close()
        print(f"\n{YEL}  ✗ No usable audio source: recording did not start and no files were created.{RESET}")
        return 2
    src.live = True
    started[0] = True          # 🔴 錄音真的開始了，Ctrl+C 才要講「正在收尾」（見 _notice）

    stem = args.out or time.strftime("Captions_%Y%m%d_%H%M")
    tr = Transcript(stem, source_line(args.source, src))
    start_level_watch(src)           # P1：開場印一次收音狀態，之後一陣子沒字幕才再印

    print(f"{BOLD}▸ Connecting to {MODEL}…{RESET}")
    print(f"{DIM}(grey = interim text, still being corrected; white = final text)  Ctrl+C to stop{RESET}")
    print(f"{DIM}  {font_hint()}{RESET}\n")

    # 🔴 定稿不能等伺服器。transcribe-live 只在偵測到講者停頓時才吐
    #    input_transcription；演講、影片、線上會議一路講不停，就會變成
    #    「一分鐘才出一段」，而且那一段的時間戳是「收到的時刻」不是「講的時刻」
    #    （實測 7 分鐘只出 1 段、整段標成 01:08）。
    #    雙語準確模式老早就用 SentenceGate 自己從 interim 切句解決了，
    #    同一個模型、同一套辦法，這裡以前沒跟上。
    def emit_line(s, frag=False):
        tr.add_final(s, gate.cur_turn)      # V1.35：這一行是第幾回合講的（見 _live.SentenceGate.cur_turn）
        print(f"\r\033[K{CYAN}[{int((time.time()-tr.t0)//60):02d}:"
              f"{int((time.time()-tr.t0)%60):02d}]{RESET} {s}")

    gate = SentenceGate(emit_line)

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
                    print(f"{CLR_LINE}\n{YEL}  ⚠ Sentence splitting ran into a problem, so captions may be a little slower ({type(e).__name__}); recording and saving are not affected{RESET}")

    tk_task = asyncio.create_task(ticker())

    rc = Reconnect()
    # 🔴 2026-09-22（P5）：SilenceGate.held_seconds 原本定義了卻全樹無人使用，
    #    它的註解寫「收尾時可以告訴使用者省了多少」，但那段回報從沒實作。
    #    閘門是每條連線各建一個（建在 feed() **外層**，見下方該處說明），
    #    所以在這裡累加跨連線的總量。
    held_total = [0.0]
    # V1.26 B1：只收電腦聲音時，送給 Google 的那一份先放大（見 _live.Leveler）。跨連線共用，換線時倍數不用重來。
    leveler = Leveler() if args.source == "system" else None
    open_turn = [False]      # V1.35：這一回合已經有暫定稿、還沒等到定稿（見下面換線時補的佔位定稿）
    while not stop_all.is_set():
        seg_start = time.time()
        # V1.35（複查 R1'）：上一條連線的最後一回合有暫定稿卻沒等到定稿就斷了（換線、斷線；真實 22 次換線有 3 次）——
        #    補一則空的定稿佔住它的回合編號，不然那幾行會被算成這條新連線第一則定稿的回合（見 _live.number_fixes ⑤）。
        if open_turn[0]:
            tr.final_texts.append((time.time() - tr.t0, ""))
            gate.turn = len(tr.final_texts)
            open_turn[0] = False
        try:
            # 🔴 握手一定要走 open_live：原本直接 `async with connect(...)` 沒有時限，
            #    卡住就是無限安靜等待、Ctrl+C 也叫不動（2026-09-18 使用者實測）。
            async with open_live(
                    client.aio.live.connect(model=MODEL, config=cfg),
                    stop_all) as session:
                rc.ok()          # 連上了，重置失敗計數

                # 🔴 2026-09-21：持續安靜就不要再餵模型（見 _live.SilenceGate）。
                #    實測：靜音 3 分鐘時，沒有這道閘門的話會送出 1800 塊空白音訊，
                #    而模型吃到連續靜音會退化成填充詞迴圈（原文欄自己重複、停不下來），
                #    同時持續計費（約 US$0.32/小時）。有閘門的對照組只送 29 塊、且完全沒有跳針。
                #    功能 1 的 --source 只有 system/mic/both，沒有檔案來源，所以一律啟用。
                # 🔴 2026-09-22（P5）：建在 feed() **外面**（但仍是每條連線一個，行為不變）。
                #    feed() 會被 cancel（伺服器斷線時正是如此），累加寫在它裡面會被跳過 ——
                #    而那正好是壓制最多的情況。放外層才統計得到。
                silence_gate = SilenceGate(floor=gate_floor(args.source))   # V1.23 B：只收電腦聲音時下限放寬

                async def feed():
                    # 8 分鐘到了之後等講者停頓再換線（2026-09-20 N5，見 _live.RotateWhenQuiet）
                    # V1.25：麥克風、兩者都要漸進；看「實際」開起來的收音方式（完整收音開不起來會退回一般收音）
                    rot = RotateWhenQuiet(seg_start, SESSION_SOFT_LIMIT,
                                          **rotate_opts(args.source, getattr(src, "mic_raw_active", args.mic_raw)))
                    while not stop_all.is_set():
                        # 🔴 不用 asyncio.to_thread(src.q.get, True, 0.3)：伺服器先結束連線（go_away、1008）時
                        #    feed 會被取消，但丟進執行緒的 get 還在等，下一塊聲音（100ms）會被它拿走、丟掉
                        #    （2026-09-19 審查重現：每次換線少 1 塊）。跟準確模式一樣改成輪詢。
                        try:
                            pcm = src.q.get_nowait()
                        except queue.Empty:
                            if rot.due():        # 佇列空了才問：有積壓時先送完（見 RotateWhenQuiet）
                                break
                            await asyncio.sleep(0.02)
                            continue
                        for blk in silence_gate.feed(pcm):
                            await session.send_realtime_input(
                                audio=types.Blob(data=leveler.apply(blk) if leveler else blk,
                                                 mime_type=f"audio/pcm;rate={TARGET_SR}"))
                        # 🔴 rot.saw() 要在閘門之外、每一塊都呼叫：8 分鐘換線是靠它累積
                        #    音量高點與安靜塊數，被閘門擋掉的塊也必須算進去，否則判斷失準。
                        rot.saw(pcm)
                        if rot.due():
                            break
                    await session.send_realtime_input(audio_stream_end=True)

                async def read():
                    last_interim = ""
                    turn = ""        # 這一回合最新的暫定稿：定稿來的時候拿它對齊（V1.26 B2）
                    turn_long = False   # 這一回合出現過 4 字以上的暫定稿沒有（V1.35）
                    async for msg in session.receive():
                        # 🔴 go_away 一定要在 server_content 之前檢查：
                        #    GoAway 是 protobuf oneof 的另一個分支，它的
                        #    server_content 是 None，寫在 `if not sc: continue`
                        #    後面就永遠不會執行（官方範例也是第一層就檢查）。
                        if getattr(msg, "go_away", None) is not None:
                            print(f"{CLR_LINE}\n{DIM}(The server asked to switch to a new connection; reconnecting automatically){RESET}")
                            return
                        sc = msg.server_content
                        if not sc:
                            continue
                        it = getattr(sc, "interim_input_transcription", None)
                        if it and it.text and it.text != last_interim:
                            last_interim = turn = it.text
                            turn_long = turn_long or long_interim(it.text)   # V1.35：見 _live.final_extend 的 short_ok
                            open_turn[0] = True
                            gate.feed(it.text)      # ← 切句與定稿都交給它
                            # 🔴 2026-09-25：暫定稿一定要塞進「一行」——按顯示寬度截（中文一字兩格），不是按字數。
                            #    超過一行 \r 就蓋不乾淨，每更新一次留一行殘影（見 _live.fit_tail）。「… 」3 格＋留 1 格。
                            # V1.29 ③：灰字只印「還沒鎖定」的那一截。2026-09-27 全線實測：暫定稿是一整個回合越長越長的一串，
                            #    原本印它的尾巴，剛鎖成白字的句子會在灰字裡再出現一次（同一句畫面上兩遍）。全部鎖完就把灰字清掉。
                            rest = gate.pending_text().strip()
                            if rest:
                                line = fit_tail(rest, shutil.get_terminal_size().columns - 4)
                                print(f"\r{DIM}… {line}{RESET}\033[K", end="")
                            else:
                                print("\r\033[K", end="")
                        # 🔴 不要把 input_transcription 整句餵進去。那是伺服器整個回合結束才吐的
                        #    「另一版」字串，餵進 gate 會被當成新段落而整段重送
                        #    （雙語準確模式實測過：145 句裡重複 38 句）。
                        # V1.26 B2：只拿它「比暫定稿多出來的句尾」接回暫定稿後面（見 _live.final_extend）——
                        #    句尾常常只出現在定稿，以前就這樣掉了。對不上就不接。
                        ft = getattr(sc, "input_transcription", None)
                        if ft and ft.text:
                            # V1.29 ②：存檔前拿來證明「暫定稿自己多吐的重複」；V1.35：也拿來更正數字，要記收到的時間（只認時間最近的那則）
                            tr.final_texts.append((time.time() - tr.t0, ft.text))
                            open_turn[0] = False
                        if ft and ft.text and turn:
                            ext = final_extend(turn, ft.text, short_ok=not turn_long)
                            if ext:
                                gate.feed(ext)
                            turn, turn_long = "", False
                            gate.turn_done()       # V1.29 ①：這一回合結束了，手上的短殘字不必再多等
                        if ft and ft.text:
                            gate.final_check(ft.text)    # V1.36（待辦 13）：只有定稿有的那句（被蓋掉、暫定稿沒聽到）補送一行
                            gate.turn = len(tr.final_texts)    # V1.35：之後餵進來的暫定稿屬於下一則定稿那一回合

                f = asyncio.create_task(feed())
                r = asyncio.create_task(read())
                done, pending = await asyncio.wait({f, r}, return_when=asyncio.FIRST_COMPLETED)
                # 🔴 feed 先結束＝到了輪替時間。這時候伺服器手上通常還有一句
                #    沒吐回來的定稿，直接 cancel 掉 read 就會每 8 分鐘掉一句
                #    （兩小時會議約掉 15 句）。給它一點時間把最後一句收完。
                if f in done and r in pending:
                    await asyncio.wait({r}, timeout=ROTATE_GRACE)
                for t in pending:
                    t.cancel()
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
                rotating = f in done and time.time() - seg_start >= SESSION_SOFT_LIMIT
                if errs and not rotating:
                    raise errs[0]
        except Exception as e:
            if stop_all.is_set():
                break
            await asyncio.sleep(rc.failed(e))

    tk_task.cancel()
    try:
        gate.flush()  # 🔴 按 Ctrl+C 當下正在講的那一句不能弄丟
    except Exception:
        pass          # 收尾出錯也不能害 .md 存不出來
    src.close()
    md, srt = tr.save(want_srt=args.srt)
    n = len(tr.finals) - tr.dup_fixed          # 跟 .md 的段數一致（V1.29 ② 併掉的不算）
    print(f"\n\n{'✅' if n else '⚠'} Total captions: {n}" + ("" if n else " (nothing was recognised during the whole session; please check that the audio source actually had sound)"))
    if tr.dup_fixed:
        print(f"{DIM}   While saving, {tr.dup_fixed} repeated caption(s) were fixed using Google's final text (this doesn't change what was shown on screen; the .txt is kept as it was){RESET}")
    if tr.num_pairs:
        print(f"{DIM}   While saving, {len(tr.num_pairs)} number(s) were corrected using Google's final text ({', '.join(f'{a} → {b}' for a, b in tr.num_pairs[:3])}{'…' if len(tr.num_pairs) > 3 else ''}; this doesn't change what was shown on screen; the .txt is kept as it was){RESET}")
    if held_total[0] >= 1:
        # P5：讓使用者看得到靜音閘門真的有在省。1 秒以下不印，避免短測試洗版。
        print(f"{DIM}   Skipped {held_total[0]:.0f} seconds of unnecessary uploading during quiet periods{RESET}")
    print(f"   {md}")
    if srt:
        print(f"   {srt}")
    print(f"   {stem}.txt (backup copy, each caption saved to disk as soon as it appeared)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["system", "mic", "both"], default="system")
    ap.add_argument("--vocab", nargs="*", default=[], help="proper nouns (in Traditional Chinese)")
    ap.add_argument("--out", default=None, help="output file name (without extension)")
    ap.add_argument("--srt", action="store_true",
                    help="also create an .srt caption track (only needed if you want to add it to a video)")
    ap.add_argument("--mic-raw", action="store_true",
                    help="use full capture for the microphone (bypasses Windows noise suppression; loudspeakers in the room are picked up too)")
    ap.add_argument("--mic-device", default=None,
                    help="which microphone to use (the name must match what Windows shows); leave it out to follow the Windows default, which switches automatically when a headset is plugged in or out")
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    code = 0
    try:
        code = asyncio.run(run(args)) or 0
    except KeyboardInterrupt:
        pass
    finally:
        close_open()               # V1.33：沒預期的錯誤跳出來時，也要先把收音關好再結束（見 _live.close_open）
    sys.exit(code)                 # 沒有聲音來源＝2；選單看離開碼才知道不是成功


if __name__ == "__main__":
    main()
