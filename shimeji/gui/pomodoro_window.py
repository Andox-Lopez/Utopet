# -*- coding: utf-8 -*-
"""
番茄时钟窗口 / The Pomodoro timer window.

窗口只是**渲染层**：计时逻辑全部在 `shimeji/pomodoro.py` 的 `Pomodoro`
里（无 Qt、可逐帧喂测试）。这里每 500ms 调一次 `tick()` 并把快照画出来。

The window is the *rendering layer only*: the timing logic lives in
`shimeji/pomodoro.py` (Qt-free, testable frame by frame).  This file ticks it
every 500 ms and paints the snapshot.

关闭 = 隐藏，计时继续在托盘里走 —— 关掉窗口不等于取消番茄钟，否则「想在
工作时不看到倒计时」和「想让它继续计时」就互斥了。托盘菜单能随时叫回来。
Closing hides the window; the clock keeps running in the tray.  Closing must
not cancel the timer, or "I don't want to watch the countdown" and "keep it
running" would be mutually exclusive.  The tray menu brings it back.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from ..i18n import get_i18n
from ..icons import app_icon
from ..pomodoro import Pomodoro

#: 「隐藏背景」的总开关。**现在是 False** —— 按区域鼠标穿透要靠
#: `nativeEvent` 处理 `WM_NCHITTEST`，这条路径还没在本机验证过；先把按钮做出来
#: 并置灰，等真跑通了再翻成 True。
#: Master switch for "hide background".  Off for now: per-region pass-through
#: needs `nativeEvent`/`WM_NCHITTEST`, which is not yet verified on this machine.
#: The buttons exist and are disabled until that path is proven.
_HIDE_BG_ENABLED = False

#: 状态 → 三语文案键 / phase -> i18n key
_PHASE_KEY = {
    Pomodoro.IDLE: "pomo.state.idle",
    Pomodoro.WORK: "pomo.state.work",
    Pomodoro.BREAK: "pomo.state.break",
    Pomodoro.LONG_BREAK: "pomo.state.long",
    Pomodoro.PAUSED: "pomo.state.paused",
}


def _fmt(seconds: float) -> str:
    """秒 → mm:ss / seconds -> mm:ss."""
    s = max(0, int(round(seconds)))
    return "%02d:%02d" % (s // 60, s % 60)


log = logging.getLogger(__name__)


class PomodoroWindow(QWidget):
    """番茄时钟窗口。计时归 :class:`~shimeji.pomodoro.Pomodoro` 管。"""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.t = get_i18n()

        # ⭐ 计时器**必须共用 manager 的那只实例**，绝对不要在这里再建一个：
        # 曾经两边各建各的 —— 窗口里真正跑的这只回调调了
        # `manager.pomodoro_event()`（Manager 上根本不存在的方法），
        # AttributeError 被两层 try/except 静默吞掉：🍅 计数照常涨，
        # 但「今日统计」永远 0、托盘气泡 / 宠物联动 / 台词全都没触发；
        # 而设置里改时长改的是 manager 那只死实例，窗口永远用旧时长。
        # 单一实例，两条路自然都通。
        # The window MUST share the manager's Pomodoro instance, never build
        # its own: the split used to silently swallow AttributeErrors (a
        # callback to a method that does not exist), so the counter ticked up
        # while today's stats / tray balloons / pet reactions never fired, and
        # duration changes applied to the instance nobody was ticking.
        self.pom = manager.pomodoro

        self.setWindowIcon(app_icon())
        self.setWindowTitle(self.t.t("pomo.title"))
        # 计时要一直看得见才有用；不想看可以关掉窗口，托盘随时叫回来。
        # A timer is only useful while visible; hide it and the tray brings
        # it back.
        # 置顶状态存在设置里，所以**每次打开窗口**都按它重新设一次标志 ——
        # 不能只在构造时设，用户可能在设置里关掉它之后才打开这个窗口。
        # Applied on every open, not only in the constructor: the user may have
        # switched it off in settings before opening this window.
        self._apply_ontop_flag()
        self.setMinimumWidth(300)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        # 状态行 / status line
        self.state_label = QLabel()
        self.state_label.setStyleSheet("color: palette(mid); font-size: 12px;")
        v.addWidget(self.state_label)

        # 倒计时。等宽数字避免每秒抖动 —— QSS 是 CSS 子集，没有
        # font-variant-numeric，所以直接换成等宽字体。
        # Tabular digits stop the label wobbling every second; QSS has no
        # font-variant-numeric, so use a monospaced face instead.
        self.time_label = QLabel("00:00")
        font = QFont("Consolas")
        font.setPixelSize(52)
        font.setBold(True)
        self.time_label.setFont(font)
        self.time_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.time_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)

        # 已完成番茄数 / completed pomodoros
        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setStyleSheet("color: palette(mid); font-size: 12px;")
        v.addWidget(self.count_label)

        # 今日统计。**每天都在变，所以每 tick 重算**，不做缓存 ——
        # 缓存这个数字的收益是零，而「今天专注了多久」正是用户会反复看的。
        # Today's totals.  Recomputed every tick rather than cached: caching a
        # number that changes all day buys nothing, and it is the number people
        # keep glancing at.
        self.stats_label = QLabel()
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        v.addWidget(self.stats_label)

        v.addSpacing(2)

        # 按钮行 / buttons
        row = QHBoxLayout()
        self.btn_toggle = QPushButton()
        self.btn_toggle.setMinimumWidth(88)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_skip = QPushButton()
        self.btn_skip.clicked.connect(self._on_skip)
        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._on_reset)
        row.addWidget(self.btn_toggle, 1)
        row.addWidget(self.btn_skip, 1)
        row.addWidget(self.btn_reset, 1)
        v.addLayout(row)

        # ── 窗口样式开关（1.0.11 起）────────────────────────────────
        # 单独一行、用 checkable 按钮：它们改的是**窗口自己**，和上面那三个
        # 改计时状态的不是一类东西，混在一排会让人以为点错了会改时间。
        # A separate row of checkable buttons: these change the *window*, while
        # the three above change the *timer state* — mixing them invites
        # misclicks that look like they changed the clock.
        opt_row = QHBoxLayout()
        opt_row.setSpacing(6)
        self.btn_ontop = QCheckBox()
        # ⭐ **建按钮时就要把勾选状态设成设置值**。设成 True 会发一次
        # `toggled` → 槽里又会去读设置并重设标志 —— 那是多余的副作用，
        # 所以先连信号、设值，再断开。
        # ⚠️ 更要紧的是**漏了这行**的后果：QCheckBox 默认 unchecked，而设置
        # 默认 True，于是窗口置顶但复选框是空的 —— 用户以为没置顶，勾一下
        # 反而「没反应」（True→True 不发信号）。这个坑是实测抓出来的。
        # Set the checked state from settings.  Missing this shows a window
        # that *is* on top with an empty box; ticking it then looks like a
        # no-op because True -> True emits nothing.
        self.btn_ontop.blockSignals(True)
        self.btn_ontop.setChecked(
            bool(manager.settings.get("pomodoro_ontop", True)))
        self.btn_ontop.blockSignals(False)
        self.btn_ontop.toggled.connect(self._on_ontop_toggled)
        self.btn_hidebg = QCheckBox()
        self.btn_hidebg.toggled.connect(self._on_hidebg_toggled)
        opt_row.addWidget(self.btn_ontop)
        opt_row.addWidget(self.btn_hidebg)
        opt_row.addStretch(1)
        v.addLayout(opt_row)

        #: 「隐藏背景」要用**按区域**的鼠标穿透，而 Qt 只提供整窗级别的
        #: `WA_TransparentForMouseEvents`（一设整窗连那颗按钮一起穿透）。
        #: 实现方式见 `_apply_mouse_passthrough` —— 它依赖 `nativeEvent`
        # 处理 `WM_NCHITTEST`，**只有真正跑通并验证过才把开关打开**。
        #: 在那之前整组按钮置灰。
        #: Per-region pass-through needs WM_NCHITTEST; Qt only offers a
        #: whole-window flag that would also disable the very button that
        #: restores the window.  Left disabled until that path is verified.
        self._passthrough_ready = _HIDE_BG_ENABLED
        self.btn_ontop.setEnabled(self._passthrough_ready)
        self.btn_hidebg.setEnabled(self._passthrough_ready)
        if not self._passthrough_ready:
            # ⚠️ 用 `self.t`，不是裸 `t` —— `__init__` 里没有裸名 `t`，
            # 写成裸名会在构造时抛 NameError（项目铁律：Qt 槽里用裸名会静默
            # 吞掉整个槽函数）。
            # `self.t`, never a bare `t`: there is no bare `t` here, and a bare
            # one raises NameError mid-constructor.
            self.btn_ontop.setToolTip(self.t.t("pomo.wip"))
            self.btn_hidebg.setToolTip(self.t.t("pomo.wip"))

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        v.addWidget(self.hint_label)

        self._refresh_texts()

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()
        self._render()
        #: 第一次显示时居中一次；之后尊重用户拖过的位置。
        #: Centre once on first show, then respect where the user put it.
        self._centered_once = False

    # ------------------------------------------------------------------
    def center_on_cursor(self):
        """
        居中到**光标所在屏幕** / Centre on the screen the cursor is on.

        参照 kwin-move-window-to-center。用 `availableGeometry()` 而不是
        `geometry()`：前者不含任务栏，否则计时器的下半截会被任务栏盖住。
        After kwin-move-window-to-center.  `availableGeometry()` rather than
        `geometry()`: the former excludes the taskbar, which would otherwise
        cover the bottom of the window.
        """
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        self.adjustSize()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)

    # ------------------------------------------------------------------
    def _refresh_texts(self):
        t = self.t
        self.setWindowTitle(t.t("pomo.title"))
        self.btn_toggle.setText(t.t("pomo.start"))
        self.btn_skip.setText(t.t("pomo.skip"))
        self.btn_reset.setText(t.t("pomo.reset"))
        self.btn_ontop.setText(t.t("pomo.ontop"))
        self.btn_hidebg.setText(t.t("pomo.hide_bg"))
        self.hint_label.setText(t.t("pomo.hint"))
        self._render()

    def refresh_ui_texts(self):
        """语言切换后刷新 / Refresh after a language switch."""
        self.t = get_i18n()
        self._refresh_texts()
        if not self._passthrough_ready:
            self.btn_ontop.setToolTip(self.t.t("pomo.wip"))
            self.btn_hidebg.setToolTip(self.t.t("pomo.wip"))

    # ------------------------------------------------------------------
    # 窗口外观开关 / window appearance switches (1.0.11)
    # ------------------------------------------------------------------
    def _apply_ontop_flag(self):
        """按设置里的 `pomodoro_ontop` 设置置顶标志。

        ⚠️ **改窗口标志后必须重新 show()**：Qt 只在窗口显示时把标志位写进
        真实的 HWND，改了不重新显示的话用户看不出任何变化（而 `show()` 会让
        窗口重新出现在前面，所以要记住它之前是不是可见的）。
        Changing window flags only affects the live HWND while the window is
        shown, so it has to be shown again — but remember whether it was
        visible so an invisible window stays invisible.
        """
        want = bool(self.manager.settings.get("pomodoro_ontop", True))
        flags = self.windowFlags()
        has = bool(flags & Qt.WindowStaysOnTopHint)
        if want == has:
            return
        if want:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        was_visible = self.isVisible()
        if was_visible:
            self.show()
            self.raise_()

    def _on_ontop_toggled(self, checked: bool):
        """置顶开关 / Always-on-top toggle."""
        s = self.manager.settings
        s.set("pomodoro_ontop", bool(checked))
        # 直接按开关值设标志；「设置」页改动后重开窗口也会走同一条路径。
        self._apply_ontop_flag()

    def _on_hidebg_toggled(self, checked: bool):
        """隐藏背景开关 / Hide-background toggle.

        ⛔ 暂未接通：按区域穿透依赖 `WM_NCHITTEST`，本机尚未验证。
        ⛔ Not wired up yet: per-region pass-through needs `WM_NCHITTEST`,
        unverified on this machine.  `_HIDE_BG_ENABLED` keeps the button off.
        """
        if not self._passthrough_ready:
            # 防御：真被点到了（开关翻成 True 但穿透没跑通）就弹回去，别留一个
            # 什么都不干的勾。
            self.btn_hidebg.blockSignals(True)
            self.btn_hidebg.setChecked(False)
            self.btn_hidebg.blockSignals(False)
            return
        self._apply_mouse_passthrough(bool(checked))

    def _apply_mouse_passthrough(self, on: bool):
        """隐藏背景：只留倒计时与那颗按钮，其余区域鼠标穿透。

        激活时：
          - 去掉标题栏（`FramelessWindowHint`）—— Qt 只提供整窗级别的
            `WA_TransparentForMouseEvents`，一设整窗连那颗按钮一起穿透，
            所以「按区域穿透」必须走 `WM_NCHITTEST`：命中不在按钮上就返回
            `HTTRANSPARENT`，让 Windows 把这个点交给下面的窗口。
          - 隐藏标题栏 + 进度条 + 番茄数 + 今日统计 + 提示 + 三个计时按钮，
            只保留倒计时数字与那颗「隐藏背景」按钮（用户需要能点回来）。
          - **倒计时数字区域也穿透**：它是信息展示，不该挡住用户点下面的东西。

        ⛔ 当前 `_HIDE_BG_ENABLED = False`，所以这段代码**不会被执行** ——
        按区域穿透在本机尚未验证（见 `nativeEvent` 处的说明）。按钮是置灰的。
        Only the countdown and the restore button survive; everything else is
        hidden, and the frameless flag drops the title bar.
        """
        if not on:
            return
        # 无边框（去掉标题栏）/ frameless: no title bar
        if not (self.windowFlags() & Qt.FramelessWindowHint):
            was_visible = self.isVisible()
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            if was_visible:
                self.show()
        # 只留倒计时与恢复按钮 / keep only the countdown and the restore button
        for w in (self.state_label, self.bar, self.count_label,
                  self.stats_label, self.hint_label,
                  self.btn_toggle, self.btn_skip, self.btn_reset,
                  self.btn_ontop):
            w.setVisible(False)
        self.btn_hidebg.setVisible(True)
        # 数字那一块不接收鼠标 / the digits themselves take no clicks
        self.time_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.adjustSize()

    def _restore_full_panel(self):
        """退出「隐藏背景」，恢复完整面板。/ Leave hide-background mode."""
        self.setWindowFlags(self.windowFlags() & ~Qt.FramelessWindowHint)
        for w in (self.state_label, self.bar, self.count_label,
                  self.stats_label, self.hint_label,
                  self.btn_toggle, self.btn_skip, self.btn_reset,
                  self.btn_ontop, self.btn_hidebg):
            w.setVisible(True)
        self.time_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.adjustSize()
        self.show()

    # ------------------------------------------------------------------
    def _on_tick(self):
        snap = self.pom.tick()
        self._render(snap)

    # 按钮必须**立刻**重绘：逻辑层一个调用就换了状态，若只等 500ms 的
    # 定时器，用户点「开始」后界面还停在 00:00，看起来像没反应。
    # Buttons must repaint immediately: the state already changed, and waiting
    # for the 500 ms timer makes "Start" look like a no-op.
    def _on_toggle(self):
        self.pom.toggle()
        self._render()

    def _on_skip(self):
        self.pom.skip()
        self._render()

    def _on_reset(self):
        self.pom.reset()
        self._render()

    def _render(self, snap: dict | None = None):
        """把状态画出来。**只读快照，不做任何计时判断** —— 判断归逻辑层。
        Paint the snapshot.  Read-only: all decisions belong to the logic."""
        snap = snap or self.pom.snapshot()
        t = self.t
        phase = snap["phase"]
        self.time_label.setText(_fmt(snap["remaining"]))
        self.bar.setValue(int(round(snap["progress"] * 1000)))
        self.state_label.setText(t.t(_PHASE_KEY.get(phase, "pomo.state.idle")))

        # 🍅 用文字而不是图标：小尺寸的程序化图标会糊，而 emoji 在文字流里
        # 正好是「已完成几个」最直白的表达（缺字形的系统会退化成方块，可接受）。
        # Text, not an icon: programmatic icons blur at this size, and the
        # emoji reads instantly as "how many are done".
        n = snap["completed"]
        self.count_label.setText(
            "🍅 × %d" % n if n else t.t("pomo.none_done"))
        self._render_stats()

        # 按钮文案随状态换：同一个位置在「开始 / 暂停 / 继续」之间切换，
        # 比三颗按钮互相隐藏更不容易点错。
        # One button that relabels beats three buttons hiding each other.
        if phase == Pomodoro.PAUSED:
            self.btn_toggle.setText(t.t("pomo.resume"))
        elif phase in Pomodoro.RUNNING:
            self.btn_toggle.setText(t.t("pomo.pause"))
        else:
            self.btn_toggle.setText(t.t("pomo.start"))

    def _render_stats(self):
        """今日累计 / Today's totals."""
        stats = getattr(self.manager, "pomostats", None)
        if stats is None:
            self.stats_label.setText("")
            return
        try:
            today = stats.today_text()
            streak = stats.streak()
        except Exception:  # noqa: BLE001 - 统计出问题不该让窗口变空白
            # 标签清空是对的（不能显示半截数据），但要留痕：用户看到的是
            # 「统计永远是空的」，而窗口本身没有任何提示。
            # Clearing the label is right (never show half a figure), but
            # leave a trace: the user just sees a permanently empty field.
            log.warning("读取番茄钟统计失败", exc_info=True)
            self.stats_label.setText("")
            return
        t = self.t
        text = t.t("pomo.stats_today").format(today)
        if streak >= 2:
            text += " · " + t.t("pomo.streak").format(streak)
        self.stats_label.setText(text)

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt override
        """关闭 = 隐藏。计时在托盘里继续。/ Hide; the clock keeps running."""
        self.hide()
        event.ignore()
