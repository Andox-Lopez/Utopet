# -*- coding: utf-8 -*-
"""
从主图派生图标 / Derive the icon files from the master artwork
==============================================================================
`shimeji/assets/logo.png`（512×512）是**唯一的手绘源文件**，本脚本只做缩放，
不重新绘制 —— 以前 `make_logo.py` 用 PIL 几何图元程序化画的那版已经是历史，
不要再用它覆盖主图。

`shimeji/assets/logo.png` (512x512) is the single hand-made master.  This script
only *rescales* it; it never redraws.  (The old procedural artwork from
`make_logo.py` is history -- do not let it overwrite the master.)

圆角规则 / The rounded-corner rule
------------------------------------------------------------------------------
**20px 以下去圆角，以上保留圆角。** 20px 以下（实际只有 16px 那档）图标小到
圆角那两圈透明像素会白白吃掉约 1/4 面积，把猫脸压得更小，索性填成方角；
再往上圆角是外观的一部分（头像形状），去掉反而难看。

**Square off the corners below 20px, keep them from 20px up.**  Below 20px (in
practice only the 16px frame) the transparent corner pixels would eat about a
quarter of the area and shrink the face further, so they get flooded with the
neighbouring colour.  At 20px and above the rounded corners are part of the
look (it reads as a head-shaped avatar), so they stay.

产出 / Outputs
------------------------------------------------------------------------------
    logo.png   →  软件图标本体：窗口图标、任务栏、关于页、面板 Logo（保留圆角）
                  the software icon: window, taskbar, About, panel (rounded)
    logo.ico   →  系统托盘图标 16/20/22/24/32/40/48/64（仅 16 去圆角）
                  the system-tray icon (only the 16px frame is squared off)
    app.ico    →  exe / 安装包图标 16/24/…/256（Windows shell 与 Inno 只吃 ico）
                  the exe / installer icon (Windows shell and Inno take .ico only)

为什么托盘要单独一份 ico / Why the tray gets its own .ico
------------------------------------------------------------------------------
托盘图标在 100% 缩放下只有 16×20，图标直接从 512px 主图缩过来细节会糊；
而 exe 图标会被资源管理器缩到 32/48 展示，卸载列表里还会用到 256。
一份 ico 同时喂两处，小尺寸帧必然被大尺寸需求拖累，反之亦然。

Pillow ICO 编码器的坑 / A Pillow ICO gotcha worth remembering
------------------------------------------------------------------------------
`frames[0].save(ico, sizes=[...], append_images=frames[1:])` 是**错的**：
编码器以 `im.size`（即 frames[0]）为上限，`size[0] > width` 的尺寸会被静默丢弃。
旧脚本 frames[0] 恰好是 16×16，于是 10 个尺寸只剩 1 个 —— 图标一直是糊的。
更根本的是，`sizes=` 意味着**所有帧都由 Pillow 从同一张基准图降采样**，
没法「让 16px 去圆角、32px 保留圆角」。所以下面自己拼 ICO 容器，逐帧处理。
`frames[0].save(...)` is wrong twice over: the encoder drops any size larger
than `im.size` (so the old 10-size ICO collapsed to a single 16px frame), and
`sizes=` resamples *every* frame from one base image, which makes per-frame
treatment impossible.  Hence the hand-assembled ICO container below.
"""

from __future__ import annotations

import io
import os
import struct

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "shimeji", "assets")
MASTER = os.path.join(ASSETS, "logo.png")
TRAY_ICO = os.path.join(ASSETS, "logo.ico")
APP_ICO = os.path.join(ASSETS, "app.ico")

# 托盘：覆盖 100% / 125% / 150% / 200% 缩放下 Windows 会挑的尺寸
TRAY_SIZES = (16, 20, 22, 24, 32, 40, 48, 64)

# exe / 安装包：资源管理器大图标（32）、任务栏（16~48，200% 缩放下 96）、
# 卸载程序列表。**上限刻意停在 96，不放 128 / 256** —— 见下方长注释。
# exe / installer frames.  **Capped at 96 on purpose -- no 128 / 256.**
APP_SIZES = (16, 24, 32, 48, 64, 96)

# 缩到这个尺寸以下就补一点锐度，抵消 LANCZOS 降采样的糊
SHARPEN_BELOW = 32

# ICO 目录里的尺寸字节超过 127 就会让 PyInstaller 解析出负数，见 _assert_pyinstaller_safe()
MAX_SAFE_DIM = 127

# 严格小于这个尺寸才去圆角 / strictly below this size the corners get squared
SQUARE_BELOW = 20


def _frame(master: Image.Image, size: int, *, crop: bool = False) -> Image.Image:
    """
    缩出单帧，并按尺寸决定是否去圆角 / One frame, squared off if small enough.

    顺序是 **crop → square_off → resize → 锐化**，每一步都不能换：
    1. 先裁掉主图四周的透明画布留白（仅托盘），否则降采样会把留白和徽章边缘
       混色，16px 角落实测 alpha=172，根本不方；
    2. 再去圆角 —— 反过来做的话，512px 的圆角缩到 20px 只剩 1.5px，
       LANCZOS 三抽头插值会直接抹平，`square_off()` 找不到透明像素，等于空转；
    3. 最后缩放 + 小尺寸锐化，抵消降采样的糊。

    Order matters: crop -> square off -> resize -> sharpen.
    1. Crop the master's transparent canvas margin first (tray only), else
       downsampling blends it into the badge and the 16px corner comes out
       half-transparent (measured alpha=172) instead of square.
    2. Then square off -- the other way round, the ~40px corner radius is down
       to ~1.5px at 20px, LANCZOS flattens it, and square_off() finds nothing
       left to flood.
    3. Resize, then sharpen the small frames to counteract the softness.
    """
    if crop:
        master = _crop_transparent_border(master)
    if size < SQUARE_BELOW:
        master = square_off(master)
    im = master.resize((size, size), Image.LANCZOS)
    if size < SHARPEN_BELOW:
        radius = 0.6 if size <= 20 else 0.4
        im = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=140, threshold=2))
    return im


def square_off(img: Image.Image) -> Image.Image:
    """
    抹掉圆角：把透明的角填成旁边的颜色，变成方角。
    Square off the rounded corners by flooding them with the neighbouring colour.

    做法是**逐行把最外侧不透明像素的颜色向左右延伸**，而不是拿一个固定色去填 ——
    徽章本身有上下渐变（顶 #3A3633 → 底 #2E2A28），填固定色会在边缘留下一圈色差。
    Extend the outermost opaque pixel of each *row* outwards instead of flooding a
    flat colour: the badge has a vertical gradient (#3A3633 top -> #2E2A28 bottom),
    and a flat fill would leave a visible ring around the badge.
    """
    w, h = img.size
    src = img.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        xs = [x for x in range(w) if src[x, y][3] > 0]
        if not xs:
            continue
        left, right = xs[0], xs[-1]
        lc, rc = src[left, y], src[right, y]
        for x in range(w):
            if x < left:
                dst[x, y] = lc
            elif x > right:
                dst[x, y] = rc
            else:
                dst[x, y] = src[x, y]
    return out


def _crop_transparent_border(img: Image.Image) -> Image.Image:
    """
    裁掉四周完全透明的边距 / Crop the fully-transparent margin away.

    必须先裁再 square_off：主图四周有约 10px 的透明留白（512px 中的 2%），
    那是**画布留白**不是圆角。不裁的话 square_off 会把这圈留白也填成方角，
    结果托盘图标四周多出一圈实色边框；而留着它，降采样又会把这圈留白和
    徽章边缘混色，16px 的角落就变成半透明的（实测 alpha=172），根本不方。

    Crop before squaring off.  The master has ~10px of transparent padding (2% of
    512px) that is *canvas margin*, not a corner.  Left in place, square_off
    floods that margin too and the tray icon grows a solid border; kept in place,
    downsampling blends it into the badge and the 16px corner comes out
    half-transparent (measured alpha=172) instead of square.
    """
    bbox = img.split()[3].getbbox()          # 非零 alpha 的外接矩形
    if not bbox:
        return img
    # getbbox 会把「几乎全透明」的抗锯齿像素算进来，所以往内收 1px 余量
    l, t, r, b = bbox
    if r - l > 4 and b - t > 4:
        img = img.crop((l + 1, t + 1, r - 1, b - 1))
    return img


def _png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _assemble_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """
    拼一个 ICO 容器 / Assemble an ICO container from (size, png-bytes) pairs.

    为什么自己拼 / Why hand-assemble: we need per-frame corner treatment, which
    Pillow's `sizes=` cannot express.  Frame data is PNG-compressed, which
    Windows Vista+ (our floor is Windows 10) and Qt both read fine.
    """
    count = len(frames)
    offset = 6 + 16 * count
    entries, blobs = b"", b""
    for size, blob in frames:
        dim = 0 if size >= 256 else size          # 0 means 256 in the ICO dir
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return struct.pack("<HHH", 0, 1, count) + entries + blobs


def _assert_pyinstaller_safe(path: str, sizes: tuple[int, ...]) -> None:
    """
    拦住会让 PyInstaller 把 exe 图标解析坏的尺寸 / Reject sizes that break the exe icon.

    ⚠️ **为什么 exe 图标不能有 ≥128 的帧** ⚠️
    ICO 目录里的 `bWidth` / `bHeight` 是**单字节**，按规范「0 表示 256」。
    但 PyInstaller 的解析器用**有符号** char（`PyInstaller/utils/win32/icon.py`
    里的 `ICONDIRENTRY._format_ = "bbbbhhii"`），于是：
        128 → 0x80 → 读成 **-128**
        256 → 写成 0 → 读成 0（这个没问题）
    负宽度被原样搬进 `GRPICONDIR`，资源管理器解析整个图标组失败，
    结果 exe 只剩零星几个尺寸可用 —— 实测 `ExtractIconEx` 读出来是
    **32x16 / 16x8**，宽高比全错，图标彻底变形。

    所以 exe / 安装包图标一律**停在 96px**。这够用：任务栏最高 200% 缩放
    也就 96px，资源管理器大图标视图是 32px，卸载列表 32px。
    托盘那份不受影响 —— 它是 Qt 自己读的，Qt 解析 ico 没有这个 bug。

    PyInstaller parses the ICO directory with **signed** chars
    (`ICONDIRENTRY._format_ = "bbbbhhii"`), so a 128px frame (0x80) reads back
    as **-128**.  That negative width is copied verbatim into `GRPICONDIR`,
    Explorer fails on the whole group, and the exe ends up with only a few
    usable frames -- measured via `ExtractIconEx` as **32x16 / 16x8**, badly
    distorted.  Hence the 96px cap for exe/installer.  Plenty in practice: the
    taskbar tops out at 96px (200% scaling), Explorer uses 32px.  The tray ICO
    is unaffected -- Qt reads it and has no such bug.
    """
    too_big = sorted(s for s in sizes if s > MAX_SAFE_DIM)
    if too_big:
        raise SystemExit(
            f"{os.path.basename(path)}: 尺寸 {too_big} 超过 {MAX_SAFE_DIM}，"
            f"PyInstaller 会把 bWidth 读成负数、导致 exe 图标变形。\n"
            f"Sizes {too_big} exceed {MAX_SAFE_DIM}: PyInstaller would read "
            f"bWidth as a negative number and distort the exe icon.\n"
            f"把尺寸降到 {MAX_SAFE_DIM} 及以下，或用 app.ico 之外的方案。"
        )


def _write_ico(master: Image.Image, path: str, sizes: tuple[int, ...],
               *, crop: bool = False) -> None:
    """写多尺寸 ico（逐帧处理）/ Write a multi-size ICO, frame by frame."""
    _assert_pyinstaller_safe(path, sizes)
    frames = [(n, _png_bytes(_frame(master, n, crop=crop))) for n in sorted(sizes)]
    data = _assemble_ico(frames)
    with open(path, "wb") as fh:
        fh.write(data)
    written = read_ico_sizes(path)
    missing = sorted(set(sizes) - written)
    squared = [n for n in sorted(sizes) if n < SQUARE_BELOW]
    print(f"  {os.path.basename(path):<12} {len(written)} 个尺寸 {sorted(written)}  "
          f"{len(data):,} 字节  去圆角 {squared or '无'}"
          f"{'  裁边距' if crop else ''}"
          f"{'' if not missing else '  缺尺寸 ' + str(missing)}")
    if missing:
        raise SystemExit(f"{path} 写入不完整：缺 {missing}")


def read_ico_sizes(path: str) -> set[int]:
    """读出 ico 里真实存在的尺寸 / Sizes actually present in an ICO."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"\x00\x00\x01\x00":
        return set()
    count = struct.unpack("<H", data[4:6])[0]
    out: set[int] = set()
    for i in range(count):
        out.add(data[6 + i * 16] or 256)
    return out


def main() -> None:
    if not os.path.exists(MASTER):
        raise SystemExit(f"主图不存在 / master missing: {MASTER}")
    master = Image.open(MASTER).convert("RGBA")
    print(f"主图 / master: {MASTER}  {master.size[0]}×{master.size[1]}")
    # 托盘：裁掉画布留白（16px 里每一像素都金贵）+ 仅 16px 去圆角
    # Tray: crop the canvas margin (every pixel counts at 16px), square off 16px.
    _write_ico(master, TRAY_ICO, TRAY_SIZES, crop=True)
    # exe / 安装包：保留圆角与留白，那是大尺寸，无所谓
    # exe & installer: keep the rounded corners and margin exactly as drawn.
    _write_ico(master, APP_ICO, APP_SIZES)


if __name__ == "__main__":
    main()
