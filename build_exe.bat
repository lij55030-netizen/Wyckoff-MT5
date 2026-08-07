@echo off
REM ============================================================
REM  WKF 威科夫交易智能体 — EXE 打包脚本
REM  用法: 双击运行，或 build_exe.bat gui / cli / bot / all
REM  依赖: pip install pyinstaller
REM ============================================================
cd /d "%~dp0"

if "%1"=="" set MODE=all
if "%1"=="gui" set MODE=gui
if "%1"=="cli" set MODE=cli
if "%1"=="bot" set MODE=bot
if "%1"=="all" set MODE=all

echo [WKF] 开始打包（模式: %MODE%）...

REM 确保 PyInstaller 已安装
D:\python\python.exe -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [WKF] 未检测到 PyInstaller，正在安装...
    D:\python\python.exe -m pip install pyinstaller
)

REM ---- 产物目录 ----
set DIST=dist
if not exist %DIST% mkdir %DIST%

if "%MODE%"=="all" goto do_all
if "%MODE%"=="gui" goto do_gui
if "%MODE%"=="cli" goto do_cli
if "%MODE%"=="bot" goto do_bot

:do_gui
echo [WKF] 打包 GUI 面板（无控制台窗口）...
D:\python\python.exe -m PyInstaller -F -w -n Wyckoff_Analysis_GUI run.py
goto done

:do_cli
echo [WKF] 打包 CLI 工具...
D:\python\python.exe -m PyInstaller -F -n Wyckoff_CLI cli.py
goto done

:do_bot
echo [WKF] 打包飞书机器人（保留控制台日志）...
D:\python\python.exe -m PyInstaller -F -n Wyckoff_Feishu_Bot tools\feishu_commander.py
goto done

:do_all
call :do_gui
call :do_cli
call :do_bot
goto done

:done
echo.
echo [WKF] 打包完成！产物位于 dist\ 目录：
dir /b %DIST%\*.exe 2>nul
echo.
echo 说明：
echo   Wyckoff_Analysis_GUI.exe — 双击打开可视化面板
echo   Wyckoff_CLI.exe — 拖拽exe+品种周期执行，如: Wyckoff_CLI.exe NQ 15m
echo   Wyckoff_Feishu_Bot.exe — 飞书机器人常驻后台
echo.
echo 注意：EXE 运行时需要本机已安装 MetaTrader5 并登录账户，
echo       且 config/settings.json 或 config/config.ini 已配置。
pause
