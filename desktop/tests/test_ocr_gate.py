# -*- coding: utf-8 -*-
"""OCR 取词闸门单测：普通单词/数学符号才收，单个普通英文字母一律不收（纯函数，无网络无 GUI）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from et_desktop import lookup as L          # noqa: E402
from et_desktop import textgrab as TG       # noqa: E402


class OcrEntryCase(unittest.TestCase):
    """2026-10-05 回归点：word_at_point 走 OCR 兜底时必须传**根配置**。

    旧 bug：调用处把 model 子树当整份配置传 → 闸门里的 cfg.get("imageOcr") 永远读不到
    → 「图片取词」开关关了也照截图、照加载视觉模型。这里从 word_at_point 入口进，
    专门锁住这个传参错误。
    """

    def setUp(self):
        self._uia = TG.word_at_point_uia
        self._grab = TG._grab_png

    def tearDown(self):
        TG.word_at_point_uia, TG._grab_png = self._uia, self._grab

    def test_switch_off_blocks_ocr_from_entry(self):
        called = {"grab": 0}
        TG.word_at_point_uia = lambda x, y: (None, False)      # UIA 没字 → 落 OCR 兜底
        def _grab(*a, **k):
            called["grab"] += 1
            return None
        TG._grab_png = _grab
        cfg = {"imageOcr": {"enabled": False},
               "model": {"baseUrl": "http://127.0.0.1:9", "visionModel": "whatever"}}
        word, src = TG.word_at_point(5, 5, cfg)     # 返回 (词, 来源) 元组
        self.assertIsNone(word)
        self.assertEqual(0, called["grab"], "开关关了还去截图 —— 传参又错了（应传根配置）")


class TestAcceptWord(unittest.TestCase):
    def test_real_words_accepted(self):
        for w in ["Subnormal", "Fraction", "Exponent", "Bias", "IEEE", "hello", "normal",
                  "abc", "don't", "e-mail", "COVID"]:
            self.assertTrue(L.accept_ocr_word(w), w)

    def test_single_latin_letter_rejected(self):
        """用户要求：普通英文字母不要识别出来（整词被裁成一个字母的碎片会冒充它）。"""
        for w in ["a", "F", "n", "X", "x", "Q", "P", "Z"]:
            self.assertFalse(L.accept_ocr_word(w), w)

    def test_math_symbols_kept(self):
        """希腊字母 / 花体·双线体是读论文要用的，保留。"""
        for w in ["α", "Ω", "λ", "β", "ℱ", "ℒ", "𝒩", "ℝ", "𝔼", "𝔤"]:
            self.assertTrue(L.accept_ocr_word(w), w)

    def test_junk_rejected(self):
        for w in ["", "   ", "3", "42", "+", "=", "×", "中文", "概", None, 7, ["a"]]:
            self.assertFalse(L.accept_ocr_word(w), repr(w))

    def test_null_like_strings_rejected(self):
        """模型把「没有」写成字符串 null/None 时不能当成单词。"""
        for w in ["null", "NULL", "None", "none", "nan", "无", "没有"]:
            self.assertFalse(L.accept_ocr_word(w), w)

    def test_backtick_and_space_tolerated(self):
        self.assertTrue(L.accept_ocr_word("  Fraction  "))
        self.assertTrue(L.accept_ocr_word("Subnormal."))     # 末尾标点由 is_english_word 规则处理


if __name__ == "__main__":
    unittest.main()
