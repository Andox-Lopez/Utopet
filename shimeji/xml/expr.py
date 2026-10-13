# -*- coding: utf-8 -*-
"""
表达式求值器 / Expression Evaluator
==============================================================================
原版 Shimeji 使用 Mozilla Rhino（js.jar）执行配置里的表达式。这里实现一个
等价的小型求值器，把配置里的表达式翻译成 Python 再求值。

The original Shimeji evaluates configuration expressions with Mozilla Rhino
(js.jar).  This module provides an equivalent mini-evaluator that translates
those expressions into Python and evaluates them.

三种写法 / Three syntaxes
------------------------------------------------------------------------------
  #{...}   动态表达式 —— 每次求值（每帧）都会重新计算
           Dynamic expression: re-evaluated on every frame.
  ${...}   静态表达式 —— 动作实例化时求值一次
           Static expression: evaluated once when the action is instantiated.
  普通字面量 直接按 数字 / 布尔 / 字符串 解析
           Plain literal: parsed as number / boolean / string.
"""

from __future__ import annotations

import math
import random
import re

__all__ = ["Expr", "Val", "ExprError"]


class ExprError(Exception):
    """表达式求值失败 / Raised when an expression cannot be evaluated."""


# 求值全局命名空间 / Globals available to every expression
_GLOBALS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
    "_rnd": random.random,
    "_math": math,
}


def _convert_ternary(s: str) -> str:
    """把 `a ? b : c` 转成 Python 条件表达式 / Convert `a ? b : c` to a Python conditional."""
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "?" and depth == 0:
            d = 0
            tern = 0
            j = i + 1
            colon = -1
            while j < len(s):
                c = s[j]
                if c in "([{":
                    d += 1
                elif c in ")]}":
                    d -= 1
                elif d == 0 and c == "?":
                    tern += 1
                elif d == 0 and c == ":":
                    if tern > 0:
                        tern -= 1
                    else:
                        colon = j
                        break
                j += 1
            if colon < 0:
                break
            cond = _convert_ternary(s[:i])
            yes = _convert_ternary(s[i + 1:colon])
            no = _convert_ternary(s[colon + 1:])
            return "((%s) if (%s) else (%s))" % (yes.strip(), cond.strip(), no.strip())
        i += 1
    return s


def _to_python(src: str) -> str:
    """把配置表达式翻译成 Python 源码 / Translate a config expression into Python source."""
    # 配置里的表达式常被折行，先压平成一行 / expressions are often wrapped; flatten first
    s = re.sub(r"[\r\n\t]+", " ", src).strip()
    s = _convert_ternary(s)
    s = s.replace("&&", " and ").replace("||", " or ")
    # `!` 取反（不破坏 `!=`）/ logical NOT, keeping `!=` intact
    s = re.sub(r"!(?!=)", " not ", s)
    s = re.sub(r"\bMath\.random\s*\(\s*\)", "_rnd()", s)
    s = re.sub(r"\bMath\.(abs|min|max|round)\s*\(", r"\1(", s)
    s = re.sub(r"\bMath\.floor\s*\(", "_math.floor(", s)
    s = re.sub(r"\bMath\.ceil\s*\(", "_math.ceil(", s)
    s = re.sub(r"\bMath\.sqrt\s*\(", "_math.sqrt(", s)
    s = re.sub(r"\bMath\.pow\s*\(", "_math.pow(", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    s = re.sub(r"\bnull\b", "None", s)
    return s


class Expr:
    """一个已编译的表达式 / A compiled expression."""

    __slots__ = ("raw", "dynamic", "code")

    def __init__(self, raw: str, dynamic: bool = True):
        self.raw = raw
        self.dynamic = dynamic
        try:
            self.code = compile(_to_python(raw), "<shimeji-expr>", "eval")
        except SyntaxError:
            # 无法翻译的表达式退化成"永远失败"，避免拖垮整个配置加载
            # Untranslatable expressions degrade to "always fails" instead of
            # breaking the whole configuration load.
            self.code = None

    @staticmethod
    def parse(raw: str | None) -> "Expr | None":
        """
        解析属性值；带 `#{}` / `${}` 包裹才视为表达式。
        Parse an attribute value; only `#{}` / `${}` wrapped text is an expression.
        """
        if raw is None:
            return None
        s = raw.strip()
        if s.startswith("#{") and s.endswith("}"):
            return Expr(s[2:-1], True)
        if s.startswith("${") and s.endswith("}"):
            return Expr(s[2:-1], False)
        return None

    def eval(self, ns: dict):
        if self.code is None:
            raise ExprError("untranslatable: %s" % self.raw)
        try:
            return eval(self.code, _GLOBALS, ns)
        except Exception as exc:  # pragma: no cover - defensive
            raise ExprError("%s: %s" % (self.raw, exc)) from exc

    def __repr__(self) -> str:  # pragma: no cover
        return "Expr(%r, dynamic=%s)" % (self.raw, self.dynamic)


def _coerce(text, default=None):
    """把字面量字符串转成 Python 值 / Coerce a literal string into a Python value."""
    if text is None:
        return default
    t = text.strip()
    if t == "":
        return default
    low = t.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


class Val:
    """
    一个可求值的属性值（字面量 / 静态表达式 / 动态表达式）。
    An attribute value that may be a literal, a static or a dynamic expression.
    """

    __slots__ = ("raw", "expr")

    def __init__(self, raw):
        self.raw = raw
        self.expr = Expr.parse(raw if isinstance(raw, str) else None)

    @property
    def is_dynamic(self) -> bool:
        return self.expr is not None and self.expr.dynamic

    @property
    def is_static(self) -> bool:
        return self.expr is not None and not self.expr.dynamic

    def get(self, ns: dict, default=None):
        """求值，失败时返回 default / Evaluate, falling back to *default*."""
        if self.expr is not None:
            try:
                return self.expr.eval(ns)
            except ExprError:
                return default
        return _coerce(self.raw, default)

    def num(self, ns: dict, default: float = 0.0) -> float:
        v = self.get(ns, default)
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    def bool(self, ns: dict, default: bool = False) -> bool:
        v = self.get(ns, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "on", "1")
        return bool(default)

    def pair(self, ns: dict, default=(0.0, 0.0)):
        """解析 "x,y" 形式的坐标/速度 / Parse an "x,y" coordinate or velocity pair."""
        if self.expr is not None:
            v = self.get(ns, None)
            if isinstance(v, (tuple, list)) and len(v) == 2:
                return float(v[0]), float(v[1])
            if v is None:
                return default
            return float(v), float(default[1])
        if self.raw is None:
            return default
        parts = str(self.raw).replace("，", ",").split(",")
        if len(parts) != 2:
            return default
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            return default

    def text(self) -> str:
        return "" if self.raw is None else str(self.raw)

    def __repr__(self) -> str:  # pragma: no cover
        return "Val(%r)" % (self.raw,)
