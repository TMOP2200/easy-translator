# -*- coding: utf-8 -*-
"""桌面浮层：吉祥物对话气泡（与浏览器扩展同一套设计语言）。

透明的实现要点：颜色在白底上正常抗锯齿渲染，但 alpha 用**硬边形状蒙版**重写，
再配合 tkinter 的 `-transparentcolor` 抠掉窗外区域 —— 圆角边缘因此没有色键毛边。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from collections import deque
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFont, ImageTk

# —— 设计令牌：与 content/card.css 保持一致 ——
NAVY = (30, 50, 100)
INK = (38, 50, 75)
MUTED = (122, 135, 163)
SKIN = (253, 239, 230)
PAPER = (255, 255, 255)
SOFT = (244, 246, 251)
HAIR = (231, 235, 244)
KEY = (255, 0, 255)              # 色键（窗外区域）

MARGIN = 2                        # 气泡描边外留白
BORDER = 2                        # 描边宽
RADIUS = 18
PAD_X, PAD_Y = 15, 13
MASCOT_W = 72
GUTTER = 26                       # 气泡与她之间的天沟
BOTTOM = 34                       # 底部留给她的高度
MAX_W = 340

_FONTS = {}

# —— 卡片右下角那张装饰立绘（用户可在 App 的「装饰图」大类里换成自己的图）——
# 取图优先级：**应用的那张 > assets/mascot.png**。导入 = 复制进配置目录（原图挪走也不影响），
# 与总览图同一个套路，但这里**必须保留 alpha**（立绘是压在卡片白底上的，丢透明就会变成一块方块）。
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def res_dir() -> str:
    """资源根目录（assets/、docs/ 都在它下面）。

    · 源码运行：仓库根目录；
    · **PyInstaller 打包成 exe 后**：解包目录 `sys._MEIPASS` —— 不认这个，exe 一跑就找不到
      装饰图和那张 README 头图（打包时用 --add-data 把它们塞进去）。
    """
    return getattr(sys, "_MEIPASS", REPO)


DECOR_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EasyTranslator")
DECOR_IMPORTED = os.path.join(DECOR_DIR, "decor-image.png")
DECOR_DEFAULT = os.path.join(res_dir(), "assets", "decor.png")
# 默认装饰的来源（README 里那张**彩色**立绘，852×452，两姿势拼版；底是浅灰 #E2E6EE）
# 它经过 tools/make_decor.py 切单张 + 抠底，产出上面的 assets/decor.png
DECOR_SHEET = os.path.join(REPO, "docs", "mascot-preview.png")


def decor_source(imported: str = None, default: str = None) -> str:
    """装饰立绘用哪张：**应用的 > 默认立绘**（都没有就返回默认路径，调用方自己兜错）。"""
    imp = DECOR_IMPORTED if imported is None else imported
    dft = DECOR_DEFAULT if default is None else default
    for p in (imp, dft):
        if p and os.path.exists(p):
            return p
    return dft


def load_decor(path: str = None):
    """读装饰立绘（RGBA）。**找不到 / 读不了就返回 None** —— 卡片照画，只是右下角没有那张图。

    这条是「下载下来就能用」的关键：万一仓库里那张 assets/decor.png 没跟下来（或被人删了），
    取词本身绝不能因此启动不了。显式给了 path 但读不了时，还会退回默认那张再试一次。
    """
    for cand in ([path] if path else []) + [decor_source()]:
        try:
            if cand and os.path.exists(cand):
                return Image.open(cand).convert("RGBA")
        except Exception:
            continue
    return None


def import_decor_image(src: str, dest: str = None, max_w: int = 800):
    """把用户选的图作为装饰立绘复制进配置目录。返回 (是否成功, 给用户看的一句话)。

    和总览图那条不同：**保留 alpha**（透明 PNG 才贴得进卡片），只在超宽时限宽。
    """
    dest = dest or DECOR_IMPORTED
    try:
        im = Image.open(src).convert("RGBA")
        if im.width > max_w:
            im = im.resize((max_w, max(1, int(round(im.height * max_w / im.width)))), Image.LANCZOS)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im.save(dest, "PNG")
        if im.getextrema()[3][0] < 250:
            return True, "已应用（该图片包含透明背景，可直接置于卡片）"
        return True, "已应用（该图片不含透明背景，将显示为矩形）"
    except Exception as e:
        return False, "无法应用：%s" % e


def _cut_flat_background(im: Image.Image, bg=(226, 230, 238), tol: int = 18) -> Image.Image:
    """把**与四边连通**的纯色底抠成透明（从四边洪水填充）。

    不能用「全图白色→透明」那种做法：她身上的头饰、袜子本身就是白的，会被掏空；
    只吃与边界相连、且颜色接近底色的区域，角色身上的白就安然无恙。
    """
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    bg = tuple(bg)

    def near(c):
        return (c[3] > 0 and abs(c[0] - bg[0]) <= tol
                and abs(c[1] - bg[1]) <= tol and abs(c[2] - bg[2]) <= tol)

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not seen[y * w + x] and near(px[x, y]):
                seen[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and near(px[x, y]):
                seen[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and near(px[nx, ny]):
                seen[ny * w + nx] = 1
                q.append((nx, ny))
    # 收缩一圈：紧贴透明、又很接近底色的那层抗锯齿灰边也吃掉（不碰角色身上的白：白离底色更远）
    fringe = tol * 1.3
    kills = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if (abs(r - bg[0]) <= fringe and abs(g - bg[1]) <= fringe and abs(b - bg[2]) <= fringe
                    and any(0 <= nx < w and 0 <= ny < h and px[nx, ny][3] == 0
                            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))):
                kills.append((x, y))
    for x, y in kills:
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
    return im


def import_decor_colored(sheet: str = None, dest: str = None):
    """从 README 里那张**彩色立绘**拼版切出单张、**抠掉灰底**，写出默认装饰图。

    由 `tools/make_decor.py` 调用来生成 `assets/decor.png`（默认装饰就是它）。
    那张是 852×452 的**两姿势拼版**（左边一张、右边一张），整张拿来贴会出现两个头，
    所以只取左半张；它的底是项目自己的 `#E2E6EE` 浅灰，而卡片是纯白，不抠会露出一个灰方块。
    """
    sheet = sheet or DECOR_SHEET
    dest = dest or DECOR_IMPORTED
    try:
        im = Image.open(sheet).convert("RGBA")
        if im.width > im.height * 1.5:                 # 拼版：只留左半（单张立绘）
            im = im.crop((0, 0, im.width // 2, im.height))
        im = _cut_flat_background(im)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im.save(dest, "PNG")
        return True, "已生成鲸鱼娘（%d×%d，抠底完成）" % im.size
    except Exception as e:
        return False, "生成不了：%s" % e


def _font_path(kind) -> str:
    """按字体族取字体文件：cjk=雅黑、latin=Segoe UI、sym=Segoe UI Symbol。

    sym 这一族是必须的：数学符号（ℱ ℬ ℝ 𝔼 𝒩 𝝀 𝟙 ∑ ∫）在雅黑和 Segoe UI 里都没有字形，
    不单独派字体就会绘制成 □（用户报的方框）。"""
    if kind is True:
        kind = "cjk"
    elif kind is False:
        kind = "latin"
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    table = {
        "cjk": ("msyh.ttc", "msyhbd.ttc"),
        "latin": ("segoeui.ttf", "seguisb.ttf"),
        "sym": ("seguisym.ttf", "seguisym.ttf", "cambria.ttc", "segoeui.ttf"),
    }
    for name in table.get(kind, table["latin"]):
        p = os.path.join(win, name)
        if os.path.exists(p):
            return p
    return os.path.join(win, "arial.ttf")


def font(size: int, bold: bool = False, kind="cjk") -> ImageFont.FreeTypeFont:
    if kind is True:
        kind = "cjk"
    elif kind is False:
        kind = "latin"
    key = (size, bold, kind)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(_font_path(kind), size=size)
    return _FONTS[key]


def _is_cjk(ch: str) -> bool:
    """该用雅黑渲染吗。注意必须含**全角标点 U+FF00–FFEF**（，；（）之类）——
    否则这些字会被派给 Segoe UI，缺字形就画成 □（用户：分号逗号变成了方框）。"""
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x3040 <= o <= 0x30FF
            or 0xAC00 <= o <= 0xD7AF or 0xFF00 <= o <= 0xFFEF or 0xFE30 <= o <= 0xFE4F)


def _is_symbol(ch: str) -> bool:
    """数学/符号区：雅黑与 Segoe UI 都没有这些字形，得走 Segoe UI Symbol。"""
    o = ord(ch)
    return (0x2100 <= o <= 0x214F          # ℒ ℱ ℬ ℝ ℕ ℤ ℙ ℂ ℯ …
            or 0x1D400 <= o <= 0x1D7FF     # 𝒩 𝔼 𝔤 𝝀 𝜽 𝟙（数学字母数字符号）
            or 0x2190 <= o <= 0x21FF       # 箭头 ↔ ⟶
            or 0x2200 <= o <= 0x22FF       # ∑ ∫ ≈ √ ∞ ∈ ∅
            or 0x27C0 <= o <= 0x27EF or 0x2980 <= o <= 0x29FF
            or 0x2A00 <= o <= 0x2AFF or 0x2B00 <= o <= 0x2BFF)


def _kind_of(ch: str) -> str:
    if _is_symbol(ch):
        return "sym"
    return "cjk" if _is_cjk(ch) else "latin"


def _runs(text: str):
    """按字体族切分：中文→雅黑，西文/IPA→Segoe UI，数学符号→Segoe UI Symbol。"""
    out, cur, cur_kind = [], [], None
    for ch in text:
        if ch == " " and cur:               # 空格跟着前一段走
            cur.append(ch)
            continue
        k = _kind_of(ch)
        if cur_kind is None or k == cur_kind:
            cur.append(ch)
            cur_kind = k
            continue
        out.append(("".join(cur), cur_kind))
        cur, cur_kind = [ch], k
    if cur:
        out.append(("".join(cur), cur_kind))
    return out


def _draw_line(draw: ImageDraw.ImageDraw, xy, text: str, size: int, bold: bool, color):
    """混排绘制：中文 / 西文 / 数学符号 各用其字体，逐段排布。返回总宽。"""
    x, y = xy
    for chunk, kind in _runs(text):
        f = font(size, bold, kind)
        draw.text((x, y), chunk, font=f, fill=color)
        x += draw.textlength(chunk, font=f)
    return x - xy[0]


def _line_width(draw, text, size, bold=False) -> float:
    w = 0.0
    for chunk, kind in _runs(text):
        w += draw.textlength(chunk, font=font(size, bold, kind))
    return w


def _wrap(draw, text: str, size: int, bold: bool, max_w: float):
    """按宽度折行（对中英混排逐词测量，避免把词从中间截断）。"""
    lines, cur = [], ""
    for token in _split_tokens(text):
        trial = cur + token
        if cur and _line_width(draw, trial, size, bold) > max_w:
            lines.append(cur.rstrip())
            cur = token.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _split_tokens(text: str):
    out, cur = [], []
    for ch in text:
        cur.append(ch)
        if ch == ' ' or _is_cjk(ch):
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


SPEAK_SIZE = 30      # 发音按钮的边长（CSS 像素，按 scale 缩放）


def speak_rect_for(w: int, h: int, scale: float = 1.0):
    """发音按钮的命中矩形（卡片图像坐标系）。绘制端与点击端都调它 —— 永远对得上。"""
    s = int(SPEAK_SIZE * scale)
    m = int(10 * scale)
    return (int(w) - m - s, m, s, s)


def render_card(entry: dict, mascot: Image.Image = None, scale: float = 1.0,
                examples: int = 2, speak: bool = False) -> Image.Image:
    """把词条渲染成一张带气泡、尾点与吉祥物的卡片图（含硬边 alpha）。"""
    s = scale
    pad_r = int((MASCOT_W + GUTTER) * s)
    bottom = int(BOTTOM * s)
    max_w = int(MAX_W * s)
    inner_w = max_w - pad_r - 2 * (MARGIN + BORDER) - 2 * int(PAD_X * s)

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    f_word, f_body, f_small = int(20 * s), int(13 * s), int(11 * s)

    blocks = []                       # (kind, payload) 用于排版
    blocks.append(("word", entry.get("word") or ""))
    ph = entry.get("phonetics") or {}
    ph_text = "   ".join(x for x in (("英 " + ph["uk"]) if ph.get("uk") else "",
                                     ("美 " + ph["us"]) if ph.get("us") else "") if x)
    if ph_text:
        blocks.append(("phon", ph_text))
    for p in (entry.get("poses") or [])[:8]:
        blocks.append(("pos", (p.get("pos") or "", p.get("meaning") or "")))
    if entry.get("examples") and int(examples) > 0:
        blocks.append(("ex-title", "例句"))
        for ex in entry["examples"][:int(examples)]:
            blocks.append(("ex-en", ex.get("en") or ""))
            if ex.get("zh"):
                blocks.append(("ex-zh", ex.get("zh") or ""))
    if entry.get("source"):
        blocks.append(("foot", entry.get("source")))

    # —— 量高 ——
    gap = int(5 * s)
    heights, lines_of = [], {}
    for kind, payload in blocks:
        if kind == "pos":
            pos, meaning = payload
            ls = _wrap(probe, meaning, f_body, False, inner_w - (int(40 * s) if pos else 0))
            # 注意存 (ls, size) 元组，与其它块一致 —— 存裸 ls 的话绘制端 lines_of[idx][0]
            # 会取到「第一行字符串」，for 循环就逐字符迭代（释义被排成一字一行）。
            lines_of[len(heights)] = (ls, f_body)
            heights.append((len(ls), f_body))
        elif kind in ("ex-en", "ex-zh"):
            size = f_body if kind == "ex-en" else int(12 * s)
            ls = _wrap(probe, payload, size, False, inner_w - int(12 * s))
            lines_of[len(heights)] = (ls, size)
            heights.append((len(ls), size))
        elif kind == "word":
            ls = _wrap(probe, payload, f_word, True, inner_w)
            lines_of[len(heights)] = (ls, f_word)
            heights.append((len(ls), f_word))
        else:
            size = int(12.5 * s) if kind == "phon" else f_small
            ls = _wrap(probe, payload, size, False, inner_w)
            lines_of[len(heights)] = (ls, size)
            heights.append((len(ls), size))

    text_h = sum(n * (int(sz * 1.5)) for n, sz in heights) + gap * (len(blocks) - 1)
    mw = int(MASCOT_W * s) if mascot is not None else 0
    mh = round(mascot.height * mw / mascot.width) if mascot is not None else 0
    bubble_h = int(2 * (MARGIN + BORDER) + 2 * PAD_Y * s) + text_h
    if mh:
        bubble_h = max(bubble_h, mh + int(8 * s))   # 气泡至少要装得下她（loading 态也不能顶出去）
    W = max_w
    H = bubble_h + bottom

    canvas = Image.new("RGBA", (W, H), KEY + (255,))
    draw = ImageDraw.Draw(canvas)

    # —— 气泡：整块白底 + 藏青描边 + 圆角（**不做透明**，深色页面上也看得清）——
    bx0, by0 = MARGIN, MARGIN
    bx1, by1 = W - MARGIN, bubble_h - MARGIN
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=int(RADIUS * s), fill=PAPER,
                           outline=NAVY, width=max(1, int(BORDER * s)))

    # —— 正文 ——
    y = by0 + int(PAD_Y * s)
    for idx, (kind, payload) in enumerate(blocks):
        if kind == "word":
            for ln in lines_of[idx][0]:
                _draw_line(draw, (bx0 + int(PAD_X * s), y), ln, f_word, True, NAVY)
                y += int(f_word * 1.5)
        elif kind == "phon":
            for ln in lines_of[idx][0]:
                _draw_line(draw, (bx0 + int(PAD_X * s), y), ln, int(12.5 * s), False, MUTED)
                y += int(12.5 * s * 1.5)
        elif kind == "pos":
            pos, meaning = payload
            x = bx0 + int(PAD_X * s)
            if pos:
                x += _draw_line(draw, (x, y), pos, int(11.5 * s), True, NAVY) + int(6 * s)
            ls, _sz = lines_of[idx]
            for ln in ls:
                _draw_line(draw, (x, y), ln, f_body, False, INK)
                y += int(f_body * 1.5)
                x = bx0 + int(PAD_X * s)
        elif kind == "ex-title":
            _draw_line(draw, (bx0 + int(PAD_X * s), y), payload, f_small, True, MUTED)
            y += int(f_small * 1.5)
        elif kind in ("ex-en", "ex-zh"):
            ls, size = lines_of[idx]
            x0 = bx0 + int(PAD_X * s) + int(9 * s)
            draw.rectangle([x0 - int(7 * s), y + 1, x0 - int(5 * s), y + int(size * 1.4)], fill=HAIR)
            for ln in ls:
                _draw_line(draw, (x0, y), ln, size, False, INK if kind == "ex-en" else MUTED)
                y += int(size * 1.5)
        elif kind == "foot":
            _draw_line(draw, (bx0 + int(PAD_X * s), y), payload, f_small, False, MUTED)
            y += int(f_small * 1.5)
        y += gap

    # —— 发音按钮（「通用」里开着才画；命中判定用 speak_rect_for，同一函数保证对得上）——
    if speak:
        sx, sy, ssz, _ = speak_rect_for(W, H, s)
        draw.rounded_rectangle([sx, sy, sx + ssz, sy + ssz], radius=int(8 * s),
                               fill=PAPER, outline=HAIR, width=max(1, int(1.2 * s)))
        cx, cy = sx + ssz / 2.0, sy + ssz / 2.0
        r = ssz / 2.0
        draw.rectangle([cx - r * 0.58, cy - r * 0.18, cx - r * 0.30, cy + r * 0.18], fill=NAVY)
        draw.polygon([(cx - r * 0.32, cy - r * 0.18), (cx + r * 0.04, cy - r * 0.46),
                      (cx + r * 0.04, cy + r * 0.46), (cx - r * 0.32, cy + r * 0.18)], fill=NAVY)
        for rr in (0.40, 0.60):
            draw.arc([cx - r * rr, cy - r * rr, cx + r * rr, cy + r * rr],
                     start=-55, end=55, fill=NAVY, width=max(1, int(1.6 * s)))

    # —— 装饰立绘：贴在整个对话框的右下角（白底内，不透明）；没配就不画 ——
    her = None
    mx = my = 0
    if mascot is not None:
        her = mascot.resize((mw, mh), Image.LANCZOS)
        mx, my = W - mw - int(6 * s), by1 - int(2 * s) - mh
        canvas.paste(her, (mx, my), her)

    # —— 尾点按用户要求**不画**（曾压在她脸上，看起来像多了一个黑色小圈圈）——
    pass

    # —— 硬边 alpha：气泡圆角矩形 ∪ 她的轮廓（尾点已按要求去掉）——
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([bx0, by0, bx1, by1], radius=int(RADIUS * s), fill=255)
    if her is not None:
        her_alpha = her.split()[3]
        mask.paste(her_alpha, (mx, my), her_alpha)
    canvas.putalpha(mask)
    return canvas


def load_mascot(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _virtual_bounds():
    """整个虚拟桌面（多显示器、含负坐标）的边界：x, y, w, h。失败退回 (0,0,屏宽,屏高)。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return int(x), int(y), int(w), int(h)
    except Exception:
        pass
    try:
        import tkinter as _tk
        r = _tk._default_root
        if r is not None:
            return 0, 0, r.winfo_screenwidth(), r.winfo_screenheight()
    except Exception:
        pass
    return 0, 0, 0, 0


class Bubble(tk.Toplevel):
    """无边框置顶浮层：承载渲染好的卡片图；鼠标移入钉住、移出收起；点击复制。

    内容**可滚动**（滚轮 + 细滚动条）：词条长时卡片会比屏幕高，必须能滑着看全，
    所以窗口高度封顶（屏高的 MAX_H_RATIO），超出就滚。"""

    MAX_H_RATIO = 0.72          # 窗口最高占屏高比例

    def __init__(self, master, on_copy=None, on_leave=None, on_enter=None, on_click=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        key = "#%02x%02x%02x" % KEY
        self.wm_attributes("-transparentcolor", key)
        self.on_copy = on_copy
        self.on_leave = on_leave
        self.on_enter = on_enter
        self.on_click = on_click
        self._photo = None
        self.canvas = tk.Canvas(self, bd=0, highlightthickness=0, bg=key, cursor="arrow")
        self.sb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview, width=9)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.on_enter and self.on_enter())
        self.canvas.bind("<Leave>", lambda e: self.on_leave and self.on_leave())
        self.canvas.bind("<Button-1>", lambda e: self.on_click and self.on_click(
            self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.bind("<MouseWheel>", self._wheel)          # 窗口本体也接一份（滚轮事件有时落在边框上）
        self.sb.bind("<MouseWheel>", self._wheel)
        self.withdraw()

    def _wheel(self, e):
        self.canvas.yview_scroll(-int((e.delta or 0) / 120), "units")

    def point_in_bubble(self, x: int, y: int, pad: int = 8) -> bool:
        """光标是否在气泡窗口范围内（存下来的矩形，供工作线程安全读取）。

        用来判断「鼠标移开」该不该收起：只要还在气泡上／气泡边上（用户正想过去看或点复制），
        就不收起——不然鼠标刚往气泡方向挪一点，卡片就先消失了。"""
        r = getattr(self, "_rect", None)
        if not r:
            return False
        bx, by, bw, bh = r
        return (bx - pad <= x <= bx + bw + pad) and (by - pad <= y <= by + bh + pad)

    def show(self, img: Image.Image, x: int, y: int):
        self._photo = ImageTk.PhotoImage(img.convert("RGB"))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        w, h = img.size
        vx, vy, vw, vh = _virtual_bounds()
        if not vw:
            vx, vy, vw, vh = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        right, bottom = vx + vw, vy + vh
        view_h = int(min(h, vh * self.MAX_H_RATIO))
        self.canvas.configure(scrollregion=(0, 0, w, h))
        left = x + 14 if x + 14 + w + 10 < right else max(vx + 4, x - w - 24)
        # 优先放光标**上方**：原生悬停提示（VS Code 悬停说明、浏览器提示、系统 tooltip）
        # 几乎都出现在光标下方，放上方就不会盖住它们；上方放不下才落到下方。
        gap = 18
        if y - view_h - gap >= vy + 4:
            top = y - view_h - gap
        elif y + gap + view_h < bottom:
            top = y + gap
        else:
            top = max(vy + 4, y - view_h - gap)
        self.geometry(f"{w + 10}x{view_h}+{int(left)}+{int(top)}")
        # 记下矩形：工作线程靠它判断「光标是不是还在卡片上」（Tk 控件不能跨线程访问）
        self._rect = (int(left), int(top), w + 10, view_h)
        self.canvas.yview_moveto(0)          # 每次都从顶部开始看
        self.deiconify()
        self.lift()
        self._force_topmost()

    def _force_topmost(self):
        """确保浮层压在其它窗口之上 —— 光靠 wm_attributes('-topmost') 不够可靠。"""
        try:
            import win32con
            import win32gui
            hwnd = int(self.frame(), 16) or self.winfo_id()
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        except Exception:
            pass

    def hide(self):
        self._rect = None
        self.withdraw()
