from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

from vwap_executor import VwapConfig, VwapExecutionEngine
from vwap_executor.exchange.binance_spot_testnet import BinanceSpotTestnetExchange
from vwap_executor.exchange.mock import MockExchange
from vwap_executor.exchange.credentials import load_exchange_credentials
from vwap_executor.logging_store import TransactionLog


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/example_config.json") # 配置文件
    p.add_argument("--start-offset-seconds", type=int, default=2) # 启动偏移时间
    p.add_argument("--respect-config-start-time", action="store_true") # 尊重配置文件中的启动时间
    p.add_argument("--initial-mid", type=float, default=65000.0) # 初始中间价
    p.add_argument("--spread", type=float, default=20.0) # 初始价差
    p.add_argument("--spot-initial-base-qty", type=float, default=0.01) # 初始现货基础数量
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    cfg = VwapConfig.from_json_file(args.config)

    # 演示模式默认强制使用当前时间，避免示例因配置中固定时间而“等很久”。
    if args.respect_config_start_time:
        if args.start_offset_seconds is not None:
            cfg.common.start_time = cfg.common.start_time + timedelta(seconds=args.start_offset_seconds)
    else:
        cfg.common.start_time = datetime.utcnow() + timedelta(seconds=max(1, args.start_offset_seconds))

    log = TransactionLog(output_jsonl_path=cfg.log_storage.output_jsonl_path)

    if cfg.exchange.adapter == "mock":
        exchange = MockExchange(
            symbol=cfg.common.symbol,
            initial_mid=args.initial_mid,
            spread=args.spread,
            base_asset=cfg.common.base_currency,
            quote_asset=cfg.common.quote_currency,
            spot_initial_base_qty=args.spot_initial_base_qty,
            params=cfg.execution,
        )
    elif cfg.exchange.adapter == "binance_spot_testnet":
        creds = load_exchange_credentials()
        if not creds.api_key or not creds.api_secret:
            raise RuntimeError(
                "Missing EXCHANGE_API_KEY / EXCHANGE_API_SECRET env vars for Binance adapter."
            )
        exchange = BinanceSpotTestnetExchange(
            api_key=creds.api_key,
            api_secret=creds.api_secret,
            symbol=cfg.common.symbol,
            base_asset=cfg.common.base_currency,
            base_url=cfg.exchange.binance_base_url,
            params=cfg.execution,
            balance_cache_ttl_seconds=cfg.exchange.balance_cache_ttl_seconds,
            limit_order_poll_seconds=cfg.exchange.limit_order_poll_seconds,
        )
    else:
        raise ValueError(f"Unsupported exchange adapter: {cfg.exchange.adapter}")

    engine = VwapExecutionEngine(exchange=exchange, log=log)
    summary = await engine.run(cfg)

    # 写日志
    log.dump_jsonl()

    print("ExecutionSummary:", summary)


if __name__ == "__main__":
    asyncio.run(main())

