; ============================================================
; WKF 威科夫交易智能体 V3.1 — 一键安装包脚本（onedir 目录分发）
; 编译: ISCC.exe WKF_installer.iss
; 产物: installer\WKF_V3.1_Setup.exe
; 支持: 自定义安装路径 / 桌面快捷方式(可选) / 开始菜单 / 内置卸载程序
; ============================================================
#define MyAppName "WKF 威科夫交易智能体"
#define MyAppVersion "3.1.0"
#define MyAppExeName "WKF.exe"

[Setup]
AppId={{A3F7D9B2-4E6C-4B8A-9D1E-5F2C8A0B7E93}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=WKF Team
AppPublisherURL=https://github.com/lij55030-netizen/Wyckoff-MT5-Workbuddy
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=installer
OutputBaseFilename=WKF_V3.1_Setup
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked
Name: "startmenu"; Description: "创建开始菜单入口"; GroupDescription: "附加任务:"

[Files]
; 主程序 onedir 目录（PyInstaller 打包产物，含 _internal 运行时依赖）
Source: "dist\WKF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 新手使用手册与快捷启动
Source: "WKF使用手册.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "启动GUI.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "绿色免安装版说明.txt"; DestDir: "{app}"; Flags: ignoreversion
; 配置模板（不含任何真实密钥，首次启动弹窗引导配置）
; 运行时配置路径基于 _internal（onedir 打包后 wkf/config/settings.py 位于 _internal\wkf\config），
; 首次启动自动创建 settings.json；模板与运行时路径保持一致。
Source: "config\config.ini.example"; DestDir: "{app}\_internal\config"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\新手使用手册"; Filename: "{app}\WKF使用手册.md"; Tasks: startmenu
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

; 卸载清理：配置文件、报告/日志/快照缓存，确保无残留
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal\config"
Type: filesandordirs; Name: "{app}\_internal\output"
Type: filesandordirs; Name: "{app}\_internal\logs"
Type: filesandordirs; Name: "{app}\_internal\cache"
Type: filesandordirs; Name: "{app}\_internal\prompt_engineering"
