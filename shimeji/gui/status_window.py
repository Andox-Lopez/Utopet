# -*- coding: utf-8 -*-
"""
宠物状态详细窗口 / Detailed pet status window
==============================================================================
面板只有 320px 宽，`taskbar_panel.py` 里那行状态摘要**塞不下四个数值**，多角色
时更是只能拿第一只当「代表」。这个窗口补上那一块：**每只宠物、四个数值**。

The 320px panel has room for only one line of summary, and with several pets it
can only show the first one as a stand-in.  This window fills that gap: every
pet, all four numbers.

**它不是游戏。** 这里没有任务、没有目标、没有失败惩罚 —— 数值仍然只是
「给 `state()` 提供输入」。做成看得见，是为了让互动有反馈，不是为了让人刷数值。

This is not a game: no quests, no goals, no penalties.  The numbers still only
feed `state()`; showing them is about giving interaction a visible result, not
about giving the user something to grind.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QProgressBar, QVBoxLayout, QWidget)

from ..i18n import get_i18n

__all__ = ["StatusWindow"]

log = logging.getLogger(__name__)

#: 刷新间隔（毫秒）/ refresh interval.
#: 状态每 15 秒才漂移一次，1 秒刷一次足够跟得上，又不至于空转。
REFRESH_MS = 1000


class StatusWindow(QWidget):
    """每只宠物的四个数值 / All four numbers, for every pet."""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.t = get_i18n()
        self.setWindowTitle(self.t.t("panel.state_detail", "Pet Status"))
        self.setMinimumWidth(300)
        self._rows: list[dict] = []

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(12, 12, 12, 12)
        self.outer.setSpacing(8)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        """重画整张表 / Rebuild the whole table."""
        pets = list(getattr(self.manager, "mascots", []) or [])
        # 宠物数量变了就重建（行数对不上，复用旧行会留下幽灵数据）
        # Rebuild when the count changes: reusing rows would leave stale pets.
        if len(pets) != len(self._rows):
            self._rebuild(len(pets))
        if not pets:
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)

        for i, m in enumerate(pets):
            row = self._rows[i]
            st = getattr(m, "status", None)
            if st is None:
                row["frame"].setVisible(False)
                continue
            row["frame"].setVisible(True)
            d = st.detail()
            row["name"].setText(self._pet_name(m, i))
            row["state"].setText(st.state_name(d.get("state", "normal")))
            for key in ("feeling", "energy", "health", "likability"):
                # ⭐ 用 `.get()` 而不是 `[key]`：万一 `detail()` 少了某个键，
                # 窗口不该直接崩掉 —— 缺的那个显示为 0，并在日志里记一笔。
                # A missing key must not crash the window; show 0 and log it.
                if key not in d:
                    log.warning("宠物状态缺少 %s 字段，按 0 显示", key)
                v = float(d.get(key, 0.0))
                row[key]["bar"].setValue(int(round(v)))
                row[key]["num"].setText("%.0f" % v)

    # ------------------------------------------------------------------
    def _pet_name(self, mascot, index: int) -> str:
        """角色名；取不到就退回序号 / The character label, falling back to an index."""
        bundle = getattr(mascot, "bundle", None)
        label = getattr(bundle, "label", None) if bundle is not None else None
        if not label:
            label = self.manager.settings.get("character", "-")
        return "%s" % label if len(self.manager.mascots) > 1 else str(label)

    def _rebuild(self, count: int):
        """按宠物数量重建行 / Rebuild rows for `count` pets."""
        # 清掉旧的
        for row in self._rows:
            row["frame"].setParent(None)
            row["frame"].deleteLater()
        while self.outer.count():
            item = self.outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []

        self._empty_label = QLabel(self.t.t("panel.state_none",
                                            "No pets right now"))
        self._empty_label.setStyleSheet("color: palette(mid); font-size: 12px;")
        self.outer.addWidget(self._empty_label)

        for _ in range(count):
            self._rows.append(self._make_row())
        self.outer.addStretch(1)

    # ------------------------------------------------------------------
    def _make_row(self) -> dict:
        """一宠一块：名字 + 状态 + 四行数值条 / One block per pet."""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        head = QHBoxLayout()
        name = QLabel()
        name.setStyleSheet("font-weight: 600; font-size: 13px;")
        state = QLabel()
        state.setStyleSheet("color: palette(mid); font-size: 12px;")
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(state)
        v.addLayout(head)

        row = {"frame": frame, "name": name, "state": state}
        for key, tkey, default in (
                ("feeling", "panel.mood", "Mood"),
                ("energy", "panel.stamina", "Stamina"),
                ("health", "panel.health", "Health"),
                ("likability", "panel.likability", "Rapport")):
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            label = QLabel(self.t.t(tkey, default))
            label.setFixedWidth(56)
            label.setStyleSheet("color: palette(mid); font-size: 12px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            num = QLabel("0")
            num.setFixedWidth(28)
            num.setStyleSheet("font-size: 12px;")
            grid.addWidget(label, 0, 0)
            grid.addWidget(bar, 0, 1)
            grid.addWidget(num, 0, 2)
            v.addLayout(grid)
            row[key] = {"bar": bar, "num": num}

        self.outer.addWidget(frame)
        return row

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
