# -*- coding: utf-8 -*-
"""验证：每一处 `except Exception` 都必须留下痕迹。

项目笔记里的原话：
> 裸 `except Exception` 是无声功能的最佳藏身处（`_reclaim_window` 的 TypeError
> 被吞了 7 个版本）。**看到裸 except 就去查它吞了什么。**

`_reclaim_window` 那个 bug 被吞了 **7 个版本**才发现 —— 说明这类问题平均要漏
好几个版本。所以这里把「每处 except 都可观测」变成一条**可执行的规则**：
以后谁新增一处静默的裸 except，这个测试立刻挂。

判定「有痕迹」的方式（按可靠性排序）：
1. 异常块里有 `log.` 调用（warning / exception / debug 都算）
2. 异常块里显式 `raise`（往上抛不算吞）
3. 异常块里的注释说明了「为什么该吞」（`#` 开头且带说明文字）

第 3 条是兜底：有些地方吞异常是**故意的**（比如 Qt 的槽里不能让异常冒出去），
那至少要写清楚为什么。

用法：python analysis/verify_except_audit.py
"""

from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "shimeji")

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


def python_files():
    for root, dirs, fs in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(fs):
            if f.endswith(".py"):
                yield os.path.join(root, f)


def block_after(lines, idx, limit=12):
    """
    取 except 之后、同一缩进层内的代码块。

    ⚠️ **必须按缩进判断，不能按固定行数**：块里的注释长短不一，按行数切会
    把 `warn_eval_failure(...)` 切到窗口外，误报成「静默」（实测过一次）。
    缩进比行数可靠。
    The block ends at the next line with the same or shallower indent — not at
    a fixed line count.  A fixed count cut the real logging call out of the
    window and produced a false positive.
    """
    except_indent = len(lines[idx]) - len(lines[idx].lstrip())
    out = []
    for ln in lines[idx + 1: idx + 1 + limit * 3]:
        if not ln.strip():
            out.append(ln)
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= except_indent:
            break
        out.append(ln)
    return out


def has_explanation(lines, idx, limit=12):
    """
    except 块里有没有**说明为什么可以吞**的注释。

    判据：注释行里含有中文或英文的说明性词汇，且不是单纯的「noqa」标记。
    """
    keywords = ("吞", "忽略", "不影响", "不该", "不能", "继续", "降级", "失败",
                "跳过", "保住", "静默", "无害", "边界", "异常", "错", "崩",
                "skip", "ignore", "fail", "safe", "harmless", "keep",
                "survive", "border", "tolerat", "guard", "swallow")
    for ln in block_after(lines, idx, limit):
        s = ln.strip()
        if not s.startswith("#"):
            continue
        text = s.lstrip("#").strip().lower()
        if not text or text.startswith("noqa"):
            continue
        if any(k in text for k in keywords):
            return True
    return False


def main() -> int:
    total = 0
    silent = []
    for path in python_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        lines = io.open(path, encoding="utf-8").read().splitlines()
        for i, ln in enumerate(lines):
            if "except Exception" not in ln:
                continue
            total += 1
            # ⚠️ 判据集中在 `_has_trace()` 一处，自检函数也调它 —— 两边永远一致。
            # The rule lives in one place, and the self-check calls it too.
            if _has_trace(lines, i):
                continue
            silent.append("%s:%d" % (rel, i + 1))

    print("\n--- 每一处 except 都必须可观测 ---", flush=True)
    check(total > 0, "扫到了 except Exception", "%d 处" % total)
    check(not silent,
          "没有「完全静默」的 except Exception",
          "静默 %d 处：%s" % (len(silent), ", ".join(silent[:8])))

    # 反向检查：确认审计本身不是「什么都没扫到」的假绿
    print("\n--- 审计本身要有效 ---", flush=True)
    # 造一个假的静默 except，喂给判定函数，它必须报出来
    _fake = [
        "try:",
        "    pass",
        "except Exception:",
        "    pass",
        "",
    ]
    _fake_logged = [
        "try:",
        "    pass",
        "except Exception:",
        "    log.warning('x')",
        "",
    ]
    _fake_note = [
        "try:",
        "    pass",
        "except Exception:",
        "    # 这里吞掉是故意的，不影响主流程",
        "    pass",
        "",
    ]
    check(not _judge(_fake), "判定函数能认出「完全静默」的写法")
    check(_judge(_fake_logged), "判定函数认得出有 log 的写法")
    check(_judge(_fake_note), "判定函数认得出有说明注释的写法")

    print()
    print("=" * 60, flush=True)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush()
        os._exit(1)
    print("ALL PASS —— %d 项检查通过（扫了 %d 处 except）"
          % (PASSES, total), flush=True)
    sys.stdout.flush()
    os._exit(0)


def _judge(lines):
    """
    给测试用：这段 except 块算不算「有痕迹」。

    ⭐ **必须和生产判定走同一个函数** —— 否则自检测的是「另一套规则」，
    测出来的「有效」是假的。
    Must share the production rule, otherwise the self-check verifies a
    different rule and its "the audit works" claim is worthless.
    """
    for i, ln in enumerate(lines):
        if "except Exception" not in ln:
            continue
        return _has_trace(lines, i)
    return True


def _has_trace(lines, idx):
    """
    这一处 except 有没有留下痕迹。

    判据（任一即可）：
    * 块里有 `log.*` 或共享告警助手 `warn_eval_failure(...)`
    * 块里有 `raise`（往上抛不算吞）
    * 块里有**说明为什么可以吞**的注释
    """
    block = "\n".join(block_after(lines, idx))
    if ("log." in block) or ("warn_eval_failure" in block):
        return True
    if "raise " in block:
        return True
    return has_explanation(lines, idx)


if __name__ == "__main__":
    main()
