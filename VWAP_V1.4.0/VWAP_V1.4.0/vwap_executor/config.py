from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Literal, Optional
from .models import Side, OrderType


PriceOffsetMode = Literal["relative"]  # price_offset 是相对比例：0.001 => +0.1%
ReduceOnlyMode = Literal["never", "always"] # 是否允许减仓


@dataclass
class CommonInput:
    symbol: str
    side: Side
    notional: float  # 计价货币名义金额
    start_time: datetime
    quote_currency: str
    base_currency: str


@dataclass
class ExecutionParams:
    total_duration_seconds: int
    order_interval_seconds: int

    # 限价价格偏移：BUY => ask * (1 + offset)，SELL => bid * (1 - offset)
    price_offset: float
    price_offset_mode: PriceOffsetMode = "relative"

    # 在模拟撮合里用于告警：|avg_fill - limit| / limit
    max_slippage: float = 0.01

    # 每笔子订单的未成交比例告警阈值（未成交金额/订单金额）
    unfilled_alarm_threshold: float = 0.10

    # 记录粒度：目前实现为每笔子订单都落盘；保留字段可扩展
    record_granularity: Literal["per_order"] = "per_order"

    # 允许尾盘提前触发：当剩余时间 <= tail_force_early_seconds 时，触发尾盘市价强制完成
    tail_force_early_seconds: int = 0

    # 尾盘风险：若强制完成前剩余未成交金额占初始总金额比例 > 该阈值，触发全局告警
    tail_risk_threshold_ratio: float = 0.10

    # 市价强制成交的额外冲击/滑点（模拟用）
    tail_market_slippage: float = 0.002

    # 现货 SELL 时的策略：不足持仓时是否截断到最多可卖
    spot_sell_truncate_to_holdings: bool = True

    # 期货：杠杆倍数；保证金占用 = notional / leverage
    leverage: int = 1

    # 交易所合约换算（用于从“名义金额”推导数量/合约）
    # 合约每手对应的标的数量（例如合约单位不同交易所用不同手数定义时，可配置）
    contract_multiplier: float = 1.0

    # 若要限制撮合噪声/撮合难度（模拟用）
    mock_fill_sensitivity: float = 0.10

    # 是否开启调试日志
    debug: bool = False


@dataclass
class LogStorage:
    # 输出为 JSONL：每行一条订单/告警
    output_jsonl_path: Optional[str] = None


@dataclass
class AlertingConfig:
    # 同一条告警是否输出到标准输出（模拟中用于演示）
    print_alerts: bool = True


@dataclass
class ExchangeConfig:
    # 默认使用模拟撮合器，便于本地跑通
    adapter: Literal["mock", "binance_spot_testnet"] = "mock"

    # Binance testnet 交易所地址
    binance_base_url: str = "https://testnet.binance.vision"

    # LIMIT 订单：下单后最多等待/轮询多少秒取成交
    limit_order_poll_seconds: float = 1.5

    # 余额接口缓存，降低频率（模拟用）
    balance_cache_ttl_seconds: int = 5


@dataclass
class VwapConfig:
    common: CommonInput
    execution: ExecutionParams

    # 交易类型：spot/ perp（现货/永续合约）
    instrument_type: Literal["spot", "perp"]

    # 期货：合约类型（当前仅支持 U 本位永续）
    contract_type: Literal["USDT_perpetual"] = "USDT_perpetual"

    log_storage: LogStorage = field(default_factory=LogStorage)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)

    @staticmethod
    def _parse_datetime(v: str) -> datetime:
        # 支持 ISO8601：2026-04-02T15:30:00
        return datetime.fromisoformat(v)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "VwapConfig":
        common = raw["common"]
        execution = raw["execution"]

        cfg = cls(
            instrument_type=raw["instrument_type"],
            common=CommonInput(
                symbol=common["symbol"],
                side=common["side"],
                notional=float(common["notional"]),
                start_time=cls._parse_datetime(common["start_time"]),
                quote_currency=common.get("quote_currency", "USDT"),
                base_currency=common.get("base_currency", "BTC"),
            ),
            execution=ExecutionParams(**execution),
            contract_type=raw.get("contract_type", "USDT_perpetual"),
            log_storage=LogStorage(**raw.get("log_storage", {})),
            alerting=AlertingConfig(**raw.get("alerting", {})),
            exchange=ExchangeConfig(**raw.get("exchange", {})),
        )
        return cfg

    @classmethod
    def from_json_file(cls, path: str) -> "VwapConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw)


def env_get_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


