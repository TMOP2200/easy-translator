# -*- coding: utf-8 -*-
"""窗口大小一变，排版得跟着变：说明文字折行宽度、横幅/装饰图预览的宽度都要重算。

用户原话：「排版文字，注意**小窗口文字和大窗口文字的长度不同**」——
写死 wraplength 的后果：窗口拉窄，长句子被右边切掉；窗口拉宽，句子还是窄窄一列。
图和文字同理：宽度写死 700 的话，小窗口里横幅右边会被截掉。

跑：python tests/test_layout_resize.py      （unittest，不需要 pytest）
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from et_desktop import settings_ui as S                 # noqa: E402


def _all_labels(widget, out=None):
    out = [] if out is None else out
    for ch in widget.winfo_children():
        try:
            if ch.winfo_class() == "Label":
                out.append(ch)
        except Exception:
            pass
        _all_labels(ch, out)
    return out


class LayoutResizeCase(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("无 tkinter")
        try:
            self.root = tk.Tk()
        except Exception as e:
            self.skipTest("无法创建 Tk：%s" % e)
        self.root.withdraw()
        self.root.report_callback_exception = lambda *a: None
        from et_desktop import ui
        cfg = {"enabled": True, "dwellMs": 2000, "examplesCount": 3, "showSpeak": True,
               "engine": "auto",
               "model": {"enabled": True, "baseUrl": "http://127.0.0.1:11434/v1", "apiKey": "",
                         "textModel": "qwen2.5vl:3b", "visionModel": "qwen2.5vl:3b",
                         "timeoutMs": 60000},
               "imageOcr": {"enabled": True, "dwellMs": 1500, "cropW": 460, "cropH": 140,
                            "hint": True}}
        self.win = S.SettingsWindow(self.root, cfg, lambda *a: None, mascot=ui.load_decor(),
                                    test_text=lambda: (True, "ok"))
        self.win.update()

    def tearDown(self):
        try:
            self.win.destroy()
            self.root.destroy()
        except Exception:
            pass

    def _wrap_of(self, w):
        return self.win._content_width(w)

    def test_wraplength_follows_window_width(self):
        """窄窗口的折行宽度必须比宽窗口小 —— 这正是「小窗口/大窗口文字长度不同」。"""
        self.win._relayout(1400)
        wide = [lbl.cget("wraplength") for lbl in self.win._wrap_lbls]
        self.win._relayout(560)
        narrow = [lbl.cget("wraplength") for lbl in self.win._wrap_lbls]
        self.assertTrue(wide and narrow, "没有登记任何需要折行的说明文字")
        self.assertGreater(wide[0], narrow[0])
        self.assertEqual(self._wrap_of(1400), wide[0])
        self.assertEqual(self._wrap_of(560), narrow[0])

    def test_all_notes_registered_for_rewrap(self):
        """长句子必须都登记过：漏一个就会写死折行宽度、在窄窗口里被切掉。"""
        missing = [lbl.cget("text")[:40] for lbl in _all_labels(self.win)
                   if len(lbl.cget("text")) > 60 and lbl not in self.win._wrap_lbls]
        self.assertEqual([], missing, "这些长文本没登记折行：%s" % missing)

    def test_banner_shrinks_in_narrow_window(self):
        """横幅要跟着可用宽度缩，但不能超过上限（大窗口里别撑爆）。"""
        self.win._relayout(2000)
        wide = self.win._banner_photo.width()
        self.assertEqual(S.BANNER_W, wide, "大窗口应取上限 %d" % S.BANNER_W)
        self.win._relayout(560)
        narrow = self.win._banner_photo.width()
        self.assertLess(narrow, wide, "窄窗口里横幅没缩小")
        self.assertLessEqual(narrow, max(240, self._wrap_of(560)))

    def test_decor_preview_shrinks_in_narrow_window(self):
        self.win._relayout(2000)
        wide = self.win._decor_photo.width()
        self.win._relayout(380)
        narrow = self.win._decor_photo.width()
        self.assertLessEqual(narrow, wide)
        self.assertLess(narrow, 320, "窄窗口里装饰图预览没缩小")

    def test_relayout_is_idempotent_and_cheap(self):
        """同一宽度重复排不该反复重画图（拖窗口时每像素重画会卡）。"""
        self.win._relayout(900)
        photo = self.win._banner_photo
        self.win._relayout(900)
        self.assertIs(photo, self.win._banner_photo, "同宽度又重画了一遍")

    def test_content_width_is_capped_on_wide_windows(self):
        """窗口最大化时文字不能铺成一整行：折行宽度封顶在 CONTENT_MAX 附近。"""
        self.win._relayout(3000)
        wl = self.win._wrap_lbls[0].cget("wraplength")
        self.assertLessEqual(wl, S.CONTENT_MAX, "超宽窗口里说明文字没封顶")
        self.assertGreater(wl, 600, "封得太窄了，宽窗口里没必要")
        self.assertEqual(self.win._content_width(1600), self.win._content_width(4000))

    def test_cards_are_centered_on_wide_windows(self):
        """内容按最大宽度居中（左右留白），不然右边一大片空、字全挤在左边。"""
        self.win.update()
        fake = type("E", (), {"width": 3000})()
        self.win._on_canvas_configure(fake)
        x, _y = self.win._canvas.coords(self.win._inner)
        self.assertGreater(x, 100, "超宽窗口里内容没居中")

    def test_tiny_width_is_clamped(self):
        """极端窄也不能算出 0/负数折行宽度（Tk 会报错）。"""
        self.win._relayout(10)
        self.assertGreaterEqual(min(l.cget("wraplength") for l in self.win._wrap_lbls), 160)


if __name__ == "__main__":
    unittest.main(verbosity=2)
