# -*- coding: utf-8 -*-
"""Ollama 启停控件：找 exe、模型目录推断、按名字取进程、取进程路径。

（不在这里真启/真停 Ollama —— 那是带副作用的操作，测试只覆盖可判定的纯逻辑。）
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from et_desktop import settings_ui as S      # noqa: E402


class FindOllamaCase(unittest.TestCase):

    def test_cached_path_wins(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "ollama.exe")
            open(fake, "wb").close()
            cfg = {"model": {"ollamaExe": fake}}
            self.assertEqual(fake, S.find_ollama(cfg))

    def test_stale_cache_is_ignored(self):
        cfg = {"model": {"ollamaExe": r"C:\definitely\not\here\ollama.exe"}}
        got = S.find_ollama(cfg)
        # 缓存失效就重新找：结果是空串（本机没有官方安装）或真实存在的路径
        self.assertTrue(got == "" or os.path.exists(got))


class ModelsDirCase(unittest.TestCase):

    def test_portable_layout_detected(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "models", "manifests"))
            exe = os.path.join(d, "ollama.exe")
            open(exe, "wb").close()
            self.assertEqual(os.path.join(d, "models"), S.ollama_models_dir(exe))

    def test_standard_layout_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "ollama.exe")
            open(exe, "wb").close()
            self.assertEqual("", S.ollama_models_dir(exe))


class ProcessHelpersCase(unittest.TestCase):

    def test_process_path_of_self(self):
        got = S._process_path(os.getpid())
        self.assertTrue(got.lower().endswith("python.exe") or got.lower().endswith("pythonw.exe"), got)

    def test_pids_by_names_shape(self):
        rows = S._pids_by_names(("python.exe", "pythonw.exe"))
        self.assertIsInstance(rows, list)
        for pid, name in rows:
            self.assertIsInstance(pid, int)
            self.assertIn(name.lower(), ("python.exe", "pythonw.exe"))

    def test_ollama_running_is_bool(self):
        self.assertIsInstance(S.ollama_running(), bool)


class StopWhenIdleCase(unittest.TestCase):
    """本机没跑 Ollama 时，点「关闭」应如实回答「本来就没在运行」。"""

    @unittest.skipIf(S.ollama_running(), "本机 Ollama 正在运行，跳过")
    def test_idle_reports_honestly(self):
        ok, msg = S.stop_ollama()
        self.assertTrue(ok)
        self.assertIn("本来就没在运行", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
