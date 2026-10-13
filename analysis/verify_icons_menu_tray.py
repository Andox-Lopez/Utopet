# -*- coding: utf-8 -*-
"""
验证本轮三项改动 / Verify this round's three changes
==============================================================================
1. 图标分工 —— `logo.ico` 只服务托盘，`logo.png`/`app.ico` 服务软件本体，
   且 20px 以下去圆角、20px 及以上保留圆角。
2. 菜单统一 —— 托盘右键与宠物右键是**同一份**菜单，条目与顺序完全一致。
3. 无迷你条 —— 面板关闭后只剩托盘常驻，`Manager` 上不再有 `mini` 属性。

跑法 / Run:  python analysis\verify_icons_menu_tray.py
"""
from __future__ import annotations

import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ASSETS = os.path.join(ROOT, "shimeji", "assets")
TRAY_ICO = os.path.join(ASSETS, "logo.ico")
APP_ICO = os.path.join(ASSETS, "app.ico")
LOGO_PNG = os.path.join(ASSETS, "logo.png")

_fails: list[str] = []


def check(ok: bool, msg: str, detail: str = "") -> bool:
    tag = "[ok]  " if ok else "[FAIL]"
    print(f"  {tag} {msg}" + (f"  ({detail})" if detail else ""))
    if not ok:
        _fails.append(msg)
    return ok


# ----------------------------------------------------------------------
def ico_frames(path: str) -> dict[int, "Image.Image"]:
    """从 ico 容器里切出每一帧 / Slice every frame out of an ICO container."""
    from PIL import Image
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"\x00\x00\x01\x00":
        return {}
    out: dict[int, "Image.Image"] = {}
    for i in range(struct.unpack("<H", data[4:6])[0]):
        off = 6 + i * 16
        w = data[off] or 256
        size, start = struct.unpack("<II", data[off + 8:off + 16])
        blob = data[start:start + size]
        if blob[:8] != b"\x89PNG\r\n\x1a\n":
            continue
        out[w] = Image.open(io.BytesIO(blob)).convert("RGBA")
    return out


def corner_is_filled(im: "Image.Image") -> bool:
    """四角是否都不透明 / Are all four corners opaque?"""
    w, h = im.size
    px = im.load()
    return all(px[x, y][3] > 0 for x, y in
               ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))


def corner_alpha(im: "Image.Image") -> int:
    """
    左上角的 alpha 值（0=全透明，255=全不透明）/ Top-left alpha.

    比「数第一行有几个全透明像素」可靠得多。主图 512px 下圆角半径只有约 40px，
    缩到 20~24px 就只剩 1.5~1.8px，抗锯齿会让边缘留下 alpha=2~3 的极淡痕迹 ——
    按「必须恰好等于 0」判定会把这些帧全判成方角。改成看 alpha 本身即可。
    Measuring alpha directly is far more robust than counting exactly-transparent
    pixels: at 20..24px the corner radius is down to 1.5..1.8px, so
    antialiasing leaves a faint alpha of 2..3, and an "== 0" test would wrongly
    call those frames square.
    """
    return im.load()[0, 0][3]


# ----------------------------------------------------------------------
def test_icons() -> None:
    print("--- 1. 图标分工 / icon split ---")
    check(os.path.exists(TRAY_ICO), "logo.ico 存在（托盘）")
    check(os.path.exists(APP_ICO), "app.ico 存在（exe / 安装包）")
    check(os.path.exists(LOGO_PNG), "logo.png 存在（主图）")

    tray = ico_frames(TRAY_ICO)
    app = ico_frames(APP_ICO)
    check(len(tray) >= 6, "logo.ico 是多尺寸 ico", f"{sorted(tray)}")
    check(len(app) >= 6, "app.ico 是多尺寸 ico", f"{sorted(app)}")

    # exe 图标绝不能有 >=128 的帧：PyInstaller 用有符号 char 读 bWidth，
    # 128(0x80) 会读成 -128，资源管理器解析整个图标组失败，exe 图标变形。
    # 详见 tools/make_icons.py 的 _assert_pyinstaller_safe()。
    big = [s for s in app if s > 127]
    check(not big, "app.ico 无 >=128 的帧（否则 PyInstaller 读出负宽度、exe 图标变形）",
          f"过大帧={big or '无'}")
    for s in (s for s in sorted(app) if s > 16):
        check(corner_alpha(app[s]) < 128, f"app.ico {s}px 保留圆角",
              f"alpha={corner_alpha(app[s])}")
    check(20 in tray and 16 in tray, "logo.ico 覆盖托盘常用尺寸")

    # 关键规则：只有 16px 去圆角，其余保留。
    # 主图圆角半径 ≈ 40px/512，缩到 20px 只剩 1.5px，本来就近乎不可见；
    # 真正需要去圆角的是 16px 那一档（托盘 100% 缩放的实际尺寸）。
    # The rule: only the 16px frame is squared off.  The master's corner radius
    # is ~40px of 512, so by 20px it is down to ~1.5px and barely visible anyway;
    # 16px is the size the tray actually uses at 100% scaling.
    if 16 in tray:
        check(corner_alpha(tray[16]) == 255,
              "托盘 16px 已去圆角（角落全不透明 alpha=255）",
              f"alpha={corner_alpha(tray[16])}")
    for s in (s for s in sorted(tray) if s > 16):
        check(corner_alpha(tray[s]) < 128,
              f"托盘 {s}px 保留圆角（角落透明）",
              f"alpha={corner_alpha(tray[s])}")

    from PySide6.QtWidgets import QApplication
    app_q = QApplication.instance() or QApplication([])
    from shimeji.icons import app_icon, tray_icon
    a, t = app_icon(), tray_icon()
    check(not a.isNull() and not t.isNull(), "两个 QIcon 都能解码")
    af = sorted({s.width() for s in a.availableSizes()})
    tf = sorted({s.width() for s in t.availableSizes()})
    check(len(af) > 1, "app_icon 是多尺寸", f"{af}")
    check(len(tf) > 1, "tray_icon 是多尺寸", f"{tf}")
    check(tf != af, "托盘图标与软件图标是**不同**的两份", f"tray={tf} app={af}")
    for s in (16, 20, 24, 32):
        check(not t.pixmap(s, s).isNull(), f"tray_icon 在 {s}px 取到像素")


def test_menu() -> None:
    print("--- 2. 托盘 / 宠物右键菜单统一 / one shared menu ---")
    from PySide6.QtWidgets import QApplication, QMenu
    app_q = QApplication.instance() or QApplication([])
    from shimeji.engine.manager import Manager

    class FakeMascot:
        pass

    m = Manager.__new__(Manager)          # 只借方法，不跑 __init__
    m.settings = type("S", (), {"get": staticmethod(lambda k, d=None: 5)})()
    m.actions = {}
    m.mascots = []
    m.summon = m.summon_many = m.dismiss = m.dismiss_all = lambda *a, **k: None
    m.gather_all = m.toggle_hidden = m.open_settings = m.quit = lambda *a, **k: None
    m.open_taskbar_panel = lambda *a, **k: None

    tray_menu = m._build_main_menu()
    mascot_menu = m._build_main_menu(FakeMascot())

    def labels(menu):
        return [a.text() for a in menu.actions()]

    lt, lm = labels(tray_menu), labels(mascot_menu)
    check(isinstance(tray_menu, QMenu) and isinstance(mascot_menu, QMenu), "两份都是 QMenu")
    check(len(lt) == len(lm) >= 10, "条目数量与顺序一致",
          f"{len(lt)} vs {len(lm)} 项")

    # 唯一允许的差异是「解散一只 / 解散这只」—— 托盘没有「这一只」的具体对象，
    # 宠物右键才有。指代不同所以文案必须不同，其余必须逐字一致。
    # The only permitted difference is Dismiss-one: from the tray there is no
    # specific pet, so "a pet" is correct; from a mascot "this pet" is.
    diff = [(i, a, b) for i, (a, b) in enumerate(zip(lt, lm)) if a != b]
    check(len(diff) == 1 and diff[0][0] == 4,
          "仅「解散一只/这只」一处文案不同（托盘无具体对象）",
          "" if len(diff) == 1 and diff[0][0] == 4
          else f"差异处: {[(i, a, b) for i, a, b in diff]}")
    if diff:
        check("只" in diff[0][1] and "只" in diff[0][2],
              "该处两项都以「只」结尾，指代同一动作",
              f"{diff[0][1]!r} / {diff[0][2]!r}")

    # 菜单里不该再有托盘专属 / 宠物专属的分裂项：两边都来自同一个 builder
    check(lt[2] == lm[2] and lt[0] == lm[0],
          "两边同源（召唤 / 聚到鼠标旁 等公共项逐字相同）")


def test_no_mini() -> None:
    print("--- 3. 迷你条已移除 / slim bar gone ---")
    from shimeji.gui.taskbar_panel import TaskbarPanel
    src = open(TaskbarPanel.__module__.replace(".", "/") + ".py", encoding="utf-8").read() \
        if False else None
    import inspect
    panel_src = inspect.getsource(TaskbarPanel)
    for token in ("self.mini", "_collapse", "_any_visible", "close_mini",
                  "_place_mini", "_expand"):
        check(token not in panel_src, f"TaskbarPanel 里没有 {token}")

    import shimeji.engine.manager as M
    mgr_src = inspect.getsource(M.Manager)
    for token in (".mini.", "_any_visible"):
        check(token not in mgr_src, f"Manager 里没有 {token}")

    from PySide6.QtWidgets import QApplication
    app_q = QApplication.instance() or QApplication([])
    panel = TaskbarPanel.__new__(TaskbarPanel)
    check(not hasattr(panel, "mini"), "实例上没有 mini 属性")


def test_version() -> None:
    print("--- 4. 版本号 / version ---")
    from shimeji import __version__
    check(__version__ == "1.0.1", "shimeji.__version__", __version__)
    iss = open(os.path.join(ROOT, "installer", "Shimeji.iss"), encoding="utf-8").read()
    check('#define AppVersion "1.0.1"' in iss, "iss 的 AppVersion 是 1.0.1")
    check("app.ico" in iss, "iss 的 SetupIconFile 指向 app.ico")
    spec = open(os.path.join(ROOT, "shimeji.spec"), encoding="utf-8").read()
    check('os.path.join(ASSETS, "app.ico")' in spec, "spec 的 exe 图标指向 app.ico")


def main() -> int:
    for fn in (test_icons, test_menu, test_no_mini, test_version):
        fn()
    print()
    if _fails:
        print(f"FAIL —— {len(_fails)} 项未通过：")
        for f in _fails:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
