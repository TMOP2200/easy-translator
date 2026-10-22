# -*- coding: utf-8 -*-
"""Easy Translator 桌面伴生 · 控制窗口（这个伴生程序的「App」主界面）

布局对齐 Hermes 桌面版那套工作台：**左侧深色导航 + 顶部标题栏 + 中间卡片内容 + 底部状态栏**。
导航是**分页**：点哪个栏目就只显示那个栏目的内容（用户明确要的「点哪个项目就出现哪个项目的对应文字」）。
每页各自可滚动；字段都在各自页里 pack 好，切页时只是显隐切换，不存在「容器忘 pack」的形态。

功能面（字段名与扩展 lib/settings-core.js 的 DEFAULTS 一致，test_settings.py 会逐键比对防漂移）：
  · 总览 —— 总开关（开/关翻译）+ 开机自启（无窗口也能翻译）
  · 通用 —— 悬停触发时长 / 例句条数 / 发音按钮
  · 本地小模型 —— 端点、API Key、**文本模型与视觉模型从本机端点拉成可选列表**、超时、测试查词
  · 图片取词 —— 开关、驻留、裁剪尺寸、提示点
  · 数据 —— 恢复默认、配置路径
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request

from PIL import Image, ImageDraw

from et_desktop import ui                     # 装饰立绘（卡片右下角）的取图/导入都在 ui 里
from et_desktop import __version__

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:                                    # pragma: no cover
    tk = None

# —— 设计令牌（与 content/card.css 的吉祥物语言一致）——
NAVY = "#1e3264"
NAVY_DEEP = "#16264b"
INK = "#26324b"
MUTED = "#6b7280"
LINE = "#e2e6ef"
BG = "#f4f5f7"
CARD = "#ffffff"
ACCENT = NAVY
OK = "#16a34a"
ERR = "#dc2626"
WARN = "#d97706"           # 打游戏暂停中这类「注意但不是错」的状态色
SIDEBAR = "#1b2a4a"          # 左栏底色（深于内容区，和 Hermes 那套一样：导航暗、内容亮）
SIDEBAR_TXT = "#c7d2e5"
SIDEBAR_SEL = "#2b4a86"
FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_H2 = ("Microsoft YaHei UI", 9, "bold")
FONT_NAV = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)

# —— 总览横幅 ——
# **固定用 README 的头图**（用户明确要求「总览图不支持导入」）：只有这一张，
# 点图或「打开原图」用系统看图程序打开原图。想换卡片右下角那张图，去「装饰图」大类。
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README_SHOT = os.path.join(ui.res_dir(), "docs", "screenshot-web.png")   # README 头图（打包后从 _MEIPASS 拿）
BANNER_W, BANNER_H = 860, 360        # 横幅上限尺寸（窄窗口按可用宽度等比缩；宽窗口也不会拉成一长条）
CONTENT_MAX = 940                    # 卡片最大宽度：窗口再宽也不铺满，文字才读得舒服
WRAP_DEFAULT = 640                   # 说明文字的初始折行宽度（窗口尺寸一变就由 _relayout 重算）

# 图标句柄缓存：(ico 路径, 宽, 高) → HICON。
# 旧实现每次开窗都 LoadImage 两个新句柄、从不释放 —— 反复开窗就是持续的 GDI 句柄泄漏。
# 句柄本来就要一直用到进程退出，所以复用即可（这份缓存就是"只加载一次"）。
_ICON_HANDLE_CACHE = {}


def _load_icon_cached(u32, ico, w, h):
    key = (ico, int(w), int(h))
    hnd = _ICON_HANDLE_CACHE.get(key)
    if hnd:
        return hnd
    hnd = u32.LoadImageW(None, ico, 1, int(w), int(h), 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
    if hnd:
        _ICON_HANDLE_CACHE[key] = hnd
    return hnd

# —— 左侧栏目（**分页**：点哪个就只显示哪个）——
PAGES = (("overview", "总览"), ("general", "通用"), ("model", "本地小模型"),
         ("ocr", "图片取词"), ("decor", "装饰图"), ("data", "数据"),
         ("help", "使用说明"))

# —— 「使用说明」那一页的内容（写在程序里，下载下来不用翻 README）——
# 口吻：像人在正常讲话 —— 不用说明书腔，也**别满篇「你」**（用户点名说过）。
# 也不重复别的栏目已经讲过的操作（装饰图/图片取词/本地小模型各自那一页里都有），
# 这里只放「别处没有的」：怎么用、三种「关掉」的区别、出问题怎么办、以及装了些什么。
HELP_TEXT = """鼠标停留在英文单词上（默认约五秒，可在「通用」中调整）后，将显示释义卡片，内容含读音、词性、释义及例句。鼠标移开后卡片自动收起；单击卡片其余位置，整张卡片的内容即复制至剪贴板，卡片右上角为发音按钮。

查词默认经由在线词典完成（所查单词将由有道公开词典处理）；如需全程不出本机，可在「本地小模型」中配置并启用本机模型。

窗口右上角「×」按钮仅将窗口收起，取词功能仍在后台运行。如需完全停止取词，请点击左下角「退出桌面取词」。

启用「开机自启」后，本程序将于系统启动时自动在后台运行，无需手动打开窗口。

左侧各栏目分别对应一类设置，相应说明均列于各自页面内。

窗口右下角显示当前状态：左侧为取词功能的开启或关闭情况，右侧为当前所用模型。

如遇异常，可先行自检：打开命令提示符，把下载到的 exe 文件拖进窗口（路径会自动填上），空一格再输入 --selftest，回车。自检结果保存于 %APPDATA%\\EasyTranslator\\selftest.txt，运行日志为同一文件夹下的 daemon.log。

本程序在本机保存的内容（均可随时删除）：
· 程序文件 —— 下载到的那个 exe，可改名、可放在任意目录；删除后即完成移除；
· 全部设置 —— %APPDATA%\\EasyTranslator\\config.json；
· 运行日志与自检结果 —— 同一文件夹下的 daemon.log 与 selftest.txt（日志默认不记录所查单词，可在「数据」中开启记录）；
· 自定义装饰图 —— 同一文件夹下的副本，点击「恢复默认」即予删除；
· 启用「开机自启」后，会在两处各放一份启动记录：注册表 HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 中的 EasyTranslator 项，以及「启动」文件夹中的 Easy Translator (开机自启).vbs —— 系统或安全软件允许哪份生效就用哪份，关闭该选项时两处一并删除；若之后给 exe 改过名或换过位置，把该选项关闭再打开一次，指向即更新。

下载与安装说明（均为可选）：
· 本程序自身不下载、不安装任何东西 —— 下载到的就是一个 exe 文件，删除即完成卸载；
· 本地小模型的模型文件由 Ollama 从官方模型库下载（正版、免费），单个模型约 1~3 GB；
· 本程序只调用本机已安装的 Ollama，不提供、不代理、不改动任何模型文件与下载源；
· 下载只发生在两种时刻：点「下载所选模型」，或自行运行 ollama pull 命令；
· 模型存放在 Ollama 自己的目录（默认位于用户文件夹下的 .ollama\\models），删除模型需使用 Ollama；
· Ollama 本体同为可选：不安装不影响在线词典查词。

如需恢复初始状态，可使用「数据」栏目中的「恢复默认设置」。完全卸载：关闭「开机自启」，退出程序，删除那个 exe（或其所在文件夹），最后删除 %APPDATA%\\EasyTranslator 文件夹。"""




def overview_source(readme: str = None):
    """总览图用哪张：**就是 README 头图**（不支持导入）。找不到返回 ""。"""
    p = README_SHOT if readme is None else readme
    return p if p and os.path.exists(p) else ""


def banner_image(path: str, w: int = BANNER_W, h: int = BANNER_H):
    """任意图片 → w×h 横幅：等比放大到**覆盖**整块，再居中裁切（不拉伸变形）。拿不到返回 None。"""
    try:
        im = Image.open(path).convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, (0, 0), im)                 # 透明底压白，免得出现黑边
        im = bg
    except Exception:
        return None
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(round(im.width * scale))), max(1, int(round(im.height * scale)))),
                   Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


# ————————————————————————— 小模型列表（本机端点） —————————————————————————
def _model_names(payload) -> list:
    """从 /api/tags（Ollama）或 /v1/models（OpenAI 兼容）的 JSON 里抠模型名 —— 两种都认。"""
    if not isinstance(payload, dict):
        return []
    items = payload.get("models") or payload.get("data") or []
    out = []
    for m in items:
        if isinstance(m, dict):
            n = m.get("name") or m.get("model") or m.get("id")
            if n:
                out.append(str(n))
        elif isinstance(m, str):
            out.append(m)
    return sorted(set(out))


def fetch_models(base_url: str, api_key: str = "", timeout: float = 3.0) -> list:
    """从本机端点拉模型名列表；拉不到就返回空表（永不抛，UI 不该因为端点没起就崩）。"""
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return []
    cands = []
    # 用户可能把**完整端点**直接粘进来（…/api/tags 或 …/v1/models）→ 先按原样试一次
    if root.endswith("/api/tags") or root.endswith("/models"):
        cands.append(root)
    if root.endswith("/v1"):
        cands.append(root[:-3].rstrip("/") + "/api/tags")      # 只填到 /v1 时补 Ollama 原生口
        cands.append(root + "/models")                          # OpenAI 兼容口
    elif not cands:
        cands.append(root + "/api/tags")
        cands.append(root + "/v1/models")
    seen = set()
    for url in [c for c in cands if not (c in seen or seen.add(c))]:
        try:
            headers = {"Authorization": "Bearer " + api_key} if api_key else {}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                names = _model_names(json.loads(r.read().decode("utf-8", "ignore")))
            if names:
                return names
        except Exception:
            continue
    return []


def _set_run_entry(on: bool) -> bool:
    """写/删注册表 Run 项。成功返回 True。"""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            if on:
                winreg.SetValueEx(k, "EasyTranslator", 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, "EasyTranslator")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def _get_run_entry():
    """读注册表 Run 项：(是否启用, 命令行)。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            try:
                val, _ = winreg.QueryValueEx(k, "EasyTranslator")
                return True, str(val)
            except FileNotFoundError:
                return False, ""
    except Exception:
        return False, ""


# —— 开机自启：注册表 Run + 「启动」文件夹双保险 ——
# 有的机器（公司安全代理 / EDR）会在 1~2 分钟内把新加的 Run 项清掉
# （本机实测：写好 40 秒还在、130 秒就没了），所以再放一份到「启动」文件夹。
# 放的是个 vbs（wscript 跑，完全无窗口）；两个位置任一存在都算「已开启」，
# 关闭时两处一起删。两份不会双开：程序有单实例锁，第二份会自己退出。
STARTUP_VBS = "Easy Translator (开机自启).vbs"


def startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def startup_vbs_path() -> str:
    return os.path.join(startup_dir(), STARTUP_VBS)


def startup_vbs_content() -> str:
    """「启动」文件夹里那份 vbs 的内容：开机时把守护无窗口拉起来。"""
    cmd = autostart_command()                    # 「exe --daemon」或「wscript 那个 vbs」
    return ("' Easy Translator: start the background daemon at logon (no window)\r\n"
            'Set sh = CreateObject("WScript.Shell")\r\n'
            'sh.Run "%s", 0, False\r\n' % cmd.replace('"', '""'))


def _write_startup_entry(on: bool) -> bool:
    try:
        p = startup_vbs_path()
        if on:
            d = startup_dir()
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            # WSH 按 ANSI 代码页解析无 BOM 的脚本：UTF-8 路径里的中文（中文用户名）
            # 会变乱码、自启静默失效 —— 必须写 UTF-16（Python 的 utf-16 会带 BOM，
            # WSH 认 BOM，中文路径就活了）。
            with open(p, "w", encoding="utf-16") as f:
                f.write(startup_vbs_content())
        else:
            if os.path.exists(p):
                os.remove(p)
        return True
    except Exception:
        return False


def autostart_info():
    """读「开机自启」。返回 (是否已启用, 命令行或位置)。两处任一在即算开启。"""
    on, cmd = _get_run_entry()
    try:
        if os.path.exists(startup_vbs_path()):
            return True, cmd or startup_vbs_path()
    except Exception:
        pass
    return (None, "") if on is None else (on, cmd)


def set_autostart(on: bool) -> bool:
    """开/关开机自启：注册表与「启动」文件夹两处一起写/一起删。"""
    a = _set_run_entry(on)
    b = _write_startup_entry(on)
    return bool(a and b)


# ————————————————————————— 模型从哪来（官方渠道） —————————————————————————
OLLAMA_SITE = "https://ollama.com/download"          # Ollama 官方安装包（免费）
OLLAMA_LIBRARY = "https://ollama.com/library"        # 官方模型库（正版）


def model_library_url(name: str) -> str:
    """某个模型在官方库里的页面：qwen2.5vl:3b → https://ollama.com/library/qwen2.5vl"""
    base = (name or "").strip().split(":")[0].strip()
    return OLLAMA_LIBRARY + "/" + base if base else OLLAMA_LIBRARY


def _ollama_candidates():
    """ollama.exe 的候选位置：PATH + 官方安装包目录 + 盘符根下的便携目录。"""
    out = []
    try:
        import shutil
        p = shutil.which("ollama")
        if p:
            out.append(p)
    except Exception:
        pass
    for cand in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                 os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
                 os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Ollama", "ollama.exe")):
        if cand:
            out.append(cand)
    for drive in ("C:", "D:", "E:", "F:"):
        out.append(drive + os.sep + "ollama" + os.sep + "ollama.exe")
    return out


def find_ollama(cfg=None) -> str:
    """找 ollama.exe：配置里记过的 → 候选路径 → 盘符浅扫（便携版常见 <盘>:\\ollama\\）。"""
    try:
        cached = ((cfg or {}).get("model") or {}).get("ollamaExe") or ""
        if cached and os.path.exists(cached):
            return cached
    except Exception:
        pass
    for c in _ollama_candidates():
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            pass
    try:
        import glob
        for drive in ("C:", "D:", "E:", "F:"):
            for hit in glob.glob(drive + os.sep + "*" + os.sep + "ollama.exe"):
                return hit
    except Exception:
        pass
    return ""


def ollama_running(timeout: float = 0.25) -> bool:
    """Ollama 服务在不在：看 127.0.0.1:11434 能不能连上。

    比查进程准 —— 端口在，模型接口就真能用；也快（毫秒级），可以频繁调用。"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=timeout):
            return True
    except Exception:
        return False


def ollama_models_dir(exe: str) -> str:
    """便携版：模型目录通常就在 ollama.exe 旁边（<安装目录>\\models\\manifests）。"""
    try:
        d = os.path.join(os.path.dirname(exe), "models")
        if os.path.isdir(os.path.join(d, "manifests")):
            return d
    except Exception:
        pass
    return ""


def start_ollama(exe: str) -> tuple:
    """无窗口启动 `ollama serve`（等最多 8 秒确认端口起来）。返回 (成功?, 一句人话)。"""
    import subprocess
    try:
        env = dict(os.environ)
        md = ollama_models_dir(exe)
        if md:
            env["OLLAMA_MODELS"] = md          # 便携版的模型在它旁边
        subprocess.Popen([exe, "serve"], env=env,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except Exception as e:
        return False, "启动失败：%s" % e
    for _ in range(40):
        if ollama_running():
            return True, "Ollama 已启动"
        time.sleep(0.2)
    return False, "启动命令已发出，但服务暂未响应（首次可能更久）"


def _pids_by_names(names) -> list:
    """按进程名取 (pid, name) 列表（tasklist 解析，不碰 PowerShell 的引号地狱）。"""
    import subprocess
    out = []
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        want = {n.lower() for n in names}
        for line in (r.stdout or "").splitlines():
            parts = [x.strip('"') for x in line.split(",")]
            if len(parts) >= 2 and parts[0].lower() in want:
                try:
                    out.append((int(parts[1]), parts[0]))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _process_path(pid: int) -> str:
    """进程的可执行文件全路径（取不到返回空串）。"""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                 ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        h = k.OpenProcess(0x1000, 0, pid)          # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.c_ulong(1024)
            if k.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
                return buf.value
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        pass
    return ""


def stop_ollama() -> tuple:
    """停掉 Ollama 本体和它的模型进程；只动路径里带 ollama 的，绝不碰别人家的 llama-server。"""
    import subprocess
    cand = _pids_by_names(("ollama.exe", "ollama_llama_server.exe", "llama-server.exe"))
    hit = []
    for pid, name in cand:
        path = _process_path(pid).lower()
        if name.lower() in ("ollama.exe", "ollama_llama_server.exe") or "ollama" in path:
            hit.append((pid, name))
    for pid, _name in hit:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    if hit:
        time.sleep(0.8)
    if ollama_running():
        # 兜底：谁占着 11434，就查它路径（仍然只杀 ollama）
        try:
            r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in (r.stdout or "").splitlines():
                if ":11434" in line and "LISTENING" in line.upper():
                    pid = int(line.split()[-1])
                    if "ollama" in _process_path(pid).lower():
                        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
        time.sleep(0.6)
    if ollama_running():
        return False, "仍在运行（端口 11434 还被占用）"
    return (True, "已关闭 Ollama") if hit else (True, "Ollama 本来就没在运行")


def ollama_pull(names) -> tuple:
    """用本机 Ollama 从官方库下载模型。返回 (成功?, 一句人话状态)。

    非开发者用户的「一键下载」就走这里 —— 来源是 Ollama 官方渠道（正版），
    本程序自己不提供任何模型文件、也不改下载源。
    """
    import subprocess
    exe = find_ollama()
    if not exe:
        return False, "没找到 Ollama：先点「先装 Ollama」装好它（免费、官方），再回来下载。"
    todo = [str(n) for n in (names or []) if str(n).strip()]
    if not todo:
        return False, "先在上面选好模型，或手动填一个模型名。"
    for n in todo:
        try:
            r = subprocess.run([exe, "pull", n], capture_output=True, text=True, timeout=3600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                why = (r.stderr or r.stdout or "").strip().splitlines()
                return False, "下载 %s 失败：%s" % (n, (why[-1][:60] if why else "未知原因"))
        except Exception as e:
            return False, "下载 %s 出错：%s" % (n, e)
    return True, "已下载完成：%s（可点「刷新列表」确认）" % "、".join(todo)


def autostart_command() -> str:
    """「开机自启」要写的命令：源码跑 = vbs（无窗口拉起守护）；打包成 exe = 直接用 exe。

    注意打包后**不能再写 vbs** —— 别人机器上没有那个脚本，自启会指向一个不存在的文件。
    """
    if getattr(sys, "frozen", False):
        return '"%s" --daemon' % sys.executable
    vbs = os.path.join(REPO, "desktop", "start_daemon.vbs")
    return 'wscript.exe "%s"' % vbs


def _header_png(mascot: Image.Image, width: int = 520) -> Image.Image:
    """把标题画成「她的对话气泡」+ 右上角立绘 —— 与卡片同一套画法。"""
    h = 86
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bx1 = width - 96
    d.rounded_rectangle([2, 2, bx1, h - 16], radius=16, fill=(255, 255, 255, 255),
                        outline=(30, 50, 100, 255), width=2)
    # 两颗尾点指向她
    for (cx, cy, r) in ((bx1 - 26, h - 13, 7), (bx1 - 8, h - 5, 4)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255),
                  outline=(30, 50, 100, 255), width=2)
    mw = 74
    mh = round(mascot.height * mw / mascot.width)
    her = mascot.resize((mw, mh), Image.LANCZOS)
    img.paste(her, (width - mw - 6, h - mh - 2), her)
    return img


class SettingsWindow(tk.Toplevel if tk else object):
    """控制窗口 = 这个伴生程序的主界面。字段与 options/options.html 一一对应。"""

    def __init__(self, master, cfg, save, on_toggle=None, on_quit=None, mascot=None,
                 test_text=None, on_decor=None):
        super().__init__(master)
        self.cfg = cfg
        self.save = save
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.test_text = test_text
        self.on_decor = on_decor          # 换了装饰立绘时通知后台（App 重新读图 + 清渲染缓存）
        self._mascot = mascot             # 总览卡顶部的「她的对话气泡」立绘
        self._decor_path = ui.decor_source()
        self._sel = "overview"
        self.title("Easy Translator — 桌面取词设置 v%s" % __version__)
        self._apply_window_icon()        # 任务栏/窗口图标用同一枚 .ico（否则是 Tk 的羽毛图标）
        self.configure(bg=BG)
        self.geometry("960x800")
        self.minsize(860, 640)

        # 侧栏（深色） / 内容区（浅色）两列
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True)
        self._rail = tk.Frame(shell, bg=SIDEBAR, width=200)
        self._rail.pack(side="left", fill="y")
        self._rail.pack_propagate(False)
        body = tk.Frame(shell, bg=BG)
        body.pack(side="left", fill="both", expand=True)

        self._build_rail()
        self._build_topbar(body)
        self._build_content(body)
        self._build_statusbar(body)

        self._nav_select("overview")
        self._refresh_toggle()
        self._refresh_models_hint()
        self._refresh_autostart_label()
        self.after(200, lambda: self._fetch_models_async(initial=True))

    # ————————————————————————— 窗口图标 —————————————————————————
    def _apply_window_icon(self):
        """把窗口/任务栏图标换成吉祥物那枚 .ico（由 desktop/tools/make_app_icon.py 生成）。

        ⚠ 只调 Tk 的 `iconbitmap()` 不够：实测三种写法（map 前 / map 后 / iconphoto）
        读回来都是同一个默认图标（`WM_GETICON` 抠出来跟 .ico 只匹配 37%）——
        所以再走一遍 Win32 正规路径：`LoadImage` + `WM_SETICON`（大小图标都给），
        并把**窗口类图标**也设上（任务栏在窗口图标缺失时会退到类图标、再退到 exe 图标，
        那就会变成 pythonw 的图标 —— 正是「任务栏和桌面图标不一致」的来源）。

        图标只是观感：任何一步失败都安静跳过，别挡住建窗口。
        """
        ico = os.path.join(ui.res_dir(), "assets", "easy-translator.ico")
        if not os.path.exists(ico):
            return
        self._icon_path = ico
        try:
            self.iconbitmap(ico)                     # Tk 那套（无害，某些 Tk 版本更爱它）
        except Exception:
            pass
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.GetParent.argtypes = [ctypes.c_void_p]
            u32.GetParent.restype = ctypes.c_void_p
            u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u32.LoadImageW.restype = ctypes.c_void_p
            u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_void_p, ctypes.c_void_p]
            u32.SendMessageW.restype = ctypes.c_void_p
            u32.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            u32.SetClassLongPtrW.restype = ctypes.c_void_p
            # Tk 的 Toplevel：winfo_id() 是 TkChild，带标题/图标的外壳是它的父窗口
            hwnd = u32.GetParent(self.winfo_id()) or self.winfo_id()
            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
            WM_SETICON, ICON_SMALL, ICON_BIG = 0x80, 0, 1
            GCLP_HICON, GCLP_HICONSM = -14, -34
            SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON = 11, 12, 49, 50
            # 尺寸要**按系统指标**加载：传 0,0 只会拿到最小的一档（实测读回来是 16×16），
            # 任务栏/Alt-Tab 那档就会糊。进程已声明 per-monitor DPI 感知，拿到的就是物理像素。
            bw, bh = u32.GetSystemMetrics(SM_CXICON), u32.GetSystemMetrics(SM_CYICON)
            sw, sh = u32.GetSystemMetrics(SM_CXSMICON), u32.GetSystemMetrics(SM_CYSMICON)
            big = _load_icon_cached(u32, ico, bw or 32, bh or 32)
            small = _load_icon_cached(u32, ico, sw or 16, sh or 16)
            if big:
                u32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
                u32.SetClassLongPtrW(hwnd, GCLP_HICON, big)
            if small or big:
                u32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small or big)
                u32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small or big)
        except Exception:
            pass

    # ————————————————————————— 左栏 —————————————————————————
    def _build_rail(self):
        brand = tk.Frame(self._rail, bg=SIDEBAR)
        brand.pack(fill="x", padx=14, pady=(16, 18))
        tk.Label(brand, text="Easy Translator", bg=SIDEBAR, fg="#ffffff",
                 font=FONT_BOLD, anchor="w").pack(anchor="w")
        tk.Label(brand, text="桌面取词 · 控制台", bg=SIDEBAR, fg=SIDEBAR_TXT,
                 font=FONT_SMALL, anchor="w").pack(anchor="w")

        self._nav = {}
        for key, text in PAGES:
            b = tk.Label(self._rail, text="   " + text, bg=SIDEBAR, fg=SIDEBAR_TXT,
                         font=FONT_NAV, anchor="w", padx=6, pady=7, cursor="hand2")
            b.pack(fill="x", padx=8, pady=1)
            b.bind("<Button-1>", lambda ev, k=key: self._nav_select(k))
            b.bind("<Enter>", lambda ev, w=b: w.configure(bg=SIDEBAR_SEL)
                   if w.cget("bg") != ACCENT else None)
            b.bind("<Leave>", lambda ev, k=key, w=b: w.configure(
                bg=ACCENT if self._sel == k else SIDEBAR))
            self._nav[key] = b

        bottom = tk.Frame(self._rail, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=12, pady=14)
        tk.Button(bottom, text="退出桌面取词", command=self.on_quit, font=FONT_SMALL,
                  bg=NAVY_DEEP, fg="#ffffff", activebackground=NAVY, activeforeground="#ffffff",
                  bd=0, highlightthickness=0, pady=6, cursor="hand2").pack(fill="x")
        tk.Label(bottom, text="关窗不退出", bg=SIDEBAR, fg=SIDEBAR_TXT,
                 font=FONT_SMALL).pack(pady=(6, 0))

    def _nav_select(self, key):
        self._sel = key
        for k, b in self._nav.items():
            b.configure(bg=ACCENT if k == key else SIDEBAR,
                        fg="#ffffff" if k == key else SIDEBAR_TXT)
        self.show_page(key)

    def show_page(self, key):
        """切页：**只显示当前栏目**（用户要的「点哪个项目就出哪个项目的对应文字」）。

        切页后回到该页顶部；尺寸变化仍由 canvas 的 Configure 统一重排。
        """
        if key not in getattr(self, "_pages", {}):
            return
        self._sel = key
        for k, p in self._pages.items():
            try:
                if k == key:
                    p.pack(fill="x")
                else:
                    p.pack_forget()
            except Exception:
                pass
        try:
            self.update_idletasks()
            self._canvas.yview_moveto(0.0)
            self._on_cards_configure()
        except Exception:
            pass

    _jump = show_page          # 老名字留着（脚本/旧测试里可能还在用）

    # ————————————————————————— 顶栏 —————————————————————————
    def _build_topbar(self, parent):
        bar = tk.Frame(parent, bg=CARD)
        bar.pack(fill="x")
        left = tk.Frame(bar, bg=CARD)
        left.pack(side="left", fill="y", padx=18, pady=(10, 10))
        tk.Label(left, text="鼠标悬停翻译", bg=CARD, fg=INK,
                 font=FONT_TITLE).pack(anchor="w")
        tk.Label(left, text="停留即显示卡片 · 移开即自动收起",
                 bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w", pady=(2, 0))
        self.status_lbl = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=FONT)
        self.status_lbl.pack(side="right", padx=(6, 18))
        tk.Label(bar, text="v%s" % __version__, bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="right")
        tk.Frame(parent, bg=LINE, height=1).pack(fill="x")

    # ————————————————————————— 内容区 —————————————————————————
    def _build_content(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._cards = tk.Frame(self._canvas, bg=BG)
        inner = self._canvas.create_window((0, 0), window=self._cards, anchor="nw")
        self._inner = inner
        self._cards.bind("<Configure>", self._on_cards_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        try:
            self._canvas.bind_all("<MouseWheel>",
                                  lambda e: self._canvas.yview_scroll(-int(e.delta / 120), "units"))
        except Exception:
            pass

        self._cards_map = {}
        self._pages = {}
        for key, _text in PAGES:
            self._pages[key] = tk.Frame(self._cards, bg=BG)
        self._wrap_lbls = []          # 需要跟着窗口宽度改折行的说明文字
        self._img_w = 0               # 上次按多宽画的图（窗口大小变了要重画）
        self._card_overview()
        self._card_general()
        self._card_model()
        self._card_ocr()
        self._card_decor()
        self._card_data()
        self._card_help()
        self.show_page(self._sel)     # 开局只显示「总览」那一页

    # ————————————————————————— 跟着窗口宽度排版 —————————————————————————
    def _on_canvas_configure(self, e):
        """内容按**最大宽度**居中：窗口拉得再宽，卡片也不摊成一条 —— 一行太长读着累。"""
        w = min(e.width, CONTENT_MAX + 28)
        try:
            self._canvas.itemconfigure(self._inner, width=w)
            self._canvas.coords(self._inner, max(0, (e.width - w) // 2), 0)
        except Exception:
            pass

    def _on_cards_configure(self, e=None):
        """内容区尺寸变了：更新滚动范围 + 重排（折行宽度、按可用宽度重画图）。"""
        try:
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except Exception:
            pass
        w = (getattr(e, "width", 0) or 0) or self._cards.winfo_width()
        if w and w > 50:
            self._relayout(w)

    def _content_width(self, w: int = None) -> int:
        """卡片里真正能放文字/图的宽度：扣掉外层 padx 14×2、卡片内 padx 14×2、边框和滚动条。

        上限 CONTENT_MAX —— 窗口最大化时也不能让说明文字铺成一整行（一行 150 字读着累）。
        """
        w = w or self._cards.winfo_width() or 800
        return max(200, min(w, CONTENT_MAX) - 14 * 4 - 12)

    def _relayout(self, w: int = None):
        """**小窗口和大窗口的文字长度不一样**：折行宽度跟着窗口走，别写死。"""
        avail = self._content_width(w)
        for lbl in getattr(self, "_wrap_lbls", []):
            try:
                lbl.configure(wraplength=avail)
            except Exception:
                pass
        if abs(avail - self._img_w) >= 24:          # 差得不多就别重画（拖窗口时每像素重画太费）
            self._img_w = avail
            for fn in ("_refresh_banner", "_refresh_decor"):
                f = getattr(self, fn, None)
                if f:
                    try:
                        f()
                    except Exception:
                        pass

    # ---------- 卡片：总览（总览图 + 总开关 + 开机自启） ----------
    def _card_overview(self):
        c = self._card("总览", key="overview")
        # 总览图：固定 README 头图，不支持导入。点图（或「打开原图」）用系统看图程序打开原图。
        row = self._row(c, "总览图")
        tk.Button(row, text="打开原图", command=self._open_overview, font=FONT_SMALL, bg=CARD, fg=INK,
                  bd=1, highlightthickness=1, highlightbackground=LINE,
                  cursor="hand2").pack(side="left")
        self._banner_src_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=FONT_SMALL,
                                        anchor="w", justify="left", wraplength=WRAP_DEFAULT)
        self._banner_src_lbl.pack(side="left", padx=(10, 0))
        self._wrap_lbls.append(self._banner_src_lbl)

        self._banner_lbl = tk.Label(c, bg=CARD, bd=0, cursor="hand2")
        self._banner_lbl.pack(anchor="w", padx=14, pady=(2, 6))
        self._banner_lbl.bind("<Button-1>", lambda ev: self._open_overview())
        self._refresh_banner()

        bar = tk.Frame(c, bg=CARD)
        bar.pack(fill="x", padx=14, pady=(8, 2))
        self.enabled_var = tk.BooleanVar(value=bool(self.cfg.get("enabled", True)))
        self.enable_btn = tk.Button(
            bar, text="", command=self._toggle, cursor="hand2",
            font=("Microsoft YaHei UI", 12, "bold"),
            bd=0, highlightthickness=0, padx=24, pady=10, relief="flat")
        self.enable_btn.pack(side="left")
        self._gaming_lbl = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=FONT)
        self._gaming_lbl.pack(side="left", padx=(14, 0))
        self._note(c, "检测到全屏应用（如游戏）且显卡繁忙时自动暂停，退出后自动恢复。")

        row = self._row(c, "开机自启")
        self._autostart_var = tk.BooleanVar(value=bool(autostart_info()[0]))
        tk.Checkbutton(row, variable=self._autostart_var, bg=CARD, activebackground=CARD,
                       bd=0, highlightthickness=0, command=self._on_autostart
                       ).pack(side="left")
        self._autostart_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=FONT)
        self._autostart_lbl.pack(side="left", padx=(8, 0))
        self._note(c, "随系统启动在后台运行，关闭本窗口不影响取词；「退出桌面取词」可完全退出。")

        # —— 运行状态：这页就是「查看守护」的地方 ——
        # 本窗口进程本身就是取词服务：它开着，后台就一定在工作。这组状态把
        # 「服务活着吗 / 最近取过词吗 / 是不是在游戏暂停」直接摊开，用户不必猜。
        tk.Label(c, text="运行状态", bg=CARD, fg=INK, font=FONT_TITLE).pack(anchor="w", padx=14, pady=(14, 2))
        self._rt_rows = {}
        for key, label in (("svc", "取词服务"), ("last", "最近一次取词"), ("game", "全屏应用自动暂停")):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", padx=14, pady=1)
            tk.Label(r, text=label, bg=CARD, fg=MUTED, font=FONT, width=12, anchor="w").pack(side="left")
            v = tk.Label(r, text="…", bg=CARD, fg=INK, font=FONT, anchor="w")
            v.pack(side="left", padx=(8, 0))
            self._rt_rows[key] = v
        self._note(c, "本窗口就是取词服务本体：它开着，后台就在工作。")

        # —— 本机模型服务（Ollama）：独立进程，关翻译不会关它 —— 这里给一个明确的开关 ——
        r = tk.Frame(c, bg=CARD)
        r.pack(fill="x", padx=14, pady=(8, 1))
        tk.Label(r, text="本机模型服务", bg=CARD, fg=MUTED, font=FONT,
                 width=12, anchor="w").pack(side="left")
        self._ollama_state = tk.Label(r, text="…", bg=CARD, fg=INK, font=FONT, anchor="w")
        self._ollama_state.pack(side="left", padx=(8, 0))
        self._ollama_btn = tk.Button(r, text="启动 Ollama", command=self._toggle_ollama,
                                     font=FONT_SMALL, bg=CARD, fg=INK, bd=1, highlightthickness=1,
                                     highlightbackground=LINE, cursor="hand2")
        self._ollama_btn.pack(side="left", padx=(10, 0))
        self._ollama_msg = tk.Label(c, text="", bg=CARD, fg=MUTED, font=FONT_SMALL,
                                    anchor="w", justify="left", wraplength=WRAP_DEFAULT)
        self._ollama_msg.pack(fill="x", padx=14)
        self._wrap_lbls.append(self._ollama_msg)
        self._note(c, "Ollama 与「翻译」总开关相互独立：关闭翻译不会关闭它；用完可在这里关闭以释放内存。")
        self._ollama_last = 0.0
        self.refresh_ollama()

    def set_ollama_msg(self, text: str, ok: bool = True):
        try:
            self._ollama_msg.configure(text=text, fg=OK if ok else ERR)
        except Exception:
            pass

    def refresh_ollama(self):
        """刷新「本机模型服务」一行（状态 + 按钮文字）。永不抛。"""
        try:
            on = ollama_running()
            self._ollama_state.configure(text="运行中" if on else "未运行", fg=OK if on else MUTED)
            self._ollama_btn.configure(text="关闭 Ollama" if on else "启动 Ollama")
        except Exception:
            pass

    def _toggle_ollama(self):
        """按钮动作：在跑就停，没跑就起（都在后台线程，不卡界面）。"""
        def run():
            try:
                if ollama_running():
                    ok, msg = stop_ollama()
                else:
                    exe = find_ollama(self.cfg)
                    if not exe:
                        ok, msg = False, "没找到 ollama.exe（可先点「先装 Ollama」安装官方版）"
                    else:
                        try:
                            self.cfg.setdefault("model", {})["ollamaExe"] = exe
                            self.on_change("model.ollamaExe", exe)   # 记下来，下次直接用
                        except Exception:
                            pass
                        ok, msg = start_ollama(exe)
            except Exception as e:
                ok, msg = False, "操作失败：%s" % e
            self.after(0, lambda: (self.set_ollama_msg(msg, ok), self.refresh_ollama()))
        threading.Thread(target=run, daemon=True).start()

    # ---------- 卡片：通用 ----------
    def _card_general(self):
        c = self._card("通用", key="general")
        self._row_scale(c, "悬停触发时长", "dwellMs", 1000, 15000, 500, lambda v: f"{v / 1000:g} 秒")
        self._row_number(c, "例句条数", "examplesCount", 0, 5)
        self._row_check(c, "显示发音按钮", "showSpeak")
        self._row_check(c, "全屏应用时自动暂停", "gameAutoPause")
        self._note(c, "鼠标在英文上停留多久后显示卡片。")
        self._note(c, "全屏应用时自动暂停：检测到全屏且显卡繁忙的应用（如游戏）即停工，退出后自动恢复。")

    # ---------- 卡片：本地小模型 ----------
    def _card_model(self):
        c = self._card("本地小模型（OpenAI 兼容端点）", key="model")
        self._row_check(c, "启用小模型", "model.enabled", sub="model", key2="enabled")
        self._row_text(c, "接口地址", "model.baseUrl", sub="model", key2="baseUrl",
                       placeholder="http://127.0.0.1:11434/v1")
        self._row_text(c, "API Key（可空）", "model.apiKey", sub="model", key2="apiKey",
                       placeholder="本地 Ollama 留空即可", secret=True)

        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="本机模型", bg=CARD, fg=INK, font=FONT, width=18, anchor="w").pack(side="left")
        tk.Button(row, text="刷新列表", command=lambda: self._fetch_models_async(initial=False),
                  font=FONT_SMALL, bg=CARD, fg=INK, bd=1, highlightthickness=1,
                  highlightbackground=LINE, cursor="hand2").pack(side="left")
        self._models_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=FONT_SMALL)
        self._models_lbl.pack(side="left", padx=(8, 0))

        self._row_combo(c, "文本模型", "model.textModel", sub="model", key2="textModel")
        self._row_combo(c, "视觉模型", "model.visionModel", sub="model", key2="visionModel")
        self._note(c, "文本模型用于查词，视觉模型用于识别图片中的文字。")

        # 没有需要的模型？从官方渠道装 —— 面向非开发者的「一键下载」
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="下载模型", bg=CARD, fg=INK, font=FONT,
                 width=18, anchor="w").pack(side="left")
        tk.Button(row, text="下载所选模型", command=self._pull_models, font=FONT_SMALL,
                  bg=CARD, fg=INK, bd=1, highlightthickness=1, highlightbackground=LINE,
                  cursor="hand2").pack(side="left")
        tk.Button(row, text="打开官方模型库", command=self._open_library, font=FONT_SMALL,
                  bg=CARD, fg=INK, bd=1, highlightthickness=1, highlightbackground=LINE,
                  cursor="hand2").pack(side="left", padx=(6, 0))
        tk.Button(row, text="先装 Ollama", command=self._open_ollama, font=FONT_SMALL,
                  bg=CARD, fg=INK, bd=1, highlightthickness=1, highlightbackground=LINE,
                  cursor="hand2").pack(side="left", padx=(6, 0))
        self._dl_lbl = tk.Label(c, text="", bg=CARD, fg=MUTED, font=FONT_SMALL,
                                anchor="w", justify="left", wraplength=WRAP_DEFAULT)
        self._dl_lbl.pack(fill="x", padx=14)
        self._wrap_lbls.append(self._dl_lbl)
        self._note(c, "模型由 Ollama 从官方库下载（正版、免费）：文本约 1 GB、视觉约 3 GB。")

        self._row_number(c, "超时（毫秒）", "model.timeoutMs", 2000, 180000, sub="model", key2="timeoutMs")

        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=6)
        tk.Button(row, text="测试文本查词", command=self._test, font=FONT, bg=CARD, fg=INK,
                  bd=1, highlightthickness=1, highlightbackground=LINE, cursor="hand2").pack(side="left")
        self.result_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=FONT)
        self.result_lbl.pack(side="left", padx=10)
        self._note(c, "本地模型首次启动约需 1–3 分钟，之后每次查词约数百毫秒。")

    # ---------- 卡片：图片取词 ----------
    def _card_ocr(self):
        c = self._card("图片取词", key="ocr")
        self._row_check(c, "启用", "imageOcr.enabled", sub="imageOcr", key2="enabled")
        self._row_scale(c, "图片驻留时长", "imageOcr.dwellMs", 500, 8000, 100,
                        lambda v: f"{v / 1000:g} 秒", sub="imageOcr", key2="dwellMs")
        self._row_number(c, "裁剪宽度", "imageOcr.cropW", 200, 900, sub="imageOcr", key2="cropW")
        self._row_number(c, "裁剪高度", "imageOcr.cropH", 80, 500, sub="imageOcr", key2="cropH")
        self._row_check(c, "识别期间显示提示点", "imageOcr.hint", sub="imageOcr", key2="hint")
        self._note(c, "需要本地视觉模型；未识别到英文单词时不显示卡片。")

    # ---------- 卡片：装饰图（卡片右下角那张立绘） ----------
    def _card_decor(self):
        c = self._card("装饰图（卡片右下角）", key="decor")
        self._decor_lbl = tk.Label(c, bg=CARD, bd=0, cursor="hand2")
        self._decor_lbl.pack(anchor="w", padx=14, pady=(2, 4))
        self._decor_lbl.bind("<Button-1>", lambda ev: self._open_decor())
        self._refresh_decor(sync_entry=True)

        self._decor_var = tk.StringVar(value="")
        self._image_row(c, "装饰图", self._decor_var, self._pick_decor,
                        self._apply_decor_path, self._reset_decor)
        self._decor_msg_lbl = tk.Label(c, text="", bg=CARD, fg=MUTED, font=FONT_SMALL,
                                       anchor="w", justify="left", wraplength=WRAP_DEFAULT)
        self._decor_msg_lbl.pack(fill="x", padx=14)
        self._wrap_lbls.append(self._decor_msg_lbl)
        self._note(c, "可更换为自定义图片：填写路径或点击「浏览…」，再点击「应用」；"
                      "「恢复默认」可还原为内置鲸鱼娘。")

    # ---------- 卡片：使用说明（app 内置的说明书） ----------
    def _card_help(self):
        c = self._card("使用说明", key="help")
        for para in HELP_TEXT.split("\n\n"):
            lbl = tk.Label(c, text=para.strip(), bg=CARD, fg=INK, font=FONT,
                           justify="left", anchor="w", wraplength=WRAP_DEFAULT)
            lbl.pack(fill="x", padx=14, pady=5)
            self._wrap_lbls.append(lbl)

    # ---------- 卡片：数据 ----------
    def _card_data(self):
        c = self._card("数据", key="data")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=6)
        tk.Button(row, text="恢复默认设置", command=self._reset, font=FONT, bg=CARD, fg=INK,
                  bd=1, highlightthickness=1, highlightbackground=LINE, cursor="hand2").pack(side="left")
        self._row_check(c, "日志记录所查单词（排障用）", "logWords")
        self._note(c, "查询结果仅缓存在本机；默认经由在线词典查询（联网说明见「使用说明」）。\n配置文件：%APPDATA%\\EasyTranslator\\config.json")

    # ————————————————————————— 底部状态栏 —————————————————————————
    def _build_statusbar(self, parent):
        tk.Frame(parent, bg=LINE, height=1).pack(fill="x")
        bar = tk.Frame(parent, bg=CARD, height=30)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._dot = tk.Label(bar, text="●", bg=CARD, fg=OK, font=FONT_SMALL)
        self._dot.pack(side="left", padx=(18, 4))
        self._state_lbl = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=FONT_SMALL)
        self._state_lbl.pack(side="left")
        self._foot_lbl = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=FONT_SMALL)
        self._foot_lbl.pack(side="right", padx=18)

    def _refresh_footer(self):
        try:
            m = self.cfg.get("model") or {}
            self._foot_lbl.configure(
                text="文本 %s · 视觉 %s" % (m.get("textModel") or "-", m.get("visionModel") or "-"))
        except Exception:
            pass

    # ————————————————————————— 组件工厂 —————————————————————————
    def _card(self, title: str, key: str = None):
        parent = self._pages.get(key, self._cards)      # 每个栏目各自一页，卡片就长在自己那页里
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", padx=14, pady=(12, 0))
        c = tk.Frame(wrap, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        c.pack(fill="x")
        head = tk.Frame(c, bg=CARD)
        head.pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(head, text=title.upper(), bg=CARD, fg=NAVY, font=FONT_H2, anchor="w").pack(side="left")
        body = tk.Frame(c, bg=CARD)
        body.pack(fill="both", expand=True, pady=(0, 10))
        if key:
            self._cards_map[key] = wrap
        return body

    def _row(self, parent, label):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text=label, bg=CARD, fg=INK, font=FONT, width=18, anchor="w").pack(side="left")
        return row

    def _image_row(self, parent, label, var, on_pick, on_apply, on_reset):
        """「标签 + 图片路径文本框 + 浏览…/应用/恢复默认」这一行（装饰图用）。

        文本框只在**用户自己指定了图片**时才显示路径；用自带默认图时**留空**——
        用户说了「不要出现默认图片的地址」。想看现在那张原图，点上面的预览就行。
        """
        row = self._row(parent, label)
        e = tk.Entry(row, textvariable=var, font=FONT_SMALL, bd=1, highlightthickness=1,
                     highlightbackground=LINE, relief="flat")
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: on_apply())
        for text, cmd in (("浏览…", on_pick), ("应用", on_apply), ("恢复默认", on_reset)):
            tk.Button(row, text=text, command=cmd, font=FONT_SMALL, bg=CARD, fg=INK,
                      bd=1, highlightthickness=1, highlightbackground=LINE,
                      cursor="hand2").pack(side="left", padx=(4, 0))
        return row

    def _get(self, path, sub=None, key2=None):
        if sub:
            return self.cfg.get(sub, {}).get(key2)
        return self.cfg.get(path)

    def _set(self, value, sub=None, key2=None, path=None):
        if sub:
            self.cfg.setdefault(sub, {})[key2] = value
            self.save(self.cfg, f"{sub}.{key2}")
        else:
            self.cfg[path] = value
            self.save(self.cfg, path)
        self._refresh_footer()

    def _row_check(self, parent, label, path, sub=None, key2=None):
        row = self._row(parent, label)
        var = tk.BooleanVar(value=bool(self._get(path, sub, key2)))
        tk.Checkbutton(row, variable=var, bg=CARD, activebackground=CARD, bd=0, highlightthickness=0,
                       command=lambda: self._set(var.get(), sub, key2, path)).pack(side="left")

    def _row_text(self, parent, label, path, sub=None, key2=None, placeholder="", secret=False):
        row = self._row(parent, label)
        e = tk.Entry(row, font=FONT, show="•" if secret else "", bd=1, highlightthickness=1,
                     highlightbackground=LINE, relief="flat")
        e.insert(0, str(self._get(path, sub, key2) or ""))
        e.pack(side="left", fill="x", expand=True)
        e.bind("<FocusOut>", lambda ev: self._set(e.get(), sub, key2, path))
        e.bind("<Return>", lambda ev: self._set(e.get(), sub, key2, path))

    def _row_combo(self, parent, label, path, sub=None, key2=None, values=None):
        """可编辑下拉：既可选本机拉到的模型，也能手打任意模型名。"""
        row = self._row(parent, label)
        var = tk.StringVar(value=str(self._get(path, sub, key2) or ""))
        cb = ttk.Combobox(row, textvariable=var, values=list(values or []), font=FONT)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda ev: self._set(var.get(), sub, key2, path))
        cb.bind("<Return>", lambda ev: self._set(var.get(), sub, key2, path))
        cb.bind("<FocusOut>", lambda ev: self._set(var.get(), sub, key2, path))
        cb._et_var = var            # 值取这里：下拉在**没映射的页**上时 cb.get() 会读成空串
        setattr(self, "_combo_" + str(key2 or path), cb)
        return cb

    def _row_number(self, parent, label, path, lo, hi, sub=None, key2=None):
        row = self._row(parent, label)
        var = tk.IntVar(value=int(self._get(path, sub, key2) or 0))
        sp = tk.Spinbox(row, from_=lo, to=hi, textvariable=var, font=FONT, width=8,
                        bd=1, highlightthickness=1, highlightbackground=LINE, relief="flat",
                        command=lambda: self._set(var.get(), sub, key2, path))
        sp.pack(side="left")
        sp.bind("<FocusOut>", lambda ev: self._set(var.get(), sub, key2, path))

    def _row_scale(self, parent, label, path, lo, hi, res, fmt, sub=None, key2=None):
        row = self._row(parent, label)
        cur = int(self._get(path, sub, key2) or lo)
        var = tk.IntVar(value=cur)
        out = tk.Label(row, text=fmt(cur), bg=CARD, fg=MUTED, font=FONT, width=8, anchor="e")

        def on_move(_v):
            out.configure(text=fmt(int(float(_v))))
        sc = tk.Scale(row, from_=lo, to=hi, resolution=res, orient="horizontal", variable=var,
                      bg=CARD, fg=INK, highlightthickness=0, bd=0, troughcolor=LINE,
                      showvalue=False, command=on_move)
        sc.configure(sliderrelief="flat", activebackground=ACCENT)
        sc.pack(side="left", fill="x", expand=True)
        out.pack(side="left", padx=(8, 0))
        sc.bind("<ButtonRelease-1>", lambda ev: self._set(var.get(), sub, key2, path))

    def _note(self, parent, text):
        lbl = tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=FONT_SMALL, justify="left",
                       anchor="w", wraplength=WRAP_DEFAULT)
        lbl.pack(fill="x", padx=14, pady=(4, 12))
        self._wrap_lbls.append(lbl)      # 窗口变宽/变窄时重算折行
        return lbl

    # ————————————————————————— 总览图（固定用 README 头图，不支持导入） —————————————————————————
    def _refresh_banner(self, *_a, **_kw):
        """总览横幅：固定用 README 头图，按窗口宽度等比缩放（上限 BANNER_W）。

        卡片上不写任何说明文字 —— 这块就是「总览图」本身。
        """
        path = overview_source()
        w = int(max(240, min(BANNER_W, self._img_w or BANNER_W)))
        h = int(max(90, round(w * BANNER_H / float(BANNER_W))))
        img = banner_image(path, w=w, h=h) if path else None
        if img is None and getattr(self, "_mascot", None) is not None:
            img = _header_png(self._mascot, width=w)
        if img is not None:
            try:
                self._banner_photo = _to_photo(img)   # 必须留引用：PhotoImage 被 GC 掉图就没了
                self._banner_lbl.configure(image=self._banner_photo)
            except Exception:
                pass

    def _set_banner_msg(self, text: str, ok: bool = True):
        try:
            self._banner_src_lbl.configure(text=text, fg=MUTED if ok else ERR)
        except Exception:
            pass

    def _open_overview(self):
        """用系统默认看图程序打开这张原图（点图片本身也能触发）。"""
        path = overview_source()
        if not path:
            self._set_banner_msg("未找到图片文件", ok=False)
            return
        try:
            os.startfile(path)                     # noqa: S606 —— 本机看图，路径来自本仓库
            self._set_banner_msg("已用系统默认看图程序打开", ok=True)
        except Exception as e:
            self._set_banner_msg("打开失败：%s" % e, ok=False)

    # ————————————————————————— 装饰图（卡片右下角） —————————————————————————
    def _decor_preview_image(self, w: int = 320, h: int = 180):
        """画出「卡片右下角的样子」：浅灰底上一块白卡，立绘贴右下角（透明一眼可见）。"""
        img = Image.new("RGB", (w, h), (244, 245, 247))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=14, fill=(255, 255, 255),
                            outline=(226, 230, 239), width=1)
        try:
            dec = ui.load_decor(self._decor_path)
        except Exception:
            return img
        th = int(h * 0.62)
        tw = max(1, int(round(dec.width * th / dec.height)))
        if tw > int(w * 0.62):                     # 太宽就按宽度收回来
            tw = int(w * 0.62)
            th = max(1, int(round(dec.height * tw / dec.width)))
        dec = dec.resize((tw, th), Image.LANCZOS)
        img.paste(dec, (w - tw - 8, h - th - 6), dec)
        return img

    def _refresh_decor(self, sync_entry: bool = False):
        """刷新装饰图预览 + 来源说明。预览按**窗口可用宽度**等比缩（小窗口也不溢出）。"""
        self._decor_path = ui.decor_source()
        w = int(max(200, min(320, self._img_w or 320)))
        h = int(max(110, round(w * 180 / 320.0)))
        try:
            self._decor_photo = _to_photo(self._decor_preview_image(w, h))
            self._decor_lbl.configure(image=self._decor_photo)
        except Exception:
            pass
        if self._decor_path == ui.DECOR_DEFAULT:
            text = "当前装饰图：内置鲸鱼娘"
        else:
            text = "当前装饰图：自定义图片"
        self._set_decor_msg(text, ok=True)
        try:
            if sync_entry or not self._decor_var.get().strip():
                # 用自带默认图时**留空**（用户要求「不要出现默认图片的地址」）；
                # 只有用户自己指定的图才把路径回填到文本框
                self._decor_var.set(self._decor_path
                                    if self._decor_path == ui.DECOR_IMPORTED else "")
        except Exception:
            pass

    def _set_decor_msg(self, text: str, ok: bool = True):
        try:
            self._decor_msg_lbl.configure(text=text, fg=MUTED if ok else ERR)
        except Exception:
            pass

    def _notify_decor(self):
        """告诉后台换图了（App 会重新读图 + 清掉按词缓存的成品卡片）。"""
        if self.on_decor:
            try:
                self.on_decor()
            except Exception:
                pass

    def _pick_decor(self):
        try:
            from tkinter import filedialog
        except Exception:
            return
        try:
            src = filedialog.askopenfilename(
                title="选一张图片作为卡片右下角的装饰图",
                filetypes=[("图片（建议 PNG，带透明）", "*.png *.webp *.gif *.bmp *.jpg *.jpeg"),
                           ("所有文件", "*.*")])
        except Exception:
            src = None
        if not src:
            return
        self._decor_var.set(src)
        self._apply_decor_path()

    def _apply_decor_path(self):
        """把文本框里的路径应用为装饰立绘（保留 alpha 复制进配置目录），并**立刻生效**。"""
        src = (self._decor_var.get() or "").strip().strip('"')
        if not src:
            self._set_decor_msg("请先填写图片路径，或点击「浏览…」选择", ok=False)
            return
        try:
            same = os.path.normcase(os.path.abspath(src)) == os.path.normcase(ui.DECOR_IMPORTED)
        except Exception:
            same = False
        if same and os.path.exists(ui.DECOR_IMPORTED):
            self._set_decor_msg("当前已是该图片", ok=True)
            return
        ok, msg = ui.import_decor_image(src)
        self._refresh_decor(sync_entry=True)
        self._set_decor_msg(msg, ok=ok)
        if ok:
            self._notify_decor()

    def _open_decor(self):
        """用系统默认看图程序打开当前装饰图（点预览也能触发）。"""
        path = ui.decor_source()
        if not path or not os.path.exists(path):
            self._set_decor_msg("未找到可打开的图片文件", ok=False)
            return
        try:
            os.startfile(path)                     # noqa: S606 —— 本机看图，路径来自用户或本仓库
            self._set_decor_msg("已用系统默认看图程序打开", ok=True)
        except Exception as e:
            self._set_decor_msg("打开失败：%s" % e, ok=False)

    def _use_colored_decor(self):
        """一键换成 README 里那张彩色立绘（拼版自动切成单张）。"""
        ok, msg = ui.import_decor_colored()
        self._refresh_decor(sync_entry=True)
        self._set_decor_msg(msg, ok=ok)
        if ok:
            self._notify_decor()

    def _reset_decor(self):
        """删掉复制进来的那份 → 回到仓库里的默认立绘，并立刻生效。"""
        try:
            if os.path.exists(ui.DECOR_IMPORTED):
                os.remove(ui.DECOR_IMPORTED)
        except Exception:
            pass
        self._refresh_decor(sync_entry=True)
        self._set_decor_msg("已恢复为内置鲸鱼娘", ok=True)
        self._notify_decor()

    # ————————————————————————— 模型列表 —————————————————————————
    def _fetch_models_async(self, initial=False):
        """后台拉本机模型名（网络请求不能卡 Tk 主线程）。"""
        def run():
            m = self.cfg.get("model") or {}
            names = fetch_models(m.get("baseUrl") or "http://127.0.0.1:11434/v1",
                                 m.get("apiKey") or "")
            try:
                self.after(0, lambda: self._apply_models(names, initial))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _apply_models(self, names, initial=False):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._models_lbl.configure(
            text=("已读取到 %d 个模型，可在下方两个下拉框中选择" % len(names)) if names
            else "端点无响应（Ollama 未启动？）—— 也可直接输入模型名")
        for key2 in ("textModel", "visionModel"):
            cb = getattr(self, "_combo_" + key2, None)
            if cb is None:
                continue
            try:
                var = getattr(cb, "_et_var", None)
                # 下拉在别的页上（没映射）时 cb.get() 读不到东西 —— 一律走 textvariable
                cur = str(var.get()) if var is not None else str(cb.get() or "")
                cb.configure(values=list(names))
                if cur:
                    cb.set(cur)
                    if var is not None:
                        var.set(cur)
            except Exception:
                pass

    def _refresh_models_hint(self):
        try:
            self._models_lbl.configure(text="正在读取本机模型…")
        except Exception:
            pass

    # ————————————————————————— 模型下载（官方渠道） —————————————————————————
    def _open_url(self, url: str) -> bool:
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def _set_dl_msg(self, text: str, ok: bool = True):
        try:
            self._dl_lbl.configure(text=text, fg=OK if ok else ERR)
        except Exception:
            pass

    def _open_ollama(self):
        if self._open_url(OLLAMA_SITE):
            self._set_dl_msg("已打开 Ollama 官网下载页（免费、官方）。")
        else:
            self._set_dl_msg("打不开浏览器：请手动访问 ollama.com/download", ok=False)

    def _open_library(self):
        m = self.cfg.get("model") or {}
        url = model_library_url(m.get("visionModel") or m.get("textModel") or "")
        if self._open_url(url):
            self._set_dl_msg("已打开官方模型库：" + url)
        else:
            self._set_dl_msg("打不开浏览器：请手动访问 " + url, ok=False)

    def _selected_models(self) -> list:
        out = []
        for key2 in ("textModel", "visionModel"):
            cb = getattr(self, "_combo_" + key2, None)
            var = getattr(cb, "_et_var", None) if cb is not None else None
            n = str(var.get()).strip() if var is not None else ""
            if n and n not in out:
                out.append(n)
        return out

    def _pull_models(self):
        """一键下载：把当前选中的模型交给本机 Ollama 从官方库拉下来。"""
        names = self._selected_models()
        if not names:
            self._set_dl_msg("先在上面选好模型，或手动填一个模型名。", ok=False)
            return
        self._set_dl_msg("正在下载 %s …（有几个 GB，可能要几分钟）" % "、".join(names))
        threading.Thread(target=self._pull_worker, args=(names,), daemon=True).start()

    def _pull_worker(self, names):
        ok, msg = ollama_pull(names)
        try:
            self.after(0, lambda: self._pull_done(ok, msg))
        except Exception:
            pass

    def _pull_done(self, ok, msg):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._set_dl_msg(msg, ok=ok)
        if ok:
            self._fetch_models_async()      # 下完顺手刷新列表

    # ————————————————————————— 自启 —————————————————————————
    def _on_autostart(self):
        on = bool(self._autostart_var.get())
        ok = set_autostart(on)
        self._refresh_autostart_label(ok=ok)

    def _refresh_autostart_label(self, ok=True):
        try:
            enabled, _ = autostart_info()
            if enabled is None:
                self._autostart_lbl.configure(text="无法读取注册表项", fg=MUTED)
            elif not ok:
                self._autostart_lbl.configure(text="修改失败（权限不足？）", fg=ERR)
            else:
                self._autostart_lbl.configure(
                    text="已开启 · 关闭窗口仍可取词" if enabled else "未开启 · 需手动打开",
                    fg=MUTED)
        except Exception:
            pass

    # ————————————————————————— 动作 —————————————————————————
    def _toggle(self):
        # 大按钮不绑变量（Button 没有 variable），点一下自己翻转状态
        on = not bool(self.enabled_var.get())
        self.enabled_var.set(on)
        self._set(on, path="enabled")
        self._refresh_toggle()
        if self.on_toggle:
            self.on_toggle(on)
        self.set_status("已启用" if on else "已暂停")

    def _refresh_toggle(self):
        """大按钮的字面与配色跟着开关走：开着 = 绿底「点此关闭」，关着 = 灰底「点此开启」。"""
        on = bool(self.enabled_var.get())
        try:
            self.enable_btn.configure(
                text="翻译已开启 · 点此关闭" if on else "翻译已关闭 · 点此开启",
                bg=OK if on else "#9aa3b2", fg="#ffffff",
                activebackground="#128040" if on else "#8b93a1",
                activeforeground="#ffffff")
        except Exception:
            pass

    def _test(self):
        if not self.test_text:
            return
        self.result_lbl.configure(text="查询中…", fg=MUTED)

        def run():
            ok, msg = self.test_text()
            self.after(0, lambda: self.result_lbl.configure(text=msg, fg=OK if ok else ERR))
        threading.Thread(target=run, daemon=True).start()

    def _reset(self):
        # 一键清掉全部设置是不可逆的 —— 可见时先问一句（自动化/无界面调用直接跳过）
        try:
            if self.winfo_viewable():
                from tkinter import messagebox
                if not messagebox.askyesno("恢复默认设置", "将重置全部设置（含翻译开关与模型配置），确定继续？"):
                    return
        except Exception:
            pass
        if self.on_reset:
            self.on_reset()
        self.result_lbl.configure(text="已恢复默认设置", fg=OK)

    on_reset = None

    def set_status(self, text: str):
        try:
            self.status_lbl.configure(text=text)
            on = bool(self.enabled_var.get())
            self._state_lbl.configure(text=text)
            self._dot.configure(fg=OK if on else MUTED)
            self._refresh_footer()
        except Exception:
            pass

    def set_enabled(self, on: bool):
        """外部改了配置（热加载）时同步界面 —— 只管显示，不再回写、不触发回调。"""
        try:
            if bool(self.enabled_var.get()) != bool(on):
                self.enabled_var.set(bool(on))
                self._refresh_toggle()
        except Exception:
            pass

    def set_gaming(self, gaming: bool):
        """打游戏中：守护会把整条取词链停掉 —— 在这里给一句解释，免得用户以为坏了。"""
        try:
            self._gaming_lbl.configure(
                text="全屏应用中 · 已自动暂停" if gaming else "",
                fg=NAVY if gaming else MUTED)
        except Exception:
            pass

    def set_runtime(self, uptime_s=None, last_lookup=0.0, gaming=None, enabled=None):
        """「运行状态」三行刷新（App 每 0.6 秒推一次，都在 Tk 主线程里）。"""
        def _ago(t):
            if not t:
                return "尚无记录"
            d = max(0, int(time.time() - t))
            if d < 5:
                return "刚刚"
            if d < 60:
                return f"{d} 秒前"
            if d < 3600:
                return f"{d // 60} 分钟前"
            return f"{d // 3600} 小时前"
        try:
            if uptime_s is not None:
                u = max(0, int(uptime_s))
                up = (f"{u // 3600} 小时 {u % 3600 // 60} 分" if u >= 3600
                      else (f"{u // 60} 分 {u % 60} 秒" if u >= 60 else f"{u} 秒"))
                head = "运行中" if enabled is not False else "运行中（翻译已暂停）"
                self._rt_rows["svc"].configure(text=f"{head} · 已运行 {up}")
            if last_lookup is not None:
                self._rt_rows["last"].configure(text=_ago(last_lookup))
            if gaming is not None:
                self._rt_rows["game"].configure(
                    text="正在暂停（全屏应用）" if gaming else "未触发",
                    fg=WARN if gaming else INK)
            # Ollama 状态：轻量刷新（端口探测，3 秒一次就够）
            if time.time() - getattr(self, "_ollama_last", 0.0) > 3.0:
                self._ollama_last = time.time()
                self.refresh_ollama()
        except Exception:
            pass


def _to_photo(img: Image.Image):
    """PIL → tk.PhotoImage。走 Pillow 的 ImageTk（Pillow 已是依赖），
    不自己拼 base64/PPM —— 那条路 Tk 会报「couldn't recognize image data」。"""
    from PIL import ImageTk
    return ImageTk.PhotoImage(img.convert("RGB"))
