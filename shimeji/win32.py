# -*- coding: utf-8 -*-
"""
Windows 原生窗口接口 / Native Windows window helpers
==============================================================================
原版 Shimeji 通过 JNA 调用 User32；这里用 ctypes 实现同样能力：
枚举窗口、取窗口矩形、读取工作区（排除任务栏）、移动窗口。

The original Shimeji calls User32 through JNA.  Here we do the same with ctypes:
enumerate windows, read window rectangles, read the work area (taskbar excluded)
and move windows.

坐标系 / Coordinate system
------------------------------------------------------------------------------
本模块对外**一律返回「逻辑像素」**（Qt 使用的坐标系）。Qt 应用在 Windows 上默认是
DPI-aware 的，而 User32 返回的是物理像素，所以所有返回值都要除以当前缩放比。
用 `set_dpi_scale()` 设置缩放比，通常取
`QApplication.primaryScreen().devicePixelRatio()`。

Every function here returns **logical pixels** (Qt's coordinate system).  Qt apps
are DPI-aware on Windows while User32 reports physical pixels, so results are
divided by the current scale.  Call `set_dpi_scale()` with
`QApplication.primaryScreen().devicePixelRatio()`.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

__all__ = [
    "get_work_area", "get_screen_rect", "get_cursor_pos",
    "list_windows", "window_at", "move_window", "get_window_title",
    "get_foreground_window",
    "enum_monitors", "set_dpi_scale", "dpi_scale", "is_zoomed",
    "set_app_user_model_id", "APP_ID", "make_taskbar_window", "window_rect",
    "get_input_caret_rect", "visible_ime_rects", "key_pressed_since",
]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

#: 任务栏身份 / taskbar identity —— 让 Windows 把本进程当成独立应用，
#: 这样任务栏按钮显示的是我们的 Logo，且右键可「固定到任务栏」。
#: Lets Windows treat this process as its own application, so the taskbar
#: button shows our own logo and can be pinned.
APP_ID = "Karandox.Utopet.DesktopPet"

SPI_GETWORKAREA = 0x0030
GA_ROOT = 2
DWMWA_CLOAKED = 14
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
MONITOR_DEFAULTTOPRIMARY = 1

#: 物理像素 -> 逻辑像素 的除数 / physical -> logical divisor
_dpi_scale = 1.0


# ══════════════════════════════════════════════════════════════════════════
# 输入状态探测 / Input-state probing
# ══════════════════════════════════════════════════════════════════════════
# 用途：用户正在打字时，宠物不该跑到输入框和输入法候选窗上压着。
#
# ⭐ 实测结论（本机逐条验过，别再重复推��）：
#   · `rcCaret`（精确光标矩形）在 **Firefox 67 次采样全 0**、Chrome 全 0。
#     原因：现代应用（Chromium / Electron / Gecko）**自己画光标**，不用系统
#     caret。只有记事本、Office 这类传统 Win32 控件才提供。
#   · `ImmGetContext(前台窗口)` 在现代应用下返回 0，拿不到输入法上下文。
#   · 枚举 `IME*` / `MSCTFIME UI` 窗口：系统里常驻 131 个，但平时**全部
#     `visible=0` 且矩形为空**，只有真正激活输入法时才有可用的。
#   · `GetCursorPos` **零依赖永远可用** —— 这是唯一能在所有应用上工作的锚点。
#   · `GetAsyncKeyState` 可用（实测注入 F12 能读到低位），但**逐键点名不可靠**，
#     所以这里扫全键空间而不是列一张「打字键位表」。
#   · ⛔ `GetLastInputInfo` **不区分键鼠**：用户动一下鼠标它就归零。用它判
#     「正在打字」会导致宠物因鼠标移动而无缘无故躲开。
#
# So the exact caret rect is *not* available on modern apps; the cursor position
# is the only universally reliable anchor, and keyboard activity is the only
# usable "is the user typing" signal.


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", _RECT),
    ]


#: `IME*` / `MSCTFIME UI` 窗口类前缀。输入法候选窗和组合串窗都是独立顶层窗口，
#: 可见时能被枚举到 —— 这是「输入法激活」唯一能直接读到的信号。
#: The IME candidate / composition windows are separate top-level windows, so
#: enumerating them is the one direct signal for "an IME is showing".
_IME_CLASS_PREFIXES = ("IME",)
_IME_CLASS_EXACT = frozenset(("MSCTFIME UI", "Default IME"))


def get_input_caret_rect() -> tuple[int, int, int, int] | None:
    """输入光标矩形（屏幕坐标），拿不到返回 ``None``。

    精确信息，只在**传统 Win32 文本控件**下有效（记事本、Office、Delphi…）。
    Firefox / Chrome / VS Code 一律返回 `None` —— 它们自己画光标，不提供
    系统 caret。调用方**必须**有回退路径。
    The exact caret rect, in screen coordinates, or None.

    Only available for classic Win32 text controls.  Browsers and Electron apps
    draw their own caret and report nothing, so callers must have a fallback.
    """
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    if not _user32.GetGUIThreadInfo(0, ctypes.byref(info)):
        return None
    if not info.hwndCaret:
        return None
    rc = info.rcCaret
    # rcCaret 恒为 0 就是「没有真光标」的信号，与 hwndCaret 缺失互相印证。
    if rc.right - rc.left <= 0 or rc.bottom - rc.top <= 0:
        return None
    # rcCaret 是**客户区坐标**，必须转屏幕坐标才能和光标位置比较。
    # rcCaret is in client coordinates; screen space is what the engine speaks.
    top_left = wintypes.POINT(rc.left, rc.top)
    bottom_right = wintypes.POINT(rc.right, rc.bottom)
    if not _user32.ClientToScreen(info.hwndCaret, ctypes.byref(top_left)):
        return None
    if not _user32.ClientToScreen(info.hwndCaret, ctypes.byref(bottom_right)):
        return None
    return (_l(top_left.x), _l(top_left.y),
            _l(bottom_right.x), _l(bottom_right.y))


def visible_ime_rects() -> list[tuple[int, int, int, int]]:
    """**可见且矩形非空**的输入法窗口 / Visible, non-empty IME windows.

    平时返回空列表（系统里那 130 来个 IME 辅助窗口全都不可见），只有输入法
    真的被激活、候选窗弹出来时才有值。用来在「正在选字」时把宠物赶得更远。

    ⭐ **实测耗时 1.35ms**（枚举全部顶层窗口），是本模块最贵的调用。相对 40ms
    的帧长占 3.4%，可以每帧调，但**更划算的做法是只在检测到键盘活动时调** ——
    IME 被激活必然伴随键盘输入，这个前置条件是可靠的。
    Normally empty; populated only while an IME candidate window is up.

    Measured at 1.35 ms — the most expensive call here.  Call it only after
    keyboard activity is detected: an IME can only be up if the user typed.
    """
    out: list[tuple[int, int, int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        cls_name = buf.value
        if not (cls_name.startswith(_IME_CLASS_PREFIXES)
                or cls_name in _IME_CLASS_EXACT):
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        r = _RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return True
        if r.right - r.left <= 0 or r.bottom - r.top <= 0:
            return True
        out.append((_l(r.left), _l(r.top), _l(r.right), _l(r.bottom)))
        return True

    _user32.EnumWindows(_cb, 0)
    return out


def key_pressed_since() -> bool:
    """自**上次调用**以来，是否有任意键盘输入。/ Any keyboard input since the last call.

    ⭐ 靠 `GetAsyncKeyState` 的**低位**（bit 0）：Windows 规定「自上次调用以来
    该键被按过」置位，且读取即清零。所以这个函数**只能按固定节奏轮询**，
    调用太稀会漏、调用太频没有额外代价。
    ⛔ 绝不能用 `GetLastInputInfo`：它不区分键鼠，用户动一下鼠标就归零。
    ⛔ 扫描范围是**全部 256 个虚拟键码**而不是「打字键位表」：实测逐键点名极
    不可靠（按住 Shift/Ctrl 常常读不到，只有 Alt 能复现），扫全空间就没这个
    问题。代价是 256 次 ctypes 调用，约 20µs，相对每帧 40ms 完全可忽略。

    Uses bit 0 of `GetAsyncKeyState`, which Windows clears on read — hence
    "poll at a fixed cadence".  Scans all 256 virtual-key codes rather than a
    "typing keys" table: measured, a hand-written table misses most keys.
    """
    get = _user32.GetAsyncKeyState
    for vk in range(1, 256):
        if get(vk) & 0x0001:
            return True
    return False



def set_dpi_scale(value: float):
    """设置 DPI 缩放比 / Set the DPI scale factor (physical / logical)."""
    global _dpi_scale
    _dpi_scale = float(value) if value and value > 0 else 1.0


def dpi_scale() -> float:
    return _dpi_scale


def _l(value: float) -> int:
    """物理 -> 逻辑 / physical to logical."""
    return int(round(float(value) / _dpi_scale))


def _p(value: float) -> int:
    """逻辑 -> 物理 / logical to physical."""
    return int(round(float(value) * _dpi_scale))


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_ulong, ctypes.c_ulong,
                                      ctypes.POINTER(wintypes.RECT), ctypes.c_long)
_user32.EnumDisplayMonitors.argtypes = [wintypes.HMONITOR, wintypes.HDC,
                                        _MONITORENUMPROC, ctypes.c_long]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [ctypes.c_ulong, ctypes.POINTER(MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = ctypes.c_ulong

# ⭐ 窗口 -> 所在显示器。用来把窗口移动限制在**它当前所在的那块屏幕**内，
# 从而保证它不会跑出当前虚拟桌面（见 `move_window_at()` 的说明）。
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = ctypes.c_ulong

_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                          ctypes.c_void_p, wintypes.UINT]
_user32.SystemParametersInfoW.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.GetShellWindow.argtypes = []
_user32.GetShellWindow.restype = wintypes.HWND
_user32.GetDesktopWindow.argtypes = []
_user32.GetDesktopWindow.restype = wintypes.HWND

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    try:
        _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                      ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    except OSError:
        return False
    return bool(cloaked.value)


def get_screen_rect() -> tuple[int, int, int, int]:
    """虚拟屏幕矩形 / The virtual screen rectangle (left, top, right, bottom)."""
    return (0, 0,
            _l(_user32.GetSystemMetrics(0)),   # SM_CXSCREEN
            _l(_user32.GetSystemMetrics(1)))   # SM_CYSCREEN


def get_work_area() -> tuple[int, int, int, int]:
    """主显示器工作区矩形（排除任务栏）/ Primary monitor's work area, taskbar excluded."""
    rect = wintypes.RECT()
    if _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return _l(rect.left), _l(rect.top), _l(rect.right), _l(rect.bottom)
    left, top, right, bottom = get_screen_rect()
    return left, top, right, bottom - 40


def enum_monitors() -> list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """
    枚举所有显示器 / Enumerate every monitor.

    返回 [((monitor left, top, right, bottom), (work left, top, right, bottom)), ...]
    Returns a list of (full rect, work-area rect) pairs in logical pixels.
    """
    out = []

    def _cb(hmon, _hdc, _rect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            m = (_l(info.rcMonitor.left), _l(info.rcMonitor.top),
                 _l(info.rcMonitor.right), _l(info.rcMonitor.bottom))
            w = (_l(info.rcWork.left), _l(info.rcWork.top),
                 _l(info.rcWork.right), _l(info.rcWork.bottom))
            out.append((m, w))
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0)
    except OSError:
        pass
    if not out:
        out.append(((0, 0) + get_screen_rect()[2:], get_work_area()))
    return out


def get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return _l(pt.x), _l(pt.y)


def get_foreground_window() -> int:
    """
    当前前台（活动）窗口的句柄 / Handle of the foreground (active) window.

    没有前台窗口时返回 0（例如正在切换桌面、锁屏）。
    Returns 0 when there is none, e.g. while switching desktops or on the lock
    screen.
    """
    try:
        return int(_user32.GetForegroundWindow() or 0)
    except OSError:
        return 0


def get_window_title(hwnd: int) -> str:
    n = _user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _rect_of(hwnd: int):
    r = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    if r.right - r.left <= 0 or r.bottom - r.top <= 0:
        return None
    return r.left, r.top, r.right, r.bottom


def list_windows(min_size: int = 120) -> list[tuple[int, tuple[int, int, int, int]]]:
    """
    枚举可作为「地面/墙壁」的可见顶层窗口。
    Enumerate visible top-level windows that can act as floor / wall / ceiling.

    排除：本进程窗口、隐藏窗口、最小化窗口、Cloaked（UWP 隐藏）窗口、过小窗口。
    Excludes: our own windows, invisible, minimised, cloaked and tiny windows.
    """
    me = os.getpid()
    shell = _user32.GetShellWindow()
    desktop = _user32.GetDesktopWindow()
    out: list[tuple[int, tuple[int, int, int, int]]] = []

    def _cb(hwnd, _lparam):
        try:
            if hwnd in (shell, desktop):
                return True
            if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
                return True
            if _pid_of(hwnd) == me:
                return True
            if _is_cloaked(hwnd):
                return True
            r = _rect_of(hwnd)
            if r is None:
                return True
            lr = (_l(r[0]), _l(r[1]), _l(r[2]), _l(r[3]))
            if (lr[2] - lr[0]) < min_size or (lr[3] - lr[1]) < min_size:
                return True
            out.append((hwnd, lr))
        except OSError:
            pass
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return out


def window_at(x: int, y: int) -> tuple[int, tuple[int, int, int, int]] | None:
    """取坐标处的顶层窗口 / The top-level window under a point, or None."""
    hwnd = _user32.WindowFromPoint(wintypes.POINT(_p(x), _p(y)))
    if not hwnd:
        return None
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    if root:
        hwnd = root
    if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return None
    if _pid_of(hwnd) == os.getpid():
        return None
    r = _rect_of(hwnd)
    if r is None:
        return None
    return hwnd, r


#: `MonitorFromWindow` 的第二参数：窗口不在任何显示器上时选最近的
#: `MONITOR_DEFAULTTONEAREST` = 2
MONITOR_DEFAULTTONEAREST = 2


def _monitor_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """
    窗口所在显示器的**完整屏幕范围** / The full screen rect of the monitor the window is on.

    用 `MonitorFromWindow` 而不是 `MonitorFromPoint`：窗口可能已经被拖到屏幕
    边缘之外，用光标反推所属的显示器会错。

    `MonitorFromWindow` rather than `MonitorFromPoint`: the window may already
    hang over the edge of the screen, so the monitor under the *cursor* would
    be the wrong one.
    """
    try:
        hmon = _user32.MonitorFromWindow(wintypes.HWND(hwnd),
                                         MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        rc = info.rcMonitor
        return rc.left, rc.top, rc.right, rc.bottom
    except (AttributeError, OSError, ValueError):
        return None


def clamp_to_desktop(hwnd: int, x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """
    把目标位置夹到**窗口当前所在显示器**的屏幕范围内。

    -> Clamp the target position into the screen rect of the monitor the
    -> window currently sits on.

    ⭐⭐ **为什么这个夹取是必须的（Windows 虚拟桌面）** ⭐⭐

    Windows 的虚拟桌面（Virtual Desktop）是按**全局坐标**分区的：桌面 1 占
    主显示器的坐标区域（单显示器就是 0,0-1920,1080），桌面 2 就在它右侧或
    下方的**另一块坐标区域**。

    **把窗口移到当前桌面范围之外的坐标，Windows 会把它自动移到那个坐标所在
    的虚拟桌面。** 用户就再也切不回那扇窗口了 —— 只能关掉软件重开。

    这正是本项目测试里把真实应用窗口挪到 `work_area.right + 500`（2420）
    造成的后果。

    所以任何移动窗口的调用都必须先经过这里。用窗口**当前所在**的显示器
    （而不是主显示器）做夹取：多显示器时窗口可能在副屏上，而副屏在当前
    虚拟桌面里也有自己的坐标区域。

    A move to a coordinate outside the current virtual desktop makes Windows
    relocate the window to the desktop owning that coordinate, and the user
    can never switch back to it.  Every window move must go through this
    clamp.
    """
    rect = _monitor_rect(hwnd)
    if rect is None:
        return x, y
    left, top, right, bottom = rect
    if w <= 0:
        w = 1
    if h <= 0:
        h = 1
    # 窗口比屏幕大时（超广显示器）不能归回一个越界的位置，就停在屏幕左上角。
    # A window larger than the screen is clamped to the top-left corner
    # instead of an out-of-range position.
    nx = min(max(x, left), max(left, right - w))
    ny = min(max(y, top), max(top, bottom - h))
    return nx, ny


def move_window_at(hwnd: int, x: int, y: int) -> tuple[int, int] | None:
    """
    移动窗口并返回**实际落点** / Move a window, returning where it landed.

    实际落点可能不是请求的 (x, y) —— 见 `clamp_to_desktop()`。调用方**必须**
    用返回值更新自己的坐标记录，否则引擎会以为窗口在别处（而它实际在这里），
    下一帧的位移就会累积成巨大的跳跃。

    The landing point may differ from the requested one (see
    `clamp_to_desktop()`).  Callers **must** update their own coordinates from
    the return value, or the engine will believe the window is elsewhere and
    the next frame's delta will accumulate into a huge jump.
    """
    w = h = 0
    r = _rect_of(hwnd)
    if r is not None:
        w = r[2] - r[0]
        h = r[3] - r[1]
    nx, ny = clamp_to_desktop(hwnd, x, y, w, h)
    try:
        ok = bool(_user32.SetWindowPos(hwnd, 0, _p(nx), _p(ny), 0, 0,
                                       SWP_NOSIZE | SWP_NOZORDER
                                       | SWP_NOACTIVATE))
    except OSError:
        return None
    if not ok:
        return None
    return nx, ny


def move_window(hwnd: int, x: int, y: int) -> bool:
    """
    只移动、不改变尺寸和 Z 序 / Move a window without resizing or restacking it.

    ⭐ 会先夹到当前桌屏内（虚拟桌面安全），见 `clamp_to_desktop()`。
    -> Clamped into the current desktop first; see `clamp_to_desktop()`.
    """
    return move_window_at(hwnd, x, y) is not None


def is_zoomed(hwnd: int) -> bool:
    return bool(_user32.IsZoomed(hwnd))


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """
    窗口的**含边框**矩形（逻辑像素）/ The window rect *including* its frame.

    Qt 的 `width()/height()` 只算客户区，而 `GetWindowRect` 算上不可见边框，
    两者能差 30~40px（Windows 11 的阴影/扩展边框）。要把窗口精确贴到工作区
    边缘，必须用这个含边框的尺寸。

    Qt reports the client area only while `GetWindowRect` includes the invisible
    resize border -- on Windows 11 the difference is 30-40 px.  Use this when a
    window has to sit exactly at the edge of the work area.
    """
    r = _rect_of(hwnd)
    if r is None:
        return None
    return _l(r[0]), _l(r[1]), _l(r[2]), _l(r[3])


def set_app_user_model_id(app_id: str = APP_ID) -> bool:
    """
    声明本进程的任务栏身份 / Declare this process's taskbar identity.

    Windows 默认按「宿主可执行文件」给任务栏按钮分组；Python 脚本跑起来时
    任务栏会显示 python.exe 的图标。调用
    `SetCurrentProcessExplicitAppUserModelID` 之后，系统把本进程当作独立应用，
    于是：① 按钮用我们自己设的窗口图标；② 右键菜单里能「固定到任务栏」；
    ③ 开机自启后不会和别的 Python 程序挤成一组。

    Windows groups taskbar buttons by the host executable, so a Python script
    would show up under python.exe's icon.  Calling
    `SetCurrentProcessExplicitAppUserModelID` makes the shell treat this process
    as a standalone app: the button uses our own window icon, "Pin to taskbar"
    becomes available, and the auto-start entry no longer merges with other
    Python programs.

    必须在创建任何窗口之前调用 / must be called before any window is created.
    """
    try:
        fn = _shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = [ctypes.c_wchar_p]
        fn.restype = ctypes.HRESULT
        hr = fn(app_id)
        return hr >= 0
    except (AttributeError, OSError):
        return False


# ------------------------------------------------------------------------------
# 强制任务栏按钮 / forcing a taskbar button
# ------------------------------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = ctypes.c_longlong
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
_user32.SetWindowLongPtrW.restype = ctypes.c_longlong


def make_taskbar_window(hwnd: int) -> bool:
    """
    强制给窗口一个任务栏按钮 / Force a taskbar button for this window.

    Qt 6 的普通 QWidget 并不带 `WS_EX_APPWINDOW`（实测只有 0x100），是否显示
    按钮取决于外壳对「无属主顶层窗口」的判定，行为随 Qt / Windows 版本浮动。
    这里显式置位并清掉 `WS_EX_TOOLWINDOW`，按钮一定会出现，右键菜单也就能
    「将此程序固定到任务栏」。

    A plain Qt 6 QWidget does not get `WS_EX_APPWINDOW` (measured: only 0x100),
    so whether a button appears depends on the shell's rules for unowned
    top-level windows and drifts between Qt / Windows versions.  Setting the bit
    (and clearing `WS_EX_TOOLWINDOW`) guarantees the button, which in turn makes
    "Pin this program to taskbar" available.
    """
    try:
        ex = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex == 0:
            return False
        new = (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        if new == ex:
            return True
        return bool(_user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new))
    except (AttributeError, OSError):
        return False


def open_settings_page(uri: str) -> bool:
    """打开系统设置里的某个页面 / Open a page of Windows Settings.

    用 `ShellExecuteW` 而不是 `os.startfile`：`ms-settings:` 这类 URI 必须由
    shell 解析，`startfile` 在部分 Python 版本上对未知协议会静默失败。
    Returns False instead of raising so callers can show a message.
    """
    try:
        # 6 = SW_SHOWNORMAL
        rc = _shell32.ShellExecuteW(None, "open", uri, None, None, 6)
        return int(rc) > 32          # <= 32 表示失败
    except (AttributeError, OSError):
        return False


def open_taskbar_settings() -> bool:
    """直接跳到系统设置的「任务栏」页 / Jump straight to Settings > Taskbar.

    为什么需要它：托盘图标被收进任务栏右侧的「^」溢出区是 Windows 10 起的
    默认行为，而这正是「桌宠找不到」的头号原因。用户抱怨找不到图标时，让他
    去「设置 > 个性化 > 任务栏 > 其它系统托盘图标」逐个翻找是不现实的 ——
    直接把那一页打开摆在他面前。

    `ms-settings:` 在 Windows 10 1709 之后可用；更老的系统会失败，此时
    返回 False，调用方应回退到说明文字而不是报错。
    Jump to Settings > Taskbar.

    The tray icon landing in the "^" overflow area is default behaviour since
    Windows 10 and the single biggest reason users lose track of the pet.
    Make the user dig through "Other system tray icons" one by one is not a
    reasonable answer — open the page for them.  `ms-settings:` needs Windows
    10 1709+; on older systems this returns False and the caller falls back to
    written instructions.
    """
    return open_settings_page("ms-settings:taskbar")
