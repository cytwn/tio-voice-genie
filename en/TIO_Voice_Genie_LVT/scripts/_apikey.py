# -*- coding: utf-8 -*-
"""API 金鑰：讀取、遮蔽顯示、檢查格式、連線驗證、記住／清除。安裝精靈與選單共用這一支。

🔴 金鑰等同帳號密碼：畫面上一律只顯示 mask() 過的樣子；驗證時放在 x-goog-api-key 標頭，不放進網址。
🔴 setx 只寫登錄檔，「存金鑰之前就已經開著」的程式（例如安裝精靈自己）和它開出來的視窗都讀不到。
   所以讀的時候一定要退回去直接讀登錄檔（saved()），不能只看 os.environ。
   2026-09-19 使用者回報：安裝時貼過金鑰，從「立即開始使用」開的選單一選功能又要再貼一次。
"""
import os
import re
import sys

NAME = "GEMINI_API_KEY"
_VERIFY_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"


def mask(key):
    key = (key or "").strip()
    if not key:
        return "(none)"
    if len(key) < 12:
        return f"({len(key)} characters, too short to show)"
    return f"{key[:5]}…{key[-4:]} ({len(key)} characters)"


def format_problem(key):
    """回 (等級, 說明)。等級 None＝看起來像金鑰；"bad"＝一定不是；"odd"＝不像但不敢說錯，交給 verify()。"""
    if not key:
        return "bad", "Nothing was received."
    if re.search(r"\s", key):
        return "bad", "It contains spaces or line breaks; other text may have been pasted along with it."
    if not re.fullmatch(r"[\x21-\x7e]+", key):
        return "bad", "It contains Chinese, full-width or other special characters; it may be the wrong text."
    if key.startswith("AIza") and len(key) != 39:
        return "bad", f"Keys starting with AIza are 39 characters long; this one has {len(key)}, so part of it may be missing or extra."
    if not key.startswith(("AIza", "AQ.")):
        return "odd", "It does not start like a Gemini API key (usually AIza… or AQ.…)."
    return None, ""


def verify(key, timeout=10):
    """問 Google 一次「可用模型清單」（不計費）確認金鑰能用。

    回 ("ok" | "bad" | "unknown", 中文說明)。"unknown"＝連不上或判斷不了，呼叫端照樣收下，
    不可以因為網路問題就把可能是對的金鑰擋掉。
    """
    # 🔴 格式一定錯的先擋：金鑰要放進 HTTP 標頭，含中文／全形／隱形字元或換行時 http.client
    #    在連線之前就丟例外，下面的 except 會把它誤報成「連不上 Google」，使用者就一直去查網路
    level, why = format_problem(key)
    if level == "bad":
        return "bad", why
    import urllib.error
    import urllib.request
    req = urllib.request.Request(_VERIFY_URL, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(1)
        return "ok", "The key works."
    except urllib.error.HTTPError as e:
        try:
            low = e.read(4000).decode("utf-8", "replace").lower()
        except Exception:
            low = ""
        if e.code == 429:
            # V1.31：專案的「每月花費上限」到了——等一下也不會好，要去 AI Studio 調高、或等下個月（見 _live.diagnose）
            if re.search(r"spend(ing)?.?cap", low):
                return "ok", ("The key works, but this Google project has reached its monthly spend cap and can't be used until the 1st of next month. To use it right away: at aistudio.google.com, open Spend and raise the Monthly spend cap.")
            return "ok", "The key works, but its usage limit has been reached for now; try again later."
        if e.code in (400, 401, 403) and re.search(r"api.?key|permission|unauthenticated|credential", low):
            if "expired" in low:
                return "bad", "Google says this key has expired."
            if "leak" in low:
                return "bad", "Google says this key was leaked and has been disabled; please create a new one at aistudio.google.com/apikey."
            return "bad", "Google says this key cannot be used (mistyped, deleted, disabled, or the Gemini API is not enabled)."
        return "unknown", f"Google replied HTTP {e.code}; the key cannot be checked right now."
    except Exception:
        return "unknown", "Cannot reach Google (no internet, or blocked by the office/campus network), so the key cannot be checked right now."


def saved():
    """記在 Windows 使用者環境變數（HKCU\\Environment）裡的金鑰；沒有回 None。"""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, t = winreg.QueryValueEx(k, NAME)
    except OSError:
        return None
    if t == winreg.REG_EXPAND_SZ:
        v = os.path.expandvars(v)
    v = str(v).strip().strip('"')
    return v or None


def use(key):
    """這個視窗（以及之後從它開的程式）用這組金鑰。"""
    os.environ[NAME] = key


def for_script():
    """給各支程式單獨執行時用：環境變數沒有就讀記住的那一組；都沒有就用中文說明、回 None。

    🔴 2026-09-20 筆電實測 N6-3：子程式原本只讀 os.environ["GEMINI_API_KEY"]，照 README 的命令列用法直接跑時
       （金鑰是在選單或安裝精靈裡記住的、不在這個視窗的環境變數裡），一開始就丟英文 KeyError。
    🔴 只有「這個視窗根本沒有這個變數」才去讀記住的那一組。變數在（即使是空字串）就原樣照用、跟以前一樣：
       空字串＝有人刻意清掉（多支離線測試就靠設成空字串保證絕不連網），不可以偷偷換成登錄檔裡的真金鑰。
    🔴 2026-09-20 筆電全流程檢測（⚠-4）：空字串回的是 ""、不是 None，而五個呼叫點只擋 `is None`，
       於是拿空金鑰去打 Google，畫面說「金鑰可能打錯、被停用」，把使用者導去查一把好好的金鑰。
       **呼叫端一律寫 `if not key:`**（空字串跟 None 一樣：不建立 client、直接結束）——
       離線測試那句「保證不連網」也要這樣才真的成立。
    """
    if NAME in os.environ:
        val = os.environ[NAME].strip()
        if val:
            return val
        # 變數在、但是空的：不可以偷偷改用登錄檔裡記住的那一組（離線測試就靠這個保證不連網），
        # 但也要把原因講清楚 —— 舊版在這裡回 ""，呼叫端拿空金鑰去連網，畫面說「金鑰可能打錯」。
        print("\n✗ GEMINI_API_KEY in this window is empty (the variable exists but has no value).")
        print("  In that case the key you saved is not used (so tests or scripts cannot quietly go online).")
        print("  → To use the saved key: close this window and start from the menu (4_Start.bat).")
        print("  → To run in this window: set the environment variable first, then run again (cmd: set, PowerShell: $env:).")
        print("     🔴 The key is as good as a password: setting it leaves it in plain text on screen, so do not share screenshots of this window afterwards.")
        return None
    key = saved() or ""
    if key:
        use(key)
        return key
    print("\n✗ No Gemini API key found.")
    print("  Double-click 4_Start.bat first, press 9 in the menu, choose 1 (Change to a new key) and paste the key; when asked whether to remember it, choose \"Yes\";")
    print("  or run  set GEMINI_API_KEY=your_key  in this window first, then run again.")
    return None


def remember(key):
    """記進 Windows 使用者環境變數，下次開程式直接讀得到。回 (成功?, 錯誤訊息)。"""
    use(key)
    import subprocess
    try:
        subprocess.run(["setx", NAME, key], capture_output=True, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}"


def forget():
    """刪掉記住的金鑰，這個視窗也不再使用。回 (有沒有刪到東西, 錯誤訊息)。"""
    os.environ.pop(NAME, None)
    if sys.platform != "win32":
        return False, ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
    except FileNotFoundError:
        return False, ""
    except OSError as e:
        return False, str(e)
    _broadcast_env_change()
    return True, ""


def _broadcast_env_change():
    """通知檔案總管環境變數變了（setx 會自己做，直接改登錄檔要自己補），之後雙擊開的程式才讀得到新值。"""
    try:
        import ctypes
        from ctypes import wintypes
        res = wintypes.DWORD()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000,
                                                 ctypes.byref(res))
    except Exception:
        pass


def _clipboard_text():
    import ctypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)                     # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def read_secret(prompt, out=None):
    """在主控台讀金鑰：每收到一個字印一個 *，貼上之後看得到有沒有進去（舊版 getpass 完全沒反應，
    使用者以為貼不上去）。有些主控台把 Ctrl+V 當成一個字元送進來而不是貼上，這時自己讀剪貼簿。
    """
    out = out or sys.stdout
    try:
        import msvcrt
    except ImportError:
        import getpass
        return getpass.getpass(prompt)
    if sys.stdin is None or not sys.stdin.isatty():
        return input(prompt)
    out.write(prompt)
    out.flush()
    buf = []

    def add(ch):
        if ch >= " " and ch != "\x7f":
            buf.append(ch)
            out.write("*")

    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            if not buf and msvcrt.kbhit():
                continue      # 貼上的內容開頭就是換行、後面還有字：不是使用者按了 Enter
            break
        if ch == "\x03":
            out.write("\n")
            out.flush()
            raise KeyboardInterrupt
        if ch in ("\x00", "\xe0"):                       # 方向鍵等功能鍵：後面還跟一碼，丟掉
            msvcrt.getwch()
            continue
        if ch == "\x16":
            for c in _clipboard_text().strip():
                add(c)
        elif ch in ("\b", "\x7f"):
            if buf:
                buf.pop()
                out.write("\b \b")
        else:
            add(ch)
        out.flush()
    # 🔴 同一次貼上剩下的（第二行、多貼的字）一律丟掉。留著的話會被下一個一般的 input()
    #    讀走，而主控台會把它**明文顯示**在畫面上——金鑰就這樣露出來了。
    drain_input()
    out.write("\n")
    out.flush()
    return "".join(buf)


def drain_input():
    """把主控台裡還沒讀的按鍵全部丟掉（貼上殘留、驗證時多按的 Enter）。"""
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:
        pass
