# -*- coding: utf-8 -*-
"""打游戏自动暂停（gamewatch）的判据 —— 纯函数层，喂合成数据即可。

用户要求：不依赖本机那个外部看门狗，打包出去的 exe 自己也该会暂停。
这里钉住四条边界（每一条都对应一种真实误判）：

  · 全屏前台 + 显卡忙 = 游戏 → 停工；
  · 全屏但显卡不忙（全屏看视频 / 投屏）→ 不停（用户可能还想取词）；
  · 不全屏但显卡很忙（自家视觉模型 / 后台计算）→ 不停（最容易被误判的一种）；
  · 本程序自己的窗口、资源管理器铺满屏 → 不算游戏。

再加两条行为：退出要连续两次「不像游戏」才恢复（防菜单/加载来回抖）；
「通用」里的开关关掉后，永远不停工。

跑：python tests/test_gamewatch.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from et_desktop import gamewatch as G          # noqa: E402


class DecideCase(unittest.TestCase):
    def test_fullscreen_with_busy_gpu_is_gaming(self):
        self.assertTrue(G.decide(1.0, "spore.exe", False, 80))

    def test_fullscreen_video_is_not_gaming(self):
        self.assertFalse(G.decide(1.0, "vlc.exe", False, 8))

    def test_busy_gpu_in_background_is_not_gaming(self):
        # 自家视觉模型把显卡跑满，但它不是全屏前台 —— 不能因此停掉取词
        self.assertFalse(G.decide(0.4, "python.exe", False, 95))

    def test_own_window_fullscreen_is_not_gaming(self):
        self.assertFalse(G.decide(1.0, "pythonw.exe", True, 90))

    def test_shell_fullscreen_is_ignored(self):
        self.assertFalse(G.decide(1.0, "explorer.exe", False, 90))

    def test_without_gpu_probe_does_not_pause(self):
        # 两种查显卡都量不到（极老系统）：不判游戏、不暂停。
        # 2026-10-05 改：以前是「全屏就算」，但那样 A 卡/核显机器全屏看视频/PPT 放映
        # 会被误停取词 —— 现在的原则是「没数据不误停」。
        self.assertFalse(G.decide(1.0, "game.exe", False, None))
        self.assertFalse(G.decide(0.5, "game.exe", False, None))

    def test_gpu_value_from_pdh_still_gates(self):
        # PDH（所有厂商）读到的 3D 利用率照常按阈值判
        self.assertTrue(G.decide(1.0, "game.exe", False, 55))
        self.assertFalse(G.decide(1.0, "game.exe", False, 12))

    def test_threshold_boundary(self):
        self.assertTrue(G.decide(1.0, "g.exe", False, G.GPU_MIN))
        self.assertFalse(G.decide(1.0, "g.exe", False, G.GPU_MIN - 1))

    def test_coverage_boundary(self):
        self.assertTrue(G.decide(G.FULL_MIN, "g.exe", False, 99))
        self.assertFalse(G.decide(G.FULL_MIN - 0.01, "g.exe", False, 99))

    def test_maximized_window_with_caption_is_not_fullscreen(self):
        # 最大化（有标题栏、差一点点没铺满，比如任务栏那一条）→ 不是全屏应用：
        # 否则「浏览器最大化 + 自家模型在跑」会被误判成游戏
        self.assertFalse(G.decide(0.98, "chrome.exe", False, 90, caption=True))
        self.assertTrue(G.decide(1.0, "chrome.exe", False, 90, caption=True))     # 真铺满才算
        self.assertTrue(G.decide(0.98, "game.exe", False, 90, caption=False))     # 无标题栏全屏


class HysteresisCase(unittest.TestCase):
    """进入立刻停工；退出要连续 RESUME_N 次采样都不像游戏。"""

    def setUp(self):
        self._orig = (G.foreground_info, G.gpu_util)
        G._state["gaming"] = False
        G._state["_calm"] = 0

    def tearDown(self):
        G.foreground_info, G.gpu_util = self._orig
        G._state["gaming"] = False
        G._state["_calm"] = 0

    def _fake(self, cover, exe, gpu, caption=True):
        G.foreground_info = lambda: (cover, exe, False, caption)
        G.gpu_util = lambda: gpu

    def test_enter_now_resume_after_two_calm_samples(self):
        self._fake(1.0, "game.exe", 90)
        self.assertTrue(G.sample())
        self._fake(0.3, "explorer.exe", 5)
        self.assertTrue(G.sample())      # 第 1 次冷静 → 还没恢复（防菜单/加载抖）
        self.assertFalse(G.sample())     # 第 2 次 → 恢复

    def test_reenter_resets_calm_counter(self):
        # T,F,T,F 这种抖动：中间攒的「冷静」必须被重新进入清零 ——
        # 否则最后一个 F 就凑满 RESUME_N 提前复工（正是要防的来回抖）。
        self._fake(1.0, "game.exe", 90)
        self.assertTrue(G.sample())                 # T
        self._fake(0.3, "explorer.exe", 5)
        self.assertTrue(G.sample())                 # F（第 1 次冷静，计数=1）
        self._fake(1.0, "game.exe", 90)
        self.assertTrue(G.sample())                 # T（计数应清零）
        self._fake(0.3, "explorer.exe", 5)
        self.assertTrue(G.sample())                 # F → 只该算第 1 次，仍停工
        self.assertFalse(G.sample())                # 再 F → 才恢复

    def test_config_switch_off_never_games(self):
        self._fake(1.0, "game.exe", 90)
        self.assertFalse(G.sample(lambda: False))
        self.assertFalse(G.is_gaming())

    def test_foreground_error_is_never_gaming(self):
        G.foreground_info = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertFalse(G.sample())


class InMemoryOnlyCase(unittest.TestCase):
    """2026-10-04 用户要求：改成「内存看门狗」——取词链只认进程内状态，不碰任何文件。"""

    def test_gaming_now_follows_the_in_memory_state(self):
        from et_desktop import textgrab as TG
        orig = G.is_gaming
        try:
            G.is_gaming = lambda: True
            self.assertTrue(TG.gaming_now())
            G.is_gaming = lambda: False
            self.assertFalse(TG.gaming_now())
        finally:
            G.is_gaming = orig

    def test_no_flag_file_paths_are_left(self):
        """旧机制必须彻底消失：textgrab 里不能再有 GAMING_FLAG* 这些路径。"""
        from et_desktop import textgrab as TG
        for name in ("GAMING_FLAG", "GAMING_FLAG_LOCAL", "GAMING_FLAG_EXE"):
            self.assertFalse(hasattr(TG, name), "还留着旧的标记文件路径：%s" % name)

    def test_gaming_now_never_raises_without_gamewatch(self):
        from et_desktop import textgrab as TG
        orig = G.is_gaming
        try:
            def boom():
                raise RuntimeError("boom")
            G.is_gaming = boom
            self.assertFalse(TG.gaming_now())      # 出岔子就当没在玩，绝不阻断取词
        finally:
            G.is_gaming = orig


if __name__ == "__main__":
    unittest.main(verbosity=1)
