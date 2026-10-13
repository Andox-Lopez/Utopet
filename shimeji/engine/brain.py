# -*- coding: utf-8 -*-
"""
行为选择 / Behaviour selection
==============================================================================
按 Behavior.xml 的「頻度」做加权随机，并支持「次の行動リスト」约束：

Picks a behaviour by weighted random on `頻度`, honouring `次の行動リスト`:

* `追加="false"` —— 只能从该列表里选下一个行为 / the next behaviour must come from this list
* `追加="true"`  —— 该列表并入全局候选池 / the list is merged into the global pool
* `頻度="0"`     —— 系统保留行为，不会被自动选中 / reserved, never auto-selected
"""

from __future__ import annotations

import random

from ..xml.config import BehaviorDef, BehaviorSet

__all__ = ["Brain"]

#: 找不到任何可用行为时的兜底行为名（按顺序尝试）
# Fallback behaviour names, tried in order, when nothing else is available.
FALLBACKS = ("立ってボーっとする", "立つ", "落下する")


class Brain:
    """行为选择器 / Chooses what a mascot should do next."""

    def __init__(self, manager):
        self.manager = manager

    # ------------------------------------------------------------------
    # 资源解析 / resource resolution
    # ------------------------------------------------------------------
    def actions_of(self, mascot):
        """
        这只宠物自己的动作表 / This mascot's own action table.

        1.0.3 起桌面上可以同时有多个**不同角色**，每只宠物带着自己的
        `CharacterBundle`。没有 bundle 的（例如从旧会话快照恢复的）回退到
        Manager 全局那套，保持向后兼容。
        Since 1.0.3 several distinct characters can share the screen, each with
        its own bundle.  A mascot without one (e.g. restored from an old
        session snapshot) falls back to the manager's global set.
        """
        b = getattr(mascot, "bundle", None)
        if b is not None:
            return b.actions
        return self.manager.actions

    def behaviors_of(self, mascot):
        """这只宠物自己的行为表 / This mascot's own behaviour table."""
        b = getattr(mascot, "bundle", None)
        if b is not None:
            return b.behaviors
        return self.manager.behaviors

    def behavior_by_name(self, mascot, name: str):
        b = getattr(mascot, "bundle", None)
        if b is not None:
            return b.behavior_by_name(name)
        return self.manager.behavior_by_name(name)

    # ------------------------------------------------------------------
    def _ns(self, mascot) -> dict:
        ns = mascot.namespace()
        constants = getattr(self.manager, "constants", None)
        if constants:
            ns.update(constants)
        b = getattr(mascot, "bundle", None)
        if b is not None and b.constants:
            ns.update(b.constants)
        return ns

    @staticmethod
    def _true(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return bool(value)

    def _known(self, name, mascot=None) -> bool:
        """行为名必须同时存在于配置里才可用 / A behaviour is usable only if its action exists."""
        if not name:
            return False
        if mascot is None:
            return name in self.manager.actions
        return name in self.actions_of(mascot)

    def _weight(self, name, freq, mascot=None):
        """
        套用用户在设置里做的逐条覆盖，再乘上状态权重。
        Apply the user's per-behaviour overrides, then the state bias.

        返回 (是否启用, 权重) —— 返回 None 表示该行为被禁用。
        Returns (enabled, weight); the behaviour is skipped when disabled.

        1.0.3 接入 `PetStatus`：状态不改动作本身，只改**出现频率** ——
        开心时跳跃/奔跑/爬墙更常见，生病时只发呆。这样既借到了 VPet 的养成
        反馈，又不会因为某个数值让桌宠做出反常的举动。
        1.0.3 hooks in `PetStatus`: the state never changes which action runs,
        only how often it comes up — jumps/runs/climbs show up more when happy,
        idling more when ill.

        1.0.4 起每条行为还可以**单独**覆盖 CalMode 权重（类别 + 强度），
        见 settings 的 `cal_overrides` 与设置窗口的行为表。
        Since 1.0.4 each behaviour can override the CalMode weight on its own
        (class + strength); see `cal_overrides` in the settings.
        """
        overrides = getattr(self.manager.settings, "data", {}).get("behavior_overrides", {})
        rule = overrides.get(name) if isinstance(overrides, dict) else None
        if rule and not rule.get("enabled", True):
            return None
        value = float(freq)
        if rule and rule.get("frequency", None) is not None:
            try:
                value = float(rule["frequency"])
            except (TypeError, ValueError):
                value = float(freq)
        status = getattr(mascot, "status", None) if mascot is not None else None
        if status is not None:
            data = getattr(self.manager.settings, "data", {})
            cal = data.get("cal_overrides", {}) if isinstance(data, dict) else {}
            rule = cal.get(name) if isinstance(cal, dict) else None
            value *= status.weight_bias(name, rule)
        return value

    # ------------------------------------------------------------------
    def _global_pool(self, mascot, ns):
        pool = []
        for cond, b in self.behaviors_of(mascot).entries:
            if not self._known(b.name, mascot):
                continue
            if cond is not None:
                try:
                    if not self._true(cond.eval(ns)):
                        continue
                except Exception:
                    continue
            freq = self._weight(b.name, b.frequency.num(ns, 0), mascot)
            if freq is None or freq <= 0:
                continue
            pool.append((freq, b))
        return pool

    def _next_pool(self, mascot, ns):
        prev = mascot.previous_behavior
        if prev is None or prev.next_list is None:
            return None
        pool = []
        for ref in prev.next_list.refs:
            if not self._known(ref.name, mascot):
                continue
            if ref.condition is not None:
                try:
                    if not self._true(ref.condition.eval(ns)):
                        continue
                except Exception:
                    continue
            freq = self._weight(ref.name, ref.frequency.num(ns, 0), mascot)
            if freq is None or freq <= 0:
                continue
            pool.append((freq, self.behavior_by_name(mascot, ref.name)))
        if prev.next_list.add:
            pool.extend(self._global_pool(mascot, ns))
        return pool

    # ------------------------------------------------------------------
    def choose(self, mascot) -> str | None:
        """
        挑一个行为名 / Pick a behaviour name.

        优先级顺序（对应用户诉求「优先级应该是并行/序列而不是替换」）：

        1. **排队中的强制行为**（拖拽 / 抛出 / 落下 / 聚到鼠标旁 / 菜单指定）
        2. 「次の行動リスト」约束下的候选
        3. 全局候选池（加权随机）
        4. 兜底

        队列而不是直接替换：直接替换会在动作跑到一半时把它掐断，动画之间就
        接不上了（用户反馈的「动作不连贯 / 会闪现」）。
        A queue rather than a replacement: replacing mid-action truncates the
        animation and consecutive actions no longer connect.
        """
        # 1) 强制行为队列（先来先服务）/ the forced-behaviour queue, FIFO
        if mascot.pending_behaviors:
            name = mascot.pending_behaviors.pop(0)
            if self._known(name, mascot):
                mascot.previous_behavior = self.behavior_by_name(mascot, name)
                return name
            # 未知名字就地丢弃，继续看下一个 / drop an unknown name, keep looking

        ns = self._ns(mascot)
        # 兼容旧的 forced_behavior 字段（出生行为等一次性场景）
        # Still honour the legacy field for one-shot cases such as birth.
        if mascot.forced_behavior:
            name = mascot.forced_behavior
            mascot.forced_behavior = None
            mascot.previous_behavior = self.behavior_by_name(mascot, name)
            if self._known(name, mascot):
                return name

        pool = self._next_pool(mascot, ns)
        if pool is None:
            pool = self._global_pool(mascot, ns)
        if not pool:
            pool = self._global_pool(mascot, ns)

        if pool:
            total = sum(w for w, _ in pool)
            r = random.random() * total
            for w, b in pool:
                r -= w
                if r <= 0:
                    mascot.previous_behavior = b
                    return b.name

        for name in FALLBACKS:
            if self._known(name, mascot):
                mascot.previous_behavior = self.behavior_by_name(mascot, name)
                return name
        order = self.actions_of(mascot).order
        if order:
            return order[0]
        return None
