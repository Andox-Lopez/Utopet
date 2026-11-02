# -*- coding: utf-8 -*-
"""验证气泡续命 bug（1.2.0 修）：冒泡间隔 < 显示时长时，气泡到点必须消失。

## 根因（用户报告：状态台词触发后气泡一直不消失、跟着宠物走）

`_tick_balloon()` 以前在气泡**可见**时也累计 interval，一到点又调一次 `say()`。
`say()` 会把消失定时器重置成 `serifu_seconds`。于是：

    冒泡间隔(1s) <= 显示时长(5s)
    -> 每 1 秒续命一次 -> 永远到不了消失那一刻

用户配置正是 interval=1、seconds=5。

## 测什么

不弹真实窗口（offscreen 足够验证 isVisible 逻辑与 tick 调度）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(cond: bool, msg: str, detail: str = ""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(t):
    print("\n--- %s ---" % t, flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    d = tempfile.mkdtemp(prefix="utopet_balloon_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("restore_session", False)
        s.set("initial_count", 1)
        s.set("serifu_enabled", True)
        # ⭐ 用户的真实配置：间隔 1 秒、显示 5 秒（续命 bug 的触发条件）
        s.set("serifu_interval", 1)
        s.set("serifu_seconds", 5)

        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        from shimeji.engine.environment import Pt
        wa = mgr.shared_env.work_area
        m = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m is not None, "召唤出宠物")
        dur = mgr.serifu.duration_ms()
        interval = mgr.serifu.interval_ms()
        check(dur == 5000 and interval == 1000,
              "复现条件：显示 5s、冒泡间隔 1s（间隔 < 时长）",
              "dur=%d interval=%d" % (dur, interval))

        # 直接说一句（模拟状态台词/任意气泡出现）
        ok = mgr.say()
        check(ok, "气泡出现")
        b = mgr._balloon
        check(b is not None and b.isVisible(), "气泡当前可见")

        # 用真实 tick 推进（每帧走 _tick_balloon）。跑 **8 秒**：
        # 旧代码下气泡会被 1s 一次的 say() 续命，8 秒后仍可见；
        # 修复后 5s 就该消失。
        section("推进 8 秒（间隔 1s、时长 5s）")
        steps = [0]
        TICK_MS = 40

        def tick():
            mgr.tick()
            steps[0] += 1

        drv = QTimer()
        drv.setInterval(TICK_MS)
        drv.timeout.connect(tick)
        drv.start()

        samples = {}

        def sample(sec):
            samples[sec] = b.isVisible()
            print("  t=%ds 可见=%s" % (sec, b.isVisible()), flush=True)

        for sec in (1, 3, 4, 6, 8):
            QTimer.singleShot(sec * 1000, lambda sec=sec: sample(sec))

        def finish():
            drv.stop()
            # 核心断言：超过显示时长后**至少有一次**确实消失了 —— 证明它没被
            # 无限续命。（消失后间隔 1s 会再冒新一句，所以 t=8 可能又可见，
            # 那是正常的「下一句」，不是 bug。）
            # The key point: it must actually disappear at least once past the
            # duration.  A new line can pop later after the interval.
            check(samples.get(6) is False,
                  "显示 5s 后气泡**确实消失过**（没被 1s 间隔无限续命）",
                  "t=6s visible=%s" % samples.get(6))
            check(samples.get(3) is True,
                  "显示时长内（3s < 5s）气泡仍在",
                  "t=3s visible=%s" % samples.get(3))
            app.quit()

        QTimer.singleShot(8200, finish)
        QTimer.singleShot(12000, app.quit)
        app.exec()
        mgr.quit()
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print()
    print("=" * 60, flush=True)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush()
        os._exit(1)
    print("ALL PASS —— %d 项检查通过" % PASSES, flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
