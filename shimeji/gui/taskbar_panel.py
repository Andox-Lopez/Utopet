# -*- coding: utf-8 -*-
"""
任务栏常驻控制面板 / Always-on taskbar control panel
==============================================================================
一个普通（非 Tool、非置顶）的小窗口，因此会在 Windows 任务栏上占据一个按钮，
可以像普通软件一样被「固定到任务栏」。它把原本只存在于托盘右键菜单里的操作
变成一排按钮，鼠标一点就能召唤 / 解散 / 设置 / 退出。

A plain (non-Tool, non-topmost) little window, so it owns a real taskbar button
that can be pinned like any other app.  It turns the operations that used to live
only in the tray context menu into a row of clickable buttons.

关掉面板只是隐藏它，**程序继续在托盘常驻** —— 想找回面板就点托盘图标右键
「显示任务栏面板」，想彻底退出就点「退出」。
Closing the panel only hides it; the app stays resident **in the tray**.  Bring
the panel back via the tray menu ("Show taskbar panel"), or quit for good.

为什么不再有迷你条 / Why there is no slim bar any more
--------------------------------------------------------------------------
之前这里有第二条「迷你条」，关面板时缩成一条常驻任务栏。现在去掉了：托盘图标
本身已经是常驻入口，托盘右键菜单又能一键叫回面板，第二条常驻物只是重复，
还让「到底有几个窗口」变得难以预期。

There used to be a slim bar that the panel collapsed into.  It is gone: the tray
icon is already a permanent, always-visible entry, and its right-click menu
brings the panel straight back.  A second resident widget only duplicated that
and made "how many windows does this app own?" harder to reason about.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import win32
from ..icons import app_icon, logo_pixmap
from ..i18n import get_i18n

__all__ = ["TaskbarPanel"]


class TaskbarPanel(QWidget):
    """任务栏控制面板 / The taskbar control panel."""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.t = get_i18n()
        # _place()/ _clamp_into_work_area() 自己 move() 时会触发 moveEvent，
        # 那个不是用户拖的，不能当成「用户选了新位置」存起来 —— 否则每次打开
        # 都把上一次的右下角坐标存成「用户偏好」，位置永远不变。
        # Our own move() calls fire moveEvent too; those are not user drags and
        # must not be recorded as a preference, or the corner would get saved
        # as the user's choice and never change.
        self._placing = False

        # 普通窗口（不带 Qt.Tool），这样任务栏才会给它一个按钮
        # A normal window (no Qt.Tool) so the taskbar gives it a button
        self.setWindowIcon(app_icon())
        self.setWindowTitle(self.t.t("panel.title"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        # 关键：显示时不抢焦点。否则面板会抢走用户当前窗口的焦点，而且正好
        # 弹在鼠标下方时，用户随手一点就误触了「设置」甚至「退出」。
        # Critical: never steal focus.  Otherwise the panel steals focus from
        # whatever the user is doing, and if it happens to appear under the
        # cursor a careless click can hit "Settings" -- or even "Quit".
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # 标题行 / header row
        head = QHBoxLayout()
        self.logo_label = QLabel()
        self.logo_label.setPixmap(logo_pixmap(40))
        self.logo_label.setFixedSize(40, 40)
        self.title_label = QLabel(self.t.t("panel.title"))
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        head.addWidget(self.logo_label)
        head.addSpacing(6)
        head.addWidget(self.title_label, 1)
        outer.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        outer.addWidget(line)

        # 状态 / status
        self.count_label = QLabel()
        self.count_label.setStyleSheet("font-size: 13px;")
        self.char_label = QLabel()
        self.char_label.setStyleSheet("color: palette(mid); font-size: 12px;")
        outer.addWidget(self.count_label)
        outer.addWidget(self.char_label)
        # 1.0.3：状态摘要（心情好/累/生病…），由 CalMode 推出
        self.state_label = QLabel()
        self.state_label.setStyleSheet("color: palette(mid); font-size: 12px;")
        outer.addWidget(self.state_label)

        outer.addSpacing(4)

        # 第一行：[数量输入] [召唤]
        # 顺序是「输入框在按钮前面」—— 按钮只写「召唤」，数量一眼就能看到，
        # 不用去猜它到底是「召唤一只」还是「召唤 5 只」。
        # 以前是「一次召唤 [5] [召唤一只]」，两个控件都在讲数量，重复且啰嗦。
        # Row one: [count input] [Summon].  The number sits in front of the
        # button, so the button can just say "Summon" -- it used to read
        # "Summon one" right next to a spinbox already showing 5.
        row1 = QHBoxLayout()
        self.summon_spin = QSpinBox()
        self.summon_spin.setRange(1, 100)
        self.summon_spin.setFixedWidth(64)
        self.summon_spin.setValue(int(self.manager.settings.get("summon_count", 5)))
        self.summon_spin.valueChanged.connect(self._on_count_changed)
        self.btn_summon = QPushButton()
        self.btn_summon.setMinimumWidth(84)
        self.btn_summon.clicked.connect(self._summon_many)
        row1.addStretch(1)
        row1.addWidget(self.summon_spin)
        row1.addWidget(self.btn_summon)
        outer.addLayout(row1)

        # 第二行：逐只 / 全部解散 / second row: dismiss
        row2 = QHBoxLayout()
        self.btn_dismiss = QPushButton()
        self.btn_dismiss_all = QPushButton()
        self.btn_dismiss.clicked.connect(lambda: self.manager.dismiss(None))
        self.btn_dismiss_all.clicked.connect(self.manager.dismiss_all)
        for b in (self.btn_dismiss, self.btn_dismiss_all):
            row2.addWidget(b)
        outer.addLayout(row2)

        # 第三行：显隐 / 设置 / 退出
        # 「聚到鼠标旁」曾在 1.0.0 作为面板按钮存在，但它在托盘和宠物右键菜单里
        # 都有，导致同一功能出现三处入口。1.0.5 从面板拿掉，只保留菜单入口。
        # "Gather" used to sit here as well, but it also lives in the tray and
        # pet context menus — three entry points for one action was too many.
        # 1.0.5 drops it from the panel; the menus keep it.
        row3 = QHBoxLayout()
        self.btn_hide = QPushButton()
        self.btn_settings = QPushButton()
        self.btn_quit = QPushButton()
        self.btn_hide.clicked.connect(self.manager.toggle_hidden)
        self.btn_settings.clicked.connect(self.manager.open_settings)
        self.btn_quit.clicked.connect(self.manager.quit)
        for b in (self.btn_hide, self.btn_settings, self.btn_quit):
            row3.addWidget(b)
        outer.addLayout(row3)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        outer.addWidget(self.hint_label)

        # 必须在这里填一次文字。
        #
        # 所有按钮都是 `QPushButton()`（无文字）建的，文字只在 `_refresh_texts()`
        # 里设置；而它此前只在「设置里点应用」那条路径上被调到，于是**程序一启动
        # 面板就是一排空白按钮**，用户得先去点一次「应用」才看得见字 —— 面板是
        # 用户唯一能看见的入口，空白面板等于「按不到任何东西」。
        # 构造末尾补这一次调用，`refresh_status()` 才去谈状态。
        #
        # Fill the labels here.  Every button is built as a bare `QPushButton()`
        # and only `_refresh_texts()` gives them text; that used to be reached
        # exclusively from "Apply" in the settings, so **on a fresh start the
        # panel was a row of blank buttons** and you had to apply settings once
        # before any label appeared.  The panel is the only entry point the user
        # can see, so a blank one means "nothing is clickable".
        self._refresh_texts()
        self.refresh_status()

        # 数量会随分裂 / 解散自己变化，低频轮询足够
        # Counts change on their own (cloning, dismissing); a slow poll is enough.
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

    def _on_count_changed(self, value: int):
        """记住上次选择的批量数量 / Remember the chosen batch size."""
        self.manager.settings.set("summon_count", int(value))

    def _summon_many(self):
        n = int(self.summon_spin.value())
        self.manager.summon_many(n)
        self.refresh_status()

    def _refresh_texts(self):
        t = self.t
        self.setWindowTitle(t.t("panel.title"))
        self.title_label.setText(t.t("panel.title"))
        # 面板按钮用短文案，避免英文被截断 / short labels so English fits
        self.btn_summon.setText(t.t("panel.summon"))
        self.btn_dismiss.setText(t.t("panel.dismiss_one"))
        self.btn_dismiss_all.setText(t.t("panel.dismiss_all"))
        self.btn_hide.setText(t.t("panel.show_hide"))
        self.btn_settings.setText(t.t("panel.settings"))
        self.btn_quit.setText(t.t("panel.quit"))
        self.hint_label.setText(t.t("panel.hint"))
        # 输入框没有可见标签了（按钮只写「召唤」），数量含义靠 tooltip 传达
        # The spin box lost its visible label (the button just says "Summon"),
        # so the count's meaning is carried by the tooltip.
        self.summon_spin.setToolTip(t.t("panel.summon_count"))
        self.summon_spin.setAccessibleName(t.t("panel.summon_count"))

    def refresh_ui_texts(self):
        """语言切换后刷新 / Refresh after a language switch."""
        self.t = get_i18n()
        self._refresh_texts()
        self.refresh_status()

    # ------------------------------------------------------------------

    def refresh_status(self):
        n = str(self.manager.count())
        self.count_label.setText(self.t.t("panel.count").replace("{0}", n))
        self.char_label.setText(self.t.t("panel.character").replace(
            "{0}", self.manager.settings.get("character", "-")))
        # 状态摘要：取第一只宠物的状态。多角色时这只是「代表」，不做逐只列表 ——
        # 面板只有 320px 宽，塞不下 4 行数值。
        # The first pet's state stands for all of them; the 320px panel has no
        # room for a per-pet list.
        m = self.manager.mascots[0] if self.manager.mascots else None
        self.state_label.setText(
            m.status.summary(self.manager.settings.get("language", "zh_CN"))
            if m is not None else "")
        # 只做「不出界」夹取，不再把面板拽回右下角。
        # 面板每 500ms 刷新一次，如果这里无条件 _place()，用户刚把面板拖到
        # 别处，半秒内就被拽回原点 —— 表现为「面板被固定在右下角，拖不动」。
        # Clamp only; do not drag it back to the corner.  refresh_status() runs
        # every 500ms, so an unconditional _place() would yank a user-moved
        # panel straight back — that is the "panel is stuck in the corner" bug.
        self._clamp_into_work_area()
    def _place(self):
        """
        把面板放到工作区右下角（仅在「打开」时调用）。

        这里**刻意不探测鼠标位置**。早期版本为了「避免面板压住光标导致误触」
        会读一次光标坐标，一旦鼠标移进面板就把它弹到别处 —— 结果用户想点
        「设置」时面板自己跳走了，按钮根本点不着。面板是常驻控件，位置必须
        稳定；防误触要靠「显示时不抢焦点」，而不是让它乱跑。

        Place the panel at the work-area bottom-right.  Called only when the
        panel is *opened*, never from the periodic refresh — otherwise a
        user-moved panel would be dragged back every 500ms.

        如果用户上次把面板拖到过别处，就沿用那个位置；只有从没拖过的时候
        才落到右下角。位置有效性在这里就校验：屏幕分辨率变过、记忆的坐标
        已经落在工作区外时，照样回退到右下角，不会把面板藏到看不见的地方。

        Reuse the position the user dragged it to last time; only fall back to
        the corner when it has never been moved.  The remembered position is
        validated here: after a resolution change it may sit outside the work
        area, in which case we fall back to the corner rather than hiding the
        panel off-screen.
        """
        if not self.isVisible():
            return
        try:
            left, top, right, bottom = win32.get_work_area()
        except Exception:
            return
        self.adjustSize()
        w, h = self.width(), self.height()
        # Qt 的尺寸只含客户区，GetWindowRect 还含不可见边框（Win11 差 30~40px），
        # 贴边要用含边框的尺寸，否则底部会被任务栏吃掉一截。
        # Qt measures the client area only; patch it with the frame size.
        try:
            r = win32.window_rect(int(self.winId()))
            if r:
                w = max(w, r[2] - r[0])
                h = max(h, r[3] - r[1])
        except Exception:
            pass
        # 1.0.5 的原版实现（1.1.0 把它抽成了 _remembered_pos，
        # 随界面重做一并回退，这里把内联逻辑写回来）：
        # 记得用户上次把面板拖到哪儿，没有记录才落到右下角。
        # The 1.0.5 form: honour the remembered spot, fall back to the corner.
        # 1.1.0 factored this out into _remembered_pos(); restoring the inline
        # version since that helper goes away with the UI rework.
        pos = self.manager.settings.get("panel_pos", None)
        if (isinstance(pos, (list, tuple)) and len(pos) == 2
                and all(isinstance(v, (int, float)) for v in pos)):
            px, py = int(pos[0]), int(pos[1])
            # 记忆位置可能因换分辨率/改任务栏而落到屏幕外，这时退回右下角，
            # 绝不把面板藏到用户看不到的地方。
            # The remembered spot can fall off-screen after a resolution or
            # taskbar change; fall back rather than hide the panel.
            if left <= px <= right - w and top <= py <= bottom - h:
                x, y = px, py
            else:
                x, y = right - w - 12, bottom - h - 12
        else:
            x, y = right - w - 12, bottom - h - 12

        self._placing = True
        try:
            if (self.x(), self.y()) != (int(x), int(y)):
                self.move(int(x), int(y))
        finally:
            self._placing = False

    def _clamp_into_work_area(self):
        """
        只保证面板不出工作区，不改变用户选的位置。

        与 `_place()` 的区别是全部：`_place()` 是「放到右下角」，这个只是
        「别跑出屏幕」。数字变长、语言切换导致面板变高时用它，用户把面板拖到
        哪儿它就还在哪儿。

        Keep the panel inside the work area without touching where the user
        put it.  This is the whole difference from _place(): _place() moves it
        to the corner, this only stops it from leaving the screen.  Use it
        when the panel grows (longer count, language switch).
        """
        if not self.isVisible():
            return
        try:
            left, top, right, bottom = win32.get_work_area()
        except Exception:
            return
        try:
            r = win32.window_rect(int(self.winId()))
        except Exception:
            return
        if not r:
            return
        w, h = r[2] - r[0], r[3] - r[1]
        x = min(max(self.x(), left), max(left, right - w))
        y = min(max(self.y(), top), max(top, bottom - h))
        if (self.x(), self.y()) != (int(x), int(y)):
            self._placing = True
            try:
                self.move(int(x), int(y))
            finally:
                self._placing = False

    def show_near_taskbar(self):
        """打开面板：出现在工作区右下角（用户之后可以随便拖）。

        只在「这次打开」时定位一次。之前的实现除了立即定位，还挂了
        `singleShot(0)` 和 `singleShot(400)` 两次补定位 —— 于是用户刚把面板
        拖走，400ms 内就被拽回右下角，观感就是「面板被固定在角落拖不动」。
        现在补定位只做不出界夹取，位置交给用户。

        Open the panel at the work-area bottom-right; the user may drag it
        anywhere afterwards.  Positioning happens once per open.  The old code
        also queued singleShot(0) and singleShot(400) re-positions, which
        yanked a just-dragged panel back to the corner within 400ms — the
        "panel is stuck in the corner" symptom.  The deferred passes now only
        clamp, they never relocate.
        """
        self.show()
        # 确保任务栏一定有按钮（Qt 6 默认不给 WS_EX_APPWINDOW）
        # Guarantee a taskbar button (Qt 6 does not set WS_EX_APPWINDOW).
        try:
            win32.make_taskbar_window(int(self.winId()))
        except Exception:
            pass
        self._place()
        # 显示后字体与换行才最终生效，高度会变，所以再夹一次
        # Fonts and word wrap only settle after show(), so clamp once more.
        QTimer.singleShot(0, self._clamp_into_work_area)
        QTimer.singleShot(400, self._clamp_into_work_area)
        # 注意：这里刻意不 raise_()/activateWindow()，避免抢焦点
        # Deliberately no raise_()/activateWindow(): that is what steals focus.

    def closeEvent(self, event):  # noqa: N802 - Qt override
        """
        关闭 = 隐藏面板，程序继续在托盘常驻。

        这里**不能退出进程**，但也别再自动弹出任何常驻控件。托盘图标始终在，
        右键它选「显示任务栏面板」就能叫回来 —— 托盘已经是唯一的常驻入口，
        再加第二条常驻物只会让人搞不清当前到底有几个窗口。

        Earlier this shrank the panel into a slim bar.  That is gone: the tray
        icon is a permanent entry and its menu brings the panel back in one
        click, so a second resident widget only muddied "how many windows does
        this app own right now?".
        """
        self.hide()
        event.ignore()

    def moveEvent(self, event):  # noqa: N802 - Qt override
        """记住用户把面板拖到了哪里 / Remember where the user dragged it.

        不记的话，每次打开都跳回右下角 —— 用户明明刚把它拖到左手边，重启或
        重新打开又回到原点，看起来跟「固定在角落」没区别。

        Without this the panel jumps back to the corner on every open, which
        looks identical to being pinned there.
        """
        super().moveEvent(event)
        if self._placing or not self.isVisible():
            return
        try:
            self.manager.settings.set("panel_pos", [int(self.x()), int(self.y())])
        except Exception:
            pass
