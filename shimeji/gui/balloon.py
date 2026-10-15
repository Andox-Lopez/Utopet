# -*- coding: utf-8 -*-
"""
气泡台词窗口 / The speech balloon window.

**必须是独立的顶层窗口，不能做成 Mascot 的子控件**：Mascot 的窗口尺寸恰好等于
当前帧图片的尺寸（`Mascot.set_image` 会 resize），子控件超出父窗口的部分会被
裁掉，而气泡要挂在**头顶上方** —— 也就是说它天生在父窗口外面。

Must be a separate top-level window rather than a child widget: the Mascot
window is resized to exactly the current frame's pixmap, so anything above it
would be clipped.

三个关键点：
- `WA_TransparentForMouseEvents`：气泡飘在桌面上，不能挡住用户点下面的东西。
- `WA_ShowWithoutActivating`：冒泡不能抢焦点，否则用户正在打字会被打断。
- 跟随：宠物在走动时气泡要粘着它，所以 Manager 每帧调 `follow()`。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

#: 气泡配色。用**半透明深色 + 白字 + 浅色描边**：桌面上什么背景都有，
#: 不透明的话白底上会瞎、白字在亮背景上看不清。
#: Semi-transparent dark with white text: the desktop can be anything, so an
#: opaque box either glares on light backgrounds or loses white text.
_BG = QColor(28, 28, 32, 225)
_BORDER = QColor(255, 255, 255, 90)
_TEXT = QColor(240, 240, 245, 255)

_TAIL_W = 12
_TAIL_H = 9
_PAD_X = 10
_PAD_Y = 6
_MIN_W = 60
_MAX_W = 260


class Balloon(QWidget):
    """一个会说话的气泡 / One balloon that says a line."""

    def __init__(self, serifu, parent=None):
        super().__init__(parent)
        self.serifu = serifu
        self._owner = None               # 正在跟随的宠物 / the mascot it follows
        self._text = ""

        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 关键：气泡飘在桌面上，点击必须穿透到下面的东西。
        # Critical: clicks must fall through to whatever is underneath.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_)

    # ------------------------------------------------------------------
    def say(self, text: str, owner=None, always_on_top: bool = True):
        """
        说一句话。`owner` 是这只宠物，气泡会跟着它。
        Say a line; the balloon sticks to `owner`.
        """
        text = (text or "").strip()
        if not text:
            return False
        self._text = text
        self._owner = owner
        # 一次只改一次：setWindowFlag 在可见时会隐藏窗口，所以放在 show 之前，
        # 且下面会补一次 show()。
        # One call only: setWindowFlag hides a visible widget, hence it happens
        # before show() and show() is re-issued below.
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(always_on_top))
        self._resize_to_text()
        self.follow(owner)
        if not self.isVisible():
            self.show()
        self._timer.start(self.serifu.duration_ms())
        return True

    def hide_(self):
        """到时收起 / Dismiss when the timer runs out."""
        self.hide()
        self._owner = None

    @property
    def text(self) -> str:
        return self._text

    # ------------------------------------------------------------------
    def _resize_to_text(self):
        px = self.serifu.font_px()
        font = QFont()
        font.setPixelSize(px)
        fm = QFontMetrics(font)
        # 一个「词」宽度上限，逼长句换行，而不是拉出一块横跨半个屏幕的板子。
        # 换行宽度只能靠 QRect 那个重载传（PySide6 的
        # `boundingRect(x,y,w,h,flags)` 少了 text 参数）。
        # Cap the width so long lines wrap.  The wrap width can only be passed
        # through the QRect overload -- PySide6's boundingRect(x,y,w,h,flags)
        # has no `text` argument.
        rect = fm.boundingRect(QRect(0, 0, _MAX_W - _PAD_X * 2, 4000),
                               Qt.TextWordWrap | Qt.AlignLeft, self._text)
        w = max(_MIN_W, min(_MAX_W, rect.width() + _PAD_X * 2))
        h = rect.height() + _PAD_Y * 2
        self.resize(int(w), int(h) + _TAIL_H)
        self.setFont(font)

    def follow(self, mascot=None):
        """
        粘在宠物头顶。**每帧由 Manager 调用** —— 宠物到处走，气泡不跟就飘在原地。
        Stick above the mascot.  Called every frame by the Manager: the pet walks
        around, a balloon left behind looks broken.
        """
        target = mascot if mascot is not None else self._owner
        if target is None or not target.isVisible():
            return
        dx, dy = self.serifu.offset()
        # 水平居中，气泡底部（含尾巴）刚好压在宠物头顶上方
        # Centre horizontally; the balloon's tail sits just above the head.
        x = target.x() + target.width() // 2 - self.width() // 2 + dx
        y = target.y() - self.height() + dy
        self.move(int(x), int(y))

    # ------------------------------------------------------------------
    def paintEvent(self, _event):  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - _TAIL_H - 1.0)
        path = QPainterPath()
        path.addRoundedRect(body, 6, 6)
        # 小尾巴：指向下方的宠物 / a small tail pointing down at the pet
        cx = self.width() // 2
        path.moveTo(cx - _TAIL_W / 2, body.bottom() - 1)
        path.lineTo(cx, self.height() - 1)
        path.lineTo(cx + _TAIL_W / 2, body.bottom() - 1)
        path.closeSubpath()

        p.setPen(QPen(_BORDER, 1))
        p.setBrush(_BG)
        p.drawPath(path)
        p.setPen(_TEXT)
        p.drawText(QRectF(_PAD_X, _PAD_Y, self.width() - _PAD_X * 2,
                          self.height() - _TAIL_H - _PAD_Y * 2),
                   Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
                   self._text)
        p.end()
