# -*- coding: utf-8 -*-
"""卡片右下角那张「装饰图」（立绘）——取图优先级、导入保留透明、以及窗口那层的接线。

这张图和「总览图」不是一回事：
  * 总览图 = App 总览卡顶上那张横幅，导入时压白底（RGB）；
  * 装饰图 = **每张弹出的释义卡片右下角**贴的立绘，导入时**必须保留 alpha**（丢透明就变成一块方块）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from et_desktop import settings_ui as S  # noqa: E402
from et_desktop import ui as U  # noqa: E402


def _png(path, size=(60, 80), color=(30, 50, 100, 255), mode="RGBA"):
    Image.new(mode, size, color).save(path)
    return path


def _rgba_with_hole(path, size=(60, 80)):
    """左半边不透明、右半边全透明——用来证明导入没有把透明抹掉。"""
    im = Image.new("RGBA", size, (30, 50, 100, 0))
    for x in range(size[0] // 2):
        for y in range(size[1]):
            im.putpixel((x, y), (30, 50, 100, 255))
    im.save(path)
    return path


class DecorSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="et-decor-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.imp = os.path.join(self.tmp, "decor-image.png")
        self.dft = os.path.join(self.tmp, "mascot.png")
        _png(self.dft)

    def test_default_when_nothing_imported(self):
        self.assertEqual(U.decor_source(imported=self.imp, default=self.dft), self.dft)

    def test_imported_wins(self):
        _png(self.imp)
        self.assertEqual(U.decor_source(imported=self.imp, default=self.dft), self.imp)

    def test_missing_imported_falls_back_to_default(self):
        """导入的那份被删掉（比如「恢复默认」或清理工具）→ 自动回默认立绘。"""
        self.assertEqual(U.decor_source(imported=self.imp, default=self.dft), self.dft)

    def test_default_missing_returns_default_path_not_none(self):
        """两个都没有也别返回 None——调用方按路径兜错，返 None 会在别处炸。"""
        self.assertEqual(U.decor_source(imported=self.imp, default=self.imp), self.imp)

    def test_load_decor_is_rgba(self):
        self.assertEqual(U.load_decor(self.dft).mode, "RGBA")


class DecorImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="et-decor-imp-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dest = os.path.join(self.tmp, "decor-image.png")

    def test_import_keeps_alpha(self):
        """关键区别：装饰图**不压白底**，透明得留着。"""
        src = _rgba_with_hole(os.path.join(self.tmp, "hole.png"))
        ok, msg = U.import_decor_image(src, dest=self.dest)
        self.assertTrue(ok, msg)
        self.assertEqual(Image.open(self.dest).convert("RGBA").getextrema()[3][0], 0)
        self.assertIn("透明", msg)

    def test_import_flattens_opaque_photo_without_claiming_transparency(self):
        src = _png(os.path.join(self.tmp, "photo.jpg"), size=(60, 80),
                   color=(200, 120, 90), mode="RGB")          # 真·不透明照片（JPEG 那种）
        ok, msg = U.import_decor_image(src, dest=self.dest)
        self.assertTrue(ok)
        self.assertNotIn("带透明背景", msg)      # 不能反过来暗示它带透明

    def test_import_copies_not_links(self):
        src = _png(os.path.join(self.tmp, "src.png"))
        ok, _ = U.import_decor_image(src, dest=self.dest)
        self.assertTrue(ok)
        os.remove(src)                                    # 原图挪走
        self.assertTrue(os.path.exists(self.dest))        # 副本还在

    def test_import_downscales_over_wide(self):
        src = _png(os.path.join(self.tmp, "wide.png"), size=(1000, 500))
        ok, _ = U.import_decor_image(src, dest=self.dest, max_w=800)
        self.assertTrue(ok)
        self.assertEqual(Image.open(self.dest).size, (800, 400))   # 等比，不拉伸

    def test_import_reports_failure_instead_of_raising(self):
        ok, msg = U.import_decor_image(os.path.join(self.tmp, "nope.png"), dest=self.dest)
        self.assertFalse(ok)
        self.assertIn("无法应用", msg)


class DecorRenderedOnCardTest(unittest.TestCase):
    def test_decor_lands_in_bottom_right_of_card(self):
        """把一张纯绿立绘渲染进卡片：绿色只该出现在**右下角**，左半边不该有。"""
        tmp = tempfile.mkdtemp(prefix="et-decor-render-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        decor = Image.new("RGBA", (40, 40), (0, 255, 0, 255))
        sample = {"word": "serendipity",
                  "phonetics": {"uk": "/ˌserənˈdɪpəti/", "us": "/ˌserənˈdɪpəti/"},
                  "poses": [{"pos": "n.", "meaning": "意外发现珍奇事物的运气"}],
                  "examples": [{"en": "The word was coined in 1854.", "zh": "这个词是 1854 年造的。"}]}
        img = U.render_card(sample, decor, scale=1.0)
        self.assertIsNotNone(img)
        rgb = img.convert("RGB")
        w, h = rgb.size
        px = rgb.load()
        greens_left = sum(1 for x in range(0, w // 2) for y in range(h)
                          if px[x, y] == (0, 255, 0))
        greens_right = sum(1 for x in range(w // 2, w) for y in range(h)
                           if px[x, y] == (0, 255, 0))
        self.assertGreater(greens_right, 0, "装饰图没画进卡片")
        self.assertEqual(greens_left, 0, "装饰图跑到左半边去了")


class DecorColoredPresetTest(unittest.TestCase):
    """一键切「README 里的彩色立绘」：那张是两姿势拼版，必须切成单张。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="et-decor-sheet-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dest = os.path.join(self.tmp, "decor-image.png")

    def test_two_up_sheet_is_split_into_single_sprite(self):
        sheet = os.path.join(self.tmp, "sheet.png")
        Image.new("RGBA", (852, 452), (90, 120, 200, 255)).save(sheet)
        ok, msg = U.import_decor_colored(sheet=sheet, dest=self.dest)
        self.assertTrue(ok, msg)
        self.assertEqual(Image.open(self.dest).size, (426, 452))   # 只留左半，不是整张
        self.assertIn("鲸鱼娘", msg)

    def test_single_sprite_is_kept_whole(self):
        """本来就是单张（接近正方形）就别切。"""
        sheet = os.path.join(self.tmp, "single.png")
        Image.new("RGBA", (452, 452), (90, 120, 200, 255)).save(sheet)
        ok, _ = U.import_decor_colored(sheet=sheet, dest=self.dest)
        self.assertTrue(ok)
        self.assertEqual(Image.open(self.dest).size, (452, 452))

    def test_missing_sheet_reports_failure_instead_of_raising(self):
        ok, msg = U.import_decor_colored(sheet=os.path.join(self.tmp, "nope.png"), dest=self.dest)
        self.assertFalse(ok)
        self.assertIn("生成不了", msg)

    def test_cut_flat_background_keeps_white_parts(self):
        """抠灰底只吃「与四边连通」的灰：角色身上的白必须留着（不然头饰袜子会被掏空）。"""
        im = Image.new("RGBA", (60, 60), (226, 230, 238, 255))
        for x in range(20, 40):
            for y in range(20, 40):
                im.putpixel((x, y), (30, 50, 100, 255))       # 深色"身体"
        for x in range(24, 36):
            for y in range(24, 36):
                im.putpixel((x, y), (255, 255, 255, 255))     # 身体里的"白"
        out = U._cut_flat_background(im)
        self.assertEqual(out.getpixel((0, 0))[3], 0)          # 外围灰底 → 透明
        self.assertEqual(out.getpixel((58, 58))[3], 0)
        self.assertEqual(out.getpixel((30, 30)), (255, 255, 255, 255))   # 白还在
        self.assertEqual(out.getpixel((22, 22))[3], 255)      # 深色轮廓还在

    def test_colored_preset_message_mentions_cut(self):
        sheet = os.path.join(self.tmp, "sheet.png")
        Image.new("RGBA", (852, 452), (226, 230, 238, 255)).save(sheet)
        ok, msg = U.import_decor_colored(sheet=sheet, dest=self.dest)
        self.assertTrue(ok, msg)
        self.assertIn("抠底", msg)

    def test_load_decor_returns_none_instead_of_raising(self):
        """「下载下来就能用」：那张默认图万一没跟下来，读图必须返回 None 而不是抛异常。"""
        orig_i, orig_d = U.DECOR_IMPORTED, U.DECOR_DEFAULT
        U.DECOR_IMPORTED = os.path.join(self.tmp, "nope.png")
        U.DECOR_DEFAULT = os.path.join(self.tmp, "nope2.png")
        try:
            self.assertIsNone(U.load_decor(), "两张都不在时必须返回 None")
            self.assertIsNone(U.load_decor(os.path.join(self.tmp, "nope3.png")))
        finally:
            U.DECOR_IMPORTED, U.DECOR_DEFAULT = orig_i, orig_d

    def test_load_decor_falls_back_to_default_when_explicit_path_bad(self):
        """显式给的图读不了 → 退回默认那张（而不是干脆没装饰）。"""
        orig_i, orig_d = U.DECOR_IMPORTED, U.DECOR_DEFAULT
        U.DECOR_IMPORTED = os.path.join(self.tmp, "nope.png")
        U.DECOR_DEFAULT = _png(os.path.join(self.tmp, "mascot.png"))
        try:
            im = U.load_decor(os.path.join(self.tmp, "nope4.png"))
            self.assertIsNotNone(im)
            self.assertEqual("RGBA", im.mode)
        finally:
            U.DECOR_IMPORTED, U.DECOR_DEFAULT = orig_i, orig_d

    def test_card_renders_without_decoration(self):
        """装饰图缺失时卡片照画（右下角空着），不能因为没图就不出卡片。"""
        sample = {"word": "serendipity",
                  "phonetics": {"uk": "/ˌserənˈdɪpəti/", "us": "/ˌserənˈdɪpəti/"},
                  "poses": [{"pos": "n.", "meaning": "意外发现珍奇事物的运气"}],
                  "examples": [{"en": "The word was coined in 1854.", "zh": "这个词是 1854 年造的。"}]}
        img = U.render_card(sample, None, scale=1.0)
        self.assertIsNotNone(img)
        self.assertGreater(img.width, 100)
        # 气泡下方那条本来是给她站的预留带：没装饰时应该只有色键（窗外全透明）
        self.assertEqual((255, 0, 255), img.convert("RGB").getpixel((img.width - 30, img.height - 5)))

    def test_repo_sheet_exists_and_is_two_up(self):
        """仓库里那张真在、真是拼版——否则按钮点了会白点。"""
        self.assertTrue(os.path.exists(U.DECOR_SHEET), U.DECOR_SHEET)
        im = Image.open(U.DECOR_SHEET)
        self.assertGreater(im.width, im.height * 1.5)


class DefaultDecorAssetTest(unittest.TestCase):
    """默认装饰 = **鲸鱼娘**（assets/decor.png）。这条防退化，别让默认又变回黑白那张。"""

    def test_default_asset_is_colored_and_cut(self):
        self.assertTrue(os.path.exists(U.DECOR_DEFAULT), U.DECOR_DEFAULT)
        self.assertEqual(U.DECOR_DEFAULT, U.decor_source(), "默认装饰不是 assets/decor.png")
        im = U.load_decor()
        small = im.convert("RGB").resize((40, 40))
        raw = small.tobytes()                     # RGB 三连字节，避开 Pillow 的弃用告警
        sat = sum(max(raw[i:i + 3]) - min(raw[i:i + 3]) for i in range(0, len(raw), 3)) / (len(raw) // 3)
        self.assertGreater(sat, 20, "默认装饰不是彩色（像素平均彩度 %.1f）" % sat)
        self.assertEqual(0, im.getextrema()[3][0], "默认装饰没抠底（没有全透明像素）")

    def test_make_decor_tool_reproduces_the_asset(self):
        """默认装饰必须能由 tools/make_decor.py 复现（换机器/换仓库不至于拿不到那张图）。"""
        tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tools", "make_decor.py")
        self.assertTrue(os.path.exists(tools), tools)
        self.assertTrue(os.path.exists(U.DECOR_SHEET), U.DECOR_SHEET)


class DecorWindowTest(unittest.TestCase):
    """窗口那层：文本框应用 → 通知后台 → 预览/来源跟着变；恢复默认回得去。"""

    def setUp(self):
        import tkinter as tk
        self.tmp = tempfile.mkdtemp(prefix="et-decor-win-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._orig = (U.DECOR_IMPORTED, U.DECOR_DEFAULT)
        U.DECOR_IMPORTED = os.path.join(self.tmp, "decor-image.png")
        U.DECOR_DEFAULT = _png(os.path.join(self.tmp, "mascot.png"))
        self.root = tk.Tk()
        self.root.withdraw()
        self.calls = []
        cfg = {"enabled": True, "dwellMs": 2000, "examplesCount": 3, "showSpeak": True,
               "engine": "auto",
               "model": {"enabled": True, "baseUrl": "http://127.0.0.1:11434/v1",
                         "textModel": "m", "visionModel": "m"}}
        self.win = S.SettingsWindow(self.root, cfg, lambda *a: None,
                                    mascot=Image.open(U.DECOR_DEFAULT).convert("RGBA"),
                                    on_decor=lambda: self.calls.append(1))

    def tearDown(self):
        U.DECOR_IMPORTED, U.DECOR_DEFAULT = self._orig
        try:
            self.win.destroy()
            self.root.destroy()
        except Exception:
            pass

    def test_apply_from_textbox_copies_and_notifies(self):
        src = _png(os.path.join(self.tmp, "mine.png"))
        self.win._decor_var.set('"%s"' % src)              # 带引号（资源管理器复制来的）
        self.win._apply_decor_path()
        self.assertTrue(os.path.exists(U.DECOR_IMPORTED))
        self.assertEqual(self.win._decor_var.get(), U.DECOR_IMPORTED)   # 文本框跟到副本
        self.assertEqual(self.calls, [1], "没通知后台换图，卡片不会更新")

    def test_apply_same_file_twice_is_noop(self):
        src = _png(os.path.join(self.tmp, "mine.png"))
        self.win._decor_var.set(src)
        self.win._apply_decor_path()
        self.win._apply_decor_path()                       # 第二次：就是现在用的这张
        self.assertEqual(self.calls, [1], "重复应用不该反复清缓存")
        self.assertIn("当前已是该图片", self.win._decor_msg_lbl.cget("text"))

    def test_apply_bad_path_reports_and_keeps_default(self):
        self.win._decor_var.set(os.path.join(self.tmp, "nope.png"))
        self.win._apply_decor_path()
        self.assertFalse(os.path.exists(U.DECOR_IMPORTED))
        self.assertEqual(self.calls, [])
        self.assertIn("无法应用", self.win._decor_msg_lbl.cget("text"))
        self.assertEqual(U.decor_source(), U.DECOR_DEFAULT)

    def test_reset_returns_to_default_and_notifies(self):
        src = _png(os.path.join(self.tmp, "mine.png"))
        self.win._decor_var.set(src)
        self.win._apply_decor_path()
        self.win._reset_decor()
        self.assertFalse(os.path.exists(U.DECOR_IMPORTED))
        self.assertEqual(U.decor_source(), U.DECOR_DEFAULT)
        self.assertEqual(self.calls, [1, 1])

    def test_preview_is_drawn_on_card_mock(self):
        """预览得有东西（不是一张空白/异常图）。"""
        img = self.win._decor_preview_image()
        self.assertEqual(img.size, (320, 180))
        self.assertGreater(len(set(img.convert("RGB").tobytes())), 3)

    def test_nav_has_decor_entry(self):
        self.assertIn("decor", self.win._nav)
        self.assertIn("装饰图", self.win._nav["decor"].cget("text"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
