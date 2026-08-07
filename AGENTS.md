# AGENTS.md — WKF 智能体开发规范

本文件供 AI 编码助手（Claude/Cursor/WorkBuddy 等）在修改 WKF 代码时遵循。

## 项目定位

WKF 是威科夫2.0 交易分析智能体。分析管线严格遵循三层框架，**任何分析输出必须经过三层**：

1. **背景判定**（`wkf/wyckoff/background.py`）：先定性平衡/失衡（趋势 vs 区间），吸筹/派发倾向
2. **价值区域**（`wkf/wyckoff/value_area.py`）：VAH/VAL/VPOC/VWAP/HVN/LVN 客观价位
3. **订单流验证**（`wkf/wyckoff/orderflow_verify.py`）：失衡/吸收/主动，逐K验证入场

跳过任何一层 = 输出不合格。

## 核心约定

- **数值锚点**（不可随意改）：VA=68.2% 成交量（±1σ）；足迹图失衡阈值 200%/300%/400%；反转三步骤 衰竭→吸收→主动；80% 规则
- **数据完整性**：分析具体行情必须先获取真实数据（MT5 K线 + tick），禁止编造行情
- **措辞纪律**：面向用户的结论用条件化措辞（「如果……则……」），只对下一步提概率场景
- **只读原则**：WKF 只做分析，不连接券商、不执行下单、不修改用户仓位
- **订单流数据说明**：MT5 CFD tick 仅有 bid/ask 报价，方向按 Tick Rule 近似分类，成交量以 tick 计数代替——输出必须标注此局限性

## 目录职责

| 目录 | 职责 | 注意事项 |
|------|------|---------|
| `wkf/data/` | K线数据结构、MT5数据源、tick桥接 | 不掺业务逻辑 |
| `wkf/indicators/` | 纯函数指标计算 | 输入序列、输出序列，无状态 |
| `wkf/wyckoff/` | 威科夫三层分析（核心） | 背景→区域→订单流 顺序不可颠倒 |
| `wkf/ai/` | DeepSeek客户端、Prompt组装 | 威科夫诊断段注入用户Prompt |
| `wkf/gui/` | PyQt6 图表与主窗口 | GUI 不直接调 API |
| `wkf/notify/` | 飞书通知与指令监听 | 后台线程，不阻塞主流程 |
| `wkf/config/` | 配置模型 | settings.json 加载/校验 |

## 测试与验证

```cmd
python cli.py NQ 15m          # 命令行跑通完整管线
python tools/test_e2e.py      # 端到端测试
pytest -q                     # 单元测试
```

验收标准：数据→指标→订单流→威科夫三层→AI诊断→输出，全链路无异常。
