# -*- coding: utf-8 -*-
"""截任务栏面板，确认新按钮布局。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from shimeji.settings import Settings
from shimeji.engine.manager import Manager
from shimeji.gui.taskbar_panel import TaskbarPanel

m = Manager(app, Settings())
m.settings.set("summon_count", 5)
p = TaskbarPanel(m)
p.show()
app.processEvents()
p.adjustSize()
pm = p.grab()
pm.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_panel_new.png"))
print("panel size:", pm.width(), "x", pm.height())
print("btn_summon:", repr(p.btn_summon.text()))
print("spin:", p.summon_spin.value(), "tooltip:", repr(p.summon_spin.toolTip()))
print("btn_hide:", repr(p.btn_hide.text()))
