# -*- coding: utf-8 -*-
"""验证 F4（番茄钟联动）：专注时段活跃行为权重下降，但行为集合不变。

核心约束（与 F1~F3 一致）：**只改频率，不改行为集合**。
- WORK 阶段：活跃行为（走る/跳ね/登る…）权重 ×0.5，安静行为 ×1.1
- 其余阶段（idle/break/long/paused）：×1.0
- 任何行为权重都不会被清零（专注是「不打扰」，不是「不动」）
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
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

    d = tempfile.mkdtemp(prefix="utopet_pomo_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku"); s.set("taskbar_panel", False)
        s.set("restore_session", False); s.set("initial_count", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        from shimeji.engine.environment import Pt
        wa = mgr.shared_env.work_area
        m = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m is not None, "召唤出宠物")
        b = mgr.brain
        pom = mgr.pomodoro

        # 收集配置里真实存在的活跃 / 安静 / 中性行为名
        names = list(mgr.actions.order)
        from shimeji.engine.petstate import ACTIVE_KEYS, QUIET_KEYS

        def kind_of(n):
            if any(k in n for k in ACTIVE_KEYS):
                return "active"
            if any(k in n for k in QUIET_KEYS):
                return "quiet"
            return "neutral"

        active = [n for n in names if kind_of(n) == "active"]
        quiet = [n for n in names if kind_of(n) == "quiet"]
        check(len(active) > 0, "配置里存在活跃行为", str(active[:3]))
        print("      活跃 %d 个 / 安静 %d 个 / 中性 %d 个"
              % (len(active), len(quiet), len(names) - len(active) - len(quiet)),
              flush=True)

        # ==================================================================
        section("1. 非专注阶段乘数恒为 1.0")
        for ph in ("idle", "break", "long_break", "paused"):
            pom._phase = ph
            vals = {n: b._pomodoro_bias(n) for n in names}
            check(all(v == 1.0 for v in vals.values()),
                  "%s 阶段所有行为乘数 = 1.0" % ph)

        # ==================================================================
        section("2. 专注（work）阶段：活跃行为 ×0.5")
        pom._phase = "work"
        for n in active:
            v = b._pomodoro_bias(n)
            check(abs(v - 0.5) < 1e-9, "活跃行为 %s 专注时权重减半" % n, str(v))

        # 安静行为 ×1.1（若配置里有）
        for n in quiet:
            v = b._pomodoro_bias(n)
            check(abs(v - 1.1) < 1e-9, "安静行为 %s 专注时略增" % n, str(v))

        # 中性行为 ×1.0
        neutral = [n for n in names if kind_of(n) == "neutral"]
        check(all(b._pomodoro_bias(n) == 1.0 for n in neutral),
              "中性行为专注时不受影响")

        # ==================================================================
        section("3. ⭐ 只改频率：行为集合不变，权重不清零")
        ns = mgr.brain._ns(m)
        pom._phase = "idle"
        idle_pool = {x.name: f for f, x in b._global_pool(m, ns)}
        pom._phase = "work"
        work_pool = {x.name: f for f, x in b._global_pool(m, ns)}

        check(set(idle_pool) == set(work_pool),
              "专注前后**候选行为集合完全相同**（只改权重不改集合）",
              "idle=%d work=%d" % (len(idle_pool), len(work_pool)))
        check(all(f > 0 for f in work_pool.values()),
              "专注时**没有任何行为权重被清零**",
              "最小权重=%.4f" % min(work_pool.values()))

        # 活跃行为在 work 池里的权重确实比 idle 小
        active_in_pool = [n for n in active if n in idle_pool and n in work_pool]
        if active_in_pool:
            sample = active_in_pool[0]
            check(work_pool[sample] < idle_pool[sample],
                  "活跃行为 %s 在专注时权重更低" % sample,
                  "idle=%.3f work=%.3f" % (idle_pool[sample], work_pool[sample]))

        # ==================================================================
        section("4. 专注结束（回 idle）后恢复正常")
        pom._phase = "idle"
        again = {x.name: f for f, x in b._global_pool(m, ns)}
        check(again == idle_pool,
              "回到空闲后权重完全恢复",
              "一致" if again == idle_pool else "不一致")

        pom._phase = "idle"
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
