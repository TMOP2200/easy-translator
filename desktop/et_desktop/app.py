# -*- coding: utf-8 -*-
"""
Easy Translator 桌面伴生：整台电脑的悬停查词。

用法：
    python -m et_desktop                 # 桌面 App：弹出控制窗口（顶上一颗大开关）并开始监听
    python -m et_desktop --selftest      # 自检：UIA 取词 + 渲染 + 引擎连通
    python -m et_desktop --settings      # 只开控制窗口，不监听（不抢单实例锁）
    python -m et_desktop --daemon        # 只监听不弹窗（开机自启用）

单实例：默认模式与 --daemon 抢**同一把锁**。已经有一个实例在跑时，再双击 App 不会起第二个监听，
只写一个「请弹窗」标记（%APPDATA%\EasyTranslator\show.flag），由在跑的那个把控制窗口弹出来。
窗口右上角「×」只是收起来，监听继续；要真的退出用窗口底部的「退出桌面取词」。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

from PIL import Image

# Windows 高 DPI：声明统一挪到 main() 开头（_enable_dpi_awareness）。
# 这里曾经在**导入时**就调 SetProcessDpiAwareness(1) —— DPI 感知每进程只能设一次，
# 那会把后面的 per-monitor v2 永久挡掉（混合缩放副屏上坐标/渲染错位）。
# 模块导入阶段不取任何坐标，无需在此声明。

try:
    import tkinter as tk
except Exception:                                   # pragma: no cover
    tk = None

from . import gamewatch, lookup, settings_ui, textgrab, ui

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MASCOT = os.path.join(REPO, "assets", "mascot.png")
CFG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EasyTranslator", "config.json")
CFG_DIR = os.path.dirname(CFG_PATH)
# 「请把控制窗口弹出来」的标记文件（存在即请求，读到即删）。
# 双击桌面 App 时，如果已有实例在跑（多半是开机自启的那个隐藏守护），新进程只写这个文件就退出，
# 由在跑的实例弹窗 —— 否则两个进程会各建一份监听、各弹各的卡片（实测过的双开）。
# 与「请窗口弹出来」的 show.flag 是同一类跨进程信号：存在即命令、读到即删、读写都永不抛。
SHOW_FLAG = os.environ.get("ET_SHOW_FLAG") or os.path.join(CFG_DIR, "show.flag")
DAEMON_MUTEX = "EasyTranslatorDaemonMutex"

# 字段名与 lib/settings-core.js 的 DEFAULTS 保持一致 —— 两端各叫各的就会漂移，
# desktop/tests/test_settings.py 会拿 JS 侧逐键比对。
DEFAULTS = {
    "enabled": True,
    "dwellMs": 5000,
    "engine": "auto",
    "examplesCount": 3,
    "showSpeak": True,
    "gameAutoPause": True,       # 打游戏时自动暂停（本程序自己检测：前台全屏 + 显卡占用）
    "logWords": False,           # 日志是否记录悬停到的单词（默认关：日志会被发送给排障者）
    "model": {"enabled": False, "baseUrl": "http://127.0.0.1:11434/v1", "apiKey": "",
              "textModel": "qwen2.5:1.5b", "visionModel": "qwen2.5vl:3b", "timeoutMs": 60000,
              "ollamaExe": ""},
    "imageOcr": {"enabled": True, "dwellMs": 1500, "cropW": 460, "cropH": 140, "hint": True},
}

# 老配置文件里的旧字段名 → 新名（读到就搬过来，避免升级后设置"失踪"）
_LEGACY = {"dwell": "dwellMs", "showExamples": "examplesCount"}


def _merge(base: dict, extra: dict) -> dict:
    out = json.loads(json.dumps(base))
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load_cfg() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        for old, new in _LEGACY.items():             # 老字段名平移
            if old in user and new not in user:
                user[new] = user.pop(old)
        if "dwell" in user:                          # 老的是「秒」，新的是毫秒
            try:
                user["dwellMs"] = int(float(user.pop("dwell")) * 1000)
            except Exception:
                user.pop("dwell", None)
        cfg = _merge(cfg, user)
    except Exception:
        pass
    # 数值兜底：坏值（手改配置写错类型）不能掀翻启动 —— 每个都单独兜住
    for _k, _lo, _hi, _dflt in (("dwellMs", 1000, 15000, 5000),
                                ("examplesCount", 0, 5, 3)):
        try:
            cfg[_k] = max(_lo, min(_hi, int(float(cfg.get(_k)))))
        except Exception:
            cfg[_k] = _dflt
    return cfg


def save_cfg(cfg: dict):
    """原子写（临时文件 + replace）。

    别的进程随时可能在读这个文件（配置热加载），直接覆盖会撞上「读到一半的 JSON」——
    load_cfg 解析失败就退回默认值，用户改过的设置会整片丢掉。
    """
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        tmp = CFG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_PATH)
    except Exception:
        pass


def _show_flag_paths():
    """「请弹窗」标记的两条查找路径（环境变量 + 默认目录）—— 换一种启动方式也要生效。"""
    out = []
    for p in (os.environ.get("ET_SHOW_FLAG"), SHOW_FLAG):
        if p and p not in out:
            out.append(p)
    return out


def request_show() -> bool:
    """请已在运行的实例把控制窗口弹出来（双击 App、但它已经在跑时走这条）。永不抛。"""
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
    except Exception:
        pass
    for p in _show_flag_paths():
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("1")
            return True
        except Exception:
            continue
    return False


def take_show_request() -> bool:
    """取出弹窗请求（读到即删）。每 600ms 被调一次，必须永不抛。"""
    got = False
    for p in _show_flag_paths():
        try:
            if os.path.exists(p):
                os.remove(p)
                got = True
        except Exception:
            pass
    return got


def acquire_single_instance():
    """抢单实例锁：拿到返回句柄（必须一直持有到进程结束），已被占用返回 None，查不了返回 True。

    窗口模式与 --daemon 抢的是**同一把**锁 —— 否则「开机自启的隐藏守护 + 双击桌面 App」
    会变成两个监听进程：同一处弹两张卡片、UIA 轮询开销翻倍。
    句柄不能丢（被 GC 掉锁就释放了），所以由调用方一直引用着。

    ⚠ 两个坑（2026-10-03 加固；`restype` 那个是照 memory 里记的同类事故一并填的）：
      · `CreateMutexW` 不声明 `restype` → 64 位下句柄可能被**按 c_int 截断**（本次没实测到，
        但这台机器上 ctypes 句柄截断已经坑过一次，见 DeleteObject）；
      · `ctypes.windll` 默认 `use_last_error=False` → 紧接 `GetLastError()` 读到的**不一定**是
        这次调用留下的错（ctypes 内部/属性查找都可能动它）。锁本来就判得对（实测第二个实例
        1 秒内自己退出），但这么写迟早会在某些调用序下失灵，所以改成官方写法：
        `WinDLL(..., use_last_error=True)` + `ctypes.get_last_error()` + 声明 `argtypes/restype`。

    ⚠ 别把「两个 pythonw.exe」当成两个守护：这个 venv 里的 `Scripts\\pythonw.exe` 是**转发器**
    （263KB，系统那份 101KB），它会再拉起基础解释器的子进程 ——
    **一父一子两个 pythonw = 一个守护**（父=转发器，子=真身，`-m et_desktop --daemon` 都在）。
    """
    try:
        import ctypes as _ct
        from ctypes import wintypes
        k32 = _ct.WinDLL("kernel32", use_last_error=True)      # 关键：拿错误要显式走 use_last_error
        k32.CreateMutexW.restype = wintypes.HANDLE             # 关键：别让 64 位句柄被截断
        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        h = k32.CreateMutexW(None, False, DAEMON_MUTEX)
        if not h:
            return True                                        # 建不出来就别把功能挡死
        if _ct.get_last_error() == 183:                        # ERROR_ALREADY_EXISTS
            return None
        return h
    except Exception:
        return True                              # 查不了就别把功能挡死


def _setup_logfile(tag="daemon start"):
    """没有控制台（pythonw）时把 stderr 落到 daemon.log。

    Tk 主循环回调异常、线程异常、excepthook 全经 stderr —— 不落文件的话，
    崩溃后只剩「它怎么不出卡片了」，一点线索都没有。
    """
    try:
        if getattr(sys, "frozen", False):
            # 打包成 exe 后，__file__ 在临时解包目录里（退出即删）→ 日志必须落到配置目录
            base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EasyTranslator")
            os.makedirs(base, exist_ok=True)
        else:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
        log_path = os.path.abspath(os.path.join(base, "daemon.log"))
        try:
            if os.path.exists(log_path) and os.path.getsize(log_path) > 1_000_000:
                os.remove(log_path)              # 轮转：太大就从头写
        except Exception:
            pass
        logf = open(log_path, "a", encoding="utf-8")
        logf.write("\n=== %s %s ===\n" % (tag, time.strftime("%Y-%m-%d %H:%M:%S")))
        logf.flush()
        sys.stderr = logf

        def _excepthook(t, v, tb):
            import traceback as _tb
            _tb.print_exception(t, v, tb, file=logf)
            logf.flush()
        sys.excepthook = _excepthook
        return logf
    except Exception:
        return None


def _enable_dpi_awareness():
    """声明进程 DPI 感知 —— 必须在任何取坐标之前调用。

    不声明时（150% 缩放的笔记本屏上）：GetCursorPos / UIA 给的是**逻辑坐标**
    （1707×1067），而 PIL 的 ImageGrab(all_screens=True) 给的是**物理坐标**
    （2560×1600），两套坐标差 1.5 倍 → OCR 截图中心整体偏移，红叉指到旁边的词，
    于是「鼠标在 desktop 上却翻译成 et」。声明后三套坐标统一为物理像素；
    顺带 _scale() 拿到真实 DPI，气泡按 1.5 倍渲染再 1:1 显示，更清晰。
    """
    try:
        import ctypes
        try:
            # Windows 10 1703+：per-monitor v2
            if ctypes.windll.user32.SetProcessDpiAwarenessContext(-4):
                return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()            # 老系统兜底
    except Exception:
        pass


def _set_app_user_model_id():
    """给进程一个自己的 AppUserModelID。

    不设的话，pythonw 启动的窗口在任务栏上会挂到**解释器**的身份上 —— 分组、跳转列表、
    以及图标都可能取 pythonw 自己的，用户看到的就是「任务栏图标和桌面图标不是一个」。
    必须在**建任何窗口之前**调用。
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "TMOP2200.EasyTranslator.Desktop")
    except Exception:
        pass


def cursor_pos():
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return 0, 0


def _lbutton_down():
    """左键是否正按下（无需焦点/钩子，轮询式全局检测）。"""
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
    except Exception:
        return False


def _elog(msg):
    """把「弹卡片 / 无释义 / 显示失败」这类关键动作写进 daemon.log（stderr 已重定向到那里）。"""
    try:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)
    except Exception:
        pass


def _foreground_hwnd():
    """当前前台窗口句柄（比较用）。出错返回 -1，永不抛。"""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        u32.GetForegroundWindow.restype = ctypes.c_void_p
        return u32.GetForegroundWindow() or 0
    except Exception:
        return -1


class Watcher(threading.Thread):
    """同词驻留计时：目标变化即重置；微动不打断；取不到词一律静默。"""

    def __init__(self, cfg, bubble_img, panel):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.render = bubble_img
        self.panel = panel
        self.word = None
        self.anchor = (0, 0)
        self.since = 0.0
        self._last_seen = 0.0
        self._dwell = 5.0
        self.shown = False
        self.lock = threading.Lock()
        self.stop_flag = False
        # 「停稳」追踪：把驻留时长算在光标停下来之后，而不是「识别到词之后」——
        # OCR 面识别本身要 1~2 秒，若再从识别完开始算 2 秒，总延迟就翻倍了。
        self._px, self._py = -9999, -9999
        self._stop_since = 0.0
        self._fg = -1                  # 上次扫描时的前台窗口（卡片挂着时用来判断「换了新界面」）
        self._mov = 8                  # 判定「移动了」的像素阈值（按屏幕 DPI 缩放）
        try:
            sc = ctypes.windll.user32.GetDpiForSystem() / 96.0
            self._mov = max(8, int(8 * sc))
        except Exception:
            pass

    def run(self):
        # UIA 依赖 COM：非主线程必须显式 CoInitialize，否则 uiautomation 每次调用都报
        # 「尚未调用 CoInitialize」并失败 → 文本取词全废、只能走 OCR 兜底。
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        while not self.stop_flag:
            time.sleep(0.06)           # 轮询间隔：取词结果有缓存，快轮询 = 反应更跟手
            if not self.cfg.get("enabled", True):
                # 总开关关掉：与「打游戏停工」同一套动作 —— 立刻收起卡片、清掉当前词，
                # 并放慢到 200ms（关着的时候没必要 60ms 轮询；重新打开 ≤200ms 就恢复）。
                with self.lock:
                    if self.shown:
                        self.shown = False
                        self._schedule_hide()
                    self.word = None
                time.sleep(0.2)
                continue
            if textgrab.gaming_now():
                # 打游戏：整条取词链停工。UIA 单次要走一遍控件树（实测 ~500ms），
                # 而这里是 60ms 轮询一次 —— 那才是游戏期间的主要开销；OCR 另外还抢显存。
                # 收起已有卡片，之后约 1 秒探一次（只查文件是否存在，几乎不占 CPU）。
                with self.lock:
                    if self.shown:
                        self.shown = False
                        self._schedule_hide()
                    self.word = None
                time.sleep(0.9)
                continue
            x, y = cursor_pos()
            t_poll = time.time()
            # 光标停稳了吗？（相对上次停稳点移动超过阈值 = 重新计停稳起点）
            if abs(x - self._px) > self._mov or abs(y - self._py) > self._mov:
                self._px, self._py, self._stop_since = x, y, t_poll
            with self.lock:
                if self.shown:
                    # 快速收起：光标明显移开或单击 → 立即收起，不等下面那轮可能耗时 1-2 秒的
                    # OCR。但只要光标还在气泡上／气泡附近（用户正想过去看或点复制），就不收起。
                    pinned = self.panel.is_pinned()
                    moved = abs(x - self.anchor[0]) > 32 or abs(y - self.anchor[1]) > 32
                    near = False
                    try:
                        near = self.panel.point_in_bubble(x, y)
                    except Exception:
                        near = False
                    if not pinned and not near and (moved or _lbutton_down()):
                        self.shown = False
                        self.word, self.since = None, t_poll
                        self._schedule_hide()
                        continue
            if self.shown:
                # 卡片挂着时（用户正在读、或正要过去点复制）不必每个 tick 都扫。
                # 鼠标没动、前台窗口也没换 → 光标底下的词不可能变 —— 直接跳过这次
                # UIA 走树（单次要 ~500ms），把「卡片挂着的整段时间」的占用省掉。
                if (abs(x - self._px) <= 3 and abs(y - self._py) <= 3
                        and _foreground_hwnd() == self._fg):
                    time.sleep(0.12)
                    continue
            self._busy_since = time.time()
            try:
                word, src = textgrab.word_at_point(x, y, self.cfg)
            finally:
                self._busy_since = 0.0
            self._fg = _foreground_hwnd()       # 记下这次扫描时的前台窗口
            now = time.time()
            with self.lock:
                if not word:
                    # 瞬时取不到词（焦点瞬变 / 光标微动到词缝）不立即重置计时；
                    # 超过 0.8s 宽限期才清空。气泡钉在鼠标下时（pinned）不收起。
                    if self.word is None or now - self._last_seen > 0.8:
                        if self.shown and not self.panel.is_pinned():
                            self.shown = False
                            self._schedule_hide()
                        self.word = None
                    continue
                self._last_seen = now
                if word != self.word:
                    # 鼠标移到了别的词（或从别处回来）：收起旧气泡，重新驻留
                    if self.shown:
                        self.shown = False
                        self._schedule_hide()
                    # OCR 取词用图片取词自己的驻留时长（与浏览器扩展一致：默认 1.5s）
                    if src == "ocr":
                        self._dwell = float((self.cfg.get("imageOcr") or {}).get("dwellMs", 1500)) / 1000.0
                    else:
                        self._dwell = float(self.cfg.get("dwellMs", 5000)) / 1000.0
                    self.word, self.anchor, self.since = word, (x, y), (self._stop_since or now)
                    continue
                if self.shown:
                    continue
                if now - self.since < self._dwell:
                    # 「不动才翻译」的计时重置**只由「词变了」触发**（见上面 word != self.word 分支）。
                    # 这里曾再按 12px 位移清零计时 —— 实测那是致命的：大字号（公式/幻灯片）下
                    # 鼠标"停住"时手抖 12px 太常见，计时被反复清零，卡片永远等不到
                    #（用户报「截屏/公式里的英文识别不了」，其实词早就读到了）。
                    continue
                self.shown = True
            threading.Thread(target=self._fire, args=(word, x, y, src), daemon=True).start()

    def _schedule_hide(self):
        try:
            self.panel.after(0, self.panel.hide_bubble)
        except Exception:
            pass

    def _fire(self, word, x, y, src):
        data = lookup.lookup(word, self.cfg)
        w_disp = repr(word) if self.cfg.get("logWords") else "（词已隐去，可在设置中开启记录）"
        if not lookup.has_definition(data):
            _elog("无释义不弹: %s (src=%s, 引擎=%s)" % (w_disp, src, (data or {}).get("source", "-")))
            return        # 查不到、或只有音标没有释义 → 静默，不弹空壳
        try:
            img = self.render(data, x, y)
            self._last_data = data
            self.panel.after(0, lambda: self.panel.show_bubble(img, x, y, word))
            _elog("弹卡片: %s ← %s (来源 %s)" % (w_disp, src, (data or {}).get("source", "-")))
        except Exception as exc:
            _elog("渲染/显示失败: %r (%r)" % ("（词已隐去）" if not self.cfg.get("logWords") else word, exc))


def selftest(cfg) -> int:
    """跑自检并把输出落到该去的地方。

    打包成 exe（--windowed）后**没有控制台**：`sys.stdout is None`，print 的东西会直接丢掉。
    所以那种情况下把输出接到内存、结束后写进 `%APPDATA%\\EasyTranslator\\selftest.txt`
    （使用说明里就是这么告诉用户的），出问题时至少有东西可查。
    """
    orig = sys.stdout
    buf = None
    for stream in (sys.stdout, sys.stderr):
        try:
            # 中文控制台（GBK）里 ✔ 这种符号会直接抛 UnicodeEncodeError 把自检打断 ——
            # 输出编码兜底：解不了就写个替代字符，别让「检查工具」自己先崩。
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if orig is None:
        import io as _io
        buf = _io.StringIO()
        sys.stdout = buf
    try:
        return _selftest_run(cfg)
    finally:
        if buf is not None:
            sys.stdout = orig
            try:
                os.makedirs(CFG_DIR, exist_ok=True)
                with open(os.path.join(CFG_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
                    f.write(buf.getvalue())
            except Exception:
                pass


def _selftest_run(cfg) -> int:
    print("== 自检 ==")
    ok = True

    decor_path = ui.decor_source()
    mascot = ui.load_decor(decor_path)
    if mascot is None:
        print(f"  装饰立绘: 没找到（{decor_path}）—— 卡片照画，只是不贴那张图 ✔")
    else:
        print(f"  装饰立绘: {mascot.size} ✔  ← {decor_path}")

    sample = {"word": "serendipity", "phonetics": {"uk": "/ˌserənˈdɪpəti/", "us": "/ˌserənˈdɪpəti/"},
              "poses": [{"pos": "n.", "meaning": "意外发现珍奇事物的天赋"}],
              "examples": [{"en": "A fortunate stroke of serendipity brought them together.",
                            "zh": "一次幸运的机缘让他们相遇。"}], "source": "自检样例"}
    img = ui.render_card(sample, mascot, scale=1.0)
    out = os.path.join(os.environ.get("TEMP", "."), "et-desktop-card-preview.png")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, (0, 0), img)
    bg.save(out)
    print(f"  气泡渲染: {img.size} ✔ 预览 → {out}")

    word, src = textgrab.word_at_point(*cursor_pos(), cfg)
    print(f"  当前光标取词: {word!r}（来源 {src or '无'}）"
          + ("   [注: 光标不在文字上属正常]" if not word else ""))

    got = lookup.lookup("hello", cfg)
    print(f"  引擎连通: {'✔ ' + (got.get('source') or '') if got else '✘ 查不到 hello（检查网络或本地模型）'}")
    if not got:
        ok = False

    if tk is not None:
        try:
            root = tk.Tk()
            root.withdraw()
            mascot = ui.load_decor()
            win = settings_ui.SettingsWindow(root, json.loads(json.dumps(DEFAULTS)), lambda *a: None, mascot=mascot)
            win.update_idletasks()
            print(f"  设置窗口可创建: {win.winfo_width()}x{win.winfo_height()} ✔")
            win.destroy()
            root.destroy()
        except Exception as e:
            print(f"  设置窗口可创建: ✘ {e}")
            ok = False
    print("自检" + ("通过" if ok else "有项失败"))
    return 0 if ok else 1


class App:
    """控制窗口（= 桌面 App 的主界面）+ 取词监听。

    窗口是**按需**建的：开机自启走 `--daemon` 时不建窗（完全隐藏），双击桌面 App 才建。
    窗口右上角「×」只是收起来，监听照跑；真退出用窗口底部的「退出桌面取词」。
    """

    def __init__(self, cfg, root, on_quit, headless=False):
        self.root = root
        self.cfg = cfg
        self.on_quit = on_quit
        self.headless = headless
        self._decor_path = ui.decor_source()          # 卡片右下角那张装饰立绘（可被 App 换掉）
        self._mascot = ui.load_decor(self._decor_path)
        self._cache = {}
        self._last_word = ""
        self._last_lookup_t = 0.0         # 最近一次弹出卡片的时刻（「运行状态」用）
        self.started_at = time.time()     # 本进程 = 取词服务本体的启动时刻
        self._last_data = None            # 最近一张卡片的词条数据（点击复制全文用）
        self._speak_rect = None           # 最近一张卡片上发音按钮的命中矩形
        self._toast_win = None            # 「已复制」小提示
        self._toast_lbl = None
        self._dot_win = None              # 「识别中」小圆点
        self._busy_since = 0.0            # 取词调用开始阻塞的时刻（>0 = 正在识别）
        self._pinned = False
        self._bubble_at = None            # 气泡弹出时的光标位置（收起看门狗用）
        self._cfg_mtime = None            # config.json 的 mtime（热加载用）
        self.bubble = ui.Bubble(root, on_copy=self._copy, on_leave=self._on_bubble_leave,
                                on_enter=self._on_bubble_enter, on_click=self._on_bubble_click)
        self.win = None
        self.watcher = Watcher(cfg, self._render, self)
        # 打游戏自动暂停：本程序自己采样（前台全屏 + 显卡占用），不依赖任何外部看门狗。
        # getter 每轮现读一次 → 「通用」里的开关改了立即生效（不用重启）。
        try:
            gamewatch.start(lambda: bool(self.cfg.get("gameAutoPause", True)))
        except Exception:
            pass
        # 收起看门狗：跑在 Tk 主线程，不依赖 watcher 的循环（OCR 期间 watcher 是阻塞的）
        try:
            self.root.after(120, self._hide_tick)
            # App 心跳（600ms）：弹窗请求 + 配置热加载 + 状态行
            self.root.after(600, self._app_tick)
        except Exception:
            pass

    def reload_decor(self):
        """装饰立绘换了（在 App 的「装饰图」里应用的）→ 重新读图 + 清渲染缓存。

        必须清 `_cache`：那是**按词缓存的成品卡片图**，不清的话旧词的卡片还会用旧立绘。
        """
        try:
            self._decor_path = ui.decor_source()
            self._mascot = ui.load_decor(self._decor_path)
            self._cache.clear()
            _elog("装饰立绘已换：%s" % self._decor_path)
            return True
        except Exception as e:
            _elog("装饰立绘换不了：%r" % (e,))
            return False

    def _build_window(self):
        """建控制窗口（只在真的要用时建）。建不出来也不影响取词：记一行日志就行。"""
        if self.win is not None:
            return self.win
        try:
            self.win = settings_ui.SettingsWindow(
                self.root, self.cfg, self._change, on_toggle=self._on_toggle,
                on_quit=self.on_quit, mascot=self._mascot, test_text=self._test_text,
                on_decor=self.reload_decor)
            self.win.on_reset = self._reset
            self.win.protocol("WM_DELETE_WINDOW", self.hide_window)   # 关窗 = 收起来，不是退出
            self._refresh_status()
        except Exception as e:
            self.win = None
            _elog("控制窗口建不出来: %r" % (e,))
        return self.win

    def show_window(self):
        """把控制窗口摆到用户眼前（已建就直接抬起来）。"""
        w = self._build_window()
        if w is None:
            return False
        try:
            w.deiconify()
            w.lift()
            w.attributes("-topmost", True)
            w.after(150, lambda: w.attributes("-topmost", False))
            w.focus_force()
        except Exception:
            pass
        try:
            w._apply_window_icon()      # 映射之后再补一次：map 时窗口可能被重建，图标会掉
        except Exception:
            pass
        self._refresh_status()
        return True

    def hide_window(self):
        """收起来 —— 监听继续跑（这是「App」而不是「一次性设置面板」的关键）。"""
        try:
            if self.win is not None:
                self.win.withdraw()
        except Exception:
            pass

    def _app_tick(self):
        """App 心跳，全跑在 Tk 主线程：别人双击 App 了 / 配置文件被改了 / 状态要刷新。"""
        try:
            if take_show_request():
                _elog("收到弹窗请求：显示控制窗口")
                self.show_window()
        except Exception:
            pass
        try:
            self._reload_cfg_if_changed()
        except Exception:
            pass
        self._refresh_status()
        try:
            self.root.after(600, self._app_tick)
        except Exception:
            pass

    def _reload_cfg_if_changed(self):
        """config.json 被别人改了（`--settings` 窗口、手改、脚本）→ 就地生效，不必重启。

        就地 = 对同一个 dict 做 clear+update：设置窗口与 Watcher 拿的都是这个对象，
        换成新对象两边就断了。
        """
        try:
            m = os.path.getmtime(CFG_PATH)
        except Exception:
            return                       # 文件还不存在（还没人改过设置）→ 下一轮再看
        if m == self._cfg_mtime:
            return
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                json.load(f)             # 先确认能解析：正好撞上别人写一半就下一轮再说
        except Exception:
            return                       # 注意别在这条路上认时间戳，否则残缺文件会被「跳过一次」
        first = self._cfg_mtime is None
        self._cfg_mtime = m              # 只在真的读成功之后才认这个时间戳
        fresh = load_cfg()
        self.cfg.clear()
        self.cfg.update(fresh)
        if self.win is not None:
            try:
                self.win.set_enabled(self.cfg.get("enabled", True))
            except Exception:
                pass
        if not first:
            _elog("配置已热加载：enabled=%s dwellMs=%s" % (self.cfg.get("enabled"), self.cfg.get("dwellMs")))

    def _refresh_status(self):
        if self.win is None:
            return
        try:
            on = bool(self.cfg.get("enabled", True))
            self.win.set_status("已启用" if on else "已暂停")
            gaming = bool(textgrab.gaming_now())
            self.win.set_gaming(gaming)
            self.win.set_runtime(uptime_s=time.time() - self.started_at,
                                 last_lookup=self._last_lookup_t,
                                 gaming=gaming, enabled=on)
        except Exception:
            pass

    # Watcher 通过这两个方法回调（panel.after / panel.show_bubble）
    def after(self, ms, fn):
        self.root.after(ms, fn)

    def show_bubble(self, img, x, y, word):
        self._last_word = word
        self._last_lookup_t = time.time()
        self._bubble_at = (x, y)
        self.bubble.show(img, x, y)

    def _hide_tick(self):
        """UI 线程的收起看门狗（每 120ms 一次）。

        为什么需要它：收起判断原来只写在 watcher 循环里，而取词走 OCR 时 watcher 会**阻塞
        1–3 秒**（模型冷启动更久），这期间它没法检查「鼠标移开了没有」→ 卡片迟迟不收；
        更糟的是鼠标一旦「进过」气泡就置 `_pinned=True`，而解除只靠 Tk 的 `<Leave>` 事件，
        该事件在「气泡在光标下弹出」「快速划过」「窗口重画」等情况下会漏 →
        `_pinned` 永远是 True，收起条件里的 `not pinned` 永不成立 → 卡片再也收不起来。
        这个 tick 跑在 Tk 主线程，不受上述两件事影响，且会把「光标已不在气泡上」的
        陈旧钉住状态当作安全网解除掉。
        """
        try:
            if getattr(self.bubble, "_rect", None):
                x, y = cursor_pos()
                try:
                    inside = self.bubble.point_in_bubble(x, y)      # 还在气泡上/边上 → 不收
                except Exception:
                    inside = False
                if not inside:
                    if self._pinned:
                        self._pinned = False          # 陈旧钉住：光标已经不在气泡上了
                    ax, ay = self._bubble_at or (x, y)
                    if abs(x - ax) > 32 or abs(y - ay) > 32 or _lbutton_down():
                        self.hide_bubble()
        except Exception:
            pass
        # —— 图片识别中的小圆点：OCR 要 1–3 秒，只在真的久等时才出现（设置里可关）——
        try:
            hint_on = bool((self.cfg.get("imageOcr") or {}).get("hint", True))
            busy = getattr(self.watcher, "_busy_since", 0.0)
            if hint_on and busy and (time.time() - busy > 0.6) and not self.shown:
                if self._dot_win is None:
                    w = tk.Toplevel(self.root)
                    w.overrideredirect(True)
                    w.attributes("-topmost", True)
                    w.attributes("-transparentcolor", "#010203")
                    cv = tk.Canvas(w, width=16, height=16, bg="#010203", highlightthickness=0)
                    cv.create_oval(3, 3, 13, 13, fill="#6d28d9", outline="#ffffff")
                    cv.pack()
                    self._dot_win = w
                px, py = cursor_pos()
                self._dot_win.geometry("+%d+%d" % (px + 16, py + 16))
                self._dot_win.deiconify()
                self._dot_win.lift()
            elif self._dot_win is not None:
                self._dot_win.withdraw()
        except Exception:
            pass
        try:
            self.root.after(120, self._hide_tick)
        except Exception:
            pass

    def _render(self, data, x=None, y=None):
        sc = self._scale(x, y)
        ex_n = int(self.cfg.get("examplesCount", 3) or 0)
        speak = bool(self.cfg.get("showSpeak", True))
        key = (data.get("word"),
               tuple(sorted((p.get("pos"), p.get("meaning")) for p in data.get("poses") or [])),
               round(sc, 2), ex_n, speak)   # 不同缩放/例句数/发音按钮的渲染结果不能混用缓存
        if key not in self._cache:
            self._cache[key] = ui.render_card(data, self._mascot, scale=sc,
                                              examples=ex_n, speak=speak)
        img = self._cache[key]
        # 发音按钮的命中矩形在这里算（这里才有缩放与图尺寸）。
        # ⚠ 别把这一句挪回 Watcher._fire —— _scale 是 App 的方法，Watcher 上没有它
        # （2026-10-08 事故：悬停认出词后渲染必炸，卡片弹不出来）。
        try:
            self._speak_rect = ui.speak_rect_for(img.size[0], img.size[1], sc)
        except Exception:
            self._speak_rect = None
        return img

    def _scale(self, x=None, y=None):
        """气泡按**光标所在那块屏**的 DPI 渲染 —— 混合缩放（如笔记本 150% + 外接 100%）
        下主屏与副屏不同，取系统 DPI 会让副屏上的卡片大一整圈。"""
        try:
            import ctypes
            from ctypes import wintypes
            if x is not None and y is not None:
                u32 = ctypes.windll.user32
                u32.MonitorFromPoint.argtypes = [wintypes.POINT, ctypes.c_uint]
                u32.MonitorFromPoint.restype = ctypes.c_void_p
                mon = u32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)   # NEAREST
                if mon:
                    s32 = ctypes.windll.shcore
                    s32.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                     ctypes.POINTER(ctypes.c_uint),
                                                     ctypes.POINTER(ctypes.c_uint)]
                    s32.GetDpiForMonitor.restype = ctypes.c_long
                    dx, dy = ctypes.c_uint(), ctypes.c_uint()
                    if s32.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                        return max(1.0, min(2.0, dx.value / 96.0))
        except Exception:
            pass
        try:
            return max(1.0, min(2.0, ctypes.windll.user32.GetDpiForSystem() / 96.0))
        except Exception:
            return 1.0

    def _hide(self):
        self.bubble.hide()

    def hide_bubble(self):
        self._hide()

    def is_pinned(self):
        return self._pinned

    def _on_bubble_enter(self):
        self._pinned = True

    def _on_bubble_leave(self):
        self._pinned = False
        self._hide()

    def _on_bubble_click(self, x=None, y=None):
        """点卡片：点在发音按钮上 → 读发音（卡片留下）；点别处 → 复制整张卡片内容后收起。"""
        try:
            if (x is not None and y is not None and self._speak_rect
                    and bool(self.cfg.get("showSpeak", True))):
                sx, sy, sw, sh = self._speak_rect
                if sx <= x <= sx + sw and sy <= y <= sy + sh:
                    word = (self._last_data or {}).get("word") or self._last_word
                    if word:
                        lookup.speak_async(word, self.cfg, on_fail=lambda: self.root.after(0, self._toast, "无可用发音（需联网）"))
                    return
        except Exception:
            pass
        self._copy()
        self._hide()

    def _copy(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._copy_text())
            self._toast("已复制")
        except Exception:
            pass

    def _copy_text(self) -> str:
        """复制的是**整张卡片的内容**（单词 + 音标 + 释义 + 例句），不只是那个单词。"""
        d = self._last_data if isinstance(self._last_data, dict) else None
        if not d:
            return self._last_word or ""
        lines = [d.get("word") or ""]
        ph = d.get("phonetics") or {}
        phs = "  ".join(x for x in (("英 " + ph["uk"]) if ph.get("uk") else "",
                                    ("美 " + ph["us"]) if ph.get("us") else "") if x)
        if phs:
            lines.append(phs)
        for p in (d.get("poses") or []):
            s = ("%s %s" % (p.get("pos") or "", p.get("meaning") or "")).strip()
            if s:
                lines.append(s)
        exs = d.get("examples") or []
        if exs:
            lines.append("例句：")
            for ex in exs:
                if ex.get("en"):
                    lines.append(ex["en"])
                if ex.get("zh"):
                    lines.append(ex["zh"])
        return "\n".join(x for x in lines if x)

    def _toast(self, text: str, ms: int = 1000):
        """光标旁冒一句小提示（「已复制」这类），过会儿自己消失。永不抛。"""
        try:
            if self._toast_win is None:
                w = tk.Toplevel(self.root)
                w.overrideredirect(True)
                w.attributes("-topmost", True)
                self._toast_lbl = tk.Label(w, text="", bg="#1b2a4a", fg="#ffffff",
                                           font=("Microsoft YaHei UI", 9), padx=10, pady=4)
                self._toast_lbl.pack()
                self._toast_win = w
            self._toast_lbl.configure(text=text)
            x, y = cursor_pos()
            self._toast_win.geometry("+%d+%d" % (x + 16, y + 18))
            self._toast_win.deiconify()
            self._toast_win.lift()
            self.root.after(ms, lambda: self._toast_win and self._toast_win.withdraw())
        except Exception:
            pass

    def _change(self, key, value):
        # 设置窗口已改好 self.cfg，这里只负责落盘
        save_cfg(self.cfg)
        try:
            self._cfg_mtime = os.path.getmtime(CFG_PATH)   # 自己写的，别触发一轮无意义的热加载
        except Exception:
            self._cfg_mtime = None

    def _on_toggle(self, on):
        _elog("总开关：%s" % ("开" if on else "关"))
        self._refresh_status()

    def _reset(self):
        self.cfg.clear()
        self.cfg.update(json.loads(json.dumps(DEFAULTS)))
        save_cfg(self.cfg)

    def _test_text(self):
        got = lookup.lookup("hello", self.cfg)
        return bool(got), (f"✔ {got.get('source') or '查到 hello'}" if got else "✘ 查不到 hello（检查网络或本地模型）")

    @staticmethod
    def warmup(cfg):
        """后台预热视觉模型（微信/游戏等无文字界面要靠它）—— 冷启动 1–3 分钟，别挡界面。"""
        threading.Thread(target=lookup.warmup_vision, args=(cfg,), daemon=True).start()

    def stop(self):
        self.watcher.stop_flag = True
        if self.win is not None:
            self.win.destroy()
        self.root.destroy()


def main(argv=None) -> int:
    _enable_dpi_awareness()      # 必须在取任何坐标 / 建 Tk 之前：统一物理像素坐标系
    _set_app_user_model_id()     # 也在建窗口之前：任务栏身份（图标/分组）靠它才不挂到 pythonw 上
    ap = argparse.ArgumentParser(description="Easy Translator 桌面取词")
    ap.add_argument("--selftest", action="store_true", help="跑一遍自检后退出")
    ap.add_argument("--settings", action="store_true", help="只打开设置窗口，不开始监听")
    ap.add_argument("--daemon", action="store_true", help="只监听不弹窗口（开机自启用的静默模式）")
    args = ap.parse_args(argv)
    cfg = load_cfg()

    # 自检不监听、不建窗口：绝不能去抢单实例锁（否则有守护在跑时 --selftest 会直接return 0、什么都不输出）
    listening = (not args.settings) and (not args.selftest)
    _mtx = None
    if listening:
        # 单实例：窗口模式与 --daemon 抢**同一把锁**（开机自启 + 双击 App + 自愈可能同时发生）。
        # 已经有实例在跑 → 只留一个「请弹窗」请求，本进程立刻退出，绝不起第二份监听
        #（两份监听 = 同一处弹两张卡片、UIA 轮询翻倍）。
        _mtx = acquire_single_instance()          # 句柄要一直持有：被 GC 掉锁就释放了
        if _mtx is None:
            if not args.daemon:
                request_show()                    # 请那个在跑的实例把控制窗口弹出来
            return 0
    if not args.selftest:
        # 没有控制台（pythonw / 桌面快捷方式启动）时把 stderr 落到 daemon.log，崩溃原因可事后查。
        # （Tk 主循环回调异常、线程异常、excepthook 全部经 stderr 落入此文件）
        _setup_logfile("daemon start" if args.daemon else "app start")
    if args.selftest:
        return selftest(cfg)
    if tk is None:
        print("缺少 tkinter，无法打开界面（可用 --selftest 走命令行自检）")
        return 2

    root = tk.Tk()
    root.withdraw()

    app = App(cfg, root, lambda: app.stop(), headless=args.daemon)
    if listening:
        app.warmup(cfg)                  # 预热视觉模型：微信/游戏等无文字界面的取词靠它
        app.watcher.start()
    if not args.daemon:
        app.show_window()                # 桌面 App：双击/手动启动就把控制窗口摆出来
    root.protocol("WM_DELETE_WINDOW", app.stop)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
