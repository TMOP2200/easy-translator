# -*- coding: utf-8 -*-
"""极简测试运行器 —— 让 pytest 风格（`def test_x(monkeypatch, tmp_path)`）的测试
文件在**没装 pytest 的环境**里也能真跑起来。

为什么需要它：venv 里没有 pytest，而 pytest 风格的文件 `python tests/xxx.py` 跑完
是「零条测试、退出码 0」—— 看着是 PASS，其实是空的（2026-10-04 实测 test_compound/
test_uia_widen/test_gaming_flag 三个文件都是这种假绿）。

用法（放在文件末尾）：
    if __name__ == "__main__":
        import os, sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _minipytest import run
        raise SystemExit(run(globals()))

支持的 fixture 只有两个（够用就好）：`tmp_path`（每次一个全新临时目录，跑完删掉）、
`monkeypatch`（setattr / setenv / delenv，跑完自动还原）。
"""
import inspect
import os
import shutil
import tempfile
import traceback


class _MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name, None), hasattr(obj, name)))
        setattr(obj, name, value)

    def setenv(self, name, value):
        self._undo.append((os.environ, name, os.environ.get(name), name in os.environ))
        os.environ[name] = str(value)

    def delenv(self, name, raising=True):
        self._undo.append((os.environ, name, os.environ.get(name), name in os.environ))
        if name in os.environ:
            del os.environ[name]
        elif raising:
            raise KeyError(name)

    def undo(self):
        for obj, name, old, existed in reversed(self._undo):
            try:
                if existed:
                    setattr(obj, name, old)
                else:
                    try:
                        delattr(obj, name)
                    except Exception:
                        if obj is os.environ:
                            os.environ.pop(name, None)
            except Exception:
                pass
        self._undo = []


def run(namespace: dict) -> int:
    tests = [(k, v) for k, v in namespace.items()
             if k.startswith("test_") and callable(v)]
    ok = bad = 0
    for name, fn in tests:
        try:
            n_args = len([p for p in inspect.signature(fn).parameters.values()
                          if p.default is inspect.Parameter.empty])
        except Exception:
            n_args = 0
        fixtures = {}
        tmp = None
        if n_args:
            params = list(inspect.signature(fn).parameters)
            if "tmp_path" in params:
                tmp = tempfile.mkdtemp(prefix="minipytest-")
                fixtures["tmp_path"] = __import__("pathlib").Path(tmp)
            if "monkeypatch" in params:
                fixtures["monkeypatch"] = _MonkeyPatch()
        try:
            fn(**fixtures)
            ok += 1
        except Exception:
            bad += 1
            print("FAIL %s" % name)
            traceback.print_exc()
        finally:
            if "monkeypatch" in fixtures:
                fixtures["monkeypatch"].undo()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    print("Ran %d test(s)：%d ok, %d failed" % (len(tests), ok, bad))
    return 0 if bad == 0 and tests else 1
