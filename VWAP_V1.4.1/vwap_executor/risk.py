from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Alert, Side

#每一笔子订单执行完之后，系统都要确认这笔单有没有风险？要不要报警？
@dataclass
class OrderRiskResult:
    unfilled_ratio: float
    triggered: bool # 是否触发告警
    alarm: Optional[Alert] = None # 如果触发，表示告警的详细信息


class RiskManager:
    def __init__( # 初始化风险管理器，设置告警阈值
        self,
        *,
        unfilled_alarm_threshold: float,
        tail_risk_threshold_ratio: float,
        max_slippage: float,
    ) -> None:
        self.unfilled_alarm_threshold = float(unfilled_alarm_threshold)
        self.tail_risk_threshold_ratio = float(tail_risk_threshold_ratio)
        self.max_slippage = float(max_slippage)

    def assess_unfilled_ratio( # 评估未成交比例是否超过阈值
        self,
        *,
        alert_time: datetime,
        symbol: str,
        order_id: str,
        sub_order_notional: float,
        unfilled_notional: float,
        side: Side,
    ) -> OrderRiskResult:
        notional = float(sub_order_notional)
        unfilled = float(unfilled_notional)
        if notional <= 0:
            ratio = 0.0
        else:
            ratio = unfilled / notional

        triggered = ratio > self.unfilled_alarm_threshold
        alarm = None
        if triggered:
            alarm = Alert(
                alert_time=alert_time,
                alert_type="ORDER_UNFILLED_RATIO",
                symbol=symbol,
                order_id=order_id,
                message=f"Unfilled ratio exceeded threshold: {ratio:.4f} > {self.unfilled_alarm_threshold:.4f}",
                unfilled_ratio=ratio,
                remaining_unfilled_notional=unfilled,
            )
        return OrderRiskResult(unfilled_ratio=ratio, triggered=triggered, alarm=alarm)

    def assess_tail_risk( # 评估尾盘风险：剩余未成交金额占初始总金额比例是否超过阈值
        self,
        *,
        alert_time: datetime,
        symbol: str,
        initial_notional: float,
        remaining_unfilled_notional: float,
    ) -> Optional[Alert]:
        if initial_notional <= 0:
            return None
        ratio = remaining_unfilled_notional / initial_notional
        if ratio <= self.tail_risk_threshold_ratio:
            return None
        return Alert(
            alert_time=alert_time,
            alert_type="TAIL_RISK",
            symbol=symbol,
            order_id=None,
            message=f"Tail remaining unfilled notional too large: ratio={ratio:.4f} > {self.tail_risk_threshold_ratio:.4f}",
            remaining_unfilled_notional=remaining_unfilled_notional,
            unfilled_ratio=ratio,
        )

    def assess_slippage_limit( # 评估滑点是否超过阈值
        self,
        *,
        alert_time: datetime,
        symbol: str,
        order_id: str,
        slippage_ratio: Optional[float],
    ) -> Optional[Alert]:
        if slippage_ratio is None:
            return None
        if slippage_ratio <= self.max_slippage:
            return None
        return Alert(
            alert_time=alert_time,
            alert_type="ORDER_SLIPPAGE_LIMIT",
            symbol=symbol,
            order_id=order_id,
            message=f"Slippage ratio exceeded limit: {slippage_ratio:.6f} > {self.max_slippage:.6f}",
            extra={"slippage_ratio": slippage_ratio, "max_slippage": self.max_slippage},
        )

# 滑点：看的是 价格有没有成交得太差
# 尾盘风险：看的是 到最后还有没有剩太多没做完