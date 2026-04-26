from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Tuple

from ..models import OrderFill, OrderType, Side


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

