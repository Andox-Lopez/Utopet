# -*- coding: utf-8 -*-
"""验证 release.py 里两块**不碰 GitHub** 的逻辑。

① 版本一致性检查（能抓到真问题的那几种情况）
② CHANGELOG → Release 说明的抽取
③ commit message 的生成（剥 Markdown、跳过加粗行、取第一句）
④ 脏文件解析（含非 ASCII 路径的引号情况）
"""
import importlib.util
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "rel", os.path.join(ROOT, "tools", "release.py"))
rel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rel)

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


def section(t):
    print("\n--- %s ---" % t, flush=True)


# ── ① 版本一致性 ────────────────────────────────────────────────────
section("版本号一致性检查")
probs = rel.version_consistency()
check(not probs, "当前仓库版本号三处一致", str(probs))
check(rel.current_version() == "1.0.10",
      "版本号从 __init__.py 读出来", rel.current_version())

# 造一个假的仓库副本，把 .iss 改成不一致，看能不能抓到
tmp = tempfile.mkdtemp(prefix="rel_test_")
import shutil
for name in ("shimeji", "installer"):
    shutil.copytree(os.path.join(ROOT, name), os.path.join(tmp, name),
                    ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy(os.path.join(ROOT, "CHANGELOG.md"),
            os.path.join(tmp, "CHANGELOG.md"))
_fake_root = rel.ROOT
rel.ROOT = tmp
try:
    probs = rel.version_consistency()
    check(not probs, "副本里版本号仍然一致", str(probs))

    # 把 .iss 的 AppVersion 改掉
    iss = os.path.join(tmp, "installer", "Utopet.iss")
    txt = open(iss, encoding="utf-8").read()
    open(iss, "w", encoding="utf-8").write(
        txt.replace('#define AppVersion "1.0.10"',
                    '#define AppVersion "1.0.9"'))
    probs = rel.version_consistency()
    check(any("AppVersion" in p for p in probs),
          ".iss 的 AppVersion 对不上时能抓到", str(probs))

    # VersionInfoVersion 不是四段数字
    open(iss, "w", encoding="utf-8").write(
        txt.replace("VersionInfoVersion=1.0.10.0",
                    "VersionInfoVersion=1.0.10"))
    probs = rel.version_consistency()
    check(any("四段数字" in p for p in probs),
          "VersionInfoVersion 不是四段数字时能抓到", str(probs))

    # CHANGELOG 顶部版本对不上
    open(iss, "w", encoding="utf-8").write(txt)
    cl = os.path.join(tmp, "CHANGELOG.md")
    c = open(cl, encoding="utf-8").read()
    open(cl, "w", encoding="utf-8").write(
        c.replace("## [1.0.10]", "## [9.9.9]", 1))
    probs = rel.version_consistency()
    check(any("CHANGELOG" in p for p in probs),
          "CHANGELOG 顶部版本对不上时能抓到", str(probs))
finally:
    rel.ROOT = _fake_root

# ── ② commit message ───────────────────────────────────────────────
section("commit message 生成")
msg = rel.commit_message("1.0.10", None)
print("    -> %s" % msg)
check("1.0.10" in msg, "message 里带版本号")
check("**" not in msg and "`" not in msg,
      "剥掉了 Markdown 强调符号（commit 列表里很难看）")
check(msg.startswith("feat: 发布"), "前缀是约定的 feat: 发布")
# 抓到的是 CHANGELOG 里的**加粗标题句**，不是后面的解释段落
check("你打字的时候" in msg,
      "用的是 CHANGELOG 里那一版的标题句，不是解释段落", msg)
check(len(msg) < 80, "长度克制（git log 一行放得下）", "%d 字符" % len(msg))
custom = rel.commit_message("1.0.10", "我的自定义 message")
check(custom == "我的自定义 message", "-m 能覆盖自动生成的")

# ── ③ Release 说明抽取 ─────────────────────────────────────────────
section("Release 说明 = CHANGELOG 那一节的正文")
notes = os.path.join(tmp, "_notes.md")
rel._write_notes("1.0.10", notes)
body = open(notes, encoding="utf-8").read()
print("    前 3 行：")
for line in body.splitlines()[:3]:
    print("      %s" % line[:70])
check(len(body) > 200, "抽到了实质内容", "%d 字符" % len(body))
check("## [1.0.10]" not in body,
      "不包含版本标题行本身（GitHub 会单独显示标题）")
check("1.0.9" not in body.split("###")[0],
      "不串到上一版的内容")
check("输入回避" in body or "输入" in body,
      "内容确实是 1.0.10 的（提到输入回避）")
# 下一版不能漏
rel._write_notes("1.0.9", notes)
b9 = open(notes, encoding="utf-8").read()
check("输入回避" not in b9,
      "取 1.0.9 时不会混入 1.0.10 的内容")
os.remove(notes)

# ── ④ 脏文件解析 ───────────────────────────────────────────────────
section("未提交改动解析")
rel.ROOT = _fake_root
files = rel.dirty_files()
print("    -> %d 个文件" % len(files))
check(isinstance(files, list), "返回列表")
# 人工构造带引号的输出（git 对非 ASCII 路径会加引号）
fake = ' M "shimeji/\u4e2d\u6587\u8def\u5f84.py"\n?? plain.py\nA  staged.py\n'
parsed = []
for line in fake.splitlines():
    line = line.rstrip()
    if not line:
        continue
    p = line[3:].strip() if len(line) > 3 else ""
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p:
        parsed.append(p)
check(parsed == ["shimeji/\u4e2d\u6587\u8def\u5f84.py", "plain.py", "staged.py"],
      "非 ASCII 路径的引号被正确剥掉", str(parsed))
rel.ROOT = _fake_root

# ── ⑤ 确认型开关不会静默同意 ──────────────────────────────────────
section("非交互环境下不会默认同意")
class _NoTTY:
    def isatty(self):
        return False
_saved_stdin = sys.stdin
try:
    sys.stdin = _NoTTY()
    check(not sys.stdin.isatty(), "模拟出非交互 stdin")
    raised = False
    try:
        rel.publish("1.0.10", "x.exe", dry=False, assume_yes=False,
                    message=None)
    except rel.Abort as e:
        raised = "没有可交互的终端" in e.why
    except Exception:
        raised = False
    check(raised,
          "没有终端时拒绝发布，而不是当成同意（推 tag 撤不回来）")
finally:
    sys.stdin = _saved_stdin

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