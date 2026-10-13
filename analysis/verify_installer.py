# -*- coding: utf-8 -*-
"""实测安装包：静默安装到临时目录 → 检查内容 → 跑起来 → 卸载。

这是唯一能证明安装包真的可用的测法。只看 ISCC 编译成功是不够的。

做法：
  1. /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=... 静默安装
  2. 检查 exe、_internal（含 python3xx.dll / Qt6Core.dll）、locales、assets
  3. **重点：characters 只能有 Miku**
  4. 清空 PATH 启动 exe，确认脱离 Python 能跑
  5. 静默卸载，确认目录清空

用法：python analysis/verify_installer.py
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 下面要从 shimeji.settings 读默认角色，所以项目根必须在 sys.path 上。
# 从项目根运行时 cwd 恰好是根，但换个目录调用就 ModuleNotFoundError ——
# 路径要自己算，不能指望 cwd。
sys.path.insert(0, ROOT)   # to import shimeji.settings below
TESTDIR = os.path.join(ROOT, "analysis", "_installtest")


def _find_setup() -> str:
    """挑 output 里最新的安装包，复制到暂存目录后返回副本。

    为什么要复制：这个脚本会反复安装/卸载，而安装包的卸载流程偶尔会把
    output\ 当成安装目录处理 —— 实测跑一轮就把output\ 里的安装包全删了
    （只剩一个早先的旧版本），脚本下一次调用就FileNotFoundError。
    对副本下手，产物就安全了。

    Stage a copy of the newest setup instead of using the original.
    This script installs and uninstalls repeatedly, and that occasionally
    reaches output\ as if it were the install directory — a real run wiped
    every package there but one, and the next run died with
    FileNotFoundError.  Operating on a copy keeps the artifacts safe.

    按文件名排序取最后一个，而不是把版本号写死在代码里 ——
    否则每次升版本（1.0.0 -> 1.0.1）都要记得改这里，忘了就测的是上一版。
    """
    out = os.path.join(ROOT, "output")
    found = sorted(glob.glob(os.path.join(out, "Utopet-Setup-*.exe")))
    if not found:
        raise SystemExit(f"output 里没有安装包：{out}")
    stage = os.path.join(ROOT, "analysis", "_upg_stage")
    os.makedirs(stage, exist_ok=True)
    src = found[-1]
    dst = os.path.join(stage, os.path.basename(src))
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copy2(src, dst)
    print(f"[setup] {os.path.basename(src)} -> 暂存副本用于测试")
    return dst


SETUP = _find_setup()

FAILS: list[str] = []


def check(cond: bool, msg: str, detail: str = ""):
    """detail 是可选的补充说明（尺寸列表、路径之类），只在输出里显示，不参与判定。"""
    line = ("  [ok]   " if cond else "  [FAIL] ") + msg
    if detail:
        line += f"({detail})"
    print(line, flush=True)
    if not cond:
        FAILS.append(msg)


def run_installer(args: list[str], wait_ms: int = 60000) -> int:
    p = subprocess.Popen([SETUP] + args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait_ms / 1000:
        if p.poll() is not None:
            return p.returncode
        time.sleep(0.5)
    p.kill()
    return -1


def main() -> int:
    if not os.path.exists(SETUP):
        print("[FAIL] 安装包不存在:", SETUP, flush=True)
        return 1

    # 清掉上次测试残留
    if os.path.isdir(TESTDIR):
        subprocess.run(["taskkill", "/IM", "Utopet.exe", "/F"], capture_output=True)
        time.sleep(1.0)
        # 删不掉就走 unins000 卸载
        if os.path.isdir(TESTDIR):
            unins = glob.glob(os.path.join(TESTDIR, "unins*.exe"))
            if unins:
                subprocess.run([unins[0], "/VERYSILENT", "/NORESTART"],
                               capture_output=True, timeout=60)
                time.sleep(2.0)
        if os.path.isdir(TESTDIR):
            print("[warn] 旧测试目录删不掉，换个名字", flush=True)
            globals()["TESTDIR"] = TESTDIR + "_" + str(int(time.time()))

    # 另外两个测试目录也必须清：4b 组在 _migrate_target 里造一个 Ayaka 角色
    # 来验证「用户自己的角色被搬过来」，而 _oldshimeji 是伪造的旧版安装。
    # 这两处上一轮没清，于是下一轮 3组先读到残留的 Ayaka，报
    # 「characters 只含 Miku」失败 —— 看起来像打包把Ayaka 打进包了，
    # 实际是上一轮测试的垃圾没删。测试脚本自己制造假失败，比不打更糟。
    # Clean the other two test dirs too: group 4b plants an Ayaka pack in
    # _migrate_target to prove user characters survive an upgrade, and
    # _oldshimeji is the faked legacy install.  Leaving them behind made the
    # next run see a leftover Ayaka and report "characters must contain only
    # Miku" — a false failure that looks like a packaging bug.
    for _d in (os.path.join(ROOT, "analysis", "_migrate_target"),
               os.path.join(ROOT, "analysis", "_oldshimeji")):
        if os.path.isdir(_d):
            shutil.rmtree(_d, ignore_errors=True)

    print(f"[setup] {SETUP}  ({os.path.getsize(SETUP)/1024/1024:.1f} MB)", flush=True)
    print(f"[dir]   {TESTDIR}\n", flush=True)

    # ---- 1. 静默安装 ----
    print("--- 1. 静默安装 ---", flush=True)
    rc = run_installer(["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        f"/DIR={TESTDIR}", "/LOG=" +
                        os.path.join(ROOT, "analysis", "_install.log")])
    check(rc == 0, f"安装返回码 {rc}（0 = 成功）")
    if rc != 0:
        log = os.path.join(ROOT, "analysis", "_install.log")
        if os.path.exists(log):
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            errs = [x for x in txt.splitlines() if "Error" in x or "error" in x]
            print("  日志里的错误行:", flush=True)
            for e in errs[:15]:
                print("   ", e, flush=True)
        return 2

    # ---- 2. 文件完整性 ----
    print("\n--- 2. 安装内容完整性 ---", flush=True)
    check(os.path.isfile(os.path.join(TESTDIR, "Utopet.exe")), "主程序 Utopet.exe")
    check(os.path.isfile(os.path.join(TESTDIR, "unins000.exe")), "卸载程序 unins000.exe")
    internal = os.path.join(TESTDIR, "_internal")
    check(os.path.isdir(internal), "_internal 运行库目录")
    if os.path.isdir(internal):
        check(bool(glob.glob(os.path.join(internal, "python3*.dll"))),
              "Python 运行库 python3*.dll")
        check(bool(glob.glob(os.path.join(internal, "**", "Qt6Core.dll"), recursive=True)),
              "Qt6Core.dll")
        n = sum(len(f) for _, _, f in os.walk(internal))
        print(f"      _internal 共 {n} 个文件", flush=True)
    check(os.path.isdir(os.path.join(internal, "shimeji", "locales")),
          "语言包 locales/")
    assets = os.path.join(internal, "shimeji", "assets")
    check(os.path.isdir(assets), "图标资源 assets/")

    # ---- 2b. 三份图标都要在，且 app.ico 不能含 >=128 的帧 ----
    # >=128 的帧会被 PyInstaller 读成负宽度、把 exe 图标解析坏，
    # 详见 tools/make_icons.py 的 _assert_pyinstaller_safe()。
    print("\n--- 2b. 图标三件套 ---", flush=True)
    import struct
    icons = {}
    for name in ("logo.png", "logo.ico", "app.ico"):
        p = os.path.join(assets, name)
        ok = os.path.exists(p)
        check(ok, f"assets/{name}" + (f"  ({os.path.getsize(p):,} 字节)" if ok else ""))
        if ok and name.endswith(".ico"):
            d = open(p, "rb").read()
            cnt = struct.unpack("<H", d[4:6])[0]
            icons[name] = [d[6 + i * 16] or 256 for i in range(cnt)]
            print(f"      {name} 帧: {icons[name]}", flush=True)
    if "logo.ico" in icons:
        check(16 in icons["logo.ico"], "logo.ico 含 16px（托盘 100% 缩放）")
    if "app.ico" in icons:
        too_big = [s for s in icons["app.ico"] if s > 127]
        check(not too_big,
              "app.ico 无 >=128 的帧（否则 exe 图标变形）",
              f"过大={too_big or '无'}")

    # ---- 3. characters 只应有 Miku（默认角色）----
    print("\n--- 3. characters 只包含 Miku（默认角色）---", flush=True)
    chars = os.path.join(TESTDIR, "characters")
    check(os.path.isdir(chars), "characters 目录存在")
    if os.path.isdir(chars):
        found = sorted(d for d in os.listdir(chars)
                       if os.path.isdir(os.path.join(chars, d)))
        print(f"      实际内容: {found}", flush=True)
        # 安装包只带 Miku，而 Miku 也是默认角色 —— 两者必须一致，
        # 否则新用户首屏就是「找不到角色」。
        # Only Miku ships and Miku is the default: they have to agree, or a fresh
        # install would start with no usable character.
        check(found == ["Miku"], f"只含 Miku（实际 {found}）")
        miku = os.path.join(chars, "Miku")
        check(os.path.isfile(os.path.join(miku, "conf", "Actions.xml")),
              "Miku/conf/Actions.xml")
        check(os.path.isfile(os.path.join(miku, "conf", "Behavior.xml")),
              "Miku/conf/Behavior.xml")
        nimg = len(glob.glob(os.path.join(miku, "img", "*.png")))
        check(nimg >= 40, f"Miku 图片 {nimg} 张")
        # 默认设置指向的角色必须真的存在，否则首屏是空的
        from shimeji.settings import DEFAULTS
        default_char = DEFAULTS.get("character")
        check(os.path.isdir(os.path.join(chars, default_char or "")),
              f"默认角色 {default_char!r} 在安装包里")

    # ---- 4. 脱离 Python 启动 ----
    print("\n--- 4. 脱离 Python 环境启动 ---", flush=True)
    env = {k: v for k, v in os.environ.items()
           if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                            "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "SYSTEMDRIVE")}
    env["PATH"] = r"C:\Windows\System32"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen([os.path.join(TESTDIR, "Utopet.exe")],
                            env=env, cwd=TESTDIR)
    time.sleep(11.0)
    if proc.poll() is not None:
        check(False, f"exe 启动即退出 rc={proc.returncode}")
        for fn in ("data/shimeji.log", "data/startup_error.log"):
            p = os.path.join(TESTDIR, fn)
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    print(f"  --- {fn} ---", flush=True)
                    print("\n".join(f.readlines()[-12:]), flush=True)
    else:
        check(True, "exe 在无 Python 环境下正常运行")
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        EP = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        vis = {"panel": 0, "pet": 0}

        def cb(h, _):
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == proc.pid and u.IsWindowVisible(h):
                ex = u.GetWindowLongPtrW(h, -20)
                if ex & 0x40000 and not (ex & 0x80):
                    vis["panel"] += 1
                elif ex & 0x80:
                    vis["pet"] += 1
            return True

        u.EnumWindows(EP(cb), 0)
        check(vis["panel"] == 1, f"任务栏面板 1 个（实际 {vis['panel']}）")
        check(vis["pet"] >= 1, f"宠物窗口 {vis['pet']} 个")
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
        time.sleep(1.0)

    # ---- 4b. 从旧版 Shimeji 升级：配置与角色必须保留 ----
    # 这一组是 1.0.3 改名 + 迁移逻辑的唯一实测。做法是真的伪造一个「旧版安装
    # 目录」，再跑新安装包，看它会不会把设置和用户自己加的角色搬过去。
    # The only real test of the 1.0.3 rename + migration: fake an actual old
    # install tree, run the new setup over it, and see whether the settings and
    # the user's own character packs survive.
    print("\n--- 4b. 从旧版 Shimeji 升级（配置 + 角色迁移）---", flush=True)
    olddir = os.path.join(ROOT, "analysis", "_oldshimeji")
    if os.path.isdir(olddir):
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", olddir],
                       capture_output=True)
    # 只放「用户的东西」：一份 settings.json（带一个非默认值，好证明它真的
    # 被搬过去了）+ 一个包里没有的角色 Ayaka + 一个用户改过的标记文件。
    # Only the user's stuff: a settings.json with a non-default value (so we can
    # tell it really moved), a character the bundle does not ship, and a marker
    # file standing in for "user edited this pack".
    os.makedirs(os.path.join(olddir, "data"), exist_ok=True)
    with open(os.path.join(olddir, "data", "settings.json"), "w",
              encoding="utf-8") as f:
        f.write('{"language": "ja_JP", "character": "Ayaka", '
                '"summon_count": 7}')
    aya = os.path.join(olddir, "characters", "Ayaka", "conf")
    os.makedirs(aya, exist_ok=True)
    with open(os.path.join(aya, "USER_EDITED.marker"), "w",
              encoding="utf-8") as f:
        f.write("user content")
    # 用户改过的 Miku：用来验证「包自带的 Miku 不会把它盖回去」。
    # A user-modified Miku: proves the bundled copy does not clobber it.
    mu = os.path.join(olddir, "characters", "Miku", "conf")
    os.makedirs(mu, exist_ok=True)
    with open(os.path.join(mu, "USER_EDITED.marker"), "w",
              encoding="utf-8") as f:
        f.write("user content")
    with open(os.path.join(olddir, "Shimeji.exe"), "w") as f:
        f.write("MZ stub")   # 迁移逻辑只看这个文件在不在

    # 旧版必须装在 {commonpf}\Shimeji 才会被迁移逻辑发现 —— 这里不能改路径，
    # 所以把测试目录做成 Program Files 下的一个真目录。
    real_old = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                            "Shimeji")
    if os.path.isdir(real_old):
        print(f"      [skip] 真实旧版目录已存在，不覆盖：{real_old}", flush=True)
    else:
        subprocess.run(["cmd", "/c", "mklink", "/J", real_old, olddir],
                       capture_output=True)
    # 必须装到**全新目录**：真实升级就是「{commonpf}\Shimeji 存在，
    # {commonpf}\Utopet 还不存在」。装到已装过 Utopet 的目录会命中安装脚本里
    # 「已经是 Utopet 就跳过迁移」的守卫，那样测的就不是迁移路径了。
    # A fresh target directory: a real upgrade means the old dir exists and the
    # new one does not.  Installing over an existing Utopet hits the "already
    # Utopet, skip migration" guard and would test nothing.
    migdir = os.path.join(ROOT, "analysis", "_migrate_target")
    if os.path.isdir(migdir):
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", migdir],
                       capture_output=True)
    if os.path.isdir(real_old):
        rc3 = run_installer(["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             f"/DIR={migdir}",
                             "/LOG=" + os.path.join(ROOT, "analysis",
                                                     "_install_migrate.log")])
        check(rc3 == 0, f"迁移安装返回码 {rc3}")
        d = os.path.join(migdir, "data", "settings.json")
        check(os.path.isfile(d), "旧版 settings.json 被带到新目录",
              f"{d}")
        if os.path.isfile(d):
            import json
            try:
                with open(d, "r", encoding="utf-8") as f:
                    got = json.load(f)
            except Exception as e:  # noqa: BLE001
                got = {}
                print("      解析失败:", e, flush=True)
            check(got.get("character") == "Ayaka",
                  "旧设置被保留（character 仍是 Ayaka）", f"{got.get('character')}")
            check(got.get("summon_count") == 7,
                  "旧设置被保留（summon_count 仍是 7）", f"{got.get('summon_count')}")
        m = os.path.join(migdir, "characters", "Ayaka", "conf",
                         "USER_EDITED.marker")
        check(os.path.isfile(m), "用户自己加的角色 Ayaka 被带过来了", f"{m}")
        check(os.path.isdir(os.path.join(migdir, "characters", "Miku")),
              "Miku 也在（包自带的那份）")
        # 包里的 Miku 不该覆盖用户改过的版本：备份优先
        # The bundled Miku must not clobber a user-modified one: backup wins.
        um = os.path.join(migdir, "characters", "Miku", "conf",
                          "USER_EDITED.marker")
        check(os.path.isfile(um),
              "用户改过的 Miku 也没被包里的版本覆盖",
              f"{um}")
        # 迁移时旧目录应该已经清空或删掉。junction 本身删不掉（它只是个链接），
        # 所以这里只断言「里面已经没有旧版的文件」。
        # The old *directory* is gone; the junction pointing at it may remain,
        # so assert the old files are gone rather than the link itself.
        left = os.listdir(real_old) if os.path.isdir(real_old) else []
        check(not left, "旧版目录已清理", f"残留 {left[:5] if left else '无'}")
    else:
        # junction 建不起来（非管理员）就跳过，不要让整个验证挂掉
        print("      [skip] 无法在 Program Files 建测试目录，跳过迁移验证",
              flush=True)
    # 收尾：无论成败都把 junction 拆掉，否则下次 mkdir 会失败
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", migdir], capture_output=True)
    subprocess.run(["cmd", "/c", "rmdir", real_old], capture_output=True)
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", olddir],
                   capture_output=True)

    # ---- 5. 卸载 ----
    print("\n--- 5. 静默卸载 ---", flush=True)
    unins = glob.glob(os.path.join(TESTDIR, "unins*.exe"))
    if unins:
        rc2 = run_installer([]) if False else None
        p = subprocess.Popen([unins[0], "/VERYSILENT", "/SUPPRESSMSGBOXES",
                              "/NORESTART"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 60 and p.poll() is None:
            time.sleep(0.5)
        check(p.poll() is not None, "卸载程序能启动并结束")
        time.sleep(1.5)
        # ⚠️ 别用 `and` 把「目录还在但内容为空」和「目录不存在」混为一谈：
        # os.listdir 对空目录返回 []，而 not [] 是 True —— 之前这里
        # `left = isdir and listdir` 让**空目录直接通过检查**，所以
        # 「卸载完在 Program Files 里留一个空壳目录」这个 bug 一直没被抓到。
        # 目录存不存在和里面有没有东西必须分开判定。
        # Never conflate "still there but empty" with "gone": listdir returns
        # [] for an empty dir and not [] is True, so an empty leftover folder
        # passed this check and the bug went unnoticed.
        still_there = os.path.isdir(TESTDIR)
        left = os.listdir(TESTDIR) if still_there else None
        check(not still_there,
              f"卸载后目录本身被删除（目录仍存在，残留 {left}）"
              if still_there else "卸载后目录已删除")
    else:
        check(False, "找不到卸载程序")

    print("\n" + "=" * 58, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print("ALL PASS —— 安装包可用", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
