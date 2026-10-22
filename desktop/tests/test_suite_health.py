# -*- coding: utf-8 -*-
"""测试套件自己的健康检查：每个 tests/test_*.py 都必须**真的会跑测试**。

来由（2026-10-04）：venv 里没有 pytest，而 pytest 风格的三个文件
（test_compound / test_uia_widen / test_gaming_flag）跑起来是
「零条测试、退出码 0」—— 看着全绿，其实什么都没验。
这里静态钉住：每个测试文件都要有 runner（`unittest.main()` 或 `_minipytest.run`）。

跑：python tests/test_suite_health.py
"""
import glob
import io
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class SuiteHealthCase(unittest.TestCase):
    def _files(self):
        return sorted(glob.glob(os.path.join(HERE, "test_*.py")))

    def test_there_are_test_files(self):
        self.assertGreaterEqual(len(self._files()), 10, "测试文件少得可疑")

    def test_every_test_file_has_a_runner(self):
        bad = []
        for p in self._files():
            s = io.open(p, encoding="utf-8").read()
            if "unittest.main(" not in s and "_minipytest import run" not in s:
                bad.append(os.path.basename(p))
        self.assertEqual([], bad, "这些测试文件跑起来是空的（没有 runner）：%s" % bad)

    def test_every_test_file_has_tests(self):
        bad = []
        for p in self._files():
            s = io.open(p, encoding="utf-8").read()
            if not re.search(r"def test_|\(unittest\.TestCase\)", s):
                bad.append(os.path.basename(p))
        self.assertEqual([], bad, "这些测试文件里没有任何测试：%s" % bad)


if __name__ == "__main__":
    unittest.main(verbosity=1)
