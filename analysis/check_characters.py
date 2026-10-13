# -*- coding: utf-8 -*-
"""
角色素材一致性检查 / Character asset consistency check
==============================================================================
对每个角色：比较 conf/Actions.xml 里引用的图片名与 img/ 里实际存在的文件，
并逐帧检查「引用得到 + 有非透明像素」，定位「窗口在但画不出东西」的角色。
Compares image names referenced by Actions.xml with the files actually present,
then verifies each referenced frame has visible (non-transparent) pixels.
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = os.path.join(ROOT, "characters")

for d in sorted(os.listdir(CH)):
    p = os.path.join(CH, d)
    if not os.path.isdir(p):
        continue
    img_dir = p if os.path.exists(os.path.join(p, "shime1.png")) else os.path.join(p, "img")
    conf_dir = os.path.join(p, "conf")
    xmls = []
    for root, _dirs, files in os.walk(p):
        for f in files:
            if f.lower().endswith(".xml"):
                xmls.append(os.path.join(root, f))
    refs = Counter()
    for x in xmls:
        with open(x, encoding="utf-8", errors="replace") as fh:
            for m in re.finditer(r'画像="([^"]+)"', fh.read()):
                refs[m.group(1).lstrip("/\\").lower()] += 1
    have = {f.lower() for f in os.listdir(img_dir) if f.lower().endswith(".png")}
    missing = sorted(r for r in refs if r not in have)
    blank = []
    for r in sorted(refs):
        fp = os.path.join(img_dir, r)
        if not os.path.exists(fp):
            continue
        im = Image.open(fp).convert("RGBA")
        bb = im.split()[-1].getbbox()
        if bb is None or (bb[2] - bb[0] <= 2 and bb[3] - bb[1] <= 2):
            blank.append((r, im.size, bb))
    print("=== %s ===" % d)
    print("   img=%s  xml=%d  refs=%d  missing=%d"
          % (os.path.relpath(img_dir, p), len(xmls), len(refs), len(missing)))
    if missing:
        print("   MISSING:", ", ".join(missing[:12]), "..." if len(missing) > 12 else "")
    if blank:
        print("   EMPTY/1px frames:", blank[:6])
    if not missing and not blank:
        print("   OK: 所有引用都存在且有内容 / every referenced frame exists and has content")