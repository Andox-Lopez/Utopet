# -*- coding: utf-8 -*-
"""
全局设置 / Global settings
==============================================================================
设置持久化在 `config/settings.json`（带注释的可读 JSON）；自定义动作与行为
持久化在 `data/custom.xml`
（与原始配置同构，可随时手工编辑）。

Settings are persisted in `config/settings.json` (commented, human-editable
JSON); custom actions and behaviours are persisted in `data/custom.xml`, which
uses the very same schema as the original configuration files and can
therefore be hand-edited.
"""

from __future__ import annotations

import json
import os
import sys

from .i18n import LANGUAGES

from . import cfgfmt

__all__ = ["Settings", "APP_ROOT", "CONFIG_DIR", "DATA_DIR", "CHARACTERS_DIR",
           "RESOURCE_DIR"]


def _app_root() -> str:
    """
    定位「程序所在目录」/ Locate the folder the application lives in.

    源码运行时就是项目根目录；但 PyInstaller 打包后 `__file__` 指向解包出来的
    `_internal`，那里的 characters/ 和 data/ 都不存在。所以打包后改用 exe
    旁边的目录 —— 角色包和设置都放在 exe 旁边，方便用户直接替换角色。

    Running from source the root is the project folder.  In a PyInstaller build
    `__file__` points inside the unpacked `_internal`, where neither characters/
    nor data/ exists, so we use the folder next to the executable instead: the
    character packs and settings then live right beside the .exe.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#: 程序根目录 / application root —— 角色与设置都在这儿 / character packs & settings live here
APP_ROOT = _app_root()
#: 只读资源（locales / assets）所在目录 / read-only resources
RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
#: 用户可改配置 / user-editable configuration.
#: 独立成 config\ 而不是塞在 data\ 里：data\ 装的是运行期产物（日志、缓存、
#: 崩溃转储），卸载时整体删掉没问题；而 config\ 里是用户花时间调出来的偏好，
#: 需要一眼看出「哪些能手改」，两者混在一起迟早被误删。
#: Separate from data\: data\ holds run-time output (logs, caches, crash dumps)
#: and is fine to wipe on uninstall, while config\ holds preferences the user
#: spent time tuning.  Mixing them means a careless wipe loses real settings.
CONFIG_DIR = os.path.join(APP_ROOT, "config")
DATA_DIR = os.path.join(APP_ROOT, "data")
CHARACTERS_DIR = os.path.join(APP_ROOT, "characters")

DEFAULTS = {
    # 界面 / interface
    "language": "zh_CN",              # 界面语言 / UI language
    "bilingual": True,                # 动作名双语显示 / bilingual action labels
    # 角色 / character
    # 默认 Miku —— 也正是安装包唯一自带的角色包（installer\Utopet.iss 只打 Miku）。
    # Ayaka / 花卷 需要用户自己把角色包丢进 characters\，设置里就能切换。
    # Miku is the default *and* the only bundled character: the installer ships
    # Miku alone, so the default must match or fresh installs start with nothing.
    "character": "Miku",             # 当前角色目录名 / current character folder
    "character_dirs": [],             # 额外角色目录 / extra character folders
    # 外观 / appearance
    "scale": 1.0,                     # 缩放 / scale factor
    "tick_ms": 40,                    # 帧间隔（毫秒，原版 40ms = 25fps）/ frame interval
    "opacity": 1.0,                   # 不透明度 / window opacity
    "always_on_top": True,            # 始终置顶 / keep mascots on top
    # 行为 / behaviour
    "initial_count": 1,               # 启动时召唤几只 / how many mascots on start-up
    "restore_session": True,          # 记住上次退出的宠物与位置 / restore last session
    "session": [],                    # 上次会话快照 / last session snapshot
    # 逐条覆盖 Behavior.xml 的频次 / per-behaviour frequency overrides
    # 形如 {"分裂する": {"enabled": False}} 或 {"座る": {"frequency": 300}}
    "behavior_overrides": {},
    "max_count": 50,                  # 宠物数量上限 / mascot limit
    "self_cloning_enabled": True,     # 允许自我增殖 / allow self-cloning
    # 与窗口互动的两个独立开关。
    # 1.0.4 之前只有一个 `ie_interaction`，同时管爬窗和扔窗 —— 用户想只关掉
    # 「扔窗户」（宠物被抛出屏幕外就找不回来）却被迫连爬墙一起禁掉。
    # Two independent switches.  Before 1.0.4 a single `ie_interaction`
    # gated both climbing and throwing, so disabling "throw" to stop pets
    # flying off-screen also killed climbing.
    "climb_enabled": True,            # 允许爬窗户 / allow climbing windows
    "throw_enabled": True,            # 允许把窗户扔出去 / allow throwing windows
    # 旧键，仅用于迁移（见 load()）。升级过的配置不会凭空重新打开被用户关掉的
    # 行为。
    # Legacy key kept only for migration in load(); without it an upgraded
    # config would silently re-enable a behaviour the user had turned off.
    "ie_interaction": True,
    # 多宠物 / multi-mascot
    # 面板与托盘「一次召唤」的默认数量 / default batch size for "summon several"
    "summon_count": 5,
    # 一次召唤多只时是否均匀铺开（否则纯随机，容易叠成一堆）
    # Spread the drop points evenly when summoning several (random tends to pile up)
    "spawn_spread": True,
    # 鼠标静止时聚集；默认关闭 —— 原版 Behavior.xml 里「マウスの周りに集まる」
    # 的后续行为列表是封闭的，一旦进入宠物会一直坐着看鼠标，观感偏呆。
    # Gather around an idle cursor; off by default because the original
    # "マウスの周りに集まる" chain is封闭 (self-contained) and the pet would just sit
    # and stare at the cursor forever.
    "idle_gather": False,
    "idle_gather_sec": 25,            # 静止判定秒数 / idle threshold in seconds
    # 窗口 / windows
    "titles": [],                     # 窗口标题过滤 / window title filter
    "window_offset": [0, 0, 0, 0],    # X / Y / 宽 / 高 偏移 / rect offsets
    # 系统 / system
    "start_with_windows": False,      # 开机自启 / launch at login
    # 番茄时钟 / Pomodoro timer
    "pomodoro_work_min": 25,          # 工作时长 / work length
    "pomodoro_break_min": 5,          # 短休息 / short break
    "pomodoro_long_break_min": 15,    # 长休息 / long break
    "pomodoro_long_every": 4,         # 每几轮一次长休息 / long break every N
    "pomodoro_pet_react": True,       # 阶段切换时宠物做个动作 / pet reacts
    # 任务栏常驻控制面板：一个普通窗口，可在任务栏固定
    # Always-on taskbar control panel: a normal window that can be pinned
    "taskbar_panel": True,
    # 面板上次被拖到的位置 [x, y]；None = 从没拖过，打开时落右下角。
    # Where the panel was last dragged to; None means never moved, so it opens
    # at the bottom-right corner.
    "panel_pos": None,
    # 首次启动引导是否已看过。默认 False = 还没看，会弹一次。
    # Whether the first-run guidance has been seen.  False = not yet.
    "first_run_guide_done": False,
}

CUSTOM_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" ?>'


class Settings:
    """读写 config\\settings.json / Reads and writes config\\settings.json.

    文件格式是**带注释、分组的 JSON**（见 cfgfmt）。用户可以直接手改，
    程序读的时候会把 `//` 注释剥掉再解析。
    The file is commented, grouped JSON (see cfgfmt): the user may hand-edit
    it, and comment lines are stripped before parsing.
    """

    def __init__(self, path: str | None = None):
        # 默认落在 config\ 下；旧版在 data\settings.json，自动迁移过去，
        # 免得升级后用户精心调过的设置「凭空重置」。
        self.path = path or os.path.join(CONFIG_DIR, "settings.json")
        if path is None:
            self._migrate_legacy_path()
        self.data = dict(DEFAULTS)
        self.load()

    def _migrate_legacy_path(self) -> None:
        """把旧位置的 settings.json 搬到 config\\，再删掉旧的。

        不搬的话，1.0.5 之后的程序会读不到任何旧设置 —— 用户看到的就是
        「升级完设置全没了」，而这恰恰是这个版本要解决的问题。
        Move a legacy data\\settings.json into config\\ and remove the old one.
        Skipping this would make an upgrade look like a settings reset — the
        very problem 1.0.5 exists to fix.
        """
        legacy = os.path.join(DATA_DIR, "settings.json")
        if os.path.abspath(legacy) == os.path.abspath(self.path):
            return
        if not os.path.exists(legacy):
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            os.replace(legacy, self.path)
        except OSError:
            #搬不动（权限/占用）就退回读旧位置，绝不能把用户的配置弄丢。
            # If the move fails (permissions, a running instance), fall back
            # to reading the old location — never lose the user's settings.
            self.path = legacy

    def load(self):
        loaded: dict = {}
        self.load_error = ""
        self._user_comments: dict[str, list[str]] = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = f.read()
            loaded = cfgfmt.loads_stripping_comments(raw)
            # 收下用户自己写的注释，重写时原样贴回去
            self._user_comments = cfgfmt.read_extra_comments(raw)
        except OSError:
            loaded = {}
        except ValueError as e:
            # 手改配置写坏了要**明确告诉用户**，不能静默当成空配置 ——
            # 静默的话用户一开软件发现设置全没了，更不知道是自己改坏的。
            # A hand-edit that broke the file must be reported loudly; treating
            # it as empty would wipe the user's settings with no explanation.
            self.load_error = str(e)
            try:
                os.replace(self.path, self.path + ".broken")
                self.load_error += "（原文件已改名保存为 settings.json.broken）"
            except OSError:
                pass
            loaded = {}
        if isinstance(loaded, dict):
            for k, v in loaded.items():
                self.data[k] = v
        # 迁移：旧的单一 `ie_interaction` 拆成爬窗 / 扔窗两个独立开关。
        # 只在**旧键存在且新键缺失**时派生，之后两者各自独立，互不影响。
        # Migrate the single legacy `ie_interaction` into two independent
        # switches.  Only derive when the legacy key is present and the new
        # ones are missing; after that the two are fully independent.
        if "ie_interaction" in loaded and not (
                "climb_enabled" in loaded or "throw_enabled" in loaded):
            legacy = bool(self.data.get("ie_interaction", True))
            self.data["climb_enabled"] = legacy
            self.data["throw_enabled"] = legacy
        # 语言合法性校正 / validate the language code
        if self.data.get("language") not in LANGUAGES:
            self.data["language"] = "zh_CN"

    def save(self):
        """原子写入，避免断电/崩溃留下半份配置。

        用户配置是这个软件里最不该丢的数据 —— 丢一次等于把人家调了一下午的
        设置全部归零。先写 .tmp 再 os.replace。
        Atomic write: a half-written config would reset every setting the user
        tuned.  Write a .tmp first, then os.replace.
        """
        cfgfmt.atomic_write(
            self.path,
            cfgfmt.dumps_readable(self.data, list(DEFAULTS.keys()),
                                  self._user_comments))

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

    def reset(self):
        self.data = dict(DEFAULTS)

    # ------------------------------------------------------------------
    @property
    def custom_xml(self) -> str:
        return os.path.join(DATA_DIR, "custom.xml")

    def ensure_custom_xml(self):
        """确保自定义配置文件存在 / Make sure the custom-configuration file exists."""
        p = self.custom_xml
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(CUSTOM_XML_HEADER)
                f.write("<マスコット>\n\t<動作リスト>\n\t</動作リスト>\n")
                f.write("\t<行動リスト>\n\t</行動リスト>\n</マスコット>\n")
        return p
