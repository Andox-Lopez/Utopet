# -*- coding: utf-8 -*-
"""
自定义动作编辑器 / Custom action editor
==============================================================================
可视化地新建 / 修改一个动作：挑选角色素材里的帧、设置每帧的基准坐标、
移动速度与时长，并可把它绑定到行为池里按权重自动触发。

Create or edit an action visually: pick frames from the character's sprite set,
set each frame's anchor point, velocity and duration, and optionally bind the
action to the behaviour pool so it triggers automatically.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..i18n import get_i18n
from ..names import FRAME_NAMES

__all__ = ["ActionEditor"]

# 锚框 日文值 <-> 显示 / anchor frame: Japanese value <-> label
FRAME_VALUES = {"ground": "地面", "wall": "壁", "ceiling": "天井"}
KIND_VALUES = {"fixed": "固定", "stay": "静止", "move": "移動"}


class ActionEditor(QDialog):
    """动作编辑对话框 / The action editing dialog."""

    def __init__(self, manager, custom, action: dict | None = None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.custom = custom
        self.action = action
        self.t = get_i18n()

        self.setWindowTitle(self.t.t("editor.title"))
        self.resize(720, 520)
        self._build()
        self._load(action)

    # ------------------------------------------------------------------
    def _build(self):
        t = self.t
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow(t.t("editor.name"), self.name_edit)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("固定 / Fixed", "固定")
        self.kind_combo.addItem("静止 / Stay", "静止")
        self.kind_combo.addItem("移動 / Move", "移動")
        form.addRow(t.t("actions.col_kind"), self.kind_combo)

        self.frame_combo = QComboBox()
        for key, ja in FRAME_VALUES.items():
            zh, en = FRAME_NAMES.get(key, (ja, key))
            self.frame_combo.addItem("%s %s" % (zh, en), ja)
        form.addRow("枠 / Anchor", self.frame_combo)
        root.addLayout(form)

        # ---- 帧表格 / frame table ----
        root.addWidget(QLabel(t.t("editor.frames")))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            t.t("editor.image"), t.t("editor.base"),
            t.t("editor.velocity"), t.t("editor.duration")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._preview_current)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton(t.t("btn.add_frame"))
        self.btn_del = QPushButton(t.t("btn.del_frame"))
        self.btn_up = QPushButton(t.t("btn.move_up"))
        self.btn_down = QPushButton(t.t("btn.move_down"))
        self.btn_add.clicked.connect(self.add_frame)
        self.btn_del.clicked.connect(self.del_frame)
        self.btn_up.clicked.connect(lambda: self.move_frame(-1))
        self.btn_down.clicked.connect(lambda: self.move_frame(1))
        for b in (self.btn_add, self.btn_del, self.btn_up, self.btn_down):
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

        # ---- 预览 / preview ----
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(128, 128)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#f0f0f0;border:1px solid #ccc;")
        prev_row.addWidget(self.preview)

        # 预览循环播放当前帧序列 / the preview loops through the frame sequence
        self._preview_index = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(320)
        self._preview_timer.timeout.connect(self._advance_preview)
        self._preview_timer.start()

        bind_box = QVBoxLayout()
        self.bind_check = QCheckBox(t.t("editor.bind"))
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel(t.t("editor.frequency")))
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(0, 100000)
        self.freq_spin.setValue(30)
        freq_row.addWidget(self.freq_spin)
        freq_row.addStretch(1)
        bind_box.addWidget(self.bind_check)
        bind_box.addLayout(freq_row)
        bind_box.addStretch(1)
        prev_row.addLayout(bind_box, 1)
        root.addLayout(prev_row)

        root.addWidget(QLabel(t.t("editor.tip")))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(self.t.t("btn.save"))
        buttons.button(QDialogButtonBox.Cancel).setText(self.t.t("btn.cancel"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    def _image_names(self):
        imgs = self.manager.images
        return imgs.names if imgs else []

    def _make_image_combo(self, current: str = "") -> QComboBox:
        combo = QComboBox()
        names = self._image_names()
        for n in names:
            combo.addItem(n)
        if current:
            idx = combo.findText(current.lstrip("/\\"))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.currentTextChanged.connect(self._preview_current)
        return combo

    def add_frame(self, frame: dict | None = None):
        frame = frame or {"image": "shime1.png", "base": "64,128",
                          "velocity": "0,0", "duration": "10"}
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, 0, self._make_image_combo(frame["image"]))
        for col, key in ((1, "base"), (2, "velocity"), (3, "duration")):
            item = QTableWidgetItem(str(frame[key]))
            self.table.setItem(r, col, item)
        self.table.selectRow(r)

    def del_frame(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def move_frame(self, delta: int):
        r = self.table.currentRow()
        target = r + delta
        if r < 0 or target < 0 or target >= self.table.rowCount():
            return
        data = self._row_data(r)
        self.table.removeRow(r)
        self.table.insertRow(target)
        self.table.setCellWidget(target, 0, self._make_image_combo(data["image"]))
        for col, key in ((1, "base"), (2, "velocity"), (3, "duration")):
            self.table.setItem(target, col, QTableWidgetItem(str(data[key])))
        self.table.selectRow(target)

    def _row_data(self, r: int) -> dict:
        combo = self.table.cellWidget(r, 0)
        image = combo.currentText() if combo else ""
        def txt(col):
            item = self.table.item(r, col)
            return item.text() if item else ""
        return {"image": image, "base": txt(1), "velocity": txt(2), "duration": txt(3)}

    def frames(self) -> list[dict]:
        return [self._row_data(r) for r in range(self.table.rowCount())]

    # ------------------------------------------------------------------
    def _advance_preview(self):
        """预览自动播到下一帧 / advance the preview to the next frame."""
        n = self.table.rowCount()
        if n <= 0:
            return
        self._preview_index = (self._preview_index + 1) % n
        self._show_frame(self._preview_index)

    def _show_frame(self, index: int):
        if index < 0 or index >= self.table.rowCount():
            return
        data = self._row_data(index)
        pix = self.manager.images.get("/" + data["image"]) if self.manager.images else None
        if pix is None:
            self.preview.setText("—")
            return
        self.preview.setPixmap(pix.scaled(128, 128, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))

    def _preview_current(self):
        r = self.table.currentRow()
        if r < 0:
            return
        self._preview_index = r
        self._show_frame(r)

    # ------------------------------------------------------------------
    def _load(self, action: dict | None):
        if action:
            self.name_edit.setText(action.get("name", ""))
            ja_kind = action.get("kind", "固定")
            for i in range(self.kind_combo.count()):
                if self.kind_combo.itemData(i) == ja_kind:
                    self.kind_combo.setCurrentIndex(i)
                    break
            ja_frame = action.get("frame", "地面")
            for i in range(self.frame_combo.count()):
                if self.frame_combo.itemData(i) == ja_frame:
                    self.frame_combo.setCurrentIndex(i)
                    break
            for f in action.get("poses", []):
                self.add_frame(f)
            freq = str(action.get("frequency", "0"))
            try:
                fv = int(float(freq))
            except ValueError:
                fv = 0
            self.freq_spin.setValue(fv)
            self.bind_check.setChecked(fv > 0)
        if self.table.rowCount() == 0:
            self.add_frame()

    # ------------------------------------------------------------------
    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, self.t.t("editor.title"),
                                self.t.t("editor.name"))
            return
        frames = self.frames()
        if not frames:
            QMessageBox.warning(self, self.t.t("editor.title"),
                                self.t.t("editor.frames"))
            return
        freq = self.freq_spin.value() if self.bind_check.isChecked() else 0
        action = {
            "name": name,
            "kind": self.kind_combo.currentData(),
            "frame": self.frame_combo.currentData(),
            "poses": [dict(f, image="/" + f["image"].lstrip("/\\")) for f in frames],
            "frequency": str(freq),
        }
        self.custom.upsert(action)
        self.custom.save()
        self.result_action = action
        self.accept()
