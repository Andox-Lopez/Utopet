# -*- coding: utf-8 -*-
"""验证 `xml/expr.py`：表达式翻译器 + `Val` 的取值。

⭐ 这个模块是**所有行为条件的求值基础** —— `Behavior.xml` / `Actions.xml`
里每一条 `#{...}` / `${...}` 都在这里翻译成 Python 再求值。它坏掉的症状
极其隐蔽：**整条行为永远不会被选中，而且完全静默**（`Expr.__init__` 里
`except SyntaxError: self.code = None` 把编译失败吞掉了）。

## 2026-10-29 修的真 bug

原版 `Behavior.xml` 里「壁から落ちる」（从墙上落下）那条行为的条件是：

```
( mascot.lookRight ? ( ... ) : ( ... ) ) and (!floor.isOn(anchor))
```

**整个三元被一对括号包住**。旧的 `_convert_ternary` 只在 `depth == 0` 的
位置找 `?`，括号让 depth 变深 → 里面的 `?` 永远找不到 → 翻译结果里还留着
`?` → Python 语法错误 → `code = None` → **这条行为永远不会被选中**。

而且 **Ayaka / Miku / 花卷 三个角色包全都中招**（共用同一份原版配置）。

修法：`_split_brackets()` 先把括号内的内容**递归**翻译掉，外层的 `?` 就
露出来了。

所以本文件除了单元测试，还有一节**直接扫描真实角色包**——那才是能真正
兜住这类问题的关卡。

用法：python analysis/verify_expr.py
"""

from __future__ import annotations

import glob
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimeji.xml.expr import Expr, ExprError, Val, _to_python  # noqa: E402

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


def compiles(src: str) -> bool:
    return Expr(src).code is not None


def main() -> int:
    # ==============================================================
    section("1. Java/Rhino 语法翻译成 Python")
    cases = [
        ("a && b", "a  and  b"),
        ("a || b", "a  or  b"),
        # ⭐ `!` 译成 `not `（**后缀**空格，不是前缀）—— 前缀空格会让
        # 以 `!` 开头的表达式翻译后以空格开头，eval 模式直接拒绝
        # （"unexpected indent"）。真实配置里有 9 处这种写法。
        ("!a", "not a"),
        ("a != b", "a != b"),                 # ⭐ `!` 不能破坏 `!=`
        ("a !== b", "a !== b"),
        ("!a && !b", "not a  and  not b"),
        ("true", "True"),
        ("false", "False"),
        ("null", "None"),
    ]
    for src, expect in cases:
        got = _to_python(src)
        check(got == expect, "翻译 %r" % src, "got=%r expect=%r" % (got, expect))

    # Math.* -> Python
    check("_rnd()" in _to_python("Math.random()"), "Math.random() -> _rnd()")
    check("abs(" in _to_python("Math.abs(-3)"), "Math.abs -> abs")
    check("_math.floor(" in _to_python("Math.floor(1.5)"), "Math.floor -> _math.floor")
    check("_math.ceil(" in _to_python("Math.ceil(1.5)"), "Math.ceil -> _math.ceil")
    check("_math.sqrt(" in _to_python("Math.sqrt(4)"), "Math.sqrt -> _math.sqrt")
    check("_math.pow(" in _to_python("Math.pow(2,3)"), "Math.pow -> _math.pow")

    # ==============================================================
    section("2. 三元运算符（含**括号包裹**这个真 bug）")
    check("if" in _to_python("a ? b : c"), "三元被翻译成 Python 条件表达式")
    check(compiles("a ? b : c"), "普通三元能编译")
    check(compiles("a ? b : c ? d : e"), "嵌套三元能编译")
    # ⭐ 下面这条是 2026-10-29 修的真 bug
    check(compiles("(a ? b : c) ? d : e"),
          "**整个三元被括号包住**也能编译（真 bug 的回归测试）")
    check(compiles("(a ? b : c) && d"), "括号三元 + 逻辑与能编译")
    check(compiles("(a && b) ? c : d"), "括号逻辑 + 三元能编译")
    check(compiles("((a ? b : c) ? d : e) ? f : g"), "多层括号嵌套能编译")
    # 字符串字面量里的括号不是分组
    check(compiles('x == "a(b)" ? 1 : 2'), "字符串字面量里的括号不被误处理")
    # ⭐ 以 `!` 开头的表达式必须能编译（2026-10-29 修的第二个真 bug：
    # 旧翻译在 `!` 前面插空格 -> eval 模式拒绝前导空格）
    check(compiles("!a"), "**以 ! 开头**的表达式能编译（真 bug 的回归测试）")
    check(compiles("!a.b.c(d)"), "以 ! 开头的属性调用能编译")
    check(compiles("!a && !b"), "以 ! 开头的逻辑表达式能编译")
    check(_to_python("!a").startswith("not "),
          "`!` 译成 not 且**不带前导空格**", repr(_to_python("!a")))

    # ==============================================================
    section("3. Expr：parse / eval / 失败")
    e = Expr.parse("#{a + b}")
    check(e is not None and e.dynamic, "#{...} 是动态表达式")
    e2 = Expr.parse("${a + b}")
    check(e2 is not None and not e2.dynamic, "${...} 是静态表达式")
    check(Expr.parse("plain text") is None, "普通文本不是表达式")
    check(Expr.parse(None) is None, "None 不是表达式")

    # ⚠️ `Expr` 直接构造时 raw 是**表达式内容**，`#{}` 是 `parse()` 剥掉的 ——
    # 传 "#{1 + 2}" 会连着花括号一起翻译，必然编译失败。
    # Expr's raw is the expression *body*; parse() strips the #{...}.
    check(Expr("1 + 2").eval({}) == 3, "eval 能算出结果")
    # 命名空间
    check(Expr("x * 2").eval({"x": 21}) == 42, "eval 能读到命名空间")
    # 除零 -> ExprError
    try:
        Expr("1 / 0").eval({})
        check(False, "除零应抛 ExprError")
    except ExprError:
        check(True, "除零抛 ExprError")
    # 编译失败 -> eval 抛 ExprError
    try:
        Expr("#{!!!").eval({})
        check(False, "编译失败应抛 ExprError")
    except ExprError:
        check(True, "编译失败抛 ExprError")
    # 翻译不了 -> code 是 None
    check(Expr("!!!").code is None, "翻译不了的表达式 code 为 None")
    check(not compiles("a ? b"), "缺 ':' 的三元编译不了")

    # ==============================================================
    section("4. Val：字面量与类型转换")
    check(Val("123").get({}) == 123, "字面量整数")
    check(Val("1.5").get({}) == 1.5, "字面量浮点")
    check(Val("true").get({}) is True, "字面量 true")
    check(Val("yes").get({}) is True, "字面量 yes")
    check(Val("off").get({}) is False, "字面量 off")
    check(Val("hello").get({}) == "hello", "字面量字符串")
    check(Val(None).get({}, "d") == "d", "None 取默认值")

    # num
    check(Val("5").num({}) == 5.0, "num() 取整数")
    check(Val("true").num({}) == 1.0, "num() 把 true 当 1")
    check(Val("false").num({}) == 0.0, "num() 把 false 当 0")
    check(Val("abc").num({}, 7.0) == 7.0, "num() 转换失败用默认值")
    check(Val("#{x}").num({"x": 3}) == 3.0, "num() 能算表达式")

    # bool
    check(Val("true").bool({}) is True, "bool() 读 true")
    check(Val("0").bool({}) is False, "bool() 把 0 当假")
    check(Val("1").bool({}) is True, "bool() 把 1 当真")
    check(Val("#{x > 0}").bool({"x": 5}) is True, "bool() 能算表达式")
    check(Val("#{x > 0}").bool({"x": -5}) is False, "bool() 表达式为假")

    # pair
    check(Val("10,20").pair({}) == (10.0, 20.0), "pair() 解析 'x,y'")
    check(Val("10，20").pair({}) == (10.0, 20.0), "pair() 认全角逗号")
    check(Val("bad").pair({}, (1.0, 2.0)) == (1.0, 2.0), "pair() 格式错用默认值")
    check(Val("#{[x, y]}").pair({"x": 3, "y": 4}) == (3.0, 4.0),
          "pair() 能取表达式的二元列表")

    # ⭐ Val.get 会吞掉 ExprError 返回默认值 —— 这正是「无声失败」的来源，
    # 所以必须有测试钉住这个行为（它是有意的降级，但别悄悄改了语义）。
    check(Val("#{1 / 0}").get({}, "fallback") == "fallback",
          "表达式出错时 get() 返回默认值（不抛异常）")

    # ==============================================================
    section("5. 真实角色包：所有表达式都必须能编译")
    # ⭐ 这是最重要的一节 —— 单元测试只能验证「我想到的写法」，
    # 扫真实配置才能发现「配置里真的有人这么写」。
    # 原版 Behavior.xml 里就有三处括号包裹的三元，之前全部编译失败。
    # ⚠️⚠️ **必须走真实解析路径**（`load_actions` / `load_behavior`），
    # **不能直接正则读原始 XML 文本**！
    # 原始文本里 `<` 写成 `&lt;`、`&&` 写成 `&amp;&amp;` —— 那是 **XML 实体
    # 转义**，解析器（`ET.fromstring`）会反转义。我一开始用正则扫原始文本，
    # 报出「108 处编译失败」，全是假警报；换成真实解析路径后是 **0 处**。
    # 这个坑我踩了两次（诊断脚本 + 测试），所以在这里写清楚。
    #
    # Scan through the real parser, never the raw XML text: the raw text
    # contains XML entity escapes that the parser resolves.
    from shimeji.xml.config import load_actions, load_behavior

    def _attrs(obj):
        """`__slots__` 的类要用它自己的 __slots__（`dir()` 不一定返回）。"""
        slots = getattr(type(obj), "__slots__", None)
        if slots:
            return list(slots)
        return [a for a in dir(obj) if not a.startswith("_")]

    def _collect(obj, acc, depth=0):
        if depth > 8:
            return
        for attr in _attrs(obj):
            try:
                v = getattr(obj, attr)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(v, Expr):
                acc.append(v)
            elif isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, Expr):
                        acc.append(item)
                    elif isinstance(item, (list, tuple)):
                        _collect(item, acc, depth + 1)
                    elif hasattr(item, "__slots__"):
                        _collect(item, acc, depth + 1)
            elif isinstance(v, dict):
                for item in v.values():
                    if isinstance(item, Expr):
                        acc.append(item)
                    elif hasattr(item, "__slots__"):
                        _collect(item, acc, depth + 1)
            elif hasattr(v, "__slots__") and not isinstance(
                    v, (str, int, float, bool)):
                _collect(v, acc, depth + 1)

    broken = []
    total = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "characters", "*", "conf",
                                          "*.xml"))):
        base = os.path.basename(f).lower()
        try:
            if base == "actions.xml":
                s = load_actions(f)
                for d in s.actions.values():
                    acc = []
                    _collect(d, acc)
                    total += len(acc)
                    broken += [(base, x.raw[:80]) for x in acc
                               if x.code is None]
            elif base == "behavior.xml":
                b = load_behavior(f)
                acc = []
                for cond, bd in b.entries:
                    if cond is not None:
                        acc.append(cond)
                    _collect(bd, acc)
                total += len(acc)
                broken += [(base, x.raw[:80]) for x in acc if x.code is None]
        except Exception as exc:  # noqa: BLE001
            check(False, "解析 %s" % base, str(exc))

    check(total > 0, "扫到了角色包里的表达式", "%d 处" % total)
    check(not broken,
          "角色包里的表达式全部能编译",
          "失败 %d 处：%s" % (len(broken), broken[:3]))

    # ==============================================================
    section("6. 审计脚本自检")
    # 判定函数本身要认得出「编译失败」
    check(not compiles("a ? b"), "自检：缺 ':' 的三元被认成编译失败")
    check(compiles("(a ? b : c) ? d : e"),
          "自检：括号包裹的三元被认成能编译（真 bug 的判据）")

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
