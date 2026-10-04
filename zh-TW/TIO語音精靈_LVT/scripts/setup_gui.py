# -*- coding: utf-8 -*-
"""
安裝精靈（有視窗、有同意頁、有進度條）。

3_安裝.bat 只負責一件事：確認電腦上真的有可以跑的 Python。確認之後就交棒給這支。
沒有 tkinter 的環境（極少見）會退回文字版 setup.py，功能一樣。

刻意設計：
  - 動手之前先把「會在你電腦上做什麼」整份列出來，按下同意才開始。
  - 每一步都有進度，不是一片黑畫面讓人猜跑到哪。
  - 失敗時把「真正的錯誤訊息」貼出來，不要只說「請看上面」。
"""
import os
import queue
import subprocess
import sys
import threading
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(ROOT, "requirements.txt")
START_BAT = os.path.join(ROOT, "4_開始使用.bat")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _winpath import (desktop_dir, make_shortcut, shortcut_path,   # noqa: E402
                      unblock_files, zone_marked_files)
from _ui import (apply_icon, attach_paste_menu,                 # noqa: E402
                 build_scrollable, fit)
import _apikey                                                  # noqa: E402

DESKTOP = desktop_dir()
SHORTCUT = shortcut_path()

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 「立即開始使用」啟動選單時包的一層小外殼（見 Wizard.launch 的說明）。
# 🔴 不能只是 `python menu.py` 就了事：4_開始使用.bat 那一行尾巴的
#    「|| if not errorlevel 3 pause」是刻意設計的安全網 —— 選單在**載入階段**
#    就出錯（缺檔、檔案壞掉，連 menu.py 的 _entry() 都還沒跑到）時，讓視窗停住
#    給人看見錯誤，而不是一閃就關、同事什麼都沒看到。
#    繞過 .bat 就等於繞過那張網，所以這裡把同一套規則原樣搬過來：
#    離開碼 3 ＝ menu.py 自己已經顯示過錯誤也等過使用者，不要再停第二次。
_LAUNCH_CODE = (
    "import runpy, sys, traceback\n"
    "try:\n"
    "    import ctypes\n"
    "    ctypes.windll.kernel32.SetErrorMode(0)\n"
    # 🔴 解除繼承來的「忽略 Ctrl+C」，否則即時字幕／口譯按 Ctrl+C 停不下來（見 Wizard.launch）
    "    ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)\n"
    # 分頁／視窗標題跟桌面捷徑開的一樣叫 TIO，不要顯示一長串 python.exe 路徑
    "    ctypes.windll.kernel32.SetConsoleTitleW('TIO')\n"
    "    ctypes.windll.kernel32.SetConsoleOutputCP(65001)\n"
    "    ctypes.windll.kernel32.SetConsoleCP(65001)\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
    "    sys.stderr.reconfigure(encoding='utf-8', errors='replace')\n"
    "except Exception:\n"
    "    pass\n"
    "def _hold():\n"
    "    print()\n"
    "    try:\n"
    "        input('按 Enter 關閉…')\n"
    "    except Exception:\n"
    "        pass\n"
    "try:\n"
    "    runpy.run_path(sys.argv[1], run_name='__main__')\n"
    "except SystemExit as e:\n"
    "    if e.code not in (0, 3, None):\n"
    "        _hold()\n"
    "except BaseException:\n"
    "    traceback.print_exc()\n"
    "    _hold()\n"
)

# 🔴 舊版留下來、新版已經沒有的檔名。**只認這份寫死的清單**，
#    絕對不用萬用字元 —— 這是要刪使用者電腦上的檔案，寧可漏掉也不能誤刪。
#
#    為什麼需要這個：解壓縮新版時 Windows 只會覆蓋同名檔，舊檔原封不動留著。
#    2026-09-10 實測升級路徑：同事的資料夾裡會同時出現 3_安裝.bat 和 安裝.bat、
#    4_開始使用.bat 和 start.bat、兩份安裝說明 —— 他不會知道該點哪一個。
LEGACY_FILES = [
    "start.bat",                    # → 4_開始使用.bat
    "安裝.bat",                      # → 3_安裝.bat
    "解除安裝.bat",                   # → 7_解除安裝.bat
    "診斷.bat",                      # → 6_診斷.bat
    "刪不掉時救援.bat",                # → 8_刪不掉時救援.bat
    "給對方的安裝說明.md",              # → 1_安裝說明（先讀這個）.md
    "使用說明.md",                    # → 5_使用說明（功能操作）.md
]
LEGACY_SHORTCUTS = ["Gemini 語音工具", "會議字幕工具",
                    "TIO-會議字幕工具"]   # 歷代舊桌面捷徑名（現在叫「TIO語音精靈」）


def legacy_leftovers():
    """列出這個資料夾裡的舊版殘留。只比對完整檔名，不做任何樣式比對。"""
    out = []
    for name in LEGACY_FILES:
        p = os.path.join(ROOT, name)
        if os.path.isfile(p):
            out.append(p)
    return out


PKG_WHY = {
    "google-genai": "連線 Google Gemini",
    "sounddevice": "錄麥克風",
    "PyAudioWPatch": "錄電腦播出來的聲音",
    "numpy": "處理聲音資料",
    "scipy": "重新取樣（把聲音轉成模型要的格式）",
}


# ─────────────────── 「立即開始使用」的背景小幫手（見 Wizard.launch）───────────────────
_WAIT_SEC = 15              # 最多等安裝視窗關掉多久
_SETTLE_SEC = 1.0           # 安裝視窗的行程都結束後，再給終端機收尾的時間
_STATUS_CONTROL_C_EXIT = 0xC000013A   # 使用者自己按 X 關掉選單，不是啟動失敗


def _console_pids():
    """現在掛在這個主控台上的所有行程（3_安裝.bat 的 cmd、py 啟動器、精靈自己）。"""
    pids = {os.getpid()}
    if sys.platform == "win32":
        try:
            import ctypes
            arr = (ctypes.c_ulong * 64)()
            n = ctypes.windll.kernel32.GetConsoleProcessList(arr, 64)
            pids.update(arr[i] for i in range(min(n, 64)))
        except Exception:
            pass
    return sorted(pids)


def _deferred_launch(pids):
    """背景小幫手（沒有主控台）：等安裝視窗整個關掉才開選單；開不起來就改走檔案總管。"""
    import ctypes
    import time
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    deadline = time.time() + _WAIT_SEC
    for pid in pids:
        h = k32.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
        if h:
            k32.WaitForSingleObject(h, max(0, int((deadline - time.time()) * 1000)))
            k32.CloseHandle(h)
    time.sleep(_SETTLE_SEC)

    # 🔴 一定要先壓住系統的「應用程式無法正確啟動」視窗：不壓的話失敗的行程會卡在
    #    那個視窗上等人按確定，看起來像還活著，下面就判斷不出失敗（實測結束碼 0x103）。
    #    選單的 _LAUNCH_CODE 一開頭就把它設回 0。
    k32.SetErrorMode(0x0001)                                   # SEM_FAILCRITICALERRORS
    menu = os.path.join(ROOT, "scripts", "menu.py")
    try:
        p = subprocess.Popen([sys.executable, "-u", "-c", _LAUNCH_CODE, menu],
                             cwd=ROOT, close_fds=True,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return 0                            # 選單正在等使用者操作＝成功
    except Exception:
        pass
    else:
        code = p.returncode & 0xFFFFFFFF
        if code < 0xC0000000 or code == _STATUS_CONTROL_C_EXIT:
            return 0                        # 有開起來，只是很快就被關掉

    # 最後一招：跟使用者自己雙擊一模一樣，交給檔案總管開 4_開始使用.bat
    k32.SetErrorMode(0)
    time.sleep(2.0)
    try:
        if "," in START_BAT:                # explorer 的命令列把逗號當分隔符號
            os.startfile(START_BAT)
        else:
            subprocess.Popen(["explorer.exe", START_BAT], close_fds=True)
    except Exception:
        ctypes.windll.user32.MessageBoxW(
            None, "選單沒有自動開起來。\n\n請直接點資料夾裡的「4_開始使用.bat」或桌面捷徑。",
            "TIO", 0x40)
    return 0


# ───────────────────────── 主控台視窗的顯示／隱藏 ─────────────────────────
def _console(show):
    """安裝時把黑視窗藏起來；真的爆炸時再叫出來給人看錯誤。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)
    except Exception:
        pass


def read_packages():
    """從 requirements.txt 讀出要裝的套件，回傳 [(原始字串, 顯示名, 用途)]。"""
    out = []
    try:
        with open(REQ, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = line.split(">=")[0].split("==")[0].split("[")[0].strip()
                out.append((line, name, PKG_WHY.get(name, "")))
    except Exception:
        pass
    return out


# ───────────────────────────────── GUI ─────────────────────────────────
import tkinter as tk
from tkinter import ttk, messagebox

BG = "#f7f7f5"
FG = "#1f1f1d"
MUTED = "#6b6b66"
ACCENT = "#c8622a"
OK = "#1a7f4b"
BAD = "#b3261e"
FONT = "Microsoft JhengHei UI"


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TIO — 安裝")
        apply_icon(self)
        self.configure(bg=BG)
        # 🔴 千萬不要改回 resizable(False, False)：螢幕比視窗矮的筆電上，
        #    按鈕會掉到螢幕外面，使用者連取消都按不到。
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.pkgs = read_packages()
        self.q = queue.Queue()
        self.cancelled = threading.Event()
        self.proc = None
        self.results = []
        self.key_var = tk.StringVar()
        self.sc_var = tk.BooleanVar(value=True)
        self.legacy = legacy_leftovers()
        self.lg_var = tk.BooleanVar(value=bool(self.legacy))
        self.blocked = zone_marked_files(ROOT)   # 被 Windows 貼「來自網路」標記的檔案
        self.ssl_blocked = False     # 公司網路攔截 HTTPS，pip 連不上 PyPI
        self.trust_hosts = False     # 使用者明確同意「信任 PyPI、略過憑證檢查」

        self.body, self.footer, self.canvas = build_scrollable(self, BG)
        self.page_consent()
        self.lift()
        self.focus_force()

    def fit(self):
        fit(self, self.body, self.footer)

    def clear(self):
        for c in self.body.winfo_children():
            c.destroy()
        for c in self.footer.winfo_children():
            c.destroy()

    def head(self, title, sub):
        tk.Label(self.body, text=title, bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body, text=sub, bg=BG, fg=MUTED, justify="left",
                 font=(FONT, 10)).pack(anchor="w", padx=28, pady=(0, 12))

    # ───────────────────────── 第一頁：同意 ─────────────────────────
    def page_consent(self):
        self.clear()
        self.head("安裝前，先說清楚會做什麼",
                  "這個工具會用 Google Gemini 把會議語音轉成文字。\n"
                  "按下同意之前，下面每一項都不會執行。")

        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28)

        rows = [
            ("1", "檢查 ffmpeg（處理音訊的免費工具）",
             "沒有的話用 Windows 內建的 winget 安裝。不需要系統管理員權限。"),
            ("2", f"安裝 {len(self.pkgs)} 個 Python 套件",
             "、".join(f"{n}（{w}）" for _, n, w in self.pkgs)),
            ("3", "在桌面建立捷徑",
             "說明書裡寫的「點兩下桌面圖示」就是它。"),
            ("4", "儲存你的 Gemini API 金鑰",
             "存成這台電腦、這個使用者帳號的環境變數 GEMINI_API_KEY，不會外傳。"),
        ]
        if self.legacy:
            rows.append(
                ("5", f"清掉舊版留下的 {len(self.legacy)} 個檔案",
                 "、".join(os.path.basename(p) for p in self.legacy)
                 + "　（新版已經改名，留著會讓你不知道該點哪一個。"
                   "不想刪就把下面的勾取消。）"))
        if self.blocked:
            # 編號用 len(rows)+1 算，不要寫死：上面那條「清掉舊版」是有殘留才出現的。
            rows.append(
                (str(len(rows) + 1),
                 f"解除這個資料夾裡 {len(self.blocked)} 個檔案的「來自網路」封鎖",
                 "從 Email 或雲端拿到的壓縮檔，解開之後 Windows 會把裡面的 .bat "
                 "當成可疑程式擋下來，所以你點安裝／開始使用／解除安裝都會跳警告。"
                 "這一步只刪掉那個隱形標記，檔案內容一個位元組都不會動，"
                 "也不改任何系統設定。"))
        for n, t, d in rows:
            r = tk.Frame(box, bg="white")
            r.pack(fill="x", padx=16, pady=(10, 0))
            tk.Label(r, text=n, bg=ACCENT, fg="white", width=2,
                     font=(FONT, 9, "bold")).pack(side="left", anchor="n")
            c = tk.Frame(r, bg="white")
            c.pack(side="left", fill="x", expand=True, padx=(10, 0))
            tk.Label(c, text=t, bg="white", fg=FG, anchor="w",
                     font=(FONT, 10, "bold")).pack(fill="x")
            tk.Label(c, text=d, bg="white", fg=MUTED, anchor="w", justify="left",
                     wraplength=520, font=(FONT, 9)).pack(fill="x")
        tk.Frame(box, bg="white", height=10).pack()

        note = tk.Frame(self.body, bg="#fff8e6", highlightbackground="#e8d9a8",
                        highlightthickness=1)
        note.pack(fill="x", padx=28, pady=(14, 0))
        tk.Label(note, text="不會動到的東西",
                 bg="#fff8e6", fg="#7a5c12", anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(note,
                 text="不會改系統設定、不會開機自動啟動、不會蒐集或上傳你電腦裡的檔案。\n"
                      "隨時可以雙擊「7_解除安裝.bat」把上面這些原樣移除。",
                 bg="#fff8e6", fg="#7a5c12", anchor="w", justify="left",
                 font=(FONT, 9)).pack(fill="x", padx=12, pady=(2, 10))

        k = tk.Frame(self.body, bg=BG)
        k.pack(fill="x", padx=28, pady=(16, 0))
        tk.Label(k, text="Gemini API 金鑰（可以先跳過，第一次使用時會再問）",
                 bg=BG, fg=FG, anchor="w", font=(FONT, 10, "bold")).pack(fill="x")
        tk.Label(k, text="還沒有的話，到 aistudio.google.com/apikey 免費申請，一分鐘就好。",
                 bg=BG, fg=MUTED, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(0, 4))
        tk.Label(k, text=(
            "⚠ 要拿來錄真實會議，請務必開通付費層（在 AI Studio 綁定帳單）。\n"
            "　 免費層的內容 Google 會拿去改進產品，人工審閱者可能讀到，"
            "官方明文警告不要送機密資訊。"),
            bg=BG, fg="#8a5a00", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", pady=(0, 6))
        e = tk.Entry(k, textvariable=self.key_var, show="•", font=("Consolas", 10),
                     relief="solid", bd=1)
        e.pack(fill="x", ipady=4)
        # 🔴 同事貼金鑰的第一個動作是「右鍵→貼上」，而 tkinter 的 Entry 沒有右鍵選單，
        #    按下去毫無反應、只有 Ctrl+V 有用（2026-09-18 使用者回報）。
        attach_paste_menu(e, secret=True)
        if os.environ.get(_apikey.NAME) or _apikey.saved():
            self.key_var.set("")
            tk.Label(k, text="（偵測到這台電腦已經設定過金鑰了，留空就是沿用舊的）",
                     bg=BG, fg=OK, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(4, 0))

        tk.Checkbutton(self.body, text="在桌面建立捷徑", variable=self.sc_var,
                       bg=BG, fg=FG, activebackground=BG, selectcolor="white",
                       font=(FONT, 9)).pack(anchor="w", padx=26, pady=(10, 0))
        if self.legacy:
            tk.Checkbutton(self.body,
                           text=f"順便清掉舊版留下的 {len(self.legacy)} 個檔案",
                           variable=self.lg_var, bg=BG, fg=FG, activebackground=BG,
                           selectcolor="white",
                           font=(FONT, 9)).pack(anchor="w", padx=26, pady=(2, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", padx=0, pady=0, ipady=8)
        tk.Button(bar, text="取消", command=self.destroy, width=10,
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG,
                  activebackground="#d8d8d4", cursor="hand2").pack(side="right")
        tk.Button(bar, text="我同意，開始安裝", command=self.start, width=18,
                  font=(FONT, 10, "bold"), relief="flat", bg=ACCENT, fg="white",
                  activebackground="#a94f21", activeforeground="white",
                  cursor="hand2").pack(side="right", padx=(0, 8))

        self.fit()

    # ───────────────────────── 第二頁：進度 ─────────────────────────
    def page_progress(self):
        self.clear()
        self.head("安裝中", "請不要關掉這個視窗。第一次安裝大約 1～3 分鐘。")

        self.pb = ttk.Progressbar(self.body, mode="determinate",
                                  maximum=self.total, length=560)
        self.pb.pack(padx=28, pady=(0, 6))
        self.now = tk.Label(self.body, text="準備中…", bg=BG, fg=FG, anchor="w",
                            font=(FONT, 10, "bold"))
        self.now.pack(fill="x", padx=28)

        f = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                     highlightthickness=1)
        f.pack(fill="both", expand=True, padx=28, pady=(8, 0))
        self.log = tk.Text(f, height=12, width=68, bg="white", fg=FG, bd=0,
                           font=("Consolas", 9), wrap="word", state="disabled")
        sb = tk.Scrollbar(f, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.log.tag_configure("ok", foreground=OK)
        self.log.tag_configure("bad", foreground=BAD)
        self.log.tag_configure("dim", foreground=MUTED)

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        self.cancel_btn = tk.Button(bar, text="取消安裝", command=self.on_cancel,
                                    width=10, font=(FONT, 10), relief="flat",
                                    bg="#e6e6e2", fg=FG, cursor="hand2")
        self.cancel_btn.pack(side="right")
        self.fit()

    def say(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    # ───────────────────────── 第三頁：完成 ─────────────────────────
    def page_done(self, failed):
        self.clear()
        if failed:
            self.head("安裝沒有全部完成",
                      "下面列出哪幾項沒成功。已經成功的部分不用重做，"
                      "修好問題後再跑一次「3_安裝.bat」即可。")
        else:
            self.head("安裝完成", "接下來點兩下桌面上的「TIO語音精靈」就可以開始用了。")

        # 🔴 SSL 攔截時，先把「到底發生什麼事」用白話講清楚，
        #    不要讓使用者對著一整片英文 pip 錯誤發呆。
        if self.ssl_blocked:
            self.ssl_panel()

        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28)
        for name, ok, detail in self.results:
            # ok 可以是 "warn"：要提醒、但不算安裝失敗（例如金鑰被 Google 拒絕，選單之後會再問）
            mark, col = ("✓", OK) if ok is True else ("!", "#8a5a00") if ok == "warn" else ("✗", BAD)
            r = tk.Frame(box, bg="white")
            r.pack(fill="x", padx=16, pady=(8, 0))
            tk.Label(r, text=mark, bg="white",
                     fg=col, width=2,
                     font=(FONT, 11, "bold")).pack(side="left", anchor="n")
            c = tk.Frame(r, bg="white")
            c.pack(side="left", fill="x", expand=True)
            tk.Label(c, text=name, bg="white", fg=FG, anchor="w",
                     font=(FONT, 10)).pack(fill="x")
            if detail:
                tk.Label(c, text=detail, bg="white", fg=MUTED if ok is True else col,
                         anchor="w", justify="left", wraplength=500,
                         font=(FONT, 9)).pack(fill="x")
        tk.Frame(box, bg="white", height=10).pack()

        tk.Label(self.body,
                 text="不想用了？雙擊資料夾裡的「7_解除安裝.bat」，會逐項問你要移除什麼。",
                 bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 9)).pack(fill="x", padx=28, pady=(14, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="關閉", command=self.destroy, width=10,
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG,
                  cursor="hand2").pack(side="right")
        if not failed:
            tk.Button(bar, text="立即開始使用", width=14, cursor="hand2",
                      command=self.launch, font=(FONT, 10, "bold"), relief="flat",
                      bg=ACCENT, fg="white", activeforeground="white",
                      activebackground="#a94f21").pack(side="right", padx=(0, 8))
        man = os.path.join(ROOT, "5_使用說明（功能操作）.md")
        if os.path.exists(man):
            tk.Button(bar, text="打開使用說明", width=12, cursor="hand2",
                      command=lambda: os.startfile(man), font=(FONT, 10),
                      relief="flat", bg="#e6e6e2", fg=FG).pack(side="right", padx=(0, 8))
        self.fit()

    def ssl_panel(self):
        """公司網路攔截 HTTPS 時，講清楚原因與三條路。"""
        f = tk.Frame(self.body, bg="#fdf3f2", highlightbackground="#e8c4c0",
                     highlightthickness=1)
        f.pack(fill="x", padx=28, pady=(0, 14))
        tk.Label(f, text="為什麼裝不起來：這台電腦的網路擋住了 Python 下載套件",
                 bg="#fdf3f2", fg=BAD, anchor="w",
                 font=(FONT, 10, "bold")).pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(f, text=(
            "公司／學校的防火牆或防毒軟體會攔下 HTTPS 連線做檢查，換上自己的憑證。\n"
            "瀏覽器認得那張憑證（IT 有裝進 Windows），但 Python 預設不認得，所以\n"
            "連不上套件伺服器（pypi.org）。這不是你操作錯誤，也不是程式壞掉。\n\n"
            "我已經自動用「Windows 憑證存放區」重試過一次了，還是不行。"),
            bg="#fdf3f2", fg="#6b3a36", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(f, text="接下來可以這樣做（由簡單到麻煩）：",
                 bg="#fdf3f2", fg=BAD, anchor="w",
                 font=(FONT, 10, "bold")).pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(f, text=(
            "① 換一個網路再跑一次「3_安裝.bat」—— 例如用手機開熱點。\n"
            "    這是最快也最乾淨的做法。公司網路如果只擋下載套件，\n"
            "    裝好之後就能照常使用；使用時若出現「憑證被攔截」，\n"
            "    代表連 Google 也被擋，要請 IT 放行\n"
            "    generativelanguage.googleapis.com。\n"
            "② 請 IT 把 pypi.org 和 files.pythonhosted.org 加入白名單。\n"
            "③ 下面那顆按鈕：略過憑證檢查直接裝（見說明）。"),
            bg="#fdf3f2", fg="#6b3a36", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        w = tk.Frame(f, bg="#fff8e6", highlightbackground="#e8d9a8",
                     highlightthickness=1)
        w.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(w, text=(
            "③ 的取捨：略過憑證檢查等於不驗證對方是不是真的 pypi.org。\n"
            "你的連線本來就已經被公司設備解開來看了，所以這裡多半只是讓 Python\n"
            "接受同一套設備；但如果這台電腦連的是不明的公共 Wi-Fi，就不要用。\n"
            "它只影響這一次安裝，不會改變電腦的其他設定。"),
            bg="#fff8e6", fg="#7a5c12", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=12, pady=8)

        tk.Button(f, text="我了解風險，略過憑證檢查重試",
                  command=self.retry_trusted, cursor="hand2",
                  font=(FONT, 10, "bold"), relief="flat",
                  bg="#8a5a00", fg="white", activeforeground="white",
                  activebackground="#6d4700").pack(anchor="w", padx=14, pady=(0, 12))

    def retry_trusted(self):
        if not messagebox.askyesno(
                "再確認一次",
                "接下來會用「信任 pypi.org、不驗證憑證」的方式重新安裝那幾個套件。\n\n"
                "只影響這一次安裝，不會改變這台電腦的其他設定。\n\n"
                "如果你現在連的是不認識的公共 Wi-Fi，請不要用這個方式。\n\n"
                "要繼續嗎？"):
            return
        self.trust_hosts = True
        self.ssl_blocked = False
        self.results = []
        self.cancelled.clear()
        self.start()

    def launch(self):
        """
        完成頁的「立即開始使用」。

        🔴 病根（2026-09-18，兩台筆電）：問題在「開新視窗的同時，精靈與 3_安裝.bat
           的主控台正在關閉」，跟開的是哪支程式無關：
             ・第一版 `os.startfile(START_BAT)` → 同事筆電跳 `cmd.exe 0xc0000142`
             ・第二版直接開新主控台跑 python → 使用者筆電跳 `python.exe 0xc0000142`
           兩台直接點桌面捷徑都正常。0xc0000142＝新程式還沒啟動完成，它的主控台主機
           就先沒了（microsoft/terminal #13340 維護者說明、#18209 同型案例）。
           Win11 的主控台由 Windows Terminal 接手；桌機（WT 1.24）連同 CPU 滿載跑
           10 次都重現不出來，所以修法不能靠「時機剛好」。

        改法：精靈只啟動一個**沒有主控台**的背景小幫手（DETACHED_PROCESS，碰不到任何
        主控台主機），然後照常關閉。小幫手等安裝視窗上的每個行程都結束、再等 1 秒，
        才開選單；選單若仍啟動失敗，改走檔案總管開 .bat——跟使用者自己雙擊同一條路
        （見 _deferred_launch）。
        🔴 menu.py 自己會把主控台字碼頁設成 65001，不要退回去依賴 .bat 的 chcp。
        🔴 **絕對不要加 CREATE_NEW_PROCESS_GROUP**：Windows 會替新行程群組停用 Ctrl+C，
           而且一路繼承給選單與即時字幕／口譯 —— 按 Ctrl+C 完全停不下來、繼續計費
           （2026-09-19 使用者筆電踩到；跟 4_開始使用.bat 註解「不要加 /B」是同一件事）。
           _LAUNCH_CODE 另外會主動解除一次，當第二道保險。
        """
        try:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--launch-menu"]
                             + [str(p) for p in _console_pids()],
                             cwd=ROOT, close_fds=True,
                             creationflags=subprocess.DETACHED_PROCESS)
        except Exception as e:
            messagebox.showerror(
                "打不開",
                f"{type(e).__name__}: {e}\n\n"
                f"請直接點資料夾裡的「4_開始使用.bat」或桌面捷徑。")
        self.destroy()

    # ───────────────────────────── 流程控制 ─────────────────────────────
    def start(self):
        # 🔴 在主執行緒先把 Tk 變數的值取下來。工作執行緒直接讀 tk 變數不保證
        #    安全（tkinter 非執行緒安全），跑不跑 mainloop 行為還不一樣。
        #    先快照就完全沒有這個變數。
        self.want_shortcut = bool(self.sc_var.get())
        self.want_clean = bool(self.lg_var.get()) and bool(self.legacy)
        self.api_key = self.key_var.get().strip().strip('"')
        self.total = (2 + len(self.pkgs) + (1 if self.want_shortcut else 0)
                      + (1 if self.want_clean else 0)
                      + (1 if self.blocked else 0))
        self.page_progress()
        threading.Thread(target=self._work, daemon=True).start()
        self.after(80, self._pump)

    def on_cancel(self):
        if messagebox.askyesno("取消安裝", "確定要中斷安裝嗎？\n已經裝好的部分會留著。"):
            self.cancelled.set()
            self.cancel_btn.configure(state="disabled", text="正在停止…")
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except Exception:
                    pass

    def on_close(self):
        if getattr(self, "pb", None) and self.pb.winfo_exists():
            self.on_cancel()
        else:
            self.destroy()

    def _post(self, kind, *a):
        self.q.put((kind, a))

    def _pump(self):
        try:
            while True:
                kind, a = self.q.get_nowait()
                if kind == "step":
                    self.now.configure(text=a[0])
                    self.pb["value"] = a[1]
                elif kind == "log":
                    self.say(a[0], a[1] if len(a) > 1 else None)
                elif kind == "done":
                    self.page_done(a[0])
                    return
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _run(self, cmd, desc):
        """跑一個指令。回傳 (成功, 錯誤訊息最後幾行)。"""
        if self.cancelled.is_set():
            return False, "使用者取消"
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW)
            out = self.proc.communicate()[0] or ""
            rc = self.proc.returncode
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        finally:
            self.proc = None
        if rc == 0:
            return True, ""
        tail = "\n".join(out.strip().splitlines()[-6:])
        return False, tail or f"錯誤碼 {rc}"

    def _save_key(self, key):
        """安裝步驟 4：先跟 Google 確認金鑰，再存；確定無效就不存，讓使用者之後在選單 9 重貼。

        🔴 存好之後精靈自己也要拿到（_apikey.use）：「立即開始使用」開的選單繼承的是精靈的環境，
           而 setx 只寫登錄檔。少了這一行，選單一選功能就又要使用者貼一次（2026-09-19 回報）。
        """
        if key:
            status, why = _apikey.verify(key)
            if status == "bad":
                # 🔴 不可以記成失敗：其他都裝好了，失敗會讓完成頁叫人重跑安裝、還把「立即開始使用」藏起來
                self._post("log", f"! 金鑰沒有存：{why}", "bad")
                self.results.append(("API 金鑰", "warn",
                                     f"沒有存：{why}開始使用時會請你重新貼一組（之後也可以在選單選 9 換）。"))
                return
            ok, err = self._run(["setx", _apikey.NAME, key], "金鑰")
            if ok:
                _apikey.use(key)
                self._post("log", "✓ 金鑰已儲存", "ok")
                self.results.append(("API 金鑰", True,
                                     "存好了，程式會自動讀到。" if status == "ok"
                                     else f"存好了，但{why}"))
            else:
                self._post("log", f"✗ 金鑰儲存失敗\n{err}", "bad")
                self.results.append(("API 金鑰", False, err[:200]))
        elif os.environ.get(_apikey.NAME) or _apikey.saved():
            if not os.environ.get(_apikey.NAME):
                _apikey.use(_apikey.saved())
            self._post("log", "· 沿用這台電腦原本就有的金鑰", "dim")
            self.results.append(("API 金鑰", True, "沿用原本設定的"))
        else:
            self._post("log", "· 跳過金鑰，第一次使用時程式會再問", "dim")
            self.results.append(("API 金鑰", True, "跳過了；第一次執行時會再問一次"))

    # pip 失敗時，怎麼判斷是「公司網路在攔 HTTPS」而不是普通的網路不通
    SSL_MARKERS = ("SSLCertVerificationError", "SSLError",
                   "certificate verify failed",
                   "problem confirming the ssl certificate",
                   "CERTIFICATE_VERIFY_FAILED", "self signed certificate")

    @staticmethod
    def looks_like_ssl(text):
        t = (text or "")
        return any(m.lower() in t.lower() for m in Wizard.SSL_MARKERS)

    def _pip(self, spec, name):
        """
        裝一個套件。遇到 SSL 憑證錯誤會自動換方式重試。

        🔴 2026-09-08 同事回報：公司/學校網路對 HTTPS 做中間人檢查（防火牆或
           防毒把憑證換成自己的），Python 內建的憑證清單不認得那張憑證，
           pip 就完全連不上 PyPI —— 但同一台電腦的瀏覽器連得上，因為
           Windows 的憑證存放區裡有 IT 裝的根憑證。

           所以第二次改用 --use-feature=truststore：讓 pip 改走 Windows 憑證
           存放區驗證。這是**正解**，不是繞過檢查，安全性沒有降低。
           （truststore 已內建在 pip 裡，乾淨安裝的環境也用得到。）

           還是不行才把它記成「被 SSL 攔截」，交給結果頁提供最後手段。
        """
        base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
        ok, err = self._run(base + [spec], name)
        if ok:
            return True, ""

        if self.looks_like_ssl(err):
            self._post("log", "  ↻ 憑證驗證失敗，改用 Windows 憑證存放區重試…", "dim")
            ok2, err2 = self._run(base + ["--use-feature=truststore", spec], name)
            if ok2:
                self._post("log", "  ✓ 用 Windows 憑證存放區裝好了", "ok")
                return True, ""
            err = err2 or err

        if self.trust_hosts:            # 使用者在結果頁按過「信任 PyPI 重試」
            self._post("log", "  ↻ 以信任 PyPI 的方式重試…", "dim")
            ok3, err3 = self._run(
                base + ["--trusted-host", "pypi.org",
                        "--trusted-host", "files.pythonhosted.org",
                        "--trusted-host", "pypi.python.org", spec], name)
            if ok3:
                self._post("log", "  ✓ 裝好了", "ok")
                return True, ""
            err = err3 or err

        if self.looks_like_ssl(err):
            self.ssl_blocked = True
        return False, err

    def _work(self):
        try:
            self.__work()
        except Exception:
            self._post("log", traceback.format_exc(), "bad")
            self.results.append(("安裝程式本身出錯", False, traceback.format_exc()[-300:]))
            self._post("done", True)

    def __work(self):
        from shutil import which
        n = 0

        # 🔴 requirements.txt 釘 scipy>=1.18.0，而 scipy 1.18 要 Python 3.12 以上
        #    （沒有 cp311 的 wheel）。舊 Python 會在 pip 那一步噴一堆看不懂的
        #    編譯錯誤，不如先擋下來講清楚。
        if sys.version_info < (3, 12):
            v = ".".join(map(str, sys.version_info[:3]))
            self._post("log", f"✗ 這台電腦的 Python 是 {v}，太舊了", "bad")
            self.results.append((
                "Python 版本", False,
                f"目前是 {v}，這個工具需要 3.12 以上（套件相依需求）。"
                "請到 python.org 安裝 3.13，或移除舊版後重跑 3_安裝.bat。"))
            self._post("done", True)
            return

        # 0.5 解除「來自網路」封鎖
        # 🔴 刻意排在最前面：後面任何一步失敗或被取消，至少 4_開始使用.bat 和
        #    7_解除安裝.bat 已經不會再被 Windows 攔 —— 解除安裝被攔住最麻煩。
        #    點 3_安裝.bat 那一次的警告擋不掉（程式還沒開始跑），但只會有那一次。
        if self.blocked:
            n += 1
            self._post("step", "解除「來自網路」封鎖…", n)
            done, fail = unblock_files(self.blocked)
            msg = f"已解除 {len(done)} 個檔案"
            if fail:
                msg += "；沒解掉：" + "、".join(fail)
            self._post("log", "✓ " + msg +
                       "（之後點 4_開始使用.bat 不會再跳警告）", "ok")
            self.results.append(("解除「來自網路」封鎖", True, msg))

        # 1. ffmpeg
        n += 1
        self._post("step", "檢查 ffmpeg…", n)
        if which("ffmpeg") and which("ffprobe"):
            self._post("log", "✓ ffmpeg 已經在這台電腦上", "ok")
            self.results.append(("ffmpeg", True, "本來就有"))
        elif which("winget") is None:
            self._post("log", "✗ 沒有 ffmpeg，這台電腦也沒有 winget", "bad")
            self.results.append(("ffmpeg", False,
                                 "請到 gyan.dev/ffmpeg/builds 下載，解壓後把 bin 加進 PATH"))
        else:
            self._post("log", "· 沒有 ffmpeg，正在用 winget 安裝（要等一下）", "dim")
            ok, err = self._run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                                 "--accept-source-agreements",
                                 "--accept-package-agreements"], "ffmpeg")
            if ok:
                self._post("log", "✓ ffmpeg 安裝完成", "ok")
                self.results.append(("ffmpeg", True, "已安裝（可能要重開視窗才找得到）"))
            else:
                self._post("log", f"✗ ffmpeg 安裝失敗\n{err}", "bad")
                self.results.append(("ffmpeg", False, err[:200]))

        # 2. Python 套件（逐一裝，才看得到進度）
        for spec, name, why in self.pkgs:
            if self.cancelled.is_set():
                break
            n += 1
            self._post("step", f"安裝 {name}（{why}）…", n)
            self._post("log", f"· pip install {spec}", "dim")
            ok, err = self._pip(spec, name)
            if ok:
                self._post("log", f"✓ {name}", "ok")
                self.results.append((f"套件 {name}", True, ""))
            else:
                self._post("log", f"✗ {name} 裝不起來\n{err}", "bad")
                self.results.append((f"套件 {name}", False, err[:200]))

        if self.cancelled.is_set():
            self.results.append(("安裝被中斷", False, "你按了取消。已裝好的部分留著。"))
            self._post("done", True)
            return

        # 3. 桌面捷徑
        if self.want_shortcut:
            n += 1
            self._post("step", "建立桌面捷徑…", n)
            ok, info = make_shortcut(START_BAT, ROOT)
            if ok:
                self._post("log", "✓ 桌面捷徑：" + info, "ok")
                self.results.append(("桌面捷徑", True, info))
            else:
                self._post("log", f"✗ 捷徑建立失敗\n{info}", "bad")
                self.results.append((
                    "桌面捷徑", False,
                    (info or "")[:220] +
                    "　→ 不影響使用：直接點資料夾裡的 4_開始使用.bat 就可以了。"))

        # 3.5 清掉舊版殘留（使用者在同意頁勾選過才會走到這裡）
        if self.want_clean:
            n += 1
            self._post("step", "清掉舊版留下的檔案…", n)
            done, fail = [], []
            for p in self.legacy:
                try:
                    os.remove(p)
                    done.append(os.path.basename(p))
                except Exception as e:
                    fail.append(f"{os.path.basename(p)}（{e}）")
            # 舊的桌面捷徑。remove_shortcut() 只認名字、不會去讀捷徑指向哪裡，
            # 所以這一步的把關是「這個資料夾裡確實有舊版殘留」（走到這裡就成立），
            # 而且名字是本工具自己用過的舊名，不是通用字眼。
            try:
                from _winpath import remove_shortcut
                for _legacy in LEGACY_SHORTCUTS:
                    ok_sc, info_sc = remove_shortcut(_legacy)
                    if ok_sc and "已刪除" in info_sc:
                        done.append(f"{_legacy} 捷徑")
            except Exception:
                pass
            msg = "、".join(done) if done else "沒有東西需要清"
            if fail:
                msg += "；刪不掉：" + "、".join(fail)
            self._post("log", "✓ 舊版殘留已清除：" + msg, "ok")
            self.results.append(("清掉舊版留下的檔案", True, msg))

        # 4. API 金鑰
        n += 1
        self._post("step", "儲存 API 金鑰…", n)
        self._save_key(self.api_key)

        self._post("step", "完成", self.total)
        self._post("done", any(not ok for _, ok, _ in self.results))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--launch-menu":
        return _deferred_launch([int(a) for a in sys.argv[2:] if a.isdigit()])
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    _console(False)
    try:
        Wizard().mainloop()
    except Exception:
        _console(True)
        traceback.print_exc()
        try:
            input("\n安裝程式出錯了。請把上面的訊息拍下來，照「1_安裝說明（先讀這個）」的「卡住的時候」回報。按 Enter 關閉…")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
