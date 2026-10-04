# -*- coding: utf-8 -*-
"""
6_診斷.bat 的套件檢查。

🔴 為什麼要獨立成一支檔，而不是塞在 .bat 的 python -c 裡：

出貨前稽核（2026-09-09）實測抓到——原本是一行 list comprehension 呼叫
importlib.util.find_spec()。當 google-genai 從來沒裝成功時（公司網路擋 PyPI，
說明書自己花了一整節在講這個情境），連上層的 google 套件都不存在，
find_spec('google.genai') 直接丟 ModuleNotFoundError，整串 comprehension 中止，
後面的 sounddevice / PyAudioWPatch / numpy / scipy 一個都不會被檢查。
stderr 又被 2>nul 吃掉，同事截圖回報時只看得到一行 could not check。

也就是說：這支診斷工具在「最需要它」的那個情況下，正好什麼都查不出來。
批次檔一行寫不下 try/except，所以拆成獨立檔案。

輸出刻意維持純 ASCII —— 這段是在 CP950 主控台裡印的。

2026-09-18 起多一個子命令：`_selfcheck.py mark` 印出「還帶著來自網路標記」的檔案。
同樣是照上面那個理由拆進 .py —— 這段要 try/except、要走訪資料夾、還要印路徑，
塞進 .bat 的 python -c 只會寫出一行沒人看得懂又容易壞的東西。
"""
import importlib.util
import os
import sys

PKGS = ["google.genai", "sounddevice", "pyaudiowpatch", "numpy", "scipy"]
# 🔴 2026-09-20 筆電實測（P0）：find_spec 只看得到「檔案在不在」，看不到「載不載得起來」。
#    Windows 11 的智慧型應用程式控制（Smart App Control）會擋下剛裝好、還沒有雲端信譽的未簽章 DLL
#    （事件檢視器 CodeIntegrity 3118／3077 點名 scipy\special\_ufuncs_cxx.cp313-win_amd64.pyd），
#    那時 find_spec 照樣回 OK，功能 1／3／6 一開卻丟英文 ImportError: DLL load failed。
#    幾分鐘後雲端信譽判定完成就會自己放行 —— 但同事當下看到的是診斷說 OK、程式說 traceback。
#    所以真的 import 一次：這幾個套件都帶原生 DLL，只有 import 才試得出來。
# 🔴 只對「純算數、匯入沒有副作用」的套件做真的 import：sounddevice／pyaudiowpatch 一匯入就初始化
#    PortAudio（複查實測診斷從 0.07 秒變 2 秒，沒有音效卡的機器還可能卡住），得不償失。
IMPORT_CHECK = {"scipy": "scipy.signal", "numpy": "numpy",
                "google.genai": "google.genai"}
#    只有帶「政策封鎖」字樣的才算 BLOCKED：單純的 DLL load failed 多半是版本不合或缺 VC 執行檔，
#    那是 BROKEN，兩者要給不同的建議（等一下 vs 重裝）。
#    🔴 英文版 Windows 的訊息是英文，只認中文字樣會整個判成 BROKEN、連那段建議都不印（複查指出）。
# 🔴 2026-09-22（P2）：這份清單原本是本檔自己的一份，與三支即時腳本的那三份漂到不一致
#    （本檔 7 個、腳本 5 個）。已抽成 _blockhint.classify()，四處共用同一個判斷。
#    🔴 這裡**一定要包 try**：本檔是「東西壞掉時才會被點開」的診斷工具，
#    不可以因為多了一個相依而變得更容易死。載不到就退回本地備援，照樣跑得完。
try:
    from _blockhint import classify as _classify
except Exception:                                      # pragma: no cover
    _FALLBACK = ("application control", "0x800704ec", "blocked by", "smart app control",
                 "應用程式控制", "已封鎖", "被封鎖")

    def _classify(msg):
        low = str(msg).lower()
        if any(k in low for k in _FALLBACK):
            return "BLOCKED"
        return "MISSING" if "no module named" in low else "BROKEN"


def status(name):
    """回傳 OK / MISSING / BROKEN / BLOCKED。單一套件出事不能拖垮其他套件的檢查。"""
    try:
        if not importlib.util.find_spec(name):
            return "MISSING"
    except ModuleNotFoundError:
        # 上層套件不存在（例如 google-genai 整包沒裝）→ 就是沒裝
        return "MISSING"
    except Exception as e:
        # 裝了但壞掉（版本衝突、檔案損毀）。這跟「沒裝」要分得出來，
        # 不然遠端協助的人會叫同事重裝一個其實已經在的東西。
        return "BROKEN (%s)" % type(e).__name__
    mod = IMPORT_CHECK.get(name)
    if not mod:
        return "OK"
    try:
        importlib.import_module(mod)
        return "OK"
    except ImportError as e:
        msg = str(e).replace("\n", " ")
        if _classify(msg) == "BLOCKED":
            return "BLOCKED (%s)" % msg[:90]
        return "BROKEN (ImportError: %s)" % msg[:80]
    except Exception as e:
        return "BROKEN (%s)" % type(e).__name__


def marks():
    """
    印出還帶著「來自網路」標記的檔案。

    為什麼診斷要查這個：從 Email／雲端拿到的 zip，解壓縮會把標記蓋到 .bat 上，
    同事點安裝／開始使用／解除安裝就被 Windows 擋下來，但說明文件都正常
    —— 看起來很像被單位政策封鎖。這一項讓回報的截圖裡直接看得到答案。
    """
    # 🔴 這一段是全檔唯一會印出非 ASCII 的地方（檔名是中文），而它是在主控台
    #    字碼頁底下印的。cp950 印得出來，但別的字碼頁（或改過 chcp 的視窗）會噴
    #    UnicodeEncodeError，整段就變成診斷畫面上一句 "could not check"。
    #    改成 errors="replace"：印不出來的字變成 ?，但**絕不會整段消失**。
    #    用 reconfigure 而不是換掉 sys.stdout —— 換掉會在被 import 時互關底層 buffer。
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    try:
        sys.path.insert(0, here)
        from _winpath import zone_marked_files
        found = zone_marked_files(root)
    except Exception as e:
        print("    could not check (%s)" % type(e).__name__)
        return 0
    if not found:
        print("    none - OK")
        return 0
    print("    %d file(s) still marked as downloaded from the internet" % len(found))
    print("    Windows shows a security warning when you double-click these:")
    for p in found[:8]:
        print("      " + os.path.relpath(p, root))
    if len(found) > 8:
        print("      ... and %d more" % (len(found) - 8))
    # 🔴 2026-09-20 筆電全流程檢測（⚠-1）：安裝「剛跑完」時這裡誤報過 21 個檔還帶標記，2 分鐘後自己歸零。
    #    原因未能歸因（筆電做了三次對照實驗都推翻），但建議文字不能叫使用者再跑一次他剛跑完的安裝檔。
    print("    -> if you just ran the setup file (3_), close this and run this")
    print("       diagnostic again in a minute - the marks often clear by themselves.")
    print("    -> if they are still listed, run the setup file (3_) once; it clears them")
    return 0


_PKEY_RAW = "{8943b373-388c-4395-b557-bc6dbaffafdb},2"      # PKEY_Devices_AudioDevice_RawProcessingSupported


def _raw_supported(root, guid):
    """這支麥克風支不支援「完整收音」（RAW）。登錄檔存的是序列化的 PROPVARIANT：VT_BOOL(11)… 值 0xFFFF＝TRUE。"""
    import winreg
    try:
        with winreg.OpenKey(root, guid + "\\Properties") as p:
            v = winreg.QueryValueEx(p, _PKEY_RAW)[0]
        return isinstance(v, (bytes, bytearray)) and len(v) >= 10 and v[0] == 11 and v[8:10] == b"\xff\xff"
    except OSError:
        return False


def audio():
    """
    6_診斷.bat 的 [Audio devices]：麥克風權限、Windows 預設的錄音／播放裝置、所有啟用中的麥克風。

    🔴 2026-09-22（P3）：收音是這個工具最常壞的地方（當天會議實測），診斷卻完全沒有音訊項目。
       併進桌機 mic_diag.py 的 [2][3] 段。**不錄音、不開 PortAudio**（理由同上方 IMPORT_CHECK：
       一匯入就初始化聲音元件，沒有音效卡的機器還可能卡住），只讀登錄檔與 COM。
    """
    try:
        sys.stdout.reconfigure(errors="replace")      # 裝置名稱是中文；印不出來變 ?，不可以整段消失
    except Exception:
        pass
    import winreg
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    for hive, label, sub in ((winreg.HKEY_LOCAL_MACHINE, "whole PC    ", ""),
                             (winreg.HKEY_CURRENT_USER, "this user   ", ""),
                             (winreg.HKEY_CURRENT_USER, "desktop apps", r"\NonPackaged")):
        try:
            with winreg.OpenKey(hive, base + sub) as k:
                val = winreg.QueryValueEx(k, "Value")[0]
        except OSError:
            val = None                                   # 沒有這個值＝沒被關掉
        print("    mic permission, %s: %s" % (label, "OK" if val in (None, "Allow") else
                                                 "BLOCKED (%s) -> Settings > Privacy > Microphone" % val))
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import _audioroute as ar
    for flow, label in ((1, "default microphone"), (0, "default speaker   ")):
        name = ar.endpoint_full_name((ar.default_endpoint_ids(flow) or {}).get(0))
        print("    %s: %s" % (label, name or "NONE"))
    rows = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ar._REG_CAPTURE)
        for i in range(winreg.QueryInfoKey(root)[0]):
            guid = winreg.EnumKey(root, i)
            try:
                with winreg.OpenKey(root, guid) as k:
                    if winreg.QueryValueEx(k, "DeviceState")[0] != 1:
                        continue
            except OSError:
                continue
            rows.append((ar.endpoint_full_name("{0.0.1.00000000}." + guid) or guid, _raw_supported(root, guid)))
    except OSError:
        pass
    print("    microphones (%d):" % len(rows))
    for name, raw in rows:
        print("      - %s%s" % (name, "   [full capture: yes]" if raw else ""))
    if not rows:
        print("      NONE -> plug in a microphone or headset")
    return 0


def capture():
    """
    6_診斷.bat 的 [Recording devices]：照 TIO 找裝置的做法（_live）真的找一次，找到就開一下再關（聲音不讀進來、不存）。

    🔴 2026-09-28 同事的 ASUS：[Audio devices] 全部正常，功能 6 一開卻「找不到側錄裝置」——那一段只列登錄檔的名稱，
       從沒走過程式真正找裝置的那一步。
    要開 PortAudio 才找得到裝置，沒有音效卡的機器可能卡住（見 IMPORT_CHECK），所以放在子行程、20 秒逾時。
    """
    import subprocess
    try:
        sys.stdout.reconfigure(errors="replace")      # 裝置名稱是中文；印不出來變 ?，不可以整段消失
    except Exception:
        pass
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "capture-child"],
                           capture_output=True, timeout=20)
    except subprocess.TimeoutExpired as e:
        # 已經查完的那幾行照樣印出來（例如麥克風 OK、卡在電腦聲音），不要一起吞掉（V1.31 審查 #3）
        part = (e.stdout or b"").decode("utf-8", "replace").replace("\r\n", "\n").rstrip()
        if part:
            print(part)
        print("    could not finish (the sound components did not answer within 20 s)")
        return 0
    out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").rstrip()   # 子行程已經換成 \r\n，再印一次會變 \r\r\n
    if out:
        print(out)
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        print("    could not finish (%s)" % (err[-1][:100] if err else "exit %d" % r.returncode))
    return 0


def _capture_child():
    # line_buffering：印到管線的輸出預設整塊暫存，卡住被收掉時會整段不見——每行立刻送出（V1.31 審查第二輪 #2）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    import time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _live
    import sounddevice as sd
    devs = _live._wasapi_inputs(sd)[1]
    ids = _live._ids_available(sd, devs)
    if not devs:
        # V1.34：沒接麥克風時清單是空的，_ids_available 一定回 False——那不代表聲音元件舊（桌機 09-29 回報四之 1）
        print("    matching devices by : (skipped - no microphone found)")
    else:
        print("    matching devices by : %s" % ("Windows endpoint ID" if ids else "name (older sound component)"))
    want = _live.default_device_id(1) if ids else _live.default_device_name(1)
    idx, d = _live._pick_input(sd, want)
    if d is None:
        print("    default microphone  : NOT FOUND (Windows default: %s)" % (_live._device_label(want) or "none"))
    else:
        try:
            with sd.InputStream(device=idx, channels=d["max_input_channels"], samplerate=int(d["default_samplerate"]),
                                dtype="float32", extra_settings=sd.WasapiSettings(), callback=lambda *a: None):
                time.sleep(0.3)
            print("    default microphone  : %s -> opened OK" % d["name"])
        except Exception as e:
            print("    default microphone  : %s -> FAILED to open (%s)" % (d["name"], str(e)[:80]))
    try:                                  # 功能 6 口譯播放拔插後能不能自動接回：拿預設喇叭試一次「找同一顆」（同 _live.Speaker）
        o = sd.query_devices(kind="output")
        full = _live._full_output_name(sd, o["index"], o["name"])
        tw, by = _live._wasapi_twin(sd, o["index"]), "ID"
        if tw is None:
            tw, by = _live._wasapi_output(sd, full), "name"
        print("    speaker reconnect   : %s (default speaker) -> %s" % (
            full or o["name"], "OK, same device found by %s" % by if tw is not None
            else "NOT available - after an unplug it can only retry the old stream"))
    except Exception as e:
        print("    speaker reconnect   : could not check (%s)" % type(e).__name__)
    import pyaudiowpatch as pa
    want = _live._endpoint_friendly_name(_live.default_device_id(0, role=1))     # 跟 capture_loopback 同一個找法
    with pa.PyAudio() as p:
        lb, seen = _live._pick_loopback(p, pa, want)
        if lb is None:
            print("    computer sound      : NOT FOUND - loopback devices seen: %s" % (", ".join(seen) or "none"))
            return 0
        try:
            st = p.open(format=pa.paInt16, channels=lb["maxInputChannels"], rate=int(lb["defaultSampleRate"]),
                        input=True, input_device_index=lb["index"], frames_per_buffer=1024)
            st.close()
            print("    computer sound      : %s -> opened OK" % lb["name"])
        except Exception as e:
            print("    computer sound      : %s -> FAILED to open (%s)" % (lb["name"], str(e)[:80]))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "mark":
        return marks()
    if len(sys.argv) > 1 and sys.argv[1] == "audio":
        return audio()
    if len(sys.argv) > 1 and sys.argv[1] == "capture":
        return capture()
    if len(sys.argv) > 1 and sys.argv[1] == "capture-child":
        return _capture_child()
    try:
        # BLOCKED／BROKEN 會把 Windows 的原文訊息帶出來（中文版 Windows 就是中文）；
        # 印不出來的字變成 ?，不可以讓整段診斷消失（同 marks()）。
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    blocked = False
    for n in PKGS:
        st = status(n)
        blocked = blocked or st.startswith("BLOCKED")
        print("    %-14s %s" % (n, st))
    if blocked:
        # 純 ASCII：這段是在 CP950 主控台裡印的（同本檔開頭的說明）
        print("    -> BLOCKED means the file is there but Windows refused to load it.")
        print("       Windows 11 Smart App Control blocks freshly installed unsigned")
        print("       DLLs until they get a cloud reputation - usually a few minutes.")
        print("       Wait, then run this diagnostic again. Features 1/3/6 need these.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
