# -*- coding: utf-8 -*-
"""打包入口 —— 只有 PyInstaller 用它（源码运行时用 `python -m et_desktop`）。

为什么单独一个文件：PyInstaller 是把这个脚本当**顶层脚本**执行的，
包内的 `__main__.py` 里 `from .app import ...` 那种相对导入会找不到包上下文。
这里先把自己的目录塞进 sys.path，再按绝对包名导入。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from et_desktop.app import main          # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
