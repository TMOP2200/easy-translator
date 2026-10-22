# -*- coding: utf-8 -*-
"""核对「窗口/任务栏图标」与「桌面快捷方式图标」是不是同一枚 assets/easy-translator.ico。

为什么要单独核对：
  · `wm_iconbitmap()` 那个**取值**在窗口 map 之前恒为空串 —— 拿它断言会假绿；
  · pythonw 启动的 GUI 若不声明 AppUserModelID，任务栏可能照样用解释器自己的图标/分组；
  · 桌面快捷方式读的是 .lnk 里的 IconLocation，跟窗口图标是**两条独立的链**，
    只改一条就会出现「桌面是小吉祥物、任务栏是 Tk 羽毛」这种不一致。

做法：找 et_desktop 的可见窗口 → `WM_GETICON`（拿不到退 `GetClassLongPtr`）→
`GetIconInfo` + `GetDIBits` 抠出真实像素 → 与 .ico 逐像素比 → 报匹配率；
再读桌面 `Easy Translator.lnk` 的 IconLocation 是否指向同一枚文件。

用法：python desktop/tools/check_window_icon.py        退出码 0 = 两边一致且是白底方片
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICO = os.path.join(ROOT, "assets", "easy-translator.ico")
TITLE_KEY = "Easy Translator"

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32

WM_GETICON, ICON_SMALL, ICON_BIG = 0x007F, 0, 1
GCLP_HICON, GCLP_HICONSM = -14, -34
DIB_RGB_COLORS = 0

# 64 位下 HANDLE 是指针：不声明 argtypes/restype 的话，ctypes 默认按 c_int 传，
# 句柄会被截断（DeleteObject 报 OverflowError: int too long to convert）。
PVOID = ctypes.c_void_p
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.restype = ctypes.c_void_p
u32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetClassLongPtrW.restype = PVOID
u32.GetIconInfo.argtypes = [PVOID, ctypes.c_void_p]
u32.GetIconInfo.restype = wintypes.BOOL
u32.GetDC.argtypes = [wintypes.HWND]
u32.GetDC.restype = PVOID
u32.ReleaseDC.argtypes = [wintypes.HWND, PVOID]
u32.ReleaseDC.restype = ctypes.c_int
g32.GetObjectW.argtypes = [PVOID, ctypes.c_int, ctypes.c_void_p]
g32.GetObjectW.restype = ctypes.c_int
g32.GetDIBits.argtypes = [PVOID, PVOID, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.UINT]
g32.GetDIBits.restype = ctypes.c_int
g32.DeleteObject.argtypes = [PVOID]
g32.DeleteObject.restype = wintypes.BOOL


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def find_windows():
    """所有 et_desktop 窗口 (hwnd, 标题, 是否可见)。

    可见性只影响「任务栏有没有按钮」，图标本身是设在窗口上的 —— 所以隐藏的窗口也照样核对，
    只是提示一句（用户点过 × 就会是这种状态）。
    """
    out = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _l):
        n = u32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if TITLE_KEY in buf.value:
                out.append((hwnd, buf.value, bool(u32.IsWindowVisible(hwnd))))
        return True

    u32.EnumWindows(PROC(cb), 0)
    return out


def window_hicon(hwnd, big=True):
    """窗口当前的图标句柄：先问 WM_GETICON，再退到窗口类的图标。"""
    h = u32.SendMessageW(hwnd, WM_GETICON, ICON_BIG if big else ICON_SMALL, 0)
    if not h:
        h = u32.GetClassLongPtrW(hwnd, GCLP_HICON if big else GCLP_HICONSM)
    return h


def hicon_to_image(hicon):
    """HICON → PIL.Image（RGBA）。交给 GDI 抠像素，不看它「应该」是什么。"""
    if not hicon:
        return None
    ii = ICONINFO()
    if not u32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    try:
        if not ii.hbmColor:                     # 单色图标：只有掩码
            return None
        bm = BITMAP()
        if not g32.GetObjectW(ii.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        hdr = BITMAPINFOHEADER()
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth, hdr.biHeight = w, -h        # 负高度 = 自顶向下
        hdr.biPlanes, hdr.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        hdc = u32.GetDC(0)
        try:
            ok = g32.GetDIBits(hdc, ii.hbmColor, 0, h, buf, ctypes.byref(hdr), DIB_RGB_COLORS)
        finally:
            u32.ReleaseDC(0, hdc)
        if not ok:
            return None
        return Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).copy()
    finally:
        for hbm in (ii.hbmColor, ii.hbmMask):
            if hbm:
                try:
                    g32.DeleteObject(ctypes.c_void_p(hbm))
                except Exception:
                    pass


def ico_at(size):
    im = Image.open(ICO)
    want = min(im.info.get("sizes", {(256, 256)}), key=lambda s: abs(s[0] - size))
    im.size = want
    im.load()
    return im.convert("RGBA")


def match_ratio(a: Image.Image, b: Image.Image, tol=12) -> float:
    """两张图逐像素比（只统计 a 的不透明像素），返回匹配率。"""
    if b.size != a.size:
        b = b.resize(a.size, Image.LANCZOS)
    ap, bp = a.load(), b.load()
    tot = hit = 0
    for y in range(a.height):
        for x in range(a.width):
            r, g, bl, al = ap[x, y]
            if al < 200:
                continue
            tot += 1
            r2, g2, b2, _ = bp[x, y]
            if abs(r - r2) <= tol and abs(g - g2) <= tol and abs(bl - b2) <= tol:
                hit += 1
    return (hit / tot) if tot else 0.0


def shortcut_icon():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$w=New-Object -ComObject WScript.Shell;"
             "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Easy Translator.lnk';"
             "if(Test-Path $p){$w.CreateShortcut($p).IconLocation}"],
            capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception as e:
        return "读不到：%r" % (e,)


def main() -> int:
    if not os.path.exists(ICO):
        print("没有 %s（先跑 tools/make_app_icon.py）" % ICO)
        return 2
    wins = find_windows()
    if not wins:
        print("没找到 et_desktop 的控制窗口（先双击桌面上的 Easy Translator 把窗口叫出来）")
        return 2
    ok = True
    for hwnd, title, visible in wins:
        print("窗口 %s  (hwnd=%s%s)" % (title, hwnd, "" if visible else "，当前隐藏 —— 任务栏不会有按钮"))
        for big, name in ((True, "大图标(任务栏/Alt-Tab)"), (False, "小图标(标题栏)")):
            img = hicon_to_image(window_hicon(hwnd, big))
            if img is None:
                print("  %-22s 取不到" % name)
                ok = False
                continue
            mine = ico_at(img.width)
            ratio = match_ratio(mine, img)
            white = sum(1 for px in img.getdata() if px[3] > 200 and min(px[:3]) > 240)
            opaque = sum(1 for px in img.getdata() if px[3] > 200)
            print("  %-22s %dx%d  与 .ico 匹配 %.0f%%   白底像素 %d/%d"
                  % (name, img.width, img.height, ratio * 100, white, max(1, opaque)))
            if ratio < 0.8:
                ok = False
    loc = shortcut_icon()
    same = os.path.normcase(ICO) in os.path.normcase(loc)
    print("桌面快捷方式图标：%s  → %s" % (loc or "(空)", "同一枚 .ico ✔" if same else "不一致 ✘"))
    ok = ok and same
    print("\n结论：" + ("任务栏/窗口/桌面三处一致，且是白底方片" if ok else "有不一致项，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
