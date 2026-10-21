# -*- coding: utf-8 -*-
"""
宠物窗口 / Mascot window
==============================================================================
一个无边框、背景透明、可置顶、按 alpha 抠图的 QWidget；负责渲染当前帧、
按锚点定位、以及鼠标拖拽 / 右键菜单的交互。

A frameless, translucent, optionally always-on-top QWidget with an alpha-derived
input mask.  It renders the current frame, positions itself from the anchor point
and handles dragging and the context menu.

坐标换算（与原版 Mascot.getBounds 一致）/ Geometry (same as Mascot.getBounds)
------------------------------------------------------------------------------
    left = anchor.x - base.x * scale           （朝左 / facing left）
    left = anchor.x - (width - base.x) * scale （朝右 / facing right, mirrored）
    top  = anchor.y - base.y * scale
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBitmap, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QWidget

from .environment import MascotEnvironment, Pt
from .petstate import PetStatus

__all__ = ["CharacterBundle", "ImageSet", "Mascot", "MascotRef"]

#: 视为"不透明"的 alpha 阈值 / alpha above this counts as a solid pixel
ALPHA_THRESHOLD = 16


class ImageSet:
    """角色图片集（shime1..N.png + icon.png）/ A character's image set."""

    def __init__(self, img_dir: str):
        self.dir = img_dir
        self.images: dict[str, QPixmap] = {}
        self.icon: QPixmap | None = None
        self.load()

    def load(self):
        self.images.clear()
        if not os.path.isdir(self.dir):
            return
        for fn in sorted(os.listdir(self.dir)):
            if not fn.lower().endswith(".png"):
                continue
            pix = QPixmap(os.path.join(self.dir, fn))
            if pix.isNull():
                continue
            if fn.lower() == "icon.png":
                self.icon = pix
            else:
                self.images[fn] = pix
        if self.icon is None and "shime1.png" in self.images:
            self.icon = self.images["shime1.png"]

    def get(self, name: str) -> QPixmap | None:
        """按配置里的图片名取图（"/shime1.png" -> shime1.png）/ Look up an image by name."""
        if not name:
            return None
        key = name.lstrip("/\\")
        return self.images.get(key)

    @property
    def names(self):
        return sorted(self.images.keys())


class CharacterBundle:
    """
    一个角色的全部资源 / Everything one character needs.

    1.0.2 时`Manager` 只有一套 `actions`/`behaviors`/`images`，所有宠物共用 ——
    所以屏幕上只可能出现「同一个角色的多只」。1.0.3 要支持同时召唤**不同角色**，
    资源就必须按角色分组持有：每只宠物记住所属bundle，`Brain` 与
    `create_action` 通过宠物取自己角色的动作表，而不是去问 Manager 要那个全局的。

    Since 1.0.2 the manager held a single `actions`/`behaviors`/`images` triple
    shared by every mascot, so only multiple copies of one character could ever
    appear.  Supporting several distinct characters at once means the resources
    are grouped per character: each mascot remembers its own bundle and both the
    behaviour chooser and the action factory resolve through the mascot.
    """

    def __init__(self, label: str, directory: str, images: "ImageSet",
                 actions, behaviors, constants: dict):
        self.label = label          # 显示名/ 目录名 / display (folder) name
        self.directory = directory
        self.images = images
        self.actions = actions
        self.behaviors = behaviors
        self.constants = constants

    def behavior_by_name(self, name: str):
        if not name:
            return None
        for _, b in self.behaviors.entries:
            if b.name == name:
                return b
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CharacterBundle {self.label!r}>"


class MascotRef:
    """表达式命名空间里的 `mascot` 对象 / The `mascot` object exposed to expressions."""

    def __init__(self, mascot: "Mascot"):
        self._m = mascot

    @property
    def anchor(self):
        return self._m.anchor

    @property
    def lookRight(self):
        return self._m.look_right

    @property
    def look_right(self):
        return self._m.look_right

    @property
    def totalCount(self):
        return self._m.manager.count()

    @property
    def environment(self):
        return self._m.env

    @property
    def fleeTargetX(self):
        """输入回避时要飞扑到的 X（`None` = 没有在回避）。

        暴露给表达式是为了让**角色包**能写出「往屏幕左边/右边跑」的目的地，
        而不必改 `Actions.xml` —— 那是原版配置文件，全生态共用，改它等于
        改动所有角色的行为。原版的 `走る` 目的地是随机表达式
        （`workArea.left+64+Math.random()*(width-128)`），光翻转朝向只会让它在
        屏幕中间随机走 —— 那正是 1.0.10「宠物凭空行走」的成因。
        Exposed so character packs can express the flee target; `Actions.xml`
        is the original shared config, so editing it would change every pack.
        """
        return getattr(self._m, "_avoid_target_x", None)


class Mascot(QWidget):
    """桌上的一只宠物 / One mascot on the desktop."""

    # 请求右键菜单 / emitted when a context menu is requested
    menuRequested = Signal(object, object)

    def __init__(self, manager, image_set: ImageSet, env, scale: float = 1.0,
                 always_on_top: bool = True, opacity: float = 1.0,
                 bundle: "CharacterBundle | None" = None):
        super().__init__()
        self.manager = manager
        self.images = image_set
        self.shared_env = env
        self.env = MascotEnvironment(env, self)
        #: 1.0.3：所属角色的资源集。多角色共存时不同宠物用不同的动作表。
        #: The resources of the character this mascot belongs to.
        self.bundle = bundle

        #: 1.0.3：养成数值与状态（CalMode）。每只宠物一份，
        #: 由 `Brain` 读取它来决定行为的出现频率。
        #: The pet's own care numbers (CalMode); `Brain` reads it to bias
        #: how often each kind of behaviour comes up.
        self.status = PetStatus()

        self.anchor = Pt(200, 600)
        self.look_right = False
        self.image_name = ""
        self.base = Pt(64, 128)      # 当前帧的基准坐标 / anchor inside the image
        self.scale = scale

        self.dragging = False
        self.drag_offset = Pt(0, 0)
        self.visible_image = None

        #: 行为名队列（等待执行）/ pending behaviour names, executed in order.
        #:
        #: 原版的行为切换是「替换」语义（`mascot.setBehavior()` 直接换掉当前
        #: behavior），但**替换的时机**由 `UserBehavior.next()` 把控：动作跑完
        #: 才换下一条。我们之前在 `begin_drag` / `end_drag` 里直接
        #: `mascot.action = None`，等于在动作**跑到一半**时把它掐断 —— 表现就是
        #: 「动作不连贯」「上一秒还在任务栏上，下一秒就到屏幕最上面」。
        #:
        #: 改成队列后：强制行为排队，等当前动作自然结束再依次执行；只有用户
        #: 主动拖拽（`interrupt=True`）才立刻接管，因为那时用户已经按住宠物了，
        #: 任何延迟都会手感发涩。
        #:
        #: The original replaces the behaviour too, but only *after* the current
        #: action finishes.  We used to null out `mascot.action` mid-action, which
        #: truncated animations and caused the visible teleport.  Now forced
        #: behaviours queue up; only an explicit drag interrupts, because the user
        #: is already holding the mascot and any delay feels broken.
        self.pending_behaviors: list[str] = []

        #: 1.0.10 输入回避：**进入**回避区时定下的逃跑方向（-1 左 / +1 右 / 0 未定）
        #: 与「上一帧是否还在区内」。两者一起用：每帧重算方向会折返，而只在
        #: 首次进入时定会让宠物出去再被推进来时沿用上次的边。判据是
        #: 「这一帧在区内、上一帧在区外」。
        #: Pinned flee direction plus "was inside last frame".  Recomputing every
        #: tick makes the pet double back; pinning only on the first entry keeps
        #: a stale side once the pet leaves and is pushed back in.
        self._avoid_dir = 0
        self._avoid_in = False
        #: 1.0.11：这次要飞扑到的屏幕边缘 X（-1 / +1 时分别是左边 / 右边）。
        #: `None` = 不在回避。供 `MascotRef.fleeTargetX` 读，让自定义动作里能写
        #: `目的地X="#{mascot.fleeTargetX}"` 真正飞过去。
        #: Where to leap to: the X of the nearer screen edge.  None = not fleeing.
        self._avoid_target_x = None

        #: 会话恢复用：上次退出时正在播放的行为名与已经跑了多少帧。
        #: 下一个动作创建时会**只对同名行为**生效（见 `Manager._tick_mascot`）：
        #: 存档里的行为在新角色表里不存在时，行为选择会自动退回到正常随机，
        #: 这时候把 `resume_seek` 用在别的动作上就会莫名其妙地跳帧。
        #: Session-restore state: the behaviour that was playing when the app was
        #: closed, and how many frames into it we were.  It is applied only when
        #: the *same* behaviour comes up (see `Manager._tick_mascot`): if the
        #: saved behaviour is missing from the character's table the normal
        #: random pick takes over, and applying the seek to some other action
        #: would skip frames for no reason.
        self.resume_behavior: str | None = None
        self.resume_seek: int = 0
        self.resume_index: int = 0

        #: 1.0.9：下一次挑行为时**忽略「次の行動リスト」约束**，强制走全局池。
        #: 只给「鼠标静止聚集」的自动散开用：原版那条链是封闭的，不明确放出来
        #: 宠物会一直坐在那儿看鼠标。用掉一次就由 Manager 清掉。
        #: 1.0.9: ignore the "next behaviour list" for the next pick and go
        #: straight to the global pool.  Only used when releasing the pets from
        #: the closed "gather around the cursor" chain; Manager clears it once
        #: it has been consumed.
        self.release_next_list: bool = False

        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setWindowOpacity(opacity)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

        self._mask_cache: dict[tuple, QRegion] = {}
        self._pix_cache: dict[tuple, QPixmap] = {}

    # ------------------------------------------------------------------
    # 渲染 / rendering
    # ------------------------------------------------------------------
    def _pixmap(self, name: str, mirrored: bool) -> QPixmap | None:
        key = (name, mirrored, self.scale)
        pix = self._pix_cache.get(key)
        if pix is not None:
            return pix
        src = self.images.get(name)
        if src is None:
            return None
        if mirrored:
            w = max(1, int(round(src.width() * self.scale)))
            h = max(1, int(round(src.height() * self.scale)))
            scaled = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = scaled.transformed(QTransform(-1, 0, 0, 1, w, 0))
        else:
            w = max(1, int(round(src.width() * self.scale)))
            h = max(1, int(round(src.height() * self.scale)))
            pix = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pix_cache[key] = pix
        return pix

    def _region_for(self, pix: QPixmap) -> QRegion:
        """按 alpha 生成可点击区域（按行合并矩形）/ Build a clickable region from alpha."""
        from PySide6.QtGui import QImage
        key = (self.image_name, self.look_right, self.scale)
        reg = self._mask_cache.get(key)
        if reg is not None:
            return reg
        w, h = pix.width(), pix.height()
        img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
        region = QRegion()
        for y in range(h):
            x = 0
            while x < w:
                if ((img.pixel(x, y) >> 24) & 0xFF) > ALPHA_THRESHOLD:
                    x0 = x
                    while x < w and ((img.pixel(x, y) >> 24) & 0xFF) > ALPHA_THRESHOLD:
                        x += 1
                    region = region.united(QRect(x0, y, x - x0, 1))
                else:
                    x += 1
        self._mask_cache[key] = region
        return region

    def set_image(self, name: str, base=None):
        """设置当前帧 / Set the current frame."""
        if not name:
            return
        self.image_name = name
        if base is not None:
            self.base = Pt(base[0], base[1])
        pix = self._pixmap(name, self.look_right)
        if pix is None:
            self.clearMask()
            self.update()
            return
        if self.width() != pix.width() or self.height() != pix.height():
            self.setFixedSize(pix.width(), pix.height())
        self.setMask(self._region_for(pix))
        self.reposition()
        self.update()

    def set_look_right(self, value: bool):
        if self.look_right == value:
            return
        self.look_right = value
        self._pix_cache.clear()
        self._mask_cache.clear()
        if self.image_name:
            self.set_image(self.image_name)

    def reposition(self):
        """按锚点与基准坐标移动窗口 / Move the window to match the anchor."""
        src = self.images.get(self.image_name)
        iw = src.width() if src else 128
        bx = (iw - self.base.x) if self.look_right else self.base.x
        left = self.anchor.x - bx * self.scale
        top = self.anchor.y - self.base.y * self.scale
        self.move(int(round(left)), int(round(top)))

    def set_scale(self, scale: float):
        self.scale = scale
        self._pix_cache.clear()
        self._mask_cache.clear()
        if self.image_name:
            self.set_image(self.image_name)

    # ------------------------------------------------------------------
    # 外观开关 / appearance switches
    # ------------------------------------------------------------------
    def set_opacity(self, value: float):
        """
        设窗口不透明度 / Set the window opacity.

        夹到 `[0.1, 1.0]`：0 会让窗口整个消失，用户以为程序崩了；
        而 Qt 对 0 的处理也不可靠（下层窗口会透出来）。0.1 就是「几乎看不见」，
        够用且不会引发这类误解。

        Clamped to `[0.1, 1.0]`: 0 makes the window vanish entirely (users read
        that as a crash) and Qt's handling of 0 is unreliable anyway (lower
        windows bleed through).  0.1 is "almost invisible" and still honest.

        与设置窗口的 `opacity_spin` 范围保持一致，避免两条路径能设出不同值。
        Same range as the settings window's spinner so the two paths can never
        disagree about what is legal.
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        v = min(1.0, max(0.1, v))
        self.setWindowOpacity(v)
        self.update()

    def set_click_through(self, enabled: bool):
        """
        鼠标穿透 / Mouse click-through.

        `Qt.WA_TransparentForMouseEvents` 让整个窗口对鼠标**完全透明** ——
        不是「只有图像外的透明像素不响应」（那是 `setMask` 一直在做的事），
        而是连不透明像素上的点击和拖拽也一并丢掉，事件直接落到下层窗口。

        这正是用户要的效果：小猫横在输入框上时，按不到它就等于不在。

        This is `Qt.WA_TransparentForMouseEvents`: the whole window becomes
        transparent to the mouse.  Clicks and drags on *opaque* pixels fall
        through to whatever is underneath, instead of merely being blocked by
        the window's shape (`setMask`, which has always been in effect).
        """
        on = bool(enabled)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, on)
        # 穿透开着时如果正好在拖拽，鼠标抓取必须立刻交还，否则宠物会黏在
        # 光标上、跟着一个它已经收不到事件的鼠标跑。
        if on and self.dragging:
            self.dragging = False
            try:
                self.releaseMouse()
            except RuntimeError:
                # 窗口已经在销毁流程里 / already tearing down
                pass

    @property
    def click_through(self) -> bool:
        """当前是否开启穿透 / Whether click-through is on."""
        return bool(self.testAttribute(Qt.WA_TransparentForMouseEvents))

    def paintEvent(self, event):  # noqa: N802
        pix = self._pixmap(self.image_name, self.look_right)
        if pix is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, pix)
        p.end()

    # ------------------------------------------------------------------
    # 交互 / interaction
    # ------------------------------------------------------------------
    def _hit(self, pos) -> bool:
        """透明处不响应点击（遮罩未生效时的兜底）/ Ignore clicks on transparent pixels."""
        pix = self._pixmap(self.image_name, self.look_right)
        if pix is None:
            return True
        x, y = int(pos.x()), int(pos.y())
        if not (0 <= x < pix.width() and 0 <= y < pix.height()):
            return False
        from PySide6.QtGui import QImage
        img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
        return ((img.pixel(x, y) >> 24) & 0xFF) > ALPHA_THRESHOLD

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            if not self._hit(event.position()):
                return
            event.accept()
            self.dragging = True
            cur = event.globalPosition()
            self.drag_offset = Pt(self.anchor.x - cur.x(), self.anchor.y - cur.y())
            self.grabMouse()
            self.manager.begin_drag(self)
        elif event.button() == Qt.RightButton:
            event.accept()
            self.menuRequested.emit(self, event.globalPosition())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.dragging:
            event.accept()
            cur = event.globalPosition()
            self.anchor = Pt(cur.x() + self.drag_offset.x, cur.y() + self.drag_offset.y)
            self.reposition()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self.dragging and event.button() == Qt.LeftButton:
            event.accept()
            self.dragging = False
            self.releaseMouse()
            self.manager.end_drag(self)

    def closeEvent(self, event):  # noqa: N802
        self.manager.unregister(self)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def namespace(self) -> dict:
        """表达式命名空间 / The namespace used to evaluate expressions."""
        return {
            "mascot": MascotRef(self),
            "footX": self.anchor.x,
            "footY": self.anchor.y,
        }
