from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

Side = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET"]
OrderStatus = Literal["SUBMITTED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED"]
# 告警类型：订单未成交比例、尾盘风险、全局错误、交易标的错误、订单滑点超过阈值
# 其中，"GLOBAL_ERROR", "INSTRUMENT_ERROR"没有相应的报警逻辑，再base.py中有相应预留字段
AlertType = Literal["ORDER_UNFILLED_RATIO", "TAIL_RISK", "GLOBAL_ERROR", "INSTRUMENT_ERROR", "ORDER_SLIPPAGE_LIMIT"]
    


@dataclass
class SubOrderSpec:
    sub_order_index: int
    scheduled_time: datetime
    target_notional: float
    limit_price: Optional[float] = None

# 成交结果
@dataclass
class OrderFill:
    order_id: str
    executed_at: datetime
    order_type: OrderType
    side: Side
    symbol: str # 标的

    ordered_notional: float # 订单名义金额
    filled_notional: float # 成交名义金额
    filled_qty: float # 成交数量
    avg_fill_price: float # 平均成交价

    limit_price: Optional[float] = None # 限价金额
    slippage_ratio: Optional[float] = None  #滑点 |avg_fill - limit|/limit（模拟告警）
    estimated_margin: Optional[float] = None  # 期货：notional / leverage（用于日志追溯）


@dataclass
class Alert:
    alert_time: datetime
    alert_type: AlertType
    symbol: str
    order_id: Optional[str]

    message: str # 告警信息
    unfilled_ratio: Optional[float] = None # 未成交比例
    remaining_unfilled_notional: Optional[float] = None # 剩余未成交名义金额
    extra: Optional[Dict[str, Any]] = None # 额外字段


@dataclass
class OrderLogEntry:
    # 订单执行完整明细（类似结算单）
    sub_order_index: int
    sub_order_time: datetime

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType

    notional: float
    limit_price: Optional[float]
    avg_fill_price: float

    ordered_notional: float
    filled_notional: float
    filled_qty: float

    unfilled_notional: float
    unfilled_ratio: float

    slippage_ratio: Optional[float]
    triggered_alarm: bool
    # 兼容旧字段：单条告警（当同时触发多条时，这里只放“第一条”）
    alarm_type: Optional[str]
    alarm_message: Optional[str]

    # 新字段：支持一笔订单关联多条告警（例如未成交比例 + 滑点同时触发）
    alarm_types: Optional[List[str]] = None
    alarm_messages: Optional[List[str]] = None

    # 额外字段预留
    raw: Optional[Dict[str, Any]] = None

