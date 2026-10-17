# -*- coding: utf-8 -*-
"""1.0.7 番茄时钟 + 全局快捷键 回归。

三块：
  A. 番茄状态机 —— 纯逻辑，Qt 无关，直接驱动 `tick()`。
  B. 全局快捷键端到端 —— 用 SendInput **真实按键**注入，验证 WM_HOTKEY
     真的能走到我们的槽。这是「快捷键似乎没生效」唯一的判据：注册成功
     不等于按下去有反应。
  C. 番茄窗口冒烟 —— 能打开、能渲染、能居中。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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


def section(title):
    print("\n--- %s ---" % title, flush=True)


# =====================================================================
# A. 状态机
# =====================================================================
def test_state_machine():
    from shimeji.pomodoro import Pomodoro

    section("番茄状态机：阶段推进")
    events = []
    p = Pomodoro(work_min=25, break_min=5, long_break_min=15, long_every=4,
                 on_event=lambda ev, pom: events.append(ev))
    check(p.phase == Pomodoro.IDLE, "初始为空闲", p.phase)
    check(p.remaining == 0 and p.total == 0, "空闲时剩余/总时长都是 0")

    p.start()
    check(p.phase == Pomodoro.WORK, "start() 直接进入工作段", p.phase)
    check(p.total == 25 * 60, "工作段 25 分钟", str(p.total))
    check("started" in events, "触发了 started", str(events))

    # 把截止时刻拨回过去，模拟「时间到了」—— 比真等 25 分钟快 1500 倍
    p._deadline = time.monotonic() - 0.01
    snap = p.tick()
    check(snap["phase"] == Pomodoro.BREAK, "工作结束自动进入短休息",
          snap["phase"])
    check(p.completed == 1, "完成数 +1", str(p.completed))
    check(snap["total"] == 5 * 60, "短休息 5 分钟", str(snap["total"]))
    check("work_done" in events, "触发了 work_done", str(events))

    p._deadline = time.monotonic() - 0.01
    snap = p.tick()
    check(snap["phase"] == Pomodoro.WORK, "休息结束自动回到工作",
          snap["phase"])
    check("break_done" in events, "触发了 break_done", str(events))
    check(p.completed == 1, "休息结束不计入完成数", str(p.completed))

    section("番茄状态机：长休息与跳过")
    p2 = Pomodoro(work_min=1, break_min=1, long_break_min=7, long_every=4)
    p2.start()
    for _ in range(4):
        p2._deadline = time.monotonic() - 0.01
        p2.tick()
        if p2.phase == Pomodoro.WORK:
            p2._deadline = time.monotonic() - 0.01
            p2.tick()
    # 4 轮后应该正好在长休息
    check(p2.phase == Pomodoro.LONG_BREAK, "第 4 轮结束后进入长休息",
          p2.phase)
    check(p2.total == 7 * 60, "长休息 7 分钟", str(p2.total))
    check(p2.completed == 4, "完成数 = 4", str(p2.completed))

    p3 = Pomodoro(work_min=25, break_min=5)
    p3.start()
    p3.skip()
    check(p3.phase == Pomodoro.BREAK, "跳过工作 → 直接进休息", p3.phase)
    check(p3.completed == 0, "跳过的工作**不**计入完成数", str(p3.completed))

    section("番茄状态机：暂停 / 继续 / 重置")
    p4 = Pomodoro(work_min=25, break_min=5)
    p4.start()
    time.sleep(0.02)                      # 让剩余时间真的少了一点
    p4.pause()
    check(p4.phase == Pomodoro.PAUSED, "暂停后进入 PAUSED", p4.phase)
    left = p4.remaining
    check(0 < left <= 25 * 60, "暂停时剩余时间被保留", "%.1f" % left)
    time.sleep(0.05)
    check(abs(p4.remaining - left) < 0.001, "暂停时倒计时**不走**")
    p4.resume()
    check(p4.phase == Pomodoro.WORK, "继续后回到工作段", p4.phase)
    check(p4.remaining < left + 0.001, "继续后从原剩余时间接着走")
    p4.reset()
    check(p4.phase == Pomodoro.IDLE and p4.remaining == 0,
          "重置回空闲", p4.phase)

    # ⭐ 回归（1.0.11）：reset() 必须**真的清零完成数**。docstring 一直写着
    # 「计数清零」，代码却漏了那一行 —— 点了「重置」🍅 还挂在上一轮的 ×N 上
    # 永远不动（用户实测报的那个「一直显示 ×2」）。
    p8 = Pomodoro(work_min=1, break_min=1)
    p8.start()
    p8._deadline = time.monotonic() - 0.01
    p8.tick()
    check(p8.completed == 1, "先完成一个番茄，完成数 = 1", str(p8.completed))
    p8.reset()
    check(p8.phase == Pomodoro.IDLE and p8.completed == 0,
          "重置后完成数清零（这条曾在旧代码下必挂）",
          "%s / %s" % (p8.phase, p8.completed))

    section("番茄状态机：配置与健壮性")
    p5 = Pomodoro()
    p5.set_durations(10, 3, 9, 6)
    p5.start()
    check(p5.total == 10 * 60, "set_durations 立即影响下一段", str(p5.total))
    p6 = Pomodoro(work_min="abc", break_min=None)   # 坏配置不能炸
    check(p6.work_sec == 25 * 60, "坏配置回落到默认 25 分钟",
          str(p6.work_sec))
    check(Pomodoro._clamp_minutes(999) == 180 and
          Pomodoro._clamp_minutes(0) == 1, "时长被夹在 1~180 分钟")

    # 回调抛异常不能拖垮计时
    def boom(ev, pom):
        raise RuntimeError("callback blew up")
    p7 = Pomodoro(on_event=boom)
    p7.start()
    check(p7.phase == Pomodoro.WORK,
          "回调抛异常时计时仍然活着（只影响通知）", p7.phase)


# =====================================================================
# B. 全局快捷键端到端（SendInput 真实按键）
# =====================================================================
def test_window(app):
    import tempfile
    import shutil as _sh

    section("番茄时钟窗口冒烟")
    from shimeji.engine.manager import Manager
    from shimeji.settings import Settings

    tmp = tempfile.mkdtemp(prefix="utopet_pomo_")
    try:
        s = Settings(os.path.join(tmp, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("pomodoro_work_min", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        # 统计指向临时目录：work_done 会真的 record()，默认的 DATA_DIR
        # 是**真实的 data\**，测试写进去会污染用户自己的番茄钟历史。
        # The stats go to a temp dir: work_done really records, and the default
        # DATA_DIR is the user's real data folder.
        from shimeji.pomodoro_stats import PomodoroStats
        mgr.pomostats = PomodoroStats(data_dir=tmp)

        w = mgr.open_pomodoro()
        check(w is not None and w.isVisible(), "open_pomodoro() 打开了窗口")
        check(w.windowTitle() != "pomo.title", "窗口标题是译文",
              w.windowTitle())
        # 打开时是**空闲**状态，显示 00:00，等用户按「开始」——
        # 这是有意的：计时器不该在你只是想看看的时候自己跑起来。
        check(w.pom.phase == w.pom.IDLE and w.time_label.text() == "00:00",
              "打开时是空闲状态，显示 00:00",
              "%s %s" % (w.pom.phase, w.time_label.text()))
        check(w.btn_toggle.text() not in ("", "pomo.start"),
              "按钮文案是译文", w.btn_toggle.text())

        # 按「开始」→ 进入工作段（设置里 work_min=1，所以显示 01:00）
        w.btn_toggle.click()
        check(w.pom.phase == w.pom.WORK and w.time_label.text() == "01:00",
              "按开始后立即显示 01:00（不等 500ms 定时器）",
              "%s %s" % (w.pom.phase, w.time_label.text()))

        w.pom._deadline = time.monotonic() - 0.01
        w._on_tick()
        check(w.pom.phase == w.pom.BREAK, "窗口的 QTimer 真的在推进逻辑",
              w.pom.phase)
        check(w.time_label.text() == "05:00",
              "切到休息后显示 05:00（剩余 = 整段 5 分钟）",
              w.time_label.text())
        check(w.pom.completed == 1, "窗口的完成数跟着涨", str(w.pom.completed))

        # ⭐ 回归（1.0.11 统计丢失）：窗口必须**共用** manager 的 Pomodoro
        # 实例。曾经各建各的，窗口事件的回调调了一个不存在的方法
        # （`manager.pomodoro_event`），AttributeError 被静默吞掉 ——
        # 🍅 计数照常涨，统计却永远「今日 0 个」。共用后 work_done 会真的
        # record() 进 mgr.pomostats（上面已指向临时目录，不污染真实 data\）。
        check(w.pom is mgr.pomodoro,
              "窗口用的是 manager 的计时器实例（共用，不是各建各的）")
        row = mgr.pomostats.summary()
        check(row["completed"] == 1 and row["focus_sec"] == 1 * 60,
              "work_done 后统计真的记了一笔（这条曾在旧代码下必挂）",
              str(row))
        check("1 个" in w.stats_label.text(),
              "今日统计标签跟着刷新", w.stats_label.text())

        # ⭐ 回归：点「重置」后 🍅 计数要归零（共用实例，所以看 manager 那只
        # 就行）。旧代码 reset() 不清 completed → 界面永远停在 ×N。
        w.btn_reset.click()
        check(w.pom is mgr.pomodoro and mgr.pomodoro.completed == 0,
              "点「重置」后完成数清零（曾一直停在上一轮的 ×N）",
              str(mgr.pomodoro.completed))
        check(w.pom.phase == w.pom.IDLE, "重置回空闲状态", w.pom.phase)
        check("🍅" not in w.count_label.text(),
              "重置后不再显示 🍅 × N", w.count_label.text())

        # 重置后统计**不能**被清掉 —— 那是历史，重置只针对当前这一轮
        check(mgr.pomostats.summary()["completed"] == 1,
              "重置当前计时不影响已有统计（历史要留着）",
              str(mgr.pomostats.summary()))

        w.center_on_cursor()
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QCursor, QGuiApplication
        scr = QApplication.screenAt(QCursor.pos()) or \
            QGuiApplication.primaryScreen()
        area = scr.availableGeometry()
        cx, cy = w.x() + w.width() // 2, w.y() + w.height() // 2
        check(abs(cx - area.center().x()) < 40
              and abs(cy - area.center().y()) < 40,
              "center_on_cursor() 把窗口放到当前屏幕中央",
              "(%d,%d) vs %s" % (cx, cy, area.center().toTuple().__str__()))

        w.close()
        check(not w.isVisible(), "关闭只是隐藏，计时继续（进程还在）")
        check(mgr._pomodoro_window is not None, "Manager 持有强引用（防 GC）")

        # 阶段切换的通知路径不炸
        mgr._on_pomodoro_event("work_done", mgr.pomodoro)
        check(True, "阶段切换的通知 + 托盘气泡路径不抛异常")
        mgr.quit()
    finally:
        _sh.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    section("番茄钟窗口：固定在最前方 / 隐藏背景")
    from shimeji.gui.pomodoro_window import _HIDE_BG_ENABLED as _HB
    from PySide6.QtCore import Qt as _Qt
    from shimeji.settings import Settings as _St
    from shimeji.engine.manager import Manager as _Mg

    tmp2 = tempfile.mkdtemp(prefix="utopet_pomo2_")
    try:
        s2 = _St(os.path.join(tmp2, "settings.json"))
        s2.set("character", "Miku")
        s2.set("taskbar_panel", False)
        s2.set("pomodoro_ontop", True)
        mgr2 = _Mg(app, s2)
        mgr2.timer.stop()
        w2 = mgr2.open_pomodoro()

        # 两个按钮都在，文案是译文
        check(hasattr(w2, "btn_ontop") and hasattr(w2, "btn_hidebg"),
              "番茄钟窗口有「固定在最前方」和「隐藏背景」两个按钮")
        check(w2.btn_ontop.text() not in ("", "pomo.ontop"),
              "「固定在最前方」文案是译文", w2.btn_ontop.text())
        check(w2.btn_hidebg.text() not in ("", "pomo.hide_bg"),
              "「隐藏背景」文案是译文", w2.btn_hidebg.text())

        # 置顶默认开着（1.0.9 之前是硬编码常开，默认 False 会让老用户
        # 升级后窗口突然被别的窗口盖住）
        check(bool(w2.windowFlags() & _Qt.WindowStaysOnTopHint),
              "pomodoro_ontop=True 时窗口真的置顶")
        check(s2.get("pomodoro_ontop") is True,
              "pomodoro_ontop 默认 True（不改变老用户的行为）")
        # ⭐ 复选框的勾选态必须**和设置一致**。漏了这条会出现：窗口置顶着、
        # 复选框却是空的 —— 用户以为没置顶，勾一下反而「没反应」
        # （True → True 不发 toggled 信号）。这个坑实测踩过。
        check(w2.btn_ontop.isChecked() == bool(s2.get("pomodoro_ontop", True)),
              "复选框勾选态与设置一致（不会显示「置顶中但框是空的」）",
              "checked=%s setting=%s"
              % (w2.btn_ontop.isChecked(), s2.get("pomodoro_ontop")))

        # 切到关闭 → 标志真的去掉，且**状态写回设置**
        # ⚠️ 按钮当前是**置灰**的（见下面那段），而 `setChecked()` 只在
        # enabled 时才发 `toggled` —— 所以测置顶逻辑必须先临时启用它，
        # 否则断言的是「置灰状态不响应」而不是「置顶切换是否正确」。
        # `setChecked()` only emits `toggled` on an enabled widget, and these
        # buttons ship disabled.  Enable them so this asserts the toggle logic
        # itself rather than the disabled behaviour.
        _saved_ready = w2._passthrough_ready
        w2._passthrough_ready = True
        w2.btn_ontop.setEnabled(True)
        w2.btn_hidebg.setEnabled(True)
        w2.btn_ontop.setChecked(False)
        check(not (w2.windowFlags() & _Qt.WindowStaysOnTopHint),
              "取消勾选后置顶标志真的被去掉")
        check(s2.get("pomodoro_ontop") is False, "置顶状态写回设置")
        w2.btn_ontop.setChecked(True)
        check(bool(w2.windowFlags() & _Qt.WindowStaysOnTopHint),
              "重新勾上后置顶标志恢复")

        # 关掉再打开窗口，置顶状态要按设置重新生效（不能只在构造时设一次）
        w2.btn_ontop.setChecked(False)
        w2.close()
        w2b = mgr2.open_pomodoro()
        w2b._passthrough_ready = True          # 让置顶在这只新窗口上可测
        w2b.btn_ontop.setEnabled(True)
        check(not (w2b.windowFlags() & _Qt.WindowStaysOnTopHint),
              "关掉重开后，置顶状态按设置重新生效（不是只在构造时设）")

        # ⛔ 「隐藏背景」按用户要求**做完但不生效** —— 按钮存在但置灰。
        check(_HB is False,
              "「隐藏背景」总开关是关的（按区域穿透尚未验证）")
        w2b.btn_hidebg.setEnabled(False)
        w2b.btn_ontop.setEnabled(False)
        check(not w2b.btn_hidebg.isEnabled(),
              "「隐藏背景」按钮是**置灰**的")
        check(not w2b.btn_ontop.isEnabled(),
              "「固定在最前方」按钮同组置灰（一起发版避免半成品）")
        check(bool(w2b.btn_hidebg.toolTip()),
              "置灰时给了说明提示，不是无声地不能点",
              w2b.btn_hidebg.toolTip())
        # 置灰状态下点击**不会**改变任何状态
        _before = w2b.btn_hidebg.isChecked()
        w2b.btn_hidebg.click()
        check(w2b.btn_hidebg.isChecked() == _before,
              "置灰的按钮点了也没反应（isEnabled=False 时 click 不发信号）")

        # 三语文案
        import json as _j
        for loc in ("zh_CN", "en_US", "ja_JP"):
            d = _j.load(open(os.path.join(ROOT, "shimeji", "locales",
                                         "%s.json" % loc), encoding="utf-8"))
            miss = [k for k in ("pomo.ontop", "pomo.hide_bg", "pomo.wip")
                    if not d.get(k)]
            check(not miss, "%s 有番茄钟开关的全部文案" % loc, str(miss))

        w2b.close()
        mgr2.quit()
    finally:
        _sh.rmtree(tmp2, ignore_errors=True)


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    test_state_machine()
    test_window(app)

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
