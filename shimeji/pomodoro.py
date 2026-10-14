# -*- coding: utf-8 -*-
"""
番茄时钟的核心状态机 / The core state machine of the Pomodoro timer.

**刻意不 import Qt** —— 计时逻辑必须能在没有 QApplication 的情况下逐帧喂进去测
（`analysis/verify_pomodoro.py` 就是这么测的），否则「时间到了会不会正确切阶段」
这种关键行为只能靠人肉盯着窗口等 25 分钟验证。

Deliberately Qt-free: the timing logic has to be drivable frame by frame
without a QApplication, otherwise "does the phase actually switch when the
clock runs out" could only be verified by staring at a window for 25 minutes.

设计参照 coolcode/tomato-clock（一个极简命令行番茄钟）：
  25 分钟工作 + 5 分钟休息，自动衔接，阶段切换时给一次通知。
  在此之上加了标准的「每 N 轮一次长休息」（tomato-clock 没有，但 4×25 分钟
  只配 5 分钟休息确实撑不住）。

Modelled on coolcode/tomato-clock, a minimalist command-line Pomodoro:
  25 min work + 5 min break, chained automatically, one notification per
  transition.  On top of that: a standard long break every N rounds
  (tomato-clock does not have one, but four 25-minute rounds with only
  5-minute breaks is genuinely too much).

计时用 `time.monotonic()` 而不是「每秒减一」：
  QTimer 会漂移，笔记本睡眠 / 系统卡顿更会让「每秒减一」与真实时间脱节；
  存一个截止时刻、每次 tick 用单调钟重新算剩余，睡一觉醒来依然是对的。
  `time.monotonic()` rather than "subtract one per tick": QTimer drifts, and
  laptop sleep / stalls break a one-per-second decrement entirely.  Store a
  deadline and recompute from a monotonic clock; it stays correct after sleep.
"""

from __future__ import annotations

import logging
import time

__all__ = ["Pomodoro"]

log = logging.getLogger("shimeji")

#: 时长的硬边界（分钟）/ hard bounds for the durations, in minutes
MIN_MINUTES = 1
MAX_MINUTES = 180


class Pomodoro:
    """
    一个番茄钟。阶段：空闲 → 工作 → 休息 → 工作 → … → 长休息 → 工作 → …

    **不持有任何 Qt 对象**：UI 层用 QTimer 每秒调一次 :meth:`tick`，
    逻辑层只负责「到了没有、该切哪一段」，并通过 :attr:`on_event` 回调通知。
    回调抛异常会被记进日志但**不能**拖垮计时 —— 计时是这里唯一不能死的东西。

    A Pomodoro timer.  Phases: idle → work → break → work → … → long break → …
    Holds no Qt objects: the UI drives :meth:`tick` once a second from a QTimer,
    and the logic only decides "is it over, and what comes next", reporting
    through the :attr:`on_event` callback.  A raising callback is logged and
    *must not* take the clock down with it.
    """

    IDLE = "idle"
    WORK = "work"
    BREAK = "break"
    LONG_BREAK = "long_break"
    PAUSED = "paused"

    #: 正在计时的阶段 / phases that are actually counting down
    RUNNING = (WORK, BREAK, LONG_BREAK)

    def __init__(self, work_min: int = 25, break_min: int = 5,
                 long_break_min: int = 15, long_every: int = 4,
                 on_event=None):
        self.work_sec = self._clamp_minutes(work_min) * 60
        self.break_sec = self._clamp_minutes(break_min) * 60
        self.long_break_sec = self._clamp_minutes(long_break_min) * 60
        self.long_every = max(1, min(12, int(long_every or 4)))
        #: 阶段切换回调：`on_event(event, pomodoro)`。event 取值见下方常量。
        self.on_event = on_event

        self._phase = self.IDLE
        self._prev = self.WORK          # 暂停前的阶段 / the phase before pausing
        self._deadline: float | None = None
        self._remaining = 0.0
        #: 已完成的番茄数 / completed pomodoros
        self.completed = 0

    # ------------------------------------------------------------------
    # 对外只读状态 / read-only state
    # ------------------------------------------------------------------
    @property
    def phase(self) -> str:
        """当前阶段 / the current phase."""
        return self._phase

    @property
    def running(self) -> bool:
        """正在倒计时（未暂停、未空闲）/ actively counting down."""
        return self._phase in self.RUNNING

    @property
    def remaining(self) -> float:
        """本阶段剩余秒数 / seconds left in the current phase."""
        if self._phase == self.IDLE:
            return 0.0
        if self._phase == self.PAUSED:
            return self._remaining
        if self._deadline is None:
            return 0.0
        return max(0.0, self._deadline - time.monotonic())

    @property
    def total(self) -> float:
        """本阶段总秒数 / total seconds of the current phase."""
        return self._remaining if self._phase == self.PAUSED else self._duration_of(self._phase)

    @property
    def progress(self) -> float:
        """0~1 的进度 / progress within the current phase."""
        total = self.total
        if total <= 0:
            return 0.0
        return min(1.0, max(0.0, 1.0 - self.remaining / total))

    def snapshot(self) -> dict:
        """UI 渲染要用的全部数据 / everything the UI needs to render."""
        return {"phase": self._phase, "remaining": self.remaining,
                "total": self.total, "completed": self.completed,
                "progress": self.progress}

    # ------------------------------------------------------------------
    # 操作 / actions
    # ------------------------------------------------------------------
    def start(self):
        """
        开始（或继续）/ Start, or resume a paused timer.

        从空闲开始总是先进入工作段 —— 「点一下就开始 25 分钟」是番茄工作法的
        全部入口，不该再让用户选先工作还是先休息。
        From idle this always enters a work phase first: one click and the
        25 minutes are running.  Never ask work-or-break-first.
        """
        if self._phase == self.PAUSED:
            self._phase = self._prev
            self._deadline = time.monotonic() + self._remaining
            self._fire("resumed")
            return
        if self._phase == self.IDLE:
            self._begin(self.WORK)
            self._fire("started")

    def pause(self):
        """暂停（保留剩余时间）/ Pause, keeping the remaining time."""
        if self._phase not in self.RUNNING:
            return
        self._remaining = self.remaining
        self._prev = self._phase
        self._phase = self.PAUSED
        self._deadline = None
        self._fire("paused")

    def toggle(self):
        """空格键最常用的那颗按钮 / what the space bar should do."""
        if self._phase == self.PAUSED:
            self.resume()
        elif self._phase in self.RUNNING:
            self.pause()
        else:
            self.start()

    def resume(self):
        """继续（与 :meth:`start` 等价，语义上更明确）/ Resume."""
        self.start()

    def skip(self):
        """
        跳过当前阶段 / Skip the current phase.

        **不计入完成数** —— 跳过一段工作等于没做完它，把它算进「已完成」会让
        计数失去意义（也让长休息来得莫名其妙）。
        A skipped work phase is *not* counted: counting it would make the
        counter meaningless and long breaks arrive out of nowhere.
        """
        if self._phase not in self.RUNNING:
            return
        self._advance(self._phase, count=False)
        self._fire("skipped")

    def reset(self):
        """回到空闲并清零计数 / Back to idle, counter zeroed."""
        self._phase = self.IDLE
        self._deadline = None
        self._remaining = 0.0
        self._fire("reset")

    def tick(self) -> dict:
        """
        推进一拍（UI 的 QTimer 每秒调一次）/ Advance one beat.

        时间没到就原样返回快照；到了就切换阶段并触发对应事件。
        Returns the current snapshot; when the deadline passes the phase
        switches and the matching event fires.
        """
        if self._phase in (self.IDLE, self.PAUSED):
            return self.snapshot()
        if self.remaining <= 0.0:
            prev = self._phase
            self._advance(prev, count=True)
            self._fire("work_done" if prev == self.WORK else "break_done")
        return self.snapshot()

    # ------------------------------------------------------------------
    # 配置 / configuration
    # ------------------------------------------------------------------
    def set_durations(self, work_min: int, break_min: int,
                      long_break_min: int, long_every: int):
        """
        改时长。**立即生效于下一段**，不打断正在跑的这一段 —— 中途改时长把
        剩余时间重算一遍，用户会以为计时被重置了。
        Change the durations; takes effect on the *next* phase.  Recomputing
        the remaining time mid-phase would look exactly like a reset.
        """
        self.work_sec = self._clamp_minutes(work_min) * 60
        self.break_sec = self._clamp_minutes(break_min) * 60
        self.long_break_sec = self._clamp_minutes(long_break_min) * 60
        self.long_every = max(1, min(12, int(long_every or 4)))

    # ------------------------------------------------------------------
    # 内部 / internals
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_minutes(v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 25
        return max(MIN_MINUTES, min(MAX_MINUTES, v))

    def _duration_of(self, phase: str) -> float:
        return {self.WORK: self.work_sec,
                self.BREAK: self.break_sec,
                self.LONG_BREAK: self.long_break_sec}.get(phase, 0.0)

    def _begin(self, phase: str):
        self._phase = phase
        self._remaining = self._duration_of(phase)
        self._deadline = time.monotonic() + self._remaining

    def _advance(self, prev: str, count: bool):
        """一段结束，进入下一段 / One phase ended, move to the next one."""
        if prev == self.WORK:
            if count:
                self.completed += 1
            nxt = (self.LONG_BREAK
                   if self.completed and self.completed % self.long_every == 0
                   else self.BREAK)
        else:
            nxt = self.WORK
        self._begin(nxt)

    def _fire(self, event: str):
        if self.on_event is None:
            return
        try:
            self.on_event(event, self)
        except Exception:  # noqa: BLE001
            # 回调属于界面层：它坏了只该影响「通知」这一件事。
            # 计时本身必须活着，所以记日志而不是让异常沿着 QTimer 冒出去。
            # The callback belongs to the UI layer: if it breaks, only the
            # notification should suffer.  The clock must survive, so log
            # instead of letting the exception ride the QTimer out.
            log.exception("pomodoro event callback failed (%s)", event)
