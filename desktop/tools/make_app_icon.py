# -*- coding: utf-8 -*-
"""生成桌面 App 图标：assets/easy-translator.ico —— **ET 艺术字，黑字白底**。

为什么是白底黑字（用户定的）：
  · 立绘是黑白墨线，透明底到深色任务栏/壁纸上会糊；ET 字样本身就是黑白语言，白底最干净；
  · 小尺寸（16/32px）下图形会糊成一团，**字母反而认得出来** —— 图标的本职就是「一眼认出是谁」。

几种「艺术字」风格（`--style`，都能在预览表里并排看）：
  black   Arial Black —— 最稳、16px 也清楚（默认）
  impact  Impact —— 更窄更重，方片里更满
  amber   华文琥珀 —— 圆润粗体，中文艺术字体的拉丁字形
  ink     Ink Free —— 手写墨线，和最上面的立绘同一路子（小尺寸会糊，慎用）

产物：
  assets/easy-translator.ico                多尺寸（16/24/32/48/64/128/256）
  <TEMP>/easy-translator-icon-preview.png   `--preview` 时输出：各风格 × 各尺寸的对照表

用法：
  python desktop/tools/make_app_icon.py                      # 用默认风格生成 .ico
  python desktop/tools/make_app_icon.py --style impact       # 换风格
  python desktop/tools/make_app_icon.py --preview            # 额外输出对照表（所有风格）
"""
from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_ICO = os.path.join(ROOT, "assets", "easy-translator.ico")
FONTS = r"C:\Windows\Fonts"

# 风格 → (字体文件, 字面占比, 说明, 描边加厚比例)。占比 = 「ET」两条墨迹的总宽 占 方片边长 的比例；
# 描边比例 = 额外描边宽度占字号的比例（手写体太细，加厚后小尺寸才认得出，也更像「艺术字」）。
STYLES = {
    "black":   ("ariblk.ttf", 0.60, "Arial Black（最稳，16px 也清楚）", 0.0),
    "impact":  ("impact.ttf", 0.62, "Impact（窄而重）", 0.0),
    "amber":   ("STHUPO.TTF", 0.62, "华文琥珀（圆润粗体）", 0.0),
    "inkbold": ("Inkfree.ttf", 0.58, "手写加粗（墨线味）", 0.07),
    "ink":     ("Inkfree.ttf", 0.58, "Ink Free 细体", 0.0),
}
LABEL_FONT = os.path.join(FONTS, "arial.ttf")

INK = (17, 17, 17, 255)          # 黑字（不纯 0 是为了在现代屏上不那么死）
WHITE = (255, 255, 255, 255)
BORDER = (226, 230, 239, 255)    # 极浅描边：白底压在浅色壁纸上时不然看不出边界
SIZES = (16, 24, 32, 48, 64, 128, 256)
SS = 4                           # 超采样倍数：文字按 4 倍画完再缩，小尺寸才不毛


def _fit_font(draw, text, path, canvas, ratio, stroke_ratio=0.0):
    """二分出「墨迹宽度 ≈ canvas×ratio」的字号（按实际 textbbox 量，不按字号猜）。

    描边会让墨迹更宽，所以量的 bbox 要带上 `stroke_width`（Pillow ≥ 8 支持），
    否则加粗的那档会溢出画布。
    """
    lo, hi, best = 4, canvas, None
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            f = ImageFont.truetype(path, mid)
        except Exception:
            return None
        sw = int(round(mid * stroke_ratio)) if stroke_ratio else 0
        bb = draw.textbbox((0, 0), text, font=f, stroke_width=sw)
        if (bb[2] - bb[0]) <= canvas * ratio:
            best = (f, bb, sw)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def make_icon(text: str, size: int, style: str = "black", border: bool = True) -> Image.Image:
    """一块白底圆角方片 + 居中的黑字。按 size 超采样绘制再缩回，保证小尺寸质量。"""
    font_file, ratio, _desc, stroke_ratio = STYLES.get(style, STYLES["black"])
    path = os.path.join(FONTS, font_file)
    c = size * SS
    tile = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    radius = max(2, int(round(c * 0.22)))
    line = 0
    if border and size >= 32:                    # 16px 加描边只会糊
        line = max(1, int(round(c * 0.03)))
    d.rounded_rectangle([0, 0, c - 1, c - 1], radius=radius, fill=WHITE,
                        outline=BORDER if line else None, width=line)

    pad = int(round(c * (0.04 if size <= 32 else 0.08)))
    box = c - 2 * pad
    got = _fit_font(d, text, path, box, ratio, stroke_ratio) if os.path.exists(path) else None
    if got is None:                              # 字体不在就退回 Pillow 默认位图字体
        f = ImageFont.load_default()
        bb = d.textbbox((0, 0), text, font=f)
        sw = 0
    else:
        f, bb, sw = got
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((c - w) // 2 - bb[0], (c - h) // 2 - bb[1]), text, font=f, fill=INK,
           stroke_width=sw, stroke_fill=INK)
    return tile.resize((size, size), Image.LANCZOS)


def make_preview(text="ET", styles=None, sizes=(256, 48, 32, 16)) -> str:
    """各风格 × 各尺寸的对照表（浅灰底模拟桌面 + 每行左侧写风格名）。"""
    styles = styles or list(STYLES)
    gap, pad, label_w = 18, 22, 150
    rows = [make_icon(text, 256, s) for s in styles]
    cell = max(i.height for i in rows)
    W = pad * 2 + label_w + sum(cell if s == 256 else s for s in sizes) + gap * (len(sizes) + 1)
    H = pad * 2 + cell * len(styles) + gap * (len(styles) - 1) + 40
    sheet = Image.new("RGB", (W, H), (233, 236, 242))
    d = ImageDraw.Draw(sheet)
    try:
        lf = ImageFont.truetype(LABEL_FONT, 18)
        hf = ImageFont.truetype(LABEL_FONT, 16)
    except Exception:
        lf = hf = ImageFont.load_default()
    x0 = pad + label_w
    for s in sizes:
        d.text((x0 + 4, 10), "%dpx" % s, font=hf, fill=(90, 96, 110))
        x0 += cell if s == 256 else s
        x0 += gap
    y = pad + 34
    for st in styles:
        d.text((pad, y + cell // 2 - 12), "%s — %s" % (st, STYLES.get(st, ("", 0, ""))[2]),
               font=lf, fill=(40, 48, 64))
        x = pad + label_w
        for s in sizes:
            img = rows[styles.index(st)] if s == 256 else make_icon(text, s, st)
            slot = cell if s == 256 else s
            sheet.paste(img, (x, y + (cell - img.height) // 2), img)
            x += slot + gap
        y += cell + gap
    out = os.path.join(os.environ.get("TEMP", "."), "easy-translator-icon-preview.png")
    sheet.save(out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 ET 艺术字图标（黑字白底）")
    ap.add_argument("--style", default="black", choices=sorted(STYLES) + ["all"])
    ap.add_argument("--text", default="ET")
    ap.add_argument("--no-border", action="store_true", help="不要那圈极浅描边（纯白底）")
    ap.add_argument("--preview", action="store_true", help="输出各风格对照表")
    args = ap.parse_args(argv)

    if args.style == "all":
        print("对照表 → %s" % make_preview(args.text))
        return 0
    base = make_icon(args.text, 256, args.style, border=not args.no_border)
    base.save(OUT_ICO, sizes=[(s, s) for s in SIZES])
    print("图标 → %s（%d 字节，风格 %s，%d 个尺寸）"
          % (OUT_ICO, os.path.getsize(OUT_ICO), args.style, len(SIZES)))
    if args.preview:
        print("对照表 → %s" % make_preview(args.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
