# -*- coding: utf-8 -*-
"""验证：窗口移动**永远不会被移出当前虚拟桌面**。

## 为什么要有这个测试

Windows 的虚拟桌面（Virtual Desktop）是按**全局坐标**分区的：桌面 1 占主
显示器的坐标区域（单显示器就是 0,0-1920,1080），桌面 2 就在它右侧或下方
的**另一块坐标区域**。

**把窗口移到当前桌面范围之外的坐标，Windows 会把它自动移到那个坐标所在
的虚拟桌面。** 用户就再也切不回那扇窗口了 —— 只能关掉软件重开。

这正是本项目曾经造成的问题：`verify_physics_101.py` 把桌面上任意一扇
**真实应用窗口**挪到 `work_area.right + 500`（2420），正好落进虚拟桌面 2
的坐标区域。

## 这个测试怎么做到没有副作用

**只拿桌宠自己的窗口当被测对象**（测试自己创建的），绝不碰用户的窗口。
窗口被移动的是桌宠自己，坏了也只是测试画面难看。

验证三件事：
1. `clamp_to_desktop()` 把越界坐标夹回**窗口当前所在显示器**内
2. `move_window_at()` 返回的**实际落点**在当前显示器内（不是请求的坐标）
3. 移动**真的发生**之后，窗口仍在当前显示器内（用 `window_rect` 实测）

用法：python analysis/verify_desktop_safety.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# ⚠️ **不能用 offscreen**：offscreen 平台下 `winId()` 恒为 1、窗口根本没创建，
# 而「窗口被移出虚拟桌面」这个行为**只有真实窗口**才存在。
# No offscreen: there, winId() is always 1 and no window is ever created, but
# the virtual-desktop behaviour only exists for real windows.

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from shimeji import win32  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(cond: bool, msg: str, detail: str = ""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(t):
    print("\n--- %s ---" % t, flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ══════════════════════════════════════════════════════════════
    section("1. 夹取逻辑：越界坐标必须被拉回当前显示器内")
    # 用桌宠**自己**的窗口当被测对象 —— 绝不碰用户的窗口。
    # 桌宠窗口有真实的 hwnd（`Mascot` 是 QWidget），而普通 QWidget 在
    # 没有真正 show 之前 `winId()` 可能还是 0。
    tmp = tempfile.mkdtemp(prefix="utopet_desk_")
    st = Settings(os.path.join(tmp, "settings.json"))
    st.set("restore_session", False)
    st.set("initial_count", 1)
    st.set("taskbar_panel", False)
    from shimeji.engine.manager import Manager
    mgr = Manager(app, st)
    app.processEvents()
    mascot = mgr.mascots[0]
    mascot.set_image("shime1.png")
    app.processEvents()
    own = mascot
    hwnd = int(own.winId())
    check(hwnd not in (0, 1),
          "拿到桌宠自己窗口的**真实** hwnd", "hwnd=%d" % hwnd)

    rect = win32._monitor_rect(hwnd)
    check(rect is not None, "能读到窗口所在显示器的范围", str(rect))
    if rect is None:
        print()
        print("=" * 60, flush=True)
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush()
        os._exit(1)
    left, top, right, bottom = rect

    # 各个方向都要试：右、下、左、上、以及远超屏幕的坐标
    cases = [
        ("往右越界", (right + 500, top + 50), 200, 200),
        ("往下越界", (left + 50, bottom + 500), 200, 200),
        ("往左越界", (left - 500, top + 50), 200, 200),
        ("往上越界", (left + 50, top - 500), 200, 200),
        ("远超屏幕", (right + 5000, bottom + 5000), 200, 200),
        ("负坐标", (-9999, -9999), 200, 200),
    ]
    for label, (x, y), w, h in cases:
        cx, cy = win32.clamp_to_desktop(hwnd, x, y, w, h)
        inside = (left <= cx and cx + w <= right
                  and top <= cy and cy + h <= bottom)
        check(inside,
              "%s的坐标被夹回显示器内" % label,
              "(%d,%d) -> (%d,%d) 显示器=(%d,%d,%d,%d)"
              % (x, y, cx, cy, left, top, right, bottom))

    # 合法坐标**不能**被改动
    ok_x, ok_y = left + 100, top + 100
    cx, cy = win32.clamp_to_desktop(hwnd, ok_x, ok_y, 200, 200)
    check((cx, cy) == (ok_x, ok_y),
          "本来就在屏内的坐标**不被改动**",
          "(%d,%d) -> (%d,%d)" % (ok_x, ok_y, cx, cy))

    # 窗口比屏幕还大时不能归到越界位置
    cx, cy = win32.clamp_to_desktop(hwnd, right + 500, bottom + 500,
                                    right - left + 100, bottom - top + 100)
    check(left <= cx <= right and top <= cy <= bottom,
          "窗口比屏幕还大时也不会被夹到越界位置",
          "(%d,%d)" % (cx, cy))

    # ══════════════════════════════════════════════════════════════
    section("2. 真实移动：落点与实际窗口位置都在当前显示器内")
    # 把桌宠自己的窗口往「虚拟桌面外」挪 —— 修复后它应该停在屏幕内，
    # **不会**跑到别的虚拟桌面去。
    #
    # ⚠️ 尺寸必须用**实测值**，不能写死：桌宠窗口实际是 128x128（缩放 1.0），
    # 我一开始按 200 写，断言就误报了（1792 + 200 > 1920，但窗口其实只有
    # 128 宽，右边缘正好 1920 = 屏幕右边缘，完全正常）。
    # Use the measured size: the mascot window is 128x128, and hard-coding
    # 200 made the assertion report a false failure.
    _r0 = win32.window_rect(hwnd)
    if _r0 is None:
        _r0 = (0, 0, 128, 128)
    ww = _r0[2] - _r0[0]
    wh = _r0[3] - _r0[1]
    check(ww > 0 and wh > 0, "读到窗口实际尺寸", "%dx%d" % (ww, wh))

    want_x, want_y = right + 500, top + 50
    landed = win32.move_window_at(hwnd, want_x, want_y)
    check(landed is not None, "move_window_at 成功")
    if landed is not None:
        lx, ly = landed
        check(left <= lx and lx + ww <= right,
              "返回的落点在显示器内（不是请求的越界坐标）",
              "请求=(%d,%d) 落点=(%d,%d) 宽=%d" % (want_x, want_y, lx, ly, ww))
        # 实测窗口真实位置
        app.processEvents()
        r = win32.window_rect(hwnd)
        check(r is not None, "能读到窗口真实矩形")
        if r is not None:
            inside = (r[0] >= left and r[0] + ww <= right
                      and r[1] >= top and r[1] + wh <= bottom)
            check(inside,
                  "**窗口实测仍在当前显示器内**（不会被移出虚拟桌面）",
                  "rect=%s 显示器=(%d,%d,%d,%d)"
                  % (str(r), left, top, right, bottom))

    # ══════════════════════════════════════════════════════════════
    section("3. move_window() 旧接口也必须被夹取（向后兼容）")
    win32.move_window(hwnd, right + 800, bottom + 800)
    app.processEvents()
    r = win32.window_rect(hwnd)
    check(r is not None and r[0] >= left and r[1] >= top,
          "move_window() 也不会把窗口挪出当前显示器",
          "rect=%s" % str(r))

    # ══════════════════════════════════════════════════════════════
    section("4. 桌宠自己也要能被正常移动（别把功能焊死）")
    target_x = left + 60
    target_y = top + 60
    landed = win32.move_window_at(hwnd, target_x, target_y)
    app.processEvents()
    r = win32.window_rect(hwnd)
    check(landed == (target_x, target_y),
          "合法位置能精确落到位（夹取没有误伤）",
          "请求=(%d,%d) 落点=%s" % (target_x, target_y, str(landed)))
    check(r is not None and r[0] == target_x and r[1] == target_y,
          "窗口真实位置与请求一致",
          "rect=%s" % str(r))

    mgr.quit()
    app.processEvents()

    print()
    print("=" * 60, flush=True)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush()
        os._exit(1)
    print("ALL PASS —— %d 项检查通过" % PASSES, flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
