# -*- coding: utf-8 -*-
"""
自定义动作 / Custom actions
==============================================================================
用户自建的动作保存在 `data/custom.xml`，结构与原版配置完全一致（日文标签），
因此既能被本程序直接加载，也能被原版 Shimeji 读取。

User-authored actions are stored in `data/custom.xml`, using exactly the same
schema as the original configuration (Japanese tags), so the file is both
loadable by this app and by the original Shimeji.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import xml.sax.saxutils as su

from .settings import CUSTOM_XML_HEADER

__all__ = ["CustomConfig"]

NS = 'xmlns="http://www.group-finity.com/Mascot"'


class CustomConfig:
    """读写 data/custom.xml / Reads and writes data/custom.xml."""

    def __init__(self, path: str):
        self.path = path
        self.actions: list[dict] = []
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        self.actions = []
        if not os.path.exists(self.path):
            return
        try:
            root = ET.parse(self.path).getroot()
        except ET.ParseError:
            return

        def _tag(e):
            return e.tag.split("}", 1)[-1]

        def _attr(e, name, default=None):
            for k, v in e.attrib.items():
                if k.split("}", 1)[-1] == name:
                    return v
            return default

        freqs = {}
        for child in root:
            if _tag(child) == "行動リスト":
                for b in child:
                    if _tag(b) == "行動":
                        freqs[_attr(b, "名前")] = _attr(b, "頻度", "0")

        for child in root:
            if _tag(child) != "動作リスト":
                continue
            for act in child:
                if _tag(act) != "動作":
                    continue
                name = _attr(act, "名前")
                if not name:
                    continue
                poses = []
                for anim in act:
                    if _tag(anim) != "アニメーション":
                        continue
                    for p in anim:
                        if _tag(p) != "ポーズ":
                            continue
                        poses.append({
                            "image": _attr(p, "画像", ""),
                            "base": _attr(p, "基準座標", "64,128"),
                            "velocity": _attr(p, "移動速度", "0,0"),
                            "duration": _attr(p, "長さ", "10"),
                        })
                self.actions.append({
                    "name": name,
                    "kind": _attr(act, "種類", "固定"),
                    "frame": _attr(act, "枠", "地面"),
                    "poses": poses,
                    "frequency": freqs.get(name, "0"),
                })

    # ------------------------------------------------------------------
    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        lines = [CUSTOM_XML_HEADER, "<マスコット %s>" % NS, "\t<動作リスト>"]
        for a in self.actions:
            if not a.get("poses"):
                continue
            lines.append('\t\t<動作 名前="%s" 種類="%s" 枠="%s">' % (
                su.quoteattr(a["name"])[1:-1], a.get("kind", "固定"), a.get("frame", "地面")))
            lines.append("\t\t\t<アニメーション>")
            for p in a["poses"]:
                lines.append('\t\t\t\t<ポーズ 画像="%s" 基準座標="%s" 移動速度="%s" 長さ="%s" />' % (
                    p["image"], p["base"], p["velocity"], p["duration"]))
            lines.append("\t\t\t</アニメーション>")
            lines.append("\t\t</動作>")
        lines.append("\t</動作リスト>")
        lines.append("\t<行動リスト>")
        for a in self.actions:
            freq = str(a.get("frequency", "0"))
            if freq and freq not in ("0", ""):
                lines.append('\t\t<行動 名前="%s" 頻度="%s" />' % (
                    su.quoteattr(a["name"])[1:-1], freq))
        lines.append("\t</行動リスト>")
        lines.append("</マスコット>")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


    # ------------------------------------------------------------------
    def get(self, name: str):
        for a in self.actions:
            if a["name"] == name:
                return a
        return None

    def upsert(self, action: dict):
        for i, a in enumerate(self.actions):
            if a["name"] == action["name"]:
                self.actions[i] = action
                return
        self.actions.append(action)

    def remove(self, name: str):
        self.actions = [a for a in self.actions if a["name"] != name]

    @property
    def names(self) -> set[str]:
        return {a["name"] for a in self.actions}
