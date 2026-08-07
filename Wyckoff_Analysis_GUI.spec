# -*- mode: python ; coding: utf-8 -*-
"""WKF 主程序 onedir 打包配置（V3.0）。

模式：PyInstaller onedir（目录分发，启动快、便于排查缺失依赖）。
剔除：tests/、tools/ 测试脚本、test_reports、cache 调试缓存（不进入包）。
仅打包 GUI 主程序（run.py → WKF.exe）；CLI/飞书机器人另行独立打包。
"""

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/alert.wav', 'assets'),          # 提示音（运行时播放）
    ],
    hiddenimports=[
        'MetaTrader5',                            # 行情数据源（MT5 实盘）
        'yfinance',                               # 可选数据源（公开行情）
        'openai',                                 # DeepSeek AI 客户端
        'requests',                               # 飞书 webhook / 网络
        'pydantic',                               # 配置模型
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests', 'tools', 'test_reports',         # 剔除测试文件
        'cache',                                  # 剔除调试 JSON 缓存（运行时重建）
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                        # onedir：二进制由 COLLECT 分发
    name='WKF',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WKF',
)
