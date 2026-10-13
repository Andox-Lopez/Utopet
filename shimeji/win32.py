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
    "enum_monitors", "set_dpi_scale", "dpi_scale", "is_zoomed",
    "set_app_user_model_id", "APP_ID", "make_taskbar_window", "window_rect",
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


def move_window(hwnd: int, x: int, y: int) -> bool:
    """只移动、不改变尺寸和 Z 序 / Move a window without resizing or restacking it."""
    try:
        return bool(_user32.SetWindowPos(hwnd, 0, _p(x), _p(y), 0, 0,
                                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))
    except OSError:
        return False


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
