# -*- coding: utf-8 -*-
r"""
番茄钟历史统计 / Pomodoro history.

**刻意不 import Qt**，也**不碰 config\settings.json**：
统计是运行期产物（会天天变），和「用户花时间调好的偏好」分开住，
与 1.0.5 把 settings 挪进 `config\` 的理由一致 —— 误删 `data\` 不会连历史一起赔进去。

每天一行 ``{"completed": 3, "focus_sec": 4500}``，只保留最近 30 天：
「今天做了几个」需要，三个月前的明细不需要，而文件无限增长迟早变成一个
没人敢打开的大家伙。

Deliberately Qt-free and deliberately NOT in settings.json: this is run-time
data that changes daily, not a preference the user tuned.  Same reasoning that
moved settings into config\ in 1.0.5.  One line per day, only the last 30.
"""

from __future__ import annotations

import json
import os
import time

from .settings import DATA_DIR

__all__ = ["PomodoroStats"]

_KEEP_DAYS = 30
_FILENAME = "pomodoro_stats.json"


class PomodoroStats:
    """按天记录完成的番茄数与专注秒数 / Completed pomodoros and focus time per day."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or DATA_DIR
        self.path = os.path.join(self.data_dir, _FILENAME)
        self._data: dict[str, dict] = {}
        self._loaded_day: str | None = None
        self._load()

    # ------------------------------------------------------------------
    @staticmethod
    def today() -> str:
        """本地日期字符串 / Local date string (YYYY-MM-DD)."""
        return time.strftime("%Y-%m-%d")

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self._data = {str(k): v for k, v in raw.items()
                              if isinstance(v, dict)}
        except (OSError, ValueError):
            # 没有文件 / 坏了都当作「从零开始」，不该让统计功能拖垮程序启动。
            # Missing or corrupt counts as "starting fresh"; statistics must
            # never be the reason the app fails to start.
            self._data = {}

    def _save(self) -> None:
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)      # 原子写入 / atomic
        except OSError:
            pass

    def _prune(self) -> None:
        """只保留最近 N 天 / Keep only the most recent days."""
        if len(self._data) <= _KEEP_DAYS:
            return
        days = sorted(self._data.keys())
        for day in days[:-_KEEP_DAYS]:
            self._data.pop(day, None)

    # ------------------------------------------------------------------
    def record(self, focus_sec: int = 0, count: int = 1) -> None:
        """记一次完成的番茄 / Record one finished pomodoro."""
        day = self.today()
        row = self._data.setdefault(day, {"completed": 0, "focus_sec": 0})
        try:
            row["completed"] = int(row.get("completed", 0)) + int(count)
            row["focus_sec"] = int(row.get("focus_sec", 0)) + max(0, int(focus_sec))
        except (TypeError, ValueError):
            self._data[day] = {"completed": int(count), "focus_sec": int(focus_sec)}
        self._prune()
        self._save()

    def summary(self, day: str | None = None) -> dict:
        """某天的统计 / Statistics for one day."""
        row = self._data.get(day or self.today(), {})
        try:
            completed = int(row.get("completed", 0))
            focus = int(row.get("focus_sec", 0))
        except (TypeError, ValueError):
            completed, focus = 0, 0
        return {"day": day or self.today(), "completed": completed,
                "focus_sec": focus}

    def today_text(self, fmt_hm: bool = True) -> str:
        """
        「今日 3 个 · 1 小时 15 分」/ A one-line summary for today.
        """
        s = self.summary()
        n, sec = s["completed"], s["focus_sec"]
        if fmt_hm:
            return "%d 个 · %d 小时 %02d 分" % (n, sec // 3600, (sec % 3600) // 60)
        return "%d 个 · %d 分" % (n, sec // 60)

    def total(self) -> dict:
        """全部保留期的合计 / Totals across the retained window."""
        done = sum(int(v.get("completed", 0) or 0) for v in self._data.values())
        sec = sum(int(v.get("focus_sec", 0) or 0) for v in self._data.values())
        return {"completed": done, "focus_sec": sec, "days": len(self._data)}

    def total_text(self) -> str:
        """「累计 5 个 · 4 小时 20 分」/ Totals across the retained window."""
        t = self.total()
        sec = t["focus_sec"]
        return "%d 个 · %d 小时 %02d 分" % (t["completed"], sec // 3600,
                                           (sec % 3600) // 60)

    def streak(self) -> int:
        """
        连续多少天**至少完成过一个**番茄（今天没做完不算断）。
        Consecutive days with at least one pomodoro; today being empty does
        not break the streak (it is not over yet).
        """
        if not self._data:
            return 0
        days = sorted(self._data.keys())
        have = {d for d, v in self._data.items()
                if int(v.get("completed", 0) or 0) > 0}
        if not have:
            return 0
        cursor = time.localtime()
        # 今天还没完成就从昨天开始数 / start from yesterday when today is empty
        if time.strftime("%Y-%m-%d", cursor) not in have:
            cursor = time.localtime(time.time() - 86400)
        n = 0
        while True:
            key = time.strftime("%Y-%m-%d", cursor)
            if key not in have:
                break
            n += 1
            cursor = time.localtime(time.mktime(cursor) - 86400)
        return n

    def clear(self) -> None:
        """清空全部历史 / Wipe the whole history."""
        self._data = {}
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass
