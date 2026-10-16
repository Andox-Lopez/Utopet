# -*- coding: utf-8 -*-
"""验证 1.0.11 的飞扑回避：宠物真的飞向**更近的那侧**屏幕边缘。

要证的三件事：
  1. `escape_direction(x, y, left, right)` 挑的是**更近的边**，不是回避区中心。
  2. `_params["destX"]` 能**覆盖**原版 `走る` 的随机目的地 —— 这是「飞扑」能
     成立的前提；覆盖不了的话宠物只是随机走。
  3. **不再每帧重置动作** —— 1.0.10 的「原地踏步 + 反复转向」就是这么来的。
  4. 默认关闭，且老配置（avoid_input=True）也不会被误判为「默认关」。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from shimeji.engine.avoid import AvoidZones
from shimeji.engine.manager import Manager, BEHAVIOR_RUN_AWAY
from shimeji.engine.environment import Pt
from shimeji.settings import Settings, DEFAULTS

FAILS = []
PASSES = 0


def check(cond, msg, detail=""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(t):
    print("\n--- %s ---" % t, flush=True)


# ══════════════════════════════════════════════════════════════════
section("1. escape_direction 挑更近的屏幕边")

z = AvoidZones()
z.set_clock(lambda: 1000)
z.feed_keyboard(True)
z.update()
L, T, R, B = z.rects[0]
print("  回避区 = (%d,%d)-(%d,%d)" % (L, T, R, B))

SCREEN_L, SCREEN_R = 0, 1920
_MID = (SCREEN_L + SCREEN_R) // 2
# ⭐ 语义是「飞扑到**离自己更近**的那条屏幕边」，不是「更远的那条」。
# 屏幕右侧的宠物（离右边近）→ 往右；左侧的 → 往左。写反了会以为代码有 bug，
# 其实是我把需求读反了（第一版测试就是这么错的）。
cases = [
    (100, -1, "屏幕最左（离左边 100 vs 右边 1820）→ 往左"),
    (400, -1, "偏左 400（离左 400 vs 右 1520）→ 往左"),
    # 距离相等时实现取 `<=` 所以往左。
    (_MID, -1, "屏幕正中 %d → 往左（距离相等时取左）" % _MID),
    (1500, 1, "偏右 1500（离左 1500 vs 右 420）→ 往右"),
    (1900, 1, "屏幕最右（离右 20 vs 左 1900）→ 往右"),
]
for x, want, why in cases:
    got = z.escape_direction(x, (T + B) // 2, SCREEN_L, SCREEN_R)
    check(got == want, "x=%-5d → %s" % (x, "右" if want > 0 else "左"), why)

# ⭐ 关键回归：方向**只由「离左右屏幕边多远」决定，与回避区在哪无关**。
# 判据换成与光标位置无关的固定点 —— 上一版用回避区中点，而回避区跟着光标
# 移动，有时落在屏幕左半边，断言就时对时错（flaky）。
# The direction depends ONLY on the distance to the screen edges, not on where
# the zone happens to be.  Use fixed points: the previous version used the
# zone's centre, which follows the cursor and made the assertion flaky.
for _x, _want, _why in ((200, -1, "屏幕左侧 → 往左"),
                        (1700, 1, "屏幕右侧 → 往右")):
    _g = z.escape_direction(_x, 500, SCREEN_L, SCREEN_R)
    check(_g == _want, "x=%-5d → %s（与回避区位置无关）"
          % (_x, "右" if _want > 0 else "左"), _why)

# 同一个 x，不管回避区挪到哪，答案都一样 —— 这才是「只看屏幕边」
for _zx in ((0, 0, 100, 100), (1700, 400, 1900, 500)):
    z.rects = [_zx]
    _g1 = z.escape_direction(200, 500, SCREEN_L, SCREEN_R)
    _g2 = z.escape_direction(200, 500, SCREEN_L, SCREEN_R)
    check(_g1 == _g2 == -1,
          "回避区在 %s 时 x=200 仍往左（结果稳定）" % (str(_zx[0]),))
z.rects = [(L, T, R, B)]

# 不给屏幕边界时退回旧行为（离回避区中心远的那侧），且**永远不返回 0**
_g_fallback = z.escape_direction(L + 10, (T + B) // 2)
check(_g_fallback in (-1, 1),
      "不给屏幕边界时返回 ±1，不返回 0（0 会让 look_right=False）",
      str(_g_fallback))

# ══════════════════════════════════════════════════════════════════
section("2. destX 参数真的能覆盖原版的随机目的地")

tmp = tempfile.mkdtemp(prefix="avoid_pounce_")
try:
    s = Settings(os.path.join(tmp, "settings.json"))
    s.set("character", "Miku")
    s.set("taskbar_panel", False)
    s.set("initial_count", 1)
    s.set("avoid_input", True)
    mgr = Manager(app, s)
    mgr.timer.stop()
    mgr.dismiss_all()
    wa = mgr.shared_env.work_area
    print("  工作区 = (%d,%d)-(%d,%d)" % (wa.left, wa.top, wa.right, wa.bottom))

    # 宠物在屏幕**右侧** → 离右边更近 → 往**右**飞（用户要的是「近的那边」）
    bx, by = wa.left + int(wa.width * 0.75), wa.top + int(wa.height * 0.5)
    zone = [(bx - 210, by - 80, bx + 210, by + 80)]

    # ⛔ 必须接管 `update`：真实实现每帧都按**光标位置**重算 rects（那是 B 路
    # 的语义），测试里手动摆的区会被立刻覆盖掉，于是宠物根本不在区内。
    # 顺带也说明了一件要紧的事：这个功能按光标判定，所以「宠物往鼠标凑」
    # 天然会撞进回避区 —— 这正是 1.0.10 误触发的根源，也是默认关闭的原因。
    mgr.avoid.update = (lambda typing=False, tick_ms=40:
                        (mgr.avoid.feed_keyboard(True),
                         setattr(mgr.avoid, "typing", True),
                         setattr(mgr.avoid, "rects", list(zone)))[-1])

    pet = mgr.summon(Pt(bx, by))
    # ⚠️ **先断言、再让它跑**：宠物一飞起来位置就变了，事后再看
    # `_avoid_dir` / `_avoid_target_x` 会误判（上一版就是这么 flaky 的）。
    # ⚠️⚠️ 还要**清掉冷却**：1.0.11 加了「一次只飞一次」，上一段留下的触发
    # 会让这里直接 return —— 症状是「宠物没被标记、位移却是 0」。
    # 每次要断言「能触发」之前都必须把冷却归零，否则测的是冷却不是触发。
    mgr._avoid_last_flee = -1e9
    mgr._check_input_avoid()
    check(getattr(pet, "_avoid_in", False), "宠物被标记为「正在飞扑」")
    check(pet._avoid_dir == 1,
          "在屏幕右侧 → 选右边（离它更近）", "dir=%s" % pet._avoid_dir)
    want_x = wa.right - 64
    check(pet._avoid_target_x == want_x,
          "目标 X = 右边内侧 64px（不贴边）",
          "%s 期望 %s" % (pet._avoid_target_x, want_x))
    check(pet.look_right is True, "朝向右")

    # 判据：**起点到终点的净位移**朝目标方向（≥32px 即算「真的飞了」）。
    # 之前用「每帧同向位移」判定，阈值 0.5px 太敏感 —— 宠物飞抵边缘后会被
    # 引擎的落点保护拉回原处（`_rescue_if_offscreen` 一类），那几帧是反向的，
    # 于是「出现过同向位移」反而成了不稳定断言。
    # Use the net displacement; the per-frame test was flaky because the
    # engine pulls the pet back once it reaches the very edge.
    _want_dir = pet._avoid_dir
    x0 = float(pet.anchor.x)
    # 60 帧 = 2.4 秒，足够跑完一段飞扑。原版'走る' 每帧 4px，1200px 要 300 帧；
    # 跑太久会踩到另一个问题：测试里 '永远 typing'，宠物飞到边缘又被同一块区
    # 重新触发，一路飞到对面去（位移正好 -1440/+1440 就是这么来的）。
    # 60 frames = 2.4 s, enough for one leap.  Running longer trips over a
    # different problem: the test keeps 'typing' forever, so a pet that reaches
    # the edge gets re-triggered by the same zone and crosses to the far side.
    for _ in range(60):
        mgr.tick()
    _d = float(pet.anchor.x) - x0
    check(_d * _want_dir > 32,
          "宠物朝目标方向真的飞过去了（位移 %.0f，方向 %+d）"
          % (_d, _want_dir), "期望同向且 >32px")

    # 再测屏幕左侧 → 离左边更近 → 往左（同样：先断言，后跑）
    _lx = wa.left + int(wa.width * 0.25)
    zone[:] = [(_lx - 210, by - 80, _lx + 210, by + 80)]
    pet2 = mgr.summon(Pt(_lx, by))
    mgr._avoid_last_flee = -1e9   # 清冷却（见上）
    mgr._check_input_avoid()
    check(pet2._avoid_dir == -1,
          "在屏幕左侧 → 选左边（离它更近）", "dir=%s" % pet2._avoid_dir)
    check(pet2._avoid_target_x == wa.left + 64,
          "目标 X = 左边内侧 64px", str(pet2._avoid_target_x))

    # 判据同上一段：净位移朝目标方向且超过阈值。
    # Same measure as above: net displacement along the chosen direction.
    _want_dir = pet2._avoid_dir
    x1 = float(pet2.anchor.x)
    for _ in range(60):   # 同上：60 帧够跑完一段，别跑太久
        mgr.tick()
    _d2 = float(pet2.anchor.x) - x1
    check(_d2 * _want_dir > 32,
          "第二只也朝目标方向飞过去了（位移 %.0f，方向 %+d）"
          % (_d2, _want_dir))

    # ══════════════════════════════════════════════════════════
    section("3. 不再每帧重置动作（1.0.10 那个 bug 的回归防线）")
    zone[:] = [(wa.left, wa.top, wa.right, wa.bottom)]
    pet3 = mgr.summon(Pt((wa.left + wa.right) // 2, by))
    for _ in range(12):
        mgr.tick()
    mgr._check_input_avoid()
    # 连续跑 40 帧，记录 action 指针被换掉了几次
    swaps = 0
    prev = pet3.action
    for _ in range(40):
        mgr._check_input_avoid()
        if pet3.action is not prev:
            swaps += 1
            prev = pet3.action
    check(swaps <= 2,
          "40 帧里动作最多换 1~2 次（不是每帧重置）",
          "换了 %d 次" % swaps)
    check(swaps == 0 or swaps == 1,
          "飞扑期间动作是稳定的", "swaps=%d" % swaps)

    # 朝向也不能反复翻转
    flips = 0
    last_lr = pet3.look_right
    for _ in range(60):
        mgr._check_input_avoid()
        if pet3.look_right != last_lr:
            flips += 1
            last_lr = pet3.look_right
    check(flips <= 1, "飞扑期间朝向不反复翻转", "翻了 %d 次" % flips)

    # ══════════════════════════════════════════════════════════
    section("4. 默认关闭 + 冷却可配")
    check(DEFAULTS.get("avoid_input") is False,
          "avoid_input 默认 False（升级即不会再自己走）",
          str(DEFAULTS.get("avoid_input")))
    check(DEFAULTS.get("avoid_flee_cooldown_sec") == 30,
          "飞扑冷却默认 30 秒",
          str(DEFAULTS.get("avoid_flee_cooldown_sec")))
    check(abs(mgr._flee_cooldown_sec() - 30.0) < 0.01,
          "Manager 读到 30 秒", str(mgr._flee_cooldown_sec()))
    # ⭐ 改设置后**不用重启**就该生效（每帧读设置，不能缓存在 __init__）
    s.set("avoid_flee_cooldown_sec", 5)
    check(abs(mgr._flee_cooldown_sec() - 5.0) < 0.01,
          "改了设置立刻生效（每帧读，不缓存在 __init__）",
          str(mgr._flee_cooldown_sec()))
    s.set("avoid_flee_cooldown_sec", 30)

    # ══════════════════════════════════════════════════════════
    section("5. 所有宠物都飞到边缘（不是只挑一只）")
    zone[:] = [(wa.left, wa.top, wa.right, wa.bottom)]
    pets = []
    for i in range(3):
        p = mgr.summon(Pt(wa.left + 300 + i * 200, wa.top + 400))
        if p is not None:
            pets.append(p)
    check(len(pets) == 3, "召唤了 3 只宠物", str(len(pets)))
    # 先接管 update、再触发、**立刻**断言（宠物一动位置就变了）
    mgr.avoid.update = (lambda typing=False, tick_ms=40:
                        (mgr.avoid.feed_keyboard(True),
                         setattr(mgr.avoid, "typing", True),
                         setattr(mgr.avoid, "rects",
                                 [(wa.left, wa.top, wa.right, wa.bottom)]))[-1])
    mgr._avoid_last_flee = -1e9   # 清冷却（见第 2 节的说明）
    mgr._check_input_avoid()
    fled = [p for p in pets if getattr(p, "_avoid_in", False)]
    check(len(fled) == 3,
          "三只宠物**全部**被触发飞扑（用户要的是都收进边缘）",
          "%d/3" % len(fled))
    for i, p in enumerate(pets):
        want = (wa.left + 64 if abs(p.anchor.x - wa.left)
                <= abs(wa.right - p.anchor.x) else wa.right - 64)
        check(p._avoid_target_x == want,
              "第 %d 只目标 X = **离它更近**那侧的边缘内侧" % (i + 1),
              "%s 期望 %s (x=%.0f)" % (p._avoid_target_x, want, p.anchor.x))

    # ══════════════════════════════════════════════════════════
    section("6. 冷却期内不再飞（防往复踱步）")
    # 先**手动清掉冷却**再放回区里：否则前面的触发还挂着冷却，
    # 「没再触发」就分不清是冷却生效还是压根没判上 —— 那种测试是假绿。
    # Clear the cooldown first, otherwise a leftover cooldown from the previous
    # section would make "not triggered" ambiguous and the test falsely green.
    s.set("avoid_flee_cooldown_sec", 30)
    mgr._avoid_last_flee = -1e9
    p0 = pets[0]
    p0._avoid_in = False
    p0._avoid_dir = 0
    p0._avoid_target_x = None
    mgr.avoid.rects = [(wa.left, wa.top, wa.right, wa.bottom)]
    mgr.avoid.typing = True
    mgr._check_input_avoid()
    check(p0._avoid_in,
          "冷却已清空时同一只宠物能再次触发（先确认这一步有效）",
          "_avoid_in=%s" % p0._avoid_in)

    # 现在把冷却设成很大 → 再放回区里就该**不**触发
    p0._avoid_in = False
    p0._avoid_dir = 0
    p0._avoid_target_x = None
    s.set("avoid_flee_cooldown_sec", 3600)
    mgr._check_input_avoid()
    check(not p0._avoid_in,
          "冷却期内同一只宠物不会被再次触发（避免飞到边又飞回来）",
          "_avoid_in=%s" % p0._avoid_in)

    # 冷却设为 0 → 立刻可以再飞
    s.set("avoid_flee_cooldown_sec", 0)
    mgr._check_input_avoid()
    check(p0._avoid_in,
          "冷却设 0 时立刻可以再飞（用户自己控制）",
          "_avoid_in=%s" % p0._avoid_in)
    s.set("avoid_flee_cooldown_sec", 30)

    mgr.quit()
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 68)
if FAILS:
    print("%d FAILED / %d passed" % (len(FAILS), PASSES))
    for f in FAILS:
        print("  x %s" % f)
    sys.stdout.flush()
    os._exit(1)
print("ALL PASS —— %d 项检查通过" % PASSES)
sys.stdout.flush()
os._exit(0)
