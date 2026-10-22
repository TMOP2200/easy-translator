# -*- coding: utf-8 -*-
"""把桌面 App 打成一个 exe：`desktop/dist/Easy Translator.exe`（双击即用，不需要装 Python）。

文件名叫「Easy Translator」：与窗口标题、任务栏显示、桌面快捷方式一致；
用户下载后**可以自行改名**（开机自启写的是当前 exe 的完整路径，改名后重开一次自启即指向新文件）。

用户要的「下载就能用」就是这条路：exe 里自带解释器，对方机器上什么都不用装。

用法：
  python desktop/tools/build_exe.py              # 打包
  python desktop/tools/build_exe.py --check      # 只看产物在不在、多大

打进 exe 的资源（运行时要能读到，代码里靠 `ui.res_dir()` = sys._MEIPASS 找）：
  assets/decor.png            卡片右下角那张默认装饰图
  assets/easy-translator.ico  窗口/任务栏图标
  docs/screenshot-web.png     总览图上那张 README 头图
配置与日志不进 exe —— 它们落在 `%APPDATA%\\EasyTranslator`（每个用户一份）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))        # desktop/tools
DESKTOP = os.path.dirname(HERE)                          # desktop
REPO = os.path.dirname(DESKTOP)                          # 仓库根
DIST = os.path.join(DESKTOP, "dist")
EXE = os.path.join(DIST, "Easy Translator.exe")

RES = ((os.path.join(REPO, "assets", "decor.png"), "assets"),
       (os.path.join(REPO, "assets", "easy-translator.ico"), "assets"),
       (os.path.join(REPO, "docs", "mascot-header.png"), "docs"),
       (os.path.join(REPO, "docs", "screenshot-web.png"), "docs"))
ICON = os.path.join(REPO, "assets", "easy-translator.ico")


def check() -> int:
    if not os.path.exists(EXE):
        print("还没有产物：%s\n跑一次  python desktop/tools/build_exe.py" % EXE)
        return 1
    print("%s  %.1f MB" % (EXE, os.path.getsize(EXE) / 1024 / 1024))
    return 0


def build() -> int:
    # 正在跑的那个 exe 会把文件锁住，PyInstaller 只会丢一句难懂的报错 —— 先友好地提醒。
    # （外部看门狗已删：自愈/每分钟拉起那套没有了，打包前用 tools\daemon_ctl.ps1 暂停、打完 -Resume 恢复。）
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Easy Translator.exe"],
                             capture_output=True, text=True).stdout
        if "Easy Translator.exe" in out:
            print("正在运行的 Easy Translator.exe 会让打包写不进文件。\n"
                  "先暂停：  powershell -NoProfile -ExecutionPolicy Bypass -File tools\\daemon_ctl.ps1\n"
                  "打完恢复：同一条命令加 -Resume")
            return 1
    except Exception:
        pass
    # 默认装饰图是生成物：没有就先按配方生成，免得打出一个没图的 exe
    if not os.path.exists(RES[0][0]):
        print("先补 assets/decor.png …")
        subprocess.check_call([sys.executable, os.path.join(HERE, "make_decor.py")])
    for src, _dest in RES:
        if not os.path.exists(src):
            print("缺资源：%s" % src)
            return 1

    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--windowed", "--name", "Easy Translator",
            "--icon", ICON,
            "--paths", DESKTOP,
            "--distpath", DIST,
            "--workpath", os.path.join(DESKTOP, "build"),
            "--specpath", os.path.join(DESKTOP, "build")]
    for src, dest in RES:
        args += ["--add-data", "%s%s%s" % (src, os.pathsep, dest)]
    # comtypes 是 uiautomation 的 COM 依赖，属动态导入，PyInstaller 有时漏掉 → 显式收全
    args += ["--collect-all", "comtypes"]
    args += [os.path.join(DESKTOP, "pack_entry.py")]

    print("PyInstaller …")
    subprocess.check_call(args)
    return check()


def main() -> int:
    ap = argparse.ArgumentParser(description="打包桌面 App 成单文件 exe")
    ap.add_argument("--check", action="store_true", help="只看产物")
    args = ap.parse_args()
    return check() if args.check else build()


if __name__ == "__main__":
    raise SystemExit(main())
