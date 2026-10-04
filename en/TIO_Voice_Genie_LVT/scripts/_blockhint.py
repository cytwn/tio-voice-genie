# -*- coding: utf-8 -*-
"""ImportError 訊息的三分類：BLOCKED（被擋，等一下）／MISSING（沒裝）／BROKEN（重裝）。

🔴 為什麼要有這個檔（2026-09-22，P2）：

這個判斷原本有 **4 份各自獨立的拷貝** —— live_caption.py／live_bilingual.py／
live_bilingual_hq.py 的 `_need()` 各一份（5 個關鍵字），以及 _selfcheck.py 的
`_BLOCK_HINT`（7 個關鍵字，多了 "blocked by" 與 "smart app control"）。
四份已經漂到不一致：同一則錯誤訊息，診斷工具可能說「被擋了，等一下」，
主程式卻說「檔案壞了，去重裝」—— 而「重裝」對被擋的檔案完全沒用。

原本各檔的註解早就寫了「改字要一起改」，**但警語擋不住漂移**，結果還是漂了。
所以改成共用**函式**（不只是共用清單）：判斷邏輯只有一份，想不一致都不行。

🔴 為什麼不放在 _live.py：
_selfcheck.py 是「東西壞掉時才會被點開」的診斷工具，它刻意只相依標準庫
（見該檔開頭的說明）。若讓它去 import _live.py，_live.py 一旦壞掉，
診斷工具就跟著死 —— 而那正是最需要它的時候。
所以這個檔**刻意保持極小、零專案內相依**，不要往裡面加東西。

🔴 清單取「超集」（7 個）的理由：兩種誤判的代價不對稱 ——
  · 該說「重裝」卻說「等一下」→ 白等幾分鐘
  · 該說「等一下」卻說「重裝」→ 使用者真的去重裝，裝完還是壞的（這是修正前的現況）
"""

BLOCK_HINT = ("application control", "0x800704ec", "blocked by", "smart app control",
              "應用程式控制", "已封鎖", "被封鎖")

BLOCKED = "BLOCKED"
MISSING = "MISSING"
BROKEN = "BROKEN"


def classify(msg):
    """把 ImportError 的訊息分成 BLOCKED／MISSING／BROKEN。

    只吃字串、不丟例外：判斷失準也不可以害呼叫端連錯誤訊息都印不出來。
    """
    low = str(msg).lower()
    if any(k in low for k in BLOCK_HINT):
        return BLOCKED
    if "no module named" in low:
        return MISSING
    return BROKEN
