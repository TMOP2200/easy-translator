# -*- coding: utf-8 -*-
"""_fire 全链路回归：Watcher 线程里**不许碰 App 的方法**。

2026-10-08 事故：_fire 里写了 `self._scale(...)`（_scale 是 App 的、Watcher 没有）——
每次悬停认出词后渲染必炸（AttributeError），卡片永远弹不出来，而单测全绿
（旧的测试没有真正走到「认出词 → 渲染 → 弹卡片」这条链）。
本测试直接把 _fire 驱动到底：修好前必红。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from et_desktop import app as A            # noqa: E402
from et_desktop import lookup as L         # noqa: E402


class _Panel:
    """假面板：after 立即执行；记下 show_bubble 的调用。"""

    def __init__(self):
        self.shown = []

    def after(self, ms, fn):
        fn()

    def show_bubble(self, img, x, y, word):
        self.shown.append((img, x, y, word))


class FirePathCase(unittest.TestCase):

    def setUp(self):
        self._orig_lookup = L.lookup
        self._orig_has = L.has_definition

    def tearDown(self):
        L.lookup, L.has_definition = self._orig_lookup, self._orig_has

    def test_fire_renders_and_shows_without_touching_app_methods(self):
        entry = {"word": "hello", "phonetics": {"uk": "həˈləʊ", "us": "həˈloʊ"},
                 "poses": [{"pos": "int.", "meaning": "喂"}], "examples": [],
                 "source": "测试"}
        L.lookup = lambda word, cfg: entry
        L.has_definition = lambda d: True

        img = object()                      # 渲染产物随便给个哨兵
        panel = _Panel()
        w = A.Watcher({"logWords": False}, lambda data, x, y: img, panel)
        w._fire("hello", 10, 20, "uia")     # 旧代码在这里 AttributeError: _scale
        self.assertEqual(1, len(panel.shown), "认出词后必须走到弹卡片")
        self.assertIs(img, panel.shown[0][0])
        self.assertEqual("hello", (w._last_data or {}).get("word"))

    def test_fire_never_raises_when_render_fails(self):
        """渲染炸了也只写日志，绝不把守护线程带死。"""
        L.lookup = lambda word, cfg: {"word": "x", "poses": [{"pos": "", "meaning": "y"}]}
        L.has_definition = lambda d: True

        def boom(data, x, y):
            raise RuntimeError("渲染坏了")
        panel = _Panel()
        w = A.Watcher({"logWords": False}, boom, panel)
        w._fire("x", 1, 1, "uia")           # 不许抛
        self.assertEqual(0, len(panel.shown))


if __name__ == "__main__":
    unittest.main(verbosity=2)
