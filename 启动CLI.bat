@echo off
REM ============================================================
REM  WKF 威科夫交易智能体 — 命令行分析工具
REM  用法: 双击本文件，按提示输入品种和周期
REM       或拖拽: 启动CLI.bat NQ 15m
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title WKF 命令行分析

if "%~1"=="" (
    echo ============================================
    echo   WKF 命令行分析工具
    echo ============================================
    echo.
    set /p SYM=请输入品种 (NQ/ES/XAU): 
    set /p TF=请输入周期 (5m/10m/15m/30m/1h，默认15m): 
    if "%TF%"=="" set TF=15m
    D:\python\python.exe cli.py %SYM% %TF%
) else (
    if "%~2"=="" (
        D:\python\python.exe cli.py %~1 15m
    ) else (
        D:\python\python.exe cli.py %~1 %~2
    )
)
echo.
pause
