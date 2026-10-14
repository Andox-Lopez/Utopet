# -*- coding: utf-8 -*-
"""
角色包导入 / 导出 / 描述文件增补
==============================================================================
原版 shimeji 的角色包有两种布局，**两种都要认**：

    <角色名>/
    ├── conf/                     开发用描述文件（原版角色包的必备件）
    │   ├── Actions.xml           动作定义
    │   ├── Behavior.xml          行为定义
    │   └── Mascot.xsd            配置的 schema
    └── img/                      序列帧
        └── shime1.png ...

    <角色名>/shime1.png ...       原版 1.0.0 就是这个布局：PNG 直接放包根

The original shimeji ships character packs in two layouts and both must work:
a `img/` sub-folder, or the PNGs sitting directly in the pack root (which is
what the original 1.0.0 build does).

三件事 / three jobs
------------------------------------------------------------------------------
* :func:`import_pack`    把 zip / 目录搬进 ``characters\\``
* :func:`export_pack`    把一个角色打成 zip（可分享给别人或丢回原版 shimeji）
* :func:`supplement_conf` 补齐缺失的**原版开发描述文件**

第三条是针对很常见的「半成品角色包」：网上下载的包经常只带 ``img/``，
作者把 ``conf/`` 里的描述文件删掉以求省事（体积小、也没改过），
拿原版跑会直接报错。导入时自动从内置的原版描述文件补上，
用户不需要自己去翻文档找这三个文件是什么。

The third point targets the very common "half-finished pack": packs downloaded
from the internet frequently ship only ``img/`` with the ``conf/`` description
files stripped (smaller, and the author never edited them).  The original
shimeji refuses to start on those.  We silently fill them in from the built-in
originals instead of making the user go find out what those three files are.

安全 / safety
------------------------------------------------------------------------------
解压 zip 一律做 **zip-slip 防护**（拒绝绝对路径、``..``、跨盘符）并限制条目数
与总解压体积 —— 一个恶意/损坏的压缩包不该把文件写到 characters\\ 之外，
也不该把磁盘塞满。
Zip extraction always guards against zip-slip (absolute paths, ``..``, other
drive letters) and caps the entry count and total unpacked size: a hostile or
corrupt archive must not write outside ``characters\\`` nor fill the disk.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field

from .settings import CHARACTERS_DIR, RESOURCE_DIR

__all__ = [
    "REQUIRED_CONF", "SUPPORTED_ARCHIVES",
    "PackReport", "default_conf_dir", "is_character_dir", "find_pack_root",
    "safe_name", "supplement_conf", "import_pack", "export_pack",
    "is_supported_source",
]

#: 一个角色包必须有的**开发描述文件**（原版 shimeji 同款）。
#: The development description files every character pack needs — the same set
#: the original shimeji requires.
REQUIRED_CONF = ("Actions.xml", "Behavior.xml", "Mascot.xsd")

#: 支持的压缩包后缀 / archive extensions we can read.
SUPPORTED_ARCHIVES = (".zip",)

#: 单张序列帧的最大边长（像素）。原版素材是 128×128 级别，
#: 给 64 倍余量足够夸张了，主要是拦住「拿 4K 图片当角色」这种事。
#: Sanity cap for a single frame; the original art is ~128 px, so 8192 is
#: already absurd and only exists to reject "4K wallpaper as a mascot".
_MAX_IMAGE_PIXELS = 8192

#: 解压防护上限 / extraction guards.
_MAX_ENTRIES = 20000
_MAX_TOTAL_BYTES = 512 * 1024 * 1024

#: Windows 保留文件名 / Windows reserved device names.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

#: 生成的角色目录名里不允许出现的字符 / characters a generated folder name may not contain.
_ILLEGAL = set('<>:"/\\|?*') | {chr(c) for c in range(32)}


@dataclass
class PackReport:
    """一次导入/导出/增补的结果 / The outcome of one import, export or supplement."""

    ok: bool = False
    action: str = ""                 # import / export / supplement
    name: str = ""                   # 角色名（导入/导出时）
    path: str = ""                   # 目标或来源路径 / target or source path
    added_conf: list[str] = field(default_factory=list)
    #: 目标已存在、于是换了个名字 / set when the target existed and we renamed.
    renamed_from: str = ""
    images: int = 0
    error: str = ""

    @property
    def summary(self) -> str:
        """给日志用的一行摘要 / one-line summary for the log."""
        if not self.ok:
            return f"{self.action} failed: {self.error}"
        bits = [f"{self.action} {self.name}"]
        if self.images:
            bits.append(f"{self.images} frames")
        if self.renamed_from:
            bits.append(f"renamed from {self.renamed_from}")
        if self.added_conf:
            bits.append("conf +" + ",".join(self.added_conf))
        return " / ".join(bits)


# ---------------------------------------------------------------------------
# 路径与校验 / paths & validation
# ---------------------------------------------------------------------------
def default_conf_dir() -> str:
    """内置的原版开发描述文件所在目录 / Where the built-in originals live.

    打包后这些文件在 `_internal\\shimeji\\assets\\conf_defaults\\conf`，
    `shimeji.spec` 已经把整个 `shimeji/assets` 塞进 datas，所以这里不用额外
    声明；**改目录结构时必须同时改 spec**，否则打包版会找不到而静默补不上。
    In a frozen build these sit inside `_internal`; `shimeji.spec` already ships
    the whole `shimeji/assets` tree, so nothing extra is needed -- but moving
    this folder means editing the spec too, or the frozen build silently fails
    to supplement.
    """
    return os.path.join(RESOURCE_DIR, "assets", "conf_defaults", "conf")


def _image_root(path: str) -> str | None:
    """`path` 自己是不是一个「图片根」/ Is `path` itself an image root?

    返回真实放 PNG 的目录，认两种布局：`path/img/shime1.png` 和 `path/shime1.png`。
    Returns the folder that really holds the PNGs, accepting both layouts.
    """
    if os.path.exists(os.path.join(path, "img", "shime1.png")):
        return os.path.join(path, "img")
    if os.path.exists(os.path.join(path, "shime1.png")):
        return path
    return None


def is_character_dir(path: str) -> bool:
    """`path` 能不能直接当角色包用 / Can `path` serve as a character pack?"""
    return _image_root(path) is not None


def find_pack_root(path: str, max_depth: int = 3) -> str | None:
    """
    在解出来的目录树里找**角色包根** / Locate the pack root inside a tree.

    需要它是因为压缩包里的层级千奇百怪：有的直接是 ``img/conf``，
    有的外面还套一层 ``Miku_v2/``，还有的套了 ``新建文件夹/Miku``。
    这里按「层数最少优先」找第一个能当角色包用的目录。

    Archives nest arbitrarily (``img/conf`` at the top, or wrapped in
    ``Miku_v2/``, or in a generic ``新建文件夹/``).  We search breadth-first and
    take the shallowest directory that qualifies, so the wrapper is peeled off
    but the pack's own structure is preserved.
    """
    if not os.path.isdir(path):
        return None
    if is_character_dir(path):
        return path
    # 广度优先：层数最少的最可能是包根 / BFS: the shallowest hit is the root
    frontier = [(path, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        try:
            names = sorted(os.listdir(current))
        except OSError:
            continue
        for name in names:
            if name in ("__MACOSX", ".git", "cache", "__pycache__"):
                continue
            sub = os.path.join(current, name)
            if not os.path.isdir(sub):
                continue
            if is_character_dir(sub):
                return sub
            frontier.append((sub, depth + 1))
    return None


def count_frames(char_dir: str) -> int:
    """数一数这个角色有几张序列帧 / Count the frames a pack carries."""
    root = _image_root(char_dir)
    if root is None:
        return 0
    try:
        return sum(1 for n in os.listdir(root)
                   if n.lower().endswith(".png") and n.lower().startswith("shime"))
    except OSError:
        return 0


def safe_name(name: str, fallback: str = "character") -> str:
    """
    把任意字符串变成安全的目录名 / Turn anything into a safe folder name.

    角色名会变成 `characters\\<名>` 的目录名，所以必须挡住路径分隔符和
    Windows 保留名 —— 否则一个叫 ``../..`` 的压缩包就能写到任意位置。
    The pack name becomes a folder under `characters\\`, so path separators and
    Windows device names must go: an archive named ``../..`` would otherwise
    write anywhere.
    """
    cleaned = "".join("_" if ch in _ILLEGAL else ch for ch in (name or ""))
    cleaned = cleaned.replace("..", "_").strip().strip(".")
    cleaned = " ".join(cleaned.split())
    if not cleaned or cleaned in (".", ".."):
        cleaned = fallback
    if cleaned.upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned[:80]


def _unique_dir(parent: str, name: str) -> str:
    """不覆盖已有目录：`名`、`名_2`、`名_3`… / Never clobber: name, name_2, name_3…"""
    candidate = os.path.join(parent, name)
    if not os.path.exists(candidate):
        return candidate
    for i in range(2, 1000):
        candidate = os.path.join(parent, f"{name}_{i}")
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(parent, f"{name}_{os.getpid()}")


# ---------------------------------------------------------------------------
# 描述文件增补 / supplementing the description files
# ---------------------------------------------------------------------------
def supplement_conf(char_dir: str) -> list[str]:
    """
    补齐缺失的**原版开发描述文件** / Fill in missing original description files.

    只补**缺的**，已有的绝不覆盖 —— 作者改过的 Behavior.xml 是他的劳动成果，
    被我们悄悄换回默认版就等于把他的调整抹掉了。
    Only *missing* files are added; existing ones are never touched.  A pack
    author's edited Behavior.xml is his work — silently reverting it to the
    default would erase his tuning.

    返回被补上的文件名列表 / returns the file names that were added.
    """
    src = default_conf_dir()
    if not os.path.isdir(src):
        return []
    conf = os.path.join(char_dir, "conf")
    added: list[str] = []
    try:
        os.makedirs(conf, exist_ok=True)
    except OSError:
        return []
    for name in REQUIRED_CONF:
        target = os.path.join(conf, name)
        if os.path.exists(target):
            continue
        origin = os.path.join(src, name)
        if not os.path.exists(origin):
            continue
        try:
            shutil.copy2(origin, target)
            added.append(name)
        except OSError:
            continue
    return added


# ---------------------------------------------------------------------------
# 导入 / export
# ---------------------------------------------------------------------------
def is_supported_source(path: str) -> bool:
    """拖进来的东西我们能处理吗 / Can we handle what was dropped?"""
    if os.path.isdir(path):
        return True
    return os.path.isfile(path) and path.lower().endswith(SUPPORTED_ARCHIVES)


def _check_zip_member(info: zipfile.ZipInfo, dest: str) -> bool:
    """这个 zip 条目安全吗 / Is this archive entry safe to extract?"""
    name = info.filename.replace("\\", "/")
    if not name or name.endswith("/"):
        return True                      # 目录条目 / a directory entry
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return False                     # 绝对路径 / 盘符 / absolute or drive-qualified
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return False                     # 往上跳 / tries to climb out
    target = os.path.abspath(os.path.join(dest, *parts))
    root = os.path.abspath(dest)
    return target == root or target.startswith(root + os.sep)


def _extract_zip(src: str, dest: str) -> None:
    """
    解压（带 zip-slip 防护与体积上限）/ Extract, guarded.

    失败抛 `ValueError`，调用方转成用户能看懂的提示。
    Raises `ValueError`; the caller turns it into a readable message.
    """
    with zipfile.ZipFile(src) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise ValueError(f"too many entries ({len(infos)})")
        total = sum(i.file_size for i in infos)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("archive too large")
        bad = [i.filename for i in infos if not _check_zip_member(i, dest)]
        if bad:
            raise ValueError(f"unsafe path in archive: {bad[0]}")
        zf.extractall(dest)


def _copy_tree(src: str, dest: str) -> None:
    """复制角色包（跳过缓存）/ Copy a pack, skipping caches."""
    shutil.copytree(
        src, dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cache"),
        dirs_exist_ok=True,
    )


def _name_from_source(src: str) -> str:
    """从来源推一个角色名 / Derive a pack name from the source."""
    if os.path.isdir(src):
        return os.path.basename(os.path.normpath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    # 常见命名：Miku_v2、miku-1.0 → 保留原样，只做安全化
    return stem


def import_pack(src: str, characters_dir: str | None = None,
                name: str | None = None) -> PackReport:
    """
    导入一个角色包 / Import one character pack.

    `src` 可以是 **zip 文件**，也可以是**目录**（从资源管理器直接拖进来就是它）。
    目标目录已存在时**换名而不是覆盖** —— 覆盖会毁掉用户原来那份角色，
    而角色包里的 PNG 是没法「撤销」的。要覆盖请自己先删掉再导入。

    `src` may be a zip file *or* a directory (dragging a folder in gives you
    that).  If the target name already exists we **rename instead of
    overwriting**: the PNGs in a pack cannot be undone, so clobbering a pack is
    irreversible.  Delete first if you really mean to replace.
    """
    report = PackReport(action="import", path=src)
    chars = characters_dir or CHARACTERS_DIR
    if not src or not os.path.exists(src):
        report.error = "not found"
        return report
    if not is_supported_source(src):
        report.error = "unsupported file type"
        return report
    if not name:
        name = _name_from_source(src)

    tmp = None
    try:
        if os.path.isdir(src):
            root = find_pack_root(src)
            if root is None:
                report.error = "no shime1.png found"
                return report
            source_root = root
        else:
            tmp = tempfile.mkdtemp(prefix="utopet_pack_")
            try:
                _extract_zip(src, tmp)
            except (zipfile.BadZipFile, ValueError, OSError) as e:
                report.error = f"bad archive: {e}"
                return report
            root = find_pack_root(tmp)
            if root is None:
                report.error = "no shime1.png found"
                return report
            source_root = root

        clean = safe_name(name)
        try:
            os.makedirs(chars, exist_ok=True)
        except OSError as e:
            report.error = f"cannot use characters folder: {e}"
            return report
        target = _unique_dir(chars, clean)
        if os.path.basename(target) != clean:
            report.renamed_from = clean
        report.name = os.path.basename(target)

        _copy_tree(source_root, target)
        report.added_conf = supplement_conf(target)
        report.images = count_frames(target)
        report.path = target
        report.ok = True
    except (OSError, shutil.Error) as e:
        report.error = str(e)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return report


def export_pack(char_dir: str, dest_zip: str,
                supplement: bool = False) -> PackReport:
    """
    把一个角色打成 zip / Pack one character up as a zip.

    导出的是 `characters\\<角色>\\` **整棵子树**（`img/` + `conf/` + 作者自带的
    其它文件），解压出来就是原版 shimeji 认识的角色包结构 —— 所以导出的东西
    既能给别的 Utopet 用，也能直接丢回原版 Shimeji。

    The whole subtree is exported (`img/` + `conf/` + anything else the author
    put there), so the result is a pack the original shimeji understands as
    well as this program.

    `supplement=True` 时**先在临时副本上补齐描述文件再打包**，避免导出物
    缺 conf 而在别处打不开；用户自己的目录一个字节都不改。
    With `supplement=True` the description files are filled in **on a temporary
    copy** before packing, so the export always opens elsewhere while the user's
    own folder stays byte-for-byte untouched.
    """
    report = PackReport(action="export", path=dest_zip)
    if not os.path.isdir(char_dir):
        report.error = "not a folder"
        return report
    name = safe_name(os.path.basename(os.path.normpath(char_dir)))
    report.name = name
    tmp = None
    try:
        source = char_dir
        if supplement:
            tmp = tempfile.mkdtemp(prefix="utopet_export_")
            staged = os.path.join(tmp, name)
            _copy_tree(char_dir, staged)
            supplement_conf(staged)
            source = staged
        parent = os.path.dirname(os.path.abspath(dest_zip))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, dirs, files in os.walk(source):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "cache")]
                for fn in files:
                    if fn.endswith((".pyc", ".log")):
                        continue
                    full = os.path.join(base, fn)
                    rel = os.path.relpath(full, source)
                    zf.write(full, os.path.join(name, rel))
        report.images = count_frames(char_dir)
        report.ok = True
    except (OSError, zipfile.BadZipFile) as e:
        report.error = str(e)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return report
