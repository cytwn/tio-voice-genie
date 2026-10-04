# -*- coding: utf-8 -*-
"""
Windows 桌面路徑與捷徑的共用工具。

🔴 為什麼不能用 os.path.join(expanduser("~"), "Desktop")：
   公司／學校電腦只要接了 OneDrive（M365 環境幾乎必然），桌面會被重新導向到
   「%USERPROFILE%\\OneDrive\\Desktop」或「OneDrive - 某某大學\\Desktop」。
   這時候拼出來的 ~\\Desktop 根本不存在 —— 捷徑建不起來，逐字稿也會存到
   一個使用者看不到的地方。正確做法是問 Windows 本人（known folder API）。
"""
import base64
import ctypes
import os
import subprocess
import sys

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _decode(b):
    """
    PowerShell 的錯誤訊息是用主控台字碼頁（繁中 Windows 是 cp950）輸出的，
    直接當 UTF-8 解會變成一整片問號 —— 使用者拍照回報時我們就看不到真正的錯誤。
    先試 UTF-8，再試系統 ANSI 字碼頁。
    """
    if not b:
        return ""
    for enc in ("utf-8", "mbcs" if sys.platform == "win32" else "latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_byte * 8)]


# FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
_FOLDERID_DESKTOP = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                          (ctypes.c_byte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                              0x9A, 0x87, 0xC6, 0x41))


def _from_known_folder():
    try:
        buf = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(_FOLDERID_DESKTOP), 0, None, ctypes.byref(buf))
        if hr == 0 and buf.value:
            p = buf.value
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return p
    except Exception:
        pass
    return None


def _from_registry():
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v = winreg.QueryValueEx(k, "Desktop")[0]
        return os.path.expandvars(v)
    except Exception:
        return None


def desktop_dir():
    """回傳這台電腦真正的桌面資料夾。三層備援，最後才用拼的。"""
    for get in (_from_known_folder, _from_registry):
        p = get()
        if p and os.path.isdir(p):
            return p
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "桌面")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(home, "Desktop")     # 真的都找不到才回這個


def _short_or(p):
    """回傳 8.3 短路徑（通常是純 ASCII）；拿不到就回原路徑。"""
    if sys.platform != "win32":
        return p
    try:
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024) and buf.value:
            return buf.value
    except Exception:
        pass
    return p


def _desktop_writable():
    """實際寫一個小檔試試看。公司電腦的『受控資料夾存取』就是擋在這裡。"""
    probe = os.path.join(desktop_dir(), "._gs_write_probe.tmp")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except Exception:
            pass
        return False


def icon_file():
    """
    視窗與捷徑共用的圖示：assets 底下那顆 .ico。

    刻意**不寫死檔名**：圖示檔名必須等於桌面捷徑名（make_shortcut 由捷徑名推導），
    寫死就會變成第二個權威落點，改名時一定有一邊忘記改。打包白名單只放一顆 .ico，
    所以「assets 裡的第一顆 .ico」就是它。
    找不到就回 None —— 圖示純屬外觀，缺檔絕不能讓程式跑不起來。
    """
    try:
        assets = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
        for f in sorted(os.listdir(assets)):
            if f.lower().endswith(".ico"):
                return os.path.join(assets, f)
    except Exception:
        pass
    return None


def set_console_icon():
    """
    把圖示掛到主控台視窗（選單本體是 cmd 視窗，標題列圖示不是 tkinter 管得到的）。

    🔴 一定要設 restype／argtypes：64 位元下 HICON 是指標，ctypes 預設把回傳值
       當 c_int 會把 handle 截半，WM_SETICON 收到一個無效 handle —— 不報錯、沒效果。
    🔴 Windows Terminal 不吃 WM_SETICON（標籤頁圖示它自己管），這時候是安靜沒效果，
       不是錯誤；傳統主控台（conhost）才會換。所以一律當「有就好」處理。
    """
    if sys.platform != "win32":
        return False
    p = icon_file()
    if not p:
        return False
    try:
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        u32.LoadImageW.restype = ctypes.c_void_p
        u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u32.SendMessageW.restype = ctypes.c_void_p
        u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_void_p]
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return False
        done = False
        # ICON_BIG=1（Alt-Tab／工作列）、ICON_SMALL=0（標題列）要各設一次
        for wparam, px in ((1, 32), (0, 16)):
            h = u32.LoadImageW(None, p, 1, px, px, 0x0010)   # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                u32.SendMessageW(ctypes.c_void_p(hwnd), 0x0080,      # WM_SETICON
                                 ctypes.c_void_p(wparam), ctypes.c_void_p(h))
                done = True
        return done
    except Exception:
        return False


ZONE_ADS = ":Zone.Identifier"     # NTFS 的「這個檔案來自網路」標記（額外資料流）


def zone_marked_files(folder):
    """
    列出 folder 底下被 Windows 貼上「來自網路」標記的檔案。只讀，不動任何東西。

    🔴 病根（2026-09-18，兩位同事的電腦）：從 Email／雲端拿到的 .zip，Windows 會在
       壓縮檔上貼這個標記，**解壓縮時還會蓋到裡面的檔案上**。實測（同一顆 zip）：
         ‧ WinRAR 解壓 → 29 個檔只蓋 6 個，剛好是 5 支 .bat ＋ scripts/rescue.ps1
         ‧ 檔案總管解壓 → 29 個檔全蓋
       於是安裝、開始使用、解除安裝（全是 .bat）每次點都被當成可疑程式擋下來，
       而 .md 說明檔完全正常 —— 看起來像被學校政策封鎖，其實只是這個標記。
       同一顆 zip 先「解除封鎖」再解壓，一個都不會被蓋。

    非 NTFS（FAT32／exFAT 隨身碟）沒有這種資料流，會回空清單。
    """
    out = []
    if sys.platform != "win32":
        return out
    for root, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.exists(p + ZONE_ADS):
                    out.append(p)
            except Exception:
                pass
    return out


def unblock_files(paths):
    """
    清掉「來自網路」標記，等同於檔案總管裡的「內容 → 解除封鎖」。回傳 (清掉的, 失敗的)。

    做法是直接刪掉 NTFS 的 Zone.Identifier 資料流：**檔案本身一個位元組都不動**
    （實測 11,776 bytes 的 .bat 刪完還是 11,776 bytes），不需要系統管理員權限，
    也不必叫 PowerShell。
    本來就沒有標記的檔案會噴 FileNotFoundError，那是正常結果、不算失敗。
    """
    done, fail = [], []
    for p in paths:
        try:
            os.remove(p + ZONE_ADS)
            done.append(p)
        except FileNotFoundError:
            pass
        except Exception as e:
            fail.append(f"{os.path.basename(p)}（{e}）")
    return done, fail


def shortcut_path(name="TIO語音精靈"):
    return os.path.join(desktop_dir(), name + ".lnk")


def make_shortcut(target_bat, workdir, name="TIO語音精靈"):
    """
    在桌面建立捷徑。回傳 (成功, 說明)。

    多層備援，因為公司電腦擋東西的方式很多：
      1. PowerShell + WScript.Shell（正常路徑）
         🔴 一定要用 -EncodedCommand，不能用 -Command。實測（2026-09-07，同事的
            電腦，資料夾放在 OneDrive 底下）：路徑含中文時用 -Command 會噴
            「剖析錯誤 字元:264」，捷徑建不出來。-EncodedCommand 收 base64 的
            UTF-16LE，完全不經過字碼頁，中文路徑一律安全。
         🔴 也要帶 -ExecutionPolicy Bypass，很多機關把預設政策設成 Restricted。
      2. 退而求其次：在桌面放一個 .bat 啟動器（不是捷徑，但點兩下一樣能用）
    """
    dst = os.path.join(desktop_dir(), name + ".lnk")
    errors = []

    # ── 1. PowerShell ──
    # 沒有指定圖示的話，Windows 會用 .bat 的預設齒輪圖 —— 很醜也認不出來。
    icon = os.path.join(workdir, "assets", name + ".ico")
    icon_line = ("$s.IconLocation = '%s,0'; " % icon.replace("'", "''")
                 if os.path.isfile(icon) else "")
    ps = ("$ErrorActionPreference='Stop'; "
          "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
          "$s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
          "%s"
          "$s.Description = 'TIO Voice Genie'; $s.Save()"
          % (dst.replace("'", "''"), target_bat.replace("'", "''"),
             workdir.replace("'", "''"), icon_line))
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            capture_output=True, creationflags=NO_WINDOW, timeout=60)
        if os.path.exists(dst):
            return True, dst
        errors.append("PowerShell: " + (_decode(r.stdout) + _decode(r.stderr)).strip()
                      or f"PowerShell: 回傳碼 {r.returncode}，但檔案沒出現")
    except Exception as e:
        errors.append(f"PowerShell: {type(e).__name__}: {e}")

    # ── 2. 桌面 .bat 啟動器 ──
    # 🔴 不能用 encoding="ascii" 寫：路徑有中文就會丟 UnicodeEncodeError，
    #    而且檔案已經開好了，會在桌面留下一個只有 "@echo off" 的壞檔。
    #    先試 8.3 短路徑（多半是純 ASCII），不行才用系統 ANSI 字碼頁（cmd 就是用它讀的）。
    bat = os.path.join(desktop_dir(), name + ".bat")
    tgt, wd = _short_or(target_bat), _short_or(workdir)
    # 🔴 用 call，不要用 start ""：start 開 .bat 會用 cmd /K，而 4_開始使用.bat 自己會另開選單
    #    視窗再結束，結果多留一個停在提示字元、標題一樣的空白視窗（2026-09-11 稽核抓到）。
    body = '@echo off\r\ncd /d "%s"\r\ncall "%s"\r\n' % (wd, tgt)
    for enc in ("ascii", "mbcs"):
        try:
            with open(bat, "wb") as f:
                f.write(body.encode(enc))
            if os.path.getsize(bat) > 20:
                return True, (bat + "　（這台電腦不讓程式建立捷徑，改放了一個 .bat "
                                    "啟動器，點兩下一樣能用。）")
        except Exception as e:
            errors.append(f".bat 備援({enc}): {type(e).__name__}: {e}")
            try:
                if os.path.exists(bat) and os.path.getsize(bat) < 20:
                    os.remove(bat)          # 別在桌面留下半截的壞檔
            except Exception:
                pass

    # ── 3. 連桌面都寫不進去：講清楚，不要只丟一串英文 ──
    if not _desktop_writable():
        return False, ("這台電腦不允許程式寫入桌面（常見於公司電腦的防毒"
                       "「受控資料夾存取」或群組原則）。"
                       "不影響使用——直接點資料夾裡的 4_開始使用.bat 就好，"
                       "或自己在 4_開始使用.bat 上按右鍵→傳送到→桌面(建立捷徑)。")
    return False, "　/　".join(errors)[:400]


def remove_shortcut(name="TIO語音精靈"):
    """把捷徑和 .bat 備援都清掉。回傳 (成功, 說明)。"""
    d = desktop_dir()
    removed, errs = [], []
    for f in (os.path.join(d, name + ".lnk"), os.path.join(d, name + ".bat")):
        if os.path.exists(f):
            try:
                os.remove(f)
                removed.append(os.path.basename(f))
            except Exception as e:
                errs.append(f"{os.path.basename(f)}: {type(e).__name__}: {e}")
    if errs:
        return False, "　/　".join(errs)
    if removed:
        return True, "已刪除 " + "、".join(removed)
    return True, "本來就不存在"


def shortcut_exists(name="TIO語音精靈"):
    d = desktop_dir()
    return (os.path.exists(os.path.join(d, name + ".lnk"))
            or os.path.exists(os.path.join(d, name + ".bat")))


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    print("known folder :", _from_known_folder())
    print("registry     :", _from_registry())
    print("拼字串       :", os.path.join(os.path.expanduser("~"), "Desktop"))
    print("最後採用     :", desktop_dir())
    print("桌面存在     :", os.path.isdir(desktop_dir()))
    print("捷徑已存在   :", shortcut_exists())
