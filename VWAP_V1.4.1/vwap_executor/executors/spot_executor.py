from __future__ import annotations

import uuid
from datetime import datetime

from ..config import VwapConfig
from ..exchange.base import BaseExchange
from ..logging_store import TransactionLog
from ..models import OrderFill, OrderLogEntry, Side, SubOrderSpec
from ..risk import RiskManager
from .base_executor import ExecutionSummary, VwapBaseExecutor


class SpotVwapExecutor(VwapBaseExecutor):
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

        target_notional = spec.target_notional
        notional_to_send = float(target_notional)

        if common.side == "SELL":
            # 折算：qty = notional / price
            available_qty = self.exchange.get_available_base_qty(common.symbol)
            max_notional = available_qty * limit_price
            if execution.spot_sell_truncate_to_holdings:
                notional_to_send = min(notional_to_send, max_notional)
            else:
                # 不允许截断：若不足则直接让交易失败（模拟拒单）
                if notional_to_send > max_notional:
                    raise RuntimeError("Insufficient spot holdings to place SELL order")

            notional_to_send = max(0.0, notional_to_send)

        client_order_id = f"spot-{common.symbol}-{spec.sub_order_index}-{uuid.uuid4().hex[:8]}"
        fill = self.exchange.place_limit_order(
            symbol=common.symbol,
            side=common.side,
            notional=notional_to_send,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )
        return fill

    async def _force_tail_market_fill(
        self, *, remaining_unfilled_notional: float, executed_notional_so_far: float
    ) -> float:
        common = self.config.common
        execution = self.config.execution

        if remaining_unfilled_notional <= 0:
            return 0.0

        # 对现货 SELL：依然必须不超卖（截断到可用持仓）
        notional_to_send = float(remaining_unfilled_notional)
        if common.side == "SELL":
            # 用“最新 best bid”估计能卖多少
            best = self.exchange.get_best_prices(common.symbol)
            available_qty = self.exchange.get_available_base_qty(common.symbol)
            max_notional = available_qty * best.bid
            if execution.spot_sell_truncate_to_holdings:
                notional_to_send = min(notional_to_send, max_notional)
            else:
                if notional_to_send > max_notional:
                    notional_to_send = 0.0
                    # 让未成交残留在风险结果里（引擎本版本只记录日志，不抛错）

        if notional_to_send <= 0:
            return 0.0

        client_order_id = f"spot-tail-{common.symbol}-{uuid.uuid4().hex[:8]}"
        fill = self.exchange.place_market_order(
            symbol=common.symbol,
            side=common.side,
            notional=notional_to_send,
            client_order_id=client_order_id,
            slippage=execution.tail_market_slippage,
        )

        # 这里尾盘市价订单也落一条日志，便于分析
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
            raw={"tail": True},
        )
        self.log.add_order_log(entry)
        return float(fill.filled_notional)

