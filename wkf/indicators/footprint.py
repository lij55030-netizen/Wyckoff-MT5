"""Footprint 足迹图：逐价位买卖量分布 + 失衡检测（威科夫2.0 阈值）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FootprintBar:
    price_levels: dict[float, dict[str, float]]  # price -> {bid, ask}
    delta: float
    total_volume: float
    poc_price: float


def build_footprint(ticks: list[Any], tick_size: float = 0.25) -> FootprintBar | None:
    """按中间价量化，累积每价位的 buy(bid) / sell(ask) 量。"""
    if not ticks:
        return None

    levels: dict[float, dict[str, float]] = {}
    for t in ticks:
        price = round(float(getattr(t, "mid_price", 0.0)) / tick_size) * tick_size
        side = getattr(t, "side", "buy")
        vol = float(getattr(t, "volume", 1.0))
        d = levels.setdefault(price, {"bid": 0.0, "ask": 0.0})
        if side == "buy":
            d["bid"] += vol
        else:
            d["ask"] += vol

    delta = sum(d["bid"] - d["ask"] for d in levels.values())
    total = sum(d["bid"] + d["ask"] for d in levels.values())
    poc = max(levels, key=lambda p: sum(levels[p].values())) if levels else 0.0
    return FootprintBar(price_levels=levels, delta=delta, total_volume=total, poc_price=poc)


def get_imbalances(
    fp: FootprintBar,
    thresholds: tuple[float, ...] = (2.0, 3.0, 4.0),
) -> list[dict]:
    """检测每价位失衡。

    威科夫2.0：失衡最低参数 200%/300%/400%（失衡侧是对角侧 2/3/4 倍）。
    返回 [{price, ratio, side, level}]，level 1/2/3 对应 2x/3x/4x。
    """
    out: list[dict] = []
    for price, vols in fp.price_levels.items():
        bid = vols["bid"]
        ask = vols["ask"]
        if bid <= 0 or ask <= 0:
            continue
        ratio = bid / ask
        if ratio >= thresholds[2]:
            out.append({"price": price, "ratio": round(ratio, 2), "side": "buy", "level": 3})
        elif ratio >= thresholds[1]:
            out.append({"price": price, "ratio": round(ratio, 2), "side": "buy", "level": 2})
        elif ratio >= thresholds[0]:
            out.append({"price": price, "ratio": round(ratio, 2), "side": "buy", "level": 1})

        ratio_inv = ask / bid
        if ratio_inv >= thresholds[2]:
            out.append({"price": price, "ratio": round(ratio_inv, 2), "side": "sell", "level": 3})
        elif ratio_inv >= thresholds[1]:
            out.append({"price": price, "ratio": round(ratio_inv, 2), "side": "sell", "level": 2})
        elif ratio_inv >= thresholds[0]:
            out.append({"price": price, "ratio": round(ratio_inv, 2), "side": "sell", "level": 1})
    out.sort(key=lambda x: x["price"])
    return out


def detect_stacked_imbalances(
    imbalances: list[dict],
    tick_size: float = 0.25,
    min_stack: int = 2,
) -> list[list[dict]]:
    """检测连续价位上的同向失衡（堆叠失衡）。"""
    stacks: list[list[dict]] = []
    cur: list[dict] = []
    prev_price: float | None = None
    for item in imbalances:
        if prev_price is None or abs(item["price"] - prev_price) <= tick_size * 1.01:
            if cur and cur[-1]["side"] == item["side"]:
                cur.append(item)
            else:
                if len(cur) >= min_stack:
                    stacks.append(cur)
                cur = [item]
        else:
            if len(cur) >= min_stack:
                stacks.append(cur)
            cur = [item]
        prev_price = item["price"]
    if len(cur) >= min_stack:
        stacks.append(cur)
    return stacks


def footprint_to_dict(fp: FootprintBar, top_n: int = 8) -> dict:
    """序列化为可注入 Prompt 的摘要。"""
    if fp is None:
        return {}
    levels = sorted(fp.price_levels.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
    top = [
        {"price": p, "bid": d["bid"], "ask": d["ask"], "total": d["bid"] + d["ask"]}
        for p, d in levels[:top_n]
    ]
    return {
        "delta": fp.delta,
        "total_volume": fp.total_volume,
        "poc": fp.poc_price,
        "top_levels": top,
    }
