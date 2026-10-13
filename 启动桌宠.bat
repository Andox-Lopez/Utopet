@echo off
rem ============================================================
rem  Shimeji 重制版 —— 源码启动器 / source launcher
rem
rem  关键点：不只找「存在的 Python」，而是找一个「确实装了 PySide6 的
rem  Python」。Windows 上 `where python` 常返回好几个候选（PATH 里
rem 排在前面的那个往往没装依赖），选错就会弹 ModuleNotFoundError。
rem
rem  Key point: pick a Python that actually *has* PySide6, not merely the
rem  first one on PATH. That mismatch was the real cause of the
rem  "ModuleNotFoundError: No module named 'PySide6'" popup.
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY="

rem --- 1) PATH 上的 pythonw / python，逐个验证 ---
call :probe_name pythonw.exe
if not defined PY call :probe_name python.exe

rem --- 2) py launcher 注册的所有版本 ---
if not defined PY call :probe_pylist

if not defined PY (
    echo.
    echo [Shimeji] 没找到装了 PySide6 的 Python / No Python with PySide6 found.
    echo.
    echo   办法一 / option 1: 装依赖 / install the deps
    echo     pip install -r requirements.txt
    echo.
    echo   办法二 / option 2: 生成免安装版（推荐，不需要 Python）
    echo     python tools\build_release.py
    echo   然后双击 / then double-click:  dist\Shimeji\Shimeji.exe
    echo.
    pause
    exit /b 1
)

echo [Shimeji] using %PY%
start "" "%PY%" "%~dp0main.py"
exit /b 0

rem ---------- 子过程：验证 PATH 上某个名字的每个候选 ----------
:probe_name
for /f "delims=" %%P in ('where %1 2^>nul') do (
    if not defined PY (
        "%%P" -c "import PySide6.QtWidgets" >nul 2>&1 && set "PY=%%P"
    )
)
exit /b 0

rem ---------- 子过程：遍历 py -0p 列出的所有版本 ----------
:probe_pylist
for /f "delims=" %%L in ('py -0p 2^>nul') do (
    if not defined PY (
        rem tokens=2* = 跳过版本号那一个 token，剩下整段就是路径（保住含空格的路径）
        for /f "tokens=2*" %%T in ("%%L") do set "_cand=%%T"
        if defined _cand if exist "!_cand!" (
            "!_cand!" -c "import PySide6.QtWidgets" >nul 2>&1 && set "PY=!_cand!"
        )
    )
)
exit /b 0
