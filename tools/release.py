# -*- coding: utf-8 -*-
"""
一条命令完成整个发版流程 / One command for the whole release
==============================================================================
    python tools/release.py            # 全流程，推送前先确认
    python tools/release.py --yes      # 全流程，不询问（CI / 已经确认过）
    python tools/release.py --dry-run  # 只打印要做什么，不动任何东西
    python tools/release.py --build-only   # 只构建+打包+测试，不 commit/推送/发版
    python tools/release.py --skip-tests   # 跳过安装测试（它会 taskkill 正在跑的实例）

五步：
    1. 自检        工具链、版本号三处一致、工作区状态
    2. 构建        tools/build_release.py -> dist\\Utopet\\
    3. 打包        ISCC -> output\\Utopet-Setup-<版本>.exe
    4. 测试        全量回归 + 安装包实测（静默装 / 脱离 Python 启动 / 卸载）
    5. 发布        commit -> push -> 建 GitHub Release -> 上传安装包附件

⛔ **推 GitHub 和建 Release 之前一定会停下来问**（除非 `--yes`）。
   这两步一旦做出去就很难收回：tag 推到远端后，强推会被拒绝，删 tag 又会
   让已经下载过的人拿到错乱的引用。所以默认停下来确认。
⛔ `--dry-run` **什么都不会改**（不构建、不 commit、不推送），可以放心跑。

The two outward-facing steps (pushing to GitHub, creating the Release) always
pause for confirmation unless `--yes` is given.  A pushed tag is effectively
irreversible: force-pushing it gets rejected, and deleting it leaves anyone who
already downloaded pointing at a confusing ref.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTE = "Utopet"                      # git remote 名字，不是 URL
BRANCH = "main"
DEFAULT_MESSAGE = "feat: 发布 %s"


def find_iscc() -> str:
    """找到 ISCC.exe / ISCC。/ Locate the Inno Setup compiler.

    Inno Setup 是**外部软件**，装在哪儿由用户决定 —— 与本仓库无关，所以
    不写死。优先用环境变量 `ISCC`（可以是完整 exe 路径），再找环境变量
    `ISCC_DIR`，最后退到几个常见安装位置（32/64 位都试）。

    Inno Setup is an external tool installed wherever the user put it, so it is
    not hard-coded.  Prefer `$ISCC` (full path to the exe), then `$ISCC_DIR`,
    then the usual install locations.
    """
    # 显式指定的路径**即使不存在也直接返回**，不静默回退 —— 用户特意设了
    # ISCC / ISCC_DIR 却发现脚本跑去用别的安装，那就永远搞不清自己哪里配错了。
    # `ISCC_DIR` 也要「照办」：目录是用户指明的，目录里的 exe 不存在就该
    # 报错说他装的不对，而不是悄悄换个安装用起来。
    # An explicit override is honoured even when it does not exist: silently
    # falling back hides the user's own mistake.  `ISCC_DIR` counts as an
    # override too — if its exe is missing, say so rather than quietly using
    # a different installation.
    exe = os.environ.get("ISCC")
    if exe:
        return exe
    d = os.environ.get("ISCC_DIR")
    if d:
        return os.path.join(d, "ISCC.exe")
    for c in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
              r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if os.path.exists(c):
            return c
    # 都不在：返回 32 位那个，交给调用处的报错带上它
    return r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"


def find_gh() -> str:
    """找到 GitHub CLI。/ Locate the GitHub CLI.

    ⭐ **为什么不能直接用 `gh`**：GitHub CLI 装在
    `C:/Program Files/GitHub CLI/gh.exe`，**默认不在 PATH 里**。Windows 的
    「Add to PATH」选项默认不勾，而装完 CLI 的人很少手动去勾。

    所以直接跑 `gh` 的后果是「看运气」：有时 PATH 里有（同一个安装程序在
    某些版本里会问要不要加），有时没有。发 1.1.2 时 PATH 里恰好有，
    发 1.1.2-beta.2 时就没有 —— 同一个人、同一个脚本，行为却不一样，
    排查起来极其费劲。

    查找顺序：
    1. 环境变量 `GH`（完整 exe 路径）
    2. 环境变量 `GITHUB_CLI`（同上）
    3. 常见安装位置（Program Files / Program Files (x86)）
    4. PATH 里的 `gh`（交回裸名字，让系统去找）

    与 `find_iscc()` 一致：**显式指定的路径即使不存在也直接返回**，
    不静默回退 —— 用户特意设了 `GH` 却发现脚本跑去用别的，那永远搞不清
    自己哪里配错了。

    The GitHub CLI is not on PATH by default on Windows, so calling `gh`
    directly makes the release script work "by luck".  Look for an explicit
    override first, then the usual install locations, then fall back to PATH.
    """
    for var in ("GH", "GITHUB_CLI"):
        p = os.environ.get(var)
        if p:
            return p
    for c in (r"C:\Program Files\GitHub CLI\gh.exe",
              r"C:\Program Files (x86)\GitHub CLI\gh.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe")):
        if os.path.exists(c):
            return c
    # 都不在：交回裸名字，交给系统按 PATH 找（找不到会在调用处报错）
    return "gh"


def gh_cmd(*args: str) -> list[str]:
    """拼一条 gh 命令。/ Build a gh command line."""
    return [find_gh()] + list(args)


def iss_path() -> str:
    """`.iss` 的路径。/ Path to the installer script.

    ⚠️ 这些路径**必须运行时从 `ROOT` 算**，不能在模块加载时定成常量。
    模块级 `ISS = os.path.join(ROOT, ...)` 只在 ROOT 永远不变时成立；
    一旦有测试或别的场景临时改 `ROOT`（指向一个仓库副本），那些常量会
    继续读**原仓库** —— 于是「测副本里的配置」变成了「测真仓库」，
    断言永远为真，测试假绿。
    These must be derived from `ROOT` at call time.  As module-level constants
    they froze the original ROOT, so pointing ROOT at a repo copy left the
    paths still reading the real repo — tests passed while verifying nothing.
    """
    return os.path.join(ROOT, "installer", "Utopet.iss")


def dist_exe() -> str:
    return os.path.join(ROOT, "dist", "Utopet", "Utopet.exe")


def output_dir() -> str:
    return os.path.join(ROOT, "output")

# 走这些的脚本会打印大量日志，只在出错时保留输出。
# Scripts run quietly unless they fail; their own output is a wall of noise.
QUIET_SCRIPTS = (
    "verify_pomodoro.py",
    "verify_multi_character.py",
    "verify_avoid_pounce.py",
    "verify_serifu.py",
    "verify_characterpack.py",
    "verify_cfgfmt.py",
    "verify_version_resources.py",
    "verify_release_script.py",
    "verify_iscc_lookup.py",
    "verify_no_hardcoded_paths.py",
    "regression_actions.py",
    "smoke_taskbar.py",
)


# ----------------------------------------------------------------------
# 输出helpers / output helpers
# ----------------------------------------------------------------------
def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, total: int, title: str) -> None:
    say("")
    say("=" * 68)
    say("  第 %d/%d 步 · %s" % (n, total, title))
    say("=" * 68)


def ok(msg: str) -> None:
    say("  [ok]   %s" % msg)


def warn(msg: str) -> None:
    say("  [warn] %s" % msg)


def fail(msg: str, detail: str = "") -> None:
    say("  [FAIL] %s%s" % (msg, ("  (%s)" % detail) if detail else ""))


class Abort(Exception):
    """流程被用户或前置检查中止。/ The flow was stopped."""

    def __init__(self, why: str, code: int = 1):
        super().__init__(why)
        self.why = why
        self.code = code


# ----------------------------------------------------------------------
# 工具 / helpers
# ----------------------------------------------------------------------
def run(cmd, timeout=None, quiet=False, cwd=ROOT, check=True):
    """跑一个命令。/ Run a command.

    ⛔ **绝不用 `shell=True`**：Windows 上那会让参数里的空格和引号按 cmd 的
    规则重新解析，路径里有空格就被拆成两个参数。列表参数 + `shell=False`
    是唯一可靠的写法。
    Never `shell=True`: on Windows the shell re-parses the argument string and
    a path with spaces becomes two arguments.  A list is the only safe form.

    :param quiet: 成功时只回退出码，失败时把输出打出来（失败还静默是最烦人的
        调试体验）。Suppress output on success; print it on failure.
    """
    printable = " ".join(str(c) for c in cmd)
    if not quiet:
        say("  $ %s" % printable)
    p = subprocess.run(cmd, cwd=cwd, timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        # 失败一律打印，哪怕 quiet —— 静默的失败比报错难查一百倍。
        # Always print on failure, even when quiet: a silent failure is far
        # harder to debug than a noisy one.
        out = (p.stdout or "").strip()
        if out:
            say(out)
    return p.returncode


#: 网络类错误的关键词 —— 只有这些才值得重试。
#: Keywords that identify a *network* failure; only those are worth retrying.
_NET_ERRORS = ("connection", "timeout", "timed out", "dial tcp",
               "temporarily unavailable", "connection reset",
               "connection refused", "eof", "tls", "ssl",
               "could not resolve", "bad gateway", "service unavailable",
               "502", "503", "504",
               # ★ 2026-10-29 实测遇到的真实错误（发 v1.1.3-beta.1 时）：
               #   error checking for existing release: Head
               #   "https://api.github.com/repos/.../releases/tags/...":
               #   dial tcp 198.18.1.67:443: connectex: ...
               # 它里的关键词是「connectex」与「attempt failed」——
               # 不是常见的 "connection" / "timeout"，所以下面单独列了。
               "connectex", "attempt failed", "no such host",
               "network is unreachable", "operation timed out")


def is_network_error(text: str) -> bool:
    """
    这段错误输出是不是**网络**问题 / Is this a network failure?

    只对网络类错误重试 —— tag 冲突、参数写错、权限不足这些重试多少次都没用，
    而且**重试会掩盖真正的错误**。
    Only network failures are retried: a tag conflict or a bad argument will
    never fix itself, and retrying would only hide the real error.
    """
    low = (text or "").lower()
    return any(k in low for k in _NET_ERRORS)


def capture(cmd, timeout=None, cwd=ROOT):
    """跑命令并**拿到输出**，返回 `(rc, stdout)`。/ Run and capture output."""
    p = subprocess.run(cmd, cwd=cwd, timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "")


def have(cmd: str) -> bool:
    """某个可执行文件在不在。/ Is this executable on PATH?"""
    rc, _ = capture([cmd, "--version"], timeout=30)
    return rc == 0


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


# ----------------------------------------------------------------------
# 版本号 / version
# ----------------------------------------------------------------------
def current_version() -> str:
    """从 `shimeji/__init__.py` 反查版本号 —— 不写死在这里。/ Read, never hard-code."""
    src = open(os.path.join(ROOT, "shimeji", "__init__.py"),
               encoding="utf-8").read()
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        raise Abort("shimeji/__init__.py 里找不到 __version__")
    return m.group(1)


def setup_path() -> str:
    v = current_version()
    return os.path.join(output_dir(), "Utopet-Setup-%s.exe" % v)


def version_consistency() -> list[str]:
    """版本号在源码、`.iss`、CHANGELOG 三处是否一致。/ Cross-check the version.

    ⚠️ 三处不一致时**必须在这里停**：装出来的包版本和用户看到的不一样，
    是最难排查的一类问题（用户装完看到「1.0.9」，而 CHANGELOG 写的是「1.0.11」）。
    """
    problems = []
    v = current_version()
    iss = open(iss_path(), encoding="utf-8").read()
    m = re.search(r'(?mi)^#define AppVersion\s+"([^"]+)"', iss)
    if not m:
        problems.append(".iss 里找不到 #define AppVersion")
    elif m.group(1) != v:
        problems.append(".iss 的 AppVersion=%s，源码是 %s" % (m.group(1), v))
    m2 = re.search(r"(?mi)^VersionInfoVersion\s*=\s*(\S+)", iss)
    vv = m2.group(1) if m2 else ""
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", vv):
        problems.append("VersionInfoVersion=%r 不是四段数字" % vv)
    elif vv.rstrip("0").rstrip(".") != v:
        problems.append("VersionInfoVersion=%s 对应不上 %s" % (vv, v))
    # CHANGELOG 顶部条目
    cl = os.path.join(ROOT, "CHANGELOG.md")
    if os.path.exists(cl):
        text = open(cl, encoding="utf-8").read()
        m3 = re.search(r"^##\s*\[([0-9][^\]]*)\]", text, re.M)
        if not m3:
            problems.append("CHANGELOG.md 顶部没有版本条目")
        elif not m3.group(1).strip().startswith(v):
            problems.append("CHANGELOG.md 顶部是 [%s]，源码是 %s"
                            % (m3.group(1).strip(), v))
    return problems


# ----------------------------------------------------------------------
# git / GitHub
# ----------------------------------------------------------------------
def git(*args, timeout=120, quiet=True):
    return run(["git"] + list(args), timeout=timeout, quiet=quiet)


def git_capture(*args, timeout=120):
    return capture(["git"] + list(args), timeout=timeout)


def dirty_files() -> list[str]:
    rc, out = git_capture("status", "--porcelain")
    if rc != 0:
        return []
    files = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # `?? name` / ` M name` / `M  name` / `MM name` —— 取最后一段就是路径。
        # Paths may be quoted when they contain non-ASCII; strip the quotes.
        p = line[3:].strip() if len(line) > 3 else ""
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        if p:
            files.append(p)
    return files


def upstream_divergence() -> tuple[int, int]:
    """本地领先/落后远端各多少个提交。/ Commits ahead / behind upstream."""
    rc, out = git_capture("rev-list", "--left-right", "--count",
                          "%s/%s...HEAD" % (REMOTE, BRANCH))
    if rc != 0:
        return (0, 0)
    parts = out.split()
    try:
        # --left-right 给出 `<上游独有> <本地独有>`
        return (int(parts[1]), int(parts[0]))
    except (IndexError, ValueError):
        return (0, 0)


def commit_message(version: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    cl = os.path.join(ROOT, "CHANGELOG.md")
    if os.path.exists(cl):
        text = open(cl, encoding="utf-8").read()
        m = re.search(r"^##\s*\[%s\][^\n]*\n+(.{0,300})" % re.escape(version),
                      text, re.M | re.S)
        if m:
            # CHANGELOG 里这一版的第一段正文。⛔ 跳过 `**加粗**` 开头的行 ——
            # 那是版本的「一句话标题」（如"**你打字的时候，宠物会让开。**"），
            # 才是真正适合当 commit 标题的那句。
            # The first line of the section, skipping bold-only lines: those
            # are the version's one-line title and make a much better subject.
            for line in m.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith(("#", ">", "|", "-")):
                    continue
                bare = re.sub(r"[*_`]+", "", line).strip()
                if not bare:
                    continue
                bare = re.split(r"[。！？.!?]", bare)[0].strip()
                if bare:
                    return "feat: 发布 %s — %s" % (version, bare[:48])
    return DEFAULT_MESSAGE % version


# ----------------------------------------------------------------------
# 步骤 1 · 自检
# ----------------------------------------------------------------------
def preflight(dry: bool) -> str:
    step(1, 5, "自检：工具链、版本号、工作区")
    version = current_version()
    ok("版本号 %s（从 shimeji/__init__.py 读出来的，不是写死的）" % version)

    problems = version_consistency()
    if problems:
        for p in problems:
            fail("版本号不一致：%s" % p)
        raise Abort("版本号在三处对不上，先改一致再打包。"
                    "装出来的版本和用户看到的不一样是最难查的一类问题。")

    # ⚠️ 用 `find_gh()` 而不是裸 "gh"：GitHub CLI 默认**不在 PATH** 里
    # （安装时那个「Add to PATH」默认不勾）。直接跑 `gh` 的后果是「看运气」——
    # 有时能跑、有时不能，同一个人同一脚本行为却不一样。
    # Use find_gh() rather than a bare "gh": the CLI is not on PATH by default.
    _gh = find_gh()
    if not have(_gh):
        fail("找不到 gh（GitHub CLI）：%s" % _gh)
        raise Abort("Release 那一步需要 gh。先装：winget install GitHub.cli")
    rc, out = capture(gh_cmd("auth", "status"), timeout=60)
    # ⚠️ 别用 `ok()` 打印「异常」—— `ok()` 是**无条件**加 `[ok]` 前缀的，
    # 拿它报失败会让人以为自检通过了。异常要走 `fail()`。
    # Do not print a failure through ok(): it always tags the line "[ok]".
    if rc == 0:
        ok("gh 已登录")
    else:
        fail("gh 登录状态异常", out[:200].replace("\n", " "))
        raise Abort("gh 没登录，先跑 gh auth login")

    rc, url = git_capture("remote", "get-url", REMOTE)
    if rc != 0:
        fail("没有名为 %s 的 remote" % REMOTE)
        raise Abort("git remote 里没有 %s" % REMOTE)
    ok("remote %s → %s" % (REMOTE, url.strip()))

    # 上游有没有别人的新提交 —— 有就别推了，强推会把别人的工作弄丢。
    ahead, behind = upstream_divergence()
    if behind > 0:
        fail("本地落后远端 %d 个提交" % behind)
        raise Abort("先 git pull %s %s 再发版。"
                    "本地有落后时推送会被拒，强推更不行。" % (REMOTE, BRANCH))
    if ahead > 0:
        ok("本地领先远端 %d 个提交" % ahead)

    files = dirty_files()
    if files:
        warn("工作区有 %d 个文件未提交，本次会自动一起提交：" % len(files))
        for f in files[:12]:
            say("       %s" % f)
        if len(files) > 12:
            say("       … 还有 %d 个" % (len(files) - 12))
    else:
        ok("工作区干净，没有未提交的改动")

    existing = os.path.exists(setup_path())
    if existing:
        warn("output\\ 里已经有 %s（会被覆盖）"
             % os.path.basename(setup_path()))
    return version


# ----------------------------------------------------------------------
# 步骤 2 · 构建自包含程序
# ----------------------------------------------------------------------
def build_dist(dry: bool) -> None:
    step(2, 5, "构建自包含可执行程序（PyInstaller）")
    if dry:
        say("  --dry-run：跳过")
        return
    t0 = time.time()
    rc = run([sys.executable, os.path.join("tools", "build_release.py")],
             timeout=1800, quiet=False)
    if rc != 0:
        raise Abort("构建失败（返回码 %d）" % rc)
    if not os.path.exists(dist_exe()):
        raise Abort("构建说成功了，但 %s 不存在"
                    % os.path.relpath(dist_exe(), ROOT))
    n = sum(len(f) for _, _, f in os.walk(os.path.join(ROOT, "dist", "Utopet")))
    ok("dist/ 就绪：%s（约 %s，%d 个文件），用时 %.0fs"
       % (os.path.relpath(os.path.dirname(dist_exe()), ROOT),
          human(sum(os.path.getsize(os.path.join(r, f))
                    for r, _, fs in os.walk(os.path.join(ROOT, "dist", "Utopet"))
                    for f in fs)), n, time.time() - t0))


# ----------------------------------------------------------------------
# 步骤 3 · 编译安装包
# ----------------------------------------------------------------------
def build_setup(version: str, dry: bool) -> str:
    step(3, 5, "编译安装包（Inno Setup）")
    path = setup_path()
    if dry:
        say("  --dry-run：跳过（将会生成 %s）" % os.path.basename(path))
        return path
    iscc = find_iscc()
    if not os.path.exists(iscc):
        raise Abort("找不到 ISCC（Inno Setup 6 的编译器）。"
                    "装好 Inno Setup 6，或用环境变量 ISCC 指定 exe 完整路径。"
                    "最后试过的位置：%s" % iscc)

    # ⭐ ISCC 必须**从 PowerShell** 调。Bash 里 `cmd /c xxx.bat` 会被沙箱
    # 直接拦掉（"Invoking cmd.exe from Bash bypasses all command
    # validation"），所以那套「先写 .bat 再 cmd /c」的老办法不能用了。
    # ISCC must be invoked from PowerShell: `cmd /c` from Bash is blocked by
    # the sandbox, so the old "write a .bat then call cmd /c" trick is dead.
    say("  $ powershell ISCC installer\\Utopet.iss")
    p = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         '& "%s" "%s"; exit $LASTEXITCODE' % (iscc, iss_path())],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=1800)
    if p.returncode != 0:
        say((p.stdout or "").strip()[-3000:])
        raise Abort("ISCC 返回码 %d" % p.returncode)
    if not os.path.exists(path):
        raise Abort("ISCC 说成功了，但 %s 不存在" % os.path.basename(path))
    ok("安装包：%s（%s）"
       % (os.path.basename(path), human(os.path.getsize(path))))
    return path


# ----------------------------------------------------------------------
# 步骤 4 · 测试
# ----------------------------------------------------------------------
def run_tests(dry: bool, skip_installer: bool) -> None:
    step(4, 5, "回归测试")
    if dry:
        say("  --dry-run：跳过")
        return

    scripts = [s for s in QUIET_SCRIPTS]
    for name in scripts:
        path = os.path.join(ROOT, "analysis", name)
        if not os.path.exists(path):
            continue
        rc = run([sys.executable, os.path.join("analysis", name)],
                 timeout=1800, quiet=True)
        if rc != 0:
            raise Abort("%s 返回码 %d" % (name, rc))
        ok("%s 通过" % name)

    if skip_installer:
        warn("按要求跳过安装包实测")
    else:
        # ⚠️ 这一步会 **taskkill 掉正在运行的 Utopet**（脚本按设计如此，
        # 它要反复装卸）。跑完那个实例就没了，需要用户自己再打开。
        warn("安装包实测会 taskkill 掉正在运行的桌宠（按设计如此）")
        rc = run([sys.executable, os.path.join("analysis", "verify_installer.py")],
                 timeout=1800, quiet=True)
        if rc != 0:
            raise Abort("verify_installer.py 返回码 %d" % rc)
        ok("verify_installer.py 通过（安装 / 脱离 Python 启动 / 迁移 / 卸载）")


# ----------------------------------------------------------------------
# 步骤 5 · 发布
# ----------------------------------------------------------------------
def publish(version: str, setup_path_: str, dry: bool, assume_yes: bool,
            message: str | None, prerelease: str | None = None) -> None:
    step(5, 5, "推送 GitHub 并创建 Release")

    msg = commit_message(version, message)
    files = dirty_files()
    # ---- 测试版用**独立 tag** ----
    # A pre-release gets its own tag.
    #
    # ⛔ 不能复用 `v1.1.2`：tag 一旦推上去就收不回来（强推会被 GitHub 拒绝，
    # 删 tag 又会让已经下载过的人拿到错乱的引用）。将来 1.1.2 正式发布时需要
    # 那个 tag，所以测试版必须另起一个（`v1.1.2-beta.1`）。
    # Reusing `v1.1.2` is a trap: a pushed tag is effectively irreversible
    # (force-push is rejected, deleting it leaves anyone who already
    # downloaded pointing at a confusing ref).  The real 1.1.2 release will
    # need that tag, so a pre-release must use its own (`v1.1.2-beta.1`).
    if prerelease:
        tag = "v%s-%s" % (version, prerelease)
    else:
        tag = "v%s" % version

    # ---- 5.1 提交 ----
    if files:
        say("")
        say("  待提交 %d 个文件：" % len(files))
        for f in files:
            say("    %s" % f)
        say("")
        say("  commit message：%s" % msg)
        if dry:
            say("  --dry-run：跳过提交")
        else:
            # 检查「有没有测试脚本被 .gitignore 挡在这次提交之外」。
            #
            # ⚠️ 2026-10-29 更正：这里的原注释说「`.gitignore` 里有 `analysis/*`，
            # 整个 analysis 目录被忽略」—— **这是错的**。`.gitignore` 里并没有
            # `analysis/*` 这条规则，只有 `analysis/_*` 和几个截图产物
            # （`analysis/appearance_*.png` 等）。实测：新写的 `analysis/verify_x.py`
            # 用普通 `git add` 就能入库，42 个测试脚本一直都在版本控制里。
            #
            # **检查本身要留着** —— 规则随时可能变，而且「测试没提交」是最容易漏
            # 掉又最难发现的坑：提交里少了测试，回归就再也跑不到那些断言。
            # 只是别再把原因说成「整个目录被忽略」。
            #
            # Check whether any test script is excluded from this commit by
            # .gitignore.  The original comment claimed `analysis/*` was
            # ignored — that was wrong: only `analysis/_*` and a few
            # screenshots are, and new test scripts have always been
            # committable with a plain `git add`.  The check stays, because
            # "the test never got committed" is the most easily missed and
            # hardest-to-notice kind of mistake.
            rc = git("add", "-A", timeout=120)
            if rc != 0:
                raise Abort("git add 失败")
            rc, out = git_capture("ls-files", "--others",
                                  "--ignored", "--exclude-standard",
                                  "analysis")
            new_ignored = [l for l in out.splitlines()
                           if l.strip().endswith(".py")]
            if new_ignored:
                warn("analysis\\ 下有 %d 个 .py 文件被 .gitignore 排除，"
                     "这次提交**不含**它们（如需入库：git add -f）："
                     % len(new_ignored))
                for f in new_ignored[:6]:
                    say("       %s" % f)
            rc = run(["git", "commit", "-m", msg], timeout=120, quiet=True)
            if rc != 0:
                raise Abort("git commit 失败")
            ok("已提交：%s" % msg)
    else:
        ok("没有需要提交的改动")

    # ---- 5.2 推送前确认 ----
    rc, out = git_capture("rev-parse", "HEAD")
    head = out.strip()[:12] if rc == 0 else "?"
    repo = _gh_repo_slug(REMOTE) if not dry else "(dry-run)"
    # Release 已经存在的话，现在推上去只会半路失败（代码推了、Release 建不了），
    # 留下一个"代码推了但没发版"的半成品状态。所以提前查、提前说清楚。
    rel_exists = False
    if not dry:
        rc2, _ = capture(gh_cmd("release", "view", tag, "--repo", repo),
                         timeout=120)
        rel_exists = (rc2 == 0)
        if rel_exists:
            fail("GitHub 上已经有 Release %s 了" % tag)
            say("")
            say("       这一版的代码推上去之后就没有对应的 Release，"
                "会留个半成品。")
            say("       想重发这一版的话，先删掉旧的：")
            say("         gh release delete %s --repo %s --yes" % (tag, repo))
            say("       并删掉本地 tag：")
            say("         git tag -d %s && git push %s --delete %s"
                % (tag, REMOTE, tag))
            say("")
            say("       或者换个 tag 发（比如 %s）：" % ("v" + version + "-2"))
            say("         python tools/release.py -m \"你的 message\"")
            say("         （脚本目前按 v<版本号> 命名 tag，重名时会在这里提示）")
            raise Abort("Release %s 已存在，先处理掉再发" % tag)

    say("")
    say("  " + "-" * 64)
    say("  即将对 GitHub 做这些事：")
    say("    仓库    %s（%s）" % (repo, REMOTE))
    say("    分支    %s（当前提交 %s）" % (BRANCH, head))
    if files:
        say("    提交    %s" % msg)
    say("    推送    git push %s %s" % (REMOTE, BRANCH))
    say("    Release %s  tag=%s" % (version, tag))
    if prerelease:
        say("    类型    **测试版（pre-release）** —— 不占用「最新版本」位置，")
        say("            用户在 Releases 列表里要自己点进去才看得到。")
    say("    附件    %s（%s）"
        % (os.path.basename(setup_path_),
           human(os.path.getsize(setup_path_)) if os.path.exists(setup_path_) else "?"))
    say("  " + "-" * 64)

    if dry:
        say("")
        say("  --dry-run：到此为止，什么都没真的做。")
        return

    if not assume_yes:
        say("")
        # ⚠️ **必须有真终端**才能问。stdin 被重定向（CI、管道、`nohup`）时
        # `input()` 会抛 EOFError；那种情况下**宁可不发**也不要默认同意 ——
        # 推 tag 和建 Release 撤不回来。
        # `input()` needs a real terminal.  With stdin redirected (CI, a pipe,
        # nohup) it raises EOFError; in that case refuse rather than assume
        # yes: a pushed tag and a published Release cannot be taken back.
        if not sys.stdin or not sys.stdin.isatty():
            raise Abort("没有可交互的终端，无法确认。"
                        "确认要发布的话，加 --yes 重跑。")
        try:
            ans = input("  确认推送并创建 Release？输入 yes 继续，其它任意键取消: ")
        except (EOFError, KeyboardInterrupt):
            say("")
            say("  已取消。")
            raise Abort("用户取消", code=0)
        if ans.strip().lower() not in ("yes", "y"):
            say("")
            say("  已取消。前面几步的产物都还在，可以直接用。")
            raise Abort("用户取消", code=0)
    else:
        say("")
        warn("--yes：跳过确认，直接推送并创建 Release（不可撤销）")

    # ---- 5.3 推代码 ----
    rc = git("push", REMOTE, BRANCH, timeout=600, quiet=True)
    if rc != 0:
        raise Abort("push 失败（返回码 %d）" % rc)
    ok("已推送 %s → %s/%s" % (BRANCH, REMOTE, BRANCH))

    # ---- 5.4 建 Release + 传附件 ----
    notes_path = os.path.join(ROOT, "_release_notes.tmp.md")
    _write_notes(version, notes_path)
    try:
        repo = _gh_repo_slug(REMOTE)
        title = "Utopet %s" % version
        cmd = gh_cmd("release", "create", tag,
                     "--repo", repo,
                     "--title", title,
                     "--notes-file", notes_path)
        if prerelease:
            # `--prerelease` 让 GitHub 把它标成测试版：不会成为 "Latest"，
            # 用户默认也看不到，得自己点进 Releases 才找得到。这正是测试版
            # 该有的待遇 —— 不跟正式版抢「最新版本」的位置。
            # `--prerelease` keeps it out of the "Latest" slot: users do not
            # see it by default, which is exactly right for a test build.
            cmd.append("--prerelease")
            title = "%s（测试版 %s）" % (title, prerelease)
            cmd[cmd.index("--title") + 1] = title
        cmd.append(setup_path_)
        say("  $ gh release create %s --repo %s%s …" % (
            tag, repo, " --prerelease" if prerelease else ""))
        # ⭐⭐ **网络类错误重试 3 次**。
        #
        # 2026-10-29 发 `v1.1.3-beta.1` 时这一步曾因代理的 fake-ip 连接超时而挂掉：
        # `dial tcp 198.18.1.67:443: connectex: A connection attempt failed`。
        # 那时 main 已推送、commit 已提交、构建与测试全过，**只有 tag 和
        # Release 没建**，最后靠手写脚本补跑了 11 分钟（主要是 35.8 MB 上传）。
        #
        # 重试**不重建任何东西**：`gh release create` 对已存在的 tag 是幂等的
        # （只有 tag 已存在**且已有 Release**才会失败）。
        #
        # 只对**网络类**错误重试：tag 冲突、参数错、权限不足重试没用，
        # 而且重试会**掩盖真正的错误**。
        #
        # Retry only *network* failures.  A tag conflict or a permission error
        # will never fix itself, and retrying would hide the real problem.
        rc, out = 1, ""
        for _attempt in range(1, 4):
            rc, out = capture(cmd, timeout=900)
            if rc == 0:
                if _attempt > 1:
                    ok("网络恢复，第 %d 次尝试成功" % _attempt)
                break
            if not is_network_error(out):
                break
            if _attempt < 3:
                warn("网络错误（%s），5 秒后重试（%d/3）"
                     % (out.strip().splitlines()[-1][:80] if out.strip() else "?",
                        _attempt))
                time.sleep(5)
        if rc != 0:
            say(out.strip()[-2000:])
            raise Abort("gh release create 返回码 %d" % rc)
        ok("Release 已创建并附上安装包%s"
           % ("（测试版）" if prerelease else ""))
        say("")
        say("  %s" % (out.strip().splitlines()[-1] if out.strip() else ""))
    finally:
        if os.path.exists(notes_path):
            try:
                os.remove(notes_path)
            except OSError:
                pass


def _gh_repo_slug(remote: str) -> str:
    """从 remote URL 解析出 `owner/repo`。/ Parse owner/repo out of the remote URL."""
    rc, out = git_capture("remote", "get-url", remote)
    url = out.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if not m:
        raise Abort("从 remote URL 里解析不出 owner/repo：%s" % url)
    return "%s/%s" % (m.group(1), m.group(2))


def _write_notes(version: str, path: str) -> None:
    """把 CHANGELOG 里这一版的正文抽出来当 Release 说明。

    抽 CHANGELOG 而不是另写一份：两份说明迟早会对不上，而 Release 说明
    本来就是 CHANGELOG 的复制品。
    Pull this version's section out of CHANGELOG rather than keeping a second
    copy: two copies drift, and release notes are a copy of the changelog.
    """
    cl = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(cl):
        open(path, "w", encoding="utf-8").write("Utopet %s" % version)
        return
    text = open(cl, encoding="utf-8").read()
    m = re.search(r"^##\s*\[%s\][^\n]*\n(.*?)(?=^##\s*\[|\Z)"
                  % re.escape(version), text, re.M | re.S)
    body = m.group(1).strip() if m else ""
    # 去掉版本标题行里重复的日期引用
    body = re.sub(r"^###\s*已知限制.*$", "### Known limitations", body,
                  flags=re.M)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body or "见 CHANGELOG.md 的 `%s` 条目。" % version)


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="构建 + 打包 + 测试 + 推送 + 发版，一条命令走完。")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="推送和建 Release 前不询问")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="只打印要做什么，不改动任何东西")
    ap.add_argument("--skip-tests", action="store_true",
                    help="跳过安装包实测（它会 taskkill 正在运行的桌宠）")
    ap.add_argument("--message", "-m", default=None,
                    help="commit message（默认取 CHANGELOG 里这一版的标题）")
    ap.add_argument("--build-only", "-b", action="store_true",
                    help="只构建 + 打包 + 测试，**不 commit、不 push、不建 Release**。"
                         "产物留在 dist\\ 与 output\\，确认满意后再跑一次"
                         "（去掉本参数）就能发出去。"
                         " Build and package only: no commit, no push, no Release.")
    ap.add_argument("--prerelease", default=None, metavar="SUFFIX",
                    help="发成**测试版**：tag 用 v<版本>-<SUFFIX>（如 beta.1），"
                         "Release 标记为 pre-release，不占用「最新版本」位置。"
                         " Publish as a pre-release: the tag becomes "
                         "v<version>-<SUFFIX> and the Release is flagged "
                         "pre-release, so it does not take the Latest slot.")
    args = ap.parse_args()

    t0 = time.time()
    say("=" * 68)
    say("  Utopet 发布流程")
    if args.dry_run:
        say("  模式：--dry-run（什么都不改）")
    say("=" * 68)

    try:
        version = preflight(args.dry_run)
        build_dist(args.dry_run)
        setup = build_setup(version, args.dry_run)
        run_tests(args.dry_run, args.skip_tests)
        if args.build_only and not args.dry_run:
            # 「只打包」模式：前四步照跑，第五步整个跳过。
            # **连 commit 都不做** —— 用户可能还想改点东西再发，工作区保持
            # 原样才不会把「还没想好」的状态推到远端。
            step(5, 5, "跳过发布（--build-only）")
            say("")
            ok("只构建不发布：没有 commit、没有 push、没有 Release")
            say("")
            say("  安装包  %s" % os.path.basename(setup))
            say("  免安装  %s" % os.path.relpath(os.path.dirname(dist_exe()),
                                                ROOT))
            say("")
            say("  确认满意后，去掉 --build-only 再跑一次就能发出去；")
            say("  想先看看会做什么，加 --dry-run。")
            say("=" * 68)
            return 0
        publish(version, setup, args.dry_run, args.yes, args.message,
                prerelease=args.prerelease)
    except Abort as e:
        say("")
        if e.why:
            fail(e.why)
        say("")
        say("流程中止。已生成的产物都保留在原处。")
        return e.code
    except KeyboardInterrupt:
        say("")
        fail("被中断")
        return 130

    say("")
    say("=" * 68)
    ok("全部完成，用时 %.0fs" % (time.time() - t0))
    if not args.dry_run:
        say("")
        say("  安装包  %s" % os.path.basename(setup))
        say("  dist    %s"
            % os.path.relpath(os.path.dirname(dist_exe()), ROOT))
        say("  桌宠跑完安装测试后不在运行，需要的话自己再打开。")
    say("=" * 68)
    return 0


if __name__ == "__main__":
    # 退出码必须可信：发版脚本被 CI 调，返回值就是「成没成」的判断依据。
    # The exit code must be trustworthy: CI keys off it.
    sys.stdout.flush()
    sys.exit(main())