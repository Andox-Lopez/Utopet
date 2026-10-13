# -*- coding: utf-8 -*-
"""对打包好的 exe 验证右键宠物能弹出菜单。

复用 verify_right_click_e2e 的做法，但目标是 dist\\Shimeji\\Shimeji.exe，
且启动前清空 PATH 以证明不依赖本机 Python。

用法：python analysis/verify_exe_right_click.py
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
DIST = os.path.join(ROOT, "dist", "Shimeji")
EXE = os.path.join(DIST, "Shimeji.exe")

user32 = ctypes.windll.user32
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]


def send_mouse(flags: int):
    user32.SendInput(1, ctypes.byref(INPUT(0, MOUSEINPUT(0, 0, 0, flags, 0, None))),
                     ctypes.sizeof(INPUT))


def wins(pid: int) -> list[dict]:
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append({"hwnd": hwnd, "visible": bool(user32.IsWindowVisible(hwnd)),
                        "tool": bool(ex & 0x80), "rect": (r.left, r.top, r.right, r.bottom)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def all_hwnds() -> set[int]:
    s: set[int] = set()
    user32.EnumWindows(EnumWindowsProc(lambda h, _: (s.add(h), True)[1]), 0)
    return s


def popups(before: set[int]) -> list[dict]:
    """Qt 的弹出菜单是独立原生窗口，不能按 pid 过滤，只能按 class 认。"""
    res = []

    def cb(hwnd, _):
        if hwnd in before:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "Popup" in cls.value or "QMenu" in cls.value:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if (r.right - r.left) > 20 and (r.bottom - r.top) > 20:
                res.append({"cls": cls.value, "rect": (r.left, r.top, r.right, r.bottom)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return res


def main() -> int:
    env = {k: v for k, v in os.environ.items()
           if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                            "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "SYSTEMDRIVE")}
    env["PATH"] = r"C:\Windows\System32"
    proc = subprocess.Popen([EXE], env=env, cwd=DIST)
    pid = proc.pid
    print(f"[pid] {pid}  (PATH={env['PATH']})", flush=True)
    time.sleep(10.0)

    if proc.poll() is not None:
        print(f"[FAIL] 退出 rc={proc.returncode}", flush=True)
        return 2

    pets = [w for w in wins(pid) if w["visible"] and w["tool"]]
    print(f"[宠物] {len(pets)} 个", flush=True)
    if not pets:
        print("[FAIL] 没有宠物", flush=True)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return 3

    p = pets[0]
    x0, y0, x1, y1 = p["rect"]
    cx, cy = (x0 + x1) // 2, y1 - 42
    print(f"[右键点] ({cx}, {cy})  宠物rect={p['rect']}", flush=True)

    before = all_hwnds()
    user32.SetCursorPos(cx, cy)
    time.sleep(0.3)
    send_mouse(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(0.06)
    send_mouse(MOUSEEVENTF_RIGHTUP)
    time.sleep(1.2)

    pops = popups(before)
    print(f"\n[结果] 弹出窗口 {len(pops)} 个", flush=True)
    for w in pops:
        ww, hh = w["rect"][2] - w["rect"][0], w["rect"][3] - w["rect"][1]
        print(f"    {w['cls']}  {w['rect']}  {ww}x{hh}px", flush=True)

    # ESC 关菜单
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 2, 0)
    time.sleep(0.4)
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)

    ok = len(pops) >= 1
    print(f"\n结论 / verdict: "
          f"{'PASS exe 右键弹出菜单' if ok else 'FAIL exe 右键无菜单'}", flush=True)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
