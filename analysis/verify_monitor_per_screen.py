# -*- coding: utf-8 -*-
"""验证 F5 P1（每屏独立数量/缩放）：按屏分配 + 每屏独立配置。

## 测什么

1. Environment 层：monitor_max_count / monitor_scale / apply_monitor_settings
2. Manager 层：按屏分配（用 mock 多屏模拟）

## 单屏策略

这台机器只有 1 块屏。多屏逻辑通过**临时改 monitor_info** 模拟两块屏来测。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from shimeji.engine.environment import Pt, Area  # noqa: E402
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

    d = tempfile.mkdtemp(prefix="utopet_mon_p1_")
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
        device = e.monitor_info[0]["device"]

        # ==================================================================
        section("1. Environment：monitor_max_count / monitor_scale")
        # 默认继承全局
        check(e.monitor_max_count(device, 50) == 50,
              "未配置时继承全局 max")
        check(abs(e.monitor_scale(device, 1.0) - 1.0) < 1e-9,
              "未配置时继承全局 scale")

        # apply_monitor_settings
        e.apply_monitor_settings({
            device: {"max_count": 3, "scale": 1.5},
        })
        check(e.monitor_max_count(device, 50) == 3,
              "配置后用屏上 max_count")
        check(abs(e.monitor_scale(device, 1.0) - 1.5) < 1e-9,
              "配置后用屏上 scale")

        # 部分配置 -> 继承全局
        e.apply_monitor_settings({
            device: {"max_count": 5},
        })
        check(e.monitor_max_count(device, 50) == 5,
              "只配 max_count 时 max_count 生效")
        check(abs(e.monitor_scale(device, 2.0) - 2.0) < 1e-9,
              "未配 scale 时继承全局")

        # None 配置 -> 继承
        e.apply_monitor_settings(None)
        check(e.monitor_max_count(device, 50) == 50,
              "None 配置后恢复继承")

        # ==================================================================
        section("2. 模拟两屏：按屏分配")
        # 临时改 monitor_info 模拟两块屏
        original = list(e.monitor_info)
        fake = [
            {"device": "D1", "monitor": (0, 0, 1920, 1080),
             "work": (0, 0, 1920, 1032), "primary": True,
             "allowed": True, "max_count": 2, "scale": 1.0},
            {"device": "D2", "monitor": (1920, 0, 3840, 1080),
             "work": (1920, 0, 3840, 1032), "primary": False,
             "allowed": True, "max_count": 3, "scale": 1.5},
        ]
        e.monitor_info[:] = fake
        # 同步 monitors 列表（summon_many 用 monitor_info，不直接用 monitors）
        e.monitors = [
            (Area(f["monitor"][0], f["monitor"][1], f["monitor"][2], f["monitor"][3], True),
             Area(f["work"][0], f["work"][1], f["work"][2], f["work"][3], True))
            for f in fake
        ]

        # 设全局 max 为 100（避免干扰）
        s.set("max_count", 100)
        s.set("monitor_settings", {
            "D1": {"max_count": 2, "scale": 1.0},
            "D2": {"max_count": 3, "scale": 1.5},
        })
        mgr._apply_env_options()

        def pets_on(dev):
            n = 0
            for m in mgr.mascots:
                info = e.monitor_at(m.anchor.x, m.anchor.y)
                if info is not None and info["device"] == dev:
                    n += 1
            return n

        # 召唤 5 只：D1 满 2 只，D2 满 3 只
        mgr.dismiss_all()
        added = mgr.summon_many(5)
        check(added == 5, "召唤 5 只成功")
        check(pets_on("D1") == 2, "D1 上 2 只（max=2）")
        check(pets_on("D2") == 3, "D2 上 3 只（max=3）")

        # 再召 1 只 -> D1/D2 都满了，应该停止召唤（每屏上限是真的上限）
        added2 = mgr.summon_many(1)
        check(added2 == 0, "满员后再召 1 只被拒绝（不超上限）")

        # 按屏缩放：D2 上的宠物 scale 应该是 1.5
        d2_pets = [m for m in mgr.mascots
                   if e.monitor_at(m.anchor.x, m.anchor.y) is not None
                   and e.monitor_at(m.anchor.x, m.anchor.y)["device"] == "D2"]
        if d2_pets:
            check(abs(d2_pets[0].scale - 1.5) < 1e-9,
                  "D2 上宠物 scale=1.5", "scale=%s" % d2_pets[0].scale)

        # D1 上的宠物 scale = 1.0
        d1_pets = [m for m in mgr.mascots
                   if e.monitor_at(m.anchor.x, m.anchor.y) is not None
                   and e.monitor_at(m.anchor.x, m.anchor.y)["device"] == "D1"]
        if d1_pets:
            check(abs(d1_pets[0].scale - 1.0) < 1e-9,
                  "D1 上宠物 scale=1.0", "scale=%s" % d1_pets[0].scale)

        # ==================================================================
        section("3. 禁屏 + 满屏 组合")
        mgr.dismiss_all()
        # D2 禁用
        e.monitor_info[1]["allowed"] = False
        added3 = mgr.summon_many(3)
        check(added3 == 2,
              "D2 禁了（max=2），最多召 2 只")
        check(pets_on("D1") == 2, "全在 D1 上")
        check(pets_on("D2") == 0, "D2 上 0 只")

        # ⭐ 核心：手动把一只宠物放进禁屏 D2，下一次 tick 必须拉回 D1。
        # 这条断言能抓到历史 F5 的真实潜伏 bug：`m._win` 不存在，
        # move_window_at 返回 tuple 却被当 Pt 访问，导致回调异常被 Manager.tick
        # 吞掉，用户看到宠物仍留在禁屏，日志里有错误。
        mover = mgr.mascots[0]
        mover.anchor = Pt(2100, 800)   # D2 区域
        mover.reposition()
        before = e.monitor_at(mover.anchor.x, mover.anchor.y)
        check(before is not None and before["device"] == "D2",
              "宠物已在禁屏 D2", str(mover.anchor))
        mgr._clamp_to_allowed(mover)
        after = e.monitor_at(mover.anchor.x, mover.anchor.y)
        check(after is not None and after["device"] == "D1",
              "被直接拉回允许屏 D1（不依赖行为 tick）", str(mover.anchor))

        # 允许屏之间自由跨 + 自动切换目标屏 scale
        e.monitor_info[1]["allowed"] = True
        mover.anchor = Pt(2100, 800)   # D2 允许屏
        mover.reposition()
        mgr._clamp_to_allowed(mover)
        check(abs(mover.scale - 1.5) < 1e-9,
              "跨到 D2 后自动切换 scale=1.5", "scale=%s" % mover.scale)
        mover.anchor = Pt(500, 800)    # D1 允许屏
        mover.reposition()
        mgr._clamp_to_allowed(mover)
        check(abs(mover.scale - 1.0) < 1e-9,
              "跨回 D1 后自动恢复 scale=1.0", "scale=%s" % mover.scale)

        # ⭐ 防回归：同一屏上重复检查不能每帧覆盖手动设置的 scale。
        # 否则 verify_mascot 的「set_scale(2.0) 生效」会在 timer 跑时失败。
        mover.set_scale(2.0)
        mgr._clamp_to_allowed(mover)
        mgr._clamp_to_allowed(mover)
        check(abs(mover.scale - 2.0) < 1e-9,
              "同一屏上手动 set_scale 不被每帧重置", "scale=%s" % mover.scale)

        # ==================================================================
        section("4. 恢复原始 monitor_info")
        e.monitor_info[:] = original
        e.monitors = [
            (Area(f["monitor"][0], f["monitor"][1], f["monitor"][2], f["monitor"][3], True),
             Area(f["work"][0], f["work"][1], f["work"][2], f["work"][3], True))
            for f in original
        ]
        mgr.dismiss_all()

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
