from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import Alert, OrderLogEntry

# 系统执行过程中发生的订单明细和报警信息，先放到一个日志收集器里，最后再统一写成 JSONL 文件。

# 日志收集器
class TransactionLog:
    def __init__(self, output_jsonl_path: Optional[str] = None):
        self.output_jsonl_path = output_jsonl_path
        self.order_logs: List[OrderLogEntry] = []
        self.alerts: List[Alert] = []

    def add_order_log(self, entry: OrderLogEntry) -> None:
        self.order_logs.append(entry)

    def add_alert(self, alert: Alert) -> None:
        self.alerts.append(alert)

    def _to_jsonable(self, obj: Any) -> Any:
        if hasattr(obj, "__dict__"):
            d: Dict[str, Any] = obj.__dict__.copy()
            for k, v in d.items():
                d[k] = self._to_jsonable(v)
            return d
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, list):
            return [self._to_jsonable(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._to_jsonable(v) for k, v in obj.items()}
        return obj

    def dump_jsonl(self) -> None:
        if not self.output_jsonl_path:
            return

        payloads: List[Dict[str, Any]] = []
        for o in self.order_logs:
            payloads.append(self._to_jsonable({"type": "order", **o.__dict__}))
        for a in self.alerts:
            payloads.append(self._to_jsonable({"type": "alert", **a.__dict__}))

        # 确保目录存在交给用户环境；这里不做额外依赖
        with open(self.output_jsonl_path, "w", encoding="utf-8") as f:
            for p in payloads:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

