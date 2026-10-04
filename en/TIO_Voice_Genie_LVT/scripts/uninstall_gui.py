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
            note = f"error while restoring the sound output ({type(e).__name__})"
        # 改回成功（或本來就是原本那顆）時 recover 會自己把紀錄清掉；還在＝沒改回來，或功能 6 正在另一個視窗跑
        if os.path.isfile(f):
            return False, ("The sound output could not be switched back to the original speakers automatically (or feature 6 is still open), so the record is kept for now"
                           + (" (the menu will try again the next time you open it)." if menu_stays else ".")
                           + " If needed, click the speaker icon at the bottom right and switch it back yourself." + (f" ({note})" if note else ""))
    try:
        if os.path.isdir(d):
            os.rmdir(d)               # 只刪空資料夾：裡面有別的東西就留著，不去碰
    except OSError:
        return False, f"The folder still has other files in it, so it was not deleted: {d}"
    # recover_if_needed 改回失敗時也會清掉紀錄（它的說明裡有「失敗」），這時要報成失敗，不能打綠勾
    return (not ("failed" in note or "error" in note)), note or "Deleted"


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
        return True, "It was not there to begin with"
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
        self.title("TIO — Uninstall")
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
            Item("key", "Remove the saved Gemini API key",
                 "Stored in the environment variable GEMINI_API_KEY. The key is as good as a password: always remove it before you hand the PC on or return it to your organisation."
                 + ("" if key_here else "  (Not found right now; it was never set)"),
                 default=True, present=key_here),
            Item("tempaudio", "Delete the temporary meeting recordings",
                 (f"{len(_ta)} file(s), {sum(os.path.getsize(f) for f in _ta) / 1048576:.0f} MB in total  (in %TEMP%; the raw audio of whole meetings, left behind when the program is force-closed)"
                  if _ta else "(None left behind right now)"),
                 default=True, present=bool(_ta)),
            Item("shortcut", "Delete the desktop shortcut",
                 SHORTCUT if sc_here else "(This shortcut is not on the desktop right now)",
                 default=True, present=sc_here),
            Item("appdata", "Delete the sound-output record left by interpreter mode (feature 6)",
                 (gd + "  — It only notes \"which device to switch the sound output back to after interpreting\"; it is not one of your files."
                  + ("\n⚠ It holds a pending record: the last interpreter-mode session did not end normally, so the sound output has not been switched back yet. The sound output will first be switched back to the original device, then the record is deleted."
                     if gd_pending else "")) if gd_here else "(None right now)",
                 default=True, present=gd_here),
            Item("pkg_excl", "Remove the Python packages only this tool uses",
                 (", ".join(excl) + "  — Only this tool uses them, so removing them is safe.") if excl
                 else "(No longer installed on this PC)",
                 default=True, present=bool(excl)),
            Item("pkg_shared", "Remove the shared Python packages",
                 (", ".join(shar) + "  — ⚠ Very common general-purpose packages; other Python programs on your PC are quite likely to use them too. If unsure, leave this unticked.") if shar
                 else "(No longer installed on this PC)",
                 default=False, risky=True, present=bool(shar)),
            # 🔴 2026-09-20 筆電全流程檢測（⚠-8）：這兩列原本沒傳 present=，所以沒裝也照樣勾得到、
            #    而且是橘色警告色。其他六列都有判斷。ffmpeg 用 PATH 上找不找得到判斷；
            #    Python 一定在（這支就是它跑起來的），維持 present=True 但寫清楚理由。
            Item("ffmpeg", "Remove ffmpeg",
                 ("⚠ A general-purpose audio/video tool that video editors, downloaders and the like often use as well. If this tool did not install it, leave it unticked.") if ff_here else "(ffmpeg cannot be found on this PC's PATH)",
                 default=False, risky=True, present=ff_here),
            Item("python", "Remove Python 3.13 itself",
                 f"⚠ Highest risk. Many programs rely on Python, and removing it may break other things. Leave it unticked unless Python was installed on this PC for the first time just for this tool.  (This uninstaller itself is running on Python {'.'.join(map(str, sys.version_info[:2]))})",
                 default=False, risky=True),
            Item("folder", "Delete this whole program folder",
                 ROOT + "  — Deleted only after all the other items are done.",
                 default=False, risky=True),
        ]

    # ───────────────────────── 第一頁：勾選 ─────────────────────────
    def page_pick(self):
        self.clear()
        tk.Label(self.body, text="What do you want to remove?", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body,
                 text="You decide each item yourself. Only ticked items are acted on;\nanything unticked is left completely alone.",
                 bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 10)).pack(fill="x", padx=28, pady=(0, 10))

        safe = tk.Frame(self.body, bg="#f0f7f2", highlightbackground="#cfe4d8",
                        highlightthickness=1)
        safe.pack(fill="x", padx=28)
        tk.Label(safe, text="🔒 These are never deleted",
                 bg="#f0f7f2", fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(safe,
                 text="All the transcripts, captions and bilingual documents you have made\n(the .md / .txt / .json files on your desktop) are kept.\nNot a single line of this program touches them.",
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
        tk.Button(bar, text="Cancel", command=self.destroy, width=10, cursor="hand2",
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG).pack(side="right")
        tk.Button(bar, text="Next: review list", command=self.page_confirm, width=16,
                  cursor="hand2", font=(FONT, 10, "bold"), relief="flat",
                  bg=DANGER, fg="white", activeforeground="white",
                  activebackground="#8f1e18").pack(side="right", padx=(0, 8))
        self.fit()

    def warn(self, it):
        if not it.var.get():
            return
        if not messagebox.askyesno(
                "Please confirm",
                f"{it.label}\n\n{it.detail}\n\nDo you really want to remove this as well?"):
            it.var.set(False)

    # ───────────────────────── 第二頁：確認 ─────────────────────────
    def page_confirm(self):
        picked = [i for i in self.items if i.var.get() and i.present]
        if not picked:
            messagebox.showinfo("Nothing selected", "Nothing is ticked, so there is nothing to remove.")
            return
        self.picked = picked
        self.clear()
        tk.Label(self.body, text="Final check", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body, text="When you press \"Start removing\", the following actions will run in order:",
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
                 text="Everything else (including your transcripts and caption files) is kept.",
                 bg=BG, fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=28, pady=(12, 0))

        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="Back", command=self.page_pick, width=10, cursor="hand2",
                  font=(FONT, 10), relief="flat", bg="#e6e6e2", fg=FG).pack(side="right")
        tk.Button(bar, text="Start removing", command=self.start, width=12, cursor="hand2",
                  font=(FONT, 10, "bold"), relief="flat", bg=DANGER, fg="white",
                  activeforeground="white",
                  activebackground="#8f1e18").pack(side="right", padx=(0, 8))
        self.fit()

    def plan(self):
        keys = {i.key for i in self.picked}
        acts = []
        if "key" in keys:
            acts.append("Delete the environment variable GEMINI_API_KEY (HKCU\\Environment)")
        if "tempaudio" in keys:
            _n = len(temp_audio())
            acts.append(f"Delete {_n} temporary meeting recording file(s) in %TEMP%")
        if "shortcut" in keys:
            acts.append(f"Delete {SHORTCUT}")
        if "appdata" in keys:
            acts.append(f"Delete {os.path.join(genie_dir(), GENIE_FILE)}, and the folder too if it is then empty (if the record shows the sound output has not been switched back yet, it is first switched back to the original device)")
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
            acts.append(f"Delete the folder {ROOT} (last step; runs only after this window is closed)\n     What actually runs: powershell -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand <embedded script>\n     That script will: wait for this program to exit → close File Explorer windows open in this folder → clear read-only attributes →\n     rename the folder and move it beside the original (same drive) → delete from the deepest level up → if that fails, show a dialog explaining what to do\n     (Only this folder is deleted. It is first renamed to _gs_removed_<number>; if that renamed folder cannot be deleted, it is left right next to where the original folder was)")
        return acts

    # ───────────────────────── 第三頁：進度 ─────────────────────────
    def page_progress(self):
        self.clear()
        tk.Label(self.body, text="Removing", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        tk.Label(self.body, text="Please do not close this window.", bg=BG, fg=MUTED, anchor="w",
                 font=(FONT, 10)).pack(fill="x", padx=28, pady=(0, 10))
        self.pb = ttk.Progressbar(self.body, mode="determinate",
                                  maximum=len(self.picked), length=560)
        self.pb.pack(padx=28, pady=(0, 6))
        self.now = tk.Label(self.body, text="Preparing…", bg=BG, fg=FG, anchor="w",
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
        tk.Label(self.body, text="Removal complete" if not bad else "Some items could not be removed",
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
                 text="Your transcripts, captions and bilingual files are all still where they were;\nnot a single one was touched.",
                 bg=BG, fg=OK, anchor="w",
                 font=(FONT, 9, "bold")).pack(fill="x", padx=28, pady=(14, 0))
        if self.folder_pending:
            tk.Label(self.body,
                     text="The program folder is deleted only after you press \"Close\"\n(this program is running inside it).",
                     bg=BG, fg=WARN, anchor="w", justify="left",
                     font=(FONT, 9)).pack(fill="x", padx=28, pady=(4, 0))
        bar = tk.Frame(self.footer, bg=BG, highlightbackground="#e0e0dc",
                       highlightthickness=1)
        bar.pack(fill="x", ipady=8)
        tk.Button(bar, text="Close", command=self.finish, width=12, cursor="hand2",
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
            return False, f"Command not found: {cmd[0]}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if r.returncode == 0:
            return True, ""
        tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-5:])
        return False, tail or f"Error code {r.returncode}"

    def _work(self):
        try:
            self.__work()
        except Exception:
            self._post("log", traceback.format_exc(), "bad")
            self.results.append(("The uninstaller itself hit an error", False,
                                 traceback.format_exc()[-300:]))
            self._post("done")

    def __work(self):
        keys = {i.key for i in self.picked}
        n = 0

        if "key" in keys:
            n += 1
            self._post("step", "Removing the API key…", n)
            ok, msg = remove_key()
            self._post("log", ("✓ Key removed from the environment variables" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("Gemini API key", ok,
                                 msg or "Any window that is already open must be reopened to see the change"))

        if "tempaudio" in keys:
            n += 1
            self._post("step", "Deleting the temporary meeting recordings…", n)
            files = temp_audio()
            freed, bad = 0, 0
            for f in files:
                try:
                    sz = os.path.getsize(f)
                    os.remove(f)
                    freed += sz
                except Exception:
                    bad += 1        # 還開著的檔刪不掉，很正常，不要當成失敗
            msg = (f"{len(files) - bad} file(s), {freed / 1048576:.0f} MB"
                   + (f" ({bad} still in use, not deleted)" if bad else ""))
            self._post("log", f"✓ Temporary recordings cleared: {msg}", "ok")
            self.results.append(("Temporary meeting recordings", True, msg))

        if "shortcut" in keys:
            n += 1
            self._post("step", "Deleting the desktop shortcut…", n)
            ok, msg = remove_shortcut()
            self._post("log", ("✓ Desktop shortcut deleted" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("Desktop shortcut", ok, msg))

        if "appdata" in keys:
            n += 1
            self._post("step", "Deleting the sound-output record of interpreter mode (feature 6)…", n)
            ok, msg = clear_genie_dir(menu_stays="folder" not in keys)
            self._post("log", ("✓ Sound-output record deleted" if ok else f"✗ {msg}"), "ok" if ok else "bad")
            self.results.append(("Sound-output record of interpreter mode (feature 6)", ok, msg))

        for grp, names, label in (
                ("pkg_excl", excl_pkgs(self), "This tool's packages"),
                ("pkg_shared", shared_pkgs(self), "Shared packages")):
            if grp not in keys or not names:
                continue
            n += 1
            self._post("step", f"{label}: removing…", n)
            self._post("log", "· pip uninstall -y " + " ".join(names), "dim")
            ok, msg = self._run([sys.executable, "-m", "pip", "uninstall", "-y",
                                 "--disable-pip-version-check"] + names)
            self._post("log", (f"✓ {label} removed: " + ", ".join(names)) if ok
                       else f"✗ {msg}", "ok" if ok else "bad")
            self.results.append((f"{label} ({', '.join(names)})", ok, msg[:200]))

        for grp, wid, label in (("ffmpeg", "Gyan.FFmpeg", "ffmpeg"),
                                ("python", "Python.Python.3.13", "Python 3.13")):
            if grp not in keys:
                continue
            n += 1
            self._post("step", f"Removing {label}…", n)
            if shutil.which("winget") is None:
                self._post("log", f"✗ This PC has no winget, so {label} cannot be removed automatically", "bad")
                self.results.append((label, False,
                                     "No winget. Please remove it yourself in \"Settings → Apps\"."))
                continue
            if not installed_by_winget(wid):
                self._post("log", f"· {label} is not listed in winget; it was probably not installed with winget", "dim")
                self.results.append((label, False,
                                     "winget has no record of it (it was not installed by winget). Please check in \"Settings → Apps\" and remove it yourself."))
                continue
            ok, msg = self._run(["winget", "uninstall", "--id", wid, "-e",
                                 "--accept-source-agreements"])
            self._post("log", (f"✓ {label} removed" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append((label, ok, msg[:200]))

        if "folder" in keys:
            n += 1
            self._post("step", "Scheduling deletion of the program folder…", n)
            ok, msg = self.schedule_folder_delete()
            self.folder_pending = ok
            self._post("log", ("✓ Scheduled: it will be deleted as soon as you close this window" if ok else f"✗ {msg}"),
                       "ok" if ok else "bad")
            self.results.append(("Program folder", ok, msg or f"{ROOT} will be deleted after you close this window"))

        self._post("step", "Done", len(self.picked))
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
            return False, "Cannot find the program folder"
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
        #      3. 先試著改名搬到 %TEMP%（沒有東西鎖住時，這樣桌面立刻乾淨）
        #         ⚠ 實測修正：Windows **不允許**改名一個「裡面有檔案被開著」的
        #           資料夾（開檔沒帶 FILE_SHARE_DELETE 時），所以這一步不是萬靈丹，
        #           只是能救到「目錄本身沒被鎖、只是內容多」的情況。
        #      4. 由深到淺逐個刪，單一個鎖住的檔案不會讓整批放棄
        #      5. 真的失敗就**跳一個中文對話框**告訴使用者怎麼辦
        #         （早期版本只寫紀錄到 %TEMP%，等於沒講——沒人會去看那裡）
        pid = os.getpid()
        # 🔴 暫存區必須跟目標在**同一個磁碟**，不能用 %TEMP%。
        #    2026-09-10 實測：跨磁碟時 Move-Item 是「逐檔複製再刪除」，
        #    中途卡住會變成「一半的檔已經被搬走、$moved 卻是 False」，
        #    於是程式跳過刪除、對話框對使用者說「一個都沒有刪」——那是假的，
        #    而且被搬走的正好包含解除安裝程式和救援工具。
        #    同磁碟的 Move-Item 是單純改名：要嘛整個成功、要嘛完全不動。
        stage = os.path.join(os.path.dirname(os.path.abspath(ROOT)),
                             "_gs_removed_%d" % pid)
        note = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                            "TIO_removal_log.txt")

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
            "try { Move-Item -LiteralPath $t -Destination $s -ErrorAction Stop; "
            "$moved=$true } catch {}; "
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
            " $m = 'This folder could not be deleted. It is still here:' + [char]10 + $t + [char]10 + [char]10 +"
            " 'This is usually because a program is still using a file inside it' + [char]10 +"
            " '(most often, File Explorer has this folder open).' + [char]10 + [char]10 +"
            " 'To be safe, not a single file inside was deleted. All your files are still there.' + [char]10 + [char]10 +"
            " 'Please try these steps in order:' + [char]10 +"
            " '  1. Close every related window (especially File Explorer showing this folder), then delete it by hand again' + [char]10 +"
            " '  2. If that does not work, restart the PC and delete it before doing anything else' + [char]10 +"
            " '  3. If it still will not delete, double-click “8_Rescue_Undeletable_Folder.bat” in the folder; it tells you what is using it'; "
            " $m | Out-File -LiteralPath $g -Encoding UTF8; "
            " Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            " [System.Windows.Forms.MessageBox]::Show($m, 'TIO — Folder not deleted',"
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
                    "Folder not deleted",
                    "The program folder was not deleted:\n%s\n\nPlease delete it yourself in File Explorer:\n%s"
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
            input("\nThe uninstaller ran into an error. Take a photo of the message above and report it as described under “When you're stuck” in 1_Install_Guide_READ_FIRST.md.\nPress Enter to close…")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
