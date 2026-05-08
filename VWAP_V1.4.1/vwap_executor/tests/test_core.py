import asyncio
import unittest
from datetime import datetime, timedelta

from vwap_executor.config import (
    AlertingConfig,
    CommonInput,
    ExchangeConfig,
    ExecutionParams,
    LogStorage,
    TakeProfitStopLossConfig,
    VwapConfig,
)
from vwap_executor.exchange.mock import MockExchange
from vwap_executor.execution_engine import VwapExecutionEngine
from vwap_executor.logging_store import TransactionLog
from vwap_executor.order_manager import _split_notional_equal
from vwap_executor.risk import RiskManager


class TestSplitNotional(unittest.TestCase):
    def test_sum_equals_total(self):
        parts = _split_notional_equal(10000.0, 7)
        self.assertAlmostEqual(sum(parts), 10000.0, places=6)
        self.assertEqual(len(parts), 7)


class TestRiskManager(unittest.TestCase):
    def test_unfilled_ratio_trigger(self):
        rm = RiskManager(unfilled_alarm_threshold=0.1, tail_risk_threshold_ratio=0.2, max_slippage=0.01)
        res = rm.assess_unfilled_ratio(
            alert_time=datetime.utcnow(),
            symbol="BTCUSDT",
            order_id="o1",
            sub_order_notional=100.0,
            unfilled_notional=15.0,
            side="BUY",
        )
        self.assertTrue(res.triggered)
        self.assertAlmostEqual(res.unfilled_ratio, 0.15)


def _build_config(
    *,
    side: str,
    instrument_type: str = "spot",
    tp_sl: TakeProfitStopLossConfig,
    notional: float = 1000.0,
) -> VwapConfig:
    return VwapConfig(
        common=CommonInput(
            symbol="BTCUSDT",
            side=side,  # type: ignore[arg-type]
            notional=notional,
            start_time=datetime.utcnow() + timedelta(milliseconds=10),
            quote_currency="USDT",
            base_currency="BTC",
        ),
        execution=ExecutionParams(
            total_duration_seconds=2,
            order_interval_seconds=1,
            price_offset=0.001,  # 跨价，确保限价能成交
            mock_fill_sensitivity=0.5,
        ),
        instrument_type=instrument_type,  # type: ignore[arg-type]
        log_storage=LogStorage(),
        alerting=AlertingConfig(print_alerts=False),
        exchange=ExchangeConfig(adapter="mock"),
        tp_sl=tp_sl,
    )


def _build_mock(*, spot_initial_base_qty: float = 0.0) -> MockExchange:
    return MockExchange(
        symbol="BTCUSDT",
        initial_mid=100.0,
        spread=0.2,
        base_asset="BTC",
        quote_asset="USDT",
        spot_initial_base_qty=spot_initial_base_qty,
    )


def _run(config: VwapConfig, mock: MockExchange) -> None:
    engine = VwapExecutionEngine(exchange=mock, log=TransactionLog())
    asyncio.run(engine.run(config))


class TestOcoPlacement(unittest.TestCase):
    def test_disabled_no_oco(self):
        cfg = _build_config(side="BUY", tp_sl=TakeProfitStopLossConfig(enabled=False))
        mock = _build_mock()
        _run(cfg, mock)
        self.assertEqual(len(mock._oco_placements), 0)

    def test_buy_spot_places_oco_sell(self):
        tp_sl = TakeProfitStopLossConfig(
            enabled=True, tp_pct=0.02, sl_pct=0.01, sl_limit_buffer=0.002
        )
        cfg = _build_config(side="BUY", tp_sl=tp_sl)
        mock = _build_mock()
        _run(cfg, mock)

        self.assertGreater(len(mock._oco_placements), 0)
        for oco in mock._oco_placements:
            self.assertEqual(oco.side, "SELL")
            self.assertGreater(oco.qty, 0)
            # TP 高于触发价高于 SL limit
            self.assertGreater(oco.tp_price, oco.sl_stop_price)
            self.assertGreater(oco.sl_stop_price, oco.sl_limit_price)

    def test_spot_sell_skips_oco(self):
        tp_sl = TakeProfitStopLossConfig(enabled=True)
        cfg = _build_config(
            side="SELL", instrument_type="spot", tp_sl=tp_sl, notional=100.0
        )
        # 给足现货持仓，让 SELL 能成交，验证即便成交也不挂 OCO
        mock = _build_mock(spot_initial_base_qty=10.0)
        _run(cfg, mock)
        self.assertEqual(len(mock._oco_placements), 0)

    def test_perp_sell_places_oco_buy(self):
        tp_sl = TakeProfitStopLossConfig(
            enabled=True, tp_pct=0.02, sl_pct=0.01, sl_limit_buffer=0.002
        )
        cfg = _build_config(side="SELL", instrument_type="perp", tp_sl=tp_sl)
        mock = _build_mock(spot_initial_base_qty=10.0)
        _run(cfg, mock)

        self.assertGreater(len(mock._oco_placements), 0)
        for oco in mock._oco_placements:
            self.assertEqual(oco.side, "BUY")
            # SELL 主单：TP 价格低于成交价低于 SL 触发价
            self.assertLess(oco.tp_price, oco.sl_stop_price)
            self.assertLess(oco.sl_stop_price, oco.sl_limit_price)


if __name__ == "__main__":
    unittest.main()

