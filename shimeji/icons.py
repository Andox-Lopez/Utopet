# -*- coding: utf-8 -*-
"""
程序图标 / Application icons
==============================================================================
三个文件的分工（**手工维护，别搞混**）—— the three files and what each is for:

* `logo.png`  512×512 **唯一的手绘源文件**，保留圆角。软件图标本体：窗口图标、
  任务栏、关于页、面板里的 Logo、exe 图标都由它派生。
  The single hand-made master, rounded corners kept.  It is *the* software
  icon: window icon, taskbar, About page, the logo in the panel, and the
  source every other icon is derived from.

* `logo.ico`  **系统托盘图标**，方角。托盘在 100% 缩放下只有 16×16 —— 圆角那两圈
  透明像素等于白吃掉 1/4 面积，所以单独存一份**方角**、覆盖 16…64 的多尺寸 ico
  （小尺寸额外补了锐化）。
  The **system-tray icon**, with square corners.  The tray is only 16x16 at
  100% scaling, so the transparent corner pixels would eat a quarter of the
  area; hence a separate *squared-off* multi-size ICO with extra sharpening on
  the small frames.

* `app.ico`   **exe / 安装包图标**，保留圆角。Windows 资源管理器、任务栏 exe
  按钮、卸载程序列表和 Inno Setup 都只认 .ico，且需要 256px 这种大尺寸。
  The **exe / installer icon**, rounded corners kept.  Explorer, the taskbar
  button, the Add-Remove list and Inno Setup only accept .ico and want large
  frames (256px).

改主图后重跑 `python tools/make_icons.py` 重新派生另外两个。
After editing the master, run `python tools/make_icons.py` to re-derive both.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

__all__ = [
    "ASSETS_DIR", "LOGO_PNG", "LOGO_ICO", "APP_ICO",
    "logo_path", "app_icon", "tray_icon", "logo_pixmap",
]

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO_PNG = os.path.join(ASSETS_DIR, "logo.png")
LOGO_ICO = os.path.join(ASSETS_DIR, "logo.ico")
APP_ICO = os.path.join(ASSETS_DIR, "app.ico")

_icon_cache: dict[str, QIcon] = {}


def logo_path() -> str:
    """返回存在的图标文件路径 / Path of an existing icon file (ico preferred)."""
    if os.path.exists(LOGO_ICO):
        return LOGO_ICO
    return LOGO_PNG


def _load(key: str, *, png: str, ico: str) -> QIcon:
    """
    按 ico → png 顺序找一份能解码的图标 / Load the first decodable icon.

    ico 优先是因为它自带多尺寸，Qt 会按需挑帧；png 只是兜底。
    The ICO comes first because it carries multiple frames for Qt to pick from;
    the PNG is only a fallback.

    参数是**关键字参数**：两个都是「图片路径」，位置传参很容易把 ico 和 png
    传反 —— 传反了不会报错，只是静默回退到另一张图，图标看着「有」，其实用错了。
    Keyword-only on purpose: both arguments are image paths, so positional
    arguments invite a silent swap -- and a swap does not raise, it just
    quietly falls back to the other image.
    """
    if key in _icon_cache:
        return _icon_cache[key]
    icon = QIcon()
    if os.path.exists(ico):
        icon = QIcon(ico)
    if icon.isNull() and os.path.exists(png):
        icon = QIcon(png)
    _icon_cache[key] = icon
    return icon


def app_icon() -> QIcon:
    """
    软件图标（窗口 / 任务栏 / 关于页 / exe），带缓存。
    The software icon (window / taskbar / About / exe), cached.

    优先 `logo.png` 主图 —— 512px 源带 alpha，Qt 缩放任何尺寸都干净，
    圆角在任务栏和窗口标题栏上也更好看。
    Prefers the 512px `logo.png` master; with alpha it scales cleanly to any
    size, and the rounded corners look better on a title bar.
    """
    return _load("app", png=LOGO_PNG, ico=APP_ICO)


def tray_icon() -> QIcon:
    """
    系统托盘图标，带缓存。/ The system-tray icon, cached.

    这里**必须**用 `logo.ico` 而不是主图：托盘只有 16×16，主图缩下来会糊成一团，
    而且方角版本能省下圆角那两圈透明像素。
    Deliberately `logo.ico`, not the master PNG: the tray is 16x16, a
    downscaled 512px master turns to mush, and the squared-off frames reclaim
    the pixels the rounded corners would waste.
    """
    return _load("tray", png=LOGO_PNG, ico=LOGO_ICO)


def logo_pixmap(size: int = 48) -> QPixmap:
    """按给定像素尺寸取 Logo 图 / Grab the logo scaled to `size` pixels."""
    pm = QPixmap(LOGO_PNG)
    if pm.isNull() and os.path.exists(LOGO_ICO):
        pm = QPixmap(LOGO_ICO)
    if pm.isNull():
        return pm
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
