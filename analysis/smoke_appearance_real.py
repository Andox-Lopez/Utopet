# -*- coding: utf-8 -*-
"""真实窗口下的冒烟测试：程序起得来，菜单能弹，三项开关都真生效。

与 verify_menu_appearance.py 的区别：那个用 offscreen 平台（无头，纯逻辑），
这个用**真实窗口**（QT_QPA_PLATFORM 被清掉），验证的是「菜单真的能显示出来、
点了真的有反应」——离屏平台上的 QMenu 不会真正显示，那个是测不出来的。

用法：python analysis/smoke_appearance_real.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 必须用真实窗口：offscreen 下 QMenu 不会显示，测不到「菜单弹出来了」
# Real windows are required: under offscreen a QMenu never shows, so "the
# menu pops up" cannot be tested there.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QActionGroup  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def find_menu(menu, title):
    for act in menu.actions():
        sub = act.menu()
        if sub is not None and sub.title() == title:
            return sub
    return None


def find_action(menu, title):
    for act in menu.actions():
        if act.text() == title:
            return act
    return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tmp = tempfile.mkdtemp(prefix="utopet_smoke_real_")
    s = Settings(os.path.join(tmp, "settings.json"))
    s.set("restore_session", False)
    s.set("initial_count", 1)
    s.set("taskbar_panel", True)
    m = Manager(app, s)
    app.processEvents()

    t = get_i18n()
    mascot = m.mascots[0]
    mascot.set_image("shime1.png")
    app.processEvents()

    print("\n--- 1. 真实窗口下菜单能显示出来 ---", flush=True)
    menu = m._build_main_menu(mascot)
    menu.show()
    app.processEvents()
    check(menu.isVisible(), "主菜单在真实窗口下可见")
    check(menu.size().width() > 0 and menu.size().height() > 0,
          f"菜单有实际尺寸（{menu.size().width()}x{menu.size().height()}）")

    app_sub = find_menu(menu, t.t("menu.appearance"))
    check(app_sub is not None, "「外观与交互」子菜单存在")
    if app_sub is not None:
        app_sub.show()
        app.processEvents()
        check(app_sub.isVisible(), "子菜单也能显示出来")
        check(len(app_sub.actions()) >= 3,
              f"子菜单里至少三项（{len(app_sub.actions())}）")

    print("\n--- 2. 菜单项真的能触发（模拟点击）---", flush=True)
    size_sub = find_menu(app_sub, t.t("menu.pet_size"))
    if size_sub is not None:
        # 找 200% 那一项并触发它
        target = None
        for act in size_sub.actions():
            if "200" in act.text():
                target = act
                break
        check(target is not None, "尺寸子菜单里找得到 200%")
        if target is not None:
            target.trigger()
            app.processEvents()
            check(abs(mascot.scale - 2.0) < 1e-6,
                  f"点了 200% 之后宠物真的变成 2.0 倍（当前 {mascot.scale}）")

    op_sub = find_menu(app_sub, t.t("menu.pet_opacity"))
    if op_sub is not None:
        target = None
        for act in op_sub.actions():
            if act.text().strip() == "50%":
                target = act
                break
        check(target is not None, "透明度子菜单里找得到 50%")
        if target is not None:
            target.trigger()
            app.processEvents()
            check(abs(mascot.windowOpacity() - 0.5) < 0.01,
                  f"点了 50% 之后窗口透明度真的变了"
                  f"（当前 {mascot.windowOpacity()}）")

    through = find_action(app_sub, t.t("menu.click_through"))
    if through is not None:
        check(through.isChecked() is False, "穿透项初始未勾选")
        through.trigger()
        app.processEvents()
        check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is True,
              "点了一下，宠物窗口真的变成对鼠标透明了")
        through.trigger()
        app.processEvents()
        check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is False,
              "再点一下，又能点到了")

    menu.close()
    app.processEvents()

    print("\n--- 3. 托盘菜单也能用（穿透的回头路）---", flush=True)
    tray_menu = m._build_main_menu(None)
    tray_menu.show()
    app.processEvents()
    check(tray_menu.isVisible(), "托盘菜单可见")
    tray_app = find_menu(tray_menu, t.t("menu.appearance"))
    check(tray_app is not None, "托盘菜单里也有「外观与交互」")
    tray_menu.close()
    app.processEvents()

    m.quit()
    print("\n" + "=" * 56, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print("ALL PASS —— 真实窗口下菜单与三项开关均正常", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
