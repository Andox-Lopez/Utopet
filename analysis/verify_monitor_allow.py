# -*- coding: utf-8 -*-
"""验证 F5（多显示器独立配置）：允许/禁止宠物去某块屏。

## 最小切片

只做「允许/禁止去某块屏」+ 设备名持久化 + 落点夹回。
每屏数量/缩放留到后续（那需要分配器，复杂度再上一个量级）。

## 单屏测试策略

这台机器只有 1 块屏，所以：
- 设置匹配设备名 -> allowed=True
- 设置不匹配设备名 -> allowed=False（宠物没地方去，不动）
- 设置空集合 -> 全部 allowed（默认行为）
- 召唤 -> 锚点始终在允许屏内（单屏下 trivial，但逻辑走通）

多屏场景（拔插后配置残留、跨屏移动拉回）在真实硬件上验证。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Pt  # noqa: E402
from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

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

    d = tempfile.mkdtemp(prefix="utopet_mon_")
    try:
        s = Settings(os.path.join(d, "settings.json"))
        s.set("character", "Miku")
        s.set("taskbar_panel", False)
        s.set("restore_session", False)
        s.set("initial_count", 1)
        mgr = Manager(app, s)
        mgr.timer.stop()
        mgr.dismiss_all()
        e = mgr.shared_env

        # 拿到真实设备名（这台机器只有 1 块屏）
        device = e.monitor_info[0]["device"]
        check(len(device) > 0, "设备名非空", repr(device))
        check(e.monitor_info[0]["primary"], "主屏标记正确")
        print("      设备名: %s" % device, flush=True)

        # ==================================================================
        section("1. 默认（空集合）= 全部允许")
        check(e.monitor_info[0]["allowed"], "默认 allowed=True")

        # ==================================================================
        section("2. 设置匹配设备名 -> allowed=True")
        s.set("monitor_allow", [device])
        mgr._apply_env_options()
        check(e.monitor_info[0]["allowed"],
              "匹配设备名后 allowed=True")

        # ==================================================================
        section("3. 设置不匹配设备名 -> allowed=False")
        s.set("monitor_allow", ["\\\\.\\DISPLAY99"])
        mgr._apply_env_options()
        check(not e.monitor_info[0]["allowed"],
              "不匹配设备名后 allowed=False")

        # ==================================================================
        section("4. 召唤 -> 锚点始终在允许屏内")
        # 即使主屏被禁，单屏下没地方去 -> 锚点仍在屏上
        s.set("monitor_allow", ["\\\\.\\DISPLAY99"])
        mgr._apply_env_options()
        wa = mgr.shared_env.work_area
        m = mgr.summon(Pt(wa.left + 300, wa.bottom))
        check(m is not None, "召唤成功（即使主屏被禁）")
        check(m.anchor.x >= e.monitor_info[0]["monitor"][0]
              and m.anchor.x <= e.monitor_info[0]["monitor"][2],
              "锚点 x 仍在屏上")

        # ==================================================================
        section("5. 设置匹配设备名 -> allowed 恢复")
        s.set("monitor_allow", [device])
        mgr._apply_env_options()
        check(e.monitor_info[0]["allowed"],
              "恢复匹配后 allowed=True")

        # ==================================================================
        section("6. monitor_at 按坐标返回屏幕信息")
        info = e.monitor_at(m.anchor.x, m.anchor.y)
        check(info is not None, "坐标命中屏")
        check(info["device"] == device, "设备名一致")
        info2 = e.monitor_at(-9999, -9999)  # 屏幕外
        check(info2 is None, "屏幕外返回 None")

        # ==================================================================
        section("7. 禁屏上的宠物 tick 时夹回允许屏")
        # 单屏：禁屏后没地方去 -> 夹到自己的 work 区（y 可能变）。
        # 多屏场景下会拉到最近允许屏 —— 这台机器单屏，逻辑走通即可。
        s.set("monitor_allow", ["\\\\.\\DISPLAY99"])
        mgr._apply_env_options()
        mgr.tick()
        check(wa.left <= m.anchor.x <= wa.right,
              "拉回后 x 在屏上",
              "anchor.x=%d" % m.anchor.x)

        # 恢复允许 -> 锚点仍在屏上
        s.set("monitor_allow", [device])
        mgr._apply_env_options()
        mgr.tick()
        check(wa.left <= m.anchor.x <= wa.right,
              "恢复允许后锚点仍在屏上")

        # ==================================================================
        section("8. monitor_info 与 monitors 数量一致")
        check(len(e.monitor_info) == len(e.monitors),
              "monitor_info 与 monitors 数量一致",
              "%d vs %d" % (len(e.monitor_info), len(e.monitors)))

        mgr.quit()
    finally:
        shutil.rmtree(d, ignore_errors=True)

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
