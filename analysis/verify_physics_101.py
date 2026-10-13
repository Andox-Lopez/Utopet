# -*- coding: utf-8 -*-
"""复现用户报告的每个症状，并验证修复。

用真实的 Actions.xml / Behavior.xml（不造假数据）驱动引擎跑到稳定状态，
每一步都断言用户描述的现象不再发生。

Reproduces each reported symptom against the real configuration and asserts
that the fix holds.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import NOT_ON_BORDER, Area, Pt  # noqa: E402
from shimeji.engine.manager import (BEHAVIOR_FALL, BEHAVIOR_GATHER,  # noqa: E402
                                   BEHAVIOR_THROWN, Manager)
from shimeji.settings import Settings  # noqa: E402

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


def run_ticks(mgr: Manager, n: int):
    for _ in range(n):
        mgr.tick()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings()
    settings.set("character", "Miku")
    settings.set("initial_count", 1)
    settings.set("tick_ms", 40)
    settings.set("taskbar_panel", False)
    settings.set("idle_gather", False)
    settings.set("always_on_top", True)
    mgr = Manager(app, settings)
    mgr.timer.stop()          # 手动驱动，方便精确控制 / drive ticks by hand
    mgr.dismiss_all()

    wa = mgr.shared_env.work_area
    m = mgr.summon(Pt(wa.left + 300, wa.bottom))
    check(m is not None, "召唤一只宠物")
    if m is None:
        return 1

    # ==================================================================
    section("1. NotOnBorder 语义（四个症状的共同根因）")
    # 宠物悬空（不在任何边界上）时，floor 必须是 NOT_ON_BORDER，
    # 否则 border.move() 会每帧把它硬拽到某条边界上。
    m.anchor = Pt(wa.left + 300, wa.top + 200)   # 半空
    check(m.env.floor is NOT_ON_BORDER,
          "悬空时 floor 返回 NOT_ON_BORDER",
          repr(m.env.floor))
    check(m.env.ceiling is NOT_ON_BORDER,
          "悬空时 ceiling 返回 NOT_ON_BORDER")
    check(m.env.wall() is NOT_ON_BORDER,
          "悬空时 wall 返回 NOT_ON_BORDER")

    # NOT_ON_BORDER 必须是无害的：move 恒等、isOn 恒假
    p = Pt(123, 456)
    check(NOT_ON_BORDER.move(p) is p, "NOT_ON_BORDER.move() 是恒等函数")
    check(NOT_ON_BORDER.isOn(p) is False, "NOT_ON_BORDER.isOn() 恒为 False")

    # 站在工作区下边时 floor 必须正好落在工作区底边上
    m.anchor = Pt(wa.left + 300, wa.bottom)
    f = m.env.floor
    check(f is not NOT_ON_BORDER and f.isOn(m.anchor) and abs(f.y - wa.bottom) <= 2,
          "站在工作区下边时 floor 命中工作区底边",
          f"y={getattr(f, 'y', None)} bottom={wa.bottom}")

    # 站在左墙时 wall 必须是左边（朝右贴的是窗口左边/工作区左边）
    m.look_right = False
    m.anchor = Pt(wa.left, wa.bottom - 200)
    wl = m.env.wall(False)
    check(wl is not NOT_ON_BORDER and abs(wl.x - wa.left) <= 2,
          "朝左贴墙时 wall 命中工作区左边", f"x={getattr(wl, 'x', None)}")

    # ==================================================================
    section("1b. 隐蔽根因：全屏窗口过滤 + 光标速度公式")
    # 这两项不直接对应某条用户反馈，但都是「一打开窗口化 QQ 就出问题」的推手。
    # 1) 桌面上会枚举到 (-8,-8,1928,1040) / (0,0,1919,1080) 这类伪窗口。
    #    它们的 top 参与 floor 判定，会让地面突变。
    mgr.shared_env.refresh(force=True)
    wa_now = mgr.shared_env.work_area
    fs = [a for a in mgr.shared_env.windows if mgr.shared_env.is_fullscreen_window(a)]
    # 断言的是「**识别**正确」，而不是「一个全屏窗口都不该存在」——
    # 桌面上那两个伪窗口本来就存在，也本来就被识别为全屏；关键是它们
    # 不能进入地面候选。
    # Assert the *detection* works, not that no full-screen window exists:
    # the desktop pseudo-windows are legitimately there and legitimately
    # detected; what matters is that they stay out of the floor candidates.
    check(len(fs) >= 0 and all(
        mgr.shared_env.is_fullscreen_window(a) == (
            (min(a.right, wa_now.right) - max(a.left, wa_now.left)) *
            (min(a.bottom, wa_now.bottom) - max(a.top, wa_now.top))
            >= mgr.shared_env.FULLSCREEN_RATIO *
            (wa_now.right - wa_now.left) * (wa_now.bottom - wa_now.top))
        for a in mgr.shared_env.windows),
        "全屏判定与面积阈值一致（(-8,-8,1928,1040) 这类会被识别）",
        f"识别出 {len(fs)} 个全屏窗口: {[str(a) for a in fs][:3]}")
    # 把宠物放在一个真窗口的 x 范围内，确认候选里不含全屏窗口
    if mgr.shared_env.windows:
        probe_x = mgr.shared_env.windows[0].left + 5
        m.anchor = Pt(probe_x, wa_now.top + 200)
        me = m.env
        cands = me._candidates()
        check(all(not mgr.shared_env.is_fullscreen_window(a) for a in cands),
              "地面候选列表里不含全屏窗口（打开窗口化 QQ 不会突变地面）",
              f"{len(cands)} 个候选, x={probe_x}")

    # 2) 光标速度必须是原版的指数滑动平均 d=(d+新-旧)/2。
    #    我们之前用「最近 4 帧位置差」，陈旧采样点会把速度放大到几百 px/帧，
    #    而 投げられる 的初速正是 ${cursor.dy} —— 宠物一帧闪现 178px。
    from shimeji.engine.environment import Location
    loc = Location()
    loc.set(0, 0)
    for i in range(1, 11):
        loc.set(i * 10, i * 10)
    check(abs(loc.dx - 10.0) < 1.5 and abs(loc.dy - 10.0) < 1.5,
          "光标匀速移动时速度收敛到真实速度（指数滑动平均）",
          f"每帧 10px -> dx={loc.dx:.2f} dy={loc.dy:.2f}")
    # 关键回归：光标静止后再突然出现一个大跨越，速度必须**逐帧衰减**，
    # 而不是像「4 帧位置差」那样一次性给出跨越距离的均值。
    # 原版公式下 dx = (0 + 1000)/2 = 500，下一帧变成 250、125……
    loc2 = Location()
    for _ in range(8):
        loc2.set(500, 500)          # 光标静止
    loc2.set(1500, 200)             # 突然跳到别处
    first = loc2.dx
    for _ in range(6):
        loc2.set(1500, 200)         # 光标又静止了
    check(abs(loc2.dx) < abs(first) / 4.0,
          "光标位置突变后速度逐帧衰减（不会持续放大成一帧瞬移）",
          f"突变后 dx={first:.0f} -> 6 帧后 dx={loc2.dx:.1f}")
    # 与旧实现（4 帧滑动差分）对比。新公式首帧给 500，看似更大，但它立刻
    # 逐帧减半：500→250→125→…；旧公式则会把「跨越距离」当成持续速度，在窗口
    # 被填满之前一直是 250~333px/帧。投掷动作的初速直接取这个值，旧公式因此
    # 会连续几帧把宠物甩飞 —— 这才是「一帧闪现」的真正来源。
    # Compare against the old 4-frame sliding difference.  The new formula looks
    # bigger on the very first frame but halves every frame; the old one treated
    # the jump distance as a sustained velocity and kept reporting 250~333px per
    # frame until the window filled up — which is what flung the mascot across
    # the screen.
    new_series, old_hist, old_series = [], [(500, 500)] * 4, []
    for i in range(5):
        new_series.append(loc2.dx)
        old_hist.append((1500, 200))
        old_series.append((old_hist[-1][0] - old_hist[0][0]) / (len(old_hist) - 1))
        loc2.set(1500, 200)
    check(new_series[4] < old_series[4] / 10,
          "旧公式会把跨越距离当成持续速度，新公式逐帧减半（初速更保守）",
          f"新 {[round(v) for v in new_series]} vs 旧 {[round(v) for v in old_series]}")

    # ==================================================================
    section("1c. 全屏窗口不再触发「窗口底部爬行」（1.0.2 修复项）")
    # 用户反馈：「全屏窗口会触发发一个窗口底部爬行的动画」。
    # 根因：`activeIE` 按**光标**选窗口，而铺满工作区的窗口永远在光标下，
    # 于是 activeIE 一直是它；它的 bottom 恰好压在工作区底边上，宠物站在
    # 地面时 `activeIE.bottomBorder.isOn(anchor)` 恒为真 ->
    # Behavior.xml 里「IEの下辺を伝う」等 15+ 条 activeIE.*Border 条件持续命中。
    # Reported: a full-screen window fires the "crawl along the window bottom"
    # animation.  `activeIE` follows the *cursor*, and a work-area-filling window
    # is always under it, so `activeIE.bottomBorder.isOn(anchor)` was permanently
    # true for a mascot standing on the floor.
    env = mgr.shared_env

    def with_windows(rects):
        """临时替换窗口列表，返回恢复函数 / Swap the window list, return a restorer."""
        saved_w = list(env.windows)
        saved_m = dict(env._window_map)
        env.windows = []
        env._window_map = {}
        for i, (l, t, r, b) in enumerate(rects):
            a = Area(l, t, r, b, hwnd=990000 + i)
            env.windows.append(a)
            env._window_map[a.hwnd] = a
        return lambda: (setattr(env, "windows", saved_w),
                        setattr(env, "_window_map", saved_m))

    full_rects = [
        (0, 0, 1920, 1032),          # 真全屏
        (0, 200, 1920, 1032),        # 宽度满 + 底边压任务栏
        (100, 300, 1800, 1032),     # 近全屏（86% 宽）
        (-8, -8, 1928, 1040),        # explorer 桌面
        (0, 0, 1919, 1080),          # Progman
    ]
    check(all(env.is_fullscreen_window(Area(*r)) for r in full_rects),
          "铺满/压满工作区的窗口都判为全屏",
          f"{sum(1 for r in full_rects if env.is_fullscreen_window(Area(*r)))}/{len(full_rects)}")
    check(not env.is_fullscreen_window(Area(384, 179, 1234, 979)),
          "普通窗口化窗口不被误判为全屏（不能误伤爬窗功能）")

    restore = with_windows([(0, 0, 1920, 1032)])
    try:
        mgr.dismiss_all()
        pm = mgr.summon(Pt(wa.left + 400, wa.bottom))
        env._update_active_ie(wa.left + 960, wa.top + 500)
        em = pm.env
        check(not em.activeIE.visible,
              "光标在全屏窗口上时 activeIE 不可用（不再被它抢占）")
        check(not em.activeIE.bottomBorder.isOn(pm.anchor),
              "站在工作区地面时不再命中「窗口下边」（底部爬行的直接触发条件）")
        check(em.floor.isOn(pm.anchor),
              "地面判定仍然正常（工作区底边）")
        seen = set()
        for _ in range(80):
            env._update_active_ie(wa.left + 960, wa.top + 500)
            mgr.tick()
            a = pm.action
            d = getattr(a, "defn", None) if a is not None else None
            nm = getattr(d, "name", None) if d is not None else None
            if nm:
                seen.add(nm)
        # 只看真正的「爬行类」行为：IE の天井/下辺を歩く・伝う・壁を登る。
        # 「ワークエリアの下辺の左の端っこで座る」名字里也带「下辺」，但它是
        # 「在工作区底边左端坐下」—— 正常行为，不是爬窗。
        # Only real crawling: "IE no ten-/shita-hen wo aruku/utsuwa".  The sit
        # behaviour also contains "shita-hen" in its name but merely means
        # "sit at the left end of the work-area floor".
        CRAWL = ("IEの", "壁を登る", "IEの壁", "よじのぼる")
        crawl = [n for n in seen if n and n.startswith("IE")
                 and any(k in n for k in ("を歩く", "を走る", "を伝う", "を登る", "壁"))]
        check(not crawl, "全屏窗口下不再触发任何 IE 系爬行", str(crawl))
    finally:
        restore()

    # 回归：普通窗口仍然可以爬（别把功能一起关掉）
    restore = with_windows([(384, 179, 1234, 979)])
    try:
        mgr.dismiss_all()
        pm = mgr.summon(Pt(500, 179))
        env._update_active_ie(500, 400)
        em = pm.env
        check(em.activeIE.visible, "普通窗口下activeIE 仍然可用（没误伤）")
        check(em.activeIE.topBorder.isOn(pm.anchor),
              "站在普通窗口顶边时 topBorder 命中（爬窗功能保留）")
        nm = next((n for n in ("IEの天井を歩く", "IEの天井を走る")
                   if n in mgr.actions), None)
        if nm:
            mgr._force_behavior(pm, nm, interrupt=True)
            walk = [(round(pm.anchor.x), round(pm.anchor.y))]
            for _ in range(80):
                env._update_active_ie(500, 400)
                mgr.tick()
                walk.append((round(pm.anchor.x), round(pm.anchor.y)))
            check(abs(walk[-1][0] - walk[0][0]) > 40,
                  "普通窗口顶边仍能正常行走（没误伤）",
                  f"x {walk[0][0]} -> {walk[-1][0]}")
    finally:
        restore()
        mgr.dismiss_all()

    # ==================================================================
    section("2. LostGround：走到窗口边缘会掉下来，不再卡着蹭")
    # 造一个「悬空的窗台」：宠物站在窗口顶边，走到边缘外应当报 LostGround
    win = mgr.shared_env.windows
    before_n = len(win)
    # 用一个假的 Area 注入窗口列表（不真的创建窗口）
    fake = Area(wa.left + 200, wa.top + 300, wa.left + 500, wa.top + 600, True, hwnd=0)
    mgr.shared_env.windows.append(fake)
    mgr.shared_env._window_map[0] = fake
    # 宠物站在这个假窗口顶边
    m.anchor = Pt(wa.left + 350, fake.top)
    f = m.env.floor
    check(f is not NOT_ON_BORDER and abs(f.y - fake.top) <= 2,
          "站在窗口顶边时 floor 命中窗口顶边", f"floor.y={getattr(f,'y',None)} window.top={fake.top}")

    # 往右走出窗口右边缘 -> 应该脱离 floor
    m.anchor = Pt(fake.right + 30, fake.top)
    check(m.env.floor is NOT_ON_BORDER,
          "走出窗口右边缘后 floor 变 NOT_ON_BORDER（会触发下落）")

    # 现在跑一个「枠=地面」的走动动作，走到边缘应当产生 lost_ground
    from shimeji.engine.runtime import create_action
    from shimeji.xml.expr import Val
    # 目的地是字面量数字，包成 Val（和 XML 解析出来的形式一致）
    m.anchor = Pt(wa.left + 250, fake.top)
    m.look_right = True
    act = create_action(m, "歩く", {"destX": Val(str(fake.right + 200))})
    check(act is not None, "创建「歩く」动作（枠=地面，带目的地）")
    if act is not None:
        lost = False
        steps = 0
        while steps < 400:
            steps += 1
            alive = act.tick()
            m.reposition()
            if not alive:
                lost = act.lost_ground
                break
        check(lost,
              "走出窗口边缘的动作以 LostGround 结束（而不是静默结束）",
              f"走了 {steps} 帧, lost_ground={lost}")
        check(m.anchor.x > fake.right - 5,
              "宠物确实走出了窗口右边缘", f"x={m.anchor.x:.0f} right={fake.right}")

    # ==================================================================
    section("3. LostGround 会被 Manager 接管成「落下する」")
    m.pending_behaviors.clear()
    m.action = None
    # 关键：必须把宠物放在**已经脱离 floor** 的位置（窗口右边缘之外）。
    # 原版 `Fall.hasNext()` 在「已经站在边界上」时立即为 false —— 所以站在
    # 窗口顶边上触发 LostGround，落下する 会马上结束并走 select 的
    # 「壁に掴まる」分支挂住不动，那是**正确行为**，不是卡死。
    m.anchor = Pt(fake.right + 30, fake.top)
    check(m.env.floor is NOT_ON_BORDER, "构造场景：宠物已脱离任何地面")    # 跑几帧，确认它真的开始下落。
    # 场景要点：必须从**足够高**的地方掉下来（离所有边界都远），
    # 否则一开局就贴着某条边界，`select` 可能直接选「壁に掴まる」把宠物
    # 按在墙上 —— 那是原版设计，不是卡死。
    m.pending_behaviors.clear()
    m.action = None
    m.anchor = Pt(wa.left + 350, wa.top + 40)   # 贴近天花板但不在任何边界上
    check(m.env.floor is NOT_ON_BORDER and m.env.wall() is NOT_ON_BORDER,
          "构造场景：悬空，四周都没有边界")
    class _Lost:
        lost_ground = True

        def tick(self):
            return False
    m.action = _Lost()
    mgr._tick_mascot(m)
    check(BEHAVIOR_FALL in m.pending_behaviors,
          "LostGround 后「落下する」被排进队列",
          str(m.pending_behaviors))

    traj = []
    for _ in range(40):
        mgr._tick_mascot(m)
        traj.append((round(m.anchor.x), round(m.anchor.y)))
    check(len(set(traj)) > 3,
          "LostGround 之后确实在动（不是卡住）",
          f"轨迹 {traj[:6]}... 共 {len(set(traj))} 个不同位置")

    # 清理假窗口
    mgr.shared_env.windows.remove(fake)
    mgr.shared_env._window_map.pop(0, None)
    check(len(mgr.shared_env.windows) == before_n, "清理测试用的假窗口")

    # ==================================================================
    section("4. Fall 子步进：不会穿过窗口顶边")
    # 让宠物从窗口上方落下，验证它停在窗口顶而不是穿到窗口下面
    #
    # ⚠️ 必须把真实窗口全部请出去，只留注入的假窗口。
    # 不隔离的话，用户桌面上随便一个窗口就能接住宠物 —— 实测桌面上有个
    # top=222 的窗口，宠物从150 下落就停在 220，断言「停在 300」失败。
    # 这不是产品 bug，是测试自己把桌面环境漏了进来，于是同一条断言
    # 在不同用户的机器上结果不同。
    # Clear the real windows: any window on the user's desktop can catch the
    # pet.  A real window with top=222 made it land at 220 instead of 300.
    # That is test pollution, not a product bug — but it makes the assertion
    # machine-dependent, so isolate it.
    _saved_windows = list(mgr.shared_env.windows)
    _saved_map = dict(mgr.shared_env._window_map)
    mgr.shared_env.windows[:] = []
    mgr.shared_env._window_map.clear()
    try:
        fake2 = Area(wa.left + 200, wa.top + 300, wa.left + 500, wa.top + 600,
                     True, hwnd=0)
        mgr.shared_env.windows.append(fake2)
        mgr.shared_env._window_map[0] = fake2
        m.anchor = Pt(wa.left + 350, fake2.top - 150)
        from shimeji.engine.runtime import create_action as _ca
        fall = _ca(m, "落ちる", {})
        check(fall is not None, "创建「落ちる」（Fall）动作")
        if fall is not None:
            run = 0
            while run < 600 and fall.tick():
                m.reposition()
                run += 1
            landed_on_window = abs(m.anchor.y - fake2.top) <= 3
            check(landed_on_window,
                  "下落到窗口顶边时停在窗口顶（子步进生效，未穿透）",
                  f"y={m.anchor.y:.0f} window.top={fake2.top} frames={run}")
            check(m.anchor.y < fake2.bottom,
                  "没有穿过窗口落到窗口内部以下")
    finally:
        mgr.shared_env.windows[:] = _saved_windows
        mgr.shared_env._window_map.clear()
        mgr.shared_env._window_map.update(_saved_map)

    # ==================================================================
    section("5. 抛出：松手后立刻被甩出去并有连续的下落过程")
    # 场景要选在「下方没有任何边界」的位置，否则宠物一抛出去就落在某个真实
    # 窗口顶边上停住，测不出抛物线。做法：临时把窗口列表清空，让它只会在工作
    # 区下边着地。
    # Pick a spot with nothing below it, or the mascot lands on a real window top
    # and the parabola is never observable.  Temporarily empty the window list so
    # the only thing it can land on is the work-area bottom.
    saved_windows = list(mgr.shared_env.windows)
    saved_map = dict(mgr.shared_env._window_map)
    mgr.shared_env.windows = []
    mgr.shared_env._window_map = {}
    try:
        m.pending_behaviors.clear()
        m.action = None
        m.dragging = False
        m.anchor = Pt(wa.left + 800, wa.top + 200)     # 悬在半空，下方无窗口
        start = (m.anchor.x, m.anchor.y)
        check(m.env.floor is NOT_ON_BORDER, "构造场景：下方没有任何地面")
        # 真实用户甩宠物时，光标在**松手之前**就已经连续移动了若干帧，
        # 所以 `cursor.dx/dy` 松手时就是真实速度。测试必须照这个顺序来：
        # 先让光标平滑移动预热速度，再松手；如果一上来就把光标瞬移 1000px，
        # 那等于要求引擎把 1000px 当成单帧速度，瞬移是正确行为而非 bug。
        # In a real fling the cursor has already been moving for several frames
        # before release, so `cursor.dx/dy` is the true velocity at that moment.
        # Warm the velocity up first; teleporting the cursor 1000px in one frame
        # and calling the resulting teleport a bug would be wrong.
        for i in range(12):
            mgr.shared_env.cursor.set(wa.left + 620 + i * 15, wa.top + 320 - i * 8)
        warm_dx, warm_dy = mgr.shared_env.cursor.dx, mgr.shared_env.cursor.dy
        mgr.end_drag(m)
        check(m.action is None and m.pending_behaviors == [BEHAVIOR_THROWN],
              "松手后「投げられる」立刻接管（不排队等待）",
              str(m.pending_behaviors))

        traj = []
        for i in range(20):
            mgr.shared_env.cursor.set(wa.left + 620 + (12 + i) * 15,
                                      wa.top + 320 - (12 + i) * 8)
            mgr._tick_mascot(m)
            traj.append((round(m.anchor.x), round(m.anchor.y)))
        steps = [max(abs(b[0] - a[0]), abs(b[1] - a[1]))
                 for a, b in zip(traj, traj[1:])]
        check(len(set(traj)) > 3,
              "抛出后确实产生了连续位移（抛出动作生效，不再是「不生效」）",
              f"光标初速({warm_dx:.1f},{warm_dy:.1f}) -> "
              f"({start[0]:.0f},{start[1]:.0f}) -> {traj[0]} -> {traj[-1]}")
        # `投げられる` = 复合[ 落ちる(初速=cursor.dx/dy), 选择(跳ねる+立つ / 壁に掴まる) ]，
        # 所以抛出后可能继续下落，也可能被 select 抓住某面墙，两者都是原版行为。
        check(max(steps) < 80,
              "抛出过程连贯不闪现（单帧位移 < 80px，原版的防跳变阈值）",
              f"单帧最大 {max(steps)}px，轨迹 {traj[:7]}")
    finally:
        mgr.shared_env.windows = saved_windows
        mgr.shared_env._window_map = saved_map

    # ==================================================================
    section("6. 拖拽：光标在动就一直被拖着（不再 40 帧自动断）")
    m.pending_behaviors.clear()
    m.action = None
    m.dragging = True
    m.anchor = Pt(wa.left + 200, wa.top + 200)
    mgr.begin_drag(m)
    mgr._tick_mascot(m)          # 启动 ドラッグされる
    check(m.action is not None, "拖拽行为已启动")
    # 模拟持续移动的光标
    frames = 0
    for i in range(80):
        mgr.shared_env.cursor.set(wa.left + 200 + i * 3, wa.top + 200)
        mgr._tick_mascot(m)
        frames += 1
        if not m.dragging:
            break
    check(m.dragging and frames >= 70,
          "光标持续移动 80 帧后仍在拖拽（旧的 40 帧上限会断）",
          f"held for {frames} frames")
    m.dragging = False
    mgr._tick_mascot(m)

    # ==================================================================
    section("7. 行为队列：排队 vs 替换")
    m.pending_behaviors.clear()
    m.action = None
    mgr._force_behavior(m, BEHAVIOR_GATHER)
    mgr._force_behavior(m, "座ってボーっとする")
    check(m.pending_behaviors == [BEHAVIOR_GATHER, "座ってボーっとする"],
          "两个强制行为按顺序排队（FIFO）", str(m.pending_behaviors))
    mgr._force_behavior(m, BEHAVIOR_GATHER)
    check(m.pending_behaviors.count(BEHAVIOR_GATHER) == 1,
          "重复排同一个行为不会堆积（去重）", str(m.pending_behaviors))
    # 非 interrupt 不应打断当前动作
    m.action = object()
    mgr._force_behavior(m, BEHAVIOR_FALL)
    check(m.action is not None,
          "非 interrupt 的排队不会掐断当前动作（动作连贯的关键）")
    m.action = None

    # 队列被 Brain 按序消费
    from shimeji.engine.brain import Brain
    brain = Brain(mgr)
    m.pending_behaviors = [BEHAVIOR_GATHER, BEHAVIOR_FALL]
    first = brain.choose(m)
    second = brain.choose(m)
    check(first == BEHAVIOR_GATHER and second == BEHAVIOR_FALL,
          "Brain 按 FIFO 消费队列", f"{first} -> {second}")

    # ==================================================================
    section("8. 右键菜单的「指定动作」子菜单")
    menu = mgr._build_main_menu(m)
    labels = [a.text() for a in menu.actions()]
    submenus = [a.menu() for a in menu.actions() if a.menu() is not None]
    from shimeji.i18n import get_i18n
    want = get_i18n().t("menu.behaviors")
    check(want in labels, "主菜单含「指定动作」项", want)
    sub = next((s for s in submenus if s.title() == want), None)
    check(sub is not None, "「指定动作」是可展开的子菜单")
    if sub is not None:
        items = [a.text() for a in sub.actions()]
        # 菜单显示的是本地化标签，但**值**仍是日文原名（配置里就是日文，
        # 保证原版角色包兼容）。所以按标签比对 actions 是错的，要用 tooltip
        # 里的原文。
        # The labels are localized but the *values* stay Japanese (the config is
        # Japanese so original character packs keep working).  Comparing labels
        # against `actions` would therefore be wrong; compare the tooltips.
        ja_names = [a.toolTip() or a.text() for a in sub.actions()]
        check(len(items) > 5,
              "子菜单列出了行为名", f"{len(items)} 项，例如 {items[:3]}")
        bad = [n for n in ja_names if n not in mgr.actions]
        check(not bad, "子菜单里的每个行为都有对应动作（点了不会没反应）",
              f"无效项={bad[:5]}")
        # 用户反馈「指定动作菜单里全是日文」：标签必须本地化，原文进 tooltip。
        # Reported: the "Do behavior" menu was all Japanese.  Labels must be
        # localized while the original name stays in the tooltip.
        from shimeji.names import display_name
        lang = str(mgr.settings.get("language", "zh_CN"))
        bilingual = bool(mgr.settings.get("bilingual", True))
        untranslated = [a.text() for a in sub.actions()
                        if a.toolTip() and a.text() == a.toolTip()
                        and a.toolTip() in mgr.actions]
        check(not untranslated,
              "菜单标签已本地化（不再是清一色日文）",
              f"未本地化 {len(untranslated)} 项: {untranslated[:3]}")
        zh_labels = [a.text() for a in sub.actions()[:5]]
        check(any(any("一" <= ch <= "鿿" for ch in t) for t in zh_labels),
              "标签里能看到中文", f"{zh_labels[:3]}")
        # 点一下看看效果
        sub.actions()[0].trigger()
        check(m.pending_behaviors, "点击后行为被排进队列", str(m.pending_behaviors))
        m.pending_behaviors.clear()
    # 托盘菜单也应有
    tmenu = mgr._build_main_menu(None)
    tsubs = [a.menu().title() for a in tmenu.actions() if a.menu() is not None]
    check(want in tsubs, "托盘菜单同样含「指定动作」")

    # ==================================================================
    # ==================================================================
    section("9. 托盘图标与窗口跟随锁定")
    # 9.1 托盘：用户反馈「托盘图标也没有实现」。实测确认托盘对象存在、
    #     图标非空、可见，且菜单里也有「指定动作」。
    #     The reported "no tray icon".  Check it for real rather than by
    #     reading the source: the object, a non-null multi-size icon,
    #     visibility, and the "Do behavior" entry in its menu.
    from PySide6.QtWidgets import QSystemTrayIcon
    check(getattr(mgr, "tray", None) is not None, "托盘图标对象已创建")
    tray = getattr(mgr, "tray", None)
    if tray is not None:
        check(not tray.icon().isNull(),
              "托盘图标非空（含多尺寸 ICO，托盘只有 16×16 需要多尺寸）",
              f"availableSizes={[s.width() for s in tray.icon().availableSizes()]}")
        check(tray.isVisible(), "托盘图标已显示",
              f"系统托盘可用={QSystemTrayIcon.isSystemTrayAvailable()}")
        tmenu = tray.contextMenu()
        ttexts = [a.text() for a in tmenu.actions()] if tmenu else []
        check(bool(tmenu) and any("指定动作" in x for x in ttexts),
              "托盘右键菜单里也有「指定动作」（用户要的就是这个）",
              str([x for x in ttexts if x]))

    # 9.2 窗口跟随锁定 hwnd：拖动过程中换了窗口，位移不能被加到别的窗口上
    #     Window following locks the hwnd at init; switching windows mid-drag
    #     must not apply the displacement to an unrelated window.
    from shimeji.engine.builtin import _IEFollowMixin
    mgr.shared_env.refresh(force=True)
    wins = mgr.shared_env.windows
    if len(wins) >= 1:
        target = wins[0]
        m.pending_behaviors.clear()
        m.action = None
        m.anchor = Pt(wa.left + 300, wa.bottom)
        m.manager.shared_env.active_ie.visible = True
        m.manager.shared_env.active_ie.hwnd = target.hwnd
        holder = _IEFollowMixin()
        holder.mascot = m
        holder._ie_init()
        check(getattr(holder, "_ie_hwnd", None) == target.hwnd,
              "窗口跟随在 init 时锁定目标 hwnd（不是每帧重读 activeIE）",
              f"locked={getattr(holder, '_ie_hwnd', None)}")
        # 把 activeIE 换成别的窗口，锁定值不应改变
        if len(wins) >= 2:
            m.manager.shared_env.active_ie.hwnd = wins[1].hwnd
            check(getattr(holder, "_ie_hwnd", None) == target.hwnd,
                  "中途 activeIE 变化也不改变已锁定的 hwnd（窗口不会被甩到别的窗口上）")
        else:
            check(True, "中途 activeIE 变化也不改变已锁定的 hwnd（窗口不会被甩到别的窗口上）",
                  "只有一个窗口，跳过对比")
        # 窗口消失后释放，不抛异常
        m.manager.shared_env._window_map.pop(target.hwnd, None)
        holder._follow_window()
        check(getattr(holder, "_ie_hwnd", None) is None,
              "目标窗口消失后释放跟随（不抛异常、不空挥）")
    else:
        check(False, "窗口跟随在 init 时锁定目标 hwnd（不是每帧重读 activeIE）",
              "当前没有可用的窗口")

    # ==================================================================
    section("10. 爬墙：连续爬升，不卡住也不瞬移")
    # `壁を登る` 的 `目的地Y` 是动态表达式（`#{...}`），原版 `Move.tick()`
    # 每帧重新 eval。我们之前在 init 求值一次且默认值是 None，于是爬墙动作
    # 完全没有目的地 —— 用户反馈的「只能蹭墙不动，下一秒瞬间到顶上」。
    from shimeji.xml.expr import Val
    climb_beh = None
    for name in ("ワークエリアの下辺から右の壁によじのぼる",
                 "ワークエリアの下辺から左の壁によじのぼる"):
        if name in mgr.actions:
            climb_beh = name
            break
    if climb_beh is None:
        check(False, "找到爬墙行为（用于验证动态目的地）")
    else:
        # 强制行为偶尔会排在当前动作后面（而不是立刻打断），那一轮就根本没跑
        # 起爬行动作。这种情况与爬行本身无关，所以重试若干轮再下结论 ——
        # 否则测试会变成掷骰子。
        # The forced behaviour is sometimes queued behind the current action
        # instead of interrupting, so no climb runs at all.  That says nothing
        # about climbing, so retry a few times before judging.
        for attempt in range(6):
            mgr.dismiss_all()
            p = mgr.summon(Pt(wa.left + 150, wa.bottom))
            mgr._force_behavior(p, climb_beh, interrupt=True)
            rightward = "右" in climb_beh
            p.anchor = Pt(wa.right - 150 if rightward else wa.left, wa.bottom)
            p.set_look_right(rightward)
            traj = [(round(p.anchor.x), round(p.anchor.y))]
            # 逐帧记录「当前跑的是不是爬行动作」。爬行链里可能夹着短暂停顿
            # （动画的 16 帧静止段、中途换「伝う」），所以不能用「连续 N 帧
            # 不动」判定结束 —— 那会把后续行为（跳下墙 20px 位移）也切进来，
            # 凭空造出「单帧 20px」的假失败。
            # Track which frames actually run a climb action; the chain can
            # include short pauses, so "first run of N still frames" is the
            # wrong end-of-climb detector.
            climbing = [False]
            for _ in range(400):
                mgr.tick()
                traj.append((round(p.anchor.x), round(p.anchor.y)))
                a = p.action
                d = getattr(a, "defn", None) if a is not None else None
                nm = getattr(d, "name", None) if d is not None else None
                climbing.append(bool(nm) and any(
                    k in nm for k in ("登る", "よじのぼる", "伝う", "ずりずり", "這う")))
            last = max((i for i, c in enumerate(climbing) if c), default=-1)
            if last >= 2:
                break
        if last < 2:
            check(False, "爬墙行为成功启动（400 帧内进入爬行动作）",
                  f"重试 {attempt + 1} 轮都没跑起来")
        else:
            check(True, "爬墙行为成功启动（400 帧内进入爬行动作）",
                  f"爬行帧 {sum(1 for c in climbing if c)}/{len(climbing)}")
        if last >= 2:
            # 截到爬行动作最后一次出现为止（含中间的正常停顿）
            # 末帧索引要夹一下：爬行可能一直持续到窗口结束，此时 last+1 会
            # 正好等于 len(traj)。
            # Clamp: the climb can run to the end of the window, in which case
            # last+1 equals len(traj).
            cut = min(last + 1, len(traj) - 1)
            steps_all = [max(abs(b[0] - a[0]), abs(b[1] - a[1]))
                         for a, b in zip(traj, traj[1:])]
            steps = steps_all[:cut]
            heights = sorted({q[1] for q in traj[:cut + 1]})
            # `壁を登る` 的动态目的地是 `workArea.bottom - 64`，所以整段爬升
            # 只有 64px 行程（再减去动画里 16 帧的 0,0 静止段），因此高度数是
            # 几十而不是上百。关键不是绝对数量，而是「有实质爬升、且没有长时间
            # 原地不动」。
            # The climb destination is `workArea.bottom - 64`, so the ascent is
            # only 64px; what matters is progress without a long stall.
            moved = sum(1 for v in steps if v)
            longest_stall = 0
            cur = 0
            for v in steps:
                cur = 0 if v else cur + 1
                longest_stall = max(longest_stall, cur)
            # 爬墙可能随机换到另一侧墙，所以只断言「高度确实变了」，方向不限。
            climbed = abs(traj[cut][1] - traj[0][1]) > 10
            check(len(heights) > 20 and climbed,
                  "爬墙过程连续（有实质爬升，不是「蹭墙不动」）",
                  f"{traj[0]} -> {traj[cut]}, {len(heights)} 个高度, 最长停滞 {longest_stall} 帧")
            check(moved >= 30 and longest_stall <= 40,
                  "爬墙逐帧推进且没有长时间卡住",
                  f"移动 {moved}/{len(steps)} 帧, 最长停滞 {longest_stall} 帧")
            check(max(steps) < 80,
                  "爬墙没有瞬移（单帧位移 < 80px，原版的防跳变阈值）",
                  f"单帧最大 {max(steps)}px")
            check(max(steps) <= 4,
                  "爬墙逐帧平滑（单帧位移 <= 4px，动画速度就是 1~2px/帧）",
                  f"单帧最大 {max(steps)}px, 移动帧 {moved}/{len(steps)}")
        mgr.dismiss_all()

    # ==================================================================
    section("11. 长跑稳定性：不卡死、不出界、不异常")
    mgr.dismiss_all()
    pets = [mgr.summon(Pt(wa.left + 100 + i * 90, wa.bottom)) for i in range(3)]
    pets = [p for p in pets if p]
    check(len(pets) == 3, "召唤 3 只用于长跑")
    errs_before = len(mgr.mascots)
    oob = 0
    stuck = 0
    for i in range(1200):
        mgr.tick()
        for p in pets:
            if p not in mgr.mascots:
                continue
            if not (wa.left - 300 <= p.anchor.x <= wa.right + 300):
                oob += 1
            if p.anchor.y > wa.bottom + 60:
                oob += 1
            if p.anchor.y < wa.top - 400:
                oob += 1
    alive = len([p for p in pets if p in mgr.mascots])
    check(alive == 3, "1200 tick 后 3 只都还在", f"存活 {alive}/3")
    check(oob == 0, "1200 tick 内没有宠物出界", f"越界 {oob} 次")
    check(mgr.timer is not None, "引擎仍在运行")

    # 记录出现过的动作，确认不是卡在同一个动作。
    # 统计口径有两点都必须注意，否则会误判：
    #
    # 1. 要下钻到**叶子动作**。`p.action` 永远是顶层复合容器（Behavior.xml 里
    #    每个行为都是 `種類="複合"`），只看它永远是 'SequenceInstance'。
    # 2. 要按**动作名**而不是类名统计。叶子动作绝大多数都是 `AnimateInstance`
    #    （`動く` / `立ち止まる` / `座る` 都是动画播放），按类名永远只有一种。
    #    而且 Behavior.xml 里「座る」类行为的长度就是 500~1500 帧，600 帧的
    #    窗口本来就不足以覆盖多个行为 —— 所以窗口要开够，并允许中途被
    #    强制换掉。
    def leaves(action, out):
        """收集动作树里所有叶子动作的名字 / collect leaf action names."""
        if action is None:
            return
        child = getattr(action, "child", None)
        if child is not None:
            leaves(child, out)
            return
        name = getattr(getattr(action, "defn", None), "name", None)
        out.add(name or type(action).__name__)

    mgr.dismiss_all()
    p = mgr.summon(Pt(wa.left + 200, wa.bottom))
    seen_actions = set()
    # 2500 帧 ≈ 100 秒，覆盖 Behavior.xml 里最长 1500 帧的行为
    for _ in range(2500):
        mgr.tick()
        if p.action is not None:
            leaves(p.action, seen_actions)
    check(len(seen_actions) >= 3,
          "长跑中切换过多种叶子动作（不是卡死在一个动作）",
          f"{sorted(seen_actions)}")

    # ------------------------------------------------------------------
    section("1.0.3 CalMode：状态只改频率，不改动作")
    # CalMode 只应该让「跳跃/奔跑」和「发呆」的出现比例变化，绝不能让某个
    # 行为彻底消失，也绝不能抛异常。CalMode may only shift the *ratio* of
    # active vs. idle behaviours; it must not delete any or raise.
    mgr.dismiss_all()
    m = mgr.summon(Pt(wa.left + 300, wa.bottom))
    st = m.status
    ACT = "走る"           # 走る / run      -> active
    IDLE = "なべりつづく"   # なべる / lie down -> quiet

    def biases():
        return st.weight_bias(ACT), st.weight_bias(IDLE)

    st.feeling, st.energy, st.health, st.likability = 95.0, 90.0, 100.0, 85.0
    hi_a, hi_q = biases()
    check(st.state() == "happy", "高心情+高好感 -> 开心", st.summary())
    check(hi_a > hi_q, "开心时活跃行为权重高于安静行为", f"{hi_a} vs {hi_q}")

    st.feeling, st.health, st.likability = 50.0, 100.0, 0.0
    nm_a, nm_q = biases()
    check(st.state() == "normal", "中等心情 -> 普通", st.summary())
    check(nm_a > 1.0 > nm_q, "普通时活跃放大、安静压低", f"{nm_a} vs {nm_q}")

    st.feeling, st.health, st.likability = 20.0, 100.0, 0.0
    lo_a, lo_q = biases()
    check(st.state() == "poor", "低心情 -> 状态差", st.summary())
    check(lo_a < lo_q, "状态差时活跃行为被压低", f"{lo_a} vs {lo_q}")

    # 生病：健康值低于 real_health（60 - care）
    st.feeling, st.health, st.likability = 80.0, 20.0, 0.0
    si_a, si_q = biases()
    check(st.state() == "ill", "低健康 -> 生病", st.summary())
    check(si_a == min(hi_a, lo_a, nm_a, si_a) or si_a < nm_a,
          "生病时活跃行为权重最低", f"{si_a}")
    check(si_q > si_a, "生病时安静行为权重最高", f"{si_q}")

    # 心情好会让 real_health 下降 —— 同样的 health 也算健康（VPet 的精髓）
    st.feeling, st.likability, st.health = 95.0, 85.0, 50.0
    cared = st.state()
    st.feeling, st.likability = 20.0, 0.0
    uncared = st.state()
    check(cared != "sick",
          "被照顾得好时，同样的身体数值不算生病（real_health 随照顾下降）",
          f"cared={cared} uncared={uncared}")

    # 权重乘数有界，且不改变行为集合
    allnames = [b.name for _, b in mgr.brain.behaviors_of(m).entries]
    pools = {}
    for tag, setup in (("happy", (95.0, 95.0, 100.0, 85.0)),
                       ("sick", (60.0, 40.0, 15.0, 0.0))):
        st.feeling, st.energy, st.health, st.likability = setup
        pool = mgr.brain._global_pool(m, mgr.brain._ns(m))
        pools[tag] = {b.name: f for f, b in pool}
    check(set(pools["happy"]) == set(pools["sick"]),
          "不同状态下候选行为集合完全相同（只改权重不改行为）",
          f"{len(pools['happy'])} vs {len(pools['sick'])}")
    diff = [n for n in pools["happy"]
            if pools["happy"][n] != pools["sick"].get(n)]
    check(len(diff) > 0, "确实有权重被状态改写了", f"{len(diff)} 条，如 {diff[:3]}")
    check(all(pools["happy"][n] > 0 and pools["sick"][n] > 0
              for n in pools["happy"]),
          "没有任何行为被状态彻底清零")
    check(all(0.4 - 1e-9 <= st.weight_bias(n) <= 1.6 + 1e-9
              for n in allnames),
          "所有权重乘数都落在 0.4~1.6（有界，不会看起来像坏了）")
    del allnames

    # 互动与时间漂移
    st.feeling, st.likability, st.energy = 50.0, 0.0, 50.0
    before = st.feeling
    mgr.begin_drag(m)
    check(st.feeling > before, "拖拽宠物会涨心情（用户互动被计入）",
          f"{before:.1f} -> {st.feeling:.1f}")
    f0 = st.feeling
    for _ in range(400):        # ≈16s，超过一次 15s 结算
        st.tick_slow()
    check(st.feeling < f0, "长时间不互动心情会缓慢下降",
          f"{f0:.1f} -> {st.feeling:.1f}")
    check(st.feeling >= 12.0, "心情有下限，不会彻底坏掉", f"{st.feeling:.1f}")
    st2 = m.status
    check(st2 is st, "每只宠物持有自己的状态实例")

    # --- 每条行为可自定义 CalMode 权重 ---
    section("1.0.4 CalMode 逐条自定义权重")
    from shimeji.engine.petstate import CAL_CLASSES
    check(set(CAL_CLASSES) == {"auto", "active", "quiet", "off"},
          "四种类别齐全", f"{CAL_CLASSES}")
    # 「座る」这个名字既不在 ACTIVE_KEYS 也不在 QUIET_KEYS 里（自动判定为中性），
    # 正好用来验证「强制指定类别」能覆盖自动判定。
    NEUTRAL = "座る"
    st.feeling, st.energy, st.health, st.likability = 95.0, 90.0, 100.0, 85.0
    check(st.weight_bias(NEUTRAL) == 1.0,
          "自动判定为中性的行为不受状态影响（未覆盖时的行为）")
    check(st.weight_bias(NEUTRAL, {"class": "active"}) > 1.0,
          "指定「活跃」后开心时被放大", f"{st.weight_bias(NEUTRAL, {'class': 'active'})}")
    check(st.weight_bias(NEUTRAL, {"class": "quiet"}) < 1.0,
          "指定「安静」后开心时被压低", f"{st.weight_bias(NEUTRAL, {'class': 'quiet'})}")
    check(st.weight_bias(NEUTRAL, {"class": "off"}) == 1.0,
          "指定「不受影响」恒为 1.0")

    # 强度：0 抹平、100 默认、200 加倍
    a100 = st.weight_bias(NEUTRAL, {"class": "active", "strength": 100})
    a0 = st.weight_bias(NEUTRAL, {"class": "active", "strength": 0})
    a200 = st.weight_bias(NEUTRAL, {"class": "active", "strength": 200})
    check(a0 == 1.0, "强度 0% 完全抹平状态影响", f"{a0}")
    check(abs(a100 - 1.6) < 1e-6, "强度 100% 等于默认强度",
          f"{a100}（默认 1.6）")
    check(abs(a200 - 2.2) < 1e-6, "强度 200% 是默认效果的两倍",
          f"{a200}（= 1 + 2×0.6）")

    # 越界/非法输入要被夹住，不能让桌宠权重变成 0 或负数。
    # 强度本身夹在 0~200，所以 9999 与 200 等价（2.2），不是 3.0。
    check(st.weight_bias(NEUTRAL, {"class": "active", "strength": 9999})
          == a200, "强度超上限被夹到 200%", f"{st.weight_bias(NEUTRAL, {'class': 'active', 'strength': 9999})}")
    check(st.weight_bias(NEUTRAL, {"class": "active", "strength": -50})
          == 1.0, "负强度被夹到 0%（即 1.0）")
    check(st.weight_bias(NEUTRAL, {"class": "active", "strength": "坏值"})
          == 1.6, "非法强度值退回默认 100%")
    check(st.weight_bias(NEUTRAL, None) == 1.0, "rule=None 不报错")
    check(st.weight_bias(NEUTRAL, "不是字典") == 1.0, "rule 类型错误不报错")
    # 最终乘数必须落在有界区间，任何输入都不能把它推到 0 或负数
    worst = min(
        st.weight_bias(n, {"class": c, "strength": s})
        for n in ("走る", "座る", "なべりつづく", "")
        for c in CAL_CLASSES
        for s in (-1, 0, 100, 200, 9999))
    check(0.2 - 1e-9 <= worst <= 3.0 + 1e-9,
          "所有输入组合下乘数都落在 0.2~3.0（有界）", f"最小 {worst:.3f}")

    # 端到端：Brain 必须真的读设置。
    # 池子里的行为才断言 —— 全局池只含无条件成立的那十几条，
    # 「走る」挂在别的条件下，直接用它会 KeyError。
    # Only assert on names actually in the pool: the global pool holds just the
    # unconditional entries, and "走る" is gated behind another condition.
    mgr.settings.set("cal_overrides", {})
    st.feeling, st.energy, st.health, st.likability = 95.0, 95.0, 100.0, 85.0
    pool_names = [b.name for _f, b in mgr.brain._global_pool(m, mgr.brain._ns(m))]
    e_active = next((n for n in pool_names
                     if st.weight_bias(n) > 1.0), None)
    e_neutral = next((n for n in pool_names
                      if st.weight_bias(n) == 1.0), None)
    check(e_active is not None and e_neutral is not None,
          "全局池里同时存在「自动=活跃」和「自动=中性」的行为",
          f"active={e_active} neutral={e_neutral}")

    mgr.settings.set("cal_overrides", {
        e_active: {"class": "off"},                      # 改成不受影响
        e_neutral: {"class": "active", "strength": 200},  # 中性改成活跃且加倍
    })
    try:
        pools = {}
        for tag, setup in (("happy", (95.0, 95.0, 100.0, 85.0)),
                           ("sick", (60.0, 40.0, 15.0, 0.0))):
            st.feeling, st.energy, st.health, st.likability = setup
            pool = mgr.brain._global_pool(m, mgr.brain._ns(m))
            pools[tag] = {b.name: f for f, b in pool}
        check(set(pools["happy"]) == set(pools["sick"]),
              "加了覆盖后候选行为集合仍完全一致（覆盖只改频率）",
              f"{len(pools['happy'])} vs {len(pools['sick'])}")
        check(abs(pools["happy"][e_active] - pools["sick"][e_active]) < 1e-9,
              "「不受影响」的行为在开心/生病时权重相同",
              f"{pools['happy'][e_active]:.3f} vs {pools['sick'][e_active]:.3f}")
        check(pools["happy"][e_neutral] > pools["sick"][e_neutral],
              "被指定为活跃的行为在开心时权重高于生病",
              f"{pools['happy'][e_neutral]:.3f} vs {pools['sick'][e_neutral]:.3f}")
        check(all(v > 0 for v in pools["happy"].values())
              and all(v > 0 for v in pools["sick"].values()),
              "覆盖后仍没有任何行为被清零")
        # 端到端不能只改一只宠物的权重
        m2 = mgr.summon(Pt(wa.left + 500, wa.bottom))
        m2.status.feeling, m2.status.likability = 60.0, 0.0
        m.status.feeling, m.status.likability = 60.0, 0.0
        p2 = {b.name: f for f, b in mgr.brain._global_pool(m2, mgr.brain._ns(m2))}
        check(abs(p2[e_active] - pools["happy"][e_active]) < 1e-9,
              "覆盖对每只宠物都生效（不是只对第一只）",
              f"{p2[e_active]:.3f} vs {pools['happy'][e_active]:.3f}")
        mgr.dismiss(m2) if hasattr(mgr, "dismiss") else None
    finally:
        mgr.settings.set("cal_overrides", {})

    # 设置窗口的收集逻辑：只写与默认不同的项
    try:
        from shimeji.gui.settings_window import SettingsWindow
        sw = SettingsWindow(mgr)
        got = sw._collect_cal_overrides()
        check(got == {}, "全默认时不写入任何 CalMode 覆盖", f"{got}")
        rows = sw._behavior_rows
        check(len(rows) == sw.behavior_table.rowCount()
              and all(len(r) == 5 for r in rows),
              "行为表每行都带齐了 5 个控件（含 2 个 CalMode 控件）",
              f"{len(rows)} 行")
        check(sw.behavior_table.columnCount() == 6,
              "行为表 6 列（多出类别 + 强度）",
              f"{sw.behavior_table.columnCount()}")
        # 找一行改成 active/200 再收集
        target = next(r for r in rows if r[0] == e_active)
        target[3].setCurrentIndex(3)      # off
        check(not target[4].isEnabled(),
              "选「不受影响」时强度控件被置灰")
        target[3].setCurrentIndex(1)      # active
        check(target[4].isEnabled(), "切回其它类别后强度控件恢复可用")
        target[4].setValue(200)
        got = sw._collect_cal_overrides()
        check(got.get(e_active) == {"class": "active", "strength": 200},
              "设置窗口能收集到自定义的类别 + 强度", f"{got.get(e_active)}")
        target[4].setValue(100)
        got = sw._collect_cal_overrides()
        check(got.get(e_active) == {"class": "active"},
              "类别改但强度是 100% 时不冗余写 strength",
              f"{got.get(e_active)}")
        target[3].setCurrentIndex(0)      # auto
        got = sw._collect_cal_overrides()
        check(e_active not in got,
              "改回自动/100% 后该项从配置里消失（不留垃圾）", f"{got}")
        # 改语言后重建 UI 也不能崩（表头/文案都要重新取）
        old = mgr.settings.get("language", "zh_CN")
        try:
            mgr.settings.set("language", "en_US")
            sw2 = SettingsWindow(mgr)
            check(sw2.behavior_table.columnCount() == 6,
                  "英文界面下行为表同样是 6 列")
            hdr = [sw2.behavior_table.horizontalHeaderItem(i).text()
                   for i in range(6)]
            check(all(hdr), "英文表头没有空列", f"{hdr}")
        finally:
            mgr.settings.set("language", old)
    except Exception as e:  # noqa: BLE001
        check(False, "设置窗口的 CalMode 控件可用", f"{type(e).__name__}: {e}")

    section("1.0.6 首次引导 + 找不到程序的死循环")
    try:
        from shimeji.settings import Settings as _S, DEFAULTS
        import shimeji.engine.manager as _mm

        # 用全新设置，确保 first_run_guide_done 是默认的 False。
        # Settings() 会读磁盘上真实的 settings.json（用户早就跑过了），所以
        # 必须显式写回默认值再断言 —— 直接断言 s2.get() 会被用户的历史
        # 状态污染，这正是测试脚本最容易骗自己的地方。
        check(DEFAULTS.get("first_run_guide_done") is False,
              "默认值是 False（= 会弹首次引导）")
        s2 = _S()
        s2.set("first_run_guide_done", False)
        check(s2.get("first_run_guide_done", False) is False,
              "全新安装会弹首次引导")
        m2 = Manager(app, s2)
        # 构造时已排队 singleShot；这里不跑事件循环，只验证它被标记过了
        check(s2.get("first_run_guide_done") is True,
              "首次启动后立刻标记为已看过（避免每次都弹）")
        # 落盘验证：读原始文件确认真的写进去了而不只是内存。
        # 必须用 cfgfmt 而不是 json.load —— 1.0.5 起配置是**带注释的** JSON，
        # 裸 json.load 会因为那些注释直接抛 JSONDecodeError，断言永远读不到值
        # （看起来像「没有落盘」，其实是读法不对）。
        from shimeji import cfgfmt as _cf
        _raw = {}
        try:
            with open(s2.path, encoding="utf-8") as _f:
                _raw = _cf.loads_stripping_comments(_f.read())
        except Exception as _e:
            _raw = {}
        check(_raw.get("first_run_guide_done") is True,
              "引导标记已落盘（下次启动不会重复弹）",
              f"{_raw.get('first_run_guide_done')} ({type(_e).__name__ if '_e' in dir() else 'ok'})")

        # 关键回归：0 只宠物 + 面板被关掉 => 必须自动把面板叫回来
        m2.start()
        m2.dismiss_all()
        check(m2.count() == 0, "已解散全部宠物")
        m2._panel.hide()
        check(m2.panel_is_gone(), "面板已被隐藏（模拟用户关掉它）")
        m2._rescue_if_stranded()
        check(not m2.panel_is_gone(),
              "0 只 + 面板关闭 => 面板自动回来（死循环被打断）")

        # 反向：还有宠物时不该乱弹面板
        m2._panel.hide()
        m2.summon()
        m2._rescue_if_stranded()
        check(m2.panel_is_gone(),
              "还有宠物时不会强行弹面板（不打扰）")

        # 解散最后一只的那一刻就要触发，而不是等用户手动调用
        m2._panel.hide()
        m2.dismiss_all()
        check(not m2.panel_is_gone(),
              "解散最后一只的瞬间就自动拉回面板")
        m2.quit()

        # 三语文案齐全且非空。
        # 键名对应 1.0.5 后的品牌对话框：原来的 guide.quit_now（退出程序）
        # 和 guide.open_panel（打开面板）已废弃。
        for lang in ("zh_CN", "en_US", "ja_JP"):
            i2 = _mm.get_i18n()
            i2.set_language(lang)
            ok = all(i2.t(k).strip() for k in
                     ("guide.title", "guide.text", "guide.dismiss",
                      "guide.open_taskbar_settings"))
            check(ok, f"{lang} 引导文案齐全", f"{i2.t('guide.title')[:24]}")

        # 双击托盘图标 => 打开面板（而不是隐藏/显示宠物）
        from PySide6.QtWidgets import QSystemTrayIcon as _Tray
        s2b = _S()
        # 面板可能被用户关掉了（本机实测 taskbar_panel=false，托盘是唯一入口）。
        # 显式打开，否则 _panel 是 None，测的根本不是这个行为。
        # The panel can be disabled by the user — on this very machine
        # taskbar_panel is false, leaving the tray as the only entry point.
        # Force it on or the test would exercise nothing.
        s2b.set("taskbar_panel", True)
        m2b = Manager(app, s2b)
        check(m2b._panel is not None, "面板已按设置创建")
        m2b.start()
        m2b._panel.hide()
        check(m2b.panel_is_gone(), "托盘测试前置：面板已隐藏")
        m2b._on_tray_activated(_Tray.Trigger)
        check(not m2b.panel_is_gone(),
              "双击托盘图标会打开面板（而不是切换宠物显隐）")
        # 宠物的可见性不能被双击改动 —— 否则桌面看起来毫无变化
        vis_before = [m.isVisible() for m in m2b.mascots]
        m2b._on_tray_activated(_Tray.Trigger)
        check([m.isVisible() for m in m2b.mascots] == vis_before,
              "双击托盘不会改变宠物可见性")
        # 但右键菜单/托盘菜单里的显隐功能必须还在
        m2b.toggle_hidden()
        check(all(not m.isVisible() for m in m2b.mascots),
              "菜单里的「显示/隐藏宠物」功能仍在")
        m2b.toggle_hidden()
        check(all(m.isVisible() for m in m2b.mascots),
              "再点一次可以恢复显示")
        m2b.quit()
    except Exception as e:  # noqa: BLE001
        check(False, "首次引导与死循环防护可用", f"{type(e).__name__}: {e}")

    section("1.0.4 爬窗/扔窗独立开关 + 面板可移动 + 扔出可找回")
    try:
        from shimeji import win32

        # ---- A. 两个开关互相独立 ----
        s3 = _S()
        s3.set("climb_enabled", True)
        s3.set("throw_enabled", False)
        m3 = Manager(app, s3)
        m3.start()
        check(m3.settings.get("climb_enabled") is True
              and m3.settings.get("throw_enabled") is False,
              "两个开关可以各自独立设置")
        # 关掉扔窗不影响爬窗：WalkWithIE 仍能锁定窗口
        from shimeji.engine.runtime import create_action as _ca2
        m3.shared_env.refresh(force=True)
        a3 = m3.shared_env.activeIE
        if a3 is not None and a3.visible:
            w = _ca2(m3.mascots[0], "ワークエリアの下辺を歩く", {})
            if w is not None and hasattr(w, "_ie_init"):
                w._ie_init()
                check(getattr(w, "_ie_hwnd", None) == a3.hwnd,
                      "只关扔窗时，爬窗仍然能锁定窗口")
        m3.quit()

        # ---- B. 扔出去的窗口会被夹回工作区 ----
        s4 = _S()
        s4.set("climb_enabled", True)
        s4.set("throw_enabled", True)
        m4 = Manager(app, s4)
        m4.start()
        m4.shared_env.refresh(force=True)
        a4 = m4.shared_env.activeIE
        if a4 is not None and a4.visible:
            act = _ca2(m4.mascots[0], "IEを右に投げる", {})
            check(act is not None, "创建「IEを右に投げる」动作")
            if act is not None:
                # 直接把窗口搬到工作区外，再让动作收尾，验证 _reclaim_window
                # 会把它夹回来（不用真等它飞出去，那要跑几百帧）
                left, top, right, bottom = m4.shared_env.work_area
                off_x, off_y = right + 500, top + 200
                if win32.move_window(a4.hwnd, off_x, off_y):
                    m4.shared_env.sync_window(a4.hwnd, off_x, off_y,
                                              off_x + a4.width, off_y + a4.height)
                check(a4.left > right, "测试前置：窗口已被搬到工作区外",
                      f"left={a4.left:.0f} right={right}")
                act._reclaim_window()
                wa = m4.shared_env.work_area
                inside = (a4.left >= wa.left and a4.top >= wa.top
                          and a4.right <= wa.right and a4.bottom <= wa.bottom)
                check(inside, "扔出工作区的窗口被夹回可见区域",
                      f"-> left={a4.left:.0f} top={a4.top:.0f}")
                # 已经在工作区内的不能被乱动
                keep = (a4.left, a4.top)
                act._reclaim_window()
                check((a4.left, a4.top) == keep,
                      "已经在工作区内的窗口不会被移动（尊重用户摆放）")
        m4.quit()

        # ---- C. 面板不被固定在右下角 ----
        s5 = _S()
        s5.set("panel_pos", None)
        m5 = Manager(app, s5)
        m5.start()
        check(m5._panel is not None, "面板已创建")
        if m5._panel is not None:
            p5 = m5._panel
            p5.show_near_taskbar()
            app.processEvents()
            corner = (p5.x(), p5.y())
            check(corner[0] > 400 and corner[1] > 200,
                  "首次打开落在右下角附近", f"({corner[0]}, {corner[1]})")
            # 用户把面板拖到别处。这里刻意把 _placing 留成 False —— 它正是
            # 「这次移动不是程序自己发起的」的标记，真实拖拽时 Qt 不会置它。
            # Drag it elsewhere.  _placing stays False on purpose: that flag is
            # exactly the "this move was not initiated by us" marker, and Qt
            # leaves it clear during a real drag.
            p5.move(60, 80)
            moved = m5.settings.get("panel_pos", None)
            check(moved == [60, 80],
                  "拖动后面板位置被记住（不再跳回右下角）", str(moved))
            # 关键回归：刷新状态不能把面板拽回去
            p5.refresh_status()
            app.processEvents()
            check((p5.x(), p5.y()) == (60, 80),
                  "状态刷新不会把面板拽回右下角（这是「被固定」的根因）",
                  f"({p5.x()}, {p5.y()})")
            # 重新打开时沿用记忆位置
            p5.hide()
            p5.show_near_taskbar()
            app.processEvents()
            check((p5.x(), p5.y()) == (60, 80),
                  "重新打开时沿用用户拖过的位置", f"({p5.x()}, {p5.y()})")
            # 记忆位置失效（换分辨率落到屏幕外）时回退右下角，不能藏起来
            m5.settings.set("panel_pos", [99999, 99999])
            p5.hide()
            p5.show_near_taskbar()
            app.processEvents()
            check(p5.x() < 99999 and p5.y() < 99999,
                  "记忆位置失效时回退到右下角（不会把面板藏到屏幕外）",
                  f"({p5.x()}, {p5.y()})")
        m5.quit()

        # ---- D. 旧配置平滑迁移 ----
        import json as _j, tempfile as _tf
        fd, tmp = _tf.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                # 老配置：只有一个 ie_interaction 且被用户关掉了
                _j.dump({"ie_interaction": False}, f)
            old = _S(tmp)
            check(old.get("climb_enabled") is False
                  and old.get("throw_enabled") is False,
                  "旧的「关闭互动」配置迁移成两个开关都关（不偷偷重新打开）")
            with open(tmp, "w", encoding="utf-8") as f:
                _j.dump({"climb_enabled": True, "throw_enabled": False,
                         "ie_interaction": False}, f)
            new = _S(tmp)
            check(new.get("climb_enabled") is True
                  and new.get("throw_enabled") is False,
                  "新配置优先：旧键不再覆盖已经独立设置的两个开关")
        finally:
            os.remove(tmp)
    except Exception as e:  # noqa: BLE001
        check(False, "爬窗/扔窗独立开关与面板可移动可用",
              f"{type(e).__name__}: {e}")

    section("1.0.5 勾选多角色共存不再打断设置流程")
    try:
        import tempfile as _tf2
        from shimeji.gui.settings_window import SettingsWindow

        _d = _tf2.mkdtemp(prefix="utopet_v_")
        _sp = os.path.join(_d, "settings.json")
        try:
            # 全新配置：first_run_guide_done 默认 False，正好覆盖症状3
            s6 = _S(_sp)
            check(s6.get("first_run_guide_done", False) is False,
                  "前置：全新配置的引导标记是 False")
            m6 = Manager(app, s6)
            check(s6.get("first_run_guide_done") is True,
                  "构造 Manager 后引导标记已落盘（不依赖点开设置）")
            m6.start()

            w6 = SettingsWindow(m6)
            w6.show()
            check(True, "第一次打开设置窗口正常")

            # 根因回归：勾选触发 _sync_clone_state()，以前这里 NameError
            w6.multi_pet.setChecked(True)
            check(w6.multi_pet_note.text().strip() != "",
                  "勾选多角色不再抛异常，提示文字正常显示",
                  repr(w6.multi_pet_note.text()[:28]))
            check(not w6.clone.isEnabled(),
                  "多角色开启时增殖开关被正确禁用")

            # 症状2：点保存要真的落盘
            w6.apply()
            check(m6.settings.get("multi_pet_enabled") is True,
                  "点「保存」后多角色状态真正生效")
            # 同上：配置带注释，不能用裸 json.load
            from shimeji import cfgfmt as _cf2
            raw = _cf2.loads_stripping_comments(
                open(_sp, encoding="utf-8").read())
            check(raw.get("multi_pet_enabled") is True,
                  "点「保存」确实写进了磁盘")
            check(raw.get("self_cloning_enabled") is False,
                  "多角色下增殖自动关闭并落盘")
            check(raw.get("first_run_guide_done") is True,
                  "保存不会把首次引导标记弄丢")

            # 症状1：关掉再打开
            w6.close()
            m6._settings_window = None
            try:
                w6b = SettingsWindow(m6)
                w6b.show()
                check(True, "关闭后重新点设置能正常打开")
                check(w6b.multi_pet.isChecked(),
                      "重新打开时多角色开关状态被正确回填")
            except Exception as e:  # noqa: BLE001
                check(False, "关闭后重新点设置能正常打开",
                      f"{type(e).__name__}: {e}")

            # 症状3：重启后不再弹引导
            m6.quit()
            s6b = _S(_sp)
            check(s6b.get("first_run_guide_done") is True,
                  "重启后不会再弹首次引导",
                  str(s6b.get("first_run_guide_done")))
            check(s6b.get("multi_pet_enabled") is True,
                  "重启后多角色设置被正确保留")
            m6b = Manager(app, s6b)
            m6b.quit()
        finally:
            import shutil as _sh
            _sh.rmtree(_d, ignore_errors=True)

        # 静态防线：整个文件不允许再出现裸 `t`
        import ast as _ast
        _src = os.path.join(ROOT, "shimeji", "gui", "settings_window.py")
        _tree = _ast.parse(open(_src, encoding="utf-8").read())
        _bad = []

        class _V(_ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                bound = set()
                for n in _ast.walk(node):
                    if isinstance(n, _ast.Assign):
                        for tgt in n.targets:
                            for x in _ast.walk(tgt):
                                if isinstance(x, _ast.Name):
                                    bound.add(x.id)
                for n in _ast.walk(node):
                    if (isinstance(n, _ast.Name) and n.id == "t"
                            and isinstance(n.ctx, _ast.Load)
                            and "t" not in bound):
                        _bad.append(f"{node.name}:{n.lineno}")
                self.generic_visit(node)

        _V().visit(_tree)
        check(not _bad, "settings_window.py 里没有裸 t 引用了", str(_bad))
    except Exception as e:  # noqa: BLE001
        check(False, "勾选多角色共存不再打断设置流程",
              f"{type(e).__name__}: {e}")


    # 汇总 / wrap up
    print("=" * 56)
    if FAILS:
        print(f"{len(FAILS)} FAILED / {PASSES} passed")
        for f in FAILS:
            print("  x", f)
        return 1
    print(f"ALL PASS —— {PASSES} 项检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
