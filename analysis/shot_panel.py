# -*- coding: utf-8 -*-
"""给任务栏面板与 Logo 出图 / screenshot the taskbar panel and the logo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 注意：offscreen 平台缺 CJK 字体会渲染成方块，这里必须用真实窗口
# NOTE: the offscreen platform lacks CJK fonts and shows tofu; use real windows.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.icons import app_icon  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

import tempfile  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402

s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 3)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
panel = m._panel
panel.show()
app.processEvents()

here = os.path.dirname(os.path.abspath(__file__))
panel.grab().save(os.path.join(here, "panel_zh.png"))

s.set("language", "en_US")
m.apply_settings()
app.processEvents()
panel.grab().save(os.path.join(here, "panel_en.png"))

s.set("language", "ja_JP")
m.apply_settings()
app.processEvents()
panel.grab().save(os.path.join(here, "panel_ja.png"))

# 设置窗口「关于」页也带 Logo / the About tab now carries the logo too
s.set("language", "zh_CN")
m.apply_settings()
m.open_settings()
w = m._settings_window
w.tabs.setCurrentIndex(5)
w.show()
app.processEvents()
w.grab().save(os.path.join(here, "settings_about.png"))

print("saved panel_zh/en/ja.png + settings_about.png", flush=True)
m.quit()
