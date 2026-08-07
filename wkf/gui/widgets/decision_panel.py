"""决策面板（原 main_window 决策标签页渲染逻辑拆分）。

【改动点】需求一.1：架构重构——主窗口渐进式拆分。
本文件承载「决策」标签页：富文本渲染（四段 + 概率总结），
以及行情概率测算（compute_probabilities，纯函数，供决策面板/提示音/飞书共用）。
仅做渲染与确定性测算，不改变任何威科夫核心逻辑。
【涉及文件】wkf/gui/widgets/decision_panel.py（新增，自 main_window 抽出）
【验证方式】python -m unittest discover tests；执行分析后决策页显示四段+红色粗体概率总结；
            订单流区块顶部有 Tick 近似换算风险提示。
"""
from __future__ import annotations

import html

from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from wkf.util.timefmt import beijing_now_str


def compute_probabilities(wa) -> dict:
    """行情概率测算（确定性规则，完全基于 wa 现有盘面字段，可复现、不虚构）。

    依据：
      ① 趋势结构：regime + HH+HL / LH+LL 摆动计数
      ② 订单流状态：active_side（买/卖方主导）+ reversal_stage
      ③ VWAP 位置：现价高于/低于 VWAP（决定多空承压方向）
    输出：空头/多头/震荡观望 三个概率（和为 100%）。
    """
    long_p, short_p, neutral_p = 33.0, 33.0, 34.0  # 中性基线

    bg = wa.background
    # ① 趋势结构
    if bg.regime == "trend_up":
        long_p += 15 + min(bg.hh_hl_count, 5) * 3
        short_p -= 8
    elif bg.regime == "trend_down":
        short_p += 15 + min(bg.lh_ll_count, 5) * 3
        long_p -= 8
    elif bg.regime == "range":
        neutral_p += 20
        long_p -= 8
        short_p -= 8

    # ② 订单流状态
    if wa.orderflow is not None:
        of = wa.orderflow
        if of.active_side == "buy":
            long_p += 8
        elif of.active_side == "sell":
            short_p += 8
        if of.reversal_stage == "absorption":
            # 吸收阶段：多空趋于平衡，增加震荡权重
            neutral_p += 5
            long_p -= 2
            short_p -= 3

    # ③ VWAP 位置（价格承压/支撑方向）
    if wa.value_area is not None and wa.value_area.vwap is not None and wa.price is not None:
        if wa.price > wa.value_area.vwap:
            long_p += 6
        elif wa.price < wa.value_area.vwap:
            short_p += 6

    # 归一化到 100%（截断负值后按比例缩放）
    long_p = max(0.0, long_p)
    short_p = max(0.0, short_p)
    neutral_p = max(0.0, neutral_p)
    total = long_p + short_p + neutral_p
    if total <= 0:
        return {"short": 33, "long": 33, "neutral": 34}
    long_pct = round(long_p / total * 100)
    short_pct = round(short_p / total * 100)
    neutral_pct = 100 - long_pct - short_pct  # 保证三项合计恒为 100
    return {"short": short_pct, "long": long_pct, "neutral": neutral_pct}


# 【改动点】订单流风险提示固定文案（GUI 决策面板顶部；与文件头/HTML报告/飞书同文案）
# 吸收结构补充说明：由 放量 + 窄幅震荡 + Delta背离 三重条件共同判定，非单纯放量K线。
ORDERFLOW_RISK_NOTICE = (
    "⚠ 订单流由 MT5 Tick 数据近似换算生成，并非交易所原始盘口订单流，"
    "仅用于威科夫结构定性研判，不建议作为高频短线交易依据。"
    "吸收结构由放量+窄幅震荡+Delta背离共同判定，非单纯放量K线。"
)


class DecisionPanel(QWidget):
    """决策标签页：富文本四段决策 + 底部行情概率总结（红色粗体）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QTextEdit()  # 决策页：富文本（红色粗体核心结论）
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "QTextEdit{background-color:#0f1419;color:#e6edf3;border:none;font-size:13px;}"
        )
        layout.addWidget(self.view)

    def render(self, wa, analysis_time: str = "", prob: dict | None = None) -> None:
        """渲染决策面板。wa 为威科夫分析结果；analysis_time 为本次分析时间。"""
        self.view.setHtml(self._build_html(wa, analysis_time, prob))

    def _build_html(self, wa, analysis_time: str = "", prob: dict | None = None) -> str:
        """决策标签页 HTML（文案规范化）：行情倾向/入场触发/失效阈值/订单流结构/备注。

        严格写实：全部内容仅基于 wa 中已计算出的盘面数据陈述，不做行情预判与夸大推演；
        核心结论（行情倾向）使用红色粗体标注。
        """
        if wa is None:
            return "未分析"
        bias_zh = {"long": "多头", "short": "空头", "neutral": "中性"}.get(wa.bias, wa.bias)
        regime_zh = {
            "trend_up": "上升趋势", "trend_down": "下降趋势",
            "range": "区间震荡", "unknown": "结构不明",
        }.get(wa.background.regime, wa.background.regime)
        bg = wa.background

        p = []
        p.append("<div style='font-size:13px;line-height:1.8'>")
        # 【改动点】V1.3.3：决策面板头部固定文字「决策生成时间：{YYYY-MM-DD HH:mm:ss}」。
        # 使用本地系统时间（北京时间，与顶部时钟同一时间源）。
        # 修复：仅"获取数据"（未提交分析）时 analysis_time 为空，
        # 此前时间块被整体跳过；现改为空值自动取当前时间兜底，保证始终显示。
        atime = analysis_time or beijing_now_str()
        p.append(
            f"<p style='margin:0 0 8px;padding:6px 10px;background:#161d26;border-left:3px solid #f59e0b'>"
            f"<b style='color:#f59e0b'>🕐 决策生成时间：</b>"
            f"　<span style='color:#e6edf3'>{atime}</span></p>"
        )
        p.append("<p style='margin:2px 0 8px'><b style='color:#8b949e'>交易决策（基于当前盘面数据，严格写实）</b></p>")

        # ① 行情倾向 —— 核心结论：红色粗体
        p.append("<p style='margin:6px 0 2px'><b style='color:#e6edf3'>① 行情倾向</b></p>")
        p.append(
            f"<p style='margin:2px 0'><b><span style='color:#ef4444;font-size:15px'>{bias_zh}</span></b>"
            f"　<span style='color:#8b949e'>背景：{regime_zh}（HH+HL {bg.hh_hl_count} 组 / LH+LL {bg.lh_ll_count} 组）</span></p>"
        )

        # ② 入场触发条件（点位红色加粗高亮）
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>② 入场触发条件</b></p>")
        p.append(
            f"<p style='margin:2px 0'><b><span style='color:#ef4444'>{html.escape(wa.trigger)}</span></b></p>"
        )

        # ③ 失效硬阈值（风控点位红色加粗高亮）
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>③ 失效硬阈值</b></p>")
        p.append(
            f"<p style='margin:2px 0'><b><span style='color:#ef4444'>{html.escape(wa.invalidation)}</span></b></p>"
        )

        # ④ 订单流结构
        p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>④ 订单流结构</b></p>")
        # 【改动点】订单流面板顶部固定风险提示（Tick 近似换算，非原始盘口）
        p.append(
            f"<p style='margin:2px 0 6px;color:#8b949e;font-size:12px'>{ORDERFLOW_RISK_NOTICE}</p>"
        )
        if wa.orderflow is not None:
            of = wa.orderflow
            # 订单流文本本地化汉化：活跃方/反转阶段英文→中文
            side_zh = {"buy": "买方", "sell": "卖方", "none": "无"}.get(
                str(of.active_side).lower(), str(of.active_side))
            stage_zh = {
                "absorption": "吸收", "accumulation": "吸筹", "distribution": "派发",
                "markup": "拉升", "markdown": "下跌", "active": "活跃", "none": "无",
            }.get(str(of.reversal_stage).lower(), str(of.reversal_stage))
            p.append(
                f"<p style='margin:2px 0;color:#e6edf3'>活跃方：{side_zh}　|　反转阶段：{stage_zh}"
                f"　|　失衡 {len(of.imbalances)} 处　|　堆叠 {len(of.stacked_imbalances)} 组</p>"
            )
        else:
            p.append("<p style='margin:2px 0;color:#8b949e'>无订单流数据（Tick 数据不足）</p>")

        # 备注
        if wa.notes:
            p.append("<p style='margin:8px 0 2px'><b style='color:#e6edf3'>⑤ 备注</b></p>")
            for n in wa.notes:
                # 备注汉化：吸收阶段固定文案 + 其余英文关键词替换为中文
                note = html.escape(n)
                if wa.orderflow is not None and str(wa.orderflow.reversal_stage).lower() == "absorption":
                    note = "订单流处于反转「吸收」阶段，尚需主动行为确认"
                else:
                    for en, zh in (
                        ("absorption", "吸收"), ("accumulation", "吸筹"),
                        ("distribution", "派发"), ("buy", "买方"), ("sell", "卖方"),
                    ):
                        note = note.replace(en, zh)
                p.append(f"<p style='margin:2px 0;color:#8b949e'>· {note}</p>")

        # ── 底部：行情概率总结（基于本页盘面结论的确定性测算，红色加粗）────
        if prob is None:
            prob = compute_probabilities(wa)
        p.append(
            "<p style='margin:10px 0 2px;border-top:1px solid #2a3442;padding-top:8px'>"
            "<b style='color:#ef4444;font-size:14px'>"
            f"当前盘面综合研判：空头行情概率 {prob['short']}%，多头行情概率 {prob['long']}%，震荡观望概率 {prob['neutral']}%"
            "</b></p>"
        )

        p.append("</div>")
        return "".join(p)

    def toPlainText(self) -> str:
        return self.view.toPlainText()
