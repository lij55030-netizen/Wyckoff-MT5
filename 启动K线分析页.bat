@echo off
chcp 65001 >nul
title WKF 股票K线分析页面
echo ============================================================
echo   WKF 股票K线分析页面 启动中...
echo   服务地址: http://127.0.0.1:8000
echo   关闭本窗口即停止服务
echo ============================================================
cd /d "%~dp0"
start "" http://127.0.0.1:8000
D:\python\python.exe web\server.py
pause
