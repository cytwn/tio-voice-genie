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
    _in(C("\n按 Enter 回選單…", DIM))


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
        print(C("  請輸入上面其中一個號碼。", YEL))


def _names_warning(n_got, n_spk, fallback):
    """講者名字填的數量跟講者數不一樣時的提醒。🔴 2026-09-20 筆電實測 N6-7：原本不分多少一律說
    「沒填到的會沿用…」，那只適用於填太少；填太多時多出來的名字根本用不到。"""
    if n_got > n_spk:
        return f"  ⚠ 你填了 {n_got} 個，但這份只有 {n_spk} 位講者；多出來的 {n_got - n_spk} 個名字用不到，會被略過。"
    return f"  ⚠ 你填了 {n_got} 個，但這份有 {n_spk} 位講者；沒填到的會沿用{fallback}。"


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
    names = split_names(_in("\n講者名字："))
    if names:
        print(C(f"  讀到 {len(names)} 位：{'／'.join(names)}", DIM))
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
                title="選擇逐字稿 .json 檔",
                filetypes=[("逐字稿資料檔", "*.json"), ("所有檔案", "*.*")])
            r.destroy()
            return p
        # 🔴 2026-09-20 筆電實測 N6-6：功能 4（transcript=True）預設只列 .json／.srt，標題卻寫「選擇會議錄音檔」
        p = filedialog.askopenfilename(
            title="選擇逐字稿、字幕或錄音檔" if transcript else "選擇會議錄音檔",
            # 🔴 第一個篩選器就是視窗打開時的預設。標題說「逐字稿、字幕或錄音檔」，
            #    第一個卻是「逐字稿或字幕」，音檔整個看不到（2026-09-20 筆電 ⚠-5）。
            filetypes=([("所有支援的檔案",
                         "*.json *.srt *.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.opus "
                         "*.mp4 *.mov *.mkv *.avi *.webm"),
                        ("逐字稿或字幕", "*.json *.srt"),
                        ("音訊或影片", "*.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.mp4 *.mov *.mkv *.avi"),
                        ("所有檔案", "*.*")] if transcript else
                       [("音訊或影片", "*.mp3 *.m4a *.wav *.wma *.aac *.flac *.ogg *.mp4 *.mov *.mkv *.avi"),
                        ("所有檔案", "*.*")]))
        r.destroy()
        return p
    except Exception:
        return _in("請把錄音檔拖進來，然後按 Enter：").strip().strip('"')


def safe_name(name):
    """
    把使用者輸入的名稱變成合法檔名。

    🔴 台灣行政人員寫日期習慣用「9/8」，直接接到路徑上會變成不存在的子目錄，
       程式當場噴 FileNotFoundError。Windows 不允許的字元一律換成底線。
    """
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    if cleaned != name:
        print(C(f"  （檔名不能有 \\ / : * ? \" < > |，已改成：{cleaned}）", DIM))
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

    print(C("\n講者名字（選填）", BOLD))
    if preview:
        print(C(f"  這份有 {n_spk} 位講者：", DIM))
        for who, txt in preview:
            print(C(f"    {who} 第一句：{txt}…", DIM))
        print(C(f"  照順序填 {n_spk} 個，用空白隔開；名字本身有空白（例如英文全名）就改用逗號隔開。", DIM))
    else:
        print(C("  這是音檔，還沒轉檔、現在還不知道有幾位講者。", DIM))
        print(C("  知道的話照「先開口的順序」填，用空白隔開（名字本身有空白就改用逗號）；不確定就直接 Enter。", DIM))
    # 🔴 to 是 None（功能 4 選「1 自動判斷」，而且它是第一個選項）時，目標語言要等
    #    translate_transcript 自己判：中文稿→英文（Speaker 1）、英文稿→臺灣繁體（講者1），
    #    選單另外指定才會是日文（話者1）。舊版一律印「講者1、講者2」，但自動判斷碰到
    #    中文稿時三份輸出檔（_對照.md／_對照表.md／_en.md）全寫 Speaker 1，
    #    畫面講的和檔案寫的對不起來（2026-09-15 對抗式複查 R3-1）。
    #    這裡不 import translate_transcript（選單不該為了一句提示去載翻譯模組、
    #    也避免音檔輸入時根本還沒轉檔、無從判斷），改成把三種可能都講清楚、不猜一種。
    if to is None:
        eg = ("譯文語言的預設編號：中文稿翻英文是「Speaker 1、Speaker 2」，"
              "英文稿翻中文是「講者1、講者2」，翻日文是「話者1、話者2」")
        egN = "譯文語言的預設編號（英文「Speaker N」、中文「講者N」、日文「話者N」）"
    else:
        fallback = {"en": "Speaker 1、Speaker 2", "ja": "話者1、話者2"}.get(to, "講者1、講者2")
        eg = f"「{fallback}」"
        egN = f"「{fallback.split('、')[0][:-1]}N」"
    if known:
        print(C(f"  例如：處長 秘書　　直接 Enter 就沿用上面的名字（{'、'.join(known.values())}）；"
                f"沒有名字的講者用{eg}。", DIM))
    else:
        print(C(f"  例如：處長 秘書　　直接 Enter 就沿用{eg}。", DIM))
    got = ask_names()
    if got and n_spk and len(got) != n_spk:
        print(C(_names_warning(len(got), n_spk, egN), YEL))
    return got


def ask_vocab():
    print(C("\n專有名詞（很重要，會大幅提高正確率）", BOLD))
    print(C("  例如：深耕計畫 研發處 會計室 教學組長", DIM))
    print(C("  用空白隔開，直接按 Enter 可以跳過。", DIM))
    v = _in("\n專有名詞：").strip()
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
        print(C(f"\n✅ 檔案在桌面：{base}.md（給人讀）"
                + (f"／{base}.txt（備份）" if has_txt else ""), GRN))
        if rc not in (0, None):
            print(C("   （程式是非正常結束的，內容可能不完整，請開檔確認）", YEL))
    elif has_txt:
        print(C(f"\n⚠ 只有即時備份：{base}.txt（在桌面）", YEL))
        print(C("   整理好的 .md 沒有產生——程式應該是被中途關掉或出錯了。", DIM))
        print(C("   已經辨識出來的字幕都在這個 .txt 裡，用記事本就打得開。", DIM))
    elif cancelled:
        # 使用者自己取消的，不是故障：不要叫他去找錯誤訊息、更不要叫他截圖回報。
        print(C("\n✗ 已取消，沒有產生任何檔案。", YEL))
        print(C("   （這不是錯誤——你按了 Ctrl+C。要重來就回選單再選一次。）", DIM))
    else:
        print(C("\n✗ 沒有產生任何檔案。", RED))
        print(C("   上面應該有錯誤訊息，請往上捲看看；", DIM))
        print(C("   需要協助時，點兩下 6_診斷.bat 並把整個視窗截圖回報。", DIM))


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
    print(C(f"\n  ⚠ 桌面上已經有同名的檔案了，這次改存成："
            f"{os.path.basename(new)}", YEL))
    print(C("     （原本那份完全沒有被動到）", DIM))
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
        print(C("  正在啟動…第一次開啟要載入語音元件，可能要 30 秒，請稍候。", DIM))
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
    opts = [("1", f"讓程式自己選（建議）：現在會用「{dflt or '查不到'}」；中途拔掉或插上耳麥，會自動跟著換")]
    opts += [(str(i), f"只用「{n}」：全程固定這一支，拔掉或插上耳麥都不換"
                      + ("　← 現在 Windows 的預設就是這一支" if dflt and n == dflt else ""))
             for i, n in enumerate(names, 2)]
    # 🔴 2026-09-25（V1.21 ③）：使用者在「兩者都要」選了固定耳麥、拔掉後字幕還在跑，以為固定失效。
    #    拔插實測：麥克風那一路確實停了；還在出字幕的是電腦聲音那一路（影片改從筆電喇叭播，側錄照設計跟過去）。
    #    原句「那一支被拔掉時字幕會停」在兩者都要時不成立。
    stop_what = ("那一支被拔掉時只有麥克風這一路會停（電腦播的聲音照樣會出字幕）" if both
                 else "那一支被拔掉時字幕會停")
    print(C("\n   ※ 兩種只差一件事：拔插耳麥時要不要跟著換。選 1 會跟著換；選其他就認定那一支，"
            f"{stop_what}，插回去會自己接上。", DIM))
    # 🔴 2026-09-23 使用者指出例外：原本寫「多人會議，筆電內建麥克風比放桌上的耳麥穩」是把 09-22 的**一組**比較
    #    （內建麥克風陣列 vs 放桌上的 3.5mm 耳麥）寫成了通則。那次沒測過任何會議用的外接麥克風，
    #    不能替它排名——高收音效率的外接會議麥克風本來就是為「放桌上收整桌」做的。
    #    改法：只講各類麥克風的設計用途（這是可靠的），排名交給畫面上的收音檢查讓使用者自己量。
    print(C("   ※ 收遠處的人（多人會議）：耳麥是貼著嘴巴設計的，人離超過約 1.5 公尺就容易收不到；"
            "筆電內建麥克風收得比較廣；\n     會議用的外接麥克風（放桌上收整桌那種）本來就是為這種場合做的，"
            "有接就優先試它。", DIM))
    print(C("   ※ 選好之後看畫面上的「收音檢查」：有人講話時要顯示「有收到聲音」，"
            "若顯示「聲音偏小」就換另一支試。", DIM))
    r = ask("用哪一支麥克風？（直接 Enter＝讓程式自己選）", opts, default="1")
    return None if r == "1" else names[int(r) - 2]


def ask_mic_raw():
    """選了「麥克風」時問一題：現場有沒有擴音器的聲音要收。回傳 True＝用完整收音（--mic-raw）。

    🔴 2026-09-22 筆電實測（使用者核准做成「選項」、預設維持一般收音）：
       ・筆電喇叭播會議錄音：一般收音辨識 0 句，完整收音 4 句（原檔 7 句）——Windows 的收音處理把喇叭聲整段刪掉
       ・真人站 3 公尺：兩種都辨識得出來；一般收音略好 ⇒ 預設不換
       ・手機小喇叭放 2 公尺：兩種都 0 句 ⇒ **不能保證**收得到會議室擴音器，說明文字要照實講
       線上與會者的聲音最可靠的是走數位：讓這台電腦也加入會議、改選「兩者都要」。
    """
    r = ask("現場的聲音裡，有沒有從擴音器（喇叭）放出來、也要做字幕的？（直接 Enter＝沒有）", [
        ("1", "沒有，都是現場的人直接講（建議：收音最乾淨）"),
        ("2", "有，要一起收（完整收音：不經 Windows 降噪。擴音器的聲音比較收得到，但不保證；"
              "冷氣、鍵盤聲也會進來）"),
    ], default="1")
    if r == "2":
        print(C("   ※ 擴音器放的如果是線上會議的聲音，最可靠的做法是：讓這台電腦也加入那場會議，"
                "改選「兩者都要」。", YEL))
    return r == "2"


# ────────────────────────────── 三個功能 ──────────────────────────────
def do_live():
    print(C("\n【會議即時字幕】", BOLD))
    print("  會議進行中，字幕會即時跑出來。結束後自動存檔。")
    src = ask("請選擇（輸入號碼）：", [
        ("1", "線上會議（Teams / Meet / Zoom）— 錄電腦播出來的聲音"),
        ("2", "實體會議 — 錄麥克風"),
        ("3", "兩者都要（我人在線上會議，也要收自己的麥克風）"),
        ("0", "回上一頁"),
    ])
    if src == "0":
        return
    mode = {"1": "system", "2": "mic", "3": "both"}[src]
    mic_dev = ask_mic_device(both=mode == "both") if mode in ("mic", "both") else None
    mic_raw = ask_mic_raw() if mode == "mic" else False
    vocab = ask_vocab()

    name = _in("\n這場會議叫什麼名字？（直接 Enter 用今天日期）：").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("會議字幕_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    print(C("\n※ 開始後，講話就會出現字幕：", BOLD))
    print(C("   灰色字 = 還在辨識中，會一直修正", DIM))
    print(C("   白色字 = 已經鎖定的句子（一句講完就鎖一句）", DIM))
    print(C(f"   {font_hint()}", DIM))
    print(C("\n※ 會議結束時，在這個視窗按 Ctrl + C 就會存檔。", BOLD))
    print(C("   檔案會存到你的桌面。", DIM))
    print(C("   開始後盡量不要拔插耳麥；萬一插頭鬆了，程式會自動接回並告訴你。", DIM))
    _in(C("\n準備好了就按 Enter 開始…", GRN))

    args = [os.path.join(SCRIPTS, "live_caption.py"), "--source", mode, "--out", stem]
    if mic_raw:
        args.append("--mic-raw")
    if mic_dev:
        args += ["--mic-device", mic_dev]
    if vocab:
        args += ["--vocab"] + vocab
    rc = run(args, "即時字幕進行中（按 Ctrl+C 結束）", warmup=True)
    report_live(rc, stem)
    pause()


def do_transcribe():
    print(C("\n【錄音檔轉逐字稿】", BOLD))
    print("  已經錄好的會議錄音，轉成有講者、有時間的繁體逐字稿。")
    print(C("\n  正在開啟選檔視窗…（如果沒看到，請看工作列）", DIM))
    path = pick_file()
    if not path or not os.path.exists(path):
        print(C("  沒有選到檔案。", YEL)); pause(); return
    print(f"  已選擇：{C(os.path.basename(path), CYAN)}")

    vocab = ask_vocab()

    print(C("\n講者名字（選填）", BOLD))
    print(C("  按錄音中「第一個開口的人、第二個開口的人」的順序填。", DIM))
    print(C("  例如：處長 秘書　　直接 Enter 就用「講者1、講者2」。", DIM))
    print(C("  名字本身有空白（例如英文全名）就改用逗號隔開。", DIM))
    names = ask_names()

    # 🔴 撞名不要靜默覆蓋：同事很可能已經把上一版逐字稿的講者名字、錯字
    #    一句一句改好了，再轉一次就整份沒了。功能 1、3 早就這樣做，這裡補上。
    out = safe_stem(
        os.path.join(DESKTOP, os.path.splitext(os.path.basename(path))[0] + "_逐字稿"),
        (".md", ".json")) + ".md"
    args = [os.path.join(SCRIPTS, "transcribe_meeting.py"), path, "--out", out]
    if vocab:
        args += ["--vocab"] + vocab
    if names:
        args += ["--names"] + names
    run(args, "轉檔中，一小時的錄音大約要等 1～3 分鐘")
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
        if "**這份逐字稿可能不完整**" in head or "段辨識失敗，這份逐字稿並不完整" in head:
            # 🔴 逐字稿缺尾或有段落失敗時，檔頭已經寫了原因；這裡不能還打 ✅（2026-09-14 驗收抓到）
            print(C(f"\n⚠ 逐字稿在桌面：{os.path.basename(out)}，但可能不完整（原因見上方，檔頭也有寫）", YEL))
        else:
            print(C(f"\n✅ 逐字稿在桌面：{os.path.basename(out)}", GRN))
        # 🔴 2026-09-20 筆電實測 N6-8：說明書教首次試用「一路 Enter 到底」，這一題原本不收空白 Enter。
        #    直接 Enter＝不用（不會自己打開任何東西，最安全）。
        if ask("要現在打開來看嗎？（直接 Enter＝不用）", [("1", "好"), ("0", "不用")], default="0") == "1":
            os.startfile(out)
    pause()


def do_translate():
    print(C("\n【逐字稿轉雙語對照】", BOLD))
    print("  把錄音、逐字稿或字幕檔翻成雙語對照文件。")
    print(C("  跟「即時雙語字幕」的差別：這支是整份一起翻，模型看得到上下文，品質好很多。", DIM))
    print(C("\n  正在開啟選檔視窗…", DIM))
    path = pick_file(transcript=True)
    if not path or not os.path.exists(path):
        print(C("  沒有選到檔案。", YEL)); pause(); return
    print(f"  已選擇：{C(os.path.basename(path), CYAN)}")

    d = ask("要翻成什麼？", [
        ("1", "自動判斷（中文稿→英文；英文稿→中文）"),
        ("2", "翻成臺灣繁體中文"),
        ("3", "翻成英文"),
        ("4", "翻成日文"),
    ])
    to = {"1": None, "2": "zh-TW", "3": "en", "4": "ja"}[d]

    # 翻成日文時，格式與範例要是「中文=日文」（原本一律只給英文範例，2026-09-14 使用者核准修正）。
    # 日文範例用東京大學《大学論叢》第 5 號（2025-11）裡的寫法：高等教育深耕計画、教務処。
    gl_fmt = "中文=日文" if to == "ja" else "中文=English"
    print(C("\n固定譯名（選填，但很有用）", BOLD))
    print(C(f"  寫成「{gl_fmt}」，多組用分號或逗號隔開（譯名裡有空白沒關係）。", DIM))
    if to == "ja":
        print(C("  例：深耕計畫=高等教育深耕計画 ; 教務處=教務処", DIM))
    else:
        print(C("  例：深耕計畫=Higher Education Sprout Project ; 研發處=Office of Research and Development", DIM))
    gl = _in("\n固定譯名：").strip()
    # 🔴 解析與確認要**緊接在輸入之後**。這段是「譯名被空白切碎」那個
    #    blocker 的安全網 —— 切錯了至少使用者當場看得見，離輸入越遠越沒用。
    gl_pairs, gl_dropped = parse_glossary(gl) if gl else ([], [])
    if gl:
        if gl_pairs:
            print(C(f"  已鎖定 {len(gl_pairs)} 組：", BOLD))
            for _p in gl_pairs:
                _k, _v = _p.split("=", 1)
                print(C(f"     {_k.strip()} → {_v.strip()}", DIM))
        if gl_dropped:
            # 靜默丟掉最毒：使用者以為鎖住了，其實沒有。
            print(C(f"  ⚠ 這些看不懂、已略過（要寫成「{gl_fmt}」）："
                    f"{'、'.join(gl_dropped)}", YEL))
        if not gl_pairs:
            print(C("  這次沒有套用任何固定譯名。", DIM))

    note = _in("\n這份文件的背景？（選填，例：研發處深耕計畫會議）：").strip()

    is_audio = os.path.splitext(path)[1].lower() in {
        ".mp3", ".m4a", ".wav", ".wma", ".aac", ".flac", ".ogg",
        ".mp4", ".mov", ".mkv", ".avi"}
    vocab = ask_vocab() if is_audio else []
    spk_names = ask_speaker_names(path, to)

    # 🔴 translate_transcript 實際會寫 5 種檔，撞名檢查要全部納入。
    #    漏掉 _<語言>.md 的後果：同事留著純譯文版（要寄給外賓的那份）、
    #    把太雜的 _對照.md 刪掉，再跑一次同一份就被靜默覆蓋。
    out = safe_stem(
        os.path.join(DESKTOP, os.path.splitext(os.path.basename(path))[0]),
        ("_對照.md", "_對照表.md", "_對照.json",
         "_zh-TW.md", "_en.md", "_ja.md", "_雙語.srt"))
    args = [os.path.join(SCRIPTS, "translate_transcript.py"), path, "--out", out]
    if is_audio:
        # 🔴 輸入是音檔時會先轉一次逐字稿。那份中繼稿的檔名跟功能 2 的產出
        #    完全一樣，不先算好防撞名就會把同事改過的那份蓋掉。
        interim = safe_stem(
            os.path.join(DESKTOP,
                         os.path.splitext(os.path.basename(path))[0] + "_逐字稿"),
            (".md", ".json")) + ".md"
        args += ["--interim-out", interim]
        print(C(f"  （這是音檔，會先轉一次逐字稿：{os.path.basename(interim)}）", DIM))
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
        print(C("\n※ 這是音檔，會先轉逐字稿再翻，時間比較久。", YEL))
    _in(C("\n按 Enter 開始…", GRN))
    rc = run(args, "翻譯中")

    # 🔴 兩個條件都要看：檔案在，**而且**回傳碼是 0。
    #    只看檔案在不在是不夠的 —— 翻譯全部失敗時仍然會產出一份
    #    「全是（這段沒翻到）」的檔案，那不叫成功。
    #    （2026-09-10 稽核抓到：這是「單批失敗不中止」帶來的副作用。）
    made = os.path.basename(out)
    if rc not in (0, None) or not os.path.exists(out + "_對照.md"):
        print(C("\n✗ 翻譯沒有完成。", RED))
        # 🔴 音檔已經先轉了一次逐字稿、錢也花了。不講的話同事會整個重跑，
        #    等於同一份錄音付兩次轉錄費。
        if is_audio and os.path.exists(interim):
            print(C(f"   不過逐字稿已經轉好了，在桌面："
                    f"{os.path.basename(interim)}", GRN))
            print(C("   要重試翻譯的話，回選單按 4、這次直接選那個 .json，"
                    "就不用再付一次轉錄的錢。", DIM))
        print(C("   請往上捲看紅色的錯誤訊息；看不懂就點兩下 6_診斷.bat 截圖回報。", DIM))
        pause(); return
    # 🔴 2026-09-20 複查（major）：逐字稿本身缺了一段時，翻完的四個檔照樣打綠勾 ——
    #    而 _<語言>.md 正是要寄給外賓的那份。比照功能 2／5：讀 _對照.md 的檔頭決定 ✅ 還是 ⚠。
    #    標記字串跟 transcribe_meeting.py／json_to_md.warn_lines 寫檔頭的地方必須一致。
    head4 = io.open(out + "_對照.md", encoding="utf-8",
                    errors="replace").read(3000).split("\n---\n", 1)[0]
    if ("**這份逐字稿可能不完整**" in head4 or "段辨識失敗，這份逐字稿並不完整" in head4):
        # 🔴 V1.26（C1）：翻譯程式自己已經印過「原來的逐字稿就不完整」、缺口清單和「寄出去之前先看缺口」，
        #    這裡原本整句再講一次（同一句印兩遍），還印出 Markdown 的 ** 星號（主控台不會變粗體，只會原樣印出）。
        #    改成一句狀態＋檔案清單。上面判斷用的 "**這份逐字稿可能不完整**" 是**檔案內容**的字樣，不能動。
        #    🔴 只翻成一部分時翻譯程式不列缺口，所以這裡指向檔頭、不說「上面列的」（V1.26 審查 #6）。
        print(C(f"\n⚠ 桌面上這幾個檔（都以 {made} 開頭；原來的逐字稿不完整，缺口時段寫在檔頭）：", YEL))
    else:
        print(C(f"\n✅ 桌面上會有這幾個檔（都以 {made} 開頭）：", GRN))
    print("     _對照.md    ← 一段原文、一段譯文，給人看的")
    print("     _對照表.md  ← 表格，方便貼進 Word / Excel")
    print("     _<語言>.md  ← 只有譯文的乾淨版")
    if os.path.exists(out + "_對照.md"):
        # 🔴 跟功能 2（410 行）、功能 5（880 行）同一題：直接 Enter＝不用（說明書教「一路 Enter 到底」）
        if ask("要現在打開對照檔嗎？（直接 Enter＝不用）", [("1", "好"), ("0", "不用")],
               default="0") == "1":
            os.startfile(out + "_對照.md")
    pause()


def do_bilingual():
    print(C("\n【即時雙語字幕】", BOLD))
    print("  上面出原文、下面出譯文（可選繁體中文、日文或英文），同時顯示。")
    m = ask("聲音從哪裡來？", [
        ("1", "電腦播出來的聲音（YouTube / 線上會議 / 線上研討會）"),
        ("2", "麥克風（現場有外賓演講）"),
        ("3", "兩者都要（實體＋線上混合會議）"),
        ("4", "已經存好的影音檔（選檔案，不會錄到別的聲音）"),
        ("0", "回上一頁"),
    ])
    if m == "0":
        return
    path = None
    if m == "4":
        print(C("\n  正在開啟選檔視窗…", DIM))
        path = pick_file()
        if not path or not os.path.exists(path):
            print(C("  沒有選到檔案。", YEL)); pause(); return
        print(f"  已選擇：{C(os.path.basename(path), CYAN)}")
    mic_dev = ask_mic_device(both=m == "3") if m in ("2", "3") else None
    mic_raw = ask_mic_raw() if m == "2" else False

    q = ask("要快，還是要準？", [
        ("1", "準　－ 等整句講完才翻，延遲約 2～3 秒，譯文語序正常（建議）"),
        ("2", "快　－ 邊聽邊翻，延遲約 1 秒，但語序偶爾會卡住"),
    ])
    hq = (q == "1")

    lang = ask("要翻成什麼語言？", [
        ("1", "繁體中文（台灣）"),
        ("2", "日文"),
        ("3", "英文（聽中文演講、要英文字幕時）"),
    ])
    # 🔴 準確、快速共用同一份對應表。原本各有一份，快速模式那份寫成 en-US ——
    #    翻譯模型不收，每次連線都被 1007 拒絕、零字幕、無限重連
    #    （2026-09-11 對照實驗：en ✅ 25 行｜ja ✅ 23 行｜en-US ❌ 0 行）。
    #    兩份各改各的，就是這樣漂移出來的。
    target = {"1": "zh-TW", "2": "ja", "3": "en"}[lang]

    name = _in("\n這場叫什麼名字？（直接 Enter 用今天日期）：").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("雙語字幕_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    if m in ("1", "3"):
        print(C("\n※ 注意：選「電腦播出來的聲音」會錄到電腦當下播的所有聲音，", YEL))   # V1.26：主控台不吃 Markdown，** 會原樣印出
        print(C("   開始前請先把不相干的影片、音樂關掉。", YEL))
    print(C(f"\n※ 灰色 = 原文，藍色 = 譯文。延遲約 {'2～3' if hq else '1'} 秒。", BOLD))
    print(C(f"   {font_hint()}", DIM))
    print(C("※ 按 Ctrl + C 結束，檔案存到桌面。", BOLD))
    if m in ("2", "3"):
        print(C("   開始後盡量不要拔插耳麥；萬一插頭鬆了，程式會自動接回並告訴你。", DIM))
    _in(C("\n準備好了就按 Enter…", GRN))

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
    rc = run(args, f"雙語字幕進行中・{'準確模式' if hq else '快速模式'}（按 Ctrl+C 結束）", warmup=True)
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
    print(C("\n【即時語音翻譯（口譯模式）】", BOLD))
    print("  聽外語演講或開會時，耳機裡直接聽到翻譯好的中文（也可翻成日文、英文）。")
    print("  畫面上同時照常跑雙語字幕，結束一樣存檔。")
    print(C("\n  ※ 錄「電腦播出來的聲音」時，原音與口譯語音必須走兩條不同的路線，"
            "待會兒會請你分別指定；你只會聽到口譯。", YEL))

    m = ask("聲音從哪裡來？", [
        ("1", "電腦播出來的聲音（Teams / Meet / Zoom / YouTube）"),
        ("2", "麥克風（現場有外賓演講）"),
        ("3", "已經存好的影音檔（不會錄到別的聲音）"),
        ("0", "回上一頁"),
    ])
    if m == "0":
        return

    path = None
    if m == "3":
        print(C("\n  正在開啟選檔視窗…", DIM))
        path = pick_file()
        if not path or not os.path.exists(path):
            print(C("  沒有選到檔案。", YEL)); pause(); return
        print(f"  已選擇：{C(os.path.basename(path), CYAN)}")

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
            print(C(f"\n  ✗ 查不到播放裝置：{e}", RED)); pause(); return
        if not routes:
            # 🔴 一條都查不到有兩種可能：喇叭／耳機都沒接（插孔偵測標成未插入），或聲音元件這一刻沒回應
            #    （重新初始化失敗、sounddevice 載不起來）。程式分不出來，兩種都要講；走下面「只有一個輸出」
            #    那段是誤導（2026-09-19 審查）。
            print(C("\n  ✗ 查不到可以用的播放裝置：可能是喇叭／耳機都沒接上，或聲音元件這一刻沒有回應。", YEL))
            print(C("     接上之後按 Enter 回選單再選一次 6；還是不行，就把選單視窗關掉重開。", DIM))
            pause(); return
        # 🔴 兩條路線卻對到同一個播放裝置（程式分不出來）也算只有一個：不然①選哪條都會被卡在
        #    「剩下的路線都播不出口譯語音」的迴圈裡，只能按 0 離開（2026-09-19 審查）
        if len(routes) < 2 or len({r.get("sd_index") for r in routes}) < 2:
            print(C("\n  ✗ 這台電腦只有一個聲音輸出，這個模式開不了。", YEL))
            print(C("     原音和口譯語音必須走兩條不同的路線，否則你會同時聽到兩種聲音，", DIM))
            print(C("     而且口譯語音會被錄回去、變成翻譯翻自己。", DIM))
            print(C("\n     解法：接上耳機，通常會多出第二條路線（一台筆電的有線耳機實測可以；藍牙還沒測）。", GRN))
            print(C("     沒有耳機的話，改用「2 麥克風」或「3 已經存好的影音檔」，那兩個沒有這個限制。", DIM))
            pause(); return

        while True:
            print(C("\n  這個模式需要兩條路線，請分別指定：", BOLD))
            print(C("\n  ① 原音（會議的聲音）走哪一條？", BOLD))
            print(C("     這條你「不會」聽到，只拿來側錄。請挑一個沒接喇叭或耳機的輸出，", DIM))
            print(C("     例如沒插線的數位輸出；或是插著、但你不會戴上的耳機。", DIM))
            opts = [(str(k), r["name"]) for k, r in enumerate(routes, 1)]
            opts.append(("0", "回上一頁"))
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
                    print(C("\n  ✗ 剩下能播的路線跟①是同一個播放裝置（程式分不出這兩條），請換一條原音路線。", YEL))
                else:
                    print(C("\n  ✗ 剩下的路線都播不出口譯語音，請換一條原音路線。", YEL))
                continue
            print(C("\n  ② 口譯語音要從哪裡聽？（這條你「要」聽得到）", BOLD))
            opts = [(str(k), r["name"]) for k, r in enumerate(rest, 1)]
            opts.append(("0", "重新選"))
            pick = ask("", opts)
            if pick == "0":
                continue
            spk_route = rest[int(pick) - 1]

            # ── 試聽：選反了當場就發現，不必等到開會中才知道 ────────────────
            while True:
                print(C("\n  【試聽】兩條各播一聲，確認沒有選反：", BOLD))
                print(f"    ① 原音路線「{src_route['name']}」… ", end="", flush=True)
                ok1, e1 = ar.play_test_tone(src_route["sd_index"], freq=660)
                print(C("這一聲你應該「聽不到」", DIM) if ok1 else C(f"播不出來（{e1}）", YEL))
                time.sleep(0.5)
                print(f"    ② 口譯路線「{spk_route['name']}」… ", end="", flush=True)
                ok2, e2 = ar.play_test_tone(spk_route["sd_index"], freq=990)
                print(C("這一聲你應該「聽得到」", DIM) if ok2 else C(f"播不出來（{e2}）", YEL))

                ans = ask("\n  結果對嗎？", [
                    ("1", "對：第一聲沒聽到、第二聲聽到了"),
                    ("2", "不對，兩條重新選"),
                    ("3", "沒聽清楚，再播一次"),
                    ("0", "回上一頁"),
                ])
                if ans != "3":
                    break
            if ans == "0":
                return
            if ans == "2":
                continue
            device = spk_route["device_name"]
            route_original = src_route["id"]
            print(C(f"\n  ✓ 原音走「{src_route['name']}」（你聽不到），"
                    f"口譯語音從「{spk_route['name']}」出來。", GRN))
            print(C("     開始時程式會自動把系統聲音輸出切過去，結束後自動切回來。", DIM))
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
            print(C(f"\n  ⚠ 查不到播放裝置清單（{e}），口譯會從 Windows 預設的播放裝置出來。", YEL))
        else:
            if not devs:        # output_devices() 出錯時會吞掉、回空清單：一樣要講，不然使用者不知道沒問
                print(C("\n  ⚠ 查不到播放裝置清單，口譯會從 Windows 預設的播放裝置出來。", YEL))
        while len(devs) > 1:
            print(C("\n  口譯語音要從哪裡聽？", BOLD))
            if m == "2":
                # V1.32：補「停不下來、一直計費」（2026-09-28 使用者實際選了喇叭：講完之後一直重複同一句）
                print(C("     請選你戴在頭上的耳機。選喇叭的話，口譯會被麥克風錄回去，\n"
                        "     模型會一直重複翻自己講的話、停不下來，這段時間也一直在計費。", DIM))
            opts = [(str(k), lab + ("（目前的預設）" if d else ""))
                    for k, (_i, _n, d, lab) in enumerate(devs, 1)]
            opts.append(("0", "回上一頁"))
            pick = ask("", opts)
            if pick == "0":
                return
            idx, dev_name, _d, label = devs[int(pick) - 1]     # dev_name 交給程式、label 給人看（V1.29 ⑤）
            print(f"    試聽「{label}」… ", end="", flush=True)
            try:
                import _audioroute as ar
                ok, err = ar.play_test_tone(idx, freq=990)
            except Exception as e:
                ok, err = False, e
            print(C("應該聽得到一聲", DIM) if ok else C(f"播不出來（{err}）", YEL))
            ans = ask("  有從你要的地方聽到嗎？", [
                ("1", "有"),
                ("2", "沒有，重新選"),
                ("0", "回上一頁"),
            ])
            if ans == "0":
                return
            if ans == "1":
                device = dev_name
                print(C(f"\n  ✓ 口譯語音從「{label}」出來。", GRN))
                break
        # 🔴 2026-09-23 使用者指示（選項 B）：只剩一個播放裝置時，上面那個迴圈完全不跑——不問、也不講，
        #    口譯就從那一顆（通常是筆電喇叭）放出來。使用者拔掉耳麥後進來，以為「選輸出口的步驟被改壞了」。
        #    改成明講會從哪裡出來、怎麼改用耳機；選麥克風時再問一次要不要繼續（喇叭的口譯現場都聽得到，
        #    而且會被麥克風錄回去、一直重複翻，見 V1.32 那段），一定要輸入 1 或 0，不接受直接 Enter。
        if len(devs) == 1:
            only = devs[0][3]          # 只拿來顯示（V1.29 ⑤：完整名稱）；這條路本來就不傳裝置給口譯程式
            print(C(f"\n  ⚠ 這台電腦現在只有一個播放裝置：口譯語音會從「{only}」出來；", YEL))
            print(C("     要用耳機聽，請先插上耳機，再回選單選 6。", YEL))
            if m == "2":
                # V1.32：原本寫「可能被麥克風收進去、再翻一次」太輕——實測收回去之後會一直重複、停不下來、一直計費
                print(C("     這樣現場的人都會聽到口譯，而且口譯會被麥克風錄回去：\n"
                        "     模型會一直重複翻、停不下來，這段時間也一直在計費。", DIM))
                if ask("要繼續嗎？請輸入 1 或 0，再按 Enter：", [
                    ("1", f"繼續，用「{only}」放口譯"),
                    ("0", "回上一頁（先去插耳機）"),
                ]) == "0":
                    return

    mic_dev = ask_mic_device() if m == "2" else None

    lang = ask("要翻成什麼語言？", [
        ("1", "繁體中文（台灣）"),
        ("2", "日文"),
        ("3", "英文（聽中文演講、要英文語音時）"),
    ])
    # 🔴 語言碼跟功能 3 共用同一份對應表的值，改的時候兩邊要一起改。
    #    zh-TW 與官方語言表的 zh-Hant 實測等價（各 3 次，都出繁體臺灣用語）；
    #    zh-Hant-TW 與 cmn-Hant-TW 會被伺服器以 1007 拒絕，不要拿來用。
    target = {"1": "zh-TW", "2": "ja", "3": "en"}[lang]

    name = _in("\n這場叫什麼名字？（直接 Enter 用今天日期）：").strip()
    stem = os.path.join(DESKTOP, safe_name(name) or time.strftime("語音翻譯_%Y%m%d_%H%M"))
    stem = safe_stem(stem, (".txt", ".md", ".srt"))

    if m == "1":
        print(C("\n※ 注意：會錄到電腦當下播的所有聲音，開始前請先把不相干的影片、音樂關掉。", YEL))   # V1.26：同上，拿掉 **
    if m == "2":
        print(C("\n※ 請戴上耳機。口譯語音如果從喇叭放出來，會被麥克風錄回去，\n"
                "   模型會一直重複翻自己講的話、停不下來，這段時間也一直在計費。", YEL))
    print(C("\n※ 會聽到口譯語音，畫面上灰色＝原文、藍色＝譯文，延遲約 1～2 秒。", BOLD))
    print(C(f"   {font_hint()}", DIM))
    print(C("※ 按 Ctrl + C 結束，檔案存到桌面。", BOLD))
    _in(C("\n準備好了就按 Enter…", GRN))

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
    rc = run(args, "語音翻譯進行中（按 Ctrl+C 結束）", warmup=True)
    report_live(rc, stem)
    pause()


def do_json_to_md():
    print(C("\n【逐字稿重新排版／救回】", BOLD))
    print("  用工具 2 轉過的逐字稿，旁邊都會留一個同名的 .json 資料檔。")
    print("  這支把 .json 重新排成可讀的 .md。")
    print(C("\n  兩種用途：", BOLD))
    print("    ・轉檔轉到一半當掉／被關掉 → 只剩 .partial.json，用這支救回來")
    print("    ・想改講者名字、或重新排版 → 不必重轉整份錄音")
    print(C("\n  純本機處理，不連網、不呼叫 API、不花錢。", GRN))
    print(C("\n  正在開啟選檔視窗…（如果沒看到，請看工作列）", DIM))
    path = pick_file(json_only=True)
    if not path or not os.path.exists(path):
        print(C("  沒有選到檔案。", YEL)); pause(); return
    print(f"  已選擇：{C(os.path.basename(path), CYAN)}")

    # 先讀一次，把裡面有幾位講者告訴使用者，才知道要填幾個名字
    n_spk, n_seg, preview, known = 0, 0, [], {}
    try:
        from json_to_md import load_transcript, speaker_list, generic_names, saved_names   # 讀法與講者排法都只有這一份
        segs, _meta = load_transcript(path)
        if not isinstance(segs, list) or not segs:
            print(C("\n  ✗ 這個 .json 裡沒有逐字稿段落。", RED))
            print(C("     請選工具 2 產生的「_逐字稿.json」或「_逐字稿.partial.json」。", DIM))
            pause(); return
        # 🔴 2026-09-21 筆電第四輪驗收 P1：要在**問講者名字之前**就擋下功能 4 的對照檔。
        #    以前這裡照單全收，還報得出「6 段、2 位講者」，同事完全不會懷疑自己選錯檔，
        #    最後拿到一份警語全失、畫面打 ✅ 的「乾淨」逐字稿。
        #    kind 是新版寫的；translation 欄是為了認出桌面上早就存在的舊 _對照.json。
        #    json_to_md.py 那支也擋一次（CLI 直接跑不會經過這裡）——兩層保險。
        if (_meta.get("kind") == "translation-pair"
                or any("translation" in s for s in segs[:5] if isinstance(s, dict))):
            print(C("\n  ✗ 這是「翻譯」（功能 4）產出的對照檔，不是逐字稿。", RED))
            print(C("     它裡面是「原文＋譯文」的配對。重新排版會把原本的缺口提醒弄丟，", DIM))
            print(C("     產出一份看起來完整、其實不完整的逐字稿。", DIM))
            # 🔴 2026-09-21 筆電第五輪觀察-1：先確認「隔壁那個檔」真的在，再叫使用者去找它。
            b = os.path.basename(path)
            if b.endswith("_對照.json"):
                sib = b[:-len("_對照.json")] + ".json"
                if os.path.exists(os.path.join(os.path.dirname(path), sib)):
                    print(C(f"     你要的應該是隔壁那個「{sib}」。", DIM))
            print(C("     想重新排版譯文，回選單按 4、選逐字稿檔重跑一次翻譯就好。", DIM))
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
        print(C(f"\n  ✗ 這個檔案讀不開：{type(e).__name__}", RED))
        print(C(f"     {str(e)[:120]}", DIM))
        print(C("     請確認選到的是工具 2 產生的 .json。", DIM))
        pause(); return

    print(C(f"\n  這份有 {n_seg} 段、{n_spk} 位講者。", BOLD))
    if ".partial." in os.path.basename(path):
        print(C("  （這是中斷時留下的暫存檔，內容是當時已經轉好的部分。）", YEL))
    for who, txt in preview:
        print(C(f"    {who} 第一句：{txt}…", DIM))

    print(C(f"\n講者名字（選填，要填請填 {n_spk} 個）", BOLD))
    print(C("  照上面「講者1、講者2…」的順序填，用空白隔開；名字本身有空白（例如英文全名）就改用逗號隔開。", DIM))
    if known:
        print(C(f"  例如：處長 秘書　　直接 Enter 就沿用上面的名字（{'、'.join(known.values())}）；"
                f"沒有名字的講者用「講者N」。", DIM))
    else:
        print(C("  例如：處長 秘書　　直接 Enter 就沿用「講者1、講者2」。", DIM))
    names = ask_names()
    if names and len(names) != n_spk:
        print(C(_names_warning(len(names), n_spk, "「講者N」"), YEL))

    base = os.path.basename(path)
    for suf in (".partial.json", ".json"):
        if base.endswith(suf):
            base = base[:-len(suf)]
            break
    out = safe_stem(os.path.join(DESKTOP, base), (".md",)) + ".md"
    args = [os.path.join(SCRIPTS, "json_to_md.py"), path, "--out", out]
    if names:
        args += ["--names"] + names
    run(args, "重新排版中（純本機，幾秒就好）")
    if os.path.exists(out):
        # 🔴 2026-09-20 筆電全流程檢測（⚠-12）：這裡本來**無條件**印 ✅，所以一份原本標著
        #    「可能不完整」的逐字稿，重排一次就變成綠勾。比照功能 2：讀檔頭決定 ✅ 還是 ⚠。
        #    兩個標記字串跟 transcribe_meeting.py／json_to_md.py 寫檔頭的地方必須一致。
        head5 = io.open(out, encoding="utf-8", errors="replace").read(3000).split("\n---\n", 1)[0]
        if ("**這份逐字稿可能不完整**" in head5 or "段辨識失敗，這份逐字稿並不完整" in head5
                or "這份是從中斷的暫存檔救回來的" in head5):
            print(C(f"\n⚠ 逐字稿在桌面：{os.path.basename(out)}，但檔頭標了「可能不完整」"
                    f"（原始轉檔當時就有的提醒，內容見檔頭）", YEL))
        else:
            print(C(f"\n✅ 逐字稿在桌面：{os.path.basename(out)}", GRN))
        if ask("要現在打開來看嗎？（直接 Enter＝不用）", [("1", "好"), ("0", "不用")], default="0") == "1":
            os.startfile(out)
    else:
        print(C("\n✗ 沒有產生檔案，上面應該有錯誤訊息。", RED))
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
    print(C("\n這是第一次使用，還需要一組 Gemini API 金鑰才能連線。", BOLD))
    print(C("  沒有的話，去 aistudio.google.com/apikey 免費申請一組（一分鐘搞定）。", DIM))
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
            "\n貼上你的 API 金鑰後按 Enter（每個字會顯示成 *；直接按 Enter 取消）：")
        key = key.strip().strip('"')
        if not key:
            print(C("  沒有輸入，已取消。", YEL))
            return False
        print(C(f"  收到：{_apikey.mask(key)}", DIM))
        level, why = _apikey.format_problem(key)
        if level == "bad":
            print(C(f"  ✗ 這看起來不是金鑰：{why}", YEL))
            print(C("    請到 aistudio.google.com/apikey 按金鑰旁的「複製」，再貼一次。", DIM))
            continue
        print(C("  正在跟 Google 確認這組金鑰…", DIM))
        status, msg = _apikey.verify(key)
        if status == "bad":
            print(C(f"  ✗ {msg}", RED))
            if ask("要怎麼做？", [("1", "重新貼一組"), ("0", "先不要（回選單）")]) == "1":
                continue
            return False
        if status == "ok":
            print(C(f"  ✓ {msg}", GRN))
        else:
            print(C(f"  ⚠ {msg}", YEL))
            if level == "odd":
                print(C(f"    另外，{why}", YEL))
            print(C("    先照樣使用；之後連不上的話，回選單選 9 檢查或換一組。", DIM))
        _apikey.use(key)
        old = _apikey.saved()
        other = bool(old) and old != key       # 電腦裡記著的是另一組（通常就是要換掉的那組）
        _apikey.drain_input()                   # 驗證時多按的 Enter 不要被當成這一題的答案
        if ask("要記住這組金鑰，下次不用再貼嗎？", [
                ("1", "要" + ("（取代電腦裡記住的舊金鑰）" if other else "")),
                ("0", "只用這一次" + ("（下次開程式會用回電腦裡記住的舊金鑰）" if other else "")),
        ]) == "1":
            ok, err = _apikey.remember(key)
            if ok:
                print(C("  已記住，下次開程式會自動使用。", GRN))
            else:
                print(C(f"  記住失敗（{err}），但這次還是可以正常使用。", YEL))
        return True


def do_api_key():
    print(C("\n【API 金鑰設定】", BOLD))
    cur, saved = os.environ.get(_apikey.NAME), _apikey.saved()
    print(f"  這個視窗正在用：{_apikey.mask(cur)}")
    print(f"  電腦裡記住的　：{_apikey.mask(saved)}")
    c = ask("要做什麼？", [
        ("1", "換一組新的金鑰"),
        ("2", "檢查目前這組是否有效（連 Google 確認，不花錢）"),
        ("3", "清除電腦裡記住的金鑰（共用電腦、要交還電腦時用）"),
        ("0", "回上一頁"),
    ])
    if c == "0":
        return
    if c == "1":
        ask_new_key()
    elif c == "2":
        key = cur or saved
        if not key:
            print(C("\n  目前沒有任何金鑰，請選 1 貼一組。", YEL))
        else:
            print(C("\n  正在跟 Google 確認…", DIM))
            status, msg = _apikey.verify(key)
            mark, color = {"ok": ("✓", GRN), "bad": ("✗", RED)}.get(status, ("⚠", YEL))
            print(C(f"  {mark} {msg}", color))
    elif not cur and not saved:
        print(C("\n  沒有記住任何金鑰，不需要清除。", DIM))
    elif ask("確定要清除嗎？清除後下次使用要重新貼一次。",
             [("1", "確定清除"), ("0", "取消")]) == "1":
        _, err = _apikey.forget()
        if err:
            print(C(f"  ✗ 清除失敗：{err}", RED))
        else:
            print(C("  ✓ 已清除，這個視窗也不再使用它。", GRN))
    pause()


def _offer_key_fix():
    """工具失敗之後問 Google 一次：是不是金鑰壞了？是的話當場讓使用者換，不必自己找設定在哪。"""
    key = os.environ.get(_apikey.NAME)
    if not key:
        return
    print(C("\n  正在確認剛才的失敗是不是金鑰的問題…", DIM))   # 要連網，最多幾秒；不講一聲會像當掉
    status, why = _apikey.verify(key, timeout=5)
    if status != "bad":
        return
    print(C(f"\n剛才失敗的原因是金鑰：{why}", YEL))
    print(C(f"  目前的金鑰：{_apikey.mask(key)}", DIM))
    if ask("要現在換一組嗎？", [("1", "要，現在換"), ("0", "先不要")]) == "1":
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
        print(C("\n  TIO語音精靈", BOLD))
        print(C("  " + "═" * 44, DIM))
        if unblocked:
            print(C(f"  （已解除 {unblocked} 個檔案的「來自網路」封鎖，"
                    f"以後點捷徑不會再跳安全警告）", DIM))
            unblocked = 0
        if route_note:
            print(C(f"  （{route_note}）", YEL))
            route_note = None
        c = ask("請輸入號碼後按 Enter：", [
            ("1", "會議即時字幕      － 開會當下就看到字幕"),
            ("2", "錄音檔轉逐字稿    － 已錄好的檔案轉成文字"),
            ("3", "即時雙語字幕      － 同時出原文＋譯文（可翻中英日文）"),
            ("4", "逐字稿轉雙語對照  － 整份翻，品質比即時翻好很多"),
            ("5", "逐字稿重新排版    － 從 .json 重做／改講者名字，不花錢"),
            ("6", "即時語音翻譯      － 只聽口譯，不聽原音（口譯模式）"),
            ("9", "API 金鑰設定      － 換金鑰、檢查是否有效、清除記住的"),
            ("0", "關閉"),
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
                _in("\n按 Enter 回選單…")
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
        print(C("\n✗ 程式出了錯，停下來了。", RED))
        print(C("  需要協助時，點兩下 6_診斷.bat，把這個視窗和診斷視窗都截圖回報。", DIM))
        print(C("\n  技術細節（給協助的人看）：", DIM))
        print(C(traceback.format_exc().rstrip(), DIM))
        try:
            input(C("\n按 Enter 關閉視窗…", DIM))
        except (EOFError, KeyboardInterrupt):
            pass
        sys.exit(3)        # 3＝錯誤已經顯示、使用者也看過了（bat 靠它判斷要不要再停一次）


if __name__ == "__main__":
    _entry()
