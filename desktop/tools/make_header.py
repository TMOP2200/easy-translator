# -*- coding: utf-8 -*-
"""生成 README 头图（鲸鱼娘立绘 + 标题）→ docs/mascot-header.png

桌面端设置窗口的「总览图」读的就是这张（README 头图固定、不支持导入）。
素材：assets/decor.png（卡片右下角那张立绘，同一张）。

    python desktop/tools/make_header.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(REPO, "assets", "decor.png")
OUT = os.path.join(REPO, "docs", "mascot-header.png")

W, H = 1200, 520
BG = (246, 247, 249, 255)       # 浅灰底
CARD = (255, 255, 255, 255)     # 白卡片
LINE = (229, 231, 235, 255)     # 细边框
INK = (27, 42, 74, 255)         # 藏青（与程序界面一致）
MUTED = (107, 114, 128, 255)

FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/Deng.ttf",
)


def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    if not os.path.exists(SRC):
        raise SystemExit("找不到立绘：%s" % SRC)
    girl = Image.open(SRC).convert("RGBA")

    canvas = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    m = 28
    card_bottom = H - m
    d.rounded_rectangle([m, m, W - m, card_bottom], radius=24, fill=CARD, outline=LINE, width=2)

    # —— 立绘：贴右侧，底边与卡片内边对齐（半身像的齐切边因此变成"从画面底部进入"）——
    target_h = card_bottom - m - 6
    scale = target_h / float(girl.height)
    g = girl.resize((max(1, int(girl.width * scale)), target_h), Image.LANCZOS)
    gx = W - m - 46 - g.width
    gy = card_bottom - 2 - g.height

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    a = g.split()[3].point(lambda v: int(v * 0.14))
    dark = Image.new("RGBA", g.size, (17, 24, 39, 255))
    dark.putalpha(a)
    shadow.paste(dark, (gx + 4, gy + 10), dark)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(g, (gx, gy))

    # —— 左侧标题（留白对齐卡片内边距）——
    x0 = m + 62
    title = "Easy Translator"
    sub1 = "悬停查词 · 桌面版"
    sub2 = "全屏应用自动暂停 · 单文件 exe"

    f_title = _font(66)
    f_sub = _font(26)
    d.text((x0, 176), title, font=f_title, fill=INK)
    d.text((x0 + 4, 276), sub1, font=f_sub, fill=INK)
    d.text((x0 + 4, 318), sub2, font=_font(22), fill=MUTED)
    # 一条极细的强调线
    d.rounded_rectangle([x0 + 4, 258, x0 + 96, 262], radius=2, fill=(59, 130, 246, 255))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    canvas.convert("RGB").save(OUT, "PNG", optimize=True)
    print("已生成: %s  %dx%d" % (OUT, W, H))


if __name__ == "__main__":
    main()
