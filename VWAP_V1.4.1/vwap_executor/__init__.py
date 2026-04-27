"""
VWAP 执行器包。

核心能力：
- 时间切片 VWAP：固定间隔拆单执行
- 限价为主、尾盘市价强制完成
- 未成交比例监控与告警
- 现货/期货完全分离模块
"""

from .config import VwapConfig  # noqa: F401
from .execution_engine import VwapExecutionEngine  # noqa: F401

