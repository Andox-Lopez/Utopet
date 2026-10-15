# -*- coding: utf-8 -*-
"""1.0.8 回归：气泡台词 / 番茄钟统计 / 角色库管理。"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

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


def _group_titles(window, tab_index):
    """某一页上的分组框标题 / The group-box titles on one tab."""
    from PySide6.QtWidgets import QGroupBox
    page = window.tabs.widget(tab_index)
    return [g.title() for g in page.findChildren(QGroupBox)]


# =====================================================================
def test_serifu_logic():
    from shimeji.serifu import BUILTIN_PHRASES, Serifu

    section("台词库：来源优先级")
    tmp = tempfile.mkdtemp(prefix="utopet_serifu_")
    try:
        # 1) 内置兜底
        s = Serifu(None)
        check(len(s.global_phrases()) == 0, "没给设置时全局台词为空")
        check(s.phrases_for(None) == list(BUILTIN_PHRASES),
              "什么都没有时用内置台词")

        # 2) 全局台词库
        from shimeji.settings import Settings
        sp = os.path.join(tmp, "settings.json")
        cfg = Settings(sp)
        cfg.set("serifu_phrases", ["你好", "  ", "在忙吗？"])
        s2 = Serifu(cfg)
        check(s2.global_phrases() == ["你好", "在忙吗？"],
              "全局台词去掉空行", str(s2.global_phrases()))
        check(s2.phrases_for(None) == ["你好", "在忙吗？"],
              "没有角色台词时用全局台词库")

        # 3) 角色自带 wins
        char = os.path.join(tmp, "P1", "conf")
        os.makedirs(char)
        with open(os.path.join(char, "serifu.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("# 注释要跳过\n\n角色专属第一句\n角色专属第二句\n")

        class _B:
            label = "P1"
            directory = os.path.join(tmp, "P1")
        got = s2.load_from_dir(_B.directory)
        check(got == ["角色专属第一句", "角色专属第二句"],
              "读角色自带 serifu.txt，跳过注释与空行", str(got))
        check(s2.phrases_for(_B()) == got,
              "角色自带台词**优先于**全局台词库")

        # 4) 大写 SERIFU 也认（原版命名）
        char2 = os.path.join(tmp, "P2")
        os.makedirs(os.path.join(char2, "conf"))
        with open(os.path.join(char2, "conf", "SERIFU.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("原版大写文件名\n")
        check(s2.load_from_dir(char2) == ["原版大写文件名"],
              "认原版的大写 SERIFU.txt")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    section("台词库：挑选与触发判定")
    pool = ["A", "B", "C"]
    s3 = Serifu(None)
    picks = [s3.pick(pool) for _ in range(12)]
    check(all(p in pool for p in picks), "挑出来的都在候选里", str(set(picks)))
    check(len(set(picks)) >= 2, "不会连续 12 句都一样", str(set(picks)))
    check(s3.pick([]) != "", "候选为空时回落到内置，不会「什么都不说」")

    # 原版行为名五花八门，按包含判断
    for name in ("serifu", "SERIFU", "serifu 2", "セリフ", "せりふ",
                 "セリフ（(random)）", "Speech", "balloon"):
        check(Serifu.is_trigger(name), "触发词命中：%s" % name)
    for name in ("歩く", "座る", "分裂した", None, ""):
        check(not Serifu.is_trigger(name), "普通行为不触发：%s" % name)

    section("台词库：配置读取与夹取")
    from shimeji.settings import Settings
    tmp = tempfile.mkdtemp(prefix="utopet_serifu2_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("serifu_enabled", True)
        cfg.set("serifu_seconds", 999)      # 越界
        cfg.set("serifu_interval", -5)      # 负数
        cfg.set("serifu_font_px", 999)
        s4 = Serifu(cfg)
        check(s4.enabled() is True, "启用状态读得到")
        check(s4.duration_ms() == 60000, "停留秒数夹到上限 60", str(s4.duration_ms()))
        check(s4.interval_ms() == 0, "负数间隔夹到 0（= 不定时）",
              str(s4.interval_ms()))
        check(s4.font_px() == 32, "字号夹到上限 32", str(s4.font_px()))
        cfg.set("serifu_enabled", False)
        check(Serifu(cfg).enabled() is False, "关闭后 enabled 为假")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_serifu_window(app):
    from PySide6.QtCore import Qt
    from shimeji.serifu import Serifu
    from shimeji.gui.balloon import Balloon

    section("气泡窗口：窗口属性与跟随")
    b = Balloon(Serifu(None))
    check(b.testAttribute(Qt.WA_TransparentForMouseEvents),
          "气泡不吃鼠标点击（飘在桌面上不能挡住下面的东西）")
    check(b.testAttribute(Qt.WA_ShowWithoutActivating),
          "气泡不抢焦点（否则用户打字会被打断）")
    check(not b.say(""), "空台词不显示")
    check(b.say("你好"), "有台词才显示")
    check(b.text == "你好", "记下了台词")
    b.hide_()
    check(not b.isVisible(), "到时收起")

    # 跟随：宠物移动后气泡要跟着
    from shimeji.engine.manager import Manager
    from shimeji.engine.environment import Pt
    from shimeji.settings import Settings
    tmp = tempfile.mkdtemp(prefix="utopet_balloon_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("character", "Miku")
        cfg.set("taskbar_panel", False)
        mgr = Manager(app, cfg)
        mgr.timer.stop()
        mgr.dismiss_all()
        wa = mgr.shared_env.work_area
        pet = mgr.summon(Pt(wa.left + 400, wa.bottom))
        check(pet is not None, "召唤一只用于跟随测试")
        b2 = mgr._balloon_window()
        check(b2.say("跟我走", pet), "Manager 的气泡窗口能说话")
        x1 = b2.x()
        pet.move(400, 200)
        app.processEvents()
        b2.follow()
        check(b2.x() != x1, "宠物移动后气泡跟着移动", "%d -> %d" % (x1, b2.x()))
        check(b2.y() < pet.y(), "气泡在宠物头顶上方", "b=%d pet=%d" % (b2.y(), pet.y()))
        mgr.quit()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pomodoro_stats():
    from shimeji.pomodoro_stats import PomodoroStats

    section("番茄钟统计")
    d = tempfile.mkdtemp(prefix="utopet_stats_")
    try:
        s = PomodoroStats(data_dir=d)
        check(s.summary()["completed"] == 0, "新文件从零开始")
        s.record(focus_sec=1500)
        s.record(focus_sec=1500)
        s.record(focus_sec=600)
        got = s.summary()
        check(got["completed"] == 3, "完成数累加", str(got["completed"]))
        check(got["focus_sec"] == 3600, "专注时长累加", str(got["focus_sec"]))
        check("3 个" in s.today_text(), "今日文案含完成数", s.today_text())
        check(s.total()["completed"] == 3, "合计正确")

        # 持久化：重新构造后数据还在
        s2 = PomodoroStats(data_dir=d)
        check(s2.summary()["completed"] == 3, "重新加载后数据仍在（原子写入生效）")
        check(s2.streak() == 1, "今天完成过 → 连续 1 天")

        # 坏文件不能带崩程序
        with open(os.path.join(d, "pomodoro_stats.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ 这不是 json")
        s3 = PomodoroStats(data_dir=d)
        check(s3.summary()["completed"] == 0,
              "统计文件损坏时当作从零开始（不该拖垮启动）")

        # 只保留最近 30 天
        d2 = tempfile.mkdtemp(prefix="utopet_stats2_")
        try:
            s4 = PomodoroStats(data_dir=d2)
            for i in range(40):
                s4._data["2026-01-%02d" % (i + 1)] = {"completed": 1,
                                                       "focus_sec": 60}
            s4._prune()
            check(len(s4._data) == 30, "只保留最近 30 天", str(len(s4._data)))
        finally:
            shutil.rmtree(d2, ignore_errors=True)

        s.clear()
        check(s.summary()["completed"] == 0, "清空后归零")
        check(not os.path.exists(os.path.join(d, "pomodoro_stats.json")),
              "清空把文件也删了")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_library(app):
    from shimeji.engine.manager import list_characters
    from shimeji.settings import Settings

    section("角色库：停用后从所有选择器消失")
    tmp = tempfile.mkdtemp(prefix="utopet_lib_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("character", "Miku")
        cfg.set("taskbar_panel", False)
        all_names = [lb for lb, _ in list_characters(cfg)]
        check(len(all_names) >= 2, "至少两个角色", str(all_names))
        target = next(x for x in all_names if x != "Miku")
        cfg.set("disabled_chars", [target])
        shown = [lb for lb, _ in list_characters(cfg)]
        check(target not in shown, "停用的角色不出现在选择器里", str(shown))
        check("Miku" in shown, "其它角色不受影响", str(shown))
        listed_all = [lb for lb, _ in list_characters(cfg, include_disabled=True)]
        check(target in listed_all,
              "角色库管理页仍然能看到被停用的角色（否则没法启用回来）",
              str(listed_all))
        # 停用是纯设置操作，一个文件都不动
        check(os.path.isdir(os.path.join(ROOT, "characters", target)),
              "停用不删文件")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    section("角色库：设置页的表格与按钮")
    from shimeji.engine.manager import Manager
    from shimeji.gui.settings_window import SettingsWindow
    from PySide6.QtWidgets import QGroupBox, QTableWidget
    tmp = tempfile.mkdtemp(prefix="utopet_lib2_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("character", "Miku")
        cfg.set("taskbar_panel", False)
        mgr = Manager(app, cfg)
        mgr.timer.stop()
        mgr.dismiss_all()
        w = SettingsWindow(mgr)
        titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        check(w.tabs.count() == 8, "设置仍是 8 页", str(titles))
        check(w.t.t("tab.serifu") in titles, "气泡台词**独立成页**", str(titles))
        # 台词组必须**从「高级」页搬走了**，而不是在两处各建一份
        # （同一个 self.xxx 建两次 = 本项目吃过的两个大亏）
        adv = titles.index(w.t.t("tab.advanced"))
        check(w.t.t("grp.serifu") not in _group_titles(w, adv),
              "台词组不在「高级」页上（不是复制一份过去）",
              str(_group_titles(w, adv)))
        check(w.t.t("grp.serifu") in _group_titles(
                  w, titles.index(w.t.t("tab.serifu"))),
              "台词组在新页上", str(_group_titles(w, titles.index(w.t.t("tab.serifu")))))
        lib = getattr(w, "library", None)
        check(isinstance(lib, QTableWidget), "有角色库表格")
        if lib is not None:
            check(lib.rowCount() >= 2, "表格列出了全部已装角色",
                  str(lib.rowCount()))
            check(lib.columnCount() == 4, "四列（名称/图片数/来源/状态）",
                  str(lib.columnCount()))
            check(lib.verticalHeader().defaultSectionSize() >= 30,
                  "行高显式设过（默认行高塞不下内容）")
            names = [lib.item(r, 0).text() for r in range(lib.rowCount())]
            check("Miku" in names, "含默认角色", str(names))
            states = [lib.item(r, 3).text() for r in range(lib.rowCount())]
            check(all(s for s in states), "状态列有内容", str(states))
        check(hasattr(w, "_toggle_character") and hasattr(w, "_delete_character"),
              "有停用/启用与删除的处理函数")
        w.close()
        mgr._settings_window = None
        mgr.quit()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_settings_ui(app):
    from shimeji.pomodoro_stats import PomodoroStats
    from shimeji.engine.manager import Manager
    from shimeji.gui.settings_window import SettingsWindow
    from shimeji.settings import Settings
    from PySide6.QtWidgets import QGroupBox, QPlainTextEdit
    section("设置页：台词组与统计清空")
    tmp = tempfile.mkdtemp(prefix="utopet_serifu_ui_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("character", "Miku")
        cfg.set("taskbar_panel", False)
        mgr = Manager(app, cfg)
        mgr.timer.stop()
        mgr.dismiss_all()
        # 统计必须指到临时目录：默认的 DATA_DIR 是**真实的 data\**，
        # 测试往那里写会污染用户自己的番茄钟历史。
        # Point the stats at a temp dir: the default DATA_DIR is the real data
        # folder and writing there would pollute the user's own history.
        mgr.pomostats = PomodoroStats(data_dir=tmp)
        w = SettingsWindow(mgr)
        titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        groups = [g.title() for g in w.findChildren(QGroupBox)]
        check(w.t.t("grp.serifu") in
              _group_titles(w, titles.index(w.t.t("tab.serifu"))),
              "「气泡台词」页上有台词分组",
              str(_group_titles(w, titles.index(w.t.t("tab.serifu")))))
        check(hasattr(w, "serifu_enabled"), "有启用开关")
        check(hasattr(w, "serifu_phrases")
              and isinstance(w.serifu_phrases, QPlainTextEdit),
              "有台词库文本框")
        check(set(w.serifu_spins) == {"serifu_seconds", "serifu_interval",
                                      "serifu_font_px"},
              "三个时长/字号自旋框", str(sorted(w.serifu_spins)))

        # 写台词 → apply → 真正进设置
        w.serifu_phrases.setPlainText("第一句\n\n  第二句  \n")
        w.apply()
        check(cfg.get("serifu_phrases") == ["第一句", "第二句"],
              "台词库保存时去掉空行与首尾空白", str(cfg.get("serifu_phrases")))
        check(cfg.get("serifu_enabled") in (True, False),
              "启用开关被写回")

        check(hasattr(w, "_refresh_pomodoro_stats")
              and hasattr(w, "_clear_pomodoro_stats"),
              "有统计刷新与清空")
        mgr.pomostats.record(focus_sec=1500)
        w._refresh_pomodoro_stats()
        check("累计" in w.stats_label.text() and "1 个" in w.stats_label.text(),
              "统计标签含今日与累计", w.stats_label.text())
        w.close()
        mgr._settings_window = None
        mgr.quit()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wiring(app):
    from shimeji.pomodoro_stats import PomodoroStats
    section("接线：行为触发与番茄钟切换都会说话")
    from shimeji.engine.manager import Manager
    from shimeji.settings import Settings
    tmp = tempfile.mkdtemp(prefix="utopet_wire_")
    try:
        cfg = Settings(os.path.join(tmp, "settings.json"))
        cfg.set("character", "Miku")
        cfg.set("taskbar_panel", False)
        cfg.set("serifu_enabled", True)
        mgr = Manager(app, cfg)
        mgr.timer.stop()
        mgr.dismiss_all()
        mgr.pomostats = PomodoroStats(data_dir=tmp)   # 别写进真实 data\
        wa = mgr.shared_env.work_area
        from shimeji.engine.environment import Pt
        pet = mgr.summon(Pt(wa.left + 400, wa.bottom))
        check(pet is not None, "召唤一只")
        check(mgr.say(pet, "手动说一句"), "say() 直接说话")
        check(mgr._balloon.text == "手动说一句", "气泡显示该句")
        mgr.say(pet, "")
        check(mgr._balloon.text == "手动说一句", "空句不覆盖上一句")

        # 番茄钟切换 → 统计 + 气泡
        before = mgr.pomostats.summary()["completed"]
        mgr._on_pomodoro_event("work_done", mgr.pomodoro)
        after = mgr.pomostats.summary()["completed"]
        check(after == before + 1, "完成一段工作就记一次统计",
              "%d -> %d" % (before, after))
        check(mgr._balloon.isVisible(), "阶段切换时冒了一句")

        # 关闭开关后不再说话
        cfg.set("serifu_enabled", False)
        check(mgr.say(pet, "不该出现") is False, "关闭后 say() 直接拒绝")
        mgr.quit()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    test_serifu_logic()
    test_serifu_window(app)
    test_pomodoro_stats()
    test_library(app)
    test_settings_ui(app)
    test_wiring(app)

    print("=" * 44)
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
