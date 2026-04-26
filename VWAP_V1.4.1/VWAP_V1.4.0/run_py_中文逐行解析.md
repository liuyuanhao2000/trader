# run.py 中文逐行解析

这个 Notebook 专门解释项目根目录下的 `run.py`。它不修改源代码，只帮助你理解：

- `run.py` 在整个 VWAP 项目里承担什么角色；
- 每一段代码的具体含义；
- `parse_args()` 和 `main()` 里每一行、每个结构在做什么；
- 如何调用运行；
- 运行后终端输出和 `execution_logs.jsonl` 日志结果怎么看。

> 重要提醒：下面的运行示例使用 `mock` 模拟交易所，不会连接真实交易所。若使用 Binance testnet 适配器，则需要配置 API Key，并且会访问测试网接口。

## 1. run.py 的整体作用

`run.py` 是这个项目的命令行启动入口。你可以把它理解成“总开关”：

1. 读取命令行参数，例如配置文件路径、模拟价格、启动延迟等；
2. 从 JSON 配置文件加载 VWAP 执行参数；
3. 根据配置选择交易所适配器：`mock` 模拟交易所或 `binance_spot_testnet`；
4. 创建日志收集器 `TransactionLog`；
5. 创建 VWAP 执行引擎 `VwapExecutionEngine`；
6. 异步执行 VWAP 拆单；
7. 把订单和告警日志写入 JSONL 文件；
8. 在终端打印最终执行摘要 `ExecutionSummary`。

它本身不负责具体拆单算法。真正的执行逻辑主要在：

- `vwap_executor/config.py`：配置结构和 JSON 读取；
- `vwap_executor/execution_engine.py`：根据现货/期货选择执行器；
- `vwap_executor/executors/spot_executor.py`：现货执行逻辑；
- `vwap_executor/executors/base_executor.py`：通用 VWAP 执行流程；
- `vwap_executor/exchange/mock.py`：模拟交易所撮合；
- `vwap_executor/logging_store.py`：订单和告警日志写入。

## 2. 原始 run.py 代码

下面是 `run.py` 当前代码，便于后面对照解释。


```python
from pathlib import Path

print(Path("run.py").read_text(encoding="utf-8"))
```

## 3. import 区域逐行解释

```python
from __future__ import annotations
# 启用 Python 未来版本的注解行为。
# 作用：类型注解可以延迟解析，减少循环引用或运行时解析类型带来的问题。
# 在本文件里，它让 `-> argparse.Namespace`、`-> None` 等类型提示更轻量。

import argparse
# 导入 Python 标准库 argparse。
# 作用：解析命令行参数，例如 --config、--initial-mid。

import asyncio
# 导入 Python 标准库 asyncio。
# 作用：运行异步函数 main()，因为 VWAP 执行过程中要等待下单时间点。

from datetime import datetime, timedelta
# 从 datetime 标准库导入两个对象：
# datetime：获取当前 UTC 时间，例如 datetime.utcnow()。
# timedelta：表示时间差，例如启动时间往后偏移 2 秒。

from vwap_executor import VwapConfig, VwapExecutionEngine
# 从项目包 vwap_executor 的 __init__.py 导入两个核心类：
# VwapConfig：负责把 JSON 配置转成程序内部配置对象。
# VwapExecutionEngine：VWAP 执行引擎，负责选择 spot/perp 执行器并启动执行。

from vwap_executor.exchange.binance_spot_testnet import BinanceSpotTestnetExchange
# 导入 Binance 现货测试网交易所适配器。
# 当配置 exchange.adapter == "binance_spot_testnet" 时使用。

from vwap_executor.exchange.mock import MockExchange
# 导入模拟交易所适配器。
# 当配置 exchange.adapter == "mock" 时使用，适合本地演示和测试。

from vwap_executor.exchange.credentials import load_exchange_credentials
# 导入读取交易所 API Key/API Secret 的函数。
# 当前实现从环境变量 EXCHANGE_API_KEY 和 EXCHANGE_API_SECRET 读取。

from vwap_executor.logging_store import TransactionLog
# 导入日志收集器。
# 作用：先收集订单日志和告警，最后统一写入 JSONL 文件。
```

## 4. parse_args() 函数逐行解释

`parse_args()` 的职责是读取命令行参数，并把参数结果返回给 `main()` 使用。
# 在你的代码里，典型用法是：
# args = parse_args()
# 然后通过属性读取参数值：
# args.config
# args.start_offset_seconds
# args.respect_config_start_time
# 小结：
# parse_args() 本身不做交易，它只负责“把命令行字符串 -> 结构化参数对象 args”。
# 真正业务逻辑在 main() 里用 args 的各字段继续执行。

完整加注释版本如下：

```python
def parse_args() -> argparse.Namespace:
    # 定义一个普通函数，函数名叫 parse_args。
    # -> argparse.Namespace 是类型注解，表示这个函数返回 argparse 解析后的命名空间对象。
    # Namespace 对象可以用 args.config、args.initial_mid 这种属性方式取参数。

    p = argparse.ArgumentParser()
    # 创建一个命令行参数解析器。
    # 变量 p 是 parser 的缩写。
    # 后续通过 p.add_argument(...) 注册支持哪些命令行参数。

    p.add_argument("--config", default="config/example_config.json") # 配置文件
    # 注册 --config 参数。
    # 参数形式：python run.py --config 某个配置文件路径
    # default="config/example_config.json" 表示如果用户不传 --config，就默认读取这个示例配置。
    # 这个配置文件里包含交易标的、买卖方向、名义金额、执行时长、交易所类型等。
    # 也就是说，python run.py 等价于 python run.py --config config/example_config.json（在 config 默认存在的前提下）
    # 命令行运行示例：
    # python run.py
    # python run.py --config config/example_config.json
    # python run.py --config config/binance_spot_testnet_example_config.json
    # python run.py --config /Users/wangbotao/Desktop/VWAP_V1.4/config/example_config.json
    # 可与其他参数组合：
    # python run.py --config config/example_config.json --start-offset-seconds 2
    # python run.py --config config/binance_spot_testnet_example_config.json --respect-config-start-time --start-offset-seconds 1
    # 这个参数是先传给 argparse 解析，再传给 VwapConfig.from_json_file(args.config) 去真正读取 JSON 配置内容。


    p.add_argument("--start-offset-seconds", type=int, default=2) # 启动偏移时间
    # 注册 --start-offset-seconds 参数。
    # type=int 表示命令行传入值会被转换成整数。
    # default=2 表示默认从当前时间往后推 2 秒启动。
    # 这个参数主要用于演示，避免配置文件里的固定 start_time 已经过期或太远。
    # 具体命令怎么写：
    # 用默认值（2秒）：
    # python run.py
    # 显式传 1 秒：
    # python run.py --start-offset-seconds 1
    # 传 5 秒并指定配置：
    # python run.py --config config/example_config.json --start-offset-seconds 5

    p.add_argument("--respect-config-start-time", action="store_true") # 尊重配置文件中的启动时间
    # 注册 --respect-config-start-time 布尔开关。
    # action="store_true" 的含义是：
    #   如果命令行出现这个参数，args.respect_config_start_time 就是 True；
    #   如果没出现，就是 False。
    # True 时程序会以配置文件 common.start_time 为基础。
    # False 时程序会强制改成当前 UTC 时间附近启动。
    # 运行命令示例：
    # 默认模式（不尊重配置时间，默认是当前 UTC 时间再往后偏移 2 秒）：
    # python run.py
    # 尊重配置文件中的启动时间：
    # python run.py --respect-config-start-time
    # 尊重配置时间，并额外偏移 3 秒：
    # python run.py --respect-config-start-time --start-offset-seconds 3
    # 配置文件 + 尊重配置时间：
    # python run.py --config config/example_config.json --respect-config-start-time

    p.add_argument("--initial-mid", type=float, default=65000.0) # 初始中间价
    # 注册 --initial-mid 参数。
    # type=float 表示转成浮点数。
    # 只在 mock 模拟交易所中使用。
    # 它表示模拟盘口的初始中间价，例如 BTCUSDT 初始价格 65000。
    # 使用默认值 65000.0
    # python run.py
    # 指定初始中间价为 70000
    # python run.py --initial-mid 70000
    # 配合配置文件一起传
    # python run.py --config config/example_config.json --initial-mid 62000.5

    # 注意：
    # 这是 mock 交易所里的“模拟市场初始状态”，不是币安测试网真实市场的第0秒状态。
    # 在 binance_spot_testnet 模式下，这两个值通常不决定真实行情。

    p.add_argument("--spread", type=float, default=20.0) # 初始价差
    # 注册 --spread 参数。
    # 只在 mock 模拟交易所中使用。
    # spread 是买一价 bid 和卖一价 ask 的差值。
    # 如果 initial_mid=65000，spread=20，则初始 bid 大约是 64990，ask 大约是 65010。
    # default=20.0：不传时默认20.0
    # 命令行示例：
    # python run.py
    # python run.py --spread 10
    # python run.py --initial-mid 65000 --spread 30
    # python run.py --config config/example_config.json --spread 15.5

    p.add_argument("--spot-initial-base-qty", type=float, default=0.01) # 初始现货基础数量
    # --spot-initial-base-qty：设置“现货基础资产”的初始持仓数量（base asset qty）
    # type=float：命令行传入值会转成浮点数
    # default=0.01：不传时默认初始持仓是 0.01（例如 BTC）
    # 这个参数主要用于 mock 模式：
    # 它决定模拟账户一开始有多少基础币可用（比如 BTC 数量）
    # 对 SELL 场景影响更明显：卖出现货不能超过你持有的基础币数量
    # 对 BUY 场景通常影响较小（买入主要受 quote 资金和下单逻辑限制）
    # 命令行运行示例：
    # python run.py
    # python run.py --spot-initial-base-qty 0.05
    # python run.py --config config/example_config.json --spot-initial-base-qty 0.2
    # python run.py --initial-mid 65000 --spread 20 --spot-initial-base-qty 0.1
    # 在 binance_spot_testnet 模式下，这个参数通常不决定真实账户持仓，真实可卖数量取决于测试网账户实际余额。

    return p.parse_args()
    # 真正解析命令行参数。
    # 返回 argparse.Namespace。
    # 例如：
    #   args.config
    #   args.start_offset_seconds
    #   args.respect_config_start_time
    #   args.initial_mid
    #   args.spread
    #   args.spot_initial_base_qty
```

这个函数只是解析参数，不执行交易、不读取配置、不写日志。

## 5. main() 函数逐行解释

`main()` 是真正的启动流程。它被定义为异步函数，因为执行引擎内部会根据 VWAP 时间表等待每个子订单的执行时间。

```python
async def main() -> None:
    # 定义异步函数 main。
    # async 表示函数内部可以使用 await。
    # -> None 表示这个函数没有显式返回值。

    args = parse_args()
    # 调用前面定义的 parse_args()。
    # 把命令行参数保存到 args。
    # 后面所有 args.xxx 都来自命令行或默认值。

    cfg = VwapConfig.from_json_file(args.config)
    # 从 JSON 配置文件读取 VWAP 配置。
    # args.config 默认是 config/example_config.json。
    # VwapConfig.from_json_file 会：
    #   1. 打开 JSON 文件；
    #   2. json.load 读取成 dict；
    #   3. 转成 VwapConfig、CommonInput、ExecutionParams 等 dataclass 对象。

    # 演示模式默认强制使用当前时间，避免示例因配置中固定时间而“等很久”。
    # 这是说明性注释。
    # 因为配置文件里的 start_time 可能是固定日期。
    # 如果直接尊重配置，程序可能等待很久，或者因为时间已过而立即执行。

    if args.respect_config_start_time:
        # 如果命令行传了 --respect-config-start-time，就进入这个分支。
        # 这个分支表示：以配置文件里的 cfg.common.start_time 为准。

        if args.start_offset_seconds is not None:
            # 检查 start_offset_seconds 是否不是 None。
            # 当前 add_argument 给了 default=2，所以正常情况下它一定不是 None。

            cfg.common.start_time = cfg.common.start_time + timedelta(seconds=args.start_offset_seconds)
            # 在配置文件原始 start_time 基础上增加偏移秒数。
            # 例如配置是 2026-04-02T15:30:00，offset=2，实际启动就是 15:30:02。
    else:
        # 如果没有传 --respect-config-start-time，就进入默认演示模式。

        cfg.common.start_time = datetime.utcnow() + timedelta(seconds=max(1, args.start_offset_seconds))
        # 把启动时间改成“当前 UTC 时间 + 偏移秒数”。
        # datetime.utcnow()：当前 UTC 时间。
        # max(1, args.start_offset_seconds)：至少偏移 1 秒，避免马上错过调度点。
        # 这会覆盖 JSON 配置里的 common.start_time。

    log = TransactionLog(output_jsonl_path=cfg.log_storage.output_jsonl_path)
    # 创建日志收集器。
    # cfg.log_storage.output_jsonl_path 来自配置文件 log_storage.output_jsonl_path。
    # 示例配置里是 execution_logs.jsonl。
    # 执行过程中订单日志先保存在内存里，最后调用 dump_jsonl() 写入文件。

    if cfg.exchange.adapter == "mock":
        # 如果配置文件里的 exchange.adapter 是 mock，使用模拟交易所。
        # 当前 config/example_config.json 没显式写 exchange，所以 ExchangeConfig 默认 adapter="mock"。

        exchange = MockExchange(
            # 创建 MockExchange 实例。
            # 这个对象提供 get_best_prices、place_limit_order、place_market_order 等交易所接口。

            symbol=cfg.common.symbol,
            # 交易对，例如 BTCUSDT。

            initial_mid=args.initial_mid,
            # 模拟盘口初始中间价，来自命令行 --initial-mid。

            spread=args.spread,
            # 模拟盘口价差，来自命令行 --spread。

            base_asset=cfg.common.base_currency,
            # 基础资产，例如 BTC。

            quote_asset=cfg.common.quote_currency,
            # 计价资产，例如 USDT。

            spot_initial_base_qty=args.spot_initial_base_qty,
            # 模拟账户初始基础资产数量，例如初始持有 0.01 BTC。

            params=cfg.execution,
            # 把执行参数传给 mock。
            # mock 会用其中的 mock_fill_sensitivity 等参数模拟成交难度和价格波动。
        )
        # MockExchange 创建完成后，变量 exchange 就是本次运行使用的交易所对象。

    elif cfg.exchange.adapter == "binance_spot_testnet":
        # 如果配置文件里的 exchange.adapter 是 binance_spot_testnet，使用 Binance 现货测试网。

        creds = load_exchange_credentials()
        # 从环境变量读取 API Key 和 API Secret。
        # 需要提前设置：
        #   EXCHANGE_API_KEY
        #   EXCHANGE_API_SECRET

        if not creds.api_key or not creds.api_secret:
            # 如果 key 或 secret 为空，就不能使用 Binance 适配器。

            raise RuntimeError(
                "Missing EXCHANGE_API_KEY / EXCHANGE_API_SECRET env vars for Binance adapter."
            )
            # 主动抛出 RuntimeError，提示缺少环境变量。
            # 这样可以避免程序带着空凭证继续请求交易所。

        exchange = BinanceSpotTestnetExchange(
            # 创建 Binance 现货测试网交易所实例。

            api_key=creds.api_key,
            # API Key。

            api_secret=creds.api_secret,
            # API Secret。

            symbol=cfg.common.symbol,
            # 交易对，例如 BTCUSDT。

            base_asset=cfg.common.base_currency,
            # 基础资产，例如 BTC。

            base_url=cfg.exchange.binance_base_url,
            # Binance 测试网地址，默认 https://testnet.binance.vision。

            params=cfg.execution,
            # 执行参数，例如价格偏移、订单间隔等。

            balance_cache_ttl_seconds=cfg.exchange.balance_cache_ttl_seconds,
            # 余额缓存时间，减少频繁查询余额。

            limit_order_poll_seconds=cfg.exchange.limit_order_poll_seconds,
            # 限价单提交后轮询成交状态的等待时间。
        )
        # BinanceSpotTestnetExchange 创建完成后，exchange 指向真实测试网适配器。

    else:
        # 如果 adapter 既不是 mock，也不是 binance_spot_testnet，就进入异常分支。

        raise ValueError(f"Unsupported exchange adapter: {cfg.exchange.adapter}")
        # 抛出 ValueError，说明配置文件里的交易所类型不被当前 run.py 支持。

    engine = VwapExecutionEngine(exchange=exchange, log=log)
    # 创建 VWAP 执行引擎。
    # exchange：刚才选择好的交易所对象。
    # log：日志收集器。
    # 引擎内部会根据 cfg.instrument_type 选择 SpotVwapExecutor 或 PerpVwapExecutor。

    summary = await engine.run(cfg)
    # 异步运行 VWAP 执行流程。
    # await 表示等待 engine.run(cfg) 完成。
    # 对 mock 示例来说，它会按 total_duration_seconds 和 order_interval_seconds 拆单执行。
    # 返回值 summary 是 ExecutionSummary，包含总名义金额、已成交金额、剩余未成交金额等。

    # 写日志
    # 说明性注释：下面要把内存里的订单日志/告警日志写入文件。

    log.dump_jsonl()
    # 如果配置里有 output_jsonl_path，就把日志写成 JSONL 文件。
    # JSONL 是一行一个 JSON 对象，方便后续用 pandas、脚本或日志系统读取。
    # 示例配置会写入 execution_logs.jsonl。

    print("ExecutionSummary:", summary)
    # 在终端打印最终执行摘要。
    # 输出大致像：
    # ExecutionSummary: ExecutionSummary(symbol='BTCUSDT', side='BUY', notional_total=10000.0, executed_notional=10000.0, remaining_unfilled_notional=0.0)
```

## 6. 文件末尾入口判断逐行解释

```python
if __name__ == "__main__":
    # Python 文件既可以被 import，也可以被直接运行。
    # 当你执行 python run.py 时，__name__ 的值就是 "__main__"。
    # 当别的文件 import run 时，__name__ 通常是 "run"。
    # 这个判断确保只有直接运行 run.py 时才启动交易流程。

    asyncio.run(main())
    # 用 asyncio.run 启动异步 main()。
    # 它会创建事件循环，运行 main，等待 main 完成，然后关闭事件循环。
```

为什么这里需要 `asyncio.run(main())`？因为 `main()` 是 `async def` 定义的异步函数，不能像普通函数那样直接 `main()` 就完成执行。直接 `main()` 只会得到一个协程对象，不会真正跑里面的逻辑。

## 7. 默认配置文件会触发什么行为

默认命令：

```bash
python run.py
```

等价于大致使用：

```bash
python run.py --config config/example_config.json --start-offset-seconds 2 --initial-mid 65000 --spread 20 --spot-initial-base-qty 0.01
```

`config/example_config.json` 的核心含义：

- `instrument_type: "spot"`：执行现货 VWAP；
- `symbol: "BTCUSDT"`：交易 BTCUSDT；
- `side: "BUY"`：买入；
- `notional: 10000`：目标成交名义金额 10000 USDT；
- `total_duration_seconds: 10`：总执行时长 10 秒；
- `order_interval_seconds: 2`：每 2 秒一笔子订单；
- `price_offset: -0.0003`：限价相对盘口价格做 -0.03% 偏移；
- `output_jsonl_path: "execution_logs.jsonl"`：执行日志写入这个文件；
- 没写 `exchange.adapter` 时，默认使用 `mock` 模拟交易所。

因此默认会把 10000 USDT 拆成约 5 个子订单，每笔约 2000 USDT。如果限价单没有全部成交，最后会用尾盘市价单补齐剩余金额。

## 8. 如何运行 mock 示例

在项目根目录运行：

```bash
python run.py --config config/example_config.json --start-offset-seconds 1
```

运行时长通常约为配置里的 `total_duration_seconds`，当前示例大约 10 秒。

注意：运行会根据配置覆盖写入 `execution_logs.jsonl`。如果你想保留旧日志，可以先把旧日志另存一份，或者修改配置文件里的 `log_storage.output_jsonl_path` 指向新文件。


```python
# 如果你想在 Notebook 中直接运行，可以取消下一行注释。
# 注意：这会执行 mock VWAP，并覆盖写入 execution_logs.jsonl。
# !python run.py --config config/example_config.json --start-offset-seconds 1
```

一次 mock 运行的终端输出示例：

```text
ExecutionSummary: ExecutionSummary(symbol='BTCUSDT', side='BUY', notional_total=10000.0, executed_notional=10000.0, remaining_unfilled_notional=0.0)
```

字段解释：

- `symbol='BTCUSDT'`：本次执行的交易对；
- `side='BUY'`：买入方向；
- `notional_total=10000.0`：目标总名义金额；
- `executed_notional=10000.0`：最终已成交名义金额；
- `remaining_unfilled_notional=0.0`：最终剩余未成交金额。

mock 交易所带有随机游走和成交模拟，但随机种子固定，所以同一套参数下结果通常比较稳定；时间戳会随运行时间变化。

## 9. 如何查看日志输出

运行完成后，日志文件默认是：

```text
execution_logs.jsonl
```

可以在终端查看前几行：

```bash
head -n 3 execution_logs.jsonl
```

也可以在 Notebook 里读取：


```python
from pathlib import Path
import json

log_path = Path("execution_logs.jsonl")
if log_path.exists():
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("日志条数:", len(rows))
    print("第一条日志:")
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))
else:
    print("还没有 execution_logs.jsonl，请先运行 run.py。")
```

日志常见字段解释：

- `type`：日志类型，通常是 `order` 或 `alert`；
- `sub_order_index`：子订单编号，`0, 1, 2...` 表示正常 VWAP 子订单，`-1` 表示尾盘强制市价单；
- `sub_order_time`：该子订单计划执行时间；
- `order_id`：订单 ID，mock 下由本地生成；
- `symbol`：交易对；
- `side`：买卖方向；
- `order_type`：订单类型，`LIMIT` 或 `MARKET`；
- `notional` / `ordered_notional`：本笔订单下单名义金额；
- `filled_notional`：本笔实际成交名义金额；
- `filled_qty`：成交数量，约等于成交名义金额 / 成交价格；
- `unfilled_notional`：本笔未成交名义金额；
- `unfilled_ratio`：本笔未成交比例；
- `limit_price`：限价单价格；市价单为 `null`；
- `avg_fill_price`：平均成交价格；
- `slippage_ratio`：滑点比例；
- `triggered_alarm`：是否触发告警；
- `alarm_type` / `alarm_message`：告警类型和告警信息；
- `raw.best_bid` / `raw.best_ask`：下单时参考的盘口买一/卖一价格；
- `raw.tail`：如果是尾盘强制成交订单，通常会出现 `tail: true`。

## 10. 如何使用 Binance Spot Testnet

如果要用 Binance 现货测试网，需要配置文件里使用：

```json
"exchange": {
  "adapter": "binance_spot_testnet",
  "binance_base_url": "https://testnet.binance.vision"
}
```

并在 shell 里设置环境变量：

```bash
export EXCHANGE_API_KEY="你的测试网 API Key"
export EXCHANGE_API_SECRET="你的测试网 API Secret"
```

然后运行类似：

```bash
python run.py --config config/binance_spot_testnet_example_config.json --start-offset-seconds 2
```

如果没有设置环境变量，`run.py` 会抛出：

```text
RuntimeError: Missing EXCHANGE_API_KEY / EXCHANGE_API_SECRET env vars for Binance adapter.
```

这是一个保护措施，避免程序拿空凭证访问交易所。

## 11. run.py 的调用链总结

从入口到结果的调用链可以概括为：

```text
python run.py
  -> asyncio.run(main())
    -> parse_args()
    -> VwapConfig.from_json_file(args.config)
    -> 调整 cfg.common.start_time
    -> TransactionLog(...)
    -> 根据 cfg.exchange.adapter 创建 MockExchange 或 BinanceSpotTestnetExchange
    -> VwapExecutionEngine(exchange=exchange, log=log)
    -> await engine.run(cfg)
       -> 根据 cfg.instrument_type 选择 SpotVwapExecutor 或 PerpVwapExecutor
       -> 执行 VWAP 时间切片、限价单、风险检查、尾盘市价补单
    -> log.dump_jsonl()
    -> print("ExecutionSummary:", summary)
```

一句话总结：`run.py` 不实现核心交易算法，而是负责把配置、交易所适配器、日志和执行引擎组装起来，然后启动一次完整 VWAP 执行。
