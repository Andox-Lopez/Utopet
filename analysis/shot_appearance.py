# -*- coding: utf-8 -*-
"""给 1.1.1 的新外观菜单与任务栏面板出图。

用法：python analysis/shot_appearance.py
产物：appearance_menu_zh.png / _en.png / _ja.png / panel_zh.png
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# offscreen 平台缺 CJK 字体会渲染成方块，这里必须用真实窗口
# The offscreen platform lacks CJK fonts and renders tofu; use real windows.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="utopet_shot_")
s = Settings(os.path.join(tmp, "settings.json"))
s.set("initial_count", 2)
s.set("taskbar_panel", True)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
app.processEvents()

# 让宠物有一帧，窗口尺寸才是真的
for mas in m.mascots:
    mas.set_image("shime1.png")
app.processEvents()


def shot_menu(lang: str):
    get_i18n().set_language(lang)
    m.refresh_ui_texts()
    app.processEvents()
    menu = m._build_main_menu(m.mascots[0])
    menu.show()
    app.processEvents()
    # 主菜单整体
    menu.grab().save(os.path.join(here, "appearance_menu_%s.png" % lang))
    menu.hide()
    app.processEvents()

    # 「外观与交互」子菜单单独出图：它才是这次的重点
    t = get_i18n()
    app_sub = None
    for act in menu.actions():
        sub = act.menu()
        if sub is not None and sub.title() == t.t("menu.appearance"):
            app_sub = sub
            break
    if app_sub is None:
        return
    app_sub.show()
    app.processEvents()
    app_sub.grab().save(os.path.join(here, "appearance_sub_%s.png" % lang))

    # 再把「宠物尺寸」的档位展开，看看勾选状态长什么样
    for act in app_sub.actions():
        sub = act.menu()
        if sub is not None:
            sub.show()
            app.processEvents()
            sub.grab().save(os.path.join(here, "appearance_size_%s.png" % lang))
            sub.hide()
            break
    app_sub.hide()
    app.processEvents()


for lang in ("zh_CN", "en_US", "ja_JP"):
    shot_menu(lang)

# 面板（带新的「鼠标穿透」按钮）
get_i18n().set_language("zh_CN")
m.refresh_ui_texts()
panel = m._panel
panel.show()
app.processEvents()
panel.grab().save(os.path.join(here, "panel_zh.png"))

print("saved appearance_menu_zh/en/ja.png + panel_zh.png", flush=True)
m.quit()
