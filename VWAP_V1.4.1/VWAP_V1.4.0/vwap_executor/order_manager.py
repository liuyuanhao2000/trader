from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from .config import ExecutionParams, PriceOffsetMode
from .models import Side, SubOrderSpec
from .exchange.base import BestPrices

# 先把一笔大单按时间拆成很多执行时点，再把总金额均匀分到每一笔子订单上；另外还提供了一个根据盘口计算限价单价格的函数。
def _split_notional_equal(total: float, n_slices: int) -> List[float]:
    """
    将 total 平均拆分成 n_slices 份，尽量保证求和误差最小。
    """
    if n_slices <= 0:
        raise ValueError("n_slices must be positive")

    raw = total / n_slices
    parts = [raw for _ in range(n_slices)]

    # 修正累计浮点误差：把差额加到最后一笔
    diff = total - sum(parts)
    parts[-1] += diff
    return parts


@dataclass
class LimitPricePlan:
    limit_price: float # 限价金额
    best_bid: float # 盘口最佳卖价
    best_ask: float # 盘口最佳买价

# 根据盘口计算限价单价格
def compute_limit_price(
    *,
    side: Side,
    best: BestPrices,
    price_offset: float,
    price_offset_mode: PriceOffsetMode,
) -> LimitPricePlan:
    if price_offset_mode != "relative":
        raise ValueError(f"Unsupported price_offset_mode={price_offset_mode}")

    if side == "BUY":
        # 限价：ask * (1 + offset) 买单限价 = 当前卖一价 × (1 + 偏移比例)
        return LimitPricePlan(limit_price=best.ask * (1.0 + price_offset), best_bid=best.bid, best_ask=best.ask)
    # SELL
    return LimitPricePlan(limit_price=best.bid * (1.0 - price_offset), best_bid=best.bid, best_ask=best.ask)

# 生成执行时间表
def build_vwap_schedule(
    start_time: datetime,
    *,
    total_duration_seconds: int,
    order_interval_seconds: int,
) -> List[datetime]:
    if order_interval_seconds <= 0:
        raise ValueError("order_interval_seconds must be positive")
    if total_duration_seconds <= 0:
        raise ValueError("total_duration_seconds must be positive")

    # 示例：20 分钟，1 分钟 => 20 笔
    n_slices = int(total_duration_seconds // order_interval_seconds)
    if n_slices <= 0:
        n_slices = 1

    # 如果不是整除，也至少覆盖整个周期：增加最后一笔
    if total_duration_seconds % order_interval_seconds != 0:
        n_slices += 1

    return [start_time + timedelta(seconds=i * order_interval_seconds) for i in range(n_slices)]

# 把时间表和金额拆分合成子订单计划
def build_sub_orders(
    *,
    symbol: str,
    side: Side,
    notional_total: float,
    start_times: List[datetime],
    execution: ExecutionParams,
) -> List[SubOrderSpec]:
    n_slices = len(start_times)
    notional_parts = _split_notional_equal(notional_total, n_slices)

    specs: List[SubOrderSpec] = []
    for i, t in enumerate(start_times):
        specs.append(
            SubOrderSpec(
                sub_order_index=i,
                scheduled_time=t,
                target_notional=float(notional_parts[i]),
            )
        )
    return specs

