# -*- coding: utf-8 -*-
"""验证 `engine/brain.py`：行为选择（加权随机 + next_list 约束 + 兜底）。

这个模块决定「宠物下一刻做什么」。它坏掉的症状：

* **选不到该选的行为** —— 宠物该跳不跳、该爬不爬，但用户看不出哪里错了
* **选到不该选的行为** —— 比如 `頻度="0"` 的系统保留行为被自动选中
* **约束失效** —— `次の行動リスト` 说只能接 A，却接了 B

而且行为是**随机**选的，所以光跑一遍看不出问题 —— 必须**跑很多次**看分布。

⭐ 用真实的 `BehaviorDef` / `NextList` / `BehaviorRef` / `Val` 构造，
不 mock —— mock 出来的对象和真的不一样，测了等于没测。

用法：python analysis/verify_brain.py
"""

from __future__ import annotations

import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from shimeji.engine.brain import FALLBACKS, Brain  # noqa: E402
from shimeji.settings import Settings  # noqa: E402
from shimeji.xml.config import (BehaviorDef, BehaviorRef, BehaviorSet,  # noqa: E402
                                NextList, Val)

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


# ----------------------------------------------------------------------
class FakeStatus:
    """替身 PetStatus：只提供 weight_bias。"""

    def __init__(self, bias=1.0):
        self._bias = bias

    def weight_bias(self, name, rule=None):
        return self._bias


class FakeMascot:
    """替身宠物：只提供 Brain 用到的那几个属性。"""

    def __init__(self, bundle=None):
        self.bundle = bundle
        self.previous_behavior = None
        self.pending_behaviors = []
        self.forced_behavior = None
        self.release_next_list = False
        self.status = None

    def namespace(self):
        return {"footX": 0, "footY": 0}


class FakeBundle:
    """替身 CharacterBundle。"""

    def __init__(self, actions, behaviors):
        self.actions = actions
        self.behaviors = behaviors
        self.constants = {}

    def behavior_by_name(self, name):
        for _c, b in self.behaviors.entries:
            if b.name == name:
                return b
        return None


class FakeActions:
    """替身 ActionSet。"""

    def __init__(self, names):
        self.actions = {n: object() for n in names}
        self.order = list(names)

    def __contains__(self, name):
        return name in self.actions

    def get(self, name):
        return self.actions.get(name)


class FakeManager:
    """替身 Manager：Brain 只用到 actions / behaviors / constants / settings。"""

    def __init__(self, action_names, behavior_entries, constants=None):
        self.actions = FakeActions(action_names)
        self.behaviors = BehaviorSet()
        self.behaviors.entries = list(behavior_entries)
        self.constants = constants or {}
        tmp = tempfile.mkdtemp(prefix="utopet_brain_")
        self.settings = Settings(os.path.join(tmp, "settings.json"))

    def behavior_by_name(self, name):
        for _c, b in self.behaviors.entries:
            if b.name == name:
                return b
        return None


def bd(name, freq="1", condition=None, next_list=None):
    """造一个行为定义。"""
    return BehaviorDef(name, Val(freq), condition, next_list)


def main() -> int:
    random.seed(20261029)

    # ==============================================================
    section("1. 加权随机：权重为 0 的行为不会被选中")
    mgr = FakeManager(
        ["A", "B", "C"],
        [(None, bd("A", "1")), (None, bd("B", "0")), (None, bd("C", "1"))],
    )
    brain = Brain(mgr)
    mascot = FakeMascot()
    picked = set()
    for _ in range(400):
        picked.add(brain.choose(mascot))
    check("B" not in picked,
          "頻度=0 的行为不会被自动选中（系统保留行为）",
          "picked=%s" % sorted(x for x in picked if x))
    check(picked <= {"A", "C"},
          "只从有正权重的行为里选", "picked=%s" % sorted(picked))

    # 分布：A 和 C 各 1 权重，应该大致各占一半
    counts = {"A": 0, "C": 0}
    for _ in range(600):
        n = brain.choose(mascot)
        if n in counts:
            counts[n] += 1
    ratio = counts["A"] / max(1, counts["A"] + counts["C"])
    check(0.35 < ratio < 0.65,
          "等权重的两个行为分布大致均匀",
          "A=%d C=%d ratio=%.2f" % (counts["A"], counts["C"], ratio))

    # ==============================================================
    section("2. 权重越大越常被选中")
    mgr2 = FakeManager(
        ["Rare", "Common"],
        [(None, bd("Rare", "1")), (None, bd("Common", "50"))],
    )
    brain2 = Brain(mgr2)
    m2 = FakeMascot()
    c = {"Rare": 0, "Common": 0}
    for _ in range(600):
        n = brain2.choose(m2)
        if n in c:
            c[n] += 1
    check(c["Common"] > c["Rare"] * 5,
          "权重 50 的行为明显更常被选中",
          "Common=%d Rare=%d" % (c["Common"], c["Rare"]))

    # ==============================================================
    section("3. 次の行動リスト 约束（追加=false）")
    # 上一个行为的 next_list 说「只能接 A」-> 只能选 A
    mgr3 = FakeManager(
        ["A", "B", "C"],
        [(None, bd("A", "1")), (None, bd("B", "1")), (None, bd("C", "1"))],
    )
    brain3 = Brain(mgr3)
    m3 = FakeMascot()

    # ⭐⭐ **next_list 是「上一个行为结束后能接什么」** —— `choose()` 每次都会
    # 把 `previous_behavior` 更新成刚选中的那个，而那个行为的 next_list 往往
    # 是空的 -> **第二次起约束就消失了**。所以测约束必须**每次都重置**
    # `previous_behavior`，否则测到的是「约束只生效一次」。
    # The constraint applies to the *previous* behaviour, and choose() overwrites
    # previous_behavior every time — so the constraint must be re-armed on each
    # iteration, or we only ever see it hold for the first pick.
    def choose_with_prev(prev_def, times=50):
        out = set()
        for _ in range(times):
            m3.previous_behavior = prev_def
            out.add(brain3.choose(m3))
        return out

    prev_locked = bd("Prev", "1", None,
                     NextList(False, [BehaviorRef("A", Val("1"), None)]))
    got = choose_with_prev(prev_locked)
    check(got == {"A"},
          "追加=false 时只能从 next_list 里选",
          "got=%s" % sorted(got))

    # 追加=true -> next_list 并入全局池（三个都能被选到）
    prev_add = bd("Prev", "1", None,
                  NextList(True, [BehaviorRef("A", Val("1"), None)]))
    got = choose_with_prev(prev_add, 200)
    check(got == {"A", "B", "C"},
          "追加=true 时 next_list 并入全局池",
          "got=%s" % sorted(got))

    # next_list 里带条件的引用：条件不满足 -> 约束生效，**不会选到约束外的行为**
    from shimeji.xml.expr import Expr
    prev_cond = bd(
        "Prev", "1", None,
        NextList(False, [BehaviorRef("A", Val("1"),
                                     Expr.parse("#{footX > 1000}"))]))
    got = choose_with_prev(prev_cond)
    # 约束池为空 -> 走兜底链（FALLBACKS 不在这个动作表里）-> 用动作表第一个
    check(got == {"A"},
          "next_list 条件不满足时不会选到约束外的行为（走兜底）",
          "got=%s" % sorted(got))

    # ==============================================================
    section("4. release_next_list：放出宠物时忽略约束")
    m4 = FakeMascot()
    m4.previous_behavior = bd("Prev", "1", None,
                              NextList(False, [BehaviorRef("A", Val("1"), None)]))
    m4.release_next_list = True
    got = set(brain3.choose(m4) for _ in range(200))
    check("B" in got or "C" in got,
          "release_next_list 时忽略 next_list 约束（能回到全局池）",
          "got=%s" % sorted(got))

    # ==============================================================
    section("5. 强制行为队列（FIFO）")
    m5 = FakeMascot()
    m5.pending_behaviors = ["A", "C"]
    brain3 = Brain(FakeManager(
        ["A", "B", "C"],
        [(None, bd("A", "1")), (None, bd("B", "1")), (None, bd("C", "1"))]))
    first = brain3.choose(m5)
    check(first == "A", "强制队列按先进先出", "got=%s" % first)
    check(m5.pending_behaviors == ["C"], "出队后剩下的还在队列里",
          str(m5.pending_behaviors))
    second = brain3.choose(m5)
    check(second == "C", "接着取队列里的下一个", "got=%s" % second)

    # 队列里塞了未知名字 -> 跳过它，继续看下一个
    m5.pending_behaviors = ["不存在的名字", "C"]
    got = brain3.choose(m5)
    check(got == "C", "强制队列里的未知名字被跳过", "got=%s" % got)

    # ==============================================================
    section("6. 条件不满足的行为不参与选择")
    from shimeji.xml.expr import Expr
    mgr6 = FakeManager(
        ["A", "B"],
        [(Expr.parse("#{footX > 1000}"), bd("A", "1")),
         (None, bd("B", "1"))],
    )
    brain6 = Brain(mgr6)
    m6 = FakeMascot()
    got = set(brain6.choose(m6) for _ in range(50))
    check(got == {"B"},
          "条件为假的行为不会被选中", "got=%s" % sorted(got))

    # ==============================================================
    section("7. 兜底链")
    # 什么行为都没有 -> 走 FALLBACKS
    # ⚠️ 兜底行为必须**在动作表里**才算可用（`_known()` 会查）—— 所以这里
    # 要把 FALLBACKS 的名字放进动作表，否则会一路落到「动作表第一个」。
    # The fallback names must exist in the action table to count.
    brain7 = Brain(FakeManager(["A"] + list(FALLBACKS), []))
    m7 = FakeMascot()
    got = brain7.choose(m7)
    check(got == FALLBACKS[0],
          "没有可用行为时用第一个兜底", "got=%s" % got)
    # 连兜底都没有 -> 用动作表第一个
    brain8 = Brain(FakeManager(["OnlyAction"], []))
    m8 = FakeMascot()
    got = brain8.choose(m8)
    check(got == "OnlyAction",
          "连兜底都没有时用动作表第一个", "got=%s" % got)
    # 兜底逐个尝试：只有第二个可用时应该选第二个
    brain9 = Brain(FakeManager([FALLBACKS[1]], []))
    m9 = FakeMascot()
    got = brain9.choose(m9)
    check(got == FALLBACKS[1],
          "兜底按顺序试，跳过不可用的", "got=%s" % got)

    # ⚠️ 兜底名都不在动作表里 -> 用动作表第一个（不是 None）
    brain9b = Brain(FakeManager(["OnlyAction"], []))
    got = brain9b.choose(FakeMascot())
    check(got == "OnlyAction",
          "兜底行为都不在动作表里时用动作表第一个", "got=%s" % got)

    # ==============================================================
    section("8. 用户覆盖（behavior_overrides）")
    mgr10 = FakeManager(
        ["A", "B"],
        [(None, bd("A", "1")), (None, bd("B", "1"))],
    )
    mgr10.settings.data["behavior_overrides"] = {"B": {"enabled": False}}
    brain10 = Brain(mgr10)
    m10 = FakeMascot()
    got = set(brain10.choose(m10) for _ in range(50))
    check(got == {"A"}, "被用户禁用的行为不会被选中", "got=%s" % sorted(got))

    # 覆盖频率
    mgr11 = FakeManager(
        ["A", "B"],
        [(None, bd("A", "1")), (None, bd("B", "1"))],
    )
    mgr11.settings.data["behavior_overrides"] = {"B": {"frequency": 100}}
    brain11 = Brain(mgr11)
    m11 = FakeMascot()
    c = {"A": 0, "B": 0}
    for _ in range(300):
        n = brain11.choose(m11)
        if n in c:
            c[n] += 1
    check(c["B"] > c["A"] * 3,
          "用户覆盖的频率生效（权重 100 应该压倒 1）",
          "A=%d B=%d" % (c["A"], c["B"]))

    # ==============================================================
    section("9. 状态权重（CalMode）只改频率不改行为集合")
    mgr12 = FakeManager(
        ["A", "B"],
        [(None, bd("A", "1")), (None, bd("B", "1"))],
    )
    brain12 = Brain(mgr12)
    m12 = FakeMascot()
    m12.status = FakeStatus(bias=3.0)
    c = {"A": 0, "B": 0}
    for _ in range(300):
        n = brain12.choose(m12)
        if n in c:
            c[n] += 1
    check(c["A"] > 0 and c["B"] > 0,
          "状态权重不改变「哪些行为可选」，只改频率",
          "A=%d B=%d" % (c["A"], c["B"]))

    # ==============================================================
    section("10. 每只宠物用自己的行为表")
    mgr13 = FakeManager(["Global"], [])
    bundle_behaviors = BehaviorSet()
    bundle_behaviors.entries = [(None, bd("OnlyInBundle", "1"))]
    bundle = FakeBundle(FakeActions(["OnlyInBundle"]), bundle_behaviors)
    brain13 = Brain(mgr13)
    m13 = FakeMascot(bundle=bundle)
    got = brain13.choose(m13)
    check(got == "OnlyInBundle",
          "有 bundle 的宠物用自己行为表里的行为", "got=%s" % got)

    # ==============================================================
    section("11. 名字不在动作表里的行为不可用")
    # 行为表里有「Ghost」，但动作表里没有 -> 不可选
    mgr14 = FakeManager(["Real"], [(None, bd("Ghost", "1"))])
    brain14 = Brain(mgr14)
    m14 = FakeMascot()
    got = brain14.choose(m14)
    check(got != "Ghost", "动作表里没有的行为不会被选中", "got=%s" % got)

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
