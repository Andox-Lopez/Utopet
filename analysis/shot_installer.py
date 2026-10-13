# -*- coding: utf-8 -*-
"""截图 Inno Setup 安装向导，确认中文界面正常。

做法：装到一个临时目录（用 /DIR= 指定，不弹管理员），但**不静默** ——
让它显示向导，然后抓取窗口截图。
注意：这会真的弹窗，脚本跑完要关掉。

用法：python analysis/shot_installer.py
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "output", "Shimeji-Setup-1.0.0.exe")
SHOT = os.path.join(ROOT, "analysis", "_installer_wizard.png")
TESTDIR = os.path.join(ROOT, "analysis", "_wizardtest")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_setup_window() -> int:
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, t, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "TSetup" in cls.value or "安装" in t.value or "Setup" in t.value:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if (r.right - r.left) > 300:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def shot(hwnd: int, path: str) -> bool:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return False
    hdc = user32.GetWindowDC(hwnd)
    gdi = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(gdi, bmp)
    # PW_RENDERFULLCONTENT = 2
    user32.PrintWindow(hwnd, gdi, 2)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bi = BMI()
    bi.biSize = ctypes.sizeof(BMI)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(gdi, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(gdi)
    user32.ReleaseDC(hwnd, hdc)

    try:
        from PIL import Image
    except ImportError:
        # 没有 PIL 就写个极简 BMP（BMP 不用压缩，24 位即可）
        hdr = ctypes.create_string_buffer(54)
        filesize = 54 + ((w * 3 + 3) // 4) * 4 * h
        ctypes.memmove(hdr, b"BM", 2)
        ctypes.memmove(hdr[2:], ctypes.c_uint32(filesize).value.to_bytes(4, "little"), 4)
        ctypes.memmove(hdr[10:], ctypes.c_uint32(54).value.to_bytes(4, "little"), 4)
        ctypes.memmove(hdr[14:], ctypes.c_uint32(40).value.to_bytes(4, "little"), 4)
        ctypes.memmove(hdr[18:], ctypes.c_int32(w).value.to_bytes(4, "little"), 4)
        ctypes.memmove(hdr[22:], ctypes.c_int32(h).value.to_bytes(4, "little"), 4)
        ctypes.memmove(hdr[26:], ctypes.c_uint16(1).value.to_bytes(2, "little"), 2)
        ctypes.memmove(hdr[28:], ctypes.c_uint16(24).value.to_bytes(2, "little"), 2)
        row = (w * 3 + 3) // 4 * 4
        with open(path, "wb") as f:
            f.write(hdr)
            for y in range(h - 1, -1, -1):
                line = bytearray()
                for x in range(w):
                    o = (y * w + x) * 4
                    b, g, r = buf[o], buf[o + 1], buf[o + 2]
                    line += bytes((r, g, b))
                line += b"\x00" * (row - len(line))
                f.write(line)
        return True
    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    return True


def main() -> int:
    if not os.path.exists(SETUP):
        print("[FAIL] 安装包不存在", flush=True)
        return 1
    print(f"[setup] {SETUP}", flush=True)
    proc = subprocess.Popen([SETUP, f"/DIR={TESTDIR}"])
    print(f"[pid] {proc.pid}", flush=True)

    hwnd = 0
    for _ in range(30):
        time.sleep(1.0)
        hwnd = find_setup_window()
        if hwnd:
            break
    if not hwnd:
        print("[FAIL] 没找到安装向导窗口（可能弹了 UAC？）", flush=True)
        proc.kill()
        return 2

    t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, t, 512)
    print(f"[window] hwnd={hwnd}  标题={t.value!r}", flush=True)
    time.sleep(1.0)
    for step in range(int(os.environ.get("SHOT_STEPS", "0"))):
        # 点「下一步」/「是」翻页
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        user32.keybd_event(0x0D, 0, 0, 0)  # VK_RETURN
        user32.keybd_event(0x0D, 0, 2, 0)
        time.sleep(1.2)
        p2 = SHOT.replace(".png", f"_s{step+1}.png")
        if shot(hwnd, p2):
            print(f"[shot] {p2}  ({os.path.getsize(p2)} B)", flush=True)
    if shot(hwnd, SHOT):
        print(f"[shot] {SHOT}  ({os.path.getsize(SHOT)} B)", flush=True)
    else:
        print("[shot] 截图失败", flush=True)

    # 关掉向导（发 WM_CLOSE）
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    time.sleep(2.0)
    if proc.poll() is None:
        proc.kill()
    print("[cleanup] 向导已关闭（未实际安装）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
