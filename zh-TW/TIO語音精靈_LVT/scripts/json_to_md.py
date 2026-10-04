# -*- coding: utf-8 -*-
"""
把逐字稿 .json 重新產生成給人看的 .md（純本機處理，不呼叫 API、不花錢）。

用途：萬一 .md 不見了、或想換講者名字重新排版，不必重新轉錄整份錄音。

用法：
  python json_to_md.py 會議錄音_逐字稿.json
  python json_to_md.py 會議錄音_逐字稿.json --names 校長 主秘 處長
"""
import argparse
import io
import json
import os
import re
import sys

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)


def hhmmss(t):
    t = float(t or 0)
    return f"{int(t//3600):02d}:{int(t%3600//60):02d}:{int(t%60):02d}"


def load_transcript(path):
    """讀逐字稿 .json，回 (段落陣列, meta)。

    🔴 兩種格式都要讀得動：
       新版（2026-09-20 起）＝ {"meta": {...}, "segments": [...]}
       舊版與 .partial.json ＝ 直接就是段落陣列（meta 回空的 {}）
    這是整包唯一的讀法，menu.py 與 translate_transcript.py 也用這一支，不要各自再寫一份。
    """
    d = json.load(io.open(path, encoding="utf-8"))
    if isinstance(d, dict):
        return list(d.get("segments") or []), dict(d.get("meta") or {})
    return list(d or []), {}


# ── 講者標籤：排序與預設名字（功能 2／4／5 與選單共用，整包只有這一份）──
# 標籤是模型給的 spk:N；切段的錄音第 2 段起由 transcribe_meeting 加上段號：c2:spk:0（V1.22 起）。
_SPK = re.compile(r"(?:c(\d+):)?spk:(\d+)")
GENERIC_NAME = re.compile(r"(第\d+段)?講者\d+")      # 功能 2 自己給的預設名（不是使用者填的）


def speaker_part(sp):
    """講者標籤屬於第幾段：c2:spk:0 → 2；spk:0（第 1 段，或沒切段）→ 1。"""
    m = _SPK.fullmatch(str(sp))
    return int(m.group(1) or 1) if m else 1


def speaker_key(sp):
    """講者標籤的排序鍵：照「第幾段、第幾號」的**數字**排。

    🔴 2026-09-25（V1.22 ②）：原本各處的 sorted() 照字串排，spk:10 會排在 spk:2 前面——講者 11 位以上時，
       照開口順序填的名字從第 3 位起整排錯位（12 人假逐字稿實測：第 3 個開口的人拿到第 5 個名字）。
    """
    m = _SPK.fullmatch(str(sp))
    return (0, int(m.group(1) or 1), int(m.group(2))) if m else (1, 0, str(sp))


def speaker_list(segs):
    """逐字稿裡的講者標籤，照 speaker_key 排好。不要各自再 sorted() 一次。"""
    return sorted({s.get("speaker", "spk:0") for s in segs if isinstance(s, dict)}, key=speaker_key)


def generic_names(spks, lang=None):
    """沒填名字時每個標籤叫什麼：第 1 段「講者N」；切段時第 2 段起「第K段講者N」（N＝在那一段裡的順序）。
    lang＝譯文語言（功能 4）：en → Speaker N／Part K Speaker N；ja → 話者N／第K部 話者N。

    🔴 2026-09-25（V1.22 ③）：模型每一段各自分講者，第 2 段的 spk:0 跟第 1 段的 spk:0 不是同一個人。
       以前兩段共用同一個名字，自製會議實測第 2 段外賓的英文發言被記成「主席」。
    """
    base = (lang or "").replace("_", "-").split("-")[0].lower()
    one, part = {"en": ("Speaker {n}", "Part {k} Speaker {n}"),
                 "ja": ("話者{n}", "第{k}部 話者{n}")}.get(base, ("講者{n}", "第{k}段講者{n}"))
    out, cnt = {}, {}
    for sp in spks:
        k = speaker_part(sp)
        cnt[k] = cnt.get(k, 0) + 1
        out[sp] = (one if k == 1 else part).format(k=k, n=cnt[k])
    return out


def saved_names(spks, meta):
    """功能 2 存在 .json 裡、使用者真的填過的名字（{標籤: 名字}）；「講者1」這種功能 2 自己給的預設名不算。

    🔴 V1.26（C2）：功能 4 沒填名字時早就沿用這些（V1.22 ④），功能 5 卻一律用「講者N」——
       只是想重新排版一次，功能 2 填好的「主席、秘書」就被洗掉（09-26 實測）。兩邊改成同一套規則。
    """
    return {sp: v for sp, v in ((meta or {}).get("speakers") or {}).items()
            if sp in spks and v and not GENERIC_NAME.fullmatch(str(v))}


def warn_lines(meta, partial=False):
    """由 meta 產生檔頭的缺口／失敗警語行（給 json_to_md 與 translate_transcript 共用）。

    🔴 字樣必須跟 transcribe_meeting.py 寫檔頭的地方一致：menu 是靠這兩句判 ✅／⚠ 的。
    🔴 partial=True（.partial.json 救回來的殘稿）也要標：它一定不完整。
    """
    out = []
    failed = [x for x in (meta.get("failed") or []) if isinstance(x, (list, tuple)) and len(x) >= 4]
    if failed:
        out += ["", f"> 🔴 **有 {len(failed)} 段辨識失敗，這份逐字稿並不完整**，缺少下列時段（原始轉檔當時的紀錄）："]
        out += [f"> - 第 {i} 段 {hhmmss(cs)} – {hhmmss(ce)}　（{err}）" for i, cs, ce, err in failed]
    gaps = [g for g in (meta.get("gaps") or []) if str(g).strip()]
    if gaps:
        out += ["", "> ⚠️ **這份逐字稿可能不完整**（原始轉檔當時就有的提醒，重新排版或翻譯不會讓它消失）："]
        out += [f"> - {g}" for g in gaps]
    if partial and not gaps:
        out += ["", "> ⚠️ **這份逐字稿可能不完整**：來源是中斷時的暫存檔（`.partial.json`），"
                "後面沒轉到的部分不在裡面。"]
    return out


def note_lines(meta):
    """V1.36（待辦 18 B）：轉檔當時的 ℹ️ 說明（例如「這份錄音幾乎沒有安靜的時候」）照樣帶過來；不算缺口、不影響 ✅。
    🔴 跟 warn_lines 分開回傳（審查第三輪）：原本放在 warn_lines 裡，功能 4、5 只看「有沒有警語」就判不完整——
       畫面打 ⚠、給外賓的譯文多一句「This transcript is incomplete」，檔頭卻一個缺口都沒有。"""
    return [x for n in (meta.get("notes") or []) if str(n).strip() for x in ("", f"> ℹ️ {n}")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--names", nargs="*", default=[], help="講者真名，依出現順序")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    segs, meta = load_transcript(a.json_file)
    if not segs:
        print("✗ 這個檔案裡沒有段落")
        return 1
    # 🔴 2026-09-21 筆電第四輪驗收 P1：功能 4 產出的 `_對照.json` 以前會被這支照單全收，
    #    報得出段數與講者、畫面打 ✅，產出一份看起來完整正常、實際上把來源警語全弄丟的逐字稿。
    #    kind 是新版寫的；`translation` 欄是為了認得出**同事桌面上早就存在的舊 `_對照.json`**。
    if meta.get("kind") == "translation-pair" or any("translation" in s for s in segs[:5]):
        base = os.path.basename(a.json_file)
        print(f"✗ 這個檔是「翻譯」產出的對照檔，不是逐字稿：{base}")
        print("   它裡面是「原文＋譯文」的配對，重新排版會把原本的缺口提醒弄丟，")
        print("   產出一份看起來完整、其實不完整的逐字稿。")
        # 🔴 2026-09-21 筆電第五輪觀察-1：檔名是純字串取代算出來的，要先確認那個檔真的在。
        #    同事改過名或把逐字稿搬走時，原本會指向一個不存在的檔，讓人白找一圈。
        guess = base.replace("_對照.json", ".json")
        if guess != base and os.path.exists(os.path.join(os.path.dirname(a.json_file), guess)):
            print(f"   你要的應該是同一個資料夾裡的「{guess}」（功能 2 轉出來的那一份）。")
        print("   要重新排版譯文的話，回選單按 4、選逐字稿檔，重跑一次翻譯就好。")
        return 1

    spks = speaker_list(segs)
    names = generic_names(spks)
    if not a.names:
        names.update(saved_names(spks, meta))   # V1.26（C2）：沒填名字就沿用功能 2 存的（同功能 4）
    names.update(zip(spks, a.names))     # 選單已先把每位講者的第一句印給使用者看，照這個順序套
    chunks = sorted({s["chunk"] for s in segs if "chunk" in s})
    # 🔴 2026-09-20 筆電實測 N6-1：原本拿「最後一段的起點」算長度，47.5 秒的錄音被寫成 32 秒。改成最後一段的結束時間。
    total = max((float(s.get("end") or s.get("start") or 0) for s in segs), default=0)

    md = ["# 會議逐字稿", "",
          f"- 來源：`{os.path.basename(a.json_file)}`",
          ]
    if ".partial." in os.path.basename(a.json_file):
        # 🔴 救回來的檔一定要標。不標的話，過幾週再打開這份 .md 沒有人會
        #    記得它是中斷時的殘稿，下面那個「長度」也只是最後一段的時間，
        #    看起來像完整的會議紀錄。
        md += ["- ⚠️ **這份是從中斷的暫存檔救回來的，不是完整的會議紀錄。**",
               "  後面沒轉到的部分不在這裡，下面的「長度」只到中斷的那一刻為止。"]
    md += [
          f"- 長度：約 {hhmmss(total)}　段落：{len(segs)}　"
          + (f"講者標籤：{len(spks)} 個（每段分開算，同一個人可能重複）" if len(chunks) > 1 else f"講者：{len(spks)} 位")]
    if len(chunks) > 1:
        md += ["",
               f"> ⚠️ 這份錄音超過單段上限，當初是切成 {len(chunks)} 段分別辨識。",
               "> **講者編號是每一段各自判斷的**，不同段之間的「講者1」不保證是同一個人。"]
    # 功能 2 補轉回來的段（2026-09-20 N2）在 .json 裡標 recovered；重新排版時標記和說明要跟著帶過來，
    # 不然換個名字重排一次，〔補轉〕就不見了（複查指出）。字樣跟 transcribe_meeting.py 產生的一致。
    n_rec = sum(1 for s in segs if s.get("recovered"))
    if n_rec:
        md += ["", f"> ℹ️ 有 {n_rec} 處是第 2 趟整理時漏掉、再從原音單獨補轉回來的（內文標〔補轉〕）："
                   "講者與時間取自第 1 趟，建議對照錄音核對一下。"]
    # 🔴 2026-09-20 筆電全流程檢測（⚠-12）：原本重排一次就把「這份逐字稿可能不完整」整段弄丟，
    #    使用者只是想改個講者名字，卻拿到一份看起來完整、其實缺了 19 分鐘的逐字稿。
    #    這兩段的字樣必須跟 transcribe_meeting.py 寫檔頭的地方一致：menu 是靠這兩句判 ✅／⚠ 的。
    partial = ".partial." in os.path.basename(a.json_file)
    warn = warn_lines(meta, partial)
    md += warn + note_lines(meta)
    md += ["", "---", ""]

    last = None
    for s in segs:
        c = s.get("chunk")
        if len(chunks) > 1 and c != last:
            last = c
            md += [f"### 〔第 {c} 段〕", ""]
        who = names.get(s.get("speaker", "spk:0"), "講者")
        md += [f"**[{hhmmss(s.get('start'))}] {who}**" + ("　〔補轉〕" if s.get("recovered") else ""), "",
               (s.get("text") or s.get("raw") or "").strip(), ""]

    out = a.out or os.path.splitext(a.json_file)[0] + ".md"
    io.open(out, "w", encoding="utf-8").write("\n".join(md))
    # 檔頭有警語時不可以只印 ✅（跟功能 2 的收尾一致）
    # 🔴 .partial.json 救回來的殘稿也算：檔頭自己就寫著「不是完整的會議紀錄」，畫面不可以打綠勾
    #    （2026-09-20 複查指出，而 ⚠-7 的新提示正好把使用者導向這條路）。
    print(f"{'⚠' if warn else '✅'} 已產生：{out}")
    for line in warn:
        if line.startswith("> - "):
            print(f"   ⚠ {line[4:]}")
    print(f"   {len(segs)} 段、{len(spks)} 位講者、約 {hhmmss(total)}")
    print(f"   講者對應：{names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
