# -*- coding: utf-8 -*-
"""总览图（横幅）的判据：**固定用 README 头图、不支持导入**、点图能打开、等比裁切不变形。

为什么这几条值得钉住：
  · 用户明确要求「**总览图不支持导入**」——留着一个导入入口就是错的（功能会在别人手里复活）；
  · 横幅必须**等比覆盖 + 居中裁切**：直接拉伸会把人脸拉扁（用户对穿模/比例很敏感）；
  · 宽度要跟着窗口走（小窗口/大窗口都得合适），所以 banner_image 必须收尺寸参数。

跑：python tests/test_overview_banner.py      （unittest，不需要 pytest）
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from PIL import Image                                    # noqa: E402

from et_desktop import settings_ui as S                  # noqa: E402


class OverviewBannerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="et-banner-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)  # 跑完自己收拾，别在 %TEMP% 积几百个

    def _png(self, name, size, color=(200, 30, 30)):
        p = os.path.join(self.tmp, name)
        Image.new("RGB", size, color).save(p)
        return p

    # ————————————————— 取图：只有 README 头图这一张 —————————————————
    def test_source_is_readme_head_image(self):
        """总览图就是 README 头图那一张（且它必须真的存在，不然横幅会空）。"""
        self.assertTrue(os.path.exists(S.README_SHOT),
                        "找不到 README 头图：%s" % S.README_SHOT)
        self.assertEqual(S.README_SHOT, S.overview_source())

    def test_missing_readme_returns_empty_not_none(self):
        """找不到那张图时返回 ""（调用方按假值兜错），别返回 None 让别处炸。"""
        self.assertEqual("", S.overview_source(os.path.join(self.tmp, "nope.png")))

    def test_import_api_is_gone(self):
        """「总览图不支持导入」是硬要求：导入入口、导入函数、配置目录那份副本都得消失。"""
        self.assertFalse(hasattr(S, "import_overview_image"), "导入函数还留着")
        self.assertFalse(hasattr(S, "OVERVIEW_IMG"), "配置目录里的总览图副本概念还留着")
        self.assertFalse(hasattr(S, "OVERVIEW_DIR"), "配置目录常量还留着")

    # ————————————————— 横幅：尺寸、裁切、透明底 —————————————————
    def test_banner_is_exact_size_and_not_stretched(self):
        """宽图/高图都要出**要求的**尺寸，且是裁切而不是拉伸（长宽比不变形）。"""
        wide = self._png("wide.png", (1250, 300))         # 很扁
        tall = self._png("tall.png", (300, 1250))         # 很高
        for p in (wide, tall):
            img = S.banner_image(p)
            self.assertEqual((S.BANNER_W, S.BANNER_H), img.size)
            self.assertNotEqual(img.size[0] / img.size[1],
                                Image.open(p).size[0] / Image.open(p).size[1])

    def test_banner_takes_arbitrary_size(self):
        """窗口窄了要给得出小横幅（否则小窗口右边被截掉）。"""
        p = self._png("src.png", (1250, 765))
        img = S.banner_image(p, w=400, h=171)
        self.assertEqual((400, 171), img.size)
        self.assertEqual((400, 171), S.banner_image(p, w=400, h=171).size)

    def test_banner_handles_alpha_and_small_images(self):
        """透明底要压白（不然会出现黑边）；比横幅还小的图也要放大到标准尺寸。"""
        p = os.path.join(self.tmp, "alpha.png")
        Image.new("RGBA", (80, 60), (0, 0, 0, 0)).save(p)
        img = S.banner_image(p)
        self.assertEqual((S.BANNER_W, S.BANNER_H), img.size)
        self.assertEqual((255, 255, 255), img.getpixel((5, 5)), "透明区没压成白底")

    def test_banner_bad_input_returns_none(self):
        self.assertIsNone(S.banner_image(os.path.join(self.tmp, "nope.png")))
        bad = os.path.join(self.tmp, "not-an-image.png")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("这不是图片")
        self.assertIsNone(S.banner_image(bad))

    # ————————————————— 窗口那层：没有导入入口、点图能打开 —————————————————
    def _make_window(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("无 tkinter")
        try:
            root = tk.Tk()
        except Exception as e:
            self.skipTest("无法创建 Tk：%s" % e)
        root.withdraw()
        root.report_callback_exception = lambda *a: None
        from et_desktop import ui
        cfg = {"enabled": True, "dwellMs": 2000, "examplesCount": 3, "showSpeak": True,
               "engine": "auto",
               "model": {"enabled": True, "baseUrl": "http://127.0.0.1:11434/v1", "apiKey": "",
                         "textModel": "qwen2.5vl:3b", "visionModel": "qwen2.5vl:3b",
                         "timeoutMs": 60000},
               "imageOcr": {"enabled": True, "dwellMs": 1500, "cropW": 460, "cropH": 140,
                            "hint": True}}
        mascot = ui.load_decor()
        win = S.SettingsWindow(root, cfg, lambda *a: None, mascot=mascot,
                               test_text=lambda: (True, "ok"))
        win.update()
        return root, win

    def test_window_has_no_import_widgets(self):
        """窗口里不该有总览图的路径框/浏览/应用/恢复默认 —— 连属性都不该在。"""
        root, win = self._make_window()
        try:
            self.assertFalse(hasattr(win, "_banner_var"), "总览图的路径文本框还在")
            for name in ("_pick_overview", "_apply_overview_path", "_reset_overview"):
                self.assertFalse(hasattr(win, name), "%s 还在" % name)
        finally:
            win.destroy()
            root.destroy()

    def test_overview_card_is_just_the_image(self):
        """用户要求「总览图就是总览图」：卡片里只留「总览图」这个标签 + 「打开原图」按钮，
        不写「这是什么 / 从哪来的 / 不能换」这类说明文字。
        """
        root, win = self._make_window()
        try:
            blobs = []

            def walk(w):
                for ch in w.winfo_children():
                    try:
                        if ch.winfo_class() in ("Label", "Button"):
                            blobs.append(ch.cget("text"))
                    except Exception:
                        pass
                    walk(ch)
            walk(win)
            txt = " ".join(blobs)
            self.assertIn("总览图", txt, "连「总览图」这个标签都没了")
            self.assertIn("打开原图", txt)
            for phrase in ("不支持导入", "说明文档", "不能换成别的图", "这里放的是", "README"):
                self.assertNotIn(phrase, txt, "总览卡里还留着多余说明：%s" % phrase)
            # 也不该有「总览图不该出现的长句」：超过 24 字的说明都不是标签而是解释
            long_notes = [t for t in blobs if len(t) > 24 and "总览" in t]
            self.assertEqual([], long_notes, "总览图旁边还有解释文字：%s" % long_notes)
        finally:
            win.destroy()
            root.destroy()

    def test_open_uses_system_viewer_on_readme_image(self):
        """点图/「打开原图」= 用系统默认程序打开那张 README 头图。"""
        root, win = self._make_window()
        opened = []
        S.os.startfile = lambda p: opened.append(p)     # 临时替换，禁止真弹看图程序
        try:
            win._open_overview()
            self.assertEqual([S.overview_source()], opened)
            self.assertIn("已用系统默认看图程序打开", win._banner_src_lbl.cget("text"))
        finally:
            import os as _os
            S.os.startfile = _os.startfile
            win.destroy()
            root.destroy()

    def test_banner_is_clickable(self):
        """点图片本身要能打开原图（绑了 <Button-1>），别只剩「打开原图」按钮。"""
        root, win = self._make_window()
        try:
            self.assertTrue(win._banner_lbl.bind("<Button-1>"), "图片没绑点击")
            self.assertEqual("hand2", str(win._banner_lbl.cget("cursor")))
        finally:
            win.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
