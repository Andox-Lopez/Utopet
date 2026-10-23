# -*- coding: utf-8 -*-
"""验证窗口可交互判定（1.1.3）+ 爬墙镜像朝向（1.1.2）。

## 一、可交互判定：**未被完全遮盖**的窗口都可以接收交互

1. **任意未被完全遮盖的窗口都能接收交互**；只有被**完全**遮盖的才禁止。
   选哪一扇由「光标位置 + Z 序」决定（`EnumWindows` 自上而下枚举，第一个
   包含光标点的就是最上层那扇）。
   1.1.1 一度改成「只跟前台窗口互动」，1.1.2 又把可站立面也收窄到前台那
   一个 —— 范围太窄了：用户想让宠物爬哪一扇，应该由他把鼠标放到哪一扇决定。
2. **虚空行走**：`floor` / `ceiling` / `wall` 的候选里**不能有被完全遮盖的
   窗口** —— 用户看不见它，宠物在上面走就是浮在半空。
3. **互动过程中**：目标被完全遮盖就当帧放手（拖一扇看不见的窗口没意义）。

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

    def set_windows(rects, cursor=None):
        """
        装一批假窗口。

        **列表顺序 = Z 序（顶层在前）**，这跟 `EnumWindows` 的行为一致，
        遮挡判定就靠这个顺序。
        The list order is the Z order (topmost first), matching EnumWindows.
        """
        env.windows = []
        env._window_map = {}
        for i, r in enumerate(rects):
            a = Area(*r, hwnd=770000 + i)
            env.windows.append(a)
            env._window_map[a.hwnd] = a
            env._titles[a.hwnd] = "Fake-%d" % i
        env._enumerate = lambda *a, **k: None
        env.recompute_occlusion()
        if cursor is not None:
            env.cursor.set(cursor[0], cursor[1])
        env._update_active_ie()

    try:
        # ⚠️ 1.1.3 的新接口不存在时要**报失败**而不是崩掉 —— 崩掉的话
        # 后面的断言根本没跑，就看不出哪些还有鉴别力。
        # Report the missing API as a failure instead of crashing: a crash
        # means the remaining assertions never run and we cannot tell
        # whether they still have any teeth.
        _missing = [n for n in ("recompute_occlusion", "is_occluded",
                                "interactive_window")
                    if not hasattr(env, n)]
        if _missing:
            check(False, "Environment 提供 1.1.3 的遮挡判定接口",
                  "缺少 %s" % _missing)
            say_footer = "=" * 56
            print("FAIL: 1.1.3 的接口不存在，后续检查无法进行", flush=True)
            return 1

        # ==============================================================
        section("1. 未被完全遮盖的窗口都可以接收交互")
        # 两扇互不重叠的窗口：光标在谁身上就跟谁互动
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)],
                     cursor=(600, 500))
        check(env.active_ie.visible and env.active_ie.hwnd == 770000,
              "光标在 0 号窗口里 -> activeIE 是它", "hwnd=%s" % env.active_ie.hwnd)
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)],
                     cursor=(1200, 500))
        check(env.active_ie.hwnd == 770001,
              "光标移到 1 号窗口 -> activeIE 切过去（两扇都能接收交互）",
              "hwnd=%s" % env.active_ie.hwnd)
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)],
                     cursor=(1700, 900))
        check(not env.active_ie.visible,
              "光标不在任何窗口上 -> 没有 activeIE")

        # ==============================================================
        section("2. 遮挡判定：完全被盖住的窗口不参与交互")
        # 0 号在上层，1 号在下层且被完全盖住
        set_windows([(300, 400, 900, 800), (400, 500, 800, 700)],
                     cursor=(600, 600))
        check(not env.is_occluded(770000),
              "上层窗口没有被遮盖")
        check(env.is_occluded(770001),
              "下层窗口被上层完全盖住 -> 判定为遮盖")
        check(env.interactive_window(770001) is None,
              "被完全遮盖的窗口不是可交互对象")
        check(env.interactive_window(770000) is not None,
              "未被遮盖的窗口仍然是可交互对象")

        # 露出半扇 -> 不算完全遮盖
        set_windows([(300, 400, 900, 800), (850, 500, 1500, 700)],
                     cursor=(600, 600))
        check(not env.is_occluded(770001),
              "只露出一条边的窗口不算被完全遮盖")
        check(env.interactive_window(770001) is not None,
              "露出半扇的窗口仍是可交互对象")

        # ==============================================================
        section("3. 虚空行走：被完全遮盖的窗口不能当地面")
        set_windows([(300, 400, 900, 800), (400, 500, 800, 700)],
                     cursor=(600, 600))
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(600, 500)   # 下层窗口的顶边
        mascot.reposition()
        fl = mascot.env.floor
        fl_hwnd = getattr(getattr(fl, "area", None), "hwnd", None)
        check(fl_hwnd != 770001,
              "被完全遮盖的窗口不能当地面（宠物不会在看不见的边上走）",
              "floor=%s hwnd=%s" % (type(fl).__name__, fl_hwnd))

        # 未被遮盖的窗口仍然可以当地面
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)],
                     cursor=(600, 600))
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(600, 400)
        mascot.reposition()
        fl2 = mascot.env.floor
        check(fl2 is not NOT_ON_BORDER and getattr(fl2, "area", None) is not None
              and fl2.y == 400,
              "未被遮盖的窗口顶边仍然可以当地面",
              "floor=%s y=%s" % (type(fl2).__name__, getattr(fl2, "y", None)))

        # ==============================================================
        section("3b. 互动过程中：目标被完全遮盖就放手")
        set_windows([(300, 400, 900, 800), (1000, 400, 1500, 800)],
                     cursor=(600, 600))
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(600, 400)
        mascot.look_right = True
        mascot.reposition()
        act = create_action(mascot, "IEを持って歩く", {}, None)
        check(act is not None, "创建「IEを持って歩く」动作")
        locked = getattr(act, "_ie_hwnd", None)
        check(locked == 770000, "锁定的是 0 号窗口", "hwnd=%s" % locked)

        # 把它完全盖住 -> 当帧放手。
        # ⚠️ 被盖住的必须**就是动作锁定的那一扇**（770000），所以它要放到
        # **下层**，上面再盖一扇更大的。我一开始把顺序搞反了（把锁定的那扇
        # 放到了上层），结果它根本没被遮盖 —— 不放手才是对的。
        # The covered window must be the locked one (770000), so it goes in
        # the *lower* layer with a bigger window on top.
        # ⚠️ 三处都踩过坑，这里一次说清：
        #  1. **被盖住的那一扇必须是动作锁定的那一扇**（770000），所以它要
        #     放在**下层**（列表靠后 = Z 序靠后）。
        #  2. 上层必须**完全包含**下层（四条边都包住），否则下层还露出底边。
        #  3. 上面那扇不能太大：铺满工作区 80% 以上的会被判成「全屏窗口」，
        #     而全屏窗口**不作为遮挡者**（explorer 桌面那种伪窗口会盖住一切）。
        # The covered window must be the locked one, so it goes in the lower
        # layer; the upper one must contain it on all four sides and must not
        # be work-area-filling (those are not occluders).
        set_windows([(300, 300, 1000, 900), (300, 400, 900, 800)],
                     cursor=(600, 600))
        _locked_under = 770001          # 列表索引 1 = 下层 = 被盖住的那扇
        act._ie_hwnd = _locked_under
        check(env.is_occluded(_locked_under),
              "构造场景：目标被上层大窗完全盖住")
        act.tick()
        check(getattr(act, "_ie_hwnd", None) is None,
              "目标被完全遮盖后立刻放手（不再拖看不见的窗口）",
              "hwnd=%s" % getattr(act, "_ie_hwnd", None))

        # ==============================================================
        section("3c. 多窗口层叠时的判定一致性")
        # 三扇窗口层层压：0 在最上，1 在中间，2 在最下
        set_windows([(200, 200, 800, 600),      # 0：上层
                     (250, 250, 750, 550),      # 1：中间，被 0 完全盖住
                     (300, 300, 700, 500)],     # 2：最下，被 0 和 1 完全盖住
                     cursor=(400, 300))
        check(not env.is_occluded(770000),
              "最上层窗口未被遮盖")
        check(env.is_occluded(770001),
              "中间那层被最上层完全盖住")
        check(env.is_occluded(770002),
              "最下那层也被完全盖住")
        check(env.active_ie.hwnd == 770000,
              "光标在层叠处 -> 命中最上面那扇（Z 序最靠前）",
              "hwnd=%s" % env.active_ie.hwnd)

        # 把最上层挪开 -> 中间那层露出来 -> 变成可交互
        set_windows([(250, 250, 750, 550),      # 0：现在是最上层（原先那扇中间窗）
                     (300, 300, 700, 500)],     # 1：下面那扇
                     cursor=(400, 300))
        check(not env.is_occluded(770000),
              "挪开后原先那扇变成最上层 -> 不再被遮盖")
        check(env.is_occluded(770001),
              "下面那扇仍然被盖住")
        check(env.active_ie.hwnd == 770000,
              "activeIE 跟着切到新的最上层",
              "hwnd=%s" % env.active_ie.hwnd)

        # ==============================================================
        section("4. 爬墙镜像：屏幕边缘")
        # 爬工作区**左**墙：贴图必须朝左（look_right=False）
        # ⚠️ 同上：先停动作、不要 processEvents()。
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(wa.left, wa.bottom - 200)
        mascot.look_right = True          # 故意设成「错的方向」
        mascot.reposition()
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
        # ⚠️ 要先停掉上一个动作，并且**不要** processEvents()：Manager 的
        # timer 会在事件循环里继续 tick，把还在跑的爬行动作推进几帧，锚点
        # 就被推离右墙（`Wall.isOn` 的横向容差只有 2px）-> 偶发失败。
        # 症状是「单独跑 8 次全过、放进回归序列就挂」。
        # Stop the previous action and do NOT pump the event loop: the
        # manager's timer advances the running climb and pushes the anchor
        # off the wall (the tolerance is only 2px).
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(wa.right, wa.bottom - 200)
        mascot.look_right = False         # 故意设成「错的方向」
        mascot.reposition()
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
        env._enumerate = lambda *a, **k: None
        # ⚠️ 要重算遮挡：`wall_at()` / `_candidates()` 都会查它，
        # 不重算的话用的是上一轮的遮挡集合。
        env.recompute_occlusion()
        env.cursor.set(fake.left + 10, fake.top + 10)
        env._update_active_ie()
        check(env.active_ie.visible, "光标下的窗口可见")

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
        # ⚠️ 要把锚点**放回**左边缘：上一节爬窗时宠物移动过，位置已经漂了。
        # Put the anchor back on the edge: the climb above moved it.
        mascot.action = None
        mascot.anchor = type(mascot.anchor)(fake.left, fake.top + 100)
        mascot.reposition()
        seen = []
        for lr in (True, False):
            mascot.look_right = lr
            seen.append(getattr(mascot.env.wall_at(), "x", None))
        check(len(set(seen)) == 1 and seen[0] == fake.left,
              "朝向变化不影响「实际贴着哪条墙」的判定",
              f"x={seen} anchor=({mascot.anchor.x:.0f},{mascot.anchor.y:.0f}) "
              f"fake=({fake.left},{fake.top},{fake.right},{fake.bottom}) "
              f"cand={[(a.left,a.right) for a in mascot.env._candidates()]} "
              f"occl={sorted(env._occluded)}")

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
