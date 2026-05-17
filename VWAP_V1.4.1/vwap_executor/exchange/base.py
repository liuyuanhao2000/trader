from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Tuple

from ..models import OrderFill, OcoPlacement, OrderType, Side


@dataclass
class BestPrices:
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class ExchangeError(RuntimeError):
    pass


class InstrumentError(ExchangeError):
    pass


class BaseExchange(ABC):
    @abstractmethod
    def get_best_prices(self, symbol: str) -> BestPrices:
        raise NotImplementedError

    @abstractmethod
    def get_available_base_qty(self, symbol: str) -> float:
        """
        现货用：用于限制 SELL 不出现负仓位。
        期货可返回很大值或用于做“可用保证金”限制（本版本用不上）。
        """

    def get_total_base_qty(self, symbol: str) -> float:
        """
        现货 base 资产 free + locked 总量（含被挂单锁住的部分）。
        默认实现退化为 get_available_base_qty —— 适配器若需要更精确语义请覆盖。
        """
        return self.get_available_base_qty(symbol)

    def cancel_open_ocos(self, symbol: str) -> int:
        """
        撤掉该 symbol 当前所有活跃 OCO。返回撤掉的 list 数量。
        默认 no-op，便于不支持 OCO 的适配器无需感知。
        """
        return 0

    def get_min_notional(self, symbol: str) -> float:
        """
        返回交易所对该交易对要求的最小名义金额（USDT 等计价货币）。
        无要求或未知时返回 0.0；调用方应据此跳过过小的下单以避免被交易所拒单。
        """
        return 0.0

    @abstractmethod
    def place_limit_order( # 限价单下单
        self,
        *,
        symbol: str,
        side: Side,
        notional: float,
        limit_price: float,
        client_order_id: str,
    ) -> OrderFill:
        raise NotImplementedError

    @abstractmethod
    def place_market_order( # 市价单下单
        self,
        *,
        symbol: str,
        side: Side,
        notional: float,
        client_order_id: str,
        slippage: float = 0.0,
    ) -> OrderFill:
        raise NotImplementedError

    @abstractmethod
    def place_oco_order( # OCO 止盈止损下单
        self,
        *,
        symbol: str,
        side: Side,                # 平仓方向（与主单相反）
        qty: float,
        tp_price: float,
        sl_stop_price: float,
        sl_limit_price: float,
        client_order_id_prefix: str,
    ) -> OcoPlacement:
        raise NotImplementedError

