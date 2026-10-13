# -*- coding: utf-8 -*-
"""端到端验证：真的用鼠标右键点宠物，菜单窗口是否出现。

这是唯一能证明「用户右键真的有反应」的测法 —— 前面那些都只能证明信号连上了。
做法：
  1. 启动程序，找一只宠物的窗口矩形
  2. 取宠物不透明像素最多的位置（避免点到透明区被 _hit 过滤掉）
  3. 用 SendInput 发真实的右键按下+抬起
  4. 枚举新出现的弹出菜单窗口（Qt 的 QMenu 是独立顶层窗口）

用法：python analysis/verify_right_click_e2e.py
"""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

user32 = ctypes.windll.user32
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]


def send_mouse(flags: int, x: int = 0, y: int = 0):
    mi = MOUSEINPUT(x, y, 0, flags, 0, None)
    inp = INPUT(INPUT_MOUSE, mi)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move_cursor(x: int, y: int):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)


def wins(pid: int) -> list[dict]:
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            out.append({"hwnd": hwnd, "visible": bool(user32.IsWindowVisible(hwnd)),
                        "tool": bool(ex & 0x80), "appwindow": bool(ex & 0x40000),
                        "rect": (r.left, r.top, r.right, r.bottom), "cls": cls.value})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def popup_menus(before: set[int]) -> list[dict]:
    """找出新出现的弹出菜单窗口 / newly appeared popup windows.

    注意：QMenu 是**独立进程**的窗口（Qt 弹出菜单会用自己的原生窗口），
    所以不能按 pid 过滤，否则找不到。要按 class 名认 QMenu / QtPopup。
    Also note: QMenu windows belong to no PID we can filter on, so match by class.
    """
    res = []

    def cb(hwnd, _):
        if hwnd in before:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        name = cls.value
        if "Popup" in name or "QMenu" in name or "Qt5/Qt6" in name and "Window" in name:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if (r.right - r.left) > 20 and (r.bottom - r.top) > 20:
                res.append({"hwnd": hwnd, "cls": name,
                            "rect": (r.left, r.top, r.right, r.bottom),
                            "visible": bool(user32.IsWindowVisible(hwnd))})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return res


def all_hwnds() -> set[int]:
    """当前所有顶层窗口的 hwnd 集合 / snapshot of every top-level window."""
    s: set[int] = set()

    def cb(hwnd, _):
        s.add(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return s


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "main.py")],
        cwd=ROOT, creationflags=0x08000000)
    pid = proc.pid
    print(f"[pid] {pid}", flush=True)
    time.sleep(8.0)

    if proc.poll() is not None:
        print("[FAIL] 进程启动即退出", flush=True)
        return 2

    # 找宠物窗口（tool 且可见）
    pets = [w for w in wins(pid) if w["visible"] and w["tool"]]
    print(f"[宠物] {len(pets)} 个", flush=True)
    if not pets:
        print("[FAIL] 没有宠物窗口", flush=True)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return 3

    p = pets[0]
    x0, y0, x1, y1 = p["rect"]
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    # 宠物是 128x128、脚底在底部，中心偏下更可能是不透明的躯干
    cy = y1 - 42
    print(f"[宠物窗口] rect={p['rect']}  -> 右键点 ({cx}, {cy})", flush=True)

    before = all_hwnds()

    move_cursor(cx, cy)
    time.sleep(0.3)
    send_mouse(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(0.06)
    send_mouse(MOUSEEVENTF_RIGHTUP)
    print("[操作] 已发出真实右键", flush=True)

    time.sleep(1.2)
    popups = [w for w in popup_menus(before) if w["visible"]]
    print(f"\n[结果] 新出现的弹出窗口 {len(popups)} 个", flush=True)
    for w in popups:
        w_, h_ = w["rect"][2] - w["rect"][0], w["rect"][3] - w["rect"][1]
        print(f"    {w['cls']}  {w['rect']}  {w_}x{h_}px", flush=True)

    # 收尾：按 ESC 关掉菜单
    send_mouse(0x0001)  # 保持位置
    user32.keybd_event(0x1B, 0, 0, 0)  # VK_ESCAPE down
    user32.keybd_event(0x1B, 0, 2, 0)  # up
    time.sleep(0.4)

    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)

    big = [w for w in popups if (w["rect"][2] - w["rect"][0]) > 60
           and (w["rect"][3] - w["rect"][1]) > 60]
    ok = len(big) >= 1
    print(f"\n结论 / verdict: "
          f"{'PASS 右键弹出了菜单' if ok else 'FAIL 右键没有菜单'}  "
          f"(找到 {len(big)} 个尺寸合理的弹出窗口)", flush=True)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
