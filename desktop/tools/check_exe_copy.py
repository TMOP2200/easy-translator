# -*- coding: utf-8 -*-
"""查 exe 里到底装的是哪版文案：把单文件 exe 里的 settings_ui 字节码挖出来，找字符串常量。

用途：核对「打包的 exe 是不是最新的」—— 屏幕上的一行小字靠截图认不牢（视觉模型会脑补），
代码对象的常量表是硬证据。

用法：
    python tools/check_exe_copy.py dist/EasyTranslator.exe 停留即显示卡片 停住不动才弹卡片
（参数：exe 路径 + 若干「期望出现的字符串」；只报每个串在不在。）
"""
import sys
import zlib

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))


def _walk_seq(seq, out):
    for x in seq:
        if isinstance(x, str):
            out.add(x)
        elif hasattr(x, "co_consts"):
            walk_consts(x, out)
        elif isinstance(x, (tuple, frozenset, list)):
            _walk_seq(x, out)          # 嵌套元组要**递归**：((\"svc\",\"取词服务\"),…)


def walk_consts(code, out):
    """收集所有字符串常量。

    注意 CPython 会把「全是常量的元组」折叠成一整个 tuple 常量（比如
    `(("svc", "取词服务"), ("last", "最近一次取词"))`）—— 只认 str 和 code
    对象的话，整组字符串都挖不到（曾让检查工具误报「exe 里没有」）。
    """
    _walk_seq(code.co_consts, out)


def strings_in_exe(path):
    import os
    import tempfile

    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    car = CArchiveReader(path)
    # PYZ 在归档里叫 PYZ.pyz（旧版叫 PYZ-00.pyz），按前缀找
    pyz_name = [n for n in car.toc if str(n).startswith("PYZ")][0]
    data = car.extract(pyz_name)
    tmp = os.path.join(tempfile.gettempdir(), "et_check_pyz.pyz")
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        z = ZlibArchiveReader(tmp)
    except Exception:
        z = ZlibArchiveReader(data)  # 有的版本直接吃 bytes
    found = set()
    for name in z.toc:
        if not name.startswith("et_desktop"):
            continue
        try:
            code = z.extract(name)
        except Exception:
            continue
        if hasattr(code, "co_consts"):
            walk_consts(code, found)
    return found


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    exe, needles = sys.argv[1], sys.argv[2:]
    found = strings_in_exe(exe)
    blob = "\n".join(found)
    bad = 0
    for n in needles:
        hit = n in blob
        print(("有  " if hit else "没有") + "：" + n)
        bad += 0 if hit else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
