# -*- coding: utf-8 -*-
"""验证 `engine/mascot.py`：贴图镜像、朝向与锚点补偿。

⭐ 为什么这个模块要有测试：1.1.2 修了「爬墙时贴图方向翻错」那个 bug
（爬墙动作只有 `目的地Y`、没有 `目的地X`，方向一路沿用爬前的值）。
**但这个模块当时没有任何测试守着** —— 也就是说同一个方向的错误随时可能
再犯，而且没人会发现。

本文件盯住三件事：
1. **镜像真的翻转了像素**（不是只改了个布尔值）
2. **切换朝向会清缓存**（否则贴图不更新 —— 症状是「宠物转身了但还是旧朝向」）
3. **锚点补偿在镜像时方向相反**（`reposition()` 里 `bx` 的两分支）

用法：python analysis/verify_mascot.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Area, Environment  # noqa: E402
from shimeji.engine.mascot import Mascot  # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(cond: bool, msg: str, detail: str = ""):
    global PASSES
    print(("  [ok]   " if cond else "  [FAIL] ") + msg
          + ("  (%s)" % detail if detail else ""), flush=True)
    if cond:
        PASSES += 1
    else:
        FAILS.append(msg)


def section(t):
    print("\n--- %s ---" % t, flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from shimeji.engine.manager import Manager
    from shimeji.settings import Settings

    tmp = tempfile.mkdtemp(prefix="utopet_mascot_")
    st = Settings(os.path.join(tmp, "settings.json"))
    st.set("restore_session", False)
    st.set("initial_count", 1)
    st.set("taskbar_panel", False)
    mgr = Manager(app, st)
    app.processEvents()

    mascot = mgr.mascots[0]
    mascot.set_image("shime1.png")
    app.processEvents()

    # ==============================================================
    section("1. 镜像真的翻转了像素")
    plain = mascot._pixmap("shime1.png", False)
    mirrored = mascot._pixmap("shime1.png", True)
    check(plain is not None and mirrored is not None,
          "两种朝向都能拿到位图")
    check(plain.width() == mirrored.width()
          and plain.height() == mirrored.height(),
          "镜像前后尺寸相同",
          "%dx%d vs %dx%d" % (plain.width(), plain.height(),
                              mirrored.width(), mirrored.height()))

    # 逐行比较：镜像位图的第 x 列应当等于原图第 (w-1-x) 列
    a = plain.toImage().convertToFormat(QImage.Format_ARGB32)
    b = mirrored.toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = a.width(), a.height()
    same_as_original = True
    mirrored_ok = True
    for y in range(0, h, max(1, h // 12)):
        for x in range(0, w, max(1, w // 12)):
            if a.pixel(x, y) != b.pixel(x, y):
                same_as_original = False
            if a.pixel(x, y) != b.pixel(w - 1 - x, y):
                mirrored_ok = False
    check(not same_as_original, "镜像后的像素确实不同（不是原图）")
    check(mirrored_ok,
          "镜像是**水平翻转**：第 x 列 == 原图第 (w-1-x) 列")

    # ==============================================================
    section("2. 切换朝向会清缓存并重新贴图")
    mascot.look_right = False
    mascot.set_image("shime1.png")
    app.processEvents()
    before = mascot._pixmap("shime1.png", mascot.look_right)
    mascot.set_look_right(True)
    app.processEvents()
    check(mascot.look_right is True, "set_look_right(True) 生效")
    after = mascot._pixmap("shime1.png", mascot.look_right)
    check(after is not None, "切换后仍能拿到位图（缓存没被清坏）")
    # 朝右时应该拿到「镜像」那一份
    # ⚠️ 注意这条**不能**当成「缓存清了」的证据：`_pixmap` 的缓存 key 是
    # `(name, mirrored, scale)`，**带 mirrored** —— 所以 mirrored 一变就是
    # 另一个 key，自然拿到不同位图，跟清没清缓存无关。
    # 变异测试实测：把 `set_look_right` 里的 `_pix_cache.clear()` 删掉，
    # 这条断言**照样通过** —— 它是假绿。真正会用到「同 key、内容变了」的是
    # `set_scale`，所以缓存这件事放到第 6 节去测。
    # This cannot prove the cache was cleared: the cache key includes
    # `mirrored`, so a different key gives a different pixmap anyway.
    check(after.toImage() != before.toImage(),
          "切换朝向后拿到的是镜像那一份位图")

    # 同值调用应该是空操作（不该白清缓存）
    mascot.set_look_right(True)
    app.processEvents()
    check(mascot.look_right is True, "重复设置同值不改变状态")

    # ==============================================================
    section("3. 锚点补偿：镜像时基准点方向相反")
    # `reposition()`：bx = (iw - base.x) if look_right else base.x
    # 也就是说朝右时锚点在图内的基准 x 是「从右往左」量的 —— 镜像后
    # 图内的左右也翻了，两者必须**抵消**，宠物才会站在同一个锚点上。
    # 这正是镜像方向算错的根源，也是 1.1.2 修的那个 bug 的底层机制。
    mascot.look_right = False
    mascot.base = type(mascot.base)(40, 100)
    mascot.anchor = type(mascot.anchor)(500, 300)
    mascot.reposition()
    app.processEvents()
    left_when_facing_left = mascot.x()

    mascot.look_right = True
    mascot.reposition()
    app.processEvents()
    left_when_facing_right = mascot.x()

    iw = mascot.images.get("shime1.png").width()
    # 朝左：left = anchor.x - base.x * scale
    # 朝右：left = anchor.x - (iw - base.x) * scale
    expect_l = 500 - 40 * mascot.scale
    expect_r = 500 - (iw - 40) * mascot.scale
    check(abs(left_when_facing_left - expect_l) <= 1,
          "朝左时锚点基准取 base.x",
          "left=%d expect=%.0f" % (left_when_facing_left, expect_l))
    check(abs(left_when_facing_right - expect_r) <= 1,
          "朝右时锚点基准取 (图宽 - base.x) —— 与镜像方向相反",
          "left=%d expect=%.0f" % (left_when_facing_right, expect_r))
    check(left_when_facing_left != left_when_facing_right,
          "两种朝向的窗口位置不同（镜像确实改变了锚点补偿）",
          "%d vs %d" % (left_when_facing_left, left_when_facing_right))

    # ==============================================================
    section("4. 透明处不响应点击")
    mascot.look_right = False
    mascot.set_image("shime1.png")
    app.processEvents()
    from PySide6.QtCore import QPoint
    img = mascot._pixmap("shime1.png", False).toImage().convertToFormat(
        QImage.Format_ARGB32)
    # 找一个全透明的点
    transparent = None
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            if ((img.pixel(x, y) >> 24) & 0xFF) < 8:
                transparent = QPoint(x, y)
                break
        if transparent:
            break
    if transparent is None:
        check(True, "这张图没有透明像素（跳过透明点击检查）")
    else:
        check(mascot._hit(transparent) is False,
              "透明像素处不响应点击",
              "pos=(%d,%d)" % (transparent.x(), transparent.y()))
    # 越界坐标
    check(mascot._hit(QPoint(-5, -5)) is False, "越界坐标不响应点击")

    # ==============================================================
    section("5. 表达式命名空间")
    ns = mascot.namespace()
    check("mascot" in ns and "footX" in ns and "footY" in ns,
          "命名空间含 mascot / footX / footY", str(sorted(ns.keys())))
    check(ns["footX"] == mascot.anchor.x and ns["footY"] == mascot.anchor.y,
          "footX/footY 就是当前锚点")
    ref = ns["mascot"]
    check(ref.look_right == mascot.look_right,
          "mascot.lookRight 与实际朝向一致")
    check(abs(ref.anchor.x - mascot.anchor.x) < 0.001,
          "mascot.anchor 与实际锚点一致")

    # ==============================================================
    section("6. 缩放 / 透明度 / 鼠标穿透")
    # ⭐ 「缓存必须被清」这件事的**可观测后果是内存，不是正确性** ——
    # `_pixmap` 的 key 是 `(name, mirrored, scale)`，scale 变了 key 就变了，
    # 所以旧位图**不会被误用**。变异测试实测：删掉 `set_scale` 里的
    # `_pix_cache.clear()`，「位图尺寸」那条断言照样通过（假绿）。
    # 真正变差的是**缓存条目堆积** —— 每个 scale 各留一份位图。
    # 所以这里断言**缓存条目数**，那才是能被观测到的差别。
    # The observable consequence of not clearing the cache is *memory*, not
    # correctness: the key includes the scale, so a stale entry is never
    # used.  A size assertion cannot tell the difference (verified by
    # mutation) — the entry count can.
    _before_entries = len(mascot._pix_cache)
    mascot.set_scale(2.0)
    app.processEvents()
    check(mascot.scale == 2.0, "set_scale 生效")
    pix2 = mascot._pixmap("shime1.png", mascot.look_right)
    check(pix2.width() == plain.width() * 2,
          "改缩放后位图按新尺寸重算",
          "%d vs %d" % (pix2.width(), plain.width()))
    # 遮罩也必须跟着重算（否则点击区域还是旧的）
    reg = mascot._region_for(pix2)
    check(reg.boundingRect().width() == pix2.width(),
          "遮罩也跟着新尺寸重算",
          "mask=%d pixmap=%d" % (reg.boundingRect().width(), pix2.width()))
    # ⭐ 缓存条目数：清缓存后不该把旧 scale 的那份留着
    _scaled_entries = len(mascot._pix_cache)
    check(_scaled_entries <= _before_entries,
          "改缩放后缓存条目没堆积（旧 scale 的位图被清掉了）",
          "%d -> %d" % (_before_entries, _scaled_entries))
    mascot.set_scale(1.0)

    mascot.set_opacity(0.5)
    app.processEvents()
    # 8 位 alpha 量化：读回 0.5 会是 127/255 = 0.498...
    check(abs(mascot.windowOpacity() - 0.5) < 0.01,
          "set_opacity 生效（8 位量化，容差 0.01）",
          "%.6f" % mascot.windowOpacity())

    mascot.set_click_through(True)
    app.processEvents()
    check(mascot.click_through is True, "鼠标穿透可开")
    mascot.set_click_through(False)
    app.processEvents()
    check(mascot.click_through is False, "鼠标穿透可关")

    mgr.quit()
    print()
    print("=" * 60, flush=True)
    if FAILS:
        print("%d FAILED / %d passed" % (len(FAILS), PASSES), flush=True)
        for f in FAILS:
            print("  x %s" % f, flush=True)
        sys.stdout.flush()
        os._exit(1)
    print("ALL PASS —— %d 项检查通过" % PASSES, flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
