from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str


def load_exchange_credentials() -> ExchangeCredentials:
    """
    交易所 API Key 预留位置（当前示例用的是 MockExchange，不会读取这些值）。

    建议：
    - 使用环境变量注入（例如通过你的 shell profile 或 secrets manager）
    - 线上/实际交易时在 exchange adapter（如 Binance/OKX）里读取并使用
    """

    api_key = os.getenv("EXCHANGE_API_KEY", "")
    api_secret = os.getenv("EXCHANGE_API_SECRET", "")
    # 允许空：因为本 repo 的演示用 MockExchange
    return ExchangeCredentials(api_key=api_key, api_secret=api_secret)

