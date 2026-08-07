"""WKF 威科夫三层分析模块（核心）。

严格按《威科夫2.0》框架：
  第一层  背景判定：平衡/失衡、吸筹/派发倾向
  第二层  价值区域：VAH/VAL/VPOC/VWAP/HVN/LVN
  第三层  订单流验证：失衡/吸收/主动

使用方式：``analyze(frame) -> WyckoffAnalysis``。
"""
