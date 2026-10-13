# -*- coding: utf-8 -*-
"""
引擎回归 / Engine regression
==============================================================================
把配置里的每一个动作都实例化并推进 120 帧，统计失败数。
Instantiate every configured action and tick it 120 frames, counting failures.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager  # noqa: E402
from shimeji.engine.runtime import create_action  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 1)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
mascot = m.mascots[0]

total = failed = 0
for name in list(m.actions.order):
    total += 1
    try:
        mascot.forced_behavior = None
        act = create_action(mascot, name, {})
        if act is None:
            print("SKIP", name, flush=True)
            failed += 1
            continue
        for _ in range(120):
            if not act.tick():
                break
        mascot.action = None
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print("FAIL", name, "->", type(exc).__name__, exc, flush=True)

# 6000 帧长测 / long soak: let the brain drive freely
soak_errors = 0
for _ in range(6000):
    m.tick()
m.quit()

print("actions=%d failed=%d | soak 6000 frames done" % (total, failed), flush=True)
sys.exit(1 if failed else 0)
