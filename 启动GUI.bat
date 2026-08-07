@echo off
REM ============================================================
REM  WKF 威科夫交易智能体 — GUI 可视化面板启动
REM  用法: 双击本文件
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title WKF 威科夫交易智能体 - GUI

echo ============================================
echo   WKF 威科夫交易智能体 - GUI 可视化面板
echo ============================================
echo.

REM 检查 Python
D:\python\python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确认 D:\python 已安装
    pause
    exit /b 1
)

echo [启动] 正在打开可视化面板...
echo [提示] 请保持本窗口开启，关闭窗口即退出程序
echo.
D:\python\python.exe run.py
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出，错误码: %errorlevel%
    echo 可查看 logs 目录日志排查
)
pause
