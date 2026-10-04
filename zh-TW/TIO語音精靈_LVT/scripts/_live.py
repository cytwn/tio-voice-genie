# -*- coding: utf-8 -*-
"""
即時字幕共用：連線中斷的退避與升級警告、音訊被丟棄的偵測、句子斷句器。

為什麼要獨立一支：三支即時工具各自有一份 AudioSource 的複製，如果這裡的
邏輯也複製三份，下次改就會漏掉其中一支。這個檔是唯一的真相源。

🔴 病根（2026-09-08 檢討出來的，不是使用者回報的）：
   原本連線斷掉只會每隔幾秒印一行「(連線中斷…，N 秒後重連)」，永遠重試、
   沒有退避、也不判讀原因。如果是**額度用完**或**金鑰失效**，它會一直重試到
   天荒地老，而使用者看到的只是同一行訊息在滾。
   會議正在進行、字幕停了，主持人不會馬上發現 —— 這是最糟的時機。
"""
import asyncio
import collections
import contextlib
import difflib
import re
import sys
import threading
import time
import unicodedata

DIM, YEL, RED, GRN, BOLD, RESET = ("\033[2m", "\033[33m", "\033[31m",
                                   "\033[32m", "\033[1m", "\033[0m")

# 握手（連線建立）的上限與「久到該講一聲」的門檻。
# 🔴 2026-09-18 使用者回報：家裡兩台新筆電，裝完第一次用功能 1，畫面停在
#    「▸ 連線 …」很久完全沒反應，連按 Ctrl+C 才吐出一堆英文堆疊，關掉重開就正常。
#    病根是原本 `async with client.aio.live.connect(...)` **沒有任何時限**：
#    握手卡住就是無限安靜等待，而下面那套退避與中文提示只在「丟出例外」時才啟動
#    —— 卡住不是例外，所以一句提示都不會出現。
CONNECT_TIMEOUT = 30.0
SLOW_HINT_AFTER = 8.0
_POLL = 0.5            # 等待切片。切小一點，Ctrl+C 才會在半秒內被看到


class ConnectStalled(Exception):
    """握手卡住：伺服器沒有回應，也沒有報錯。做成例外，好讓 Reconnect 退避接手。"""
    zh = "連線沒有回應"


class ConnectAborted(Exception):
    """握手期間使用者按了 Ctrl+C。呼叫端的 `if stop.is_set(): break` 會安靜收掉。"""
    zh = "使用者取消"


SENT_END = "。！？.!?"
# 🔴 句尾標點後面緊跟的收引號／收括號要跟著那一句一起送，下一句開頭的開引號／開括號也不能被跳過
#    （2026-09-19 審查：真實輸出 '…this idea of a "kill switch.' 少了後引號；'He left. "Stop," she said.' 第二句少了開頭的 "）。
SENT_CLOSE = "\"'”’」』）)］]》〉"
SENT_OPEN = "“‘「『（(［[《〈"

# 中日韓字元（含全形標點）。用來判斷「這個空白是不是夾在兩個中文字之間」。
_CJK = ("\u2e80-\u2eff\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff"
        "\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef")
_CJK_GAP = re.compile("([%s])[ \t]+(?=[%s])" % (_CJK, _CJK))


def tidy_cjk(s):
    """把夾在中文字之間的空白收掉。

    🔴 transcribe-live 的 interim 是**逐詞**長出來的，中文會長成
       「好, 那我 們 今 天 的 研 發 處 會 議 就 開 始 了 。」。
       伺服器的定稿版本沒有這個問題，但我們刻意不用定稿
       （見 live_caption.py：餵給切句器會整段重送），所以要自己收乾淨。

    只有**前後都是中日韓字元**才刪，英文的空白一個都不能碰
    （"Hello world" 不可以變成 "Helloworld"）。
    """
    return _CJK_GAP.sub(r"\1", s)


def fit_tail(s, cols):
    """s 的結尾、顯示寬度不超過 cols 格的那一段（中日韓全形字佔 2 格；寬度不明的符號也當 2 格，寧可短一點）。

    🔴 2026-09-25（使用者截圖：功能 1 用手機播新聞，畫面被灰字洗滿）：暫定稿原本取「最後 70 個字」、
       用 \\r 蓋回同一行。70 個中文字約 140 格，比視窗一行（預設 120 格）寬 → 折成兩行，
       \\r 只退得回最後一行，每更新一次就留下一行殘影（存檔不受影響）。
       英文 70 個字母只佔 70 格不會折行，所以以前的英文測試看不出來。
       本機重現（120 格的主控台）：原寫法更新 17 次留下 9 行殘影；改用本函式截斷後 0 行。
    """
    out, w = [], 0
    for ch in reversed(s):
        cw = 2 if unicodedata.east_asian_width(ch) in "WFA" else 1
        if w + cw > cols:
            break
        out.append(ch)
        w += cw
    return "".join(reversed(out))


# 🔴 2026-09-25（使用者核准）：功能 1 的灰色暫定稿停在同一行、沒有換行（live_caption 用 \r 蓋寫）。這時印別的訊息，
#    開頭只寫 \n 會把那半截灰字留在畫面上（09-25 真實確認：開場第 6 秒「收音檢查」留下一行「… 好, 那」）。
#    所以進行中可能印出的訊息，一律先 CLR_LINE 清掉那一行；其他功能的游標本來就在行首，清一個空行看不出差別。
CLR_LINE = "\r\033[K"

# 「.」不一定是句尾（2026-09-25 使用者核准）：小數點（8.933）、稱謂縮寫後面接名字（Mr. Kuo、Dr. Chen、M. Macron）。
# 切句器（SentenceGate）與 live_bilingual 的原文／中日文譯文 Buffer 共用這一套；英文譯文的 SoftBuffer 另有自己的 TITLES。
# 不收 St.（街名常在句尾）、No.、U.S. 這類：它們真的當句尾的機率不低，SoftBuffer 那套有另外的規則。
_ABBR_TITLES = ("Mr", "Mrs", "Ms", "Dr", "Prof", "Jr", "Sr", "Sra", "Dra", "Mme")
_ABBR_TAIL = re.compile(r"(?:^|[^A-Za-z])(%s|M)$" % "|".join(_ABBR_TITLES))
# 手上的字停在這種點（「8.」「Mr.」）時，停頓多久才送出。切句器與 live_bilingual 的 Buffer／SoftBuffer 共用
# （假伺服器端到端：Buffer 原本只等 idle 2.5 秒，停頓 2 秒加上字與字的間隔剛好 2.5 秒就被切開，跟切句器不一致）。
DOT_WAIT = 3.0


# V1.32：時間的「a.m.／p.m.」（2026-09-28 全線實測英文版 B2：「…Friday at 5:00 p.m.」被切成「…5:00 p.」「m.」兩行、
#    譯文重複一次；「…9:30 a.m.｜on Monday.」斷在句子中間）。Google 送來的原文是完整的 p.m.，是這裡把點當成句尾。
#    英文譯文的 SoftBuffer 早就認得「p.m.｜on」（見 live_bilingual.SoftBuffer._abbr_end），這裡補上同一件事。
# 🔴 V1.32 發布前審查：a／p 前面一定要是時間數字（「5 p」「5:00 p」「5p」）。原本任何單獨的 A／P 都算，
#    「Plan A.」「I got an A.」「Room 5A.」會多等最多 3 秒才出來，「A.M. Turing」「P.M. Modi」在功能 3 快／6
#    從 V1.31 的一行變成被切兩行。代價：拼成英文字的時間（eight p.m.）、大寫又沒空格的「5P.M.」不認。
_AMPM_LETTER = re.compile(r"\d(?:\s[AaPp]|[ap])$")          # 點前面是時間數字＋a／p（「5:00 p」）：後面接「m.」才算
_AMPM_WORD = re.compile(r"\d(?:\s[AaPp]|[ap])\.[Mm]$")      # 點前面是時間數字＋a.m／p.m：後面接什麼才算同一句，見 dot_joins_next
_AMPM_NEXT = re.compile(r"[Mm](?:\.|$)")                   # 「p.」後面接的是「m.」或只有「m」
# 「9 a.m.｜Monday」「5 p.m.｜October 3」「3 p.m.｜Eastern time」：時間後面接星期、月份、時區，是同一句
# （接其他大寫字多半是新的一句）
_AMPM_THEN = re.compile(r"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day|January|February|March|April|May|June|July"
                        r"|August|September|October|November|December"
                        r"|Eastern|Central|Mountain|Pacific|Taipei|GMT|UTC|[ECMP][SD]T)\b")   # \b：Mayor、Marching 不算


def dot_may_join(before):
    """before＝某個「.」前面的文字。這個點**有可能**不是句尾（小數、稱謂、a.m./p.m.），要看後面接什麼才知道。"""
    return (before[-1:].isdigit() or bool(_ABBR_TAIL.search(before))
            or bool(_AMPM_LETTER.search(before)) or bool(_AMPM_WORD.search(before)))


_DEC_HEAD = re.compile(r"(?<![\d,.])\d{1,3}\.$")
# 點後面那一截「像小數的尾巴」：數字後面緊接 % , ; : )、單位字，或直接接中日文字（「5 百萬」「2個百分點」「9。」）
_DEC_TAIL = re.compile(r"\d+(?:[%,;:)]|\s*(?:million|billion|thousand|percent|per cent|points?)\b|\s*[^\x00-\x7f])", re.I)


def join_decimal(buf, text):
    """V1.29 ⑨：把下一小段接到 buf 後面。小數被拆成「8.」｜「 5 million」兩小段送來時，去掉中間那個空白（→「8.5 million」）。
    🔴 2026-09-27 全線實測：功能 3 快／6 的原文與譯文出現「8. 5 百萬」「0. 75」「62. 5%」「12. 5」（旁聽層 13 處），
       看起來像句點；那個空白是模型下一小段開頭自帶的，接起來時留下來了。
    只在點前面是 1～3 位數（前面不是數字、逗號或點）、後面接的是數字時才考慮：「2015.｜ 5 people」這種年份常是句尾，
    「1,250.」「1.2.」也不動。
    🔴 V1.29 審查：英文句尾是數字、下一句又用數字開頭時會接錯——「October 15.｜ 3 teams」→「15.3 teams」、
       「Chapter 2.｜ 3 questions」→「2.3」（變成錯的數字，比多一格空白嚴重）。所以還要符合其一才接：
       ① 數字前面是中日文字（中文句尾用「。」，半形「.」幾乎一定是小數點）
       ② 點後面那一截像小數的尾巴（見 _DEC_TAIL）。
       真實紀錄 36 處拆開的小數（09-26／09-27 全部原始小段流）兩條合起來全部接得回來；審查的 4 個反例都不接。
       代價：英文「8.｜ 5」後面的字晚一小段才到（這一段只有數字）時不接，照舊留空白。"""
    m = _DEC_HEAD.search(buf)
    if m and text[:1].isspace() and text.lstrip()[:1].isdigit():
        before = buf[:m.start()].rstrip()[-1:]
        if (before and not before.isascii()) or _DEC_TAIL.match(text.lstrip()):
            return buf + text.lstrip()
    return buf + text


def dot_joins_next(before, after):
    """這個「.」其實接著後面（after＝點後面、去掉空白的文字）：
    小數點後面是數字；稱謂後面是字（單字母 M. 要接大寫才算，像 M. Macron）；
    a.m./p.m.（V1.32）：「p.｜m.」接起來；「p.m.」後面接小寫字、逗號類標點（「5 p.m., so…」）、中日文字
    （「9 a.m. 開始」：中文句尾用「。」）、星期、月份、時區才接（接其他大寫字多半是新的一句）。"""
    if before[-1:].isdigit():
        return after[:1].isdigit()
    if _AMPM_LETTER.search(before):
        return bool(_AMPM_NEXT.match(after))    # 口譯模型一次吐一兩個字：下一小段可能只有「m」、點還沒到
    if _AMPM_WORD.search(before):
        return (after[:1].islower() or after[:1] in (",", ";", ":", ")", "]") or not after[:1].isascii()
                or bool(_AMPM_THEN.match(after)))
    m = _ABBR_TAIL.search(before)
    if not m:
        return False
    return after[:1].isupper() if m.group(1) == "M" else after[:1].isalpha()


_SPEND_CAP = re.compile(r"spend(ing)?.?cap", re.I)


def diagnose(exc):
    """
    從例外判斷「這是暫時的，還是要人介入的」。
    回傳 (是否需要人介入, 標題, 該怎麼辦)。
    """
    s = f"{type(exc).__name__}: {exc}"
    low = s.lower()

    if isinstance(exc, ConnectStalled):
        return (True, "連線一直沒有回應",
                f"握手在 {CONNECT_TIMEOUT:.0f} 秒內沒有完成（不是被拒絕，是完全沒回應）。\n"
                "      → 防毒或防火牆第一次會問「要不要讓 python 連上網路」，"
                "那個對話框常常藏在別的視窗後面，去工作列找一下\n"
                "      → 公司/學校網路在檢查 HTTPS 時，第一次握手會特別慢\n"
                "      → 換一個網路（例如手機熱點）再試一次")
    # 🔴 2026-09-28 使用者實際操作：Google 專案到了「每月花費上限」，即時連線被 1011 關掉、訊息寫著
    #    「Your project has exceeded its monthly spending cap」（一般呼叫是 429 RESOURCE_EXHAUSTED、同一句）。
    #    以前沒有這一條：1011 當成一般斷線，畫面叫人「檢查網路」。一定要排在 429 前面（429 那條講的是另一回事）。
    if _SPEND_CAP.search(low):
        return (True, "Google 專案這個月的花費上限到了（不是網路問題）",
                "這把金鑰所屬的 Google 專案，本月花費已經到了 AI Studio 裡設的上限，Google 暫停服務到下個月 1 號。\n"
                "      → 要馬上恢復：到 aistudio.google.com 左邊的「Spend」→「Monthly spend cap」→「Edit spend cap」調高上限\n"
                "        （要有這個專案的擁有者或編輯者權限；調高後若還連不上，等幾分鐘再試）\n"
                "      → 即時字幕會自己接上；轉檔、翻譯做到一半的那一份要重跑")
    if re.search(r"429|resource_exhausted|quota|rate.?limit", low):
        return (True, "API 額度用完了",
                "這把金鑰今天的用量到上限了。\n"
                "      → 免費層額度較低，改用付費層（在 Google Cloud 綁定帳單）\n"
                "      → 或等額度重置後再繼續")
    if re.search(r"401|403|permission_denied|unauthenticated|api.?key|invalid.?argument.*key", low):
        return (True, "API 金鑰有問題",
                "金鑰可能打錯、被停用、或這個專案沒開通這個模型。\n"
                "      → 回到選單選「9 API 金鑰設定」檢查或換一組（即時字幕請先按 Ctrl+C 結束）\n"
                "      → 或到 aistudio.google.com/apikey 確認金鑰仍然有效")
    if re.search(r"getaddrinfo|name.?resolution|no address|dns", low):
        return (True, "連不到網路",
                "查不到伺服器位址，通常是網路斷了或 DNS 有問題。\n"
                "      → 檢查網路連線")
    if re.search(r"ssl|certificate", low):
        return (True, "憑證被攔截",
                "公司/學校的防火牆在攔 HTTPS。\n"
                "      → 換一個網路（例如手機熱點）再試")
    # 🔴 2026-09-22（S2）：這裡原本有一條
    #      `if re.search(r"1007|connectionclosed|going away|keepalive|…"): return (False,"","")`
    #    ——**它的分支與下面的 fall-through 回傳同一個值，整條是死碼**。
    #    同日稍早的 P4「補上 1008」因此是 no-op，執行期行為 0 變化；當時寫的
    #    「1008 靠類別名矇中，例外型別一換就會漏判成需要人介入」也**不成立**：
    #    沒被上面任何一條命中的訊息，本來就落到這個 return、need_human=False。
    #    死碼與那段錯誤的因果說明一併移除，模式清單保留備查。
    #
    #    已知的暫時性斷線樣態（都落到下面的預設值，不需要人介入）：
    #      1007／1008／ConnectionClosed*／going away／keepalive／timeout／
    #      timed out／connection reset／broken pipe
    #    實測（2026-09-21）：Live API 閒置滿 60 秒就以 1008 policy violation 關閉連線、
    #    不發 go_away；裝了 SilenceGate 的功能在長靜音時必然會遇到。
    #
    # 🔴 2026-09-25：畫面上的英文類別名（`(連線中斷 ConnectionClosedError，2 秒後重連)`）已改成中文，
    #    但**不是**在這裡改：暫時性斷線要講什麼，由 Reconnect.failed() 看 _LinkClock 的時間決定
    #    （安靜斷線／斷線前有一段沒字幕／一般斷線），不靠例外字串 —— 同一種斷線的類別與字串會隨模型與 SDK 變
    #    （09-23 網路卡死是 ConnectionClosedError、09-25 安靜斷線是 APIError 1008）。這裡維持只判「要不要人介入」。
    return (False, "", "")


ROTATE_PAUSE_WAIT = 30.0   # 到了換線時間之後，最多再等幾秒找講者停頓（8 分＋30 秒仍遠低於伺服器上限）
_PAUSE_BLOCKS = 3          # 連續幾塊（每塊約 100 毫秒）安靜才算停頓
# 這麼久沒有收到聲音（來源安靜時不送資料）也算停頓。
# 🔴 一定要明顯大於 MIX_GRACE（0.3）：「兩個都要」模式一路停送時，混音器會等它 MIX_GRACE 秒才單獨送另一路，
#    佇列因此空約 0.3 秒 —— 門檻也是 0.3 的話，另一路的人還在講就被當成停頓換線（2026-09-20 複查重現，case a 27/40）。
_PAUSE_IDLE = 0.6


def _rms16(pcm):
    """int16 單聲道 PCM 的音量（0～1）。這個檔不相依 numpy，用 array 算。"""
    import array
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    return (sum(x * x for x in a) / len(a)) ** 0.5 / 32768.0


class RotateWhenQuiet:
    """每 8 分鐘換一條連線時，等講者停頓一下再換。

    🔴 2026-09-20 筆電實測 N5：9 分鐘長場在換線點掉了 3 個字（「開幕後首個**比賽日**，共產生 31 枚金牌」少了「比賽日」）。
       聲音本身沒丟（送出 537.0 秒對牆鐘 536.2 秒）：換線那一刻正講到一半，舊連線收到了最後那一兩個字的聲音、
       還沒轉出文字就被關掉；新連線從下一個字開始。原本是時間一到立刻換，跟講者講到哪裡無關。
       改成：時間到了以後，繼續送、直到出現停頓（連續約 0.3 秒音量掉到最近高點的一成二以下，或來源 _PAUSE_IDLE 秒
       沒送聲音）再換；最多多等 ROTATE_PAUSE_WAIT 秒，一直沒有停頓就照舊換（不會因為等停頓而撞上伺服器的連線上限）。
    用法：每一條連線開始時建一個；每送出一塊聲音就 rot.saw(pcm)，再問 rot.due()；
          佇列是空的時候也問 rot.due()。
    🔴 不要寫成 `while not stop and not rot.due(): get_nowait()`（先問再拿）：事件迴圈被卡住一下（例如主控台選取文字時
       print 會卡住）再回來時，佇列裡明明還有好幾塊講話的聲音，卻因為「很久沒收到」被當成停頓換線（2026-09-20 複查重現 8/10）。
       有積壓就先送，佇列空了才算「沒收到聲音」。
    idle=False：來源是檔案時不用「沒收到聲音」這條 —— 檔案是連續送的，停頓靠音量判斷就夠；
       而且檔案讀完到設 eof 之間也會空約 0.6 秒，用這條會在檔尾換線，走不到「等最後幾句翻完」的收尾（複查指出）。
    floor：「安靜」的絕對下限（建立時傳 **rotate_opts(來源)，見 ROTATE_FLOOR_SYSTEM 上面的說明）。
    🔴 2026-09-26（V1.24，使用者核准）：原本寫死 0.002。電腦播放音量小的時候，講話本身就低於 0.002 → 每一塊都算「安靜」
       → 8 分鐘一到立刻換線、切在句子中間，就是上面 N5 那種掉字。
    ramp：（V1.25）到點之後這麼多秒內，下限從 floor 放寬到 QUIET_FLOOR（對數等速），之後維持；None＝固定 floor。
    mixed：（V1.25，一般收音）放寬到 QUIET_FLOOR 之前不用「比最近高點低 18 dB」那條。兩項都見 ROTATE_RAMP 上面的說明。
    """

    def __init__(self, start, limit, wait=None, clock=time.time, idle=True, floor=None, ramp=None, mixed=False):
        self.start, self.limit, self.clock, self.idle = start, limit, clock, idle
        self.wait = ROTATE_PAUSE_WAIT if wait is None else wait
        self.floor = QUIET_FLOOR if floor is None else floor    # QUIET_FLOOR 定義在下面，不能直接當預設值
        self.ramp, self.mixed = ramp, mixed
        self.quiet, self.peak, self.last_rx = 0, 0.0, start

    def saw(self, pcm):
        rms = _rms16(pcm)
        self.peak = max(rms, self.peak * 0.97)        # 最近的音量高點，約每 3 秒衰減到四成
        f, rel = self.floor, True
        if self.ramp:
            # 放寬滿 ramp 秒就直接用 QUIET_FLOOR：時鐘往前跳很多（筆電睡眠）時次方不會溢位，「放寬到頂」也不靠小數相等
            over = self.clock() - self.start - self.limit
            if over >= self.ramp:
                f = QUIET_FLOOR
            elif over > 0:
                f = self.floor * (QUIET_FLOOR / self.floor) ** (over / self.ramp)
            rel = not self.mixed or over >= self.ramp
        self.quiet = self.quiet + 1 if rms < (max(f, 0.12 * self.peak) if rel else f) else 0
        self.last_rx = self.clock()

    def due(self):
        now = self.clock()
        el = now - self.start
        if el < self.limit:
            return False
        return (self.quiet >= _PAUSE_BLOCKS or (self.idle and now - self.last_rx >= _PAUSE_IDLE)
                or el >= self.limit + self.wait)


HOLD_QUIET = 3.0           # 連續安靜這麼多秒，就不要再把音訊送給模型
HOLD_PREFIX = 0.5          # 恢復送出時，要一起補送的「開口前」長度
# 🔴 2026-09-26（V1.23 B）：「安靜」的絕對下限。原本寫死 0.002（約 −54 dBFS）。
#    實測：TIO 側錄「電腦播出的聲音」錄到的是**套用裝置音量之後**的聲音——播放裝置的音量小，錄進來就小；
#    講話時的音量中位數掉到約 −61 dBFS，閘門就把講話當成安靜、壓下來不送（真實錄音：−60.3 不漏、−61.8 開始漏、
#    −64.4 漏掉 9.5 秒），Google 根本沒收到，畫面也零提示（V1.20 功能 6「原音走喇叭」兩次播放中段都消失就是這樣）。
#    只收電腦聲音時放寬到 0.0005（約 −66 dBFS）：模擬與實測都是「下限再低約 6 dB 才開始漏」，多出 12 dB 餘裕。
#    側錄在沒播的時候是數位靜音（或乾脆不給資料），放寬不會多送雜音；代價：影片停頓時若有 −66～−54 dB 的背景嘶聲，
#    閘門會開著照送（回到沒有閘門時的樣子）。
#    麥克風與「兩者都要」維持 0.002：那兩種混著現場底噪，放寬會讓閘門幾乎關不起來，回到 09-21 的跳針＋持續計費。
QUIET_FLOOR = 0.002
QUIET_FLOOR_SYSTEM = 0.0005


def gate_floor(source):
    """SilenceGate 的絕對下限：只收電腦聲音時用寬的那個（見 QUIET_FLOOR_SYSTEM 上面的說明）。"""
    return QUIET_FLOOR_SYSTEM if source == "system" else QUIET_FLOOR


# 🔴 2026-09-26（V1.24，使用者核准）：8 分鐘換線「等講者停頓」的絕對下限，只收電腦聲音時用這個。
#    **不能跟閘門用同一個數字**：閘門要「連續 3 秒」小聲才停，換線只要「連續 0.3 秒」就算停頓——字跟字之間的輕音
#    本來就比講話低 10 dB 以上，下限離講話太近就會一直被當成停頓。實測（unit_v124／掃描，三段真實語音、每段 8～25 個換線點，
#    看換線前那 0.3 秒在正常音量下有沒有講話）：收音檢查 −58 dB 時切在講話中間——0.002：6/8、18/19、21/25；
#    0.0005（閘門那個）：5/8、12/19、14/25；0.00005：**0**（−40 到 −66 dB 全部 0，−70 dB 各 1 次，那個音量閘門本來就不送了）。
#    真正判斷停頓的是「比最近高點低 18 dB」那條相對規則（跟音量大小無關），下限只負責讓數位靜音（0）算安靜。
#    側錄在停頓時是數位靜音，壓這麼低不會把雜音當講話；影片本身有底噪時，停頓照樣靠相對規則抓到。
#    麥克風、「兩者都要」V1.24 時維持 0.002，V1.25 改成下面的「漸進」。
ROTATE_FLOOR_SYSTEM = 0.00005
# 🔴 2026-09-26（V1.25，使用者核准）：麥克風與「兩者都要」改成「漸進」——到點時下限跟電腦聲音一樣是 ROTATE_FLOOR_SYSTEM，
#    等不到停頓就在 ROTATE_RAMP 秒內（對數等速）放寬到 QUIET_FLOOR 後維持（最多仍再等到 ROTATE_PAUSE_WAIT）。
#    一般收音（預設）的停頓是數位 0：收音檢查 −30～−58 dB 六種音量共 312 個換線點，0.002 切到講話 173 次，漸進 0 次。
#    不能照抄 V1.24 直接壓低：完整收音（--mic-raw）的停頓裡有真實底噪（09-22 安靜房間約 −61～−64 dBFS），壓低之後停頓永遠
#    「不夠安靜」→ 等滿 30 秒硬換、多半切在講話中間（掃描 274 組情境 88 組比 0.002 差）。漸進＝先挑最安靜的時刻、找不到才
#    退回 0.002：274 組 156 組較好、117 組一樣、1 組較差（講話只比底噪大 2 dB 那組，聽得到的切到 1→3 次）。
#    🔴 一般收音另加 mixed：「最近高點」可能是另一個人——兩者都要的另一路、或同一支麥克風前坐得比較近的人。大聲的剛講完、
#    小聲的一開口，整段都低於高點的一成二而被當成停頓（差 20 dB、小聲的剛開口就到點：20 次全切到）。所以放寬到
#    QUIET_FLOOR 之前只看下限，之後才把相對規則加回來（吵的房間裡講話大聲時仍找得到停頓）。一般收音停頓是數位 0，
#    用 mixed 之後：兩人音量差 10～20 dB 輪流講 0 次（漸進不加 mixed 是 1～9／42）；代價是很小聲時 312 點多切 6 次。
#    完整收音不加 mixed：停頓有底噪，要靠相對規則早點找到停頓（加了反而較差：真實錄音 93 點 20→35）。
#    量測：verify\scan_v125_mic.py；使用者 2026-09-26 核准「兩者都要」與「麥克風一般收音」都用 mixed。
ROTATE_RAMP = 15.0


def rotate_floor(source):
    """換線判斷一到點時的「安靜」下限：影音檔 QUIET_FLOOR，其他（電腦聲音、麥克風、兩者都要）ROTATE_FLOOR_SYSTEM。"""
    return QUIET_FLOOR if source == "file" else ROTATE_FLOOR_SYSTEM


def rotate_opts(source, raw=False):
    """建 RotateWhenQuiet 時傳 **rotate_opts(來源, 是否完整收音)：麥克風、兩者都要用漸進（V1.25；一般收音再加 mixed），
    電腦聲音、影音檔是固定下限。"""
    opts = {"floor": rotate_floor(source)}
    if source in ("mic", "both"):
        opts.update(ramp=ROTATE_RAMP, mixed=not raw)
    return opts


class SilenceGate:
    """持續安靜時就不要再送音訊給模型。

    🔴 2026-09-21 使用者回報：功能 6（麥克風）在現場聲音結束後**一直跳針**，
       反覆吐「ですね。」「で、」這類填充詞停不下來。查出來的事實：
       原文欄自己就在重複，而原文是 `input_transcription` 原封不動印出來的
       —— 我們的程式不產生任何文字，所以那是模型收到靜音／底噪之後退化成迴圈。
       而 feed() 無條件把每一塊 PCM 都送出去，等於一直餵它；功能 6 又是最貴的一支
       （≈US$2.2/小時），畫面停不下來、帳單也停不下來。

    🔴 **不可以「一塊安靜就不送」**：那會把句子中間的氣口切掉、吃掉字。
       所以是「連續安靜 HOLD_QUIET 秒」才停，而且**一偵測到聲音就立刻恢復**。

    🔴 恢復時要**補送開口前的那幾塊**（HOLD_PREFIX 秒）。開口的第一個音通常還在
       門檻以下，不補送就會吃掉字頭（官方 VAD 也有 prefix_padding_ms 這個概念）。

    音量門檻沿用 RotateWhenQuiet 那一套（`rms < max(0.002, 0.12 * 最近高點)`，
    高點每塊衰減 0.97）—— 那組值是 N5 換線實測調出來的，不另外發明一套。
    長靜音時高點會衰減到趨近 0，門檻自然掉到絕對下限 0.002，輕聲講話也叫得醒。
    （V1.23：只收電腦聲音時絕對下限改 0.0005，見 QUIET_FLOOR_SYSTEM。）

    用法（每收到一塊聲音呼叫一次）：
        for chunk in gate.feed(pcm):
            await session.send_realtime_input(audio=...chunk...)
    回傳空串列＝這一塊壓下來不要送；回傳多塊＝剛恢復，含補送的前綴。

    enabled=False 時完全不作用（原樣送出），給檔案來源與測試用。
    """

    def __init__(self, enabled=True, hold=HOLD_QUIET, prefix=HOLD_PREFIX, block=0.1, floor=QUIET_FLOOR):
        self.enabled = enabled
        self.floor = floor            # 絕對下限；只收電腦聲音時傳 gate_floor("system")（V1.23 B）
        self.block = block            # 🔴 S6：held_seconds 要用它換算，不可寫死 0.1
        self.hold_blocks = max(1, int(round(hold / block)))
        self.keep = max(1, int(round(prefix / block)))
        self.pending = collections.deque(maxlen=self.keep)
        self.quiet = 0
        self.peak = 0.0
        self.holding = False
        self.held_blocks = 0          # 壓下來幾塊（收尾時可以告訴使用者省了多少）

    def feed(self, pcm):
        if not self.enabled:
            return [pcm]
        rms = _rms16(pcm)
        self.peak = max(rms, self.peak * 0.97)
        quiet_now = rms < max(self.floor, 0.12 * self.peak)
        if not quiet_now:
            LINK.voice()                  # 「真的有聲音」＝閘門會被叫醒的那種；Reconnect 靠它認「同一段安靜」
        self.quiet = self.quiet + 1 if quiet_now else 0

        if self.holding:
            self.pending.append(pcm)      # 壓著的時候也要留最近幾塊，恢復時補送
            if quiet_now:
                self.held_blocks += 1
                return []
            self.holding = False          # 有聲音了，立刻恢復
            out = list(self.pending)
            self.pending.clear()
            # 🔴 2026-09-22（S6）：out 裡除了當下這塊，前面那幾塊是**已經算進 held_blocks
            #    的安靜塊**，現在要當前綴補送出去 —— 不扣回來，held_seconds 每喚醒一次
            #    就多報 (keep-1)×block 秒。而 held_seconds 是要印給使用者看的數字。
            self.held_blocks -= len(out) - 1
            return out

        if quiet_now and self.quiet >= self.hold_blocks:
            self.holding = True
            self.pending.clear()
            self.pending.append(pcm)
            self.held_blocks += 1
            return []
        return [pcm]

    @property
    def held_seconds(self):
        # 🔴 S6：用 self.block，不要寫死 0.1 —— 寫死時 SilenceGate(block=0.05) 會高報一倍。
        return self.held_blocks * self.block


# ─────────────────── 送出前把「電腦播出的聲音」放大（V1.26 B1）───────────────────
# 🔴 2026-09-26 實測（tio-lvt-test-0926\runs\diagB1～B5：同一段 9 分鐘會議錄音、真的 Google、只改送出音量）：
#    transcribe-live 聽到的聲音越小，**整段漏轉**越多——不是字幕程式弄丟的（5 場 TIO 自己切句弄丟都是 0）。
#    收音檢查約 −16.5 dB 時字幕涵蓋 95.8%、−33.5 dB 84.1%、−40.5 dB 78.2%（句尾不見 2／6／9 句）。
#    「電腦播出的聲音」錄到的是**套用 Windows 音量之後**的聲音（09-26 T1 喇叭 52%，主段約 −33.5 dB）——
#    音量調小，送給 Google 的聲音就小。側錄沒有現場底噪（沒在播就是數位 0），放大不會把噪音一起放大；
#    −40.5 dB 那場跟 −16.5 dB 那場是同一段錄音、只差 24 dB，等於直接證明放大能把 78% 拉回 96%。
#    🔴 只放大「送給 Google 的那一份」：靜音閘門、8 分鐘換線、畫面上的收音檢查都還是看**原始音量**
#       （V1.23／V1.24 的門檻是照原始音量量出來的，改了會全部失準），「聲音偏小」提醒也照舊。
#    🔴 只用在「只收電腦聲音」。麥克風 09-26 實測過（真人對內建麥克風念 20 句，50 公分／2 公尺，講話只有 −39／−44 dBFS，
#       同一段錄音放大 ×8／×12 跟不放大同時送 Google，tio-lvt-test-0926\runs\mic_*）：功能 1 涵蓋 96.7／92.5% vs 98.0／91.8%、
#       功能 3 快 98.7／95.0% vs 100／94.3%，句尾全保住 ⇒ 量不到差別，不接（完整收音有底噪、連續討論沒測）。
#       兩者都要是兩路混在一起才送，放大會連麥克風一起放大，也不動。
#    🔴 功能 3「快」／6（翻譯模型）不接：使用者 09-26 核准「實測有改善才加」。一度量到 −40.5 dB 原文涵蓋 94.3%、句尾 44/49
#       （正常音量 98.2%、49/49），後來發現那場有一條連線吐簡體字（78 字），比對時被算成漏字；簡轉繁（s2twp）後
#       −40.5 dB 沒放大 97.7%、放大 97.9%、正常音量 97.9%，句尾都 49/49 ⇒ 翻譯模型到 −40.5 dB 都不吃音量，放大沒有改善。
#       （diagA1／A2、v126_A_m24_lev；比對 Google 的中文輸出前一定要先簡轉繁。）
AMP_TARGET = 0.12         # 講話時每塊音量的 90 百分位放大到這裡（約 −18 dBFS，接近實測最好的 −16.5）
AMP_MAX = 16.0            # 最多放大 16 倍（+24 dB）：−42 dB 的講話拉到 −18；更小的多半是沒在播，不硬拉
AMP_VOICED = QUIET_FLOOR_SYSTEM   # 比這個小的塊不算講話，不拿來估音量（同只收電腦聲音時的閘門下限）
AMP_BLOCKS = 150          # 拿最近幾塊講話估音量（每塊 0.1 秒＝15 秒）
AMP_PEAK = 0.9            # 放大後的峰值上限（不破音）
AMP_STEP = 0.2            # 每塊往目標倍數靠近幾成（約 1 秒到位，不會忽大忽小）


class Leveler:
    """把送給 Google 的 int16 PCM 放大到固定的講話音量：只放大不縮小、峰值有上限、倍數慢慢變。"""

    def __init__(self, target=AMP_TARGET, max_gain=AMP_MAX):
        self.target, self.max_gain = target, max_gain
        self.hist = collections.deque(maxlen=AMP_BLOCKS)
        self.gain = 1.0

    def apply(self, pcm):
        import numpy as np          # 放在函式裡：這個模組本身不相依 numpy
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if not len(x):
            return pcm
        rms = float(np.sqrt(np.mean(x * x)))
        if rms >= AMP_VOICED:          # 只有講話的塊才調倍數；停頓時倍數凍結，再開口不用重來
            self.hist.append(rms)
            if len(self.hist) >= 5:
                want = min(self.max_gain, max(1.0, self.target / float(np.percentile(self.hist, 90))))
                self.gain += (want - self.gain) * AMP_STEP
        g, peak = self.gain, float(np.max(np.abs(x)))
        if peak * g > AMP_PEAK:
            g = max(1.0, AMP_PEAK / peak)
        if g <= 1.001:
            return pcm
        return np.clip(np.round(x * g * 32768.0), -32768, 32767).astype(np.int16).tobytes()


# ─────────────────── 斷線的性質：安靜斷線／斷線前漏了一段／一般斷線 ───────────────────
IDLE_CLOSE_AFTER = 45.0   # 這麼久沒送出任何聲音之後的斷線，當成「安靜太久，被 Google 關掉」（實測門檻 60 秒）
LOST_REPORT_MIN = 3.0     # 送出後伺服器一直沒回應的聲音超過這麼多秒，才講「斷線前有一段沒有字幕」


class _LinkClock:
    """記「最後一次送出聲音」與「送出後伺服器還沒回應的秒數」，給 Reconnect 判斷這次斷線是哪一種。

    🔴 2026-09-25 使用者回報兩種斷線，畫面原本都只印一行英文「(連線中斷 XxxError，2 秒後重連)」：
       ・安靜斷線：靜音閘門壓著（不送聲音）滿 60 秒，Google 就主動關掉連線，而且每分鐘一次
         （09-21 功能 3/6、09-25 功能 1 實測 `APIError: 1008 None. The operation was aborted.`，60.6 秒）。
         什麼都沒漏，使用者卻以為壞掉（09-23 功能 6 那場他問「剛才上面斷線了嗎？」）。
       ・網路卡死：09-23 20:52 筆電的 IPv6 路由消失 36 秒，連線不是「斷」而是「卡」—— 照樣把聲音送進去、
         伺服器卻不再回應，要等 websockets 每 20 秒一次的 ping 逾時才發現 → 約 22 秒的內容沒有字幕，畫面沒講。
       這兩件事用我們自己量的時間分，不靠例外字串（同一種斷線的類別與字串會隨模型與 SDK 版本變）。
    整個行程同一時間只有一條 Live 連線，所以用一個模組層級的 LINK 就夠。
    """

    def __init__(self):
        self.last_audio = 0.0       # 最後一次送出聲音（含安靜的塊）：伺服器的閒置計時是從這裡算
        self.last_voice = 0.0       # 最後一次「真的有聲音」（靜音閘門判定不安靜）：「同一段安靜」靠它認
        self.conn_start = time.time()
        self.unanswered = 0.0       # 上次收到伺服器訊息之後，又送出了幾秒聲音
        self.answered_at = 0.0      # V1.31：最後一次「送出的聲音有得到回應」的時間（剛連上時伺服器自己送的訊息不算）

    def connected(self):
        self.conn_start = time.time()
        self.unanswered = 0.0

    def sent(self, secs):
        self.last_audio = time.time()
        self.unanswered += secs

    def voice(self):
        # 🔴 不能拿 last_audio 認「同一段安靜」：每次重連，新的靜音閘門都會先把約 3 秒的安靜聲音送出去才壓住
        #    （09-21 實測放行 58 塊＝29×2），last_audio 每分鐘都在動 → 「只講一次」會變成每分鐘講一次（假伺服器端到端抓到）。
        self.last_voice = time.time()

    def got(self):
        if self.unanswered > 0:
            self.answered_at = time.time()
        self.unanswered = 0.0

    def idle_for(self):
        """這條連線已經幾秒沒送出任何聲音（剛連上還沒送就從連上那一刻算）。"""
        return time.time() - max(self.last_audio, self.conn_start)


LINK = _LinkClock()


class _Tracked:
    """包住 Live 連線（open_live 交給呼叫端的就是它）：送出聲音、收到訊息時記到 LINK，其他一律原樣轉給原本的 session。
    三支即時程式都經過 open_live，所以不必各改一份（改三份一定會漏，見本檔開頭的說明）。"""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    async def send_realtime_input(self, **kw):
        await self._s.send_realtime_input(**kw)
        blob = kw.get("audio")
        if blob is not None:
            m = re.search(r"rate=(\d+)", getattr(blob, "mime_type", None) or "")
            LINK.sent(len(getattr(blob, "data", None) or b"") / 2 / (int(m.group(1)) if m else 16000))

    async def receive(self):
        async for msg in self._s.receive():
            LINK.got()
            yield msg


def _close_code(exc):
    """例外訊息裡的 WebSocket 關閉代碼（1000～1015），沒有就回 None。只拿來印在畫面上，方便截圖回報時查。"""
    m = re.search(r"\b(10(?:0\d|1[0-5]))\b", str(exc))
    return m.group(1) if m else None


class Reconnect:
    """
    連線中斷後的退避與警告。

    退避：2 → 4 → 8 → 15 → 15…（封頂 15 秒），不要一直敲 API。
    升級：連續失敗 3 次就從「一行小字」升級成明顯警告，並判讀原因。
    """
    CAP = 15
    MIN_HEALTHY = 20      # 一段連線要真的撐過這麼久，才算「恢復了」

    def __init__(self, say=print, escalate_after=3):
        self.say = say
        self.escalate_after = escalate_after
        self.fails = 0
        self.first_fail_at = None
        self.connected_at = None
        self._timer = None
        self._idle_told = None    # 「安靜斷線」那句是在哪一段安靜講過的（LINK.last_voice），同一段只講一次
        self.resend = 0.0         # V1.26 A2：呼叫 failed() 前由呼叫端設定＝斷線前那段、重新連上後會補送的秒數
        self._told = None         # V1.31：已經完整講過的「要人處理」原因（標題）；同一個原因之後只補一行短的
        self._told_at = 0.0
        self._told_cap = False    # 講過的是「花費上限」：要真的收到 Google 對聲音的回應才算恢復（見 _healthy）

    def ok(self):
        """連上了。

        🔴 這裡**不能**宣布恢復，也不能把失敗計數歸零 ——「連得上」不等於「能用」：
           伺服器接受連線後幾秒就回 1007／1008 把人踢掉，每連一次就歸零一次的話，
           退避永遠停在 2 秒、永遠到不了「連續失敗 3 次」的明顯警告
           （2026-09-10 實測：斷線後 6 分鐘零字幕、零提示）。
        🔴 第一版改成「比較兩次 ok() 的間隔」，但那段間隔包含了 15 秒的退避等待，
           每次只要撐超過 5 秒就被誤判成撐住了，對使用者謊報「✓ 連線恢復了」
           （2026-09-11 實測：整場 45 次 1007、零字幕，中間卻印了一次恢復）。
        所以現在：連上時只記時間，並排一個 MIN_HEALTHY 秒後的檢查；
        這段連線真的撐到那時候還沒斷，才宣布恢復並歸零。中途斷了就取消。
        """
        self._cancel()
        self.connected_at = time.time()
        timer = threading.Timer(self.MIN_HEALTHY, self._healthy, args=(self.connected_at,))
        timer.daemon = True               # 程式結束時不要被它卡住
        self._timer = timer
        timer.start()

    def _healthy(self, since):
        """這段連線撐過 MIN_HEALTHY 秒了，才是真的恢復。"""
        if self.connected_at != since:    # 期間斷過又重連了，這次的檢查作廢
            return
        if self._told_cap and LINK.answered_at < since:
            # 🔴 講過「花費上限」：要真的收到 Google 對聲音的回應才算恢復——安靜的會議室不送聲音，連線可以空撐很久，
            #    一開口才被關掉；只看「撐過 20 秒」會先印「✓ 連線恢復了」再印紅字（V1.31 審查第二輪 #4）。還沒證明就每 5 秒再看一次。
            #    只限花費上限：網路、金鑰這些，連線撐得過 20 秒就是好了（V1.30 原本的判斷；審查第三輪 #1）。
            timer = threading.Timer(5.0, self._healthy, args=(since,))
            timer.daemon = True
            self._timer = timer
            timer.start()
            return
        # _told：已經印過紅字（例如花費上限，第一次斷就講），就算只斷了一兩次也要講恢復了，不然紅字一直留在畫面上（V1.31 審查 #2）
        if self.fails >= self.escalate_after or self._told:
            down = int(since - (self.first_fail_at or since))
            self.say(f"{CLR_LINE}\n{GRN}  ✓ 連線恢復了（中斷約 {down} 秒，"
                     f"這段期間的聲音沒有字幕）{RESET}")
        self.fails = 0
        self.first_fail_at = None
        self._told, self._told_cap = None, False

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def failed(self, exc):
        """回報一次失敗，回傳「該睡幾秒」。"""
        self._cancel()
        resend, self.resend = self.resend, 0.0    # 只算這一次（見 __init__）
        was_up = self.connected_at is not None      # 斷的是已經連上的線（不是握手就失敗）
        # 量「這一段連線本身活了多久」（此時還沒開始睡退避）。撐得夠久就代表先前那一串
        # 失敗其實已經結束了——正常情況下 _healthy 早就歸零過，這裡只是保險。
        if (self.connected_at is not None
                and time.time() - self.connected_at >= self.MIN_HEALTHY):
            self.fails = 0
            if not self._told:            # 紅字講過的原因還沒恢復（例如花費上限）：「中斷約 N 秒」照第一次斷的時間算，不要歸零（審查第四輪 #2）
                self.first_fail_at = None
        self.connected_at = None
        self.fails += 1
        if self.first_fail_at is None:
            self.first_fail_at = time.time()
        delay = min(2 ** (self.fails - 1) * 2, self.CAP)

        # 🔴 V1.31：花費上限到了不會自己好，第一次斷就講清楚（以前要連斷 3 次、而且叫人檢查網路）
        if self.fails < self.escalate_after and not _SPEND_CAP.search(str(exc)):
            # 🔴 2026-09-25：分三種講、一律中文（原本印英文類別名，對同事沒有意義）。依據見 _LinkClock 的說明。
            #    開頭的 \r\033[K：功能 1 的灰色暫定稿停在同一行沒換行，不先清掉，這句會黏在暫定稿後面。
            if was_up and LINK.idle_for() >= IDLE_CLOSE_AFTER:
                # 安靜太久被 Google 關掉：什麼都沒漏。同一段安靜只講一次，之後每分鐘照樣安靜地重連。
                if LINK.last_voice != self._idle_told:
                    self._idle_told = LINK.last_voice
                    self.say(f"{CLR_LINE}{DIM}（一分鐘以上沒有聲音，Google 先把連線關掉了；"
                             f"有人開口就會自動接上，不會漏字）{RESET}")
                return delay
            label = getattr(exc, "zh", None) or "網路或伺服器斷線"
            code = _close_code(exc)
            if code:
                label += f"（代碼 {code}）"
            lost = LINK.unanswered if was_up else 0.0
            if resend >= LOST_REPORT_MIN:
                # V1.26 A2：這段不會消失，重新連上後補送（見 LagWatch）
                self.say(f"{CLR_LINE}{YEL}(連線中斷：{label}。斷線前約 {resend:.0f} 秒的聲音，重新連上後會補送，"
                         f"字幕會晚一點出現；{delay} 秒後自動重連){RESET}")
            elif lost >= LOST_REPORT_MIN:
                self.say(f"{CLR_LINE}{YEL}(連線中斷：{label}。斷線前約 {lost:.0f} 秒的聲音沒有字幕，"
                         f"{delay} 秒後自動重連){RESET}")
            else:
                self.say(f"{CLR_LINE}{DIM}(連線中斷：{label}，{delay} 秒後自動重連){RESET}")
            return delay

        need_human, title, hint = diagnose(exc)
        now = time.time()
        down = int(now - self.first_fail_at)
        if need_human and title == self._told:
            # 同一個原因已經完整講過：之後每 15 秒重試一次，不要每次都印一整段洗掉字幕畫面，一分鐘最多補一行
            if now - self._told_at >= 60:
                self._told_at = now
                self.say(f"{CLR_LINE}{YEL}  ⚠ 還是一樣：{title}——字幕目前是停的（中斷約 {down} 秒），"
                         f"仍在每 {delay} 秒自動重試{RESET}")
            return delay
        self._told, self._told_at = (title, now) if need_human else (None, 0.0)
        self._told_cap = bool(need_human and _SPEND_CAP.search(str(exc)))
        self.say(f"{CLR_LINE}\n{YEL}  ⚠ 連線已經連續失敗 {self.fails} 次"
                 f"（中斷約 {down} 秒），字幕目前是停的{RESET}")
        if need_human:
            self.say(f"{RED}      {title}{RESET}")
            self.say(f"{DIM}      {hint}{RESET}")
        else:
            self.say(f"{DIM}      技術細節：{type(exc).__name__}: "
                     f"{str(exc)[:100]}{RESET}")
            self.say(f"{DIM}      仍在自動重連中。若一直沒恢復，"
                     f"請檢查網路，或按 Ctrl+C 結束（已辨識的內容都已存檔）。{RESET}")
        self.say(f"{DIM}      {delay} 秒後再試…{RESET}")
        return delay


# ─────────────────── 翻譯模型停住／落後：提醒、主動換線、補送（V1.26 A1／A2）───────────────────
# 🔴 2026-09-26 實測（tio-lvt-test-0926\runs\diagA1／A2：同一段 9 分鐘錄音同時跑兩場、記下每一則送收）：
#    翻譯模型（功能 3「快」、功能 6）回來的語音是即時速度的串流（每 30 秒剛好 30.0 秒）；TIO 送出每塊只等 0.5ms、
#    沒有積壓——但 A2 第 413 秒起 **Google 自己停了**：原文 14.6 秒、語音 9.3 秒什麼都沒回來，之後才恢復
#    （那兩句落後 14、11 秒，內容都補回來了）。09-26 T3（13:35）與 T6 影音檔（12:54）是同一種停頓**沒恢復**：
#    落後到約 25 秒被 Google 以 1011 關掉，停住期間送出去的聲音沒人處理、重連後也沒補送 ⇒ 20～25 秒整段不見，
#    畫面只有一行灰字。舊的「斷線前約 N 秒沒有字幕」量的是「多久沒收到任何訊息」，伺服器慢慢吐舊譯文時一直被歸零，所以也沒講。
#    這裡改量兩件事（取大的＝behind）：
#      ①送出後多久沒收到任何進度（原文、譯文或語音）＝停住
#      ②「送出的聲音」減「收到的語音」比最近 60 秒的最低點多出多少＝落後（伺服器照常回、只是越來越慢的那種）
#    behind ≥ STALL_WARN → 畫面講「Google 暫時沒有回應」；≥ REDIAL_LAG → 主動換一條連線，把最近送出、還沒被處理的
#    那一段（最多 RESEND_MAX 秒，多抓 RESEND_PAD 秒）在新連線一開始補送。斷線時也一樣補送。
#    門檻依據（同兩場真實紀錄模擬）：A1（正常）behind 最大 5.2 秒（換線後第一句的正常延遲）；A2（停住後自己恢復）9.3 秒；
#    T3／T6（沒恢復）約 25 秒才被斷。7 秒提醒、15 秒換線：正常的不誤觸，會自己恢復的只提醒、不換線。
#    🔴 代價（已跟使用者說明）：補送那段會晚十幾秒出現；伺服器其實處理過一部分時，那一兩句會重複一次。
STALL_WARN = 7.0
REDIAL_LAG = 15.0
RESEND_MAX = 30.0
RESEND_PAD = 2.0          # 補送時多往前抓幾秒（寧可重複一兩句，不要漏）
# 🔴 補送不能一口氣灌（2026-09-26 真的 Google、強制在第 40 秒換線補送 23 秒，tio-lvt-test-0926\runs\v126_A2_*）：
#    一口氣送完 → 補送那段有轉出來，但**接在後面的即時聲音整段沒轉**（兩句都不見，多等 60 秒也沒有）；
#    補送用 2 倍速、之後佇列一口氣送 → 第一句回來、最後一句還是不見。看起來 Google 手上沒處理的聲音太多時，
#    後到的會被丟掉。所以換線後「補送＋這段期間積在佇列的即時聲音」一律照 RESEND_RATE 倍速送，追平才恢復即時。
#    同一次實測 Google 轉文字的速度約 1.5 倍即時。
RESEND_RATE = 1.5
LAG_BASE_WINDOW = 60.0    # 落後的基準：最近這麼多秒裡「送出減收到」的最低點（會自己恢復的停頓之後，60 秒內基準會跟上）
# 🔴 Google 一直停住時不能無限換線（V1.26 審查 #3：每條撐 5 秒就停，每 24 秒換一次、多傳約 33%，畫面永遠只說「會晚一點」）：
#    換線後這條連線撐不到 STALL_RESET 秒又要換線，就累計；連續 3 次起講明「字幕目前是停的」並跟斷線一樣退避。
STALL_RESET = 60.0


class LagWatch:
    """一條翻譯連線的送收帳（只給會回語音的翻譯模型用）。sr＝回來的語音取樣率（Live API 固定 24kHz）。

    sent(塊, count=False)：補送的舊聲音只記進帳本、不算進落後（伺服器要一點時間消化，算進去會馬上又判定落後、一直換線）。
    """

    def __init__(self, keep=RESEND_MAX, block=0.1, sr=24000, clock=time.time):
        self.clock, self.sr, self.block = clock, sr, block
        self.buf = collections.deque(maxlen=int(round(keep / block)) + 1)   # 最近送出的每一塊（補送時原樣再送）
        self.sent_s = 0.0          # 這條連線送出的即時聲音（秒）
        self.got_s = 0.0           # 收到的語音（秒）
        self.since_msg = 0.0       # 上次收到任何進度之後，又送出了幾秒即時聲音
        self.resent_s = 0.0        # 這條連線一開始補送的舊聲音（秒）
        self.hist = collections.deque()    # (時間, 送出−收到)，算最近 LAG_BASE_WINDOW 秒的最低點

    def sent(self, pcm, rate=16000, count=True):
        self.buf.append(pcm)
        if not count:
            self.resent_s += len(pcm) / 2 / rate
            return
        s = len(pcm) / 2 / rate
        self.sent_s += s
        self.since_msg += s
        now = self.clock()
        self.hist.append((now, self.sent_s - self.got_s))
        while self.hist and self.hist[0][0] < now - LAG_BASE_WINDOW:
            self.hist.popleft()

    def got(self, audio_bytes=0):
        """收到一則有進度的訊息（原文、譯文或語音）；audio_bytes＝裡面的語音位元組數。"""
        self.got_s += audio_bytes / 2 / self.sr
        self.since_msg = 0.0

    def lag(self):
        if not self.hist:
            return 0.0
        return max(0.0, (self.sent_s - self.got_s) - min(x for _, x in self.hist))

    def behind(self):
        """估計還沒被處理的聲音秒數：停住與落後取大的。"""
        return max(self.since_msg, self.lag())

    def rebase(self):
        """追平之後重新起算落後的基準：追趕期間送得比收得快是刻意的，不能算成落後（不然一追平就又換線）。"""
        self.hist.clear()

    def unacked(self):
        """斷線時要補送多少：behind()，或剛補送過、伺服器還沒回完的那段（取大的）。
        🔴 不能拿來判斷要不要換線：補送完那一刻它一定很大，拿來判斷會一直換線。"""
        return max(self.behind(), self.resent_s - self.got_s)

    def backlog(self, secs):
        """最近 secs 秒送出的聲音（原樣），最多 RESEND_MAX 秒。"""
        n = min(len(self.buf), int(round(min(secs, RESEND_MAX) / self.block)))
        return list(self.buf)[-n:] if n > 0 else []


class DropWatch:
    """
    音訊佇列滿了、開始丟資料時提醒使用者。

    佇列滿代表「錄進來的比送出去的快」——通常是連線斷了、送不出去。
    這種時候聲音是真的會遺失的，必須講，不能靜默。
    只在開始丟的時候講一次，恢復時再講一次，不要洗版。
    """

    def __init__(self, say=print, chunk_ms=100, warn_after_ms=3000):
        self.say = say
        self.chunk_ms = chunk_ms
        self.need = max(1, warn_after_ms // chunk_ms)
        self.run = 0
        self.warned = False
        self.total = 0

    def dropped(self):
        self.total += 1
        self.run += 1
        if self.run >= self.need and not self.warned:
            self.warned = True
            self.say(f"{CLR_LINE}\n{YEL}  ⚠ 聲音來不及送出，開始有音訊被丟棄"
                     f"（這段話不會有字幕）{RESET}")
            self.say(f"{DIM}      通常是連線斷掉造成的，恢復後就會停止。{RESET}")

    def kept(self):
        if self.warned and self.run:
            lost = self.total * self.chunk_ms / 1000
            self.say(f"{CLR_LINE}{GRN}  ✓ 聲音恢復正常（總共丟失約 {lost:.0f} 秒）{RESET}")
            self.warned = False
        self.run = 0

    @property
    def lost_seconds(self):
        return self.total * self.chunk_ms / 1000


CAPTURE_JOIN = 2.0         # V1.32：收尾時等收音執行緒把串流關好的上限（秒）


def join_capture(threads, timeout=CAPTURE_JOIN):
    """V1.32：收尾時等收音執行緒（麥克風／電腦聲音）自己把串流關好，再讓程式結束。
    影音檔的讀檔執行緒不碰 PortAudio，三支都沒把它記進來，不用等。
    AudioSource.close()（live_caption／live_bilingual／live_bilingual_hq 共用這一支）在設了停止旗標之後呼叫。

    🔴 2026-09-28 全線實測：C2（完整收音）結束那一刻 python.exe 以 0xC0000374（記憶體堆積損毀）當掉，
       這台 09-22 起同代碼 12 筆。原因：收音執行緒是守護執行緒，停止旗標一設、主程式就往下走到結束；
       直譯器收尾時 sounddevice 的結束處理（atexit → Pa_Terminate）會關掉還開著的串流，
       同一刻收音執行緒也正要離開 with sd.InputStream(...) 去關同一條 → 兩邊一起關就損毀。
       一般收音也會中，不是完整收音特有（交錯重現見 tio-v131-realtest\\runs\\crash\\round2.jsonl）；
       功能 3 準／6 的兩支也會，機率較低（tio-v132-realtest\\runs\\crash\\round3.jsonl：V1.31 3/40、V1.32 0/40）。
    🔴 等太久還沒關好（驅動卡住）：取消 sounddevice 的結束處理——跟口譯播放那邊（Speaker.close）同一招，
       否則當機只是延到最後。只看已經載入的 sounddevice，不在這裡 import（在主執行緒第一次 import 會改變 COM 行為）。
    回傳 True＝全部都關好了。"""
    end = time.monotonic() + timeout
    alive = []
    for t in threads:
        if t is None or t is threading.current_thread():
            continue
        t.join(max(0.0, end - time.monotonic()))
        if t.is_alive():
            alive.append(t)
    if alive:
        sd = sys.modules.get("sounddevice")
        if sd is not None:
            try:
                import atexit
                atexit.unregister(sd._exit_handler)
            except Exception:
                pass
    return not alive


# V1.33：還開著的收音來源（三支的 AudioSource）與口譯播放（Speaker）。
# 🔴 V1.32 發布前審查：收音開始之後、run() 自己收尾之前，只要冒出沒預期的錯誤（例如建 .txt 時被 Windows
#    「受控制資料夾存取」擋下），就走不到 src.close()／spk.close()——收音執行緒還在跑、程式就結束，
#    可能撞上 V1.32 修掉的那種當機（0xC0000374，見 join_capture）。這是推論：真機模擬「開始收音後建檔失敗」
#    V1.32 50 次沒重現（那條路上收音執行緒沒有同時在關串流）；這裡改的是收尾順序，屬於預防。
#    做法：開好（start() 第一行）時記進清單、close() 時拿掉；三支的 main() 在最外層 finally 呼叫 close_open()，把還沒關的關好。
#    正常收尾時 run() 早就關過了，清單是空的、什麼都不做；只有例外跳出時才真的有事。
#    🔴 不能改用 atexit：sounddevice 常常在收音執行緒裡才第一次 import，它的結束處理會登記得比我們晚、先跑。
_OPEN = []


def keep_open(obj):
    """收音來源／口譯播放開好之後呼叫（V1.33）。"""
    if obj not in _OPEN:
        _OPEN.append(obj)


def forget_open(obj):
    """close() 裡呼叫：已經關了，不用再收（V1.33）。"""
    try:
        _OPEN.remove(obj)
    except ValueError:
        pass


def close_open():
    """三支即時程式 main() 最外層 finally 呼叫（V1.33）：把還開著的收音／口譯播放關好，後開的先關。
    close() 本來就可以重複呼叫；單一個關的時候出錯不影響其他個。"""
    for obj in reversed(list(_OPEN)):
        try:
            obj.close()
        except Exception:
            pass
        forget_open(obj)


# 混音器等一路「還在送」的寬限秒數。影音檔來源收尾時要等得比它久（見 live_bilingual*.py 的 _file）。
MIX_GRACE = 0.3


def mix_lanes(src, n, grace=MIX_GRACE, max_blocks=5, poll=0.01):
    """
    AudioSource 的混音迴圈（live_caption／live_bilingual／live_bilingual_hq 共用）。
    src 要有：_lanes（{名稱: queue}）、stop（Event）、q（輸出 queue）、drop（DropWatch）。
    n＝一塊的取樣數（16kHz × 100ms＝1600）。

    🔴 2026-09-19 筆電實測（B1）：舊寫法是「任何一路有資料就立刻送一塊」。兩路都持續送資料、
       只是到達時間錯開時（Realtek 耳機靜音也一直送、Teams 通話也是），這一塊只有 A、下一塊
       只有 B ——等於交錯：6 秒送成 9 秒、講話那一路每 3 塊夾 1 塊空白，辨識覆蓋率掉到 36～47%，
       計費也變 1.5 倍。
       現在改成：**正在送資料的每一路都湊滿一塊，才相加送出**。某一路超過 grace 秒沒送資料
       （WASAPI 側錄在端點閒置時完全不給資料），就不等它、當成靜音，另一路照常即時送出；
       它恢復送資料後自動加回來。
    🔴 一定要對 src._lanes 取快照再迭代：某一路啟動失敗時 _guard 會把它從字典移掉。
    """
    import queue
    import numpy as np          # 放在函式裡：這個模組本身不相依 numpy
    buf, last = {}, {}
    cut = {}                    # 每一路這一波卡住後被剪掉的量：[累計樣本數, 最後一次修剪的時間]

    def report(k):
        total = cut.pop(k)[0]
        if total > 3 * n:
            src.drop.say(f"{CLR_LINE}\n{YEL}  ⚠ 有一路聲音卡住後一次補進來，為了跟上即時，剛才丟掉了約 "
                         f"{total / (n * 10):.1f} 秒（這段話可能沒有字幕）{RESET}")

    while not src.stop.is_set():
        lanes = [k for k, _ in list(src._lanes.items())]        # ← 快照
        if not lanes:
            time.sleep(0.05)
            continue
        for k in list(buf):             # 被 _guard 移掉的那一路，殘留資料一起丟掉
            if k not in lanes:
                buf.pop(k)
                last.pop(k, None)
        for k in lanes:
            lq = src._lanes.get(k)
            b = buf.setdefault(k, np.zeros(0, dtype=np.float32))
            parts = []
            while lq is not None:
                try:
                    parts.append(lq.get_nowait())
                except queue.Empty:
                    break
            if parts:
                b = np.concatenate([b] + parts)
                last[k] = time.monotonic()      # 不用 time.time()：系統對時往回跳會把閒置的一路誤當成還在送
            buf[k] = b
        now = time.monotonic()
        live = [k for k in lanes if now - last.get(k, float("-inf")) <= grace]
        for k in [k for k, c in cut.items() if now - c[1] > 2.0]:
            report(k)                   # 超過 2 秒沒再剪＝這一波結束，講一次總量
        if live and any(len(buf[k]) < n for k in live):
            time.sleep(poll)            # 有一路正在送、只是這一塊還沒到齊 → 等它（最多 grace 秒）
            continue
        # 兩個裝置的時鐘不會一樣快，快的那一路會比慢的那一路越囤越多（0.1% 的誤差一小時約 3.6 秒）。
        # 🔴 只修剪「比最慢那一路多出來」的部分；兩路的積壓在同一輪一起讀到（例如混音器執行緒自己
        #    短暫卡住）是正常的聲音，一個字都不能丟。兩路的積壓如果分在不同輪才到，後到那一路一樣會被
        #    當成下面講的「某一路卡住後一次補進來」而剪掉（2026-09-19 審查）。
        # 🔴 修剪一定要排在上面的等待之後：某一路剛停、還在 grace 內時手上不到一塊，這時算出來的
        #    最慢量是 0，另一路正在講的聲音會被當成「多出來的」剪掉（審查模擬：少 200ms）。
        # 🔴 取捨（2026-09-19 審查）：某一路卡住超過約 0.7 秒、之後一次補進來時，補進來的真聲音也會被
        #    當成漂移剪掉。不剪的話那一路之後會一直延遲、而且每卡一次就往上加，所以還是剪，但要講——
        #    跟 DropWatch 同一個原則：聲音遺失不能靜默。積壓常常分好幾輪才吐完，所以每次修剪都累計進
        #    這一路的「這一波」，2 秒沒再剪＝一波結束，總量超過 3 塊才講一次——不然會拆成好幾行、每行只報
        #    一部分，或慢慢吐出時每輪都不到門檻而完全不講（2026-09-19 審查）。時鐘漂移一次只剪一塊左右、
        #    兩次修剪隔好幾秒，會各自成一波、不到門檻，不會誤報。
        if len(live) > 1:
            floor = min(len(buf[k]) for k in live)
            for k in live:
                extra = len(buf[k]) - floor - max_blocks * n
                if extra > 0:
                    buf[k] = buf[k][extra:]
                    c = cut.setdefault(k, [0, now])
                    c[0] += extra
                    c[1] = now
        # 閒置那幾路剩下不到一塊的尾巴也併進來（補零），不要卡在緩衝裡
        use = [k for k in lanes if len(buf[k]) >= n or (k not in live and len(buf[k]) > 0)]
        if not use:
            time.sleep(poll)
            continue
        mix = np.zeros(n, dtype=np.float32)
        for k in use:
            take = min(len(buf[k]), n)
            mix[:take] += buf[k][:take]
            buf[k] = buf[k][take:]
        try:
            src.q.put_nowait(np.clip(mix, -32768, 32767).astype(np.int16).tobytes())
            src.drop.kept()
        except queue.Full:
            # 佇列滿＝送不出去，聲音是真的會遺失的，必須講
            src.drop.dropped()
    for k in list(cut):
        report(k)                       # 收尾時還沒講的那一波也要講


# ─────────────────────── 收音：跟著 Windows 預設裝置走，掉了自動接回 ───────────────────────
# 🔴 2026-09-22 會議實測：耳麥插頭鬆了約 3 秒（14:25:12），「兩者都要」兩路收音永久失效、插回去也不恢復，
#    畫面還印「仍會用麥克風繼續，字幕照常運作」。同晚用 TIO 自己的 AudioSource 重現（20:52:39）：
#    側錄丟 OSError -9999 被 _guard 移除；麥克風的回呼停了沒有任何人發現。兩路都只在開頭開一次裝置。
#    這裡改成每一路自己看門：掉了就講一聲、每秒用「Windows 當下的預設裝置」重開，接回來再講一聲。
MIC_LOST_AFTER = 1.5   # 麥克風活著就一定每 100ms 送一塊（連降噪輸出的全 0 也會送）；這麼久沒有＝裝置掉了
REOPEN_EVERY = 1.0     # 掉了之後每隔多久試一次
DEFAULT_POLL = 1.0     # 多久問一次 Windows「現在預設是哪顆」（純 COM＋登錄檔，約 1 毫秒）
# 🔴 完整收音（RAW）沒有 Windows 的濾波：耳麥 RAW 實測 51% 能量在 100Hz 以下（嗡聲），辨識 0 句；
#    濾掉 120Hz 以下變 2 句，內建麥克風濾前濾後一樣（2026-09-22 筆電 E5）。
MIC_HPF_HZ = 120

# 這個行程裡有沒有 sounddevice 的播放串流開著（口譯語音 Speaker）。
# 🔴 有的話絕對不能重新初始化 PortAudio：播放執行緒還在寫的時候拆掉聲音元件，python.exe 會整個當掉
#    （0xC0000005，見 Speaker.close 的說明）。這時麥克風只在「開頭就認得的裝置」之間切換。
_sd_outputs_open = 0
# 🔴 重抓裝置清單（_terminate/_initialize）跟「開口譯語音的播放串流」不可以同時發生：功能 6 是先開收音、
#    再開 Speaker，這一兩秒內剛好碰上拔插，兩邊就會撞在一起。兩個動作都要先拿這把鎖。
_sd_lock = threading.Lock()
MIC_FIRST_GRACE = 5.0  # 剛開的裝置第一塊可能要等比較久（藍牙耳麥切到通話模式要 1～3 秒），這段期間不判斷斷線


class _Switch(Exception):
    """Windows 的預設裝置換了：改用新的那顆。"""


def default_device_name(flow):
    """Windows 此刻的預設裝置（0＝播放、1＝錄音）的完整名稱；問不到回 None。**V1.31 起只給畫面顯示與「查不到 ID」時的退路用。**

    🔴 不可以問 PortAudio：它的裝置清單在行程啟動時就定了，之後不會更新（見 _audioroute._refresh_sounddevice）。
    """
    try:
        import _audioroute
        ids = _audioroute.default_endpoint_ids(flow)
        return _audioroute.endpoint_full_name((ids or {}).get(0))
    except Exception:
        return None


# ─────────────────── V1.31：認裝置一律用 Windows 的端點 ID，不比名稱 ───────────────────
# 🔴 2026-09-28 同事的 ASUS（中文 Windows）：功能 6 收電腦聲音一開就「找不到「 耳機 (Realtek(R) Audio)」的側錄裝置」，
#    6_診斷 卻全部 OK。原因：以前拿「登錄檔組出來的名稱」去錄音元件的清單裡找同名的那一顆，兩個來源在那台差了一個
#    看不見的字元（開頭多一格）。裝置名稱是每台電腦的音效驅動程式寫的（廠商、語言各自不同，使用者也能在「聲音」控制台
#    改名；微軟文件 Friendly Names for Audio Endpoint Devices），換一台就可能換一種差法——一台一台修不完。
#    所以從源頭改：「哪一顆」一律比 Windows 給每個裝置的端點 ID（固定、唯一）；錄音元件的裝置用 PaWasapi_GetIMMDevice
#    查出它的端點 ID。只有這台查不到 ID（舊版元件）時才退回名稱，而且比對前先 norm_device_name。
def default_device_id(flow, role=0):
    """Windows 此刻的預設裝置（flow 0＝播放、1＝錄音）的端點 ID（{0.0.0.…}／{0.0.1.…}）；問不到回 None。
    role：0＝一般（選單、_audioroute 用的）、1＝多媒體——🔴 PortAudio／PyAudioWPatch 的「預設」是多媒體角色
    （原始碼 pa_win_wasapi.c：GetDefaultAudioEndpoint(…, eMultimedia, …)，兩份都查過），跟它比的地方要用 1。
    Windows 的「聲音」設定一律兩個角色一起設，只有第三方工具會把它們拆開。"""
    try:
        import _audioroute
        return (_audioroute.default_endpoint_ids(flow) or {}).get(role)
    except Exception:
        return None


def norm_device_name(s):
    """查不到端點 ID 時比名稱用：全形半形統一、拿掉看不見的字元（方向標記、零寬字元、控制字元）、頭尾與重複的空白、大小寫。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Cc"))
    return " ".join(s.split()).casefold()


_GET_IMM = []      # PaWasapi_GetIMMDevice（第一次用到才找；元件太舊沒有這個函式＝[None]）


def wasapi_endpoint_id(sd, index):
    """sounddevice（PortAudio）的 WASAPI 裝置編號 → Windows 端點 ID；取不到回 None（元件太舊、不是 WASAPI 裝置、出錯）。

    PaWasapi_GetIMMDevice 取得那一顆的 IMMDevice，再呼叫 IMMDevice::GetId。🔴 虛擬函式表的位置：0 QueryInterface、
    1 AddRef、2 Release、3 Activate、4 OpenPropertyStore、5 GetId（數錯一格就會呼叫到別的方法）。
    2026-09-28 筆電實測：三個 WASAPI 裝置都查得到，預設播放／錄音那兩顆的 ID 與 Windows 回報的預設 ID 完全相同。
    """
    try:
        import ctypes
        if not _GET_IMM:
            lib = getattr(sd, "_libname", None)
            fn = getattr(ctypes.CDLL(lib), "PaWasapi_GetIMMDevice", None) if lib else None
            if fn is not None:
                fn.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
                fn.restype = ctypes.c_int
            _GET_IMM.append(fn)
        fn = _GET_IMM[0]
        if fn is None:
            return None
        dev = ctypes.c_void_p()
        if fn(int(index), ctypes.byref(dev)) != 0 or not dev.value:
            return None
        vtbl = ctypes.cast(dev, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_id = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(vtbl[5])
        out = ctypes.c_void_p()
        if get_id(dev, ctypes.byref(out)) != 0 or not out.value:
            return None
        try:
            return ctypes.wstring_at(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(out.value))
    except Exception:
        return None


def _is_endpoint_id(key):
    return str(key or "").startswith("{0.0.")


def _same_key(a, b):
    """兩個「認裝置用的鍵」是不是同一顆：都是端點 ID 就比 ID；否則比 norm_device_name 之後的名稱。"""
    if not a or not b:
        return False
    if _is_endpoint_id(a) and _is_endpoint_id(b):
        return str(a).lower() == str(b).lower()
    return norm_device_name(a) == norm_device_name(b)


def _device_label(key):
    """畫面上要顯示的名稱：端點 ID 就問 Windows 它叫什麼（查不到就顯示 ID 本身）。"""
    if _is_endpoint_id(key):
        try:
            import _audioroute
            return (_audioroute.endpoint_full_name(key) or key).strip()
        except Exception:
            return key
    return key


def _ids_available(sd, devs):
    """這台的錄音元件查不查得到端點 ID（devs＝[(編號, 裝置資訊)]）。查不到＝舊版元件，改用名稱。"""
    return any(wasapi_endpoint_id(sd, i) for i, _d in devs)


def _key_of(sd, idx, d):
    """已經開起來的那一顆，之後拿來比對用的鍵：端點 ID（查得到時）或它在錄音元件裡的名稱。"""
    return wasapi_endpoint_id(sd, idx) or d["name"]


def _wasapi_inputs(sd):
    try:
        api = next(i for i, a in enumerate(sd.query_hostapis()) if a["name"] == "Windows WASAPI")
    except StopIteration:
        return None, []
    return api, [(i, d) for i, d in enumerate(sd.query_devices())
                 if d["hostapi"] == api and d["max_input_channels"] > 0 and "[Loopback]" not in d["name"]]


def _pick_input(sd, want, keep=None):
    """在 PortAudio 的 WASAPI 錄音裝置裡找 want（Windows 的預設）；找不到就退回 keep（目前在用的）。
    V1.31：want／keep 是端點 ID（比 ID）或名稱（使用者在選單指定的那一支、或這台查不到 ID 時；比 norm_device_name）。"""
    api, devs = _wasapi_inputs(sd)
    for key in (want, keep):
        for i, d in devs:
            if key and (_same_key(wasapi_endpoint_id(sd, i), key) if _is_endpoint_id(key)
                        else _same_key(d["name"], key)):
                return i, d
    if api is not None and not want and not keep:
        i = sd.query_hostapis(api)["default_input_device"]
        if i is not None and i >= 0:
            return i, sd.query_devices(i)
    return None, None


def input_device_names():
    """這台電腦的錄音裝置（WASAPI 名稱，跟 Windows 顯示的一樣），給選單列出來讓使用者挑。查不到回 []。"""
    try:
        import sounddevice as sd
        return [d["name"] for _i, d in _wasapi_inputs(sd)[1]]
    except Exception:
        return []


def default_input_name():
    """Windows 此刻的預設麥克風，用 input_device_names() 那一套名稱（選單標「← 現在 Windows 的預設就是這一支」用）。
    V1.31：用端點 ID 對到清單裡那一支；這台查不到 ID 才退回登錄檔的名稱。查不到回 None。"""
    try:
        import sounddevice as sd
        devs = _wasapi_inputs(sd)[1]
        if _ids_available(sd, devs):
            want = default_device_id(1)
            return next((d["name"] for i, d in devs if _same_key(wasapi_endpoint_id(sd, i), want)), None)
    except Exception:
        pass
    return default_device_name(1)


def capture_mic(src, lane, chunk_ms, raw=False, device=None, say=print):
    """麥克風這一路。開 Windows 目前的預設錄音裝置（WASAPI 共用模式），裝置掉了、或預設換了就自動重開。
    device：使用者指定的麥克風名稱（選單 P2）。有指定就只用那一支、不跟著 Windows 預設換，掉了就等它回來；
    第一次就開不起來時**不退回別支**（見下面 except 的說明），講清楚之後丟例外。

    raw=True：完整收音——AUDCLNT_STREAMOPTIONS_RAW，繞過 Windows 的降噪／迴音消除／自動增益，
    會議室擴音器、筆電自己的喇叭放出來的聲音才收得到（2026-09-22 筆電實測：筆電喇叭播會議錄音，
    一般收法辨識 0 句、完整收音 4 句，原檔 7 句）。代價是冷氣、鍵盤聲也會照單全收。
    第一次就開不起來才丟例外（交給各支腳本的 _guard 講原因）；之後的中斷一律自己處理、不往外丟。
    src 要有：_push(樣本, 取樣率, lane)、_ready、stop。
    """
    # 🔴 2026-09-25 拔插實測（V1.21 ①）：PortAudio 的 WASAPI 串流要「開它的那條執行緒」初始化過 COM。
    #    sounddevice 在哪條執行緒第一次 import，PortAudio 就在那條初始化（COM 也只有那條有）。功能 6 在主執行緒先
    #    試開口譯的播放裝置 → 這條收音執行緒沒有 COM → 指定的那支 start() 失敗（-9999；訊息裡的 WDM-KS 是殘留的舊錯誤，
    #    不是真因）→ 以前退回 MME＝Windows 預設：「只用某一支」在功能 6 從 V1.13 起從沒生效過，拔掉耳麥後還用 MME 的
    #    舊編號重開，錄到內建麥克風卻印「耳麥接回來了」，插回去也不會換回來。
    #    「讓程式自己選」一直沒事，只是因為它先問 Windows 預設（_audioroute 的 CoInitialize 順便初始化了這條執行緒）。
    #    所以這裡自己先初始化，不靠那個巧合。
    try:
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass
    import numpy as np
    import sounddevice as sd
    from scipy.signal import butter, sosfilt
    devs = src.__dict__.setdefault("devices", {})
    first, told, cur, skip, why = True, False, None, None, ""
    cur_key, ids_ok = None, False   # V1.31：目前這一支的鍵（端點 ID，查不到才用名稱）；這台查不查得到 ID
    legacy = False      # WASAPI 第一次就開不起來：退回舊版的路徑（PortAudio 預設＝MME），照樣看門
    while not src.stop.is_set():
        try:
            if not first:
                with _sd_lock:
                    if _sd_outputs_open == 0:
                        # 看得到「開始之後才插上」的裝置。只有這個行程沒有其他 sounddevice 串流時才可以做。
                        sd._terminate()
                        sd._initialize()
            if legacy:
                idx, d, extra = None, sd.query_devices(kind="input"), None
            else:
                ids_ok = _ids_available(sd, _wasapi_inputs(sd)[1])
                if device:
                    idx, d = _pick_input(sd, device)
                    if d is None:
                        raise RuntimeError(f"找不到你指定的麥克風「{device}」")
                else:
                    idx, d = _pick_input(sd, default_device_id(1) if ids_ok else default_device_name(1), keep=cur_key)
                if d is None:
                    raise RuntimeError("找不到錄音裝置")
                extra = sd.WasapiSettings()
                if raw:
                    extra._streaminfo.streamOption = sd._lib.eStreamOptionRaw
            sr = int(d["default_samplerate"])
            ch = 1 if legacy else d["max_input_channels"]
            sos = butter(4, MIC_HPF_HZ, btype="highpass", fs=sr, output="sos") if raw else None
            zi = [np.zeros((sos.shape[0], 2)) if sos is not None else None]
            last = [None]                      # 最後一次收到資料的時間；None＝這條串流還沒送過任何一塊

            def cb(indata, frames, t, status):
                if src.stop.is_set():
                    raise sd.CallbackStop
                last[0] = time.monotonic()
                x = indata.mean(axis=1).astype(np.float64) * 32768.0
                if sos is not None:
                    x, zi[0] = sosfilt(sos, x, zi=zi[0])
                note_level(src, lane, float(np.sqrt(np.mean(np.square(x)))) / 32768.0)
                src._push(x.astype(np.float32), sr, lane)

            with sd.InputStream(device=idx, samplerate=sr, channels=ch, dtype="float32",
                                blocksize=int(sr * chunk_ms / 1000), callback=cb, extra_settings=extra):
                cur = devs[lane] = d["name"]
                cur_key = _key_of(sd, idx, d) if not legacy else cur
                src.__dict__["mic_raw_active"] = bool(raw)     # 完整收音開不起來時會退回一般收音，檔頭照實寫
                if _same_key(cur_key, skip):
                    skip = None
                if first:
                    say(f"{DIM}  麥克風：{cur}  {sr}Hz"
                        f"{'（完整收音：不經 Windows 降噪，擴音器的聲音也收）' if raw else ''}{RESET}")
                    src._ready.add(lane)
                elif why == "switch":
                    say(f"{CLR_LINE}{GRN}  ✓ 麥克風改用：{cur}{RESET}\n")
                else:
                    say(f"{CLR_LINE}\n{GRN}  ✓ 麥克風接回來了：{cur}{RESET}\n")
                first, told = False, False
                opened = time.monotonic()
                poll = opened + DEFAULT_POLL
                while not src.stop.is_set():
                    time.sleep(0.1)
                    now = time.monotonic()
                    if (now - last[0] > MIC_LOST_AFTER) if last[0] else (now - opened > MIC_FIRST_GRACE):
                        raise RuntimeError("收不到麥克風的聲音")
                    if now >= poll and not legacy and not device:
                        poll = now + DEFAULT_POLL
                        # V1.31：比端點 ID（這台查不到 ID 才比名稱）。以前比名稱：登錄檔的名稱跟錄音元件的名稱差一個
                        #    看不見的字元時，每一輪都判成「預設換了」、反覆重開。
                        nxt = default_device_id(1) if ids_ok else default_device_name(1)
                        if nxt and not _same_key(nxt, cur_key) and not _same_key(nxt, skip):
                            hit = _pick_input(sd, nxt)[1]
                            # 新的預設不在清單裡：能重抓清單才去試（試過一次沒有就記住，不要每秒重開一次）
                            if hit is not None or _sd_outputs_open == 0:
                                skip = nxt
                                raise _Switch(hit["name"] if hit else _device_label(nxt))
            return
        except _Switch as e:
            why = "switch"
            say(f"{CLR_LINE}\n{DIM}  🔄 Windows 的預設麥克風換成「{e}」，跟著換過去…{RESET}")
        except Exception:
            why = "lost"
            if first and not legacy:
                if raw:
                    say(f"{YEL}  ⚠ 完整收音開不起來，改用一般收音（擴音器的聲音可能收不到）。{RESET}")
                    if device:
                        raw = False        # 指定了裝置：先在同一支上改一般收音再試，不要直接跳去 MME 的「Windows 預設」
                        continue
                if device:
                    # 🔴 2026-09-25（V1.21 ②，使用者核准）：指定的那一支開不起來，不可以默默改用別支——以前這裡退回
                    #    MME＝Windows 預設，檔頭和畫面照寫指定的名字，實際錄的卻是另一支。講清楚，交給 _guard 收這一路。
                    #    （技術細節由 _guard 接著印，這裡不重複；只收麥克風時程式會自己結束，所以不教按 Ctrl+C）
                    say(f"{CLR_LINE}\n{YEL}  ⚠ 你指定的麥克風「{device}」開不起來，沒有改用別支（以免錄錯麥克風）。{RESET}\n"
                        f"{DIM}     要改用別支：結束這一場之後回選單重選（選 1＝讓程式自己選）。{RESET}")
                    raise
                legacy, raw = True, False
                continue
            if first:
                raise
            if src.stop.is_set():
                return
            if not told:
                told = True
                say(f"{CLR_LINE}\n{YEL}  ⚠ 麥克風中斷了（耳麥被拔掉，或插頭鬆了？）——正在自動重新接上，接好會告訴你。"
                    f"{RESET}\n{DIM}     這段時間講的話不會有字幕。"
                    + (f"你指定的是「{device}」，要改用別支請按 Ctrl+C 結束後重開。" if device else "")
                    + f"{RESET}")
            src.stop.wait(REOPEN_EVERY)


def _render_present(eid):
    """這顆播放裝置（端點 ID）現在還在不在（登錄檔 DeviceState＝1 啟用）。

    🔴 查不到（沒有 ID、登錄檔出錯）一律當作還在——誤判成「掉了」會讓側錄每秒重開一次，比沒偵測更糟。
    V1.31：以前拿名稱在登錄檔裡找，名稱寫法跟錄音元件不一樣的電腦一顆都對不上，偵測等於沒有；改成直接查那個端點：
    先問 Windows 正式的狀態（_audioroute.endpoint_state），問不到才看登錄檔。
    """
    try:
        import _audioroute
        st = _audioroute.endpoint_state(eid) if eid else None
        if st is not None:
            return st == _audioroute._DEVICE_STATE_ACTIVE
    except Exception:
        pass
    try:
        import winreg
        import _audioroute
        guid = str(eid).rsplit("}.", 1)[1]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _audioroute._REG_RENDER + "\\" + guid) as k:
            return winreg.QueryValueEx(k, "DeviceState")[0] == _audioroute._DEVICE_STATE_ACTIVE
    except Exception:
        return True


def _lb_key(s):
    """PyAudioWPatch 側錄裝置名稱的比對鍵：它把「名稱 [Loopback]」截在 126 個位元組（pa_win_wasapi.c：
    _snprintf(…, PA_WASAPI_DEVICE_NAME_LEN - 1, "%s [Loopback]", name)），拿來比的一方也照樣截。"""
    return str(s or "").encode("utf-8")[:126].decode("utf-8", "ignore")


def _endpoint_friendly_name(eid):
    """端點 ID → Windows 的 FriendlyName（＝PyAudioWPatch 名稱的來源，見 _audioroute.endpoint_friendly_name）；問不到回 None。"""
    try:
        import _audioroute
        return _audioroute.endpoint_friendly_name(eid) if eid else None
    except Exception:
        return None


def _render_id_named(name, old=None):
    """照名稱接回同一顆之後，它現在的端點 ID：舊的還在就用舊的；不在了（USB 重新辨識換了 ID）就找啟用中、名稱相同的那一個；
    同名的不只一個又分不出來就回 None（之後預設剛好是它時再補，見 capture_loopback 的檢查）。"""
    try:
        import _audioroute
        st = _audioroute.endpoint_state(old) if old else None
        if st == _audioroute._DEVICE_STATE_ACTIVE:
            return old
        ids = _audioroute.active_render_ids_named(name)
    except Exception:
        return old
    if len(ids) == 1:
        return ids[0]
    return old if (old in ids or st is None) else None    # 狀態問不到又對不出唯一一顆：照舊（寧可不偵測，也不要每秒重開）


def _pick_loopback(p, pa, name=None, k=None, n=None):
    """在這個 PyAudio 看得到的側錄裝置裡找一顆，回 (裝置資訊 或 None, [看得到的側錄裝置名稱])；
    裝置資訊多兩欄：_k＝它是同名裡的第幾顆、_n＝同名的一共幾顆。
    name＝播放裝置的 FriendlyName（Windows 給那個 ID 的名稱，或上次錄的那一顆在 PyAudio 裡的名稱）；
    None＝退而求其次，用 PyAudio 自己抓的預設（只在問不到 Windows 時）。
    k、n＝功能 6 重開時：當初是同名 n 顆裡的第 k 顆。🔴 同名的沒有全部到齊（n 對不上）就當作沒找到、繼續等——
       少了一顆，順位就會位移，可能挑到同名的口譯那一顆、錄到自己的口譯（V1.31 審查第四輪 #1）。

    🔴 V1.31：不再拿登錄檔組出來的名稱來找——09-28 同事的 ASUS：登錄檔那邊開頭多一格空白，一個字元對不上就「找不到側錄裝置」。
       依據（PyAudioWPatch 0.2.12.8 原始碼 pa_win_wasapi.c，09-28 查過）：播放裝置的名稱＝Windows 的 FriendlyName；
       第 j 個播放裝置的側錄裝置接在清單尾端第 j 個，名稱＝「原名稱 [Loopback]」（作者註明別的專案靠這個名稱找，不會改）。
       兩顆同名時（分不出來），用 PyAudio 的預設「是同名裡的第幾顆」對到同名側錄的第幾顆——兩邊都照同一個順序建。
    """
    lbs = list(p.get_loopback_device_info_generator())
    names = [d["name"] for d in lbs]
    try:
        w = p.get_host_api_info_by_type(pa.paWASAPI)
        out = p.get_device_info_by_index(w["defaultOutputDevice"])
    except Exception:
        out = None
    if name is None:
        if out is None:
            return None, names
        name = out["name"]
    want = _lb_key(name + " [Loopback]")
    hits = [d for d in lbs if _lb_key(d["name"]) == want]
    if n is not None and n > 1 and len(hits) != n:
        return None, names
    if len(hits) > 1 and k is None and out is not None and _lb_key(out["name"] + " [Loopback]") == want:
        try:
            same = [d["index"] for d in p.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI)
                    if not d.get("isLoopbackDevice") and d.get("maxOutputChannels", 0) > 0
                    and _lb_key(d["name"] + " [Loopback]") == want]
            k = same.index(out["index"]) if out["index"] in same else 0
        except Exception:
            k = 0
    k = k if k is not None and 0 <= k < len(hits) else 0
    return (dict(hits[k], _k=k, _n=len(hits)) if hits else None), names


def capture_loopback(src, lane, chunk_ms, follow_default=True, say=print):
    """電腦播出來的聲音這一路。側錄 Windows 目前的預設播放裝置；裝置掉了、或預設換了就自動重開。

    🔴 不用阻塞的 read()：端點上沒有任何程式在播放時，WASAPI 側錄完全不給資料，read() 會一直卡住
       （09-19 筆電實測），看門狗也就跟著卡死。改成先問 get_read_available()。
    🔴 每次重開都 new 一個 PyAudio：pyaudiowpatch 只有這時才會重新問 Windows 裝置清單。
       整個行程只有這一路用 pyaudiowpatch，所以可以這樣做。
    follow_default=False：只在「同一顆」掉了又回來時接回，不跟著預設換（功能 6 口譯：
       預設播放是刻意切過去的，跟著換可能換到口譯語音那顆，自己錄到自己）。
    """
    import numpy as np
    import pyaudiowpatch as pa
    devs = src.__dict__.setdefault("devices", {})
    first, told, cur, why = True, False, None, ""
    cur_id = None      # V1.31：錄的那一顆的端點 ID（看它還在不在、預設有沒有換，都比 ID）
    cur_lb = None      # 錄的那一顆在 PyAudio 裡的側錄名稱（功能 6 重開時照它找回同一顆）
    cur_k = None       # 它是同名裡的第幾顆（兩顆同名時，功能 6 重開照這個順位，不看當下的預設：審查第三輪 #4）
    cur_n = None       # 開的時候同名的一共幾顆（功能 6 重開時同名的要全部到齊才接：審查第四輪 #1）
    while not src.stop.is_set():
        try:
            follow = follow_default or cur is None
            if follow:
                # 🔴 開「Windows 預設（多媒體角色）的那一顆」：先問它的 ID，再用 Windows 給這個 ID 的 FriendlyName 去找——
                #    PyAudioWPatch 的名稱就是讀這個屬性，同一個來源。不用 PyAudio 自己抓的預設：它晚幾十～幾百毫秒才抓，
                #    預設剛好在那一瞬間閃一下（HDMI、藍牙）就會錄到別顆、記下的 ID 卻是原本那顆，之後永遠不會發現
                #    （V1.31 審查第二輪 #1）。這樣記下的 ID 一定就是開的那一顆。問不到 Windows 才退回 PyAudio 的預設。
                cur_id = default_device_id(0, role=1)
                want = _endpoint_friendly_name(cur_id)
            else:
                want = cur_lb[:-len(" [Loopback]")] if cur_lb.endswith(" [Loopback]") else cur_lb   # 功能 6：同一顆，同一個來源的名稱
            with pa.PyAudio() as p:
                lb, seen = (_pick_loopback(p, pa, want) if follow else _pick_loopback(p, pa, want, cur_k, cur_n))
                if lb is not None and not follow and (cur_n or 1) == 1:
                    # 照名稱接回同一顆：USB 裝置重新辨識時名稱一樣、端點 ID 可能換了——補上它現在的 ID，
                    # 不然「還在不在」一直看舊的 ID，每兩秒斷一次又接回來（審查第三輪 #3）。同名的不只一顆時不換（分不出是哪一顆）
                    cur_id = _render_id_named(want, cur_id)
                if lb is None:
                    what = "Windows 預設的播放裝置" if follow else cur
                    listed = "、".join(seen) or "一個都沒有"
                    raise RuntimeError(f"找不到「{what}」的側錄裝置（這台看得到的側錄裝置：{listed}）")
                sr, ch = int(lb["defaultSampleRate"]), lb["maxInputChannels"]
                n = int(sr * chunk_ms / 1000)
                st = p.open(format=pa.paInt16, channels=ch, rate=sr, input=True,
                            input_device_index=lb["index"], frames_per_buffer=n)
                try:
                    prev = cur
                    cur_lb, cur_k, cur_n = lb["name"], lb.get("_k", 0), lb.get("_n", 1)
                    cur = devs[lane] = lb["name"].replace(" [Loopback]", "")
                    if first:
                        say(f"{DIM}  聲音來源：{lb['name']}  {sr}Hz{RESET}")
                        src._ready.add(lane)
                    elif why == "switch":
                        say(f"{CLR_LINE}{GRN}  ✓ 電腦聲音改從這顆錄：{cur}{RESET}\n")
                    elif cur != prev:
                        # V1.31（使用者 09-28 拔電視實測後同意改）：原本那顆不見了、跟著 Windows 的預設改錄另一顆——
                        # 以前也寫「接回來了」，看起來像原本那顆（電視）回來了
                        say(f"{CLR_LINE}\n{GRN}  ✓ 電腦聲音改從這顆錄：{cur}（原本那顆不見了）{RESET}\n")
                    else:
                        say(f"{CLR_LINE}\n{GRN}  ✓ 電腦聲音接回來了：{cur}{RESET}\n")
                    first, told = False, False
                    poll = time.monotonic() + DEFAULT_POLL
                    while not src.stop.is_set():
                        if st.get_read_available() >= n:
                            raw = st.read(n, exception_on_overflow=False)
                            a = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).mean(axis=1)
                            note_level(src, lane, float(np.sqrt(np.mean(np.square(a)))) / 32768.0)
                            src._push(a, sr, lane)
                            continue
                        time.sleep(0.01)
                        now = time.monotonic()
                        if now >= poll:
                            poll = now + DEFAULT_POLL
                            nxt = default_device_id(0, role=1)
                            # 🔴 開的時候剛好問不到 ID（USB 耳機拔插的那一瞬間、COM 偶爾失敗）＝cur_id 是空的，拔除和換預設都偵測不到
                            #    （V1.31 審查 #1、第二輪 #3）：現在的預設就是這一顆（名稱同一個來源）→ 直接補上 ID，不用重開
                            if not cur_id and nxt and _lb_key((_endpoint_friendly_name(nxt) or "\0") + " [Loopback]") == _lb_key(cur_lb):
                                cur_id = nxt
                            # 🔴 拔掉的端點不一定讓 get_read_available() 丟例外，自己再看一次它還在不在
                            if cur_id and not _render_present(cur_id):
                                raise RuntimeError(f"「{cur}」不見了")
                            if follow_default and nxt and not _same_key(nxt, cur_id):
                                raise _Switch(_device_label(nxt))
                finally:
                    try:
                        st.stop_stream()
                        st.close()
                    except Exception:
                        pass
            return
        except _Switch as e:
            why = "switch"
            say(f"{CLR_LINE}\n{DIM}  🔄 Windows 的預設播放裝置換成「{e}」，電腦聲音改從那顆錄…{RESET}")
        except Exception:
            why = "lost"
            if first:
                raise
            if src.stop.is_set():
                return
            if not told:
                told = True
                say(f"{CLR_LINE}\n{YEL}  ⚠ 抓不到電腦播出的聲音了（播放裝置被拔掉或換掉？）——正在自動重新接上，接好會告訴你。"
                    f"{RESET}\n{DIM}     這段時間線上的聲音不會有字幕。{RESET}")
            src.stop.wait(REOPEN_EVERY)


# ─────────────────────── 收音狀態（P1 音量表）───────────────────────
# 🔴 2026-09-22 會議：TIO 沒有任何音量顯示，「錄到零／太小聲／網路或辨識出問題」在畫面上長得一模一樣（都是沒字幕），
#    使用者只能會後才發現。但也不要一直洗版：開場印一次，之後只在「一陣子沒有新字幕」時才印——
#    那正是使用者會想問「是沒收到聲音，還是有聲音卻沒出字？」的時候。
#    🔴 不在安靜時擋下來：內建麥克風在安靜房間本來就輸出數位 0（E1：−96.7 dBFS），跟壞掉在取樣上一模一樣。
LEVEL_WINDOW = 30.0        # 看最近幾秒的音量
LEVEL_STALE = 2.0          # 這一路最後一塊比這更舊＝現在沒在收（麥克風活著每 100ms 一塊；看門狗 1.5 秒沒資料就判定掉了）
QUIET_REPORT_AFTER = 30.0  # 這麼久沒有新字幕，就印一次收音狀態
QUIET_REPEAT = 120.0       # 一直沒字幕時，之後隔多久再印（會議休息時不要一直洗版）
# 🔴 2026-09-26（V1.23 C）：電腦播放音量小時，講話會被安靜地漏掉，而「收音檢查」只在開場 6 秒、和整整 30 秒沒字幕時才印
#    ——字幕斷斷續續還在出的時候，使用者完全不會知道。改成：電腦聲音「一直有在播、但一直偏小」就主動提醒一次，點名是哪顆裝置。
#    門檻＝level_report「有收到聲音／聲音偏小／幾乎沒有在播」同一組分界（−50／−70 dB）——兩邊必須一致，
#    否則會出現「提醒說偏小、收音檢查卻說有收到聲音」。改一邊要改另一邊（unit_v123 會抓不一致）。
#    （V1.35 起這組只管電腦聲音；麥克風的「有收到聲音」分界是下面的 MIC_OK_DB，這個提醒本來就只看電腦聲音。）
LOW_SYS_OK_DB = -50.0      # 高於這個＝有收到聲音
LOW_SYS_FLOOR_DB = -70.0   # 低於這個＝電腦幾乎沒有在播（不是太小聲，是沒在播，不提醒）
LOW_SYS_WINDOW = 20.0      # 連續這麼久都偏小才提醒（影片開頭安靜、講話中間的停頓不算）
LOW_SYS_FILL = 0.8         # 這段時間內至少八成有收到資料（＝一直有東西在播）才算數
# V1.35（待辦 7）：麥克風「有收到聲音／聲音偏小」的分界，從 −50 改成 MIC_OK_DB（電腦聲音照舊用 LOW_SYS_OK_DB）。
# 🔴 2026-10-03 V1.34 全線實測 C2（只用麥克風陣列、筆電喇叭播語音）：喇叭 30% 時麥克風第 90 百分位 −49 dB，畫面標「有收到聲音
#    （字幕出得來）」、30 秒提示說「比較可能在網路或辨識」，實際是第 3 句被靜音閘門壓掉、第 5～7 句 Google 回 0 字（7 句只出 3 句）；
#    同一項喇叭 50%（−45.3 dB）7/7、80%（−39.1 dB）7/7 → 取兩者中間。電腦聲音那一路沒有這種實測（V1.23 已把它的閘門下限放低），不動。
#    🔴 V1.35 審查：第一版只改 30 秒提示（門檻 −45）、標籤還是 −50，−50～−45 時同一個畫面上面寫「有收到聲音（字幕出得來）」、
#       下面寫「偏小」。所以改成標籤本身換分界，30 秒提示照標籤講（見 loud_enough），兩邊一定一致。
MIC_OK_DB = -47.0
_last_caption = [0.0]


def note_caption():
    """有新的一句字幕定稿了（三支即時程式在輸出字幕的地方各呼叫一次）。"""
    _last_caption[0] = time.monotonic()


def note_level(src, lane, rms):
    """記下一塊聲音的音量（0～1），給 level_report 用。收音看門狗每收到一塊就呼叫一次。"""
    q = src.__dict__.setdefault("_lvl", {}).get(lane)
    if q is None:
        q = src.__dict__["_lvl"][lane] = collections.deque(maxlen=int(LEVEL_WINDOW * 10) + 50)
    q.append((time.monotonic(), rms))


def level_report(src):
    """(多行說明, 有沒有任何一路收到聲音)。用最近 LEVEL_WINDOW 秒、每 100ms 一塊的音量取第 90 百分位。

    🔴 2026-09-23 使用者指示：原本是「電腦聲音 -37 dB 有聲音」，非工程背景看不懂。
       改成長條圖＋白話，dB 留在括號裡（截圖回報時仍看得到數字）。
       格子換算：−80 dB＝全空、−20 dB＝全滿（實測對照：人在面前約 −35、3 公尺外約 −50、安靜房間約 −96）。
    """
    import math
    names = {"mic": "麥克風　", "system": "電腦聲音"}     # 全形空白是為了兩行對齊
    now, lines, any_sound = time.monotonic(), [], False
    for lane in ("mic", "system"):                        # 固定順序：先麥克風（使用者最常看的那一路）
        if lane not in getattr(src, "_wanted", []):
            continue
        got = src.__dict__.get("_lvl", {}).get(lane, ())
        # 🔴 2026-09-25 拔插實測（V1.21 ④）：耳麥拔掉、這一路已經 0 塊/秒，這裡卻照樣印「有收到聲音（字幕出得來）」——
        #    30 秒的窗裡還留著拔掉前的資料。最後一塊已經超過 LEVEL_STALE 秒＝現在沒在收，照「沒有資料」講。
        vals = [] if not got or now - got[-1][0] > LEVEL_STALE else \
            sorted(r for t, r in got if now - t <= LEVEL_WINDOW)
        if not vals:
            lines.append(f"     {names[lane]}：{'▯' * 8}  "
                         + ("電腦現在沒有在播（沒在播就不會有字幕）" if lane == "system"
                            else "沒有收到資料（裝置被拔掉了？不會有字幕）"))
            continue
        p90 = vals[max(0, int(len(vals) * 0.9) - 1)]
        db = 20 * math.log10(p90) if p90 > 0 else -120.0
        # 🔴 2026-09-23 使用者指示：白話要講「影響」，不是只講大小聲。門檻取自 09-22 實測：
        #    真人 3 公尺內建麥克風 −50 左右辨識正常；手機喇叭 2 公尺 −57～−61 辨識 0 句；−70 以下等於沒有聲音。
        #    V1.35：麥克風的分界改 MIC_OK_DB（−47，見上面 C2 實測）；電腦聲音照舊 −50（LOW_SYS_OK_DB）。
        if db > (MIC_OK_DB if lane == "mic" else LOW_SYS_OK_DB):
            label, any_sound = "有收到聲音", True
            effect = "字幕出得來"
        elif db > -70:
            label, any_sound = "聲音偏小", True
            effect = "字幕可能漏字、不準"
        elif lane == "system":
            label, effect = "電腦現在幾乎沒有在播", "沒有聲音就不會有字幕"
        else:
            label, effect = "幾乎沒有聲音", "不會有字幕"
        n = max(0, min(8, int(round((db + 80) / 7.5))))
        lines.append(f"     {names[lane]}：{'▮' * n}{'▯' * (8 - n)}  {label}（{max(db, -99):.0f} dB，{effect}）")
    return "\n".join(lines), any_sound


def loud_enough(src):
    """這一場收的各路裡，有沒有一路現在標得到「有收到聲音」（跟 level_report 同一種算法、同一組分界）。
    V1.35（待辦 7）給「一陣子沒字幕」的提示判斷用：沒有任何一路夠大 → 提示講「偏小」，不說「比較可能是網路或辨識」。"""
    import math
    now = time.monotonic()
    for lane in ("mic", "system"):
        if lane not in getattr(src, "_wanted", []):
            continue
        got = src.__dict__.get("_lvl", {}).get(lane, ())
        if not got or now - got[-1][0] > LEVEL_STALE:
            continue
        vals = sorted(r for t, r in got if now - t <= LEVEL_WINDOW)
        if not vals:
            continue
        p90 = vals[max(0, int(len(vals) * 0.9) - 1)]
        if p90 > 0 and 20 * math.log10(p90) > (MIC_OK_DB if lane == "mic" else LOW_SYS_OK_DB):
            return True
    return False


def weak_lane(src):
    """V1.36（待辦 14）：「兩者都要」時，一路標「有收到聲音」、另一路沒有 → 回傳 (那一路, 'weak'／'none')：
    'weak'＝標「聲音偏小」；'none'＝標「幾乎沒有聲音／沒有在播／沒有收到資料」（V1.36 審查第二輪：筆電麥克風按了靜音、
    耳麥拔掉時，原本照第 1 句說「不是收音」，跟上一行「不會有字幕」矛盾）。其他情況 → None。跟 level_report 同一種算法、同一組分界。"""
    import math
    wanted = [l for l in ("mic", "system") if l in getattr(src, "_wanted", [])]
    if len(wanted) != 2:
        return None
    now, state = time.monotonic(), {}
    for lane in wanted:
        got = src.__dict__.get("_lvl", {}).get(lane, ())
        vals = [] if not got or now - got[-1][0] > LEVEL_STALE else \
            sorted(r for t, r in got if now - t <= LEVEL_WINDOW)
        if not vals:
            state[lane] = "none"
            continue
        p90 = vals[max(0, int(len(vals) * 0.9) - 1)]
        db = 20 * math.log10(p90) if p90 > 0 else -120.0
        state[lane] = "ok" if db > (MIC_OK_DB if lane == "mic" else LOW_SYS_OK_DB) else "weak" if db > -70 else "none"
    other = [(l, s) for l, s in state.items() if s != "ok"]
    return other[0] if len(other) == 1 else None


def system_level_db(src, now):
    """電腦聲音最近 LOW_SYS_WINDOW 秒的音量（dB，第 90 百分位，跟 level_report 同一種算法）；
    沒在收電腦聲音、現在沒在播、或這段時間沒有一直在播 → None（不下判斷）。"""
    import math
    if "system" not in getattr(src, "_wanted", []):
        return None
    got = src.__dict__.get("_lvl", {}).get("system", ())
    if not got or now - got[-1][0] > LEVEL_STALE:
        return None
    vals = sorted(r for t, r in got if now - t <= LOW_SYS_WINDOW)
    if len(vals) < LOW_SYS_WINDOW * 10 * LOW_SYS_FILL:    # 每 100ms 一塊（三支即時程式的 CHUNK_MS 都是 100）
        return None
    p90 = vals[max(0, int(len(vals) * 0.9) - 1)]
    return 20 * math.log10(p90) if p90 > 0 else -120.0


def start_level_watch(src, say=print, first_after=6.0, loud_extra=None):
    """背景印收音狀態：開場 first_after 秒一次；之後超過 QUIET_REPORT_AFTER 秒沒有新字幕才再印。
    另外：電腦聲音一直在播、卻一直偏小，就提醒一次（V1.23 C；回到正常音量之後再變小會再提醒）。
    loud_extra：聲音夠大卻一直沒字幕時，接在提示後面的一句（V1.35：只有功能 3「快」傳，叫人改用「準」試試）。"""
    # V1.29 ④：提示要看這一場收的是什麼。🔴 2026-09-27 全線實測：只收電腦聲音時，畫面仍叫人「把麥克風移近講者」
    #    「看看麥克風、耳麥插頭」——那一場根本沒開麥克風。三種來源各講各的（只收電腦聲音／只收麥克風／兩者都要）。
    wanted = set(getattr(src, "_wanted", []) or [])
    kind = "system" if wanted == {"system"} else "mic" if wanted == {"mic"} else "both"
    first_tip = {
        "system": ("     ※ 電腦在播有人講話的內容時，應該看到「有收到聲音」。若是「聲音偏小」，請把播放裝置或會議軟體／影片的音量調大；"
                   "「幾乎沒有在播」就是沒錄到聲音，字幕不會出現。\n"
                   "     ※ 這幾段是 TIO 依實測定的，不是 Google 的規定；聲音太小 Google 不會報錯，只會安靜地聽不出來。"),
        "mic": ("     ※ 有人正在講話時應該看到「有收到聲音」。若是「聲音偏小」，請把麥克風移近講者；"
                "「幾乎沒有聲音」就是沒收到，字幕不會出現。\n"
                "     ※ 這三段是 TIO 依實測定的（人在面前約 −35 dB；3 公尺約 −50，已經算「聲音偏小」；安靜房間約 −96），"
                "不是 Google 的規定；聲音太小 Google 不會報錯，只會安靜地聽不出來。"),
        "both": ("     ※ 有人正在講話時應該看到「有收到聲音」。麥克風「聲音偏小」請把麥克風移近講者；"
                 "電腦聲音「聲音偏小」請把播放裝置或會議軟體的音量調大；「幾乎沒有聲音」「幾乎沒有在播」就是沒收到，字幕不會出現。\n"
                 "     ※ 這幾段是 TIO 依實測定的（麥克風：人在面前約 −35 dB；3 公尺約 −50，已經算「聲音偏小」；安靜房間約 −96），"
                 "不是 Google 的規定；聲音太小 Google 不會報錯，只會安靜地聽不出來。"),
    }[kind]
    # V1.35（待辦 7）：第 1 句＝有一路標「有收到聲音」；第 2 句＝幾乎沒收到；第 3 句＝有收到、但每一路都只到「聲音偏小」（見 loud_enough）。
    #    🔴 2026-10-03 X8：素材本身小 28 dB、喇叭 30%，迴路錄音 −74 dB，內容其實在播，畫面說「電腦沒有播出聲音」
    #       ——第 2 句補「或音量開得太小」。
    #    🔴 V1.35 審查：第 3 句也要有「如果確實有人在講話」的前提——休息時間室內底噪約 −60 dB，不加的話每 2 分鐘叫人換麥克風。
    quiet_tip = {
        "system": ("聲音有進來。如果正在播的內容確實有人在講話，問題比較可能在網路或辨識，不是收音。",
                   "電腦幾乎沒有播出聲音：看看會議或影片是不是從這台電腦播出、有沒有被暫停或靜音、音量是不是開得太小。",
                   "聲音有進來，但偏小。如果正在播的內容確實有人在講話：太小聲時 Google 只會安靜地聽不出來、不會報錯，"
                   "先把播放裝置或會議軟體／影片的音量調大；調大了還是沒字，再看網路。"),
        "mic": ("聲音有進來。如果現場確實有人在講話，問題比較可能在網路或辨識，不是收音。",
                "聲音沒有進來（或現場很安靜）：看看麥克風、耳麥插頭，以及麥克風有沒有被靜音、輸入音量是不是調得太小。",
                "聲音有進來，但偏小。如果現場確實有人在講話：太小聲時 Google 只會安靜地聽不出來、不會報錯，"
                "請把麥克風移近講者，或換一支麥克風；還是沒字，再看網路。"),
        "both": ("聲音有進來。如果現場確實有人在講話，問題比較可能在網路或辨識，不是收音。",
                 "聲音沒有進來（或現場很安靜）：看看麥克風、耳麥插頭，或線上會議的聲音是不是從這台電腦播出、音量是不是開得太小。",
                 "聲音有進來，但偏小。如果現場確實有人在講話：太小聲時 Google 只會安靜地聽不出來、不會報錯，"
                 "請把麥克風移近講者，或把播放裝置／會議軟體的音量調大；還是沒字，再看網路。"),
    }[kind]
    # V1.36（待辦 14）：「兩者都要」時一路夠大、另一路偏小——原本照第 1 句講「問題比較可能在網路或辨識，不是收音」，
    #    跟上一行那一路標的「聲音偏小」不搭（V1.35 審查）。程式不知道現在是哪一路的人在講，所以兩種情況都講、點名偏小的那一路。
    #    V1.36 審查第二輪：另一路「幾乎沒有聲音／沒有在播」也點名（麥克風按了靜音、耳麥拔掉、會議聲音沒從這台播出）。
    #    審查第三輪：耳麥拔掉時上一行標的是「沒有收到資料」，提示也要講到。
    weak_tip = {
        ("mic", "weak"): ("電腦聲音有進來，麥克風那一路偏小。如果是現場的人在講話：太小聲時 Google 只會安靜地聽不出來、不會報錯，"
                          "請把麥克風移近講者，或換一支麥克風；如果是線上會議裡的人在講話，問題比較可能在網路或辨識。"),
        ("system", "weak"): ("麥克風有進來，電腦聲音那一路偏小。如果是線上會議或影片裡的人在講話：太小聲時 Google 只會安靜地聽不出來、"
                             "不會報錯，請把播放裝置或會議軟體的音量調大；如果是現場的人在講話，問題比較可能在網路或辨識。"),
        ("mic", "none"): ("電腦聲音有進來，麥克風那一路幾乎沒有聲音或沒有收到資料。如果是現場的人在講話：看看麥克風有沒有被靜音、耳麥插頭有沒有鬆、"
                          "輸入音量是不是調得太小；如果是線上會議裡的人在講話，問題比較可能在網路或辨識。"),
        ("system", "none"): ("麥克風有進來，電腦幾乎沒有播出聲音。如果是線上會議或影片裡的人在講話：看看會議或影片是不是從這台電腦播出、"
                             "有沒有被暫停或靜音、音量是不是開得太小；如果是現場的人在講話，問題比較可能在網路或辨識。"),
    }

    def run():
        t0 = time.monotonic()
        _last_caption[0] = t0
        first, last_print, streak = True, t0, 0
        low_told = False
        while not src.stop.wait(1.0):
            now = time.monotonic()
            if first:
                if now - t0 >= first_after:
                    first, last_print = False, now
                    # 🔴 2026-09-23 使用者問「這是機器／Google／TIO 的收音標準？」——要在畫面上講明是誰定的。
                    say(f"{CLR_LINE}\n{DIM}  🎚 收音檢查（聲音有沒有進到程式裡）\n{level_report(src)[0]}\n"
                        f"{first_tip}{RESET}\n")
                continue
            # V1.23 C：不看有沒有字幕——字幕斷斷續續還在出的時候，正是使用者不會發現漏字的時候。
            # ponytail: 只看音量不看起伏；穩定的底噪（例如線上會議沒人講話時的舒適雜訊）落在 −70～−50 也會提醒一次，
            #           所以句子寫成「如果正在播的是有人講話的內容」。誤報多再加「起伏」判斷（講話忽大忽小、底噪平平的）。
            db = system_level_db(src, now)
            if db is not None and db > LOW_SYS_OK_DB:
                low_told = False
            elif db is not None and db > LOW_SYS_FLOOR_DB and not low_told:
                low_told = True
                name = getattr(src, "devices", {}).get("system") or "目前的播放裝置"
                say(f"{CLR_LINE}\n{YEL}  ⚠ 電腦播出的聲音一直偏小（約 {db:.0f} dB）：字幕可能漏字、不準。{RESET}\n"
                    f"{DIM}     TIO 錄的是「{name}」播出去的聲音：它的音量越小，錄進來就越小。\n"
                    f"     → 如果正在播的是有人講話的內容：把「{name}」的音量調大（工作列右下角的喇叭圖示），"
                    f"或把會議軟體／影片播放器自己的音量調大。{RESET}\n")
            quiet = now - _last_caption[0]
            if quiet < QUIET_REPORT_AFTER:
                streak = 0
                continue
            if now - last_print < (QUIET_REPORT_AFTER if streak == 0 else QUIET_REPEAT):
                continue
            last_print, streak = now, streak + 1
            text, any_sound = level_report(src)
            if not any_sound:
                hint = quiet_tip[1]
            elif not loud_enough(src):
                hint = quiet_tip[2]
            else:
                lane = weak_lane(src) if kind == "both" else None
                hint = (weak_tip[lane] if lane else quiet_tip[0]) + (f"\n     → {loud_extra}" if loud_extra else "")
            say(f"{CLR_LINE}\n{DIM}  🎚 已經 {int(quiet)} 秒沒有新字幕，收音狀態：\n{text}\n     → {hint}{RESET}\n")
    threading.Thread(target=run, daemon=True).start()


def source_line(mode, src):
    """檔頭加的一行：這一場用什麼收音、實際是哪顆裝置。

    🔴 2026-09-22：使用者把字幕檔刪了又要追原因，只能靠內容和時間去猜每一場是「麥克風」還是「兩者都要」，
       猜不準。寫在檔頭，事後一眼就知道。記的是開始那一刻的裝置（中途換了畫面上會講）。
    """
    names = {"system": "電腦播出的聲音", "mic": "麥克風", "both": "兩者都要", "file": "影音檔"}
    devs = getattr(src, "devices", None) or {}
    parts = [names.get(mode, mode)]
    if devs.get("system"):
        parts.append(f"電腦聲音：{devs['system']}")
    if devs.get("mic"):
        parts.append(f"麥克風：{devs['mic']}" + ("（完整收音）" if getattr(src, "mic_raw_active", False) else ""))
    return "來源：" + "｜".join(parts)


def font_hint():
    """字幕太小時怎麼放大（使用者 2026-09-22 指示：要寫在程式裡，不然記不得）。

    Windows Terminal 的放大／縮小是 Ctrl＋「+」／Ctrl＋「-」（官方預設 adjustFontSize，delta ±1）；
    傳統主控台沒有這組快捷鍵，要從視窗內容改。
    🔴 2026-09-23 使用者指示：**不要教 Ctrl＋0**（官方的「還原字級」鍵）——自然輸入法把 Ctrl＋0 用掉了，
       按下去會被輸入法吃掉。改教 Ctrl＋「-」縮小，放大縮小都在同一排按鍵、也不會撞到輸入法。
    🔴 不能看 WT_SESSION：4_開始使用.bat 用 start 開視窗，是 Windows 把它「轉交」給 Windows Terminal 的，
       這種視窗裡沒有 WT_SESSION（2026-09-22 筆電實測）。改看主控台視窗的類別：
       Windows Terminal＝PseudoConsoleWindow、傳統主控台＝ConsoleWindowClass（兩種都實測過）。
    """
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetConsoleWindow()
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.user32.GetClassNameW(ctypes.c_void_p(h), buf, 64)
        cls = buf.value
    except Exception:
        cls = ""
    if cls == "ConsoleWindowClass":
        return "字太小？在視窗標題列按右鍵 →「內容」→「字型」調大"
    return "字太小？按 Ctrl ＋「+」放大（可連按），Ctrl ＋「-」縮小"


SPEAK_SR = 24000        # Live API 的輸出取樣率，規格固定


def probe_output_device(idx, sr=SPEAK_SR):
    """真的把這顆裝置開起來再關掉，回 (可用?, 錯誤訊息)。

    🔴 **不要用「host API 名稱」猜哪顆能用。** 同一台機器上實測（2026-09-18）：
       ・MME、DirectSound         → 開得起來
       ・Windows WASAPI           → `Invalid sample rate [-9997]`（裝置混音率 48000，不吃 24000）
       ・Windows WDM-KS           → `Blocking API not supported yet [-9999]`
       兩種失敗訊息完全不同，而且換一台機器、換一版驅動就可能又不一樣。
       唯一可靠的判準是**開開看**：能開就是能用，開不起來就別列給使用者選。
       病根：使用者從選單挑了一顆 WDM-KS 裝置，一路走到會議開始才看到
       「翻譯語音播不出來」——而語音正是那個功能的全部意義。
    """
    try:
        import sounddevice as sd
        s = sd.RawOutputStream(samplerate=sr, channels=1, dtype="int16",
                               blocksize=1024, device=idx)
        s.start(); s.stop(); s.close()
        return True, ""
    except Exception as e:
        return False, str(e)


def output_devices(usable_only=False):
    """可以拿來播放的裝置 [(編號, 名稱)]。沒裝 sounddevice 就回空清單，不要讓呼叫端爆掉。

    usable_only=True 時會逐顆開開看，只留真的播得出 24kHz 的（見 probe_output_device），
    而且不列 DirectSound（見 _host_api_rank：開得起來、寫得進去，卻完全沒聲音，開開看也測不出來）。
    """
    try:
        import sounddevice as sd
    except Exception:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) > 0:
                if usable_only and (_host_api_rank(i) >= _RANK_DSOUND or not probe_output_device(i)[0]):
                    continue
                out.append((i, d["name"]))
    except Exception:
        return []
    return out


# 播放用的 host API 優先順序。🔴 DirectSound 排最後（2026-09-20 筆電實測 N1）：PortAudio 19.7 的 DirectSound
# 用阻塞寫入（Speaker、試聽都是）時**完全沒聲音、也不報錯**——筆電的電視／喇叭／耳機、桌機的喇叭／數位輸出
# 五顆全部一樣；同一個編號改用 callback 模式有聲，MME 用阻塞寫入也有聲。WASAPI 不吃 24kHz，會直接報錯
# （至少是看得到的失敗）。所以：MME → WASAPI → 其他 → DirectSound。
_RANK_DSOUND = 3


def _host_api_rank(idx):
    try:
        import sounddevice as sd
        api = sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"]
    except Exception:
        return 2                          # 查不到 host API（測試用的假裝置等）：當成「其他」，保持原本順序
    return {"MME": 0, "Windows WASAPI": 1, "Windows DirectSound": _RANK_DSOUND}.get(api, 2)


def mme_endpoint_map():
    """{音訊端點 ID（小寫）: sounddevice 的 MME 播放編號}。問不到就回 {}（呼叫端退回用名稱配對）。

    🔴 2026-09-20 筆電實測 N1：完整名稱超過 31 字的裝置（「1 - KONKA LCDTV (AMD High Definition Audio Device)」）
       用名稱只配得到 DirectSound 那一個編號（MME 把名稱截成 31 字），而 DirectSound 阻塞寫入沒聲音
       （見 _host_api_rank）。MME 的截字名稱又分不出「前 31 字相同」的兩顆，所以直接問 Windows：
       每一個 waveOut 裝置是哪一個音訊端點（DRV_QUERYFUNCTIONINSTANCEID）。
       PortAudio 的 MME 播放清單是「音效對應表」在最前面、接著 waveOut 0…n-1；數量或名稱有一個對不上
       （PortAudio 跳過了某一顆），順序就不可信，整張表不用。
    """
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes
        import sounddevice as sd

        class _Caps(ctypes.Structure):
            _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                        ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD),
                        ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD), ("dwSupport", wintypes.DWORD)]
        winmm = ctypes.WinDLL("winmm")
        winmm.waveOutGetNumDevs.restype = wintypes.UINT
        winmm.waveOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.c_void_p, wintypes.UINT]
        winmm.waveOutGetDevCapsW.restype = wintypes.UINT
        winmm.waveOutMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        winmm.waveOutMessage.restype = wintypes.UINT
        mme = next((a for a in sd.query_hostapis() if a.get("name") == "MME"), None)
        if mme is None:
            return {}
        outs = [i for i in mme["devices"] if sd.query_devices(i).get("max_output_channels", 0) > 0]
        n = winmm.waveOutGetNumDevs()
        if len(outs) != n + 1:
            return {}
        found = {}
        for w in range(n):
            caps = _Caps()
            if winmm.waveOutGetDevCapsW(w, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
                return {}
            idx = outs[w + 1]
            if sd.query_devices(idx)["name"].strip() != caps.szPname.strip():
                return {}
            size = wintypes.ULONG(0)
            if winmm.waveOutMessage(ctypes.c_void_p(w), 0x0812, ctypes.byref(size), None) or not size.value:
                continue                  # 0x0812＝DRV_QUERYFUNCTIONINSTANCEIDSIZE
            buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
            if winmm.waveOutMessage(ctypes.c_void_p(w), 0x0811, buf, ctypes.c_void_p(size.value)):
                continue                  # 0x0811＝DRV_QUERYFUNCTIONINSTANCEID
            found[buf.value.strip().lower()] = idx
        return found
    except Exception:
        return {}


def default_output_name():
    """系統預設的播放裝置名稱。查不到回 None。"""
    try:
        import sounddevice as sd
        return sd.query_devices(kind="output")["name"]
    except Exception:
        return None


def resolve_output_device(spec):
    """把使用者給的播放裝置（None／編號／名稱片段／音訊端點 ID）解析成 (編號, 名稱)。

    🔴 同一顆喇叭在 MME／DirectSound／WASAPI 底下會各出現一次，而且 MME 會把名稱
       截成 31 個字。所以名稱比對用「片段、忽略大小寫」，完整名稱也認得 MME 的截字版。
    🔴 符合的有好幾個時，照 _host_api_rank 挑（MME 優先、DirectSound 最後）。以前「取第一個符合的」，
       完整名稱超過 31 字時只對得到 DirectSound，口譯整場沒聲音、畫面還說播了幾十秒（2026-09-20 筆電實測 N1）。
    🔴 音訊端點 ID（選單「電腦播出來的聲音」的②傳這個）直接問 Windows 對到哪一個 MME 編號，
       前 31 字相同的兩顆也分得開（見 mme_endpoint_map）。
    """
    import sounddevice as sd
    if spec is None or spec == "":
        return None, sd.query_devices(kind="output")["name"]   # None＝交給系統預設
    if isinstance(spec, int) or str(spec).strip().isdigit():
        i = int(spec)
        d = sd.query_devices(i)
        if d.get("max_output_channels", 0) <= 0:
            raise ValueError(f"裝置 {i}（{d['name']}）不能播放聲音")
        return i, d["name"]
    raw = str(spec).strip()
    if raw.startswith("{0.0.0."):
        i = mme_endpoint_map().get(raw.lower())
        if i is None:
            raise ValueError(f"找不到這個音訊端點對應的播放裝置（{raw}），可能已經拔掉了")
        return i, sd.query_devices(i)["name"]
    key = raw.lower()
    hits = [(i, name) for i, name in output_devices()
            if key in name.lower() or (len(name.strip()) >= 31 and key.startswith(name.strip().lower()))]
    if not hits:
        raise ValueError(f"找不到叫「{spec}」的播放裝置")
    hits.sort(key=lambda h: _host_api_rank(h[0]))          # 穩定排序：同一種 API 內維持原本順序
    return hits[0]


def same_device(a, b, n=25):
    """兩個名稱是不是同一顆裝置。MME 會把名稱截短，所以只比前 n 個字。"""
    if not a or not b:
        return False
    return a.strip().lower()[:n] == b.strip().lower()[:n]


# 🔴 這幾個不是實體裝置，是「跟著系統預設走」的轉接器。拿它們當播放目標，聲音還是
#    送到預設那顆去 —— 只比名稱的話會以為選了別顆，回授防護就整個被繞過去。
_DEFAULT_ALIASES = ("microsoft 音效對應表", "microsoft sound mapper",
                    "主要音效驅動程式", "primary sound driver")


def is_default_like(name, default_name=None, idx=None):
    """這顆裝置是不是等於系統預設（本身就是預設，或是跟著預設走的轉接器）。

    V1.31：給了 idx（sounddevice 編號）就比端點 ID——跟側錄錄的那一顆（Windows 多媒體角色的預設）是不是同一顆。
    🔴 以前只比名稱前 25 個字：兩顆不同的裝置前 25 個字一樣（「Speakers (Realtek High Definition Audio)」與
       「…Audio(SST)」這種）就被當成同一顆，功能 6 直接拒絕開始；反過來名稱寫法不同時，防回授就失效。
       查不到 ID（DirectSound、或這台問不到）才退回比名稱。
    """
    if not name:
        return False
    low = name.strip().lower()
    if any(a in low for a in _DEFAULT_ALIASES):
        return True
    if idx is not None:
        try:
            import sounddevice as sd
            eid, dflt = _output_endpoint_id(sd, idx), default_device_id(0, role=1)
            if _is_endpoint_id(eid) and _is_endpoint_id(dflt):
                return _same_key(eid, dflt)
        except Exception:
            pass
    return same_device(name, default_output_name() if default_name is None else default_name)


def _wasapi_output(sd, full):
    """完整名稱 → 同一顆裝置的 WASAPI 播放編號；名稱要完全一樣、而且只有一顆（兩顆同名分不出來就不猜）。沒有回 None。

    🔴 口譯播放斷掉後重開用這個，不用原本的 MME 編號：PortAudio 的 MME 編號是「開程式那一刻 Windows 的第幾顆」，
       拔插之後順序會變（2026-09-26 筆電：拔掉耳麥時喇叭從第 2 顆變第 1 顆），拿舊編號重開可能開到別顆。
       WASAPI 編號綁的是裝置本身（同一天：麥克風拔插後用舊的 WASAPI 編號重開，接回的就是同一支）。
    """
    if not full:
        return None
    try:
        api = next(i for i, a in enumerate(sd.query_hostapis()) if a["name"] == "Windows WASAPI")
        hits = [i for i, d in enumerate(sd.query_devices())
                if d["hostapi"] == api and d.get("max_output_channels", 0) > 0 and _same_key(d["name"], full)]
    except Exception:
        return None
    return hits[0] if len(hits) == 1 else None


def _wasapi_twin(sd, idx):
    """這顆播放裝置（任何一種編號）在 WASAPI 底下的編號，認端點 ID（V1.31）；查不到回 None（呼叫端再用名稱找）。

    🔴 以前用「登錄檔組出來的名稱」去 WASAPI 清單找同名的，名稱寫法兩邊不一樣的電腦就找不到，
       口譯斷掉後沒辦法自動接回（09-28 同事的 ASUS 就是兩邊差一格空白）。MME 編號 → 端點 ID 是直接問 Windows 的。
    """
    try:
        api = next(i for i, a in enumerate(sd.query_hostapis()) if a["name"] == "Windows WASAPI")
        if sd.query_devices(idx)["hostapi"] == api:
            return idx
        eid = _output_endpoint_id(sd, idx)
        if not eid:
            return None
        hits = [i for i, d in enumerate(sd.query_devices())
                if d["hostapi"] == api and d.get("max_output_channels", 0) > 0 and _same_key(wasapi_endpoint_id(sd, i), eid)]
    except Exception:
        return None
    return hits[0] if len(hits) == 1 else None


def _output_endpoint_id(sd, idx):
    """sounddevice 的播放裝置編號 → Windows 端點 ID（WASAPI 直接問 PortAudio；MME 問 Windows，見 mme_endpoint_map）。
    查不到（DirectSound 等、或這台問不到）回 None，呼叫端退回比名稱。"""
    try:
        if idx is None:
            return None
        if sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"] == "Windows WASAPI":
            eid = wasapi_endpoint_id(sd, idx)
        else:
            eid = next((e for e, i in mme_endpoint_map().items() if i == idx), None)
        return eid if _is_endpoint_id(eid) else None      # 只認格式正確的端點 ID，其他一律當作查不到
    except Exception:
        return None


def _full_output_name(sd, idx, name):
    """這顆播放裝置在 Windows 的完整名稱（＝WASAPI 裡的名稱）。MME 會把名稱截成 31 字，截過的就問 Windows 它是哪個端點。"""
    try:
        if sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"] == "Windows WASAPI":
            return name
        eid = next((e for e, i in mme_endpoint_map().items() if i == idx), None)
        if eid:
            import _audioroute
            full = _audioroute.endpoint_full_name(eid)
            if full:
                return full
    except Exception:
        pass
    return name if name and len(name.strip()) < 31 else None


class Speaker:
    """把伺服器回傳的翻譯語音播出去（Live API 的輸出固定 24kHz、單聲道、int16 PCM）。

    🔴 播放一定要另開執行緒：sounddevice 的 write() 是阻塞的、照真實時間走。
       直接寫在 asyncio 的收訊迴圈裡，整條連線會被聲音卡住，字幕也會跟著停。
    🔴 佇列一定要有上限。伺服器偶爾會一次吐一大段，沒有上限就會越落後越多
       （畫面已經翻到下一段、耳朵還在聽三分鐘前那句），記憶體也一路長。
       滿了就丟最舊的：口譯寧可少半句，也不要整場延遲。
    🔴 開不起來不可以讓字幕跟著死。沒有播放裝置、裝置被別的程式獨佔、取樣率不支援
       都會丟例外 —— 這裡一律收下來、把 ok 設成 False，呼叫端照樣跑字幕。
    🔴 2026-09-26 筆電實測（V1.28，使用者回報「拔插耳麥之後只剩字幕、沒有口譯」）：口譯送到筆電喇叭（MME）時，
       拔掉耳麥的那一刻——喇叭本身沒被拔——write() 先報 `MME error 6: There is no driver installed`，
       再下一次 write() 就卡在 PortAudio 裡永遠不回來，插回耳麥也不會恢復。以前這裡把錯誤吞掉、沒有重開：
       字幕照常、口譯整場消失、畫面一個字都沒講（重現與量測在 tio-lvt-test-0926\\spk_unplug）。
       現在：寫入出錯、或卡住超過 STALL 秒，就換一條新的串流接著播（重開走 WASAPI，見 _wasapi_output），
       畫面講「斷了／接回來了」。卡住的舊串流留著不碰（關它會當機，見 close）。
    """

    RECV_SR = 24000        # Live API 輸出取樣率，規格固定（不要從回應內容猜）
    # 🔴 一次最多寫 0.1 秒：收到「停止」時，播放執行緒才能在 0.1 秒內自己停下來（見 close）
    SLICE = RECV_SR * 2 // 10
    STALL = 2.0            # 一次只寫 0.1 秒（正常 0.05 秒內回來），超過這麼久沒回來＝卡死了
    RETRY = 1.0            # 接不回來時，每隔幾秒再試一次
    NAG_AFTER = 10.0       # 超過這麼久還接不回來，再講一次
    # 接回來不到這麼久又斷＝一直斷斷續續：放慢重試、訊息只講第一次（V1.28 審查 #6）。
    # 🔴 不可以設太長：09-27 真機，人正常拔插時「接回來到下一次斷」最短 3.7 秒（四輪 13 次，3.7～27 秒）——
    #    第一版設 5 秒，正常插回就被當成「斷斷續續」：不講話、還多等 1 秒。一寫就錯的裝置（審查 t4）是 0.3 秒內斷。
    FLAP = 1.5
    # 🔴 第一條串流照舊走 MME、不改走 WASAPI：2026-09-26 同一台實測，一開始就走 WASAPI 的串流在耳麥每一次拔、插時
    #    一樣報 AUDCLNT_E_DEVICE_INVALIDATED（4/4），恢復時間也一樣（約 2 秒）——改了沒好處，只多一個變數。

    def __init__(self, device=None, say=print, max_lag=6.0):
        self.say = say
        self.ok = False
        self.name = None
        self.dropped_bytes = 0
        self.played_bytes = 0
        self.outages = 0           # 中途斷過幾次
        self._max_bytes = int(max_lag * self.RECV_SR * 2)
        self._buf = collections.deque()
        self._bytes = 0
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._stream = None
        self._thread = None
        self._gen = 0              # 現在是第幾條串流；換一條就 +1，舊的播放執行緒看到不一樣就自己結束
        self._busy = {}            # {第幾條: 這次 write() 開始的時間}：一直沒回來＝卡死了（各條只清自己那一格）
        self._broken = -1          # 寫入出錯的是第幾條
        self._dead = []            # 死掉的串流：不可以再碰，結束時也不可以關（見 close）
        self._retry = []           # 斷掉之後重開要試的 [(編號, 走 WASAPI?)]；空的＝沒辦法自動重接（見 _warn_once）
        self._full = None          # 裝置的完整名稱（MME 會截成 31 字）
        self._life = threading.Lock()   # 看門狗換線 ↔ close()：同一把鎖（close 才不會 join 到還沒 start 的執行緒）
        self._carry = b""          # 奇數長度多出來的半個樣本，留給下一塊（見 play）
        self._opened = 0.0         # 現在這一條是幾點開的（判斷「一直斷斷續續」）
        self._flaps = 0            # 連續幾次「接回來不到 FLAP 秒又斷」
        self._warned = False       # 沒辦法自動重接的裝置出事：只講一次
        try:
            import sounddevice as sd
            idx, self.name = resolve_output_device(device)
            # 🔴 device=None＝交給系統預設。PortAudio 的「預設播放裝置」其實是**開程式那一刻** Windows 預設的那一顆實體裝置
            #    （MME 的位置），不是會跟著換的「音效對應表」（09-20 真機清單：預設＝KONKA 電視；09-26 本機：預設＝MME 第 4 顆耳機）。
            #    所以重開也要認「那一顆」本身，不可以再拿 device=None（＝舊的 MME 位置）重開（V1.28 審查 #1）。
            real = sd.query_devices(kind="output")["index"] if idx is None else idx
            # 🔴 找「同一顆」會呼叫 PortAudio 手上的裝置物件（wasapi_endpoint_id）：功能 6 這時麥克風那一路可能正在重抓裝置清單
            #    （_terminate 會把那些物件放掉），要跟它拿同一把鎖（V1.31 審查 #4）
            with _sd_lock:
                self._full = _full_output_name(sd, real, self.name)
                twin = _wasapi_twin(sd, real)
                if twin is None:
                    twin = _wasapi_output(sd, self._full)
            self._retry = [(twin, True)] if twin is not None else []
            self._stream = self._open(sd, idx, False)
            self._opened = time.monotonic()
        except Exception as e:
            self.say(f"{YEL}  ⚠ 翻譯語音播不出來：{e}{RESET}")
            self.say(f"{DIM}     字幕不受影響，會照常顯示。{RESET}")
            return
        self.ok = True
        self._thread = threading.Thread(target=self._run, args=(0, self._stream), daemon=True)
        self._thread.start()
        threading.Thread(target=self._watch, daemon=True).start()
        keep_open(self)            # V1.33：例外跳出時由 main() 的 close_open() 關好

    def _open(self, sd, idx, wasapi):
        # RawOutputStream 直接吃 bytes，省掉 numpy 轉換（這個檔不該相依 numpy）
        # WASAPI 不吃 24kHz（-9997），要請 Windows 自己轉取樣率（auto_convert）；MME 照舊、不帶任何設定。
        global _sd_outputs_open
        extra = sd.WasapiSettings(auto_convert=True) if wasapi else None
        with _sd_lock:                 # 不可以跟麥克風看門狗重抓裝置清單同時發生（見 capture_mic）
            s = sd.RawOutputStream(samplerate=self.RECV_SR, channels=1, dtype="int16",
                                   blocksize=1024, device=idx, extra_settings=extra)
            try:
                s.start()
            except Exception:
                s.close()              # 還沒寫過，可以安全關掉
                raise
            _sd_outputs_open += 1      # 開著的時候，麥克風看門狗不可以重新初始化 PortAudio
        return s

    def _run(self, gen, stream, delay=0.0):
        if stream is None:             # 斷掉之後的新一條：在這條執行緒裡開
            stream = self._reopen(gen, delay)
            if stream is None:
                return
        while not self._stop.is_set() and gen == self._gen:
            with self._cv:
                while not self._buf and not self._stop.is_set() and gen == self._gen:
                    self._cv.wait(0.2)
                if self._stop.is_set() or gen != self._gen:
                    break
                pcm = self._buf.popleft()
                self._bytes -= len(pcm)
            for i in range(0, len(pcm), self.SLICE):
                if self._stop.is_set() or gen != self._gen:
                    return
                piece = pcm[i:i + self.SLICE]
                self._busy[gen] = time.monotonic()
                try:
                    stream.write(piece)
                except Exception:
                    # 播放失敗不值得中斷會議，字幕還在跑。
                    if not self._retry:
                        # 沒有同一顆的 WASAPI 可以換（只有 MME 有、或兩顆同名）：照 V1.27 丟掉這一段、下一段再試
                        # （裝置自己好了就繼續播），只多講一聲——不可以比 V1.27 更差（V1.28 審查 #4）
                        self._warn_once()
                        break
                    # 這一條不再寫（再寫就會卡死在 PortAudio 裡），交給 _watch 換一條。
                    # 🔴 只有現役那一條可以報：卡死很久的舊一條晚一步帶著錯誤回來，會把新那條的「斷了」蓋掉（V1.28 審查 #2）
                    if gen == self._gen:
                        self._broken = gen
                    return
                finally:
                    self._busy.pop(gen, None)
                self.played_bytes += len(piece)   # 診斷用：真的寫進裝置的量

    def _warn_once(self):
        if not self._warned:
            self._warned = True
            self.say(f"{CLR_LINE}\n{YEL}  ⚠ 口譯語音出了問題（播放裝置可能有變動，例如耳麥被拔插），這顆裝置沒辦法自動重新接上。{RESET}\n"
                     f"{DIM}     字幕照常。如果之後一直聽不到口譯：按 Ctrl+C 結束，再回選單選 6。{RESET}")

    def _watch(self):
        """看門狗：播放串流出錯或卡死 → 換一條新的，畫面講一聲。"""
        while not self._stop.wait(0.2):
            gen = self._gen
            b = self._busy.get(gen)
            stuck = b is not None and time.monotonic() - b > self.STALL
            if not self._retry:
                if stuck:
                    self._warn_once()   # 沒辦法換：不丟下它（它可能自己好，V1.27 就是這樣），講一聲就好
                continue
            if not stuck and self._broken != gen:
                continue
            with self._life:
                if self._stop.is_set():
                    return
                # 接回來不到 FLAP 秒又斷＝一直斷斷續續：重試越放越慢（0→1→3→7→15→30 秒），訊息只講第一次（V1.28 審查 #6）
                self._flaps = self._flaps + 1 if self.outages and time.monotonic() - self._opened < self.FLAP else 0
                self.outages += 1
                if self._stream is not None:
                    self._dead.append(self._stream)   # 不關：卡住的執行緒可能還在裡面（見 close）
                self._stream = None
                self._gen = gen + 1
                with self._cv:
                    self._cv.notify_all()              # 叫醒沒卡住的舊播放執行緒，讓它自己結束
                if self._flaps == 0:
                    self.say(f"{CLR_LINE}\n{YEL}  ⚠ 口譯語音斷了（播放裝置有變動，例如耳麥被拔插）——正在重新接上，接好會告訴你。{RESET}\n"
                             f"{DIM}     字幕照常；這段時間的口譯聽不到。{RESET}")
                elif self._flaps == 3:
                    self.say(f"{CLR_LINE}\n{YEL}  ⚠ 口譯語音一直斷斷續續（播放裝置一直有變動？例如耳麥插頭鬆了）——會放慢重新接上的速度。{RESET}\n"
                             f"{DIM}     字幕照常。插頭插緊，或按 Ctrl+C 結束後回選單改用別顆。{RESET}")
                wait = min(2 ** self._flaps - 1, 30) * self.RETRY      # RETRY＝1 秒：0、1、3、7、15、30 秒
                t = threading.Thread(target=self._run, args=(self._gen, None, wait), daemon=True)
                t.start()                              # 先 start 完才讓 close() 看得到（見 close）
                self._thread = t

    def _reopen(self, gen, delay=0.0):
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)   # WASAPI 要「開它的那條執行緒」有 COM（見 capture_mic 的說明）
        except Exception:
            pass
        import sounddevice as sd
        shown = self._full or self.name
        if delay:
            self._stop.wait(delay)
        t0, nagged = time.monotonic(), False
        while not self._stop.is_set() and gen == self._gen:
            for i, wasapi in self._retry:
                try:
                    s = self._open(sd, i, wasapi)
                except Exception:
                    continue
                with self._cv:     # 斷掉這段排著的舊語音不播了：接回來從現在開始，不要一路落後好幾秒
                    self.dropped_bytes += self._bytes
                    self._buf.clear()
                    self._bytes = 0
                self._stream = s
                self._opened = time.monotonic()
                if self._flaps == 0 and not self._stop.is_set():   # 收尾中才接上就不講了（不然會印在結尾統計後面）
                    self.say(f"{CLR_LINE}\n{GRN}  ✓ 口譯語音接回來了：{shown}{RESET}\n")
                return s
            if not nagged and time.monotonic() - t0 >= self.NAG_AFTER:
                nagged = True
                self.say(f"{CLR_LINE}\n{YEL}  ⚠ 口譯語音還接不回來（「{shown}」被拔掉了嗎？）——接上就會自動恢復，字幕照常。{RESET}\n"
                         f"{DIM}     要改用別顆：按 Ctrl+C 結束，再回選單選 6。{RESET}")
            self._stop.wait(self.RETRY)
        return None

    def play(self, pcm):
        if not self.ok or not pcm:
            return
        with self._cv:
            # int16：奇數長度多出來的半個樣本留給下一塊。sounddevice 的 write() 對奇數長度會丟 ValueError，
            # V1.28 會把它當成「裝置斷了」去換線（V1.28 審查 #5）。
            pcm = self._carry + bytes(pcm)
            self._carry = b""
            if len(pcm) % 2:
                pcm, self._carry = pcm[:-1], pcm[-1:]
            if not pcm:
                return
            self._buf.append(pcm)
            self._bytes += len(pcm)
            while self._bytes > self._max_bytes and len(self._buf) > 1:
                old = self._buf.popleft()
                self._bytes -= len(old)
                self.dropped_bytes += len(old)
            self._cv.notify()

    def flush(self):
        """把還沒播的丟掉（換線、重連時用，否則會接著播上一段的尾巴）。"""
        with self._cv:
            self._buf.clear()
            self._bytes = 0
            self._carry = b""

    @property
    def lag_seconds(self):
        return self._bytes / (self.RECV_SR * 2)

    @property
    def dropped_seconds(self):
        return self.dropped_bytes / (self.RECV_SR * 2)

    @property
    def played_seconds(self):
        return self.played_bytes / (self.RECV_SR * 2)

    @property
    def recovered(self):
        """中途斷掉之後，最後有沒有接回來（沒斷過也算有）。手上那一條已經報錯、還沒換掉的，不算接回來。"""
        return self._stream is not None and self._broken != self._gen

    def close(self):
        """先讓播放執行緒自己停下來，再關串流。

        🔴 不可以在播放執行緒還在 write() 的時候關串流或重啟聲音元件：PortAudio 會讀到已經
           釋放的緩衝區，整個 python.exe 當掉（0xC0000005，libportaudio64bit.dll）。
           2026-09-19 桌機靜音實測：一段 2 秒時直接關 3/12 當掉；按 X 關視窗時重啟元件
           0.5 秒一段就 4/10、2 秒一段 7/10 當掉。使用者筆電 09-18 23:59 同一個模組當過一次。
        """
        forget_open(self)          # V1.33：放最前面——下面有提早 return 的路（見 close_open）
        # 🔴 跟看門狗換線共用同一把鎖：換到一半時等它換完、而且它看到「要收尾了」就不會再開新的一條。
        #    以前 close() 可能讀到看門狗剛建好、還沒 start 的執行緒 → join() 丟 RuntimeError → 整理好的 .md 沒產生、
        #    Pa_Terminate 也沒取消（V1.28 審查 #3）。
        with self._life:
            self.ok = False
            self._stop.set()
            t = self._thread
        with self._cv:
            self._cv.notify_all()
        if t is not None:
            t.join(timeout=2.0)
        # 手上這一條已經報錯、看門狗還沒換掉（出錯後 0.2 秒內按 Ctrl+C）：當成死掉的，不碰（V1.28 審查 #9）
        stuck = (t is not None and t.is_alive()) or self._broken == self._gen
        if stuck or self._dead:
            # 裝置卡住寫不完（或中途有串流卡死、留著沒關，見 _watch）：
            # sounddevice 在程式結束時還會自己 Pa_Terminate 一次，也要取消，否則當機只是延到最後。
            try:
                import atexit
                import sounddevice as sd
                atexit.unregister(sd._exit_handler)
            except Exception:
                pass
            if stuck:
                return    # 現在這條也還在寫：寧可不關（行程馬上要結束），也不要拆掉它正在用的串流
        global _sd_outputs_open
        try:
            if self._stream is not None:
                with _sd_lock:
                    self._stream.stop(); self._stream.close()
                    _sd_outputs_open = max(0, _sd_outputs_open - 1)
        except Exception:
            pass


class SentenceGate:
    """
    判斷一句已定案的條件（滿足其一）：
      A. 句子結尾標點之後，interim 又長出新的字 → 模型已講到下一句
      B. interim 超過 settle 秒沒變動 → 講者停頓
      C. 累積超過 max_chars → 太長了先送，不要卡住

    🔴 關鍵：interim **不是只往後長，模型會回頭改寫已經出現過的字**。
       實測「…out of one message. No editing software,」被改寫成
       「…out of one message, no editing software, nothing manual.」
       ——句號變逗號、No 變小寫。
       所以「已送出到哪裡」不能用原字串的位置記，一改寫就對不上，
       會被誤判成新段落而**把整段重送一次**（實測 145 句裡 38 句重複）。
       改成記「正規化後（去標點、去空白、轉小寫）的字數」，改寫就傷不到。
    """

    MIN_DEDUP = 24        # 少於這麼多正規化字元就不做去重（8 太短，會誤殺真內容）
    MIN_SEG = 5           # 舊暫定稿少於這麼多正規化字元，不判斷「換新段」（見 _new_segment）
    NEW_SEG = 1 / 3       # 舊暫定稿留在新稿裡的比例低於這個 → 換新段（實測改寫 ≥0.5、換段 ≤0.06）
    DOT_WAIT = DOT_WAIT   # 殘句停在「8.」「Mr.」這種還不確定是不是句尾的點：停頓送出前多等到這麼多秒（見 tick）
    # V1.29 ①：殘句只有 1～2 個字、又沒有句尾標點時，停頓送出前多等到 SHORT_WAIT 秒（見 tick／_short）。
    # 🔴 2026-09-27 全線實測（B1 小聲段）：暫定稿長出「我」之後 Google 停了 4.2 秒才接「們希望…」，settle 1.2 秒一到
    #    就把「我」單獨送成一行（「[09:56] 我」＋「[10:05] 們希望…」，「小」＋「聲的測試…」同樣）。一般音量同一處只停 0.5 秒。
    #    筆電 194 份真實字幕檔 5,509 行：沒標點的 1 字行 11、2 字行 62。6 秒＝實測停頓 4.2 秒再留餘裕。
    SHORT_HOLD = 3        # 正規化後少於這麼多字才算「短殘字」
    SHORT_WAIT = 6.0
    FINAL_CHECK_MAX = 400  # V1.36：定稿正規化後超過這麼多字，final_check 就不檢查（見 final_check ③）
    RESEND_WINDOW = 3.0    # V1.36：補送後這麼多秒內，Google 以那句開頭再送才當成重送（見 feed 的 R4）

    def __init__(self, emit, settle=1.2, max_chars=240):
        self.emit = emit
        self.settle = settle
        self.max_chars = max_chars
        self.turn_over = False   # V1.29 ①：這一回合的定稿已經來了（見 turn_done）——短殘字不必再等
        # V1.35（審查 R5）：每一行是第幾回合講的，存檔前更正數字只認那一回合的定稿（見 number_fixes ⑤）。
        #    turn＝現在餵進來的暫定稿屬於第幾回合（會由第幾則定稿收尾，從 0 起算）：呼叫端每收到一則定稿、處理完之後設成「已收到幾則」。
        #    cur_turn＝cur 那段暫定稿是第幾回合餵進來的。emit 回呼裡讀它＝正在送出的這一行屬於哪一回合
        #    （定稿之後才靠停頓送出的、下一回合開始時補送的舊殘句，都還是舊回合的）。只記不影響切句。
        self.turn = 0
        self.cur_turn = 0
        self.cur = ""            # 這段最新的 interim（原字串）
        self.cur_norm = ""       # 它的正規化版
        self.cur_idx = []        # 正規化第 k 個字 → 原字串的第幾格
        self.emitted_norm = ""   # 本段已送出的內容（正規化）
        self.last_change = time.time()
        # 🔴 第二道保險：最近幾則輸出（各自獨立保存，不串成一坨）。
        #    實測 interim 會在「長句」與「短句」之間來回跳，光靠本段前綴追蹤仍會重送。
        self.recent = collections.deque(maxlen=8)
        self.last_closed = True  # 上一則輸出是不是停在句尾標點（見 _emit 的殘渣規則）
        self.last_tail = ""      # 上一則若以英文 " ' 結尾，記最後兩個字（見 _pending：同一個引號不能再補一次）
        self.turn_norm = ""      # V1.36：上一則定稿之後送出的行（正規化、接成一串），見 final_check
        self.turn_seen = collections.deque(maxlen=64)   # V1.36：上一則定稿之後餵進來的暫定稿（正規化）
        self.turn_max = 0        # V1.36：其中最長的有幾個字
        self.rescued = ""        # V1.36：final_check 剛補送的那句（正規化），見 feed 的 R4
        self.rescued_at = 0.0    # 　　　 補送的時間

    @staticmethod
    def _norm_map(text):
        """去標點空白、轉小寫，並記錄每個保留字元在原字串的位置。"""
        chars, idx = [], []
        for i, ch in enumerate(text):
            c = ch.lower()
            if c.isalnum():
                chars.append(c)
                idx.append(i)
        return "".join(chars), idx

    def _pending(self):
        """還沒送出的部分（原字串）。"""
        skip = min(len(self.emitted_norm), len(self.cur_norm))
        if skip >= len(self.cur_idx):
            return "", skip
        start = self.cur_idx[skip]
        # 🔴 cur_idx 只記英數字的位置，開引號／開括號定位不到，不往回補就會被跳過。
        #    只在「這一段還沒送過」或「上一則停在句尾」時補：上一則若是停頓時整段送出、剛好以「結尾，
        #    那個「已經送過了，再補會重複。
        if skip == 0 or self.last_closed:
            while start > 0 and self._is_opener(self.cur, start - 1):
                # 🔴 上一則已經把這個 " 當收引號送出去了（暫定稿先停在「。"」、下一筆才在後面長出字），
                #    不能再當開引號補一次（2026-09-19 審查：否則同一個引號送兩次）
                #    比「上一則結尾那串標點裡有幾個同樣的引號」：句號被改成逗號（「好。"」→「好，"」）時只比最後兩個字
                #    會對不上而再送一次（2026-09-19 第二次審查）
                q = self.cur[start - 1]
                if (skip and q in self.last_tail
                        and self.cur[self.cur_idx[skip - 1] + 1:start - 1].count(q) < self.last_tail.count(q)):
                    break
                start -= 1
        return self.cur[start:], skip

    @staticmethod
    def _is_opener(text, k):
        c = text[k]
        # 英文的 " ' 前後引號同一個字：後面緊接著字才當開引號（「他走了。"停下來"」的第一個 "）。
        # 🔴 不要再加「前面要是空白或句尾標點」：收括號、破折號、開括號後面的開引號會被丟掉
        #    （「」"走」「("Stop」，2026-09-19 審查）；已經送過的那一個由 last_tail 擋。
        return c in SENT_OPEN or (c in "\"'" and k + 1 < len(text) and text[k + 1].isalnum())

    @staticmethod
    def _is_closer(text, j):
        c = text[j]
        # 英文的 " ' 後面緊接著字（含中文字）時，是下一句的開引號，不能切進上一句
        return c in SENT_CLOSE and not (c in "\"'" and j + 1 < len(text) and text[j + 1].isalnum())

    def feed(self, text):
        if not text:
            return
        tn, tidx = self._norm_map(text)
        if not tn:
            return      # 只有標點／空白的暫定稿：不能拿它覆寫 cur，不然還沒送出的字會被無聲抹掉
        if not self.turn_seen or self.turn_seen[-1] != tn:      # live_bilingual_hq 同一則暫定稿會重複餵
            self.turn_seen.append(tn)
        self.turn_max = max(self.turn_max, len(tn))

        # V1.29 ①：手上壓著的短殘字（見 tick），V1.28 在 settle 秒後就會送出。新來的暫定稿如果不是接著它長
        #    （換成別的字，或這一回合的定稿已經來過＝下一回合開始了），就照 V1.28 的結果先把它送出去，免得被覆蓋掉
        #    （短殘字不到 MIN_SEG，不會被當成換段補送）；接著它長的（「我」→「我們希望…」）就不送，跟後面合成一行。
        # ⛔ 不要在「定稿來過」之後把這一段歸零（當成新回合重新比前綴）。V1.29 審查試過兩種寫法：只清已送出游標
        #    → 上一回合整段再送一次；連暫定稿一起清 → 43 份真實紀錄裡 3 份多送 6 行、整句重複 2→3 處——
        #    Google 在定稿之後還會再送含上一回合尾巴的暫定稿。代價（已知、V1.28 就有）：下一回合剛好用同一個字開頭時
        #    （「好。」→「好的，我們開始吧。」）會被當成接著長，存成「好」＋「的，我們開始吧。」。
        if self._short() and (self.turn_over or (time.time() - self.last_change > self.settle
                                                 and not tn.startswith(self.cur_norm))):
            self.flush()
        # V1.36（待辦 13）：上一回合的定稿已經到了（turn 往前走）、新的暫定稿跟手上那句幾乎沒有共同的字
        #    （舊稿留在新稿裡不到 NEW_SEG，跟 _new_segment 同一套＝下一位重新開口，不是同一段話接著長或改寫）
        #    → 先把手上那句送出。帶句號的短句（「我附議。」）不到 MIN_SEG、也不算短殘字，以前會被下一位的開口蓋掉。
        #    「≤」：3 個字的短句只撞 1 個字（「我附議」→「我同意」）也算換人。接著長、縮回開頭（定稿後再送的短暫定稿）都不送。
        # 🔴 V1.36 審查第二輪：第一版比「共同開頭不到 3/4」——Google 常改寫開頭的字（週↔周、二↔2、洲↔州），
        #    定稿之後再送同一段、又改了 1 個字就被當成換人：送出改寫前的錯數字「30000」、整句重複（diagB4 只差不到 1 個字；
        #    語料裡相鄰暫定稿這種開頭改寫 155 處）。改比「留下幾成」：改寫留得多、換人留得少；送出時舊稿跟新稿本來就差很多，
        #    下面「已送出的部分還接得上嗎」一定判成新段，已送游標不會吃掉新稿的字（第一版 diagB3 那個退步）。
        #    代價（已接受）：下一回合剛好用同樣幾個字開頭（「好，那就這樣。」→「好，那我補充…」留下 2/5）照舊被蓋掉。
        elif (self.turn != self.cur_turn and self.cur_norm and not self.cur_norm.startswith(tn)
              and not tn.startswith(self.cur_norm)):
            sm = difflib.SequenceMatcher(None, self.cur_norm, tn, autojunk=False)
            if sum(b.size for b in sm.get_matching_blocks()) <= len(self.cur_norm) * self.NEW_SEG:
                self.flush()
        self.turn_over = False
        # V1.36 審查第二輪（R4）：final_check 剛補送了一句、Google 接著又把同一句當暫定稿送來、後面接新的話
        #    （「所以不會影響其他的計劃，我們繼續。」）→ 補送過的那一截當成已經送過，只送多出來的；不然同一句會出現兩次。
        #    手上還沒送出、又不是這句開頭的舊殘句（聽錯的「說以」）照常先送。
        # 🔴 審查第三輪：只認「完整以補送那句開頭」、補送後 RESEND_WINDOW 秒內、補送那句至少 4 個字——第二輪也認「補送那句的
        #    任何開頭」，下一位開口第一則暫定稿常常只有 1～2 個字（語料 57%），剛好對上就被吃掉：補送「沒問題。」之後下一位說
        #    「沒有意見。」存成「有意見。」、「不同意」變「同意」，意思整個反過來。還在長的再送（「所以不會」）不必另外處理：
        #    它長過補送那句之前通常還沒被停頓送出，長過去時上面這條會把它整截當成已送。
        if (self.rescued and tn.startswith(self.rescued) and not self.cur_norm.startswith(self.rescued)
                and time.time() - self.rescued_at <= self.RESEND_WINDOW):
            if not self.rescued.startswith(self.cur_norm):
                old_pending, old_skip = self._pending()
                if old_pending.strip():
                    self._emit(old_pending, old_skip)
            self.emitted_norm, self.rescued = self.rescued, ""

        # 已送出的部分還接得上嗎？（比正規化後的共同前綴，容許標點/大小寫被改寫）
        en = self.emitted_norm
        cp = 0
        while cp < min(len(tn), len(en)) and tn[cp] == en[cp]:
            cp += 1
        if (en and cp < len(en) * 0.75) or (not en and self._new_segment(tn)):
            # 差太多 → 真的是新段落。舊段落還沒送出的殘句要先補送，不然會掉字。
            old_pending, old_skip = self._pending()
            if old_pending.strip():
                self._emit(old_pending, old_skip)
            en = self.emitted_norm = ""

        if text != self.cur:
            # V1.36 審查第二輪：一字不差重餵（live_bilingual_hq 定稿之後常再送同一則）還是上一回合的話，不改它的回合——
            #    改了會讓下一位真的開口時認不出換回合（上面那條），存檔前更正數字也會認錯回合。
            #    🔴 審查第三輪：比原字串，不比正規化（去掉標點）的——下一位的暫定稿只多一個句號也會被當成「同一則」而留在
            #    上一回合，存檔前更正數字就拿上一位的定稿去改這一行。
            self.cur_turn = self.turn
        self.cur, self.cur_norm, self.cur_idx = text, tn, tidx
        self.last_change = time.time()

        pending, skip = self._pending()
        if not pending.strip():
            return

        # 條件 A（句尾標點後面緊跟的收引號／收括號算這一句的）
        # 🔴 切句的時機跟以前一樣：句尾標點後面有任何字（收引號也算）就切。不要改成「收引號後面還要有字」——
        #    多等的那段時間，下一段剛好以同樣的字開頭時會被當成「縮回開頭」而整句覆蓋掉（2026-09-19 合成串流：
        #    加引號後遺失 639→1002 字）。
        cut = 0
        for i, ch in enumerate(pending):
            if ch in SENT_END and pending[i + 1:].strip():
                # 🔴 2026-09-25（使用者截圖：體操分數 8.933 被切成「8.」「933 以及 bonus 0.」「1 分數來到了 15.」）：
                #    小數點不是句號。暫定稿會先長成「拿到了 8.」再長成「8.9」「8.933」，舊寫法在「8.9」那一刻就切下去
                #    （桌面 09-23 測試檔 6 處）。V1.20 起稱謂也一樣：「Mr.｜Kuo」「Dr.｜Chen」不切（見 dot_joins_next）。
                #    講者停在「8.」「Mr.」後面頓一下的情況，由 tick() 多等一下處理（見 DOT_WAIT）。
                if ch == "." and dot_joins_next(pending[:i], pending[i + 1:].lstrip()):
                    continue
                j = i + 1
                while j < len(pending) and self._is_closer(pending, j):
                    j += 1
                cut = j
        if cut:
            self._emit(pending[:cut], skip)
            return

        # 條件 C：真的太長才硬切（實測真實句子最長 218 字，240 幾乎不會觸發）。
        # 🔴 優先切在子句邊界（逗號/分號/冒號），切在介系詞中間會產生
        #    「…until basically this」／「month.」這種殘句，下半句翻出來就是「個月」。
        if len(pending) >= self.max_chars:
            w = pending[:self.max_chars]
            cut = max(w.rfind("，"), w.rfind(","), w.rfind("；"), w.rfind(";"),
                      w.rfind("："), w.rfind(":"))
            if cut < 40:
                cut = w.rfind(" ")            # 沒有子句邊界才退而求其次找空白
            self._emit(pending[:cut + 1] if cut > 40 else w, skip, fragment=True)

    def _new_segment(self, tn):
        """本段還沒切出任何一句時，新的 interim 是「換了一段」還是「改寫同一段」。

        🔴 B2（2026-09-19 筆電實測）：原本只有本段已送出過句子（emitted_norm 非空）時，才會先補送
           舊的殘句。這一段一句都還沒切出來、模型就換成不相干的新段落（雜音幻聽「我不會。」「喂。」、
           換講者）時，舊的暫定稿會被直接覆蓋——整段沒定稿的字消失（R4：「深耕計畫的期中報告」等
           三句不見；R2c：約 45 個英文字不見）。「準」模式的漏開頭也走這條路。
        🔴 但模型改寫同一段時覆蓋才是對的（「請給」→「請各學院在」、「第三根計劃」→「第深圳計劃的」）。
           分辨法：舊暫定稿依序還有多少字留在新稿裡。筆電真實記錄：改寫 0.5～0.89、換新段 0～0.06，
           門檻取 1/3，兩邊都留足餘裕。
           兩種情況不判成換段：舊稿太短（< MIN_SEG 字：短暫定稿被換掉多半是聽錯重來或雜音幻聽——
           筆電 7 份真實記錄重播，救回的真內容都 ≥5 字，而 4 字的全是弱訊號下幻聽出來的詞彙表用語
           「深耕計畫」，補送只會多雜訊）；新稿是舊稿的開頭（模型把暫定稿縮回去，之後會再長回來）。
        """
        old = self.cur_norm
        if len(old) < self.MIN_SEG or old.startswith(tn):
            return False
        sm = difflib.SequenceMatcher(None, old, tn, autojunk=False)
        kept = sum(b.size for b in sm.get_matching_blocks())
        return kept / len(old) < self.NEW_SEG

    def tick(self):
        """條件 B：講者停頓，把手上的殘句送出。"""
        wait = self.settle
        # 🔴 2026-09-25（使用者核准）：殘句停在「數字.」或「稱謂.」時多等到 DOT_WAIT 秒 —— 講者常在「八點」「Mister」
        #    後面頓一下才講下去，settle 一到就送會切成「…拿到了 8.」「933 …」。
        #    代價（已說明）：真的以數字結尾的句子（「目標是 8.」）要晚約 2 秒才出現。收尾的 flush() 不等。
        tail = self._pending()[0].rstrip()
        if tail.endswith(".") and dot_may_join(tail[:-1]):
            wait = max(wait, self.DOT_WAIT)
        if not self.turn_over and self._short():
            wait = max(wait, self.SHORT_WAIT)      # V1.29 ①：見 SHORT_WAIT
        if time.time() - self.last_change <= wait:
            return
        self.flush()

    def _short(self):
        """V1.29 ①：手上還沒送出的殘句是不是「1～2 個字、沒有句尾標點」的短殘字。"""
        tail = self._pending()[0].strip()
        if not tail or tail.rstrip(SENT_CLOSE)[-1:] in SENT_END:
            return False
        return len(self._norm_map(tail)[0]) < self.SHORT_HOLD

    def turn_done(self):
        """V1.29 ①：這一回合的定稿（input_transcription）來了——手上的短殘字不會再長了，照一般的停頓送出。
        呼叫端（live_caption／live_bilingual_hq）在處理完定稿之後呼叫。"""
        self.turn_over = True

    def final_check(self, final):
        """V1.36（待辦 13）：定稿的字，在「上一則定稿之後送出的行＋最近 8 行＋手上那句」裡找不到一半，而且
        （a）它在上一則定稿之後的暫定稿裡出現過（被蓋掉了），或（b）那段時間的暫定稿最長還不到它的一半（暫定稿根本沒聽到）
        → 定稿整句補送一行。
        🔴 2026-10-03 筆電 111 份真實串流重播：暫定稿「我附議。」之後，下一位的「我同意。」比「我附議。」的定稿先到——
           同一回合裡被蓋掉（feed 的換回合規則接不到，走 a）；只來一則聽錯的暫定稿「說以」、定稿才是「所以不會影響其他的計劃。」（走 b）。
           手上那句整句都在定稿裡就不再另送（免得重複）；不是的（「我同意。」）照常送。
        🔴 只看「找不到一半」不夠（第一版）：暫定稿「點五。」、定稿「煙霧。」是同一段聲音的兩種聽法——暫定稿那邊已經有
           差不多長的版本，補送會多一行聽錯的字（diagB1）。日文暫定稿配中文定稿那種（同長、內容不同）也照舊不補。
        🔴 要連「最近 8 行」一起比：定稿常常落後，兩句的暫定稿都送出了、兩則定稿才陸續到，只比上一則定稿之後的會把第二句重送。
        🔴 V1.36 審查第二輪：①（b）的「那段時間的暫定稿」不可以每則定稿就整個清空——上一則定稿晚到時，下一句的暫定稿已經餵進來，
           清掉會讓下一則定稿以為「暫定稿沒聽到」，把同一段聲音的另一種聽法補進來（「點五。」之後才到的定稿害「煙霧。」被補送）；
           只清掉屬於這則定稿的（開頭 8 個字在定稿裡）。②手上那句只有「是定稿的開頭」或「3 個字以上、整句在定稿裡」才算定稿已經包含
           ——只看「在裡面」會把下一位開頭的「我」當成定稿的一部分吃掉。③定稿正規化超過 FINAL_CHECK_MAX 字不檢查、
           比對的範圍限縮到最近約 3,000 字：要救的是短句；審查量到很長的英文回合一次比對要 3～5 秒，會卡住畫面。
        呼叫端每收到一則有字的定稿都呼叫（在 gate.turn 往前走之前；final_extend 之後）。"""
        fn = self._norm_map(final or "")[0]
        pn = self._norm_map(self._pending()[0])[0]
        self.rescued = ""
        if 2 <= len(fn) <= self.FINAL_CHECK_MAX:
            have = "".join(self.recent)[-1500:] + self.turn_norm[-1500:] + pn
            got = len(fn) if fn in have else \
                sum(b.size for b in difflib.SequenceMatcher(None, fn, have, autojunk=False).get_matching_blocks())
            if got < len(fn) * 0.5 and (any(fn in x for x in self.turn_seen) or self.turn_max < len(fn) * 0.5):
                if pn and (fn.startswith(pn) or (len(pn) >= 3 and pn in fn)):
                    self.emitted_norm = self.cur_norm
                text = " ".join(final.split())
                self.recent.append(fn)
                if len(fn) >= 4:                   # 見 feed 的 R4（太短的句子撞開頭的機會太大，不認再送）
                    self.rescued, self.rescued_at = fn, time.time()
                self.last_closed = text.rstrip(SENT_CLOSE)[-1:] in SENT_END
                self.emit(tidy_cjk(text), False)
        # 只留「最後一則屬於這則定稿的暫定稿」之後的（下一句的暫定稿一定排在這句後面）；更早、對不上任何定稿的
        # 聽錯殘稿（「第2暗示…」，定稿是「第2案是…」）一起清掉，不然它會一直把（b）擋住（審查第二輪修正時自己重播抓到）。
        # 「屬於」＝開頭或結尾 8 個字在定稿裡（審查第三輪：定稿把開頭改掉——去掉「那我們」、Miss→Ms.——時只比開頭會整串對不上）
        last = max((i for i, x in enumerate(self.turn_seen) if x[:8] in fn or x[-8:] in fn), default=-1)
        keep = list(self.turn_seen)[last + 1:]
        self.turn_seen.clear()
        self.turn_seen.extend(keep)
        self.turn_max = max((len(x) for x in keep), default=0)
        self.turn_norm = ""

    def pending_text(self):
        """V1.29 ③：還沒送出的部分（原字串）。畫面上的灰字只印這一截，已經鎖定成白字的不再重複印。"""
        return self._pending()[0]

    def flush(self):
        """收尾用：不管停頓多久，把手上還沒送出的殘句送出。

        🔴 沒有這一段，使用者按 Ctrl+C 的當下正在講的那一句會整句消失
           （tick 要等 settle 秒才動作，收尾時不保證已經等到）。
        """
        pending, skip = self._pending()
        if pending.strip():
            self._emit(pending, skip)

    def _emit(self, s, skip, fragment=False):
        s = s.strip()
        if not s:
            return
        sn, sidx = self._norm_map(s)
        # 用「正規化字數」推進游標，模型之後再怎麼改標點都對得上
        self.emitted_norm = self.cur_norm[:skip + len(sn)]
        # 上一則若以英文 " ' 結尾，記下最後一個英數字之後的整串標點（見 _pending）。🔴 要在任何 return 之前更新：
        #    被去重擋下的那一則，它的引號也已經算「送過」了，不更新會把下一句真的開引號吃掉（同上審查）
        _i = len(s)
        while _i > 0 and not s[_i - 1].isalnum():
            _i -= 1
        self.last_tail = s[_i:] if s[-1:] in ("\"", "'") else ""

        if not sn:
            return

        # 🔴 去重保險（第二版）。第一版把整場的正規化文字串成「一大坨沒有分隔的字串」，
        #    再用 `in` 做子字串比對，門檻只有 8 個字元 —— 英文 8 個字元毫無鑑別度，
        #    結果刪掉了真實內容：
        #      「software.」整句被刪（55 秒前另一句裡出現過 software）
        #      「I'll break down 」被截掉（38 秒前講過 I'll break down what）
        #    改法：只跟「最近幾則各自獨立的輸出」比，而且比對整句相等而非子字串；
        #    門檻拉到 MIN_DEDUP 個字元。實測重複的樣態是 96 字元的整段重送，
        #    遠高於門檻，所以擋得住重複又不會誤殺短句。
        if len(sn) >= self.MIN_DEDUP and sn in self.recent:
            return

        # 🔴 recent 要存「完整一句」，不能存截掉前綴後剩下的部分：存截剩的，下一次跟它比時可能
        #    不到 MIN_DEDUP 字而比不到，長句與短句來回跳時整段會再送一次（2026-09-19 審查重現）。
        full_sn = sn
        # 前綴保險：只跟「上一則」比（而且要整段對齊開頭），不跟整場比。
        # 這樣才擋得住 interim 長短交替造成的整段重送，又不會誤傷偶然撞詞的句子。
        stripped = False
        if self.recent:
            prev = self.recent[-1]
            k = min(len(sn), len(prev))
            while k >= self.MIN_DEDUP:
                if sn[:k] == prev[-k:]:
                    s = s[sidx[k]:].strip() if k < len(sidx) else ""
                    sn = sn[k:]
                    stripped = True
                    break
                k -= 1
        # 只有「截掉前綴後剩下的殘渣」才丟；正常的短句（例如單字「請」）要留著。
        # 🔴 但上一則如果不是停在句尾標點（換段時被截斷送出的殘句），剩下的短殘字就是它漏掉的
        #    結尾（「…送會計室複」→「核。」），要照送（2026-09-19 審查：5000 組合成串流
        #    有遺失的組數 111→41，沒有任何一組遺失變多；13 份筆電真實記錄 0 差異）。
        #    代價（已接受）：這個字自成一列，原本會接到下一列的字也可能被拆開（「50 萬」→「5」「0 萬」），
        #    準確模式會把它當上一句的接續去翻。13 份真實記錄一次都沒走到這條路。
        if not s or not sn or (stripped and len(sn) < 2 and self.last_closed):
            return

        if stripped and len(sn) < 2:
            # 🔴 1 字殘句：完整句本來就包含上一則的尾巴，拿它取代上一則，不要多佔一格。recent 只有 8 格，
            #    多佔一格會把長稿開頭那一則擠掉，之後整段重送、還會連鎖（2026-09-19 審查重現：多送兩整句）。
            #    代價（已接受）：之後模型若退回到那個截斷稿、又被換段打斷，那一句會整句重送一次——
            #    這條路 6 份真實記錄與 1 萬組合成串流都沒走到，而退回到截斷稿其他長度時舊版本來就會重送。
            self.recent[-1] = full_sn
        else:
            self.recent.append(full_sn)
        self.last_closed = s.rstrip(SENT_CLOSE)[-1:] in SENT_END
        self.turn_norm += sn
        # 🔴 一定要在所有「用索引切字串」的步驟都做完之後才收空白，
        #    不然 sidx 算出來的位置會對不上。
        self.emit(tidy_cjk(s), fragment)


# ─────────────────── 定稿比暫定稿多出來的句尾（V1.26 B2）───────────────────
# 🔴 2026-09-26 實測（tio-lvt-test-0926\runs\diagB1～B5 記下每一則暫定稿／定稿）：一句話的最後幾個字常常**只出現在定稿**
#    （input_transcription），暫定稿停在前一步——「…joint research」→ 定稿「…joint research symposium.」、
#    「12.5%」→「12.5% compared with」。功能 1／3「準」只用暫定稿（定稿不能直接餵斷句器：它跟暫定稿用字不同的地方
#    會被判成新段落而整段重送，實測 145 句重 38 句），所以這幾個字就掉了——正常音量時約 0～4% 的句子。
#    官方文件（ai.google.dev「Live transcription」2026-08-26 版）：暫定稿＝講話中的推測；定稿在停頓／回合結束時送。
#    做法：只拿定稿裡「接在暫定稿結尾之後」的那一截，接回暫定稿後面再餵斷句器——斷句器看到的是同一段的延長，不會重送；
#    對不上（模型改寫太多、定稿屬於別的回合）就不接、維持原樣。5 場真實紀錄：定稿前一定有暫定稿（0 例外），
#    暫定稿結尾在定稿裡找得到 92～96%，其餘就是不接的那幾則。
TAIL_MATCH = 4      # 暫定稿結尾至少要有這麼多個字在定稿裡對得上
TAIL_SAME = 0.6     # 暫定稿跟「定稿到對上那裡」的相似度至少要這麼高，才算同一段
TAIL_MAX = 200      # 接上去的尾巴最多這麼多個字（正規化後）；再長多半不是同一段


def long_interim(s):
    """這則暫定稿正規化後有沒有 TAIL_MATCH 個字以上（V1.35：給 final_extend 的 short_ok 用，呼叫端記「這一回合出現過沒有」）。"""
    return len(SentenceGate._norm_map(s or "")[0]) >= TAIL_MATCH


def final_extend(interim, final, short_ok=True):
    """回傳「暫定稿＋定稿多出來的句尾」給斷句器；定稿沒有多出來、或對不上時回 None。
    short_ok：這一回合從來沒出現過 TAIL_MATCH 個字以上的暫定稿（呼叫端用 long_interim 記）；False 時短暫定稿一律不接。"""
    ni, ii = SentenceGate._norm_map(interim or "")
    nf, fi = SentenceGate._norm_map(final or "")
    # V1.35（待辦 8）：暫定稿不到 TAIL_MATCH 個字時，原本一律不接。🔴 2026-10-03 V1.34 全線實測 X20：Google 最後一則暫定稿
    #    只有「先報告」「沒問題。」，0.15 秒後定稿是「先報告工程進度。」「沒問題，我們會一併列出採購清單。」——後面那截整個沒了
    #    （畫面、存檔都沒有；當輪 110 則定稿 2 則、15 字）。改成：定稿（正規化後）就是以這幾個字開頭時照樣接——同一回合的定稿
    #    從頭講起，開頭一字不差是很強的證據；開頭不同（改寫、換人）一樣不接。
    #    🔴 V1.35 審查：只限「這一回合從頭到尾都是短暫定稿」（short_ok）。同一回合先有長暫定稿、縮回「先報告」才來定稿，
    #       或下一回合的「好」比上一回合的定稿先到，長的那段早就送進斷句器了，再接一次就整句重複（合成序列 S1／S2 重現；
    #       93 份真實串流這種順序 0 次，X20 兩處都是整回合短暫定稿，照接）。
    if 0 < len(ni) < TAIL_MATCH:
        if short_ok and len(nf) > len(ni) and nf.startswith(ni) and len(nf) - len(ni) <= TAIL_MAX:
            return interim[:ii[-1] + 1] + final[fi[len(ni) - 1] + 1:]
        return None
    if len(ni) < TAIL_MATCH or len(nf) <= len(ni) - 2:
        return None
    key = ni[-TAIL_MATCH:]
    # 定稿裡可能不只一處跟暫定稿結尾一樣（「執行率是…、執行率是…」）：挑「定稿到那裡」跟暫定稿最像的那一處，
    # 一樣像才挑位置最接近暫定稿長度的。🔴 不能只看位置：定稿刪掉開頭的贅字（so um…）時，最接近長度的那處
    # 會落在後面重複出現的同一串，中間那段就被吞掉（V1.26 審查 #4）。
    ends = [m.start() + TAIL_MATCH for m in re.finditer(re.escape(key), nf)]
    if not ends:
        return None
    sim = {e: difflib.SequenceMatcher(None, ni, nf[:e], autojunk=False).ratio() for e in ends}
    end = max(ends, key=lambda e: (sim[e], -abs(e - len(ni))))
    if end >= len(nf) or len(nf) - end > TAIL_MAX:
        return None
    if sim[end] < TAIL_SAME:
        return None
    # 暫定稿留到它最後一個字為止，後面接定稿的版本（連標點、空白）：暫定稿結尾的標點要換成定稿的，
    # 不然「12.5%」接「% compared with」會變成「12.5%% compared with」
    return interim[:ii[-1] + 1] + final[fi[end - 1] + 1:]


# ─────────────── 存檔前用 Google 定稿更正「字一樣、只有數字不同」的地方（V1.35，待辦 9）───────────────
# 🔴 2026-10-03 V1.34 全線實測 X18：最後一則暫定稿是「…萬元，執行率 80%」，0.04 秒後的定稿是「…萬元，執行率87.5%。」——
#    字幕與存檔用的是暫定稿，定稿只拿來接句尾（final_extend）與修重複（V1.29 ②），改對的數字就這樣丟了。
#    會議紀錄的數字錯了沒人會發現，但「改錯」比「沒改」更糟（見 V1.29 ② 的教訓），所以條件全部往「不改」收：
#    ① 這一行有數字，而且去掉數字之後還有 NUM_SKEL_MIN 個字以上（太短的句子跟別句巧合相同的機會大）
#    ② 這一行的「骨架」（數字換成 #、去掉標點空白、英文轉小寫）在**整場所有定稿**裡剛好出現一次（同一句話只有一個出處）
#    ③ 對到的那一段數字個數一樣、有沒有 % 一樣；只換值不同的數字（1,300＝1300 不算不同），其餘的字一個都不動
#    寫法不同（三月／3月、八／8）骨架就對不上 → 不動。定稿本身也可能聽錯，但它是 Google 看完整句才給的最終版本。
#    ④ 數字可能被斷在兩行時不動：這一行開頭是數字、上一行結尾也是數字（或「數字.」）；或這一行結尾是數字、下一行開頭也是數字。
#       🔴 第一版拿筆電 93 份真實串流重播抓到：「…分數是 8 .」｜「933 分，比上一次的 8 .」兩行各自對到定稿的 8.933，
#          兩行都被補成 8.933——同一個數字出現兩次（「註冊率是 90%」｜「8%，比去年…」也一樣）。斷開的小數本來只是難看，
#          補錯就變成錯的數字，所以兩行都不碰。
#       🔴 V1.35 審查：「點」「point」「．」也是小數的接續。真實串流 diagB3：「…version 2.」｜「point five of the reporting…」，
#          上一行被補成 2.5、下一行還是 point five（diagC3「執行率是 60%」｜「點五。」同型）。
#    ⑤ 只認這一行「自己那一回合」的定稿（V1.35 審查）：整場定稿裡「別處」剛好有一句同骨架、數字不同的話
#       （表決「贊成 12 票」的定稿寫成國字、下一案「贊成9票」；自己的定稿換線時遺失、20 分鐘後同一句講了新數字），
#       ② 擋不住，正確的數字會被改成別句的。
#       🔴 第一版改成「時間最近、NUM_NEAR_S 秒內」還不夠（複查 R5）：乙沿用甲的句型、講完接著講下去，乙那一行在乙還在講時
#          就切出來了，最近的反而是甲 2 秒前的定稿，乙自己的定稿要等整段講完、又寫成「百分之九十二」→ 乙的 92% 被改成 95%。
#          所以行要帶回合（SentenceGate.cur_turn：第幾則定稿收尾的那一回合），命中的必須就是那一則；那一則沒到（Ctrl+C）就不改。
#          換線時沒等到的那則定稿，由兩支即時程式補一則空的佔住編號（複查 R1'），不然那幾行會被算到下一條連線的第一則。
#          保險：就算回合對上，定稿跟這一行相隔超過 NUM_TURN_MAX_S 也不認（同一條連線內漏定稿，資料裡還沒看過）。
#          沒帶回合的行（舊資料、測試）才退回「時間最近、NUM_NEAR_S 秒內」。
NUM_SKEL_MIN = 6
NUM_NEAR_S = 15.0
NUM_TURN_MAX_S = 60.0
_NUM = re.compile(r"\d+(?:[.,]\d+)*%?")
_NUM_AT_START = re.compile(r"\s*(?:\d|點|．|point)", re.I)
_NUM_AT_END = re.compile(r"(?:\d%?|點|．|point)\s*[.。,，]?\s*$", re.I)


def _split_number(lines, k):
    """第 k 行跟上一行或下一行之間，可能有一個數字被斷開（見上面 ④）。"""
    s = lines[k][1]
    prev_end = k > 0 and _NUM_AT_END.search(lines[k - 1][1])
    next_start = k + 1 < len(lines) and _NUM_AT_START.match(lines[k + 1][1])
    return bool((_NUM_AT_START.match(s) and prev_end) or (_NUM_AT_END.search(s) and next_start))


def _num_skel(s):
    """(骨架, [數字])：骨架＝數字換成 #、只留英數字與中文字（英文小寫）；數字照出現順序。"""
    parts, nums, pos = [], [], 0
    for m in _NUM.finditer(s):
        parts.append(s[pos:m.start()])
        parts.append("\x00")
        nums.append(m.group())
        pos = m.end()
    parts.append(s[pos:])
    skel = "".join("#" if c == "\x00" else c.lower() for c in "".join(parts) if c == "\x00" or c.isalnum())
    return skel, nums


def _num_val(x):
    return unicodedata.normalize("NFKC", x).replace(",", "")      # 全形數字、千分位逗號都算同一個值


def number_fixes(lines, finals):
    """[(秒, 字幕行[, 回合])], [(收到的秒, 定稿字串)]（兩邊同一個起點；回合＝第幾則定稿，從 0 起算）
    → [(第幾行, 新的字幕行, [(舊數字, 新數字)])]，只列真的要改的行（見上面 ①～⑤）。"""
    fsk = [(ft, *_num_skel(f or "")) for ft, f in (finals or [])]      # 不濾空的：回合編號＝這張表的位置
    out = []
    for k, row in enumerate(lines):
        t, s = row[0], row[1]
        own = row[2] if len(row) > 2 else None
        sk, nums = _num_skel(s)
        if not nums or len(sk.replace("#", "")) < NUM_SKEL_MIN or _split_number(lines, k):
            continue
        hits = []
        for j, (_ft, fs, fn) in enumerate(fsk):
            i = fs.find(sk)
            while i >= 0:
                hits.append((j, i))
                i = fs.find(sk, i + 1)
        if len(hits) != 1:
            continue
        j, i = hits[0]
        if own is not None:
            if j != own or abs(fsk[j][0] - t) > NUM_TURN_MAX_S:      # 只認自己那一回合的定稿
                continue
        else:
            dt = abs(fsk[j][0] - t)
            if dt > NUM_NEAR_S or any(abs(ft - t) < dt for ft, _fs, _fn in fsk):     # 有別則定稿比它更近 → 不認
                continue
        _ft, fs, fn = fsk[j]
        got = fn[fs[:i].count("#"):][:len(nums)]
        if len(got) != len(nums) or any(a.endswith("%") != b.endswith("%") for a, b in zip(nums, got)):
            continue
        pairs = [(a, b) for a, b in zip(nums, got) if _num_val(a) != _num_val(b)]
        if not pairs:
            continue
        new, pos = [], 0
        for m, a, b in zip(_NUM.finditer(s), nums, got):
            new += [s[pos:m.start()], b if _num_val(a) != _num_val(b) else a]
            pos = m.end()
        out.append((k, "".join(new) + s[pos:], pairs))
    return out


# ─────────────────── 存檔前修掉「暫定稿自己多吐的重複」（V1.29 ②）───────────────────
# 🔴 2026-09-27 全線實測（功能 1，斷線重連後第一句）：Google 的暫定稿本身就是「剛才安靜了 1 分鐘。 分鐘多，現在繼續測試。」
#    （iit 原文），TIO 照它切句存成「1 分鐘。」＋「分鐘多，…」兩行；同一回合的定稿是對的「一分鐘多，現在繼續測試。」。
#    功能 1 只用暫定稿（定稿不能直接餵斷句器，見 final_extend 上面的說明），畫面已經印出去的收不回來；
#    這裡只在寫 .md／.srt 之前修，而且**只在定稿能證明時**才修：定稿裡有「X＋後面的字」、卻沒有「X＋X」。
#    定稿裡也重複（真的講了兩次，例如「謝謝。謝謝大家」）、或找不到對得上的定稿 → 一律不動。
DUP_MIN, DUP_MAX = 2, 8   # 重複的那一截（正規化後）至少 2 個字、最多看 8 個字
DUP_AFTER = 2             # 重複那截後面至少還要有這麼多字，拿去跟定稿對照（太短的話「在定稿裡找得到」沒有鑑別力）
# V1.29 ⑧：整句重送。🔴 2026-09-27 全線實測 B1：暫定稿「報告主席，學生會 會希望 在」之後 Google 停了 4 秒，settle 1.2 秒先把
#    「報告主席，學生會會希望在」鎖成一行；接著 Google 把它改寫成「學生會 希望在 校園裡…」，跟已送出的共同前綴只剩 7/11
#    （< SentenceGate 的 75%），被當成新段落整句再送一次。定稿是「報告主席，學生會希望在校園裡…」、完全沒有「學生會會」。
RESEND_MIN = 4            # 上一行（正規化）至少這麼多字才看（太短的相似沒有意義）
RESEND_SAME = 0.8         # 上一行 vs 下一行開頭同長那一截的相似度（difflib ratio）至少這麼高，才算「同一句被改寫後重送」
DUP_COVER = 0.6           # 拿來證明的那則定稿，至少要涵蓋上一行這麼多（正規化字數）——同一個回合才算數
# 🔴 第一版只看「那則定稿裡有沒有重複」，重播真實紀錄抓到兩種誤修（09-27）：
#    ① C1：線上的人講「…用了 320萬元」、現場的人接「320 萬元這個數字…」——兩人各講一次，但分屬兩則定稿，
#       各自都「沒有重複」，就被合成「…用了 320萬元這個數字」（少了一個「元」、兩句變一句）→ 加 DUP_COVER
#    ② 09-26 diagB4：「…agrees with the」＋「He thinks…」只因字母「he」一樣就合成「thethinks」→ 英數字的重複要落在完整單字上
# 🔴 V1.29 獨立審查（09-27）又造出 12 種會把「真的講過的話」刪掉或併錯的情境，全部是「兩句其實分屬不同回合」：
#    講者先說「我們不同意這個提案的內容」再改口「我們同意…」（上一行暫定稿有一個錯字）→ 刪掉「不同意」＝意思整個反過來；
#    甲說完「謝謝主席。」、乙接「謝謝主席，接下來…」→ 併成一句、少一次；相隔 3 分鐘各講一次 → 前一行被刪、時間往前挪 3 分鐘。
#    原本的毛病只是「多出重複的字」，修錯卻會刪掉真的講過的話，所以三道防護都往「寧可不修」收：
#    ① 兩行相隔超過 RESEND_GAP 秒不修　② 那則定稿裡，上一行的內容要緊接在「下一行開頭」前面（同一句話）、
#       而且前面不能另外有一份像上一行的字　③ 緊鄰的前一則定稿，結尾不能就是上一行（＝上一個回合真的講過）
RESEND_GAP = 15.0         # 同一回合的改寫、重吐都在幾秒內（真實 B1 相隔 7 秒）
NEAR_COPY = 0.8           # 「另外講過一次」：一段字配得上上一行這麼多，而且集中在不超過上一行兩倍長的範圍


def _cover(na, f):
    """定稿 f（正規化）涵蓋 na 的比例。"""
    if not na:
        return 0.0
    return sum(b.size for b in difflib.SequenceMatcher(None, na, f, autojunk=False).get_matching_blocks()) / len(na)


def _mid_word(s, i):
    """s 的第 i 個字元跟前一個字元是不是同一個英數字單字的一部分（中文字不算）。"""
    return (0 < i < len(s) and s[i - 1].isascii() and s[i - 1].isalnum()
            and s[i].isascii() and s[i].isalnum())


def _near_copy(na, g):
    """g（正規化）裡有沒有「另一份」na：配得上的字 ≥ NEAR_COPY，而且集中在不超過 na 兩倍長的一段裡（不是散在長句裡的巧合）。"""
    if not na or not g:
        return False
    bl = [b for b in difflib.SequenceMatcher(None, na, g, autojunk=False).get_matching_blocks() if b.size]
    return sum(b.size for b in bl) >= NEAR_COPY * len(na) and bl[-1].b + bl[-1].size - bl[0].b <= 2 * len(na)


def _said_before(na, fins, j):
    """緊鄰第 j 則之前的那則定稿，結尾就是上一行（上一個回合真的講過，例如甲說完的「謝謝主席。」）。"""
    return j > 0 and _near_copy(na, fins[j - 1][-(len(na) + 4):])


def _proves_resend(na, nb, fins):
    """⑧ 的證據：有一則定稿有「下一行的開頭」，而且上一行在定稿裡只有這一份——那則定稿裡緊接在前面的那段、
    以及前一則定稿的結尾，都不能另外有一份像上一行的字（講者自己重講、或改口）。"""
    key = nb[:len(na) + 2]
    for j, f in enumerate(fins):
        i = f.find(key)
        if i >= 0 and _cover(na, f) >= DUP_COVER:
            return not (_near_copy(na, f[max(0, i - len(na) - 2):i]) or _said_before(na, fins, j))
    return False


def _proves_join(na, d, after, fins):
    """② 的證據：有一則定稿有「重複那截＋下一行接下去的字」、沒有「那截重複兩次」，上一行的內容就緊接在它前面
    （同一句話），而且前一則定稿的結尾不是上一行。"""
    for j, f in enumerate(fins):
        i = f.find(d + after)
        if (i >= 0 and d + d not in f and _cover(na, f[max(0, i - len(na) - 2):i + len(d)]) >= DUP_COVER
                and not _said_before(na, fins, j)):
            return True
    return False


def repair_boundary_dups(lines, finals):
    """[(秒, 字幕行)], [定稿字串] → (修過的 [(秒, 字幕行)], 修了幾處)。兩種情況，都只在定稿能證明時才修：

    ② 相鄰兩行：上一行的結尾（正規化 2～8 字）＝下一行的開頭，而且有一則定稿裡有「那一截＋下一行接下去的字」、
       沒有「那一截重複兩次」→ 兩行併成一行（時間用上一行的）：上一行去掉句尾標點，接下一行去掉重複那截之後的字。
       上一行結尾是收引號／收括號的不動（併起來會很奇怪）。
    ⑧ 整句重送：上一行沒有句尾標點（是停頓時先鎖的半句），下一行開頭跟它幾乎一樣（相似度 ≥ RESEND_SAME）又比它長，
       而且有一則定稿裡有「下一行的開頭」、**所有**定稿裡都沒有「上一行」那個版本 → 丟掉上一行、下一行接手它的時間。
    兩種都要求：拿來證明的那則定稿同時涵蓋上一行至少 DUP_COVER（同一個回合）；英數字的重複要落在完整單字上。
    V1.29 審查後再加三道（見 RESEND_GAP 上面的說明）：兩行相隔 ≤ RESEND_GAP 秒；那則定稿裡上一行的內容緊接在前、
    前面沒有另一份（見 _proves_resend／_proves_join）；緊鄰的前一則定稿結尾不是上一行（見 _said_before）。"""
    fins = [SentenceGate._norm_map(f)[0] for f in (finals or []) if f]
    rows = [list(x) for x in lines]       # V1.35：行後面多帶的欄位（回合，見 number_fixes）原樣保留；兩行併成一行時跟著上一行
    if not fins or len(rows) < 2:
        return [tuple(x) for x in rows], 0
    out, fixed = [rows[0]], 0
    for row in rows[1:]:
        t, s = row[0], row[1]
        ta, a = out[-1][0], out[-1][1]
        na, ia = SentenceGate._norm_map(a)
        nb, ib = SentenceGate._norm_map(s)
        close = t - ta <= RESEND_GAP                                           # 防護 ①
        if (close and len(na) >= RESEND_MIN and len(nb) > len(na) and a.rstrip()[-1:] not in SENT_END + SENT_CLOSE
                and difflib.SequenceMatcher(None, na, nb[:len(na)], autojunk=False).ratio() >= RESEND_SAME
                and not any(na in f for f in fins)
                and _proves_resend(na, nb, fins)):                             # 防護 ②③
            out[-1][1] = s                # ⑧：上一行的時間、下一行的完整字
            fixed += 1
            continue
        k = next((L for L in range(min(DUP_MAX, len(na), len(nb) - DUP_AFTER), DUP_MIN - 1, -1)
                  if na[-L:] == nb[:L]), 0)
        if (close and k and a.rstrip()[-1:] not in SENT_CLOSE
                and not _mid_word(a, ia[len(na) - k])                          # 上一行那截不是從單字中間開始
                and not (k < len(ib) and _mid_word(s, ib[k - 1] + 1))          # 下一行那截不是停在單字中間
                and _proves_join(na, nb[:k], nb[k:k + 4], fins)):              # 防護 ②③
            head = a.rstrip()
            while head and head[-1] in SENT_END:
                head = head[:-1].rstrip()
            # V1.29 審查：接「重複那截後面」的原字（空白、逗號照留），不 lstrip——英文原本會黏成「Reportfrom」「newlab」；
            #    中文字之間的空白由 tidy_cjk 收掉
            out[-1][1] = tidy_cjk(head + s[ib[k - 1] + 1:])
            fixed += 1
            continue
        out.append(row)
    return [tuple(x) for x in out], fixed


# ─────────────────────────── 視窗被關掉時的收尾 ───────────────────────────
_CLOSE_HANDLERS = []      # 🔴 ctypes 的回呼一定要留著參考，不然被回收後 Windows 一呼叫就當掉


def on_console_close(callback):
    """視窗被關掉（按右上角的 X）、登出、關機時，先跑 callback，再讓 Windows 結束程式。

    🔴 atexit 只在程式「自己結束」時跑。同事按視窗的 X，Windows 送出 CTRL_CLOSE_EVENT 之後就把
       行程殺掉，atexit 一行都不會執行——整場會議的暫存錄音（%TEMP%）和已經上傳到雲端的原始錄音
       就這樣留下來：雲端最多 48 小時、本機沒有期限（2026-09-14 實操驗收抓到）。
       Windows 給處理函式大約 5 秒，所以 callback 要先刪本機檔、再試雲端，而且不能等太久。
    Ctrl+C（CTRL_C_EVENT）不在這裡處理：回傳 False 讓 Python 自己的 KeyboardInterrupt 照常運作，
    那條路本來就會跑 atexit。非 Windows、或註冊失敗，就什麼都不做並回傳 False。
    實測（2026-09-15）：傳統主控台按 X → 處理函式有跑、暫存檔刪掉；Windows Terminal 關分頁走同一個事件。
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def handler(event):
        if event in (2, 5, 6):        # CTRL_CLOSE_EVENT／CTRL_LOGOFF_EVENT／CTRL_SHUTDOWN_EVENT
            try:
                callback()
            except Exception:
                pass
            return True
        return False

    fn = proto(handler)
    _CLOSE_HANDLERS.append(fn)
    try:
        return bool(ctypes.windll.kernel32.SetConsoleCtrlHandler(fn, True))
    except Exception:
        return False


# ───────────────────── 握手：有時限、可以中斷、會講話 ─────────────────────
@contextlib.asynccontextmanager
async def open_live(cm, stop, say=print,
                    timeout=CONNECT_TIMEOUT, hint_after=SLOW_HINT_AFTER):
    """
    包住 `client.aio.live.connect(...)` 的握手，補三件原本沒有的事：

      1. **握手有上限**：超過 timeout 秒丟 ConnectStalled，交給 Reconnect 退避＋中文說明
      2. **握手期間 Ctrl+C 真的有效**：同時等 stop，一設就放棄（丟 ConnectAborted）
      3. **久了先講一聲**：超過 hint_after 秒印一行，讓使用者知道不是死機

    用法（三支即時字幕腳本都一樣）：
        async with open_live(client.aio.live.connect(model=M, config=cfg), stop_all) as session:

    🔴 不能直接用 `async with asyncio.timeout(...)` 包原本那一行：時限會把**整段連線**
       一起罩住，會議開兩小時會在 30 秒被砍掉。這裡只罩住握手，進去之後就不再計時。
    🔴 也不能用 `asyncio.wait_for`：它等不到 stop，握手期間 Ctrl+C 照樣沒反應
       —— 那正是原本的病根。
    🔴 等待切成 _POLL 秒一段：Windows 的 SelectorEventLoop 卡在 select() 裡時，
       Python 的訊號處理函式要等迴圈醒來才跑得到。切小一點，Ctrl+C 才會在半秒內生效。
    """
    enter = asyncio.create_task(cm.__aenter__())
    stopper = asyncio.create_task(stop.wait())
    t0 = time.time()
    hinted = False

    async def _cleanup(cancel_enter):
        """把兩個工作收乾淨。🔴 例外一定要取回，否則 asyncio 會自己倒英文 traceback。"""
        for t in (enter, stopper):
            if cancel_enter or t is stopper:
                if not t.done():
                    t.cancel()
        for t in (enter, stopper):
            with contextlib.suppress(BaseException):
                await t

    try:
        while True:
            done, _ = await asyncio.wait({enter, stopper}, timeout=_POLL,
                                         return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                await _cleanup(cancel_enter=True)
                raise ConnectAborted()
            if enter in done:
                break
            waited = time.time() - t0
            if waited >= timeout:
                await _cleanup(cancel_enter=True)
                raise ConnectStalled()
            if not hinted and waited >= hint_after:
                hinted = True
                say(f"{DIM}  · 還在連線…（第一次連線遇到防毒或公司網路檢查憑證時"
                    f"會比較久，最多再等 {max(1, int(timeout - waited))} 秒）{RESET}")
    except BaseException:
        # Ctrl+C／取消也要收乾淨，不然畫面會多出「Task exception was never retrieved」
        await _cleanup(cancel_enter=True)
        raise

    await _cleanup(cancel_enter=False)        # 握手成功，只收掉 stopper
    session = enter.result()
    LINK.connected()
    try:
        yield _Tracked(session)               # 記送出／收到的時間，給 Reconnect 判斷斷線的性質（見 _LinkClock）
    finally:
        with contextlib.suppress(BaseException):
            await cm.__aexit__(None, None, None)


def quiet_async_noise(say=print):
    """
    把 asyncio「工作出例外但沒人取回」的預設行為（倒一整段英文 traceback）
    換成一行中文。

    🔴 病根（2026-09-18 使用者回報）：連線卡住時連按 Ctrl+C，畫面上會噴出一堆英文，
       同事看到只會直接關視窗，而真正的原因也埋在裡面看不出來。
    只換顯示方式、不吞資訊：例外型別與訊息前 90 字照樣印出來。
    正常收尾（CancelledError／KeyboardInterrupt）不吵。
    """
    def handler(_loop, context):
        exc = context.get("exception")
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            return
        if exc is not None:
            detail = f"{type(exc).__name__}: {str(exc)[:90]}"
        else:
            detail = str(context.get("message", ""))[:110]
        say(f"{DIM}  （背景工作結束：{detail}）{RESET}")

    try:
        asyncio.get_running_loop().set_exception_handler(handler)
    except RuntimeError:
        pass                              # 沒有正在跑的迴圈就算了
