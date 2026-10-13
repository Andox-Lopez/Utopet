# -*- coding: utf-8 -*-
r"""验证带注释 JSON 的读写往返 + 旧配置迁移。"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, "E:/shimejee-remake")

from shimeji import cfgfmt
from shimeji.settings import DEFAULTS, Settings

ok = True


def check(cond, msg, detail=""):
    global ok
    line = ("  [ok]   " if cond else "  [FAIL] ") + msg
    if detail:
        line += f"({detail})"
    print(line)
    if not cond:
        ok = False


print("--- 1. 序列化出来的样子 ---")
text = cfgfmt.dumps_readable(dict(DEFAULTS), list(DEFAULTS.keys()))
print(text[:420])
print("  ...")

print("\n--- 2. 往返：写出再读回，值必须一致 ---")
data = dict(DEFAULTS)
data["summon_count"] = 7
data["titles"] = ["Notepad", "浏览器"]
data["panel_pos"] = [123, 456]
d = tempfile.mkdtemp()
try:
    p = os.path.join(d, "settings.json")
    s = Settings(p)
    s.set("summon_count", 7)
    s.set("titles", ["Notepad", "浏览器"])
    s.set("panel_pos", [123, 456])
    s.save()
    s2 = Settings(p)
    check(s2.get("summon_count") == 7, "标量往返正确")
    check(s2.get("titles") == ["Notepad", "浏览器"], "含中文的列表往返正确")
    check(s2.get("panel_pos") == [123, 456], "嵌套结构往返正确")

    print("\n--- 3. 用户手加的注释不能被抹掉 ---")
    with io.open(p, encoding="utf-8") as f:
        content = f.read()
    check("// 界面 / interface" in content, "写出的文件带分组注释")
    manual = content.replace(
        '  "summon_count": 7,',
        '  // 这行是我自己加的备注，别删\n  "summon_count": 7,')
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(manual)
    s3 = Settings(p)
    check(s3.get("summon_count") == 7, "带注释的文件能正常读")
    s3.save()
    with io.open(p, encoding="utf-8") as f:
        check("我自己加的备注" in f.read(),
              "重写后用户手加的注释被保留")

    print("\n--- 4. 值里的 // 不能被当成注释 ---")
    p2 = os.path.join(d, "u.json")
    s4 = Settings(p2)
    s4.set("titles", ["https://example.com/a//b"])
    s4.save()
    s5 = Settings(p2)
    check(s5.get("titles") == ["https://example.com/a//b"],
          "URL 里的双斜杠不会被误当注释", str(s5.get("titles")))

    print("\n--- 5. 手改写坏要有明确提示，且原文件保住 ---")
    p3 = os.path.join(d, "bad.json")
    with io.open(p3, "w", encoding="utf-8") as f:
        f.write('{"summon_count": 5,,}')
    s6 = Settings(p3)
    check(bool(getattr(s6, "load_error", None)),
          "解析失败时记录了错误（可提示用户）",
          str(getattr(s6, "load_error", ""))[:60])
    check(os.path.exists(p3 + ".broken"),
          "损坏的原文件被改名保留，没有被静默覆盖")

    print("\n--- 6. 默认路径在 config\\ 下 ---")
    import shimeji.settings as S
    check(S.CONFIG_DIR.endswith("config"), "CONFIG_DIR 指向 config 子目录",
          S.CONFIG_DIR)
    check(S.Settings().path == os.path.join(S.CONFIG_DIR, "settings.json"),
          "默认 settings.json 路径在 config\\ 下", S.Settings().path)
finally:
    shutil.rmtree(d, ignore_errors=True)

print("\n" + ("ALL PASS" if ok else "FAILED"))
sys.exit(0 if ok else 1)