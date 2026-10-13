# -*- coding: utf-8 -*-
"""
Shimeji 重制版 —— 程序入口
Shimeji Remake —— application entry point
==============================================================================

    python main.py

启动后：任务栏会出现一个常驻控制面板（可右键「固定到任务栏」），系统托盘也有
图标；右键宠物本体可召唤 / 解散 / 打开设置。

On start: a control panel shows up in the taskbar (right-click it to "Pin to
taskbar"), a tray icon appears as well, and right-clicking a mascot summons,
dismisses or opens the settings window.

启动失败（缺依赖等）不会静默退出：写 data/startup_error.log 并弹窗说明原因。
A failed start-up never exits silently: the reason goes to
data/startup_error.log and is shown in a message box.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 保证从任意目录启动都能 import shimeji / make imports work from any cwd
sys.path.insert(0, APP_DIR)

ERROR_LOG = os.path.join(APP_DIR, "data", "startup_error.log")

# 切换解释器时用它防止无限递归：置位后子进程不再尝试切换
_RELAUNCH_GUARD = "SHIMEJI_NO_RELAUNCH"


def _probe_has_pyside6(interpreter: str) -> bool:
    """问一个解释器「你装 PySide6 了吗」/ Ask an interpreter whether PySide6 is there."""
    if not interpreter or not os.path.isfile(interpreter):
        return False
    try:
        import subprocess

        r = subprocess.run(
            [interpreter, "-c", "import PySide6.QtWidgets"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001 - 探测失败就当它不行
        return False


def _candidate_interpreters() -> list[str]:
    """列出机器上所有可能的 Python / List every plausible Python on this box.

    Windows 上 `where python` 经常返回一堆：WorkBuddy 自带的、conda 的、
    C:\\Python314 的…… 用户双击 .bat 时命中的可能恰好是没装 PySide6 的那个。
    这就是「手动启动看起来没正确运行」的直接原因，所以这里要把它们都试一遍。
    """
    import glob
    import subprocess

    found: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if not p:
            return
        p = os.path.abspath(p)
        key = p.lower()
        if key in seen or not os.path.isfile(p):
            return
        seen.add(key)
        found.append(p)

    add(sys.executable)

    # `py -0p` 会列出 py launcher 已知的所有版本（最权威）
    try:
        r = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            # 形如 "  -V:3.13        C:\Python313\python.exe"
            if "python" in line.lower() and ("\\" in line or "/" in line):
                add(line.strip().split()[-1].strip('"'))
    except Exception:  # noqa: BLE001
        pass

    # PATH 里的 python / pythonw
    for name in ("pythonw.exe", "python.exe"):
        try:
            r = subprocess.run(["where", name], capture_output=True, text=True, timeout=10)
            add(r.stdout.strip().splitlines()[0])
        except Exception:  # noqa: BLE001
            pass

    # 常见安装位置兜底
    for pat in (
        r"C:\Python*\python.exe",
        r"C:\Python*\pythonw.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\pythonw.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\python.exe"),
        r"C:\ProgramData\Anaconda3\python.exe",
        r"C:\ProgramData\Miniconda3\python.exe",
        os.path.expandvars(r"%USERPROFILE%\anaconda3\python.exe"),
        os.path.expandvars(r"%USERPROFILE%\miniconda3\python.exe"),
    ):
        for p in glob.glob(pat):
            add(p)

    return found



def startup_fail(exc: BaseException, phase: str) -> int:
    """把启动失败写日志 + 弹窗，绝不静默退出 / Log and report a start-up failure."""
    detail = traceback.format_exc()
    try:
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("=== %s  [%s]\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                            phase, detail))
    except OSError:
        pass
    msg = (
        "Utopet 桌宠启动失败 / failed to start\n\n"
        "%s: %s\n\n"
        "常见原因 / common causes:\n"
        "  · 没装依赖 / dependencies missing -> pip install -r requirements.txt\n"
        "  · 目录里有中文/空格导致路径异常\n\n"
        "更省事的办法 / easier way:\n"
        "  直接运行 tools\\build_release.py 生成自包含的 Utopet.exe，\n"
        "  之后双击 exe 即可，不需要装 Python 和任何依赖。\n\n"
        "详细日志 / full log:\n%s" % (type(exc).__name__, exc, ERROR_LOG)
    )
    print(msg, file=sys.stderr)
    try:  # 依赖都没装时 PySide6 不可用，退回 Win32 弹窗
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Utopet", 0x10)
    except Exception:  # noqa: BLE001
        pass
    return 2


def _try_relaunch_on_better_python(exc: BaseException) -> bool:
    """当前解释器缺 PySide6 时，换一个装了依赖的解释器重新启动。

    背景：Windows 上 `where python` 常返回多个候选，用户双击 .bat 命中的可能
    恰好是没装 PySide6 的那个（我们自己的运行环境就装在 WorkBuddy 目录里，
    但用户 PATH 里的 C:\\Python314 并没有）。与其报错让用户自己装依赖，
    不如先扫一遍机器上的 Python，找到能 import PySide6 的那个直接 exec 过去。

    Returns True 表示已成功移交，本进程不要再继续报错退出。
    """
    if os.environ.get(_RELAUNCH_GUARD):
        return False
    if not isinstance(exc, ImportError) or "PySide6" not in str(exc):
        return False

    current = os.path.abspath(sys.executable) if sys.executable else ""
    for cand in _candidate_interpreters():
        if os.path.abspath(cand).lower() == current.lower():
            continue
        if not _probe_has_pyside6(cand):
            continue
        print("[shimeji] 换用 %s 重新启动 / relaunching with %s" % (cand, cand),
              file=sys.stderr, flush=True)
        env = dict(os.environ)
        env[_RELAUNCH_GUARD] = "1"
        try:
            os.execve(cand, [cand, os.path.abspath(__file__)] + sys.argv[1:], env)
        except Exception:  # noqa: BLE001
            continue
    return False


try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from shimeji import win32
    from shimeji.engine.manager import Manager, list_characters
    from shimeji.i18n import get_i18n
    from shimeji.icons import app_icon
    from shimeji.settings import CHARACTERS_DIR, Settings
except BaseException as exc:  # noqa: BLE001 - 缺依赖时必须给出可读的原因
    if not _try_relaunch_on_better_python(exc):
        sys.exit(startup_fail(exc, "import"))


def main() -> int:
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("Utopet")
        app.setApplicationDisplayName("Utopet 桌宠")
        app.setWindowIcon(app_icon())
        # 必须在创建任何窗口之前声明，否则任务栏会显示 python.exe 的图标
        # Must be declared before any window is created, or the taskbar shows
        # python.exe's icon instead of ours.
        win32.set_app_user_model_id()

        settings = Settings()
        get_i18n().set_language(settings.get("language", "zh_CN"))

        if not list_characters(settings):
            QMessageBox.warning(
                None, get_i18n().t("app.name"),
                "%s\n%s" % (get_i18n().t("msg.no_character"), CHARACTERS_DIR))
            # 仍然启动，方便用户之后放入角色后再打开设置
            # still start so the user can fix it later
        manager = Manager(app, settings)
        return app.exec()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        return startup_fail(exc, "runtime")


if __name__ == "__main__":
    sys.exit(main())