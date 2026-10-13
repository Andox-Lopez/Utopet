# -*- coding: utf-8 -*-
"""
标签 / 属性别名表 —— 日 · 中 · 英 三语
Tag & Attribute Alias Table —— Japanese / Chinese / English
==============================================================================
原版 Group-Finity Shimeji 的配置全部使用日文标签（動作 / ポーズ / アニメーション …）。
本模块把日文标签与属性名归一化成英文规范名，并同时接受中文与英文写法。

The original Group-Finity Shimeji configuration uses Japanese tags throughout.
This module normalises JP / ZH / EN spellings of every tag and attribute into a
canonical English key, so that:
  * 原版日文 XML 100% 兼容 (legacy Japanese XML stays 100% compatible)
  * 可以用中文重写 (you may author the configuration in Chinese)
  * 可以用英文重写 (you may author the configuration in English)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 元素标签 / Element tags
# ---------------------------------------------------------------------------
TAG_ALIASES: dict[str, tuple[str, ...]] = {
    # 根元素 / root
    "mascot":         ("マスコット", "mascot", "吉祥物", "桌宠"),
    # 动作列表 / action list
    "actionList":     ("動作リスト", "actionList", "动作列表"),
    # 动作 / action
    "action":         ("動作", "action", "动作"),
    # 动画 / animation
    "animation":      ("アニメーション", "animation", "动画"),
    # 姿势(一帧) / pose (single frame)
    "pose":           ("ポーズ", "pose", "姿势", "帧"),
    # 动作引用 / action reference
    "actionRef":      ("動作参照", "actionRef", "动作引用"),
    # 常量 / constant
    "constant":       ("定数", "constant", "常量"),
    # 行为列表 / behavior list
    "behaviorList":   ("行動リスト", "behaviorList", "行为列表"),
    # 行为 / behavior
    "behavior":       ("行動", "behavior", "行为"),
    # 条件块（包裹若干行为）/ conditional block wrapping behaviors
    "conditionBlock": ("条件", "conditionBlock", "条件块"),
    # 后续行为列表 / next-behavior list
    "nextList":       ("次の行動リスト", "nextBehaviorList", "后续行为列表"),
    # 行为引用 / behavior reference
    "behaviorRef":    ("行動参照", "behaviorRef", "行为引用"),
}

# ---------------------------------------------------------------------------
# 属性 / Attributes
# ---------------------------------------------------------------------------
ATTR_ALIASES: dict[str, tuple[str, ...]] = {
    "name":         ("名前", "name", "名称", "名字"),
    "kind":         ("種類", "kind", "type", "类型", "种类"),
    "frame":        ("枠", "frame", "anchorFrame", "框", "锚框"),
    "repeat":       ("繰り返し", "repeat", "重复", "循环"),
    "clazz":        ("クラス", "class", "clazz", "类"),
    "condition":    ("条件", "condition", "条件表达式"),
    "image":        ("画像", "image", "图像", "图片"),
    "base":         ("基準座標", "base", "anchorPoint", "基准坐标"),
    "velocity":     ("移動速度", "velocity", "移动速度"),
    "duration":     ("長さ", "duration", "时长", "长度"),
    "add":          ("追加", "add", "追加"),
    "frequency":    ("頻度", "frequency", "频率"),
    "value":        ("値", "value", "值"),
    # 物理参数 / physics parameters
    "speed":        ("速度", "speed", "速度"),
    "gravity":      ("重力", "gravity", "重力"),
    "airX":         ("空気抵抗X", "airResistanceX", "空气阻力X", "空气阻力x"),
    "airY":         ("空気抵抗Y", "airResistanceY", "空气阻力Y", "空气阻力y"),
    "initVX":       ("初速X", "initialVelocityX", "初速X", "初速度X"),
    "initVY":       ("初速Y", "initialVelocityY", "初速Y", "初速度Y"),
    # IE（窗口）相关 / window (IE) related
    "ieEdgeX":      ("IEの端X", "ieEdgeX", "窗口边缘X", "IE边缘X"),
    "ieEdgeY":      ("IEの端Y", "ieEdgeY", "窗口边缘Y", "IE边缘Y"),
    # 增殖相关 / breeding related
    "birthX":       ("生まれる場所X", "birthX", "出生位置X"),
    "birthY":       ("生まれる場所Y", "birthY", "出生位置Y"),
    "bornBehavior": ("生まれた時の行動", "bornBehavior", "出生时的行为", "出生行为"),
    # 位移 / offset
    "x":            ("X", "x", "横位移", "位移X"),
    "y":            ("Y", "y", "纵位移", "位移Y"),
    # 朝向 / facing
    "lookRight":    ("右向き", "lookRight", "朝右", "面向右"),
    # 目的地 / destination
    "destX":        ("目的地X", "destinationX", "目的地X", "目标X"),
    "destY":        ("目的地Y", "destinationY", "目的地Y", "目标Y"),
}

# ---------------------------------------------------------------------------
# 动作种类 / Action kinds
# ---------------------------------------------------------------------------
KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "stay":      ("静止", "stay", "still", "静止"),
    "move":      ("移動", "move", "移动"),
    "fixed":     ("固定", "fixed", "固定"),
    "composite": ("複合", "composite", "sequence", "复合"),
    "select":    ("選択", "select", "branch", "选择"),
    "builtin":   ("組み込み", "builtin", "built-in", "内建"),
}

# ---------------------------------------------------------------------------
# 锚框 / Anchor frames
# ---------------------------------------------------------------------------
FRAME_ALIASES: dict[str, tuple[str, ...]] = {
    "ground":  ("地面", "ground", "floor", "地面"),
    "wall":    ("壁", "wall", "墙", "墙壁"),
    "ceiling": ("天井", "ceiling", "天花板"),
}


def _build(aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """把别名表反转成 {任意写法: 规范名} / Build the reverse lookup table."""
    table: dict[str, str] = {}
    for canonical, names in aliases.items():
        for n in names:
            table[n] = canonical
        table[canonical] = canonical
    return table


TAG_LOOKUP = _build(TAG_ALIASES)
ATTR_LOOKUP = _build(ATTR_ALIASES)
KIND_LOOKUP = _build(KIND_ALIASES)
FRAME_LOOKUP = _build(FRAME_ALIASES)


def strip_ns(tag: str) -> str:
    """去掉 XML 命名空间前缀 / Strip the XML namespace prefix."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def canon_tag(elem) -> str:
    """返回元素的规范标签名 / Return the canonical tag name of an element."""
    return TAG_LOOKUP.get(strip_ns(elem.tag), strip_ns(elem.tag))


def canon_kind(raw: str | None) -> str | None:
    """归一化动作种类 / Normalise an action kind."""
    return KIND_LOOKUP.get(raw, raw) if raw is not None else None


def canon_frame(raw: str | None) -> str | None:
    """归一化锚框 / Normalise an anchor frame."""
    return FRAME_LOOKUP.get(raw, raw) if raw is not None else None


def attr(elem, key: str, default=None):
    """
    按规范名读取属性（支持日/中/英任意写法）
    Read an attribute by canonical key, accepting any JP/ZH/EN spelling.
    """
    if elem is None:
        return default
    for raw_name, raw_value in elem.attrib.items():
        if ATTR_LOOKUP.get(strip_ns(raw_name)) == key:
            return raw_value
    return default


def iter_attrs(elem):
    """遍历 (规范名, 原始值) / Iterate over (canonical key, raw value) pairs."""
    for raw_name, raw_value in elem.attrib.items():
        yield ATTR_LOOKUP.get(strip_ns(raw_name), strip_ns(raw_name)), raw_value


def children(elem, tag: str):
    """按规范标签名取子元素 / Yield children matching a canonical tag."""
    for child in elem:
        if canon_tag(child) == tag:
            yield child
