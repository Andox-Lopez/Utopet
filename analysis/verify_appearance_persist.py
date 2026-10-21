# -*- coding: utf-8 -*-
"""端到端：用户右键改外观 → 立即生效 → 写进磁盘 → 重启后还在。

这是「功能真的能用」的那一层：前面的测试各自验证一段，这条把它们串起来，
并且**真的把配置写到磁盘再读回来** —— 写回内存不算数，用户重启就丢了。

用法：python analysis/verify_appearance_persist.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tmp = tempfile.mkdtemp(prefix="utopet_persist_")
    path = os.path.join(tmp, "settings.json")

    s = Settings(path)
    s.set("restore_session", False)
    s.set("initial_count", 1)
    s.set("taskbar_panel", False)
    m = Manager(app, s)
    app.processEvents()

    t = get_i18n()
    mascot = m.mascots[0]
    mascot.set_image("shime1.png")
    app.processEvents()

    print("\n--- 1. 用户在菜单里改了三项 ---", flush=True)
    menu = m._build_main_menu(mascot)
    app_sub = None
    for act in menu.actions():
        sub = act.menu()
        if sub is not None and sub.title() == t.t("menu.appearance"):
            app_sub = sub
            break
    check(app_sub is not None, "找到「外观与交互」子菜单")

    # 尺寸：点 150%
    size_sub = None
    op_sub = None
    for act in app_sub.actions():
        sub = act.menu()
        if sub is None:
            continue
        if sub.title() == t.t("menu.pet_size"):
            size_sub = sub
        elif sub.title() == t.t("menu.pet_opacity"):
            op_sub = sub
    check(size_sub is not None and op_sub is not None, "两个档位子菜单都在")

    target = None
    for act in size_sub.actions():
        if "150" in act.text():
            target = act
            break
    check(target is not None, "找得到 150% 那一档")
    if target is not None:
        target.trigger()
        app.processEvents()
    check(abs(mascot.scale - 1.5) < 1e-6,
          f"宠物立刻变成 1.5 倍（当前 {mascot.scale}）")

    # 透明度：点 70%
    target = None
    for act in op_sub.actions():
        if act.text().strip() == "70%":
            target = act
            break
    check(target is not None, "找得到 70% 那一档")
    if target is not None:
        target.trigger()
        app.processEvents()
    check(abs(mascot.windowOpacity() - 0.7) < 0.01,
          f"宠物立刻变透明（当前 {mascot.windowOpacity()}）")

    # 穿透：勾上
    through = None
    for act in app_sub.actions():
        if act.text() == t.t("menu.click_through"):
            through = act
            break
    check(through is not None, "找得到穿透开关")
    if through is not None:
        through.trigger()
        app.processEvents()
    check(mascot.testAttribute(Qt.WA_TransparentForMouseEvents) is True,
          "宠物立刻变成对鼠标透明")

    print("\n--- 2. 配置真的写进磁盘了 ---", flush=True)
    check(os.path.exists(path), f"配置文件存在（{path}）")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        check('"scale"' in raw, "磁盘上有 scale 键")
        check('"opacity"' in raw, "磁盘上有 opacity 键")
        check('"click_through"' in raw, "磁盘上有 click_through 键")
        # 用官方的解析器读（配置是带注释的 JSON，不能用裸 json.load）
        from shimeji import cfgfmt
        data = cfgfmt.loads_stripping_comments(raw)
        check(abs(float(data.get("scale", 1.0)) - 1.5) < 1e-6,
              f"读回来的 scale 是 1.5（当前 {data.get('scale')}）")
        check(abs(float(data.get("opacity", 1.0)) - 0.7) < 1e-6,
              f"读回来的 opacity 是 0.7（当前 {data.get('opacity')}）")
        check(data.get("click_through") is True,
              f"读回来的 click_through 是 True（当前 {data.get('click_through')}）")

    print("\n--- 3. 重启后还在（模拟新进程读同一份配置）---", flush=True)
    m.quit()
    app.processEvents()

    s2 = Settings(path)
    check(abs(float(s2.get("scale", 1.0)) - 1.5) < 1e-6,
          f"新进程读到的 scale 是 1.5（当前 {s2.get('scale')}）")
    check(abs(float(s2.get("opacity", 1.0)) - 0.7) < 1e-6,
          f"新进程读到的 opacity 是 0.7（当前 {s2.get('opacity')}）")
    check(s2.get("click_through") is True,
          f"新进程读到的 click_through 是 True（当前 {s2.get('click_through')}）")

    # 新起的 Manager 也要按这份配置来
    s2.set("restore_session", False)
    s2.set("taskbar_panel", False)
    m2 = Manager(app, s2)
    app.processEvents()
    check(len(m2.mascots) >= 1, "新进程的宠物起来了")
    if m2.mascots:
        mas2 = m2.mascots[0]
        check(abs(mas2.scale - 1.5) < 1e-6,
              f"新宠物按 1.5 倍出场（当前 {mas2.scale}）")
        check(abs(mas2.windowOpacity() - 0.7) < 0.01,
              f"新宠物按 0.7 透明度出场（当前 {mas2.windowOpacity()}）")
        check(mas2.testAttribute(Qt.WA_TransparentForMouseEvents) is True,
              "新宠物带着穿透状态出场")
    m2.quit()

    print("\n" + "=" * 56, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print("ALL PASS —— 改完立刻生效、写进磁盘、重启后还在", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
