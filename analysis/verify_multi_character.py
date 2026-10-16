# -*- coding: utf-8 -*-
"""实测多角色共存：到底能不能召唤出「不同角色」的宠物。

同时验证新的面板角色下拉框（1.0.7-2 新增）。
"""
import os
import shutil
import sys
import tempfile

# 从脚本位置反推仓库根 —— **不要写死 `E:\shimejee-remake`**：
# 换台机器、换个盘符、或者把仓库 clone 到别处，这个脚本就直接失效；
# 而且它是「跑测试」的第一步，路径错了后面全废。
# Derive the repo root from this file's location.  Never hard-code a drive
# letter: the script dies on any other machine, and this is step one -- a
# wrong root makes everything after it meaningless.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

from shimeji.engine.manager import Manager
from shimeji.engine.environment import Pt
from shimeji.settings import Settings

FAILS = []
PASSES = 0


def check(cond, msg, detail=""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(t):
    print("\n--- %s ---" % t, flush=True)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="utopet_multi_")
    try:
        s = Settings(os.path.join(tmp, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("multi_pet_enabled", True)
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        wa = mgr.shared_env.work_area

        section("多角色：list_characters 列出全部角色")
        from shimeji.engine.manager import list_characters
        chars = list_characters(s)
        labels = [lb for lb, _ in chars]
        print("   可用角色:", labels, flush=True)
        check(len(labels) >= 2, "至少有两个角色可召唤", str(labels))

        section("多角色：summon_character 真的召唤出不同角色")
        m1 = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m1 is not None, "召唤第一只（默认角色）")
        check(m1.bundle.label == "Miku", "第一只是 Miku", m1.bundle.label)

        other = next((lb for lb in labels if lb != "Miku"), None)
        check(other is not None, "找到一个非默认角色", str(other))
        m2 = mgr.summon_character(other)
        check(m2 is not None, "summon_character() 成功召唤另一个角色",
              str(other))
        check(m2 is not None and m2.bundle.label == other,
              "召唤出来的确实是那个角色",
              m2.bundle.label if m2 else "None")
        check(m1.bundle.images is not m2.bundle.images,
              "两只宠物用的是**各自的**图片集（不是同一份）")

        section("托盘菜单里会出现「召唤其他角色」子菜单")
        menu = mgr._build_main_menu()
        found = [a.text() for a in menu.actions() if a.menu() is not None]
        print("   子菜单:", found, flush=True)
        check(any("角色" in f for f in found),
              "主菜单里有「召唤其他角色」子菜单", str(found))
        sub = next((a.menu() for a in menu.actions()
                    if a.menu() is not None and "角色" in a.text()), None)
        if sub is not None:
            items = [a.text() for a in sub.actions()]
            print("   子菜单项:", items, flush=True)
            check(len(items) >= 1, "子菜单里有可选项（已排除屏幕上的角色）",
                  str(items))
            # 真的点一下第一项
            sub.actions()[0].trigger()
            check(any(m.bundle.label == items[0] for m in mgr.mascots),
                  "点子菜单项真的召唤出了对应角色",
                  str([m.bundle.label for m in mgr.mascots]))

        section("面板：新增角色下拉框，且在数字选框**之前**")
        from shimeji.gui.taskbar_panel import TaskbarPanel
        panel = TaskbarPanel(mgr)
        check(hasattr(panel, "char_combo"), "面板有角色下拉框（char_combo）")
        if hasattr(panel, "char_combo"):
            items = [panel.char_combo.itemText(i) for i in
                     range(panel.char_combo.count())]
            print("   下拉框项:", items, flush=True)
            check(len(items) >= 2, "下拉框列出了所有角色", str(items))
            check("Miku" in items, "下拉框含当前默认角色 Miku", str(items))
            # 顺序：下拉框必须在 count 输入框之前。面板有多个 QHBoxLayout，
            # 逐个找包含这两个控件的那个，再按下标比先后。
            from PySide6.QtWidgets import QSpinBox, QHBoxLayout
            spin_at = combo_at = -1
            for box in panel.findChildren(QHBoxLayout):
                for i in range(box.count()):
                    w = box.itemAt(i).widget()
                    if w is None:
                        continue
                    if isinstance(w, QSpinBox):
                        spin_at = i
                    if w is panel.char_combo:
                        combo_at = i
            print("   下拉框位置 %d，数量框位置 %d" % (combo_at, spin_at),
                  flush=True)
            check(combo_at >= 0 and spin_at >= 0 and combo_at < spin_at,
                  "角色下拉框在数量选框**之前**",
                  "combo=%d spin=%d" % (combo_at, spin_at))

        section("面板下拉框：选角色后点召唤，召唤出该角色")
        if hasattr(panel, "char_combo"):
            other2 = next((lb for lb in labels if lb != "Miku"), None)
            i = panel.char_combo.findData(other2) if other2 else -1
            if i < 0:
                i = panel.char_combo.findText(other2 or "")
            check(i >= 0, "下拉框里能找到另一个角色",
                  "other=%s i=%d" % (other2, i))
            if i >= 0:
                # 把数量设成 2，断言「恰好 2 只、且都是选中的那个角色」。
                # 默认 summon_count 是 5，用 2 才能区分「批量生效」与「漏传角色」。
                panel.summon_spin.setValue(2)
                before = [m.bundle.label for m in mgr.mascots]
                panel.char_combo.setCurrentIndex(i)
                panel.btn_summon.click()
                after = [m.bundle.label for m in mgr.mascots]
                check(len(after) == len(before) + 2,
                      "点了召唤按数量批量 +2", "%s -> %s" % (before, after))
                new_ones = [lb for lb in after[len(before):]]
                check(new_ones and set(new_ones) == {other2},
                      "新召唤的都是下拉框里选的那个角色",
                      "new=%s want=%s" % (new_ones, other2))

        mgr.quit()

        section("只有一个角色时下拉框隐藏，召唤仍正常")
        import shimeji.engine.manager as _mgr_mod
        solo = tempfile.mkdtemp(prefix="utopet_solo_")
        try:
            solo_chars = os.path.join(solo, "chars")
            shutil.copytree(os.path.join(ROOT, "characters", "Miku"),
                            os.path.join(solo_chars, "Miku"))
            old_dir = _mgr_mod.CHARACTERS_DIR
            _mgr_mod.CHARACTERS_DIR = solo_chars
            try:
                s2 = Settings(os.path.join(solo, "settings.json"))
                s2.set("character", "Miku")
                s2.set("taskbar_panel", False)
                s2.set("multi_pet_enabled", True)
                mgr2 = Manager(app, s2)
                mgr2.timer.stop()
                mgr2.dismiss_all()
                p2 = TaskbarPanel(mgr2)
                check(p2.char_combo.count() == 1, "只有一个角色", str(p2.char_combo.count()))
                check(not p2.char_combo.isVisible(),
                      "只有一个角色时下拉框隐藏（一个选项的下拉框只是噪音）")
                n_before = len(mgr2.mascots)
                p2.summon_spin.setValue(1)
                p2.btn_summon.click()
                check(len(mgr2.mascots) == n_before + 1,
                      "下拉框隐藏时召唤仍然正常（走默认角色）",
                      "%d -> %d" % (n_before, len(mgr2.mascots)))
                mgr2.quit()
            finally:
                _mgr_mod.CHARACTERS_DIR = old_dir
        finally:
            shutil.rmtree(solo, ignore_errors=True)

        section("运行时新增角色目录 → 下拉框自动更新")
        extra = tempfile.mkdtemp(prefix="utopet_extra_")
        try:
            # 造一个全局目录里**没有**的角色名，才能验证「真的新增了一项」
            src = os.path.join(ROOT, "characters", "花卷")
            dst = os.path.join(extra, "测试角色")
            shutil.copytree(src, dst)
            s3 = Settings(os.path.join(tmp, "settings.json"))
            s3.set("character", "Miku")
            s3.set("taskbar_panel", False)
            s3.set("multi_pet_enabled", True)
            s3.set("character_dirs", [])
            mgr3 = Manager(app, s3)
            mgr3.timer.stop()
            mgr3.dismiss_all()
            p3 = TaskbarPanel(mgr3)
            base = [p3.char_combo.itemText(i) for i in range(p3.char_combo.count())]
            print("   初始:", base, flush=True)
            check("测试角色" not in base, "初始不含新角色", str(base))
            s3.set("character_dirs", [extra])
            p3.refresh_status()          # 500ms 轮询会调到这里
            now = [p3.char_combo.itemText(i) for i in range(p3.char_combo.count())]
            print("   加目录后:", now, flush=True)
            check("测试角色" in now, "新增角色目录后下拉框立刻出现该角色", str(now))
            check(len(now) == len(set(now)),
                  "下拉框里没有重复条目（同名角色按显示名去重）", str(now))
            mgr3.quit()
        finally:
            shutil.rmtree(extra, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 40)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES))
        for f in FAILS:
            print("  x", f)
        sys.stdout.flush()
        os._exit(1)
    print("ALL PASS —— %d 项检查通过" % PASSES)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
