# -*- coding: utf-8 -*-
"""
即時雙語字幕（原文 + 譯文同時出現）    gemini-3.5-live-translate-preview

看外語演講/影片時，上面一行是原文，下面一行是譯文（預設翻成中文，也可以翻成英文、日文），同時出現。

原理：這個模型本來是做「同步口譯」的，一條連線就會回兩種文字：
  input_transcription  = 它聽到什麼（原文）
  output_transcription = 它翻成什麼（譯文）

用法：
  python live_bilingual.py --source system                    # 抓電腦播出來的聲音
  python live_bilingual.py --source system --target ja        # 翻成日文
  python live_bilingual.py --source mic                       # 抓麥克風
按 Ctrl+C 結束，存成雙語 .md（給人讀）與 .txt（即時備份）。
"""
import os, sys, io, asyncio, argparse, time, queue, threading, signal

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

MODEL = "gemini-3.5-live-translate-preview"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _live import (Reconnect, DropWatch, Speaker, on_console_close,   # noqa: E402
                   open_live, quiet_async_noise, output_devices,
                   default_output_name, resolve_output_device, same_device,
                   is_default_like, probe_output_device, mix_lanes, MIX_GRACE, RotateWhenQuiet, SilenceGate,
                   mme_endpoint_map, capture_mic, capture_loopback, font_hint, source_line,
                   note_caption, start_level_watch, dot_may_join, dot_joins_next, DOT_WAIT, gate_floor,
                   rotate_opts, LagWatch, STALL_WARN, REDIAL_LAG, RESEND_MAX, RESEND_PAD, RESEND_RATE,
                   LOST_REPORT_MIN, STALL_RESET, join_decimal, join_capture,
                   keep_open, forget_open, close_open)

TARGET_SR = 16000
CHUNK_MS = 100
FILE_WAIT_Q = 150        # V1.26 A3：影音檔來源，輸出佇列（容量 400 塊）積到這麼多就先停下來等，不要讓混音器丟聲音
ROTATE_GRACE = 3.0       # 輪替時等最後一句定稿的寬限秒數
SESSION_SOFT_LIMIT = 8 * 60

DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"
SRC_C, TGT_C, YEL = "\033[38;5;250m", "\033[36m", "\033[33m"
GRN = "\033[32m"


def _print_devices(usable_only=True):
    """把播放裝置印出來（--speak 指錯裝置時要讓人看得到能選什麼）。

    🔴 預設只印「真的開得起來」的：查得到的裝置裡有一大半（WDM-KS、WASAPI）
       其實播不出 24kHz，印給使用者選等於挖坑給他跳。
    """
    devs = output_devices(usable_only=usable_only)
    if not devs:
        print(f"{DIM}     (No device can play the interpreter voice — please plug in headphones and try again){RESET}")
        return
    dflt = default_output_name()
    print(f"{DIM}     {'Devices that can play the interpreter voice' if usable_only else 'All playback devices'}:{RESET}")
    for i, n in devs:
        mark = "  ← system default (can't be used with --source system/both)" if is_default_like(n, dflt, idx=i) else ""
        print(f"{DIM}       {i:>3}  {n}{mark}{RESET}")


def display_name(sd_index, fallback):
    """畫面顯示用的裝置名稱：拿 sounddevice 的播放編號反查音訊端點，再取登錄檔裡的完整名稱。

    🔴 只給人看。比對、開裝置一律用 sd_index 或 resolve 出來的名稱，不可以拿這個名字去找裝置。
    🔴 MME 把名稱截成 31 字（「1 - KONKA LCDTV (AMD High Defin」），直接顯示會讓使用者以為自己選錯裝置。
       2026-09-20 起改成反查：不管選單傳來的是端點 ID（功能 6 選 1）還是裝置名稱（選 2／3），
       三條路都看得到完整名稱；問不到 Windows 的對照表時退回原本的名稱（複查指出的缺口）。
    """
    try:
        import _audioroute as _ar
        eid = next((k for k, v in mme_endpoint_map().items() if v == sd_index), None)
        return (_ar.endpoint_name(eid) if eid else None) or fallback
    except Exception:
        return fallback

# 🔴 給 menu.py 判讀用的固定標記，不是給人看的說明文字。
#    使用者在「等聲音來源開好」那段期間按 Ctrl+C 取消時，這一行會原封不動印在 stdout 上
#    （純 ASCII、自己一行、不帶顏色碼），父行程用子字串比對就分得出「使用者自己取消」與「出錯了」。
#    為什麼不用離開碼：見下面取消分支裡的說明（從選單進來時 130 會被吃成 0）。
#    三支 live 腳本用同一個字串，改的時候三支要一起改（開發端的 test_r2_live_review.py ⑧ 會比對，該檔不隨附）。


# ── 音訊擷取（與 live_caption.py 相同） ──
class AudioSource:
    def __init__(self, source, path=None):
        self.source = source
        self.path = path
        self.eof = False
        # 輸出（已混音）。V1.26：200→400 塊（40 秒）——換線補送最多 30 秒、照 1.5 倍速要送 20 秒，
        #    這段期間進來的即時聲音都要排得下，不然會被混音器丟掉（見 _live.RESEND_RATE）
        self.q = queue.Queue(maxsize=400)
        self.drop = DropWatch(chunk_ms=CHUNK_MS)
        self.stop = threading.Event()
        self._lanes = {}
        self._failed = set()
        self._ready = set()          # 已經開好、開始收音的來源
        self._wanted = []            # 這次要開的來源
        self.live = False            # 主流程確認至少一路可用之後才設 True（見 wait_ready）
        self.mic_raw = False         # 完整收音（--mic-raw）：繞過 Windows 降噪，擴音器的聲音也收
        self.mic_device = None       # 指定麥克風（--mic-device）；None＝跟著 Windows 預設
        self.follow_default = True   # 口譯（--speak）時設 False：不跟著預設播放裝置換（見 _live.capture_loopback）
        self.devices = {}            # 每一路目前實際在用的裝置名稱（寫進檔頭，見 _live.source_line）
        self.threads = []            # V1.32：麥克風／電腦聲音的收音執行緒（收尾時等它們關好串流，見 close）

    # 🔴 2026-09-22：兩路都改用 _live 的看門狗版本（三支即時程式共用）——裝置掉了、預設換了會自動接回。
    #    舊版只在開頭開一次，耳麥插頭鬆 3 秒整場就沒字幕（會議實測 14:25:12），見 _live.capture_mic 的說明。
    def _wasapi_loopback(self, lane='system'):
        capture_loopback(self, lane, CHUNK_MS, follow_default=self.follow_default)

    def _mic(self, lane='mic'):
        capture_mic(self, lane, CHUNK_MS, raw=self.mic_raw, device=self.mic_device)

    def _file(self, lane='file'):
        """讀現成的影音檔（不碰喇叭、不錄到別的聲音）。"""
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
            wav = os.path.join(tempfile.gettempdir(), f"bi_{abs(hash(self.path)) % 10**8}.wav")
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                            "-i", self.path, "-ar", str(TARGET_SR), "-ac", "1",
                            "-c:a", "pcm_s16le", wav], check=True)
            # 🔴 這是整場會議的完整聲音，未加密躺在 %TEMP%。用完要刪，
            #    不然解除安裝之後它還在，而且沒有人知道它在那裡。
            atexit.register(_quiet_remove, wav)
            on_console_close(lambda: _quiet_remove(wav))   # 視窗被關掉時 atexit 不會跑
        try:
            wf = wave.open(wav, "rb")
            sr = wf.getframerate()
            self._ready.add(lane)
            print(f"{DIM}  Source file: {os.path.basename(self.path)}  {sr}Hz, {wf.getnframes()/sr:.0f} seconds{RESET}")
            fpc = int(sr * CHUNK_MS / 1000)
            while not self.stop.is_set():
                d = wf.readframes(fpc)
                if not d:
                    break
                # V1.26 A3：檔案不必趕即時。連線正在重連／補送、聲音送不出去（佇列快滿）時先停下來等——
                #    舊版照樣往下讀，混音器塞不進佇列就把聲音丟掉，斷線那幾秒的檔案內容就消失了（09-26 T6）。
                while self.q.qsize() >= FILE_WAIT_Q and not self.stop.is_set():
                    time.sleep(0.05)
                self._push(np.frombuffer(d, dtype=np.int16).astype(np.float32), sr, lane)
                time.sleep(CHUNK_MS / 1000)     # 照真實速度餵，模擬直播
            wf.close()
        finally:
            # 🔴 不能只靠 atexit：實測按 Ctrl+C 中斷或被強制關閉時它不一定跑得到，
            #    整場會議的未加密音訊就會留在 %TEMP%。這裡讀完就先刪一次。
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


# ── 台灣用語校正 ──
# 實測：模型出的是繁體字，但用詞常是大陸慣用語（計劃/項目/報銷）。
# 🔴 只放「在臺灣幾乎不可能有別的意思」的詞。
# 刻意不放：項目(會把「項目會議」誤傷成「專案會議」)、計劃(當動詞是對的)、通過(通過審查是對的)、
#           同行(同行者)、數據(大數據)、程序(程序正義)、質量(物理的質量)、登錄(法律用語)、菜單(餐廳)。
#           這些交給連線層的 TW_STYLE_INSTRUCTION（2026-09-15 使用者核准的第 5 項）。
# 🔴 這張表跟 live_bilingual_hq.py 的那張必須一模一樣（開發端的 test_to_tw_scope.py 會比，該檔不隨附）。
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

# ── 臺灣用語：連線層的指示 ──
# e5 實測（2026-09-15，9 條連線）：live-translate-preview 吃得下 system_instruction，0 斷線、譯文長度沒縮、
# 簡體 0；項目／在線／通過／同行 從 12/12 次全中降到 1/24。🔴 只解決「發音不同」的詞：計劃↔計畫同音，
# 寫法是輸出轉錄的 ASR 挑的、指示管不到（同一場「基金計劃」「導師計畫」並存），所以 TW_TERMS 事後替換
# 要留著當第二道防線。🔴 文字要跟實測完全一樣——加了詞就是沒測過的版本。
TW_STYLE_INSTRUCTION = ("譯文請用臺灣慣用的說法：專案（不是項目）、線上（不是在線）、"
                        "透過（不是通過）、同儕（不是同行）、計畫（不是計劃）。")



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


def to_tw(text, extra=None):
    for a, b in TW_TERMS.items():
        if a != b:
            text = text.replace(a, b)
    for a, b in (extra or {}).items():
        text = text.replace(a, b)
    return text


def _lang_base(target):
    """語言碼的主標籤：en-US／en_US／EN → en；zh-TW → zh（跟 live_bilingual_hq.py 同一寫法）。"""
    return (target or "").replace("_", "-").split("-")[0].lower()


def is_zh_target(target):
    """譯文是中文（zh…、cmn…、yue…）才做臺灣用語替換；沒給語言碼照舊替換。

    🔴 TW_TERMS 是「中文詞 → 臺灣用詞」。英文、日文譯文裡剛好出現這幾個漢字時
       （例如日文在講中文的「視頻」），換掉就改掉了原意（2026-09-14 使用者核准修正）。
       live_bilingual_hq.py 有同一條規則，兩邊要一起改。
    """
    base = _lang_base(target)
    return not base or base in ("zh", "cmn", "yue")


def is_tw_style_target(target):
    """譯文是「臺灣繁體」才給連線層的 TW_STYLE_INSTRUCTION。zh-TW、cmn-Hant-TW、zh-Hant… 為 True。

    🔴 跟上面的 is_zh_target 是兩回事，不要合併，也不要把 is_zh_target 改成這個：
       ・is_zh_target 管的是 to_tw（事後替換）。它只問「譯文是不是中文」，因為 TW_TERMS 的鍵
         全是繁體字，對簡體譯文本來就命中不了，放寬到 zh／zh-CN 不會有副作用。
       ・is_tw_style_target 管的是 system_instruction（送給模型、會真的改變輸出）。
         --target zh／zh-CN 依本檔 --target 的說明是「出簡體」，再塞「請用臺灣慣用的說法」
         就自相矛盾（2026-09-15 第二輪複查 R2-6）。所以這裡要求語言碼真的帶 TW 或 Hant。
       ・另一個差別：語言碼空白時 is_zh_target 回 True（照舊替換），這裡回 False
         —— 沒講明是臺灣繁體就不要自作主張給指示。
    """
    t = (target or "").replace("_", "-")
    if _lang_base(t) not in ("zh", "cmn", "yue"):
        return False
    return any(p.lower() in ("tw", "hant") for p in t.split("-")[1:])


# 譯文的標籤（.txt 每一行前面、畫面圖例）。
# 🔴 不能寫死「中文」：選單也能翻成英文、日文，原本 .txt 會把每一行英文都標成「中文」
#    （2026-09-11 稽核抓到）。
TGT_LABEL = {"zh-TW": "Chinese", "en": "English", "ja": "Japanese"}


def tgt_label(target):
    return TGT_LABEL.get(target, "Translation")


# ── 雙語字幕記錄 ──
SENT_END = "。！？.!?；;"
SRC_MAX_CHARS = 90        # 原文行的長度上限（Bilingual 的原文 Buffer；配對時也拿它當「滿一行」的尺）


class Buffer:
    """模型一次只吐一兩個詞，要攢成完整句子才像字幕。"""

    def __init__(self, flush_cb, max_chars=70, idle=2.5):
        self.buf = ""
        self.start = None
        self.flush_cb = flush_cb
        self.max_chars = max_chars
        self.idle = idle
        self.last = time.time()
        self._dot_hold = False    # 上一小段停在「8.」「Mr.」這種還不確定是不是句尾的點：等下一小段再決定

    def add(self, text, now):
        # 🔴 2026-09-25（使用者核准；同 _live.SentenceGate 的修正）：模型一次吐一兩個詞，「8.933」常被拆成
        #    「8.」｜「933」兩小段送來，舊寫法看到結尾是「.」就整句送出 →「…拿到了 8.」「933 以及 bonus 0.」
        #    （假伺服器端到端重現）；V1.20 起「Mr.｜Kuo」這類稱謂也一樣（09-23 功能 6 實測被切成兩行）。
        #    原文行與中／日文譯文行都走這裡；英文譯文走 SoftBuffer（它有自己的 TITLES 與 ② 的 num）。
        #    改成：結尾是這種點先不送，下一小段接得上（小數接數字、稱謂接名字，見 _live.dot_joins_next）就併成同一句；
        #    接不上、或 idle 秒都沒有下一段，才送出。
        if self._dot_hold:
            self._dot_hold = False
            if not dot_joins_next(self.buf.rstrip()[:-1], text.lstrip()):
                self.flush()              # 接不上：那個「.」真的是句尾，先把上一句送出去
        if self.start is None:
            self.start = now
        self.buf = join_decimal(self.buf, text)     # V1.29 ⑨：「8.」＋「 5」接成「8.5」，不留空白
        self.last = time.time()
        tail = self.buf.rstrip()
        if tail.endswith(tuple(SENT_END)) or len(self.buf) >= self.max_chars:
            if tail[-1:] == "." and dot_may_join(tail[:-1]) and len(self.buf) < self.max_chars:
                self._dot_hold = True
                return
            self.flush()

    def tick(self):
        idle = self.idle
        t = self.buf.rstrip()
        if t.endswith(".") and dot_may_join(t[:-1]):
            idle = max(idle, DOT_WAIT)    # 停在「8.」「Mr.」：跟切句器一樣多等一下（SoftBuffer 也走這裡）
        if self.buf and time.time() - self.last > idle:
            self.flush()

    def flush(self):
        self._dot_hold = False
        if not self.buf.strip():
            self.buf = ""; self.start = None; return
        self.flush_cb(self.start or 0.0, self.buf.strip())
        self.buf = ""
        self.start = None


class SoftBuffer(Buffer):
    """英文譯文用：切在句子或子句的邊界，後半段留著繼續攢。

    🔴 Bilingual 給譯文設 45 字上限、一到就整段送出。45 個中文字約佔主控台 90 格，
       英文 45 個字母只佔 45 格，句子會被切成兩半，例如「Uh, I'd like to add something, it's about the」
       （2026-09-14 使用者核准修正；只改英文，中文、日文照舊用 Buffer）。
    送出規則（每收到一小段就檢查一次）：
      ① 緩衝中間出現句尾標點、後面又接了字（例如一小段「 department. Okay.」）→ 先送前面那句
      ② 結尾是句尾標點 → 整段送出；但結尾是 Prof.／Dr. 這類頭銜（St. 只在緩衝未滿 max_chars 時），
         或緩衝未滿 soft 字、結尾是 U.S.／p.m. 這種「字母.字母.」或句中的 No.（Room No.）時，先等下一小段
      ③ 攢到 soft 字、裡面有子句標點 → 切在最後一個子句標點（後面緊接句尾標點的「yes,...」不算）
      ④ 攢到 max_chars 還沒有標點 → 結尾剛好是子句標點就整段送出；否則切在最後一個空白，
         行尾盡量不留 the／of／and、所有格（college's），以及前面是這類字的數量詞（the eight｜colleges）
    ③④ 的切點離開頭至少 FLOOR 字；收尾的引號括號跟著上一段走；同一緩衝裡的「12,000」「15.5」「...」「?!」不從中間切。
    做不到的（取捨）：縮寫後面接大寫字（U.S. News、Taiwan vs. Japan）會被當成句尾切開；
    標點剛好被拆在兩小段之間（Really?｜!、"Stop.｜"）、或 vs.／etc.／...／單一字母／句首的 No. 剛好在一小段結尾時，
    不等下一小段就送出（15.｜5 這種小數 2026-09-25 起會等，見 ② 的 num）；St. 在緩衝滿 max_chars 時會跟後面的名字分兩行，剛好是街名句尾時會跟下一句併成一行；
    句中的 No. 剛好是句尾（The answer is No.）時要等下一小段或停頓 idle 秒；阿拉伯數字（the 8｜colleges'）行尾不處理。
    後半段的時間用它第一個字實際收到的時間，存 .md 時依時間配對原文才不會跑掉。
    """
    CLAUSE = ",;:，、；："
    CLOSERS = "\"'”’)]）」』"
    OPENERS = "(\"'“‘[（「『"
    TITLES = ("Dr", "Prof", "Mr", "Mrs", "Ms", "St")
    WEAK = frozenset("a an the of to for and or but nor in on at by with from into as that which who whose "
                     "about without during through between "
                     "my your our their his her its this these those each every some any not also "
                     "is are was were be been have has had will would can could should may might must "
                     "if than so".split())
    # 數量詞只有在前一個字是 WEAK 時才算（the eight｜colleges 往左找；chapter one、thank you all 照常可以放行尾）
    QUANT = frozenset("all both several many few one two three four five six seven eight nine ten eleven twelve".split())
    FLOOR = 20

    def __init__(self, flush_cb, max_chars=90, soft=60, idle=2.5):
        super().__init__(flush_cb, max_chars=max_chars, idle=idle)
        self.soft = soft
        self._marks = []         # [(這一小段在 buf 的起點, 收到的秒數)]

    def add(self, text, now):
        if self.start is None:
            self.start = now
        if not self.buf:
            self._marks = []
        self._marks.append((len(self.buf), now))
        self.buf = join_decimal(self.buf, text)     # V1.29 ⑨：同 Buffer（這一小段的起點位置不變）
        self.last = time.time()
        while self.buf.strip():
            k = self._cut()
            if k is None:
                return
            self._split(k)

    def _last_word(self, s):
        """s 最後一個字（去掉結尾的點與前後引號括號）。"""
        words = s.rstrip(".").split()
        return words[-1].strip(self.OPENERS + self.CLOSERS) if words else ""

    def _title_at(self, s):
        """s 結尾的「.」是不是 Dr./Prof./St. 這類頭銜的點（通常後面還接名字，不是句尾）。"""
        return s.endswith(".") and self._last_word(s) in self.TITLES

    def _hold_end(self, s):
        """② 要不要先等下一小段：結尾是 U.S./p.m. 這種「字母.字母.」（頭銜另外判斷）。
        年份數字、No.（常是回答「沒有」）、etc. 常常真的是句尾，不等（等了字幕會晚 2～3 秒）。"""
        return s.endswith(".") and s[-3:-2] == "." and s[-2:-1].isascii() and s[-2:-1].isalpha()

    def _no_abbr(self, s):
        """句中大寫的 No.（Room No. 5、Regulation No. 3）是編號縮寫；句首、引號或問句後面的 No. 是回答「沒有」。"""
        if not s.endswith("No.") or self._last_word(s) != "No":
            return False
        before = s[:-3].rstrip()
        return bool(before) and before[-1] not in SENT_END + self.CLAUSE + self.OPENERS

    def _abbr_end(self, s):
        """④ 找空白時要跳過的結尾（不影響送出時機，可以寬一點）：頭銜、U.S./p.m.、No./vs./etc./approx.、
        數字加點（15.｜5）、單一字母加點（但 2B. 這種數字加字母不算）、刪節號。"""
        if not s.endswith("."):
            return False
        if (s.endswith("..") or self._title_at(s) or self._hold_end(s)
                or self._last_word(s).lower() in ("no", "vs", "etc", "approx")):
            return True
        c, before = s[-2:-1], s[-3:-2]
        return c.isdigit() or (c.isascii() and c.isalpha() and not before.isalnum())

    def _ok(self, k, j, stop):
        """送出 buf[:k]、留下 buf[k:]，這個切點能不能用。j＝標點後面的位置（k 可能再跳過收尾的引號括號）。"""
        s = self.buf
        prev, nxt = s[j - 1], s[k]
        if not prev.isspace() and prev.isascii() and nxt.isalnum():
            return False                              # 12,000／15.5／U.S. 字母中間
        if nxt in self.CLOSERS or nxt in SENT_END:
            return False                              # "yes,"／,...／?! 只切在整串標點的最後
        if stop:
            follow = s[k:].lstrip()[:1]
            if prev == ".":
                if self._title_at(s[:j]):
                    return False                      # Prof.｜Chang
                if follow.islower() or follow.isdigit():
                    return False                      # U.S.｜embassy、No.｜5、p.m.｜on
            elif j < k and prev in "?!" and follow.islower():
                return False                          # "Why?" he asked.
        return True

    def _last(self, chars, lo, stop=False):
        """由右往左找第一個合格的標點切點（標點在 chars 裡、後面還有字、離開頭至少 lo 字）。"""
        s = self.buf
        for k in range(len(s) - 1, max(lo, 1) - 1, -1):
            j = k
            while j > 1 and s[j - 1] in self.CLOSERS:
                j -= 1                                # 收尾的引號括號跟著上一段走
            if s[j - 1] in chars and s[k:].strip() and self._ok(k, j, stop):
                return k
        return None

    def _space_cut(self):
        """④：由右往左找空白。不切在 Prof.｜Chang、No.｜5；行尾是 the／of／and 或所有格就再往左找，都不行才用最右邊那個。"""
        s = self.buf
        fallback = None
        for k in range(len(s) - 1, max(self.FLOOR, 1) - 1, -1):
            if s[k - 1] != " " or not s[k:].strip():
                continue
            head = s[:k].rstrip()
            if not head or self._abbr_end(head):
                continue
            if fallback is None:
                fallback = k
            words = head.split()
            w = self._last_word(head).lower()
            prev = words[-2].strip(self.OPENERS + self.CLOSERS).lower() if len(words) > 1 else ""
            weak = (w in self.WEAK or words[-1].endswith(("'s", "’s", "s'", "s’"))
                    or (w in self.QUANT and prev in self.WEAK))
            if not weak:
                return k
        return fallback

    def _cut(self):
        s = self.buf
        k = self._last(SENT_END, 1, stop=True)                          # ①
        if k is not None:
            return k
        tail = s.rstrip().rstrip(self.CLOSERS)
        title = self._title_at(tail) and (len(s) < self.max_chars or self._last_word(tail) != "St")
        # 🔴 2026-09-25（使用者核准）：結尾是「數字.」也先等下一小段——「15.｜5」分兩小段送來原本會被切開。
        #    下一段接數字就進了同一個緩衝，① 的 _ok 本來就不會從 15.5 中間切；接的是別的字就照 ① 切。緩衝滿了不等。
        num = tail[-1:] == "." and tail[-2:-1].isdigit() and len(s) < self.max_chars
        if tail.endswith(tuple(SENT_END)) and not (
                title or num or (len(s) < self.soft and (self._hold_end(tail) or self._no_abbr(tail)))):
            return len(s)                                               # ②
        if len(s) >= self.soft:
            k = self._last(self.CLAUSE, self.FLOOR)                     # ③
            if k is not None:
                return k
        if len(s) >= self.max_chars:
            if tail.endswith(tuple(self.CLAUSE)) and not tail[-2:-1].isdigit():
                return len(s)                                           # ④ 結尾剛好是子句標點（不含 12,｜000）
            k = self._space_cut()                                       # ④
            return len(s) if k is None else k
        return None

    def _split(self, k):
        rest = self.buf[k:].lstrip()
        if not rest:
            self.flush()
            return
        skip = len(self.buf) - len(rest)
        t = [tt for off, tt in self._marks if off <= skip][-1]
        marks = [(0, t)] + [(off - skip, tt) for off, tt in self._marks if off > skip]
        self.buf = self.buf[:k]
        self.flush()
        self.buf, self.start, self._marks = rest, t, marks


# ── .md／.srt 的原文／譯文配對 ──
# 🔴 第一版對每一句原文找「時間最接近、還沒用過」的譯文。譯文常被切成兩三行（子句、長度），一句原文的
#    譯文尾巴就會被下一句原文搶走；配對還會交錯，.md 的譯文順序跟 .txt 對不起來（實測 2 組錄音）。
# 🔴 第二版改成「先把行併成句子區塊、區塊之間做不交錯配對、區塊內第 k 行對第 k 行」，生出三個新病
#    （2026-09-15 第二輪對抗式複查，三個都有真實錄音重現）：
#      (a) 一句原文的譯文被切成兩個區塊、原文只有一個區塊時，多出來的譯文區塊會被配給「下一句原文」，
#          之後每一列連鎖往後推（r5_sapi_ja 一口氣錯 7 行）；
#      (b) 整段都沒有句尾標點時（Buffer 45／90 字硬切、停頓送出的行都沒有標點），兩邊各自併成一個大
#          區塊，區塊內用序號硬配會整批錯位；
#      (c) 區塊邊界是原文側與譯文側各自判斷的，兩側行數不等時會多出孤格、下一句原文配不到譯文
#          （開發端 test_to_tw_scope 的「No terms here.」底下是空的；該檔不隨附）。
# 這一版把「區塊」這一層整個拿掉。先量再設計（19 組真實 live-translate 串流、796 行原文、1,156 行譯文）：
#   · 模型的「原文小段」與「譯文小段」是同一條連線交錯吐出來的，每個譯文小段都在對應的原文小段之後
#     約 0.3 秒（實測 r8_sapizh_en 195～232 秒逐段列印）。而行的時間戳記是「這一行第一個小段到達的
#     時刻」（Buffer.start），所以一行原文 i 等於佔住時間區間 [s_i, s_i+1)，它的譯文行就在這裡面開始。
#   · 一行原文帶 0～7 行譯文（完全沒有譯文的 74 行、1 行的 471、2 行的 179、≥3 行的 72），
#     所以「一對一」或「區塊內第 k 行對第 k 行」一定不夠。
# 規則＝「以原文為骨幹的時間區間歸屬 ＋ 逐行單調 DP 微調」：
#   ① 因果：一行譯文不可以配給「還沒開始」的原文（容忍值見 _lead，預設 0、只有新句開頭才放寬）。
#      (a) 的連鎖錯配就是被這一條擋掉的。
#   ② 落在自己原文的區間內免費；跨過下一行原文的起點才計費，費用＝超出的秒數。
#   ③ 一行原文完全沒有譯文要付 EMPTY_PEN（＋依這行原文長度加 EMPTY_LONG）。實測「了解。」這種很短的
#      句子，譯文會慢半拍、掉到下一行原文起點之後 0.12～0.37 秒；②③ 相權就把它拉回自己的原文底下。
#   ④ 上一行譯文結尾是子句標點（SoftBuffer 刻意切在子句中間）→ 這一行換到別行原文底下要付 CONT_PEN。
# DP 的狀態只有「處理到第 i 行原文、已經用掉前 j 行譯文」，所以「每行恰好一次、順序不變、配對不交錯」
# 是結構保證，不是靠斷言；每行原文只掃自己的時間帶（兩個單調指標），2 小時素材（1440＋1440 行）實測
# 0.004 秒、記憶體峰值 1 MB（上一版的區塊 DP 是 O(區塊數²)，同一份資料要 1.9 秒）。
# 每一列的長相跟前兩版一樣（時間、一行原文、一行譯文），只有「誰配誰、先後順序」不同：.md 照配對後的
# 順序寫（一句原文的譯文尾巴一定跟在它後面）；.srt 是字幕軌，照時間排。畫面與 .txt 本來就對，這裡不碰。
LEAD_CAP = 1.5         # 一行譯文最多可以比它的原文行早幾秒開始（上限；實際容忍值見下面的 LEAD_FRAC）。
                       # 19 組錄音實測：真的該往後掛的那些行，最早比原文早 1.00 秒（h4／r2 的
                       # 「We hope it's October 15th,」一類），1.2～2.0 在 19 組上結果一模一樣（一段平原），
                       # 取中間的 1.5。3.0 以上會開始把「了解。」這種短句的譯文往後推。
LEAD_FRAC = 0.34       # 容忍值＝這一行時長的幾分之幾（再受 LEAD_CAP 封頂）。等於說「這一行的原文起點必須
                       # 落在這一行的前 34% 以內」，再往後就當它是上一句的尾巴，不准往後跳。
                       # 19 組錄音實測（容忍值真的被用到的 17 列，逐列讀中／英／日原文判讀）：
                       # 該放行的 15 列「早幾秒 ÷ 這一行多長」＝0.113～0.326；該擋的是 0.357 那一列（另有 0.129 那列被放行後仍判錯，但它不是門檻擋得掉的）
                       # （r7_long10_ja 譯#88「今日中に送ります。」，原#76「沒問題,我今天下班前會發出去。」
                       # 的下半句），兩群中間有一段空白，取 0.34。0.33～0.35 在 19 組上結果完全相同；
                       # 0.32 會誤傷 r8b 譯#80（0.326），0.36 以上就擋不住 #88 了。
                       # 🔴 原本寫死 0.5（「行的中點」）：#88 的重心只比原#77 的起點晚 0.29 秒，照樣被放行，
                       # 於是 .md 上出現「然後同步公告在研發處的內部網站上。／今日中に送ります。」這種
                       # 一眼看得出錯的配對（2026-09-15 第三輪對抗式複查 R4-2／R4-4）。
EMPTY_PEN = 0.50       # 一行原文完全沒有譯文的「基本」代價（秒）。實測「該拉回前一行原文」的 9 例超出
                       # 0.12～0.37 秒，所以要 > 0.37；再大就會把下一句的譯文也拉過來（0.6 起開始掉分）。
EMPTY_LONG = 1.00      # 再依「這行原文有多長」加上去：滿一行（SRC_MAX_CHARS）的長句沒有任何譯文非常可疑，
                       # 「嗯。」「好。」這種兩個字的填充句沒被翻很正常。
OVER_CAP = 3.00        # 譯文最多往回配給「已經結束 OVER_CAP 秒的原文」；同時也是 DP 的帶寬。
                       # 只要 > EMPTY_PEN + EMPTY_LONG（往回配的實際上限）就不影響結果，取 3.0 留餘裕。
CONT_PEN = 1.20        # 上一行譯文切在子句標點時，這一行換到別行原文底下的代價（秒）。0.5～1.5 之間
                       # 對 19 組錄音結果相同；取 1.2 是因為「一句原文的譯文尾巴晚 1 秒才到」要 > 1.0 才救得回來。
ORPHAN_PEN = 30.0      # 一行譯文完全配不到原文的代價（只會發生在第一行原文之前）
CONT_GAP = 5.0         # V1.29 ⑥：上一行譯文到這一行隔超過這麼多秒、而且這段時間裡已經開始了新的一行原文 →
                       # 這一行不是上一句的續行（不套 _lead 的「續行不給容忍值」與 CONT_PEN）。
                       # 🔴 2026-09-27 全線實測 D2（功能 6 麥克風，中→英）：原文「研究經費比去年增加了12. 5,」被切在逗號，
                       #    譯文也停在「…by 12. 5,」；15.5 秒後下一句「下午兩點由 Dr.…」的原文先出來（48.3 秒）、譯文 0.2 秒後才到，
                       #    卻被續行規則掛回 15 秒前那一句，後面整排錯一格（.md 上「下午兩點…」底下掛的是「Next March…」）。
                       #    隔很久、中間又有新原文，而且這一行看起來是新的一句（見 _looks_new），就不是同一句。
                       #    ⛔ 不能只看時間：翻譯模型會在句中停住 5～11 秒再把上一句講完（V1.29 審查 P1／P2）。


def _looks_new(prev, cur):
    """V1.29 審查：這一行譯文看起來是「新的一句」，不是上一行的後半。
    🔴 「同一句的前後兩截不會隔這麼久」不成立：翻譯模型在句中停住 5～11 秒（中間下一句原文先到）再把上一句講完，
       「especially those from Southeast Asia.」會被掛到下一句原文底下（審查 P1／P2）；真實紀錄也有
       「…launched on December 1st,」｜5.2 秒｜「and the old system…」。所以：英文字母開頭要大寫才算新句；
       數字、小寫開頭一律當續行；中日文沒有大小寫，要上一行停在標點上才算（停在字中間的「另外新版」「兩間實驗」是沒講完）。"""
    c = cur.lstrip()[:1]
    if c.isascii():
        return c.isalpha() and c.isupper()
    return bool(prev.rstrip()[-1:]) and prev.rstrip()[-1:] in SoftBuffer.CLAUSE


def _cont_break(src_rows, tgt_rows, gap=CONT_GAP):
    """V1.29 ⑥：brk[j]＝第 j 行譯文跟上一行隔了超過 gap 秒、中間開始了新的原文行，而且它看起來是新的一句（→ 不當續行）。"""
    import bisect
    s = [r[0] for r in src_rows]
    t = [r[0] for r in tgt_rows]
    return [False] + [t[j] - t[j - 1] > gap and bisect.bisect_right(s, t[j - 1]) < bisect.bisect_right(s, t[j])
                      and _looks_new(tgt_rows[j - 1][1], tgt_rows[j][1]) for j in range(1, len(t))]


def _lead(tgt_rows, cap=LEAD_CAP, frac=LEAD_FRAC, brk=None):
    """每一行譯文可以比它的原文早幾秒開始（因果閘的容忍值），逐行算。

    🔴 為什麼用「這一行時長的一個比例」而不是一個固定門檻——把原始小段流印出來讀就看得到兩種長得一樣、
       但該配給不同原文的情形（r1 38～44 秒 vs r2 64～70 秒，起點都比下一行原文早 0.8 秒）：
       · 真的屬於下一行原文：模型先漏出一兩個字（40.15 送出 ' No'），0.78 秒後原文小段才到
         （40.93 '沒問題,'），這一行剩下的 3 秒內容全部在翻下一行原文 → 原文的起點只吃掉這一行的開頭一小截。
       · 只是上一句的尾巴（'Yes.'、'Thank you.'、'教務担当に。'）：下一行原文開始時這一行已經講完了
         → 原文的起點落在這一行很後面。所以判準是「原文起點落在這一行的前 frac 以內」，
       等於容忍值＝min(cap, 這一行時長 × frac)，不必另外訂一個長度門檻。門檻怎麼取見 LEAD_FRAC。
    🔴 再加一道條件：只有「上一行譯文收完了一個句子」才給容忍值。續行（上一行沒有句尾標點）是文法上的
       尾巴，絕對不可以往後跳——19 組裡有 6 行屬於這種，放行就會錯（例如 r9 的
       「の研究支援計画の説明を…」是前一句的下半，r6 的「計劃，在提案階段…」是前一句的下半）。
    """
    m = len(tgt_rows)
    out = []
    for j in range(m):
        if j and not tgt_rows[j - 1][1].rstrip().endswith(tuple(SENT_END)) and not (brk and brk[j]):
            out.append(0.0)                       # 續行：不給容忍值（V1.29 ⑥：隔很久又有新原文的不算續行）
            continue
        part = (tgt_rows[j + 1][0] - tgt_rows[j][0]) * frac if j + 1 < m else cap
        out.append(min(cap, part) if part > 0.0 else 0.0)
    return out


def _pair_plan(src_rows, tgt_rows, lead=None, empty=None, cap=None, cont=None, longer=None):
    """回傳 owner[j]：第 j 行譯文屬於第幾行原文（-1＝在第一行原文之前，沒有原文可配）。

    單調 DP：狀態只有「處理到第 i 行原文、已經用掉前 j 行譯文」，所以配對天生不交錯，
    而且每一行原文、每一行譯文都恰好被用掉一次。代價見上面的 ①～④。
    """
    lead = LEAD_CAP if lead is None else lead
    empty = EMPTY_PEN if empty is None else empty
    longer = EMPTY_LONG if longer is None else longer
    cap = OVER_CAP if cap is None else cap
    cont = CONT_PEN if cont is None else cont
    n, m = len(src_rows), len(tgt_rows)
    if m == 0:
        return []
    if n == 0:
        return [-1] * m
    s = [r[0] for r in src_rows]
    t = [r[0] for r in tgt_rows]
    brk = _cont_break(src_rows, tgt_rows)     # V1.29 ⑥：隔很久、中間又有新原文的，不當上一句的續行
    ld = _lead(tgt_rows, cap=lead, brk=brk)   # 每一行譯文自己的因果容忍值（多半是 0）
    tl = [t[j] + ld[j] for j in range(m)]     # 因果閘用這個比；代價仍用原始的 t，免得容忍值反過來推著它走
    # 上一行譯文結尾是子句標點＝SoftBuffer 刻意切在子句邊界，這一行還是同一句 → 換原文要付 cont
    clause = tuple(SoftBuffer.CLAUSE)
    ct = [0.0] + [cont if tgt_rows[j - 1][1].rstrip().endswith(clause) and not brk[j] else 0.0
                  for j in range(1, m)]
    # 每一行原文「沒有譯文」的代價：長句的代價高（滿一行就吃滿）
    emp = [empty + longer * min(1.0, len(r[1]) / SRC_MAX_CHARS) for r in src_rows]
    INF = float("inf")

    j0 = 0                                   # 第一行原文之前的譯文只能落單
    while j0 < m and tl[j0] < s[0]:
        j0 += 1
    A = [INF] * (m + 1)                      # 存的是扣掉「前 i 行原文的落空代價總和」之後的相對值（見 shift）
    for j in range(j0 + 1):
        A[j] = j * ORPHAN_PEN
    shift = 0.0
    choice = []                              # choice[i][j]＝第 i 行原文吃掉譯文 [start, j)
    lo = hi = 0
    for i in range(n):
        nxt = s[i + 1] if i + 1 < n else INF
        # 🔴 帶的左界放寬 lead（tl 因為逐行容忍值不同，不保證單調，不能拿它走指標）；真正的因果閘在迴圈裡逐行判
        while lo < m and t[lo] < s[i] - lead:
            lo += 1
        while hi < m and t[hi] <= nxt + cap:             # 帶的右界（往回配的上限；也只會往右）
            hi += 1
        ch = {}
        e = emp[i]
        base = [A[j] + shift for j in range(lo, hi + 1)]  # 先照相，迴圈裡才不會讀到剛寫進去的值
        bval, bstart = INF, -1
        for j in range(lo, hi):
            if tl[j] < s[i]:                 # 因果：這一行譯文比第 i 行原文還早，不可能是它的
                bval, bstart = INF, -1
                continue
            over = t[j] - nxt
            over = over if over > 0.0 else 0.0
            start = base[j - lo] + over + ct[j]          # 這一行是第 i 行原文的第一行譯文
            ext = bval + over                            # 接在同一行原文的譯文後面
            # 🔴 平手時偏向 ext（這一群從更前面開始）＝把譯文交給「時間上更靠近它的那一行原文」。
            #    容忍值放行之後，「尾巴留在上一句」與「整句交給下一句」的代價常常剛好相等，用 < 才不會
            #    讓上一句白白多拿一行（r1／r2 的「No problem, I'll send it…」就是這樣被留在上一句的）。
            if start < ext:
                bval, bstart = start, j
            else:
                bval = ext
            if bval < base[j + 1 - lo] + e:
                A[j + 1] = bval - (shift + e)
                ch[j + 1] = bstart
        shift += e
        choice.append(ch)

    owner = [-1] * m                         # 回溯
    j = m
    for i in range(n - 1, -1, -1):
        st = choice[i].get(j)
        if st is None:
            continue
        for k in range(st, j):
            owner[k] = i
        j = st
    return owner


def pair_rows(src_rows, tgt_rows):
    """[(秒, 原文行)], [(秒, 譯文行)] → [(秒, 原文, 譯文)]，依配對後的順序；沒配到的那一邊留空字串。

    每一行原文、每一行譯文都恰好出現一次，兩邊的先後順序都不變，配對不交錯。
    一行原文掛到多行譯文時，第一行譯文跟原文同一列，其餘每行自己一列（只有譯文、時間用譯文的）。

    做不到的（已知限制，2026-09-15 第三輪實測過，不是估計）：這裡只有「行的起點時間」與「行尾標點」
    兩種線索，完全不看內容。19 組真實錄音、1,155 行有基準的譯文裡目前還有 5 行掛錯（1,150 對＝99.57%）：
      · r5_sapi_ja 譯#21、r9_sapizh_ja 譯#16、h4_holdoutEN_zhTW 譯#20 ——都是「續行」（上一行譯文
        沒有句尾標點），依 _lead 的規則一律 0 容忍值，可是它們該歸的那一行原文比它們晚 0.63～1.86 秒
        才開始，於是被因果閘擋回上一行原文。
        🔴 續行那條規則在現行的 LEAD_FRAC=0.34 下實際只擋住 2 列、淨賺 1 行（整條拿掉是 1150→1149）；
        「救回 6 行」是 LEAD_FRAC 還是 0.5 時的舊數字，這次把門檻降下來就過期了。
        🔴 而且上面這 3 行**不是**續行規則的代價：把規則整條拿掉，這 3 行一行都不會好——
        真正卡住前兩行的是 LEAD_CAP=1.5（它們分別需要提前 1.86 秒與 1.69 秒），
        第三行則是因果放行之後仍被 DP 代價留在原處（2026-09-15 第四輪複查逐行實測）。
      · r5_sapi_ja 譯#47 ——相反方向：容忍值放行之後跳到了下一行原文（S#50），但它其實是 S#49 的尾巴。
      · r7_long10_ja 譯#7 ——兩邊都不違反因果，純粹是 DP 的代價分不出高下。
    要再往下修得靠內容（譯文與原文的長度比、實詞對應），不是調這裡的幾個秒數就能解決：實測
    LEAD_FRAC 0.33／0.34／0.35 三個值的結果一字不差，往外挪到 0.32 或 0.36 就變回 6 行錯。
    """
    owner = _pair_plan(src_rows, tgt_rows)
    mine = [[] for _ in range(len(src_rows))]
    out = []
    for j, i in enumerate(owner):
        if i < 0:
            out.append((tgt_rows[j][0], "", tgt_rows[j][1]))   # 第一行原文之前的譯文
        else:
            mine[i].append(j)
    for i, (ts, s) in enumerate(src_rows):
        js = mine[i]
        out.append((ts, s, tgt_rows[js[0]][1] if js else ""))
        for j in js[1:]:
            out.append((tgt_rows[j][0], "", tgt_rows[j][1]))
    return out


class Bilingual:
    """原文與譯文各自到達、時間不同步，所以分別記錄，最後依時間配對（見 pair_rows）。"""

    def __init__(self, stem, target="zh-TW", source=""):
        self.stem = stem
        self.target = target
        self.source = source
        self.label = tgt_label(target)
        self.t0 = time.time()
        self.src = []   # (秒, 原文)
        self.tgt = []   # (秒, 譯文)
        self.live = open(stem + ".txt", "w", encoding="utf-8", buffering=1)
        self.live.write(f"# Bilingual captions {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        + (f"# {source}\n" if source else "") + "\n")
        self.sb = Buffer(self._emit_src, max_chars=SRC_MAX_CHARS)
        # 英文譯文切在句子／子句邊界（SoftBuffer）；其他語言照舊 45 字
        self.tb = (SoftBuffer(self._emit_tgt) if _lang_base(target) == "en"
                   else Buffer(self._emit_tgt, max_chars=45))

    # 外部只呼叫這兩個；由 Buffer 決定何時成句
    def add_src(self, text):
        self.sb.add(text, time.time() - self.t0)

    def add_tgt(self, text):
        self.tb.add(text, time.time() - self.t0)

    def tick(self):
        self.sb.tick(); self.tb.tick()

    def flush_all(self):
        self.sb.flush(); self.tb.flush()

    def _emit_src(self, t, text):
        note_caption()              # 收音狀態只在「一陣子沒有新字幕」時才印（見 _live.start_level_watch）
        self.src.append((t, text))
        self.live.write(f"[{self._ts(t)}] Source  {text}\n")
        print(f"{SRC_C}[{self._ts(t)}] {text}{RESET}")

    def _emit_tgt(self, t, text):
        if is_zh_target(self.target):
            text = to_tw(text)      # 大陸慣用語 → 台灣用語（只有中文譯文才換）
        self.tgt.append((t, text))
        self.live.write(f"[{self._ts(t)}] {self.label}  {text}\n\n")
        print(f"{TGT_C}          {text}{RESET}\n")

    @staticmethod
    def _ts(t):
        return f"{int(t//60):02d}:{int(t%60):02d}"

    @staticmethod
    def _srt_ts(t):
        h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    def save(self, want_srt=False):
        try:
            self.live.close()
        except Exception:
            pass
        pairs = pair_rows(self.src, self.tgt)          # 配對後的順序（給 .md）
        by_time = sorted(pairs, key=lambda x: x[0])    # .srt 是字幕軌，照時間排

        md = ["# Bilingual captions", "",
              f"- Created: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        if self.source:
            md.append(f"- {self.source}")
        md += [f"- Length: about {int((time.time()-self.t0)//60)} minutes", "", "---", ""]
        for t, s, g in pairs:
            md.append(f"**[{self._ts(t)}]**")
            md.append("")
            if s:
                md.append(f"> {s}")
                md.append("")
            if g:
                md.append(g)
                md.append("")
        srt = []
        for i, (t, s, g) in enumerate(by_time, 1):
            end = by_time[i][0] if i < len(by_time) else t + 5
            srt += [str(i), f"{self._srt_ts(t)} --> {self._srt_ts(end)}"]
            srt += [x for x in (s, g) if x]
            srt.append("")
        open(self.stem + ".md", "w", encoding="utf-8").write("\n".join(md))
        # 預設不產生 .srt（字幕軌，單獨點開只會跳出空的播放器）
        if want_srt:
            open(self.stem + ".srt", "w", encoding="utf-8").write("\n".join(srt))
        return len(pairs)


async def run(args):
    import _apikey
    key = _apikey.for_script()         # 環境變數沒有就讀記住的那一組（2026-09-20 N6-3），都沒有就中文說明
    # 🔴 空字串也要擋（2026-09-20 筆電 ⚠-4）：變數存在但被清空時，拿空金鑰去連網
    #    只會得到「金鑰可能打錯」這種誤導訊息。見 _apikey.for_script 的說明。
    if not key:
        return 2
    client = genai.Client(api_key=key)
    # 🔴 「聽中文時原文偶爾整段簡體」這裡刻意不加 language_codes：e7 實測（2026-09-15，29 條連線）
    #    這個模型的輸入轉錄給 cmn-Hant-TW／zh-TW、甚至 system_instruction 要求，都改不了原文字體
    #    （連反過來要求簡體也拿不到半個簡體字），加了只是安慰劑、會讓人以為修好了。
    #    live_bilingual_hq.py 用的是另一個模型（transcribe-live），那邊的語言碼是真的有效，不要類推。
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        translation_config=types.TranslationConfig(
            target_language_code=args.target, echo_target_language=False),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # 🔴 只在譯文是「臺灣繁體」時給臺灣用語指示（is_tw_style_target，不是 is_zh_target）：
        #    --target zh／zh-CN 是簡體，塞臺灣用語指示會跟目標互相矛盾。None 時 SDK 不會送這個欄位。
        system_instruction=TW_STYLE_INSTRUCTION if is_tw_style_target(args.target) else None,
    )

    # 🔴 SIGINT 的處理函式要在 src.start() 之前就登記好，等來源開好的期間 Ctrl+C 才有用
    #    （同 live_caption.py；2026-09-15 第二輪複查 R2-4）。
    # 🔴 Ctrl+C 時不要把英文 traceback 倒給使用者看（見 _live.quiet_async_noise）
    quiet_async_noise()
    stop_all = asyncio.Event()
    # 🔴 第一下 Ctrl+C 之後還要收尾幾秒（等最後一句、關連線、存檔、切回喇叭），畫面若毫無回應，
    #    使用者會以為當掉、一直按（2026-09-19 使用者回報）。所以每按一次都回一句話。
    #    不可以在訊號處理函式裡直接 print：剛好撞上字幕正在輸出時會 reentrant call 出錯，
    #    交給事件迴圈代印；迴圈已經結束時（收尾最後階段）就安靜略過。
    loop, presses, started = asyncio.get_running_loop(), [0], [False]
    back = ", switching back to the original speakers" if getattr(args, "route_original", None) else ""

    def _notice(n):
        if not started[0]:
            return            # 還沒開始錄音：下面的取消分支自己會講「已取消」，這裡講收尾會前後矛盾
        if n == 1:
            print(f"\n{DIM}  Ctrl+C received, wrapping up (saving files{back}), about 3–5 seconds…{RESET}")
        else:
            # 🔴 要講代價：按 X 會跳過整理 .md（收尾就在做這件事），而且選單在同一個視窗、會一起關掉
            print(f"{DIM}  Still wrapping up, please wait a few more seconds. You can also end it now with the X in the top-right corner of the window, but the tidied-up .md won't be produced (the word-for-word .txt is still there), and the menu will close too{'; the sound output will still switch back automatically' if back else ''}.{RESET}")

    def _on_sigint(*_):
        presses[0] += 1
        stop_all.set()
        try:
            loop.call_soon_threadsafe(_notice, presses[0])
        except Exception:
            pass

    signal.signal(signal.SIGINT, _on_sigint)

    # ── 翻譯語音播放（--speak）的事前檢查，一定要在開始錄音之前 ──────────────
    # 🔴 回授迴圈：--source system／both 是用 WASAPI loopback 錄「**預設播放裝置**正在播
    #    的東西」。翻譯語音如果也送到同一顆裝置，就會馬上被錄回去、再翻一次、再播一次，
    #    幾秒內就變成翻譯在翻自己（而且每一圈都在燒錢）。所以這個組合一定要指定另一顆
    #    裝置（通常是耳機）。戴不戴耳機不影響這個判斷——loopback 錄的是「裝置正在播什麼」，
    #    耳機本身就是那顆裝置時照樣會被錄回去。
    spk_dev = None
    if args.speak:
        try:
            spk_dev, spk_name = resolve_output_device(args.speak_device)
        except Exception as e:
            print(f"\n{YEL}  ✗ {e}{RESET}")
            _print_devices()
            return 2
        spk_show = display_name(spk_dev, spk_name)
        if args.source in ("system", "both") and is_default_like(spk_name, idx=spk_dev):   # V1.31：比端點 ID
            print(f"\n{YEL}  ✗ The interpreter voice can't be played on \"{spk_show}\".{RESET}")
            print(f"{DIM}     This is the device being recorded right now, so the translation would be recorded straight back in, creating an endless loop of the translation translating itself.{RESET}")
            print(f"{DIM}     Please use --speak-device to choose another device (e.g. plug in headphones, then choose them).{RESET}")
            _print_devices()
            return 2
        if args.source == "mic":
            print(f"{YEL}  ⚠ Please wear headphones. If the interpreter voice plays through the speakers, the microphone picks it up again,\n     and the model keeps translating its own voice over and over without stopping; you are charged the whole time.{RESET}")   # V1.32：補後果
        # 🔴 這裡就要把裝置開開看。開不起來的裝置（WDM-KS 不支援阻塞寫入、WASAPI 不吃
        #    24kHz）以前要等到會議開始、連線都連上了才會吐錯，而那時使用者已經在開會了
        #    ——而且語音正是這個模式的全部意義，只留字幕等於這趟白跑。
        ok, err = probe_output_device(spk_dev)
        if not ok:
            print(f"\n{YEL}  ✗ The device \"{spk_show}\" can't play the interpreter voice.{RESET}")
            print(f"{DIM}     The system reported: {err}{RESET}")
            print(f"{DIM}     (Common causes: WDM-KS interfaces don't support this way of playing sound; WASAPI interfaces don't accept 24kHz. Just choose a different device.){RESET}")
            _print_devices(usable_only=True)
            return 2

    src = AudioSource(args.source, args.file)
    src.mic_raw, src.mic_device = args.mic_raw, args.mic_device
    src.follow_default = not args.speak
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
        # 🔴 沒有任何聲音來源就不要連線、不要建檔，也不要說 ✅（同 live_caption.py）。
        src.close()
        print(f"\n{YEL}  ✗ No usable audio source: recording did not start and no files were created.{RESET}")
        return 2
    src.live = True
    started[0] = True

    stem = args.out or time.strftime("Bilingual_%Y%m%d_%H%M")
    bi = Bilingual(stem, args.target, source_line(args.source, src))
    if args.source != "file":
        # P1：開場印一次收音狀態，之後一陣子沒字幕才再印。
        # V1.35（待辦 7）：只有功能 3「快」（沒有口譯語音）補一句改用「準」。🔴 2026-10-03 X3／X3b：德語廣播走「快」，
        #    Google 一直有回翻譯語音、字幕文字 150 秒只回 1 則（音量 −50／−44 dB 都一樣）；同一段走「準」、法語走「快」都正常。
        #    功能 6 有口譯語音可聽，不叫人換。
        start_level_watch(src, loud_extra=None if args.speak else
                          "In this mode the captions and the translated voice come from the same model, and for some languages or content it gives only the voice and no text; try Accurate mode instead (its captions come from a separate, dedicated recognition model).")

    # 播放裝置到這裡才真的開啟：聲音來源沒開成功就直接收工，不必先佔住喇叭。
    spk = None
    if args.speak:
        spk = Speaker(device=spk_dev)
        if spk.ok:
            print(f"{GRN}  🔊 The interpreter voice will play from \"{spk_show}\"{RESET}")
        else:
            spk = None            # 開不起來就純字幕，不要讓整場停掉

    print(f"{BOLD}▸ Connecting (target language: {args.target})…{RESET}")
    lab = tgt_label(args.target)
    legend = f"{lab} translation" if lab != "Translation" else "Translation"
    print(f"{DIM}(grey = source  blue = {legend})  Ctrl+C to stop{RESET}")
    print(f"{DIM}  {font_hint()}{RESET}\n")

    # 🔴 2026-09-22（P5）：累加跨連線的靜音壓制總量，收尾時報給使用者
    #    （SilenceGate.held_seconds 原本定義了卻無人使用）。
    held_total = [0.0]
    rc = Reconnect()
    # V1.26 A2：上一條連線停住／斷掉時還沒被處理的聲音，下一條連線一開始先補送（見 _live.LagWatch）
    resend = []
    eof_redialed = [False]       # 影音檔讀完時，最多只為了補送換線一次（避免一直換）
    stalls = [0, 0.0]            # 連續幾次「換線後撐不到 STALL_RESET 秒又停住」、這一串從幾點開始
    # 🔴 這支（翻譯模型）不接 V1.26 B1 放大：實測放大沒有改善（見 _live.Leveler 上面的說明）。

    def redial_notice(behind, secs):
        print(f"\n{YEL}  ⚠ Google is about {behind:.0f} seconds behind with no progress: switching to a new connection and re-sending the last {secs:.0f} seconds of audio (captions will appear a little later, and a sentence or two may be repeated){RESET}")

    while not stop_all.is_set():
        seg0 = time.time()
        lagw = None
        redial = [False]
        try:
            # 🔴 握手走 open_live（有時限、Ctrl+C 叫得動）——見 _live.open_live 的說明。
            async with open_live(
                    client.aio.live.connect(model=MODEL, config=cfg),
                    stop_all) as session:
                rc.ok()          # 連上了，重置失敗計數
                lagw = LagWatch()

                # 🔴 2026-09-22（P5）：閘門移到 feed() 外面（仍是每條連線一個，行為不變）。
                #    feed() 會被 cancel（伺服器斷線時正是如此），統計寫在它裡面會被跳過。
                silence_gate = SilenceGate(enabled=args.source != "file",
                                           floor=gate_floor(args.source))   # V1.23 B：只收電腦聲音時下限放寬

                # V1.26 A2：換線補送之後的「追趕」：[正在追趕, 下一塊最早幾點可以送]（見 _live.RESEND_RATE）
                # 🔴 沒有補送、但握手期間佇列積了聲音（握手慢、連續握手失敗、影音檔先讀好的）也要追趕：
                #    一口氣灌會讓 Google 丟掉後面的即時聲音，停住的判斷也會被灌進去的秒數誤觸（V1.26 審查 #2）
                pace = [bool(resend) or src.q.qsize() > 3, 0.0]

                def need_redial():
                    """V1.26 A2：落後／停住超過 REDIAL_LAG 秒就換線，把還沒被處理的那段排進補送。
                    追趕期間送得比收得快是刻意的，只看「完全停住」，不看落後（不然會一直換線）。"""
                    b = lagw.since_msg if pace[0] else lagw.behind()
                    if b < REDIAL_LAG:
                        return False
                    resend[:] = lagw.backlog(b + RESEND_PAD)
                    redial[0] = True
                    redial_notice(b, len(resend) * CHUNK_MS / 1000)
                    return True

                async def send(blk, count=True):
                    if pace[0]:                  # 追趕中：照 RESEND_RATE 倍速送，不要一口氣灌
                        wait = pace[1] - time.time()
                        if wait > 0:
                            await asyncio.sleep(wait)
                        pace[1] = max(pace[1], time.time()) + CHUNK_MS / 1000 / RESEND_RATE
                    await session.send_realtime_input(audio=types.Blob(
                        data=blk, mime_type=f"audio/pcm;rate={TARGET_SR}"))
                    lagw.sent(blk, count=count)

                async def feed():
                    # 8 分鐘到了之後等講者停頓再換線（2026-09-20 N5，見 _live.RotateWhenQuiet）
                    # V1.25：麥克風、兩者都要漸進；看「實際」開起來的收音方式（完整收音開不起來會退回一般收音）
                    rot = RotateWhenQuiet(seg0, SESSION_SOFT_LIMIT, idle=args.source != "file",
                                          **rotate_opts(args.source, getattr(src, "mic_raw_active", args.mic_raw)))
                    # V1.26 A2：上一條連線沒處理完的聲音先補送（照 RESEND_RATE 倍速）。只記進帳本、不算進這條的落後
                    #    （伺服器要一點時間消化，算進去會馬上又判定落後、一直換線）。
                    # 🔴 送出一塊才從 resend 拿掉一塊：補送到一半這條也斷了時，還沒送的留在 resend、
                    #    已送出沒回應的由下面 except 接回前面（V1.26 審查 #1：原本整批先拿走，斷了就整段不見）。
                    while resend and not stop_all.is_set():   # 補送途中按 Ctrl+C：不要把 20 秒的補送送完才收尾
                        await send(resend[0], count=False)
                        resend.pop(0)
                    # 🔴 2026-09-21：持續安靜就不要再餵模型（見 _live.SilenceGate）。
                    #    使用者回報功能 6 用麥克風時，現場聲音結束後一直跳針、停不下來 ——
                    #    原文欄自己就在重複（那是 input_transcription 原封不動印出來的），
                    #    是模型收到靜音／底噪之後退化成填充詞迴圈。不餵它就不會有這件事，
                    #    而且功能 6 是最貴的一支（≈US$2.2/小時），不送就不算錢。
                    #    檔案來源不啟用：檔案讀完就 eof，沒有「一直錄空氣」的問題。
                    #    （閘門本身建在上一層，見該處說明）
                    while not stop_all.is_set():
                        if pace[0] and src.q.qsize() <= 3:   # V1.26 A2：佇列追平了，恢復即時；落後重新起算
                            pace[0] = False
                            lagw.rebase()
                        # 🔴 不用 asyncio.to_thread(src.q.get, True, 0.3)：伺服器先結束連線（go_away、1008）時
                        #    feed 會被取消，但丟進執行緒的 get 還在等，下一塊聲音（100ms）會被它拿走、丟掉
                        #    （2026-09-19 審查重現：每次換線少 1 塊）。跟準確模式一樣改成輪詢。
                        try:
                            pcm = src.q.get_nowait()
                        except queue.Empty:
                            if src.eof:
                                # V1.26 A3：影音檔讀完了。Google 還落後就多等（最多落後的秒數＋6 秒）；
                                #    還是等不到就換線補送一次（檔案不必趕即時），不要直接收工讓最後那段消失。
                                t_end = time.time() + 6 + min(lagw.behind(), RESEND_MAX)
                                while time.time() < t_end and not stop_all.is_set() and lagw.behind() > 2:
                                    await asyncio.sleep(0.5)
                                if lagw.behind() > 2 and not eof_redialed[0] and not stop_all.is_set():
                                    eof_redialed[0] = True
                                    b = lagw.behind()
                                    resend[:] = lagw.backlog(b + RESEND_PAD)
                                    redial[0] = True
                                    redial_notice(b, len(resend) * CHUNK_MS / 1000)
                                    break
                                # 等最後幾句翻完；剛補送過、伺服器還沒回完的話多等那一段。
                                # 🔴 每 0.5 秒看一次 Ctrl+C（V1.26 審查 #5：原本一口氣睡，最久 36 秒叫不動）
                                t_end = time.time() + 6 + min(max(0.0, lagw.resent_s - lagw.got_s), RESEND_MAX)
                                while time.time() < t_end and not stop_all.is_set():
                                    await asyncio.sleep(0.5)
                                stop_all.set()
                            elif rot.due():      # 佇列空了才問：有積壓時先送完（見 RotateWhenQuiet）
                                break
                            else:
                                await asyncio.sleep(0.02)
                            continue
                        for blk in silence_gate.feed(pcm):
                            await send(blk)
                        # 🔴 rot.saw() 要在 gate 之外、每一塊都呼叫：換線要等停頓是靠它累積
                        #    音量高點與安靜塊數，漏掉會讓 8 分鐘換線的判斷失準。
                        rot.saw(pcm)
                        if rot.due() or need_redial():
                            break

                async def read():
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
                        ip = getattr(sc, "input_transcription", None)
                        if ip and ip.text:
                            bi.add_src(ip.text)
                        op = getattr(sc, "output_transcription", None)
                        if op and op.text:
                            bi.add_tgt(op.text)
                        # 🔴 翻譯語音一直都在回傳（cfg 是 response_modalities=["AUDIO"]），
                        #    只是舊版把它丟掉。要不要播由 --speak 決定，但**費用照收**：
                        #    輸出音訊 token 是伺服器生成當下就算的，不看用戶端有沒有讀。
                        n_audio = 0
                        mt = getattr(sc, "model_turn", None)
                        if mt:
                            for part in (mt.parts or []):
                                if part.inline_data and part.inline_data.data:
                                    n_audio += len(part.inline_data.data)
                                    if spk is not None:
                                        spk.play(part.inline_data.data)
                        # V1.26 A1／A2：有進度（原文、譯文或語音）就記一筆——語音量拿來算落後（不管有沒有要播）
                        if n_audio or (ip and ip.text) or (op and op.text):
                            lagw.got(n_audio)

                async def ticker():
                    # 講者停頓時，把攢著還沒成句的字送出去，不要卡住
                    warned = False
                    while True:
                        await asyncio.sleep(0.5)
                        bi.tick()
                        # V1.26 A1：Google 停住或越來越慢時講一聲（字幕會晚），恢復了再講一聲。
                        #    舊版要等到被 Google 斷線才有一行灰字，而且不會說有內容漏掉。
                        b = lagw.since_msg if pace[0] else lagw.behind()     # 追趕中只看「完全停住」
                        if not warned and b >= STALL_WARN:
                            warned = True
                            print(f"\n{YEL}  ⚠ Google is not responding for the moment (about {b:.0f} seconds), so captions will be a little late; after {REDIAL_LAG:.0f} seconds the program automatically switches to a new connection and re-sends this audio{RESET}")
                        elif warned and b < 3:
                            warned = False
                            print(f"{DIM}  (Google is responding again){RESET}")

                f = asyncio.create_task(feed()); r = asyncio.create_task(read())
                tk = asyncio.create_task(ticker())
                done, pend = await asyncio.wait({f, r}, return_when=asyncio.FIRST_COMPLETED)
                # 輪替時給 read 一點寬限，否則每 8 分鐘會掉最後一句（見 live_caption 註解）
                # V1.26 A2：為了落後而換線時不等——那條連線已經停住了，等也等不到
                if f in done and r in pend and not redial[0]:
                    await asyncio.wait({r}, timeout=ROTATE_GRACE)
                tk.cancel()
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
                rotating = f in done and (time.time() - seg0 >= SESSION_SOFT_LIMIT or redial[0])
                if errs and not rotating:
                    raise errs[0]
            # 停住而換線：連續 3 次起講明字幕是停的，並退避 4→8→15 秒（見 _live.STALL_RESET）
            if redial[0] and not stop_all.is_set():
                stalls[0] = stalls[0] + 1 if time.time() - seg0 < STALL_RESET else 1
                if stalls[0] == 1:
                    stalls[1] = time.time()
                if stalls[0] >= 3:
                    delay = min(2 ** (stalls[0] - 2) * 2, rc.CAP)
                    print(f"\n{YEL}  ⚠ Google has stalled without responding {stalls[0]} times in a row (about {time.time() - stalls[1]:.0f} seconds); the captions are currently stopped{RESET}")
                    print(f"{DIM}      Still retrying automatically; connecting again in {delay} seconds. If it doesn't recover, check the network, or press Ctrl+C to stop (everything recognised so far has been saved).{RESET}")
                    t_end = time.time() + delay
                    while time.time() < t_end and not stop_all.is_set():
                        await asyncio.sleep(0.5)
        except Exception as e:
            if stop_all.is_set():
                break
            # 這個模型偶爾會回 1007，重連就好（實測過）；
            # 但連續失敗就不是「重連就好」了，Reconnect 會升級成明顯警告。
            # V1.26 A2：斷線前還沒被處理的聲音排進補送（剛補送過、伺服器還沒消化完的也算，見 LagWatch.unacked）；
            #    斷線訊息改講「重新連上後會補送」。握手就失敗（lagw 是 None）時保留原本那份。
            #    補送到一半就斷：已送出、沒回應的那段接在還沒送的前面（不管多短，接不起來就是漏一截）。
            if lagw is not None:
                b = lagw.unacked()
                if resend:
                    resend[:] = lagw.backlog(b + RESEND_PAD) + resend
                elif b >= LOST_REPORT_MIN:
                    resend[:] = lagw.backlog(b + RESEND_PAD)
            rc.resend = len(resend) * CHUNK_MS / 1000
            # 🔴 斷線時把還沒播的語音丟掉。重連要等好幾秒，殘留的半句在重連後才播出來，
            #    會跟新的譯文疊在一起（而且對不上畫面）。8 分鐘正常輪替不清——那是連續的。
            if spk is not None:
                spk.flush()
            await asyncio.sleep(rc.failed(e))

    src.close()
    if spk is not None:
        spk.close()
        # 🔴 這個數字是「寫進播放裝置的量」，不是「耳朵真的聽到的量」：寫入成功不代表有聲音
        #    （N1 就是 DirectSound 寫得進去卻完全無聲）。所以只能說「送出」，不能說「播出」
        #    （2026-09-20 使用者指示改的）。
        # 🔴 要寫出是哪一顆裝置：N1 的病根就是「送到了一顆聽不見的裝置」，
        #    開頭那行「將從「X」播出」早就捲走了，結尾不講等於把最該查的線索藏起來（複查指出）。
        # 🔴 2026-09-20 筆電全流程檢測（⚠-9）：這個數字約等於整場連線時長（實測 369 秒裡 258 秒是靜默，
        #    Live API 照樣持續送流），不是「講了幾分鐘中文」。要講明含靜音，不然使用者會以為講很久。
        print(f"\n{DIM}(This session sent about {spk.played_seconds:.0f} seconds of audio to \"{spk_show}\" in total, including silence when nobody was speaking; that is how much went into the device, which doesn't necessarily mean it could be heard){RESET}")
        if spk.outages:
            # V1.28（使用者核准）：中途斷過（例如耳麥被拔插）時，略過的主要是斷掉那幾秒，不是「來不及播」
            print(f"\n{DIM}(The interpreter voice cut out {spk.outages} time(s) along the way (the playback device changed, e.g. the headset was unplugged and plugged back in), {'and was reconnected automatically each time' if spk.recovered else 'and was not reconnected the last time'}; about {spk.dropped_seconds:.0f} seconds of interpretation were not played, but the captions are complete){RESET}")
        elif spk.dropped_seconds >= 1:
            print(f"\n{DIM}(The voice couldn't keep up, so about {spk.dropped_seconds:.0f} seconds were skipped; the captions are complete){RESET}")
    bi.flush_all()
    n = bi.save(want_srt=args.srt)
    print(f"\n\n{'✅' if n else '⚠'} Total: {n} bilingual caption pairs" + ("" if n else " (nothing was recognised during the whole session; please check that the audio source actually had sound)"))
    if held_total[0] >= 1:
        # P5：讓使用者看得到靜音閘門真的有在省。1 秒以下不印，避免短測試洗版。
        print(f"{DIM}   Skipped {held_total[0]:.0f} seconds of unnecessary uploading during quiet periods{RESET}")
    print(f"   {stem}.md\n   {stem}.txt (backup, saved in real time)")
    if args.srt:
        print(f"   {stem}.srt")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["system", "mic", "both", "file"], default="system",
                    help="system=computer audio (what the PC is playing) / mic=microphone / both=both mixed together (in person + online) / file=an existing audio/video file")
    ap.add_argument("--file", default=None, help="Source file to use with --source file")
    # 🔴 實測：這個模型只吃 zh-TW（給 cmn-Hant-TW 會 1007 斷線，跟轉錄模型的語言碼不通用）
    #    zh-TW 出繁體且是台灣用語（「大家早安」而非「大家早上好」）；zh 出簡體。
    ap.add_argument("--target", default="zh-TW",
                    help="Target language code for the translation. Chinese: zh-TW (Traditional, Taiwan); Japanese: ja, Korean: ko, Spanish: es")
    ap.add_argument("--out", default=None)
    ap.add_argument("--srt", action="store_true",
                    help="also create an .srt caption track (only needed if you want to add it to a video)")
    ap.add_argument("--mic-raw", action="store_true",
                    help="use full capture for the microphone (bypasses Windows noise suppression; loudspeakers in the room are picked up too)")
    ap.add_argument("--mic-device", default=None,
                    help="which microphone to use (the name must match what Windows shows); leave it out to follow the Windows default, which switches automatically when a headset is plugged in or out")
    # 🔴 --speak 不會多花錢：cfg 本來就是 response_modalities=["AUDIO"]，翻譯語音一直都在
    #    回傳，只是舊版讀完文字就丟掉。輸出音訊 token 在伺服器生成當下就計費了。
    ap.add_argument("--speak", action="store_true",
                    help="Play the interpreter voice aloud (live interpreter mode). Captions are shown as usual.")
    ap.add_argument("--speak-device", default=None,
                    help="Which device plays the interpreter voice (a number or part of the name). With --source system/both you must choose a device that is not the system default, otherwise the program will record its own translation.")
    ap.add_argument("--route-original", default=None,
                    help="Which route the original audio takes (audio endpoint ID). Before starting, the system default playback device is switched to it, and it is switched back automatically at the end. Together with --speak-device set to the device you \"can hear\", the user hears only the interpretation, not the original audio.")
    ap.add_argument("--list-devices", action="store_true",
                    help="List the usable playback devices, then exit")
    args = ap.parse_args()
    if args.list_devices:
        _print_devices()
        return

    # ── 兩條路線：先把系統預設輸出切到「原音路線」──────────────────────────
    # 🔴 一定要在 run() 之前切：側錄用的 WASAPI loopback 抓的是「當下的系統預設播放裝置」，
    #    切太晚就會錄到錯的那一顆。--speak 的防回授檢查（is_default_like）也要在切完之後
    #    才判斷，否則會拿舊的預設去比。
    route = None
    if args.route_original:
        try:
            import _audioroute as _ar
        except Exception as e:                       # noqa: BLE001
            print(f"\n{YEL}  ✗ Could not load the audio routing module: {e}{RESET}")
            sys.exit(2)
        note = _ar.recover_if_needed()
        if note:
            print(f"{DIM}  {note}{RESET}")
        route = _ar
        # 🔴 按視窗右上角的 X 時 atexit 不會跑，這裡要單獨掛一次，否則使用者的聲音
        #    輸出會留在「聽不到」的那一顆，然後以為電腦壞了（同 _quiet_remove 的處理）。
        #    要在切換「之前」就掛好；而且不可以重啟聲音元件（refresh=False，見 _audioroute.restore）。
        on_console_close(lambda: _ar.restore(refresh=False))

    code = 0
    try:
        # 切換也放進 try：切到一半按 Ctrl+C，finally 照樣會還原（沒切成功時 restore 什麼都不做）
        err = route.switch_to(args.route_original) if route is not None else None
        if err:
            print(f"\n{YEL}  ✗ Could not automatically switch the sound output to the original-audio route: {err}{RESET}")
            print(f"{DIM}     Please click the speaker icon at the bottom right to switch it over yourself, then run again; otherwise you'll hear the original audio from the speakers.{RESET}")
            code = 2
        else:
            code = asyncio.run(run(args)) or 0
    except KeyboardInterrupt:
        pass
    finally:
        # V1.33：沒預期的錯誤跳出來時，也要先把收音與口譯播放關好（見 _live.close_open），再改回聲音輸出
        close_open()
        if route is not None:
            # refresh=False：行程接著就結束，重啟聲音元件沒有用；萬一播放執行緒卡住沒停，
            # 重啟反而會在它寫到一半時拆掉串流而當掉（見 _audioroute.restore）
            did, back = route.restore(refresh=False)
            if did and back and back.startswith("Restore failed"):
                # 🔴 不可以印成「已改回『還原失敗：…』」（2026-09-19 審查）。狀態檔會留著，下次打開程式再試一次。
                print(f"\n{YEL}  ⚠ Could not switch the sound output back to the original speakers automatically ({back[len('Restore failed: '):]}).{RESET}")
                print(f"{DIM}     Please click the speaker icon at the bottom right and switch it back yourself; the program will also try again the next time it opens. If you set your meeting app's speaker to ①, switch that back too, to the one you normally listen on.{RESET}")
            elif did:
                print(f"{DIM}  Sound output switched back to \"{back}\".{RESET}")
                # 程式改得到 Windows，改不到會議軟體：新版 Teams 照說明指定成①的話，會一直停在聽不到的那顆
                print(f"{DIM}  If you set your meeting app's (Teams/Zoom/Webex) speaker to ①, remember to switch it back yourself to the one you normally listen on.{RESET}")
    sys.exit(code)                 # 沒有聲音來源＝2；選單看離開碼才知道不是成功


if __name__ == "__main__":
    main()
