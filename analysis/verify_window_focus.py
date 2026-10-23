# -*- coding: utf-8 -*-
"""验证 1.1.2 的两个修复：窗口焦点 + 爬墙镜像朝向。

## 一、窗口焦点（1.1.1 遗留的交互缺陷）

1. **窗口互动结束后回到地面行走**，而不是「凭空行走」（悬空位移）。
   根因：`_candidates()` 以前把**所有**窗口都当作可站立面，宠物站在窗口 A
   顶边时前台切到 B，A 退到背景，它却仍以 A 的边为「地面」继续走。
2. **互动过程中只认前台窗口**，不得与非前台窗口交互。
   根因：`_IEFollowMixin` 在 init 时锁定 hwnd 后再也不校验前台身份。

## 二、爬墙镜像朝向

3. **爬墙时贴图方向由「实际贴住哪条墙」决定**，而不是沿用爬之前的朝向。
   根因：爬墙动作 `壁を登る` 只有 `目的地Y`、没有 `目的地X`，runtime 里
   「面朝目的地」那一步根本不执行，朝向一路沿用旧值 -> 爬左墙却朝右爬。
4. **屏幕边缘与窗口边缘的朝向规则相反**（几何关系不同），两者都要覆盖：
   - 工作区（屏幕）边缘：朝右贴**右墙**（边在宠物外侧）
   - 窗口边缘：朝右贴**窗口左边**（边在宠物内侧）

用法：python analysis/verify_window_focus.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Area, NOT_ON_BORDER  # noqa: E402
from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.engine.runtime import create_action  # noqa: E402
from shimeji.settings import Settings  # noqa: E402
from shimeji.xml.expr import Val  # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(cond: bool, msg: str, detail: str = ""):
    global PASSES
    line = ("  [ok]   " if cond else "  [FAIL] ") + msg
    if detail:
        line += f"  ({detail})"
    print(line, flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(title: str):
    print(f"\n--- {title} ---", flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tmp = tempfile.mkdtemp(prefix="utopet_focus_")
    s = Settings(os.path.join(tmp, "settings.json"))
    s.set("restore_session", False)
    s.set("initial_count", 1)
    s.set("taskbar_panel", False)
    m = Manager(app, s)
    app.processEvents()

    env = m.shared_env
    mascot = m.mascots[0]
    mascot.set_image("shime1.png")
    app.processEvents()
    wa = env.work_area

    saved_w = list(env.windows)
    saved_m = dict(env._window_map)
    saved_fg = env.__dict__.get("_foreground_hwnd")
    saved_enum = env._enumerate

    def set_windows(rects, fg_index=0):
        """装一批假窗口并指定前台。"""
        env.windows = []
        env._window_map = {}
        for i, r in enumerate(rects):
            a = Area(*r, hwnd=770000 + i)
            env.windows.append(a)
            env._window_map[a.hwnd] = a
            env._titles[a.hwnd] = "Fake-%d" % i
        env._foreground_hwnd = lambda: (770000 + fg_index) if fg_index is not None else 0
        env._enumerate = lambda *a, **k: None
        env._update_active_ie()

    try:
        # ==============================================================
        section("1. 前台切走后，脚下那条边消失（不再凭空行走）")
        # 两扇顶边同高的窗口，前台在 0 号
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)], fg_index=0)
        check(env.active_ie.visible and env.active_ie.hwnd == 770000,
              "初始前台 = 0 号窗口")
        mascot.anchor = type(mascot.anchor)(600, 400)
        mascot.reposition()
        app.processEvents()
        fl = mascot.env.floor
        check(fl is not NOT_ON_BORDER and abs(fl.y - 400) <= 2,
              "站在 0 号窗口顶边时，脚下是它的边", f"floor.y={getattr(fl, 'y', None)}")

        # 切到 1 号窗口
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)], fg_index=1)
        check(env.active_ie.hwnd == 770001, "前台已切到 1 号窗口")
        fl2 = mascot.env.floor
        check(fl2 is NOT_ON_BORDER,
              "切走后脚下那条边消失（= 会触发下落，不会悬空行走）",
              f"floor={type(fl2).__name__}")
        check(not env.active_ie.topBorder.isOn(mascot.anchor),
              "1 号窗口的顶边也不在宠物脚下（顶边高度相同但不是同一扇窗）")

        # ==============================================================
        section("2. 窗口被关掉后同样失去脚下那条边")
        set_windows([(300, 400, 900, 800)], fg_index=0)
        mascot.anchor = type(mascot.anchor)(600, 400)
        mascot.reposition()
        app.processEvents()
        check(mascot.env.floor is not NOT_ON_BORDER, "窗口还在时脚下有边")
        set_windows([], fg_index=None)
        check(mascot.env.floor is NOT_ON_BORDER,
              "窗口关掉后脚下没有边（宠物会掉回地面）")

        # ==============================================================
        section("3. 互动过程中：目标失去前台身份就立刻放手")
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)], fg_index=0)
        mascot.anchor = type(mascot.anchor)(600, 400)
        mascot.look_right = True
        mascot.reposition()
        app.processEvents()
        act = create_action(mascot, "IEを持って歩く", {}, None)
        check(act is not None, "创建「IEを持って歩く」动作")
        locked = getattr(act, "_ie_hwnd", None)
        check(locked == 770000, "锁定的前台窗口是 0 号", f"hwnd={locked}")

        # 前台切走
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)], fg_index=1)
        act.tick()
        app.processEvents()
        check(getattr(act, "_ie_hwnd", None) is None,
              "目标失去前台身份后立刻放手（不再拖后台窗口）",
              f"hwnd={getattr(act, '_ie_hwnd', None)}")

        # ==============================================================
        section("4. 爬墙镜像：屏幕边缘")
        # 爬工作区**左**墙：贴图必须朝左（look_right=False）
        mascot.anchor = type(mascot.anchor)(wa.left, wa.bottom - 200)
        mascot.look_right = True          # 故意设成「错的方向」
        mascot.reposition()
        app.processEvents()
        climb = create_action(mascot, "壁を登る",
                              {"destY": Val(str(wa.bottom - 64))}, None)
        check(climb is not None, "创建「壁を登る」动作（爬工作区左墙）")
        if climb is not None:
            check(getattr(climb, "dest_x", "x") is None,
                  "爬墙动作没有目的地X（所以朝向不能靠目的地推导）",
                  f"dest_x={getattr(climb, 'dest_x', 'x')}")
            for _ in range(5):
                climb.tick()
                mascot.reposition()
            check(mascot.look_right is False,
                  "爬左墙时贴图朝左（不管爬之前朝哪边）",
                  f"look_right={mascot.look_right}")
            check(climb.border is not NOT_ON_BORDER
                  and climb.border.isOn(mascot.anchor),
                  "爬墙动作取到的 border 正是宠物贴着的那条墙",
                  f"border.x={getattr(climb.border, 'x', None)}")

        # 爬工作区**右**墙：贴图必须朝右
        mascot.anchor = type(mascot.anchor)(wa.right, wa.bottom - 200)
        mascot.look_right = False         # 故意设成「错的方向」
        mascot.reposition()
        app.processEvents()
        climb2 = create_action(mascot, "壁を登る",
                               {"destY": Val(str(wa.bottom - 64))}, None)
        if climb2 is not None:
            for _ in range(5):
                climb2.tick()
                mascot.reposition()
            check(mascot.look_right is True,
                  "爬右墙时贴图朝右",
                  f"look_right={mascot.look_right}")

        # ==============================================================
        section("5. 爬墙镜像：窗口边缘（规则与屏幕边缘相反）")
        if not hasattr(mascot.env, "wall_at"):
            check(False, "MascotEnvironment.wall_at 存在（1.1.2 新增）")
            check(False, "MascotEnvironment.facing_for_wall 存在（1.1.2 新增）")
            print("\n" + "=" * 56, flush=True)
            print("FAILED: 1.1.2 的接口不存在，后续检查无法进行", flush=True)
            return 1
        fake = Area(wa.left + 200, wa.top + 300, wa.left + 600, wa.top + 700,
                    True, hwnd=770500)
        env.windows = [fake]
        env._window_map = {770500: fake}
        env._titles[770500] = "Fake-IE"
        env._foreground_hwnd = lambda: 770500
        env._enumerate = lambda *a, **k: None
        env._update_active_ie()
        check(env.active_ie.visible, "前台窗口可见")

        # 贴窗口**左边**：窗口边在宠物内侧，贴图应朝右（面向窗口）
        # ⚠️ 同样不要 processEvents()：会把锚点推离窗口边缘（见下面那处注释）。
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(fake.left, fake.top + 100)
        mascot.look_right = False
        mascot.reposition()
        w = mascot.env.wall_at()
        check(w is not NOT_ON_BORDER, "按位置能找到宠物贴着的那条墙",
              f"wall={type(w).__name__}")
        check(mascot.env.facing_for_wall(w) is True,
              "贴窗口左边 -> 贴图朝右（面向窗口内侧）",
              f"facing={mascot.env.facing_for_wall(w)}")
        climb3 = create_action(mascot, "壁を登る",
                               {"destY": Val(str(fake.top + 64))}, None)
        if climb3 is not None:
            for _ in range(5):
                climb3.tick()
                mascot.reposition()
            check(mascot.look_right is True,
                  "爬窗口左墙时贴图朝右（面向窗口）",
                  f"look_right={mascot.look_right}")
            check(climb3.border.isOn(mascot.anchor),
                  "爬窗口左墙时 border 就是窗口左边",
                  f"border.x={getattr(climb3.border, 'x', None)} window.left={fake.left}")

        # 贴窗口**右边**：贴图应朝左
        # ⚠️ 这里**不要**调 processEvents()：Manager 的 timer 会在事件循环里
        # 继续 tick，把还在跑的爬墙动作推进一帧，锚点就被推离窗口边缘
        # （实测跑到 x=618，超出窗口右边界 600，候选集直接变空）。
        # Do not pump the event loop here: the manager's timer would advance
        # the still-running climb action and push the anchor off the edge.
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(fake.right, fake.top + 100)
        mascot.look_right = True
        mascot.reposition()
        w2 = mascot.env.wall_at()
        check(mascot.env.facing_for_wall(w2) is False,
              "贴窗口右边 -> 贴图朝左",
              f"facing={mascot.env.facing_for_wall(w2)} "
              f"anchor=({mascot.anchor.x:.0f},{mascot.anchor.y:.0f}) "
              f"wall={type(w2).__name__} x={getattr(w2, 'x', None)} "
              f"cand={[(a.left, a.right) for a in mascot.env._candidates()]}")

        # ==============================================================
        section("6. 方向与贴图解耦：朝向不再决定「找哪条墙」")
        # 同一位置、不同朝向，wall_at() 必须给出同一条墙
        mascot.anchor = type(mascot.anchor)(fake.left, fake.top + 100)
        mascot.reposition()
        app.processEvents()
        seen = []
        for lr in (True, False):
            mascot.look_right = lr
            seen.append(getattr(mascot.env.wall_at(), "x", None))
        check(len(set(seen)) == 1 and seen[0] == fake.left,
              "朝向变化不影响「实际贴着哪条墙」的判定",
              f"x={seen}")

    finally:
        env.windows = saved_w
        env._window_map = saved_m
        env._enumerate = saved_enum
        if saved_fg is None:
            env.__dict__.pop("_foreground_hwnd", None)
        else:
            env._foreground_hwnd = saved_fg
        env._update_active_ie()

    m.quit()
    print("\n" + "=" * 56, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)} / {PASSES + len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print(f"ALL PASS —— {PASSES} 项检查通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
