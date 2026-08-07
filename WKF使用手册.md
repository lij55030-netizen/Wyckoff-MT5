# WKF 使用手册（V1.0）

> WKF = Wyckoff Framework · 威科夫三层量化分析系统
> 项目位置：`E:\workbuddy\MT50802\wkf\`
> GitHub：https://github.com/lij55030-netizen/Wyckoff-MT5-Workbuddy

---

## 一、保存在哪里

```
E:\workbuddy\MT50802\wkf\
├── cli.py                    # 命令行入口
├── run.py                    # GUI 入口
├── build_exe.bat             # EXE 打包脚本
├── config/
│   ├── settings.json         # 主配置（含 DeepSeek Key / 飞书 Webhook）
│   └── config.ini.example    # 配置文件模板（复制为 config.ini 可覆盖 settings.json）
├── dist/                     # ★ 打包好的 EXE 都在这里
│   ├── Wyckoff_Analysis_GUI.exe   (119M, GUI 面板)
│   ├── Wyckoff_CLI.exe            (115M, 命令行)
│   └── Wyckoff_Feishu_Bot.exe     (115M, 飞书机器人)
├── output/                   # ★ 分析报告输出目录（HTML 报告自动生成在这里）
├── tools/feishu_commander.py # 飞书指令监听器（源码版）
└── wkf/                      # 核心代码（数据/指标/威科夫/AI/GUI/飞书）
```

---

## 二、如何打开（三种方式）

### 方式 A：可视化面板（推荐，Windows 桌面）
**双击** `E:\workbuddy\MT50802\wkf\dist\Wyckoff_Analysis_GUI.exe`
- 界面：品种下拉框（NQ/ES/XAU）+ 周期下拉框（5m/10m/15m/30m/1h）+ 「▶ 分析」按钮
- 选择品种和周期 → 点击分析 → 上方 K 线图（含布林带/VWAP/POC/价值区域阴影/RSI 子图），下方显示威科夫三层分析 + AI 诊断结果

### 方式 B：命令行（终端）
```
cd E:\workbuddy\MT50802\wkf
python cli.py NQ 15m        # 分析 NQ 15分钟
python cli.py ES 5m
python cli.py XAU 1h
python cli.py NQ 30m --no-ai   # 跳过 AI（纯规则模式）
```
或用 EXE：`dist\Wyckoff_CLI.exe NQ 15m`

### 方式 C：飞书机器人（手机远程）
```
python tools/feishu_commander.py      # 启动监听（或运行 Wyckoff_Feishu_Bot.exe）
```
然后在手机飞书里给「王柏淏的飞书 CLI」发指令（见下文指令表）。

---

## 三、飞书指令表

| 类型 | 指令示例 | 说明 |
|------|---------|------|
| 单品种单周期 | `分析 NQ 15m` | 3品种×5周期任意组合 |
| 全周期复盘 | `NQ 全周期复盘` | 5m/10m/15m/30m/1h 全跑一遍 |
| 三品种汇总 | `三品种全周期汇总` | 三个品种全部周期汇总（15次分析） |
| 关键价位 | `XAU 关键价位 30m` | 只输出 VA/VPOC/VWAP/HVN/LVN |
| 订单流拐点 | `ES 订单流拐点 5m` | 只输出失衡/堆叠失衡/反转阶段 |
| 多空定性 | `NQ 多空定性 15m` | 一句话结论 |
| HTML 报告 | `推送最新html行情报告` | 生成最新报告 |
| 帮助 | `帮助` | 显示指令手册 |

---

## 四、如何配置

### 1. DeepSeek API Key（AI 分析必需）
- 已配置在 `config/settings.json` → `provider.api_key`
- 或复制 `config/config.ini.example` 为 `config/config.ini` 填写，优先级更高
- **不配置 Key 时自动切换纯规则模式**（只出威科夫三层分析，无 AI 诊断）

### 2. 飞书 Webhook（通知 + 指令）
- 已配置在 `settings.json` → `feishu.webhook_url`（用于分析完成通知）
- 指令监听依赖 WorkBuddy 飞书连接（lark-cli），手机端给「王柏淏的飞书 CLI」发消息

### 3. 硬性前置
- ✅ 本机安装 **MetaTrader5** 并登录 GTC 账户（含 USTECHc/US500c/XAUUSD 三个 CFD 品种）
- ✅ 可联网访问 DeepSeek API（api.deepseek.com）

---

## 五、报告输出

每次分析自动在 `output/` 生成 HTML 报告：
```
E:\workbuddy\MT50802\wkf\output\wkf_report_YYYYMMDD_HHMMSS.html
```
用浏览器打开即可查看完整图表 + 分析结论。

---

## 六、常见问题

| 问题 | 解决 |
|------|------|
| EXE 双击没反应 | EXE 需与 `config/` 同目录放置；先确认 MT5 已登录 |
| 提示 MT5 无数据 | 检查 MT5 账户是否为 GTC（Exness 账户没有 US500c 等品种） |
| AI 诊断为空 | 检查 DeepSeek Key 是否有效、网络是否可达 |
| 飞书机器人收不到指令 | 确认 WorkBuddy 飞书连接在线；重启 feishu_commander.py |

---

*WKF 仅供学习研究，不构成投资建议。交易有风险，决策后果自负。*
