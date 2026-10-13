# -*- coding: utf-8 -*-
"""
运行环境 / Environment
==============================================================================
复刻原版 `com.group_finity.mascot.environment` 的几何模型：
屏幕、工作区（排除任务栏）、可见窗口（原版称 IE）、光标位置，以及
地面 / 墙壁 / 天花板三类边界（Border）的 `isOn` 判定。

Re-implements the geometry model of the original
`com.group_finity.mascot.environment` package: screen, work area (taskbar
excluded), visible windows (called "IE" in the original), the cursor, and the
floor / wall / ceiling borders with their `isOn` test.

边界判定（来自反编译）/ Border test (decompiled from the original jar)
------------------------------------------------------------------------------
    FloorCeiling.isOn(p) = visible and |y - p.y| <= 2 and left-10 <= p.x <= right+10
    Wall.isOn(p)         = visible and |x - p.x| <= 2 and top-10  <= p.y <= bottom+10
"""

from __future__ import annotations

from .. import win32

__all__ = ["Pt", "Area", "Wall", "FloorCeiling", "NotOnBorder", "NOT_ON_BORDER",
           "Location", "Environment", "MascotEnvironment"]

# 边界容差（像素）/ Border tolerance in pixels —— 与原版一致 / same as the original
BORDER_TOLERANCE = 2
ALONG_TOLERANCE = 10
# 窗口顶部必须至少低于工作区顶端这么多像素，宠物才能站在上面
# A window top must be at least this far below the work-area top to be standable.
MIN_STAND_HEIGHT = 64


class Pt:
    """一个点 / A point."""

    __slots__ = ("x", "y")

    def __init__(self, x: float = 0, y: float = 0):
        self.x = x
        self.y = y

    def __iter__(self):
        return iter((self.x, self.y))

    def __repr__(self) -> str:  # pragma: no cover
        return "Pt(%d,%d)" % (self.x, self.y)


class Area:
    """
    一个矩形区域（屏幕 / 工作区 / 窗口）/ A rectangle (screen / work area / window).

    除了四个边坐标，还保存**自上一 tick 以来各自的位移量**
    （原版 `Area.dleft / dtop / dright / dbottom`）。

    这四个字段是 `Wall.move()` / `FloorCeiling.move()` 能工作的前提 ——
    没有它就无法区分「窗口自己动了，宠物要被带着走」和「宠物自己走出了边界，
    应该掉下去」，于是边界每帧都把宠物硬拽回线上，这就是用户看到的
    「爬墙时只能蹭墙不动，下一秒瞬间到顶上」。

    Besides the four edges, each area stores **how far it moved since the last
    tick** (the original's `dleft / dtop / dright / dbottom`).  Without them a
    border cannot tell "the window moved, carry the mascot along" from "the
    mascot walked off, let it fall", so it snaps the mascot back every frame —
    which is exactly the reported "sticks to the wall / teleports to the top".
    """

    def __init__(self, left=0, top=0, right=0, bottom=0, visible=True, hwnd=None):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.visible = visible
        self.hwnd = hwnd
        # 自上一 tick 起的位移 / displacement since the previous tick
        self.dleft = 0
        self.dtop = 0
        self.dright = 0
        self.dbottom = 0
        self.leftBorder = Wall(self, False)
        self.rightBorder = Wall(self, True)
        self.topBorder = FloorCeiling(self, False)
        self.bottomBorder = FloorCeiling(self, True)

    def set_rect(self, left, top, right, bottom):
        """
        更新矩形，并记录本 tick 的位移 / Update the rect and record this tick's shift.

        对齐原版 `Area.set(Rectangle)`：先算差值，再写新值。
        Mirrors the original `Area.set(Rectangle)`: deltas first, then the values.
        """
        self.dleft = left - self.left
        self.dtop = top - self.top
        self.dright = right - self.right
        self.dbottom = bottom - self.bottom
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def clear_delta(self):
        """把位移归零（窗口本 tick 没动）/ Zero the deltas (the area did not move)."""
        self.dleft = self.dtop = self.dright = self.dbottom = 0

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    def contains_x(self, x, pad=ALONG_TOLERANCE):
        return self.left - pad <= x <= self.right + pad

    def contains_y(self, y, pad=ALONG_TOLERANCE):
        return self.top - pad <= y <= self.bottom + pad

    def __repr__(self) -> str:  # pragma: no cover
        return "Area(%d,%d,%d,%d)" % (self.left, self.top, self.right, self.bottom)


class Wall:
    """左右墙边界 / A left or right wall border."""

    def __init__(self, area: Area, right: bool):
        self.area = area
        self.right = right

    @property
    def x(self):
        return self.area.right if self.right else self.area.left

    @property
    def top(self):
        return self.area.top

    @property
    def bottom(self):
        return self.area.bottom

    def isOn(self, p) -> bool:
        if not self.area.visible:
            return False
        if abs(self.x - p.x) > BORDER_TOLERANCE:
            return False
        return self.top - ALONG_TOLERANCE <= p.y <= self.bottom + ALONG_TOLERANCE

    # 别名：兼容 Python 风格调用 / alias for a Pythonic call style
    is_on = isOn

    def move(self, p):
        """
        跟随墙自身的移动 / Follow the wall's own movement.

        **这不是「吸附到墙面」。** 对齐原版 `Wall.move()`：

            d = getBottom() - getDBottom() - (getTop() - getDTop())
            if (d == 0) return location;          // 墙没动 -> 原样返回
            new = (x + dleft, (y - oldTop) * newHeight/oldHeight + newTop)
            if (|new.x - x| >= 80 || |new.y - y| >= 80) return location;  // 防跳变
            return new;

        也就是说 `move()` **只负责把因为窗口移动/缩放而错位的宠物补回来**，
        绝不把宠物拽回墙线。宠物自己走出墙的范围时 `move()` 什么也不做，
        紧接着的 `isOn()` 判定失败 → LostGround → 切换「落下する」。

        之前我们写成 `Pt(self.x, clamp(p.y, top, bottom))`（纯吸附），于是
        宠物爬到墙顶时 y 被钳回 top，永远走不出去 —— 用户描述的「只能蹭墙
        不动，下一秒瞬间到顶上」。

        **This is not a snap.**  It only compensates for the wall's own motion;
        it never pulls a walking mascot back.  Once the mascot walks past the
        edge, `move()` is a no-op and the following `isOn()` fails, which
        raises LostGround and switches the behaviour to "Fall".
        """
        a = self.area
        if not a.visible:
            return p
        # 旧的上/下边 -> 本 tick 的位移量 / previous top/bottom vs this tick's shift
        old_top = a.top - a.dtop
        old_bottom = a.bottom - a.dbottom
        d = old_bottom - old_top
        if d == 0:
            # 墙本身没有伸缩 -> 什么都不做 / the wall did not resize: identity
            return p
        new_x = p.x + (a.dright if self.right else a.dleft)
        new_y = (p.y - old_top) * (a.bottom - a.top) / d + a.top
        # 防跳变护栏：位移过大就放弃这一帧的补偿 / anti-teleport guard
        if abs(new_x - p.x) >= 80 or abs(new_y - p.y) >= 80:
            return p
        return Pt(new_x, new_y)

    def __repr__(self) -> str:  # pragma: no cover
        return "Wall(%s)" % ("right" if self.right else "left")


class FloorCeiling:
    """地面 / 天花板 边界 / A floor or ceiling border."""

    def __init__(self, area: Area, bottom: bool):
        self.area = area
        self.bottom = bottom

    @property
    def y(self):
        return self.area.bottom if self.bottom else self.area.top

    @property
    def left(self):
        return self.area.left

    @property
    def right(self):
        return self.area.right

    def isOn(self, p) -> bool:
        if not self.area.visible:
            return False
        if abs(self.y - p.y) > BORDER_TOLERANCE:
            return False
        return self.left - ALONG_TOLERANCE <= p.x <= self.right + ALONG_TOLERANCE

    is_on = isOn

    def move(self, p):
        """
        跟随地面/天花板自身的移动 / Follow the floor's or ceiling's own movement.

        对齐原版 `FloorCeiling.move()`：

            d = getRight() - getDRight() - (getLeft() - getDLeft())
            if (d == 0) return location;          // 面没动 -> 原样返回
            new = ((x - oldLeft) * newWidth/oldWidth + left, y + dY)
            if (|new.x - x| >= 80 || new.y - y > 20 || new.y - y < -80) return location;
            return new;

        与 `Wall.move()` 同理：**只补偿，不吸附**。宠物自己走出窗口边缘时
        `move()` 不动它，`isOn()` 随即失败 → LostGround → 「落下する」。
        这正是「走到了窗口边缘会掉下来」「不会卡在边缘蹭」的实现方式；
        我们原来的 `x = clamp(p.x, left, right)` 会把它永远拽在窗口内。

        Like `Wall.move()`, this **compensates, never snaps**: once the mascot
        walks past the edge the floor lets go and LostGround fires.  Our old
        `clamp` kept it pinned inside the window forever.
        """
        a = self.area
        if not a.visible:
            return p
        old_left = a.left - a.dleft
        old_right = a.right - a.dright
        d = old_right - old_left
        if d == 0:
            # 宽度没变 -> 什么都不做 / the width did not change: identity
            return p
        new_x = (p.x - old_left) * (a.right - a.left) / d + a.left
        new_y = p.y + (a.dbottom if self.bottom else a.dtop)
        # 防跳变护栏（注意纵向阈值不对称：下 20 / 上 80）/ anti-teleport guard
        if abs(new_x - p.x) >= 80 or new_y - p.y > 20 or new_y - p.y < -80:
            return p
        return Pt(new_x, new_y)

    def __repr__(self) -> str:  # pragma: no cover
        return "FloorCeiling(%s)" % ("bottom" if self.bottom else "top")


class NotOnBorder:
    """
    「当前不在这条边上」的哨兵 / Sentinel meaning "the mascot is on no border at all".

    ---------------------------------------------------------------------------
    这是整个引擎里最容易被改错的一处语义，务必对齐原版 `NotOnBorder`。
    This is the single most easily mis-read semantic in the engine; it mirrors
    the original's ``NotOnBorder`` singleton exactly.

    原版 `MascotEnvironment.getFloor()` 只有在锚点**确实贴着**某条边时才返回那条边，
    否则返回 ``NotOnBorder.INSTANCE``。而 `Animate` / `Move` / `Stay` 每帧做的是：

        super.tick();                                   // border.move(anchor)
        if (border != null && !border.isOn(anchor)) throw new LostGroundException();

    也就是说：**宠物走到边界外 → 立刻抛 LostGround → 行为被切到「落下する」**，
    这正是「走到窗口边缘会掉下来」「不会卡在墙上蹭」的实现方式。

    之前我们在这里「找不到就退回工作区下边 / 随便一个窗口顶边」，等于永远不抛
    LostGround，于是宠物被 `border.move()` 硬拽回边界 —— 表现就是「上一秒还在
    任务栏上，下一秒瞬间到屏幕最上面」「到了窗口边缘不会掉下来」。
    """

    __slots__ = ()
    #: 原版是单例 / the original is a singleton
    INSTANCE: "NotOnBorder"

    def isOn(self, p) -> bool:  # noqa: N802 - mirrors the original API
        """永远不成立 —— 这正是「LostGround」的触发条件。/ Never true."""
        return False

    # 别名：兼容 Python 风格调用 / alias for a Pythonic call style
    is_on = isOn

    def move(self, p):
        """原样返回，不做任何吸附 —— 不在边上就没有边可站。/ Identity."""
        return p

    def __repr__(self) -> str:  # pragma: no cover
        return "NotOnBorder"


#: 哨兵单例 / the singleton
NOT_ON_BORDER = NotOnBorder()
NotOnBorder.INSTANCE = NOT_ON_BORDER


class Location:
    """
    光标位置与速度 / Cursor position and per-tick velocity.

    **速度公式必须与原版一致**，否则「抛出」会变成「瞬移」：

        setDx((getDx() + value.x - getX()) / 2);   // 指数滑动平均
        setDy((getDy() + value.y - getY()) / 2);

    我们之前用的是「最近 4 帧的位置差 / 平均帧数」。那个窗口里混着**陈旧**的
    采样点 —— 比如宠物刚被召唤、光标还没动过时，一个跨几百像素的旧点会把
    平均速度放大到几百 px/帧。`投げられる` 的初速正是 `${cursor.dy}`，
    于是宠物一帧就飞出去 178px —— 用户说的「上一秒还在任务栏上，下一秒就
    到屏幕最上面」「闪现」。

    The formula must match the original's **exponential moving average**.
    Our previous "position delta over the last 4 samples" included *stale*
    samples, so a cursor that had not moved yet (after summoning a mascot, say)
    produced a velocity of hundreds of px per frame.  Since `投げられる` takes
    its initial velocity straight from `${cursor.dy}`, the mascot teleported
    178px in one frame — the reported "flash".
    """

    def __init__(self):
        self.x = 0
        self.y = 0
        self.dx = 0
        self.dy = 0

    def set(self, x, y):
        """
        更新光标位置与速度 / Update the cursor position and velocity.

        对齐原版 `Location.set(Point)`。
        """
        self.dx = (self.dx + x - self.x) / 2.0
        self.dy = (self.dy + y - self.y) / 2.0
        self.x = x
        self.y = y


class Environment:
    """
    全局环境（所有宠物共享，每帧刷新一次）。
    The global environment: shared by every mascot, refreshed once per tick.
    """

    #: 每隔多少帧重新枚举显示器 / how often monitors are re-enumerated
    MONITOR_REFRESH_TICKS = 100
    #: 每隔多少帧重新读取窗口标题 / how often window titles are re-read
    TITLE_REFRESH_TICKS = 30
    #: 覆盖工作区这么大比例的窗口不算「可站立的地面」/ a window covering this
    #: much of the work area is not a standable surface
    FULLSCREEN_RATIO = 0.88
    #: 全屏判定：宽和高**各自**达到这个比例才算全屏/ full-screen test: the width
    #: and the height must *each* reach this ratio.  单看面积会漏掉
    #: 「宽度满、只差一条任务栏」这类窗口（QQ 最大化、贴屏视频），而它们的
    #: 底边正好压在工作区底边上—— 那是「窗口底部爬行」误触发的元凶。
    FULLSCREEN_SPAN = 0.80

    def __init__(self):
        l, t, r, b = win32.get_screen_rect()
        self.screen = Area(l, t, r, b, True)
        l, t, r, b = win32.get_work_area()
        self.work_area = Area(l, t, r, b, True)
        self.active_ie = Area(0, 0, 0, 0, False)
        self.cursor = Location()
        self.windows: list[Area] = []
        self.monitors: list[tuple[Area, Area]] = []   # (整屏, 工作区) / (full, work)
        self._window_map: dict[int, Area] = {}
        self._titles: dict[int, str] = {}
        self._tick = 0
        self.titles_filter: list[str] = []
        self.window_offset = (0, 0, 0, 0)   # x, y, width add, height add
        self._enum_monitors()
        self.refresh(force=True)

    def _enum_monitors(self):
        """枚举显示器，选出主屏工作区 / Enumerate monitors and pick the primary work area."""
        self.monitors = []
        for mrect, wrect in win32.enum_monitors():
            self.monitors.append((Area(*mrect, visible=True), Area(*wrect, visible=True)))
        if not self.monitors:
            self.monitors.append((Area(*win32.get_screen_rect(), visible=True),
                                  Area(*win32.get_work_area(), visible=True)))
        # 主屏 = 含有 (0,0) 的那一块 / primary = the one containing (0, 0)
        primary = None
        for m, w in self.monitors:
            if m.left <= 0 <= m.right and m.top <= 0 <= m.bottom:
                primary = w
                break
        if primary is None:
            primary = self.monitors[0][1]
        self.work_area.set_rect(primary.left, primary.top, primary.right, primary.bottom)
        self.screen.set_rect(self.monitors[0][0].left, self.monitors[0][0].top,
                             self.monitors[0][0].right, self.monitors[0][0].bottom)

    def work_area_at(self, x, y) -> Area:
        """坐标所在显示器的工作区 / The work area of the monitor containing a point."""
        for m, w in self.monitors:
            if m.left <= x <= m.right and m.top <= y <= m.bottom:
                return w
        # 落在缝隙里就取最近的一块 / in a gap: use the nearest monitor
        best, bestd = None, None
        for m, w in self.monitors:
            cx = max(m.left, min(m.right, x))
            cy = max(m.top, min(m.bottom, y))
            d = (cx - x) ** 2 + (cy - y) ** 2
            if bestd is None or d < bestd:
                best, bestd = w, d
        return best or self.work_area

    # 表达式里写作 `mascot.environment.workArea` / `activeIE`，这里提供同名别名
    # Expressions use `workArea` / `activeIE`; provide identically named aliases.
    @property
    def workArea(self) -> "Area":
        return self.work_area

    @property
    def activeIE(self) -> "Area":
        return self.active_ie

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False):
        """
        刷新工作区、光标与窗口矩形 / Refresh the work area, cursor and window rects.

        **窗口矩形每 tick 都更新**（对齐原版 `Environment.tick()`）。这不是性能
        优化问题，而是正确性问题：`Border.move()` 用「本 tick 与上一 tick 的
        矩形差值」来把跟着窗口移动的宠物补回原处；每 8 tick 才枚举一次，差值
        就是 8 tick 的累积量，补偿会过冲，表现为「蹭墙不动 / 瞬间到顶上」。

        Window rects are refreshed **every tick** (as the original's
        `Environment.tick()` does).  This is a correctness requirement, not a
        performance tweak: `Border.move()` derives the compensation from the
        rect delta between this tick and the previous one, so refreshing every
        8th tick makes that delta 8 ticks' worth and the compensation
        overshoots — the mascot sticks to the wall, then jumps.
        """
        self._tick += 1
        if force or self._tick % self.MONITOR_REFRESH_TICKS == 0:
            self._enum_monitors()
        else:
            # 显示器没变 -> 本 tick 位移为 0，`move()` 才能正确地恒等返回
            # The monitors did not change: zero deltas so `move()` is an identity.
            self.screen.clear_delta()
            self.work_area.clear_delta()

        cx, cy = win32.get_cursor_pos()
        self.cursor.set(cx, cy)

        self._enumerate(refresh_titles=force or self._tick % self.TITLE_REFRESH_TICKS == 1)
        self._update_active_ie(cx, cy)

    def _matches_filter(self, title: str) -> bool:
        if not self.titles_filter:
            return True
        low = title.lower()
        return any(f.lower() in low for f in self.titles_filter)

    def _enumerate(self, refresh_titles: bool = False):
        ox, oy, ow, oh = self.window_offset
        self.windows = []
        seen: dict[int, Area] = {}
        for hwnd, (l, t, r, b) in win32.list_windows():
            if refresh_titles or hwnd not in self._titles:
                self._titles[hwnd] = win32.get_window_title(hwnd)
            title = self._titles.get(hwnd, "")
            if not self._matches_filter(title):
                continue
            a = self._window_map.get(hwnd)
            if a is None:
                # 新窗口：直接落到当前矩形，不产生位移 —— 否则「从 0,0,0,0
                # 跳到真实位置」会被 `move()` 当成一次巨大位移。
                # Brand-new window: adopt the rect with no delta, otherwise the
                # jump from 0,0,0,0 reads as one huge displacement.
                a = Area(l + ox, t + oy, r + ox + ow, b + oy + oh, hwnd=hwnd)
            else:
                a.set_rect(l + ox, t + oy, r + ox + ow, b + oy + oh)
            a.visible = True
            self.windows.append(a)
            seen[hwnd] = a
        # 本 tick 没有出现在列表里的窗口（例如被最小化/关闭），把位移清零，
        # 否则它下次回来时 `move()` 会按一整段时间的差值补偿。
        # Areas that vanished this tick get zeroed so they do not carry a huge
        # accumulated delta back in when they reappear.
        for hwnd, a in self._window_map.items():
            if hwnd not in seen:
                a.clear_delta()
        self._window_map = seen

    def is_fullscreen_window(self, a: Area) -> bool:
        """
        窗口是否几乎铺满工作区 / Does the window cover (almost) the whole work area?

        桌面上会枚举到 `(-8,-8,1928,1040)`（explorer 桌面窗口）和
        `(0,0,1919,1080)`（Progman）这类「伪窗口」。它们不是可以站立的地面，
        但它们的 `top` 会参与 `floor` 判定：只要其中任何一个的 `top` 恰好
        接近宠物的高度，地面就会突变 —— 用户反馈「只有设置面板（全屏）时
        正常，打开窗口化的 QQ 就出问题」正是这个机制。

        Explorer enumerates pseudo-windows such as `(-8,-8,1928,1040)` and
        `(0,0,1919,1080)`.  They are not standable surfaces, yet their `top`
        participates in the floor test, so the floor can flip the moment one
        of them lines up with the mascot — which is why the mascot behaved
        correctly only while every other window was full-screen.
        """
        wa = self.work_area
        w = wa.right - wa.left
        h = wa.bottom - wa.top
        if w <= 0 or h <= 0:
            return False
        ix = max(0, min(a.right, wa.right) - max(a.left, wa.left))
        iy = max(0, min(a.bottom, wa.bottom) - max(a.top, wa.top))
        # 面积判据：够大就排除（explorer 桌面 `(-8,-8,1928,1040)` 之类）。
        # 面积判据 alone misses a maximised window that stops one pixel short of
        # every edge, so also require the width and the height to *each* span
        # (almost) the whole work area.
        if (ix * iy) >= self.FULLSCREEN_RATIO * w * h:
            return True
        span_x = ix >= self.FULLSCREEN_SPAN * w
        span_y = iy >= self.FULLSCREEN_SPAN * h
        if span_x and span_y:
            return True
        # **底边压在工作区底边上的宽窗口**。窗口化应用不会紧贴任务栏上沿，
        # 只有最大化/全屏/贴屏窗口才会把bottom 对齐到 workArea.bottom。
        # 这类窗口的 `bottomBorder` 与工作区地面的 y 完全相同，宠物站在地上时
        # `activeIE.bottomBorder.isOn(anchor)` 恒为真 -> 持续触发「IEの下辺を伝う」。
        # A *windowed* app never sits flush against the taskbar; only maximised or
        # full-screen windows do.  Such a bottom edge is pixel-identical to the
        # work-area floor, so `activeIE.bottomBorder.isOn(anchor)` is permanently
        # true for a mascot standing on the floor.
        return span_x and a.bottom >= wa.bottom - 2

    def _update_active_ie(self, cx, cy):
        """
        activeIE = 光标所在窗口 / The window currently under the cursor.

        **跳过全屏/铺满窗口。** 这是「窗口底部爬行」误触发的根因：
        桌面上那个铺满工作区的窗口（QQ 最大化、游戏、贴屏视频）永远在光标下，
        于是 `activeIE` 一直是它。而它的 `bottom` 恰好压在工作区底边上，
        宠物站在地面时 `activeIE.bottomBorder.isOn(anchor)` **恒为真**，
        Behavior.xml 里那15+ 条 `activeIE.*Border` 条件就会持续命中
        「IEの下辺を伝う」「IEの天井を歩く」这类爬行 —— 表现为
        「全屏窗口会触发一个窗口底部爬行的动画」。

        跳过之后继续往下找，找到光标下第一个**可用**的窗口；都没有才置为不可见。

        **Full-screen windows are skipped.**  A maximised window sits under the
        cursor at all times, so `activeIE` would always be it, and its bottom
        edge coincides with the work-area bottom — making
        `activeIE.bottomBorder.isOn(anchor)` permanently true and firing the
        "crawl along the window bottom" behaviour over and over.
        """
        # EnumWindows 按 Z 序自上而下枚举，第一个命中的就是最上层窗口
        # EnumWindows walks top-to-bottom in Z order, so the first hit is topmost.
        best = None
        for a in self.windows:
            if a.left <= cx <= a.right and a.top <= cy <= a.bottom:
                # 铺满工作区的窗口不是可交互的「窗口」/ a work-area-filling
                # window is not an interactable window
                if self.is_fullscreen_window(a):
                    continue
                best = a
                break
        if best is None:
            self.active_ie.visible = False
            self.active_ie.set_rect(-9999, -9999, -9999, -9999)
        else:
            self.active_ie.visible = True
            self.active_ie.hwnd = best.hwnd
            self.active_ie.set_rect(best.left, best.top, best.right, best.bottom)

    # ------------------------------------------------------------------
    def window_by_hwnd(self, hwnd):
        return self._window_map.get(hwnd)

    def sync_window(self, hwnd, left, top, right, bottom):
        """移动窗口后同步本地缓存 / Keep the local cache in sync after moving a window."""
        a = self._window_map.get(hwnd)
        if a is not None:
            a.set_rect(left, top, right, bottom)


class MascotEnvironment:
    """
    单个宠物看到的环境（地面 / 天花板依赖宠物自身位置）。
    The environment as seen by one mascot (floor / ceiling depend on its anchor).
    """

    def __init__(self, env: Environment, mascot):
        self._env = env
        self._mascot = mascot

    @property
    def screen(self) -> Area:
        """宠物所在显示器的整屏 / The full rect of the monitor the mascot is on."""
        for m, _w in self._env.monitors:
            if m.contains_x(self._mascot.anchor.x, 0) and m.contains_y(self._mascot.anchor.y, 0):
                return m
        return self._env.screen

    @property
    def workArea(self) -> Area:
        """
        宠物所在显示器的工作区（多显示器时随宠物位置变化）。
        The work area of the monitor the mascot is currently on.
        """
        return self._env.work_area_at(self._mascot.anchor.x, self._mascot.anchor.y)

    # 表达式里写的是 `mascot.environment.workArea`，这里同时提供 snake_case 别名
    # Expressions use `mascot.environment.workArea`; snake_case alias provided too.
    @property
    def work_area(self) -> Area:
        return self.workArea

    @property
    def activeIE(self) -> Area:
        return self._env.active_ie

    @property
    def active_ie(self) -> Area:
        return self._env.active_ie

    @property
    def cursor(self) -> Location:
        return self._env.cursor

    @property
    def complexScreen(self):  # 兼容 / compatibility
        return self._env.screen

    # ------------------------------------------------------------------
    def _candidates(self):
        """
        宠物所在列上的窗口（可作为地面/天花板）/ Windows in the mascot's column.

        **排除几乎铺满工作区的窗口。** 桌面上会枚举到 `(-8,-8,1928,1040)`
        （explorer 桌面）和 `(0,0,1919,1080)`（Progman）这类伪窗口，它们不是
        可以站立的地面；但只要它们的 `top` 恰好接近宠物高度，`floor` 就会
        突变 —— 表现为「只有设置面板（全屏）时一切正常，一打开窗口化的 QQ
        就出问题」。

        **Full-screen windows are excluded.** Explorer enumerates pseudo-windows
        such as `(-8,-8,1928,1040)` and `(0,0,1919,1080)`; they are not
        standable surfaces, yet a `top` that happens to line up with the mascot
        flips the floor — the reason everything behaved while every other
        window was full-screen but broke as soon as a windowed QQ appeared.
        """
        ax = self._mascot.anchor.x
        out = []
        for a in self._env.windows:
            if a.visible and a.contains_x(ax) and not self._env.is_fullscreen_window(a):
                out.append(a)
        return out

    @property
    def floor(self):
        """
        地面：**只在锚点确实贴着它时**返回它，否则返回 `NOT_ON_BORDER`。

        The floor, returned **only when the anchor is actually on it**; otherwise
        `NOT_ON_BORDER`.

        对齐原版 `getFloor()`：先看窗口顶边，再看工作区下边，都不在就交白卷。
        之前这里会「找不到就随便返回一个」，导致宠物被硬吸附到边界上，
        走不出窗口边缘、也会被瞬间拽到屏幕顶部。

        Mirrors the original: the window top edge, then the work-area bottom
        edge, and `NOT_ON_BORDER` when neither is underfoot.
        """
        wa = self._env.work_area
        ay = self._mascot.anchor.y
        for a in self._candidates():
            # 过矮的窗口（顶栏浮窗之类）不作为地面，否则宠物会站到标题栏上
            if a.top >= wa.top + MIN_STAND_HEIGHT and abs(a.top - ay) <= BORDER_TOLERANCE:
                return a.topBorder
        if wa.bottomBorder.isOn(self._mascot.anchor):
            return wa.bottomBorder
        return NOT_ON_BORDER

    def get_floor(self, ignore_separator: bool = False):
        """
        原版 `getFloor(boolean ignoreSeparator)`。

        `Fall` 的子步进碰撞用的是 `getFloor(true)` / `getWall(true)` —— 下落
        途中允许落在「分隔线」上（多显示器/任务栏的接缝），而动作执行时用
        `getFloor(false)`，接缝不算地面。单屏下两者等价，签名保持一致以便
        逐行对照原版。

        The overload the original's `Fall` sub-stepping uses while falling.
        Equivalent on a single monitor; kept for a line-by-line comparison.
        """
        return self.floor

    @property
    def ceiling(self):
        """
        天花板：同 `floor`，**不在边上就返回 `NOT_ON_BORDER`**。
        The ceiling under which the mascot hangs; `NOT_ON_BORDER` when not on one.
        """
        wa = self._env.work_area
        ay = self._mascot.anchor.y
        for a in self._candidates():
            if a.bottom <= wa.bottom - MIN_STAND_HEIGHT and abs(a.bottom - ay) <= BORDER_TOLERANCE:
                return a.bottomBorder
        if wa.topBorder.isOn(self._mascot.anchor):
            return wa.topBorder
        return NOT_ON_BORDER

    def get_ceiling(self, ignore_separator: bool = False):
        """原版 `getCeiling(boolean)` 的等价重载 / the original's overload."""
        return self.ceiling

    def wall(self, right=None):
        """
        左/右墙：**只在锚点确实贴着它时**返回它，否则返回 `NOT_ON_BORDER`。

        原版是按朝向取边：朝右时看「工作区右边 / 窗口左边」，朝左时反之 ——
        宠物面朝哪边，就该往那侧贴。我们之前用 `contains_x` 逐个候选找，
        会把「同一列上所有窗口的左右边」都算进来，于是宠物爬着爬着就换边了。

        The wall on the side the mascot faces; `NOT_ON_BORDER` when not on one.
        """
        if right is None:
            right = self._mascot.look_right
        p = self._mascot.anchor
        wa = self._env.work_area
        # 朝右贴的是「窗口左边」，朝左贴的是「窗口右边」/ while facing right it
        # clings to a window's LEFT edge, and vice versa.
        if right:
            for a in self._candidates():
                if a.leftBorder.isOn(p):
                    return a.leftBorder
            return wa.rightBorder if wa.rightBorder.isOn(p) else NOT_ON_BORDER
        for a in self._candidates():
            if a.rightBorder.isOn(p):
                return a.rightBorder
        return wa.leftBorder if wa.leftBorder.isOn(p) else NOT_ON_BORDER

    def get_wall(self, right=None, ignore_separator: bool = False):
        """原版 `getWall(boolean)` 的等价重载 / the original's overload."""
        return self.wall(right)

    @property
    def wallBorder(self):
        return self.wall()

    def getWall(self, right=None):
        return self.wall(right)

    def getFloor(self):
        return self.floor

    def getCeiling(self):
        return self.ceiling
