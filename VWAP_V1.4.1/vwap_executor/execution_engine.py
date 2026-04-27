from __future__ import annotations

from .config import VwapConfig
from .exchange.base import BaseExchange
from .executors.perp_executor import PerpVwapExecutor
from .executors.spot_executor import SpotVwapExecutor
from .logging_store import TransactionLog
from .risk import RiskManager


class VwapExecutionEngine:
    def __init__(self, *, exchange: BaseExchange, log: TransactionLog | None = None) -> None:
        self.exchange = exchange
        self.log = log or TransactionLog()

    async def run(self, config: VwapConfig):
        risk_manager = RiskManager(
            unfilled_alarm_threshold=config.execution.unfilled_alarm_threshold,
            tail_risk_threshold_ratio=config.execution.tail_risk_threshold_ratio,
            max_slippage=config.execution.max_slippage,
        )

        if config.instrument_type == "spot":
            executor = SpotVwapExecutor(exchange=self.exchange, config=config, log=self.log, risk_manager=risk_manager)
        elif config.instrument_type == "perp":
            executor = PerpVwapExecutor(exchange=self.exchange, config=config, log=self.log, risk_manager=risk_manager)
        else:
            raise ValueError(f"Unsupported instrument_type={config.instrument_type}")

        return await executor.execute()

