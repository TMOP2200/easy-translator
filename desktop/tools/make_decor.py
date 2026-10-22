# -*- coding: utf-8 -*-
"""生成默认装饰图：assets/decor.png —— **金鱼娘**（卡片右下角贴的那张）。

用户定的：「默认装饰改成金鱼娘」+「只留默认装饰，而不加立绘」+「总览图不支持导入」。
仓库里那张彩色的只在 `docs/mascot-preview.png` 里，而且是个 **852×452 的两姿势拼版**，
直接拿去贴会在卡片右下角出现**两个头**；它的底又是项目自己的浅灰 `#E2E6EE`，
而卡片是纯白 —— 不抠底就会露出一个灰方块。

所以这个脚本干两件事（实现都在 `et_desktop/ui.py` 里，脚本只是把它跑成产物）：
  1. 只取拼版**左半张** → 单张立绘；
  2. **从四边洪水填充**抠掉灰底（不能用「全图白→透明」：她头饰、袜子本身是白的，会被掏空）。

产物：
  assets/decor.png        默认装饰（RGBA，透明底）

用法：
  python desktop/tools/make_decor.py            # 生成/更新 assets/decor.png
  python desktop/tools/make_decor.py --check    # 只看当前那张在不在、尺寸对不对（CI/自检用）
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                                        # noqa: E402
from et_desktop import ui                                    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="生成默认装饰图 assets/decor.png（金鱼娘）")
    ap.add_argument("--check", action="store_true", help="只检查当前产物，不重新生成")
    ap.add_argument("--sheet", default=ui.DECOR_SHEET, help="彩色立绘的来源（默认 docs/mascot-preview.png）")
    ap.add_argument("--out", default=ui.DECOR_DEFAULT, help="产物路径（默认 assets/decor.png）")
    args = ap.parse_args()

    if args.check:
        if not os.path.exists(args.out):
            print(f"缺少产物：{args.out}（跑一次 python desktop/tools/make_decor.py 生成）")
            return 1
        im = Image.open(args.out)
        ok = im.mode == "RGBA" and im.getextrema()[3][0] == 0        # 必须有全透明像素（抠过底）
        print(f"{args.out}  {im.size}  {im.mode}  抠底={'是' if ok else '否'}")
        return 0 if ok else 1

    ok, msg = ui.import_decor_colored(sheet=args.sheet, dest=args.out)
    print(msg)
    if ok:
        im = Image.open(args.out)
        print(f"产物：{args.out}  {im.size}  {im.mode}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
