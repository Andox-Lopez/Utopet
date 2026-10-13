# -*- coding: utf-8 -*-
"""
修复验证 / Fix verification
==============================================================================
1) 真实启动后：任务栏面板是否抢焦点（GetForegroundWindow 是不是它）
2) 面板是否完整落在工作区内（不被任务栏遮住）
3) 启动失败路径：是否写日志 + 弹窗（弹窗用假 MessageBoxW 拦截）
Verifies: focus stealing, work-area clamping, and the failure-report path.
"""
import ctypes
import os
import subprocess
import sys
import time
import types
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from probe_windows import windows_of  # noqa: E402

_u = ctypes.WinDLL("user32", use_last_error=True)
_u.GetForegroundWindow.restype = wintypes.HWND
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u.GetWindowThreadProcessId.restype = wintypes.DWORD


def p(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 1 & 2
proc = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT)
p("child pid =", proc.pid)
time.sleep(9)

fg = _u.GetForegroundWindow()
pid = wintypes.DWORD()
_u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
p("foreground hwnd=%s pid=%s  (child=%s)" % (fg, pid.value, proc.pid))
p("focus stolen by shimeji =", pid.value == proc.pid)

ws = windows_of(proc.pid)
panel = [w for w in ws if w["appwindow"] and w["visible"]]
pets = [w for w in ws if w["layered"] and w["toolwindow"] and w["visible"]]
p("panel windows =", len(panel), "| visible pets =", len(pets))
for w in panel:
    l, t, r, b = w["rect"]
    p("  panel rect=%s  work area=%s" % (w["rect"], (0, 0, 1920, 1032)))
    p("  fully inside work area =", l >= 0 and t >= 0 and r <= 1920 and b <= 1032)

# 光标是否落在面板内（应当为 False）/ cursor must not sit inside the panel
from shimeji import win32 as _w  # noqa: E402  (无 Qt 依赖，安全)
cx, cy = _w.get_cursor_pos()
for w in panel:
    l, t, r, b = w["rect"]
    p("  cursor%s inside panel rect = %s" % ((cx, cy), l <= cx <= r and t <= cy <= b))

proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()

# ---------------------------------------------------------------- 3
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("shim_main", os.path.join(ROOT, "main.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

calls = []


class _FakeUser32:
    def MessageBoxW(self, *a):
        calls.append(a[1] if len(a) > 1 else "")
        return 1


ctypes.windll = types.SimpleNamespace(user32=_FakeUser32())
log = os.path.join(ROOT, "data", "startup_error.log")
before = os.path.getsize(log) if os.path.exists(log) else 0
rc = mod.startup_fail(RuntimeError("simulated failure"), "selftest")
after = os.path.getsize(log) if os.path.exists(log) else 0
p("startup_fail -> rc=%s | MessageBoxW called=%s | log grew %d bytes"
  % (rc, bool(calls), after - before))
if calls:
    p("--- message head ---")
    p(calls[0].splitlines()[0])
    p(calls[0].splitlines()[1][:60])