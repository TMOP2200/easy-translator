# -*- coding: utf-8 -*-
"""界面文案的规范：**人话**——不出现 markdown 星号/反引号，不出现默认图的路径。

为什么要钉住（都是用户真提过的）：
  · 「**使用人类语言的排版方式**」：Tk 的 Label 不解析 markdown，`**总览图**` 会**原样显示星号**，
    看起来像机器写的；反引号同理。
  · 「**不要出现默认图片的地址**」：用自带默认图时，界面上不该冒出带盘符的绝对路径。
  · 名字：她叫**鲸鱼娘**（用户纠正过，之前误写成「金鱼娘」）。

跑：python tests/test_copy_style.py      （unittest，不需要 pytest）
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from et_desktop import settings_ui as S                 # noqa: E402

SRC = os.path.join(ROOT, "desktop", "et_desktop", "settings_ui.py")
CARD_SRC = os.path.join(ROOT, "desktop", "et_desktop", "ui.py")


def _visible_texts(widget, out=None):
    """把窗口里所有「用户看得见的文字」抓出来（Label / Button / Checkbutton）。"""
    out = [] if out is None else out
    for ch in widget.winfo_children():
        try:
            cls = ch.winfo_class()
            if cls in ("Label", "Button", "Checkbutton", "Radiobutton"):
                t = ch.cget("text")
                if t:
                    out.append((cls, t))
        except Exception:
            pass
        _visible_texts(ch, out)
    return out


class CopyStyleCase(unittest.TestCase):
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
        self.texts = _visible_texts(self.win)

    def tearDown(self):
        try:
            self.win.destroy()
            self.root.destroy()
        except Exception:
            pass

    def test_no_markdown_marks_in_visible_text(self):
        """`**` 和反引号在 Tk 里是**字面显示**的，一律不许出现在界面上。"""
        bad = [(c, t) for c, t in self.texts if "**" in t or "`" in t]
        self.assertEqual([], bad, "界面上出现了 markdown 记号：%s" % bad[:3])

    def test_no_image_paths_in_visible_text(self):
        """不要出现图片路径（尤其是默认那张的）—— 用户要的是「不要出现默认图片的地址」。"""
        sig = (".png", ".ico", ".jpg", "assets/", "docs/", "\\assets", "\\docs")
        bad = [(c, t) for c, t in self.texts if any(s in t for s in sig)]
        self.assertEqual([], bad, "界面上出现了图片路径：%s" % bad[:3])

    def test_no_hard_wrapped_sentences(self):
        """长句子靠自动折行，别在句子中间硬敲 \\n（「人类语言的排版方式」）。"""
        bad = [(c, t) for c, t in self.texts
               if "\n" in t and not re.search(r"[。！？；]\s*\n", t)]
        self.assertEqual([], bad, "这些文字在句子中间硬换行了：%s" % bad[:3])

    def test_name_is_whale_girl(self):
        """界面上叫她鲸鱼娘；没有写成金鱼娘。"""
        joined = " ".join(t for _c, t in self.texts)
        self.assertIn("鲸鱼娘", joined, "界面上没叫她鲸鱼娘")
        self.assertNotIn("金鱼娘", joined, "写成了金鱼娘")

    def test_copy_is_not_addressing_the_reader_all_the_time(self):
        """「用人话」不等于满篇「你」：整页说明书里「你」最多出现 1 次。

        用户原话：「用人话也不是一直写「你」啊」—— 说人话 ≠ 一直指着读者讲话。
        """
        hits = S.HELP_TEXT.count("你")
        self.assertLessEqual(hits, 1, "使用说明里「你」出现了 %d 次，读起来像在训人" % hits)

    def test_copy_stays_professional(self):
        """面向的是**非开发用户**：专业、平实 —— 不用口语腔，也不教用户「把文件发出去」。

        用户原话：「专业一点，不要太口语化，你在面对非开发用户而不是开发者，
        所以你不要说什么发送之类的」。
        """
        black = ("别动", "不对劲", "就行", "多半", "那点事", "发送", "发出来", "手打")
        bad = [(c, t[:30]) for c, t in self.texts if any(b in t for b in black)]
        self.assertEqual([], bad, "这些文案太口语／在教用户发文件：%s" % bad[:3])
        bad_help = [b for b in black if b in S.HELP_TEXT]
        self.assertEqual([], bad_help, "说明书里有口语词：%s" % bad_help)

    def test_no_colloquial_particles_in_visible_text(self):
        """行文按公文/专业文风：不用「一下 / 两下 / 一遍 / 就行」这类口语助词（用户点名「一下」）。

        注意：「以下」里也含「一下」二字，用负向断言排除。
        """
        pat = re.compile(r"(?<!以)一下|两下|一遍|就行|就好|得了|回事")
        bad = [(c, t[:30]) for c, t in self.texts if pat.search(t)]
        self.assertEqual([], bad, "这些文案还有口语助词：%s" % bad[:3])
        self.assertIsNone(pat.search(S.HELP_TEXT), "说明书里有口语助词")

    def test_copy_has_nothing_machine_specific(self):
        """面向下载用户：窗口里的文字不能出现本机/仓库特有的东西，也不能把 exe 文件名写死。

        用户原话：「你写的东西是面向其他用户的，不能出现本机特有的信息或者与用户不一致的信息，
        你封装后的文件可以重命名」—— 所以文件名也不能钉进文案（用户随时会改名）。
        """
        bad_tokens = ("E:\\", "easy-translator", ".venv", "desktop\\", "C:\\Users",
                      "EasyTranslator.exe", "assets/", "docs/")
        # 本机用户名从环境里读（不把用户名写进源码；换台电脑就测那台的用户名）
        _user = os.environ.get("USERNAME") or ""
        if len(_user) >= 3:
            bad_tokens += (_user,)
        bad = [(c, t[:40]) for c, t in self.texts for tok in bad_tokens if tok in t]
        self.assertEqual([], bad, "这些文案里有本机/仓库特有的东西：%s" % bad[:3])

    def test_source_files_have_no_wrong_name(self):
        for p in (SRC, CARD_SRC):
            with open(p, encoding="utf-8") as f:
                self.assertNotIn("金鱼娘", f.read(), "%s 里写成了金鱼娘" % os.path.basename(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
