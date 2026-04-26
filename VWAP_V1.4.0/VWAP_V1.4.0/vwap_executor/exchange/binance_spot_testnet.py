from __future__ import annotations

import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

from ..config import ExecutionParams
from ..models import OrderFill, Side
from .base import BaseExchange, BestPrices


@dataclass
class BinanceSymbolFilters:
    step_size: float
    min_qty: float
    tick_size: float


class BinanceSpotTestnetExchange(BaseExchange):
    """
    Binance Spot Testnet 适配器（教学版接入）。

    说明：
    - 引擎用输入 `notional`（计价货币名义金额），本适配器将其换算成交易所需要的 `quantity`：
      quantity = notional / price
    - 限价单使用 price/tickSize，数量使用 lotSize/stepSize 并向下取整，避免下单被拒。
    - LIMIT 订单会在本适配器内轮询一小段时间；若未 FILLED，会尝试撤单，然后把已成交部分返回给引擎。
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        symbol: str,
        base_asset: str,
        base_url: str = "https://testnet.binance.vision",
        params: ExecutionParams | None = None,
        balance_cache_ttl_seconds: int = 5,
        limit_order_poll_seconds: float = 1.5,
        timeout_cancel_if_new: bool = True,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.symbol = symbol
        self.base_asset = base_asset

        self.params = params
        self.balance_cache_ttl_seconds = int(balance_cache_ttl_seconds)
        self.limit_order_poll_seconds = float(limit_order_poll_seconds)
        self.timeout_cancel_if_new = bool(timeout_cancel_if_new)

        self._balance_cache: Dict[str, Any] = {}
        self._balance_cache_ts: float = 0.0

        self._filters: Optional[BinanceSymbolFilters] = None

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params)
        return hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _signed_request(
        self, *, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        params = dict(params or {})
        params["timestamp"] = self._now_ms()
        params["signature"] = self._sign(params)
        url = self.base_url + path

        if method.upper() == "GET":
            r = requests.get(url, params=params, headers=self._headers(), timeout=10)
        elif method.upper() == "POST":
            r = requests.post(url, params=params, headers=self._headers(), timeout=10)
        elif method.upper() == "DELETE":
            r = requests.delete(url, params=params, headers=self._headers(), timeout=10)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        # 抛出错误信息便于排查
        if r.status_code >= 400:
            raise RuntimeError(f"Binance API error {r.status_code}: {r.text}")
        return r.json()

    def _public_request(self, *, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        r = requests.get(url, params=params, timeout=10)
        if r.status_code >= 400:
            raise RuntimeError(f"Binance public API error {r.status_code}: {r.text}")
        return r.json()

    def _ensure_filters(self) -> BinanceSymbolFilters:
        if self._filters is not None:
            return self._filters

        info = self._public_request(path="/api/v3/exchangeInfo", params={"symbol": self.symbol})
        symbols = info.get("symbols") or []
        if not symbols:
            raise RuntimeError(f"exchangeInfo returned empty for symbol={self.symbol}")

        sym = symbols[0]
        filters = {f["filterType"]: f for f in sym.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        price = filters.get("PRICE_FILTER", {})

        step_size = float(lot.get("stepSize", "0"))
        min_qty = float(lot.get("minQty", "0"))
        tick_size = float(price.get("tickSize", "0"))
        if step_size <= 0 or min_qty <= 0 or tick_size <= 0:
            raise RuntimeError(f"Missing/invalid filters for symbol={self.symbol}")

        self._filters = BinanceSymbolFilters(step_size=step_size, min_qty=min_qty, tick_size=tick_size)
        return self._filters

    def _round_down(self, x: float, step: float) -> float:
        if step <= 0:
            return x
        return (x // step) * step

    def _quantity_from_notional(self, *, notional: float, price: float) -> float:
        filters = self._ensure_filters()
        qty = float(notional) / float(price)
        qty = self._round_down(qty, filters.step_size)
        # 确保数量不低于 minQty
        if qty < filters.min_qty:
            return 0.0
        return qty

    def _price_from_price(self, *, limit_price: float) -> float:
        filters = self._ensure_filters()
        p = float(limit_price)
        p = self._round_down(p, filters.tick_size)
        return p

    def _get_balances_cached(self) -> Dict[str, Any]:
        ts = time.time()
        if self._balance_cache and (ts - self._balance_cache_ts) <= self.balance_cache_ttl_seconds:
            return self._balance_cache

        account = self._signed_request(method="GET", path="/api/v3/account", params={})
        self._balance_cache = account
        self._balance_cache_ts = ts
        return account

    def get_best_prices(self, symbol: str) -> BestPrices:
        if symbol != self.symbol:
            raise RuntimeError(f"Binance adapter configured symbol={self.symbol}, got {symbol}")
        book = self._public_request(path="/api/v3/ticker/bookTicker", params={"symbol": symbol})
        return BestPrices(bid=float(book["bidPrice"]), ask=float(book["askPrice"]))

    def get_available_base_qty(self, symbol: str) -> float:
        if symbol != self.symbol:
            raise RuntimeError(f"Binance adapter configured symbol={self.symbol}, got {symbol}")

        account = self._get_balances_cached()
        for b in account.get("balances", []):
            if b.get("asset") == self.base_asset:
                ############################################################
                return float(b.get("free", "0")) + float(b.get("locked", "0")) * 0.0
        return 0.0

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
            raise RuntimeError(f"Binance adapter configured symbol={self.symbol}, got {symbol}")

        limit_price = self._price_from_price(limit_price=limit_price)
        if limit_price <= 0:
            raise RuntimeError("Invalid limit_price after rounding")

        qty = self._quantity_from_notional(notional=notional, price=limit_price)
        if qty <= 0:
            # 下单会被拒，这里直接当作“零成交”
            return OrderFill(
                order_id=f"rejected-{client_order_id}",
                executed_at=self._now_datetime(),
                order_type="LIMIT",
                side=side,
                symbol=symbol,
                ordered_notional=float(notional),
                filled_notional=0.0,
                filled_qty=0.0,
                avg_fill_price=0.0,
                limit_price=float(limit_price),
                slippage_ratio=None,
                estimated_margin=None,
            )

        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{qty:.16f}".rstrip("0").rstrip("."),
            "price": f"{limit_price:.8f}".rstrip("0").rstrip("."),
            "newClientOrderId": client_order_id,
        }
        created = self._signed_request(method="POST", path="/api/v3/order", params=params)
        order_id = str(created["orderId"])

        # 轮询拿成交情况
        end_ts = time.time() + self.limit_order_poll_seconds
        last = created
        while time.time() < end_ts:
            last = self._signed_request(
                method="GET",
                path="/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
            )
            status = last.get("status")
            if status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                break
            time.sleep(0.3)

        # 超时则撤单（尽量把“子订单窗口”控制在本适配器内部）
        status = last.get("status")
        if self.timeout_cancel_if_new and status in ("NEW", "PARTIALLY_FILLED"):
            try:
                self._signed_request(
                    method="DELETE",
                    path="/api/v3/order",
                    params={"symbol": symbol, "orderId": order_id},
                )
            except Exception:
                # 撤单失败也不影响返回已成交部分
                pass
            # 再取一次状态
            last = self._signed_request(
                method="GET",
                path="/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
            )

        filled_notional = float(last.get("cummulativeQuoteQty", "0") or 0.0)
        filled_qty = float(last.get("executedQty", "0") or 0.0)
        avg_price = float(last.get("avgPrice", "0") or 0.0)

        # slippage：|avg_fill - limit|/limit（如果有成交）
        slippage_ratio = None
        if limit_price > 0 and avg_price > 0:
            slippage_ratio = abs(avg_price - limit_price) / limit_price

        return OrderFill(
            order_id=order_id,
            executed_at=self._now_datetime(),
            order_type="LIMIT",
            side=side,
            symbol=symbol,
            ordered_notional=float(notional),
            filled_notional=float(filled_notional),
            filled_qty=float(filled_qty),
            avg_fill_price=float(avg_price),
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
            raise RuntimeError(f"Binance adapter configured symbol={self.symbol}, got {symbol}")

        best = self.get_best_prices(symbol)
        # 市价：用 mid 估计价格来把 notional 换成 quantity
        mid = best.mid
        qty = self._quantity_from_notional(notional=notional, price=mid)
        if qty <= 0:
            return OrderFill(
                order_id=f"rejected-{client_order_id}",
                executed_at=self._now_datetime(),
                order_type="MARKET",
                side=side,
                symbol=symbol,
                ordered_notional=float(notional),
                filled_notional=0.0,
                filled_qty=0.0,
                avg_fill_price=0.0,
                limit_price=None,
                slippage_ratio=None,
                estimated_margin=None,
            )

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{qty:.16f}".rstrip("0").rstrip("."),
            "newClientOrderId": client_order_id,
        }
        created = self._signed_request(method="POST", path="/api/v3/order", params=params)
        order_id = str(created["orderId"])

        last = created
        # 大部分情况下 MARKET 会立刻 FILLED；这里仍取一次最终状态
        try:
            last = self._signed_request(
                method="GET",
                path="/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
            )
        except Exception:
            pass

        filled_notional = float(last.get("cummulativeQuoteQty", "0") or 0.0)
        filled_qty = float(last.get("executedQty", "0") or 0.0)
        avg_price = float(last.get("avgPrice", "0") or 0.0)

        return OrderFill(
            order_id=order_id,
            executed_at=self._now_datetime(),
            order_type="MARKET",
            side=side,
            symbol=symbol,
            ordered_notional=float(notional),
            filled_notional=float(filled_notional),
            filled_qty=float(filled_qty),
            avg_fill_price=float(avg_price),
            limit_price=None,
            slippage_ratio=None,
            estimated_margin=None,
        )

    def _now_datetime(self):
        # 避免引入 datetime 导入开销；这里直接给 str 也行，但日志期望 datetime 类型
        from datetime import datetime

        return datetime.utcnow()

