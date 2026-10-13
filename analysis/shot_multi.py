# -*- coding: utf-8 -*-
"""
多宠物真实截图 / Real desktop screenshot with several mascots
==============================================================================
真机（非离屏）召唤一批宠物，跑一会儿后截取整块屏幕与任务栏面板。
Runs for real (not offscreen): summons a batch, lets them move, then captures
the whole screen and the taskbar panel.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("QT_QPA_PLATFORM", None)  # 必须真实窗口 / must use real windows

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402


def p(*a):
    print(*a, flush=True)


here = os.path.dirname(os.path.abspath(__file__))
s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 1)
s.set("max_count", 50)
s.set("taskbar_panel", True)
get_i18n().set_language("zh_CN")
m = Manager(app, s)

p("initial =", m.count())
p("summon_many(6) ->", m.summon_many(6))
p("count =", m.count())

for _ in range(150):
    m.tick()
    app.processEvents()

# 面板截图 / the panel
panel = m._panel
panel.show_near_taskbar()
app.processEvents()
panel.grab().save(os.path.join(here, "panel_multi.png"))

# 整屏（含所有宠物）/ whole screen, mascots included
screen = QApplication.primaryScreen()
shot = screen.grabWindow(0)
target = os.path.join(here, "desktop_multi.png")
shot.save(target)
p("desktop shot ->", target, shot.size().width(), "x", shot.size().height())

anchors = sorted((round(x.anchor.x), round(x.anchor.y)) for x in m.mascots)
p("anchors =", anchors)
names = [x.action.defn.name if x.action and x.action.defn else None for x in m.mascots]
p("distinct running actions =", len(set(names)))

m.set_hidden(True)
app.processEvents()
shot_hidden = screen.grabWindow(0)
shot_hidden.save(os.path.join(here, "desktop_hidden.png"))
p("hidden shot saved, hidden =", m.hidden, "| visible windows =",
  sum(1 for x in m.mascots if x.isVisible()))

m.quit()
p("OK")
