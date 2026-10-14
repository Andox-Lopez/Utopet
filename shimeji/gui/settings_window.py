# -*- coding: utf-8 -*-
"""
设置窗口 / Settings window
==============================================================================
分页：常规 / 外观 / 行为 / 动作编辑 / 高级 / 关于。
除角色切换、缩放、置顶需要重启引擎外，其余设置即时生效。

Tabs: General / Appearance / Behaviour / Action Editor / Advanced / About.
Everything applies live except character switching, scale and always-on-top,
which need an engine restart.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..characterpack import (REQUIRED_CONF, export_pack, import_pack,
                             is_supported_source, supplement_conf)
from ..custom import CustomConfig
from ..engine.manager import LOG_PATH, list_characters
from ..engine.petstate import CAL_CLASSES
from ..hotkeys import ACTION_KEYS, DEFAULT_HOTKEYS
from ..i18n import LANGUAGES, get_i18n
from ..icons import app_icon, logo_pixmap
from ..names import KIND_NAMES, display_name
from ..settings import CHARACTERS_DIR
from .action_editor import ActionEditor

__all__ = ["SettingsWindow"]


class SettingsWindow(QWidget):
    """设置主窗口 / The settings window."""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.settings = manager.settings
        self.t = get_i18n()
        self.custom = CustomConfig(manager.settings.custom_xml)

        self.setWindowTitle(self.t.t("settings.title"))
        self.setWindowIcon(app_icon())
        self.resize(760, 600)
        # 接受拖放：把角色包 zip 或角色文件夹直接拖进来就导入。
        # 这是「导入角色包」最自然的入口 —— 用户手上就是那个文件，
        # 拖一下比「点按钮 → 在对话框里一路点进目录」少四步。
        # Accept drops: dragging a pack zip or folder in imports it.  That is the
        # natural gesture -- the file is already in the user's hand, and dragging
        # it saves the four clicks of navigating a file dialog.
        self.setAcceptDrops(True)
        self._outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self._outer.addWidget(self.tabs, 1)
        self._build_tabs()
        self._build_buttons()

    # ------------------------------------------------------------------
    def _build_tabs(self):
        self.tabs.clear()
        self._tab_general()
        self._tab_characters()
        self._tab_appearance()
        self._tab_behavior()
        self._tab_actions()
        self._tab_advanced()
        self._tab_about()

    def _build_buttons(self):
        row = QHBoxLayout()
        self.btn_apply = QPushButton(self.t.t("btn.apply"))
        self.btn_save = QPushButton(self.t.t("btn.save"))
        self.btn_restart = QPushButton(self.t.t("btn.restart"))
        self.btn_close = QPushButton(self.t.t("btn.close"))
        self.btn_apply.clicked.connect(self.apply)
        self.btn_save.clicked.connect(lambda: (self.apply(), self.settings.save()))
        self.btn_restart.clicked.connect(self.restart_engine)
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_restart)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        self._outer.addLayout(row)

    def _group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setLayout(QFormLayout())
        return g

    # ------------------------------------------------------------------
    # 常规 / general
    # ------------------------------------------------------------------
    def _tab_general(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)

        g = self._group(t.t("grp.language"))
        self.lang_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.lang_combo.addItem(label, code)
        idx = self.lang_combo.findData(self.settings.get("language", "zh_CN"))
        self.lang_combo.setCurrentIndex(max(0, idx))
        g.layout().addRow(t.t("lbl.language"), self.lang_combo)
        self.bilingual = QCheckBox(t.t("lbl.bilingual"))
        self.bilingual.setChecked(bool(self.settings.get("bilingual", True)))
        g.layout().addRow("", self.bilingual)
        v.addWidget(g)

        g1 = self._group(t.t("grp.startup"))
        self.initial_spin = QSpinBox()
        self.initial_spin.setRange(1, 100)
        self.initial_spin.setValue(int(self.settings.get("initial_count", 1)))
        g1.layout().addRow(t.t("lbl.initial_count"), self.initial_spin)
        self.restore = QCheckBox(t.t("lbl.restore_session"))
        self.restore.setChecked(bool(self.settings.get("restore_session", True)))
        g1.layout().addRow("", self.restore)
        v.addWidget(g1)

        gt = self._group(t.t("grp.multi"))
        self.summon_count = QSpinBox()
        self.summon_count.setRange(1, 100)
        self.summon_count.setValue(int(self.settings.get("summon_count", 5)))
        gt.layout().addRow(t.t("lbl.summon_count"), self.summon_count)
        self.spread = QCheckBox(t.t("lbl.spawn_spread"))
        self.spread.setChecked(bool(self.settings.get("spawn_spread", True)))
        gt.layout().addRow("", self.spread)
        # 1.0.3：多角色共存。与「自我增殖」互斥，勾上时增殖自动失效并给出提示。
        # Multi-character mode.  Mutually exclusive with self-cloning: turning
        # it on disables cloning and says so, rather than silently conflicting.
        self.multi_pet = QCheckBox(t.t("lbl.multi_pet"))
        self.multi_pet.setChecked(bool(self.settings.get("multi_pet_enabled", False)))
        self.multi_pet.setToolTip(t.t("hint.multi_pet"))
        gt.layout().addRow("", self.multi_pet)
        self.multi_pet.toggled.connect(self._on_multi_pet_toggled)
        self.multi_pet_note = QLabel("")
        self.multi_pet_note.setWordWrap(True)
        self.multi_pet_note.setStyleSheet("color: palette(mid);")
        gt.layout().addRow("", self.multi_pet_note)
        self.clone = QCheckBox(t.t("lbl.self_clone"))
        self.clone.setChecked(bool(self.settings.get("self_cloning_enabled", True)))
        self.clone.setToolTip(t.t("hint.self_cloning"))
        gt.layout().addRow("", self.clone)
        self._sync_clone_state()
        v.addWidget(gt)

        gtb = self._group(t.t("grp.taskbar"))
        self.taskbar_panel = QCheckBox(t.t("lbl.taskbar_panel"))
        self.taskbar_panel.setChecked(bool(self.settings.get("taskbar_panel", True)))
        # 1.0.6 修：这两行原来写的是 `gt`（多宠物组），于是「任务栏」这个分组
        # 从来没显示过，勾选框跑到「多宠物」里去了，`gt` 还被 addWidget 了两次。
        # 分组标题和被归入的控件必须一致，否则用户按标题找不到东西。
        # Fixed in 1.0.6: these two lines used `gt` (the multi-pet group), so the
        # "Taskbar" group never appeared and its checkbox lived under "multi-pet";
        # `gt` was also added to the layout twice.
        gtb.layout().addRow("", self.taskbar_panel)
        v.addWidget(gtb)

        # 「角色」与「角色包」两组在 1.0.6 之后独立成页（`_tab_characters`）。
        # 挤在常规页里时，角色列表 + 四个导入导出按钮把这一页拉得很长，
        # 而这两件事本身是围绕「桌面上站着的是谁」的一整套流程，放一起更顺。
        # The character and character-pack groups moved to their own page in
        # 1.0.6: they form one workflow ("who is on screen") and they made the
        # General page unreasonably tall.
        v.addStretch(1)
        self.tabs.addTab(w, t.t("tab.general"))

    # ------------------------------------------------------------------
    # 角色 / characters
    # ------------------------------------------------------------------
    def _tab_characters(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)

        g2 = self._group(t.t("grp.character"))
        self.char_combo = QComboBox()
        self._fill_characters()
        g2.layout().addRow(t.t("lbl.character"), self.char_combo)
        self.dir_list = QListWidget()
        for d in self.settings.get("character_dirs", []) or []:
            self.dir_list.addItem(d)
        # 独占一页后列表可以大一点，但别让它撑满整页 —— 上下留白才不晃眼。
        # A list on a page of its own may grow, but not to fill the whole page.
        self.dir_list.setMinimumHeight(170)
        self.dir_list.setMaximumHeight(280)
        dirs_row = QHBoxLayout()
        dirs_row.addWidget(self.dir_list, 1)
        btns = QVBoxLayout()
        b_add = QPushButton(t.t("btn.add"))
        b_del = QPushButton(t.t("btn.remove"))
        b_add.clicked.connect(self._add_char_dir)
        b_del.clicked.connect(self._del_char_dir)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)
        dirs_row.addLayout(btns)
        g2.layout().addRow(t.t("lbl.character_dirs"), dirs_row)
        v.addWidget(g2)

        gp = self._group(t.t("grp.pack"))
        pack_row = QHBoxLayout()
        self.btn_import_pack = QPushButton(t.t("btn.import_pack"))
        self.btn_import_folder = QPushButton(t.t("btn.import_folder"))
        self.btn_export_pack = QPushButton(t.t("btn.export_pack"))
        self.btn_supplement = QPushButton(t.t("btn.supplement"))
        self.btn_import_pack.clicked.connect(self._import_pack_dialog)
        self.btn_import_folder.clicked.connect(self._import_folder_dialog)
        self.btn_export_pack.clicked.connect(self._export_pack_dialog)
        self.btn_supplement.clicked.connect(self._supplement_all)
        for b in (self.btn_import_pack, self.btn_import_folder,
                  self.btn_export_pack, self.btn_supplement):
            pack_row.addWidget(b)
        gp.layout().addRow("", pack_row)
        self.pack_note = QLabel(t.t("hint.pack_drop"))
        self.pack_note.setWordWrap(True)
        self.pack_note.setStyleSheet("color: palette(mid); font-size: 11px;")
        gp.layout().addRow("", self.pack_note)
        v.addWidget(gp)
        v.addStretch(1)
        self.tabs.addTab(w, t.t("tab.characters"))

    def _sync_clone_state(self):
        """
        多角色与增殖互斥的可视化 / Reflect the multi-pet / cloning exclusion.

        多角色模式下一只宠物一个角色（各有动作表），增殖却是「同角色多一只」，
        两者同时开会产出行为错乱的组合。所以这里不只禁用控件，还要**写明原因**，
        否则用户会以为是 bug。
        The two features are semantically incompatible, so disable the checkbox
        *and say why* — otherwise it reads as a bug.
        """
        on = self.multi_pet.isChecked()
        self.clone.setEnabled(not on)
        # 必须是 self.t，不能写裸的 t —— 这里原本写的是 t，直接 NameError。
        # 后果不是「提示文字没出来」这么轻：勾选框的 toggled 信号是在用户
        # 点下去时同步触发的，异常从信号处理器里抛出去会让整个槽函数中断，
        # 于是 self.clone.setChecked(False) 之后的收尾全都没跑。更糟的是
        # 用户接着点「保存」时，_apply() 里读到的多角色状态和界面显示的不一致，
        # 表现就是「保存了但没生效、再打开设置又打不开」。
        # It must be self.t: this used to read a bare `t` and raised NameError.
        # That is not a cosmetic slip -- the toggled signal fires synchronously
        # when the user clicks, so the exception aborts the whole slot: the
        # rest of _on_multi_pet_toggled never runs, the checkbox state and the
        # saved state diverge, and the user sees "saved but nothing happened,
        # and now settings won't even open".
        self.multi_pet_note.setText(
            self.t.t("hint.multi_pet_on") if on else "")

    def _on_multi_pet_toggled(self, _checked: bool):
        """切换多角色时立刻反映到增殖开关上 / Mirror the toggle onto cloning."""
        if self.multi_pet.isChecked():
            self.clone.setChecked(False)
        self._sync_clone_state()

    def _fill_characters(self):
        current = self.settings.get("character", "")
        self.char_combo.clear()
        chars = list_characters(self.settings)
        for label, d in chars:
            self.char_combo.addItem(label, label)
        if current:
            i = self.char_combo.findData(current)
            if i >= 0:
                self.char_combo.setCurrentIndex(i)
            else:
                self.char_combo.addItem(current, current)
                self.char_combo.setCurrentIndex(self.char_combo.count() - 1)
        elif self.char_combo.count():
            self.char_combo.setCurrentIndex(0)

    def _add_char_dir(self):
        d = QFileDialog.getExistingDirectory(self, self.t.t("lbl.character_dirs"))
        if d:
            self.dir_list.addItem(d)

    def _del_char_dir(self):
        for item in self.dir_list.selectedItems():
            self.dir_list.takeItem(self.dir_list.row(item))

    # ------------------------------------------------------------------
    # 外观 / appearance
    # ------------------------------------------------------------------
    def _tab_appearance(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)
        g = self._group(t.t("grp.appearance"))

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.25, 4.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(float(self.settings.get("scale", 1.0)))
        g.layout().addRow(t.t("lbl.scale"), self.scale_spin)

        self.tick_spin = QSpinBox()
        self.tick_spin.setRange(10, 200)
        self.tick_spin.setValue(int(self.settings.get("tick_ms", 40)))
        g.layout().addRow(t.t("lbl.tick"), self.tick_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.1, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(float(self.settings.get("opacity", 1.0)))
        g.layout().addRow(t.t("lbl.opacity"), self.opacity_spin)

        self.on_top = QCheckBox(t.t("lbl.always_on_top"))
        self.on_top.setChecked(bool(self.settings.get("always_on_top", True)))
        g.layout().addRow("", self.on_top)
        v.addWidget(g)
        v.addStretch(1)
        self.tabs.addTab(w, t.t("tab.appearance"))

    # ------------------------------------------------------------------
    # 行为 / behaviour
    # ------------------------------------------------------------------
    def _tab_behavior(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)
        g = self._group(t.t("grp.behavior"))

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 500)
        self.max_spin.setValue(int(self.settings.get("max_count", 50)))
        g.layout().addRow(t.t("lbl.max_count"), self.max_spin)

        # 「允许自我增殖」不在这里建 —— 它住在「常规 → 多宠物」组里。
        #
        # 这正是用户截图指出的「两个复选框重复了」：1.1.0 回滚时两个标签页
        # 各建了一次 `self.clone`，后建的把先建的覆盖，于是两页各显示一个
        # 勾选框，而 `_sync_clone_state()` 的置灰与互斥提示、`apply()` 读到的
        # 状态，全部只作用在**第二个**上 —— 第一个成了永远不受控的幽灵控件。
        # 同一个 `self.xxx` 在两个标签页里建两次，就是这类 bug 的全部来源。
        # 养成开关属于「多宠物」组：它和「多角色共存」互斥，提示文字也在那儿。
        #
        # The self-cloning checkbox is NOT built here -- it lives in
        # "General > Multi-pet".  This is the reported "two checkboxes say the
        # same thing": the 1.1.0 rollback left one copy in each tab, the second
        # assignment shadowed the first, so both tabs showed a box while
        # `_sync_clone_state()` (grey-out + the exclusion note) and `apply()` all
        # talked to the *second* one only.  The first was an uncontrolled ghost.
        # Cloning belongs with multi-character mode: the two are mutually
        # exclusive and the explanation lives there.

        # 爬窗和扔窗是两个独立开关。以前只有一个「允许与窗口互动」同时管着
        # 两件事：想关掉「扔窗户」（窗户被扔出屏幕就找不回来）就得连爬墙一起
        # 禁掉。现在分开，各关各的。
        # Climbing and throwing are independent switches.  A single
        # "allow window interaction" used to gate both, so turning off
        # "throw" (which loses windows off-screen) also killed climbing.
        self.climb = QCheckBox(t.t("lbl.climb"))
        self.climb.setChecked(bool(self.settings.get("climb_enabled", True)))
        g.layout().addRow("", self.climb)

        self.throw = QCheckBox(t.t("lbl.throw"))
        self.throw.setChecked(bool(self.settings.get("throw_enabled", True)))
        g.layout().addRow("", self.throw)

        self.idle = QCheckBox(t.t("lbl.idle_gather"))
        self.idle.setChecked(bool(self.settings.get("idle_gather", True)))
        g.layout().addRow("", self.idle)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(3, 600)
        self.idle_spin.setValue(int(self.settings.get("idle_gather_sec", 25)))
        g.layout().addRow(t.t("lbl.idle_sec"), self.idle_spin)
        v.addWidget(g)

        # 逐条微调行为频次 / tune each behaviour individually
        g2 = self._group(t.t("grp.behavior_tuning"))
        self.behavior_table = QTableWidget(0, 6)
        self.behavior_table.setHorizontalHeaderLabels([
            t.t("behavior.col_name"), t.t("behavior.col_freq"),
            t.t("behavior.col_cal_class"), t.t("behavior.col_cal_strength"),
            t.t("behavior.col_enabled"), t.t("behavior.col_custom")])
        self.behavior_table.horizontalHeader().setStretchLastSection(True)
        self.behavior_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.behavior_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 行高必须显式给。默认行高按 13px 字号 + 单元格 padding 算出来，
        # 撑不下行内嵌的 QSpinBox / QComboBox —— 结果是每一行的控件被裁掉
        # 下半截，看起来像「表格内容显示不全」。
        # QSS 的 ::item 只管 padding，管不到行高；defaultSectionSize 只能
        # 在代码里设。
        #
        # Row height must be set explicitly.  The default is computed for the
        # 13px font and cannot contain the embedded spinbox, so every row's
        # controls get sliced in half.  QSS ::item only handles padding.
        self.behavior_table.verticalHeader().setDefaultSectionSize(34)
        self.behavior_table.verticalHeader().setMinimumSectionSize(34)
        # 两列 CalMode 控件比较窄，不让它们把「行为」列挤没。
        # The two CalMode columns are narrow; don't let them squeeze out the name.
        # ⚠️ 循环变量别叫 w —— w 是上面那个 QWidget。被覆盖后 widget 就没有
        # Python 引用了，GC 回收后 v 会变成 "Internal C++ object ... deleted"。
        # ⚠️ Don't shadow the widget: `w` must stay alive until addTab().
        hh = self.behavior_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, cw in ((1, 90), (2, 100), (3, 90), (4, 56)):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.behavior_table.setColumnWidth(col, cw)
        g2.layout().addRow(self.behavior_table)
        # 说明放在表格下面而不是 tooltip 里：这两个概念（类别 vs 强度）
        # 只看控件是猜不出来的。
        # Explain below the table rather than in tooltips: the two knobs are
        # not guessable from the widgets alone.
        hint = QLabel(t.t("hint.cal_class") + "\n" + t.t("hint.cal_strength"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        g2.layout().addRow(hint)
        v.addWidget(g2, 1)
        self.tabs.addTab(w, t.t("tab.behavior"))
        self._fill_behaviors()

    # ------------------------------------------------------------------
    def _fill_behaviors(self):
        """列出所有行为及其权重 / List every behaviour with its weight."""
        t = self.t
        lang = self.settings.get("language", "zh_CN")
        bi = bool(self.settings.get("bilingual", True))
        overrides = self.settings.get("behavior_overrides", {}) or {}
        cal = self.settings.get("cal_overrides", {}) or {}
        if not isinstance(cal, dict):
            cal = {}
        seen: dict[str, object] = {}
        for _cond, b in self.manager.behaviors.entries:
            if b.name and b.name not in seen:
                seen[b.name] = b
        self.behavior_table.setRowCount(0)
        self._behavior_rows = []
        for name, b in seen.items():
            base_freq = int(b.frequency.num({}, 0))
            rule = overrides.get(name, {}) if isinstance(overrides, dict) else {}
            enabled = bool(rule.get("enabled", True))
            freq = int(rule.get("frequency", base_freq))
            crule = cal.get(name, {}) if isinstance(cal.get(name), dict) else {}
            r = self.behavior_table.rowCount()
            self.behavior_table.insertRow(r)
            self.behavior_table.setItem(r, 0, QTableWidgetItem(
                display_name(name, lang, bi)))
            spin = QSpinBox()
            spin.setRange(0, 100000)
            spin.setValue(freq)
            self.behavior_table.setCellWidget(r, 1, spin)
            # CalMode 类别 / CalMode class
            combo = QComboBox()
            for key in CAL_CLASSES:
                combo.addItem(t.t(f"behavior.cal_{key}"), key)
            idx = combo.findData(str(crule.get("class", "auto")))
            combo.setCurrentIndex(max(0, idx))
            combo.setToolTip(t.t("hint.cal_class"))
            self.behavior_table.setCellWidget(r, 2, combo)
            # CalMode 强度（百分比）/ CalMode strength as a percentage
            cspin = QSpinBox()
            cspin.setRange(0, 200)
            cspin.setSingleStep(10)
            cspin.setSuffix(" %")
            try:
                cspin.setValue(int(crule.get("strength", 100)))
            except (TypeError, ValueError):
                cspin.setValue(100)
            cspin.setToolTip(t.t("hint.cal_strength"))
            # 类别选「不受影响」时强度没有意义 —— 置灰并提示，
            # 否则用户会以为自己设的 200% 生效了。
            # Strength is meaningless when the class is "off": grey it out so
            # nobody wonders why their 200 % does nothing.
            off = combo.currentData() == "off"
            cspin.setEnabled(not off)
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, s=cspin: s.setEnabled(c.currentData() != "off"))
            self.behavior_table.setCellWidget(r, 3, cspin)
            chk = QCheckBox()
            chk.setChecked(enabled)
            self.behavior_table.setCellWidget(r, 4, chk)
            self.behavior_table.setItem(r, 5, QTableWidgetItem(
                t.t("actions.source_custom") if rule else t.t("actions.source_xml")))
            self._behavior_rows.append((name, spin, chk, combo, cspin))

    def _collect_behavior_overrides(self) -> dict:
        """把表格内容收集成覆盖表 / Collect the table into an override map."""
        base = {}
        for _cond, b in self.manager.behaviors.entries:
            if b.name and b.name not in base:
                base[b.name] = int(b.frequency.num({}, 0))
        out = {}
        for name, spin, chk, _combo, _cspin in getattr(self, "_behavior_rows", []):
            original = base.get(name, 0)
            if not chk.isChecked():
                out[name] = {"enabled": False}
            elif spin.value() != original:
                out[name] = {"enabled": True, "frequency": spin.value()}
        return out

    def _collect_cal_overrides(self) -> dict:
        """收集每条行为的 CalMode 覆盖 / Collect the per-behaviour CalMode rules.

        只写**与默认不同**的项，这样配置文件保持小，且老版本读它也不会误解 ——
        没有的键就是「自动 / 100%」。
        Only entries that differ from the default are written, so the file stays
        small and a missing key unambiguously means "auto / 100 %".
        """
        out = {}
        for name, _spin, _chk, combo, cspin in getattr(self, "_behavior_rows", []):
            cls = str(combo.currentData() or "auto")
            strength = int(cspin.value())
            if cls == "active" or cls == "quiet" or cls == "off":
                rule = {"class": cls}
                if cls != "off" and strength != 100:
                    rule["strength"] = strength
                out[name] = rule
            elif strength != 100:
                # auto + 非 100 强度也有效（放大/抹平自动判定出来的效果）
                out[name] = {"class": "auto", "strength": strength}
        return out

    # ------------------------------------------------------------------
    # 动作编辑 / actions
    # ------------------------------------------------------------------
    def _tab_actions(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(t.t("actions.hint")))

        self.action_table = QTableWidget(0, 5)
        self.action_table.setHorizontalHeaderLabels([
            t.t("actions.col_name"), t.t("actions.col_kind"),
            t.t("actions.col_frames"), t.t("actions.col_duration"),
            t.t("actions.col_source")])
        self.action_table.horizontalHeader().setStretchLastSection(True)
        self.action_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.action_table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.action_table, 1)

        row = QHBoxLayout()
        b_new = QPushButton(t.t("btn.new"))
        b_edit = QPushButton(t.t("btn.edit"))
        b_del = QPushButton(t.t("btn.delete"))
        b_reload = QPushButton(t.t("btn.reload"))
        b_new.clicked.connect(self._new_action)
        b_edit.clicked.connect(self._edit_action)
        b_del.clicked.connect(self._delete_action)
        b_reload.clicked.connect(self._reload_config)
        for b in (b_new, b_edit, b_del, b_reload):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.tabs.addTab(w, t.t("tab.actions"))
        self._fill_actions()

    def _fill_actions(self):
        t = self.t
        lang = self.settings.get("language", "zh_CN")
        bi = bool(self.settings.get("bilingual", True))
        custom_names = self.custom.names
        self.action_table.setRowCount(0)
        for name in self.manager.actions.order:
            d = self.manager.actions[name]
            frames = sum(len(a.poses) for a in d.animations)
            total = sum(a.total_duration for a in d.animations)
            zh, en = KIND_NAMES.get(d.kind, (d.kind, d.kind))
            kind_label = "%s %s" % (zh, en) if bi and not lang.startswith("en") else \
                         ("%s %s" % (en, zh) if bi else (en if lang.startswith("en") else zh))
            r = self.action_table.rowCount()
            self.action_table.insertRow(r)
            shown = name if name in custom_names else display_name(name, lang, bi)
            self.action_table.setItem(r, 0, QTableWidgetItem(shown))
            self.action_table.setItem(r, 1, QTableWidgetItem(kind_label))
            self.action_table.setItem(r, 2, QTableWidgetItem(str(frames)))
            self.action_table.setItem(r, 3, QTableWidgetItem(str(total)))
            self.action_table.setItem(r, 4, QTableWidgetItem(
                t.t("actions.source_custom") if name in custom_names
                else t.t("actions.source_xml")))

    def _selected_action_name(self):
        r = self.action_table.currentRow()
        if r < 0:
            return None
        return self.manager.actions.order[r] if r < len(self.manager.actions.order) else None

    def _new_action(self):
        dlg = ActionEditor(self.manager, self.custom, None, self)
        if dlg.exec():
            self._reload_config()

    def _edit_action(self):
        name = self._selected_action_name()
        if not name:
            return
        existing = self.custom.get(name)
        if existing is None:
            # 复制原动作作为自定义动作起点 / clone the config action as a starting point
            d = self.manager.actions.get(name)
            if d is None:
                return
            poses = []
            for anim in d.animations:
                for p in anim.poses:
                    poses.append({"image": p.image.text(), "base": p.base.text(),
                                  "velocity": p.velocity.text(), "duration": p.duration.text()})
            existing = {"name": name + "-copy", "kind": "固定",
                        "frame": "地面", "poses": poses, "frequency": "0"}
        dlg = ActionEditor(self.manager, self.custom, existing, self)
        if dlg.exec():
            self._reload_config()

    def _delete_action(self):
        name = self._selected_action_name()
        if not name or name not in self.custom.names:
            QMessageBox.information(self, self.t.t("actions.title"),
                                    self.t.t("actions.hint"))
            return
        msg = self.t.t("actions.confirm_delete").replace("{0}", name)
        if QMessageBox.question(self, self.t.t("actions.title"), msg) == QMessageBox.Yes:
            self.custom.remove(name)
            self.custom.save()
            self._reload_config()

    def _reload_config(self):
        self.manager.reload()
        self._fill_actions()

    # ------------------------------------------------------------------
    # 高级 / advanced
    # ------------------------------------------------------------------
    def _tab_advanced(self):
        t = self.t
        w = QWidget()
        v = QVBoxLayout(w)

        g = self._group(t.t("grp.window_filter"))
        self.titles_edit = QPlainTextEdit()
        self.titles_edit.setPlainText("\n".join(self.settings.get("titles", []) or []))
        g.layout().addRow(t.t("lbl.titles"), self.titles_edit)

        offs = self.settings.get("window_offset", [0, 0, 0, 0]) or [0, 0, 0, 0]
        off_row = QHBoxLayout()
        self.off_spins = []
        for i in range(4):
            s = QSpinBox()
            s.setRange(-2000, 2000)
            s.setValue(int(offs[i]) if i < len(offs) else 0)
            off_row.addWidget(s)
            self.off_spins.append(s)
        g.layout().addRow(t.t("lbl.win_offset"), off_row)
        v.addWidget(g)

        g2 = self._group(t.t("grp.maintenance"))
        # 开机自启（1.0.6 起真正可用）。
        #
        # 1.0.4 / 1.0.5 期间这一行是置灰 + 删除线 + 标「待开发」，而且**不写回
        # 配置** —— 因为当时的实现确实是坏的：无论源码版还是打包版都写成
        # `"<解释器>" "<项目根>/main.py"`，打包后那个 main.py 根本不在安装目录里，
        # 于是自启项「有」，程序却永远不会起来。现在 `Manager.startup_command()`
        # 按 `sys.frozen` 分支处理，所以不再替用户挡着这个功能。
        # Launch-at-login really works as of 1.0.6.  Through 1.0.4 / 1.0.5 the row
        # was greyed out, struck through and marked "planned", and it never wrote
        # the setting back -- because the implementation was broken: both builds
        # emitted `"<interpreter>" "<root>/main.py"`, and in a packaged build that
        # main.py is not shipped, so the entry existed but the program never
        # started.
        self.startup = QCheckBox(t.t("lbl.startup"))
        self.startup.setChecked(bool(self.settings.get("start_with_windows", False)))
        g2.layout().addRow("", self.startup)

        b_open = QPushButton(self.settings.custom_xml)
        b_open.clicked.connect(self._open_custom)
        g2.layout().addRow("custom.xml", b_open)

        # 日志入口。日志一直在写，但**没有入口等于没有** —— 用户来报问题时
        # 我们只能说「去 data 目录里找那个 log」，而多数人并不知道 data 在哪。
        # A way in to the log.  It was always being written, but without an entry
        # point it may as well not exist: "look in the data folder" is not an
        # answer for someone who does not know where that is.
        self.btn_open_log = QPushButton(t.t("btn.open_log"))
        self.btn_open_log.clicked.connect(self._open_log)
        g2.layout().addRow(t.t("lbl.log"), self.btn_open_log)
        v.addWidget(g2)

        gh = self._group(t.t("grp.hotkeys"))
        self.hotkeys_enabled = QCheckBox(t.t("lbl.hotkeys_enabled"))
        self.hotkeys_enabled.setChecked(bool(self.settings.get("hotkeys_enabled", True)))
        self.hotkeys_enabled.toggled.connect(self._on_hotkeys_toggled)
        gh.layout().addRow("", self.hotkeys_enabled)
        self.hotkey_label = QLabel("")
        self.hotkey_label.setWordWrap(True)
        gh.layout().addRow("", self.hotkey_label)
        hint_hk = QLabel(t.t("hint.hotkeys"))
        hint_hk.setWordWrap(True)
        hint_hk.setStyleSheet("color: palette(mid); font-size: 11px;")
        gh.layout().addRow("", hint_hk)
        v.addWidget(gh)
        # 填一次现状：注册失败的原因在 Manager 那儿，不在界面里
        # Fill it in from the Manager: registration failures are known there.
        self._fill_hotkeys()

        v.addStretch(1)
        self.tabs.addTab(w, t.t("tab.advanced"))

    def _on_hotkeys_toggled(self, _checked: bool):
        """开关一变就重新注册 / Re-register as soon as the switch flips."""
        try:
            self.settings.set("hotkeys_enabled", self.hotkeys_enabled.isChecked())
            self.manager.apply_hotkeys()
        except Exception:  # noqa: BLE001 - 界面不该因为一次注册失败而中断
            pass
        self._fill_hotkeys()

    def _fill_hotkeys(self):
        """列出当前生效的快捷键 / List the shortcuts currently in effect."""
        specs = self.manager.hotkey_specs()
        failed = getattr(self.manager.hotkeys, "failed", None) or {}
        rows = []
        for key in ACTION_KEYS:
            label = self.t.t(f"hotkey.{key}")
            spec = specs.get(key) or ""
            if not spec:
                rows.append(f"{label}：{self.t.t('hotkey.off')}")
            elif key in failed:
                rows.append(f"{label}：{spec}（{self.t.t('hotkey.taken')}）")
            else:
                rows.append(f"{label}：{spec}")
        self.hotkey_label.setText("\n".join(rows))

    def _open_log(self):
        """
        打开运行日志 / Open the run-time log.

        日志还不存在时退而打开它所在的目录，而不是弹「文件不存在」——
        「打开了 data 目录」本身就是用户想要的那个结果。
        If the log does not exist yet, open its folder instead of complaining:
        "here is the data folder" is what the user was after anyway.
        """
        if os.path.exists(LOG_PATH):
            try:
                os.startfile(LOG_PATH)  # noqa: S606 - Windows-only convenience
                return
            except OSError:
                pass
        folder = os.path.dirname(LOG_PATH)
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)  # noqa: S606 - Windows-only convenience
        except OSError:
            QMessageBox.information(self, self.t.t("settings.title"), LOG_PATH)

    # ------------------------------------------------------------------
    # 角色包 / character packs
    # ------------------------------------------------------------------
    def _import_pack_dialog(self):
        """选一个 zip 导入 / Pick a zip and import it."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t.t("pack.pick_import"), "", "*.zip")
        if path:
            self._do_import(path)

    def _import_folder_dialog(self):
        """选一个角色文件夹导入 / Pick a folder and import it."""
        path = QFileDialog.getExistingDirectory(
            self, self.t.t("pack.pick_folder"), "")
        if path:
            self._do_import(path)

    def _do_import(self, src: str):
        """导入并汇报结果 / Import and report the outcome."""
        report = import_pack(src, CHARACTERS_DIR)
        t = self.t
        if not report.ok:
            QMessageBox.warning(self, t.t("settings.title"),
                                t.t("pack.failed") % report.error)
            return
        if report.added_conf and report.renamed_from:
            msg = t.t("pack.imported_both") % (report.name, report.renamed_from,
                                               ", ".join(report.added_conf))
        elif report.added_conf:
            msg = t.t("pack.imported_conf") % (report.name,
                                               ", ".join(report.added_conf))
        elif report.renamed_from:
            msg = t.t("pack.imported_renamed") % (report.name,
                                                 report.renamed_from)
        else:
            msg = t.t("pack.imported") % report.name
        QMessageBox.information(self, t.t("settings.title"), msg)
        self._refresh_characters()

    def _export_pack_dialog(self):
        """选一个角色导出成 zip / Pick a character and export it as a zip."""
        chars = list_characters(self.settings)
        if not chars:
            QMessageBox.warning(self, self.t.t("settings.title"),
                                self.t.t("msg.no_character"))
            return
        labels = [lb for lb, _ in chars]
        current = self.settings.get("character", "")
        index = labels.index(current) if current in labels else 0
        # 单独问一次「导出哪个」，不借用「当前角色」下拉：那个下拉改的是
        # 正在用的角色，让它兼职做导出选择器，用户点完保存就莫名其妙换角色了。
        # Ask separately rather than reusing the "current character" combo:
        # that combo changes which character is in use, so overloading it as an
        # export picker would silently switch characters on save.
        label, ok = QInputDialog.getItem(self, self.t.t("pack.export_title"),
                                         self.t.t("pack.select_export"),
                                         labels, index, False)
        if not ok or not label:
            return
        char_dir = dict(chars).get(label, "")
        dest, _ = QFileDialog.getSaveFileName(
            self, self.t.t("pack.pick_export"),
            os.path.join(os.path.expanduser("~"), f"{label}.zip"), "*.zip")
        if not dest:
            return
        if not dest.lower().endswith(".zip"):
            dest += ".zip"
        # supplement=True：导出物一律带齐 conf，别人拿到就能用；
        # 临时副本上补齐，用户自己的目录一个字节都不动。
        # supplement=True so the export always carries a full conf\ and opens
        # elsewhere; it is filled in on a temp copy, leaving the user's folder
        # untouched.
        report = export_pack(char_dir, dest, supplement=True)
        if report.ok:
            QMessageBox.information(self, self.t.t("settings.title"),
                                    self.t.t("pack.exported") % dest)
        else:
            QMessageBox.warning(self, self.t.t("settings.title"),
                                self.t.t("pack.failed_export") % report.error)

    def _supplement_all(self):
        """
        给所有角色补齐缺失的描述文件 / Fill in missing description files everywhere.

        做成「全扫一遍」而不是「对当前角色」：这件事本身就是修坏包，
        而坏包有几只、坏在哪一只，用户多半是不知道的（现象是「导入后就报错」）。
        幂等，只补缺的，已有的一律不动。
        A sweep rather than a per-character action: the point is repairing broken
        packs, and the user generally does not know how many are broken or which
        one -- the symptom is just "it errors after importing".  Idempotent:
        only missing files are added.
        """
        total = 0
        for _label, directory in list_characters(self.settings):
            total += len(supplement_conf(directory))
        if total:
            QMessageBox.information(
                self, self.t.t("settings.title"),
                self.t.t("pack.supplemented") % total)
        else:
            QMessageBox.information(
                self, self.t.t("settings.title"),
                self.t.t("pack.supplement_none"))

    def _refresh_characters(self):
        """导入后刷新角色下拉（新角色立刻可选）/ Refresh the combo after an import."""
        self._fill_characters()

    # ------------------------------------------------------------------
    # 拖放导入 / drag & drop import
    # ------------------------------------------------------------------
    @staticmethod
    def _drop_source(event) -> str:
        """从拖放事件里取第一个能认的来源 / First usable path in a drop event."""
        try:
            mime = event.mimeData()
            if not mime.hasUrls():
                return ""
            for url in mime.urls():
                path = url.toLocalFile()
                if path and is_supported_source(path):
                    return path
        except (AttributeError, TypeError):
            return ""
        return ""

    def dragEnterEvent(self, event):  # noqa: N802
        if self._drop_source(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._drop_source(event):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        src = self._drop_source(event)
        if not src:
            event.ignore()
            return
        event.acceptProposedAction()
        self._do_import(src)

    def _open_custom(self):
        path = self.settings.custom_xml
        if os.path.exists(path):
            try:
                os.startfile(path)  # noqa: S606 - Windows-only convenience
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 关于 / about
    # ------------------------------------------------------------------
    def _tab_about(self):
        from .. import __version__ as _ver
        
        w = QWidget()
        v = QVBoxLayout(w)
        # 版本号 + 开发者：这是「关于」页存在的全部意义。之前只有一段说明
        # 文字，用户想知道「这是哪个版本、谁做的」只能自己去猜。
        # The version and the author are the entire point of an About page;
        # before this it was one paragraph of prose and nothing else.
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        pm = logo_pixmap(88)
        if not pm.isNull():
            logo.setPixmap(pm)
        head.addWidget(logo)
        info = QVBoxLayout()
        info.setSpacing(6)
        name = QLabel(self.t.t("app.name"))
        name.setStyleSheet("font-size: 20px; font-weight: 700;")
        info.addWidget(name)
        ver = QLabel(f"{self.t.t('about.version')} {_ver}")
        ver.setStyleSheet("font-size: 13px; color: palette(mid);")
        info.addWidget(ver)
        author = QLabel(f"by {self.t.t('about.author')}")
        author.setStyleSheet("font-size: 12.5px; color: #E05B4C;")
        info.addWidget(author)
        head.addLayout(info)
        head.addStretch(1)
        v.addLayout(head)

        v.addSpacing(18)
        line = QFrame()
        line.setObjectName("hairline")
        line.setFixedHeight(1)
        v.addWidget(line)
        v.addSpacing(14)

        label = QLabel(self.t.t("about.body"))
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        v.addWidget(label)
        v.addStretch(1)
        self.tabs.addTab(w, self.t.t("tab.about"))

    # ------------------------------------------------------------------
    # 应用 / apply
    # ------------------------------------------------------------------
    def apply(self):
        s = self.settings
        old_lang = s.get("language", "zh_CN")
        old_char = s.get("character", "")
        old_scale = float(s.get("scale", 1.0))
        old_top = bool(s.get("always_on_top", True))
        old_startup = bool(s.get("start_with_windows", False))

        s.set("language", self.lang_combo.currentData() or "zh_CN")
        s.set("bilingual", self.bilingual.isChecked())
        s.set("character", self.char_combo.currentData() or "")
        s.set("character_dirs", [self.dir_list.item(i).text()
                                 for i in range(self.dir_list.count())])
        s.set("scale", self.scale_spin.value())
        s.set("tick_ms", self.tick_spin.value())
        s.set("opacity", self.opacity_spin.value())
        s.set("always_on_top", self.on_top.isChecked())
        s.set("initial_count", self.initial_spin.value())
        s.set("restore_session", self.restore.isChecked())
        s.set("max_count", self.max_spin.value())
        s.set("behavior_overrides", self._collect_behavior_overrides())
        s.set("cal_overrides", self._collect_cal_overrides())
        s.set("self_cloning_enabled", self.clone.isChecked())
        s.set("climb_enabled", self.climb.isChecked())
        s.set("throw_enabled", self.throw.isChecked())
        # 旧键跟着同步写，保持「关掉互动」的老配置在别处读到时语义不变。
        # Keep the legacy key in sync so anything still reading it sees the
        # same meaning.
        s.set("ie_interaction",
              self.climb.isChecked() and self.throw.isChecked())
        s.set("idle_gather", self.idle.isChecked())
        s.set("idle_gather_sec", self.idle_spin.value())
        s.set("titles", [x.strip() for x in self.titles_edit.toPlainText().splitlines()
                         if x.strip()])
        s.set("window_offset", [sp.value() for sp in self.off_spins])
        # 1.0.6：开机自启真的会写回配置了（此前置灰，不写回）。
        # Since 1.0.6 launch-at-login is written back for real.
        s.set("start_with_windows", self.startup.isChecked())
        s.set("hotkeys_enabled", self.hotkeys_enabled.isChecked())
        s.set("taskbar_panel", self.taskbar_panel.isChecked())
        s.set("summon_count", self.summon_count.value())
        s.set("spawn_spread", self.spread.isChecked())
        # 1.0.3：多角色共存与增殖互斥。多角色开关自己管增殖，这里只跟随。
        # 关键：不能直接把 self_cloning_enabled 写成 False —— 那样切回单角色时
        # 读回来还是 False，用户的偏好被永久吞掉。要把原偏好存进
        # self_cloning_pref。
        # The cloning preference must be *stashed*, not overwritten in place,
        # or switching back would read the forced-off value back and lose it.
        was_multi = bool(s.get("multi_pet_enabled", False))
        now_multi = self.multi_pet.isChecked()
        s.set("multi_pet_enabled", now_multi)
        if now_multi:
            s.set("self_cloning_pref", bool(s.get("self_cloning_enabled", True)))
            s.set("self_cloning_enabled", False)
        else:
            pref = s.get("self_cloning_pref", None)
            s.set("self_cloning_enabled",
                  self.clone.isChecked() if pref is None else bool(pref))
        s.save()

        if was_multi != now_multi:
            # Manager.set_multi_pet 会解散并按新模式重新召唤
            self.manager.set_multi_pet(now_multi)

        need_restart = (old_char != s.get("character")
                        or abs(old_scale - float(s.get("scale", 1.0))) > 1e-6
                        or old_top != bool(s.get("always_on_top", True)))
        # 上限同步到表达式常量 / keep the maxCount constant in sync
        self.manager.constants["maxCount"] = float(s.get("max_count", 50))
        want_startup = bool(s.get("start_with_windows", False))
        try:
            startup_ok = self.manager.set_startup(want_startup)
        except Exception:  # noqa: BLE001 - 注册表写失败不该中断整个「应用」
            startup_ok = False
        # 只在「刚被勾上、却没写进注册表」时提醒。每次都提醒的话，用户一旦
        # 遇到策略限制，每点一次应用就弹一次，很快就学会无视弹窗了。
        # Warn only when the box was just ticked and the registry write failed.
        # Warning every time would train the user to dismiss it.
        if want_startup and not startup_ok and not old_startup:
            QMessageBox.warning(self, self.t.t("settings.title"),
                                self.t.t("msg.startup_failed"))
        self.manager.apply_settings(need_restart=need_restart)

        if old_lang != s.get("language"):
            self.t = get_i18n()
            self._rebuild_ui()

    def _rebuild_ui(self):
        """语言切换后重建界面 / Rebuild the whole UI after a language switch."""
        self.custom = CustomConfig(self.settings.custom_xml)
        self.setWindowTitle(self.t.t("settings.title"))
        # 清空并重造 / clear and rebuild
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self.tabs = QTabWidget()
        self._outer.addWidget(self.tabs, 1)
        self._build_tabs()
        self._build_buttons()

    def restart_engine(self):
        self.apply()
        self.manager.restart()
        self._fill_actions()
