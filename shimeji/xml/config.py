# -*- coding: utf-8 -*-
"""
配置文件解析 / Configuration parsing
==============================================================================
解析 Actions.xml（动作定义）与 Behavior.xml（行为定义），支持日 · 中 · 英三语标签。

Parses Actions.xml (action definitions) and Behavior.xml (behaviour definitions),
accepting Japanese, Chinese or English tag / attribute spellings.
"""

from __future__ import annotations

import io
import os
import xml.etree.ElementTree as ET

from . import aliases as A
from .expr import Expr, Val

__all__ = [
    "Pose", "Animation", "ActionRef", "ActionDef", "ActionSet",
    "BehaviorRef", "NextList", "BehaviorDef", "BehaviorSet",
    "load_actions", "load_behavior",
]

# XML 中出现的固定取值（原版日文键）与其规范名
# Fixed literal values found in the original XML and their canonical names.
_KIND_LITERALS = {
    "静止": "stay", "移動": "move", "固定": "fixed",
    "複合": "composite", "選択": "select", "組み込み": "builtin",
}
_FRAME_LITERALS = {"地面": "ground", "壁": "wall", "天井": "ceiling"}


# ---------------------------------------------------------------------------
# 动作 / Actions
# ---------------------------------------------------------------------------
class Pose:
    """一帧姿势 / A single animated frame."""

    __slots__ = ("image", "base", "velocity", "duration")

    def __init__(self, image: Val, base: Val, velocity: Val, duration: Val):
        self.image = image          # 画像 / image path
        self.base = base            # 基準座標 / anchor point inside the image
        self.velocity = velocity    # 移動速度 / movement per tick
        self.duration = duration    # 長さ / duration in ticks

    def __repr__(self) -> str:  # pragma: no cover
        return "Pose(%s)" % self.image.text()


class Animation:
    """一组姿势（可带条件）/ A pose sequence, optionally guarded by a condition."""

    __slots__ = ("condition", "poses")

    def __init__(self, condition: Expr | None, poses: list[Pose]):
        self.condition = condition
        self.poses = poses

    @property
    def total_duration(self) -> int:
        return sum(int(p.duration.num({}, 1)) for p in self.poses)


class ActionRef:
    """对另一个动作的引用（可覆盖参数、可带条件）/ A reference to another action, with overrides."""

    __slots__ = ("name", "params", "condition")

    def __init__(self, name: str, params: dict[str, Val], condition: Expr | None = None):
        self.name = name
        self.params = params
        self.condition = condition

    def __repr__(self) -> str:  # pragma: no cover
        return "ActionRef(%s)" % self.name


class ActionDef:
    """一个动作定义 / An action definition."""

    __slots__ = ("name", "kind", "frame", "repeat", "clazz",
                 "condition", "animations", "children", "params")

    def __init__(self):
        self.name: str | None = None
        self.kind: str = "stay"          # 種類 / kind
        self.frame: str | None = None    # 枠 / anchor frame (ground / wall / ceiling)
        self.repeat: bool = False        # 繰り返し / repeat
        self.clazz: str | None = None    # クラス / built-in class
        self.condition: Expr | None = None
        self.animations: list[Animation] = []
        self.children: list = []         # ActionRef | ActionDef
        self.params: dict[str, Val] = {}

    # 内建动作类名（去掉包前缀）/ built-in class simple name
    @property
    def builtin(self) -> str | None:
        if not self.clazz:
            return None
        return self.clazz.rsplit(".", 1)[-1]

    def __repr__(self) -> str:  # pragma: no cover
        return "ActionDef(%s, %s)" % (self.name, self.kind)


class ActionSet:
    """全部动作定义 / All action definitions."""

    def __init__(self):
        self.actions: dict[str, ActionDef] = {}
        self.order: list[str] = []

    def __contains__(self, name) -> bool:
        return name in self.actions

    def __getitem__(self, name) -> ActionDef:
        return self.actions[name]

    def get(self, name):
        return self.actions.get(name)

    def add(self, d: ActionDef):
        if d.name:
            self.actions[d.name] = d
            if d.name not in self.order:
                self.order.append(d.name)


# ---------------------------------------------------------------------------
# 行为 / Behaviors
# ---------------------------------------------------------------------------
class BehaviorRef:
    __slots__ = ("name", "frequency", "condition")

    def __init__(self, name: str, frequency: Val, condition: Expr | None):
        self.name = name
        self.frequency = frequency   # 頻度 / frequency weight
        self.condition = condition


class NextList:
    """本行为结束后可接续的行为列表 / Behaviours that may follow this one."""

    __slots__ = ("add", "refs")

    def __init__(self, add: bool, refs: list[BehaviorRef]):
        self.add = add    # 追加 / True = merge with the global pool
        self.refs = refs


class BehaviorDef:
    __slots__ = ("name", "frequency", "condition", "next_list")

    def __init__(self, name: str, frequency: Val, condition: Expr | None,
                 next_list: NextList | None):
        self.name = name
        self.frequency = frequency
        self.condition = condition
        self.next_list = next_list

    def __repr__(self) -> str:  # pragma: no cover
        return "BehaviorDef(%s)" % self.name


class BehaviorSet:
    """全部行为定义 / All behaviour definitions."""

    def __init__(self):
        self.constants: dict[str, float] = {}
        self.entries: list[tuple[Expr | None, BehaviorDef]] = []

    def behaviors(self) -> list[BehaviorDef]:
        return [b for _, b in self.entries]


# ---------------------------------------------------------------------------
# 解析 / Parsing
# ---------------------------------------------------------------------------
def _params_from(elem) -> dict[str, Val]:
    """提取除保留键之外的所有属性作为参数 / Collect non-reserved attributes as params."""
    reserved = {"name", "kind", "frame", "repeat", "clazz", "condition"}
    out: dict[str, Val] = {}
    for key, raw in A.iter_attrs(elem):
        if key in reserved:
            continue
        out[key] = Val(raw)
    return out


def _parse_pose(elem) -> Pose:
    return Pose(
        Val(A.attr(elem, "image")),
        Val(A.attr(elem, "base", "64,128")),
        Val(A.attr(elem, "velocity", "0,0")),
        Val(A.attr(elem, "duration", "1")),
    )


def _parse_action(elem) -> ActionDef:
    d = ActionDef()
    d.name = A.attr(elem, "name")
    raw_kind = A.attr(elem, "kind")
    d.kind = _KIND_LITERALS.get(raw_kind, A.canon_kind(raw_kind) or "stay")
    raw_frame = A.attr(elem, "frame")
    d.frame = _FRAME_LITERALS.get(raw_frame, A.canon_frame(raw_frame))
    repeat = A.attr(elem, "repeat")
    d.repeat = str(repeat).strip().lower() in ("true", "yes", "on", "1") if repeat else False
    d.clazz = A.attr(elem, "clazz")
    cond = A.attr(elem, "condition")
    d.condition = Expr.parse(cond)
    d.params = _params_from(elem)

    for child in elem:
        tag = A.canon_tag(child)
        if tag == "animation":
            c = Expr.parse(A.attr(child, "condition"))
            poses = [_parse_pose(p) for p in A.children(child, "pose")]
            if poses:
                d.animations.append(Animation(c, poses))
        elif tag == "action":
            d.children.append(_parse_action(child))
        elif tag == "actionRef":
            d.children.append(ActionRef(A.attr(child, "name"), _params_from(child),
                                        Expr.parse(A.attr(child, "condition"))))
    return d


def load_actions(path: str) -> ActionSet:
    """读取 Actions.xml / Load Actions.xml."""
    with io.open(path, encoding="utf-8-sig") as f:
        root = ET.fromstring(f.read())
    s = ActionSet()
    for alist in A.children(root, "actionList"):
        for elem in A.children(alist, "action"):
            d = _parse_action(elem)
            s.add(d)
    return s


def _parse_behavior(elem) -> BehaviorDef:
    name = A.attr(elem, "name")
    freq = Val(A.attr(elem, "frequency", "0"))
    cond = Expr.parse(A.attr(elem, "condition"))
    nxt = None
    for child in elem:
        if A.canon_tag(child) == "nextList":
            add = str(A.attr(child, "add", "true")).strip().lower() in ("true", "yes", "on", "1")
            refs = []
            for r in A.children(child, "behaviorRef"):
                refs.append(BehaviorRef(A.attr(r, "name"),
                                        Val(A.attr(r, "frequency", "1")),
                                        Expr.parse(A.attr(r, "condition"))))
            nxt = NextList(add, refs)
    return BehaviorDef(name, freq, cond, nxt)


def load_behavior(path: str) -> BehaviorSet:
    """读取 Behavior.xml / Load Behavior.xml."""
    with io.open(path, encoding="utf-8-sig") as f:
        root = ET.fromstring(f.read())
    s = BehaviorSet()
    for elem in root.iter():
        if A.canon_tag(elem) == "constant":
            name = A.attr(elem, "name")
            if name:
                s.constants[name] = Val(A.attr(elem, "value", "0")).num({}, 0)
    for blist in A.children(root, "behaviorList"):
        for child in blist:
            tag = A.canon_tag(child)
            if tag == "behavior":
                s.entries.append((None, _parse_behavior(child)))
            elif tag == "conditionBlock":
                outer = Expr.parse(A.attr(child, "condition"))
                for b in A.children(child, "behavior"):
                    bd = _parse_behavior(b)
                    cond = outer
                    if bd.condition is not None:
                        cond = bd.condition if outer is None else _And(outer, bd.condition)
                    s.entries.append((cond, bd))
    return s


class _And(Expr):
    """两个条件的合取（条件块 + 行为自身条件）/ Conjunction of a block condition and its own."""

    def __init__(self, a: Expr, b: Expr):
        super().__init__("(%s) and (%s)" % (a.raw, b.raw), True)


def find_conf(char_dir: str) -> tuple[str, str]:
    """
    定位角色目录下的 conf / Locate Actions.xml and Behavior.xml for a character.

    依次尝试 / Search order:
      1. <char_dir>/conf/
      2. <char_dir>/../conf/
      3. 应用根目录 conf/ / the application's own conf directory
    """
    for base in (os.path.join(char_dir, "conf"),
                 os.path.join(os.path.dirname(char_dir.rstrip("\\/")), "conf")):
        a = os.path.join(base, "Actions.xml")
        b = os.path.join(base, "Behavior.xml")
        if os.path.exists(a) and os.path.exists(b):
            return a, b
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(root, "conf")
    return os.path.join(base, "Actions.xml"), os.path.join(base, "Behavior.xml")
