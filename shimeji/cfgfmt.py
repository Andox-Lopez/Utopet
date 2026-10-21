# -*- coding: utf-8 -*-
r"""带注释、分组的可读 JSON 读写。

为什么不用 YAML：YAML 需要 PyYAML 依赖（打包要多带一个库），而这里要的只是
「能加注释」这一件事。用 JSON 加注释行就够了，读的时候剥掉即可 ——
手改友好，且零新依赖。

设计要点：
- 注释只在**写**的时候生成，**读**的时候整行剥掉，所以用户手加的注释不会被
  程序抹掉（程序只重写它自己生成的那些键值）。
- 每组前会写「上次值 -> 新值」的说明？不要，那样文件会不断膨胀。
  只写分组标题和键的中文说明。
- 任何一行剥完不是合法 JSON 就抛错 —— 宁可让用户看到明确报错，
  也好过静默吞掉半份配置。

A commented, grouped, human-editable JSON codec.

YAML would need a PyYAML dependency (one more library in the bundle) for what
is really just "let me add comments".  JSON plus comment lines does the job,
and strips them on read, so hand-written comments survive: the program only
rewrites the values it knows about.
"""

from __future__ import annotations

import json
import os
import re
from collections import OrderedDict

__all__ = ["dumps_readable", "loads_stripping_comments",
           "read_extra_comments", "GROUPS"]


#: 每个分组的中文标题。键不在表里时会落到「其它」。
#: Human-readable group headings; unknown keys land in "其它".
GROUPS: list[tuple[str, list[str]]] = [
    ("界面 / interface", [
        "language", "bilingual", "character", "character_dirs"]),
    ("外观 / appearance", [
        "scale", "opacity", "always_on_top", "click_through"]),
    ("行为 / behaviour", [
        "tick_ms", "initial_count", "max_count", "restore_session",
        "self_cloning_enabled", "self_cloning_pref", "spawn_spread",
        "idle_gather", "idle_gather_sec"]),
    ("窗口互动 / window interaction", [
        "climb_enabled", "throw_enabled", "ie_interaction"]),
    ("多宠物 / multi-mascot", [
        "multi_pet_enabled", "summon_count"]),
    ("窗口 / windows", [
        "titles", "window_offset"]),
    ("系统 / system", [
        "start_with_windows", "taskbar_panel", "panel_pos",
        "first_run_guide_done"]),
    ("高级 / advanced", [
        "cal_overrides", "behavior_overrides", "session"]),
]

#: 分组说明，写在标题下面，读的时候忽略。
#: One-line explanation under each heading; ignored when reading.
NOTES: dict[str, str] = {
    "界面 / interface":
        "language 可选 zh_CN / en_US / ja_JP；character 必须是 characters 下的目录名",
    "窗口互动 / window interaction":
        "climb=爬窗，throw=扔窗口（越界的窗口会自动夹回工作区）",
    "系统 / system":
        "panel_pos 是面板上次被拖到的位置 [x, y]；null 表示用默认右下角",
}


def _group_of(key: str) -> str:
    for name, keys in GROUPS:
        if key in keys:
            return name
    return "其它 / other"


#: 程序自己会生成的那些注释，重写时不必回收（会原样重新写出）。
#: Built-in comments: regenerated on every write, so never harvested as "user's".
_GENERATED = {name for name, _ in GROUPS} | {"其它 / other"} | set(NOTES)


def read_extra_comments(text: str) -> dict[str, list[str]]:
    """收集用户自己手写的注释，按它所注释的键归类。

    程序重写配置时只写自己生成的那几条固定说明，**用户手加的备注会被抹掉** ——
    那等于违背「这个文件你可以随便改」的承诺。所以先把用户的注释读出来，
    写回去时再原样贴回对应的键上面。

    Harvest comments the user wrote by hand, keyed by the setting they precede.

    Rewriting the file only emits the built-in group notes, which would wipe
    any comment the user added.  Collecting them first and pasting them back
    is what actually makes the file safe to hand-edit.
    """
    out: dict[str, list[str]] = {}
    pending: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            body = stripped[2:].strip()
            # 程序自己生成的那些（分组标题 / 说明）不回收，重写时会重新生成
            if body in _GENERATED:
                pending = []
            else:
                pending.append("  // " + body)
            continue
        m = re.match(r'\s*"([^"]+)"\s*:', line)
        if m and pending:
            out.setdefault(m.group(1), []).extend(pending)
            pending = []
        elif stripped and not stripped.startswith("//"):
            pending = []
    return out


def dumps_readable(data: dict, order: list[str] | None = None,
                   user_comments: dict[str, list[str]] | None = None) -> str:
    """把配置写成带注释分组的 JSON 文本。

    `order` 给出偏好的键顺序（通常是 DEFAULTS 的顺序），让 diff 稳定 ——
    否则字典序会把同一个人为相关的键拆散，读起来费劲。
    `user_comments` 是从旧文件里收来的用户手写注释，会原样贴回对应键上方。

    逗号在这里手工加，不靠 json.dumps 整块输出：注释行必须插在键与键之间，
    所以只能一个键一个键地拼。
    Emit grouped, commented JSON.

    `order` fixes the key order so diffs stay small.  `user_comments` holds the
    comments harvested from the previous file and pastes them back above the
    key they belonged to.

    Commas are added by hand, key by key: comment lines have to be interleaved
    *between* entries, so the whole-object shortcut of json.dumps cannot be
    used here.
    """
    user_comments = user_comments or {}
    keys = [k for k in (order or list(data.keys())) if k in data]
    keys += [k for k in data if k not in keys]

    grouped: "OrderedDict[str, list]" = OrderedDict()
    for k in keys:
        grouped.setdefault(_group_of(k), []).append(k)

    lines: list[str] = ["{"]
    last_group = list(grouped.keys())[-1]
    first_group = True
    for group, gkeys in grouped.items():
        if not first_group:
            lines.append("")
        first_group = False
        lines.append(f"  // {group}")
        note = NOTES.get(group)
        if note:
            lines.append(f"  // {note}")
        for idx, k in enumerate(gkeys):
            lines.extend(user_comments.get(k, []))
            is_last = (idx == len(gkeys) - 1) and (group == last_group)
            val = json.dumps(data[k], ensure_ascii=False, indent=2)
            comma = "" if is_last else ","
            if "\n" in val:
                body = val.replace("\n", "\n  ")
                lines.append(
                    f"  {json.dumps(k, ensure_ascii=False)}: {body}{comma}")
            else:
                lines.append(
                    f"  {json.dumps(k, ensure_ascii=False)}: {val}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def loads_stripping_comments(text: str) -> dict:
    """解析带注释的 JSON。注释只认整行 `//` 前缀（块注释形式）。

    只处理「整行都是注释」和「行尾 // 注释」两种，不碰字符串里的 `//`
    （比如 URL "https://..."），所以是安全的。
    Parse commented JSON.  Only whole-line and trailing `//` comments are
    recognised, and a `//` inside a string literal (e.g. a URL) is left
    alone, so this is safe.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or not stripped:
            continue
        # 去掉行尾注释，但不能切在字符串内部
        cleaned.append(_strip_trailing_comment(line))
    joined = "\n".join(cleaned)
    if not joined.strip():
        return {}
    data = json.loads(joined)
    if not isinstance(data, dict):
        raise ValueError("配置文件的顶层必须是一个对象")
    return data


def _strip_trailing_comment(line: str) -> str:
    """去掉一行末尾的 // 注释，跳过字符串字面量内部。

    Remove a trailing // comment while skipping over string literals.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                out.append(ch)
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break        # 注释开始，剩下的丢掉
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def atomic_write(path: str, text: str) -> None:
    """先写临时文件再替换，避免写到一半断电/崩溃留下半份配置。

    用户配置是这个软件里最不该丢的数据 —— 丢一次就等于把人家调了一下午的
    设置全部归零。os.replace 在同一文件系统内是原子的。
    Write via a temp file and replace: a half-written config would silently
    reset every setting the user tuned. os.replace is atomic within a volume.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)