# -*- coding: utf-8 -*-
"""
⚠️ **已废弃，请勿运行** / DEPRECATED -- do not run this
==============================================================================
本脚本会用 PIL 几何图元**重画** Logo 并覆盖 `shimeji/assets/logo.png`。
现在的主图是手工绘制的那版，构图和配色都不一样，跑这个脚本会把主图毁掉。

This script *redraws* the logo with PIL geometry and **overwrites**
`shimeji/assets/logo.png`.  The current master is hand-made and looks nothing
like this; running the script would destroy it.

要改图标？ / Looking to change the icon?
------------------------------------------------------------------------------
1. 直接编辑 `shimeji/assets/logo.png`（512×512，唯一的手绘源文件）
2. 重跑 `python tools/make_icons.py` 派生 `logo.ico`（托盘）和 `app.ico`（exe）

以下代码仅作为历史留档。
The code below is kept for historical reference only.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "shimeji", "assets")
SIZE = 512

C_BADGE = (46, 42, 40, 255)        # #2E2A28 徽章底 / badge
C_BADGE_HI = (58, 54, 51, 255)     # #3A3633 徽章高光 / badge highlight
C_CREAM = (240, 230, 210, 255)     # #F0E6D2 奶白 / cream
C_MASK = (35, 33, 31, 255)         # #23211F 面罩 / mask
C_EYE = (255, 255, 255, 255)       # 眼白 / eye white
C_BOW = (228, 87, 76, 255)         # #E4574C 红蝴蝶结 / red bow
C_BOW_DK = (186, 62, 54, 255)      # 蝴蝶结暗部 / bow shadow

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _ellipse(d, cx, cy, rx, ry, fill):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill)


def draw(size: int = SIZE) -> Image.Image:
    """绘制一枚 Logo / Draw one logo at the requested size."""
    s = size / float(SIZE)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (x * s, y * s)

    def E(cx, cy, rx, ry, fill):
        _ellipse(d, cx * s, cy * s, rx * s, ry * s, fill)

    def poly(points, fill):
        d.polygon([P(x, y) for x, y in points], fill=fill)

    # 1) 圆角方形徽章 / rounded-square badge
    d.rounded_rectangle([P(10, 10), P(502, 502)], radius=116 * s, fill=C_BADGE)
    # 顶部一道柔和高光 / a soft highlight along the top
    d.rounded_rectangle([P(10, 10), P(502, 300)], radius=116 * s, fill=C_BADGE_HI)

    # 2) 耳朵（画在头后面）/ ears, drawn behind the head
    poly([(118, 196), (150, 52), (236, 150)], C_CREAM)
    poly([(394, 196), (362, 52), (276, 150)], C_CREAM)

    # 3) 头 / head
    E(256, 288, 152, 134, C_CREAM)

    # 4) 面罩（横跨眼部的一条深色带）/ the mask band across the eyes
    d.rounded_rectangle([P(132, 246), P(380, 330)], radius=42 * s, fill=C_MASK)

    # 5) 眼睛 / eyes
    E(198, 288, 29, 33, C_EYE)
    E(314, 288, 29, 33, C_EYE)
    # 瞳孔高光偏移，让眼神活一点 / offset pupils so the gaze reads as alive
    E(204, 292, 13, 16, C_MASK)
    E(320, 292, 13, 16, C_MASK)

    # 6) 鼻子 / nose
    E(256, 356, 24, 17, C_MASK)

    # 7) 红蝴蝶结（左下，压在头上）/ red bow at the lower left, over the head
    poly([(142, 356), (78, 320), (88, 396)], C_BOW)
    poly([(142, 356), (206, 320), (196, 396)], C_BOW)
    poly([(142, 356), (78, 320), (88, 340)], C_BOW_DK)
    poly([(142, 356), (206, 320), (196, 340)], C_BOW_DK)
    E(142, 356, 19, 19, C_BOW)
    E(142, 356, 9, 9, C_BOW_DK)

    return img


def main():
    raise SystemExit(
        "make_logo.py 已废弃：它会覆盖手工绘制的主图 logo.png。\n"
        "要改图标请直接编辑 shimeji/assets/logo.png，然后跑 tools/make_icons.py。\n"
        "\n"
        "make_logo.py is deprecated: it overwrites the hand-made master logo.png.\n"
        "Edit shimeji/assets/logo.png directly, then run tools/make_icons.py."
    )


def _legacy_main():
    """历史实现，保留仅为参考 / Legacy implementation, kept for reference."""
    os.makedirs(OUT_DIR, exist_ok=True)
    master = draw(SIZE)
    png_path = os.path.join(OUT_DIR, "logo.png")
    master.save(png_path)
    print("PNG ->", png_path)

    ico_path = os.path.join(OUT_DIR, "logo.ico")
    frames = [draw(n) for n in ICO_SIZES]
    frames[0].save(ico_path, sizes=[(n, n) for n in ICO_SIZES],
                   append_images=frames[1:])
    print("ICO ->", ico_path, ICO_SIZES)


if __name__ == "__main__":
    main()
