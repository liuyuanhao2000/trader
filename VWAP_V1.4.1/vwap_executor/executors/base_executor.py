from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from ..config import ExecutionParams, VwapConfig
from ..exchange.base import BaseExchange
from ..logging_store import TransactionLog
from ..models import Alert, OcoPlacement, OrderFill, Side, OrderLogEntry, SubOrderSpec
from ..order_manager import build_sub_orders, compute_limit_price, build_vwap_schedule
from ..risk import RiskManager

# 大单拆成子订单

@dataclass
class ExecutionSummary:
    symbol: str
    side: Side
    notional_total: float
    executed_notional: float
    remaining_unfilled_notional: float


class VwapBaseExecutor:
    def __init__(
        self,
        *,
        exchange: BaseExchange,
        config: VwapConfig,
        log: TransactionLog,
        risk_manager: RiskManager,
    ) -> None:
        self.exchange = exchange
        self.config = config
        self.log = log
        self.risk_manager = risk_manager

    async def execute(self) -> ExecutionSummary:
        """
        执行器对外入口：使用 config.common / config.execution。
        """
        common = self.config.common
        execution = self.config.execution

        start_times = build_vwap_schedule(
            common.start_time,
            total_duration_seconds=execution.total_duration_seconds,
            order_interval_seconds=execution.order_interval_seconds,
        )
        sub_orders = build_sub_orders(
            symbol=common.symbol,
            side=common.side,
            notional_total=common.notional,
            start_times=start_times,
            execution=execution,
        )

        # 当前统计
        remaining_unfilled_notional = common.notional
        executed_notional = 0.0
        initial_notional = common.notional

        # 调度：按时间点触发子订单；为简化示例，这里用“等待到 scheduled_time 后执行”
        # 注：mock 交易所的价格更新不依赖时钟，因此不会影响示例正确性。
        for spec in sub_orders:
            await self._wait_until(spec.scheduled_time)

            # 尾盘提前触发：当剩余时间 <= tail_force_early_seconds，进入尾盘市价强制完成
            if self._should_tail_force(spec.scheduled_time):
                break

            best = self.exchange.get_best_prices(common.symbol)
            plan = compute_limit_price(
                side=common.side,
                best=best,
                price_offset=execution.price_offset,
                price_offset_mode=execution.price_offset_mode,
            )

            # 子订单：由具体 executor 处理现货/期货的约束（比如现货不超卖）
            fill = self._submit_single_limit(spec=spec, limit_price=plan.limit_price)

            oco = self._maybe_place_oco_protection(fill)

            remaining_unfilled_notional = remaining_unfilled_notional - fill.filled_notional
            executed_notional += fill.filled_notional

            ordered_notional = fill.ordered_notional
            sub_unfilled_notional = ordered_notional - fill.filled_notional

            risk = self.risk_manager.assess_unfilled_ratio(
                alert_time=fill.executed_at,
                symbol=common.symbol,
                order_id=fill.order_id,
                sub_order_notional=ordered_notional,
                unfilled_notional=max(0.0, sub_unfilled_notional),
                side=common.side,
            )

            slippage_alarm = self.risk_manager.assess_slippage_limit(
                alert_time=fill.executed_at,
                symbol=common.symbol,
                order_id=fill.order_id,
                slippage_ratio=fill.slippage_ratio,
            )

            alarms: list[Alert] = []
            if risk.alarm:
                alarms.append(risk.alarm)
            if slippage_alarm:
                alarms.append(slippage_alarm)

            entry = OrderLogEntry(
                sub_order_index=spec.sub_order_index,
                sub_order_time=spec.scheduled_time,
                order_id=fill.order_id,
                symbol=common.symbol,
                side=common.side,
                order_type=fill.order_type,
                notional=ordered_notional,
                limit_price=fill.limit_price,
                avg_fill_price=fill.avg_fill_price,
                ordered_notional=fill.ordered_notional,
                filled_notional=fill.filled_notional,
                filled_qty=fill.filled_qty,
                unfilled_notional=max(0.0, ordered_notional - fill.filled_notional),
                unfilled_ratio=risk.unfilled_ratio,
                slippage_ratio=fill.slippage_ratio,
                triggered_alarm=bool(alarms),
                alarm_type=alarms[0].alert_type if alarms else None,
                alarm_message=alarms[0].message if alarms else None,
                alarm_types=[a.alert_type for a in alarms] if alarms else None,
                alarm_messages=[a.message for a in alarms] if alarms else None,
                oco=oco,
                raw={
                    "best_bid": plan.best_bid,
                    "best_ask": plan.best_ask,
                    "estimated_margin": fill.estimated_margin,
                },
            )
            self.log.add_order_log(entry)
            for a in alarms:
                self._handle_alert(a)

        # 尾盘强制完成（市价单一次性完成剩余）
        tail_alert = self._maybe_assess_tail_risk_and_alert(
            alert_time=self._now(),
            initial_notional=initial_notional,
            remaining_unfilled_notional=remaining_unfilled_notional,
        )
        if tail_alert:
            self._handle_alert(tail_alert)

        if remaining_unfilled_notional > 0:
            filled = await self._force_tail_market_fill(
                remaining_unfilled_notional=remaining_unfilled_notional,
                executed_notional_so_far=executed_notional,
            )
            executed_notional += filled
            remaining_unfilled_notional = max(0.0, remaining_unfilled_notional - filled)

        return ExecutionSummary(
            symbol=common.symbol,
            side=common.side,
            notional_total=initial_notional,
            executed_notional=executed_notional,
            remaining_unfilled_notional=max(0.0, remaining_unfilled_notional),
        )

    async def _wait_until(self, t: datetime) -> None:
        now = self._now()
        if now >= t:
            return
        await asyncio.sleep((t - now).total_seconds())

    def _now(self) -> datetime:
        # 这里用系统时间；更进一步可引入 TimeProvider
        return datetime.now(timezone.utc)

    def _should_tail_force(self, current_slice_time: datetime) -> bool:
        common = self.config.common
        execution = self.config.execution
        end_time = common.start_time.timestamp() + execution.total_duration_seconds
        remaining = end_time - current_slice_time.timestamp()
        return remaining <= execution.tail_force_early_seconds

    def _handle_alert(self, alert: Alert) -> None:
        self.log.add_alert(alert)
        if self.config.alerting.print_alerts:
            # 模拟环境直接打印
            print(
                f"[ALERT] {alert.alert_type} symbol={alert.symbol} order_id={alert.order_id} "
                f"unfilled_ratio={alert.unfilled_ratio} remaining_unfilled_notional={alert.remaining_unfilled_notional} "
                f"message={alert.message}"
            )

    def _maybe_assess_tail_risk_and_alert(
        self,
        *,
        alert_time: datetime,
        initial_notional: float,
        remaining_unfilled_notional: float,
    ) -> Optional[Alert]:
        return self.risk_manager.assess_tail_risk(
            alert_time=alert_time,
            symbol=self.config.common.symbol,
            initial_notional=initial_notional,
            remaining_unfilled_notional=remaining_unfilled_notional,
        )

    def _submit_single_limit(self, *, spec: SubOrderSpec, limit_price: float) -> OrderFill:
        raise NotImplementedError

    async def _force_tail_market_fill(
        self, *, remaining_unfilled_notional: float, executed_notional_so_far: float
    ) -> float:
        raise NotImplementedError

    def _maybe_place_oco_protection(self, fill: OrderFill) -> Optional[OcoPlacement]:
        """
        子单成交后挂 OCO 止盈止损（方案 B：全仓覆盖）。失败不打断主流程，只发 Alert。

        - 配置未启用 / 现货 SELL（无剩余仓位）/ 未成交 → 跳过。
        - BUY 主单 → 先撤掉该 symbol 所有活跃 OCO，再按账户该 base 资产 free+locked
          总持仓挂新 OCO（含历史持仓）。
        - TP/SL 基准价仍用本次子单的 fill.avg_fill_price——连续加仓会被最新一笔拉走。
        """
        tp_sl = self.config.tp_sl
        if not tp_sl.enabled:
            return None

        instrument_type = self.config.instrument_type
        main_side: Side = fill.side

        # 现货 SELL 是平仓动作，不挂 OCO（撤旧 OCO 在 SpotVwapExecutor 的 SELL 前置 hook 里）
        if instrument_type == "spot" and main_side == "SELL":
            return None

        if tp_sl.skip_if_filled_qty_zero and fill.filled_qty <= 0:
            return None

        if fill.avg_fill_price <= 0:
            return None

        # 方案 B 关键：撤掉该 symbol 已有的所有 OCO，准备按全仓重挂
        try:
            self.exchange.cancel_open_ocos(fill.symbol)
        except Exception as e:
            self._handle_alert(
                Alert(
                    alert_time=self._now(),
                    alert_type="GLOBAL_ERROR",
                    symbol=fill.symbol,
                    order_id=fill.order_id,
                    message=f"cancel_open_ocos before re-place failed: {e}",
                )
            )

        # 平仓方向与主单相反
        close_side: Side = "SELL" if main_side == "BUY" else "BUY"

        p = float(fill.avg_fill_price)
        if main_side == "BUY":
            tp_price = p * (1.0 + tp_sl.tp_pct)
            sl_stop_price = p * (1.0 - tp_sl.sl_pct)
            sl_limit_price = p * (1.0 - tp_sl.sl_pct - tp_sl.sl_limit_buffer)
        else:
            tp_price = p * (1.0 - tp_sl.tp_pct)
            sl_stop_price = p * (1.0 + tp_sl.sl_pct)
            sl_limit_price = p * (1.0 + tp_sl.sl_pct + tp_sl.sl_limit_buffer)

        # 方案 B 关键：数量 = 全仓 free+locked，覆盖历史持仓
        total_qty = self.exchange.get_total_base_qty(fill.symbol)
        if total_qty <= 0:
            return None

        prefix = f"oco-{fill.symbol}-{fill.order_id}-{uuid.uuid4().hex[:6]}"
        try:
            return self.exchange.place_oco_order(
                symbol=fill.symbol,
                side=close_side,
                qty=float(total_qty),
                tp_price=float(tp_price),
                sl_stop_price=float(sl_stop_price),
                sl_limit_price=float(sl_limit_price),
                client_order_id_prefix=prefix,
            )
        except Exception as e:
            alert = Alert(
                alert_time=self._now(),
                alert_type="GLOBAL_ERROR",
                symbol=fill.symbol,
                order_id=fill.order_id,
                message=f"OCO placement failed: {e}",
                extra={"fill_avg_price": p, "total_qty": total_qty},
            )
            self._handle_alert(alert)
            return None

