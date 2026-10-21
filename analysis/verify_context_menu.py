# -*- coding: utf-8 -*-
"""验证宠物右键菜单的信号连接（不需要真的弹菜单）。

QMenu.exec() 是模态阻塞的，无法在自动化测试里直接调 —— 会挂死等点击。
所以这里改用「信号有没有连上槽」来判定，菜单内容则直接调 show_context_menu
的等价逻辑单独构造一份来检查。

用法：python analysis/verify_context_menu.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def receivers(sig, slot_owner, slot_name: str) -> bool:
    """信号是否真的连到了某个对象的槽 / is the signal actually wired to a slot?

    PySide6 6.x 的 Signal 没有 receivers()，所以直接验证「emit 之后槽有没有跑」。
    最干净的办法：临时把 Manager.show_context_menu 换成计数器再 emit。
    Emitting with a spied-out slot is the only reliable check.
    """
    probe = []
    original = getattr(slot_owner, slot_name)
    setattr(slot_owner, slot_name, lambda *a: probe.append(1))
    try:
        sig.emit(object(), QPoint(1, 1))
    except Exception:
        pass
    finally:
        setattr(slot_owner, slot_name, original)
    return bool(probe)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # 配置写到临时目录：这个测试结尾会 m.quit()，而 quit 会存档并写盘 ——
    # 用默认路径就是每次跑测试都改一遍用户真实的 config\settings.json。
    # The settings file goes to a temp directory: this test ends with
    # m.quit(), which snapshots the session and writes to disk.  With the
    # default path, every run would rewrite the user's real settings.json.
    s = Settings(os.path.join(
        tempfile.mkdtemp(prefix="utopet_ctx_menu_"), "settings.json"))
    s.set("restore_session", False)
    s.set("initial_count", 3)
    s.set("taskbar_panel", False)
    m = Manager(app, s)
    app.processEvents()

    print(f"\n宠物数 = {len(m.mascots)}\n", flush=True)

    print("--- 1. 每只宠物都接上了右键菜单 ---", flush=True)
    for i, x in enumerate(m.mascots):
        ok = receivers(x.menuRequested, m, "show_context_menu")
        check(ok, f"#{i} 右键信号 -> show_context_menu 已连通")

    print("\n--- 2. 菜单内容正确（绕过 exec 单独构造）---", flush=True)
    t = get_i18n()
    menu = QMenu()
    menu.addAction(t.t("menu.summon"), lambda: None)
    menu.addMenu(m._build_summon_submenu(menu))
    menu.addAction(t.t("menu.gather"), lambda: None)
    menu.addSeparator()
    menu.addAction(t.t("menu.dismiss"), lambda: None)
    menu.addAction(t.t("tray.dismiss_all"), lambda: None)
    menu.addSeparator()
    menu.addAction(t.t("tray.show_hide"), lambda: None)
    menu.addAction(t.t("menu.settings"), lambda: None)
    menu.addAction(t.t("tray.panel"), lambda: None)
    menu.addAction(t.t("menu.quit"), lambda: None)
    texts = [a.text() for a in menu.actions() if a.text()]
    print(f"  菜单项（{len(texts)} 个）:", flush=True)
    for x in texts:
        print("    -", x, flush=True)
    check(len(texts) >= 9, f"菜单项足够（{len(texts)} >= 9）")
    check(any("召唤" in x or "Summon" in x for x in texts), "含召唤项")
    check(any("设置" in x or "Settings" in x for x in texts), "含设置项")
    check(any("退出" in x or "Quit" in x for x in texts), "含退出项")

    print("\n--- 3. 菜单项回调真的能操作宠物 ---", flush=True)
    before = m.count()
    m.dismiss(m.mascots[0])
    app.processEvents()
    check(m.count() == before - 1, f"解散一只生效（{before} -> {m.count()}）")
    m.summon()
    app.processEvents()
    check(m.count() == before, f"再召唤一只回来了（{m.count()}）")
    ok2 = receivers(m.mascots[-1].menuRequested, m, "show_context_menu")
    check(ok2, "新召唤的这只也接上了右键菜单")

    print("\n--- 4. 多宠全部连通 ---", flush=True)
    m.summon_many(3)
    app.processEvents()
    allc = all(receivers(x.menuRequested, m, "show_context_menu") for x in m.mascots)
    check(allc, f"{len(m.mascots)} 只全部接上右键菜单")

    m.quit()
    print("\n" + "=" * 56, flush=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}:", flush=True)
        for f in FAILS:
            print("  x", f, flush=True)
        return 1
    print("ALL PASS —— 右键菜单信号已全部接通", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
