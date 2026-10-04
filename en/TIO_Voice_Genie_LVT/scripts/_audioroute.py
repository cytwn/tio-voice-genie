# -*- coding: utf-8 -*-
"""兩條路線：原音走一條（聽不到、只拿來側錄），口譯語音走另一條（聽得到）。

為什麼要動「系統預設播放裝置」：
錄「電腦播出來的聲音」用的是 WASAPI loopback，它錄的東西就是**系統預設播放裝置正在
播什麼**。所以「不要聽到原音」沒辦法靠靜音達成 —— 靜音等於把錄音來源一起關掉。
唯一的做法是把原音送到一顆使用者聽不到的輸出（沒接線的 SPDIF／HDMI、沒戴上的耳機、
虛擬音效線），再把口譯語音播到會響的那一顆。

本機實測（2026-09-18，Realtek）：
  ・播到沒接線的 SPDIF → 它的 loopback 錄得到，−24.9 dBFS，和喇叭錄到的一模一樣
  ・口譯語音播到喇叭   → SPDIF 的 loopback **完全沒有資料**（零回授）
  ・兩個同時播、錄 SPDIF → 會議音 −22.6 dBFS、口譯音 −126.4 dBFS（＝底噪，差 104 dB）

🔴 程式**無法**自己判斷哪一條「聽不到」：光纖孔沒有可靠的插拔偵測、耳機有沒有戴在
   頭上 Windows 也不知道。所以兩條路線一律由使用者指定，這支模組只負責切換與還原。

🔴 切換是有副作用的系統設定，還原必須萬無一失，所以有兩道保險：
   ① 正常結束、Ctrl+C、按視窗 X（_live.on_console_close）都會還原
   ② 切換前把「原本那顆」寫進狀態檔；下次啟動時只要狀態檔還在，就代表上次沒還原成功
      （當機、被工作管理員砍掉），開頭先自動還原並告訴使用者
"""
import ctypes
import json
import os
import sys
import tempfile
import time

# IPolicyConfig：Windows 未公開的 COM 介面，nircmd／SoundVolumeView／AudioDeviceCmdlets
# 都是用它換預設裝置。免管理員權限、不必安裝任何東西（純 ctypes）。
_CLSID_POLICY_CONFIG = "{870af99c-171d-4f9e-af0d-e63df40c2bc9}"
_IID_POLICY_CONFIG = "{f8679f50-850a-41cf-9c72-430f290290c8}"
# vtable：QueryInterface/AddRef/Release 之後還有 10 個方法，SetDefaultEndpoint 排第 13
_VTBL_SET_DEFAULT_ENDPOINT = 13
_CLSCTX_ALL = 23
# eConsole／eMultimedia／eCommunications：三個角色都要設，否則「預設通訊裝置」會留在舊的
_ROLES = (0, 1, 2)

_REG_RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
_PKEY_DEVICE_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
_PKEY_FRIENDLY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},14"
# 介面名稱（「Realtek(R) Audio」「Logitech USB Headset H340」）。Windows 各處顯示的完整名稱＝「裝置描述 (介面名稱)」
_PKEY_IFACE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
_DEVICE_STATE_ACTIVE = 1
_MME_NAME_LEN = 31          # MME 把裝置名稱截成 31 個字

# IMMDeviceEnumerator：問 Windows「三個角色目前的預設各是哪顆」，拿到的是端點 id（不靠名稱比對）
_CLSID_MMDEVICE_ENUMERATOR = "{bcde0395-e52f-467c-8e3d-c4579291692e}"
_IID_IMMDEVICE_ENUMERATOR = "{a95664d2-9614-4f35-a746-de8db63617e6}"


def _state_path(create=False):
    """狀態檔：記「原本的預設是哪顆」，當機沒還原時靠它救回來。

    放 %LOCALAPPDATA%；真的拿不到就退到 %TEMP%（比不寫好，只是可能被清掉）。
    資料夾名用純英數，避免中文路徑在別的工具鏈上出狀況。
    🔴 只有真的要寫（create=True，切換時）才建資料夾。選單每次都會來讀，讀的時候建的話，
       每個打開選單的人電腦裡都會多一個空資料夾，解除安裝也不會刪它。
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "TIO-Meeting-Genie")
    if create:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = tempfile.gettempdir()
    elif not os.path.isdir(d):
        d = tempfile.gettempdir()             # 寫的時候建不了資料夾會退到這裡，讀也要看同一個地方
    return os.path.join(d, "audio_route.json")


def available():
    """這台機器能不能自動切換播放裝置。"""
    return sys.platform == "win32"


def _guid(s):
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]
    g = GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g)) != 0:
        raise RuntimeError("GUID parse failed: " + s)
    return g


def set_default_endpoint(endpoint_id, roles=_ROLES):
    """把系統預設播放裝置換成 endpoint_id（預設三個角色都換）。成功回 None，失敗回錯誤字串。"""
    if not available():
        return "This feature is only available on Windows"
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_POLICY_CONFIG)), None,
                                    _CLSCTX_ALL, ctypes.byref(_guid(_IID_POLICY_CONFIG)),
                                    ctypes.byref(ptr))
        if hr != 0:
            return f"Could not get IPolicyConfig (hr=0x{hr & 0xffffffff:08x})"
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                   ctypes.c_wchar_p, ctypes.c_int)
        fn = proto(vtbl[_VTBL_SET_DEFAULT_ENDPOINT])
        for role in roles:
            hr = fn(ptr, endpoint_id, role)
            if hr != 0:
                return f"Switch failed (role={role}, hr=0x{hr & 0xffffffff:08x})"
        return None
    except Exception as e:                       # noqa: BLE001 - 任何失敗都要退回手動模式
        return f"{type(e).__name__}: {e}"


def default_endpoint_ids(flow=0):
    """三個角色（0 一般、1 多媒體、2 通訊）目前的預設端點 id，{角色: id 或 None}。問不到回 None。
    flow：0＝播放裝置（預設）、1＝錄音裝置（2026-09-22 收音看門狗用，見 _live.capture_mic）。

    🔴 不要靠名稱判斷「哪顆是預設」：USB 耳麥和筆電喇叭在 Windows 裡常常都叫「喇叭」，名稱比對
       會對錯顆，結束時就改回錯的那顆（2026-09-19 審查：模擬 8 種組合錯 4 種）。問 Windows 拿端點 id 最準。
    """
    if not available():
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        enum = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_MMDEVICE_ENUMERATOR)), None, _CLSCTX_ALL,
                                    ctypes.byref(_guid(_IID_IMMDEVICE_ENUMERATOR)), ctypes.byref(enum))
        if hr != 0 or not enum:
            return None

        def method(obj, index, restype, *argtypes):
            vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])

        # IMMDeviceEnumerator：3 EnumAudioEndpoints、4 GetDefaultAudioEndpoint；IMMDevice：5 GetId
        get_default = method(enum, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        out = {}
        try:
            for role in _ROLES:
                dev = ctypes.c_void_p()
                if get_default(enum, flow, role, ctypes.byref(dev)) != 0 or not dev:   # 0＝eRender、1＝eCapture
                    out[role] = None                                                 # 這個角色沒有預設裝置
                    continue
                try:
                    pid = ctypes.c_void_p()
                    ok = method(dev, 5, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(dev, ctypes.byref(pid)) == 0
                    out[role] = ctypes.wstring_at(pid.value) if ok and pid.value else None
                    if pid.value:
                        ole32.CoTaskMemFree(pid)
                finally:
                    method(dev, 2, ctypes.c_ulong)(dev)          # Release
        finally:
            method(enum, 2, ctypes.c_ulong)(enum)
        return out
    except Exception:                            # noqa: BLE001 - 問不到就退回名稱比對
        return None


def _method(obj, index, restype, *argtypes):
    """COM 物件虛擬函式表的第 index 個方法。"""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _on_endpoint(endpoint_id, fn):
    """IMMDeviceEnumerator::GetDevice（第 5 格）拿到這個端點的 IMMDevice，交給 fn(dev)，用完一律 Release。任何失敗回 None。
    拔掉、停用的端點也拿得到（GetDevice 不看狀態）。"""
    if not available() or not endpoint_id:
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        enum = ctypes.c_void_p()
        if ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_MMDEVICE_ENUMERATOR)), None, _CLSCTX_ALL,
                                  ctypes.byref(_guid(_IID_IMMDEVICE_ENUMERATOR)), ctypes.byref(enum)) != 0 or not enum:
            return None
        try:
            dev = ctypes.c_void_p()
            if _method(enum, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(
                    enum, str(endpoint_id), ctypes.byref(dev)) != 0 or not dev:
                return None
            try:
                return fn(dev)
            finally:
                _method(dev, 2, ctypes.c_ulong)(dev)             # Release
        finally:
            _method(enum, 2, ctypes.c_ulong)(enum)
    except Exception:                            # noqa: BLE001
        return None


def endpoint_state(endpoint_id):
    """這個端點現在的狀態（IMMDevice::GetState，第 6 格：1 啟用、2 停用、4 不存在、8 拔掉）；問不到回 None。

    V1.31：側錄看「那一顆還在不在」改問這個。🔴 登錄檔的 DeviceState 帶著沒有文件的旗標位元
    （09-28 審查在這台量到：停用的端點是 0x10000001、不存在的是 0x20000004），COM 回的才是正式的值。
    """
    def get(dev):
        st = ctypes.c_ulong()
        ok = _method(dev, 6, ctypes.c_long, ctypes.POINTER(ctypes.c_ulong))(dev, ctypes.byref(st)) == 0
        return st.value if ok else None
    return _on_endpoint(endpoint_id, get)


_PROP_TYPES = []     # (PROPERTYKEY 類別, PROPVARIANT 類別, 那個 PROPERTYKEY)：只建一次——
#   🔴 每次呼叫都建新的 ctypes 類別，POINTER()／WINFUNCTYPE() 的全域快取就會一直長（09-28 審查量到每次約 18 KB）


def _prop_types():
    if not _PROP_TYPES:
        g = _guid(_PKEY_FRIENDLY_NAME.split(",")[0])

        class PKEY(ctypes.Structure):
            _fields_ = [("fmtid", type(g)), ("pid", ctypes.c_ulong)]

        class PROPVARIANT(ctypes.Structure):                              # x64：vt＋3 個保留字，值從第 8 個位元組開始，共 24 位元組
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("val", ctypes.c_void_p), ("pad", ctypes.c_void_p)]
        _PROP_TYPES.append((PKEY, PROPVARIANT, PKEY(g, int(_PKEY_FRIENDLY_NAME.split(",")[1]))))
    return _PROP_TYPES[0]


def endpoint_friendly_name(endpoint_id):
    """端點 ID → Windows 的 FriendlyName（PKEY_Device_FriendlyName）；問不到回 None。

    🔴 PortAudio／PyAudioWPatch 的裝置名稱就是讀這一個屬性（兩份 pa_win_wasapi.c 的 FillDeviceInfo，09-28 查過），
       所以拿它去對 PyAudio 的名稱是「同一個來源」；登錄檔組出來的「裝置描述 (介面名稱)」（endpoint_full_name）不保證一樣
       （09-28 同事的 ASUS 就差開頭一格空白）。IMMDevice::OpenPropertyStore 第 4 格、IPropertyStore::GetValue 第 5 格。
    """
    def get(dev):
        store = ctypes.c_void_p()
        if _method(dev, 4, ctypes.c_long, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p))(
                dev, 0, ctypes.byref(store)) != 0 or not store:             # 0＝STGM_READ
            return None
        try:
            PKEY, PROPVARIANT, key = _prop_types()
            pv = PROPVARIANT()
            if _method(store, 5, ctypes.c_long, ctypes.POINTER(PKEY), ctypes.POINTER(PROPVARIANT))(
                    store, ctypes.byref(key), ctypes.byref(pv)) != 0:
                return None
            try:
                return ctypes.wstring_at(pv.val) if pv.vt == 31 and pv.val else None     # 31＝VT_LPWSTR
            finally:
                ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
        finally:
            _method(store, 2, ctypes.c_ulong)(store)
    return _on_endpoint(endpoint_id, get)


def active_render_ids_named(name):
    """現在啟用中、FriendlyName 等於 name 的播放端點 ID（照登錄檔列舉的順序）。給側錄「照名稱接回同一顆」之後補上它的新 ID 用
    （USB 裝置拔插後重新辨識，名稱一樣、ID 可能換了）。"""
    if not available() or not name:
        return []
    import winreg
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_RENDER) as root:
            guids = [winreg.EnumKey(root, i) for i in range(winreg.QueryInfoKey(root)[0])]
    except OSError:
        return []
    for g in guids:                       # 狀態問 Windows（COM），不看登錄檔的 DeviceState（帶旗標位元，見 endpoint_state）
        eid = "{0.0.0.00000000}." + g
        if endpoint_state(eid) == _DEVICE_STATE_ACTIVE and endpoint_friendly_name(eid) == name:
            out.append(eid)
    return out


def _registry_endpoints():
    """[(endpoint_id, 短名稱, 完整名稱)]，只列 DeviceState=1（啟用中）的播放端點。

    短名稱＝裝置描述（「喇叭」「Realtek Digital Output」），給選單顯示；
    完整名稱＝「喇叭 (Realtek(R) Audio)」，跟 sounddevice 的名稱配對用。
    """
    if not available():
        return []
    import winreg
    out = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_RENDER)
    except OSError:
        return []
    for i in range(winreg.QueryInfoKey(root)[0]):
        try:
            guid = winreg.EnumKey(root, i)
            dev = winreg.OpenKey(root, guid)
            if winreg.QueryValueEx(dev, "DeviceState")[0] != _DEVICE_STATE_ACTIVE:
                continue
            props = winreg.OpenKey(dev, "Properties")

            def _val(key):
                try:
                    return winreg.QueryValueEx(props, key)[0]
                except OSError:
                    return None
            # 友善名稱常常是空的（本機實測就是），退回裝置描述（「喇叭」「Realtek Digital Output」）
            friendly, desc, iface = _val(_PKEY_FRIENDLY_NAME), _val(_PKEY_DEVICE_DESC), _val(_PKEY_IFACE_NAME)
            short = desc or friendly
            if not short:
                continue
            full = friendly or (f"{desc} ({iface})" if iface else desc)
            out.append((f"{{0.0.0.00000000}}.{guid}", str(short), str(full)))
        except OSError:
            continue
    return out


def endpoint_name(endpoint_id):
    """端點 ID → 登錄檔裡的完整名稱；查不到回 None。**只給畫面顯示用。**

    🔴 子程式解析到的是 MME 的名稱，超過 31 字會被截掉（「1 - KONKA LCDTV (AMD High Defin」）。
       口譯開始時顯示那種半截的名稱，使用者會以為選錯裝置（2026-09-20 使用者指示補的）。
       比對、開裝置一律還是用端點 ID 或 MME 名稱，不要拿這個名字去找裝置。
    """
    want = str(endpoint_id or "").lower()
    for eid, _short, full in _registry_endpoints():
        if eid.lower() == want:
            return full
    return None


_REG_CAPTURE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"


def endpoint_full_name(endpoint_id):
    """端點 ID（播放 `{0.0.0.…}` 或錄音 `{0.0.1.…}`）→ Windows 顯示的完整名稱「裝置描述 (介面名稱)」；查不到回 None。

    🔴 **不保證**跟 PortAudio 的 WASAPI 裝置名稱是同一個字串：本機兩台相同（「Headset Microphone (Realtek(R) Audio)」
       「麥克風陣列 (AMD Audio Device)」），09-28 同事的 ASUS 這裡開頭多一格空白、側錄就找不到裝置。
       V1.31 起 _live 找裝置一律比端點 ID，這個名稱只給畫面顯示、和查不到 ID 時的退路。
    🔴 不看 DeviceState：拔掉的端點也查得到名字，呼叫端自己用「開不開得起來」判斷。
    """
    if not available() or not endpoint_id:
        return None
    import winreg
    eid = str(endpoint_id)
    base = _REG_CAPTURE if eid.startswith("{0.0.1.") else _REG_RENDER
    guid = eid.rsplit("}.", 1)[-1] if "}." in eid else eid
    try:
        props = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + guid + "\\Properties")
    except OSError:
        return None

    def _val(key):
        try:
            return winreg.QueryValueEx(props, key)[0]
        except OSError:
            return None
    friendly, desc, iface = _val(_PKEY_FRIENDLY_NAME), _val(_PKEY_DEVICE_DESC), _val(_PKEY_IFACE_NAME)
    name = friendly or (f"{desc} ({iface})" if desc and iface else desc)
    return str(name) if name else None


def list_routes(probe_speak=False):
    """可以當路線用的輸出裝置。

    回傳 [{'id', 'name', 'sd_index', 'is_default', 'speakable'}]，
    id 取自登錄檔（切換預設裝置要用它），name／sd_index 取自 sounddevice
    （跟選單、--speak-device 用的是同一套名稱）。兩邊用**完整名稱**配對——登錄檔的
    「裝置描述 (介面名稱)」＝sounddevice 的「喇叭 (Realtek(R) Audio)」（MME 截成 31 字的也認得）。
    🔴 不可以只用裝置描述（「喇叭」）去比開頭：USB 耳麥和筆電喇叭常常都叫「喇叭」，兩條路線會對到
       同一顆，試聽兩聲從同一顆出來（2026-09-19 審查）。登錄檔沒有介面名稱時才退回比開頭。
       兩條路線顯示名稱一樣時，選單改顯示完整名稱，不然分不出來。

    🔴 sd_index 一定要挑**播得出 24kHz** 的那一個，不能無腦挑 WASAPI。同一顆實體裝置
       在 MME／DirectSound／WASAPI／WDM-KS 底下各出現一次，本機實測只有 MME 與
       DirectSound 開得起來，WASAPI 回 `Invalid sample rate`、WDM-KS 回
       `Blocking API not supported`（見 _live.probe_output_device）。第一版寫死抓
       WASAPI，結果兩條路線都變成 speakable=False，等於整個功能開不了。
    🔴 DirectSound「開得起來」不代表播得出來：阻塞寫入整場沒聲音、不報錯（2026-09-20 筆電實測 N1，
       桌機重現）。所以 sd_index 優先用 Windows 回報的 MME 編號，DirectSound 一律不當成播得出來。
    """
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        outs = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                if d.get("max_output_channels", 0) > 0]
    except Exception:
        return []
    defaults = default_endpoint_ids()
    default_name = "" if defaults else (current_default_name() or "")

    try:
        from _live import probe_output_device
    except Exception:
        probe_output_device = None
    try:
        from _live import _host_api_rank
    except Exception:
        _host_api_rank = lambda i: 2      # noqa: E731
    mme = _mme_map()

    rows = []
    for endpoint_id, short, full in _registry_endpoints():
        # 🔴 2026-09-20 筆電實測 N1：先直接問 Windows 這個端點是哪一個 MME 編號（見 _live.mme_endpoint_map）。
        #    上一版改成「名稱完全相同的排前面」，完整名稱超過 31 字時就對到 DirectSound，而 DirectSound
        #    阻塞寫入沒聲音：電視當②，試聽和口譯整場都沒聲音，畫面還說有播。前一版（比開頭）剛好對到 MME 才正常。
        #    問得到就只用 MME 那一個——那一個開不起來就算這條路線不能播，不退到會「假裝有播」的 DirectSound。
        mi = mme.get(endpoint_id.lower())
        if mi is not None and any(i == mi for i, _ in outs):
            cands = [(i, n) for i, n in outs if i == mi]
        else:                             # 問不到 Windows：用名稱配對，MME 優先、DirectSound 最後
            cands = [(i, n) for i, n in outs if _same_endpoint_name(n, full)]
            cands.sort(key=lambda c: (_host_api_rank(c[0]), c[1].strip().lower() != full.strip().lower()))
        exact = bool(cands)
        if not cands:                     # 登錄檔沒有介面名稱等：退回「裝置描述是名稱開頭」
            key = short.strip().lower()
            cands = [(i, n) for i, n in outs if n.strip().lower().startswith(key)]
            cands.sort(key=lambda c: _host_api_rank(c[0]))
        if not cands:
            continue
        idx, name = cands[0]
        speakable = True
        if probe_speak and probe_output_device:
            # DirectSound 開得起來卻沒聲音（開開看測不出來），不算「播得出來」
            ok = next(((i, n) for i, n in cands
                       if _host_api_rank(i) < 3 and probe_output_device(i)[0]), None)
            speakable = ok is not None
            if ok:
                idx, name = ok
        if defaults:
            is_default = defaults.get(0) == endpoint_id
        else:                             # 問不到 Windows：退回名稱比對
            dn = default_name.strip().lower()
            is_default = (full.strip().lower() == dn if exact
                          else short.strip().lower() == dn[:len(short.strip())])
        rows.append({
            "id": endpoint_id,
            # 顯示用名稱用登錄檔那個乾淨的（「喇叭」），不要用 MME 截短過的；同名時下面改成完整名稱
            "name": short,
            "full_name": full,
            # 傳給 --speak-device 用的。問得到 Windows 時傳端點 ID：子程式照同一個端點重新對到 MME 編號，
            # 不靠名稱（MME 截字名稱可能兩顆一樣，完整名稱又只對得到 DirectSound）
            "device_name": endpoint_id if mi is not None and idx == mi else name,
            "sd_index": idx,
            "is_default": is_default,
            "speakable": speakable,
        })
    names = [r["name"].strip().lower() for r in rows]
    for r in rows:
        if names.count(r["name"].strip().lower()) > 1:
            r["name"] = r["full_name"]
    return rows


def _mme_map():
    """{音訊端點 ID（小寫）: MME 播放編號}，見 _live.mme_endpoint_map。問不到回 {}（測試可以換掉這個）。"""
    try:
        from _live import mme_endpoint_map
        return mme_endpoint_map()
    except Exception:
        return {}


def _same_endpoint_name(sd_name, full):
    """sounddevice 的名稱是不是這個端點的完整名稱（MME 會截成 31 個字，截過的也算）。
    只在問不到 Windows（mme_endpoint_map 失敗）時才用得到。V1.31：比之前先清掉看不見的字元、全形半形、大小寫
    （見 _live.norm_device_name；09-28 同事那台登錄檔的名稱開頭多一格空白）。"""
    try:
        from _live import norm_device_name as norm
    except Exception:
        norm = lambda s: str(s or "").strip().lower()      # noqa: E731
    a, b = norm(sd_name), norm(full)
    return a == b or (len(sd_name.strip()) >= _MME_NAME_LEN and b.startswith(a))


def play_test_tone(sd_index, seconds=1.0, freq=880):
    """對指定裝置播一聲，讓使用者用耳朵確認這條路線聽不聽得到。回 (成功?, 錯誤訊息)。

    用裝置自己的預設取樣率（不是 24kHz）：這裡只是要發出聲音，不必遷就 Live API 的規格，
    硬指定 24kHz 反而會在某些裝置上開不起來。
    """
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:
        return False, f"Missing package: {e}"
    try:
        info = sd.query_devices(sd_index)
        sr = int(info.get("default_samplerate") or 48000)
        ch = 1 if info.get("max_output_channels", 1) < 2 else 2
        t = np.arange(int(sr * seconds)) / sr
        # 兩端做淡入淡出，不然會有「啪」的爆音
        env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.05)
        wave = (0.25 * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        buf = np.tile(wave.reshape(-1, 1), (1, ch))
        with sd.OutputStream(device=sd_index, samplerate=sr, channels=ch,
                             dtype="float32", blocksize=1024) as s:
            s.write(buf)
        return True, ""
    except Exception as e:                       # noqa: BLE001
        return False, str(e)


def current_default_name():
    """系統預設播放裝置的名稱。

    🔴 不可以用 sounddevice 查：PortAudio 在行程啟動時就把裝置清單列好了，**切換預設
       裝置之後它還是回舊的那顆**（第一版就是這樣，切完讀回來以為沒切成功）。
       pyaudiowpatch 每次 new 一個 PyAudio 都會重新問一次 Windows，拿得到最新值。
    """
    try:
        import pyaudiowpatch as pa
        with pa.PyAudio() as p:
            w = p.get_host_api_info_by_type(pa.paWASAPI)
            return p.get_device_info_by_index(w["defaultOutputDevice"])["name"]
    except Exception:
        pass
    try:
        import sounddevice as sd
        return sd.query_devices(kind="output")["name"]
    except Exception:
        return None


def find_route(rows, name_or_id):
    """用 endpoint id 或名稱片段找回某一列。找不到回 None。"""
    if not name_or_id:
        return None
    key = str(name_or_id).strip().lower()
    for r in rows:
        if r["id"].lower() == key:
            return r
    for r in rows:
        if key in r["name"].lower():
            return r
    return None


# ── 切換與還原 ──────────────────────────────────────────────────────────────
_restore_to = None          # 這個行程切換前，原本的預設是哪顆（「一般」角色）
_restore_name = None
_restore_roles = None       # {角色: 原本的端點}：三個角色各自記、各自改回（見 switch_to）


def _set_roles(roles):
    """把每個角色改回各自原本的端點。同一顆的角色一起設。成功回 None，失敗回第一個錯誤。"""
    groups = {}
    for role, eid in roles.items():
        groups.setdefault(eid, []).append(role)
    first_err = None
    for eid, rs in groups.items():
        err = (set_default_endpoint(eid) if sorted(rs) == sorted(_ROLES)
               else set_default_endpoint(eid, roles=tuple(sorted(rs))))
        first_err = first_err or err
    return first_err


def _refresh_sounddevice():
    """切換預設裝置之後，逼 sounddevice 重新問一次 Windows。

    🔴 PortAudio 在行程啟動時就把裝置清單和「哪顆是預設」讀好了，之後**不會更新**。
       不重新初始化的話 `_live.default_output_name()` 會一直回切換前的那顆，
       `is_default_like()` 就拿錯的裝置去比——實際後果是正確的設定（原音走沒接線的
       數位輸出、口譯走喇叭）會被誤判成「翻譯播回系統預設」而被擋下來，整個模式開不了。
       切換一定發生在任何串流開啟之前，所以這裡重新初始化是安全的。
       （2026-09-18 實測抓到：切到 SPDIF 之後，裝置清單仍把「喇叭」標成系統預設。）
    """
    # 🔴 關閉和重新初始化要分開包：同一個 try 的話，某次重新初始化失敗之後，之後每次都會在
    #    關閉那一步就出錯、永遠走不到重新初始化，這個選單視窗就一直查不到裝置（2026-09-19 審查）。
    try:
        import sounddevice as sd
    except Exception:
        return
    try:
        sd._terminate()
    except Exception:
        pass
    try:
        sd._initialize()
    except Exception:
        pass


def switch_to(endpoint_id, name=None):
    """把預設輸出切到 endpoint_id，並記下原本那顆。成功回 None，失敗回錯誤字串。

    🔴 狀態檔要在「切換之前」寫：先切後寫的話，切完到寫好之間當掉或被砍，就沒有任何紀錄能還原。
    🔴 三個角色（一般／多媒體／通訊）要各自記原本那顆：使用者可能另外設過「預設通訊裝置」，
       全部改回同一顆會把它蓋掉（2026-09-19 審查）。
    🔴 查不到原本的預設是哪顆就**不要切**：切了卻沒記下要改回哪裡，結束時就改不回來、也不會有任何提示。
    """
    global _restore_to, _restore_name, _restore_roles
    rows = list_routes()
    ids = default_endpoint_ids()
    roles = {r: ids[r] for r in _ROLES if ids and ids.get(r)}
    if 0 not in roles:                    # 問不到 Windows：退回用名稱找「目前的預設」，三個角色當成同一顆
        before = next((r for r in rows if r["is_default"]), None)
        if before is None:
            return "Could not find out which device is the current default playback device, so the program could not note which one to switch back to at the end"
        roles = {r: before["id"] for r in _ROLES}
    # 某個角色查不到（Windows 回空）：當成跟一般角色同一顆。下面會把三個角色都切到①，
    # 沒記到的角色結束時就改不回來（2026-09-19 第二次審查）；最差也就是舊版「全部改回同一顆」
    roles = {r: roles.get(r, roles[0]) for r in _ROLES}
    if all(v == endpoint_id for v in roles.values()):
        return None                       # 已經是這顆，不用切、也不必記還原
    back = next((r for r in rows if r["id"] == roles[0]), None)
    _restore_to, _restore_roles = roles[0], dict(roles)
    _restore_name = back["name"] if back else "the original speakers"
    try:
        with open(_state_path(create=True), "w", encoding="utf-8") as f:
            json.dump({"restore_to": roles[0], "restore_roles": {str(k): v for k, v in roles.items()},
                       "name": _restore_name, "switched_to": name or endpoint_id,
                       "pid": os.getpid(), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "at_epoch": time.time()},
                      f, ensure_ascii=False)
    except OSError:
        pass                              # 狀態檔只是保險，寫不成也不該擋住會議
    err = set_default_endpoint(endpoint_id)
    if err:
        # 🔴 可能切到一半（一般角色切過去了、下一個角色才失敗）：問一次 Windows，把已經切過去的角色改回來。
        #    改回也失敗就留著狀態檔，下次打開程式由 recover_if_needed 再試（2026-09-19 第二次審查）。
        #    問不到 Windows 就不動（分不出有沒有切到，亂改回去反而多一句誤導的錯誤）。
        now = default_endpoint_ids()
        changed = {r: v for r, v in roles.items() if now.get(r) != v} if now else {}
        rb = _set_roles(changed) if changed else None
        _restore_to = _restore_name = _restore_roles = None
        if rb:
            return f"{err}; switching back to the original device also failed ({rb}); it will be tried again the next time the program opens"
        _clear_state()
        return err
    _refresh_sounddevice()
    return None


def restore(refresh=True):
    """還原成切換前的那顆。沒切過就什麼都不做。回 (有沒有動作, 名稱或錯誤)。

    🔴 這個函式會被三條路徑呼叫（正常結束／Ctrl+C／視窗被關掉），必須可以重複呼叫。
    🔴 視窗被關掉時要傳 refresh=False：那時口譯語音可能還在播，重啟聲音元件（Pa_Terminate）
       會拆掉播放執行緒正在寫的串流 → python.exe 當掉（實測 0.5 秒一段 4/10、2 秒一段 7/10；
       不重啟 0/20）。反正行程馬上就要被 Windows 結束，不需要重啟。
    """
    global _restore_to, _restore_name, _restore_roles
    if not _restore_to:
        # 沒切過就什麼都不碰——連狀態檔也不刪：那可能是另一個視窗的口譯正在用的，
        # 刪掉之後它萬一當掉，就再也沒有紀錄能還原
        return False, None
    target, name, roles = _restore_to, _restore_name, _restore_roles
    _restore_to = _restore_name = _restore_roles = None    # 先清掉，避免重入時又跑一次
    err = _set_roles(roles) if roles else set_default_endpoint(target)
    if not err:
        _clear_state()          # 🔴 改回失敗就留著狀態檔：下次打開程式由 recover_if_needed 再試一次（2026-09-19 審查）
    if refresh:
        _refresh_sounddevice()
    return (True, name) if not err else (True, f"Restore failed: {err}")


def _clear_state():
    try:
        os.remove(_state_path())
    except OSError:
        pass


def _owner_running(pid, at_epoch):
    """寫狀態檔的那個行程是不是還活著。

    🔴 不能只看「這個編號的行程在不在」：Windows 會回收行程編號，當機留下的狀態檔可能剛好對到
       一個不相干的新行程，結果永遠不還原（這個專案 2026-09-15 在暫存檔清理上踩過同一個坑）。
       所以同時比「那個行程的建立時間」：必須早於寫狀態檔的時間，才算同一個行程。
    """
    if not pid or sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    h = k32.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:   # STILL_ACTIVE
            return False
        if not at_epoch:
            return True                   # 舊版狀態檔沒有時間，只能相信編號
        ft = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
            return True
        created = ((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime) / 1e7 - 11644473600
        return created <= float(at_epoch) + 1
    finally:
        k32.CloseHandle(h)


def recover_if_needed():
    """開機／開程式時呼叫：上次沒還原成功的話，現在補還原。

    回 None 代表沒事；否則回一段可以直接印給使用者看的說明。
    """
    path = _state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        _clear_state()
        return None
    target = st.get("restore_to")
    name = st.get("name") or "the original device"
    if not target:
        _clear_state()
        return None
    at = st.get("at_epoch")
    if at is None:                        # 舊版寫的狀態檔沒有時間：用檔案本身的修改時間（就是寫入的時間）
        try:
            at = os.path.getmtime(path)
        except OSError:
            at = None
    if st.get("pid") != os.getpid() and _owner_running(st.get("pid"), at):
        return None                       # 另一個視窗的口譯還在進行，路線是它的，不要動
    roles = {}
    for k, v in (st.get("restore_roles") or {}).items():      # 新版狀態檔：三個角色各自記
        try:
            roles[int(k)] = v
        except (TypeError, ValueError):
            pass
    now_ids = default_endpoint_ids()
    if roles:
        if now_ids and all(now_ids.get(r) == v for r, v in roles.items()):
            _clear_state()                # 已經是對的了（使用者自己切回來過）
            return None
        # 問不到 Windows 也照記下的各角色改回：重設成同一顆沒有副作用。🔴 不可以退回下面只比「一般」角色，
        # 一般角色對了就清檔，另外兩個角色就永遠停在①（2026-09-19 第二次審查）
    else:                                 # 舊版狀態檔：只有一顆
        rows = list_routes()
        now = next((r for r in rows if r["is_default"]), None)
        if now and now["id"] == target:
            _clear_state()                # 已經是對的了（使用者自己切回來過）
            return None
    err = _set_roles(roles) if roles else set_default_endpoint(target)
    _clear_state()
    if err:
        return (f"The last session did not end cleanly: the sound output may still be on \"{st.get('switched_to', 'another route')}\", and switching it back automatically failed ({err}). Please click the speaker icon at the bottom right and switch back to \"{name}\" yourself.")
    return f"The last session did not end normally; the sound output has been switched back to \"{name}\"."
