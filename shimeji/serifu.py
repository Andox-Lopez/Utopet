# -*- coding: utf-8 -*-
"""
气泡台词（Serifu）/ Speech balloons.

**原版 Shimeji 最具辨识度的功能**：宠物头顶随机冒出一句话。我们现在只有
动作与物理，没有「说话」这件事 —— 桌宠看着更像程序而不是生物。

台词来源有优先级，**角色自带的永远赢**：

1. ``characters/<角色>/conf/serifu.txt`` —— 沿用原版的 SERIFU 命名，一行一句，
   ``#`` 开头是注释。原版角色包直接放进来就能用。
2. 设置里配的**全局台词库**（设置 → 行为 → 气泡台词）。
3. 内置的默认几句（保证开箱即用，不必先写台词）。

同样**刻意不 import Qt**：台词挑选、触发判定这类逻辑必须能逐个断言，
界面那层（`gui/balloon.py`）只管画。

Deliberately Qt-free again: phrase selection and trigger matching are logic and
must be assertable one by one; `gui/balloon.py` only paints.
"""

from __future__ import annotations

import os
import random

__all__ = ["Serifu", "BUILTIN_PHRASES"]

#: 内置默认台词（中日英混合，与桌宠的「多语言」定位一致）。
#: Built-in phrases, deliberately trilingual to match the app's positioning.
BUILTIN_PHRASES = [
    "……",
    "今天也是元气满满的一天。",
    "要不要休息一下眼睛？",
    "我在看着你哦。",
    "Focus. I'll keep watch.",
    "Still here. Still watching.",
    "少し休憩しよう。",
    "もうひと息하자。",
]

#: 角色包里台词文件的名字（原版是全大写 SERIFU，两种都收）。
#: Phrase-file names inside a character pack (the original uses SERIFU).
PHRASE_FILES = ("serifu.txt", "SERIFU.txt", "serifu.dat", "SERIFU.dat")

#: 行为名里带这些词就冒泡（原版行为就叫「セリフ」）。
#: Behaviours whose name contains any of these pop a balloon.
TRIGGER_TOKENS = ("serifu", "セリフ", "せりふ", "balloon", "speech", "口号", "台詞")


class Serifu:
    """
    台词库 / The phrase book.

    一次构造，整个进程共用（Manager 持有一个实例）。
    Build once and share; the Manager owns one instance.
    """

    def __init__(self, settings=None):
        self.settings = settings
        #: 最近几句，避免同一句话连着冒出来 / recent picks, to avoid repeats
        self._recent: list[str] = []

    # ------------------------------------------------------------------
    # 台词来源 / phrase sources
    # ------------------------------------------------------------------
    def phrases_for(self, bundle) -> list[str]:
        """
        某个角色的可用台词 / phrases available for one character.

        顺序即优先级：角色自带 > 全局配置 > 内置。
        The precedence is the list order: per-character, then the global list,
        then the built-ins.
        """
        out: list[str] = []
        directory = getattr(bundle, "directory", None) if bundle is not None else None
        if directory:
            out.extend(self.load_from_dir(directory))
        if not out:
            out.extend(self.global_phrases())
        if not out:
            out.extend(BUILTIN_PHRASES)
        return out

    def load_from_dir(self, character_dir: str) -> list[str]:
        """读 ``<角色>/conf/serifu.txt`` / Read a pack's phrase file."""
        for folder in ("conf", "."):
            for name in PHRASE_FILES:
                path = os.path.join(character_dir, folder, name)
                if os.path.isfile(path):
                    lines = self._read_lines(path)
                    if lines:
                        return lines
        return []

    def _read_lines(self, path: str) -> list[str]:
        """读一行一句的文件，跳过空行与 ``#`` 注释 / One phrase per line."""
        try:
            with open(path, encoding="utf-8-sig") as fh:
                raw = fh.read()
        except (OSError, UnicodeDecodeError):
            # 角色包不是 utf-8 就退回 latin-1 试一次：宁可显示乱码也别整个
            # 角色没有台词。
            try:
                with open(path, encoding="latin-1") as fh:
                    raw = fh.read()
            except OSError:
                return []
        out = []
        for line in raw.splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            out.append(text)
        return out

    def global_phrases(self) -> list[str]:
        """设置里配的全局台词库 / The phrase list from the settings."""
        if self.settings is None:
            return []
        raw = self.settings.get("serifu_phrases", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(x).strip() for x in raw if str(x).strip()]

    # ------------------------------------------------------------------
    # 挑选 / picking
    # ------------------------------------------------------------------
    def pick(self, phrases: list[str] | None = None) -> str:
        """
        挑一句，避免与最近几句重复。

        候选不足（比如只有 1~2 句）时**不强行去重** —— 与其什么都说不出来，
        不如重复一次。候选**为空**（显式传空列表也一样）则回落到内置台词：
        「没台词」永远不该等于「宠物装死」。
        Avoid repeating the last few, but never at the cost of saying nothing:
        with only one or two phrases available, repeating beats silence.  An
        empty candidate list (including an explicit `[]`) falls back to the
        built-ins -- "no phrases" must never mean "the pet is mute".
        """
        if not phrases:
            phrases = self.global_phrases() or list(BUILTIN_PHRASES)
        pool = [p for p in phrases if p not in self._recent]
        if not pool:
            pool = list(phrases)
            self._recent.clear()
        text = random.choice(pool)
        self._recent.append(text)
        if len(self._recent) > 5:
            self._recent.pop(0)
        return text

    # ------------------------------------------------------------------
    # 触发判定 / trigger matching
    # ------------------------------------------------------------------
    @staticmethod
    def is_trigger(behavior_name: str | None) -> bool:
        """
        这个行为名是不是「说一句」的触发器。

        原版角色包里的行为就叫「セリフ」，但包五花八门（有 SERIFU、serifu、
        せりふ、Speach），所以按**包含**判断而不是全等 —— 全等会漏掉
        「serifu 2」「セリフ（(random)）」这类命名。
        """
        if not behavior_name:
            return False
        low = behavior_name.lower()
        return any(tok in low or tok in behavior_name
                   for tok in TRIGGER_TOKENS)

    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        if self.settings is None:
            return False
        return bool(self.settings.get("serifu_enabled", True))

    def duration_ms(self) -> int:
        if self.settings is None:
            return 4000
        try:
            sec = int(self.settings.get("serifu_seconds", 4))
        except (TypeError, ValueError):
            sec = 4
        return max(1, min(60, sec)) * 1000

    def interval_ms(self) -> int:
        """定时冒泡的间隔；0 = 不定时 / Auto-pop interval; 0 = never."""
        if self.settings is None:
            return 0
        try:
            sec = int(self.settings.get("serifu_interval", 0))
        except (TypeError, ValueError):
            sec = 0
        return max(0, min(3600, sec)) * 1000

    def offset(self) -> tuple[int, int]:
        """气泡相对宠物的偏移 / Balloon offset from the mascot."""
        if self.settings is None:
            return (0, 0)
        try:
            x = int(self.settings.get("serifu_offset_x", 0))
            y = int(self.settings.get("serifu_offset_y", -10))
        except (TypeError, ValueError):
            return (0, -10)
        return (max(-400, min(400, x)), max(-600, min(600, y)))

    def font_px(self) -> int:
        if self.settings is None:
            return 13
        try:
            px = int(self.settings.get("serifu_font_px", 13))
        except (TypeError, ValueError):
            px = 13
        return max(9, min(32, px))
