@echo off
REM ============================================================
REM  WKF 威科夫交易智能体 — 飞书机器人启动
REM  用法: 双击本文件（需保持窗口开启）
REM  在手机飞书给机器人发「分析 NQ 15m」即可触发分析
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title WKF 飞书机器人监听

echo ============================================
echo   WKF 飞书指令机器人 - 后台监听
echo   在手机飞书发「分析 NQ 15m」触发分析
echo   按 Ctrl+C 停止服务
echo ============================================
echo.

D:\python\python.exe tools\feishu_commander.py
if errorlevel 1 (
    echo.
    echo [错误] 飞书机器人异常退出，错误码: %errorlevel%
    echo 请确认 WorkBuddy 飞书连接在线，或检查 lark-cli 配置
)
pause
