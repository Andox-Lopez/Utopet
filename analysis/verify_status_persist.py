# -*- coding: utf-8 -*-
"""验证 1.3 P3：养成四值 + 里程碑随会话持久化。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

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


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    d = tempfile.mkdtemp(prefix="utopet_status_save_")
    try:
        path = os.path.join(d, "settings.json")
        s = Settings(path)
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("restore_session", True)
        s.set("initial_count", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        if not mgr.mascots:
            mgr.summon()
        m = mgr.mascots[0]
        st = m.status
        st.feeling = 83.2
        st.energy = 74.6
        st.health = 92.1
        st.likability = 55.3
        st._milestones_done = {50}
        mgr.save_session()
        snap = s.get("session")
        check(len(snap) == 1, "会话保存了一只宠物")
        check(snap[0].get("status", {}).get("likability") == 55.3,
              "好感值 55.3 写进快照")
        check(snap[0].get("status", {}).get("milestones_done") == [50],
              "已说过的 50 里程碑写进快照")
        mgr.quit()

        # 重新创建 Manager（模拟重启引擎）
        s2 = Settings(path)
        s2.set("taskbar_panel", False)
        mgr2 = Manager(app, s2)
        mgr2.timer.stop()
        check(len(mgr2.mascots) == 1, "重启后恢复一只宠物")
        if mgr2.mascots:
            st2 = mgr2.mascots[0].status
            check(abs(st2.feeling - 83.2) < 1e-9, "心情恢复 83.2")
            check(abs(st2.energy - 74.6) < 1e-9, "体力恢复 74.6")
            check(abs(st2.health - 92.1) < 1e-9, "健康恢复 92.1")
            check(abs(st2.likability - 55.3) < 1e-9, "好感恢复 55.3")
            check(st2._milestones_done == {50}, "50 里程碑不会重启后再说")
            # 再涨到 60，不能再次触发 50
            marks = []
            st2.on_milestone = lambda mark, owner: marks.append(mark)
            st2.likability = 60
            st2._check_milestones()
            check(marks == [], "涨到 60 不重复触发 50")
            st2.likability = 85
            st2._check_milestones()
            check(marks == [80], "跨 80 仍会正常触发")
        mgr2.quit()

        # 旧会话快照无 status 字段时不崩、用默认值
        s3 = Settings(os.path.join(d, "legacy.json"))
        s3.set("character", "Miku")
        s3.set("taskbar_panel", False)
        s3.set("restore_session", True)
        s3.set("session", [{"x": 300, "y": 800, "look_right": True}])
        mgr3 = Manager(app, s3)
        mgr3.timer.stop()
        check(len(mgr3.mascots) == 1, "旧快照无 status 仍可恢复")
        mgr3.quit()
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("=" * 60, flush=True)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush(); os._exit(1)
    print("ALL PASS —— %d 项检查通过" % PASSES, flush=True)
    sys.stdout.flush(); os._exit(0)


if __name__ == "__main__":
    main()
