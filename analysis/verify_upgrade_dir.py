# -*- coding: utf-8 -*-
r"""实测：升级安装会不会沿用上一次的安装目录。

背景：用户报「更新版本不会自动安装到之前的文件夹」。Inno Setup 靠
AppId 相同 + 注册表里的 InstallLocation 记住上次目录。

⚠️ 这个脚本会真的动这台机器上的 Utopet 安装，跑之前必须先把用户的
   data\ 与 characters\ 备份好（_realinstall_bak），跑完再装回去。
   脚本自己不做备份 —— 备份必须是显式的一步，否则出问题就没得救了。

做法：
  1. 记录当前真实安装目录与注册表里的版本
  2. 装旧版到自定义目录 → 确认注册表记住了它
  3. 不传 /DIR 装新版 → 看它落在自定义目录还是默认目录
  4. 还原：装回原目录 + 把 data\characters\ 搬回去

用法：python analysis/verify_upgrade_dir.py
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HERE = os.path.join(ROOT, "analysis")
CUSTOM = os.path.join(HERE, "_upg_target")
BAK = os.path.join(HERE, "_realinstall_bak")
USERPROFILE = os.environ.get("USERPROFILE", "")
REGKEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
          r"\{8E7C4B1A-9D2F-4A63-B5E8-1C7F3D6A2B90}_is1")
FAILS: list[str] = []

# 安装包先复制到临时目录再用。
# Stage the setup packages in a temp dir first.
#
# 这个脚本会反复装/卸，而卸载器（[UninstallDelete] 之类）在某些状态下会把
# 输出目录当成安装目录处理 —— 上一轮实测就把 output/ 里的安装包全删了，
# 只剩一个旧版本。留着这份副本，之后无论 output/ 变成什么样都能复现。
# Never install (or let the uninstaller reach) the originals in output\: a real
# run wiped every package there but one.  Work on copies so the test is
# reproducible regardless of what happens to output\.
STAGE = os.path.join(HERE, "_upg_stage")


def stage(setup: str) -> str:
    os.makedirs(STAGE, exist_ok=True)
    dst = os.path.join(STAGE, os.path.basename(setup))
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(setup):
        shutil.copy2(setup, dst)
    return dst


def check(cond: bool, msg: str, detail: str = ""):
    line = ("  [ok]   " if cond else "  [FAIL] ") + msg
    if detail:
        line += f"({detail})"
    print(line, flush=True)
    if not cond:
        FAILS.append(msg)


def p(msg: str = ""):
    print(msg, flush=True)


def setup_of(v: str) -> str:
    """取指定版本；传 "newest" 表示 output 里最新的那个。

    别把版本号写死在调用处 —— 上一版就是这么漏的：脚本还在测 1.0.5，
    而实际已经出到 1.0.6，测试全绿却什么都没验证到。
    Ask for "newest" rather than hardcoding a version: a hardcoded one
    silently keeps testing the previous build after a version bump.
    """
    import glob as _g
    if v == "newest":
        hits = sorted(_g.glob(os.path.join(ROOT, "output", "Utopet-Setup-*.exe")))
        if not hits:
            raise SystemExit("output 里没有安装包")
        return hits[-1]
    hits = sorted(_g.glob(os.path.join(ROOT, "output", f"Utopet-Setup-{v}.exe")))
    if not hits:
        raise SystemExit(f"找不到安装包 {v}")
    return hits[-1]


def run(exe: str, args: list[str], wait_s: int = 120) -> int:
    try:
        return subprocess.run([exe] + args, timeout=wait_s).returncode
    except subprocess.TimeoutExpired:
        return -1


def kill_pet():
    subprocess.run(["taskkill", "/F", "/IM", "Utopet.exe"], capture_output=True)
    time.sleep(1)


def reg_read() -> tuple[str, str]:
    """读注册表里的 (InstallLocation, DisplayVersion)。"""
    import winreg
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, REGKEY) as k:
                loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                ver, _ = winreg.QueryValueEx(k, "DisplayVersion")
                return loc, ver
        except OSError:
            continue
    return "", ""


def reg_delete():
    import winreg
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            winreg.DeleteKey(root, REGKEY)
        except OSError:
            pass


def rmtree(d: str):
    if d and os.path.isdir(d):
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", d], capture_output=True)


def same(a: str, b: str) -> bool:
    return os.path.normcase(a.rstrip("\\")) == os.path.normcase(b.rstrip("\\"))


def copy_tree(src: str, dst: str):
    """不覆盖地合并回去 —— 用户改过的文件必须赢过包里那份。"""
    if not os.path.isdir(src):
        return
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            s = os.path.join(base, f)
            d = os.path.join(target, f)
            if not os.path.exists(d):
                shutil.copy2(s, d)


def main() -> None:
    old_setup = stage(setup_of("1.0.3"))
    new_setup = stage(setup_of("newest"))
    p(f"  旧包: {os.path.basename(old_setup)}")
    p(f"  新包: {os.path.basename(new_setup)}")

    p("=== 0. 记录当前真实安装 ===")
    orig_loc, orig_ver = reg_read()
    p(f"  当前安装目录: {orig_loc}  版本: {orig_ver}")
    has_backup = os.path.isdir(os.path.join(BAK, "data"))
    check(has_backup, "已有 data\\ 备份（否则先手工备份再跑）", BAK)
    if not has_backup:
        p("  没有备份，中止。请先复制真实安装的 data\\ 和 characters\\ 到 " + BAK)
        sys.exit(2)

    try:
        p()
        p("=== A. 装旧版到自定义目录 ===")
        kill_pet()
        reg_delete()
        rmtree(CUSTOM)
        rc = run(old_setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             f"/DIR={CUSTOM}"])
        check(rc == 0, "旧版安装返回码 0", f"rc={rc}")
        check(os.path.isfile(os.path.join(CUSTOM, "Utopet.exe")),
              "旧版落在自定义目录")
        loc, ver = reg_read()
        check(same(loc, CUSTOM), "注册表记下了自定义目录", f"{loc} ({ver})")

        p()
        p("=== B. 不传 /DIR 装新版（模拟用户双击升级）===")
        kill_pet()
        rc = run(new_setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        check(rc == 0, "新版安装返回码 0", f"rc={rc}")
        in_custom = os.path.isfile(os.path.join(CUSTOM, "Utopet.exe"))
        loc2, ver2 = reg_read()
        p(f"  自定义目录里有 exe: {in_custom}")
        p(f"  注册表: {loc2} ({ver2})")
        check(same(loc2, CUSTOM),
              "新版沿用了原目录（注册表指向自定义目录）", loc2)
        # 版本号从新包文件名里读，别写死 —— 写死过一次，脚本测的还是 1.0.5
        # 而实际已经出到 1.0.6，一轮全绿却什么都没验证。
        want_ver = os.path.basename(new_setup).split("-")[-1].replace(".exe", "")
        check(ver2 == want_ver, f"版本号已更新为 {want_ver}", ver2)

        p()
        p("=== C. 对照：抹掉注册表记录后再升一次 ===")
        kill_pet()
        reg_delete()
        rc = run(new_setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             f"/DIR={CUSTOM}"])
        check(rc == 0, "对照组安装返回码 0", f"rc={rc}")
        loc3, _ = reg_read()
        check(same(loc3, CUSTOM),
              "对照组：记录缺失时会退回默认目录（这正是用户遇到的）", loc3)

        p()
        p("=== D. per-user 残留会被自动找回并清掉 ===")
        # 造一个「仅为我安装」留下的副本，里面放一份独有的设置，
        # 看新版装的时候会不会把它捞回来、并且把残留目录删掉。
        kill_pet()
        reg_delete()
        rmtree(CUSTOM)
        user_dir = os.path.join(USERPROFILE, "AppData", "Local", "Programs",
                                "Utopet")
        rmtree(user_dir)
        os.makedirs(os.path.join(user_dir, "data"), exist_ok=True)
        with open(os.path.join(user_dir, "data", "settings.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"summon_count": 9, "from": "per-user"}, f)
        # 造一个 exe 占位：安装脚本靠它（和 data\）判断这是不是安装目录。
        # 只造 data\ 不够 —— 上一轮测试就是漏了这个，白报了 FAIL。
        with open(os.path.join(user_dir, "Utopet.exe"), "wb") as f:
            f.write(b"MZstub")
        rc = run(new_setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             f"/DIR={CUSTOM}"])
        check(rc == 0, "per-user 场景安装返回码 0", f"rc={rc}")
        moved = os.path.join(CUSTOM, "data", "settings.json")
        got = None
        if os.path.exists(moved):
            with open(moved, encoding="utf-8") as f:
                got = json.load(f)
        check(bool(got) and got.get("from") == "per-user",
              "per-user 副本里的设置被搬回来了", str(got))
        check(not os.path.isdir(user_dir),
              "per-user 残留目录已被清理（不会留下第二份）",
              f"exists={os.path.isdir(user_dir)}")
    finally:
        p()
        p("=== 还原真实安装 ===")
        kill_pet()
        reg_delete()
        if orig_loc:
            rc = run(new_setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                 f"/DIR={orig_loc}"])
            p(f"  装回 {orig_loc}: rc={rc}")
            copy_tree(os.path.join(BAK, "data"), os.path.join(orig_loc, "data"))
            copy_tree(os.path.join(BAK, "characters"),
                      os.path.join(orig_loc, "characters"))
        rmtree(CUSTOM)
        loc4, ver4 = reg_read()
        p(f"  还原后注册表: {loc4} ({ver4})")
        # 这条断言是给「finally 块本身失败」兜底的：上一轮 finally 里抛了
        # FileNotFoundError（安装包被删），结果真实安装的注册表记录就没了，
        # 而测试却因为异常退出、没报任何 FAIL。
        check(same(loc4, orig_loc) and ver4 == want_ver,
              "真实安装已还原回原目录与原版本（finally 块自检）",
              f"{loc4} ({ver4})")

    p()
    p("=" * 60)
    if FAILS:
        p(f"FAILED {len(FAILS)}:")
        for f in FAILS:
            p("  x " + f)
        sys.exit(1)
    p("ALL PASS —— 升级沿用原目录")


if __name__ == "__main__":
    main()