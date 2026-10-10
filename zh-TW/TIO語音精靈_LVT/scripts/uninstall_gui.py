# -*- coding: utf-8 -*-
"""
解除安裝精靈（有視窗、逐項勾選、有進度）。

設計原則 —— 這支的危險性遠高於安裝，所以規則寫死在這裡：

  1. 預設只勾「這個工具專屬」的東西。
     Python 本身、ffmpeg、numpy、scipy 是**別的程式也可能在用的共用元件**，
     預設一律不勾，而且勾的時候會再警告一次。

  2. 🔴 絕對不碰使用者的產出。
     桌面上的逐字稿、字幕、對照檔是同事自己的資料，
     這支從頭到尾沒有任何一行程式碼會去刪它們。

  3. 先預覽、再執行。
     按下「開始移除」之前會把「實際會執行的動作」整份列出來再確認一次。
"""
import base64
import os
import queue
import shutil
import subprocess
import tempfile
import sys
import threading
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(ROOT, "requirements.txt")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _winpath import (desktop_dir, remove_shortcut,            # noqa: E402
                      shortcut_exists, shortcut_path)
from _ui import apply_icon, build_scrollable, fit              # noqa: E402

DESKTOP = desktop_dir()
SHORTCUT = shortcut_path()

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 這個工具專屬 vs 別人也可能在用 —— 決定預設要不要勾
EXCLUSIVE = {"google-genai", "sounddevice", "PyAudioWPatch"}
SHARED = {"numpy", "scipy"}


def read_packages():
    out = []
    try:
        with open(REQ, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line.split(">=")[0].split("==")[0].split("[")[0].strip())
    except Exception:
        out = ["google-genai", "sounddevice", "PyAudioWPatch", "numpy", "scipy"]
    return out


def installed_only(names):
    """names 裡真的裝在這個 Python 裡的那幾個。
    🔴 2026-09-20 筆電實測 N6-4：「專用套件」原本只看 requirements.txt 列了什麼，不管裝了沒有，
       移除過一次之後這一項照樣可以勾（重跑 pip uninstall 無害，但畫面在說假話）。
    查不出來（metadata 壞掉等）就當作有裝：寧可讓人勾，也不要把該移除的藏起來。"""
    from importlib import metadata
    out = []
    for n in names:
        try:
            metadata.version(n)
            out.append(n)
        except metadata.PackageNotFoundError:
            pass
        except Exception:
            out.append(n)
    return out


def excl_pkgs(ui):
    """真的裝著的專用套件：build_items 算過就用那份（ui.excl），沒算過就現在算。"""
    got = getattr(ui, "excl", None)
    return got if got is not None else installed_only([p for p in ui.pkgs if p in EXCLUSIVE])


def shared_pkgs(ui):
    """真的裝著的共用套件。跟 excl_pkgs 同一個道理（2026-09-20 使用者指示：共用套件也要查）：
    移除過一次之後這一項照樣可以勾，畫面等於在說假話。"""
    got = getattr(ui, "shar", None)
    return got if got is not None else installed_only([p for p in ui.pkgs if p in SHARED])


def genie_dir():
    """功能 6 的聲音輸出紀錄放的資料夾。🔴 退路要跟 _audioroute._state_path 一樣（沒有 LOCALAPPDATA 就用 %TEMP%）：
    原本退成空字串，會變成相對路徑、跟實際寫入的位置對不上（2026-09-20 複查指出）。"""
    return os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "TIO-Meeting-Genie")


GENIE_FILE = "audio_route.json"


def clear_genie_dir(menu_stays=True):
    """刪掉功能 6 留下的紀錄。回 (成功?, 說明)。menu_stays＝這次沒有連程式資料夾一起刪（之後還打得開選單）。

    🔴 2026-09-20 筆電實測 N6-5：解除安裝原本不清 %LOCALAPPDATA%\\TIO-Meeting-Genie。
    🔴 照這支程式的鐵則，不掃描、不遞迴刪：只刪自己知道檔名的那一個檔，資料夾空了才移除。
    🔴 紀錄還在＝上次功能 6 沒正常結束，聲音輸出可能還停在「聽不到」的那一顆：先照紀錄改回來再刪
       （_audioroute.recover_if_needed，跟選單開啟時做的是同一件事）。
       實際行為（2026-09-20 複查後照實寫）：改回**失敗**時 recover_if_needed 自己也會清掉紀錄，這時回報失敗、
       請使用者自己改回；紀錄還留著的只有兩種 —— 功能 6 正在另一個視窗跑（路線是它的，不能動），
       或改回的過程出錯。這兩種都不刪。
    """
    d = genie_dir()
    f = os.path.join(d, GENIE_FILE)
    note = ""
    if os.path.isfile(f):
        try:
            import _audioroute
            note = _audioroute.recover_if_needed() or ""
        except Exception as e:
            note = f"改回聲音輸出時出錯（{type(e).__name__}）"
        # 改回成功（或本來就是原本那顆）時 recover 會自己把紀錄清掉；還在＝沒改回來，或功能 6 正在另一個視窗跑
        if os.path.isfile(f):
            return False, ("聲音輸出沒辦法自動改回原本的喇叭（或功能 6 還開著），紀錄先留著"
                           + ("（下次打開選單會再試）。" if menu_stays else "。")
                           + "需要的話請點右下角喇叭圖示自己改回。" + (f"（{note}）" if note else ""))
    try:
        if os.path.isdir(d):
            os.rmdir(d)               # 只刪空資料夾：裡面有別的東西就留著，不去碰
    except OSError:
        return False, f"資料夾裡還有其他檔案，沒有刪：{d}"
    # recover_if_needed 改回失敗時也會清掉紀錄（它的說明裡有「失敗」），這時要報成失敗，不能打綠勾
    return (not ("失敗" in note or "出錯" in note)), note or "已刪除"


def _console(show):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)
    except Exception:
        pass


def has_key():
    """環境變數可能還沒傳播到這個行程，所以直接查登錄檔才準。"""
    if os.environ.get("GEMINI_API_KEY"):
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            winreg.QueryValueEx(k, "GEMINI_API_KEY")
        return True
    except Exception:
        return False


KEY_NAME = "GEMINI_API_KEY"


def remove_key(name=KEY_NAME):
    """把金鑰從使用者環境變數移除，並廣播讓其他視窗知道。

    name 參數只是為了讓開發端的回歸測試（該檔不隨附）能用一個假的變數名跑完全同一段程式碼，
    不必拿使用者真正的金鑰當白老鼠。正式使用時不要傳。
    """
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        return True, "本來就沒有"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    try:                                    # 通知系統環境變數改了
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
    except Exception:
        pass
    os.environ.pop(name, None)
    return True, ""


def _short_path(p):
    """拿 Windows 8.3 短路徑。拿不到（或磁碟關掉短檔名）就回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return None


def installed_by_winget(pkg_id):
    r = subprocess.run(["winget", "list", "--id", pkg_id, "-e"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NO_WINDOW)
    return r.returncode == 0 and pkg_id.lower() in (r.stdout or "").lower()


# ───────────────────────────────── GUI ─────────────────────────────────
import tkinter as tk
from tkinter import ttk, messagebox

BG = "#f7f7f5"
FG = "#1f1f1d"
MUTED = "#6b6b66"
DANGER = "#b3261e"
OK = "#1a7f4b"
WARN = "#8a5a00"
FONT = "Microsoft JhengHei UI"


def temp_audio():
    """
    找出這個工具留在 %TEMP% 的會議音訊暫存。

    🔴 這些是整場會議的**未加密原始聲音**。程式正常結束會自己刪，但被強制
       關閉（工作管理員、當機、直接按視窗 X）時 atexit 跑不到，檔案就會留下來，
       而且沒有人知道它在那裡。解除安裝的畫面主打「電腦要轉手時一定要移除」，
       漏掉這個說不過去。

    🔴 這裡刻意**不用 glob、也不用 os.walk**：整支解除安裝程式的鐵則是
       「絕不掃描、絕不刪除使用者的產出檔」，而萬用字元與遞迴走訪正是最容易
       失手的兩個工具（開發端的 scripts/test_uninstall.py 有靜態檢查把關，該檔不隨附）。
       這裡只列 %TEMP% 這一層，而且檔名必須完全符合本工具自己的暫存命名。
    """
    tmp = os.environ.get("TEMP") or tempfile.gettempdir()
    out = []
    try:
        names = os.listdir(tmp)
    except Exception:
        return out
    for n in names:
        low = n.lower()
        if not low.endswith(".wav"):
            continue
        # gs_chunk_* 是長會議切段時的暫存，單檔常常好幾百 MB，
        # 而且正是「被強制關掉」最容易留下的那一種。
        if not (low.startswith("bi_") or low.startswith("hq_")
                or low.startswith("gs_chunk_")
                or (low.startswith("gs_") and low.endswith("_16k.wav"))):
            continue
        p = os.path.join(tmp, n)
        if os.path.isfile(p):
            out.append(p)
    return sorted(out)


class Item:
    def __init__(self, key, label, detail, default, risky=False, present=True):
        self.key, self.label, self.detail = key, label, detail
        self.risky, self.present = risky, present
        self.var = tk.BooleanVar(value=default and present)


class Uninstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TIO — 解除安裝")
        apply_icon(self)
        self.configure(bg=BG)
        # 🔴 千萬不要改回 resizable(False, False)：螢幕比視窗矮的筆電上，
        #    「下一步」會掉到螢幕外面，整個解除安裝流程卡死。
        self.resizable(True, True)
        # 🔴 刪資料夾是排在「關閉之後」才執行的，而很多人習慣按右上角 X。
        #    不攔的話 _delete_cmd 永遠不會啟動，資料夾原封不動留著，
        #    但畫面上已經打勾說移除了。setup_gui.py 早就攔了，這支漏掉。
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.q = queue.Queue()
        self.results = []
        # 🔴 一定要在這裡先給預設值。folder_pending 原本只在 start() 才建立，
        #    而 WM_DELETE_WINDOW 綁的 finish() 會讀它 —— 使用者在還沒按
        #    「開始移除」之前按右上角 X，就會 AttributeError，
        #    tkinter 把例外吞進 stderr、視窗不關，看起來就是「按 X 沒反應」。
        self.folder_pending = False
        self.pkgs = read_packages()
        self.body, self.footer, self.canvas = build_scrollable(self, BG)
        self.build_items()
        self.page_pick()
        self.lift()
        self.focus_force()

    def fit(self):
        fit(self, self.body, self.footer)

    def clear(self):
        for c in self.body.winfo_children():
            c.destroy()
        for c in self.footer.winfo_children():
            c.destroy()

    def build_items(self):
        key_here = has_key()
        sc_here = shortcut_exists()
        _ta = temp_audio()
        excl = self.excl = installed_only([p for p in self.pkgs if p in EXCLUSIVE])
        shar = self.shar = installed_only([p for p in self.pkgs if p in SHARED])
        ff_here = bool(shutil.which("ffmpeg"))
        gd = genie_dir()
        gd_here = os.path.isdir(gd)
        gd_pending = os.path.isfile(os.path.join(gd, GENIE_FILE))

        self.items = [
            Item("key", "移除已儲存的 Gemini API 金鑰",
                 "存在環境變數 GEMINI_API_KEY。金鑰等同帳號密碼，"
                 "電腦要轉手或還給單位時一定要移除。"
                 + ("" if key_here else "　（目前查不到，本來就沒設）"),
                 default=True, present=key_here),
            Item("tempaudio", "刪除暫存的會議錄音",
                 (f"{len(_ta)} 個檔、共 {sum(os.path.getsize(f) for f in _ta) / 1048576:.0f} MB"
                  f"　（在 %TEMP%，是整場會議的原始聲音，程式被強制關掉時會留下來）"
                  if _ta else "（目前沒有殘留）"),
                 default=True, present=bool(_ta)),
            Item("shortcut", "刪除桌面捷徑",
                 SHORTCUT if sc_here else "（目前桌面上沒有這個捷徑）",
                 default=True, present=sc_here),
            Item("appdata", "刪除口譯功能（功能 6）留下的聲音輸出紀錄",
                 (gd + "　— 只記「口譯結束後要把聲音輸出改回哪一顆」，不是你的檔案。"
                  + ("\n⚠ 裡面有一筆還沒改回的紀錄（上次口譯沒有正常結束）：會先把聲音輸出改回原本那顆再刪。"
                     if gd_pending else "")) if gd_here else "（目前沒有）",
                 default=True, present=gd_here),
            Item("pkg_excl", "移除這個工具專用的 Python 套件",
                 ("、".join(excl) + "　— 只有這個工具在用，移除很安全。") if excl
                 else "（這台電腦上已經沒有裝了）",
                 default=True, present=bool(excl)),
            Item("pkg_shared", "移除共用的 Python 套件",
                 ("、".join(shar) + "　— ⚠ 很常見的通用套件，"
                  "你電腦上別的 Python 程式很可能也在用。不確定就不要勾。") if shar
                 else "（這台電腦上已經沒有裝了）",
                 default=False, risky=True, present=bool(shar)),
            # 🔴 2026-09-20 筆電全流程檢測（⚠-8）：這兩列原本沒傳 present=，所以沒裝也照樣勾得到、
            #    而且是橘色警告色。其他六列都有判斷。ffmpeg 用 PATH 上找不找得到判斷；
            #    Python 一定在（這支就是它跑起來的），維持 present=True 但寫清楚理由。
            Item("ffmpeg", "移除 ffmpeg",
                 ("⚠ 影音處理的通用工具，剪片軟體、下載器等也常常在用它。"
                  "不是這個工具裝的就別勾。") if ff_here else "（這台電腦的 PATH 上找不到 ffmpeg）",
                 default=False, risky=True, present=ff_here),
            Item("python", "移除 Python 3.13 本身",
                 "⚠ 風險最高。很多軟體靠 Python 執行，移除可能讓別的東西壞掉。"
                 "除非這台電腦是為了這個工具才第一次裝 Python，否則不要勾。"
                 f"　（這個解除安裝程式就是用 {'.'.join(map(str, sys.version_info[:2]))} 版的 Python 在跑）",
                 default=False, risky=True),
            Item("folder", "刪除這整個程式資料夾",
                 ROOT + "　— 會在其他項目都做完之後才刪。",
                 default=False, risky=True),
        ]

    # ───────────────────────── 第一頁：勾選 ─────────────────────────
    def page_pick(self):
        self.clear()
        tk.Label(self.body, text="要移除哪些東西？", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body,
                 text="每一項都可以自己決定。打勾的才會動，沒打勾的完全不碰。",
                 bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 10)).pack(fill="x", padx=28, pady=(0, 10))

        safe = tk.Frame(self.body, bg="#f0f7f2", highlightbackground="#cfe4d8",
                        highlightthickness=1)
        safe.pack(fill="x", padx=28)
        tk.Label(safe, text="🔒 這些絕對不會被刪",
                 bg="#f0f7f2", fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(safe,
                 text="你已經產出的逐字稿、字幕、雙語對照檔（桌面上那些 .md / .txt / .json）"
                      "全部保留。\n這支程式沒有任何一行會去碰它們。",
                 bg="#f0f7f2", fg="#2c5c44", anchor="w", justify="left",
                 font=(FONT, 9)).pack(fill="x", padx=12, pady=(2, 9))

        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28, pady=(12, 0))
        for it in self.items:
            r = tk.Frame(box, bg="white")
            r.pack(fill="x", padx=14, pady=(9, 0))
            cb = tk.Checkbutton(r, variable=it.var, bg="white", activebackground="white",
                                selectcolor="white", state="normal" if it.present else "disabled",
                                command=(lambda i=it: self.warn(i)) if it.risky else None)
            cb.pack(side="left", anchor="n")
            c = tk.Frame(r, bg="white")
            c.pack(side="left", fill="x", expand=True)
            tk.Label(c, text=it.label, bg="white",
                     fg=(FG if it.present else MUTED), anchor="w",
                     font=(FONT, 10, "bold")).pack(fill="x")
            # 🔴 沒東西可做的項目（present=False）一律灰色：橘色是「這裡有風險要看」的意思，
            #    拿來配「（這台電腦上已經沒有裝了）」會讓人以為有警告要處理（2026-09-20 複查指出）。
            tk.Label(c, text=it.detail, bg="white",
                     fg=(WARN if it.risky and it.present else MUTED), anchor="w", justify="left",
                     wraplength=520, font=(FONT, 9)).pack(fill="x")
        tk.Frame(box, bg="white", height=10).pack()

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="取消", command=self.destroy, width=10, cursor="hand2",
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG).pack(side="right")
        tk.Button(bar, text="下一步：確認清單", command=self.page_confirm, width=16,
                  cursor="hand2", font=(FONT, 10, "bold"), relief="flat",
                  bg=DANGER, fg="white", activeforeground="white",
                  activebackground="#8f1e18").pack(side="right", padx=(0, 8))
        self.fit()

    def warn(self, it):
        if not it.var.get():
            return
        if not messagebox.askyesno(
                "再確認一次",
                f"{it.label}\n\n{it.detail}\n\n真的要一併移除嗎？"):
            it.var.set(False)

    # ───────────────────────── 第二頁：確認 ─────────────────────────
    def page_confirm(self):
        picked = [i for i in self.items if i.var.get() and i.present]
        if not picked:
            messagebox.showinfo("沒有勾選任何項目", "一項都沒勾，沒有東西要移除。")
            return
        self.picked = picked
        self.clear()
        tk.Label(self.body, text="最後確認", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body, text="按下「開始移除」之後，會依序執行下面這些動作：",
                 bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 10)).pack(fill="x", padx=28, pady=(0, 10))

        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28)
        for i, act in enumerate(self.plan(), 1):
            tk.Label(box, text=f"{i}.  {act}", bg="white", fg=FG, anchor="w",
                     justify="left", wraplength=540,
                     font=("Consolas", 9)).pack(fill="x", padx=14, pady=(8 if i == 1 else 3, 0))
        tk.Frame(box, bg="white", height=10).pack()

        tk.Label(self.body,
                 text="其餘的東西（包含你的逐字稿與字幕檔）一律保留。",
                 bg=BG, fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=28, pady=(12, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="上一步", command=self.page_pick, width=10, cursor="hand2",
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG).pack(side="right")
        tk.Button(bar, text="開始移除", command=self.start, width=12, cursor="hand2",
                  font=(FONT, 10, "bold"), relief="flat", bg=DANGER, fg="white",
                  activeforeground="white",
                  activebackground="#8f1e18").pack(side="right", padx=(0, 8))
        self.fit()

    def plan(self):
        keys = {i.key for i in self.picked}
        acts = []
        if "key" in keys:
            acts.append("刪除環境變數 GEMINI_API_KEY（HKCU\\Environment）")
        if "tempaudio" in keys:
            _n = len(temp_audio())
            acts.append(f"刪除 %TEMP% 裡 {_n} 個會議錄音暫存檔")
        if "shortcut" in keys:
            acts.append(f"刪除 {SHORTCUT}")
        if "appdata" in keys:
            acts.append(f"刪除 {os.path.join(genie_dir(), GENIE_FILE)}，資料夾空了就一起移除"
                        "（有還沒改回的聲音輸出紀錄時，先把聲音輸出改回原本那顆）")
        if "pkg_excl" in keys:
            acts.append("pip uninstall -y " + " ".join(excl_pkgs(self)))
        if "pkg_shared" in keys:
            acts.append("pip uninstall -y " + " ".join(shared_pkgs(self)))
        if "ffmpeg" in keys:
            acts.append("winget uninstall --id Gyan.FFmpeg -e")
        if "python" in keys:
            acts.append("winget uninstall --id Python.Python.3.13 -e")
        if "folder" in keys:
            # 🔴 2026-09-20 筆電全流程檢測（⚠-13）：這是清單裡最具破壞性的一項，原本卻只印一行中文，
            #    其他項目都看得到實際指令。照實把背後跑的東西寫出來（不寫出 base64 內容，寫它做哪幾步）。
            acts.append(f"刪除資料夾 {ROOT}（最後一步，等這個視窗關閉後才執行）\n"
                        f"     實際執行：powershell -NoProfile -NonInteractive -WindowStyle Hidden "
                        f"-EncodedCommand <內嵌腳本>\n"
                        f"     那段腳本會：等這支程式結束 → 關掉開在這個資料夾裡的檔案總管視窗 → 清除唯讀屬性 →\n"
                        f"     把資料夾改名搬到它隔壁（同一個磁碟）→ 由深到淺逐一刪除 → 失敗就跳中文對話框說明\n"
                        f"     （刪除的對象只有這個資料夾；搬移的暫存名稱是 _gs_removed_<編號>，刪不掉時會留在原地隔壁）")
        return acts

    # ───────────────────────── 第三頁：進度 ─────────────────────────
    def page_progress(self):
        self.clear()
        tk.Label(self.body, text="移除中", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body, text="請不要關掉這個視窗。", bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 10)).pack(fill="x", padx=28, pady=(0, 10))
        self.pb = ttk.Progressbar(self.body, mode="determinate",
                                  maximum=len(self.picked), length=560)
        self.pb.pack(padx=28, pady=(0, 6))
        self.now = tk.Label(self.body, text="準備中…", bg=BG, fg=FG, anchor="w",
                            font=(FONT, 10, "bold"))
        self.now.pack(fill="x", padx=28)
        f = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                     highlightthickness=1)
        f.pack(fill="both", expand=True, padx=28, pady=(8, 0))
        self.log = tk.Text(f, height=11, width=68, bg="white", fg=FG, bd=0,
                           font=("Consolas", 9), wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self.log.tag_configure("ok", foreground=OK)
        self.log.tag_configure("bad", foreground=DANGER)
        self.log.tag_configure("dim", foreground=MUTED)
        tk.Frame(self.body, bg=BG, height=16).pack()
        self.fit()

    def page_done(self):
        self.clear()
        bad = [r for r in self.results if not r[1]]
        tk.Label(self.body, text="移除完成" if not bad else "部分項目沒有移除成功",
                 bg=BG, fg=FG, font=(FONT, 17, "bold")).pack(anchor="w", padx=28,
                                                             pady=(24, 8))
        box = tk.Frame(self.body, bg="white", highlightbackground="#e0e0dc",
                       highlightthickness=1)
        box.pack(fill="x", padx=28)
        for name, ok, detail in self.results:
            r = tk.Frame(box, bg="white")
            r.pack(fill="x", padx=14, pady=(8, 0))
            tk.Label(r, text="✓" if ok else "✗", bg="white", fg=OK if ok else DANGER,
                     width=2, font=(FONT, 11, "bold")).pack(side="left", anchor="n")
            c = tk.Frame(r, bg="white")
            c.pack(side="left", fill="x", expand=True)
            tk.Label(c, text=name, bg="white", fg=FG, anchor="w",
                     font=(FONT, 10)).pack(fill="x")
            if detail:
                tk.Label(c, text=detail, bg="white", fg=MUTED if ok else DANGER,
                         anchor="w", justify="left", wraplength=500,
                         font=(FONT, 9)).pack(fill="x")
        tk.Frame(box, bg="white", height=10).pack()

        tk.Label(self.body,
                 text="你的逐字稿、字幕、對照檔都還在原本的位置，一個都沒動。",
                 bg=BG, fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=28, pady=(14, 0))
        if self.folder_pending:
            tk.Label(self.body,
                     text="按下「關閉」之後，程式資料夾才會被刪掉（本程式正在裡面執行）。",
                     bg=BG, fg=WARN, anchor="w", justify="left",
                     font=(FONT, 9)).pack(fill="x", padx=28, pady=(4, 0))
        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="關閉", command=self.finish, width=12, cursor="hand2",
                  font=(FONT, 10, "bold"), relief="flat", bg="#e6e6e2",
                  fg=FG).pack(side="right")

        self.fit()

    # ───────────────────────────── 執行 ─────────────────────────────
    def start(self):
        self.folder_pending = False
        self.page_progress()
        threading.Thread(target=self._work, daemon=True).start()
        self.after(80, self._pump)

    def say(self, t, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", t + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

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
                    self.page_done()
                    return
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _run(self, cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=NO_WINDOW)
        except FileNotFoundError:
            return False, f"找不到指令 {cmd[0]}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if r.returncode == 0:
            return True, ""
        tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-5:])
        return False, tail or f"錯誤碼 {r.returncode}"

    def _work(self):
        try:
            self.__work()
        except Exception:
            self._post("log", traceback.format_exc(), "bad")
            self.results.append(("解除安裝程式本身出錯", False,
                                 traceback.format_exc()[-300:]))
            self._post("done")

    def __work(self):
        keys = {i.key for i in self.picked}
        n = 0

        if "key" in keys:
            n += 1
            self._post("step", "移除 API 金鑰…", n)
            ok, msg = remove_key()
            self._post("log", ("✓ 金鑰已從環境變數移除" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("Gemini API 金鑰", ok,
                                 msg or "已經開著的視窗要重開才會反映"))

        if "tempaudio" in keys:
            n += 1
            self._post("step", "刪除暫存的會議錄音…", n)
            files = temp_audio()
            freed, bad = 0, 0
            for f in files:
                try:
                    sz = os.path.getsize(f)
                    os.remove(f)
                    freed += sz
                except Exception:
                    bad += 1        # 還開著的檔刪不掉，很正常，不要當成失敗
            msg = (f"{len(files) - bad} 個檔、{freed / 1048576:.0f} MB"
                   + (f"（{bad} 個正在使用中，沒有刪）" if bad else ""))
            self._post("log", f"✓ 暫存錄音已清除：{msg}", "ok")
            self.results.append(("暫存的會議錄音", True, msg))

        if "shortcut" in keys:
            n += 1
            self._post("step", "刪除桌面捷徑…", n)
            ok, msg = remove_shortcut()
            self._post("log", ("✓ 桌面捷徑已刪除" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("桌面捷徑", ok, msg))

        if "appdata" in keys:
            n += 1
            self._post("step", "刪除口譯功能的聲音輸出紀錄…", n)
            ok, msg = clear_genie_dir(menu_stays="folder" not in keys)
            self._post("log", ("✓ 聲音輸出紀錄已刪除" if ok else f"✗ {msg}"), "ok" if ok else "bad")
            self.results.append(("口譯功能的聲音輸出紀錄", ok, msg))

        for grp, names, label in (
                ("pkg_excl", excl_pkgs(self), "專用套件"),
                ("pkg_shared", shared_pkgs(self), "共用套件")):
            if grp not in keys or not names:
                continue
            n += 1
            self._post("step", f"移除{label}…", n)
            self._post("log", "· pip uninstall -y " + " ".join(names), "dim")
            ok, msg = self._run([sys.executable, "-m", "pip", "uninstall", "-y",
                                 "--disable-pip-version-check"] + names)
            self._post("log", (f"✓ {label}已移除：" + "、".join(names)) if ok
                       else f"✗ {msg}", "ok" if ok else "bad")
            self.results.append((f"{label}（{'、'.join(names)}）", ok, msg[:200]))

        for grp, wid, label in (("ffmpeg", "Gyan.FFmpeg", "ffmpeg"),
                                ("python", "Python.Python.3.13", "Python 3.13")):
            if grp not in keys:
                continue
            n += 1
            self._post("step", f"移除 {label}…", n)
            if shutil.which("winget") is None:
                self._post("log", f"✗ 這台電腦沒有 winget，無法自動移除 {label}", "bad")
                self.results.append((label, False,
                                     "沒有 winget。請到「設定 → 應用程式」手動移除。"))
                continue
            if not installed_by_winget(wid):
                self._post("log", f"· winget 裡查不到 {label}，可能不是用 winget 裝的", "dim")
                self.results.append((label, False,
                                     "winget 沒有這筆紀錄（不是它裝的）。"
                                     "請到「設定 → 應用程式」確認後手動移除。"))
                continue
            ok, msg = self._run(["winget", "uninstall", "--id", wid, "-e",
                                 "--accept-source-agreements"])
            self._post("log", (f"✓ {label} 已移除" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append((label, ok, msg[:200]))

        if "folder" in keys:
            n += 1
            self._post("step", "安排刪除程式資料夾…", n)
            ok, msg = self.schedule_folder_delete()
            self.folder_pending = ok
            self._post("log", ("✓ 已排定：關閉本視窗後就會刪除" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("程式資料夾", ok, msg or f"關閉後刪除 {ROOT}"))

        self._post("step", "完成", len(self.picked))
        self._post("done")

    def schedule_folder_delete(self):
        """
        不能刪掉自己正在執行的資料夾，所以交給一個外部行程，等本程式關閉後再動手。

        🔴 為什麼不用批次檔：批次檔是用主控台的 OEM 字碼頁讀的，而同事的資料夾
        路徑很可能有中文（C:\\Users\\王小明\\Desktop\\TIO語音精靈）。8.3 短路徑
        在中文資料夾上仍然含中文（實測 "測試中~1"），改 chcp 也不安全——cmd 讀
        批次檔是按位元組偏移量 seek 的，換字碼頁後多位元組字元會失步。
        所以改用 PowerShell，路徑當成**參數**傳進去，走 Unicode 命令列，
        完全不經過字碼頁。
        """
        if not os.path.isdir(ROOT):
            return False, "找不到程式資料夾"
        # 🔴 不能用 powershell -Command "…" <路徑>：-Command 之後的東西會被當成
        #    指令的一部分，不會變成 $args。改用 -EncodedCommand（base64 的
        #    UTF-16LE），路徑直接寫進腳本裡，引號與字碼頁問題一次消失。
        #
        # 🔴 2026-09-07 同事回報：桌面上的資料夾刪不掉，Windows 反過來要求
        #    系統管理員權限。原本這裡只是「睡 2 秒 → Remove-Item -Force →
        #    失敗就靜默算了」，使用者只會看到一個賴在桌面上刪不掉的資料夾、
        #    完全沒有線索。改成五步：
        #      1. 等本程式的行程真的結束（不是盲目睡 2 秒就動手）
        #      2. 清掉唯讀屬性
        #      3. 先試著改名搬到同一層的暫存資料夾 _gs_removed_<編號>（沒有東西鎖住時，
        #         這樣桌面立刻乾淨；09-10 起不用 %TEMP%，原因見下面）
        #         ⚠ 實測修正：Windows **不允許**改名一個「裡面有東西被開著」的資料夾
        #           （檔案被開著——10-10 實測帶不帶 FILE_SHARE_DELETE 都一樣——或某個
        #           行程的工作目錄停在裡面），所以這一步不是萬靈丹，只是能救到
        #           「目錄本身沒被鎖、只是內容多」的情況。
        #      4. 由深到淺逐個刪，單一個鎖住的檔案不會讓整批放棄
        #      5. 真的失敗就**跳一個中文對話框**告訴使用者怎麼辦
        #         （早期版本只寫紀錄到 %TEMP%，等於沒講——沒人會去看那裡）
        pid = os.getpid()
        # 🔴 暫存區必須跟目標在**同一個磁碟**，不能用 %TEMP%。
        #    2026-09-10 實測：跨磁碟時 Move-Item 是「逐檔複製再刪除」，
        #    中途卡住會變成「一半的檔已經被搬走、$moved 卻是 False」，
        #    於是程式跳過刪除、對話框對使用者說「一個都沒有刪」——那是假的，
        #    而且被搬走的正好包含解除安裝程式和救援工具。
        #    🔴 2026-10-10 更正：同磁碟的 Move-Item **也不是**單純改名。裡面有東西被
        #    別的程式開著（檔案被開著，不管有沒有帶 FILE_SHARE_DELETE；或某個行程的
        #    工作目錄停在裡面的子資料夾）時整個改名會失敗，Windows PowerShell 5.1 的
        #    Move-Item 接著改成一個一個檔搬，搬到搬不動的那一個才丟例外 → 同一個病
        #    （實測：鎖 1 個檔，12～28 個檔跑進 _gs_removed_<pid>，含 7_、8_ 兩支 .bat；
        #    工作目錄停在 scripts\ 時 32 個檔全跑掉；對話框都說一個都沒有刪）。
        #    所以改用 [IO.Directory]::Move：只做真正的改名，要嘛整個成功、要嘛完全
        #    不動；跨磁碟時直接丟例外，不會退回逐檔複製。
        #    取捨：檔案被「允許刪除」的方式開著時（防毒、索引、雲端同步常這樣開），舊寫法
        #    逐檔搬會碰巧整個成功；新寫法先每秒再試、最多試 5 次（見下面），還是被佔用就整個
        #    不動、跳對話框——寧可不動，也不要拆成兩半。
        stage = os.path.join(os.path.dirname(os.path.abspath(ROOT)),
                             "_gs_removed_%d" % pid)
        note = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                            "TIO_移除紀錄.txt")

        def q(s):
            return s.replace("'", "''")

        self._delete_script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "for ($i=0; $i -lt 60; $i++) {"
            " if (-not (Get-Process -Id " + str(pid) + " -ErrorAction SilentlyContinue))"
            " { break }; Start-Sleep -Milliseconds 500 }; "
            "Start-Sleep -Milliseconds 800; "
            "$t='" + q(ROOT) + "'; $s='" + q(stage) + "'; $g='" + q(note) + "'; "
            # 🔴 2026-09-07 實證：同事那台刪不掉，真正的原因就是**檔案總管開著
            #    這個資料夾**。這種佔用用程序清單查不到（explorer.exe 的路徑和
            #    指令列都不會提到該資料夾），所以直接列舉開著的檔案總管視窗、
            #    把指向這個資料夾的關掉。不關掉別人的視窗。
            "try { $sh = New-Object -ComObject Shell.Application; "
            " foreach ($w in @($sh.Windows())) {"
            "  $loc = $null; try { $loc = $w.Document.Folder.Self.Path } catch {}; "
            "  if ($loc -and ($loc -eq $t -or $loc.StartsWith($t + [char]92,"
            "   [StringComparison]::OrdinalIgnoreCase))) { try { $w.Quit() } catch {} } };"
            " Start-Sleep -Milliseconds 1200 } catch {}; "
            "Get-ChildItem -LiteralPath $t -Recurse -Force | ForEach-Object {"
            " if ($_.Attributes -band [IO.FileAttributes]::ReadOnly) {"
            " $_.Attributes = $_.Attributes -bxor [IO.FileAttributes]::ReadOnly } }; "
            "$moved=$false; "
            # 🔴 2026-10-10（使用者裁決）：改名失敗先隔 1 秒再試，最多試 5 次（約多等 4 秒）——
            #    防毒、索引、雲端同步、剛關掉的檔案總管常常只佔用幾秒。改名是全有全無，重試不會拆成兩半。
            "for ($k=1; $k -le 5 -and -not $moved; $k++) {"
            " try { [IO.Directory]::Move($t, $s); $moved=$true }"
            " catch { if ($k -lt 5) { Start-Sleep -Milliseconds 1000 } } }; "
            # 🔴 改名失敗就停手，絕對不能往下逐檔刪除。
            #    舊版失敗後照樣把資料夾裡的東西刪光（含 1~8 全部手冊、
            #    解除安裝程式、救援工具），結果是「資料夾還在，但東西全沒了」，
            #    比不動更糟。scripts/rescue.ps1 早就修好這一條，這支漏掉沒跟上。
            "if ($moved) { "
            " Get-ChildItem -LiteralPath $s -Recurse -Force |"
            "  Sort-Object FullName -Descending | ForEach-Object {"
            "  Remove-Item -LiteralPath $_.FullName -Force -Recurse }; "
            " Remove-Item -LiteralPath $s -Force -Recurse; "
            "} "
            # 失敗要「看得到」：寫紀錄之外，直接跳一個中文對話框告訴使用者怎麼辦。
            # 只寫檔到 %TEMP% 等於沒講，沒有人會去那裡看。
            "if (Test-Path -LiteralPath $t) {"
            " $m = '這個資料夾沒有刪成功，還留在：' + [char]10 + $t + [char]10 + [char]10 +"
            " '通常是因為還有程式正在使用裡面的檔案' + [char]10 +"
            " '（最常見的是檔案總管正開著這個資料夾）。' + [char]10 + [char]10 +"
            " '為了安全起見，裡面的檔案一個都沒有刪，你的東西都還在。' + [char]10 + [char]10 +"
            " '請照這個順序處理：' + [char]10 +"
            " '  1. 關掉所有相關的視窗（特別是開著這個資料夾的檔案總管），再手動刪一次' + [char]10 +"
            " '  2. 還是不行就重新開機，開機後第一件事就是刪它' + [char]10 +"
            " '  3. 再不行就點兩下資料夾裡的「8_刪不掉時救援.bat」，它會告訴你是誰在佔用'; "
            " $m | Out-File -LiteralPath $g -Encoding UTF8; "
            " Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            " [System.Windows.Forms.MessageBox]::Show($m, 'TIO — 資料夾沒刪掉',"
            " [System.Windows.Forms.MessageBoxButtons]::OK,"
            " [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null }")
        enc = base64.b64encode(self._delete_script.encode("utf-16-le")).decode("ascii")
        self._delete_cmd = [
            "powershell", "-NoProfile", "-NonInteractive",
            "-WindowStyle", "Hidden", "-EncodedCommand", enc,
        ]
        return True, ""

    def finish(self):
        # getattr 全程防身：這支同時是「關閉」按鈕和右上角 X 的處理器，
        # 任何一頁都可能被呼叫，不能假設哪個屬性已經存在。
        cmd = getattr(self, "_delete_cmd", None)
        if getattr(self, "folder_pending", False) and cmd:
            # 🔴 這裡的旗標是實測出來的，不要改成看起來更「正確」的 DETACHED_PROCESS：
            #    DETACHED_PROCESS 會讓 PowerShell 沒有主控台可用而立刻死掉，
            #    資料夾就不會被刪（而且完全沒有錯誤訊息）。實測四種組合只有
            #    CREATE_NO_WINDOW 有效，而且本程式關閉後它仍然活著把事做完。
            try:
                subprocess.Popen(
                    cmd,
                    creationflags=NO_WINDOW,
                    cwd=os.environ.get("TEMP", os.path.expanduser("~")),
                    close_fds=True)
            except Exception as e:
                self.delete_error = f"{type(e).__name__}: {e}"
                messagebox.showerror(
                    "資料夾沒刪成功",
                    "程式資料夾沒有刪掉：\n%s\n\n請直接在檔案總管裡手動刪除：\n%s"
                    % (self.delete_error, ROOT))
                return
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    _console(False)
    try:
        Uninstaller().mainloop()
    except Exception:
        _console(True)
        traceback.print_exc()
        try:
            input("\n解除安裝程式出錯了。請把上面的訊息拍下來，照「1_安裝說明（先讀這個）」的「卡住的時候」回報。按 Enter 關閉…")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
