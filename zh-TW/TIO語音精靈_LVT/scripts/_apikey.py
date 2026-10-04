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
        return "（沒有）"
    if len(key) < 12:
        return f"（共 {len(key)} 字，太短不顯示）"
    return f"{key[:5]}…{key[-4:]}（共 {len(key)} 字）"


def format_problem(key):
    """回 (等級, 說明)。等級 None＝看起來像金鑰；"bad"＝一定不是；"odd"＝不像但不敢說錯，交給 verify()。"""
    if not key:
        return "bad", "沒有收到任何字。"
    if re.search(r"\s", key):
        return "bad", "中間有空白或換行，可能連同別的文字一起貼上了。"
    if not re.fullmatch(r"[\x21-\x7e]+", key):
        return "bad", "裡面有中文、全形字或其他特殊字元，可能貼錯了。"
    if key.startswith("AIza") and len(key) != 39:
        return "bad", f"AIza 開頭的金鑰是 39 個字，這組是 {len(key)} 個，可能少貼或多貼了。"
    if not key.startswith(("AIza", "AQ.")):
        return "odd", "開頭不像 Gemini API 金鑰（通常是 AIza… 或 AQ.…）。"
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
        return "ok", "金鑰有效。"
    except urllib.error.HTTPError as e:
        try:
            low = e.read(4000).decode("utf-8", "replace").lower()
        except Exception:
            low = ""
        if e.code == 429:
            # V1.31：專案的「每月花費上限」到了——等一下也不會好，要去 AI Studio 調高、或等下個月（見 _live.diagnose）
            if re.search(r"spend(ing)?.?cap", low):
                return "ok", ("金鑰有效，但這個 Google 專案本月的花費上限到了，下個月 1 號前都不能用；"
                              "要馬上用：到 aistudio.google.com 的「Spend」調高「Monthly spend cap」。")
            return "ok", "金鑰有效，但目前用量已到上限，等一下再用。"
        if e.code in (400, 401, 403) and re.search(r"api.?key|permission|unauthenticated|credential", low):
            if "expired" in low:
                return "bad", "Google 說這組金鑰已經過期。"
            if "leak" in low:
                return "bad", "Google 說這組金鑰曾經外流、已被停用，請到 aistudio.google.com/apikey 換一組新的。"
            return "bad", "Google 說這組金鑰不能用（打錯、已刪除、被停用，或沒開通 Gemini API）。"
        return "unknown", f"Google 回了 HTTP {e.code}，暫時判斷不了這組金鑰。"
    except Exception:
        return "unknown", "連不上 Google（沒有網路，或公司／學校網路擋住），暫時沒辦法確認。"


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
        print("\n✗ 這個視窗的 GEMINI_API_KEY 是空的（變數在，但沒有內容）。")
        print("  這種情況不會去讀你記住的那一組金鑰（避免測試或腳本偷連網）。")
        print("  → 想用記住的金鑰：關掉這個視窗，改從 4_開始使用.bat 的選單進去。")
        print("  → 想在這個視窗跑：先設好環境變數再重跑（cmd 用 set、PowerShell 用 $env:）。")
        print("     🔴 金鑰等同帳號密碼：設定時畫面會留下明文，設過之後不要把整個視窗截圖給別人。")
        return None
    key = saved() or ""
    if key:
        use(key)
        return key
    print("\n✗ 找不到 Gemini API 金鑰。")
    print("  請先點兩下 4_開始使用.bat，在選單按 9、選 1「換一組新的金鑰」貼上，問要不要記住時選「要」；")
    print("  或在這個視窗先執行 set GEMINI_API_KEY=你的金鑰 再重跑。")
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
