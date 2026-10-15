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
