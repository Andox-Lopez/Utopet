# -*- coding: utf-8 -*-
"""分析 Behavior.xml 的行为权重，定位「宠物不动」的根因。

之前的脚本直接用 ElementTree 找 `頻度` 属性，但原始 XML 是**日文标签 +
默认命名空间**，而且关键在于：主行为的 `頻度` 全是 0（那是给系统用的
入口，真正的权重在 `次の行動リスト` 的 `行動参照` 上）。所以必须用项目
自己的解析器 `load_behavior` 才能拿到真实权重。

用法：python analysis/analyze_behavior_weights.py
"""

from __future__ import annotations

import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimeji.xml.config import load_behavior  # noqa: E402

CHARS = os.path.join(ROOT, "characters")

# 用户感知上「像没动」的行为关键字
IDLE_KEYS = ("ボーッ", "ぼーっ", "ボーっと", "发呆", "发愣", "erer", "bore",
             "ねる", "寝", "sleep", "gaze", "stare", "带给", "带给")


def is_idle(name: str) -> bool:
    return any(k in name for k in IDLE_KEYS)


def analyze(char: str) -> None:
    path = os.path.join(CHARS, char, "conf", "Behavior.xml")
    if not os.path.exists(path):
        print(f"[skip] {char}: 没有 Behavior.xml")
        return
    bs = load_behavior(path)

    total = 0.0
    weights: dict[str, float] = {}
    chains: dict[str, list[tuple[str, float]]] = {}
    sinks: list[tuple[str, float, int]] = []

    for b in bs.behaviors():
        nxt: list[tuple[str, float]] = []
        nl = b.next_list
        if nl is not None:
            for ref in nl.refs:
                w = ref.frequency.num(bs.constants, 1.0) if ref.frequency else 1.0
                nxt.append((ref.name, w))
        chains[b.name] = nxt
        w = b.frequency.num(bs.constants, 0.0) if b.frequency else 0.0
        weights[b.name] = w
        if w > 0:
            total += w
            # 出口只有一个且指向自己 = 死循环，会把宠物永久锁死
            if len(nxt) == 1 and nxt[0][0] == b.name:
                sinks.append((b.name, w, 1))

    print("=" * 70)
    print(f"角色 {char}: 行为 {len(weights)} 个，入口总权重 {total:.0f}")
    print("=" * 70)

    # 入口权重排名（初始会选中的）
    top = sorted(((w, n) for n, w in weights.items() if w > 0), reverse=True)
    print("\n[入口权重 Top 12]（开局/重置时真正生效的）")
    for w, n in top[:12]:
        print(f"  {w:>6.0f}  {n}")

    idle_w = sum(w for n, w in weights.items() if w > 0 and is_idle(n))
    if total > 0:
        print(f"\n[发呆类入口占比] {idle_w:.0f}/{total:.0f} = {idle_w/total*100:.1f}%")

    # 关键：从入口出发，一跳之后会去哪
    print("\n[入口 -> 下一跳 抽样]（看是否被锁进发呆）")
    for w, n in top[:6]:
        nx = chains.get(n, [])
        nw = sum(x[1] for x in nx)
        idle_in = sum(x[1] for x in nx if is_idle(x[0]))
        pct = (idle_in / nw * 100) if nw else 0.0
        print(f"  {n[:26]:<28} w={w:<5.0f} -> 共 {len(nx)} 条，发呆占 {pct:.0f}%")

    if sinks:
        print("\n[!] 自锁死循环（指向自己的唯一出口）：")
        for n, w, _ in sinks:
            print(f"    w={w:.0f}  {n}")
    else:
        print("\n[ok] 没有「唯一出口指向自己」的自锁结构")

    # 孤立判定：某个行为虽然入口权重 0，但在别的 next 里出现多少
    reach = collections.Counter()
    for nxt in chains.values():
        for name, w in nxt:
            reach[name] += w
    unreachable = [n for n, w in weights.items() if w == 0 and reach[n] == 0]
    if unreachable:
        print(f"[note] {len(unreachable)} 个行为既无入口权重也无引用（永远不会被选中）")
    print()


def main() -> int:
    if not os.path.isdir(CHARS):
        print("找不到 characters/", CHARS)
        return 1
    for char in sorted(os.listdir(CHARS)):
        if os.path.isdir(os.path.join(CHARS, char)):
            analyze(char)
    return 0


if __name__ == "__main__":
    sys.exit(main())
