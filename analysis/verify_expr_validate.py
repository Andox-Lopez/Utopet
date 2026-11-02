# -*- coding: utf-8 -*-
"""验证 F6（表达式实时校验）：写错的 #{} 表达式当场能被识别，不再静默失效。

## 背景

`Expr` 遇到无法编译的表达式会退化成「永远失败」—— 以前用户在自定义 XML 里
写错一个表达式，运行时看到的是「动作没了」，日志里一个字都没有。
F6 提供编译期校验，把错误摆到台面。

测两层：
- `xml.expr.check_expression()`：单个字符串的校验（纯函数）
- `custom.CustomConfig.validate_expressions()`：扫描一份自定义配置
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimeji.custom import CustomConfig  # noqa: E402
from shimeji.xml.expr import check_expression  # noqa: E402

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
    # ==================================================================
    section("1. check_expression：合法的")
    ok, why = check_expression(None)
    check(ok, "None 合法")
    ok, _ = check_expression("")
    check(ok, "空串合法")
    ok, _ = check_expression("10")
    check(ok, "普通字面量（不带 #{}）不校验、合法")
    ok, _ = check_expression("64,128")
    check(ok, "坐标字面量合法")
    # 合法的动态表达式
    for good in ("#{1 + 2}", "${footX + 10}", "#{floor(footY)}",
                 "#{true ? 1 : 0}", "#{workArea.bottom - 64}"):
        ok, why = check_expression(good)
        check(ok, "合法表达式：%s" % good, why)

    # ==================================================================
    section("2. check_expression：非法的能识别并给出原因")
    # ⭐ 只测**编译期**就能发现的语法错误。像 `#{floor(}` 会被翻译器补成
    # `floor()`（空调用，能编译、运行时才因缺参数报错）—— 那不是编译期错误，
    # check_expression 故意不报（它不做求值，没有真实命名空间）。
    for bad in ("#{1 +}", "#{? ? ?}", "#{1 1 1}", "#{if if}"):
        ok, why = check_expression(bad)
        check(not ok, "识别出非法表达式：%s" % bad, why[:40])
        check(why != "", "非法时附带了原因说明（不是空字符串）")

    # 能编译但运行时才出错的（如空调用）-> 编译期不报，属于预期
    ok, _ = check_expression("#{floor()}")
    check(ok, "能编译的空调用不做编译期拦截（求值期错误不在此范围）")

    # 只有右半/左半边括号不算表达式 -> 当字面量放行（不误伤）
    ok, _ = check_expression("#{1 + 2")
    check(ok, "没闭合的 #{ 当成普通文本，不误报")

    # ==================================================================
    section("3. CustomConfig.validate_expressions：扫描一份配置")
    d = tempfile.mkdtemp(prefix="utopet_expr_")
    try:
        # 构造一份自定义 XML：一个好动作、一个带坏表达式的动作
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<ShimejiData>\n'
            '  <動作リスト>\n'
            '    <動作 名前="好动作" 種類="移動" 枠="地面">\n'
            '      <アニメーション>\n'
            '        <ポーズ 画像="a.png" 基準座標="64,128" 移動速度="#{1+1},0" 長さ="10"/>\n'
            '      </アニメーション>\n'
            '    </動作>\n'
            '    <動作 名前="坏动作" 種類="移動" 枠="地面">\n'
            '      <アニメーション>\n'
            '        <ポーズ 画像="b.png" 基準座標="64,128" '
            '移動速度="0,0" 長さ="#{? ? ?}"/>\n'
            '      </アニメーション>\n'
            '    </動作>\n'
            '  </動作リスト>\n'
            '</ShimejiData>\n'
        )
        path = os.path.join(d, "custom.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml)

        cfg = CustomConfig(path)
        cfg.load()
        check(len(cfg.actions) == 2, "加载出 2 个动作", str(len(cfg.actions)))

        problems = cfg.validate_expressions()
        check(len(problems) == 1, "只报 1 处错误（好动作不误伤）", str(problems))
        if problems:
            name, field, why = problems[0]
            check(name == "坏动作", "错误定位到「坏动作」", name)
            check(field == "duration", "错误字段是 duration（長さ）", field)
            check(why != "", "附带原因")

        # 全合法的配置 -> 空清单
        xml2 = xml.replace('長さ="#{? ? ?}"', '長さ="10"')
        path2 = os.path.join(d, "custom2.xml")
        with open(path2, "w", encoding="utf-8") as fh:
            fh.write(xml2)
        cfg2 = CustomConfig(path2)
        cfg2.load()
        check(cfg2.validate_expressions() == [],
              "全部合法时返回空清单")

        # 文件不存在时不报错
        cfg3 = CustomConfig(os.path.join(d, "nope.xml"))
        cfg3.load()
        check(cfg3.validate_expressions() == [],
              "配置文件不存在时安全返回空清单")
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
