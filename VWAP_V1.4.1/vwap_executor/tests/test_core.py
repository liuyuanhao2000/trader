import asyncio
import unittest
from datetime import datetime, timedelta, timezone

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
            alert_time=datetime.now(timezone.utc),
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
            start_time=datetime.now(timezone.utc) + timedelta(milliseconds=10),
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

    def test_buy_oco_covers_legacy_holdings(self):
        """方案 B：BUY 子单成交后 OCO qty 应等于全仓 (free+locked)，覆盖旧持仓。"""
        tp_sl = TakeProfitStopLossConfig(
            enabled=True, tp_pct=0.02, sl_pct=0.01, sl_limit_buffer=0.002
        )
        cfg = _build_config(side="BUY", tp_sl=tp_sl, notional=200.0)
        legacy_qty = 5.0
        mock = _build_mock(spot_initial_base_qty=legacy_qty)
        _run(cfg, mock)

        self.assertGreater(len(mock._oco_placements), 0)
        # 每次重挂时 qty 都应 >= 旧持仓；最后一笔应包含旧持仓 + 累计买入量
        for oco in mock._oco_placements:
            self.assertGreaterEqual(oco.qty, legacy_qty)
        last_oco = mock._oco_placements[-1]
        final_total = mock.get_total_base_qty("BTCUSDT")
        self.assertAlmostEqual(last_oco.qty, final_total, places=6)
        # 撤旧 + 重挂保证当前活跃 OCO 数 == 1
        self.assertEqual(len(mock._active_oco_list_ids.get("BTCUSDT", [])), 1)

    def test_sell_cancels_existing_ocos(self):
        """方案 B：SELL 子单触发前应撤掉所有旧 OCO。"""
        tp_sl = TakeProfitStopLossConfig(enabled=True)
        cfg = _build_config(
            side="SELL", instrument_type="spot", tp_sl=tp_sl, notional=100.0
        )
        mock = _build_mock(spot_initial_base_qty=10.0)
        # 预置一笔旧 OCO 模拟历史调仓挂的保护单
        mock.place_oco_order(
            symbol="BTCUSDT",
            side="SELL",
            qty=5.0,
            tp_price=110.0,
            sl_stop_price=95.0,
            sl_limit_price=94.0,
            client_order_id_prefix="legacy",
        )
        self.assertEqual(len(mock._active_oco_list_ids.get("BTCUSDT", [])), 1)

        _run(cfg, mock)
        # SELL 子单跑完后，旧 OCO 应已被撤掉，且 SELL 不会重挂新 OCO
        self.assertEqual(mock._active_oco_list_ids.get("BTCUSDT", []), [])


if __name__ == "__main__":
    unittest.main()

