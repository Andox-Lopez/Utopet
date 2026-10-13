# -*- coding: utf-8 -*-
"""往三语语言包里补充新键（保持原有缩进与结尾换行）。

用法：python tools/add_locale_keys.py
"""

from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, "shimeji", "locales")

NEW = {
    "zh_CN": {
        "panel.expand": "展开",
        "panel.hide_all": "收起面板（程序仍在托盘运行）",
    },
    "en_US": {
        "panel.expand": "Expand",
        "panel.hide_all": "Hide panel (app keeps running in the tray)",
    },
    "ja_JP": {
        "panel.expand": "展開",
        "panel.hide_all": "パネルを隠す（トレイで動作継続）",
    },
}


def main() -> int:
    for lang, pairs in NEW.items():
        p = os.path.join(LOCALES, f"{lang}.json")
        with io.open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        added = [k for k in pairs if k not in data]
        if not added:
            print(f"[skip] {lang}: 键已存在")
            continue
        data.update(pairs)
        # 保持 2 空格缩进 + 末尾换行，和原文件一致
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        print(f"[ok] {lang}: 新增 {added} -> 共 {len(data)} 键")
    return 0


if __name__ == "__main__":
    sys.exit(main())
