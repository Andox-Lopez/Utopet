# -*- coding: utf-8 -*-
"""角色包导入 / 导出 / 描述文件增补的回归测试。

1.0.6 新增 `shimeji/characterpack.py`，这个脚本把它按「用户会怎么用」跑一遍：
拖进来的三种来源（文件夹 / zip / 嵌套一层）、缺 conf 的包、重名的包、
恶意压缩包、以及导出后能不能再导入回来。

**不需要 Qt**，所以任何 Python 环境都能跑：

    python analysis/verify_characterpack.py

Regression tests for character-pack import / export / conf supplementing.
Deliberately Qt-free so it runs under any interpreter.

Covers the three sources a user can hand us (a folder, a zip, a nested tree), a
pack with no conf\\, a name collision, hostile archives, and whether an export
can be imported back.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimeji.characterpack import (REQUIRED_CONF, count_frames, export_pack,  # noqa: E402
                                   find_pack_root, import_pack, is_character_dir,
                                   is_supported_source, safe_name, supplement_conf)

FAILS = []
PASSES = 0


def check(cond, msg, detail=""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg + (f"  ({detail})" if detail else ""),
          flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


SRC_PNG = os.path.join(ROOT, "characters", "Miku", "img", "shime1.png")
SRC2_PNG = os.path.join(ROOT, "characters", "Miku", "img", "shime2.png")


def make_pack(base, name, layout="img", with_conf=False):
    d = os.path.join(base, name)
    if layout == "img":
        os.makedirs(os.path.join(d, "img"), exist_ok=True)
        shutil.copy2(SRC_PNG, os.path.join(d, "img", "shime1.png"))
        shutil.copy2(SRC2_PNG, os.path.join(d, "img", "shime2.png"))
    else:
        os.makedirs(d, exist_ok=True)
        shutil.copy2(SRC_PNG, os.path.join(d, "shime1.png"))
    if with_conf:
        conf = os.path.join(d, "conf")
        os.makedirs(conf, exist_ok=True)
        with open(os.path.join(conf, "Actions.xml"), "w", encoding="utf-8") as f:
            f.write("<自作/>\n")
    return d


work = tempfile.mkdtemp(prefix="utopet_packcheck_")
try:
    chars = os.path.join(work, "characters")

    print("\n--- 基础工具 ---", flush=True)
    sneak = safe_name("../..")
    check("/" not in sneak and "\\" not in sneak and ".." not in sneak
          and sneak not in (".", ".."),
          "safe_name 挡掉路径穿越", sneak)
    check(safe_name("CON") == "_CON", "safe_name 挡掉 Windows 保留名", safe_name("CON"))
    check(safe_name("Miku  v2") == "Miku v2", "safe_name 折叠多余空格", safe_name("Miku  v2"))
    check(safe_name("花卷") == "花卷", "safe_name 保留中文名")
    check(safe_name("C:evil") == "C_evil", "safe_name 挡掉盘符", safe_name("C:evil"))
    check(is_supported_source(work) is True, "目录算可导入来源")
    check(is_supported_source("x.txt") is False, "txt 不算可导入来源")

    print("\n--- 恶意角色名不会写出 characters 之外 ---", flush=True)
    sneaky = make_pack(work, "Sneaky")
    rs = import_pack(sneaky, chars, name="../../escape")
    check(rs.ok, "带穿越名字的包仍按安全名导入", rs.error)
    check(os.path.dirname(os.path.abspath(rs.path)) == os.path.abspath(chars),
          "导入结果确实落在 characters 目录里", rs.path)
    check(not os.path.exists(os.path.join(work, "escape")),
          "characters 之外没有多出目录")

    print("\n--- 导入：img/ 布局 + 自动补齐描述文件 ---", flush=True)
    src = make_pack(work, "MyPet")
    r = import_pack(src, chars)
    check(r.ok, "导入成功", r.error)
    check(r.name == "MyPet", "角色名取自目录名", r.name)
    check(r.images == 2, "数到 2 张序列帧", str(r.images))
    check(set(r.added_conf) == set(REQUIRED_CONF),
          "conf 全缺时把三份描述文件都补上", ",".join(r.added_conf))
    target = os.path.join(chars, "MyPet")
    for f in REQUIRED_CONF:
        check(os.path.exists(os.path.join(target, "conf", f)), f"补齐了 {f}")

    print("\n--- 增补是幂等的、且不覆盖已有文件 ---", flush=True)
    again = supplement_conf(target)
    check(again == [], "再补一次什么都不动", str(again))
    custom = os.path.join(target, "conf", "Behavior.xml")
    with open(custom, "w", encoding="utf-8") as f:
        f.write("<!-- 作者改过的 -->\n")
    supplement_conf(target)
    with open(custom, encoding="utf-8") as f:
        body = f.read()
    check("作者改过的" in body, "已有的 Behavior.xml 绝不被默认版覆盖")

    print("\n--- 重名：换名而不是覆盖 ---", flush=True)
    r2 = import_pack(src, chars)
    check(r2.ok and r2.name == "MyPet_2", "重名导入自动换名", r2.name)
    check(r2.renamed_from == "MyPet", "报告里记下原名", r2.renamed_from)
    check(os.path.exists(os.path.join(chars, "MyPet", "conf", "Behavior.xml")),
          "原来那只角色还在（没被覆盖）")

    print("\n--- 原版布局：PNG 直接放包根 ---", flush=True)
    flat = make_pack(work, "FlatPet", layout="flat")
    r3 = import_pack(flat, chars)
    check(r3.ok and r3.images == 1, "原版 1.0.0 的扁平布局也能导入", r3.error)

    print("\n--- 嵌套目录：剥掉外层包装 ---", flush=True)
    wrap = os.path.join(work, "download", "新建文件夹")
    os.makedirs(wrap, exist_ok=True)
    inner = make_pack(wrap, "Wrapped")
    check(find_pack_root(os.path.join(work, "download")) == inner,
          "find_pack_root 找到内层包根")
    r4 = import_pack(os.path.join(work, "download"), chars)
    check(r4.ok and r4.name == "download", "嵌套导入成功（用来源目录名）", r4.error)
    check(is_character_dir(os.path.join(chars, "download")), "导入结果确实是合法角色包")

    print("\n--- zip 导入 ---", flush=True)
    zsrc = os.path.join(work, "ZipPet")
    make_pack(work, "ZipPet")
    zpath = os.path.join(work, "ZipPet.zip")
    with zipfile.ZipFile(zpath, "w") as zf:
        for base, _dirs, files in os.walk(zsrc):
            for fn in files:
                full = os.path.join(base, fn)
                zf.write(full, os.path.relpath(full, work))
    r5 = import_pack(zpath, chars)
    check(r5.ok and r5.name == "ZipPet", "zip 导入成功", r5.error)
    check(set(r5.added_conf) == set(REQUIRED_CONF), "zip 导入同样补齐描述文件")

    print("\n--- zip-slip 防护 ---", flush=True)
    evil = os.path.join(work, "evil.zip")
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped.png", b"x")
        zf.writestr("img/shime1.png", b"x")
    r6 = import_pack(evil, chars)
    check(not r6.ok and "unsafe" in r6.error, "含 .. 的压缩包被拒绝", r6.error)
    check(not os.path.exists(os.path.join(work, "escaped.png")),
          "拒绝后没有文件被写到 characters 之外")
    abso = os.path.join(work, "abs.zip")
    with zipfile.ZipFile(abso, "w") as zf:
        zf.writestr("C:/Windows/System32/evil.png", b"x")
        zf.writestr("img/shime1.png", b"x")
    r7 = import_pack(abso, chars)
    check(not r7.ok, "含绝对路径的压缩包被拒绝", r7.error)

    print("\n--- 坏输入不崩 ---", flush=True)
    empty = os.path.join(work, "Empty")
    os.makedirs(empty, exist_ok=True)
    r8 = import_pack(empty, chars)
    check(not r8.ok and "shime1" in r8.error, "没有 shime1.png 时报错而不是崩", r8.error)
    bad = os.path.join(work, "bad.zip")
    with open(bad, "wb") as f:
        f.write(b"not a zip at all")
    r9 = import_pack(bad, chars)
    check(not r9.ok, "坏压缩包报错而不是崩", r9.error)
    r10 = import_pack(os.path.join(work, "nope"), chars)
    check(not r10.ok, "来源不存在时报错而不是崩", r10.error)

    print("\n--- 导出 ---", flush=True)
    dest = os.path.join(work, "out", "MyPet.zip")
    rep = export_pack(os.path.join(chars, "MyPet"), dest)
    check(rep.ok and os.path.exists(dest), "导出成功", rep.error)
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    check(any(n.endswith("img/shime1.png") or n.endswith("img\\shime1.png") for n in names),
          "导出物里有序列帧图")
    check(any(n.endswith("conf/Actions.xml") or n.endswith("conf\\Actions.xml") for n in names),
          "导出物里有 conf\\Actions.xml")
    check(all(n.startswith("MyPet/") for n in names), "zip 内顶层目录就是角色名")
    check(any("作者改过的" in zipfile.ZipFile(dest).read(n).decode("utf-8")
              for n in names if n.endswith("Behavior.xml")),
          "导出保留作者改过的 Behavior.xml")

    print("\n--- 导出时补齐（临时副本，不动原目录）---", flush=True)
    bare = os.path.join(chars, "Bare")
    make_pack(chars, "Bare")
    check(not os.path.exists(os.path.join(bare, "conf", "Actions.xml")),
          "前置：Bare 没有 conf")
    dest2 = os.path.join(work, "Bare.zip")
    rep2 = export_pack(bare, dest2, supplement=True)
    check(rep2.ok, "带补齐的导出成功", rep2.error)
    with zipfile.ZipFile(dest2) as zf:
        names2 = zf.namelist()
    check(any(n.endswith("conf/Actions.xml") for n in names2), "导出物补齐了 Actions.xml")
    check(not os.path.exists(os.path.join(bare, "conf", "Actions.xml")),
          "原目录一个字节都没动（补齐只发生在临时副本上）")

    print("\n--- 往返一致 ---", flush=True)
    back = os.path.join(work, "back")
    r11 = import_pack(dest, back)
    check(r11.ok, "导出的 zip 能再导入回来", r11.error)
    check(count_frames(os.path.join(back, "MyPet")) == 2, "往返后帧数一致",
          str(count_frames(os.path.join(back, "MyPet"))))
finally:
    shutil.rmtree(work, ignore_errors=True)

print("=" * 56)
if FAILS:
    print(f"{len(FAILS)} FAILED / {PASSES} passed")
    for f in FAILS:
        print("  x", f)
    sys.exit(1)
print(f"ALL PASS —— {PASSES} 项检查通过")
