# -*- coding: utf-8 -*-
"""验证 F2（互动细分）：不同互动给不同数值，摸头也算互动。

详见 `docs/FEATURES_1.2.0.md` 的 F2。

## 为什么要单独一个文件

F1 的 `verify_status_panel.py` 测的是「数值**看不看得见**」，F2 测的是
「数值**怎么变**」—— 两件事，分开更清楚。

## ⭐ 不依赖真实鼠标

`begin_drag()` / `end_drag()` 是 `Manager` 的方法，直接调用即可；
「位移」通过设 `mascot.anchor` 模拟。不需要真实鼠标，也不需要注入接缝。

（`Environment.refresh()` 每 tick 会把光标重置成真实鼠标 —— 但这两个方法
根本不读光标，所以不受影响。）

用法：python analysis/verify_interaction.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Pt  # noqa: E402
from shimeji.engine.manager import BEHAVIOR_THROWN, Manager  # noqa: E402
from shimeji.engine.petstate import PetStatus  # noqa: E402
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


def fresh(feeling=50.0, energy=80.0, health=90.0, likability=20.0):
    return PetStatus(feeling=feeling, energy=energy, health=health,
                     likability=likability)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ==================================================================
    section("1. 三种互动给出**不同**的数值变化")
    res = {}
    for kind in ("pat", "drag", "throw"):
        st = fresh()
        st.interact(kind)
        res[kind] = (st.feeling, st.likability, st.energy)
        print("      %-6s 心情 %5.2f  好感 %5.2f  体力 %5.2f"
              % (kind, *res[kind]), flush=True)

    # 三者不能全一样（以前 `del kind` 时就是全一样）
    check(len({res[k] for k in res}) == 3,
          "三种互动的数值变化**各不相同**（不再 del kind）")

    # ==================================================================
    section("2. 各自的方向符合设计")
    # 摸头：心情涨最多，体力几乎不耗
    check(res["pat"][0] > res["drag"][0] and res["pat"][0] > res["throw"][0],
          "摸头涨心情最多", "pat=%.2f drag=%.2f throw=%.2f"
          % (res["pat"][0], res["drag"][0], res["throw"][0]))
    check((80.0 - res["pat"][2]) < 0.5,
          "摸头**几乎不耗体力**", "耗 %.2f" % (80.0 - res["pat"][2]))
    # 拖拽：好感涨最多
    check(res["drag"][1] > res["pat"][1] and res["drag"][1] > res["throw"][1],
          "拖拽涨好感最多", "drag=%.2f pat=%.2f throw=%.2f"
          % (res["drag"][1], res["pat"][1], res["throw"][1]))
    # 抛出：体力耗最多
    check((80.0 - res["throw"][2]) > (80.0 - res["drag"][2]),
          "抛出耗体力最多", "throw 耗 %.2f / drag 耗 %.2f"
          % (80.0 - res["throw"][2], 80.0 - res["drag"][2]))
    # ⭐ 体力必须是**下降**的（我第一版符号写反过，变成涨体力）
    for kind in ("pat", "drag", "throw"):
        check(res[kind][2] < 80.0, "%s 后体力下降（不是上涨）" % kind,
              "%.2f" % res[kind][2])

    # ==================================================================
    section("3. 未知 kind 退回通用值，不会静默失效")
    st = fresh()
    st.interact("不存在的互动")
    check(st.feeling > 50.0 and st.energy < 80.0,
          "未知 kind 仍然生效（心情涨、体力降）",
          "心情 %.2f 体力 %.2f" % (st.feeling, st.energy))

    # ==================================================================
    section("4. ⭐ 摸头（点了没拖动）真的算互动了")
    d = tempfile.mkdtemp(prefix="utopet_interact_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("restore_session", False)
        s.set("initial_count", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        wa = mgr.shared_env.work_area
        m = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m is not None, "召唤出宠物")

        # 按下 -> 松开，**没有移动** -> 应该是摸头
        before = (m.status.feeling, m.status.likability, m.status.energy)
        mgr.begin_drag(m)
        mgr.end_drag(m)
        after = (m.status.feeling, m.status.likability, m.status.energy)
        d_feel = after[0] - before[0]
        d_energy = before[2] - after[2]
        check(abs(d_feel - 2.2) < 0.01,
              "没拖动 -> 按摸头结算（心情 +2.2）", "实际 +%.2f" % d_feel)
        check(d_energy < 0.5,
              "摸头几乎不耗体力", "耗 %.2f" % d_energy)

        # ==================================================================
        section("5. 真的拖动了 -> 按拖拽 + 抛出结算")
        before = (m.status.feeling, m.status.likability, m.status.energy)
        mgr.begin_drag(m)
        # 模拟拖着走了一大段
        m.anchor = Pt(m.anchor.x + 200, m.anchor.y - 120)
        mgr.end_drag(m)
        after = (m.status.feeling, m.status.likability, m.status.energy)
        d_feel2 = after[0] - before[0]
        d_like2 = after[1] - before[1]
        d_energy2 = before[2] - after[2]
        # drag(+0.8) + throw(+1.8) = +2.6
        check(abs(d_feel2 - 2.6) < 0.01,
              "拖走了 -> 按 drag+throw 结算（心情 +2.6）", "实际 +%.2f" % d_feel2)
        check(abs(d_like2 - 0.55) < 0.01,
              "好感按 drag+throw 结算（+0.55）", "实际 +%.2f" % d_like2)
        check(abs(d_energy2 - 4.0) < 0.01,
              "体力按 drag+throw 结算（耗 4.0）", "实际耗 %.2f" % d_energy2)
        check(d_like2 > res["pat"][1] - 20.0 + 0.4,
              "拖着走涨的好感明显多于摸头")

        # ==================================================================
        section("6. ⚠️ 产品行为不变：松手后照样是「被抛出」")
        # ⭐ 措辞要能看出**实际是什么**：detail 打印出 pending 与 forced，
        # 失败时一眼能看出是行为没排上，还是排上了别的行为。
        pending = list(getattr(m, "pending_behaviors", []) or [])
        forced = getattr(m, "forced_behavior", None)
        check(BEHAVIOR_THROWN in pending or forced == BEHAVIOR_THROWN,
              "松手后仍然切成「投げられる」（F2 只改数值，不改行为）",
              "pending=%s forced=%s" % (pending, forced))

        mgr.quit()
    finally:
        shutil.rmtree(d, ignore_errors=True)

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
