from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Tuple

from ..config import ExecutionParams
from ..models import OrderFill, Side
from .base import BaseExchange, BestPrices


@dataclass
class PriceState: # 价格状态：最新中间价和价差，用于生成盘口价格，bid=last_mid-spread/2, ask=last_mid+spread/2
    last_mid: float 
    spread: float 


class MockExchange(BaseExchange):
    """
    简化撮合：
    - 限价单根据 limit 与 ask/bid 的相对距离决定填充比例（0~1）
    - 市价单按 mid 附近成交，加入可配置滑点
    - 维护现货 base 资产余额以限制 SELL 不超卖
    """

    def __init__(
        self,
        *,
        symbol: str,
        initial_mid: float,
        spread: float,
        base_asset: str,
        quote_asset: str,
        spot_initial_base_qty: float = 0.0,
        params: ExecutionParams | None = None,
        rng_seed: int = 42,
    ) -> None:
        self.symbol = symbol
        self.params = params
        self.price_state = PriceState(last_mid=initial_mid, spread=spread)
        self._base_asset = base_asset
        self._quote_asset = quote_asset
        self._balances: Dict[str, float] = {base_asset: float(spot_initial_base_qty)}
        self._order_seq = 0
        self.rng = random.Random(rng_seed)

        # 模拟填充敏感度；数值越小，越不容易成交
        self.fill_sensitivity = (params.mock_fill_sensitivity if params else 0.10) or 0.10

    def _now(self) -> datetime:
        return datetime.utcnow()

    def _update_price(self) -> None:
        # 简化：小幅随机游走
        drift = 0.0
        vol = self.fill_sensitivity * 0.01  # 用敏感度影响波动幅度
        shock = self.rng.uniform(-vol, vol)
        self.price_state.last_mid = max(0.0001, self.price_state.last_mid * (1.0 + drift + shock))

    def get_best_prices(self, symbol: str) -> BestPrices:
        if symbol != self.symbol:
            # 本 mock 只支持单一 symbol；真实实现应该支持映射
            raise ValueError(f"MockExchange only supports symbol={self.symbol}")
        self._update_price()
        half = self.price_state.spread / 2.0
        bid = self.price_state.last_mid - half
        ask = self.price_state.last_mid + half
        return BestPrices(bid=bid, ask=ask)

    def get_available_base_qty(self, symbol: str) -> float:
        # symbol 在本 mock 不区分资产，只按 base 余额限制超卖
        if symbol != self.symbol:
            raise ValueError(f"MockExchange only supports symbol={self.symbol}")
        return float(self._balances.get(self._base_asset, 0.0))

    def _next_order_id(self, client_order_id: str) -> str: #给每次下单生成一个唯一 order_id
        self._order_seq += 1
        return f"{client_order_id}-{self._order_seq}"

    def _qty_from_notional(self, notional: float, price: float) -> float:
        # spot/perp 通用：qty = notional / price
        return notional / price

    def _fill_ratio_for_limit(self, *, side: Side, limit_price: float, bid: float, ask: float) -> float:
        # BUY：limit >= ask => 100%成交；否则根据距 ask 的距离给部分成交
        if side == "BUY":
            if limit_price >= ask:
                return 1.0
            # aggressiveness: 越接近 ask，成交越多（上限<1）
            dist = (ask - limit_price) / ask
        else:
            if limit_price <= bid:
                return 1.0
            dist = (limit_price - bid) / bid

        # 用 sensitivity 将 dist 映射到 fill_ratio
        # dist=0 => 1；dist 越大越接近 0
        # 为了稳定，这里使用线性/非线性混合
        scale = max(1e-9, self.fill_sensitivity)
        raw = 1.0 - (dist / scale)
        # 允许一定噪声
        raw += self.rng.uniform(-0.02, 0.02)
        return float(max(0.0, min(1.0, raw)))

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: Side,
        notional: float,
        limit_price: float,
        client_order_id: str,
    ) -> OrderFill:
        if symbol != self.symbol:
            raise ValueError(f"MockExchange only supports symbol={self.symbol}")

        best = self.get_best_prices(symbol)
        bid, ask = best.bid, best.ask
        fill_ratio = self._fill_ratio_for_limit(side=side, limit_price=limit_price, bid=bid, ask=ask)

        ordered_notional = float(notional)
        filled_notional = ordered_notional * fill_ratio

        # 撮合价格：若跨价，则以 ask/bid 成交；否则以 limit 成交（便于可重复）
        if side == "BUY":
            fill_price = ask if limit_price >= ask else limit_price
        else:
            fill_price = bid if limit_price <= bid else limit_price

        # 现货：当 SELL 发生成交时扣减 base_qty；BUY 时增加 base_qty（用于可用余额限制）
        filled_qty = self._qty_from_notional(filled_notional, max(1e-12, fill_price))
        if side == "BUY":
            self._balances[self._base_asset] = self._balances.get(self._base_asset, 0.0) + filled_qty
        else:
            self._balances[self._base_asset] = self._balances.get(self._base_asset, 0.0) - filled_qty

        # 现货/期货由上层 executor 控制是否允许负仓位；mock 这里不做强制截断。
        self._balances[self._base_asset] = float(self._balances.get(self._base_asset, 0.0))

        order_id = self._next_order_id(client_order_id)
        executed_at = self._now()

        slippage_ratio = None
        if limit_price > 0:
            slippage_ratio = abs(fill_price - limit_price) / limit_price

        return OrderFill(
            order_id=order_id,
            executed_at=executed_at,
            order_type="LIMIT",
            side=side,
            symbol=symbol,
            ordered_notional=ordered_notional,
            filled_notional=float(filled_notional),
            filled_qty=float(filled_qty),
            avg_fill_price=float(fill_price),
            limit_price=float(limit_price),
            slippage_ratio=slippage_ratio,
            estimated_margin=None,
        )

    def place_market_order(
        self,
        *,
        symbol: str,
        side: Side,
        notional: float,
        client_order_id: str,
        slippage: float = 0.0,
    ) -> OrderFill:
        if symbol != self.symbol:
            raise ValueError(f"MockExchange only supports symbol={self.symbol}")

        best = self.get_best_prices(symbol)
        bid, ask = best.bid, best.ask
        mid = best.mid

        ordered_notional = float(notional)

        # 市价成交价格：根据方向取 bid/ask，并加入额外 slippage（模拟尾盘冲击）
        if side == "BUY":
            fill_price = ask * (1.0 + slippage)
        else:
            fill_price = bid * (1.0 - slippage)

        filled_notional = ordered_notional
        filled_qty = self._qty_from_notional(filled_notional, max(1e-12, fill_price))

        if side == "BUY":
            self._balances[self._base_asset] = self._balances.get(self._base_asset, 0.0) + filled_qty
        else:
            self._balances[self._base_asset] = self._balances.get(self._base_asset, 0.0) - filled_qty
        self._balances[self._base_asset] = float(self._balances.get(self._base_asset, 0.0))

        order_id = self._next_order_id(client_order_id)
        executed_at = self._now()

        return OrderFill(
            order_id=order_id,
            executed_at=executed_at,
            order_type="MARKET",
            side=side,
            symbol=symbol,
            ordered_notional=ordered_notional,
            filled_notional=float(filled_notional),
            filled_qty=float(filled_qty),
            avg_fill_price=float(fill_price),
            limit_price=None,
            slippage_ratio=None,
            estimated_margin=None,
        )

