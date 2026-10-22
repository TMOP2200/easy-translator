# -*- coding: utf-8 -*-
"""控制窗口里「本机模型列表」与「开机自启」两处的判据（纯逻辑 + 本地假端点）。

为什么值得单独测：
  · 下拉列表是「可以从哪些小模型里选」的唯一入口，解析错 = 用户面前是个空列表；
  · 端点两种形态（Ollama 原生 /api/tags、OpenAI 兼容 /v1/models）都得认，
    用户填 `http://127.0.0.1:11434` 还是 `http://127.0.0.1:11434/v1` 都要能用；
  · 端点没起时**必须安静地返回空表**，不能把界面搞崩（这条最容易在真机上踩）。

跑：python tests/test_model_list.py     （unittest，不需要 pytest）
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from et_desktop import settings_ui as S          # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    """只认几条固定路径，用于验证 URL 候选顺序。"""

    def do_GET(self):                             # noqa: N802
        routes = {
            "/api/tags": {"models": [{"name": "qwen2.5vl:3b"}, {"name": "qwen2.5:1.5b"},
                                     {"name": "llama3.2:3b"}]},
            "/v1/models": {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-image-2"}]},
        }
        body = routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):                    # 静音
        pass


class ModelListCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_parse_both_shapes(self):
        """Ollama 的 models[].name 与 OpenAI 的 data[].id 都要认，且去重排序。"""
        self.assertEqual(["qwen2.5:1.5b", "qwen2.5vl:3b"],
                         S._model_names({"models": [{"name": "qwen2.5vl:3b"},
                                                    {"name": "qwen2.5:1.5b"},
                                                    {"name": "qwen2.5vl:3b"}]}))
        self.assertEqual(["gpt-4o-mini"], S._model_names({"data": [{"id": "gpt-4o-mini"}]}))
        self.assertEqual([], S._model_names(None))
        self.assertEqual([], S._model_names({"models": [{"nope": 1}, 42]}))

    def test_fetch_accepts_either_base_url_flavour(self):
        """用户填 `…:11434` 或 `…:11434/v1` 都必须能拉到同一份列表。"""
        bare = "http://127.0.0.1:%d" % self.port
        with_v1 = bare + "/v1"
        self.assertEqual(["llama3.2:3b", "qwen2.5:1.5b", "qwen2.5vl:3b"],
                         S.fetch_models(bare, timeout=3.0))
        self.assertEqual(["llama3.2:3b", "qwen2.5:1.5b", "qwen2.5vl:3b"],
                         S.fetch_models(with_v1, timeout=3.0))

    def test_fetch_against_openai_only_endpoint(self):
        """只有 /v1/models 的端点（没装 Ollama）也要能用。"""
        names = S.fetch_models("http://127.0.0.1:%d/v1/models" % self.port, timeout=3.0)
        self.assertIn("gpt-4o-mini", names)

    def test_fetch_never_raises(self):
        """端点没起 / 地址乱填 / 空串：一律返回空表，绝不能抛（UI 在线程里调它）。"""
        self.assertEqual([], S.fetch_models("", timeout=1.0))
        self.assertEqual([], S.fetch_models("　　乱写的", timeout=1.0))
        self.assertEqual([], S.fetch_models("http://127.0.0.1:9", timeout=1.0))

    def test_autostart_info_never_raises(self):
        """读注册项：返回 (True/False/None, 字符串)，不许抛。"""
        enabled, cmd = S.autostart_info()
        self.assertIn(enabled, (True, False, None))
        self.assertIsInstance(cmd, str)

    def _make_window(self, cfg=None):
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
        if cfg is None:
            cfg = json.loads(json.dumps({"enabled": True, "dwellMs": 2000, "examplesCount": 3,
                                         "showSpeak": True, "engine": "auto",
                                         "model": {"enabled": True,
                                                   "baseUrl": "http://127.0.0.1:%d/v1" % self.port,
                                                   "apiKey": "", "textModel": "qwen2.5:1.5b",
                                                   "visionModel": "qwen2.5vl:3b", "timeoutMs": 60000},
                                         "imageOcr": {"enabled": True, "dwellMs": 1500, "cropW": 460,
                                                      "cropH": 140, "hint": True}}))
        mascot = ui.load_mascot(os.path.join(ROOT, "assets", "mascot.png"))
        win = S.SettingsWindow(root, cfg, lambda *a: None, mascot=mascot,
                               test_text=lambda: (True, "ok"))
        win.update()
        return root, win

    def test_window_shows_model_choices(self):
        """窗口真建出来时：两个下拉必须存在，且 _apply_models 能把候选灌进去。"""
        root, win = self._make_window()
        self.assertIsNotNone(getattr(win, "_combo_textModel", None), "文本模型下拉没建出来")
        self.assertIsNotNone(getattr(win, "_combo_visionModel", None), "视觉模型下拉没建出来")
        # 分页之后要先把那一页切出来（没映射的下拉 cb.get() 读不到值 —— 代码里已改成走 textvariable）
        win._nav_select("model")
        win.update()
        win._apply_models(["a:1b", "b:2b"])
        win.update()
        self.assertEqual(["a:1b", "b:2b"], list(win._combo_textModel.cget("values")))
        self.assertEqual("qwen2.5vl:3b", win._combo_visionModel.get(), "灌列表不能把当前值冲掉")
        # 在别的页上刷新列表：候选要更新，但**已选模型不能被改掉**（值存在 textvariable 里）
        win._nav_select("overview")
        win.update()
        win._apply_models(["c:3b"])
        win.update()
        self.assertEqual(["c:3b"], list(win._combo_textModel.cget("values")))
        self.assertEqual("qwen2.5:1.5b", win._combo_textModel._et_var.get(),
                         "刷新列表把已选模型冲掉了")
        # 窗口/任务栏图标：同一枚 .ico（缺文件时安静跳过，所以只在文件存在时断言）。
        # 注意：`wm_iconbitmap()` 这个**取值**在窗口 map 之前恒为空串（Tk 在 Windows 上是
        # 交给窗口管理器去设的，读不回来）→ 只能断言代码路径确实拿着那枚文件跑过了。
        ico = os.path.join(ROOT, "assets", "easy-translator.ico")
        if os.path.exists(ico):
            self.assertEqual(ico, getattr(win, "_icon_path", None),
                             "窗口图标没设上（任务栏会是 Tk 羽毛）")
        win.destroy()
        root.destroy()

    def test_nav_switches_pages(self):
        """左栏导航是**分页**：点哪一项就只显示哪一页（用户要的「点哪个项目就出现哪个项目的文字」）。

        顺带钉住高亮与「切回顶部」——切页后还停在上一页的滚动位置会很怪。
        """
        root, win = self._make_window()
        self.assertEqual(S.ACCENT, win._nav["overview"].cget("bg"), "默认应高亮「总览」")
        self.assertTrue(win._pages["overview"].winfo_ismapped(), "开局应显示「总览」页")
        self.assertFalse(win._pages["model"].winfo_ismapped(), "没点过的页不该显示")

        win._nav_select("model")
        win.update()
        self.assertEqual(S.ACCENT, win._nav["model"].cget("bg"), "点「本地小模型」应高亮它")
        self.assertNotEqual(S.ACCENT, win._nav["overview"].cget("bg"), "旧高亮要撤掉")
        self.assertTrue(win._pages["model"].winfo_ismapped(), "点了就该显示这一页")
        self.assertFalse(win._pages["overview"].winfo_ismapped(), "别的页要收起来")
        self.assertEqual(0.0, win._canvas.yview()[0], "切页后应在该页顶部")

        win._nav_select("overview")
        win.update()
        self.assertTrue(win._pages["overview"].winfo_ismapped())
        self.assertFalse(win._pages["model"].winfo_ismapped())

    def test_every_nav_item_has_a_page_and_only_one_shows(self):
        """导航项与页面一一对应，且任何时候**只有一页**是显示的。"""
        root, win = self._make_window()
        self.assertEqual([k for k, _t in S.PAGES], list(win._nav.keys()))
        for key in win._nav:
            self.assertIn(key, win._pages, "「%s」没有对应页" % key)
        for key in win._nav:
            win._nav_select(key)
            win.update()
            shown = [k for k in win._pages if win._pages[k].winfo_ismapped()]
            self.assertEqual([key], shown, "选了「%s」却显示了 %s" % (key, shown))
        win.destroy()
        root.destroy()

    def test_help_page_has_the_manual(self):
        """app 里得有说明书（用户要的「写个说明书在 app 当中」），而且要写清**装了什么东西**。"""
        root, win = self._make_window()
        win._nav_select("help")
        win.update()
        texts = []

        def walk(w):
            for ch in w.winfo_children():
                try:
                    if ch.winfo_class() == "Label" and ch.cget("text"):
                        texts.append(str(ch.cget("text")))
                except Exception:
                    pass
                walk(ch)
        walk(win._pages["help"])
        joined = " ".join(texts)
        for want in ("鼠标停留在英文单词上", "退出桌面取词", "开机自启", "窗口右下角",
                     "--selftest", "%APPDATA%", "注册表", "恢复默认设置"):
            self.assertIn(want, joined, "说明书里没提「%s」" % want)
        self.assertGreater(len(joined), 300, "说明书也太短了")
        win.destroy()
        root.destroy()

    def test_help_page_does_not_repeat_other_pages(self):
        """说明书**不重复**别的栏目已经讲过的操作（用户点名说的「与前一些模块重复」）。

        装饰图 / 图片取词 / 本地小模型各自那一页里都有，说明书只指路、不复述。
        """
        root, win = self._make_window()
        win._nav_select("help")
        win.update()
        texts = []

        def walk(w):
            for ch in w.winfo_children():
                try:
                    if ch.winfo_class() == "Label" and ch.cget("text"):
                        texts.append(str(ch.cget("text")))
                except Exception:
                    pass
                walk(ch)
        walk(win._pages["help"])
        joined = " ".join(texts)
        # 「Ollama」不在黑名单里：说明书新增的「模型从哪来（正版渠道/大小/存放位置）」
        # 是原栏目没有的信息，不算重复。这里禁的是**操作步骤**被复述。
        for dup in ("浏览…", "刷新列表", "本地视觉模型", "裁剪宽度"):
            self.assertNotIn(dup, joined, "说明书把别的栏目的事又说了一遍：%s" % dup)
        win.destroy()
        root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
