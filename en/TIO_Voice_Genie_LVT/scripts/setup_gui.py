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
START_BAT = os.path.join(ROOT, "4_Start.bat")
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
    "        input('Press Enter to close…')\n"
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
    "google-genai": "connects to Google Gemini",
    "sounddevice": "records the microphone",
    "PyAudioWPatch": "records computer audio",
    "numpy": "processes sound data",
    "scipy": "resamples sound into the format the model needs",
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
            None, "The menu did not open automatically.\n\nPlease double-click \"4_Start.bat\" in the folder, or the desktop shortcut, instead.",
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
        self.title("TIO — Setup")
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
        self.head("Before installing: what this will do",
                  "This tool uses Google Gemini to turn meeting speech into text.\nNone of the steps below will happen until you press \"I agree\".")

        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28)

        rows = [
            ("1", "Check for ffmpeg (a free tool for processing audio)",
             "If it is missing, it is installed with winget, which is built into Windows. No administrator rights are needed."),
            ("2", f"Install {len(self.pkgs)} Python packages",
             ", ".join(f"{n} ({w})" for _, n, w in self.pkgs)),
            ("3", "Create a desktop shortcut",
             "This is the desktop icon the guide tells you to double-click."),
            ("4", "Save your Gemini API key",
             "Stored as the GEMINI_API_KEY environment variable of your user account on this PC. It is not shared with anyone."),
        ]
        if self.legacy:
            rows.append(
                ("5", f"Clean up {len(self.legacy)} file(s) left by an older version",
                 ", ".join(os.path.basename(p) for p in self.legacy)
                 + "  (The new version uses new names; keeping these would leave you unsure which one to click. If you don't want them deleted, untick the box below.)"))
        if self.blocked:
            # 編號用 len(rows)+1 算，不要寫死：上面那條「清掉舊版」是有殘留才出現的。
            rows.append(
                (str(len(rows) + 1),
                 f"Unblock {len(self.blocked)} file(s) in this folder marked \"from the internet\"",
                 "With a zip file from email or the cloud, once it is unzipped Windows treats the .bat files inside as suspicious and blocks them, so you get a warning whenever you click Install / Start / Uninstall. This step only removes that hidden mark: not a single byte of the files is changed, and no system settings are changed either."))
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
        tk.Label(note, text="What it will not touch",
                 bg="#fff8e6", fg="#7a5c12", anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(note,
                 text="No system settings are changed, nothing starts automatically with Windows,\nand no files on your PC are collected or uploaded.\nDouble-click \"7_Uninstall.bat\" at any time to remove everything above.",
                 bg="#fff8e6", fg="#7a5c12", anchor="w", justify="left",
                 font=(FONT, 9)).pack(fill="x", padx=12, pady=(2, 10))

        k = tk.Frame(self.body, bg=BG)
        k.pack(fill="x", padx=28, pady=(16, 0))
        tk.Label(k, text="Gemini API key (you can skip this; you will be asked again on first use)",
                 bg=BG, fg=FG, anchor="w", font=(FONT, 10, "bold")).pack(fill="x")
        tk.Label(k, text="No key yet? Get one free at aistudio.google.com/apikey; it only takes a minute.",
                 bg=BG, fg=MUTED, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(0, 4))
        tk.Label(k, text=(
            "⚠ For real meetings, you must turn on the paid tier (set up billing in AI Studio).\n   On the free tier, Google uses your content to improve its products and\n   human reviewers may read it. Google explicitly warns against sending\n   confidential information."),
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
            tk.Label(k, text="(A key is already set up on this PC. Leave this blank to keep using it.)",
                     bg=BG, fg=OK, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(4, 0))

        tk.Checkbutton(self.body, text="Create a desktop shortcut", variable=self.sc_var,
                       bg=BG, fg=FG, activebackground=BG, selectcolor="white",
                       font=(FONT, 9)).pack(anchor="w", padx=26, pady=(10, 0))
        if self.legacy:
            tk.Checkbutton(self.body,
                           text=f"Also clean up the {len(self.legacy)} file(s) left by an older version",
                           variable=self.lg_var, bg=BG, fg=FG, activebackground=BG,
                           selectcolor="white",
                           font=(FONT, 9)).pack(anchor="w", padx=26, pady=(2, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", padx=0, pady=0, ipady=8)
        tk.Button(bar, text="Cancel", command=self.destroy, width=10,
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG,
                  activebackground="#d8d8d4", cursor="hand2").pack(side="right")
        tk.Button(bar, text="I agree, start installing", command=self.start, width=18,
                  font=(FONT, 10, "bold"), relief="flat", bg=ACCENT, fg="white",
                  activebackground="#a94f21", activeforeground="white",
                  cursor="hand2").pack(side="right", padx=(0, 8))

        self.fit()

    # ───────────────────────── 第二頁：進度 ─────────────────────────
    def page_progress(self):
        self.clear()
        self.head("Installing", "Please do not close this window.\nThe first installation takes about 1–3 minutes.")

        self.pb = ttk.Progressbar(self.body, mode="determinate",
                                  maximum=self.total, length=560)
        self.pb.pack(padx=28, pady=(0, 6))
        self.now = tk.Label(self.body, text="Preparing…", bg=BG, fg=FG, anchor="w",
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
        self.cancel_btn = tk.Button(bar, text="Cancel", command=self.on_cancel,
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
            self.head("Not everything was installed",
                      "The list below shows which items did not succeed.\nParts that already worked need not be redone: fix the problem,\nthen just run \"3_Install.bat\" again.")
        else:
            self.head("Installation complete", "Now just double-click \"TIO Voice Genie\" on your desktop to start using it.")

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
                 text="Don't want it any more? Double-click \"7_Uninstall.bat\" in the folder;\nit asks you item by item what to remove.",
                 bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 9)).pack(fill="x", padx=28, pady=(14, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="Close", command=self.destroy, width=10,
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG,
                  cursor="hand2").pack(side="right")
        if not failed:
            tk.Button(bar, text="Start using now", width=14, cursor="hand2",
                      command=self.launch, font=(FONT, 10, "bold"), relief="flat",
                      bg=ACCENT, fg="white", activeforeground="white",
                      activebackground="#a94f21").pack(side="right", padx=(0, 8))
        man = os.path.join(ROOT, "5_User_Guide.md")
        if os.path.exists(man):
            tk.Button(bar, text="Open guide", width=12, cursor="hand2",
                      command=lambda: os.startfile(man), font=(FONT, 10),
                      relief="flat", bg="#e6e6e2", fg=FG).pack(side="right", padx=(0, 8))
        self.fit()

    def ssl_panel(self):
        """公司網路攔截 HTTPS 時，講清楚原因與三條路。"""
        f = tk.Frame(self.body, bg="#fdf3f2", highlightbackground="#e8c4c0",
                     highlightthickness=1)
        f.pack(fill="x", padx=28, pady=(0, 14))
        tk.Label(f, text="Why it failed: the network blocks Python's package downloads",
                 bg="#fdf3f2", fg=BAD, anchor="w",
                 font=(FONT, 10, "bold")).pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(f, text=(
            "Office/campus firewalls or antivirus software intercept HTTPS connections to\ninspect them, swapping in their own certificate. Your browser trusts that\ncertificate (IT installed it in Windows), but Python does not by default, so it\ncannot reach the package server (pypi.org). You did nothing wrong, and the\nprogram is not broken.\n\nI already retried once automatically with the \"Windows certificate store\",\nbut it still did not work."),
            bg="#fdf3f2", fg="#6b3a36", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(f, text="What you can do next (easiest first):",
                 bg="#fdf3f2", fg=BAD, anchor="w",
                 font=(FONT, 10, "bold")).pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(f, text=(
            "① Run \"3_Install.bat\" again on another network, such as your phone's hotspot.\n    This is the quickest, cleanest way. If the office network only blocks\n    package downloads, you can use the tool there as usual once it is\n    installed. If \"Certificate intercepted\" appears while you use it, the\n    connection to Google is blocked too: ask IT to allow\n    generativelanguage.googleapis.com.\n② Ask IT to add pypi.org and files.pythonhosted.org to the allowlist.\n③ The button below: install without the certificate check (see the note)."),
            bg="#fdf3f2", fg="#6b3a36", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))

        w = tk.Frame(f, bg="#fff8e6", highlightbackground="#e8d9a8",
                     highlightthickness=1)
        w.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(w, text=(
            "The trade-off with ③: skipping the certificate check means not verifying\nthat the server really is pypi.org. Your connection is already opened and\ninspected by your organisation's equipment, so this mostly just lets\nPython accept that same equipment. But if this PC is on an unknown\npublic Wi-Fi, do not use it. It only affects this one installation\nand does not change any other settings on the PC."),
            bg="#fff8e6", fg="#7a5c12", anchor="w", justify="left",
            font=(FONT, 9)).pack(fill="x", padx=12, pady=8)

        tk.Button(f, text="I understand the risk – skip the certificate check and retry",
                  command=self.retry_trusted, cursor="hand2",
                  font=(FONT, 10, "bold"), relief="flat",
                  bg="#8a5a00", fg="white", activeforeground="white",
                  activebackground="#6d4700").pack(anchor="w", padx=14, pady=(0, 12))

    def retry_trusted(self):
        if not messagebox.askyesno(
                "Please confirm",
                "Those packages will now be installed again by \"trusting pypi.org without verifying its certificate\".\n\nThis only affects this one installation and does not change any other settings on this PC.\n\nIf you are connected to a public Wi-Fi network you don't know, please do not do this.\n\nContinue?"):
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
                "Could not open",
                f"{type(e).__name__}: {e}\n\nPlease double-click \"4_Start.bat\" in the folder, or the desktop shortcut, instead.")
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
        if messagebox.askyesno("Cancel", "Are you sure you want to stop the installation?\nAnything already installed will be kept."):
            self.cancelled.set()
            self.cancel_btn.configure(state="disabled", text="Stopping…")
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
            return False, "Cancelled by the user"
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
        return False, tail or f"Error code {rc}"

    def _save_key(self, key):
        """安裝步驟 4：先跟 Google 確認金鑰，再存；確定無效就不存，讓使用者之後在選單 9 重貼。

        🔴 存好之後精靈自己也要拿到（_apikey.use）：「立即開始使用」開的選單繼承的是精靈的環境，
           而 setx 只寫登錄檔。少了這一行，選單一選功能就又要使用者貼一次（2026-09-19 回報）。
        """
        if key:
            status, why = _apikey.verify(key)
            if status == "bad":
                # 🔴 不可以記成失敗：其他都裝好了，失敗會讓完成頁叫人重跑安裝、還把「立即開始使用」藏起來
                self._post("log", f"! Key not saved: {why}", "bad")
                self.results.append(("API key", "warn",
                                     f"Not saved: {why} You will be asked to paste a new one when you start using the tool (you can also change it later with 9 in the menu)."))
                return
            ok, err = self._run(["setx", _apikey.NAME, key], "key")
            if ok:
                _apikey.use(key)
                self._post("log", "✓ Key saved", "ok")
                self.results.append(("API key", True,
                                     "Saved. The program will pick it up automatically." if status == "ok"
                                     else f"Saved, but note: {why}"))
            else:
                self._post("log", f"✗ Could not save the key\n{err}", "bad")
                self.results.append(("API key", False, err[:200]))
        elif os.environ.get(_apikey.NAME) or _apikey.saved():
            if not os.environ.get(_apikey.NAME):
                _apikey.use(_apikey.saved())
            self._post("log", "· Keeping the key already on this PC", "dim")
            self.results.append(("API key", True, "Keeping the one already set up"))
        else:
            self._post("log", "· Key skipped; the program will ask again the first time you use it", "dim")
            self.results.append(("API key", True, "Skipped; you will be asked again the first time it runs"))

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
            self._post("log", "  ↻ Certificate check failed; retrying with the Windows certificate store…", "dim")
            ok2, err2 = self._run(base + ["--use-feature=truststore", spec], name)
            if ok2:
                self._post("log", "  ✓ Installed using the Windows certificate store", "ok")
                return True, ""
            err = err2 or err

        if self.trust_hosts:            # 使用者在結果頁按過「信任 PyPI 重試」
            self._post("log", "  ↻ Retrying with PyPI trusted…", "dim")
            ok3, err3 = self._run(
                base + ["--trusted-host", "pypi.org",
                        "--trusted-host", "files.pythonhosted.org",
                        "--trusted-host", "pypi.python.org", spec], name)
            if ok3:
                self._post("log", "  ✓ Installed", "ok")
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
            self.results.append(("The installer itself hit an error", False, traceback.format_exc()[-300:]))
            self._post("done", True)

    def __work(self):
        from shutil import which
        n = 0

        # 🔴 requirements.txt 釘 scipy>=1.18.0，而 scipy 1.18 要 Python 3.12 以上
        #    （沒有 cp311 的 wheel）。舊 Python 會在 pip 那一步噴一堆看不懂的
        #    編譯錯誤，不如先擋下來講清楚。
        if sys.version_info < (3, 12):
            v = ".".join(map(str, sys.version_info[:3]))
            self._post("log", f"✗ This PC has Python {v}, which is too old", "bad")
            self.results.append((
                "Python version", False,
                f"You have {v}; this tool needs 3.12 or later (required by its packages). Install 3.13 from python.org, or remove the old version and run 3_Install.bat again."))
            self._post("done", True)
            return

        # 0.5 解除「來自網路」封鎖
        # 🔴 刻意排在最前面：後面任何一步失敗或被取消，至少 4_開始使用.bat 和
        #    7_解除安裝.bat 已經不會再被 Windows 攔 —— 解除安裝被攔住最麻煩。
        #    點 3_安裝.bat 那一次的警告擋不掉（程式還沒開始跑），但只會有那一次。
        if self.blocked:
            n += 1
            self._post("step", "Unblocking files marked \"from the internet\"…", n)
            done, fail = unblock_files(self.blocked)
            msg = f"Unblocked {len(done)} file(s)"
            if fail:
                msg += "; could not unblock: " + ", ".join(fail)
            self._post("log", "✓ " + msg +
                       " (4_Start.bat will no longer show a warning when you click it)", "ok")
            self.results.append(("Unblock files marked \"from the internet\"", True, msg))

        # 1. ffmpeg
        n += 1
        self._post("step", "Checking ffmpeg…", n)
        if which("ffmpeg") and which("ffprobe"):
            self._post("log", "✓ ffmpeg is already on this PC", "ok")
            self.results.append(("ffmpeg", True, "Already installed"))
        elif which("winget") is None:
            self._post("log", "✗ No ffmpeg, and this PC has no winget either", "bad")
            self.results.append(("ffmpeg", False,
                                 "Download it from gyan.dev/ffmpeg/builds, unzip it and add its bin folder to PATH"))
        else:
            self._post("log", "· No ffmpeg; installing it with winget (this takes a moment)", "dim")
            ok, err = self._run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                                 "--accept-source-agreements",
                                 "--accept-package-agreements"], "ffmpeg")
            if ok:
                self._post("log", "✓ ffmpeg installed", "ok")
                self.results.append(("ffmpeg", True, "Installed (you may need to reopen the window before it can be found)"))
            else:
                self._post("log", f"✗ ffmpeg installation failed\n{err}", "bad")
                self.results.append(("ffmpeg", False, err[:200]))

        # 2. Python 套件（逐一裝，才看得到進度）
        for spec, name, why in self.pkgs:
            if self.cancelled.is_set():
                break
            n += 1
            self._post("step", f"Installing {name} ({why})…", n)
            self._post("log", f"· pip install {spec}", "dim")
            ok, err = self._pip(spec, name)
            if ok:
                self._post("log", f"✓ {name}", "ok")
                self.results.append((f"Package {name}", True, ""))
            else:
                self._post("log", f"✗ {name} could not be installed\n{err}", "bad")
                self.results.append((f"Package {name}", False, err[:200]))

        if self.cancelled.is_set():
            self.results.append(("Installation interrupted", False, "You pressed Cancel. Anything already installed is kept."))
            self._post("done", True)
            return

        # 3. 桌面捷徑
        if self.want_shortcut:
            n += 1
            self._post("step", "Creating the desktop shortcut…", n)
            ok, info = make_shortcut(START_BAT, ROOT)
            if ok:
                self._post("log", "✓ Desktop shortcut: " + info, "ok")
                self.results.append(("Desktop shortcut", True, info))
            else:
                self._post("log", f"✗ Could not create the shortcut\n{info}", "bad")
                self.results.append((
                    "Desktop shortcut", False,
                    (info or "")[:220] +
                    "  → This does not affect using the tool: just double-click 4_Start.bat in the folder."))

        # 3.5 清掉舊版殘留（使用者在同意頁勾選過才會走到這裡）
        if self.want_clean:
            n += 1
            self._post("step", "Cleaning up files left by an older version…", n)
            done, fail = [], []
            for p in self.legacy:
                try:
                    os.remove(p)
                    done.append(os.path.basename(p))
                except Exception as e:
                    fail.append(f"{os.path.basename(p)} ({e})")
            # 舊的桌面捷徑。remove_shortcut() 只認名字、不會去讀捷徑指向哪裡，
            # 所以這一步的把關是「這個資料夾裡確實有舊版殘留」（走到這裡就成立），
            # 而且名字是本工具自己用過的舊名，不是通用字眼。
            try:
                from _winpath import remove_shortcut
                for _legacy in LEGACY_SHORTCUTS:
                    ok_sc, info_sc = remove_shortcut(_legacy)
                    if ok_sc and "Deleted" in info_sc:
                        done.append(f"{_legacy} shortcut")
            except Exception:
                pass
            msg = ", ".join(done) if done else "Nothing needed cleaning up"
            if fail:
                msg += "; could not delete: " + ", ".join(fail)
            self._post("log", "✓ Old-version leftovers cleaned up: " + msg, "ok")
            self.results.append(("Clean up files left by an older version", True, msg))

        # 4. API 金鑰
        n += 1
        self._post("step", "Saving the API key…", n)
        self._save_key(self.api_key)

        self._post("step", "Done", self.total)
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
            input("\nThe installer ran into an error. Take a photo of the message above and report it as described under “When you're stuck” in 1_Install_Guide_READ_FIRST.md.\nPress Enter to close…")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
