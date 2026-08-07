; ============================================================
; WKF 威科夫交易智能体 V2.4 — 一键安装包脚本
; 编译: ISCC.exe WKF_installer.iss
; 产物: installer\WKF_V2.4_Setup.exe
; ============================================================
#define MyAppName "WKF 威科夫交易智能体"
#define MyAppVersion "2.4.0"
#define MyAppExeName "Wyckoff_Analysis_GUI.exe"

[Setup]
AppId={{8E5C2F1A-7B3D-4E2A-9C4F-1D2B3C4D5E6F}
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
OutputBaseFilename=WKF_V1.3.0_Setup
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked
Name: "startmenu"; Description: "创建开始菜单入口"; GroupDescription: "附加任务:"

[Files]
; 三个主程序（PyInstaller 单文件，内嵌 Python 解释器）
Source: "dist\Wyckoff_Analysis_GUI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Wyckoff_CLI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Wyckoff_Feishu_Bot.exe"; DestDir: "{app}"; Flags: ignoreversion
; 新手使用手册与快捷启动
Source: "WKF使用手册.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "启动GUI.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "启动CLI.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "启动飞书机器人.bat"; DestDir: "{app}"; Flags: ignoreversion
; 配置模板（不含任何真实密钥，首次启动弹窗引导配置）
Source: "config\config.ini.example"; DestDir: "{app}\config"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\新手使用手册"; Filename: "{app}\WKF使用手册.md"; Tasks: startmenu
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

; 卸载清理：配置文件、报告/日志/快照缓存，确保无残留
[UninstallDelete]
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\output"
Type: filesandordirs; Name: "{app}\logs"
