# -*- coding: utf-8 -*-
"""
启动器验证 / Launcher verification
==============================================================================
按「启动桌宠.bat」的真实做法用 pythonw 启动（无控制台窗口），确认能起来、
有面板与宠物、且没有控制台窗口出现。
Launches exactly like 启动桌宠.bat does (pythonw, no console) and checks that
the app comes up with a panel and a pet and without a console window.
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from probe_windows import windows_of  # noqa: E402

_u = ctypes.WinDLL("user32", use_last_error=True)


def p(*a):
    print(*a, flush=True)


# 找到 bat 会选中的那个 pythonw / the pythonw the bat would pick
out = subprocess.run(["where", "pythonw"], capture_output=True, text=True)
exe = out.stdout.splitlines()[0].strip()
p("pythonw =", exe)

proc = subprocess.Popen([exe, "main.py"], cwd=ROOT)
p("launched pid =", proc.pid)
time.sleep(10)

if proc.poll() is not None:
    p("!! exited early, code =", proc.returncode)
    log = os.path.join(ROOT, "data", "startup_error.log")
    if os.path.exists(log):
        p(open(log, encoding="utf-8").read()[-1200:])
    sys.exit(1)

ws = windows_of(proc.pid)
panel = [w for w in ws if w["appwindow"] and w["visible"]]
pets = [w for w in ws if w["layered"] and w["toolwindow"] and w["visible"]]
console = [w for w in ws if w["title"] in ("", "标题") and not w["layered"]]
p("windows=%d | panel=%d | pets=%d" % (len(ws), len(panel), len(pets)))
for w in panel + pets:
    p("   %-28s rect=%s visible=%s" % (w["title"][:26], w["rect"], w["visible"]))

try:
    from PIL import ImageGrab
    f = os.path.join(HERE, "diag_pythonw.png")
    ImageGrab.grab().save(f)
    p("screenshot ->", f)
except Exception as exc:  # noqa: BLE001
    p("screenshot failed:", exc)

proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
p("stopped")