# -*- coding: utf-8 -*-
"""验证 dist\\Shimeji\\Shimeji.exe 能否脱离本机 Python 环境启动。

关键手法：把 PATH 和 PYTHONHOME 全部清空再启动，这样如果 exe 还能跑起来，
就证明它真的自包含 —— 而不是因为偷偷借用了我们这台机器的 Python。

用法：python analysis/verify_exe.py
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

DIST = r"E:\shimejee-remake\dist\Shimeji"
EXE = os.path.join(DIST, "Shimeji.exe")
DATA = os.path.join(DIST, "data")

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid: int) -> list[dict]:
    out: list[dict] = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            out.append({
                "hwnd": hwnd,
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "title": cls.value,
                "rect": (r.left, r.top, r.right, r.bottom),
                "appwindow": bool(ex & 0x40000),
                "toolwindow": bool(ex & 0x80),
                "cloaked": bool(user32.IsWindowVisible(hwnd) == 0),
            })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def main() -> int:
    if not os.path.exists(EXE):
        print("[FAIL] exe 不存在 / exe missing:", EXE, flush=True)
        return 1

    before_log = 0
    log = os.path.join(DATA, "shimeji.log")
    if os.path.exists(log):
        before_log = os.path.getsize(log)

    # ---- 故意切断环境，证明自包含 ----
    env = {k: v for k, v in os.environ.items()
           if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                            "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "SYSTEMDRIVE")}
    env["PATH"] = r"C:\Windows\System32"          # 只留系统目录，任何 Python 都在不了
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    print("=" * 62, flush=True)
    print("启动 exe，环境已清空 PATH/PYTHONHOME", flush=True)
    print("  PATH =", env["PATH"], flush=True)
    print("=" * 62, flush=True)

    proc = subprocess.Popen([EXE], env=env, cwd=DIST)
    print(f"[pid] {proc.pid}", flush=True)

    time.sleep(9.0)   # 给 Qt 初始化 + 召唤留时间

    if proc.poll() is not None:
        print(f"[FAIL] exe 已退出，returncode={proc.returncode}", flush=True)
        for name in ("startup_error.log", "shimeji.log"):
            p = os.path.join(DATA, name)
            if os.path.exists(p):
                print(f"\n--- {name} (tail) ---", flush=True)
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    print("\n".join(f.readlines()[-30:]), flush=True)
        return 2

    wins = windows_of(proc.pid)
    visible = [w for w in wins if w["visible"]]
    print(f"\n[窗口] 可见 {len(visible)} / 共 {len(wins)}", flush=True)
    for w in visible[:8]:
        print(f"   appwindow={w['appwindow']} tool={w['toolwindow']} "
              f"rect={w['rect']} class={w['title']}", flush=True)

    fg = user32.GetForegroundWindow()
    fgp = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg, ctypes.byref(fgp))
    stole = (fgp.value == proc.pid)
    print(f"\n[焦点] 被 exe 抢走 = {stole}", flush=True)

    print(f"\n[数据目录] {DATA}", flush=True)
    if os.path.isdir(DATA):
        for f in sorted(os.listdir(DATA)):
            print(f"   {f}  {os.path.getsize(os.path.join(DATA, f))} B", flush=True)
    else:
        print("   [WARN] exe 没能在自己旁边建出 data/ —— frozen 路径可能有问题",
              flush=True)

    if os.path.exists(log):
        grew = os.path.getsize(log) - before_log
        print(f"   shimeji.log 增长 {grew} B", flush=True)

    # ---- 收尾：正常退出，别留残余进程 ----
    print("\n[cleanup] 发送退出信号", flush=True)
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True)
    time.sleep(0.6)

    ok = len(visible) >= 1
    print(f"\n结论 / verdict: {'PASS 可脱离 Python 运行' if ok else 'FAIL 没有窗口'}", flush=True)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
