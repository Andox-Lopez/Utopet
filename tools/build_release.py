#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""一键构建自包含版 Utopet.exe

    python tools/build_release.py

做四件事：
  1. 清理旧的 build/ 与 dist/
  2. 调用 PyInstaller 用 shimeji.spec 构建
  3. 把 characters\ 复制到 dist\Utopet\ 旁边（角色包故意不进 exe，方便用户替换）
  4. 打印产物体积清单

构建产物是 **单文件夹（onedir）** 形态：dist\Utopet\ 整个目录拷给用户即可，
里面 Utopet.exe 只是入口，真正的 Qt 运行库在 _internal\ 子目录里。
这是刻意的 —— 单文件 exe 每次启动都要解压到临时目录，启动慢且被杀软误报。
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "Utopet")
SPEC = os.path.join(ROOT, "shimeji.spec")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


def run(*cmd: str) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def _purge(path: str) -> bool:
    """尽力清空一个目录，失败就返回 False。

    为什么要这么小心：WorkBuddy 环境把 shutil.rmtree 接管成了「走回收站」的
    安全删除（safe-delete fail-closed），一旦回收站拒绝就会直接抛 OSError。
    所以这里逐项删、每项都单独 try —— 大不了一条一条报错，整体仍能把能删的
    删掉。删不掉的就留给 PyInstaller 就地覆盖。

    Best-effort wipe.  WorkBuddy intercepts shutil.rmtree with a fail-closed
    "safe delete" that routes through the recycle bin and raises on refusal,
    so every item is removed independently and survivors are left for
    PyInstaller to overwrite in place.
    """
    if not os.path.isdir(path):
        return True
    ok = True
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except Exception:  # noqa: BLE001 - 删不掉就跳过
            ok = False
    try:
        os.rmdir(path)
    except OSError:
        ok = False
    return ok



def main() -> int:
    # --- 1. 清理 ---
    # build/ 是纯中间产物，正常总能删；dist/ 删不掉也没关系，下面会就地覆盖。
    for d in ("build", "dist"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            if _purge(p):
                print(f"[clean] {d}/", flush=True)
            else:
                print(f"[warn] {d}/ 未能完全清空，将就地覆盖", flush=True)

    # --- 2. 构建 ---
    t0 = time.time()
    # 不加 --clean：它会调 shutil.rmtree 清缓存，在本环境会被 safe-delete 拦下
    # 而整个构建失败。缓存我们自己已经清过了。
    # No --clean: it wipes the cache via shutil.rmtree, which the environment's
    # safe-delete shim refuses.  We already purged build/ ourselves.
    rc = run(sys.executable, "-m", "PyInstaller", "--noconfirm", SPEC)
    if rc != 0:
        print(f"\n[FAIL] PyInstaller 返回码 {rc}", flush=True)
        return rc
    print(f"\n[build] 用时 {time.time() - t0:.0f}s", flush=True)

    # --- 2.5 删掉 build/ 中间产物 ---
    # 关键：build\utopet\ 里也躺着一个同名的 Utopet.exe，但它旁边的 _internal
    # 是**空的**（真正的运行库在 COLLECT 阶段才被搬进 dist）。双击那个 exe 只会
    # 报 "Failed to load Python DLL ...\build\utopet\_internal\python313.dll"，
    # 非常容易让人以为是打包失败。所以构建完直接删掉，只留 dist 一个入口。
    #
    # Critical: build\<name>\Utopet.exe is NOT runnable -- its sibling _internal
    # is empty, so it dies with "Failed to load Python DLL".  Deleting build/
    # leaves dist\ as the single obvious entry point.
    build_dir = os.path.join(ROOT, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
        print("[clean] build/ 已删除（其中的 exe 不可运行，避免误点）", flush=True)

    # --- 3. 角色包放到 exe 旁边 ---
    src_chars = os.path.join(ROOT, "characters")
    dst_chars = os.path.join(DIST, "characters")
    if os.path.isdir(src_chars):
        shutil.copytree(src_chars, dst_chars, dirs_exist_ok=True)
        n = len([d for d in os.listdir(dst_chars) if not d.startswith((".", "__"))])
        print(f"[chars] characters/ -> {n} 个角色已复制到 exe 旁边", flush=True)
    else:
        print("[WARN] 源码 characters/ 不存在，产物启动后没有角色", flush=True)

    # settings 持久化目录，避免首次运行时目录不存在
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)

    # --- 4. 体积清单 + 完整性自检 ---
    exe = os.path.join(DIST, "Utopet.exe")
    print("\n" + "=" * 60, flush=True)
    if os.path.exists(exe):
        print(f"  入口      {exe}")
        print(f"  exe       {human(os.path.getsize(exe))}")
    total = dir_size(DIST)
    nfiles = sum(len(f) for _, _, f in os.walk(DIST))
    print(f"  整包      {human(total)}   ({DIST})")
    print(f"  文件数    {nfiles}")
    print("=" * 60, flush=True)

    # 自检：运行库必须真的搬过来了。少了 python3xx.dll 的话，双击会报
    # "Failed to load Python DLL" —— 与其让用户去猜，不如在这里就喊出来。
    # Self-check: the runtime must actually be there.  A missing python3xx.dll
    # is THE classic "build succeeded but exe won't start" trap.
    problems = []
    if not os.path.exists(exe):
        problems.append("Utopet.exe 不存在")
    internal = os.path.join(DIST, "_internal")
    if not os.path.isdir(internal):
        problems.append("_internal 目录缺失")
    else:
        if not glob.glob(os.path.join(internal, "python3*.dll")):
            problems.append("_internal 里没有 python3*.dll（运行库没搬过来）")
        # PyInstaller 把 PySide6 的运行时收在 _internal/PySide6\ 下，不是根目录
        # PySide6's runtime lives under _internal/PySide6\, not the root
        if not glob.glob(os.path.join(internal, "**", "Qt6Core.dll"), recursive=True):
            problems.append("找不到 Qt6Core.dll（Qt 运行库没打进去）")
        if not os.path.isdir(os.path.join(internal, "shimeji", "locales")):
            problems.append("语言包没打进去")
        if not os.path.isdir(os.path.join(internal, "shimeji", "assets")):
            problems.append("Logo 资源没打进去")
    if not os.path.isdir(dst_chars):
        problems.append("characters/ 没复制到 exe 旁边（程序会没有角色可用）")
    if problems:
        print("\n[自检失败 / SELF-CHECK FAILED]", flush=True)
        for p in problems:
            print("  x", p, flush=True)
        return 1
    print("[自检] 运行库完整 / runtime looks complete", flush=True)

    print(f"\n完成。双击这个文件（只有它能跑）:\n  {exe}", flush=True)
    print("注意：build/ 目录已删除，里面那个同名 exe 是不可运行的中间产物。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
