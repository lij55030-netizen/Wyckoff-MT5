# WKF — 威科夫2.0 交易分析智能体

面向主观交易者的 **威科夫（Wyckoff）量价分析** AI 辅助决策工具。与 PA-Agent 的通用价格行为分析不同，WKF 严格按《威科夫2.0 市场结构、成交量分布与订单流》三层框架设计：

```
第一层  威科夫理论    市场处于什么阶段？谁在控制？（吸筹/派发、三大定律）
  ↓
第二层  成交量分布    重要交易区域在哪里？（VAH/VAL/VPOC/VWAP/HVN/LVN）
  ↓
第三层  订单流验证    关键价位上入场信号是否触发？（失衡/吸收/主动）
```

**核心逻辑：先定背景（方向）→ 再定区域（价位）→ 最后验证入场（订单流）。**

---

## 主要功能

- 📊 **三层威科夫分析管线**：背景判定（趋势/区间/吸筹/派发）→ 价值区域定位 → 订单流验证
- 📈 **数据源**：MT5（Windows，K线 + CFD tick 订单流）、yfinance（期货/加密货币）
- 🧠 **AI 增强诊断**：威科夫程序化诊断注入 Prompt，DeepSeek 两阶段分析（市场诊断 → 交易决策）
- 📊 **GUI 可视化**：K线 + 布林带 + VWAP + POC/Value Area 阴影 + RSI 子图 + 威科夫标注
- 💬 **飞书指令通道**：手机飞书发「分析 NQ 15m」→ 自动分析 → 回传结果
- 🔔 **飞书通知**：每次分析完成后自动推送摘要到飞书群

## 关键量化锚点（威科夫2.0 原文数值）

| 锚点 | 数值 |
|------|------|
| 价值区域 VA | ±1 标准差，约 68.2% 成交量 |
| 足迹图失衡 | 200% / 300% / 400%（对角侧 2/3/4 倍） |
| 市场反转三步骤 | 衰竭 → 吸收 → 主动（缺一不可） |
| 价值区域 80% 规则 | 价格成功进入 VA 后大概率到达另一端 |

## 快速开始

```cmd
# 本机已装依赖（PyQt6/pyqtgraph/numpy/openai/MetaTrader5 等）
cd wkf

# 1. 配置 API Key（编辑 config/settings.json）
# 2. 启动 GUI
python run.py

# 3. 命令行单跑分析
python cli.py NQ 15m
python cli.py ES 1h
python cli.py XAU 15m
```

## 目录结构

```
wkf/
├── run.py / cli.py            # 启动入口（GUI / CLI）
├── wkf/
│   ├── data/                  # K线数据结构、MT5 数据源、tick 桥接
│   ├── indicators/            # RSI/布林带/VWAP/EMA/ATR/Delta/Footprint/VolumeProfile
│   ├── wyckoff/               # ★ 威科夫三层分析模块（核心）
│   ├── ai/                    # DeepSeek 客户端 + Prompt 组装
│   ├── gui/                   # PyQt6 图表与主窗口
│   ├── notify/                # 飞书通知 + 指令监听
│   └── config/                # 配置模型
└── tests/                     # 单元测试
```

## 免责声明

本工具仅供学习与研究，不构成投资建议。交易有风险，决策后果自负。采用 AGPL-3.0 许可证。
