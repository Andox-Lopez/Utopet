# -*- coding: utf-8 -*-
"""冒烟测试：Logo + 任务栏面板 / smoke test: logo & taskbar panel."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

# QPixmap / QIcon 必须在 QApplication 之后构造
# QPixmap / QIcon must be constructed *after* the QApplication
app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.icons import app_icon, logo_path, logo_pixmap  # noqa: E402
from shimeji.settings import Settings  # noqa: E402
from shimeji.win32 import set_app_user_model_id  # noqa: E402


def p(*a):
    print(*a, flush=True)


p("logo ->", os.path.basename(logo_path()),
  "| icon null?", app_icon().isNull(),
  "| pixmap null?", logo_pixmap(40).isNull())
app.setWindowIcon(app_icon())
p("AppUserModelID ->", set_app_user_model_id())

tmp = os.path.join(tempfile.mkdtemp(), "settings.json")
s = Settings(tmp)
p("taskbar_panel default =", s.get("taskbar_panel"))
get_i18n().set_language(s.get("language"))

from shimeji.engine.manager import Manager  # noqa: E402

m = Manager(app, s)
p("mascots =", m.count())
p("panel exists =", m._panel is not None, "| visible =", m._panel.isVisible())
p("panel title  =", m._panel.windowTitle())
p("panel count  =", m._panel.count_label.text())
# 没有 summon_label：数量含义是靠 tooltip 传达的（面板按钮只写「召唤」）。
# No summon_label — the spin box's meaning is carried by its tooltip.
p("panel spin   =", m._panel.summon_spin.value(), "|",
  repr(m._panel.summon_spin.toolTip()))
# 1.0.5：面板上不再有「聚到鼠标旁」按钮，功能只在托盘/右键菜单里。
p("btn_gather gone?", not hasattr(m._panel, "btn_gather"))
p("panel char   =", m._panel.char_label.text())
p("panel icon null? =", m._panel.windowIcon().isNull())

m.summon()
m.summon()
m._panel.refresh_status()
p("after summon ->", m._panel.count_label.text())

for lang in ("en_US", "ja_JP", "zh_CN"):
    s.set("language", lang)
    m.apply_settings()
    p(lang, "=>", m._panel.windowTitle(), "|", m._panel.btn_summon.text(),
      "|", m._panel.count_label.text(), "|", m._panel.btn_quit.text())

m._panel.close()
p("after close -> visible =", m._panel.isVisible(), "| mascots =", m.count())

m.set_taskbar_panel(False)
p("disabled ->", m._panel.isVisible(), s.get("taskbar_panel"))
m.set_taskbar_panel(True)
p("enabled  ->", m._panel.isVisible(), s.get("taskbar_panel"))

m.open_settings()
p("settings icon null? =", m._settings_window.windowIcon().isNull(),
  "| has taskbar cb =", hasattr(m._settings_window, "taskbar_panel"))
p("tray icon null?     =", m.tray.icon().isNull())
p("tray menu items     =", [a.text() for a in m.tray.contextMenu().actions()])

m.quit()
p("OK")
