# Utopet 桌宠 / Utopet Desktop Pet

**中文** · **English**（见文末）· [Releases 下载](/releases/latest)

> **1.0.3 起更名为 Utopet**（原名 Shimeji 重制版）。安装新版时旧版会被自动卸载，
> **设置与你自己添加的角色会完整保留**。

用 **Python + PySide6** 重新实现的桌面宠物引擎，**100% 兼容原版 Group-Finity
Shimeji 的 `Actions.xml` / `Behavior.xml` 配置** —— 网上能找到的原版角色包，
直接丢进 `characters\` 就能用。

- 完整复刻原版 **91 个动作**：走路、奔跑、坐下、爬墙、天花板、拖拽、抛投、掉落物理
- 宠物会站在窗口顶部、爬窗口边缘、**把窗口扛起来扔出去**
- 一次召唤一群（2/3/5/10 只），或同时上多个**不同角色**
- 三语界面（简中 / English / 日本語）、CalMode 养成状态、会话续播、气泡台词、番茄钟

---

## 📥 下载 / Downloads

到 **[Releases 页面](/releases/latest)** 下载最新安装包
（`Utopet-Setup-<版本>.exe`，约 34 MB），双击安装、中文向导、装完全程不用手动操作。

> 这些链接是**相对地址**，指向本仓库 —— 仓库一旦 fork，链接跟着走，不会指回原作者那里。

安装包默认装到 `C:\Program Files\Utopet\`，开始菜单和桌面会留快捷方式。
只想试试的话，下「免安装版」也行。

<details>
<summary><b>免安装版（想直接跑、或不想装东西）</b></summary>

去 Releases 下载或自行用下面的命令构建，产物是 `dist\Utopet\`（约 27 MB，含 Qt 运行库）。
**整个文件夹拷给谁都能跑**，不需要装 Python。

```cmd
python tools\build_release.py
:: 只运行这一个 / run THIS one:
:: dist\Utopet\Utopet.exe
```

角色包放在 exe 旁边的 `characters\`，自己丢角色进去就能被识别。

> ⚠️ **别运行 `build\` 目录里的 exe**。那里也曾躺着一个同名的 `Utopet.exe`，
> 但旁边的 `_internal` 是空的，双击只会报 `Failed to load Python DLL`。
> 构建脚本会在结束时自动删掉 `build\`，看到这个报错就是点错了。

</details>

---

## 🎮 上手 / Getting started

启动后会出现两样东西：**常驻任务栏面板**和**系统托盘图标**。

| 你想做的事 | 怎么做 |
| --- | --- |
| 召唤宠物 | 面板第一行 `[数量] [召唤]`；托盘菜单 →「一次召唤多只…」 |
| 换角色 | 面板第一行**最前面**那个下拉框；或托盘 →「召唤其他角色」 |
| 操作宠物 | **右键**宠物本体 / 托盘图标 —— 两者是同一份菜单，在哪点都一样 |
| 把面板叫回来 | 关掉面板它只是藏起来，程序仍在托盘常驻：托盘右键 →「显示任务栏面板」 |
| 调设置 | 面板里的齿轮按钮，或托盘右键 →「设置…」 |

**拖拽宠物**可以把它拎到任何地方；**扔出去**它会真的被抛飞并落地。
把主面板按钮右键「固定到任务栏」，以后一点就开。

---

## ✨ 功能 / Features

| | |
| --- | --- |
| **原版 91 个动作** | 走路、奔跑、坐下、趴卧、爬墙、天花板、拖拽、抛投、掉落物理 |
| **窗口互动** | 站在窗口顶部、攀爬窗口边缘、扛起窗口、扔出窗口（原版 IE 系动作） |
| **多宠物** | 一次召唤 2/3/5/10 只，落点自动铺开避免叠成一堆 |
| **多角色共存** | 多个不同角色同屏，各用各的动作表 |
| **自我增殖** | 分裂 / 拔萝卜，可在设置里关掉 |
| **行为微调** | 57 条行为逐条调权重或一键停用（比如只关掉「分裂」） |
| **CalMode 养成** | 心情/体力/健康/好感随时间漂移，影响各行为的出现频率 |
| **会话恢复** | 记住上次养了几只、站在哪、分别是什么角色，**接着做刚才那件事** |
| **气泡台词** | 宠物随机冒出一句话（原版 Serifu），台词库可自己写 |
| **输入回避** | 你打字时，压在输入区上的宠物主动跑开 |
| **番茄钟** | 25 分钟工作 + 5 分钟休息，每 4 轮一次长休息，阶段自动衔接 |
| **自定义动作** | 可视化挑帧 + 循环预览，存成与原版同构的 `custom.xml` |
| **角色包管理** | zip 拖进设置窗口就装；可停用或删除已装角色 |
| **多显示器** | 宠物走到哪块屏就用哪块屏的工作区 |
| **高 DPI** | 所有原生坐标统一换算，不会在缩放屏上错位 |
| **开机自启** | 勾选即写注册表，打包版与源码版都支持 |
| **三语界面** | 简体中文 / English / 日本語，即时切换 |

配置文件 `config\settings.json` 带注释，可以直接手改。
运行日志在 `data\shimeji.log`。

---

## 🧩 加角色 / Adding a character

把角色包丢进 `characters\<角色名>\` 就行 —— 或者在**设置 → 角色**里把 zip
**直接拖到设置窗口上**，三种常见目录布局自动识别，缺 `Actions.xml` /
`Behavior.xml` / `Mascot.xsd` 时用内置原版模板补齐（**只填不改**，不会覆盖你的文件）。

`conf\` 下的配置与原版**完全同构**，标签三种写法都认：

```xml
<!-- 原版日文 / original Japanese -->
<動作 名前="歩く" 種類="移動" 枠="地面"> ...

<!-- 中文 / Chinese -->
<动作 名称="走路" 类型="移动" 框="地面"> ...

<!-- 英文 / English -->
<action name="Walk" kind="move" frame="ground"> ...
```

---

## 🔧 从源码运行 / From source

需要 **Python 3.11+**：

```cmd
pip install -r requirements.txt

:: 双击这个（会自动挑选装了 PySide6 的解释器）/ double-click the launcher:
启动桌宠.bat
:: 或者 / or
python main.py
```

<details>
<summary><b>构建安装包 / 构建发版</b></summary>

```cmd
:: 一步搞定：构建 → 打包 → 测试 → 推送 → 建 Release 并上传安装包
:: 推送与发版前会停下来确认。/ pauses before pushing.
python tools\release.py
```

| 开关 | 作用 |
| --- | --- |
| `--dry-run` | 什么都不改，只打印计划 |
| `--yes` | 跳过确认（CI 用） |
| `--skip-tests` | 跳过安装包实测（那步会 taskkill 正在运行的桌宠） |

ISCC 需装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)。安装向导的中文语言文件由
`tools\make_isl.py` 生成，改译文后重跑该脚本即可。

</details>

---

## ⚠️ 已知限制 / Known limitations

- **「输入回避」避的是「光标附近」，不是「输入框附近」。** Windows 不告诉外部程序
  「你的输入框在哪」：浏览器、VS Code 这类应用自己绘制光标。记事本、Office 这类传统
  控件能提供精确位置，程序会自动切到精确模式。可在 **设置 → 行为** 关掉或调区域大小。
- **最大化 / 全屏窗口不参与窗口互动**（宠物不会去爬、扛、扔它们）。这类窗口的下边和
  屏幕地面完全重合，宠物站在地上会一直触发「沿窗口下边爬行」。
- **会话恢复对同一个行为精确续播**；存档里的行为在当前角色的动作表里找不到时（换了角色，
  或该动作被停用），位置照旧恢复、动作重新挑。
- **补帧上限 20000 帧**（25 fps 下约 13 分钟）。
- 「鼠标空闲聚集」默认关闭，可在 **设置 → 行为** 打开。
- 全局快捷键已于 1.0.7 移除（原因见 [CHANGELOG](CHANGELOG.md)）。

---

## 📄 项目说明 / Notes

<details>
<summary><b>引擎还原度：与原版对齐的关键语义</b></summary>

本项目按原版 `Shimeji.jar` 反编译校准，以下语义逐条对齐：

| | |
| --- | --- |
| `Pose.next` | `anchor.x += lookRight ? -dx : dx`，图片朝右时镜像 |
| `Look.apply` | `右向き` 缺省 = `!lookRight`，即**直接翻转朝向** |
| `Move.tick` | 每帧 `setLookRight(anchor.x < 目的地X)`，始终面朝目标 |
| `Jump.tick` | 非抛物线，是朝目标点的**匀速直线冲刺** |
| `Fall.tick` | `v -= v*空気抵抗`，`vy += 重力`，小数部分累积进位 |
| `Border.isOn` | `±2px` 边界容差，`±10px` 沿边范围 |
| `Environment.floor` | 优先宠物脚下窗口的顶边，否则工作区下边 |
| 动作帧率 | 40 ms/帧（25 fps） |

</details>

<details>
<summary><b>目录结构</b></summary>

```
Utopet\
├── main.py                      程序入口 / entry point
├── 启动桌宠.bat                 双击启动 / double-click launcher
├── shimeji\
│   ├── win32.py                 原生窗口接口 + 输入状态探测
│   ├── settings.py  cfgfmt.py   设置持久化 + 带注释 JSON
│   ├── characterpack.py         角色包导入·导出·描述文件增补
│   ├── serifu.py                气泡台词库（无 Qt）
│   ├── pomodoro.py              番茄钟逻辑（无 Qt）
│   ├── xml\                     Actions.xml / Behavior.xml 解析
│   ├── engine\
│   │   ├── environment.py       屏幕·工作区·窗口·边界
│   │   ├── mascot.py            透明宠物窗口
│   │   ├── runtime.py           动作执行器
│   │   ├── brain.py             行为选择
│   │   ├── avoid.py             输入回避区（无 Qt）
│   │   └── manager.py           托盘·面板·多宠物·主循环
│   └── gui\                     设置 · 动作编辑器 · 面板 · 番茄钟 · 气泡
├── characters\<角色>\            img\ + conf\
├── tools\                       发版 · 图标 · 安装向导语言
├── analysis\                    测试脚本
├── config\                      settings.json（可手改，带注释）
└── data\                        shimeji.log · custom.xml（运行期产物）
```

</details>

跑测试：

```cmd
python analysis\verify_physics_101.py   :: 引擎与行为选择
python analysis\verify_pomodoro.py      :: 番茄钟
python analysis\verify_serifu.py        :: 气泡台词
python analysis\verify_installer.py     :: 安装包实测（会 taskkill 正在运行的桌宠）
```

改动请同时更新 [CHANGELOG.md](CHANGELOG.md)。

---

## 📄 License

[Apache License 2.0](LICENSE) — Copyright 2026 Karandox Lopez

---

<div lang="en">

## English

A desktop-mascot engine re-implemented in **Python + PySide6**, **100% compatible
with the original Group-Finity Shimeji configuration files** — any original
character pack you find online drops straight into `characters\`.

- All **91 original actions**: walk, run, sit, lie, climb walls, hang from
  ceilings, drag, throw, fall physics
- Pets stand on window tops, climb window edges, **carry windows and throw them**
- Summon a crowd (2/3/5/10 at once) or several **different characters** together
- Three UI languages, CalMode state, session resume, speech balloons, Pomodoro

### Downloads

Grab the installer (≈34 MB, Chinese wizard) from the
**[Releases page](/releases/latest)**.

<details>
<summary><b>Standalone build (no install)</b></summary>

```cmd
pip install -r requirements.txt
python tools\build_release.py
:: run THIS one:
:: dist\Utopet\Utopet.exe
```

Self-contained: **no Python needed** to run it. The whole `dist\Utopet\` folder
(≈27 MB, Qt runtime included) works anywhere. Character packs live in
`characters\` next to the exe.

> ⚠️ **Only run `dist\Utopet\Utopet.exe`.** `build\` used to hold a same-named
> exe with an empty `_internal` next to it, which only yields "Failed to load
> Python DLL". The build script deletes `build\` afterwards.

</details>

### Getting started

On start you get an **always-on taskbar panel** and a **tray icon**.

| To… | Do this |
| --- | --- |
| Summon pets | Panel's first row `[count] [Summon]`; tray → "Summon several…" |
| Change character | The **first** drop-down on the panel's first row; or tray → "Summon another character" |
| Interact | **Right-click** the pet / the tray icon — both open the same menu |
| Bring the panel back | Closing it only hides it; the app stays in the tray |
| Open settings | The gear button on the panel, or tray → "Settings…" |

**Drag** a pet anywhere; **throw** it and it really flies and lands.
Right-click the panel button to pin it to the taskbar.

### Features

| | |
| --- | --- |
| **All 91 original actions** | walk, run, sit, lie, climb walls, ceilings, drag, throw, fall physics |
| **Window interaction** | stand on window tops, climb edges, carry windows, throw them |
| **Many mascots** | summon 2/3/5/10 at once, landing points spread automatically |
| **Multi-character** | several different characters on screen at once |
| **Self-cloning** | split / pull-out, switchable in settings |
| **Per-behaviour tuning** | adjust or disable each of the 57 behaviours individually |
| **CalMode** | mood / stamina / health / rapport drift over time and bias behaviour frequency |
| **Session resume** | remembers how many, where, and which character — and continues |
| **Speech balloons** | a random line above the pet's head (the original's Serifu) |
| **Input avoidance** | pets run off the area you are typing in |
| **Pomodoro** | 25 min work + 5 min break, long break every 4 rounds |
| **Custom actions** | pick frames visually, saved as `custom.xml` in the original schema |
| **Character packs** | drag a zip onto Settings; disable or delete installed packs |
| **Multi-monitor / High-DPI** | follows the pet across screens; DPI-correct everywhere |
| **Launch at login**, **three UI languages** | both configurable |

Settings live in `config\settings.json` — commented JSON you can hand-edit.
Runtime log: `data\shimeji.log`.

### Adding a character

Drop a pack into `characters\<name>\`, or **drag the zip onto the Settings
window** — three common layouts auto-detected, missing files filled from
built-in templates (**add-only, never overwritten**).

Tags are accepted in Japanese, Chinese and English:

```xml
<動作 名前="歩く" 種類="移動" 枠="地面"> ...   <!-- Japanese -->
<动作 名称="走路" 类型="移动" 框="地面"> ...   <!-- Chinese -->
<action name="Walk" kind="move" frame="ground"> ...  <!-- English -->
```

### From source

```cmd
pip install -r requirements.txt
python main.py      :: or double-click 启动桌宠.bat
```

### Known limitations

- **Input avoidance zones the area around the *cursor*, not the input box.**
  Windows does not tell outside programs where the input box is; modern apps
  draw their own caret. Classic Win32 controls (Notepad, Office) do report it.
  Switchable under **Settings → Behaviour**.
- Maximised / full-screen windows take no part in window interaction.
- Global hotkeys were removed in 1.0.7 (see [CHANGELOG](CHANGELOG.md)).

### License

[Apache License 2.0](LICENSE) — Copyright 2026 Karandox Lopez

</div>
