# -*- coding: utf-8 -*-
"""
内建动作 / Built-in actions
==============================================================================
对应原版 `com.group_finity.mascot.action.*` 里的 `種類="組み込み"` 动作。
每个类的行为都对照 jar 反编译结果实现。

Re-implements the `種類="組み込み"` actions of the original
`com.group_finity.mascot.action.*` package.  Every class mirrors the behaviour
recovered from the decompiled jar.

    Look        右向き 缺省 = 朝向翻转      / default = flip the facing direction
    Offset      位移 X / Y                  / shift the anchor by X / Y
    Jump        朝目标点匀速直线冲刺        / dash straight towards a target point
    Fall        v -= v*air; v += gravity    / air resistance then gravity
    Dragged     跟随光标                    / follow the cursor
    Regist      被抓住时挣扎                / struggle while held
    Breed       产生新宠物                  / spawn a new mascot
    WalkWithIE  抱着窗口走                  / walk while carrying a window
    FallWithIE  抱着窗口一起掉              / fall while dragging a window down
    ThrowIE     把窗口扔出去                / throw the window away
"""

from __future__ import annotations

import math

from .. import win32
from ..xml.expr import warn_eval_failure
from .environment import NOT_ON_BORDER, Pt
from .runtime import ActionInstance, AnimateInstance, InstantInstance

__all__ = ["BUILTINS", "Look", "Offset", "Jump", "Fall", "Dragged", "Regist",
           "Breed", "WalkWithIE", "FallWithIE", "ThrowIE"]

BUILTINS: dict[str, type] = {}


def _register(name: str):
    """内建类注册装饰器 / Decorator that registers a built-in action class."""
    def deco(cls):
        BUILTINS[name] = cls
        return cls
    return deco


class _Animated(ActionInstance):
    """带动画播放能力的内建动作基类 / Base class for animated built-in actions."""

    def init(self):
        super().init()
        self.pose_index = 0
        self.pose_time = 0
        self.anim = self._pick()

    def _pick(self):
        """挑选满足条件的动画 / Pick the first animation whose condition holds."""
        anims = self.defn.animations
        if not anims:
            return None
        ns = self.ns()
        for a in anims:
            if a.condition is None:
                return a
            try:
                if a.condition.eval(ns):
                    return a
            except Exception as exc:
                # 与 runtime.py 的 _pick_animation 同一件事：条件坏了就跳过
                # 这段动画（降级正确），但要留痕。
                # Same as runtime's _pick_animation: skip, but leave a trace.
                warn_eval_failure(getattr(a.condition, "raw", a.condition), exc)
                continue
        return anims[0]

    def advance_frame(self, dynamic: bool = False, loop: bool = True) -> bool:
        """
        播放一帧；返回 False 表示动画播放完毕。
        Play one frame; returns False when the animation has finished.
        """
        m = self.mascot
        if dynamic or self.anim is None:
            self.anim = self._pick()
        anim = self.anim
        if anim is None or not anim.poses:
            return False
        ns = self.ns()
        poses = anim.poses
        pose = poses[min(self.pose_index, len(poses) - 1)]
        name = pose.image.get(ns)
        if not isinstance(name, str):
            name = pose.image.text()
        base = pose.base.pair(ns, (64.0, 128.0))
        m.set_image(name, base)

        dur = int(pose.duration.num(ns, 1))
        self.pose_time += 1
        if self.pose_time >= max(1, dur):
            self.pose_time = 0
            self.pose_index += 1
            if self.pose_index >= len(poses):
                self.pose_index = 0
                return loop
        return True


# ---------------------------------------------------------------------------
# 朝向与位移 / facing and offset
# ---------------------------------------------------------------------------
@_register("Look")
class Look(InstantInstance):
    """
    转身 / Turn around
    ------------------
    原版 `Look.isLookRight()` 的缺省值是 `!mascot.isLookRight()`，
    也就是**不传 `右向き` 参数时直接把朝向翻转**。

    The original defaults to `!mascot.isLookRight()`, i.e. **without the
    `右向き` parameter the facing direction is simply flipped**.
    """

    def apply(self):
        default = not self.mascot.look_right
        self.mascot.set_look_right(self.pbool("lookRight", default))


@_register("Offset")
class Offset(InstantInstance):
    """位移 / Shift the anchor by X / Y (画像像素，会乘以缩放)."""

    def apply(self):
        s = self._scale()
        dx = self.pnum("x", 0) * s
        dy = self.pnum("y", 0) * s
        self._set_anchor(self._anchor().x + dx, self._anchor().y + dy)
        self.mascot.reposition()


# ---------------------------------------------------------------------------
# 跳跃与下落 / jumping and falling
# ---------------------------------------------------------------------------
@_register("Jump")
class Jump(_Animated):
    """
    跳跃 / Jump
    -----------
    原版实现并非抛物线，而是**朝目标点做匀速直线冲刺**：

    The original is not a parabola but a **constant-speed straight dash**:

        dx = targetX - anchor.x
        dy = (targetY - anchor.y) - |dx| / 2
        dist = sqrt(dx² + dy²)
        anchor += velocity * (dx, dy) / dist
    """

    def tick(self) -> bool:
        m = self.mascot
        tx = self.pnum("destX", m.anchor.x)
        ty = self.pnum("destY", m.anchor.y)
        speed = self.pnum("speed", 20) * self._scale()
        m.set_look_right(m.anchor.x < tx)
        dx = tx - m.anchor.x
        dy = ty - m.anchor.y
        dist = math.hypot(dx, dy)
        if dist <= max(1.0, speed):
            self._set_anchor(tx, ty)
            self.advance_frame()
            m.reposition()
            return False
        self._set_anchor(m.anchor.x + speed * dx / dist,
                         m.anchor.y + speed * dy / dist)
        self.advance_frame()
        m.reposition()
        return True


@_register("Fall")
class Fall(_Animated):
    """
    下落 / Fall
    -----------
        vx = vx - vx * 空気抵抗X
        vy = vy - vy * 空気抵抗Y + 重力
        modX += vx % 1 ; dx = int(vx) + int(modX)      （小数部分累积进位）

    **子步进碰撞检测**（原版 `Fall.tick` 的 OUTER 循环）—— 这一段是「窗口互动」
    能不能顺滑的关键，务必保留：

    一帧的位移可能有十几到几十像素（重力累积后很快）。如果整段位移一次性落地，
    中间的窗口顶边会被直接穿过，宠物看起来就是「从窗口旁边瞬移到屏幕底部」。
    原版的做法是把这一帧拆成 `dev = max(|dx|, |dy|)` 个子步，每步都测一次地面，
    撞上就停在那一小步上。向下时还会从落点往上回溯最多 80px（HACK IE），
    保证「正好落在窗口顶边」而不是穿到窗口下面。

    **Sub-stepped collision** (the original's OUTER loop) — this is what makes
    window interaction look right.  A single frame can move tens of pixels once
    gravity builds up; landing the whole step at once tunnels straight through a
    window's top edge and the mascot appears to teleport to the bottom of the
    screen.  The original splits the frame into `dev = max(|dx|, |dy|)` sub-steps
    and tests the floor at each one; while falling it additionally walks back up
    to 80px (the "HACK IE" loop) so the mascot lands *on* the edge rather than
    below it.
    """

    #: 向下穿地时向上回溯的最大像素 / how far back to search upward while falling
    BACKTRACK = 80

    def init(self):
        super().init()
        s = self._scale()
        self.vx = self.pnum("initVX", 0) * s
        self.vy = self.pnum("initVY", 0) * s
        self.gravity = self.pnum("gravity", 2) * s
        self.air_x = self.pnum("airX", 0.05)
        self.air_y = self.pnum("airY", 0.1)
        self.mod_x = 0.0
        self.mod_y = 0.0

    def _landed(self) -> bool:
        """
        是否已经落在某条边界上 / Is the mascot standing on any border now?

        对应原版 `Fall.hasNext()` 里的 `onBorder` 判定（`getFloor()` /
        `getWall()`，注意**不带** `ignoreSeparator`）。

        Mirrors the `onBorder` test in the original's `Fall.hasNext()`.
        """
        p = self.mascot.anchor
        env = self.mascot.env
        if env.floor is not NOT_ON_BORDER and env.floor.isOn(p):
            return True
        if env.wall() is not NOT_ON_BORDER and env.wall().isOn(p):
            return True
        return False

    def tick(self) -> bool:
        """
        推进一帧；返回 False 表示已经落在边界上、动作结束。

        **注意开头没有任何「已经在边界上就早退」的分支** —— 原版也没有。
        落地判定只发生在子步进循环里（撞到就停），以及动作**跑完之后**由
        `hasNext()` 判定。我们之前在 `tick()` 开头加了一个 `_landed()` 早退，
        结果是：`投げられる` 的 `落ちる` 子动作在构造时如果锚点恰好贴着地面，
        第一帧就直接返回 False —— 抛出后宠物纹丝不动，用户看到的就是
        「抛出动作不生效」。

        **There is deliberately no "already on a border" early return here**,
        matching the original.  Landing is detected only inside the sub-step
        loop (and by `hasNext()` once the action finishes).  Our earlier early
        return made `落ちる` end on its very first frame whenever the anchor
        happened to touch the floor, so a throw produced no motion at all.
        """
        m = self.mascot
        if self.vx != 0:
            m.set_look_right(self.vx > 0)
        self.vx = self.vx - self.vx * self.air_x
        self.vy = self.vy - self.vy * self.air_y + self.gravity
        self.mod_x += self.vx % 1.0
        self.mod_y += self.vy % 1.0
        dx = int(self.vx) + int(self.mod_x)
        dy = int(self.vy) + int(self.mod_y)
        self.mod_x -= int(self.mod_x)
        self.mod_y -= int(self.mod_y)

        # ---- 子步进 / sub-steps -------------------------------------------
        dev = max(abs(dx), abs(dy))
        if dev < 1:
            dev = 1
        start_x, start_y = m.anchor.x, m.anchor.y
        stopped = False
        for i in range(dev + 1):
            x = start_x + dx * i // dev
            y = start_y + dy * i // dev
            m.anchor = Pt(x, y)
            if dy > 0:
                # HACK IE：向下时从落点往上回溯，命中窗口顶边就停
                # HACK IE: while falling, walk back up to 80px so the mascot
                # lands *on* the window's top edge instead of below it.
                for j in range(-self.BACKTRACK, 1):
                    m.anchor = Pt(x, y + j)
                    if self._landed_falling():
                        stopped = True
                        break
                if stopped:
                    break
            if self._landed_falling():
                stopped = True
                break

        if stopped:
            # 贴到边界上后结束 —— 下一帧由行为层重新决策
            # Landed: finish, and let the behaviour layer decide what is next.
            self.vx = 0.0
            self.vy = 0.0
            self.advance_frame()
            m.reposition()
            return False

        self.advance_frame()
        m.reposition()
        return True

    def _landed_falling(self) -> bool:
        """
        下落途中的碰撞判定（原版 `getFloor(true)` / `getWall(true)`）。

        与 `_landed()` 的区别：原版的 `ignoreSeparator=true` 重载在下落途中
        允许落在显示器/任务栏的接缝上。单显示器下等价，这里保留独立方法
        以便逐行对照原版的 OUTER 循环。

        The collision test inside the original's OUTER loop.  It uses the
        `ignoreSeparator=true` overloads, which let a falling mascot land on a
        monitor/taskbar seam.  Equivalent on a single monitor.
        """
        p = self.mascot.anchor
        env = self.mascot.env
        f = env.get_floor(True)
        if f is not NOT_ON_BORDER and f.isOn(p):
            return True
        w = env.get_wall(None, True)
        return w is not NOT_ON_BORDER and w.isOn(p)


# ---------------------------------------------------------------------------
# 拖拽 / dragging
# ---------------------------------------------------------------------------
@_register("Dragged")
class Dragged(_Animated):
    """
    被捏住 / Dragged
    ----------------
    跟随光标移动，并按条件实时切换动画（原版 `つままれる` 有 5 段条件动画，
    条件里的 `footX` 是**平滑过的**脚部横坐标，不是锚点本身）。

    **结束条件不是固定帧数**。原版是：
        hasNext() = super.hasNext() && (time < 250 || Math.random() >= 0.1)
    且每帧只要光标横向移动超过 5px 就把 time 归零。所以「一直在动就一直被拖着」，
    只有停下来超过 250 帧（约 10 秒）才 probabilistically 松手。

    之前我们用固定的 40 帧上限，于是拖一会儿动作就自己断了，用户感觉
    「拖不动」；而停止后又因为 `advance_frame` 直接结束，宠物停在半空。

    The end condition is **not** a fixed frame count.  The original uses
    `time < 250 || random() >= 0.1` and resets `time` to 0 whenever the cursor
    moves more than 5px horizontally, so a moving cursor keeps it held and only
    a long pause (>250 ticks, ~10s) lets go probabilistically.  Our fixed 40-tick
    cap made the drag drop out early and left the mascot hanging in mid-air.
    """

    #: 静止多久后松手（tick）/ ticks of stillness before it lets go
    TIME_TO_REGIST = 250
    #: 光标横移多少像素算「在动」/ cursor movement that counts as "still being dragged"
    MOVE_EPS = 5

    def init(self):
        super().init()
        cur = self.mascot.manager.shared_env.cursor
        self.foot_x = cur.x
        self.foot_dx = 0.0

    def _has_next(self) -> bool:
        import random as _random
        intime = self.time < self.TIME_TO_REGIST
        lukewarm = _random.random() >= 0.1
        return intime or lukewarm

    def tick(self) -> bool:
        m = self.mascot
        if not m.dragging:
            return False
        cur = m.manager.shared_env.cursor
        # 光标在动就重新计时 —— 只要用户还在拖，就永远不会被判定为松手
        # Reset the timer while the cursor moves: as long as the user is still
        # dragging it can never be considered "let go".
        if abs(cur.x - m.anchor.x) >= self.MOVE_EPS:
            self.time = 0
        self.time += 1
        if not self._has_next():
            return False

        # 平滑脚部横坐标供动画条件使用（原版 footDx/footX 的阻尼）
        # Smoothed foot X for the animation conditions, as in the original.
        self.foot_dx = (self.foot_dx + (cur.x - self.foot_x) * 0.1) * 0.8
        self.foot_x += self.foot_dx
        self.locals["footX"] = self.foot_x

        self._set_anchor(cur.x + m.drag_offset.x, cur.y + m.drag_offset.y)
        self.advance_frame(dynamic=True)
        m.reposition()
        return True


@_register("Regist")
class Regist(_Animated):
    """挣扎 / Struggle — 被抓住时播放一整套挣扎动画 / plays the struggle animation while held."""

    def tick(self) -> bool:
        if not self.mascot.dragging:
            return False
        return self.advance_frame(loop=False)


# ---------------------------------------------------------------------------
# 增殖 / breeding
# ---------------------------------------------------------------------------
@_register("Breed")
class Breed(_Animated):
    """
    产生新宠物 / Breed
    ------------------
    参数 / parameters: 生まれる場所X, 生まれる場所Y, 生まれた時の行動
    受设置里的「允许自我增殖」与「宠物数量上限」约束。

    Constrained by the "allow self-cloning" and "mascot limit" settings.
    """

    def init(self):
        super().init()
        self.bred = False

    def tick(self) -> bool:
        m = self.mascot
        if not self.bred:
            self.bred = True
            mgr = m.manager
            # `effective_self_cloning` 而不是原始设置：多角色模式强制关闭增殖，
            # 否则新生儿会用**当前默认角色**的动作表，而它可能属于另一个
            # bundle，行为名对不上就什么都不做。
            # `effective_self_cloning` rather than the raw setting: multi-character
            # mode forces cloning off, otherwise a newborn would resolve names in
            # the default character's table while belonging to another bundle.
            if mgr.effective_self_cloning \
                    and mgr.count() < int(mgr.settings.get("max_count", 50)):
                s = self._scale()
                bx = self.pnum("birthX", 0) * s
                by = self.pnum("birthY", 0) * s
                if m.look_right:
                    bx = -bx
                born = self.p("bornBehavior", None)
                pt = Pt(m.anchor.x + bx, m.anchor.y + by)
                # 新生儿继承亲代的角色（增殖是「同角色多一只」，不是换角色）
                # The newborn inherits the parent's character: breeding makes
                # another copy of the *same* character, not a different one.
                b = getattr(m, "bundle", None)
                if b is not None:
                    child = mgr._summon_with(b, pt, m.look_right)
                    if child is not None:
                        child.forced_behavior = born
                else:
                    mgr.summon(pt, behavior=born, look_right=m.look_right)
        return self.advance_frame(loop=False)


# ---------------------------------------------------------------------------
# 与窗口(IE)互动 / window (IE) interaction
# ---------------------------------------------------------------------------
class _IEFollowMixin:
    """
    让窗口跟随宠物位移 / Makes a window follow the mascot's displacement.

    **目标窗口在动作 init 时锁定一次**，全程只跟着那一个 hwnd 走。

    原版 `WalkWithIE` / `FallWithIE` 在 `init()` 里保存 `getActiveIE()` 的引用，
    之后每帧都是「把宠物这一帧的位移量加到那个窗口上」。如果每帧都重新读
    `activeIE`（它跟着前台窗口走），会出现两个问题：

    1. 宠物带着窗口一起往下掉的过程中，用户切了个窗口 → `activeIE` 变成另一个
       窗口 → 位移量被加到不相干的窗口上，宠物自己却在原地；
    2. hwnd 每帧一变，`_ie_last` 就每帧重置，`dx/dy` 永远算不出来（恒为 0），
       窗口看起来「跟不动」。

    用户反馈的「关掉那个和窗口互动也不好使」就是第 2 种：拖动过程中换了窗口，
    位移一直被重置。锁定 hwnd 之后，窗口被关掉（`IsWindow` 失败）才释放。

    **但锁定不等于无条件跟到底 —— 被完全遮盖即放手。**

    1.1.3 把判定从「不再是前台」换成「**被完全遮盖**」。理由：可交互的判据
    是**用户看不看得见**，不是「谁在最前面」。用户把窗口拖到另一个窗口
    后面（完全被盖住）→ 那扇窗口用户根本看不见 → 宠物拖着它走就纯属莫名其妙。
    而窗口只是「退到后面但还露出一条边」时，用户看得见它，互动继续是合理的。

    放手的**时机**也重要：不是等动作结束才放，而是**当帧**就放。否则宠物会
    继续带着一扇已经看不见的窗口再走一段。

    这里**不重新选目标**：那会让宠物在一瞬间猛地转向另一个窗口，抱着它继续
    走 —— 比拖着旧窗口更突兀。**放手、让宠物自己回到地面**才是对的。

    The locked window is followed for the action's duration — but the lock is
    not unconditional: **being fully covered releases it.**  The test is
    whether the *user can see the window*, not which one is in front.  A
    window dragged completely behind another one is invisible, and dragging
    it around is pure nonsense; a window that merely peeks out from behind
    another is still visible, so the interaction carries on.

    The release happens on the very tick.  We deliberately do **not** re-target
    another window: the pet would suddenly grab something unrelated.
    """

    def _ie_init(self):
        """锁定要跟随的窗口 / Lock onto the window to carry."""
        m = self.mascot
        if not m.manager.settings.get("climb_enabled", True):
            self._ie_hwnd = None
            return
        a = m.manager.shared_env.activeIE
        self._ie_hwnd = a.hwnd if a.visible else None
        self._ie_last = (m.anchor.x, m.anchor.y)

    def _follow_window(self):
        m = self.mascot
        hwnd = getattr(self, "_ie_hwnd", None)
        if hwnd is None or not m.manager.settings.get("climb_enabled", True):
            return
        env = m.manager.shared_env
        a = env.window_by_hwnd(hwnd)
        # 窗口被关掉 / 最小化 / 不再可见 -> 放弃跟随，但不要抛异常
        if a is None or not a.visible:
            self._ie_hwnd = None
            return
        # 1.1.3：这扇窗口已经被**完全遮盖** -> 立刻放手，不再拖它。
        # 用户看不见它了，宠物拖着一扇看不见的窗口走，用户只会觉得莫名其妙。
        # The window has been fully covered: let go.  The user cannot see it
        # any more, so dragging an invisible window just looks bizarre.
        if env.is_occluded(hwnd):
            self._ie_hwnd = None
            return
        lx, ly = self._ie_last
        dx = m.anchor.x - lx
        dy = m.anchor.y - ly
        self._ie_last = (m.anchor.x, m.anchor.y)
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        if win32.is_zoomed(a.hwnd):
            return
        nl, nt = a.left + dx, a.top + dy
        # ★ 用 `move_window_at()` 拿**实际落点**：移动会被夹到当前屏幕内（虚拟桌面安全），落点可能不是请求的位置。若还按请求的
        # 坐标记录，引擎会认为窗口在别处 -> 下一帧位移累积成巨大跳跃。
        # Use the actual landing point: the move is clamped into the current
        # desktop, so it may differ from the requested one.
        landed = win32.move_window_at(a.hwnd, nl, nt)
        if landed is not None:
            env.sync_window(
                landed[0], landed[1],
                landed[0] + a.width, landed[1] + a.height)


@_register("WalkWithIE")
class WalkWithIE(_IEFollowMixin, AnimateInstance):
    """抱着窗口走 / Walk while carrying the window."""

    def init(self):
        super().init()
        self._ie_init()

    def tick(self) -> bool:
        running = super().tick()
        self._follow_window()
        return running


@_register("FallWithIE")
class FallWithIE(_IEFollowMixin, Fall):
    """抱着窗口一起下落（会把窗口拽下来）/ Fall while dragging the window down."""

    def init(self):
        super().init()
        self._ie_init()

    def tick(self) -> bool:
        running = super().tick()
        self._follow_window()
        return running


@_register("ThrowIE")
class ThrowIE(_Animated):
    """
    把窗口扔出去 / Throw the window
    --------------------------------
    参数 / parameters: 初速X, 初速Y, 重力

    目标窗口同样在 init 时锁定。原版 `ThrowIE` 也是这么做的：如果每帧重读
    `activeIE`，扔的过程中用户切个窗口就会换成别的窗口，窗口被「甩到别的
    窗口上」。
    """

    def init(self):
        super().init()
        s = self._scale()
        vx = self.pnum("initVX", 32) * s
        self.vx = vx if self.mascot.look_right else -vx
        self.vy = self.pnum("initVY", -10) * s
        self.gravity = self.pnum("gravity", 0.5) * s
        m = self.mascot
        a = m.manager.shared_env.activeIE
        self._ie_hwnd = a.hwnd if (a.visible and
                                    m.manager.settings.get("throw_enabled", True)) else None

    def tick(self) -> bool:
        hwnd = self._ie_hwnd
        if hwnd and self.mascot.manager.settings.get("throw_enabled", True):
            env = self.mascot.manager.shared_env
            a = env.window_by_hwnd(hwnd)
            # 窗口没了就只是空挥，宠物自己的动画照常播完
            # No window to throw: the mascot still finishes its own animation.
            if a is None or not a.visible:
                self._ie_hwnd = None
            # 1.1.3：目标窗口已经被**完全遮盖** -> 停止投掷。
            # 往一扇用户看不见的窗口上扔东西毫无意义 —— 用户只看到自己的
            # 窗口莫名其妙飞走了，却完全不明白发生了什么。
            # The target has been fully covered: stop throwing.  Flinging a
            # window the user cannot see is pointless — they just watch their
            # window fly off with no idea why.
            elif env.is_occluded(hwnd):
                self._ie_hwnd = None
            elif not win32.is_zoomed(a.hwnd):
                self.vy += self.gravity
                nl, nt = a.left + self.vx, a.top + self.vy
                # ★ 用 `move_window_at()` 拿**实际落点**：移动会被夹到当前屏幕内（虚拟桌面安全），落点可能不是请求的位置。若还按请求的
                # 坐标记录，引擎会认为窗口在别处 -> 下一帧位移累积成巨大跳跃。
                # Use the actual landing point: the move is clamped into the current
                # desktop, so it may differ from the requested one.
                landed = win32.move_window_at(a.hwnd, nl, nt)
                if landed is not None:
                    env.sync_window(
                        landed[0], landed[1],
                        landed[0] + a.width, landed[1] + a.height)
        running = self.advance_frame(loop=False)
        # 投掷结束（或窗口已经消失）时，把飞出工作区的窗口夹回来。
        #
        # 为什么需要这个：投掷的初速是 32px/帧，重力只往下拉，窗口很容易被扔到
        # 屏幕外 —— 而 Windows 不会自动帮你捞回来，用户只能去任务栏右键
        # 「移动」再把窗口拖回来，非常难用。更有甚者窗口整个飞出后连任务栏
        # 按钮都点不到（它在另一个显示器/屏幕外），看起来像程序把窗口搞坏了。
        #
        # 这里刻意**不在飞行途中夹**：边飞边被拽住，投掷就没意思了。只在动作
        # 结束的那一刻收尾，该有的快感一点没少，但窗口永远留在工作区里。
        #
        # Bring the window back into the work area once the throw ends.
        # The 32px/frame launch velocity easily sends a window off-screen, and
        # Windows will not retrieve it for you -- the user has to right-click
        # the taskbar button and use "Move", if the button is even reachable.
        # Deliberately NOT clamped mid-flight (that would ruin the throw);
        # only on the last frame, so the fun is intact but nothing is lost.
        if not running:
            self._reclaim_window()
        return running

    def _reclaim_window(self):
        """把被扔出工作区的窗口夹回可见区域 / Clamp a thrown window back inside."""
        hwnd = getattr(self, "_ie_hwnd", None)
        if not hwnd:
            return
        env = self.mascot.manager.shared_env
        a = env.window_by_hwnd(hwnd)
        if a is None or not a.visible:
            return
        # ⚠️ `Area` 没有 __iter__，只能按字段取。这里曾写成四元解包 ——
        # 必然抛 TypeError，而下面的 try/except 把它整个吞掉，于是这个
        # 「窗口被扔出屏幕后夹回来」的功能从 1.0.2 起就一直静默失效，
        # 直到 1.0.6 写回归测试时才暴露（测试自己也在犯同一个错）。
        # `Area` is not iterable.  The old four-way unpack always raised
        # TypeError, and the bare except below swallowed it, so this whole
        # feature had been silently dead since 1.0.2.
        try:
            wa = env.work_area
            left, top = wa.left, wa.top
            right, bottom = wa.right, wa.bottom
        except AttributeError:
            return
        # 已经完全在工作区内就不动它 —— 用户可能故意把窗口扔到某个角落。
        # Leave it alone when it is already fully inside: the user may have
        # aimed for a corner on purpose.
        if (a.left >= left and a.top >= top
                and a.right <= right and a.bottom <= bottom):
            return
        nl = min(max(a.left, left), max(left, right - a.width))
        nt = min(max(a.top, top), max(top, bottom - a.height))
        if (nl, nt) == (a.left, a.top):
            return
        # ★ 用 `move_window_at()` 拿**实际落点**：移动会被夹到当前屏幕内（虚拟桌面安全），落点可能不是请求的位置。若还按请求的
        # 坐标记录，引擎会认为窗口在别处 -> 下一帧位移累积成巨大跳跃。
        # Use the actual landing point: the move is clamped into the current
        # desktop, so it may differ from the requested one.
        landed = win32.move_window_at(hwnd, nl, nt)
        if landed is not None:
            env.sync_window(
                landed[0], landed[1],
                landed[0] + a.width, landed[1] + a.height)
