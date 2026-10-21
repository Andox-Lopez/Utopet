# -*- coding: utf-8 -*-
"""验证 1.1.1 的右键菜单外观功能：尺寸 / 透明度 / 鼠标穿透。

为什么单独一个文件：这三项是「菜单 → 立即生效 → 写回设置」的完整链路，
每一步都能单独出错，而出错时**不抛异常**（Qt 槽里的异常会被静默吞掉，
整个槽中断）。所以这里断言的是「效果」而不是「没抛异常」。

要验的四件事：
  1. 菜单里真的有这三个入口，且当前值有勾（用户能看出现在是什么状态）
  2. 点了之后**立刻**生效：窗口尺寸 / 窗口透明度 / 穿透属性
  3. 改动写回设置：重启后还在，新召唤的宠物也继承
  4. 穿透开着时**还有办法关掉**（这是唯一「开了就够不着自己」的开关）

用法：python analysis/verify_menu_appearance.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def find_menu(menu, title: str):
    """在菜单里找标题匹配的子菜单 / find a sub-menu by its title."""
    for act in menu.actions():
        sub = act.menu()
        if sub is not None and sub.title() == title:
            return sub
    return None


def find_action(menu, title: str):
    for act in menu.actions():
        if act.text() == title:
            return act
    return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # 关键：配置写到**临时目录**。这个测试会反复改 scale / opacity /
    # click_through 并 save()，用默认路径就是拿用户的真实 settings.json
    # 当草稿纸 —— 跑一次测试把人家调好的外观全改了。
    # The settings file must live in a temp directory: this test changes
    # scale / opacity / click-through and saves repeatedly.  With the default
    # path it would use the user's real settings.json as scratch paper and
    # quietly wreck the look they had tuned.
    tmpdir = tempfile.mkdtemp(prefix="utopet_menu_test_")
    s = Settings(os.path.join(tmpdir, "settings.json"))
    s.set("restore_session", False)
    s.set("initial_count", 2)
    s.set("taskbar_panel", False)
    m = Manager(app, s)
    app.processEvents()

    t = get_i18n()
    print(f"\n宠物数 = {len(m.mascots)}\n", flush=True)

    # ------------------------------------------------------------------
    print("--- 1. 菜单里有三个外观入口 ---", flush=True)
    menu = m._build_main_menu(m.mascots[0])
    app_sub = find_menu(menu, t.t("menu.appearance"))
    check(app_sub is not None, "主菜单里有「外观与交互」子菜单")
    if app_sub is None:
        # 不早退：继续跑完其余检查，让「旧代码下失败」列出**全部**缺失点，
        # 而不是只报第一条 —— 那样才知道每条断言都有鉴别力。
        # No early exit: run the rest so that running against the old code
        # lists *every* missing piece, not just the first.  Otherwise there is
        # no way to tell whether each assertion can actually catch a
        # regression.
        app_sub = QMenu()
        menu.addMenu(app_sub)

    size_sub = find_menu(app_sub, t.t("menu.pet_size"))
    op_sub = find_menu(app_sub, t.t("menu.pet_opacity"))
    check(size_sub is not None, "有「宠物尺寸」子菜单")
    check(op_sub is not None, "有「宠物透明度」子菜单")
    through_act = find_action(app_sub, t.t("menu.click_through"))
    check(through_act is not None, "有「鼠标穿透」开关项")
    check(through_act is not None and through_act.isCheckable(),
          "「鼠标穿透」是可勾选的开关（不是一次性动作）")

    print("\n--- 2. 当前值在菜单上有勾（用户能看出状态）---", flush=True)
    if size_sub is not None:
        checked = [a.text() for a in size_sub.actions() if a.isChecked()]
        check(len(checked) == 1,
              f"尺寸档位里恰好一个勾（当前 {checked}）")
    if op_sub is not None:
        checked = [a.text() for a in op_sub.actions() if a.isChecked()]
        check(len(checked) == 1,
              f"透明度档位里恰好一个勾（当前 {checked}）")

    # ------------------------------------------------------------------
    print("\n--- 3. 改尺寸：立刻生效 + 写回设置 ---", flush=True)
    mascot = m.mascots[0]
    # 先给宠物装一帧，否则它的窗口还是 QWidget 的默认尺寸（640x480），
    # 跟倍率无关 —— 那时量窗口大小量不到东西。真实运行时宠物一直在播动作，
    # 永远有帧。
    # Give the pet a frame first: without one its window is still QWidget's
    # default size (640x480) and says nothing about the scale.  A running pet
    # always has a frame.
    mascot.set_image("shime1.png")
    app.processEvents()
    # 原图尺寸（像素）—— 窗口尺寸应当正好是它乘以倍率。
    # The source image size: the window must be exactly that times the scale.
    src = mascot.images.get("shime1.png")
    src_w = src.width() if src else 0
    src_h = src.height() if src else 0
    check(src_w > 0, f"拿到了原图尺寸（{src_w}x{src_h}px）")
    if not hasattr(m, "set_pet_scale"):
        check(False, "Manager.set_pet_scale 存在（1.1.1 新增）")
        print("\n" + "=" * 56, flush=True)
        print("FAILED: 1.1.1 的接口不存在，后续检查无法进行", flush=True)
        return 1
    m.set_pet_scale(2.0, mascot)
    app.processEvents()
    check(mascot.scale == 2.0, f"宠物的 scale 变成 2.0（当前 {mascot.scale}）")
    check(mascot.width() == src_w * 2 and mascot.height() == src_h * 2,
          f"窗口尺寸 = 原图 × 2.0（期望 {src_w * 2}x{src_h * 2}px，"
          f"实际 {mascot.width()}x{mascot.height()}）")
    check(abs(float(s.get("scale", 1.0)) - 2.0) < 1e-6,
          f"设置里的 scale 写回了 2.0（当前 {s.get('scale')}）")

    # 菜单重开后，勾应该落在新档位上
    menu2 = m._build_main_menu(mascot)
    app_sub2 = find_menu(menu2, t.t("menu.appearance"))
    size_sub2 = find_menu(app_sub2, t.t("menu.pet_size"))
    checked2 = [a.text() for a in size_sub2.actions() if a.isChecked()]
    check(len(checked2) == 1 and "200" in checked2[0],
          f"重开菜单后勾落在 200% 上（当前 {checked2}）")

    print("\n--- 4. 改透明度：立刻生效 + 写回设置 ---", flush=True)
    # 容差 0.01：Windows 的窗口不透明度是 8 位 alpha（0.5 -> 127/255 = 0.498），
    # 这是平台量化，不是我们的 bug。断言 1e-3 会假红。
    # Tolerance 0.01: Windows window opacity is 8-bit alpha (0.5 -> 127/255 =
    # 0.498).  That is platform quantisation, not a bug; 1e-3 would be a false
    # red.
    m.set_pet_opacity(0.5, mascot)
    app.processEvents()
    check(abs(mascot.windowOpacity() - 0.5) < 0.01,
          f"窗口透明度变成 0.5（当前 {mascot.windowOpacity()}）")
    check(abs(float(s.get("opacity", 1.0)) - 0.5) < 1e-6,
          f"设置里的 opacity 写回了 0.5（当前 {s.get('opacity')}）")

    print("\n--- 5. 鼠标穿透：开关真的切属性 ---", flush=True)
    check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is False,
          "初始未开启穿透")
    m.set_click_through(True, mascot)
    app.processEvents()
    check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is True,
          "开启后 WA_TransparentForMouseEvents 为真")
    check(s.get("click_through") is True, "设置里的 click_through 写回了 True")

    # 关键：开着穿透时，勾选状态仍要正确显示（用户能从菜单看出它是开的）
    menu3 = m._build_main_menu(mascot)
    app_sub3 = find_menu(menu3, t.t("menu.appearance"))
    through_act3 = find_action(app_sub3, t.t("menu.click_through"))
    check(through_act3 is not None and through_act3.isChecked(),
          "重开菜单时穿透项显示为已勾选")

    m.set_click_through(False, mascot)
    app.processEvents()
    check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is False,
          "关闭后穿透属性回到假")

    # ------------------------------------------------------------------
    print("\n--- 6. 作用于一只 vs 作用于全部 ---", flush=True)
    m.set_pet_scale(1.0, m.mascots[0])
    m.set_pet_scale(1.0, m.mascots[1])
    m.set_pet_scale(1.5, m.mascots[0])
    app.processEvents()
    check(m.mascots[0].scale == 1.5, "指定的那只被改了尺寸")
    check(m.mascots[1].scale == 1.0, "没指定的另一只保持原样")
    m.set_pet_scale(2.0, None)     # None = 全部
    app.processEvents()
    check(all(x.scale == 2.0 for x in m.mascots),
          f"传 None 时全部都改了（{[x.scale for x in m.mascots]}）")

    print("\n--- 7. 新召唤的宠物继承当前设置 ---", flush=True)
    m.set_pet_scale(1.25, None)
    m.set_pet_opacity(0.7, None)
    m.set_click_through(True, None)
    new_m = m.summon()
    app.processEvents()
    check(new_m is not None, "召唤成功")
    if new_m is not None:
        check(abs(new_m.scale - 1.25) < 1e-6,
              f"新宠物继承了尺寸 1.25（当前 {new_m.scale}）")
        check(abs(new_m.windowOpacity() - 0.7) < 0.01,
              f"新宠物继承了透明度 0.7（当前 {new_m.windowOpacity()}）")
        check(new_m.testAttribute(Qt.WA_TransparentForMouseEvents) is True,
              "新宠物继承了穿透状态")
    m.set_click_through(False, None)

    # ------------------------------------------------------------------
    print("\n--- 8. 穿透开着时还有办法关掉（不会把自己困住）---", flush=True)
    m.set_click_through(True, None)
    app.processEvents()
    # 托盘菜单（mascot=None）必须能反映并改变全局状态
    tray_menu = m._build_main_menu(None)
    tray_app = find_menu(tray_menu, t.t("menu.appearance"))
    tray_act = find_action(tray_app, t.t("menu.click_through"))
    check(tray_act is not None, "托盘菜单里也有穿透开关")
    check(tray_act is not None and tray_act.isChecked(),
          "托盘菜单显示穿透已开启")
    m.set_click_through(False, None)
    app.processEvents()
    check(all(not x.testAttribute(Qt.WA_TransparentForMouseEvents)
              for x in m.mascots),
          "从托盘路径可以关掉穿透")

    # 设置窗口里有同名开关（第三道退路）
    s.set("click_through", True)
    m.apply_settings()
    app.processEvents()
    check(all(x.testAttribute(Qt.WA_TransparentForMouseEvents)
              for x in m.mascots),
          "设置里勾上后，apply_settings 会应用到所有宠物")
    s.set("click_through", False)
    m.apply_settings()
    app.processEvents()

    # ------------------------------------------------------------------
    print("\n--- 9. 尺寸改动不再需要重启（不该解散宠物）---", flush=True)
    before = m.count()
    s.set("scale", 1.75)
    m.apply_settings(need_restart=False)
    app.processEvents()
    check(m.count() == before,
          f"apply_settings 没有解散宠物（{before} -> {m.count()}）")
    check(all(abs(x.scale - 1.75) < 1e-6 for x in m.mascots),
          f"所有宠物的尺寸都更新了（{[x.scale for x in m.mascots]}）")

    print("\n--- 9b. 设置窗口开着时，菜单改的值要同步到设置页 ---", flush=True)
    # 「幽灵数值」是最难缠的失败模式：设置窗口已经开着，用户从右键菜单改了
    # 尺寸，那个 spin 还停在旧值，用户随手一点「应用」就把改动覆盖回去 ——
    # 菜单的功能看起来「时灵时不灵」。
    # The stale-widget failure mode: with the settings window open, a spinner
    # still showing the old value reverts the change the moment the user hits
    # Apply, and the menu feature looks "flaky".
    m.open_settings()
    app.processEvents()
    win = m._settings_window
    check(win is not None, "设置窗口打开了")
    m.set_pet_scale(1.25, None)
    app.processEvents()
    check(abs(win.scale_spin.value() - 1.25) < 1e-6,
          f"设置页的缩放框跟着更新（当前 {win.scale_spin.value()}）")
    m.set_pet_opacity(0.7, None)
    app.processEvents()
    check(abs(win.opacity_spin.value() - 0.7) < 1e-6,
          f"设置页的不透明度框跟着更新（当前 {win.opacity_spin.value()}）")
    m.set_click_through(True, None)
    app.processEvents()
    check(win.through.isChecked() is True,
          "设置页的穿透开关跟着勾上")
    m.set_click_through(False, None)
    app.processEvents()
    check(win.through.isChecked() is False,
          "设置页的穿透开关跟着取消")
    win.close()
    app.processEvents()

    print("\n--- 10. 三语文案齐全 ---", flush=True)
    for lang in ("zh_CN", "en_US", "ja_JP"):
        from shimeji.i18n import I18n
        tab = I18n(lang)
        for key in ("menu.appearance", "menu.pet_size", "menu.pet_opacity",
                    "menu.click_through", "menu.click_through_hint",
                    "lbl.click_through", "panel.click_through"):
            val = tab.t(key, "")
            check(bool(val) and val != key, f"{lang}: {key} 有文案")

    m.quit()
    print("\n" + "=" * 56, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print("ALL PASS —— 右键菜单的尺寸/透明度/穿透全部到位", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
