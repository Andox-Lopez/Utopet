# -*- coding: utf-8 -*-
"""
多宠物压力测试 / Multi-mascot stress test
==============================================================================
一次召唤 N 只，跑若干帧，检查：位置是否分散、动作是否各自独立、单帧耗时。
Summon N mascots at once, run frames, and check: spread-out positions,
independent actions, and per-tick cost.
"""
import os
import random
import sys
import tempfile
import time

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
s.set("initial_count", 1)
get_i18n().set_language("zh_CN")
m = Manager(app, s)

N = 12
for _ in range(N - m.count()):
    m.summon()
p("count after summon =", m.count())

for i in range(400):
    m.tick()

anchors = [(round(mm.anchor.x), round(mm.anchor.y)) for mm in m.mascots]
p("distinct anchors =", len(set(anchors)), "/", len(anchors))
p("anchor sample    =", anchors[:6])

actions = [mm.action.defn.name if mm.action and mm.action.defn else None for mm in m.mascots]
p("action types     =", sorted(set(actions)))
names = actions
p("distinct actions =", len(set(names)), "->", names[:6])

# 各自动? real movement check
before = list(anchors)
t0 = time.perf_counter()
FRAMES = 3000
for _ in range(FRAMES):
    m.tick()
dt = time.perf_counter() - t0
after = [(round(mm.anchor.x), round(mm.anchor.y)) for mm in m.mascots]
moved = sum(1 for a, b in zip(before, after) if a != b)
p("frames=%d  moved=%d/%d  total=%.2fs  per-tick=%.3fms"
  % (FRAMES, moved, len(after), dt, dt * 1000 / FRAMES))
for _ in range(300): m.tick()
s.set("max_count", 5)
extra = m.summon()
p("count after 300 ticks =", m.count())

m.quit()
p("OK")
