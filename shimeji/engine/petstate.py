# -*- coding: utf-8 -*-
"""
宠物状态 / Pet state
==============================================================================
借鉴 VPet（https://github.com/LorisYounger/VPet）的 `GameSave.CalMode()`：
**数值不直接决定行为，而是先经阈值转换成「状态」，再由状态影响行为权重。**

Borrowed in spirit from VPet's `GameSave.CalMode()`: numbers do not pick an
action directly — they are first folded through thresholds into a *state*, and
the state then biases the behaviour weights.

为什么要绕这一圈
----------------
VPet 的公式非常紧凑::

    realhel = 60 - (Feeling >= 80 ? 12 : 0) - (Likability >= 80 ? 12 : 6 : 0)
    if (Health <= realhel) return Health <= realhel/2 ? Ill : PoorCondition
    realfel = .90 - (Likability >= 80 ? .20 : .10 : 0)
    felps = Feeling / FeelingMax
    if (felps >= realfel)     return Happy
    else if (felps <= realfel/2) return PoorCondition
    return Nomal

妙处不在公式本身，而在于**「心情好 -> 判定阈值提高 -> 更容易判为 Happy」**
这个反馈：数值低的时候不是「直接换成难过动画」，而是先降低「开心」的门槛，
于是状态是连续变化的，不会在两个动画之间硬跳。

本项目的取舍
------------
**1.2.0 起：开始引入养成 UI，但不是把它做成游戏。**
数值仍然是「给 `state()` 提供输入」这一件事，只是现在**用户看得见、摸得着**：
面板能显示四个数值（`detail()`），摸头/拖拽/抛出会分别影响它们（`interact()` 的
`kind`）。仍然**没有任务、没有目标、没有失败惩罚** —— 状态只改行为出现的
频率，绝不改行为集合。

No progression *game* here.  The numbers still only feed `state()`, but from
1.2.0 the user can see them (`detail()`) and move them (`interact()`'s `kind`).
There are still no quests, no goals, no penalties.

1. `state()` —— 阈值转换（照抄思路，阈值按我们的取值重新定）
2. `weight_bias()` —— 一个 0.4~1.6 的乘数，由状态决定

`Brain` 拿这个乘数去调整候选池的权重。效果是：状态好的时候，跳跃/奔跑/
爬墙这类活跃行为的权重被放大，发呆/趴着被压低；反之亦然。**动作本身没变，
只是出现的频率变了** —— 这是最安全的接入方式，不会破坏任何既有行为语义。

No progression UI here.  1.0.3 only borrows the threshold fold and a 0.4~1.6
multiplier; the actions are unchanged, only how often they come up.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("shimeji")

# ⭐ 引入 `tr()` 只为了把面板文案本地化。
# `i18n.py` 只依赖 json/os，**与引擎之间没有循环导入**，放心引。
# Importing `tr()` is safe: `i18n.py` only needs json/os, so there is no
# import cycle with the engine.
from ..i18n import tr

__all__ = ["PetState", "PetStatus", "STATE_NAMES_ZH", "STATE_NAMES_EN",
           "CAL_CLASSES"]

#: CalMode 类别（用户在设置里可为每条行为单独指定）/ CalMode classes
#:
#: auto   —— 按行为名里的词根自动判断（默认，不覆盖时的行为）
#: active —— 永远按「活跃」处理：心情好时更常出现
#: quiet  —— 永远按「安静」处理：心情好时更少出现
#: off    —— 完全不受状态影响，权重恒为 1.0
CAL_CLASSES = ("auto", "active", "quiet", "off")

#: 状态枚举 / the state enum.  顺序即「从差到好」，便于比较与调权重。
class PetState:
    SICK = "ill"                # 生病：几乎不动/  sick: barely moves
    POOR = "poor"               # 状态不佳 / below par
    NORMAL = "normal"           # 普通 / neutral
    HAPPY = "happy"             # 开心 / happy


STATE_NAMES_ZH = {
    PetState.SICK: "生病",
    PetState.POOR: "状态不佳",
    PetState.NORMAL: "普通",
    PetState.HAPPY: "开心",
}

STATE_NAMES_EN = {
    PetState.SICK: "Ill",
    PetState.POOR: "Poor Condition",
    PetState.NORMAL: "Normal",
    PetState.HAPPY: "Happy",
}


#: 活跃行为关键词 -> 心情好时权重放大 / Active behaviours: boosted when happy
#:
#: 注意这些是**日文原名**里的词根，因为 Behavior.xml 写的就是日文，而配置要
#: 保持日文以兼容原版角色包。本地化只发生在菜单标签上。
#: These are substrings of the Japanese behaviour names, because that is what
#: Behavior.xml contains; only the menu labels are localised.
ACTIVE_KEYS = (
    "走る", "歩く", "登る", "跳ね", "ダッシュ", "よじのぼる", "伝う", "飛ぶ",
)

#: 安静行为关键词 -> 心情好时权重压低 / Quiet behaviours: damped when happy
QUIET_KEYS = (
    "座って", "寝そべ", "ぼーっと", "なべり", "休",
)


class PetStatus:
    """
    宠物的养成数值与由它推出的状态 / The pet's numbers and the state they imply.

    数值本身**不是**游戏内容：没有 UI 可以改，也没有游戏目标。它们只是给
    `state()` 提供输入，让行为分布随时间轻轻漂移，避免桌宠每次启动都一模一样。

    The numbers are not a game: there is no UI to change them and no goal to
    chase.  They only feed `state()` so the behaviour mix drifts a little over
    time, instead of every session being identical.
    """

    def __init__(self, feeling: float = 55.0, energy: float = 80.0,
                 health: float = 100.0, likability: float = 0.0):
        #: 心情 0-100 / mood
        self.feeling = float(feeling)
        #: 体力 0-100 / stamina
        self.energy = float(energy)
        #: 健康 0-100 / health
        self.health = float(health)
        #: 好感度 0-100，随交互缓慢增长 / rapport, grows slowly with interaction
        self.likability = float(likability)
        self._state: str = PetState.NORMAL
        # ⭐ F3：状态迁移 / 好感里程碑的监听者（由 Manager 注册）。
        # Listeners for state changes and rapport milestones (F3).
        self.on_state_changed = None   # callable(new, old, owner)
        self.on_milestone = None       # callable(value, owner)
        #: 持有本状态的宠物（Manager 回调要用，见下）/ the owning mascot.
        self.owner = None
        #: 已经报过的里程碑（一生一次；重启即重置）
        #: Milestones already announced (once per process lifetime).
        self._milestones_done: set = set()
        self._ticks = 0

    # ------------------------------------------------------------------
    def clamp(self) -> None:
        """把所有数值夹进合法区间 / Clamp every value into range."""
        self.feeling = min(100.0, max(0.0, self.feeling))
        self.energy = min(100.0, max(0.0, self.energy))
        self.health = min(100.0, max(0.0, self.health))
        self.likability = min(100.0, max(0.0, self.likability))

    # ------------------------------------------------------------------
    def state(self) -> str:
        """
        数值 -> 状态（VPet `CalMode()` 的等价物 / VPet's `CalMode()`).

        照搬结构，阈值按我们的取值重定：

        * ``real_health`` 会随着心情/好感**下降** —— 也就是说「被照顾得好，
          同样的身体数值也更容易被认为是健康」。这是 VPet 那个公式的精髓。
        * 心情用比例而不是绝对值判定，所以心情上限变化不影响判定。
        * 顺序是「先判病，再判心情」，与原版一致。

        The structure is VPet's; the thresholds are ours.  Note that
        `real_health` *drops* as mood/rapport rise — being well cared for makes
        the same physical numbers read as healthy, which is the whole trick of
        the original formula.
        """
        # 交互越多，好感越高（上限 100）/ more interaction -> more rapport
        care = (12.0 if self.feeling >= 80 else 0.0) \
            + (12.0 if self.likability >= 80 else (6.0 if self.likability >= 40 else 0.0))
        real_health = 60.0 - care
        if self.health <= real_health:
            return PetState.SICK if self.health <= real_health / 2 else PetState.POOR

        # 心情阈值同样随好感提高 / the mood bar rises with rapport too
        need = 0.90 - (0.20 if self.likability >= 80 else
                       (0.10 if self.likability >= 40 else 0.0))
        f = self.feeling / 100.0
        if f >= need:
            return PetState.HAPPY
        if f <= need / 2:
            return PetState.POOR
        return PetState.NORMAL

    def cached_state(self) -> str:
        """状态（带缓存）/ The state, cached.

        `state()` 只做几次比较，很便宜，但每帧每只宠物都调会浪费；缓存到状态
        真正变化为止。
        """
        s = self.state()
        if s != self._state:
            old = self._state
            self._state = s
            # ⭐ F3：迁移时通知监听者（回调抛异常不能打断状态机）。
            # Notify listeners; a bad callback must not break the state machine.
            cb = self.on_state_changed
            if cb is not None:
                try:
                    cb(s, old, self.owner)
                except Exception:
                    # ⭐ 可观测（项目纪律）：静默吞掉会变成「状态台词失效
                    # 且日志里一个字都没有」。
                    # Observable, per project discipline.
                    _log.warning("状态迁移回调失败", exc_info=True)
        return self._state

    # ------------------------------------------------------------------
    def tick_slow(self) -> None:
        """
        随时间缓慢漂移（默认 15 秒一次）/ Drift slowly (every 15s by default).

        照搬 VPet「定时结算而非每帧结算」的做法，也照搬它的**平方根**衰减：
        越久不互动，掉得越慢 —— 不该让用户因为离开一天回来就看到宠物半死。

        上下都有界，且心情不会低于 12（不会彻底"坏掉"），好感不会低于 0。
        """
        self._ticks += 1
        if self._ticks % 375:          # 375 tick * 40ms ≈ 15s
            return
        # 心情缓慢下降，下限 12 / mood drifts down, floor at 12
        self.feeling = max(12.0, self.feeling - 0.6)
        # 体力随时间恢复，但心情差时恢复慢 / stamina recovers, slower when unhappy
        rate = 0.8 if self.state() != PetState.SICK else 0.25
        self.energy = min(100.0, self.energy + rate)
        # 健康跟着体力与心情走 / health trails energy and mood
        if self.energy > 60 and self.feeling > 40:
            self.health = min(100.0, self.health + 0.4)
        elif self.health < 90 and self.energy < 25:
            self.health = max(30.0, self.health - 0.3)
        self.clamp()
        self._check_milestones()

    #: 互动强度表 / interaction strengths.
    #:
    #: 参照 `tick_slow()` 的漂移（心情每 15 秒 -0.6）来定量级：
    #: 摸头 +2.2 约等于抗衛 55 秒的自然衰减 —— 摸几下就看得见变化，
    #: 但不会几下就满。
    #:
    #: Sized against the drift in `tick_slow()` (mood -0.6 per 15 s): a pat is
    #: worth about 55 s of recovery, so it shows up quickly without being
    #: something you can max out in a few taps.
    _INTERACTIONS = {
        # 摸头 / 点一下：最轻也最高频，应该是主要的正向来源；几乎不累
        # ️ energy 写的是**消耗量**（正数），下面做减法。
        # 我第一版表里写负数、代码又做减法，结果体力不降反升 ——
        # 验证时才发现。The values are *costs*, subtracted below.
        "pat":   {"feeling": +2.2, "likability": +0.15, "energy": 0.2},
        # 拖拽：用户在「带着它走」，亲密但费劲
        "drag":  {"feeling": +0.8, "likability": +0.45, "energy": 1.6},
        # 抛出：玩闹，开心但最累
        "throw": {"feeling": +1.8, "likability": +0.10, "energy": 2.4},
    }

    def _check_milestones(self) -> None:
        """
        好感跨过 50/80/100 时通知一次（每个一生一次）。

        ⭐ 在 `interact()` 与 `tick_slow()` 的**末尾**调用 —— 好感只在那里变化。

        Milestones are 50/80/100; each fires once per process lifetime.
        Called at the *end* of `interact()` and `tick_slow()`, the only two
        places likability changes.
        """
        for mark in (50, 80, 100):
            if self.likability >= mark and mark not in self._milestones_done:
                self._milestones_done.add(mark)
                cb = self.on_milestone
                if cb is not None:
                    try:
                        cb(mark, self.owner)
                    except Exception:
                        _log.warning("好感里程碑回调失败", exc_info=True)

    def interact(self, kind: str = "touch") -> None:
        """
        被互动了一次 / The user interacted with the pet.

        ⭐⭐ ``kind`` **真的会改变数值**（1.2.0 F2）。

        | kind    | 心情   | 好感   | 体力   | 说明 |
        |---------|--------|--------|--------|------|
        | pat     | +2.2   | +0.15  | -0.2   | 摸头，几乎不累 |
        | drag    | +0.8   | +0.45  | -1.6   | 拖拽，亲密但费劲 |
        | throw   | +1.8   | +0.10  | -2.4   | 抛出，开心但最累 |

        **为什么摸头活得最多**：它是最轻量、最高频的互动。
        在这之前，**点击/摸头完全不算互动** ——
        `interact()` 只在拖拽与抛出两处被调用，
        用户点宠物（最自然的动作）却得不到任何回应。

        ⭐ **未知的 kind 会退回通用值**（和以前一样），
        所以旧调用方不会因为写错 kind 而变成无效。

        An unknown ``kind`` falls back to the old catch-all values, so a typo
        cannot silently disable the effect.
        """
        rule = self._INTERACTIONS.get(kind)
        if rule is None:
            # 未知类型：退回以前的通用值（中等强度）
            rule = {"feeling": +1.6, "likability": +0.25, "energy": 1.0}
        self.feeling = min(100.0, self.feeling + rule["feeling"])
        self.likability = min(100.0, self.likability + rule["likability"])
        self.energy = max(0.0, self.energy - rule["energy"])
        self.clamp()
        self._check_milestones()
    # ------------------------------------------------------------------
    def weight_bias(self, behavior_name: str, rule: dict | None = None) -> float:
        """
        状态给某个行为加的权重乘数 / Weight multiplier for one behaviour.

        活动行为在开心时放大、安静行为压低；生病时反过来（几乎只做安静的事）。
        乘数范围锁在 0.4~1.6，太极端会让桌宠看起来像坏了。

        A multiplier in 0.4~1.6: too extreme and the pet looks broken rather than
        moody.

        ``rule`` 是用户在设置里为**这一条**行为定的覆盖（见 settings 的
        `cal_overrides`）：

        * ``class`` —— ``auto``（按行为名里的词根自动判断）/ ``active``
          （永远按活跃处理）/ ``quiet``（永远按安静处理）/ ``off``
          （完全不受状态影响，恒为 1.0）。默认 ``auto``，也就是不覆盖时的行为。
        * ``strength`` —— 0~200 的百分比。100 保持默认强度；0 表示**抹平**
          状态影响（恒 1.0）；200 表示效果加倍。实现上是在 1.0 与默认强度
          之间线性插值再外插，所以 0 恰好是「无影响」，不需要特例分支。

        两项都缺省时行为与 1.0.3 完全一致 —— 这样老配置不会被悄悄改变。
        夹在 0.2~3.0：比默认宽松，但不至于让桌宠看起来像坏了。

        ``class`` picks how the behaviour is treated (auto by name / always
        active / always quiet / unaffected), ``strength`` scales the effect from
        0 (flat) to 200 (doubled).  With no rule the result is exactly the
        1.0.3 behaviour, so old configurations are unaffected.
        """
        name = behavior_name or ""
        rule = rule if isinstance(rule, dict) else {}
        cls = str(rule.get("class", "auto") or "auto")
        if cls == "off":
            return 1.0
        if cls == "active":
            active, quiet = True, False
        elif cls == "quiet":
            active, quiet = False, True
        else:
            active = any(k in name for k in ACTIVE_KEYS)
            quiet = any(k in name for k in QUIET_KEYS)
        if not (active or quiet):
            return 1.0

        st = self.cached_state()
        if active:
            base = 1.6 if st == PetState.HAPPY else (
                1.2 if st == PetState.NORMAL else (
                    0.8 if st == PetState.POOR else 0.4))
        else:
            base = 0.6 if st == PetState.HAPPY else (
                0.9 if st == PetState.NORMAL else (
                    1.3 if st == PetState.POOR else 1.6))

        try:
            strength = float(rule.get("strength", 100))
        except (TypeError, ValueError):
            strength = 100.0
        strength = min(200.0, max(0.0, strength)) / 100.0
        return min(3.0, max(0.2, 1.0 + (base - 1.0) * strength))

    def detail(self) -> dict:
        """
        四个数值 + 状态名（**结构化**的，给详细面板用）。

        All four numbers as structured data, for the detailed status popover.

        不走字符串：面板要自己排版、要列出多只宠物，
        拼好的一行字符串没法重用。

        Not a string: the panel lays it out itself and lists every pet, so a
        pre-joined line would be useless there.
        """
        return {
            "state": self.cached_state(),
            "feeling": self.feeling,
            "energy": self.energy,
            "health": self.health,
            "likability": self.likability,
        }

    def summary(self, lang: str = "zh_CN") -> str:
        """
        一行状态摘要（给面板用） / A one-line summary for the panel.

        ★ **标签走 `tr()`**（用 `panel.mood` / `panel.stamina`）。
        以前是硬编码的中/英两个分支，**日语用户会看到中文**
        （因为 `lang.startswith("en")` 为 False 时一律走中文分支）。

        Labels come from `tr()`, so Japanese no longer falls through to Chinese.

        ★ `lang` 参数保留是为了向后兼容（老调用方还在传），
        但实际显示的是用户在设置里选的语言。
        The `lang` argument is kept for compatibility; the text follows the
        language chosen in settings.
        """
        st = self.cached_state()
        mood = tr("panel.mood", "Mood")
        stamina = tr("panel.stamina", "Stamina")
        return f"{self.state_name(st)}  {mood} {self.feeling:.0f}  {stamina} {self.energy:.0f}"

    @staticmethod
    def state_name(state: str) -> str:
        """
        状态的显示名（**走 i18n**） / Display name for a state, localised.

        不再看 `lang` 参数的前缀 —— 用户在设置里选了哪种语言，
        `tr()` 就返回哪种，日语也能正确显示。

        Uses the language the user picked in settings, so Japanese works too.
        """
        keys = {
            PetState.SICK: "state.sick",
            PetState.POOR: "state.poor",
            PetState.NORMAL: "state.normal",
            PetState.HAPPY: "state.happy",
        }
        key = keys.get(state)
        if key is None:
            return state
        return tr(key, STATE_NAMES_EN.get(state, state))