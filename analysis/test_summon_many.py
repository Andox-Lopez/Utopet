# -*- coding: utf-8 -*-
"""
批量召唤测试 / Batch-summon test
==============================================================================
检查 summon_many：落点是否铺开、到达上限是否收敛、dismiss_to 是否准。
Checks summon_many: even spread, cap clamping, and dismiss_to accuracy.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402


def p(*a):
    print(*a, flush=True)


s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 0)
s.set("max_count", 50)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
p("start count (initial_count=0) =", m.count())

added = m.summon_many(10)
p("summon_many(10) ->", added, "| anchors:", sorted(round(x.anchor.x) for x in m.mascots))

wa = m.shared_env.work_area
p("work area x:", wa.left, "->", wa.right)
xs = sorted(round(x.anchor.x) for x in m.mascots)
gaps = [b - a for a, b in zip(xs, xs[1:])]
p("min gap =", min(gaps), "| avg gap =", int(sum(gaps) / len(gaps)))

# 关掉铺开对照 / compare with spread off
m.dismiss_all()
s.set("spawn_spread", False)
added2 = m.summon_many(10)
xs2 = sorted(round(x.anchor.x) for x in m.mascots)
gaps2 = [b - a for a, b in zip(xs2, xs2[1:])]
p("spread=False ->", added2, "| min gap =", min(gaps2))

# 上限收敛 / cap clamping
m.dismiss_all()
s.set("max_count", 4)
s.set("spawn_spread", True)
p("max_count=4 -> summon_many(10) =", m.summon_many(10), "| count =", m.count())

# dismiss_to
s.set("max_count", 50)
m.summon_many(8)
p("count =", m.count(), "-> dismiss_to(2) removed", m.dismiss_to(2),
  "| count =", m.count())

# 跑一段确保没有互相干扰 / run a while to be sure they don't disturb each other
m.summon_many(6)
for _ in range(1200):
    m.tick()
p("after 1200 frames -> count =", m.count(),
  "| distinct =", len({(round(x.anchor.x), round(x.anchor.y)) for x in m.mascots}))
m.quit()
p("OK")
