# -*- coding: utf-8 -*-
"""
国际化 / Internationalisation
==============================================================================
内置 简体中文 / English / 日本語 三套界面语言，可在设置里即时切换。

Ships with Simplified Chinese, English and Japanese UI languages, switchable at
runtime from the settings window.
"""

from __future__ import annotations

import json
import os

__all__ = ["I18n", "LANGUAGES", "tr"]

_LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

#: 可选语言 / available languages: code -> 显示名 / display label
LANGUAGES = {
    "zh_CN": "简体中文",
    "en_US": "English",
    "ja_JP": "日本語",
}


class I18n:
    """一个简单的键值翻译器 / A tiny key/value translator."""

    def __init__(self, lang: str = "zh_CN"):
        self.lang = lang if lang in LANGUAGES else "zh_CN"
        self._tables: dict[str, dict[str, str]] = {}
        self._load("zh_CN")          # 兜底表 / fallback table
        if self.lang != "zh_CN":
            self._load(self.lang)

    def _load(self, lang: str):
        path = os.path.join(_LOCALE_DIR, "%s.json" % lang)
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._tables[lang] = json.load(f)
        except (OSError, ValueError):
            self._tables[lang] = {}

    def set_language(self, lang: str):
        if lang in LANGUAGES:
            self.lang = lang
            if lang not in self._tables:
                self._load(lang)

    def t(self, key: str, default: str | None = None) -> str:
        table = self._tables.get(self.lang)
        if table and key in table:
            return table[key]
        base = self._tables.get("zh_CN")
        if base and key in base:
            return base[key]
        return default if default is not None else key

    def __call__(self, key: str, default: str | None = None) -> str:
        return self.t(key, default)


_I18N = I18n()


def get_i18n() -> I18n:
    return _I18N


def set_language(lang: str):
    _I18N.set_language(lang)


def tr(key: str, default: str | None = None) -> str:
    """全局快捷翻译 / Module-level translation shortcut."""
    return _I18N.t(key, default)
