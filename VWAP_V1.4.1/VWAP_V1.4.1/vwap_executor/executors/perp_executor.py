from __future__ import annotations

import uuid

from ..config import VwapConfig
from ..exchange.base import BaseExchange
from ..logging_store import TransactionLog
from ..models import OrderFill, OrderLogEntry, Side, SubOrderSpec
from ..risk import RiskManager
from .base_executor import VwapBaseExecutor


class PerpVwapExecutor(VwapBaseExecutor):
    """
    期货模块（仅本版本支持 U 本位永续）。

    - 输入 notional 视为名义价值
    - 保证金 = notional / leverage
    - 做多/做空都允许（允许负仓位，放给交易所撮合/保证金风控）
    """

    def __init__(
        self,
        *,
        exchange: BaseExchange,
        config: VwapConfig,
        log: TransactionLog,
        risk_manager: RiskManager,
    ) -> None:
        super().__init__(exchange=exchange, config=config, log=log, risk_manager=risk_manager)

    def _submit_single_limit(self, *, spec: SubOrderSpec, limit_price: float) -> OrderFill:
        common = self.config.common
        execution = self.config.execution

        notional_to_send = float(spec.target_notional)

        # 期货对“保证金占用”做显式计算（本版本仅用于日志/告警，不做强制风控）
        margin = notional_to_send / max(1e-12, float(execution.leverage))

        client_order_id = f"perp-{common.symbol}-{spec.sub_order_index}-{uuid.uuid4().hex[:8]}"
        fill = self.exchange.place_limit_order(
            symbol=common.symbol,
            side=common.side,
            notional=notional_to_send,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )

        # 把保证金写入成交对象，方便基类统一写入日志 raw 字段。
        fill.estimated_margin = float(margin)
        return fill

    async def _force_tail_market_fill(
        self, *, remaining_unfilled_notional: float, executed_notional_so_far: float
    ) -> float:
        common = self.config.common
        execution = self.config.execution

        if remaining_unfilled_notional <= 0:
            return 0.0

        notional_to_send = float(remaining_unfilled_notional)
        margin = notional_to_send / max(1e-12, float(execution.leverage))

        client_order_id = f"perp-tail-{common.symbol}-{uuid.uuid4().hex[:8]}"
        fill = self.exchange.place_market_order(
            symbol=common.symbol,
            side=common.side,
            notional=notional_to_send,
            client_order_id=client_order_id,
            slippage=execution.tail_market_slippage,
        )

        unfilled_notional = max(0.0, remaining_unfilled_notional - fill.filled_notional)
        unfilled_ratio = (unfilled_notional / remaining_unfilled_notional) if remaining_unfilled_notional > 0 else 0.0

        entry = OrderLogEntry(
            sub_order_index=-1,
            sub_order_time=self._now(),
            order_id=fill.order_id,
            symbol=common.symbol,
            side=common.side,
            order_type=fill.order_type,
            notional=fill.ordered_notional,
            limit_price=None,
            avg_fill_price=fill.avg_fill_price,
            ordered_notional=fill.ordered_notional,
            filled_notional=fill.filled_notional,
            filled_qty=fill.filled_qty,
            unfilled_notional=unfilled_notional,
            unfilled_ratio=unfilled_ratio,
            slippage_ratio=fill.slippage_ratio,
            triggered_alarm=False,
            alarm_type=None,
            alarm_message=None,
            alarm_types=None,
            alarm_messages=None,
            raw={"tail": True, "estimated_margin": margin, "leverage": execution.leverage},
        )
        self.log.add_order_log(entry)
        return float(fill.filled_notional)

