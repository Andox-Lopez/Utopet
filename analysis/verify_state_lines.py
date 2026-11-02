# -*- coding: utf-8 -*-
"""验证 F3（状态台词）：状态变化说一句、好感里程碑说一句、节流防刷屏。

## 为什么不弹窗口

气泡是 Qt 窗口，断言「有没有说」不该依赖窗口真的画出来。
`Manager.say()` 是唯一出口 —— 把它换成记录器，断言就变成「调用了什么」。

⭐ 这是项目纪律里的「**注入接缝**」：不改产品代码，只在测试里替换方法。

用法：python analysis/verify_state_lines.py
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


class Recorder:
    """替换 Manager.say，记录每次说了什么 / Stand-in for Manager.say."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, mascot=None, text=None):
        self.calls.append((mascot, text))
        return True


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ==================================================================
    section("1. 状态迁移会说一句对应状态的话")
    d = tempfile.mkdtemp(prefix="utopet_stateline_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("restore_session", False)
        s.set("initial_count", 1)
        s.set("serifu_enabled", True)
        s.set("serifu_state_cooldown", 1)     # 1 秒，测试里手动拨时钟
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        wa = mgr.shared_env.work_area
        m = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m is not None, "召唤出宠物")

        rec = Recorder()
        mgr.say = rec

        # 把心情拉到「开心」阈值之上（need 约 0.90，feeling 95 足够）
        m.status.feeling = 95
        m.status.cached_state()
        check(len(rec.calls) == 1, "状态变成开心时说了一句",
              "说了 %d 句" % len(rec.calls))
        if rec.calls:
            said = rec.calls[0][1]
            check(any(k in said for k in ("心情超好", "feeling great", "いい気分")),
                  "说的是**开心**那组台词", repr(said))

        # ==================================================================
        section("2. ⭐ 节流：冷却期内不再说")
        rec.calls.clear()
        # ⭐ 上面 happy 的迁移**已经说了一句**（冷却已被消费），所以现在把
        # 心情压到 50（normal）再取一次 —— 若没有冷却闸，这里就该说第二句。
        m.status.feeling = 50        # happy -> normal
        m.status.cached_state()
        check(len(rec.calls) == 0,
              "冷却期内状态再变化**不说**（防刷屏）",
              "说了 %d 句" % len(rec.calls))

        # 冷却过后，再发生一次**真实的迁移**（normal -> happy）又会说。
        mgr._state_say_ts = 0.0
        rec.calls.clear()
        m.status.feeling = 95
        m.status.cached_state()
        check(len(rec.calls) == 1,
              "冷却过后状态变化又会说", "说了 %d 句" % len(rec.calls))

        # ==================================================================
        section("3. 好感里程碑：每个一生只说一次")
        mgr._state_say_ts = 0.0
        rec.calls.clear()
        m.status.likability = 55
        m.status._check_milestones()
        check(len(rec.calls) == 1, "跨过 50 时说了一句",
              "说了 %d 句" % len(rec.calls))
        if rec.calls:
            check(any(k in rec.calls[0][1]
                      for k in ("更熟", "getting closer", "仲良く")),
                  "说的是 50 里程碑的台词", repr(rec.calls[0][1]))

        mgr._state_say_ts = 0.0
        rec.calls.clear()
        m.status.likability = 65
        m.status._check_milestones()
        check(len(rec.calls) == 0,
              "50 已经说过，再涨到 65 **不再说**",
              "说了 %d 句" % len(rec.calls))

        mgr._state_say_ts = 0.0
        rec.calls.clear()
        m.status.likability = 85
        m.status._check_milestones()
        check(len(rec.calls) == 1, "跨过 80 时又说了一句",
              "说了 %d 句" % len(rec.calls))

        # ==================================================================
        section("4. ⭐ 冷却设为 0 = 状态台词整个关掉")
        s.set("serifu_state_cooldown", 0)
        mgr._state_say_ts = 0.0
        rec.calls.clear()
        m.status.feeling = 95
        m.status.cached_state()
        check(len(rec.calls) == 0,
              "冷却为 0 时状态变化**一句都不说**",
              "说了 %d 句" % len(rec.calls))

        # ==================================================================
        section("5. 台词来源优先级：角色自带 > 全局 > 内置")
        # 角色包里放一份 serifu_happy.txt
        char_dir = os.path.join(d, "Miku")
        os.makedirs(os.path.join(char_dir, "conf"))
        io.open(os.path.join(char_dir, "conf", "serifu_happy.txt"),
                "w", encoding="utf-8").write("角色包专属的开心台词\n")

        class FakeBundle:
            directory = char_dir

        got = mgr.serifu.state_phrases(FakeBundle(), "happy")
        check(got == ["角色包专属的开心台词"],
              "角色包里的 serifu_happy.txt **整体替换**内置台词",
              str(got))

        # 没有角色包时，设置里的全局台词生效
        s.set("serifu_state_happy", "全局开心一\n全局开心二")
        got2 = mgr.serifu.state_phrases(None, "happy")
        check(got2 == ["全局开心一", "全局开心二"],
              "没有角色包时用设置里的全局台词", str(got2))

        # 都没有时用内置
        s.set("serifu_state_happy", "")
        got3 = mgr.serifu.state_phrases(None, "happy")
        check(len(got3) == 3, "都没有时退回内置三句", str(got3))

        # ==================================================================
        section("6. 回调抛异常不打断状态机（可观测）")
        def boom(new, old, owner=None):
            raise RuntimeError("台词模块炸了")

        m.status.on_state_changed = boom
        m.status.feeling = 10
        try:
            st = m.status.cached_state()
            ok = True
        except Exception:
            ok = False
            st = None
        check(ok, "回调抛异常后状态机仍然正常", "状态=%s" % st)
        # 恢复正常回调，免得污染后续
        m.status.on_state_changed = mgr._on_pet_state_changed

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
    import io
    main()
