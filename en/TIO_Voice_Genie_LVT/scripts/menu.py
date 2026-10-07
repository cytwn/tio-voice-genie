# -*- coding: utf-8 -*-
"""雙擊啟動用的中文選單。不必記任何指令。"""
import os, re, sys, io, subprocess, time

if __name__ == "__main__":      # 被 import 時不要動 stdout，會互相關掉底層 buffer
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if sys.platform == "win32":          # 讓舊版 cmd 也認得顏色碼
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
        # 🔴 字碼頁自己設，不要依賴 4_開始使用.bat 的 chcp 65001：
        #    安裝精靈的「立即開始使用」已改成直接開新主控台跑這支（不經過 .bat），
        #    少了 chcp 的話上面那個 UTF-8 的 stdout 會在 CP950 主控台印成一片亂碼。
        #    本來就是 65001 時再設一次沒有任何副作用。
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
PY = sys.executable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _winpath import desktop_dir, icon_file, set_console_icon   # noqa: E402
import _apikey                                                  # noqa: E402
from _live import font_hint                                     # noqa: E402  只用標準函式庫，不拖慢選單

# 🔴 不要改回 os.path.join(expanduser("~"), "Desktop")：接了 OneDrive 的
#    公司/學校電腦，桌面會被導向到別的地方，逐字稿會存到使用者看不到的路徑。
DESKTOP = desktop_dir()

C = lambda s, c: f"\033[{c}m{s}\033[0m"
BOLD, DIM, CYAN, GRN, YEL, RED = "1", "2", "36", "32", "33", "31"


def _in(prompt=""):
    try:
        return input(prompt)
    except EOFError:
        raise KeyboardInterrupt


def pause():
    _in(C("\nPress Enter to return to the menu…", DIM))


def ask(prompt, options, default=None):
    """options = [(鍵, 說明)]。default＝直接按 Enter 時當成選哪一個（None＝一定要選）。"""
    print()
    for k, d in options:
        print(f"  {C(k, CYAN)}  {d}")
    while True:
        v = _in(f"\n{prompt} ").strip()
        if not v and default is not None:
            return default
        if v in [k for k, _ in options]:
            return v
        print(C("  Please type one of the numbers above.", YEL))


def _names_warning(n_got, n_spk, fallback):
    """講者名字填的數量跟講者數不一樣時的提醒。🔴 2026-09-20 筆電實測 N6-7：原本不分多少一律說
    「沒填到的會沿用…」，那只適用於填太少；填太多時多出來的名字根本用不到。"""
    if n_got > n_spk:
        return f"  ⚠ You entered {n_got} names, but this file has only {n_spk} speaker(s); the {n_got - n_spk} extra name(s) cannot be used and will be skipped."
    return f"  ⚠ You entered {n_got} name(s), but this file has {n_spk} speakers; speakers without a name will get {fallback}."


def split_names(text):
    """講者名字：預設用空白隔開；輸入裡有逗號、頓號或分號時改用它們隔開，名字本身就可以有空白（英文全名）。
    🔴 2026-10-03 V1.34 全線實測 X15：英文版輸入「Chair Wang Ms Li Mr Chen Dr Brown」被切成 8 個名字，
       四位講者變成 Chair／Wang／Ms／Li。做法比照 parse_glossary 的分隔符（逗號、頓號、分號）。"""
    text = (text or "").strip()
    if re.search(r"[,，、;；]", text):
        return [s.strip() for s in re.split(r"[,，、;；]+", text) if s.strip()]
    return text.split()


def ask_names():
    """問講者名字，讀完回顯一次讀到幾位、各是誰。
    🔴 V1.35 審查：空白和逗號混著用時（「處長 秘書, 組長」）會變成 2 位；功能 2 不知道有幾位講者、不會提醒，名字就安靜地錯位。"""
    names = split_names(_in("\nSpeaker names: "))
    if names:
        print(C(f"  Read {len(names)} name(s): {' / '.join(names)}", DIM))
    return names


def pick_file(transcript=False, json_only=False):
    """跳出 Windows 選檔視窗。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        try:
            # 選檔視窗的圖示。default= 是設給「之後開的視窗」，所以下面那個
            # askopenfilename 才跟著換。圖示失敗絕不能害到選檔本身，所以自己一層 try。
            ip = icon_file()
            if ip:
                r.iconbitmap(default=ip)
        except Exception:
            pass
        if json_only:
            p = filedialog.askopenfilename(
                title="Choose a transcript .json file",
                filetypes=[("Transcript data file", "*.json"), ("All files", "*.*")])
            r.destroy()
            return p
        # 🔴 2026-09-20 筆電實測 N6-6：功能 4（transcript=True）預設只列 .json／.srt，標題卻寫「選擇會議錄音檔」
        p = filedialog.askopenfilename(
            title="Choose a transcript, captions or an audio/video recording" if transcript else "Choose a meeting recording (audio or video)",
            # 🔴 第一個篩選器就是視窗打開時的預設。標題說「逐字稿、字幕或錄音檔」，
            #    第一個卻是「逐字稿或字幕」，音檔整個看不到（2026-09-20 筆電 ⚠-5）。
            # V1.39（10-07 使用者要求實測 .webm）：「音訊或影片」補 *.opus、*.webm（瀏覽器錄的影片常用；以前要切到「所有檔案」才看得到）。
            filetypes=([("All supported files",
                         "*.json *.srt *.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.opus "
                         "*.mp4 *.mov *.mkv *.avi *.webm"),
                        ("Transcripts or captions", "*.json *.srt"),
                        ("Audio or video", "*.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.opus *.mp4 *.mov *.mkv *.avi *.webm"),
                        ("All files", "*.*")] if transcript else
                       [("Audio or video", "*.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.opus *.mp4 *.mov *.mkv *.avi *.webm"),
                        ("All files", "*.*")]))
        r.destroy()
        return p
    except Exception:
        return _in("Drag the recording into this window, then press Enter: ").strip().strip('"')


def safe_name(name):
    """
    把使用者輸入的名稱變成合法檔名。

    🔴 台灣行政人員寫日期習慣用「9/8」，直接接到路徑上會變成不存在的子目錄，
       程式當場噴 FileNotFoundError。Windows 不允許的字元一律換成底線。
    """
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    if cleaned != name:
        print(C(f"  (File names cannot contain \\ / : * ? \" < > |, so it was changed to: {cleaned})", DIM))
    return cleaned


def ask_speaker_names(path, to=None):
    """
    問講者名字。to＝要翻成的語言（en／ja 時，沒填的講者會寫成 Speaker N／話者N，提示要講清楚）。
    to＝None（功能 4 的「1 自動判斷」）時目標語言還沒定，提示改成條件式說法，不准猜一種。

    🔴 功能 5 早就會問，功能 4 沒問 —— 於是要寄給外賓的雙語對照文件，
       講者欄只能是「講者1／講者2」，而且工具裡沒有任何地方可以改。
       （translate_transcript.py 本來就吃 --names，只是選單沒傳。）

    輸入是 .json 時可以先讀出來，照功能 5 的做法把每位講者的第一句印出來，
    讓人對得上號再填。輸入是音檔時還沒轉檔、不知道有幾位，只能先問。
    .srt 沒有講者資訊，直接跳過不問。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".srt":
        return []
    n_spk, preview, known = 0, [], {}
    if ext == ".json":
        try:
            from json_to_md import load_transcript, speaker_list, generic_names, GENERIC_NAME
            segs, _meta = load_transcript(path)
            spks = speaker_list(segs)                   # 數字排序（V1.22 ②）
            n_spk = len(spks)
            # 🔴 2026-09-25（V1.22 ④）：功能 2 填過的名字存在 .json 裡，直接 Enter 時翻譯檔會沿用。
            #    預覽就用那些名字（沒填過的用預設編號），使用者才知道 Enter 會得到什麼。
            known = {sp: v for sp, v in (_meta.get("speakers") or {}).items()
                     if sp in spks and v and not GENERIC_NAME.fullmatch(str(v))}
            label = dict(generic_names(spks), **known)
            for sp in spks:
                first = next((s for s in segs if isinstance(s, dict)
                              and s.get("speaker", "spk:0") == sp), None)
                if first:
                    preview.append((label[sp], (first.get("text") or first.get("raw") or "").strip()[:40]))
        except Exception:
            return []          # 讀不出來就別問，下游會給正式的錯誤訊息
        if n_spk <= 1:
            return []          # 只有一位講者，問了沒意義

    print(C("\nSpeaker names (optional)", BOLD))
    if preview:
        print(C(f"  This file has {n_spk} speakers:", DIM))
        for who, txt in preview:
            print(C(f"    {who} – first line: {txt}…", DIM))
        print(C(f"  Enter {n_spk} names in this order, separated by commas (a name can contain spaces, e.g. a full name; if no name contains a space, spaces work too).", DIM))
    else:
        print(C("  This is an audio or video file that has not been transcribed yet, so the number of speakers is not known yet.", DIM))
        print(C("  If you know them, enter the names \"in the order they first speak\", separated by commas (if no name contains a space, spaces work too); if unsure, just press Enter.", DIM))
    # 🔴 to 是 None（功能 4 選「1 自動判斷」，而且它是第一個選項）時，目標語言要等
    #    translate_transcript 自己判：中文稿→英文（Speaker 1）、英文稿→臺灣繁體（講者1），
    #    選單另外指定才會是日文（話者1）。舊版一律印「講者1、講者2」，但自動判斷碰到
    #    中文稿時三份輸出檔（_對照.md／_對照表.md／_en.md）全寫 Speaker 1，
    #    畫面講的和檔案寫的對不起來（2026-09-15 對抗式複查 R3-1）。
    #    這裡不 import translate_transcript（選單不該為了一句提示去載翻譯模組、
    #    也避免音檔輸入時根本還沒轉檔、無從判斷），改成把三種可能都講清楚、不猜一種。
    if to is None:
        eg = ("the default labels (\"Speaker 1, Speaker 2\")")
        egN = "the default labels (\"Speaker N\")"
    else:
        fallback = {"en": "Speaker 1, Speaker 2", "ja": "話者1, 話者2"}.get(to, "Speaker 1, Speaker 2")
        eg = f"\"{fallback}\" (the default labels in the translated file)"
        egN = f"\"{fallback.split(', ')[0][:-1]}N\" (the default label in the translated file)"
    if known:
        print(C(f"  e.g. Chair Wang, Ms Li    Press Enter alone to keep the names above ({', '.join(known.values())}); speakers without a name get {eg}.", DIM))
    else:
        print(C(f"  e.g. Chair Wang, Ms Li    Press Enter alone to use {eg}.", DIM))
    got = ask_names()
    if got and n_spk and len(got) != n_spk:
        print(C(_names_warning(len(got), n_spk, egN), YEL))
    return got


def ask_vocab():
    print(C("\nProper nouns (important: they greatly improve accuracy)", BOLD))
    print(C("  e.g. 深耕計畫 研發處 會計室 教學組長 (write them the way they should appear in the transcript)", DIM))
    print(C("  Separate them with spaces. Press Enter alone to skip.", DIM))
    v = _in("\nProper nouns: ").strip()
    return v.split() if v else []



CANCEL_RC = 130            # 128 + SIGINT：live 腳本「使用者主動取消、還沒開始錄音」的離開碼約定
_run_interrupted = False   # 上一次 run()：選單這個父行程自己也被 Ctrl+C 打斷了
_last_rc = None            # 上一次 run() 的離開碼；None＝這一輪沒有跑任何工具


def report_live(rc, stem, cancelled=None):
    """
    即時字幕/雙語字幕結束後的回報。

    🔴 舊版不管子行程死活都印綠色的 ✅「檔案在桌面」。程式當掉時使用者會以為
       逐字稿存好了，等到要用才發現沒有 —— 而那時候會議已經開完了。
       這裡改成：檔案真的存在才說成功，否則明確講哪裡出問題。
    🔴 第二版又漏了一半：只要 .md、.txt 其中一個在，就說兩個都在桌面。
       程式被中途關掉時只會剩 .txt（.md 要按 Ctrl+C 正常結束才會寫），
       畫面卻說 .md 在桌面（2026-09-11 實戰測試抓到）。兩個檔要分開講。
    🔴 第三版要分得出「使用者自己取消」與「程式出錯」。還沒開始錄音就按 Ctrl+C 時
       一個檔都不會產生，舊版一律走到最後那一段，印「上面應該有錯誤訊息…把整個視窗
       截圖回報」—— 使用者明明是自己取消的，卻被叫去報修，會嚇到人
       （2026-09-15 對抗式複查 R2-4）。判準用兩個來源，缺一不可靠：
         · rc == CANCEL_RC：live 腳本自己回報的「取消」離開碼
         · _run_interrupted：選單跟 live 腳本同一個主控台，Ctrl+C 會先打斷選單自己，
           這時候 subprocess.run 直接丟例外，根本讀不到子行程的離開碼（實測拿到 0）
       cancelled 給值就以給的為準（測試用），None ＝ 自己判。
    """
    if cancelled is None:
        cancelled = rc == CANCEL_RC or _run_interrupted
    md, txt = stem + ".md", stem + ".txt"
    has_md, has_txt = os.path.exists(md), os.path.exists(txt)
    base = os.path.basename(stem)
    if has_md:
        # V1.38（X7h）審查第 4 輪：功能 3「準」有幾句沒有譯文（結束時還沒翻好／翻譯失敗）時 .md 檔頭照實講（都含「原文有存」）——這裡不打綠色 ✅。
        #    標記是 live_bilingual_hq.Out.save 寫進檔頭的字樣；英文版兩邊各翻一次，tools\test_coupling.py 核對兩邊一樣。
        try:
            head = io.open(md, encoding="utf-8", errors="replace").read(3000).split("\n---\n", 1)[0]
        except OSError:
            head = ""
        nomt = "the original text is saved" in head
        print(C(f"\n{'⚠' if nomt else '✅'} Saved on your desktop: {base}.md (for reading)"
                + (f" / {base}.txt (backup)" if has_txt else ""), YEL if nomt else GRN))
        if nomt:
            print(C("   Some sentences have no translation (the original text is all saved); the reason is in the .md file header.", DIM))
        if rc not in (0, None):
            print(C("   (The program did not end normally, so the content may be incomplete. Please open the file and check.)", YEL))
    elif has_txt:
        print(C(f"\n⚠ Only the live backup exists: {base}.txt (on your desktop)", YEL))
        print(C("   The tidied-up .md was not created – the program was probably closed midway or hit an error.", DIM))
        print(C("   All the captions recognised so far are in this .txt file; you can open it with Notepad.", DIM))
    elif cancelled:
        # 使用者自己取消的，不是故障：不要叫他去找錯誤訊息、更不要叫他截圖回報。
        print(C("\n✗ Cancelled. No files were created.", YEL))
        print(C("   (This is not an error – you pressed Ctrl+C. To start again, go back to the menu and choose it again.)", DIM))
    else:
        print(C("\n✗ No files were created.", RED))
        print(C("   There should be an error message above; please scroll up to see it.", DIM))
        print(C("   If you need help, double-click 6_Diagnostics.bat and send a screenshot of the whole window.", DIM))


def parse_glossary(text):
    """
    把「中文=English」的固定譯名切成一組一組。回傳 (可用的組, 被丟掉的片段)。

    🔴 不要用 text.split()。
    出貨前稽核（2026-09-09）實測：譯名本身就含空白
    （深耕計畫=Higher Education Sprout Project），純空白切開之後只有第一段
    帶著「=」，其餘的字會被下游靜默丟掉，送進模型的硬性規則就變成
    「深耕計畫 → Higher」—— 而那份文件通常是要寄給外賓的。

    🔴 2026-09-10 再修三個邊界（都是實測跑出來的，不是想像的）：
      - **全形等號 ＝**：中文輸入法最容易打出來的就是它，原本整條被丟掉
      - **鍵含空白**（Sprout Project=深耕計畫）：英文稿翻中文時就會這樣寫，
        原本只鎖到最後一個字「Project」—— 跟上面那個 bug 同一類，只是換一邊
      - **空的譯名**（深耕計畫=）：原本會送出「深耕計畫 → (空)」給模型

    切法：有分號／換行時，一個區段就是一組（鍵和值都可以含空白，最不會出錯）；
    整串沒有分隔符、而且只有一個等號時，整段就是一組；
    其餘才退回用「下一組 詞= 之前」為界切，維持舊的空白寫法相容。
    """
    import re
    text = (text or "").replace("＝", "=")
    # 逗號、頓號也要當分隔符：同事不會記得「只能用分號」，用全形逗號分隔時
    # 原本會切成「甲=A」「B，乙=C D」這種半截譯名，畫面還回報「已鎖定 2 組」。
    segs = [s.strip() for s in re.split(r"[;；,，、\n]+", text) if s.strip()]
    if len(segs) > 1:
        raw = segs
    elif segs and segs[0].count("=") == 1:
        raw = segs                      # 只有一個等號＝不可能有兩組，別再切
    elif segs:
        raw = [m.strip() for m in
               re.findall(r"\S+?=.*?(?=\s+\S+?=|$)", segs[0])] or segs
    else:
        raw = []

    good, bad = [], []
    for r in raw:
        if "=" not in r:
            bad.append(r)
            continue
        k, v = r.split("=", 1)
        (good if k.strip() and v.strip() else bad).append(r)
    return good, bad

def safe_stem(stem, exts):
    """
    🔴 不要靜默覆蓋使用者既有的檔案。

    出貨前稽核（2026-09-08）實測：使用者輸入的會議名稱直接當檔名，而 .txt 是在
    「開始錄音之前」就以 "w" 開啟的。同事這個月打了跟上個月一樣的名字，上個月的
    紀錄就在按下 Enter 的那一刻被清成 0 bytes —— 不進資源回收筒、沒有任何警告，
    而且被毀掉的正好是說明書裡稱為「當機也不會掉」的那個備份檔。

    這裡改成：撞名就自動加序號，並明白告訴使用者實際存檔的名字。
    絕不覆蓋，也絕不因此擋住會議開始。
    """
    if not any(os.path.exists(stem + e) for e in exts):
        return stem
    n = 2
    while any(os.path.exists(f"{stem}_{n}" + e) for e in exts):
        n += 1
    new = f"{stem}_{n}"
    print(C(f"\n  ⚠ A file with the same name is already on your desktop, so this time it will be saved as: {os.path.basename(new)}", YEL))
    print(C("     (The existing file has not been touched at all.)", DIM))
    return new

def run(args, title, warmup=False):
    global _run_interrupted, _last_rc
    _run_interrupted = False
    print(C(f"\n{'─'*60}", DIM))
    print(C(f"  {title}", BOLD))
    print(C(f"{'─'*60}\n", DIM))
    # 🔴 上面那行標題在子行程「還沒開始載入」時就印出去了，而冷啟載入語音元件要 30~45 秒
    #    （2026-09-21 筆電實測），使用者看到「進行中」之後畫面 30 秒不動，會以為當掉
    #    —— 先講清楚現在是在啟動。逐顆元件的進度由子行程的 _need() 印出來。
    # 🔴 2026-09-22（S5）：只有三支即時腳本（live_caption／live_bilingual／
    #    live_bilingual_hq）會走 _need() 載入語音元件，才需要這行。
    #    其餘呼叫點沒有 _need()，印了就是騙人 —— 尤其 json_to_md 的標題自己寫
    #    「純本機，幾秒就好」，緊接著印「可能要 30 秒」會直接自相矛盾。
    #    預設 False：以後新增呼叫點不會誤繼承這個訊息，要的人自己開。
    if warmup:
        print(C("  Starting… The first time, the speech components have to load, which can take 30 seconds. Please wait.", DIM))
    try:
        _last_rc = subprocess.run([PY, "-u"] + args, cwd=ROOT).returncode
        return _last_rc
    except KeyboardInterrupt:
        # 🔴 選單跟 live 腳本在同一個主控台，使用者按 Ctrl+C 時**父行程也會收到**：
        #    subprocess.run 當場丟 KeyboardInterrupt，子行程回的 CANCEL_RC 根本讀不到
        #    （實測 live 腳本 return 130，這裡拿到的是 0）。所以「是不是取消」不能只看 rc，
        #    記在旗標上給 report_live 用（2026-09-15 對抗式複查 R2-4）。
        _run_interrupted = True
        _last_rc = 0
        return 0          # Ctrl+C 是正常的結束方式，不是失敗


def ask_mic_device(both=False):
    """選了麥克風／兩者都要時問：用哪一支麥克風。回傳裝置名稱（--mic-device），None＝跟著 Windows 預設。
    both：這一場是「兩者都要」（說明要講清楚：拔掉的只是麥克風那一路）。

    🔴 2026-09-22 P2：原本只能用 Windows 預設麥克風，插著耳麥就一定用耳麥。筆電實測真人站 3 公尺，
       內建麥克風兩次都辨識正確、放桌上的耳麥一次整句錯——所以要能「耳麥插著、仍用內建麥克風」。
    🔴 列清單前先重抓裝置：選單這個行程開很久了，PortAudio 的清單是開選單那一刻的（見 _audioroute._refresh_sounddevice）。
       只有一支麥克風時不問。
    """
    try:
        import _audioroute
        _audioroute._refresh_sounddevice()
        from _live import input_device_names, default_input_name
        names, dflt = input_device_names(), default_input_name()   # V1.31：兩個名稱同一個來源（認端點 ID 對過去的）
    except Exception:
        return None
    if len(names) <= 1:
        return None
    # 🔴 2026-09-23 使用者連續指正兩次：先是「1 跟 3 看起來是同一個」，改成「自動／固定」後仍看不懂這兩個詞。
    #    第二次改法：不拿「自動／固定」當標籤（那是我們的行話），直接在選項裡寫「拔插耳麥時會發生什麼事」。
    opts = [("1", f"Let the program choose (recommended): currently \"{dflt or 'unknown'}\"; switches automatically when a headset is plugged in or out")]
    opts += [(str(i), f"Only \"{n}\": use this one the whole time; no switching when a headset is plugged in or out"
                      + ("  ← this is the current Windows default" if dflt and n == dflt else ""))
             for i, n in enumerate(names, 2)]
    # 🔴 2026-09-25（V1.21 ③）：使用者在「兩者都要」選了固定耳麥、拔掉後字幕還在跑，以為固定失效。
    #    拔插實測：麥克風那一路確實停了；還在出字幕的是電腦聲音那一路（影片改從筆電喇叭播，側錄照設計跟過去）。
    #    原句「那一支被拔掉時字幕會停」在兩者都要時不成立。
    stop_what = ("If it is unplugged, only the microphone feed stops (the computer audio still gets captions)" if both
                 else "If it is unplugged, the captions stop")
    print(C(f"\n   ※ The only difference is what happens when a headset is plugged in or out. Choose 1 and it follows the change;\n     choose any other number and it sticks to that microphone, reconnecting by itself when plugged back in.\n     {stop_what}.", DIM))
    # 🔴 2026-09-23 使用者指出例外：原本寫「多人會議，筆電內建麥克風比放桌上的耳麥穩」是把 09-22 的**一組**比較
    #    （內建麥克風陣列 vs 放桌上的 3.5mm 耳麥）寫成了通則。那次沒測過任何會議用的外接麥克風，
    #    不能替它排名——高收音效率的外接會議麥克風本來就是為「放桌上收整桌」做的。
    #    改法：只講各類麥克風的設計用途（這是可靠的），排名交給畫面上的收音檢查讓使用者自己量。
    print(C("   ※ Picking up people further away (group meetings): a headset is designed to sit by the mouth, so it often misses\n     anyone more than about 1.5 metres away; a laptop's built-in microphone covers a wider area;\n     an external conference microphone (the kind that sits on the table and covers everyone) is made for exactly this,\n     so if you have one connected, try it first.", DIM))
    print(C("   ※ After choosing, watch the \"Sound check\" on screen: while someone is speaking it should say \"sound received\";\n     if it says \"sound is weak\", try another microphone.", DIM))
    r = ask("Which microphone? (Enter alone = let the program choose)", opts, default="1")
    return None if r == "1" else names[int(r) - 2]


def ask_mic_raw():
    """選了「麥克風」時問一題：現場有沒有擴音器的聲音要收。回傳 True＝用完整收音（--mic-raw）。

    🔴 2026-09-22 筆電實測（使用者核准做成「選項」、預設維持一般收音）：
       ・筆電喇叭播會議錄音：一般收音辨識 0 句，完整收音 4 句（原檔 7 句）——Windows 的收音處理把喇叭聲整段刪掉
       ・真人站 3 公尺：兩種都辨識得出來；一般收音略好 ⇒ 預設不換
       ・手機小喇叭放 2 公尺：兩種都 0 句 ⇒ **不能保證**收得到會議室擴音器，說明文字要照實講
       線上與會者的聲音最可靠的是走數位：讓這台電腦也加入會議、改選「兩者都要」。
    """
    r = ask("Does any of the sound in the room come from loudspeakers (speakers) and also need captions? (Enter alone = No)", [
        ("1", "No, it is all people in the room speaking directly (recommended: cleanest sound)"),
        ("2", "Yes, pick it up too (full capture: bypasses Windows noise suppression. Loudspeakers are more likely to be\n     picked up, but this is not guaranteed; air conditioning and keyboard noise will come in too)"),
    ], default="1")
    if r == "2":
        print(C("   ※ If the loudspeakers are playing an online meeting, the most reliable way is to have this computer join\n     that meeting too, and choose \"Both\" instead.", YEL))
    return r == "2"


# ────────────────────────────── 三個功能 ──────────────────────────────
def do_live():
    print(C("\n[Live meeting captions]", BOLD))
    print("  Captions appear live while the meeting is running. They are saved automatically at the end.")
    src = ask("Please choose (type a number):", [
        ("1", "Online meeting (Teams / Meet / Zoom) – records the computer audio"),
        ("2", "In-person meeting – records the microphone"),
        ("3", "Both (I am in an online meeting and my own microphone should be recorded too)"),
        ("0", "Back"),
    ])
    if src == "0":
        return
    mode = {"1": "system", "2": "mic", "3": "both"}[src]
    mic_dev = ask_mic_device(both=mode == "both") if mode in ("mic", "both") else None
    mic_raw = ask_mic_raw() if mode == "mic" else False
    vocab = ask_vocab()

    name = _in("\nWhat is the meeting called? (Enter alone = use today's date): ").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("Captions_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    print(C("\n※ Once it starts, captions appear as people speak:", BOLD))
    print(C("   Grey text  = still being recognised; it keeps being corrected", DIM))
    print(C("   White text = final sentences (each sentence is locked as soon as it is finished)", DIM))
    print(C(f"   {font_hint()}", DIM))
    print(C("\n※ When the meeting ends, press Ctrl + C in this window to save.", BOLD))
    print(C("   The files are saved to your desktop.", DIM))
    print(C("   Once started, avoid plugging or unplugging the headset; if the plug comes loose, it reconnects by itself and tells you.", DIM))
    _in(C("\nPress Enter to start when you are ready…", GRN))

    args = [os.path.join(SCRIPTS, "live_caption.py"), "--source", mode, "--out", stem]
    if mic_raw:
        args.append("--mic-raw")
    if mic_dev:
        args += ["--mic-device", mic_dev]
    if vocab:
        args += ["--vocab"] + vocab
    rc = run(args, "Live captions running (press Ctrl+C to stop)", warmup=True)
    report_live(rc, stem)
    pause()


def do_transcribe():
    print(C("\n[Recording to transcript]", BOLD))
    print("  Turns a meeting you have already recorded (audio or video) into a Traditional Chinese transcript with speakers and times.")
    print(C("\n  Opening the file picker… (if you don't see it, check the taskbar)", DIM))
    path = pick_file()
    if not path or not os.path.exists(path):
        print(C("  No file was selected.", YEL)); pause(); return
    print(f"  Selected: {C(os.path.basename(path), CYAN)}")

    vocab = ask_vocab()

    print(C("\nSpeaker names (optional)", BOLD))
    print(C("  Enter them in the order people start speaking in the recording (\"first to speak, second to speak\").", DIM))
    print(C("  e.g. Chair Wang, Ms Li    Press Enter alone to use \"Speaker 1, Speaker 2\".", DIM))
    print(C("  Separate the names with commas, so a name can contain spaces (e.g. a full name); if no name contains a space, spaces work too.", DIM))
    names = ask_names()

    # 🔴 撞名不要靜默覆蓋：同事很可能已經把上一版逐字稿的講者名字、錯字
    #    一句一句改好了，再轉一次就整份沒了。功能 1、3 早就這樣做，這裡補上。
    out = safe_stem(
        os.path.join(DESKTOP, os.path.splitext(os.path.basename(path))[0] + "_transcript"),
        (".md", ".json")) + ".md"
    args = [os.path.join(SCRIPTS, "transcribe_meeting.py"), path, "--out", out]
    if vocab:
        args += ["--vocab"] + vocab
    if names:
        args += ["--names"] + names
    run(args, "Transcribing; a one-hour recording takes about 1–3 minutes")
    if os.path.exists(out):
        # 🔴 只認 transcribe_meeting 真正寫進檔頭的那兩個標記字串，不可以用「可能不完整」
        #    「辨識失敗」這種鬆散的四個字：讀進來的 3000 字裡檔頭只佔約 70 字，其餘是正文，
        #    會議裡常說的「目前的數字可能不完整」「人臉辨識失敗」、或音檔檔名（會原樣寫進
        #    「- 音檔：`…`」那一行）撞到就誤印 ⚠，跟 transcribe_meeting 自己剛印的 ✅ 打對臺
        #    （2026-09-15 對抗式複查 R3-2 實測 4 案誤報）。切到檔頭區（第一個 --- 分隔線之前）
        #    是第二層保險，防模型在正文原樣吐出同一段粗體標記。
        # 🔴 同一事實兩個落點：下面兩個標記字串抄自 transcribe_meeting.py 寫檔頭的地方
        #    （搜尋「menu.do_transcribe」可以找到那邊對應的註解）。那邊改字，這裡一定要跟著改，
        #    否則這裡會安靜地永遠判成 ✅。開發端的 test_r3_menu_translate_docs.py 有一條把關（該檔不隨附）：
        #    把這裡用的字串抽出來，確認它真的還出現在 transcribe_meeting.py 的原始碼裡。
        head = io.open(out, encoding="utf-8", errors="replace").read(3000).split("\n---\n", 1)[0]
        if "**This transcript may be incomplete**" in head or "part(s) failed to transcribe; this transcript is incomplete" in head:
            # 🔴 逐字稿缺尾或有段落失敗時，檔頭已經寫了原因；這裡不能還打 ✅（2026-09-14 驗收抓到）
            print(C(f"\n⚠ The transcript is on your desktop: {os.path.basename(out)}, but it may be incomplete (reason above; also noted in the file header)", YEL))
        else:
            print(C(f"\n✅ The transcript is on your desktop: {os.path.basename(out)}", GRN))
        # 🔴 2026-09-20 筆電實測 N6-8：說明書教首次試用「一路 Enter 到底」，這一題原本不收空白 Enter。
        #    直接 Enter＝不用（不會自己打開任何東西，最安全）。
        if ask("Open it now? (Enter alone = No)", [("1", "Yes"), ("0", "No")], default="0") == "1":
            os.startfile(out)
    pause()


def do_translate():
    print(C("\n[Transcript to bilingual]", BOLD))
    print("  Translates a recording, transcript or captions file into a bilingual document.")
    print(C("  Unlike \"Live bilingual captions\", this translates the whole file at once: the model sees the context, so quality is much better.", DIM))
    print(C("\n  Opening the file picker…", DIM))
    path = pick_file(transcript=True)
    if not path or not os.path.exists(path):
        print(C("  No file was selected.", YEL)); pause(); return
    print(f"  Selected: {C(os.path.basename(path), CYAN)}")

    d = ask("What should it be translated into?", [
        ("1", "Decide automatically (Chinese transcript → English; English transcript → Chinese)"),
        ("2", "Translate into Traditional Chinese (Taiwan)"),
        ("3", "Translate into English"),
        ("4", "Translate into Japanese"),
    ])
    to = {"1": None, "2": "zh-TW", "3": "en", "4": "ja"}[d]

    # 翻成日文時，格式與範例要是「中文=日文」（原本一律只給英文範例，2026-09-14 使用者核准修正）。
    # 日文範例用東京大學《大学論叢》第 5 號（2025-11）裡的寫法：高等教育深耕計画、教務処。
    gl_fmt = "Chinese=Japanese" if to == "ja" else "Chinese=English"
    print(C("\nFixed translations (optional, but very useful)", BOLD))
    print(C(f"  Write them as \"{gl_fmt}\"; separate several pairs with semicolons or commas (spaces inside a translation are fine).", DIM))
    if to == "ja":
        print(C("  e.g. 深耕計畫=高等教育深耕計画 ; 教務處=教務処", DIM))
    else:
        print(C("  e.g. 深耕計畫=Higher Education Sprout Project ; 研發處=Office of Research and Development", DIM))
    gl = _in("\nFixed translations: ").strip()
    # 🔴 解析與確認要**緊接在輸入之後**。這段是「譯名被空白切碎」那個
    #    blocker 的安全網 —— 切錯了至少使用者當場看得見，離輸入越遠越沒用。
    gl_pairs, gl_dropped = parse_glossary(gl) if gl else ([], [])
    if gl:
        if gl_pairs:
            print(C(f"  {len(gl_pairs)} pair(s) locked in:", BOLD))
            for _p in gl_pairs:
                _k, _v = _p.split("=", 1)
                print(C(f"     {_k.strip()} → {_v.strip()}", DIM))
        if gl_dropped:
            # 靜默丟掉最毒：使用者以為鎖住了，其實沒有。
            print(C(f"  ⚠ These could not be understood and were skipped (write them as \"{gl_fmt}\"): {', '.join(gl_dropped)}", YEL))
        if not gl_pairs:
            print(C("  No fixed translations will be applied this time.", DIM))

    note = _in("\nWhat is the background of this document? (optional, e.g. Research Office meeting on the Sprout Project): ").strip()

    # V1.39（10-07 實測 .webm 時找到，V1.38 以前就這樣）：要跟 translate_transcript.AUDIO_EXT 一樣。以前少了 .opus／.webm——
    #    翻譯程式照樣當成錄音、先轉逐字稿，選單卻不問專有名詞、也沒先算好中繼逐字稿的檔名（桌面上同名的逐字稿會被蓋掉）。
    is_audio = os.path.splitext(path)[1].lower() in {
        ".mp3", ".m4a", ".wav", ".wma", ".aac", ".flac", ".ogg", ".opus",
        ".mp4", ".mov", ".mkv", ".avi", ".webm"}
    vocab = ask_vocab() if is_audio else []
    spk_names = ask_speaker_names(path, to)

    # 🔴 translate_transcript 實際會寫 5 種檔，撞名檢查要全部納入。
    #    漏掉 _<語言>.md 的後果：同事留著純譯文版（要寄給外賓的那份）、
    #    把太雜的 _對照.md 刪掉，再跑一次同一份就被靜默覆蓋。
    out = safe_stem(
        os.path.join(DESKTOP, os.path.splitext(os.path.basename(path))[0]),
        ("_bilingual.md", "_bilingual_table.md", "_bilingual.json",
         "_zh-TW.md", "_en.md", "_ja.md", "_bilingual.srt"))
    args = [os.path.join(SCRIPTS, "translate_transcript.py"), path, "--out", out]
    if is_audio:
        # 🔴 輸入是音檔時會先轉一次逐字稿。那份中繼稿的檔名跟功能 2 的產出
        #    完全一樣，不先算好防撞名就會把同事改過的那份蓋掉。
        interim = safe_stem(
            os.path.join(DESKTOP,
                         os.path.splitext(os.path.basename(path))[0] + "_transcript"),
            (".md", ".json")) + ".md"
        args += ["--interim-out", interim]
        print(C(f"  (This is an audio or video file, so it will be transcribed first: {os.path.basename(interim)})", DIM))
    if to:
        args += ["--to", to]
    if gl_pairs:
        args += ["--glossary"] + gl_pairs
    if spk_names:
        args += ["--names"] + spk_names
    if note:
        args += ["--note", note]
    if vocab:
        args += ["--vocab"] + vocab

    if is_audio:
        print(C("\n※ This is an audio or video file: it will be transcribed first and then translated, so it takes longer.", YEL))
    _in(C("\nPress Enter to start…", GRN))
    rc = run(args, "Translating")

    # 🔴 兩個條件都要看：檔案在，**而且**回傳碼是 0。
    #    只看檔案在不在是不夠的 —— 翻譯全部失敗時仍然會產出一份
    #    「全是（這段沒翻到）」的檔案，那不叫成功。
    #    （2026-09-10 稽核抓到：這是「單批失敗不中止」帶來的副作用。）
    made = os.path.basename(out)
    if rc not in (0, None) or not os.path.exists(out + "_bilingual.md"):
        # V1.38 審查第 3 輪：一段都還沒翻好就按 Ctrl+C（使用說明寫的正常用法）——不是錯誤，不叫人找紅字、跑診斷
        cancelled = _run_interrupted and not os.path.exists(out + "_bilingual.md")
        print(C("\n✗ Cancelled (you pressed Ctrl+C); no translation files were created.", YEL) if cancelled
              else C("\n✗ The translation did not finish.", RED))
        # 🔴 音檔已經先轉了一次逐字稿、錢也花了。不講的話同事會整個重跑，
        #    等於同一份錄音付兩次轉錄費。
        if is_audio and os.path.exists(interim):
            print(C(f"   However, the transcript has already been made; it is on your desktop: {os.path.basename(interim)}", GRN))
            print(C("   To retry the translation, press 4 in the menu and pick that .json this time, so you don't pay for transcription twice.", DIM))
        if not cancelled:
            print(C("   Scroll up to read the red error message; if it is unclear, double-click 6_Diagnostics.bat and send a screenshot.", DIM))
        pause(); return
    # 🔴 2026-09-20 複查（major）：逐字稿本身缺了一段時，翻完的四個檔照樣打綠勾 ——
    #    而 _<語言>.md 正是要寄給外賓的那份。比照功能 2／5：讀 _對照.md 的檔頭決定 ✅ 還是 ⚠。
    #    標記字串跟 transcribe_meeting.py／json_to_md.warn_lines 寫檔頭的地方必須一致。
    head4 = io.open(out + "_bilingual.md", encoding="utf-8",
                    errors="replace").read(3000).split("\n---\n", 1)[0]
    gap_tr = "paragraph(s) could not be translated" in head4
    gap_src = ("**This transcript may be incomplete**" in head4 or "part(s) failed to transcribe; this transcript is incomplete" in head4)
    if gap_tr and gap_src:
        # V1.38 審查第 2 輪：兩件事都要講（只講沒翻到，會把「原來的逐字稿就不完整」蓋掉）
        print(C(f"\n⚠ Files on your desktop (all starting with {made}; some paragraphs were not translated – they are marked \"(not translated)\" in the text – and the original transcript is incomplete; the file header notes both):", YEL))
    elif gap_tr:
        # V1.38：只翻成一部分（網路一直沒回來、額度用完、按了 Ctrl+C）時不可以打 ✅（以前照樣打 ✅）。
        #    標記是 translate_transcript.write_outputs 寫進檔頭的字樣；英文版兩邊各翻一次，tools\test_coupling.py 核對兩邊一樣。
        print(C(f"\n⚠ Files on your desktop (all starting with {made}; some paragraphs were not translated – they are marked \"(not translated)\" in the text, and the header says how many):", YEL))
    elif gap_src:
        # 🔴 V1.26（C1）：翻譯程式自己已經印過「原來的逐字稿就不完整」、缺口清單和「寄出去之前先看缺口」，
        #    這裡原本整句再講一次（同一句印兩遍），還印出 Markdown 的 ** 星號（主控台不會變粗體，只會原樣印出）。
        #    改成一句狀態＋檔案清單。上面判斷用的 "**這份逐字稿可能不完整**" 是**檔案內容**的字樣，不能動。
        #    🔴 只翻成一部分時翻譯程式不列缺口，所以這裡指向檔頭、不說「上面列的」（V1.26 審查 #6）。
        print(C(f"\n⚠ Files on your desktop (all starting with {made}; the original transcript is incomplete – missing time ranges are in the file header):", YEL))
    else:
        print(C(f"\n✅ You will find these files on your desktop (all starting with {made}):", GRN))
    print("     _bilingual.md        ← a paragraph of source, then a paragraph of translation, for people to read")
    print("     _bilingual_table.md  ← a table, easy to paste into Word / Excel")
    print("     _<language>.md       ← a clean version with the translation only")
    if os.path.exists(out + "_bilingual.md"):
        # 🔴 跟功能 2（410 行）、功能 5（880 行）同一題：直接 Enter＝不用（說明書教「一路 Enter 到底」）
        if ask("Open the bilingual file now? (Enter alone = No)", [("1", "Yes"), ("0", "No")],
               default="0") == "1":
            os.startfile(out + "_bilingual.md")
    pause()


def do_bilingual():
    print(C("\n[Live bilingual captions]", BOLD))
    print("  Source on top, translation underneath (Traditional Chinese, Japanese or English), shown at the same time.")
    m = ask("Where is the sound coming from?", [
        ("1", "Computer audio (YouTube / online meetings / online seminars)"),
        ("2", "Microphone (a guest is giving a talk in the room)"),
        ("3", "Both (hybrid meeting: in person + online)"),
        ("4", "Saved audio/video file (you pick the file; no other sound is recorded)"),
        ("0", "Back"),
    ])
    if m == "0":
        return
    path = None
    if m == "4":
        print(C("\n  Opening the file picker…", DIM))
        path = pick_file()
        if not path or not os.path.exists(path):
            print(C("  No file was selected.", YEL)); pause(); return
        print(f"  Selected: {C(os.path.basename(path), CYAN)}")
    mic_dev = ask_mic_device(both=m == "3") if m in ("2", "3") else None
    mic_raw = ask_mic_raw() if m == "2" else False

    q = ask("Fast or accurate?", [
        ("1", "Accurate – waits for each sentence to finish, then translates; about 2–3 seconds behind; natural word order (recommended)"),
        ("2", "Fast     – translates while listening; about 1 second behind, but the word order is sometimes awkward"),
    ])
    hq = (q == "1")

    # V1.39（使用者 10-07）：英文選項拿掉「聽中文演講、要英文字幕時」——講者說什麼語言都不用先設定。
    #    10-07 實測：「準」翻成英文時程式把講者語言寫死成中文（live_bilingual_hq.py 的 src_lang），講者說法文、西班牙文、日文
    #    照樣轉得對、翻得對，跟指定正確語言幾乎一樣（tio-v139\pretest）；「快」本來就自動判斷。
    print(C("\n  No need to set the speaker's language first; the program works it out by itself.", DIM))
    lang = ask("Translate into which language?", [
        ("1", "Traditional Chinese (Taiwan)"),
        ("2", "Japanese"),
        ("3", "English"),
    ])
    # 🔴 準確、快速共用同一份對應表。原本各有一份，快速模式那份寫成 en-US ——
    #    翻譯模型不收，每次連線都被 1007 拒絕、零字幕、無限重連
    #    （2026-09-11 對照實驗：en ✅ 25 行｜ja ✅ 23 行｜en-US ❌ 0 行）。
    #    兩份各改各的，就是這樣漂移出來的。
    target = {"1": "zh-TW", "2": "ja", "3": "en"}[lang]

    name = _in("\nWhat is this session called? (Enter alone = use today's date): ").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("Bilingual_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    if m in ("1", "3"):
        print(C("\n※ Note: choosing \"Computer audio\" records everything the computer is playing at the time,", YEL))   # V1.26：主控台不吃 Markdown，** 會原樣印出
        print(C("   so please close any unrelated videos and music before you start.", YEL))
    print(C(f"\n※ Grey = source, blue = translation. Delay: about {'2–3 seconds' if hq else '1 second'}.", BOLD))
    print(C(f"   {font_hint()}", DIM))
    print(C("※ Press Ctrl + C to stop; the files are saved to your desktop.", BOLD))
    if m in ("2", "3"):
        print(C("   Once started, avoid plugging or unplugging the headset; if the plug comes loose, it reconnects by itself and tells you.", DIM))
    _in(C("\nPress Enter when you are ready…", GRN))

    src = {"1": "system", "2": "mic", "3": "both", "4": "file"}[m]
    script = "live_bilingual_hq.py" if hq else "live_bilingual.py"
    args = [os.path.join(SCRIPTS, script),
            "--source", src, "--target", target, "--out", stem]
    if path:
        args += ["--file", path]
    if mic_raw:
        args.append("--mic-raw")
    if mic_dev:
        args += ["--mic-device", mic_dev]
    rc = run(args, f"Bilingual captions running ・ {'Accurate mode' if hq else 'Fast mode'} (press Ctrl+C to stop)", warmup=True)
    report_live(rc, stem)
    pause()


def _output_device_list():
    """去掉重覆、而且**真的開得起來**的播放裝置清單 [(編號, 名稱, 是否等於系統預設, 顯示用的名稱)]。

    V1.29 ⑤：「名稱」是交給口譯程式的值（MME 會截成 31 字，維持 V1.28 原樣不動）；「顯示用的名稱」是 Windows 的完整名稱。
    🔴 2026-09-27 全線實測：清單把 KONKA 顯示成「1 - KONKA LCDTV (AMD High Defin」（斷在單字中間）。完整名稱用口譯播放
       本來就在用的 _live._full_output_name（問 Windows 這個 MME 編號是哪個音訊端點）；問不到就照舊顯示截過的名稱。

    🔴 同一顆喇叭在 MME／DirectSound／WASAPI／WDM-KS 底下會各出現一次（這台實測 10 筆
       其實只有 3 顆），照原樣列給使用者看是災難。用名稱前 25 個字去重。
    🔴 更重要的是：**查得到 ≠ 播得出來**。同一台機器實測，WDM-KS 那兩顆會噴
       「Blocking API not supported」、WASAPI 那兩顆會噴「Invalid sample rate」——
       而且錯誤要等到會議開始才出現。所以這裡逐顆開開看（usable_only=True），
       開不起來的根本不列出來。去重要在過濾之後做，否則會留下壞的那一顆、
       把同名可用的那顆擠掉。
    """
    from _live import (output_devices, default_output_name, is_default_like, _DEFAULT_ALIASES, _full_output_name,
                       _output_endpoint_id)
    dflt = default_output_name()
    seen, devs = set(), []
    for i, n in output_devices(usable_only=True):
        low = n.strip().lower()
        # 🔴「Microsoft 音效對應表」「主要音效驅動程式」不是實體裝置，是跟著系統預設走的轉接器。
        #    列出來會多出兩筆「（目前的預設）」，只有一顆喇叭的電腦也會被問（2026-09-19 審查）。
        if any(a in low for a in _DEFAULT_ALIASES):
            continue
        try:
            import sounddevice as sd
            eid = _output_endpoint_id(sd, i)
        except Exception:
            eid = None
        # V1.31：同一顆認端點 ID。🔴 以前用名稱前 25 個字去重：兩顆不同的裝置前 25 個字一樣，後面那顆就不會列出來、選不到。
        key = (eid or "").lower() or low[:25]
        if key in seen:
            continue
        seen.add(key)
        try:
            label = _full_output_name(sd, i, n) or n
        except Exception:
            label = n                     # 顯示名稱問不到就用原本的，清單本身不能因此出錯
        devs.append((i, n, is_default_like(n, dflt, idx=i), label))
    return devs


def do_voice_translate():
    print(C("\n[Live voice translation (interpreter mode)]", BOLD))
    print("  Hear a talk or meeting in another language translated into Chinese in your headphones (or into Japanese or English).")
    print("  Bilingual captions still run on screen at the same time, and are saved at the end as usual.")
    print(C("\n  ※ With \"Computer audio\", the original audio and the interpreter voice must take two different routes;\n     you will be asked to choose each one shortly. You will only hear the interpretation.", YEL))

    m = ask("Where is the sound coming from?", [
        ("1", "Computer audio (Teams / Meet / Zoom / YouTube)"),
        ("2", "Microphone (a guest is giving a talk in the room)"),
        ("3", "Saved audio/video file (no other sound is recorded)"),
        ("0", "Back"),
    ])
    if m == "0":
        return

    path = None
    if m == "3":
        print(C("\n  Opening the file picker…", DIM))
        path = pick_file()
        if not path or not os.path.exists(path):
            print(C("  No file was selected.", YEL)); pause(); return
        print(f"  Selected: {C(os.path.basename(path), CYAN)}")

    # ── 兩條路線：原音走一條（聽不到）、口譯語音走另一條（聽得到）───────────────
    # 🔴 錄「電腦播出來的聲音」是側錄**系統預設播放裝置**正在播的東西。所以「不要聽到
    #    原音」沒辦法靠靜音達成——靜音等於把錄音來源一起關掉。唯一的做法是把原音送到
    #    一顆使用者聽不到的輸出（沒接線的 SPDIF／HDMI、沒戴上的耳機、虛擬音效線），
    #    口譯語音則播到會響的那一顆。程式負責切換系統預設輸出，結束後自動還原。
    # 🔴 哪一條「聽不到」只有使用者知道：光纖孔沒有可靠的插拔偵測、耳機有沒有戴在頭上
    #    Windows 也查不到。所以兩條路線一律讓他自己指定，選完先試聽驗證，不要讓程式猜。
    device = None
    route_original = None
    if m == "1":
        try:
            import _audioroute as ar
            ar._refresh_sounddevice()       # 同一個選單視窗第二次進來時，才插上的耳機也要看得到
            routes = ar.list_routes(probe_speak=True)
        except Exception as e:
            print(C(f"\n  ✗ Could not look up the playback devices: {e}", RED)); pause(); return
        if not routes:
            # 🔴 一條都查不到有兩種可能：喇叭／耳機都沒接（插孔偵測標成未插入），或聲音元件這一刻沒回應
            #    （重新初始化失敗、sounddevice 載不起來）。程式分不出來，兩種都要講；走下面「只有一個輸出」
            #    那段是誤導（2026-09-19 審查）。
            print(C("\n  ✗ No usable playback device found: maybe no speakers/headphones are connected, or the sound components did not respond just now.", YEL))
            print(C("     After connecting, press Enter, then choose 6 again in the menu; if it still fails, close the menu window and reopen it.", DIM))
            pause(); return
        # 🔴 兩條路線卻對到同一個播放裝置（程式分不出來）也算只有一個：不然①選哪條都會被卡在
        #    「剩下的路線都播不出口譯語音」的迴圈裡，只能按 0 離開（2026-09-19 審查）
        if len(routes) < 2 or len({r.get("sd_index") for r in routes}) < 2:
            print(C("\n  ✗ This computer has only one sound output, so this mode cannot be used.", YEL))
            print(C("     The original audio and the interpreter voice must take two different routes; otherwise you will hear both at once,", DIM))
            print(C("     and the interpreter voice gets recorded back in, so it ends up translating itself.", DIM))
            print(C("\n     Fix: plug in headphones; that usually adds a second route (tested OK with wired ones on one laptop; Bluetooth untested).", GRN))
            print(C("     Without headphones, use \"2 Microphone\" or \"3 Saved audio/video file\" instead; those two do not have this limit.", DIM))
            pause(); return

        while True:
            print(C("\n  This mode needs two routes. Please choose each one:", BOLD))
            print(C("\n  ① Which route should the original audio (the meeting sound) take?", BOLD))
            print(C("     You will NOT hear this one; it is only used for recording. Pick an output with no speakers or headphones connected,", DIM))
            print(C("     e.g. a digital output with no cable plugged in, or headphones that are plugged in but that you will not wear.", DIM))
            opts = [(str(k), r["name"]) for k, r in enumerate(routes, 1)]
            opts.append(("0", "Back"))
            pick = ask("", opts)
            if pick == "0":
                return
            src_route = routes[int(pick) - 1]

            # 🔴 跟①對到同一個播放裝置（sd_index）的也要排除：名稱對不出來、退回比開頭時，兩條路線可能
            #    是同一顆，試聽兩聲會從同一顆出來（2026-09-19 審查）
            rest = [r for r in routes if r["id"] != src_route["id"] and r["speakable"]
                    and r.get("sd_index") != src_route.get("sd_index")]
            if not rest:
                if any(r["id"] != src_route["id"] and r["speakable"]
                       and r.get("sd_index") == src_route.get("sd_index") for r in routes):
                    print(C("\n  ✗ The remaining playable routes are on the same playback device as ① (the program cannot tell them apart);\n     please choose another route for the original audio.", YEL))
                else:
                    print(C("\n  ✗ None of the remaining routes can play the interpreter voice; please choose another route for the original audio.", YEL))
                continue
            print(C("\n  ② Where do you want to hear the interpreter voice? (you DO need to hear this one)", BOLD))
            opts = [(str(k), r["name"]) for k, r in enumerate(rest, 1)]
            opts.append(("0", "Choose again"))
            pick = ask("", opts)
            if pick == "0":
                continue
            spk_route = rest[int(pick) - 1]

            # ── 試聽：選反了當場就發現，不必等到開會中才知道 ────────────────
            while True:
                print(C("\n  [Listening test] Each route plays one beep, to check they are not the wrong way round:", BOLD))
                print(f"    ① Original audio route \"{src_route['name']}\"… ", end="", flush=True)
                ok1, e1 = ar.play_test_tone(src_route["sd_index"], freq=660)
                print(C("you should NOT hear this beep", DIM) if ok1 else C(f"could not play it ({e1})", YEL))
                time.sleep(0.5)
                print(f"    ② Interpreter route \"{spk_route['name']}\"… ", end="", flush=True)
                ok2, e2 = ar.play_test_tone(spk_route["sd_index"], freq=990)
                print(C("you SHOULD hear this beep", DIM) if ok2 else C(f"could not play it ({e2})", YEL))

                ans = ask("\n  Was that right?", [
                    ("1", "Yes: I did not hear the first beep, and I heard the second"),
                    ("2", "No, choose both routes again"),
                    ("3", "I didn't catch it, play them again"),
                    ("0", "Back"),
                ])
                if ans != "3":
                    break
            if ans == "0":
                return
            if ans == "2":
                continue
            device = spk_route["device_name"]
            route_original = src_route["id"]
            print(C(f"\n  ✓ The original audio goes to \"{src_route['name']}\" (you won't hear it); the interpreter voice comes out of \"{spk_route['name']}\".", GRN))
            print(C("     At the start, the program switches the system sound output over automatically, and switches it back at the end.", DIM))
            break

    # ── 麥克風／影音檔：口譯語音要從哪裡播 ───────────────────────────────────────
    # 🔴 B3（2026-09-19 筆電實測）：原本只有選「1」才問裝置，選 2／3 一律交給「程式啟動那一刻的
    #    Windows 預設播放裝置」。實測使用者戴著耳機，口譯卻從接 HDMI 的電視出來（預設是電視）；
    #    畫面那句「翻譯語音將從『…』播出」要按 Enter 之後才看得到，看到了也改不了。
    #    _output_device_list()（去重、逐顆試開）早就寫好，只是一直沒接上。
    if m in ("2", "3"):
        try:
            import _audioroute as ar
            # 🔴 PortAudio 的裝置清單啟動後不會自己更新：同一個選單視窗第二次進來時，
            #    才插上的耳機會看不到、「目前的預設」也是舊的。這時選單沒有在播放或錄音，重新初始化是安全的
            #    （試開裝置時萬一留下沒關的串流，PortAudio 關閉時會自己收掉）。
            ar._refresh_sounddevice()
            devs = _output_device_list()
        except Exception as e:
            devs = []
            print(C(f"\n  ⚠ Could not list the playback devices ({e}); the interpretation will play on the Windows default playback device.", YEL))
        else:
            if not devs:        # output_devices() 出錯時會吞掉、回空清單：一樣要講，不然使用者不知道沒問
                print(C("\n  ⚠ Could not list the playback devices; the interpretation will play on the Windows default playback device.", YEL))
        while len(devs) > 1:
            print(C("\n  Where do you want to hear the interpreter voice?", BOLD))
            if m == "2":
                # V1.32：補「停不下來、一直計費」（2026-09-28 使用者實際選了喇叭：講完之後一直重複同一句）
                print(C("     Please choose the headphones you are wearing. If you choose speakers, the microphone records the interpretation\n     and the model keeps translating its own words over and over without stopping, and you are charged the whole time.", DIM))
            opts = [(str(k), lab + (" (current default)" if d else ""))
                    for k, (_i, _n, d, lab) in enumerate(devs, 1)]
            opts.append(("0", "Back"))
            pick = ask("", opts)
            if pick == "0":
                return
            idx, dev_name, _d, label = devs[int(pick) - 1]     # dev_name 交給程式、label 給人看（V1.29 ⑤）
            print(f"    Test beep on \"{label}\"… ", end="", flush=True)
            try:
                import _audioroute as ar
                ok, err = ar.play_test_tone(idx, freq=990)
            except Exception as e:
                ok, err = False, e
            print(C("you should hear one beep", DIM) if ok else C(f"could not play it ({err})", YEL))
            ans = ask("  Did you hear it where you wanted?", [
                ("1", "Yes"),
                ("2", "No, choose again"),
                ("0", "Back"),
            ])
            if ans == "0":
                return
            if ans == "1":
                device = dev_name
                print(C(f"\n  ✓ The interpreter voice will come out of \"{label}\".", GRN))
                break
        # 🔴 2026-09-23 使用者指示（選項 B）：只剩一個播放裝置時，上面那個迴圈完全不跑——不問、也不講，
        #    口譯就從那一顆（通常是筆電喇叭）放出來。使用者拔掉耳麥後進來，以為「選輸出口的步驟被改壞了」。
        #    改成明講會從哪裡出來、怎麼改用耳機；選麥克風時再問一次要不要繼續（喇叭的口譯現場都聽得到，
        #    而且會被麥克風錄回去、一直重複翻，見 V1.32 那段），一定要輸入 1 或 0，不接受直接 Enter。
        if len(devs) == 1:
            only = devs[0][3]          # 只拿來顯示（V1.29 ⑤：完整名稱）；這條路本來就不傳裝置給口譯程式
            print(C(f"\n  ⚠ This computer has only one playback device right now: the interpreter voice will come out of \"{only}\".", YEL))
            print(C("     To listen with headphones, plug them in first, then go back to the menu and choose 6.", YEL))
            if m == "2":
                # V1.32：原本寫「可能被麥克風收進去、再翻一次」太輕——實測收回去之後會一直重複、停不下來、一直計費
                print(C("     If you continue like this, everyone in the room will hear the interpretation, and the microphone will record it back in:\n     the model keeps translating it over and over without stopping, and you are charged the whole time.", DIM))
                if ask("Continue? Type 1 or 0, then press Enter:", [
                    ("1", f"Continue, playing the interpretation through \"{only}\""),
                    ("0", "Back (plug in headphones first)"),
                ]) == "0":
                    return

    mic_dev = ask_mic_device() if m == "2" else None

    # V1.39（使用者 10-07）：英文選項拿掉「聽中文演講、要英文語音時」——口譯模型只設定要翻成什麼語言，講者說的語言由它自己判斷
    #    （Google〈Live translation with Gemini Live API〉：70 多種語言）。
    print(C("\n  No need to set the speaker's language first; the program works it out by itself.", DIM))
    lang = ask("Translate into which language?", [
        ("1", "Traditional Chinese (Taiwan)"),
        ("2", "Japanese"),
        ("3", "English"),
    ])
    # 🔴 語言碼跟功能 3 共用同一份對應表的值，改的時候兩邊要一起改。
    #    zh-TW 與官方語言表的 zh-Hant 實測等價（各 3 次，都出繁體臺灣用語）；
    #    zh-Hant-TW 與 cmn-Hant-TW 會被伺服器以 1007 拒絕，不要拿來用。
    target = {"1": "zh-TW", "2": "ja", "3": "en"}[lang]

    name = _in("\nWhat is this session called? (Enter alone = use today's date): ").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("Interpretation_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    if m == "1":
        print(C("\n※ Note: this records everything the computer is playing, so close any unrelated videos and music before you start.", YEL))   # V1.26：同上，拿掉 **
    if m == "2":
        print(C("\n※ Please wear headphones. If the interpreter voice comes out of speakers, the microphone records it\n   and the model keeps translating its own words over and over without stopping, and you are charged the whole time.", YEL))
    print(C("\n※ You will hear the interpreter voice; on screen, grey = source and blue = translation. Delay: about 1–2 seconds.", BOLD))
    print(C(f"   {font_hint()}", DIM))
    print(C("※ Press Ctrl + C to stop; the files are saved to your desktop.", BOLD))
    _in(C("\nPress Enter when you are ready…", GRN))

    src = {"1": "system", "2": "mic", "3": "file"}[m]
    args = [os.path.join(SCRIPTS, "live_bilingual.py"),
            "--source", src, "--target", target, "--out", stem, "--speak"]
    if mic_dev:
        args += ["--mic-device", mic_dev]
    if device is not None:
        args += ["--speak-device", device]
    if route_original:
        args += ["--route-original", route_original]
    if path:
        args += ["--file", path]
    rc = run(args, "Live voice translation running (press Ctrl+C to stop)", warmup=True)
    report_live(rc, stem)
    pause()


def do_json_to_md():
    print(C("\n[Rebuild or rescue a transcript]", BOLD))
    print("  Every transcript made with feature 2 has a .json data file with the same name next to it.")
    print("  This rebuilds the .json into a readable .md.")
    print(C("\n  Two uses:", BOLD))
    print("    ・Transcription crashed or was closed halfway → only a .partial.json is left; rescue it with this")
    print("    ・You want to change speaker names or rebuild the layout → no need to transcribe the whole recording again")
    print(C("\n  Runs entirely on this computer: no internet, no API calls, no cost.", GRN))
    print(C("\n  Opening the file picker… (if you don't see it, check the taskbar)", DIM))
    path = pick_file(json_only=True)
    if not path or not os.path.exists(path):
        print(C("  No file was selected.", YEL)); pause(); return
    print(f"  Selected: {C(os.path.basename(path), CYAN)}")

    # 先讀一次，把裡面有幾位講者告訴使用者，才知道要填幾個名字
    n_spk, n_seg, preview, known = 0, 0, [], {}
    try:
        from json_to_md import load_transcript, speaker_list, generic_names, saved_names   # 讀法與講者排法都只有這一份
        segs, _meta = load_transcript(path)
        if not isinstance(segs, list) or not segs:
            print(C("\n  ✗ This .json contains no transcript paragraphs.", RED))
            print(C("     Please pick the \"_transcript.json\" or \"_transcript.partial.json\" produced by feature 2.", DIM))
            pause(); return
        # 🔴 2026-09-21 筆電第四輪驗收 P1：要在**問講者名字之前**就擋下功能 4 的對照檔。
        #    以前這裡照單全收，還報得出「6 段、2 位講者」，同事完全不會懷疑自己選錯檔，
        #    最後拿到一份警語全失、畫面打 ✅ 的「乾淨」逐字稿。
        #    kind 是新版寫的；translation 欄是為了認出桌面上早就存在的舊 _對照.json。
        #    json_to_md.py 那支也擋一次（CLI 直接跑不會經過這裡）——兩層保險。
        if (_meta.get("kind") == "translation-pair"
                or any("translation" in s for s in segs[:5] if isinstance(s, dict))):
            print(C("\n  ✗ This is a bilingual file produced by translation (feature 4), not a transcript.", RED))
            print(C("     It holds \"source + translation\" pairs. Rebuilding it would lose the original gap warnings", DIM))
            print(C("     and produce a transcript that looks complete but is not.", DIM))
            # 🔴 2026-09-21 筆電第五輪觀察-1：先確認「隔壁那個檔」真的在，再叫使用者去找它。
            b = os.path.basename(path)
            if b.endswith("_bilingual.json"):
                sib = b[:-len("_bilingual.json")] + ".json"
                if os.path.exists(os.path.join(os.path.dirname(path), sib)):
                    print(C(f"     You probably want \"{sib}\" in the same folder.", DIM))
            print(C("     To rebuild the translation, just press 4 in the menu, pick the transcript file and run the translation again.", DIM))
            pause(); return
        n_seg = len(segs)
        spks = speaker_list(segs)             # 數字排序（V1.22 ②）；順序跟 json_to_md 套名字的一樣
        n_spk = len(spks)
        # 切段的錄音第 2 段起是「第2段講者1」（V1.22 ③）；功能 2 填過名字的用那個名字（V1.26 C2，同功能 4）
        known = saved_names(spks, _meta)
        label = dict(generic_names(spks), **known)
        for sp in spks:                       # 每位講者的第一句，幫使用者對號入座
            first = next((s for s in segs
                          if isinstance(s, dict) and s.get("speaker", "spk:0") == sp), None)
            if first:
                preview.append((label[sp], (first.get("text") or first.get("raw") or "").strip()[:40]))
    except Exception as e:
        print(C(f"\n  ✗ This file cannot be read: {type(e).__name__}", RED))
        print(C(f"     {str(e)[:120]}", DIM))
        print(C("     Please check that you picked a .json produced by feature 2.", DIM))
        pause(); return

    print(C(f"\n  This file has {n_seg} paragraph(s) and {n_spk} speaker(s).", BOLD))
    if ".partial." in os.path.basename(path):
        print(C("  (This is the temporary file left behind when the job was interrupted; it contains what had been transcribed by then.)", YEL))
    for who, txt in preview:
        print(C(f"    {who} – first line: {txt}…", DIM))

    print(C(f"\nSpeaker names (optional; if you enter them, enter {n_spk})", BOLD))
    print(C("  Enter them in the order shown above (\"Speaker 1, Speaker 2…\"), separated by commas (a name can contain spaces, e.g. a full name; if no name contains a space, spaces work too).", DIM))
    if known:
        print(C(f"  e.g. Chair Wang, Ms Li    Press Enter alone to keep the names above ({', '.join(known.values())}); speakers without a name get \"Speaker N\".", DIM))
    else:
        print(C("  e.g. Chair Wang, Ms Li    Press Enter alone to keep \"Speaker 1, Speaker 2\".", DIM))
    names = ask_names()
    if names and len(names) != n_spk:
        print(C(_names_warning(len(names), n_spk, "\"Speaker N\""), YEL))

    base = os.path.basename(path)
    for suf in (".partial.json", ".json"):
        if base.endswith(suf):
            base = base[:-len(suf)]
            break
    out = safe_stem(os.path.join(DESKTOP, base), (".md",)) + ".md"
    args = [os.path.join(SCRIPTS, "json_to_md.py"), path, "--out", out]
    if names:
        args += ["--names"] + names
    run(args, "Rebuilding (on this computer only; takes a few seconds)")
    if os.path.exists(out):
        # 🔴 2026-09-20 筆電全流程檢測（⚠-12）：這裡本來**無條件**印 ✅，所以一份原本標著
        #    「可能不完整」的逐字稿，重排一次就變成綠勾。比照功能 2：讀檔頭決定 ✅ 還是 ⚠。
        #    兩個標記字串跟 transcribe_meeting.py／json_to_md.py 寫檔頭的地方必須一致。
        head5 = io.open(out, encoding="utf-8", errors="replace").read(3000).split("\n---\n", 1)[0]
        if ("**This transcript may be incomplete**" in head5 or "part(s) failed to transcribe; this transcript is incomplete" in head5
                or "This was rescued from an interrupted temporary file" in head5):
            print(C(f"\n⚠ The transcript is on your desktop: {os.path.basename(out)}, but its header says \"may be incomplete\" (flagged when first transcribed; see the header)", YEL))
        else:
            print(C(f"\n✅ The transcript is on your desktop: {os.path.basename(out)}", GRN))
        if ask("Open it now? (Enter alone = No)", [("1", "Yes"), ("0", "No")], default="0") == "1":
            os.startfile(out)
    else:
        print(C("\n✗ No file was created; there should be an error message above.", RED))
    pause()


def ensure_api_key():
    """
    這個視窗要有一組金鑰才能連線。依序找：環境變數 → 電腦裡記住的（登錄檔）→ 請使用者貼。

    🔴 不能只看環境變數：金鑰是用 setx 存的，setx 只寫登錄檔，「存之前就開著」的程式
       （例如安裝精靈）和它開出來的視窗都看不到。2026-09-19 使用者回報「安裝時貼過，
       選功能又要再貼一次」——從精靈「立即開始使用」開的選單每次都會這樣。
    """
    if os.environ.get(_apikey.NAME):
        return True
    saved = _apikey.saved()
    if saved:
        _apikey.use(saved)
        return True
    print(C("\nThis is your first time using it, so you need a Gemini API key to connect.", BOLD))
    print(C("  If you don't have one, get one free at aistudio.google.com/apikey (it takes about a minute).", DIM))
    return ask_new_key()


def ask_new_key():
    """
    請使用者貼一組金鑰：輸入時顯示 *、收到後遮蔽確認、檢查格式、跟 Google 確認、問要不要記住。
    回 True＝這個視窗已經有可用的金鑰。

    🔴 不要用 input()：金鑰會明文留在畫面上，而使用說明教同事截圖這個視窗寄給別人。
    🔴 也不要回到 getpass：它完全不回顯，貼了看不到任何反應，使用者以為貼不上去（2026-09-19 回報）。
    """
    while True:
        key = _apikey.read_secret(
            "\nPaste your API key and press Enter (each character shows as *; Enter alone = cancel): ")
        key = key.strip().strip('"')
        if not key:
            print(C("  Nothing was entered; cancelled.", YEL))
            return False
        print(C(f"  Received: {_apikey.mask(key)}", DIM))
        level, why = _apikey.format_problem(key)
        if level == "bad":
            print(C(f"  ✗ This does not look like a key: {why}", YEL))
            print(C("    Please go to aistudio.google.com/apikey, click \"Copy\" next to the key, and paste it again.", DIM))
            continue
        print(C("  Checking this key with Google…", DIM))
        status, msg = _apikey.verify(key)
        if status == "bad":
            print(C(f"  ✗ {msg}", RED))
            if ask("What would you like to do?", [("1", "Paste a different key"), ("0", "Not now (back to the menu)")]) == "1":
                continue
            return False
        if status == "ok":
            print(C(f"  ✓ {msg}", GRN))
        else:
            print(C(f"  ⚠ {msg}", YEL))
            if level == "odd":
                print(C(f"    Also: {why}", YEL))
            print(C("    It will be used anyway for now; if it fails to connect later, choose 9 in the menu to check or change it.", DIM))
        _apikey.use(key)
        old = _apikey.saved()
        other = bool(old) and old != key       # 電腦裡記著的是另一組（通常就是要換掉的那組）
        _apikey.drain_input()                   # 驗證時多按的 Enter 不要被當成這一題的答案
        if ask("Remember this key so you don't have to paste it next time?", [
                ("1", "Yes" + (" (replaces the old key saved on this PC)" if other else "")),
                ("0", "Just this once" + (" (next time the program goes back to the old key saved on this PC)" if other else "")),
        ]) == "1":
            ok, err = _apikey.remember(key)
            if ok:
                print(C("  Saved. It will be used automatically the next time you open the program.", GRN))
            else:
                print(C(f"  Could not save it ({err}), but you can still use it normally this time.", YEL))
        return True


def do_api_key():
    print(C("\n[API key settings]", BOLD))
    cur, saved = os.environ.get(_apikey.NAME), _apikey.saved()
    print(f"  Used in this window: {_apikey.mask(cur)}")
    print(f"  Saved on this PC   : {_apikey.mask(saved)}")
    c = ask("What would you like to do?", [
        ("1", "Change to a new key"),
        ("2", "Check whether the current key works (asks Google; free)"),
        ("3", "Clear the key saved on this PC (for shared PCs, or before handing the PC back)"),
        ("0", "Back"),
    ])
    if c == "0":
        return
    if c == "1":
        ask_new_key()
    elif c == "2":
        key = cur or saved
        if not key:
            print(C("\n  There is no key at the moment; please choose 1 to paste one.", YEL))
        else:
            print(C("\n  Checking with Google…", DIM))
            status, msg = _apikey.verify(key)
            mark, color = {"ok": ("✓", GRN), "bad": ("✗", RED)}.get(status, ("⚠", YEL))
            print(C(f"  {mark} {msg}", color))
    elif not cur and not saved:
        print(C("\n  No key is saved, so there is nothing to clear.", DIM))
    elif ask("Are you sure you want to clear it? After clearing, you will have to paste it again the next time you use the program.",
             [("1", "Yes, clear it"), ("0", "Cancel")]) == "1":
        _, err = _apikey.forget()
        if err:
            print(C(f"  ✗ Could not clear it: {err}", RED))
        else:
            print(C("  ✓ Cleared. This window no longer uses it either.", GRN))
    pause()


def _offer_key_fix():
    """工具失敗之後問 Google 一次：是不是金鑰壞了？是的話當場讓使用者換，不必自己找設定在哪。"""
    key = os.environ.get(_apikey.NAME)
    if not key:
        return
    print(C("\n  Checking whether that failure was caused by the key…", DIM))   # 要連網，最多幾秒；不講一聲會像當掉
    status, why = _apikey.verify(key, timeout=5)
    if status != "bad":
        return
    print(C(f"\nThat failure was caused by the key: {why}", YEL))
    print(C(f"  Current key: {_apikey.mask(key)}", DIM))
    if ask("Change to a different key now?", [("1", "Yes, change it now"), ("0", "Not now")]) == "1":
        ask_new_key()
        pause()


LOCAL_ONLY = {"5"}      # 這些功能純本機處理，不連 Gemini，不需要金鑰


def _unblock_self():
    """
    開場把整包的「來自網路」標記清掉，回傳清了幾個。

    🔴 為什麼安裝時清過還要再清一次：拿到新版的人習慣「解壓縮覆蓋舊的」，標記會
       整包回來，而更新時不一定會再點 3_安裝.bat —— 下次點 4_開始使用.bat 就又被
       Windows 攔（實測 WinRAR 只把標記蓋在 5 支 .bat ＋ rescue.ps1 上，剛好全是
       會被雙擊的那幾個）。能跑到這一行代表使用者已經按過一次「執行」，
       所以在這裡清是白賺的：以後就不會再被問。
    失敗一律當沒事 —— 這只是省掉一個警告視窗，不值得擋住選單。
    """
    try:
        from _winpath import unblock_files, zone_marked_files
        done, _fail = unblock_files(zone_marked_files(ROOT))
        return len(done)
    except Exception:
        return 0


def _recover_audio_route():
    """上次功能 6 沒有正常結束（當機、被工作管理員砍掉）時，一打開選單就把聲音輸出改回來。

    🔴 原本只有「再跑一次功能 6 選 1」才會補還原：使用者只開選單、改用別的功能時，
       電腦就一直停在「聽不到」的那條路線（2026-09-19 驗收時發現）。
    """
    try:
        import _audioroute
        return _audioroute.recover_if_needed()
    except Exception:
        return None


def main():
    global _last_rc
    key_ok = False
    # 只在標題下方講一次就好，回選單時不要一直佔版面
    unblocked = _unblock_self()
    route_note = None
    while True:
        # 每次回到選單都檢查：功能 6 就是從這個選單開的，它當掉或被砍之後使用者會繼續用同一個選單
        route_note = route_note or _recover_audio_route()
        os.system("cls")
        print(C("\n  TIO Voice Genie", BOLD))
        print(C("  " + "═" * 44, DIM))
        if unblocked:
            print(C(f"  (Unblocked {unblocked} file(s) that had the \"from the internet\" mark, so the shortcut will no longer show a security warning)", DIM))
            unblocked = 0
        if route_note:
            print(C(f"  ({route_note})", YEL))
            route_note = None
        c = ask("Type a number and press Enter:", [
            ("1", "Live meeting captions    – see captions while the meeting runs"),
            ("2", "Recording to transcript  – turn an audio or video recording into text"),
            ("3", "Live bilingual captions  – source + translation together (Chinese, English, Japanese)"),
            ("4", "Transcript to bilingual  – translate the whole file, far better than live"),
            ("5", "Rebuild a transcript     – redo from .json / rename speakers, free"),
            ("6", "Live voice translation   – hear only the interpreter, not the original (interpreter mode)"),
            ("9", "API key settings         – change the key, check it works, clear the saved one"),
            ("0", "Close"),
        ])
        if c == "0":
            return
        if c == "9":
            do_api_key()
            key_ok = bool(os.environ.get(_apikey.NAME))
            continue
        # 需要連線的功能才問金鑰；5 是純本機處理，轉檔當掉時也一定救得回來
        if c not in LOCAL_ONLY and not key_ok:
            if not ensure_api_key():
                _in("\nPress Enter to return to the menu…")
                continue
            key_ok = True
        _last_rc = None
        {"1": do_live, "2": do_transcribe, "3": do_bilingual,
         "4": do_translate, "5": do_json_to_md,
         "6": do_voice_translate}[c]()
        # 失敗了（不是正常結束、不是使用者取消、不是「沒有聲音來源」）就順便確認是不是金鑰壞了
        if c not in LOCAL_ONLY and _last_rc not in (None, 0, 2, CANCEL_RC) and not _run_interrupted:
            _offer_key_fix()


def _entry():
    """
    🔴 從 2026-09-11 起，4_開始使用.bat 用 start 開一個新視窗跑這支、自己立刻結束。
       原因：bat 還在執行時按過 Ctrl+C（即時字幕本來就要按），最後關閉時 cmd 一定會補問
       英文的「Terminate batch job (Y/N)?」—— 試過四種 bat 寫法都擋不掉。
       代價是 bat 原本「出錯時停下來讓人看訊息」沒了，所以這裡要自己接住執行中的錯誤、停下來，
       否則視窗會一閃就關，同事什麼都看不到。
    🔴 載入階段的錯誤（缺檔、檔案壞掉，連這個函式都還沒跑到）這裡接不到，由 bat 那一行的
       「|| if not errorlevel 3 pause」讓視窗停住。這裡顯示過錯誤、等過使用者之後用 3 結束，
       bat 看到 3 就不會再停第二次（2026-09-11 稽核抓到：原本這類錯誤會一閃就關）。
    """
    try:
        set_console_icon()     # 選單這個主控台視窗的標題列／Alt-Tab 圖示
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        print(C("\n✗ The program hit an error and has stopped.", RED))
        print(C("  If you need help, double-click 6_Diagnostics.bat and send screenshots of both this window and the diagnostics window.", DIM))
        print(C("\n  Technical details (for whoever is helping you):", DIM))
        print(C(traceback.format_exc().rstrip(), DIM))
        try:
            input(C("\nPress Enter to close the window…", DIM))
        except (EOFError, KeyboardInterrupt):
            pass
        sys.exit(3)        # 3＝錯誤已經顯示、使用者也看過了（bat 靠它判斷要不要再停一次）


if __name__ == "__main__":
    _entry()
