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
    print(C(f"  ✗ {desc}失敗（錯誤碼 {r.returncode}）", RED))
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if out:
        print(C("  ── 實際的錯誤訊息 ──", DIM))
        for line in out.splitlines()[-15:]:
            print("  " + line)
    else:
        print(C("  （這個指令沒有輸出任何訊息）", DIM))
    return False


def main():
    total = 4
    print(C("\n  TIO — 安裝", BOLD))
    print(C("  " + "=" * 40, DIM))
    print(f"  使用的 Python：{sys.version.split()[0]}  ({sys.executable})")

    # 🔴 scipy>=1.18 需要 Python 3.12 以上，舊版會在 pip 噴看不懂的編譯錯誤
    if sys.version_info < (3, 12):
        v = ".".join(map(str, sys.version_info[:3]))
        print()
        print(C(f"  ✗ 這台電腦的 Python 是 {v}，太舊了。", RED))
        print("    這個工具需要 3.12 以上（套件相依需求）。")
        print("    請到 python.org 安裝 3.13，或移除舊版後重跑 3_安裝.bat。")
        return 1

    # ── 1. 解除「來自網路」封鎖 ──
    # 🔴 排在最前面：後面失敗也不會害到 4_開始使用.bat 和 7_解除安裝.bat。
    #    視窗版（setup_gui.py）有同一步，兩條路都要做，不然沒有 tkinter 的電腦
    #    會變成「備援路徑漏掉修正」。
    step(1, total, "解除「來自網路」封鎖")
    try:
        from _winpath import unblock_files, zone_marked_files
        marked = zone_marked_files(ROOT)
        if not marked:
            print(C("  ✓ 沒有被 Windows 標記的檔案", GRN))
        else:
            done, fail = unblock_files(marked)
            print(C(f"  ✓ 已解除 {len(done)} 個檔案的封鎖", GRN))
            if fail:
                print(C("  沒解掉：" + "、".join(fail), YEL))
    except Exception as e:
        print(C(f"  （跳過，不影響安裝）{e}", DIM))

    # ── 2. ffmpeg ──
    step(2, total, "檢查 ffmpeg（處理音訊用）")
    from shutil import which
    if which("ffmpeg") and which("ffprobe"):
        print(C("  ✓ 已安裝", GRN))
    else:
        print("  沒找到，嘗試用 winget 自動安裝…")
        if which("winget") is None:
            print(C("  ✗ 這台電腦沒有 winget，無法自動安裝。", RED))
            print("    請自行到 https://www.gyan.dev/ffmpeg/builds/ 下載，")
            print("    解壓縮後把裡面的 bin 資料夾加入系統 PATH。")
        else:
            ok = run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                      "--accept-source-agreements", "--accept-package-agreements"],
                     "ffmpeg 安裝")
            if ok:
                print(C("  ✓ 安裝完成（可能需要重開這個視窗才找得到）", GRN))

    # ── 3. Python 套件 ──
    step(3, total, "安裝 Python 套件")
    req = os.path.join(ROOT, "requirements.txt")
    if not os.path.exists(req):
        print(C(f"  ✗ 找不到 {req}", RED))
        return 1
    print(C("  （第一次安裝可能要幾分鐘，請不要關視窗）", DIM))
    if not run([sys.executable, "-m", "pip", "install", "-r", req], "套件安裝"):
        print(C("\n  常見原因：沒有網路、公司防火牆擋住 PyPI。", YEL))
        return 1
    print(C("  ✓ 套件都裝好了", GRN))

    # ── 4. API 金鑰 ──
    step(4, total, "設定 Gemini API 金鑰")
    import _apikey
    if os.environ.get(_apikey.NAME) or _apikey.saved():
        print(C("  ✓ 已經設定過了", GRN))
    else:
        print("  需要一組免費的 Google Gemini API 金鑰。")
        print(C("  申請網址：https://aistudio.google.com/apikey", CYAN))
        print(C("  （登入 Google 帳號 → Create API key → 複製）", DIM))
        # V1.30：視窗版（setup_gui）一直有這段警告，文字版漏了——沒有 tkinter 的電腦就看不到
        print(C("  ⚠ 要拿來錄真實會議，請務必開通付費層（在 AI Studio 綁定帳單）。", YEL))
        print(C("    免費層的內容 Google 會拿去改進產品，人工審閱者可能讀到，官方明文警告不要送機密資訊。", YEL))
        # 🔴 不要用 input()：它會把金鑰明文印在畫面上，而使用說明還教使用者
        #    「卡住就點 6_診斷.bat 截圖給人看」——金鑰會跟著被截進去。
        #    每個字顯示成 *（_apikey.read_secret），貼上之後才看得出有沒有進去。
        key = _apikey.read_secret(
            "\n  貼上金鑰後按 Enter（每個字會顯示成 *；先跳過就直接按 Enter）：").strip().strip('"')
        if key:
            print(C(f"  收到：{_apikey.mask(key)}", DIM))
            status, why = _apikey.verify(key)
            if status == "bad":
                print(C(f"  ✗ 金鑰沒有存：{why}", YEL))
                print(C("    開始使用後選「9 API 金鑰設定」重新貼一組。", DIM))
            else:
                ok, err = _apikey.remember(key)
                if ok:
                    print(C("  ✓ 已儲存" + ("" if status == "ok" else f"（但{why}）"), GRN))
                else:
                    print(C(f"  ✗ 儲存失敗：{err}", YEL))
        else:
            print(C("  跳過了。第一次執行時程式會再問你一次。", DIM))

    print(C("\n" + "  " + "=" * 40, DIM))
    print(C("  安裝完成！接下來點兩下 4_開始使用.bat 就可以用了。", GRN))
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
    input("按 Enter 關閉…")
    sys.exit(code)
