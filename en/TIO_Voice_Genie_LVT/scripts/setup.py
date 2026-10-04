# -*- coding: utf-8 -*-
"""
安裝流程的第二階段（中文介面）。

第一階段（3_安裝.bat）只負責一件事：確認電腦上真的有可以執行的 Python。
確認之後就把棒子交給這支，因為 Python 處理中文和錯誤訊息比批次檔可靠太多。
"""
import os
import subprocess
import sys

if __name__ == "__main__":
    sys.stdout = __import__("io").TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = lambda s, c: f"\033[{c}m{s}\033[0m"
BOLD, DIM, GRN, YEL, RED, CYAN = "1", "2", "32", "33", "31", "36"


def step(n, total, msg):
    print(C(f"\n[{n}/{total}] {msg}", BOLD))


def run(cmd, desc):
    """跑一個指令，失敗時把真正的錯誤印出來（不要只說『請看上面』）。"""
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return True
    print(C(f"  ✗ {desc} failed (error code {r.returncode})", RED))
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if out:
        print(C("  ── The actual error message ──", DIM))
        for line in out.splitlines()[-15:]:
            print("  " + line)
    else:
        print(C("  (This command produced no output)", DIM))
    return False


def main():
    total = 4
    print(C("\n  TIO — Setup", BOLD))
    print(C("  " + "=" * 40, DIM))
    print(f"  Python in use: {sys.version.split()[0]}  ({sys.executable})")

    # 🔴 scipy>=1.18 需要 Python 3.12 以上，舊版會在 pip 噴看不懂的編譯錯誤
    if sys.version_info < (3, 12):
        v = ".".join(map(str, sys.version_info[:3]))
        print()
        print(C(f"  ✗ This PC has Python {v}, which is too old.", RED))
        print("    This tool needs 3.12 or later (required by its packages).")
        print("    Install 3.13 from python.org, or remove the old version and run 3_Install.bat again.")
        return 1

    # ── 1. 解除「來自網路」封鎖 ──
    # 🔴 排在最前面：後面失敗也不會害到 4_開始使用.bat 和 7_解除安裝.bat。
    #    視窗版（setup_gui.py）有同一步，兩條路都要做，不然沒有 tkinter 的電腦
    #    會變成「備援路徑漏掉修正」。
    step(1, total, "Unblock files marked \"from the internet\"")
    try:
        from _winpath import unblock_files, zone_marked_files
        marked = zone_marked_files(ROOT)
        if not marked:
            print(C("  ✓ No files are marked by Windows", GRN))
        else:
            done, fail = unblock_files(marked)
            print(C(f"  ✓ Unblocked {len(done)} file(s)", GRN))
            if fail:
                print(C("  Could not unblock: " + ", ".join(fail), YEL))
    except Exception as e:
        print(C(f"  (Skipped; this does not affect the installation) {e}", DIM))

    # ── 2. ffmpeg ──
    step(2, total, "Check for ffmpeg (used to process audio)")
    from shutil import which
    if which("ffmpeg") and which("ffprobe"):
        print(C("  ✓ Already installed", GRN))
    else:
        print("  Not found; trying to install it automatically with winget…")
        if which("winget") is None:
            print(C("  ✗ This PC has no winget, so it cannot be installed automatically.", RED))
            print("    Please download it yourself from https://www.gyan.dev/ffmpeg/builds/,")
            print("    unzip it and add the bin folder inside it to the system PATH.")
        else:
            ok = run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                      "--accept-source-agreements", "--accept-package-agreements"],
                     "ffmpeg installation")
            if ok:
                print(C("  ✓ Installed (you may need to reopen this window before it can be found)", GRN))

    # ── 3. Python 套件 ──
    step(3, total, "Install the Python packages")
    req = os.path.join(ROOT, "requirements.txt")
    if not os.path.exists(req):
        print(C(f"  ✗ Cannot find {req}", RED))
        return 1
    print(C("  (The first installation may take a few minutes; please do not close the window)", DIM))
    if not run([sys.executable, "-m", "pip", "install", "-r", req], "Package installation"):
        print(C("\n  Common causes: no internet connection, or an office firewall blocking PyPI.", YEL))
        return 1
    print(C("  ✓ All packages installed", GRN))

    # ── 4. API 金鑰 ──
    step(4, total, "Set up the Gemini API key")
    import _apikey
    if os.environ.get(_apikey.NAME) or _apikey.saved():
        print(C("  ✓ Already set up", GRN))
    else:
        print("  You need a free Google Gemini API key.")
        print(C("  Get one at: https://aistudio.google.com/apikey", CYAN))
        print(C("  (Sign in with your Google account → Create API key → copy it)", DIM))
        # V1.30：視窗版（setup_gui）一直有這段警告，文字版漏了——沒有 tkinter 的電腦就看不到
        print(C("  ⚠ For real meetings, you must turn on the paid tier (set up billing in AI Studio).", YEL))
        print(C("    On the free tier, Google uses your content to improve its products and human reviewers may read it. Google explicitly warns against sending confidential information.", YEL))
        # 🔴 不要用 input()：它會把金鑰明文印在畫面上，而使用說明還教使用者
        #    「卡住就點 6_診斷.bat 截圖給人看」——金鑰會跟著被截進去。
        #    每個字顯示成 *（_apikey.read_secret），貼上之後才看得出有沒有進去。
        key = _apikey.read_secret(
            "\n  Paste the key and press Enter (each character shows as *; to skip for now, just press Enter): ").strip().strip('"')
        if key:
            print(C(f"  Received: {_apikey.mask(key)}", DIM))
            status, why = _apikey.verify(key)
            if status == "bad":
                print(C(f"  ✗ Key not saved: {why}", YEL))
                print(C("    Once you start using the tool, choose \"9 API key settings\" to paste a new one.", DIM))
            else:
                ok, err = _apikey.remember(key)
                if ok:
                    print(C("  ✓ Saved" + ("" if status == "ok" else f" (but note: {why})"), GRN))
                else:
                    print(C(f"  ✗ Could not save: {err}", YEL))
        else:
            print(C("  Skipped. The program will ask you again the first time it runs.", DIM))

    print(C("\n" + "  " + "=" * 40, DIM))
    print(C("  Installation complete! Now double-click 4_Start.bat to start using it.", GRN))
    print(C("  " + "=" * 40 + "\n", DIM))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 1
    try:
        import _apikey
        _apikey.drain_input()      # 貼金鑰時多按的 Enter 不可以直接把視窗關掉：使用者還沒看到結果
    except Exception:
        pass
    input("Press Enter to close…")
    sys.exit(code)
