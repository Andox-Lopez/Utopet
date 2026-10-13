# -*- coding: utf-8 -*-
"""复现「关掉任务栏面板 → 宠物陆续消失 / 程序自己退出」。

怀疑链条：
  1. Manager.quit() 之外，是否有别的路径让宠物被 unregister？
  2. 面板 closeEvent 调 hide()，但 Manager 没有「面板被关 → 托盘也走」的逻辑，
     那 QSystemTrayIcon 还活着吗？
  3. 真正嫌疑：面板的 closeEvent 调 self.hide()，而 TaskbarPanel 的
     `WA_ShowWithoutActivating` + 托盘都没问题；但**如果面板是唯一带
     WS_EX_APPWINDOW 的窗口**，关掉它以后进程就没有任何可见窗口了。
     Qt 的 quitOnLastWindowClosed 我们设了 False，理论上不会退……但
     QSystemTrayIcon 在某些情况下会被 Qt 视作「没有活跃 UI」而退出。
  4. 另一个非常真实的嫌疑：用户说的「不会在任务栏出现后台常驻图标」——
     面板是**唯一**的任务栏常驻物。关掉它，任务栏上就什么都不剩了，
     用户以为程序退了，但它其实还在跑；随后宠物因为某种原因消失，
     用户就归因成「自动退出」。

本脚本：启动 → 记录状态 → 关面板 → 每 2s 记录一次，共 30s，看进程/宠物/托盘变化。
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
WM_CLOSE = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid: int) -> list[dict]:
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            out.append({
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "appwindow": bool(ex & 0x40000),
                "tool": bool(ex & 0x80),
                "cls": cls.value,
            })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def find_panel(pid: int) -> int:
    for w in windows_of(pid):
        pass
    found = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            if ex & 0x40000 and not (ex & 0x80):
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "main.py")],
        cwd=ROOT, creationflags=0x08000000)
    pid = proc.pid
    print(f"[pid] {pid}", flush=True)
    time.sleep(8.0)

    wins = windows_of(pid)
    vis = [w for w in wins if w["visible"]]
    print(f"[初始] 可见窗口 {len(vis)}: "
          f"{[('panel' if w['appwindow'] else 'pet/tool') for w in vis]}", flush=True)

    panel = find_panel(pid)
    if not panel:
        print("[FAIL] 没找到面板", flush=True)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return 2
    print(f"[panel] hwnd={panel}", flush=True)

    # 关掉面板
    print("\n>>> 发送 WM_CLOSE 关闭面板", flush=True)
    user32.PostMessageW(panel, WM_CLOSE, 0, 0)

    log = os.path.join(ROOT, "data", "shimeji.log")
    start = os.path.getsize(log) if os.path.exists(log) else 0

    print("\n时间   进程   可见窗口  面板  宠物(tool)  其它")
    print("-" * 62, flush=True)
    for i in range(15):
        time.sleep(2.0)
        alive = proc.poll() is None
        if not alive:
            print(f"  {2*(i+1):>3}s  已退出 (rc={proc.returncode})", flush=True)
            break
        ws = windows_of(pid)
        v = [w for w in ws if w["visible"]]
        p_ = [w for w in v if w["appwindow"] and not w["tool"]]
        pets = [w for w in v if w["tool"]]
        other = [w for w in v if not w["appwindow"] and not w["tool"]]
        print(f"  {2*(i+1):>3}s  存活   {len(v):^6}  {len(p_):^5}  {len(pets):^9}  {len(other)}",
              flush=True)

    print("\n" + "=" * 62, flush=True)
    alive = proc.poll() is None
    ws = windows_of(pid) if alive else []
    v = [w for w in ws if w["visible"]]
    print(f"30s 后：进程 {'存活' if alive else '已退出'}", flush=True)
    print(f"        可见窗口 {len(v)} 个", flush=True)
    if alive:
        print("        -> 进程没退，但任务栏上是否还有常驻图标取决于面板是否可见", flush=True)
        print(f"        -> 面板可见 = {any(w['appwindow'] and not w['tool'] for w in v)}", flush=True)

    if os.path.exists(log):
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            f.seek(start)
            tail = f.read()
        if tail.strip():
            print("\n--- 新增日志 ---", flush=True)
            print(tail[-2000:], flush=True)

    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
