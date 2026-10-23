# -*- coding: utf-8 -*-
"""
动作运行时 / Action runtime
==============================================================================
把 XML 里声明的动作实例化成可逐帧推进的对象。语义参照原版 jar 反编译结果：

Instances of the actions declared in XML, advanced one tick at a time.
Semantics follow the decompiled original jar:

* `Pose.next`      —— 朝右时水平速度取反 / horizontal velocity is negated when facing right
* `Animate.tick`   —— 先吸附到锚框，脱离锚框则抛 LostGround（由行为切到「落下する」）
* `Fall.tick`      —— v -= v*air; v += gravity; 小数部分累积进位
* `Jump.tick`      —— 朝目标点做匀速直线冲刺
* `Look.apply`     —— 缺省参数即「朝向翻转」

LostGround 是整个引擎的中枢机制（原版 `LostGroundException`）：动作发现宠物
已经不在它依附的那条边界上时，**不是**安静地结束动作，而是抛出去让行为层立刻
切成「落下する」。少了这一步，宠物就会停在半空或被硬拽回边界 —— 也就是用户
看到的「上一秒还在任务栏上，下一秒就到屏幕最上面」。

LostGround is the pivot of the whole engine (the original's `LostGroundException`):
when an action finds the mascot is no longer on the border it clings to, it does
not quietly finish — it signals up so the behaviour layer switches to "Fall".
Without it the mascot hangs in mid-air or gets snapped back onto a border.
"""

from __future__ import annotations

import logging
import math

from ..xml.config import ActionDef, ActionRef
from .environment import NOT_ON_BORDER, Pt

__all__ = ["ActionInstance", "create_action",
           "AnimateInstance", "SequenceInstance", "SelectInstance", "InstantInstance"]

#: 模块级 logger / module logger
log = logging.getLogger(__name__)

#: 规范参数名 -> 日文参数名（表达式里直接用日文变量名）
# canonical param name -> Japanese name (expressions refer to the Japanese names)
JP_PARAM_NAMES = {
    "destX": "目的地X", "destY": "目的地Y",
    "initVX": "初速X", "initVY": "初速Y",
    "duration": "長さ", "lookRight": "右向き",
    "x": "X", "y": "Y",
    "speed": "速度", "gravity": "重力",
    "airX": "空気抵抗X", "airY": "空気抵抗Y",
    "birthX": "生まれる場所X", "birthY": "生まれる場所Y",
    "ieEdgeX": "IEの端X", "ieEdgeY": "IEの端Y",
}


class ActionInstance:
    """动作实例基类 / Base class of every action instance."""

    #: 组合动作最多套几层。`leaf()` / `progress()` 沿 child 链往下走，
    #: 这个上限只是防止配置里出现自引用时把遍历变成死循环。
    #: How deep a composite chain may nest.  `leaf()` / `progress()` walk the
    #: child chain and this only guards against a self-referencing config.
    MAX_COMPOSITE_DEPTH = 32

    def __init__(self, mascot, defn: ActionDef, params: dict, resolver,
                 seek: int = 0, seek_index: int = 0):
        self.mascot = mascot
        self.defn = defn
        self.resolver = resolver
        self.time = 0
        #: 会话恢复用的「续播」帧数：前 N 帧只补动画、不施加位移。
        #: 见 `AnimateInstance.tick` 第 0 步。
        #: Frame count to fast-forward on session restore: the first N ticks
        #: advance the animation only and apply no movement.
        try:
            self.seek_left = max(0, int(seek or 0))
        except (TypeError, ValueError):
            self.seek_left = 0
        #: 续播到组合动作的第几个子动作 / which child of a composite to resume at.
        try:
            self.seek_index = max(0, int(seek_index or 0))
        except (TypeError, ValueError):
            self.seek_index = 0
        self.locals: dict = {}
        #: 本次 tick 是否因「脱离边界」而结束 / set when this tick ended on LostGround.
        #: 由 Manager 读取并把行为切成「落下する」，见模块 docstring。
        self.lost_ground = False
        # 动作自带参数被引用处的参数覆盖 / reference params override the definition's
        merged = dict(defn.params)
        merged.update(params or {})
        self.merged = merged
        self.static: dict = {}
        self.init()

    # ------------------------------------------------------------------
    def ns(self) -> dict:
        """求值命名空间 / Namespace used for expression evaluation."""
        ns = self.mascot.namespace()
        constants = getattr(self.mascot.manager, "constants", None)
        if constants:
            ns.update(constants)
        ns.update(self.locals)
        return ns

    def init(self):
        """动作初始化：求值所有静态 `${}` 参数 / Evaluate every static `${}` parameter."""
        ns = self.mascot.namespace()
        constants = getattr(self.mascot.manager, "constants", None)
        if constants:
            ns.update(constants)
        for key, val in self.merged.items():
            if val.is_static:
                self.static[key] = val.get(ns, None)
        # 动作自身属性也参与 / the definition's own attributes too
        for key, val in self.defn.params.items():
            if key not in self.static and val.is_static:
                self.static[key] = val.get(ns, None)
        for key, value in self.static.items():
            self.locals[key] = value
            jp = JP_PARAM_NAMES.get(key)
            if jp:
                self.locals[jp] = value

    def p(self, key, default=None):
        """读取参数（静态优先，其次动态求值）/ Read a parameter."""
        if key in self.static:
            return self.static[key]
        val = self.merged.get(key)
        if val is None:
            return default
        if val.is_dynamic:
            v = val.get(self.ns(), default)
            self.locals[key] = v
            jp = JP_PARAM_NAMES.get(key)
            if jp:
                self.locals[jp] = v
            return v
        return val.get({}, default)

    def pnum(self, key, default=0.0) -> float:
        v = self.p(key, default)
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    def pbool(self, key, default=False) -> bool:
        v = self.p(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "on", "1")
        return bool(v)

    # ------------------------------------------------------------------
    # 会话恢复：这套动作到底跑到哪儿了 / where is this action right now?
    # ------------------------------------------------------------------
    def leaf(self) -> "ActionInstance":
        """
        当前**真正在播**的那个最内层动作 / the innermost action actually playing.

        必须往里钻一层的原因：组合动作（Sequence / Select）自己**从不**累加
        `time` —— 只有真正逐帧播动画的 `AnimateInstance` 会。原版 Behavior.xml 里
        绝大多数行为都是组合动作（「先走到那边 → 再坐下」），只看最外层的话
        `time` 永远是 0，续播功能等于没有。
        The reason for drilling down: composite actions never accumulate `time`
        themselves, only the leaf `AnimateInstance` does — and almost every
        behaviour in the original Behavior.xml is a composite.  Reading the
        outermost instance therefore always yields 0.
        """
        node = self
        for _ in range(self.MAX_COMPOSITE_DEPTH):
            nxt = getattr(node, "child", None)
            if nxt is None:
                break
            node = nxt
        return node

    def progress(self) -> tuple[int, int]:
        """
        `(子动作下标, 该子动作已跑帧数)` / `(child index, frames played in it)`.

        存档就靠这两个数：光有帧数不够 —— 组合动作得知道该从**哪一个**子动作
        接着放，否则「先走再坐」会从「先走」重新开始。
        Both numbers are needed: the frame count alone would restart the whole
        sequence at child 0.
        """
        node = self
        index = 0
        seen_index = False
        for _ in range(self.MAX_COMPOSITE_DEPTH):
            nxt = getattr(node, "child", None)
            if nxt is None:
                break
            if not seen_index and hasattr(node, "index"):
                # `_next_child` 先自增再返回，所以正在跑的是 index-1
                # `_next_child` increments before returning, so the running
                # child sits at index-1.
                index = max(0, int(node.index) - 1)
                seen_index = True
            node = nxt
        try:
            elapsed = int(getattr(node, "time", 0) or 0)
        except (TypeError, ValueError):
            elapsed = 0
        return index, max(0, elapsed)

    # ------------------------------------------------------------------
    def tick(self) -> bool:
        """推进一帧；返回 False 表示动作结束 / Advance one tick; False = finished."""
        return False

    def _make_child(self, item):
        """
        建一个子动作，并把**续播帧数交给第一个真正建出来的那个**。
        Build a child action, handing the resume frame count to the first one
        that actually gets created.

        为什么要「传下去」而不是各层自己补：组合动作自己不播动画（`time` 永远
        是 0），真正会消费 `seek_left` 的只有 `AnimateInstance`。所以这个帧数
        必须一路下沉到叶子动作，中间每一层建完孩子就把自己那份清零。
        Why hand it down: a composite does not play the animation itself, so
        only the leaf consumes `seek_left`.  The count therefore has to sink to
        the leaf, each level zeroing its own copy as it creates a child.
        """
        if isinstance(item, ActionRef):
            inst = self.resolver(self.mascot, item.name, item.params)
        elif isinstance(item, ActionDef):
            inst = self.resolver(self.mascot, None, {}, item)
        else:
            return None
        if inst is not None and self.seek_left:
            inst.seek_left = self.seek_left
            self.seek_left = 0
        return inst

    # 便捷方法 / convenience helpers -------------------------------------
    def _scale(self):
        return getattr(self.mascot, "scale", 1.0)

    def _anchor(self) -> Pt:
        return self.mascot.anchor

    def _set_anchor(self, x, y):
        self.mascot.anchor = Pt(x, y)


# ---------------------------------------------------------------------------
# 静止 / 移动 / 固定 —— 动画播放
# stay / move / fixed —— animation playback
# ---------------------------------------------------------------------------
class AnimateInstance(ActionInstance):
    """
    播放一段动画并（可选）朝目的地移动 / Plays an animation, optionally moving to a target.

    对应原版的 `Stay`（静止）/ `Animate`（固定）/ `Move`（移動）三合一。
    Covers the original's `Stay` / `Animate` / `Move`.

    边框在 **init 时捕获一次**（原版 `BorderedAction.init` 就是这么做的），
    不是每帧重算 —— 每帧重算会让宠物在窗口移动时跟着跳。
    The border is captured **once at init** (as the original's `BorderedAction`
    does), not recomputed per tick: recomputing makes the mascot hop along with
    a moving window.
    """

    def init(self):
        super().init()
        self.duration = self.p("duration", None)
        if self.duration is not None:
            self.duration = int(self.duration)
        self.dest_x = self.p("destX", None)
        self.dest_y = self.p("destY", None)
        self.pose_index = 0
        self.pose_time = 0
        self.anim = self._pick_animation()
        self.border = self._border()
        self.loop = (self.duration is not None
                     or self.dest_x is not None
                     or self.dest_y is not None)

    def _destinations(self):
        """
        取目的地 / Read the destination point.

        **`目的地X` / `目的地Y` 常常是动态表达式** —— `壁を登る` 就是
        `目的地Y="#{mascot.environment.workArea.bottom-64}"`（`#` 前缀表示
        每帧重算）。原版 `Move.tick()` 每帧都 `eval(getTargetY())`。

        我们之前在 `init()` 里求值一次，而 `p(key, None)` 对动态值的默认值
        是 `None`，于是 `dest_y` 变成 `None` —— **爬墙动作完全没有目的地**，
        既不会因到达而结束，动画条件 `目的地Y < mascot.anchor.y` 也永远拿到
        `None` 而走错分支。这正是用户说的「爬墙时只能蹭墙不动」。

        The destination is very often a **per-frame expression** (`#` prefix)
        and the original re-evaluates it every tick.  Caching it in `init()`
        turned `壁を登る`'s climb target into `None`, so the climb had no goal
        at all and its animation conditions all took the wrong branch.
        """
        dx = self.dest_x
        dy = self.dest_y
        # 只有动态参数才每帧重算；静态参数在 init 时已定 / only dynamic ones
        if self._is_dynamic("destX"):
            dx = self.p("destX", None)
        if self._is_dynamic("destY"):
            dy = self.p("destY", None)
        # 动画条件里会直接引用 `目的地X` / `目的地Y`
        # (e.g. `壁を登る` branches on `目的地Y < mascot.anchor.y`),
        # so publish this tick's values into the evaluation namespace.
        if dx is not None:
            self.locals["destX"] = dx
            self.locals["目的地X"] = dx
        if dy is not None:
            self.locals["destY"] = dy
            self.locals["目的地Y"] = dy
        return dx, dy

    def _is_dynamic(self, key) -> bool:
        val = self.merged.get(key)
        if val is None:
            val = self.defn.params.get(key)
        return val is not None and val.is_dynamic

    def _pick_animation(self):
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
            except Exception:
                continue
        return anims[0]

    def _border(self):
        """
        按 `枠` 取边界，**只取一次** / Resolve the `枠` frame once, at init.

        可能返回 `NOT_ON_BORDER` —— 那意味着「宠物现在不在任何边界上」，
        动作会在第一帧就抛 LostGround，由行为层切成「落下する」。这正是原版
        的行为，也是「窗口一关宠物就掉下去」而不是「粘在半空」的关键。

        May return `NOT_ON_BORDER`, which makes the action raise LostGround on
        its first tick so the behaviour layer switches to "Fall" — exactly what
        the original does, and what makes the mascot drop when its window is
        closed instead of hanging in mid-air.
        """
        frame = self.defn.frame
        if not frame:
            return None
        env = self.mascot.env
        if frame == "ground":
            return env.floor
        if frame == "ceiling":
            return env.ceiling
        if frame == "wall":
            # 1.1.2：**先按位置找**实际贴着的那条墙，再退回按朝向找。
            # 以前直接 `env.wall(look_right)` —— 那是「朝右查窗口左边、
            # 朝左查窗口右边」的规则，而爬墙动作没有目的地X、朝向沿用爬之前的
            # 值，于是经常**查错边**：宠物明明贴在屏幕左墙上，却因为朝右而去
            # 查右墙，判定不成立 -> 动作第一帧就 LostGround -> 表现为
            # 「爬墙爬到一半就掉下来」或「贴图镜像反了」。
            #
            # 按位置找就没有这个问题：位置是事实。
            # Find the wall by position first.  Asking `wall(look_right)` used
            # to pick the wrong side whenever the inherited facing disagreed
            # with where the pet actually was, and the action then raised
            # LostGround on its first frame.
            _w = env.wall_at()
            if _w is not None:
                return _w
            return env.wall(self.mascot.look_right)
        return None

    def _seek_pose(self, ns) -> None:
        """
        只推进一步动画，**不施加位移** / Advance the animation one frame, no movement.

        会话恢复时把动画补到存档那一帧用的。位移必须不重放 —— 宠物已经站在
        存档位置上了，再走一遍的表现就是「重启后瞬移」。
        Used on session restore to bring the animation up to the saved frame.
        Movement must not be replayed: the mascot already stands where it was
        saved, and walking it again looks exactly like a teleport on start-up.
        """
        self.anim = self._pick_animation()
        poses = self.anim.poses if self.anim is not None else []
        if not poses:
            return
        pose = poses[min(self.pose_index, len(poses) - 1)]
        dur = int(pose.duration.num(ns, 1))
        self.pose_time += 1
        if self.pose_time >= max(1, dur):
            self.pose_time = 0
            self.pose_index = (self.pose_index + 1) % len(poses)
        pose = poses[min(self.pose_index, len(poses) - 1)]
        name = pose.image.get(ns)
        if not isinstance(name, str):
            name = pose.image.text()
        base = pose.base.pair(ns, (64.0, 128.0))
        self.mascot.set_image(name, base)
        self.mascot.reposition()

    def tick(self) -> bool:
        self.time += 1
        m = self.mascot
        ns = self.ns()
        dest_x, dest_y = self._destinations()

        # 0) 会话恢复续播：只补动画帧，位移一步都不走。
        #    On session restore, fast-forward the animation only; not one step
        #    of movement is replayed.
        if self.seek_left > 0:
            self.seek_left -= 1
            if self.duration is not None and self.time > self.duration:
                return False
            self._seek_pose(ns)
            return True

        # 1) 吸附到锚框；脱离则抛 LostGround / snap onto the frame; LostGround if it lets go
        border = self.border
        if border is not None:
            m.anchor = border.move(m.anchor)
            if border is not NOT_ON_BORDER and not border.isOn(m.anchor):
                self.lost_ground = True
                return False

        # 2) 总时长 / total duration
        if self.duration is not None and self.time > self.duration:
            return False

        if self.anim is None:
            return False
        # **动画条件每帧重选**（原版 `ActionBase.getAnimation()` 每帧遍历）。
        # `壁を登る` 的两段动画靠 `目的地Y < mascot.anchor.y` 区分向上/向下爬，
        # 而 `目的地Y` 是动态表达式 —— 只在 init 选一次的话，宠物爬到顶时
        # 还在播向上爬的动画，看起来就是「蹭到顶就不动了」。
        # Re-pick the animation every tick (the original's `getAnimation()`
        # walks the list each frame).  `壁を登る` switches between climb-up and
        # climb-down animations on the dynamic `目的地Y`, so caching the pick
        # left it animating upwards forever at the top of the wall.
        self.anim = self._pick_animation()
        poses = self.anim.poses
        if not poses:
            return False
        pose = poses[min(self.pose_index, len(poses) - 1)]

        # 3) 面朝目的地（原版 Move.tick 每帧都做）/ face the destination every tick
        if dest_x is not None and m.anchor.x != dest_x:
            m.set_look_right(m.anchor.x < dest_x)

        # 3b) 爬墙时朝向由「实际贴住哪条墙」决定（1.1.2）
        #     On a wall, the facing follows the wall the pet is actually on.
        #
        # 爬墙动作（`壁を登る`）**只有目的地Y、没有目的地X**，所以上面第 3 步
        # 根本不会执行 —— 朝向就一路沿用「爬之前」的值。宠物从右边走到屏幕
        # 左墙时朝向右，于是**贴着左墙往上爬、贴图却是朝右的**，看起来就是
        # 「爬墙时镜像反了」。
        #
        # 而且这个错误会**自我强化**：`wall()` 是按 `look_right` 选边的
        # （朝右查窗口左边、朝左查窗口右边），朝向错 -> 查到另一条边 ->
        # 判定不成立 -> 动作第一帧就 LostGround。
        #
        # 所以这里**不看朝向，改看位置**：先由锚点找出真正贴着的那条墙，
        # 再由那条墙决定贴图该朝哪边。位置是事实，朝向只是对事实的解读 ——
        # 反过来让朝向决定位置，就会出现「因为朝右所以去找右墙，可我明明
        # 贴在左墙上」的死循环。
        #
        # 这一步放在第 3 步**之后**：有目的地X时以目的地为准（走路场景要
        # 朝向目的地），没有目的地X时（爬墙）才由墙来定。
        #
        # The climb action has a destination Y but **no destination X**, so
        # step 3 never runs and the facing is inherited from before the climb
        # — the pet walks to the left wall facing right and climbs it with a
        # right-facing sprite.  Worse, the error is self-reinforcing: `wall()`
        # picks a side *from* the facing, so a wrong facing looks for the
        # wrong edge and the action raises LostGround on its first frame.
        #
        # So here the position decides: find the wall the pet is really on,
        # then let that wall decide the sprite's facing.
        if self.defn.frame == "wall" and dest_x is None:
            try:
                _w = m.env.wall_at()
                if _w is not None:
                    m.set_look_right(m.env.facing_for_wall(_w))
            except Exception:  # noqa: BLE001 - 朝向错了不该让动作崩掉
                log.debug("resolving wall facing failed", exc_info=True)

        # 4) 按速度移动（朝右时水平取反）/ move; negate horizontal velocity when facing right
        vx, vy = pose.velocity.pair(ns, (0.0, 0.0))
        s = self._scale()
        dx = (-vx if m.look_right else vx) * s
        dy = vy * s
        finished = False
        self._set_anchor(m.anchor.x + dx, m.anchor.y + dy)

        # 5) 目的地判定 / have we reached the destination?
        #    只在「已经越过」时吸附并结束，且**不判定 LostGround** —— 走到目的地
        #    停下是正常结局，不是掉到边界外。对齐原版 `Move.tick()`。
        #    Snap only once the target is actually reached, and do NOT raise
        #    LostGround: arriving is a normal ending, not a fall.
        if dest_x is not None:
            ax = m.anchor.x
            if (dx < 0 and ax <= dest_x) or (dx > 0 and ax >= dest_x):
                self._set_anchor(dest_x, m.anchor.y)
                finished = True
        if dest_y is not None:
            ay = m.anchor.y
            if (dy < 0 and ay <= dest_y) or (dy > 0 and ay >= dest_y):
                self._set_anchor(m.anchor.x, dest_y)
                finished = True

        # 6) 推进帧 / advance the frame
        #
        #    这里**不做任何屏幕内钳制**。原版 `Move.tick()` / `Stay.tick()` /
        #    `Animate.tick()` 都没有 clamp：宠物走出屏幕是由 `UserBehavior`
        #    的 "Out of the screen bounds" 分支统一救回来的（见
        #    `Manager._rescue_if_offscreen`）。我们之前在这里夹了一句
        #    `ay = max(wa.top - 200, ...)`，结果爬墙爬到窗口顶边时 y 被强行
        #    拉回工作区上沿 200px 处 —— 用户描述的「下一秒瞬间到顶上」。
        #
        #    **No screen clamping here.**  None of the original's `Move` /
        #    `Stay` / `Animate` clamp; an off-screen mascot is fished back by
        #    `UserBehavior`'s "Out of the screen bounds" branch instead.  Our
        #    clamp yanked a wall-climbing mascot back to 200px above the work
        #    area — the reported "next tick it teleports to the top".
        dur = int(pose.duration.num(ns, 1))
        self.pose_time += 1
        if self.pose_time >= max(1, dur):
            self.pose_time = 0
            self.pose_index += 1
            if self.pose_index >= len(poses):
                self.pose_index = 0
                if not self.loop:
                    finished = True

        # 7) 出图 / render
        pose = poses[min(self.pose_index, len(poses) - 1)]
        name = pose.image.get(ns)
        if not isinstance(name, str):
            name = pose.image.text()
        base = pose.base.pair(ns, (64.0, 128.0))
        m.set_image(name, base)
        m.reposition()
        return not finished


# ---------------------------------------------------------------------------
# 复合 / 选择
# composite & select
# ---------------------------------------------------------------------------
class SequenceInstance(ActionInstance):
    """顺序执行子动作 / Runs its children one after another."""

    def init(self):
        super().init()
        # 会话恢复：从存档里的那个子动作接着放，而不是从头再来。
        # Session restore: resume at the saved child instead of from the start.
        self.index = self.seek_index
        self.child = None

    def _next_child(self):
        children = self.defn.children
        while self.index < len(children):
            item = children[self.index]
            self.index += 1
            inst = self._make_child(item)
            if inst is not None:
                return inst
        return None

    def tick(self) -> bool:
        if self.child is None:
            self.child = self._next_child()
            if self.child is None:
                if self.defn.repeat and self.defn.children:
                    self.index = 0
                    self.child = self._next_child()
                    if self.child is None:
                        return False
                else:
                    return False
        if not self.child.tick():
            # 子动作报 LostGround 就向上传递，不能被 repeat 循环吞掉 ——
            # 否则「走 → 掉出窗口 → 重新走」会原地打转，宠物看起来在蹭边缘。
            # Propagate LostGround from the child; `repeat` must not swallow it,
            # otherwise walk -> fall off -> walk loops forever on the same spot.
            self.lost_ground = self.child.lost_ground
            self.child = None
        return True


class SelectInstance(ActionInstance):
    """按条件挑选一个子分支执行 / Picks the first child whose condition holds."""

    def init(self):
        super().init()
        self.child = None

    def _make(self, item):
        return self._make_child(item)

    def tick(self) -> bool:
        if self.child is None:
            ns = self.ns()
            chosen = None
            fallback = None
            for item in self.defn.children:
                cond = item.condition if isinstance(item, ActionDef) else getattr(item, "condition", None)
                if cond is None:
                    if fallback is None:
                        fallback = item
                    continue
                try:
                    if cond.eval(ns):
                        chosen = item
                        break
                except Exception:
                    continue
            if chosen is None:
                chosen = fallback if fallback is not None else (
                    self.defn.children[0] if self.defn.children else None)
            if chosen is None:
                return False
            self.child = self._make(chosen)
            if self.child is None:
                return False
        if not self.child.tick():
            self.lost_ground = self.child.lost_ground
            return False
        return True


class InstantInstance(ActionInstance):
    """一次性动作（Look / Offset）的基类 / Base class of one-shot actions."""

    def init(self):
        super().init()
        self.done = False

    def apply(self):
        raise NotImplementedError

    def tick(self) -> bool:
        if not self.done:
            self.done = True
            self.apply()
        return False


# ---------------------------------------------------------------------------
# 工厂 / factory
# ---------------------------------------------------------------------------
_BUILTIN_CACHE: dict[str, type] = {}


def _builtin_classes() -> dict[str, type]:
    global _BUILTIN_CACHE
    if _BUILTIN_CACHE:
        return _BUILTIN_CACHE
    from . import builtin  # 延迟导入，避免循环依赖 / lazy import avoids a cycle
    _BUILTIN_CACHE = builtin.BUILTINS
    return _BUILTIN_CACHE


def create_action(mascot, name, params=None, defn=None,
                  seek: int = 0, seek_index: int = 0) -> ActionInstance | None:
    """
    创建一个动作实例。
    Create an action instance.

    `seek` / `seek_index` 只给「会话恢复」用：让动作从第 N 帧的动画状态接着播，
    而不重放前面那 N 帧的位移（宠物已经站在存档位置上了，再放一遍就是瞬移）。
    `seek_index` 是组合动作里「从第几个子动作接着放」的下标。
    两者都会**沿 child 链一路下沉到真正播动画的那个叶子动作**（见
    `ActionInstance._make_child`）—— 组合动作自己不播动画，帧数停在它身上没用。
    `seek` exists solely for session restore: continue from the Nth animation
    frame without replaying the Nth movement steps, which would teleport a
    mascot already standing at its saved position.  Both values sink down the
    child chain to the leaf that actually plays the animation — a composite
    does not animate, so a frame count left on one does nothing.

    `name` 为 None 时直接使用 `defn`（内联动作）。
    When *name* is None, *defn* (an inline action) is used directly.

    **动作表按宠物取**：1.0.3 支持多个不同角色同屏，每只宠物带着自己的
    `CharacterBundle`，动作名必须在**它自己那张表**里查。多角色没开时回退到
    manager 的全局表，行为与之前完全一致。
    The action table is resolved **through the mascot**: since 1.0.3 several
    distinct characters can share the screen and each carries its own bundle, so
    names are looked up in that mascot's own table.  Without multi-character mode
    this falls back to the manager's global table, behaving exactly as before.
    """
    bundle = getattr(mascot, "bundle", None)
    actions = bundle.actions if bundle is not None else mascot.manager.actions
    if defn is None:
        if not name:
            return None
        defn = actions.get(name)
        if defn is None:
            return None
    params = params or {}

    def resolver(m, n, p, d=None):
        return create_action(m, n, p, d)

    kind = defn.kind
    if kind == "builtin":
        cls = _builtin_classes().get(defn.builtin or "")
        if cls is not None:
            return cls(mascot, defn, params, resolver, seek, seek_index)
        # 未知内建类：退化成一次性动作 / unknown built-in: degrade to a no-op
        return InstantInstance(mascot, defn, params, resolver, seek, seek_index)
    if kind in ("composite",):
        return SequenceInstance(mascot, defn, params, resolver, seek, seek_index)
    if kind == "select":
        return SelectInstance(mascot, defn, params, resolver, seek, seek_index)
    return AnimateInstance(mascot, defn, params, resolver, seek, seek_index)
