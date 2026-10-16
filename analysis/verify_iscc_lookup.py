# -*- coding: utf-8 -*-
"""验证 Inno Setup 路径的查找/覆盖逻辑。/ Verify the ISCC lookup logic.

⚠️ 这个脚本必须 Write 落文件再跑：在 Bash heredoc 里 `r"D:\another"` 里的
`\a` 会被 shell 当成 BEL 字符，于是「D:\another」变成「D:nother」——
看起来像代码的 bug，其实是**验证手段自己被改坏了**。
This must be a real file: inside a Bash heredoc, `\\a` in a raw string is eaten
as BEL, so "D:\\another" silently becomes "D:nother" -- which then looks like a
code bug when it is really the test harness breaking itself.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAILS = []
PASSES = 0


def check(cond, msg, detail=""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fresh():
    """重新 import，避免上一个用例留下的环境变量影响下一个。"""
    os.environ.pop("ISCC", None)
    os.environ.pop("ISCC_DIR", None)
    return load("tools/release.py", "rel_%d" % PASSES)


print("--- tools/release.py 的 find_iscc() ---")
m = fresh()
_auto = m.find_iscc()
check(os.path.exists(_auto),
      "默认能找到一个真实存在的 ISCC", _auto)
check("Inno Setup" in _auto, "找到的是 Inno Setup 的编译器", _auto)

# 显式指定（即使不存在也要用它，不静默回退）
os.environ["ISCC"] = r"D:\myiscc\ISCC.exe"
check(m.find_iscc() == r"D:\myiscc\ISCC.exe",
      "环境变量 ISCC 优先，即使那个文件不存在也不回退",
      m.find_iscc())

# ISCC_DIR 要能识别出反斜杠没被吃掉
os.environ.pop("ISCC", None)
os.environ["ISCC_DIR"] = r"D:\another"
_got = m.find_iscc()
check(_got == r"D:\another\ISCC.exe",
      "环境变量 ISCC_DIR 拼出完整 exe 路径", _got)
check("\\" in _got, "路径里的反斜杠完好（没被 shell 当转义）", repr(_got))
os.environ.pop("ISCC_DIR", None)

print()
print("--- tools/make_isl.py 的 _find_default_isl() ---")
isl = load("tools/make_isl.py", "isl")
_auto_isl = isl.DEFAULT_ISL
check(os.path.exists(_auto_isl),
      "默认能找到一个真实存在的 Default.isl", _auto_isl)
check(os.path.basename(_auto_isl) == "Default.isl",
      "文件名就是 Default.isl", _auto_isl)

os.environ["ISCC_DIR"] = r"D:\custom"
isl2 = load("tools/make_isl.py", "isl2")
check(isl2.DEFAULT_ISL == r"D:\custom\Default.isl",
      "环境变量 ISCC_DIR 能覆盖安装向导语言文件的来源", isl2.DEFAULT_ISL)
os.environ.pop("ISCC_DIR", None)

print()
print("--- 这两个常量都不再是模块级硬编码 ---")
_src = open(os.path.join(ROOT, "tools", "release.py"), encoding="utf-8").read()
_isl_src = open(os.path.join(ROOT, "tools", "make_isl.py"), encoding="utf-8").read()
check('ISCC = r"' not in _src,
      "release.py 里没有模块级 ISCC = r\"...\" 常量")
check('DEFAULT_ISL = r"' not in _isl_src,
      "make_isl.py 里没有模块级 DEFAULT_ISL = r\"...\" 常量")
check("os.environ.get(\"ISCC\")" in _src,
      "release.py 支持 ISCC 环境变量")
check("os.environ.get(\"ISCC_DIR\")" in _isl_src,
      "make_isl.py 支持 ISCC_DIR 环境变量")

print()
print("=" * 60)
if FAILS:
    print("%d FAILED / %d passed" % (len(FAILS), PASSES))
    for f in FAILS:
        print("  x %s" % f)
    sys.stdout.flush()
    os._exit(1)
print("ALL PASS —— %d 项检查通过" % PASSES)
sys.stdout.flush()
os._exit(0)