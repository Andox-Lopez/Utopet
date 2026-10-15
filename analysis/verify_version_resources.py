# -*- coding: utf-8 -*-
"""校验产物里的版本号（一次性发布检查，发布前跑一遍；产物不存在时跳过）。

刻意不用 PowerShell 读版本资源：它会把 CJK 显示成乱码，还会**凭空多出一个 X**
（把 "1.0.8" 显示成 "1.0.8X"），照着它改 .iss 只会把好好的版本号改坏。
直接按字节搜最可靠：源码是 UTF-8 文本按 ASCII 搜，安装包是 PE 版本资源按
UTF-16LE 搜。

Deliberately does not use PowerShell to read version resources: it renders CJK as
mojibake *and* invents a trailing "X", so trusting it means "fixing" a version
that was never broken.  Byte-search instead.

用法：python analysis/verify_version_resources.py
"""

import glob
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimeji import __version__ as APP_VERSION  # noqa: E402


def _ver_key(path: str):
    """按**版本号**排序安装包，而不是按文件名字符串。

    ⭐ 字符串排序在 1.0.10 就坏了：'Utopet-Setup-1.0.10.exe' < '...1.0.5.exe'
    （因为 '1' < '5'），于是 `sorted(...)[-1]` 会挑中 1.0.9，把版本资源
    校验做在**错误的那个文件**上 —— 而且它还会报 FAIL，看起来像打包出了问题。
    1.0.10 是第一个会踩到的两位数修订号。
    """
    m = re.search(r"Utopet-Setup-(\d+(?:\.\d+)+)", os.path.basename(path))
    if not m:
        return (0,)
    return tuple(int(p) for p in m.group(1).split("."))


bad = 0
_setups = sorted(glob.glob(os.path.join(ROOT, "output", "Utopet-Setup-*.exe")),
                 key=_ver_key)
_dist_exe = os.path.join(ROOT, "dist", "Utopet", "Utopet.exe")

# ---- 1. 源码里的版本常量 / the version constant in the source ----
_p = os.path.join(ROOT, "shimeji", "__init__.py")
_raw = open(_p, "rb").read()
_ok = ('"%s"' % APP_VERSION).encode() in _raw
print("[%s] __init__.py 里是 %s" % ("ok  " if _ok else "FAIL", APP_VERSION))
bad += 0 if _ok else 1

# ---- 2. .iss 的 AppVersion / VersionInfoVersion ----
_iss = open(os.path.join(ROOT, "installer", "Utopet.iss"),
            encoding="utf-8").read()
_m = re.search(r'(?mi)^#define AppVersion "([^"]+)"', _iss)
_ok = bool(_m) and _m.group(1) == APP_VERSION
print("[%s] .iss 的 AppVersion = %s" % ("ok  " if _ok else "FAIL",
                                        _m.group(1) if _m else "?"))
bad += 0 if _ok else 1
# VersionInfoVersion 必须是四段数字：Windows 版本资源不认 "1.0.7-2" 这种写法，
# 而 AppVersion 可以是带后缀的 —— 两者不要共用同一个宏。
_m2 = re.search(r"(?mi)^VersionInfoVersion\s*=\s*(\S+)", _iss)
_vv = _m2.group(1) if _m2 else ""
_ok = bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", _vv))
print("[%s] VersionInfoVersion 是四段数字：%s" % ("ok  " if _ok else "FAIL", _vv))
bad += 0 if _ok else 1

# ---- 3. 安装包（产物，可能还没构建 —— 没构建就跳过，不算失败）----
# ⚠️ 必须**按版本号精确匹配当前版本**，不能取「最后一个」：output\ 里会一直
# 躺着历年的包，取最后一个等于赌它恰好是这次的。
# Match the *current* version exactly rather than taking "the last one": the
# output folder keeps every historical build, so "the last one" is a gamble.
_want_name = "Utopet-Setup-%s.exe" % APP_VERSION
_match = [p for p in _setups
          if os.path.basename(p).lower() == _want_name.lower()]
if not _setups:
    print("[skip] output\\ 里还没有安装包（先 build_release.py + ISCC）")
elif not _match:
    print("[FAIL] output\\ 里没有 %s —— 还没为当前版本打包？"
          "（找到的：%s）"
          % (_want_name,
             ", ".join(os.path.basename(p) for p in _setups) or "无"))
    bad += 1
else:
    _latest = _match[0]
    _name = os.path.basename(_latest)
    _r = open(_latest, "rb").read()
    _want = APP_VERSION
    _ok = _want.encode("utf-16-le") in _r
    print("[%s] 安装包 %s 内含版本资源 %s" % ("ok  " if _ok else "FAIL",
                                              _name, _want))
    bad += 0 if _ok else 1
    _ok = _want in _name
    print("[%s] 安装包文件名带 %s" % ("ok  " if _ok else "FAIL", _want))
    bad += 0 if _ok else 1

# ---- 4. dist exe：shimeji.spec 里 `version=None`，本来就**不写**版本资源 ----
if os.path.exists(_dist_exe):
    _r2 = open(_dist_exe, "rb").read()
    # 候选串**从当前版本倒推**，不要写死版本号：写死了就会在某次升版后
    # 悄悄漏掉新版本、还留着已经废弃的旧版本。
    _cands = []
    try:
        _maj, _min, _pat = APP_VERSION.split(".")[:3]
        for _i in range(4, 0, -1):
            _cands.append("%s.%s.%s.%d" % (_maj, _min, _pat, _i))
        _cands.append(APP_VERSION)
    except ValueError:
        _cands = [APP_VERSION]
    _hits = [v for v in _cands if v.encode("utf-16-le") in _r2]
    print("[%s] dist\\Utopet\\Utopet.exe 版本资源=%s（spec 里 version=None，"
          "符合预期）" % ("ok  " if not _hits else "warn", _hits or "none"))
    # ⚠️ dist 里可能还躺着**上一版**的产物（build_release.py 才清它）。
    # 版本资源本来就不写，所以判据只能看时间：产物早于源码改动就是过期的。
    # The dist tree may still hold the *previous* build; since no version
    # resource is written, timestamps are the only signal available.
    if os.path.exists(_p):
        _src_m = os.path.getmtime(_p)
        _exe_m = os.path.getmtime(_dist_exe)
        _stale = _exe_m < _src_m
        print("[%s] dist exe 比源码新（不是旧版残留）"
              % ("warn" if _stale else "ok  "),
              "exe %s / 源码 %s"
              % (time.strftime("%m-%d %H:%M", time.localtime(_exe_m)),
                 time.strftime("%m-%d %H:%M", time.localtime(_src_m))))
else:
    print("[skip] dist\\Utopet\\Utopet.exe 不存在（还没构建）")

print("BAD=%d" % bad)
sys.stdout.flush()
os._exit(1 if bad else 0)

