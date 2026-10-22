# -*- coding: utf-8 -*-
"""桌面 App 的控制面：单实例 / 懒建窗口 / 关窗不退 / 总开关落地 / 配置热加载。

为什么要这组测试（都是踩过的形态）：
  · 双击 App 与开机自启的隐藏守护**各起一份监听** → 同一处弹两张卡片（单实例锁必须共用）；
  · 关窗把整个进程退掉 → 用户以为只是收起来，取词却没了；
  · 开关只改了界面没落盘 → 重启后又自己开回来；
  · 外部改 config.json 不生效 → `--settings` 窗口与脚本改设置全白费；
  · 覆盖写 config.json 撞上「读到一半的 JSON」→ load_cfg 退回默认值，设置整片丢。

跑：python tests/test_app_control.py      （unittest，不需要 pytest）
注意：全程把 CFG_PATH / CFG_DIR / SHOW_FLAG 指到临时目录，绝不碰用户真实的 config.json。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))


class ControlCase(unittest.TestCase):
    """每个用例一个临时配置目录 + 一棵 Tk 树。"""

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter  # noqa: F401
        except Exception:
            raise unittest.SkipTest("无 tkinter")

    def setUp(self):
        from et_desktop import app as A
        self.A = A
        self.tmp = tempfile.mkdtemp(prefix="et-ctl-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)  # 跑完自己收拾，别在 %TEMP% 积几千个
        self._saved = (A.CFG_PATH, A.CFG_DIR, A.SHOW_FLAG, A.DAEMON_MUTEX)
        A.CFG_DIR = self.tmp
        A.CFG_PATH = os.path.join(self.tmp, "config.json")
        A.SHOW_FLAG = os.path.join(self.tmp, "show.flag")
        # 互斥体名必须**每个用例都不同**：句柄是进程级的裸 int（不会随 GC 释放），
        # 用同一个名字的话，先跑的用例会把锁一直占着，后面的用例第一次 acquire 就拿到 None。
        # （计数器要放**类**上：setUp 每个用例都是新实例，放 self 上永远是 1。）
        ControlCase._n = getattr(ControlCase, "_n", 0) + 1
        A.DAEMON_MUTEX = "EasyTranslatorTestMutex-%d-%d" % (os.getpid(), ControlCase._n)
        self.cfg = A.load_cfg()                 # 临时目录里没有文件 → 全默认
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except Exception as e:
            self.skipTest("无法创建 Tk：%s" % e)
        # 销毁后仍排队的 Tk after 回调（如取消置顶）会往 stderr 喷 "invalid command name"
        self.root.report_callback_exception = lambda *a: None
        self.root.withdraw()

    def tearDown(self):
        A = self.A
        try:
            self.root.destroy()
        except Exception:
            pass
        A.CFG_PATH, A.CFG_DIR, A.SHOW_FLAG, A.DAEMON_MUTEX = self._saved

    def _app(self, headless=True):
        return self.A.App(self.cfg, self.root, lambda: None, headless=headless)

    # ————————————————————————————————————————————————
    def test_window_is_built_lazily_and_hidden_on_close(self):
        """--daemon 启动时不该有窗口；收到弹窗请求才建；关窗是收起来不是退出。"""
        app = self._app(headless=True)
        self.assertIsNone(app.win, "守护模式启动时不该建控制窗口")
        self.assertTrue(app.show_window(), "弹窗请求应能把窗口建出来")
        win = app.win
        self.assertIsNotNone(win)
        self.root.update()
        self.assertTrue(win.winfo_exists())
        app.hide_window()
        self.root.update()
        self.assertEqual("withdrawn", win.state(), "关窗应只是收起来（监听继续）")
        # 「×」必须绑成「收起来」而不是退出：把注册进去的那条命令直接调一次 = 点 ×
        self.assertTrue(app.show_window())
        self.root.update()
        cb = self.root.tk.call("wm", "protocol", win._w, "WM_DELETE_WINDOW")
        self.assertTrue(cb, "× 没绑任何处理（会走关闭窗口 = 退出进程的默认行为）")
        self.root.tk.call(cb)
        self.root.update()
        self.assertEqual("withdrawn", win.state(), "点 × 之后应只是收起来，进程还活着")
        self.assertTrue(win.winfo_exists(), "点 × 不该销毁窗口")
        self.assertTrue(app.show_window())
        self.root.update()
        self.assertEqual("normal", win.state(), "再双击 App 应能把窗口重新摆出来")

    def test_toggle_flips_config_and_lands_on_disk(self):
        """按一下大按钮：内存、文件、按钮字面、状态行四处必须同时变。"""
        app = self._app(headless=True)
        app.show_window()
        win = app.win
        self.root.update()
        self.assertTrue(self.cfg["enabled"], "初始应为开")
        self.assertIn("已开启", win.enable_btn.cget("text"))

        win.enable_btn.invoke()                 # 真的按下去（走 _toggle → _set → 落盘）
        self.root.update()
        self.assertFalse(self.cfg["enabled"], "点一下应变成关")
        self.assertIn("已关闭", win.enable_btn.cget("text"))
        self.assertEqual("已暂停", win.status_lbl.cget("text"))
        with open(self.A.CFG_PATH, encoding="utf-8") as f:
            self.assertFalse(json.load(f)["enabled"], "开关必须落到 config.json（否则重启又开回来）")

        win.enable_btn.invoke()
        self.root.update()
        self.assertTrue(self.cfg["enabled"])
        with open(self.A.CFG_PATH, encoding="utf-8") as f:
            self.assertTrue(json.load(f)["enabled"])

    def test_saved_config_is_valid_json_at_every_moment(self):
        """非原子写会留下「读到一半的 JSON」→ 别处热加载会退回默认值、设置整片丢。"""
        app = self._app(headless=True)
        app.show_window()
        for i in range(30):
            self.cfg["dwellMs"] = 1000 + i * 100
            app._change("dwellMs", self.cfg["dwellMs"])
            with open(self.A.CFG_PATH, encoding="utf-8") as f:
                json.load(f)                    # 抛异常即失败
        self.assertFalse(os.path.exists(self.A.CFG_PATH + ".tmp"), "临时文件应已被 replace 掉")

    def test_external_config_change_is_picked_up(self):
        """外面改了 config.json（--settings 窗口 / 手改 / 脚本）→ 就地生效并同步界面。"""
        app = self._app(headless=True)
        app.show_window()
        win = app.win
        app._reload_cfg_if_changed()            # 第一轮只记 mtime
        with open(self.A.CFG_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": False, "dwellMs": 3000}, f)
        os.utime(self.A.CFG_PATH, None)
        st = os.stat(self.A.CFG_PATH)
        os.utime(self.A.CFG_PATH, (st.st_atime + 5, st.st_mtime + 5))
        app._reload_cfg_if_changed()
        self.root.update()
        self.assertFalse(self.cfg["enabled"], "外部改动没被热加载")
        self.assertEqual(3000, self.cfg["dwellMs"])
        self.assertIn("已关闭", win.enable_btn.cget("text"), "界面没跟着同步")

    def test_half_written_config_is_ignored(self):
        """撞上写一半的 JSON：这轮跳过，绝不把内存里的设置清成默认值。"""
        app = self._app(headless=True)
        app.show_window()
        self.cfg["dwellMs"] = 7000
        app._reload_cfg_if_changed()
        with open(self.A.CFG_PATH, "w", encoding="utf-8") as f:
            f.write('{"enabled": tru')          # 故意残缺
        st = os.stat(self.A.CFG_PATH)
        os.utime(self.A.CFG_PATH, (st.st_atime + 5, st.st_mtime + 5))
        app._reload_cfg_if_changed()
        self.assertEqual(7000, self.cfg["dwellMs"], "读到坏文件就该原地不动")

    def test_show_request_is_one_shot(self):
        """弹窗请求：存在即命令、读到即删 —— 否则窗口每 600ms 被反复抬到最前。"""
        self.assertFalse(self.A.take_show_request())
        self.assertTrue(self.A.request_show())
        self.assertTrue(self.A.take_show_request())
        self.assertFalse(self.A.take_show_request())
        self.assertTrue(self.A.request_show())
        app = self._app(headless=True)
        app._app_tick()                         # 心跳里会取走请求并建窗
        self.assertIsNotNone(app.win, "心跳收到请求应把窗口建出来")
        self.assertFalse(os.path.exists(self.A.SHOW_FLAG))

    def test_single_instance_lock(self):
        """同一把锁：拿到的人留下，第二个人拿到 None（= 第二份监听起不来）。"""
        first = self.A.acquire_single_instance()
        self.assertIsNotNone(first, "第一个实例应拿到锁")
        second = self.A.acquire_single_instance()
        self.assertIsNone(second, "第二个实例必须拿不到（否则两份监听各弹各的卡片）")

    def test_show_flag_never_raises_on_bad_paths(self):
        """每 600ms 被调一次：坏路径/空值都不能抛。"""
        self.A.SHOW_FLAG = "\x00bad\x00path"
        self.assertIn(self.A.take_show_request(), (True, False))
        self.assertIn(self.A.request_show(), (True, False))

    def test_selftest_is_not_blocked_by_single_instance_lock(self):
        """有守护在跑时 --selftest 仍然必须能跑。

        自检不监听、不建窗口 —— 它就不该参与单实例锁。踩过一次：锁检查放在自检之前，
        结果「有守护在跑」时 `--selftest` 直接 return 0、一行输出都没有（看起来像自检静默通过）。
        """
        A = self.A
        holder = A.acquire_single_instance()      # 模拟「已经有一个实例在跑」
        self.assertIsNotNone(holder)
        called = []
        real_selftest = A.selftest
        A.selftest = lambda cfg: (called.append(True), 0)[1]
        try:
            code = A.main(["--selftest"])
        finally:
            A.selftest = real_selftest
        self.assertEqual([True], called, "--selftest 被单实例锁挡掉了（一行输出都没有）")
        self.assertEqual(0, code)


class SingleInstanceLockCase(unittest.TestCase):
    """单实例锁本身：同一把锁第二次必须拿不到。

    锁失效的后果是「双击 App + 开机自启的守护各起一份监听 → 同一处弹两张卡片、UIA 轮询翻倍」，
    所以这条把可观察的契约钉住（2026-10-03 补，同时把 Win32 调用的写法改成了官方那套）。
    注意：真机上看到「两个 pythonw」不是两个守护 —— venv 的 pythonw 是转发器，会再拉起基础解释器。
    """

    def setUp(self):
        from et_desktop import app as A
        self.A = A
        self._orig = A.DAEMON_MUTEX
        A.DAEMON_MUTEX = "EasyTranslator-test-%d" % os.getpid()   # 别去碰用户真在跑的那把锁

    def tearDown(self):
        self.A.DAEMON_MUTEX = self._orig

    def test_second_acquire_is_refused(self):
        h1 = self.A.acquire_single_instance()
        self.assertIsNotNone(h1, "第一把锁就没拿到（返回 None）")
        self.assertNotEqual(True, h1, "拿锁时走了异常兜底（说明 Win32 调用本身出错）")
        self.assertTrue(h1, "句柄是 0/被截断 —— restype 没声明")
        h2 = self.A.acquire_single_instance()
        self.assertIsNone(h2, "第二次也拿到锁了 —— 单实例锁失效，会跑出两个守护")


class FrozenBehaviourCase(unittest.TestCase):
    """打包成 exe 之后路径与自启命令必须换一套（否则「下载就能用」会漏）。"""

    def setUp(self):
        from et_desktop import ui, settings_ui
        self.ui, self.S = ui, settings_ui
        import sys as _sys
        self._sys = _sys
        self._saved = (getattr(_sys, "frozen", None), getattr(_sys, "_MEIPASS", None))

    def tearDown(self):
        for name, val in zip(("frozen", "_MEIPASS"), self._saved):
            if val is None:
                if hasattr(self._sys, name):
                    delattr(self._sys, name)
            else:
                setattr(self._sys, name, val)

    def test_source_run_uses_repo_and_vbs(self):
        self.assertEqual(self.ui.REPO, self.ui.res_dir(), "源码运行时资源目录应是仓库根")
        self.assertIn("start_daemon.vbs", self.S.autostart_command())

    def test_frozen_run_uses_meipass_and_exe(self):
        self._sys.frozen = True
        self._sys._MEIPASS = os.path.join(os.sep, "tmp", "meipass-test")
        self.assertEqual(self._sys._MEIPASS, self.ui.res_dir(), "打包后资源目录要认 _MEIPASS")
        cmd = self.S.autostart_command()
        self.assertNotIn("wscript", cmd, "打包后自启不能再指向 vbs —— 别人机器上没有那个脚本")
        self.assertIn("--daemon", cmd)
        self.assertIn(os.path.basename(self._sys.executable).lower(), cmd.lower())


class AutostartDoubleInsuranceCase(unittest.TestCase):
    """开机自启双保险：注册表 Run + 「启动」文件夹。

    来由：本机 aTrust 这类安全代理会在 1~2 分钟内把新加的 Run 项清掉
    （实测：写好 40 秒还在、130 秒就没了）—— 只剩注册表那份的话，自启根本不生效。
    """

    def setUp(self):
        from et_desktop import settings_ui as S
        self.S = S
        self.tmp = tempfile.mkdtemp(prefix="et-autostart-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._saved = (S.startup_dir, S._set_run_entry, S._get_run_entry)
        S.startup_dir = lambda: self.tmp                 # 不碰真实「启动」文件夹
        self._run = None
        S._set_run_entry = lambda on: (setattr(self, "_run", on), True)[1]
        S._get_run_entry = lambda: (self._run is True, "run-cmd" if self._run else "")

    def tearDown(self):
        self.S.startup_dir, self.S._set_run_entry, self.S._get_run_entry = self._saved

    def test_vbs_content_quotes_and_hides(self):
        content = self.S.startup_vbs_content()
        inner = self.S.autostart_command().replace('"', '""')
        self.assertIn(inner, content, "vbs 里要把命令原样写进去（引号翻倍）")
        self.assertIn(", 0, False", content, "窗口样式 0 + 不等待 = 完全无窗口")

    def test_set_on_writes_both_places(self):
        self.assertTrue(self.S.set_autostart(True))
        self.assertTrue(os.path.exists(self.S.startup_vbs_path()))
        self.assertTrue(self.S._get_run_entry()[0])
        self.assertTrue(self.S.autostart_info()[0])

    def test_startup_vbs_is_utf16_with_bom(self):
        """中文用户名（C:\\Users\\小明）机器上，WSH 按 ANSI 解无 BOM 脚本 → 路径乱码、
        自启静默失效。必须写 UTF-16（Python 的 utf-16 自带 BOM）。"""
        self.assertTrue(self.S.set_autostart(True))
        with open(self.S.startup_vbs_path(), "rb") as f:
            head = f.read(2)
        self.assertEqual(b"\xff\xfe", head, "vbs 不是 UTF-16 带 BOM —— 中文路径会乱码")
        with open(self.S.startup_vbs_path(), encoding="utf-16") as f:
            text = f.read()
        # 源码模式内容 = 拉起 start_daemon.vbs；打包模式 = exe --daemon。两者必有 sh.Run。
        self.assertIn("sh.Run", text)
        self.assertIn("--daemon" if "--daemon" in self.S.autostart_command() else "start_daemon.vbs", text)

    def test_set_off_removes_both_places(self):
        self.S.set_autostart(True)
        self.assertTrue(self.S.set_autostart(False))
        self.assertFalse(os.path.exists(self.S.startup_vbs_path()))
        self.assertFalse(self.S._get_run_entry()[0])
        self.assertFalse(self.S.autostart_info()[0])

    def test_info_true_when_only_the_startup_folder_has_it(self):
        """注册表那份被清掉、只剩「启动」文件夹 → 仍算已开启（本机的真实情况）。"""
        self.S.set_autostart(True)
        self._run = None
        on, how = self.S.autostart_info()
        self.assertTrue(on)
        self.assertEqual(how, self.S.startup_vbs_path())


if __name__ == "__main__":
    unittest.main(verbosity=2)
