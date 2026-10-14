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
