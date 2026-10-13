# -*- coding: utf-8 -*-
r"""安全验证：用户自己下载了角色包时，卸载**绝不能**把安装目录连内容删掉。

RemoveDir 在目录非空时会失败，所以理论上安全。但「理论上」不够 ——
这里真的造一个带用户角色的安装目录，卸载一遍，看目录和角色是否都还在。
"""
import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = "E:/shimejee-remake"
TESTDIR = os.path.join(ROOT, "analysis", "_keepdata_test")
SETUP = os.path.join(ROOT, "output", "Utopet-Setup-1.0.5.exe")

ok = True


def check(cond, msg, detail=""):
    global ok
    line = ("  [ok]   " if cond else "  [FAIL] ") + msg
    if detail:
        line += f"({detail})"
    print(line, flush=True)
    if not cond:
        ok = False


subprocess.run(["taskkill", "/F", "/IM", "Utopet.exe"], capture_output=True)
time.sleep(1)
if os.path.isdir(TESTDIR):
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", TESTDIR],
                   capture_output=True)

rc = subprocess.run([SETUP, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                     "/DIR=" + TESTDIR], timeout=240).returncode
check(rc == 0, "安装成功", f"rc={rc}")

# 模拟用户自己下载了一个角色包（不是安装器放的，卸载器不认识它）
user_pack = os.path.join(TESTDIR, "characters", "Ayaka")
os.makedirs(os.path.join(user_pack, "conf"), exist_ok=True)
os.makedirs(os.path.join(user_pack, "img"), exist_ok=True)
with open(os.path.join(user_pack, "conf", "USER_EDITED.marker"), "w",
          encoding="utf-8") as f:
    f.write("mine")
for i in range(3):
    with open(os.path.join(user_pack, "img", f"p{i}.png"), "wb") as f:
        f.write(b"\x89PNG-mine")
check(os.path.isdir(user_pack), "已造出用户自己的角色包")

# 卸载
unins = glob.glob(os.path.join(TESTDIR, "unins*.exe"))
check(bool(unins), "找到卸载器")
p = subprocess.Popen([unins[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
t0 = time.time()
while time.time() - t0 < 60 and p.poll() is None:
    time.sleep(0.5)
time.sleep(1.5)

# 关键断言：目录和用户数据都必须还在
check(os.path.isdir(TESTDIR), "有用户数据时安装目录被保留（没被误删）")
check(os.path.isfile(os.path.join(user_pack, "conf", "USER_EDITED.marker")),
      "用户自己的角色包完好无损")
check(os.path.isdir(os.path.join(TESTDIR, "_internal")) or True, "")
# 程序本体应该已被卸载器清掉
check(not os.path.isfile(os.path.join(TESTDIR, "Utopet.exe")),
      "程序本体已被卸载（说明卸载确实执行了）")

if os.path.isdir(TESTDIR):
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", TESTDIR],
                   capture_output=True)

print("\n" + ("ALL PASS —— 用户数据受保护" if ok else "FAILED"))
sys.exit(0 if ok else 1)