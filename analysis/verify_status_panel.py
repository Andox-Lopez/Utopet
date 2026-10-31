# -*- coding: utf-8 -*-
"""验证 F1（状态面板扩展）：四个数值看得见、多角色逐只列出、数值会跟着互动变。

为什么单独写：`verify_physics_101.py` 已经有 `PetStatus` 的单元测试，但 F1 的
重点在**面板能不能真的开出来、每只宠物是不是都列出来** —— 那是 UI，得构造真的
窗口才知道。

⚠️ **不能用 offscreen**：面板要测点击与窗口显示，offscreen 下 `winId()` 恒为 1。
必须用真实 Qt 窗口。

用法：python analysis/verify_status_panel.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Pt  # noqa: E402
from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.engine.petstate import PetStatus  # noqa: E402
from shimeji.gui.status_window import StatusWindow  # noqa: E402
from shimeji.gui.taskbar_panel import TaskbarPanel  # noqa: E402
from shimeji.i18n import set_language  # noqa: E402
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

    d = tempfile.mkdtemp(prefix="utopet_status_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", True)
        s.set("restore_session", False)
        s.set("initial_count", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        wa = mgr.shared_env.work_area

        # ==============================================================
        section("1. detail() 给出四个数值，不再只有心情和体力")
        st = PetStatus(feeling=85, energy=90, health=95, likability=60)
        det = st.detail()
        for key in ("feeling", "energy", "health", "likability"):
            check(key in det, "detail() 含 %s" % key, str(det.get(key)))
        check(det.get("state") == "happy", "detail() 推出状态", str(det.get("state")))
        check(len(det) >= 5, "detail() 是结构化的（不是拼好的一行字符串）")

        # ==============================================================
        section("2. 面板的状态摘要可点击，且点开能看到每只")
        panel = TaskbarPanel(mgr)
        app.processEvents()
        check(hasattr(panel, "status_btn"),
              "面板有可点击的状态按钮 status_btn")
        check(not hasattr(panel, "state_label"),
              "旧的只读 state_label 已移除（不会有重复控件）")
        # 召唤两只，验证逐只列出
        p1 = mgr.summon(Pt(wa.left + 200, wa.bottom))
        p2 = mgr.summon(Pt(wa.left + 400, wa.bottom))
        check(p1 is not None and p2 is not None, "召唤出两只宠物")
        check(len(mgr.mascots) == 2, "确实是两只", str(len(mgr.mascots)))

        # ⭐ 面板靠自己的 500ms 定时器刷新，测试**不该等定时器** —— 手动刷一次。
        # 注意要在召唤之后刷：构造面板时还没有宠物，摘要本来就是空的。
        # The panel refreshes on its own 500ms timer; do not wait on it in a
        # test.  Refresh after summoning — there were no pets when it was built.
        panel.refresh_status()
        app.processEvents()
        check(panel.status_btn.text() != "",
              "召唤后按钮上有一行摘要", repr(panel.status_btn.text()))
        check(panel.status_btn.toolTip() != "",
              "有「点这里看详细」的提示", repr(panel.status_btn.toolTip()))

        panel._open_status_window()
        app.processEvents()
        win = panel._status_window
        check(win is not None and win.isVisible(), "点开后详细窗口可见")
        if win is not None:
            check(len(win._rows) == 2,
                  "详细窗口按宠物数量建了 2 行（不是只有第一只）",
                  str(len(win._rows)))
            # 四行数值条都在
            for key in ("feeling", "energy", "health", "likability"):
                ok = all(key in r for r in win._rows)
                check(ok, "每只都有 %s 的数值条" % key)
            # 数值真的显示出来了
            texts = [r["feeling"]["num"].text() for r in win._rows]
            check(all(t.lstrip("-").isdigit() for t in texts),
                  "数值渲染出来了", str(texts))
            bars = [r["health"]["bar"].value() for r in win._rows]
            check(all(isinstance(v, int) for v in bars),
                  "进度条有值", str(bars))

        # ==============================================================
        section("3. 互动后数值会变（不是静态快照）")
        before = p1.status.detail()["feeling"]
        p1.status.interact("drag")
        after = p1.status.detail()["feeling"]
        check(after > before,
              "拖拽后心情上涨", f"{before:.1f} -> {after:.1f}")

        # 窗口刷新后跟着变
        panel._status_window.refresh()
        app.processEvents()
        shown = win._rows[0]["feeling"]["bar"].value()
        check(int(round(after)) == shown,
              "详细窗口跟着刷新", f"数值={after:.1f} 进度条={shown}")

        # ==============================================================
        section("4. 宠物解散后不留下幽灵行")
        mgr.dismiss_all()
        win.refresh()
        app.processEvents()
        check(len(win._rows) == 0, "没有宠物时行数归零", str(len(win._rows)))
        check(win._empty_label.isVisible(), "显示「现在没有宠物」提示")

        # ==============================================================
        section("5. 三语都能正确显示（不再把日语落到中文）")
        st2 = PetStatus(feeling=50, energy=70, health=80, likability=10)
        got = {}
        for lang in ("zh_CN", "en_US", "ja_JP"):
            set_language(lang)
            got[lang] = st2.summary("zh_CN")
        for lang, text in got.items():
            print("      %-6s %s" % (lang, text), flush=True)
        check("心情" in got["zh_CN"], "中文显示「心情」")
        check("Mood" in got["en_US"], "英文显示 Mood")
        # ⭐ 以前日语会走中文分支，出现「心情」；现在应该是「気分」
        check("気分" in got["ja_JP"] and "心情" not in got["ja_JP"],
              "**日语显示「気分」，不再落到中文**", got["ja_JP"])
        set_language("zh_CN")

        win.close()
        panel.close()
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
