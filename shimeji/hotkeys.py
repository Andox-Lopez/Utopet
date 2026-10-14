# -*- coding: utf-8 -*-
"""
全局快捷键 / Global hotkeys
==============================================================================
用 Win32 的 `RegisterHotKey` 注册，所以**前台是任何程序时都生效** —— 这正是
「叫桌宠出来」该有的形态：用户正在写文档，想召唤一只，不该先去任务栏右侧的
溢出区里把托盘图标挖出来。

Registered through Win32 `RegisterHotKey`, so the shortcuts fire while **any**
program has focus.  That is the whole point: wanting the pet should not require
first digging the tray icon out of the overflow area.

实现要点 / the parts that are easy to get wrong
------------------------------------------------------------------------------
* Qt 没有全局快捷键（`QShortcut` 只在自家窗口有焦点时有效），所以必须走原生
  消息。注册成功的热键会以 `WM_HOTKEY` 投递到**本线程**的消息队列，
  `QAbstractNativeEventFilter` 就能收到 —— 不必另起消息循环。
  Qt has no global shortcuts (`QShortcut` only fires while one of our windows
  has focus), so this drops to native messages.  A registered hotkey posts
  `WM_HOTKEY` to *this thread's* queue, which `QAbstractNativeEventFilter`
  sees; no extra message pump is required.
* **注册失败是静默的**：键被别的程序占了，`RegisterHotKey` 返回 0 而不抛异常。
  失败必须逐条收集起来交给界面显示，否则用户看到的现象只是「设了快捷键，
  按下去没反应」，完全无从下手。
  Failure is silent: if another program owns the combination `RegisterHotKey`
  returns 0 without raising.  Failures are collected per action and surfaced in
  the UI, otherwise the user just sees "I set a shortcut and nothing happens".
* 至少要求一个修饰键。不带修饰键的注册会把那个键**从所有程序手里抢走**，
  是纯粹的破坏性配置。
  At least one modifier is required: registering a bare key steals it from every
  other program, which is destructive rather than useful.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

__all__ = [
    "ACTION_KEYS", "DEFAULT_HOTKEYS", "HotkeyManager",
    "parse_spec", "format_spec", "MODIFIER_NAMES",
]

log = logging.getLogger("shimeji")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                   wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
#: 按住不放只触发一次 / holding the key fires once, not in a burst
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

#: 动作键 → 默认快捷键 / action key -> default shortcut.
#: 选 Ctrl+Alt 是因为它极少与常见软件冲突（Ctrl+Shift 被输入法抢、
#: Ctrl+Alt+字母 基本留给用户自己）。改键直接编辑 config\settings.json。
#: Ctrl+Alt is picked because it rarely clashes (Ctrl+Shift is taken by IMEs);
#: edit config\settings.json to change them.
ACTION_KEYS = ("summon", "dismiss", "toggle_hidden", "panel")

DEFAULT_HOTKEYS = {
    "summon": "Ctrl+Alt+S",
    "dismiss": "Ctrl+Alt+D",
    "toggle_hidden": "Ctrl+Alt+H",
    "panel": "Ctrl+Alt+P",
}

_MODIFIER_BITS = (
    ("Ctrl", MOD_CONTROL),
    ("Alt", MOD_ALT),
    ("Shift", MOD_SHIFT),
    ("Win", MOD_WIN),
)

#: 中文/日文写法也认 / Chinese & Japanese spellings are accepted too
_MODIFIER_ALIASES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "ctl": MOD_CONTROL,
    "控制": MOD_CONTROL, "ctrl键": MOD_CONTROL,
    "alt": MOD_ALT, "option": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN, "cmd": MOD_WIN,
    "windows": MOD_WIN, "徽标": MOD_WIN,
}

#: 给界面显示用 / for display in the UI
MODIFIER_NAMES = {
    MOD_CONTROL: "Ctrl", MOD_ALT: "Alt", MOD_SHIFT: "Shift", MOD_WIN: "Win",
}


class MSG(ctypes.Structure):
    """Win32 `MSG` / the native message structure."""

    _fields_ = [("hWnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT)]


def parse_spec(spec: str) -> tuple[int, int] | None:
    """
    解析 `"Ctrl+Alt+S"` → `(modifiers, virtual_key)`。

    解析不出来（空串、缺修饰键、认不得的键名）一律返回 `None`，调用方按
    「未绑定」处理 —— 一条坏配置不该让整个快捷键子系统起不来。

    Returns `None` for anything unparseable (empty, no modifier, unknown key
    name).  Callers treat that as "not bound": one bad entry must not take the
    whole subsystem down.
    """
    if not spec or not isinstance(spec, str):
        return None
    mods = 0
    key: int | None = None
    for raw in spec.replace("＋", "+").split("+"):
        token = raw.strip()
        if not token:
            continue
        low = token.lower()
        if low in _MODIFIER_ALIASES:
            mods |= _MODIFIER_ALIASES[low]
            continue
        if key is not None:
            return None                      # 两个主键 / two non-modifier keys
        if len(token) == 1 and token.isalnum():
            key = ord(token.upper())
        elif token.upper().startswith("F") and token[1:].isdigit():
            n = int(token[1:])
            if 1 <= n <= 24:
                key = 0x70 + (n - 1)         # VK_F1..VK_F24
        elif token.isdigit() and len(token) == 1:
            key = ord(token)
        else:
            return None
    if key is None or mods == 0:
        return None
    return mods, key


def format_spec(mods: int, vk: int) -> str:
    """`(mods, vk)` → `"Ctrl+Alt+S"` / the inverse of :func:`parse_spec`."""
    parts = [name for name, bit in _MODIFIER_BITS if mods & bit]
    if 0x70 <= vk <= 0x87:
        parts.append("F%d" % (vk - 0x70 + 1))
    elif 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        parts.append(chr(vk))
    else:
        parts.append("0x%02X" % vk)
    return "+".join(parts)


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """
    按设置注册/注销全局快捷键 / Register and unregister global hotkeys.

    `specs` 是 `{动作: 快捷键文本}`；解析失败或注册失败的项会被记进
    :attr:`failed`，界面据此提示用户。
    `specs` maps action -> shortcut text.  Entries that fail to parse or to
    register land in :attr:`failed` so the UI can tell the user.
    """

    #: 某个快捷键被按下 / emitted with the action key
    triggered = Signal(str)

    _BASE_ID = 0xA100

    def __init__(self, app, specs: dict | None = None):
        super().__init__()
        self.app = app
        self._by_id: dict[int, str] = {}
        self._ids: list[int] = []
        self.failed: dict[str, str] = {}
        self.registered: dict[str, str] = {}
        self._installed = False
        self._specs: dict[str, str] = {}
        self.configure(specs or {})

    # ------------------------------------------------------------------
    def configure(self, specs: dict) -> None:
        """记住要注册的规格（留着 `apply()` 重注册用）/ Remember the specs."""
        self._specs = {k: str(v) if v else "" for k, v in (specs or {}).items()}

    def apply(self, specs: dict | None = None, enabled: bool = True) -> dict:
        """
        重新注册全部快捷键 / Re-register everything.

        返回 `{动作: 失败原因}`（空字典 = 全部成功）。
        Returns `{action: reason}`; an empty dict means everything worked.
        """
        if specs is not None:
            self.configure(specs)
        self.unregister()
        self.failed = {}
        self.registered = {}
        if not enabled:
            return self.failed

        event_type = self._event_type()
        if event_type is None:
            self.failed = {k: "unsupported platform"
                           for k in self._specs if self._specs.get(k)}
            return self.failed

        for index, action in enumerate(ACTION_KEYS):
            spec = self._specs.get(action) or ""
            if not spec:
                continue
            parsed = parse_spec(spec)
            if parsed is None:
                self.failed[action] = "bad spec"
                continue
            mods, vk = parsed
            hid = self._BASE_ID + index
            ok = _user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
            if not ok:
                self.failed[action] = "taken"
                log.warning("hotkey %s (%s) could not be registered",
                            spec, action)
                continue
            self._ids.append(hid)
            self._by_id[hid] = action
            self.registered[action] = format_spec(mods, vk)
        if not self._installed:
            self.app.installNativeEventFilter(self)
            self._installed = True
        return self.failed

    def unregister(self) -> None:
        """注销已注册的热键 / Release every registered hotkey.

        进程退出时没注销的话，别的程序在本次登录内都拿不到这个组合
        （Windows 会在进程结束后回收，但 RDP/快速用户切换下的表现不稳）。
        Unreleased hotkeys stay reserved for the rest of the session on some
        configurations, so release them explicitly.
        """
        for hid in self._ids:
            try:
                _user32.UnregisterHotKey(None, hid)
            except OSError:
                pass
        self._ids.clear()
        self._by_id.clear()
        if self._installed:
            try:
                self.app.removeNativeEventFilter(self)
            except (RuntimeError, TypeError):
                pass
            self._installed = False

    # ------------------------------------------------------------------
    @staticmethod
    def _event_type() -> bytes | None:
        """当前平台的原生消息类型名 / The native event type name on this platform."""
        try:
            from PySide6.QtGui import QGuiApplication
            platform = QGuiApplication.platformName()
        except Exception:  # noqa: BLE001
            platform = ""
        if platform == "windows":
            return b"windows_generic_MSG"
        return None

    # Qt 的钩子 / the Qt hook
    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type != b"windows_generic_MSG":
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY:
            action = self._by_id.get(int(msg.wParam))
            if action:
                # 交出去给主线程的槽处理，别在消息过滤器里干重活 ——
                # 这里还在原生消息分发里，弹窗/建窗都可能踩到重入。
                # Hand off to a queued slot: we are still inside native message
                # dispatch, where opening windows can re-enter.
                self.triggered.emit(action)
                return True, 0
        return False, 0
