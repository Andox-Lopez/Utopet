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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from ..i18n import get_i18n
from ..icons import app_icon
from ..pomodoro import Pomodoro

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


class PomodoroWindow(QWidget):
    """番茄时钟窗口。计时归 :class:`~shimeji.pomodoro.Pomodoro` 管。"""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.t = get_i18n()

        s = manager.settings
        # 时长从设置里来；用户在设置里改了数，这里下一段就会用新值。
        # Durations come from settings; a change applies from the next phase.
        self.pom = Pomodoro(
            work_min=int(s.get("pomodoro_work_min", 25)),
            break_min=int(s.get("pomodoro_break_min", 5)),
            long_break_min=int(s.get("pomodoro_long_break_min", 15)),
            long_every=int(s.get("pomodoro_long_every", 4)),
            on_event=self._on_event,
        )

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
            self.btn_ontop.setToolTip(t.t("pomo.wip"))
            self.btn_hidebg.setToolTip(t.t("pomo.wip"))

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
        self.hint_label.setText(t.t("pomo.hint"))
        self._render()

    def refresh_ui_texts(self):
        """语言切换后刷新 / Refresh after a language switch."""
        self.t = get_i18n()
        self._refresh_texts()

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
            self.stats_label.setText("")
            return
        t = self.t
        text = t.t("pomo.stats_today").format(today)
        if streak >= 2:
            text += " · " + t.t("pomo.streak").format(streak)
        self.stats_label.setText(text)

    # ------------------------------------------------------------------
    def _on_event(self, event: str, pom: Pomodoro):
        """阶段切换 → 托盘气泡 + 宠物反应。由逻辑层回调，别在这里做判断。
        Phase transition -> tray balloon + pet reaction.  Callback only."""
        try:
            self.manager.pomodoro_event(event, pom)
        except Exception:  # noqa: BLE001
            # 通知失败不该影响计时（逻辑层同样兜了一层，这里是第二道）。
            # A failing notification must not take the clock down; the logic
            # layer guards too, this is the second net.
            from ..engine.manager import log
            log.exception("pomodoro notification failed")

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt override
        """关闭 = 隐藏。计时在托盘里继续。/ Hide; the clock keeps running."""
        self.hide()
        event.ignore()
