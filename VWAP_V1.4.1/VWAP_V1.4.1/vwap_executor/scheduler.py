from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

# 时间提供者：用于获取当前时间，并等待直到指定时间
class TimeProvider:
    def now(self) -> datetime:
        raise NotImplementedError

    async def sleep_until(self, t: datetime) -> None:
        raise NotImplementedError

# 真实时间提供者：使用系统时间
class RealTimeProvider(TimeProvider):
    def now(self) -> datetime:
        return datetime.utcnow()

    async def sleep_until(self, t: datetime) -> None:
        while True:
            n = self.now()
            if n >= t:
                return
            await asyncio.sleep(min(0.5, (t - n).total_seconds()))

# 时间调度器：用于根据时间间隔生成时间点
@dataclass
class Schedule:
    start_time: datetime
    interval_seconds: int
    n_slices: int

    def slice_time(self, i: int) -> datetime:
        return self.start_time + timedelta(seconds=i * self.interval_seconds)

