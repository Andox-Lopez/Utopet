# -*- coding: utf-8 -*-
"""
真实环境启动测试 / Real-environment launch test
==============================================================================
真的跑 20 秒（不是离屏），检查：
* 任务栏面板是否拿到 WS_EX_APPWINDOW（即任务栏会给它一个按钮）
* 控制面板标题、图标
* 宠物是否正常走动，日志里有无异常

Really runs for 20 seconds (not offscreen) and checks:
* whether the taskbar panel got WS_EX_APPWINDOW (i.e. gets a taskbar button)
* the panel title and icon
* mascots actually move, and no exceptions land in the log
"""
import ctypes
import os
import sys
import tempfile

from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.icons import app_icon  # noqa: E402
from shimeji.settings import Settings  # noqa: E402
from shimeji.win32 import set_app_user_model_id, get_window_title  # noqa: E402

GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

_u = ctypes.WinDLL("user32", use_last_error=True)
_u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_u.GetWindowLongW.restype = ctypes.c_long


def p(*a):
    print(*a, flush=True)


p("AppUserModelID ->", set_app_user_model_id())
app.setWindowIcon(app_icon())

s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
get_i18n().set_language(s.get("language"))
m = Manager(app, s)

panel = m._panel
hwnd = int(panel.winId())
ex = _u.GetWindowLongW(hwnd, GWL_EXSTYLE)
p("panel hwnd      =", hwnd)
p("panel title     =", get_window_title(hwnd))
p("WS_EX_APPWINDOW =", bool(ex & WS_EX_APPWINDOW), " -> taskbar button:",
  bool(ex & WS_EX_APPWINDOW) and not (ex & WS_EX_TOOLWINDOW))
p("WS_EX_TOOLWINDOW=", bool(ex & WS_EX_TOOLWINDOW))
p("panel visible   =", panel.isVisible(), "| size =", panel.width(), "x", panel.height())
p("panel pos       =", panel.x(), panel.y())

before = [(mm.anchor.x, mm.anchor.y) for mm in m.mascots]
p("mascots =", m.count(), "| anchors =", before)


def finish():
    after = [(mm.anchor.x, mm.anchor.y) for mm in m.mascots]
    moved = sum(1 for a, b in zip(before, after) if a != b)
    p("moved mascots =", moved, "/", len(after))
    p("final count   =", m.count())
    m.quit()
    app.quit()


QTimer.singleShot(20000, finish)
rc = app.exec()
p("exit code =", rc)

log_path = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "data", "shimeji.log")
if os.path.exists(log_path):
    lines = open(log_path, encoding="utf-8").read().splitlines()[-15:]
    p("--- log tail ---")
    for line in lines:
        p(line)
