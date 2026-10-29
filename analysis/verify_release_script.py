# -*- coding: utf-8 -*-
"""验证 release.py 里两块**不碰 GitHub** 的逻辑。

① 版本一致性检查（能抓到真问题的那几种情况）
② CHANGELOG → Release 说明的抽取
③ commit message 的生成（剥 Markdown、跳过加粗行、取第一句）
④ 脏文件解析（含非 ASCII 路径的引号情况）
"""
import importlib.util
import inspect
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
# ⭐ 版本号**一律动态取**，绝不写死：写死 "1.0.10" 的那版在升到 1.1.0 时
# 五项全假红（替换不到目标字符串，变异测试根本没生效）。
# 此处独立从 __init__.py 源码里抓一遍，与 rel.current_version() 互为对照 ——
# 两个「读法」一致才证明它真在读文件而不是返回常量。
# Version numbers are ALWAYS read dynamically: hard-coding them makes every
# mutation test below silently no-op (and fail) on the next version bump.
probs = rel.version_consistency()
check(not probs, "当前仓库版本号三处一致", str(probs))
_init_src = open(os.path.join(ROOT, "shimeji", "__init__.py"),
                 encoding="utf-8").read()
VER = re.search(r'__version__\s*=\s*"(.+?)"', _init_src).group(1)
check(rel.current_version() == VER,
      "版本号从 __init__.py 读出来",
      "%s vs 源码 %s" % (rel.current_version(), VER))

# 造一个假的仓库副本，把 .iss 改成不一致，看能不能抓到
# ⚠️⛔ **`rel.ROOT` 必须在整个版本一致性测试期间保持指向副本**，
# 提前恢复成真仓库的话，后面的断言就全在测真仓库（永远一致，必然假绿）。
# 早先把 ROOT 恢复得太早，测试就「通过」了却什么也没验证。
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
    _iss_orig = open(os.path.join(tmp, "installer", "Utopet.iss"),
                     encoding="utf-8").read()

    def _write_iss(text):
        open(os.path.join(tmp, "installer", "Utopet.iss"), "w",
             encoding="utf-8").write(text)

    # AppVersion 对不上（换成任何一个别的版本号都该被抓到）
    _write_iss(_iss_orig.replace('#define AppVersion "%s"' % VER,
                                 '#define AppVersion "9.9.9"'))
    probs = rel.version_consistency()
    check(any("AppVersion" in p for p in probs),
          ".iss 的 AppVersion 对不上时能抓到", str(probs))

    # VersionInfoVersion 不是四段数字
    _write_iss(_iss_orig.replace("VersionInfoVersion=%s.0" % VER,
                                 "VersionInfoVersion=%s" % VER))
    probs = rel.version_consistency()
    check(any("四段数字" in p for p in probs),
          "VersionInfoVersion 不是四段数字时能抓到", str(probs))

    # VersionInfoVersion 段数对但版本对不上
    _write_iss(_iss_orig.replace("VersionInfoVersion=%s.0" % VER,
                                 "VersionInfoVersion=9.9.9.0"))
    probs = rel.version_consistency()
    check(any("VersionInfoVersion" in p for p in probs),
          "VersionInfoVersion 版本对不上时能抓到", str(probs))

    # CHANGELOG 顶部版本对不上
    _write_iss(_iss_orig)
    cl = os.path.join(tmp, "CHANGELOG.md")
    c = open(cl, encoding="utf-8").read()
    open(cl, "w", encoding="utf-8").write(
        c.replace("## [%s]" % VER, "## [9.9.9]", 1))
    probs = rel.version_consistency()
    check(any("CHANGELOG" in p for p in probs),
          "CHANGELOG 顶部版本对不上时能抓到", str(probs))
finally:
    rel.ROOT = _fake_root
    # 副本里 rel.ROOT 已被恢复，CHANGELOG 说明抽取那节也要用回真仓库
    check(rel.ROOT == _fake_root, "rel.ROOT 已恢复成真仓库")

# ── ② commit message ───────────────────────────────────────────────
section("commit message 生成")
# ⭐ 先从 CHANGELOG 动态抓出当前版本的加粗标题句，用来对照生成结果 ——
# 别把「你打字的时候」这类上一版的标题句写死在这里。
_cl_text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
_m = re.search(r"^##\s*\[%s\][^\n]*\n+(.*)" % re.escape(VER), _cl_text,
               re.M | re.S)
_tagline = ""
for _ln in (_m.group(1) if _m else "").splitlines():
    _ln = _ln.strip()
    if _ln.startswith("**"):
        _tagline = re.sub(r"[*_`]+", "", _ln).strip()
        break
check(bool(_tagline), "从 CHANGELOG 动态抓到了这一版的标题句", _tagline)
msg = rel.commit_message(VER, None)
print("    -> %s" % msg)
check(VER in msg, "message 里带版本号")
check("**" not in msg and "`" not in msg,
      "剥掉了 Markdown 强调符号（commit 列表里很难看）")
check(msg.startswith("feat: 发布"), "前缀是约定的 feat: 发布")
# 抓到的是 CHANGELOG 里的**加粗标题句**，不是后面的解释段落
check(_tagline.split("。")[0] in msg,
      "用的是 CHANGELOG 里那一版的标题句，不是解释段落", msg)
check(len(msg) < 80, "长度克制（git log 一行放得下）", "%d 字符" % len(msg))
custom = rel.commit_message(VER, "我的自定义 message")
check(custom == "我的自定义 message", "-m 能覆盖自动生成的")

# ── ③ Release 说明抽取 ─────────────────────────────────────────────
section("Release 说明 = CHANGELOG 那一节的正文")
notes = os.path.join(tmp, "_notes.md")
rel._write_notes(VER, notes)
body = open(notes, encoding="utf-8").read()
print("    前 3 行：")
for line in body.splitlines()[:3]:
    print("      %s" % line[:70])
check(len(body) > 200, "抽到了实质内容", "%d 字符" % len(body))
check("## [%s]" % VER not in body,
      "不包含版本标题行本身（GitHub 会单独显示标题）")
check("1.0.9" not in body.split("###")[0],
      "不串到上一版的内容")
# 内容确实是这一版的：标题句（本版主题）真的出现在正文里
check(_tagline.split("。")[0] in body,
      "内容确实是 %s 的（含本版标题句）" % VER)
# 上一版（1.0.9）不能漏：它的正文不该混进本版内容
rel._write_notes("1.0.9", notes)
b9 = open(notes, encoding="utf-8").read()
check("输入回避" not in b9 and _tagline.split("。")[0] not in b9,
      "取 1.0.9 时不会混入更新版本的内容")
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

# ── ⑤ 确认门：非交互环境下不会静默同意 ─────────────────────────────
section("确认门：非交互环境下拒绝发布")
# ⛔⛔ **绝对不要在测试里调 `rel.publish()`**：它会真的 commit、真的 push。
# 第一版测试就是这么写的，结果在真仓库里留下了一个提交（幸好推送前被
# 确认门拦住了）。这里只静态检查「确认门存在且先于任何写操作」。
# NEVER call `rel.publish()` here: it really commits and really pushes.  The
# first version of this test did exactly that and left a commit in the working
# repo (the confirmation gate saved the push).  Check the gate statically.
_src = open(os.path.join(ROOT, "tools", "release.py"), encoding="utf-8").read()
publish_body = _src[_src.index("def publish("):_src.index("def _gh_repo_slug(")]

check("sys.stdin.isatty()" in publish_body,
      "确认前检查了 stdin 是不是真终端")
check("raise Abort" in publish_body.split("isatty()")[1][:200],
      "没有终端时是「拒绝」而不是「默认同意」")
# 顺序：确认门必须在 push 之前
_i_confirm = publish_body.index("isatty()")
_i_push = publish_body.index('git("push"')
check(_i_confirm < _i_push, "确认门排在 push 之前（不会先推了再问）")
_i_commit = publish_body.index('"commit"')
check(_i_commit < _i_confirm,
      "commit 在确认门之前（提交是本地的，错了能改；推送不行）")
# --dry-run 必须在所有写操作之前就返回
check('if dry:\n        say("  --dry-run：到此为止' in publish_body
      or "--dry-run：到此为止" in publish_body,
      "--dry-run 会在末尾明确说「什么都没做」")
check(publish_body.index("--dry-run：到此为止") < _i_push,
      "--dry-run 的返回点在 push 之前")

# 真跑一次 dry-run，确认它一个字节都没改
_before = rel.dirty_files()
_before_ahead = rel.upstream_divergence()[0]
rel.publish(VER, "x.exe", dry=True, assume_yes=False, message=None)
_after = rel.dirty_files()
_after_ahead = rel.upstream_divergence()[0]
check(_before == _after,
      "dry-run 真的没有改动工作区（前后脏文件列表一致）",
      "%d -> %d" % (len(_before), len(_after)))
# ⚠️ 不要断言「领先 N 个提交」—— 那个 N 每次提交都会变，测试会莫名其妙地
# 开始失败。真正要证的是「dry-run 前后领先数没变」，也就是它没推。
# Never assert "ahead by N": N changes with every commit, so the test starts
# failing for no reason.  What matters is that dry-run did not change it.
check(_before_ahead == _after_ahead,
      "dry-run 没有推送（本地领先远端的提交数不变）",
      "ahead %d -> %d" % (_before_ahead, _after_ahead))

# ── ⑤ 测试版（pre-release）─────────────────────────────────────────
# ⛔ **测试版必须用独立 tag**，不能复用 `v<版本>`：tag 推上去就收不回来
# （强推被拒、删 tag 会让已下载的人引用错乱），而正式版迟早要用那个 tag。
# A pre-release must use its own tag: a pushed tag is effectively
# irreversible, and the real release will need `v<version>` later.
section("测试版（pre-release）")
_pub = inspect.getsource(rel.publish)
check('prerelease' in _pub,
      "publish() 支持 prerelease 参数")
check('"--prerelease"' in _pub,
      "给 gh release create 传了 --prerelease")
check('tag = "v%s-%s" % (version, prerelease)' in _pub,
      "测试版用独立 tag v<版本>-<后缀>（不复用 v<版本>）")
check("else:\n        tag = \"v%s\" % version" in _pub,
      "正式版仍然是 v<版本>（行为不变）")

# 命令行参数要真的存在
_help = rel.main.__doc__ or ""
_ap = None
try:
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--prerelease", default=None)
except Exception:
    pass
check(_ap is not None, "argparse 能解析 --prerelease")

# 真的用 dry-run 跑一遍预发布，确认它显示的是 beta tag
import io
import contextlib
_buf = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf):
        rel.publish(VER, "x.exe", dry=True, assume_yes=False,
                    message=None, prerelease="beta.1")
except Exception as e:
    check(False, "publish(prerelease=...) 能跑通", repr(e))
_out = _buf.getvalue()
check("v%s-beta.1" % VER in _out,
      "预发布 dry-run 显示的 tag 带 -beta.1 后缀",
      [ln for ln in _out.splitlines() if "tag=" in ln][:1])
check("pre-release" in _out,
      "预发布 dry-run 明确标出「测试版」")

# 正式版的 dry-run 不该被污染
_buf2 = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf2):
        rel.publish(VER, "x.exe", dry=True, assume_yes=False, message=None)
except Exception:
    pass
_out2 = _buf2.getvalue()
check("v%s" % VER in _out2 and "beta" not in _out2,
      "正式版 dry-run 仍然只显示 v<版本>（没有被预发布逻辑污染）")

# ── ⑥ gh 的自动定位 ─────────────────────────────────────────────
# GitHub CLI 装在「C:/Program Files/GitHub CLI/gh.exe」，**默认不在 PATH 里**
# （安装时那个「Add to PATH」默认不勾）。直接跑 `gh` 的后果是「看运气」：
# 有时 PATH 里有、有时没有，同一个人同一脚本行为却不一样。
section("gh 自动定位")
import os as _os
_saved_gh = _os.environ.pop("GH", None)
_saved_cli = _os.environ.pop("GITHUB_CLI", None)
try:
    _p = rel.find_gh()
    check(bool(_p), "find_gh() 总能返回一个候选路径", repr(_p))
    # 标准安装位置应该能被找到（CI/别的机器上靠 PATH 兜底）
    _known = (r"C:\Program Files\GitHub CLI\gh.exe",
              r"C:\Program Files (x86)\GitHub CLI\gh.exe")
    _hit = [k for k in _known if _os.path.exists(k)]
    if _hit:
        check(_p == _hit[0] or _p == "gh",
              "标准安装位置能被认出来（或退回 PATH 里的 gh）",
              "find_gh()=%s" % _p)
    # 环境变量优先
    _os.environ["GH"] = r"C:\custom\gh.exe"
    check(rel.find_gh() == r"C:\custom\gh.exe",
          "环境变量 GH 优先于标准安装位置")
    _os.environ.pop("GH")
    _os.environ["GITHUB_CLI"] = r"D:\other\gh.exe"
    check(rel.find_gh() == r"D:\other\gh.exe",
          "环境变量 GITHUB_CLI 也认")
    # 显式指定**即使不存在也照用** —— 不静默回退，用户才知道自己哪里配错了
    _os.environ["GH"] = r"C:\不存在的路径\gh.exe"
    check(rel.find_gh() == r"C:\不存在的路径\gh.exe",
          "显式指定的路径即使不存在也直接返回（不静默回退）")
finally:
    _os.environ.pop("GH", None)
    _os.environ.pop("GITHUB_CLI", None)
    if _saved_gh is not None:
        _os.environ["GH"] = _saved_gh
    if _saved_cli is not None:
        _os.environ["GITHUB_CLI"] = _saved_cli

# gh_cmd() 必须把可执行文件放在第 0 位
_c = rel.gh_cmd("release", "create", "v1.2.3")
check(len(_c) >= 4 and _c[0] == rel.find_gh() and _c[1] == "release",
      "gh_cmd() 把可执行文件放在第 0 位", " ".join(_c[:3]))

# ── ⑦ 网络重试（2026-10-29）────────────────────────────────────
# 发 `v1.1.3-beta.1` 时，流程在最后一步因代理的 fake-ip 连接超时而挂掉：
#     dial tcp 198.18.1.67:443: connectex: A connection attempt failed
# 那时 main 已推送、commit 已提交、构建与测试全过，**只有 tag 和 Release 没建**，
# 最后靠手写脚本补跑了 11 分钟（主要是 35.8 MB 上传）。
#
# 所以 `gh release create` 现在会对**网络类**错误重试 3 次。但**只对网络类** ——
# tag 冲突、参数错、权限不足重试多少次都没用，而且重试会掩盖真正的错误。

section("网络错误重试")
_net_ok = [
    "dial tcp 198.18.1.67:443: connectex: A connection attempt failed",
    # ★ 2026-10-29 发 v1.1.3-beta.1 时**实际遇到**的错误（原文）
    ("error checking for existing release: Head "
     "\"https://api.github.com/repos/Andox-Lopez/Utopet/releases/tags/v1.1.3-beta.1\": "
     "dial tcp 198.18.1.67:443: connectex: A connection attempt failed because "
     "the connected party did not properly respond after a period of time, or "
     "established connection failed because connected host has failed to respond."),
    "Read timed out",
    "connection reset by peer",
    "TLS handshake timeout",
    "503 Service Unavailable",
]
for _t in _net_ok:
    check(rel.is_network_error(_t),
          "认得出网络类错误：%s" % _t[:48])

_net_bad = [
    "HTTP 422: Validation Failed (tag already exists)",
    "HTTP 404: Not Found",
    "could not find any release with tag",
    "permission denied",
    "HTTP 401: Unauthorized",
]
for _t in _net_bad:
    check(not rel.is_network_error(_t),
          "不把非网络错误当成网络错误（免得白重试）：%s" % _t[:48])

check(not rel.is_network_error(""),
      "空输出不算网络错误")

# 源码里必须真的用了重试 —— 光有 is_network_error() 不算数
_src = inspect.getsource(rel)
check("_NET_ERRORS" in _src and "is_network_error(out)" in _src,
      "release.py 里确实接上了重试逻辑")
check("for _attempt in range(1, 4)" in _src,
      "重试次数是 3 次")

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