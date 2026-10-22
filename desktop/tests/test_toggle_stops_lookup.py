# -*- coding: utf-8 -*-
"""总开关关掉后，取词**一次都不许发生**（这是 App 的核心承诺）。

判据不用「卡片有没有弹」，也不用「光标有没有动」——那些都受环境干扰。
直接给取词入口装计数器：`textgrab.word_at_point` 被调用几次就是「取词发生几次」。
开着 → 次数持续增长；关掉 → 计数必须冻住（且热加载之后立刻冻住）。

跑：python tests/test_toggle_stops_lookup.py   （unittest，不需要 pytest）
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))


class ToggleStopsLookupCase(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("无 tkinter")
        from et_desktop import app as A
        self.A = A
        self.tmp = tempfile.mkdtemp(prefix="et-toggle-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)  # 跑完自己收拾，别在 %TEMP% 积着
        self._saved = (A.CFG_PATH, A.CFG_DIR, A.SHOW_FLAG, A.DAEMON_MUTEX)
        A.CFG_DIR = self.tmp
        A.CFG_PATH = os.path.join(self.tmp, "config.json")
        A.SHOW_FLAG = os.path.join(self.tmp, "show.flag")
        A.DAEMON_MUTEX = "EasyTranslatorTestMutex2-%d" % os.getpid()
        # 取词入口换成计数器（真实取词要 UIA + OCR，慢且会写本机轨迹）
        self.calls = {"n": 0}
        self._real_wa = A.textgrab.word_at_point

        def fake(x, y, cfg):
            self.calls["n"] += 1
            return None, None

        A.textgrab.word_at_point = fake
        self.cfg = dict(A.DEFAULTS)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = lambda *a: None

    def tearDown(self):
        A = self.A
        A.textgrab.word_at_point = self._real_wa
        try:
            self.root.destroy()
        except Exception:
            pass
        A.CFG_PATH, A.CFG_DIR, A.SHOW_FLAG, A.DAEMON_MUTEX = self._saved

    def _pump(self, seconds):
        """跑 Tk 主循环若干秒（watcher 是独立线程，会一起动）。"""
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.root.update()
            except Exception:
                break
            time.sleep(0.02)

    def test_disabled_means_zero_lookups_and_hot_reload_stops_immediately(self):
        A = self.A
        self.cfg["enabled"] = True
        app = A.App(self.cfg, self.root, lambda: None, headless=True)
        app.watcher.start()
        try:
            self._pump(2.0)
            on_calls = self.calls["n"]
            self.assertGreater(on_calls, 0, "开着的时候应该一直在取词（计数没动 = 探针本身坏了）")

            # 1) 内存里关掉（= 点大按钮走的那条路）
            self.cfg["enabled"] = False
            self._pump(1.0)
            after_off = self.calls["n"]
            self._pump(1.5)
            self.assertEqual(after_off, self.calls["n"],
                             "关掉后 watcher 仍在取词：开关没接进取词循环")

            # 2) 再打开（= 点大按钮打开）
            self.cfg["enabled"] = True
            self._pump(1.5)
            self.assertGreater(self.calls["n"], after_off, "重新打开后应恢复取词")

            # 3) 外部改文件 → 热加载 → 立刻停
            before_hot = self.calls["n"]
            with open(A.CFG_PATH, "w", encoding="utf-8") as f:
                json.dump({"enabled": False, "dwellMs": 2000}, f)
            st = os.stat(A.CFG_PATH)
            os.utime(A.CFG_PATH, (st.st_atime + 5, st.st_mtime + 5))
            app._reload_cfg_if_changed()
            self.assertFalse(self.cfg["enabled"])
            self._pump(1.0)
            hot_off = self.calls["n"]
            self._pump(1.5)
            self.assertEqual(hot_off, self.calls["n"],
                             "外部改配置热加载后 watcher 仍在取词")
            self.assertLess(hot_off - before_hot, 200, "热加载到停之间有太长的尾巴")
        finally:
            app.watcher.stop_flag = True
            threading.Event().wait(0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
