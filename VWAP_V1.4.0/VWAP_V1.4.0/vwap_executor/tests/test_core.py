import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()

