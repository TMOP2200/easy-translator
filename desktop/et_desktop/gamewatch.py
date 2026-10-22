# -*- coding: utf-8 -*-
"""打游戏时自动暂停取词 —— 由本程序**自己**检测，不依赖任何外部看门狗。

判定（`decide()` 是纯函数，单测直接覆盖）：

  ① 前台窗口盖住整块屏幕（≥97%，含无边框全屏）；
  ② 它不属于本程序自己 / 桌面外壳 / 输入法（见 IGNORE）；
  ③ 显卡 3D 引擎利用率 ≥ GPU_MIN（默认 30%）—— 优先用 Windows 自带的 GPU 性能
     计数器（PDH，NVIDIA/AMD/Intel 全有效）；老系统退回 nvidia-smi；全都量不到
     就不判「在游戏」（没数据不误停，见 decide 的 None 分支）。

三条同时成立 = 在打游戏 → 整条取词链停工。这是**纯内存**检测（进程内状态，不写任何标记文件）：
拿不到全屏或显卡判据时就当没在玩，绝不会因此卡住取词。

为什么不只看 ③：本程序自己的视觉模型跑 OCR 时显卡也会高 —— 但它不是全屏前台。
为什么不只看 ①：全屏看视频 / 全屏投屏也会命中 —— 加 ③ 过滤：视频硬解算在
VideoDecode 引擎上，而 ③ 只看 3D 引擎，天然分得开。
进入立刻停工；**退出要连续 RESUME_N 次采样都不满足才恢复**（游戏菜单/加载时显卡会掉下来，
只看单次采样会「停一会儿又开工」来回抖；重新进入时计数清零，防抖动凑数）。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time

POLL = 8                # 采样间隔（秒）
GPU_MIN = 30            # 显卡利用率阈值（%）
FULL_MIN = 0.97         # 前台窗口占屏幕比例，≥ 才算全屏
RESUME_N = 2            # 连着几次采样都不像游戏，才恢复取词

# 桌面外壳 / 输入法：它们铺满屏幕是正常现象，别当成游戏
IGNORE = {"explorer.exe", "searchhost.exe", "shellexperiencehost.exe",
          "startmenuexperiencehost.exe", "textinputhost.exe",
          "applicationframehost.exe", "sihost.exe"}


def decide(full_cover: float, exe: str, own: bool, gpu, caption: bool = False,
           gpu_min: int = GPU_MIN, full_min: float = FULL_MIN) -> bool:
    """几条判据的合成 —— 纯函数，喂合成数据就能测。

    caption = 前台窗口有没有标题栏：**带标题栏的最大化窗口不算全屏应用**
    （否则「最大化浏览器 + 自家模型在跑」会被误判成游戏）。
    """
    if own:
        return False
    if (exe or "").lower() in IGNORE:
        return False
    if full_cover < full_min:
        return False
    if caption and full_cover < 1.0:
        return False                    # 有标题栏又没铺满整屏 → 只是个最大化窗口
    if gpu is None:
        return False                    # 量不到显卡（老系统/异常）：宁可不暂停，也不误停
    return gpu >= gpu_min


# ————————————————————————— 拿系统数据 —————————————————————————

class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def _bind_user32():
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    u.MonitorFromWindow.restype = ctypes.c_void_p
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
    gl = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
    if gl is getattr(u, "GetWindowLongPtrW", None):
        gl.restype = ctypes.c_void_p            # 64 位句柄，别被截断
    else:
        gl.restype = ctypes.c_long
    gl.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return u


def foreground_info():
    """前台窗口：(盖住屏幕的比例, 进程 exe 名, 是不是自己, 有没有标题栏)。

    任何一步出错都返回 (0.0, "", False, True) —— 视同「不是游戏」，绝不抛。
    """
    try:
        u = _bind_user32()
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return 0.0, "", False, True
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        own = (pid.value == os.getpid())
        caption = bool(u.GetWindowLongPtrW(ctypes.c_void_p(hwnd), -16) & 0x00C00000)  # WS_CAPTION
        r = _RECT()
        if not u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r)):
            return 0.0, "", own, caption
        mon = u.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)      # NEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not mon or not u.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
            return 0.0, "", own, caption
        m = mi.rcMonitor
        w = min(r.right, m.right) - max(r.left, m.left)
        h = min(r.bottom, m.bottom) - max(r.top, m.top)
        area = max(1, (m.right - m.left)) * max(1, (m.bottom - m.top))
        cover = max(0.0, w) * max(0.0, h) / float(area)
        return cover, _exe_of(pid.value), own, caption
    except Exception:
        return 0.0, "", False, True


def _exe_of(pid: int) -> str:
    try:
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                 ctypes.c_wchar_p,
                                                 ctypes.POINTER(ctypes.c_ulong)]
        h = k.OpenProcess(0x1000, 0, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            n = ctypes.c_ulong(512)
            if k.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value)
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        pass
    return ""


_gpu_cache = {"t": 0.0, "v": None}
_pdh = {"ready": False, "query": None, "counter": None}

_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2


class _PDH_FMT_CV(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]


class _PDH_FMT_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PDH_FMT_CV)]


def _pdh_init():
    """打开一次 GPU 引擎计数器查询（用英文计数器名，中文系统也能加）。成功 True。"""
    if _pdh["ready"]:
        return _pdh["query"] is not None
    _pdh["ready"] = True
    try:
        p = ctypes.windll.pdh
        p.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_void_p)]
        p.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                            ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        p.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        q = ctypes.c_void_p()
        if p.PdhOpenQueryW(None, 0, ctypes.byref(q)) != 0:
            return False
        c = ctypes.c_void_p()
        if p.PdhAddEnglishCounterW(q, r"\GPU Engine(*)\Utilization Percentage",
                                   0, ctypes.byref(c)) != 0:
            p.PdhCloseQuery(q)
            return False
        _pdh["query"], _pdh["counter"] = q, c
        # 差值型计数器：连续采两次才有值（打底 + 等一小口）—— 只在初始化时付这一次
        p.PdhCollectQueryData(q)
        time.sleep(0.15)
        p.PdhCollectQueryData(q)
        return True
    except Exception:
        _pdh["query"] = _pdh["counter"] = None
        return False


def _gpu_pdh():
    """Windows 自带 GPU 性能计数器：汇总所有 engtype_3D 实例的利用率（0-100）。

    对 NVIDIA / AMD / Intel 全有效、不依赖任何厂商工具、不起子进程。
    视频硬解走 VideoDecode 引擎，不会计进来 —— 正是「全屏看电影别误判成打游戏」
    需要的那点分离度。量不到（老系统/异常）→ None。
    """
    try:
        if not _pdh_init():
            return None
        p = ctypes.windll.pdh
        if p.PdhCollectQueryData(_pdh["query"]) != 0:
            return None
        p.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                   ctypes.POINTER(ctypes.c_ulong),
                                                   ctypes.POINTER(ctypes.c_ulong),
                                                   ctypes.c_void_p]
        p.PdhGetFormattedCounterArrayW.restype = ctypes.c_long
        size, count = ctypes.c_ulong(0), ctypes.c_ulong(0)
        rc = p.PdhGetFormattedCounterArrayW(_pdh["counter"], _PDH_FMT_DOUBLE,
                                            ctypes.byref(size), ctypes.byref(count), None)
        if (rc & 0xFFFFFFFF) != _PDH_MORE_DATA or size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        rc = p.PdhGetFormattedCounterArrayW(_pdh["counter"], _PDH_FMT_DOUBLE,
                                            ctypes.byref(size), ctypes.byref(count), buf)
        if rc != 0:
            return None
        stride = ctypes.sizeof(_PDH_FMT_ITEM_W)
        total = 0.0
        for i in range(count.value):
            it = _PDH_FMT_ITEM_W.from_buffer(buf, i * stride)
            if it.szName and "engtype_3D" in it.szName and it.FmtValue.CStatus == 0:
                total += it.FmtValue.doubleValue
        return max(0.0, min(100.0, total))
    except Exception:
        return None


def _gpu_smi():
    """兜底：老系统上 PDH 没有 GPU 计数器时，NVIDIA 机器用 nvidia-smi（带 30 秒缓存）。"""
    now = time.time()
    if now - _gpu_cache["t"] < 30:
        return _gpu_cache["v"]
    v = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        v = int((out.stdout or "").strip().splitlines()[0])
    except Exception:
        v = None
    _gpu_cache["t"], _gpu_cache["v"] = now, v
    return v


def gpu_util():
    """GPU 3D 利用率（%）；两种方式都量不到 → None（调用方按「没数据就不暂停」处理）。"""
    v = _gpu_pdh()
    if v is not None:
        return v
    return _gpu_smi()


# ————————————————————————— 后台采样 —————————————————————————

_lock = threading.Lock()
_state = {"gaming": False, "thread": None, "getter": None}


def sample(getter=None) -> bool:
    """采一次样并更新状态（供线程与测试调用）。"""
    try:
        info = foreground_info()
        cover, exe, own = info[0], info[1], info[2]
        caption = info[3] if len(info) > 3 else True
        cov = cover
        if getter is not None:
            try:
                if not getter():
                    cov = 0.0                      # 用户在「通用」里关掉了自动暂停
            except Exception:
                pass
        gaming = decide(cov, exe, own, gpu_util(), caption=caption)
    except Exception:
        gaming = False
    with _lock:
        prev = _state["gaming"]
        if gaming:
            # 重新进入游戏：退出计数必须清零 —— 否则 T,F,T,F 这种抖动会在
            # 最后一个 F 就凑满 RESUME_N，提前复工（正是要防的来回抖）。
            _state["_calm"] = 0
            _state["gaming"] = True
            if not prev:
                _log("全屏应用检测：进入（前台全屏 + 显卡繁忙）→ 取词停工")
        elif prev:
            # 退出要连着 RESUME_N 次都不像游戏（防菜单/加载时来回抖）
            _state["_calm"] = _state.get("_calm", 0) + 1
            if _state["_calm"] >= RESUME_N:
                _state["gaming"] = False
                _state["_calm"] = 0
                _log("全屏应用检测：退出 → 取词恢复")
        else:
            _state["_calm"] = 0
    return _state["gaming"]


def start(getter=None):
    """起采样线程（可重复调用，只有第一个生效）。getter 每轮读一次（配置热加载）。"""
    with _lock:
        if _state["thread"] is not None:
            return
        if getter is not None:
            _state["getter"] = getter
        th = threading.Thread(target=_loop, daemon=True, name="et-gamewatch")
        _state["thread"] = th
    th.start()


def _loop():
    while True:
        try:
            sample(_state.get("getter"))
        except Exception:
            pass
        time.sleep(POLL)


def is_gaming() -> bool:
    """现在是否在打游戏（进程内检测，纯内存态：不读、不写任何标记文件）。"""
    with _lock:
        return bool(_state["gaming"])


def _log(msg: str):
    try:
        print("[gamewatch] " + msg, file=sys.stderr, flush=True)
    except Exception:
        pass
