# -*- mode: python ; coding: utf-8 -*-
# ⚠️ 这个 docstring 必须是 raw string（r"""）：路径里的 \U 会被 Python 当成
# unicode 转义起点，直接报 "truncated \UXXXXXXXX escape"。改名成 Utopet 后
# 路径以 \U 开头，正好踩中这个坑。
r"""PyInstaller 打包配置 —— 生成自包含的 Utopet.exe

用法（项目根目录）：
    python -m PyInstaller --noconfirm shimeji.spec

产物：dist\Utopet\Utopet.exe
用户双击即可运行，**不需要安装 Python，也不需要 pip install**。

关于 characters\ 目录
---------------------
角色包（约 3.6MB 的 PNG 序列）故意 *不* 打进 exe，而是构建后复制到
exe 旁边（见 tools\build_release.py）。这样用户可以直接把自己的角色丢进
Utopet 目录下的 characters\ 文件夹，程序下次启动就能识别。
settings.py 里 `_app_root()` 已经处理了 frozen 路径。
"""

import os

# 所有路径都相对本 spec 文件所在目录（即项目根），保证在任意 cwd 下都能构建
ROOT = os.path.abspath(os.getcwd())
ASSETS = os.path.join(ROOT, "shimeji", "assets")
LOCALES = os.path.join(ROOT, "shimeji", "locales")
# exe 图标用 app.ico —— 它带 16…256 全尺寸，资源管理器的大图标视图、
# 任务栏 exe 按钮、卸载程序列表都需要大尺寸帧。
# 托盘另外用 logo.ico（只有 16…64，16px 那帧去了圆角），两者刻意不共用。
# The exe icon is app.ico: it carries every size from 16 to 256 for Explorer's
# large-icon view, the taskbar button and the Add-Remove list.  The tray uses
# logo.ico separately (16..64 only, 16px squared off) -- deliberately distinct.
LOGO_ICO = os.path.join(ASSETS, "app.ico")

if not os.path.exists(LOGO_ICO):
    # 没有 app.ico 就退回 logo.ico，再退回 png（PyInstaller 能接受 png 但多尺寸会丢）
    LOGO_ICO = os.path.join(ASSETS, "logo.ico")
    if not os.path.exists(LOGO_ICO):
        LOGO_ICO = os.path.join(ASSETS, "logo.png")

# 运行时真正用到的额外数据文件：图标 + 三语语言包。
# 注意 shimeji/xml、shimeji/engine、shimeji/gui 是纯 Python 包，
# 由 PyInstaller 的依赖分析自动收集，不需要在这里列。
datas = [
    (LOCALES, "shimeji/locales"),
    (ASSETS, "shimeji/assets"),
]

# PySide6 完整安装有 1GB+，其中绝大多数本项目一行都没用到。
# 这里显式排除，既能瘦身 10 倍以上，也能显著缩短构建时间。
excludes = [
    # --- 用不到的重型 Qt 模块 ---
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQuickLayouts", "PySide6.QtQuickShapes",
    "PySide6.QtQuickTemplates2", "PySide6.QtQuickEffects",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.Qt3DAssetTypes",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSensors", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects", "PySide6.QtHttpServer",
    # --- 图形/科学计算后端：只做 alpha 抠图，用不上 ---
    "matplotlib", "numpy", "scipy", "pandas", "PIL", "Pillow",
    # --- 完全无关 ---
    "tkinter", "unittest", "pydoc_data", "test",
    "setuptools", "pip", "wheel",
    # 刻意保留 PySide6.QtNetwork：QSystemTrayIcon 的部分 Windows 实现会引用它，
    # 排除后可能出现「托盘图标不出现」的玄学问题，不值得为体积冒险。
]

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Qt 的平台插件在 Windows 上必须显式带上，否则 exe 启动即 "could not find or load
        # the Qt platform plugin windows"
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Utopet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False → 双击不弹黑框；启动失败时由 main.py 自己用 MessageBoxW 报错
    console=False,
    disable_windowed_traceback=False,
    icon=LOGO_ICO,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Utopet",
)
