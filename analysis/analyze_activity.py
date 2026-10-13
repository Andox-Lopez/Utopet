# -*- coding: utf-8 -*-
"""
活跃度分析 / Activity analysis
==============================================================================
量化「宠物看起来不动」：统计锚点发生位移的帧比例、位移距离、以及各行为的
停留时间。用来判断是不是行为权重太「静」了。
Measures how much the mascots actually move, and how long each behaviour lasts.
"""
import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.names import display_name  # noqa: E402
from shimeji.settings import Settings  # noqa: E402


def p(*a):
    print(*a, flush=True)


s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 1)
s.set("self_cloning_enabled", False)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
mm = m.mascots[0]
p("character =", s.get("character"), "| scale =", s.get("scale"))

FRAMES = 3000          # 3000 * 40ms = 120 秒 / 120 seconds
moved = 0
total_dx = 0.0
beh = Counter()
prev = (mm.anchor.x, mm.anchor.y)
for _ in range(FRAMES):
    m.tick()
    now = (mm.anchor.x, mm.anchor.y)
    if now != prev:
        moved += 1
        total_dx += abs(now[0] - prev[0])
        prev = now
    if mm.action is not None and mm.action.defn is not None:
        beh[mm.action.defn.name] += 1

p("frames=%d  moving=%d (%.1f%%)  total |dx| = %.0f px  avg speed=%.1f px/s"
  % (FRAMES, moved, 100.0 * moved / FRAMES, total_dx,
     total_dx / (FRAMES * 0.04)))
p("behavior distribution:")
for name, c in beh.most_common(14):
    p("   %-34s %4d  %5.1f%%" % (display_name(name, "zh_CN", False), c,
                                  100.0 * c / FRAMES))
m.quit()