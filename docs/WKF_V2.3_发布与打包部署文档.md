# WKF 威科夫交易智能体 V2.3 —— 发布与打包部署文档

> 本文档共三部分，相互独立：① GitHub Release 发布文案（面向零基础用户）；② 纯记事本打包部署说明（面向开发者）；③ 精简版仓库 README。
> 术语首次出现均附通俗解释，正文采用发布语气。

---

## 一、GitHub Release 发布文案（小白版）

### 产品定位

**WKF 威科夫交易智能体** 是一款纯图形化、一键安装的 K 线智能分析工具。安装包已内置 Python 运行环境、全部依赖库与配置文件——**无需 CMD、无需环境变量、无需源码操作**，全程鼠标点击即可完成安装与使用。

> 术语解释：**K 线**（蜡烛图）是记录某段时间内开盘价、最高价、最低价、收盘价的价格图形；**CMD** 即 Windows 命令行窗口。

### 安装包特性

- **自定义安装路径**：安装时可自由选择安装目录，不污染系统盘。
- **桌面 / 开始菜单快捷方式**：安装完成后自动创建，双击即用。
- **可视化改参面板**：在软件界面中直接调整 AI 模型、飞书通知、指标参数等设置，无需编辑任何文件。
- **内置卸载程序**：通过「开始菜单 → WKF → 卸载」一键完整移除，不留残留。

### 安装与使用流程（按步骤）

1. **下载安装包**：前往本仓库 **Releases** 页面，下载 `WKF_V2.3_Setup.exe`。
2. **安装**：双击安装包 → 跟随安装向导 → 点击「下一步」直至完成。
3. **启动**：双击桌面「WKF 威科夫交易智能体」快捷方式。
4. **连接行情**：打开 MetaTrader 5（简称 **MT5**，一款外汇/指数/贵金属交易终端）并登录交易账户，WKF 将自动连接并获取实时行情。
5. **选择品种与周期**：
   - 品种：NQ（纳斯达克100）、ES（标普500）、XAU（黄金）。
   - 周期（单根 K 线代表的时间长度）：**1 / 2 / 3 / 4 / 5 / 10 / 15 / 20 / 30 / 60 分钟、1H / 2H / 3H / 4H、1DAY**。
6. **获取数据**：点击「🔄 获取数据」，图表立即载入所选品种与周期的历史行情。
7. **（可选）开启辅助工具**：
   - **十字光标**：点击「➕ 十字光标」，鼠标在图表上移动时显示十字辅助线，精确查看任意 K 线的开高低收与时间戳。
   - **价格标线**：图表右侧实时显示红色最新价水平线与价格标签，随行情自动刷新。
8. **提交分析**：点击「📝 提交分析」，系统执行威科夫三层分析（结构判定 → 价值区域 → 订单流验证）并生成 AI 增强诊断。
9. **查看多空概率**：在「🎯 决策」面板底部查看**红色加粗**的行情概率总结（空头 / 多头 / 震荡，三项合计 100%）。
10. **查看推理过程**：在「🤖 问 AI」面板查看完整推理步骤与本次分析消耗的 **Token** 数量（Token 是 AI 回复的计量单位，1 Token 约等于 1 个汉字）。

### 重要说明

- **仅对接 MT5**：行情数据全部来自本机 MT5 终端，不依赖任何第三方行情源。
- **功能与源码版完全一致**：安装包与 GitHub 源码运行效果 1:1 对齐。
- **配置保存位置**：所有设置（AI 模型、飞书通知、指标参数等）保存在安装目录下的 `/config/` 文件夹中，卸载后一并移除。

---

## 二、纯记事本打包部署说明（开发者版）

> 以下步骤面向开发者，使用纯文本编辑工具（记事本）即可完成全部配置与打包。

### 1. 打包目标

产出三个独立 EXE 与一个图形化安装包，覆盖全部使用场景：

| 产物 | 说明 |
|---|---|
| `Wyckoff_Analysis_GUI.exe` | 桌面可视化面板（无控制台窗口） |
| `Wyckoff_CLI.exe` | 命令行分析工具 |
| `Wyckoff_Feishu_Bot.exe` | 飞书指令机器人常驻服务 |
| `WKF_V2.3_Setup.exe` | 一键图形化安装向导（Inno Setup） |

### 2. 核心要点

**① PyInstaller 打包独立 EXE（内嵌 Python 解释器）**

```bat
:: GUI 面板（无黑窗口）
pyinstaller -F -w -n Wyckoff_Analysis_GUI run.py

:: 命令行工具（保留控制台日志）
pyinstaller -F -n Wyckoff_CLI cli.py

:: 飞书机器人（保留控制台日志）
pyinstaller -F -n Wyckoff_Feishu_Bot tools/feishu_commander.py
```

- `-F`：打包为单文件；`-w`：隐藏控制台窗口。
- 打包后 EXE 已内嵌 Python 解释器与全部依赖，目标机器**无需安装 Python**。

**② Inno Setup 制作图形化安装向导**

编写 `WKF_installer.iss` 脚本（Inno Setup 安装程序，免费开源），配置项包括：

```ini
[Setup]
AppName=WKF 威科夫交易智能体
AppVersion=2.3
DefaultDirName={pf}\WKF 威科夫交易智能体   ; 支持安装时自定义路径
PrivilegesRequired=lowest                 ; 无需管理员权限

[Files]
Source: "dist\Wyckoff_Analysis_GUI.exe"; DestDir: "{app}"
Source: "dist\Wyckoff_CLI.exe"; DestDir: "{app}"
Source: "dist\Wyckoff_Feishu_Bot.exe"; DestDir: "{app}"

[Icons]
Name: "{autodesktop}\WKF 威科夫交易智能体"; Filename: "{app}\Wyckoff_Analysis_GUI.exe"
Name: "{group}\卸载 WKF"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\config"   ; 卸载时清理配置目录
```

- **自定义安装路径**、**桌面/开始菜单快捷方式**、**内置卸载程序**均由 Inno Setup 原生支持。
- 卸载脚本额外清理 `/config/` 目录，确保卸载无残留。

**③ 整合资源与默认配置**

将运行所需的资源与默认配置随安装包分发，放置于安装目录：

```
{app}\
├── Wyckoff_Analysis_GUI.exe / Wyckoff_CLI.exe / Wyckoff_Feishu_Bot.exe
├── config\
│   ├── CROSSHAIR_CFG.json      ; 十字光标配置（颜色/线宽/标签显隐）
│   ├── LAST_PRICE_CFG.json     ; 实时价格标线配置（颜色/线宽/货币单位）
│   └── settings.json           ; 主配置（AI 模型/飞书通知/指标参数）
└── output\                     ; 分析报告输出目录（运行时自动创建）
```

- 配置外置为 JSON：程序启动时读取 `/config/` 下配置文件，用户可在「⚙ 设置」菜单可视化修改，修改结果写回同目录 JSON。
- Inno Setup `[Files]` 段将 `config\` 目录整体复制进安装目录。

**④ 打包后全功能校验清单**

发布前必须逐项验证（在**未安装 Python 的干净机器**上执行）：

- [ ] 安装向导可正常安装至自定义路径，桌面/开始菜单快捷方式生成。
- [ ] GUI 启动、MT5 自动连接、行情显示正常。
- [ ] 周期下拉完整包含 1/2/3/4/5/10/15/20/30/60 分钟、1H/2H/3H/4H、1DAY。
- [ ] 获取数据、提交分析、红色加粗概率总结、问 AI 面板推理与 Token 统计全部可用。
- [ ] 十字光标、实时价格标线开关与视觉反馈正常。
- [ ] 修改配置后重启，配置持久化（写回 `/config/*.json`）。
- [ ] 卸载程序完整移除程序与配置，无残留。

### 3. GitHub 发布操作

1. 进入仓库 → 右侧「Releases」→「Draft a new release」（新建发布）。
2. 填写发布信息：
   - **Tag**：`v2.3`（点击「Choose a tag」输入并创建）。
   - **标题**：`V2.3 One-Click Install Release`。
   - 正文：粘贴「第一部分：GitHub Release 发布文案」内容。
3. 上传安装包：将 `WKF_V2.3_Setup.exe` 拖入附件区上传。
4. 点击「Publish release」完成发布，用户即可在 Releases 页面下载。

### 4. 版本约束

- **功能 1:1 对齐**：V2.3 发布版必须包含本版本全部新增功能（十字光标、实时价格标线、决策概率总结、AI 日志与 Token 统计）以及历史所有已优化功能，与源码版完全一致，不得缺漏。
- 任何源码改动后必须重新打包并复跑「②-④ 全功能校验」，确认无回归再发布。

---

## 三、精简版仓库 README

# WKF 威科夫交易智能体

基于威科夫（Wyckoff）量价理论的 MT5 K 线智能分析工具：纯图形化操作，一键安装，AI 辅助研判多空概率。

> 术语解释：**威科夫理论**是一套通过成交量与价格结构判断市场主力行为（吸筹/派发）的分析方法。

### 🚀 小白快速上手

**前往 [Releases](https://github.com/lij55030-netizen/Wyckoff-MT5-Workbuddy/releases) 下载一键安装包**（`WKF_V2.3_Setup.exe`），双击安装后即可使用——无需安装 Python、无需命令行、无需修改任何文件。

前置条件：本机安装并登录 **MetaTrader 5（MT5）** 交易终端。

### ✨ 主要功能

- **威科夫结构判定**：自动识别趋势/区间、吸筹/派发背景，输出结构结论。
- **VWAP / 订单流解析**：成交量加权均价（VWAP，即按成交量加权计算的平均价格）与逐笔买卖力量（Delta）可视化。
- **半自动交易决策**：输出入场触发、失效硬阈值与多空概率总结（红色加粗显示）。
- **十字光标 / 价格标线**：图表辅助工具，悬停查看任意 K 线开高低收，实时标注最新成交价。
- **概率总结与 AI 日志记录**：决策面板底部概率测算 + 问 AI 面板完整推理流程与 Token 消耗。

### 🛠 源码部署（进阶用户）

```bash
git clone https://github.com/lij55030-netizen/Wyckoff-MT5-Workbuddy.git
cd Wyckoff-MT5-Workbuddy
pip install -r requirements.txt          # 安装依赖
python cli.py NQ 15m                      # 命令行分析
python run.py                             # 启动桌面面板
```

- 需要 Python 3.11+；行情数据来自本机 MT5 终端，需先行登录。
- 详细说明见 `WKF使用手册.md` 与 `docs/` 目录。

---

**署名：向美**
