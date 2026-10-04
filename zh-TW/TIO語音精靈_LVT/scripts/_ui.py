# -*- coding: utf-8 -*-
"""
精靈視窗的共用版面。

🔴 病根（2026-09-07，同事的筆電）：視窗寫死 resizable(False, False)，內容又比
   螢幕高，結果「下一步」按鈕掉到螢幕外面，使用者完全卡死、連取消都按不到。

   所以版面規則是：
     1. 按鈕列**固定在視窗底部**，永遠看得到（先 pack side="bottom"）
     2. 中間內容放在可捲動的 Canvas 裡，內容再長都能捲
     3. 視窗高度**不超過螢幕工作區**（扣掉工作列），寬度也一樣
     4. 視窗可以自己拉大縮小
"""
import ctypes
import sys
import tkinter as tk


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def work_area():
    """回傳 (寬, 高)：螢幕可用區域，已扣掉工作列。拿不到就退回螢幕大小。"""
    if sys.platform == "win32":
        try:
            r = _RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
                return r.right - r.left, r.bottom - r.top
        except Exception:
            pass
    return None, None


def build_scrollable(root, bg):
    """
    在 root 裡建立「可捲動內容 ＋ 固定底部按鈕列」。
    回傳 (body, footer, canvas)：
      body   —— 內容往這裡 pack
      footer —— 按鈕往這裡 pack，永遠在視窗底部看得到
    """
    footer = tk.Frame(root, bg=bg)
    footer.pack(side="bottom", fill="x")

    host = tk.Frame(root, bg=bg)
    host.pack(side="top", fill="both", expand=True)

    canvas = tk.Canvas(host, bg=bg, highlightthickness=0, bd=0)
    vsb = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)

    body = tk.Frame(canvas, bg=bg)
    win = canvas.create_window((0, 0), window=body, anchor="nw")

    def _on_body(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        # 內容比視窗短就把捲軸收起來，短頁面不要無故多一條
        need = body.winfo_reqheight() > canvas.winfo_height()
        if need and not vsb.winfo_ismapped():
            vsb.pack(side="right", fill="y")
        elif not need and vsb.winfo_ismapped():
            vsb.pack_forget()

    def _on_canvas(e):
        canvas.itemconfigure(win, width=e.width)
        _on_body()

    body.bind("<Configure>", _on_body)
    canvas.bind("<Configure>", _on_canvas)

    def _wheel(e):
        if body.winfo_reqheight() > canvas.winfo_height():
            canvas.yview_scroll(-1 * int(e.delta / 120), "units")

    # bind_all 才收得到滑鼠在子元件上的滾輪
    root.bind_all("<MouseWheel>", _wheel)
    return body, footer, canvas


def fit(root, body, footer, max_w=760):
    """
    依內容算出視窗大小，但**不超過螢幕工作區**，然後置中。
    內容太高時就讓它捲動，絕不讓按鈕跑到螢幕外。

    🔴 高度要從 body + footer 算，不能用 root.winfo_reqheight()：
       內容裝在 Canvas 裡，Canvas 的請求高度是它自己的預設值、
       跟裡面的內容無關，拿它來算會得到一個莫名其妙的小視窗。
    """
    root.update_idletasks()
    ww, wh = work_area()
    if not ww:
        ww, wh = root.winfo_screenwidth(), root.winfo_screenheight() - 60

    need_w = max(body.winfo_reqwidth(), footer.winfo_reqwidth(), 620)
    need_h = body.winfo_reqheight() + footer.winfo_reqheight() + 4

    w = int(min(need_w + 20, max_w, ww - 40))
    h = int(min(need_h, wh - 40))
    x = max(0, (ww - w) // 2)
    y = max(0, (wh - h) // 3)
    root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
    # 最小尺寸也要保證按鈕列看得見
    root.minsize(560, min(320, max(200, int(wh) - 40)))


def apply_icon(win):
    """
    把 TIO 圖示掛到精靈視窗（標題列、Alt-Tab、工作列）。

    用 default=：Tk 會把它當成「這個程式之後新開的視窗」的預設圖示，所以後面跳出來的
    messagebox 也一起換掉，不必每個對話框各設一次。
    圖示純屬外觀 —— 缺檔、Tcl 不吃這顆 .ico、非 Windows，一律安靜跳過，
    不能因為一個圖示讓精靈開不起來。
    """
    try:
        from _winpath import icon_file
        p = icon_file()
        if not p:
            return False
        win.iconbitmap(default=p)
        return True
    except Exception:
        return False


def attach_paste_menu(entry, secret=False):
    """
    給輸入框加上 Windows 使用者預期的**右鍵選單**。

    🔴 病根（2026-09-18 使用者回報）：tkinter 的 Entry **沒有內建右鍵選單**。
       同事在安裝精靈貼 API 金鑰時，第一個動作就是「右鍵 → 貼上」，
       按下去卻完全沒反應，只有 Ctrl+V 有用 —— 對不熟電腦的人來說就是「壞掉了」。

    secret=True（金鑰這種遮蔽欄位）時**刻意不給「複製／剪下」**：
    欄位顯示的是圓點，但複製出去的是金鑰明文。這個工具從頭到尾的原則是
    不讓金鑰多一個外流路徑（文字版用 getpass、視窗版用 show="•"），這裡保持一致。

    用 event_generate 觸發 Tk 自己的 <<Paste>> 等虛擬事件，不自己碰剪貼簿 ——
    選取範圍、遮蔽欄位、Unicode 都交給 Tk 原本就寫好的處理。
    """
    menu = tk.Menu(entry, tearoff=0)      # 🔴 tearoff=0：不要那條可撕下的虛線
    menu.add_command(label="貼上",
                     command=lambda: entry.event_generate("<<Paste>>"))
    if not secret:
        menu.add_command(label="複製",
                         command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="剪下",
                         command=lambda: entry.event_generate("<<Cut>>"))
    menu.add_separator()
    menu.add_command(label="全選", command=lambda: (entry.select_range(0, "end"),
                                                  entry.icursor("end")))
    menu.add_command(label="清除", command=lambda: entry.delete(0, "end"))

    def popup(ev):
        entry.focus_set()                 # 先給焦點，貼上才會進到這一格
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            menu.grab_release()
        return "break"

    entry.bind("<Button-3>", popup)       # 右鍵
    entry.menu = menu                     # 留著給測試用，也避免被垃圾回收
    return menu
