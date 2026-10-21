# -*- coding: utf-8 -*-
"""给设置窗口的「外观」页出图（含 1.1.1 新增的鼠标穿透开关）。

用法：python analysis/shot_settings_appearance.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="utopet_shot_settings_")
s = Settings(os.path.join(tmp, "settings.json"))
get_i18n().set_language("zh_CN")
m = Manager(app, s)
m.open_settings()
w = m._settings_window
w.show()
app.processEvents()

# 按**标签文本**找页签，不要用 count()-N 算术（页签数会变）
# Find the tab by its label, not by index arithmetic (the tab count changes).
for i in range(w.tabs.count()):
    if w.tabs.tabText(i) == get_i18n().t("tab.appearance"):
        w.tabs.setCurrentIndex(i)
        break
app.processEvents()
w.grab().save(os.path.join(here, "settings_appearance_zh.png"))

print("saved settings_appearance_zh.png", flush=True)
m.quit()
