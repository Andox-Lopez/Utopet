# -*- coding: utf-8 -*-
"""
输入回避区 / Input avoidance zones
==============================================================================
用户正在打字时，宠物不该跑到输入框和输入法候选窗上压着 —— 那挡视线、
也容易被手肘扫到。这个模块负责算出「当前该回避哪几块矩形」。

What this module does
------------------------------------------------------------------------------
只做**几何**：把 win32 读到的原始信号翻译成矩形列表，外加一个「是否正在输入」
的状态位。判定「这只宠物要不要跑」在 `Manager` 里，不在这里。

It only does geometry: it turns raw Win32 signals into a list of rectangles
plus a "is the user typing" flag.  Deciding *which pet flees* lives in Manager.

A 路 / A path —— 精确光标矩形
    `win32.get_input_caret_rect()`。**只在传统 Win32 文本控件下有效**
    （记事本、Office、Delphi…）。实测 Firefox 67 次采样全 0、Chrome 全 0：
    现代应用自己画光标，不提供系统 caret。

B 路 / B path —— 光标附近矩形
    拿不到 caret 时，以**光标位置**为中心划一块矩形。这不是猜测的替代品，
    而是唯一在所有应用上都成立的方案 —— 用户正在输入时光标就在那块区域，
    而 `GetCursorPos` 零依赖永远可用。

IME 窗口
    输入法候选窗弹出来时也并入回避区。IME 被激活必然伴随键盘输入，所以
    调用方只在检测到键盘活动时才去查它（实测 1.35ms，是最贵的一次调用）。

Keyboard activity
    `win32.key_pressed_since()` 扫全部 256 个虚拟键码。⛔ 不用
    `GetLastInputInfo`：它不区分键鼠，用户动一下鼠标就归零 —— 宠物会因为
    鼠标移动而无缘无故躲开。
"""

from __future__ import annotations

from .. import win32

__all__ = ["AvoidZones", "DEFAULT_MARGIN_X", "DEFAULT_MARGIN_Y"]

#: B 路矩形相对光标的半宽/半高（逻辑像素）
#: Half-width/half-height of the fallback rect, relative to the cursor.
DEFAULT_MARGIN_X = 210
DEFAULT_MARGIN_Y = 80

#: 「最近有键盘输入」算「正在输入」的持续时间（毫秒）。
#: 取 1.5 秒：短于它会在打字过程中反复退出（宠物一停下就回来了），
#: 长于它会让用户打完字后宠物还躲着。
#: How long keyboard activity keeps the "user is typing" state alive.
DEFAULT_TYPING_WINDOW_MS = 1500


class AvoidZones:
    """回避区的逐帧状态 / Per-tick state of the avoidance zones.

    构造时不碰 Win32 —— 必须先 :meth:`update`，这样测试能直接喂信号而不必
    真的去按键盘。
    Constructed inert; call :meth:`update` first, so tests can feed signals
    instead of requiring a human to press keys.
    """

    def __init__(self, enabled: bool = True,
                 margin_x: int = DEFAULT_MARGIN_X,
                 margin_y: int = DEFAULT_MARGIN_Y,
                 typing_window_ms: int = DEFAULT_TYPING_WINDOW_MS):
        self.enabled = bool(enabled)
        self.margin_x = max(0, int(margin_x))
        self.margin_y = max(0, int(margin_y))
        self.typing_window_ms = max(0, int(typing_window_ms))
        #: 回避区矩形列表：(left, top, right, bottom) / the rectangles
        self.rects: list[tuple[int, int, int, int]] = []
        #: 是否处于「用户正在输入」状态 / is the user typing right now
        self.typing = False
        #: 走的是哪条路，"caret" 或 "cursor"（诊断用，日志里要看）
        #: Which path produced the zones — for the log.
        self.source = "none"
        #: 上一次检测到键盘输入的时刻（毫秒，单调时钟）
        self._last_key_ms = -10 ** 9
        #: 现在的时间源；测试可替换成假时钟 / injectable clock for tests
        self._clock_ms = None

    # ------------------------------------------------------------------
    def set_clock(self, func):
        """注入时间源（测试用）/ Inject a clock (tests only)."""
        self._clock_ms = func

    def _now_ms(self) -> int:
        if self._clock_ms is not None:
            return int(self._clock_ms())
        import time
        return int(time.monotonic() * 1000)

    # ------------------------------------------------------------------
    def feed_keyboard(self, pressed: bool = True):
        """喂一个「有键盘输入」信号。/ Feed a keyboard-activity signal.

        拆出来是为了测试：**自动化的按键注入不可靠**（本项目已知注入按键
        不触发 `RegisterHotKey`），所以测试直接调这个方法而不是想办法按键盘。
        Split out for tests: synthetic key injection is unreliable, so tests
        call this instead of trying to press keys.
        """
        if pressed:
            self._last_key_ms = self._now_ms()

    def update(self, typing: bool = False, tick_ms: int = 40) -> None:
        """每帧调用。刷新回避区。/ Call once per tick.

        :param typing: 由调用方预先判断「本帧是否有键盘活动」。
            传 True 等于告诉本模块「刚有人按键」。
            Whether a key went down this tick — the caller decides, because
            reading it has a cost.
        :param tick_ms: 当前帧长，用来在没按键时维持 typing 状态。
            Frame length, used to age out the typing state.
        """
        if not self.enabled:
            self.rects = []
            self.typing = False
            self.source = "none"
            return

        if typing:
            self.feed_keyboard(True)

        elapsed = self._now_ms() - self._last_key_ms
        self.typing = elapsed <= self.typing_window_ms
        if not self.typing:
            self.rects = []
            self.source = "none"
            return

        cx, cy = win32.get_cursor_pos()
        rects: list[tuple[int, int, int, int]] = []

        # ── A 路：精确光标矩形（传统控件） ─────────────────────────────
        caret = win32.get_input_caret_rect()
        if caret is not None:
            l, t, r, b = caret
            rects.append((l - self.margin_x, t - self.margin_y,
                          r + self.margin_x, b + self.margin_y))
            self.source = "caret"
        else:
            # ── B 路：光标附近（现代应用，实测 caret 恒为 0）───────────
            rects.append((cx - self.margin_x, cy - self.margin_y,
                          cx + self.margin_x, cy + self.margin_y))
            self.source = "cursor"

        # 输入法候选窗：IME 激活必然伴随键盘输入，所以走到这里才值得查
        # （实测 1.35ms，是最贵的一次调用）。
        # An IME can only be up while the user types, so only now is it worth
        # paying for the 1.35 ms enumeration.
        rects.extend(win32.visible_ime_rects())
        self.rects = rects

    # ------------------------------------------------------------------
    def contains(self, x: int, y: int) -> bool:
        """点是否落在任一回避区内 / Is this point inside any zone?"""
        for l, t, r, b in self.rects:
            if l <= x <= r and t <= y <= b:
                return True
        return False

    def contains_rect(self, left: int, top: int, right: int, bottom: int) -> bool:
        """矩形是否与任一回避区相交。

        调用方要传**身体的矩形**而不是锚点：精灵图的基准点通常在下方
        （图集里常见 `基準座標="64,128"`），只判锚点会出现「看着已经压上去了，
        判定却说在区外」。
        Does the rectangle overlap any zone?

        Callers must pass the sprite's *bounding box*, not its anchor: the
        baseline of these sheets sits low (`基準座標="64,128"`), so an
        anchor-only test reports "outside" while the pet visibly overlaps.
        """
        for l, t, r, b in self.rects:
            if left < r and right > l and top < b and bottom > t:
                return True
        return False

    def escape_direction(self, x: int, y: int) -> int:
        """往哪个方向逃：``-1`` 向左、``+1`` 向右。

        取「离回避区中心最远」的一侧，而不是「离得最近边最远」—— 前者一步就能
        真正离开，后者只是从贴着边变成贴着另一边，还是在输入区边上晃。
        Which way to flee: the side *further* from the zone centre, so one run
        actually clears it instead of hugging the opposite edge.
        """
        if not self.rects:
            return -1
        # 用所有区的并集包围盒的中心作参考 / centre of the union bbox
        min_l = min(r[0] for r in self.rects)
        min_t = min(r[1] for r in self.rects)
        max_r = max(r[2] for r in self.rects)
        max_b = max(r[3] for r in self.rects)
        cx = (min_l + max_r) / 2.0
        return -1 if x < cx else 1
