# -*- coding: utf-8 -*-
"""
渲染对比 / Render comparison
==============================================================================
逐个角色加载，强制显示 shime1.png，把宠物窗口 grab 出来，统计不透明像素，
并保存对比图。定位「窗口存在但画面为空」的角色。
Loads each character, forces shime1.png, grabs the mascot widget, counts
non-transparent pixels and saves a comparison image.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setQuitOnLastWindowClosed(False)

from shimeji.engine.manager import Manager, list_characters  # noqa: E402
from shimeji.i18n import get_i18n  # noqa: E402
from shimeji.settings import Settings  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def p(*a):
    print(*a, flush=True)


s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
s.set("initial_count", 1)
get_i18n().set_language("zh_CN")
m = Manager(app, s)
chars = list_characters(s)
p("characters =", [c[0] for c in chars])

from PySide6.QtGui import QImage  # noqa: E402

for label, path in chars:
    s.set("character", label)
    m.reload()
    mm = m.summon()
    if mm is None:
        p("%-14s summon failed" % label)
        continue
    mm.set_image("shime1.png")
    app.processEvents()
    pm = mm.grab()
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    opaque = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if ((img.pixel(x, y) >> 24) & 0xFF) > 16:
                opaque += 1
    src = m.images.get("shime1.png")
    src_opaque = 0
    if src is not None:
        si = src.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(si.height()):
            for x in range(si.width()):
                if ((si.pixel(x, y) >> 24) & 0xFF) > 16:
                    src_opaque += 1
    p("%-14s grab=%dx%d opaque=%-6d | src=%s opaque=%-6d | mask_empty=%s | img=%s"
      % (label, pm.width(), pm.height(), opaque,
         (src.width(), src.height()) if src else None, src_opaque,
         mm.mask().isEmpty(), mm.image_name))
    pm.save(os.path.join(HERE, "render_%s.png" % label))
    m.dismiss(mm)

m.quit()