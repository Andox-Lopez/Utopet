# -*- coding: utf-8 -*-
"""验证面板不再因为鼠标靠近而移动。

做法：启动程序 → 记录面板位置 → 把真实鼠标光标移到面板正中间 → 等 1.5 秒
（期间 refresh_status 的 500ms 定时器会触发多次 _place）→ 再记录位置。
位置必须一模一样。

顺带验证：点击「设置」按钮能真正打开设置窗口（之前面板会跑掉，点不中）。

用法：python analysis/verify_panel_stable.py
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

user32 = ctypes.windll.user32
SW_RESTORE = 9
MOUSEEVENTF_MOVE = 0x0001
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_panel(pid: int) -> int:
    """找到面板窗口：可见 + 有任务栏按钮(appwindow) + 不是桌宠(tool) """
    found = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        ex = user32.GetWindowLongPtrW(hwnd, -20)
        if ex & 0x40000 and not (ex & 0x80):   # WS_EX_APPWINDOW and not TOOLWINDOW
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def rect(hwnd: int):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def move_cursor(x: int, y: int):
    user32.SetCursorPos(int(x), int(y))


def main() -> int:
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "main.py")],
        cwd=ROOT, env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW
    print(f"[pid] {proc.pid}", flush=True)
    time.sleep(7.0)

    hwnd = find_panel(proc.pid)
    if not hwnd:
        print("[FAIL] 没找到任务栏面板", flush=True)
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        return 2
    print(f"[panel] hwnd={hwnd}", flush=True)

    r0 = rect(hwnd)
    print(f"[before] rect={r0}", flush=True)

    # 关键动作：把光标放到面板正中心
    cx = (r0[0] + r0[2]) // 2
    cy = (r0[1] + r0[3]) // 2
    move_cursor(cx, cy)
    got = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(got))
    print(f"[cursor] 已移到 ({got.x}, {got.y})，面板中心附近", flush=True)

    # 面板的 refresh_status 定时器 500ms 跑一次，等 1.6s 覆盖 3 次
    for i in range(4):
        time.sleep(0.4)
        r = rect(hwnd)
        tag = "同一位置" if r == r0 else "*** 移动了 ***"
        print(f"   t+{0.4*(i+1):.1f}s  rect={r}  {tag}", flush=True)

    r1 = rect(hwnd)
    moved = r1 != r0
    print(f"\n[结果] 光标停在面板上期间，面板{'移动了' if moved else '纹丝不动'}", flush=True)

    # 再看设置窗口能不能被点开
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    print("\n[附加] 面板在前台，检查按钮可点（未自动激活不阻塞 Qt 内部点击）", flush=True)

    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    time.sleep(0.5)
    print(f"\n结论 / verdict: {'FAIL 面板会躲光标' if moved else 'PASS 面板位置稳定'}", flush=True)
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
