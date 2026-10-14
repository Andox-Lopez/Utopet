# -*- coding: utf-8 -*-
"""
宠物管理器 / Mascot manager
==============================================================================
负责：加载角色与配置、驱动每帧循环、多宠物生命周期、系统托盘与右键菜单、
以及设置的即时应用。

Owns: character & configuration loading, the per-tick loop, the lifecycle of all
mascots, the system tray and context menus, and live application of settings.
"""

from __future__ import annotations

import logging
import os
import random
import sys
import time

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QMenu, QMessageBox,
                             QSystemTrayIcon)

from .. import win32
from ..pomodoro import Pomodoro
from ..i18n import get_i18n
from ..icons import app_icon, tray_icon
from ..names import display_name
from ..settings import APP_ROOT, CHARACTERS_DIR, DATA_DIR, Settings
from ..xml.config import (ActionSet, BehaviorSet, find_conf,
                          load_actions, load_behavior)
from .brain import Brain
from .environment import Environment, Pt
from .mascot import CharacterBundle, ImageSet, Mascot
from .runtime import create_action

__all__ = ["Manager", "CharacterBundle", "list_characters"]

# 系统保留行为名 / reserved behaviour names
BEHAVIOR_DRAGGED = "ドラッグされる"
BEHAVIOR_THROWN = "投げられる"
BEHAVIOR_FALL = "落下する"
BEHAVIOR_GATHER = "マウスの周りに集まる"
#: 会话恢复时最多补多少帧 / how many frames session restore will fast-forward.
#: 25 fps 下 20000 帧 ≈ 13 分钟；再长就不是「正在做的事」而是一段背景循环了。
#: At 25 fps that is ~13 minutes; anything longer is not "what it was doing" but
#: a background loop, and re-syncing it is pointless.
_MAX_RESUME_SEEK = 20000
#: 日志 / logger
log = logging.getLogger("shimeji")

#: 运行日志文件 / the run-time log file.
#: **界面上那个「打开日志」按钮和这里必须是同一份路径** —— 之前 README 写的是
#: `data/utopet.log`，实际写的是 `data/shimeji.log`，用户按文档去找只会扑空。
#: 路径收敛到这一个常量，界面直接引用它，就不会再对不上。
#: The "Open log" button and this constant must agree: the README used to claim
#: `data/utopet.log` while the code wrote `data/shimeji.log`, so anyone
#: following the docs found nothing.  One constant, referenced by the UI.
LOG_PATH = os.path.join(DATA_DIR, "shimeji.log")


def setup_logging():
    """把日志写进 data\\shimeji.log / Send logs to data\\shimeji.log."""
    if log.handlers:
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    except OSError:
        pass


def _pomodoro_state_text(pom: Pomodoro) -> str:
    """番茄时钟当前状态的短文本（托盘悬停提示用）/ One-line Pomodoro status."""
    t = get_i18n()
    left = int(pom.remaining)
    clock = "%02d:%02d" % (left // 60, left % 60)
    key = {"work": "pomo.state.work", "break": "pomo.state.break",
           "long_break": "pomo.state.long",
           "paused": "pomo.state.paused"}.get(pom.phase, "pomo.state.idle")
    return "%s %s" % (clock, t.t(key))


def list_characters(settings: Settings | None = None) -> list[tuple[str, str]]:
    """
    列出所有可用角色 / List every available character.

    返回 [(显示名, 目录), ...] / returns [(label, directory), ...]
    """
    roots = [CHARACTERS_DIR]
    if settings:
        roots.extend(settings.get("character_dirs", []) or [])
    out = []
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            img = d if os.path.exists(os.path.join(d, "shime1.png")) \
                else os.path.join(d, "img")
            if os.path.exists(os.path.join(img, "shime1.png")) and d not in seen:
                seen.add(d)
                out.append((name, d))
    return out


class Manager(QObject):
    """引擎主控 / The engine's main controller."""

    def __init__(self, app: QApplication, settings: Settings):
        super().__init__()
        self.app = app
        self.settings = settings
        self.actions: ActionSet = ActionSet()
        self.behaviors: BehaviorSet = BehaviorSet()
        self.constants: dict = {}
        self.images: ImageSet | None = None
        self.character_dir: str = ""
        self.mascots: list[Mascot] = []
        #: 1.0.3：按角色目录缓存的资源集 / bundles cached per character directory
        self._bundles: dict[str, CharacterBundle] = {}
        self._bundle: CharacterBundle | None = None
        self.shared_env = Environment()
        self.brain = Brain(self)
        self.hidden = False
        self._idle_ticks = 0
        self._idle_fired = False
        self._last_cursor = (0, 0)
        self._settings_window = None
        self._panel = None
        self._panel_enabled = bool(settings.get("taskbar_panel", True))
        #: 番茄时钟窗口（非模态，这里持强引用防 GC）/ Pomodoro window.
        self._pomodoro_window = None
        #: 番茄时钟 / the Pomodoro timer. 逻辑在 shimeji.pomodoro，无 Qt。
        self.pomodoro = Pomodoro(
            work_min=int(settings.get("pomodoro_work_min", 25)),
            break_min=int(settings.get("pomodoro_break_min", 5)),
            long_break_min=int(settings.get("pomodoro_long_break_min", 15)),
            long_every=int(settings.get("pomodoro_long_every", 4)),
            on_event=self._on_pomodoro_event,
        )

        setup_logging()
        # 关键：先对齐 DPI，否则高缩放屏上宠物会错位
        # Critical: align DPI first or mascots land on the wrong spot on scaled displays
        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                win32.set_dpi_scale(screen.devicePixelRatio())
                log.info("DPI scale = %s", screen.devicePixelRatio())
        except Exception:
            win32.set_dpi_scale(1.0)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)

        self._apply_env_options()
        self.reload()
        self._setup_tray()
        self._setup_panel()
        self._first_run_guide()
        self.start()

    # ------------------------------------------------------------------
    # 加载 / loading
    # ------------------------------------------------------------------
    def _apply_env_options(self):
        """把设置同步到环境对象 / Push settings into the environment object."""
        self.shared_env.titles_filter = list(self.settings.get("titles", []) or [])
        off = self.settings.get("window_offset", [0, 0, 0, 0]) or [0, 0, 0, 0]
        self.shared_env.window_offset = tuple(int(x) for x in (list(off) + [0, 0, 0, 0])[:4])

    def _character_dir(self) -> str:
        name = self.settings.get("character", "")
        chars = list_characters(self.settings)
        if name:
            for label, d in chars:
                if label == name:
                    return d
        # 回退：名字可能本身就是路径 / fall back: the name may be a path already
        if name and os.path.isdir(name):
            return name
        return chars[0][1] if chars else ""

    def _load_bundle(self, label: str, directory: str) -> CharacterBundle | None:
        """
        加载一个角色的全部资源 / Load every resource of one character.

        单独抽出来是为了让 `reload()` 和多角色召唤走同一条路径 —— 否则
        「召唤第二只不同角色」会拿到一套没合并 custom.xml、也没补maxCount
        常量的半成品配置。
        Factored out so `reload()` and multi-character summoning share one path;
        otherwise summoning a second character would hand out a config without
        custom.xml merged or the maxCount constant filled in.
        """
        if not directory or not os.path.isdir(directory):
            return None
        img_dir = directory
        if not os.path.exists(os.path.join(directory, "shime1.png")):
            img_dir = os.path.join(directory, "img")
        images = ImageSet(img_dir)
        if not images.images:
            return None
        a_xml, b_xml = find_conf(directory)
        actions = load_actions(a_xml) if os.path.exists(a_xml) else ActionSet()
        behaviors = load_behavior(b_xml) if os.path.exists(b_xml) else BehaviorSet()
        constants = dict(behaviors.constants)
        if "maxCount" not in constants:
            constants["maxCount"] = float(self.settings.get("max_count", 50))
        # 缓存：同一角色重复召唤不再重新读 XML / cache: summoning the same
        # character again must not re-parse its XML.
        cached = self._bundles.get(directory)
        if cached is not None and cached.images.names == images.names:
            return cached
        bundle = CharacterBundle(label, directory, images, actions, behaviors,
                                 constants)
        self._bundles[directory] = bundle
        return bundle

    def bundle_for(self, label: str) -> CharacterBundle | None:
        """
        按角色名取资源集 / Get the bundle for a character label.

        没开「多桌宠」时永远返回当前那一只的 bundle，这样单角色路径的行为
        与 1.0.2 完全一致。
        Without multi-pet this always returns the current character's bundle, so
        the single-character path behaves exactly as it did in 1.0.2.
        """
        if not self.multi_pet_enabled:
            return self._bundle
        for lbl, d in list_characters(self.settings):
            if lbl == label:
                b = self._load_bundle(lbl, d)
                if b is not None:
                    return b
        return None

    def reload(self):
        """重新加载角色、动作与行为 / Reload the character, actions and behaviours."""
        self._bundles = {}
        d = self._character_dir()
        self.character_dir = d
        if not d:
            self.images = None
            self._bundle = None
            return
        label = ""
        for lbl, dd in list_characters(self.settings):
            if dd == d:
                label = lbl
                break
        bundle = self._load_bundle(label or os.path.basename(d), d)
        self._bundle = bundle
        if bundle is None:
            self.images = None
            return
        self.images = bundle.images
        self.actions = bundle.actions
        self.behaviors = bundle.behaviors
        self._merge_custom()
        self.constants = dict(self.behaviors.constants)
        if "maxCount" not in self.constants:
            self.constants["maxCount"] = float(self.settings.get("max_count", 50))

    def _merge_custom(self):
        """合并 data/custom.xml 里的自定义动作与行为 / Merge custom.xml on top."""
        path = self.settings.custom_xml
        if not os.path.exists(path):
            return
        try:
            custom_actions = load_actions(path)
        except Exception:
            custom_actions = None
        if custom_actions:
            for name, defn in custom_actions.actions.items():
                self.actions.add(defn)
        try:
            custom_behavior = load_behavior(path)
        except Exception:
            custom_behavior = None
        if custom_behavior:
            self.constants.update(custom_behavior.constants)
            known = {b.name for _, b in self.behaviors.entries}
            for cond, b in custom_behavior.entries:
                if b.name not in known:
                    self.behaviors.entries.append((cond, b))
                    known.add(b.name)

    def behavior_by_name(self, name: str):
        """按名字找行为定义 / Find a behaviour definition by name."""
        if not name:
            return None
        for _, b in self.behaviors.entries:
            if b.name == name:
                return b
        return None

    @property
    def custom_action_names(self) -> set[str]:
        """自定义动作名集合 / Names of the user-defined actions."""
        path = self.settings.custom_xml
        if not os.path.exists(path):
            return set()
        try:
            return set(load_actions(path).actions.keys())
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # 角色模式：单角色增殖 vs 多角色共存（1.0.3）
    # ------------------------------------------------------------------
    @property
    def multi_pet_enabled(self) -> bool:
        """
        多角色共存开关 / Whether several distinct characters may share the screen.

        与「自我增殖」（分裂/ 拔萝卜）**互斥**，见 `effective_self_cloning`。
        Mutually exclusive with self-cloning; see `effective_self_cloning`.
        """
        return bool(self.settings.get("multi_pet_enabled", False))

    @property
    def effective_self_cloning(self) -> bool:
        """
        实际生效的增殖开关 / The self-cloning flag actually in force.

        用户要求「多桌宠」与「增值分裂/拔萝卜」互斥。理由：两者的语义是冲突的
        —— 分裂是「同一个角色多长一只出来」（子代与亲代共享同一套动作表，
        一起被同一个 Brain 权重池驱动），多桌宠是「每只一个不同角色，各用各的
        动作表」。同时开着会产出行为错乱的组合：分裂出来的幼崽用的是**当前
        角色**的动作表，但在多角色模式下它可能属于另一个 bundle，行为名对不上，
        结果就是幼崽什么都不做或做出别的角色的动作。

        规则：**多角色模式优先**，开启时强制关闭增殖（反之亦然，切回单角色
        模式时恢复用户原本的增殖偏好）。
        The two features are semantically conflicting: Split breeds another copy
        of *the same* character (same action table, same weighted pool), while
        multi-pet gives every mascot *its own* character.  Combined, a freshly
        split newborn would look up behaviour names in the wrong bundle and end
        up idle or playing another character's animation.  Multi-pet wins; when
        it is on, cloning is forced off (and the user's own preference is
        restored when they switch back).
        """
        if self.multi_pet_enabled:
            return False
        return bool(self.settings.get("self_cloning_enabled", True))

    def set_multi_pet(self, enabled: bool) -> None:
        """
        切换多角色共存 / Toggle multi-character mode.

        切到多角色时解散全部宠物（不同角色的行为池不能混在一次会话里），
        然后按新配置重新召唤。
        """
        enabled = bool(enabled)
        if enabled == self.multi_pet_enabled:
            return
        if enabled:
            # 记住用户原本的增殖偏好。直接把它写成 False 的话，切回单角色时
            # 读回来的还是 False —— 用户的设置被**永久吞掉**了。
            # Stash the user's real preference: overwriting it in place would
            # make it permanently lost, because reading it back would then
            # return the forced-off value rather than what the user chose.
            self.settings.set("self_cloning_pref",
                              bool(self.settings.get("self_cloning_enabled", True)))
            self.settings.set("self_cloning_enabled", False)
        else:
            pref = self.settings.get("self_cloning_pref", None)
            self.settings.set("self_cloning_enabled",
                              True if pref is None else bool(pref))
        self.settings.set("multi_pet_enabled", enabled)
        # 多角色之间不能互相继承行为与会话位置 / pets of different characters
        # must not inherit each other's session snapshot
        self.dismiss_all()
        self.settings.set("session", [])
        try:
            self.settings.save()
        except OSError:
            log.exception("save settings failed")
        self.reload()
        self.shared_env.refresh(force=True)
        self.summon_many(max(1, int(self.settings.get("initial_count", 1))))
        if self._panel is not None:
            self._panel.refresh_status()

    def summon_character(self, label: str, anchor: Pt | None = None) -> Mascot | None:
        """
        召唤一只**指定角色**的宠物 / Summon one mascot of a specific character.

        只在多角色模式下可用；单角色模式下退化成普通 `summon()`，所以调用方
        不需要分叉。
        Only available in multi-character mode; falls back to `summon()` in the
        single-character mode so callers need not branch.
        """
        if not self.multi_pet_enabled:
            return self.summon(anchor)
        bundle = self.bundle_for(label)
        if bundle is None:
            return None
        return self._summon_with(bundle, anchor)

    def _summon_with(self, bundle: CharacterBundle,
                     anchor: Pt | None = None,
                     look_right: bool | None = None) -> Mascot | None:
        """用指定资源集召唤 / Summon with a specific bundle."""
        if bundle is None or not bundle.images.images:
            return None
        if len(self.mascots) >= int(self.settings.get("max_count", 50)):
            return None
        m = Mascot(self, bundle.images, self.shared_env,
                   scale=float(self.settings.get("scale", 1.0)),
                   always_on_top=bool(self.settings.get("always_on_top", True)),
                   opacity=float(self.settings.get("opacity", 1.0)),
                   bundle=bundle)
        if anchor is None:
            wa = self.shared_env.work_area
            anchor = Pt(random.randint(wa.left + 80, max(wa.left + 81, wa.right - 80)),
                        wa.bottom)
        m.anchor = Pt(anchor.x, anchor.y)
        m.look_right = look_right if look_right is not None else random.random() < 0.5
        m.previous_behavior = None
        m.action = None
        m.resume_behavior = None
        m.resume_seek = 0
        m.resume_index = 0
        m.menuRequested.connect(self.show_context_menu)
        self.mascots.append(m)
        if not self.hidden:
            m.show()
        return m

    # ------------------------------------------------------------------
    # 生命周期 / lifecycle
    # ------------------------------------------------------------------
    def start(self):
        self._apply_env_options()
        ms = int(self.settings.get("tick_ms", 40))
        self.timer.start(max(10, ms))
        if self.mascots:
            return
        # 优先恢复上次会话 / prefer restoring the previous session
        if self.settings.get("restore_session", True):
            snapshot = self.settings.get("session", []) or []
            restored = 0
            for item in snapshot:
                try:
                    x = float(item.get("x", 0))
                    y = float(item.get("y", 0))
                    lr = bool(item.get("look_right", False))
                except (TypeError, ValueError):
                    continue
                # 多角色模式要按快照里记的角色恢复，否则所有宠物都会变成默认角色
                # In multi-character mode restore each mascot's own character,
                # otherwise they would all come back as the default one.
                lb = item.get("character") if isinstance(item, dict) else None
                behavior = item.get("behavior") if isinstance(item, dict) else None
                m = self.summon(Pt(x, y), look_right=lr, label=lb,
                                behavior=behavior)
                if m is not None:
                    restored += 1
                    # 续播：把上次跑到的帧数交给第一个动作补上
                    # resume: hand the saved frame count to the first action
                    if behavior:
                        try:
                            elapsed = int(item.get("elapsed", 0) or 0)
                        except (TypeError, ValueError):
                            elapsed = 0
                        if elapsed:
                            m.resume_behavior = behavior
                            m.resume_seek = max(0, min(elapsed, _MAX_RESUME_SEEK))
                            try:
                                m.resume_index = max(0, int(item.get("seq", 0) or 0))
                            except (TypeError, ValueError):
                                m.resume_index = 0
            if restored:
                return
        # 多只时用均匀铺开的落点，避免叠在一起 / spread the landing points
        self.summon_many(max(1, int(self.settings.get("initial_count", 1))))
        # 面板在 start() 之前就建好了，这里补一次刷新，避免首屏显示 0 只
        # The panel is created before start(); refresh so it never shows "0".
        if self._panel is not None:
            self._panel.refresh_status()

    def save_session(self):
        """
        记录当前宠物位置与**正在做的事** / Snapshot where each mascot is and what it is doing.

        1.0.6 起连正在播放的行为和已经跑到的帧数一起记下来，重启后接着做同一件事。
        此前只存锚点与朝向，重启后宠物会从「随机挑一个行为」开始 —— 用户看到的
        是「刚开程序它就在乱走」，而不是「它还在刚才那件事上」。

        Since 1.0.6 the playing behaviour and its frame count are saved too, so a
        restart continues the same activity.  Previously only the anchor and
        facing were stored: on start-up the pet began with a random behaviour, so
        a restart looked like "it is already wandering off" rather than "still
        doing what it was doing".

        超出 `_MAX_RESUME_SEEK` 的帧数会被截断 —— 补帧是逐帧跑的，一个跑了很久
        的循环动作没必要（也不该）在启动时补上万帧。
        Frame counts beyond `_MAX_RESUME_SEEK` are clamped: the fast-forward runs
        frame by frame, and a long looping action should not cost tens of
        thousands of iterations at start-up.
        """
        snapshot = []
        for m in self.mascots:
            item = {"x": round(m.anchor.x, 1), "y": round(m.anchor.y, 1),
                    "look_right": bool(m.look_right),
                    # 多角色模式记下角色名，下次启动才能恢复成不同的角色
                    # record the character so a restart brings back the mix
                    "character": (m.bundle.label if m.bundle
                                  else self.settings.get("character"))}
            name = getattr(getattr(m.action, "defn", None), "name", None)
            if name:
                # **必须问组合动作自己跑到哪儿了，不能读 m.action.time**：
                # 组合动作（Sequence/Select）从不累加 time，只有真正播动画的
                # 叶子动作会 —— 原版 Behavior.xml 里几乎全是组合动作，直接读
                # time 永远是 0，续播就成了一个静默失效的功能。
                # Must ask the composite for its progress: a composite never
                # accumulates `time`, only the playing leaf does.
                try:
                    seq, elapsed = m.action.progress()
                except Exception:  # noqa: BLE001 - 存档不该因读进度失败而丢掉
                    log.exception("read action progress failed")
                    seq, elapsed = 0, 0
                item["behavior"] = name
                item["seq"] = max(0, int(seq))
                item["elapsed"] = max(0, min(elapsed, _MAX_RESUME_SEEK))
            snapshot.append(item)
        self.settings.set("session", snapshot)
        try:
            self.settings.save()
        except OSError:
            log.exception("save session failed")

    def stop(self):
        self.timer.stop()

    def summon(self, anchor: Pt | None = None, behavior: str | None = None,
               look_right: bool | None = None, label: str | None = None) -> Mascot | None:
        """
        召唤一只宠物 / Summon one mascot.

        `label` 指定角色（仅多角色模式有效）；不给就用当前默认角色的 bundle。
        `label` picks the character (multi-character mode only); without it the
        current default character's bundle is used.
        """
        bundle = self._bundle
        if self.multi_pet_enabled and label:
            bundle = self.bundle_for(label) or bundle
        if bundle is None or not bundle.images.images:
            return None
        m = self._summon_with(bundle, anchor, look_right)
        if m is not None:
            m.forced_behavior = behavior
        return m

    create_mascot = summon

    def summon_many(self, count: int, behavior: str | None = None) -> int:
        """
        一次召唤多只 / Summon several mascots at once.

        开启「均匀铺开」时，落点按 n 等分横向铺在工作区里（带随机抖动），
        比纯随机更不容易叠在一起；到达数量上限时提前收尾，返回实际召唤数。

        With "spread" enabled the landing points are evenly divided across the
        work area (with jitter) so they do not pile up as often as pure random
        placement would.  Stops at the count limit and returns how many were
        actually summoned.
        """
        added = 0
        try:
            count = int(count)
        except (TypeError, ValueError):
            return 0
        if count <= 0 or self.images is None or not self.images.images:
            return 0
        wa = self.shared_env.work_area
        left, right = wa.left, wa.right
        span = max(1, right - left - 160)
        spread = bool(self.settings.get("spawn_spread", True))
        for i in range(count):
            if spread:
                # 在自己那格的中间 70% 里抖动，既整齐又不会相邻叠住
                # jitter inside the middle 70% of its own slot: ordered but not stacked
                frac = (i + 0.15 + 0.7 * random.random()) / float(count)
                x = left + 80 + span * frac
            else:
                x = random.randint(left + 80, max(left + 81, right - 80))
            if self.summon(Pt(x, wa.bottom), behavior=behavior) is None:
                break
            added += 1
        return added

    def dismiss_to(self, count: int) -> int:
        """只留下 n 只，其余解散 / Keep only `count` mascots, dismiss the rest."""
        removed = 0
        while len(self.mascots) > max(0, int(count)):
            self.dismiss(self.mascots[-1])
            removed += 1
        return removed

    def dismiss(self, mascot: Mascot | None = None):
        """解散一只 / Dismiss one mascot."""
        if mascot is None:
            if not self.mascots:
                return
            mascot = self.mascots[-1]
        if mascot in self.mascots:
            self.mascots.remove(mascot)
        mascot.close()
        # 最后一只也没了就把面板叫回来：桌面上不能什么都不剩。
        # Bring the panel back when the last one is gone: never leave the
        # desktop completely empty with no way back.
        self._rescue_if_stranded()

    def dismiss_all(self):
        for m in list(self.mascots):
            self.dismiss(m)
        self._rescue_if_stranded()

    def unregister(self, mascot: Mascot):
        if mascot in self.mascots:
            self.mascots.remove(mascot)

    def count(self) -> int:
        return len(self.mascots)

    def set_hidden(self, hidden: bool):
        self.hidden = hidden
        for m in self.mascots:
            m.setVisible(not hidden)

    def restart(self):
        """按当前设置重建所有宠物 / Rebuild every mascot from the current settings."""
        self.dismiss_all()
        self.reload()
        self._apply_env_options()
        self.shared_env.refresh(force=True)
        self.timer.setInterval(max(10, int(self.settings.get("tick_ms", 40))))
        self.summon()

    # ------------------------------------------------------------------
    # 每帧 / per tick
    # ------------------------------------------------------------------
    def tick(self):
        self.shared_env.refresh()
        self._check_idle()
        for m in list(self.mascots):
            try:
                self._tick_mascot(m)
            except Exception:  # 单只宠物出错不影响其它 / one pet must not kill the rest
                log.exception("mascot tick error")
                m.action = None

    def _tick_mascot(self, m: Mascot):
        """
        推进一只宠物 / Advance one mascot by a tick.

        顺序很重要，和原版 `UserBehavior.next()` 一致：

        1. 当前动作结束（或不存在）→ 从队列 / 行为池里挑一个行为
        2. 推进动作
        3. 动作报告 LostGround（宠物离开了它依附的边界）→ **立刻**切成「落下する」
        4. 动作结束 → 清空，等下一帧重新挑

        第 3 步是原版的 `LostGroundException` 处理，也是「不会卡在窗口边缘蹭」
        「窗口一关就掉下去」的实现方式。
        """
        # 1.0.3：养成数值每帧走一步（内部自己按 15 秒结算一次）
        m.status.tick_slow()
        if m.action is None:
            name = self.brain.choose(m)
            if not name:
                return
            # 会话恢复：**只对同一个行为**续播。存档里的行为在当前角色的表里
            # 不存在时，行为选择会退回到正常随机，这时给别的动作补帧就是白跳。
            # Session restore resumes only the *same* behaviour.  If the saved one
            # is missing from this character's table the normal random pick takes
            # over, and fast-forwarding some other action would skip frames for
            # no reason.
            hit = name == m.resume_behavior
            seek = m.resume_seek if hit else 0
            index = m.resume_index if hit else 0
            m.resume_behavior = None
            m.resume_seek = 0
            m.resume_index = 0
            m.action = create_action(m, name, {}, None, seek, index)
            if m.action is None:
                return
        if not m.action.tick():
            # LostGround 优先于一切：宠物已经不在边界上了，必须先掉下去。
            # LostGround outranks everything: the mascot is off its border and
            # must fall before anything else can happen.
            if getattr(m.action, "lost_ground", False):
                m.action = None
                self._force_behavior(m, BEHAVIOR_FALL, interrupt=True)
                return
            m.action = None
        self._rescue_if_offscreen(m)

    def _rescue_if_offscreen(self, m: Mascot):
        """
        宠物被甩到屏幕外就捞回来 / Fish the mascot back in if it left the screen.

        对应原版 `UserBehavior.next()` 里的 "Out of the screen bounds" 分支：
        在动作**还在跑**的时候检查（我们放在 tick 之后），一旦整个窗口都跑到
        屏幕外，就把锚点随机丢到屏幕上方并切到「落下する」，让它自己掉回来。

        Mirrors the original's "Out of the screen bounds" branch in
        `UserBehavior.next()`: the check runs while the action is still going, and
        an off-screen mascot is dropped back above the screen and made to fall.

        没有这一步，宠物被强力抛出后会永久消失在屏幕外 —— 用户以为它丢了。
        Without this a hard throw makes the mascot vanish for good.
        """
        screen = self.shared_env.screen
        img = m.images.get(m.image_name) if m.images else None
        if img is not None:
            iw = img.width() * m.scale
            ih = img.height() * m.scale
        else:
            iw, ih = 128.0, 256.0
        x0 = m.anchor.x - m.base.x * m.scale
        y0 = m.anchor.y - m.base.y * m.scale
        if not (x0 + iw <= screen.left or screen.right <= x0
                or screen.bottom <= y0):
            return
        log.info("offscreen mascot %s -> dropping back in", m)
        m.anchor = Pt(random.uniform(screen.left, screen.right),
                      screen.top - 256)
        self._force_behavior(m, BEHAVIOR_FALL, interrupt=True)

    def _check_idle(self):
        """鼠标静止一段时间后让宠物聚过来 / Gather mascots around an idle cursor."""
        if not self.settings.get("idle_gather", True):
            return
        cur = (self.shared_env.cursor.x, self.shared_env.cursor.y)
        if cur != self._last_cursor:
            self._last_cursor = cur
            self._idle_ticks = 0
            self._idle_fired = False
            return
        self._idle_ticks += 1
        need = int(self.settings.get("idle_gather_sec", 25)) * 1000 // max(10, int(
            self.settings.get("tick_ms", 40)))
        if not self._idle_fired and self._idle_ticks >= need:
            self._idle_fired = True
            self.force_behavior_all(BEHAVIOR_GATHER)

    # ------------------------------------------------------------------
    # 行为队列 / behaviour queue
    # ------------------------------------------------------------------
    def _force_behavior(self, mascot: Mascot, name: str, interrupt: bool = False):
        """
        把一个行为排到队列里（或立刻执行）/ Queue a behaviour, or interrupt with it.

        `interrupt=False`（默认）：排队，等当前动作自然跑完 —— 这才是原版的
        行为替换时机，也是「动作连贯」的关键。

        `interrupt=True`：立刻掐断当前动作。**只给用户主动拖拽用** ——
        按下鼠标的瞬间用户已经抓住了宠物，晚一帧都显得卡。
        """
        if not name or name not in self.actions:
            return
        if interrupt:
            mascot.pending_behaviors.clear()
            mascot.pending_behaviors.append(name)
            mascot.action = None
            return
        # 已经在队列里就不重复排，避免连点「聚到鼠标旁」排出一长串
        if name in mascot.pending_behaviors:
            return
        mascot.pending_behaviors.append(name)

    def force_behavior_all(self, name: str, interrupt: bool = False):
        """对所有宠物排队一个行为 / Queue a behaviour for every mascot."""
        for m in self.mascots:
            self._force_behavior(m, name, interrupt)

    # ------------------------------------------------------------------
    # 拖拽 / dragging
    # ------------------------------------------------------------------
    def begin_drag(self, mascot: Mascot):
        """鼠标按下：立刻接管为拖拽行为 / Mouse down: take over as the drag behaviour."""
        mascot.status.interact("drag")
        self._force_behavior(mascot, BEHAVIOR_DRAGGED, interrupt=True)

    def end_drag(self, mascot: Mascot):
        """
        鼠标松开：切成「投げられる」/ Mouse up: switch to the thrown behaviour.

        这里用 interrupt：松手之后用户期待宠物**立刻**被甩出去。
        如果排队等当前动作跑完，宠物会先把手上的动画做完再飞出去 ——
        延迟可达数秒，正是用户说的「抛出动作不生效」。

        Interrupt here: on release the user expects the pet to fly *now*.  Queuing
        would let the current animation finish first — up to several seconds of
        delay, which is the reported "the throw does not work".
        """
        mascot.status.interact("throw")
        self._force_behavior(mascot, BEHAVIOR_THROWN, interrupt=True)

    # ------------------------------------------------------------------
    # 托盘与菜单 / tray and menus
    # ------------------------------------------------------------------
    def _setup_tray(self):
        # 托盘用 tray_icon()（logo.ico，方角多尺寸）—— 托盘只有 16×16，
        # 主图缩下来会糊，圆角还会白吃掉像素。窗口/任务栏那边用 app_icon()。
        # The tray gets the squared-off multi-size ICO; windows get the master.
        # If no tray exists Qt degrades gracefully.
        self.tray = QSystemTrayIcon(tray_icon(), self)
        self.tray.setToolTip(get_i18n().t("tray.tooltip"))
        self.tray.activated.connect(self._on_tray_activated)
        self._rebuild_tray_menu()
        self.tray.show()
        # 注意：右键菜单的信号连接**不在这里**。本函数早于 start() 执行，
        # 此刻 self.mascots 还是空的。现在统一在 summon() 里逐只连接。
        # NOT here: this runs before start(), so self.mascots is still empty.
        # summon() wires each mascot as it is created.

    #: 托盘 / 右键菜单里的「一次召唤 N 只」预设 / batch-summon presets
    SUMMON_PRESETS = (2, 3, 5, 10)

    def _build_summon_submenu(self, menu: QMenu):
        """「一次召唤 N 只」子菜单 / Batch-summon sub-menu."""
        t = get_i18n()
        sub = QMenu(t.t("menu.summon_many"), menu)
        for n in self.SUMMON_PRESETS:
            sub.addAction(t.t("menu.summon_n").replace("{0}", str(n)),
                          lambda checked=False, n=n: self.summon_many(n))
        batch = int(self.settings.get("summon_count", 5) or 5)
        if batch not in self.SUMMON_PRESETS and batch > 0:
            sub.addAction(t.t("menu.summon_n").replace("{0}", str(batch)),
                          lambda checked=False, b=batch: self.summon_many(b))
        return sub

    def _build_behavior_submenu(self, menu: QMenu, mascot: "Mascot | None"):
        """
        「指定动作」子菜单 / The "Do behavior" sub-menu.

        对齐原版 `Mascot.java` 的 `Behaviors:` 子菜单：列出全部行为名，
        点一个就切换过去。

        Mirrors the original's `Behaviors:` sub-menu in `Mascot.java`.

        三个细节：

        * **只列合法的**：行为名必须在 actions 里存在，否则点了没反应。
          Only behaviours whose action actually exists — otherwise the menu item
          would silently do nothing.
        * **在队列里插到最前**：用户明确点了某个动作就是要「现在做」，
          所以插队并打断当前动作，而不是等当前动作跑完。
          The user explicitly asked for this behaviour, so it jumps the queue and
          interrupts; waiting for the current action to finish would feel ignored.
        * **作用于一只还是全部**：从宠物身上右键 = 只对它，从托盘 = 全部。
          Right-clicking a mascot targets that one; the tray targets all of them.
        * **菜单显示本地化，动作名保持日文**：配置里的名字是原版日文（兼容
          原版角色包），直接摆到菜单上对中文用户就是一片假名。`names.py` 里有
          91 条三语对照，覆盖全部 57 个可选行为，所以这里按用户的语言显示
          「中文 English」；点下去传的仍是**日文原名**，队列和 `Actions.xml`
          查找都不受影响。未收录的名字原样显示（退回日文），不丢人。
          The configured names are Japanese (required for original character
          packs), which reads as gibberish to a Chinese user.  `names.py` maps
          all 57 selectable behaviours, so labels are localized while the value
          stays Japanese — lookups and the queue are unaffected.
        """
        t = get_i18n()
        sub = QMenu(t.t("menu.behaviors"), menu)
        sub.setToolTip(t.t("menu.behaviors_hint"))
        sub.setToolTipsVisible(True)

        names = [b.name for _, b in self.behaviors.entries
                 if b.name and b.name in self.actions]
        # 去重但保持配置里的顺序 / de-duplicate, keeping config order
        seen: set[str] = set()
        ordered = [n for n in names if not (n in seen or seen.add(n))]
        if not ordered:
            action = sub.addAction(t.t("menu.behaviors_hint"))
            action.setEnabled(False)
            return sub

        lang = str(self.settings.get("language", "zh_CN"))
        bilingual = bool(self.settings.get("bilingual", True))
        for name in ordered:
            label = display_name(name, lang, bilingual)
            # 原文放在提示里：日文原名是搜索/对照的唯一线索
            # The original name stays in the tooltip: it is the only clue a user
            # has when searching the docs or matching a character pack.
            act = sub.addAction(label,
                                lambda checked=False, n=name: self._do_behavior(n, mascot))
            if label != name:
                act.setToolTip(name)
        return sub

    def _do_behavior(self, name: str, mascot: "Mascot | None"):
        """执行指定动作 / Switch to the requested behaviour."""
        if mascot is not None:
            self._force_behavior(mascot, name, interrupt=True)
        else:
            self.force_behavior_all(name, interrupt=True)

    def _build_character_submenu(self, menu: QMenu) -> QMenu | None:
        """
        「召唤其他角色」子菜单 / The "summon another character" sub-menu.

        只在多角色模式下出现，且**排除已经在屏幕上的角色** —— 同一个角色可以
        再召唤多只（那属于「多只」而不是「多角色」），但这里只列还没出现的角色，
        免得用户点了发现「怎么又来一只一样的」。

        Only shown in multi-character mode, and characters already on screen are
        left out: the same character may still be summoned again (that is "more
        pets", not "more characters"), but listing it here would read as "why did
        clicking give me a duplicate?".
        """
        if not self.multi_pet_enabled:
            return None
        present = {m.bundle.label for m in self.mascots if m.bundle is not None}
        labels = [lb for lb, _ in list_characters(self.settings) if lb not in present]
        if not labels:
            return None
        t = get_i18n()
        sub = QMenu(t.t("menu.summon_character"), menu)
        for lb in labels:
            sub.addAction(lb, lambda checked=False, n=lb: self.summon_character(n))
        return sub

    def _build_main_menu(self, mascot: "Mascot | None" = None) -> QMenu:
        """
        构建主菜单 —— 托盘右键和宠物右键**共用同一份**。

        之前这两份菜单是各写一遍的，结果文案和顺序慢慢走岔：托盘那份少了
        「聚到鼠标旁」，顺序也不一样，用户点同一个功能在不同地方看到不同的排列。
        现在只有一个来源，`mascot` 只影响「解散这只」作用于谁。

        Build the one and only menu, shared by the tray and the mascot.

        These used to be two hand-written menus that slowly drifted apart (the
        tray one lacked "Gather", the order differed), so the same action looked
        different depending on where you right-clicked.  Now there is a single
        source; `mascot` only decides *which* pet "Dismiss this one" targets.
        """
        t = get_i18n()
        menu = QMenu()
        menu.addAction(t.t("menu.summon"), lambda: self.summon())
        menu.addMenu(self._build_summon_submenu(menu))
        csub = self._build_character_submenu(menu)
        if csub is not None:
            menu.addMenu(csub)
        menu.addAction(t.t("menu.gather"), self.gather_all)
        menu.addMenu(self._build_behavior_submenu(menu, mascot))
        menu.addSeparator()
        menu.addAction(t.t("menu.dismiss") if mascot is not None
                       else t.t("tray.dismiss_one"),
                       (lambda: self.dismiss(mascot)) if mascot is not None
                       else (lambda: self.dismiss(None)))
        menu.addAction(t.t("tray.dismiss_all"), self.dismiss_all)
        menu.addSeparator()
        menu.addAction(t.t("tray.show_hide"), self.toggle_hidden)
        # 番茄时钟与「显示/隐藏」放一组：都是「把一个常驻窗口叫出来」。
        # The Pomodoro sits next to show/hide: both are "bring a resident
        # window up".
        menu.addAction(t.t("menu.pomodoro"), lambda: self.open_pomodoro())
        menu.addAction(t.t("menu.settings"), self.open_settings)
        menu.addAction(t.t("tray.panel"), self.open_taskbar_panel)
        menu.addSeparator()
        menu.addAction(t.t("menu.quit"), self.quit)
        return menu

    def _rebuild_tray_menu(self):
        """把主菜单挂到托盘上 / Attach the shared menu to the tray."""
        menu = self._build_main_menu()
        self.tray.setContextMenu(menu)
        self._tray_menu = menu

    def _on_tray_activated(self, reason):
        # 双击托盘图标 = 打开任务栏面板。
        #
        # 为什么从「隐藏/显示宠物」改成这个：宠物被隐藏起来时，托盘双击的
        # 反馈是「什么都没发生」—— 用户在桌面上看不到任何变化，会以为程序
        # 卡死了，进而连续双击。面板不一样：它有明确的窗口出现在屏幕右下角，
        # 可见、可点、还带召唤/设置/退出，是用户真正能「摸到」的入口。
        #
        # Double-clicking the tray opens the taskbar panel, not a pet
        # visibility toggle.  Toggling visibility gives *no* visible feedback
        # when the pets are already hidden — the user sees nothing happen,
        # assumes the app is stuck, and keeps clicking.  The panel is a real
        # window in the corner: visible, clickable, and it carries
        # summon / settings / quit.
        if reason == QSystemTrayIcon.Trigger:
            self.open_taskbar_panel(True)

    def toggle_hidden(self):
        """切换宠物显示 / Toggle mascot visibility."""
        self.set_hidden(not self.hidden)

    # ------------------------------------------------------------------
    # 任务栏面板 / taskbar panel
    # ------------------------------------------------------------------
    def _setup_panel(self):
        """按设置决定是否显示任务栏面板 / Show the taskbar panel if configured."""
        if not self.settings.get("taskbar_panel", True):
            return
        self.open_taskbar_panel(show=False)
        if self._panel is not None:
            self._panel.show_near_taskbar()

    def open_taskbar_panel(self, show: bool = True):
        """打开（或唤醒）任务栏面板 / Open (or raise) the taskbar panel."""
        from ..gui.taskbar_panel import TaskbarPanel
        if self._panel is None:
            self._panel = TaskbarPanel(self)
        if show:
            if not self._panel.isVisible():
                self._panel.show_near_taskbar()
            else:
                self._panel.raise_()
                self._panel.activateWindow()
        return self._panel

    # ------------------------------------------------------------------
    # 首次启动引导 / first-run guidance
    # ------------------------------------------------------------------
    def _first_run_guide(self):
        """首次启动时讲清楚「怎么回来」，只讲一次。

        为什么需要这个：托盘图标是唯一常驻的入口，但它默认被藏进系统托盘的
        溢出区（^ 箭头里）。用户关掉面板、解散掉最后一只宠物之后，桌面上
        什么都不剩，托盘也看不见 —— 于是他以为程序没了，重装一遍，旧的那份
        还在后台跑并继续写settings.json。这是个真实的死循环：重装并不能
        解决「找不到程序」，反而制造「配置被重置」的错觉。

        所以这里直接把退路摆在明面上，而不是指望用户自己发现托盘。
        Explain the way back on first run: the tray icon is the only permanent
        entry point, but Windows hides it behind the overflow caret by default.
        Dismiss the last pet, close the panel, and the desktop is empty with no
        visible way back — users then reinstall, while the old copy keeps
        running and rewriting settings.json.  Spelling out the exit routes up
        front is cheaper than diagnosing that later.
        """
        if self.settings.get("first_run_guide_done", False):
            return
        # 先落盘再看：即使引导窗口之后出问题，也别每次启动都弹。
        # Mark it done before showing: a crash later must not make it repeat.
        self.settings.set("first_run_guide_done", True)
        try:
            self.settings.save()
        except OSError:
            log.exception("save first_run_guide_done failed")
        # 等事件循环跑起来再弹，否则窗口还没就位。
        # Defer to the event loop, otherwise the dialog has no window to parent.
        QTimer.singleShot(600, self._show_first_run_guide)

    def _show_first_run_guide(self):
        """首次启动引导：讲清「怎么回到程序里」。

        两个按钮的语义（1.0.5 起改过）：
        - 「我知道了」**只关掉这个对话框**，程序照常留在托盘。
          之前这里是「我知道了，直接退出」，于是用户为了关掉一条提示
          把桌宠也关掉了 —— 「关提示」和「退出应用」挤在一个按钮里，
          必然有人误点，而这恰好会加剧提示本身要解决的问题。
        - 「打开任务栏设置」直接跳到系统的任务栏设置页。
          托盘图标被收进「^」溢出区是「找不到桌宠」的头号原因，
          让用户自己去翻「其它系统托盘图标」不现实。

        ⚠️ 用 show() + 手动清理，而不是 exec()。
        模态 exec() 会阻塞事件循环直到用户点按钮 —— 一旦这个窗口因为任何
        原因没能显示出来（无显示器的服务会话、explorer.exe 正忙、焦点被
        别的模态窗口锁住），整个程序就永久卡死，连托盘都没有。

        The first-run guidance.

        Both buttons changed meaning in 1.0.5: "Got it" only dismisses the
        dialog, and "Open taskbar settings" jumps to the Windows taskbar
        page where the tray icon actually gets hidden.

        Non-modal on purpose: exec() blocks the event loop, so a window that
        fails to appear deadlocks the whole app with no tray to escape from.
        """
        t = get_i18n().t
        box = QMessageBox(self._panel if self._panel is not None else None)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(t("guide.title"))
        box.setText(t("guide.text"))
        # 「打开任务栏设置」跳系统设置；「我知道了」只关对话框。
        # One button jumps to the Windows taskbar page, the other just closes.
        settings_btn = box.addButton(t("guide.open_taskbar_settings"),
                                    QMessageBox.AcceptRole)
        dismiss_btn = box.addButton(t("guide.dismiss"), QMessageBox.RejectRole)
        box.setDefaultButton(dismiss_btn)
        box.setWindowModality(Qt.NonModal)
        box.open()          # 非模态：不阻塞事件循环
        # open() 之后要自己接线：closeEvent 时按按钮决定去向。
        def _on_close(ev):
            try:
                clicked = box.clickedButton()
            except RuntimeError:
                clicked = None
            if clicked is settings_btn:
                from .. import win32 as _w32
                if _w32.open_taskbar_settings():
                    box.deleteLater()
                    return
                # 老系统没有 ms-settings:：退回到把面板叫回来，
                # 那本来就是一个可用入口，总比「点了没反应」强。
                self.open_taskbar_panel(True)
            box.deleteLater()
            ev.accept()

        box.closeEvent = _on_close

    def _rescue_if_stranded(self):
        """桌面上已经没有任何入口时，把面板拉回来。

        这是死循环的最后一道保险：托盘可能被用户拖出、可能被explorer.exe
        重启吞掉、用户也可能关了托盘可见项。只要「0 只宠物 + 面板不可见」
        同时成立，程序就处于无法被用户触及的状态 —— 此时无条件把面板叫回来。

        Last line of defence against the stranded loop: the tray can be hidden,
        dropped into the overflow area, or lost when explorer.exe restarts.
        Whenever there is no pet *and* no visible panel, the app cannot be
        reached at all — bring the panel back unconditionally.
        """
        if self.mascots:
            return
        if not self.panel_is_gone():
            return
        self.open_taskbar_panel(True)

    def panel_is_gone(self) -> bool:
        """面板是否被隐藏了 / Is the taskbar panel hidden?"""
        p = self._panel
        return p is None or not p.isVisible()

    def set_taskbar_panel(self, enabled: bool):
        """开关任务栏面板 / Toggle the taskbar panel."""
        self.settings.set("taskbar_panel", bool(enabled))
        if enabled:
            self.open_taskbar_panel(True)
        elif self._panel is not None:
            self._panel.hide()

    def refresh_ui_texts(self):
        """语言切换后刷新菜单文案 / Rebuild menus after a language switch."""
        self._rebuild_tray_menu()
        self.tray.setToolTip(get_i18n().t("tray.tooltip"))
        if self._panel is not None:
            self._panel.refresh_ui_texts()

    def show_context_menu(self, mascot: Mascot, global_pos):
        """宠物本体右键 —— 和托盘右键同一份菜单。/ Mascot right-click: the shared menu."""
        menu = self._build_main_menu(mascot)
        menu.exec(global_pos.toPoint() if hasattr(global_pos, "toPoint") else global_pos)

    def gather_all(self):
        """
        让所有宠物聚到鼠标旁 / Gather every mascot to the cursor.

        公开方法（不叫 `_gather_all`）：任务栏面板上也有一个「聚到鼠标旁」按钮
        要用它，私有名号会名不副实。

        排队而不是替换：正在爬墙的宠物会先把这一段爬完再走过来，而不是被
        瞬间拽到鼠标旁边 —— 后者正是用户说的「动作不连贯、优先级像是替换」。
        Public (no leading underscore): the taskbar panel has a "Gather" button
        that calls it, so a private name would be a lie.

        Queued rather than replaced: a mascot climbing a wall finishes that
        climb first instead of being yanked to the cursor mid-animation.
        """
        self.force_behavior_all(BEHAVIOR_GATHER)

    # ------------------------------------------------------------------
    def open_settings(self):
        """打开（或唤醒）设置窗口 / Open (or raise) the settings window."""
        from ..gui.settings_window import SettingsWindow
        if self._settings_window is None or not self._settings_window.isVisible():
            self._settings_window = SettingsWindow(self)
        self._settings_window.setWindowIcon(app_icon())
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def quit(self):
        self.save_session()
        self.stop()
        self.dismiss_all()
        if self._panel is not None:
            self._panel.timer.stop()
            self._panel.hide()
        self.tray.hide()
        self.app.quit()

    # ------------------------------------------------------------------
    def apply_settings(self, need_restart: bool = False):
        """设置变更后应用 / Apply changed settings."""
        get_i18n().set_language(self.settings.get("language", "zh_CN"))
        self._apply_env_options()
        self.timer.setInterval(max(10, int(self.settings.get("tick_ms", 40))))
        if need_restart:
            self.restart()
        else:
            for m in self.mascots:
                m.setWindowOpacity(float(self.settings.get("opacity", 1.0)))
        # 任务栏面板只在开关真正翻转时才动，避免每次「应用」都弹出来
        # Only touch the taskbar panel when the toggle actually flipped, so it
        # does not pop up on every "Apply".
        want = bool(self.settings.get("taskbar_panel", True))
        if want != self._panel_enabled:
            self.set_taskbar_panel(want)
        self._panel_enabled = want
        if self._panel is not None:
            self._panel.setWindowIcon(app_icon())
        # 番茄时钟时长改了 → 下一段生效（不打断正在跑的这一段）
        # Duration changes apply from the next Pomodoro phase.
        try:
            self.pomodoro.set_durations(
                work_min=int(self.settings.get("pomodoro_work_min", 25)),
                break_min=int(self.settings.get("pomodoro_break_min", 5)),
                long_break_min=int(self.settings.get("pomodoro_long_break_min", 15)),
                long_every=int(self.settings.get("pomodoro_long_every", 4)),
            )
        except Exception:  # noqa: BLE001 - 配置坏了不该拖垮整个「应用」
            log.exception("applying pomodoro durations failed")
        self.refresh_ui_texts()

    # ------------------------------------------------------------------
    # 番茄时钟 / Pomodoro timer
    # ------------------------------------------------------------------
    def open_pomodoro(self, center: bool = False):
        """
        打开（或唤醒）番茄时钟窗口 / Open (or raise) the Pomodoro window.

        `center=True` 时把窗口放到**鼠标所在屏幕**的中央 —— 参照
        kwin-move-window-to-center：计时器必须出现在用户正在看的那块屏上，
        落在另一块显示器上的计时器等于没有。
        With `center=True` the window lands in the middle of the screen the
        cursor is on, after kwin-move-window-to-center: a timer on some other
        monitor is no timer at all.
        """
        from ..gui.pomodoro_window import PomodoroWindow
        if self._pomodoro_window is None:
            self._pomodoro_window = PomodoroWindow(self)
        w = self._pomodoro_window
        if center:
            w.center_on_cursor()
        if not w.isVisible():
            w.show()
        w.raise_()
        w.activateWindow()
        return w

    def _on_pomodoro_event(self, event: str, pom: Pomodoro):
        """阶段切换 → 托盘气泡 + 宠物反应 / A phase transition happened."""
        t = get_i18n()
        key = {"work_done": "pomo.msg.work_done",
               "break_done": "pomo.msg.break_done",
               "long_break_done": "pomo.msg.break_done"}.get(event)
        if key:
            body = t.t(key)
            try:
                self.tray.showMessage(t.t("pomo.title"), body,
                                      QSystemTrayIcon.Information, 6000)
            except Exception:  # noqa: BLE001 - 气泡失败不该影响计时
                log.exception("tray balloon failed")
            # 宠物联动：休息开始了，让宠物做个动作提醒你。
            # Pet reaction: the break started, let the mascot react.
            if event == "work_done" and bool(
                    self.settings.get("pomodoro_pet_react", True)):
                self._pomodoro_pet_react()
        # 托盘悬停提示跟着变 / keep the tray tooltip in sync
        try:
            self.tray.setToolTip("%s — %s" % (t.t("pomo.title"),
                                              _pomodoro_state_text(pom)))
        except Exception:  # noqa: BLE001
            pass

    def _pomodoro_pet_react(self):
        """
        宠物对「该休息了」的反应 / How the mascot reacts to "take a break".

        找一个**这只角色动作表里真的存在**的行为来做 —— 动作名随角色包变，
        写死一个名字在别的角色上就是无声的 no-op。找不到就什么都不做。
        Pick a behaviour that actually exists in *this* character's table;
        names vary per pack, so a hard-coded one would be a silent no-op.
        """
        candidates = ("ジャンプ", "跳", "Jump")
        for m in self.mascots:
            try:
                for name in candidates:
                    if self.brain.behavior_by_name(m, name):
                        self._force_behavior(m, name, interrupt=True)
                        break
            except Exception:  # noqa: BLE001 - 一只失败不影响其它
                log.exception("pomodoro pet reaction failed")

    @staticmethod
    def startup_command() -> str:
        """
        开机自启该跑哪条命令行 / The command line Windows should run at log-in.

        打包版和源码版**必须分开**处理，这是原来写错的地方：老代码无论哪种
        情况都写成 `"<解释器>" "<项目根>/main.py"`，而打包后
        `sys.executable` 已经是 `Utopet.exe`、`main.py` 又根本没被塞进安装目录 ——
        于是自启项里的命令指向一个不存在的文件，Windows 每次登录都静默失败
        （自启项「有」，但程序从来不会起来）。

        Frozen and source builds must be handled separately.  The old code always
        emitted `"<interpreter>" "<root>/main.py"`, but in a packaged build
        `sys.executable` is already `Utopet.exe` and `main.py` is not shipped at
        all — so the entry pointed at a missing file and every log-in failed
        silently.  The entry existed; the program never started.

        源码版优先用 `pythonw.exe`：它不创建控制台窗口，而 `python.exe` 会在
        每次登录时闪一个黑框出来。
        The source build prefers `pythonw.exe`, which creates no console window;
        `python.exe` would flash a black box on every log-in.
        """
        if getattr(sys, "frozen", False):
            return '"%s"' % os.path.abspath(sys.executable)
        exe = os.path.abspath(sys.executable or "")
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(candidate):
            exe = candidate
        script = os.path.join(APP_ROOT, "main.py")
        return '"%s" "%s"' % (exe, script)

    def set_startup(self, enabled: bool) -> bool:
        """
        开机自启（写 HKCU 的 Run 项）/ Toggle launch-at-login via the registry.

        用 `CreateKeyEx` 而不是 `OpenKey`：Run 项在某些精简系统/新账户上
        还不存在，`OpenKey` 会直接抛 `FileNotFoundError`，于是「勾上自启」
        静默失败 —— 用户看到勾选框是勾着的，实际什么也没写。
        `CreateKeyEx` rather than `OpenKey`: the Run key does not exist on some
        trimmed systems and fresh profiles, and `OpenKey` raises immediately, so
        ticking the box silently did nothing while the box stayed ticked.

        返回是否真的成功 / returns whether it actually worked.
        """
        try:
            import winreg
        except ImportError:      # 非 Windows，不该发生但别炸
            return False
        name = "Utopet"
        try:
            with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ,
                                      self.startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
            log.info("startup entry %s: %s", "set" if enabled else "removed",
                     self.startup_command() if enabled else name)
            return True
        except OSError:
            log.exception("startup toggle failed")
            return False
