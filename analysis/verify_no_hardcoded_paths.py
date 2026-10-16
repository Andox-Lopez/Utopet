# -*- coding: utf-8 -*-
r"""全仓「写死地址」检查。

要区分三类，只把真正该改的判成问题：

1. **仓库自身地址**（`E:\shimejee-remake` 之类）→ **必须报出来**。
   换个盘符、clone 到别处、fork 到别的账号，这些都会坏。
2. **外部软件安装位置**（Inno Setup、Python 解释器）→ 合法的兜底候选，
   但必须**支持环境变量覆盖**，否则用户装了别处就找不到。
3. **测试隔离手段 / 安装后实际路径** → 故意写死，要确认旁边有注释说明。

⚠️ 本文件自己也在扫描范围内，所以**举例用的路径要写成拼接形式**，
否则检查脚本会把自己文档里的例子当成真问题报出来（第一版就踩了）。

跑法：python analysis/verify_no_hardcoded_paths.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 不检查的目录：产物与依赖
SKIP_DIRS = {"dist", "build", "output", "data", "config", "__pycache__",
             ".git", ".workbuddy"}
SCAN_EXT = (".py", ".iss", ".spec", ".bat", ".md", ".json", ".xml", ".txt")

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


def walk_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(SCAN_EXT):
                yield os.path.join(base, f)


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


# ── 1. 仓库自身地址 ────────────────────────────────────────────────
print("--- 1. 仓库自身的绝对路径（任何 E:\\ / C:\\开头的仓库目录都算问题）---")
# 真正的判据：盘符 + 一个**看起来像本仓库**的目录名。
# 只认本仓库名这种，不像 `C:\Program Files\Inno Setup`（那是外部软件的位置，
# 装哪儿由用户决定）。示例里提到的名字用拼接拼出来，免得**本文件自己**
# 被扫出两条假问题 —— 第一版就是这么把自己文档里的例子报成 FAIL 的。
_repo_name = "shim" + "ejee-remake"
REPO_LIKE = re.compile(r"[A-Za-z]:\\+(?:shimejee|utopet|" + _repo_name + r")"
                       r"|[A-Za-z]:\\+WorkBuddy", re.I)
hits = []
for path in walk_files():
    if os.path.abspath(path) == os.path.abspath(__file__):
        continue                      # 不扫自己（示例写在文档里）
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        # 跳过注释里明确写着「不要写死」的举例（那是在提醒，不是真的用）
        m = REPO_LIKE.search(line)
        if not m:
            continue
        if ("不要写死" in line or "never hard" in line.lower()
                or "不再写死" in line):
            continue
        hits.append("%s:%d  %s" % (rel(path), i, line.strip()[:90]))
check(not hits, "没有把仓库自身路径写死", " || ".join(hits[:4]))

# ── 2. GitHub 仓库绝对地址 ─────────────────────────────────────────
print()
print("--- 2. GitHub 仓库绝对地址（fork 后应指向自己的仓库）---")
gh = []
for path in walk_files():
    if not path.endswith((".md", ".py")):
        continue
    text = open(path, encoding="utf-8", errors="replace").read()
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r"https?://github\.com/[^/\s]+/(Utopet|Shimeji)", line):
            gh.append("%s:%d  %s" % (rel(path), i, line.strip()[:90]))
check(not gh, "没有指向某个具体 GitHub 账号的绝对 URL",
      " || ".join(gh[:4]))

# ── 3. 外部软件位置必须可用环境变量覆盖 ─────────────────────────────
print()
print("--- 3. 外部软件安装位置（Inno Setup 等）应支持环境变量覆盖 ---")
for fname, const, env in (("tools/release.py", "ISCC", "ISCC"),
                          ("tools/make_isl.py", "DEFAULT_ISL", "ISCC_DIR")):
    p = os.path.join(ROOT, fname)
    src = open(p, encoding="utf-8").read()
    name = os.path.basename(fname)
    # 不允许模块级硬编码常量
    check(not re.search(r'^%s\s*=\s*r?"[A-Za-z]:' % const, src, re.M),
          "%s 没有把 %s 写成模块级绝对路径常量" % (name, const))
    check('os.environ.get("%s' % env in src
          or "os.environ.get('%s" % env in src,
          "%s 支持用环境变量 %s 覆盖" % (name, env))

# ── 4. 故意的绝对路径旁边必须有说明 ────────────────────────────────
print()
print("--- 4. 故意的绝对路径要写清为什么（防止后人「顺手改相对」）---")
for fname, needle in (
        ("analysis/verify_installer.py", r"C:\Windows\System32"),
        ("analysis/verify_exe_right_click.py", r"C:\Windows\System32")):
    p = os.path.join(ROOT, fname)
    if not os.path.exists(p):
        continue
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    idx = next((i for i, l in enumerate(lines) if needle in l), None)
    name = os.path.basename(fname)
    if idx is None:
        check(True, "%s 里已没有 %s" % (name, needle))
        continue
    # 往上找 6 行，看有没有解释为什么
    ctx = "\n".join(lines[max(0, idx - 6):idx])
    check("测试手法" in ctx or "mechanism" in ctx or "不是偷懒" in ctx,
          "%s 的 %s 旁边写明了「这是测试手法本身」" % (name, needle))

# ── 5. PyInstaller spec 必须用 SPECPATH 而不是 getcwd ──────────────
print()
print("--- 5. shimeji.spec 的 ROOT 来源（getcwd 会跟着 cwd 跑）---")
spec = open(os.path.join(ROOT, "shimeji.spec"), encoding="utf-8").read()
# 只看**代码行**：注释里把 getcwd 当反例提一句是必要的（说明为什么不用它），
# 把注释也判成问题就等于逼着后人删掉解释。
spec_code = []
for line in spec.splitlines():
    s = line.strip()
    if s.startswith("#"):
        continue
    spec_code.append(line.split("  #")[0])
check(not any("getcwd()" in l for l in spec_code),
      "shimeji.spec 的代码里没有 getcwd()（注释里的反例说明不算）")
check("SPECPATH" in spec, "shimeji.spec 用 PyInstaller 注入的 SPECPATH")

# ── 6. 分析脚本的 ROOT 必须自引用，不能写死 ────────────────────────
print()
print("--- 6. analysis/ 下所有脚本的 ROOT 都应自引用 ---")
bad = []
for path in walk_files():
    if not path.endswith(".py") or os.sep + "analysis" + os.sep not in path:
        continue
    text = open(path, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"^ROOT\s*=\s*(.+)$", text, re.M):
        expr = m.group(1)
        if "__file__" in expr:
            continue
        if re.match(r'\s*r?"[A-Za-z]:', expr):
            bad.append("%s: %s" % (rel(path), expr.strip()[:60]))
check(not bad, "analysis/ 下没有把 ROOT 写死成盘符路径", " || ".join(bad))

print()
print("=" * 68)
if FAILS:
    print("%d FAILED / %d passed" % (len(FAILS), PASSES))
    for f in FAILS:
        print("  x %s" % f)
    sys.stdout.flush()
    os._exit(1)
print("ALL PASS —— %d 项检查通过" % PASSES)
sys.stdout.flush()
os._exit(0)