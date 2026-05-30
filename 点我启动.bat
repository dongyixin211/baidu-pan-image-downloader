@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 百度网盘图片批量下载工具

echo 正在启动，请稍等...

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD where python >nul 2>nul
if not defined PYTHON_CMD if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo.
    echo 没有找到可用的 Python 3.8 或更高版本。
    echo 请先安装 Python，再重新双击“点我启动.bat”。
    echo 下载地址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% launcher.py %*
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo.
    echo 启动没有成功。请查看上面的错误信息。
    echo.
    pause
    exit /b %ERR%
)

echo.
echo 工具已关闭。
pause
