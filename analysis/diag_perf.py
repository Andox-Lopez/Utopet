# -*- coding: utf-8 -*-
"""实测每帧开销：找出真正的热点。

用法：python analysis/diag_perf.py
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Area, Environment  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

env = Environment()
env.refresh(force=True)
print("真实窗口数：%d\n" % len(env.windows), flush=True)


def bench(label, fn, n=200):
    fn()  # 预热
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    dt = (time.perf_counter() - t0) / n * 1000
    print("  %-34s %7.3f ms" % (label, dt), flush=True)
    return dt


print("=== 单项耗时（真实桌面）===", flush=True)
bench("win32.list_windows()", lambda: env._enumerate())
bench("  └ 其中 recompute_occlusion()", lambda: env.recompute_occlusion())
bench("win32.get_cursor_pos()", lambda: env.cursor.set(*__import__("shimeji.win32", fromlist=["x"]).get_cursor_pos()))

# 造一批假窗口，测遮挡判定随窗口数增长的曲线
print("\n=== 遮挡判定随窗口数增长（假窗口）===", flush=True)
saved = list(env.windows)
saved_map = dict(env._window_map)
for count in (5, 10, 20, 40, 80):
    env.windows = []
    env._window_map = {}
    for i in range(count):
        # 随机散布、大小不一，制造「部分重叠」的典型形态
        l = 50 + (i * 37) % 1600
        t = 30 + (i * 53) % 900
        a = Area(l, t, l + 500, t + 400, True, hwnd=900000 + i)
        env.windows.append(a)
        env._window_map[a.hwnd] = a
    dt = bench("  %2d 扇窗口" % count, lambda: env.recompute_occlusion(), n=100)
env.windows = saved
env._window_map = saved_map

print("\n=== 每帧预算参考 ===", flush=True)
print("  帧间隔 40ms；一帧里 N 只宠物各自还要算 floor/ceiling/wall", flush=True)
print("  30 只宠物 × 每只查一次 _candidates()（O(n) 遍历 + is_occluded 查询）", flush=True)
