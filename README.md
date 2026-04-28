# nexus-quant-architecture

![CI](https://github.com/jaycode0101/nexus-quant-architecture/workflows/CI/badge.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)

A systematic trading framework built for quantitative researchers and developers.
It supports equities, crypto, forex, futures, and ETFs across any venue reachable
by your data provider or broker adapter.

Bring your own data source. Bring your own broker. Bring your own model. The
architecture handles signal generation, backtesting, risk management, execution
simulation, and optional low-level market-data experiments.

Works offline with local data files. Works live only when you connect a real data
provider and broker adapter. No terminal subscription required.

## Project Status

This is a personal quant engineering project in active development.

I open-sourced it before calling it finished because the goal is to learn in
public, document the architecture honestly, and invite feedback from people who
understand trading systems, market data, low-latency engineering, or quantitative
research.

The Python research layer is the most usable part today. The C11 and Java layers
are included as an optional systems track for tick-level ingestion, event
processing, and shared-memory experiments. They are not required for the Python
backtesting workflow.

This is not a live trading product. Treat it as a research and engineering lab.

## What It Actually Does

Today, the runnable path is the Python strategy layer:

- downloads or loads OHLCV data
- computes technical, volatility, sentiment, and regime features
- aggregates signals into BUY, SELL, HOLD-style decisions
- applies position sizing, stops, and circuit breakers
- can call an LLM provider for explanation and conflict checks
- is being extended with vectorized backtesting and paper execution

The C11 and Java folders are not decoration. They model a lower-latency path:
market-data ingestion, ring-buffer handoff, event orchestration, order-book
features, Hawkes intensity, and HMM regimes. The shared-memory bridge is the
integration path that will let those features feed Python without turning Python
into a low-level event engine.

## Architecture

```text
Layer 1 - Data plane (C11)
  [feed adapter] -> [normalizer] -> [SPSC ring buffer] -> [shared memory]

Layer 2 - Orchestration (Java)
  [Disruptor pipeline] -> [order book] -> [Hawkes intensity] -> [HMM regimes]
                                      |
                                      v
Layer 3 - Strategy (Python)
  [data provider] -> [features] -> [signals] -> [risk] -> [paper/live broker]
                                      |
                                      v
                              [LLM explanation layer]
```

The layers are separated on purpose:

- Python is the right tool for research, backtesting, and strategy iteration.
- Java is useful for event orchestration and stateful pipelines.
- C11 is useful for memory layout, lock-free queues, and feed-ingestion
  experiments.

Run Python only if you want research and backtesting. Enable Java/C11 if you want
to explore tick-level event pipelines and shared-memory integration.

## Quick Start

### Python research path

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python autonomous_agent.py
```

### Local LLM path

```bash
ollama pull llama3.2
copy .env.example .env
python autonomous_agent.py
```

### Full systems path

```bash
cd hft/c_data_plane
cmake -B build
cmake --build build

cd ../java_orchestration
mvn test
```

## Configuration

Market selection is configuration, not code identity.

```text
Supported markets, configured via MARKET in .env:
  equities - any venue supported by your data provider
  crypto   - spot and derivatives pairs via exchange adapters
  forex    - major and minor pairs via broker or data feed
  futures  - index, commodity, rate, and volatility contracts
  ETFs     - any ETF tradable through your broker adapter
```

Default examples use broad, recognizable instruments:

```text
WATCHLIST=SPY,QQQ,BTC-USD,AAPL,MSFT
SESSION_OPEN=09:30
SESSION_CLOSE=16:00
SESSION_TZ=UTC
COMMISSION_BPS=5
SLIPPAGE_BPS=2
```

Change those for your venue, broker, asset class, and account currency.

## LLM Providers

The LLM is not the trader. It reads a prepared market snapshot and explains,
challenges, or summarizes the signal. Orders should still pass deterministic
risk gates.

| Provider | What you need | Typical use |
|---|---:|---|
| Ollama | local model | offline/private development |
| Claude | API key | deeper reasoning |
| OpenAI | API key | general strategy synthesis |
| Gemini | API key | alternate hosted model |
| Groq | API key | fast inference |

Set `LLM_PROVIDER` in `.env`. If it is not set, the code uses Ollama.

## Data Providers

The project should accept data from multiple sources behind the same interface:

- local CSV or Parquet files
- yfinance for research data
- CCXT for exchange-normalized crypto data
- broker market-data APIs
- custom feed adapters
- the C11/Java shared-memory path for tick-level experiments

For any serious live workflow, use licensed data that matches your trading
permissions and latency needs.

## Broker Adapters

Broker support should be plugin-based. No broker is the project default.

```text
Broker adapters:
  PaperBroker          - local simulation, no real money
  AlpacaBroker         - broker API with paper environment
  InteractiveBroker    - multi-asset broker adapter
  CcxtBroker           - crypto exchange adapter through CCXT
  TradierBroker        - options and equities adapter
  CustomBroker         - implement BaseBroker for your account
```

The important part is the `BaseBroker` interface: submit, cancel, positions,
balances, fills, and account state.

## Backtesting

Backtests are where strategy claims either earn trust or die quietly.

Planned engine contract:

```python
from trading_model.backtest.engine import VectorizedBacktest

engine = VectorizedBacktest(initial_capital=100_000, commission_bps=5)
result = engine.run(ohlcv, signals)

print(result.metrics["sharpe"])
print(result.metrics["max_drawdown_pct"])
```

The engine should model signal delay, slippage, commission, turnover, drawdown,
holding period, and profit factor. A strategy without costs is not evidence.

## C11 And Java Track

Why keep the systems layer?

Python can handle prediction, research, and most portfolio workflows. It is not
the right place to experiment with cache-aligned structs, lock-free rings, or
low-level event handoff. The C11 and Java layers explore those ideas behind a
clean boundary.

Current goal:

- C11 normalizes market events into a stable binary layout
- Java consumes or enriches those events through an event pipeline
- Python reads the shared-memory output and turns microstructure features into
  strategy inputs

Until the bridge is fully tested, this path is experimental.

## Mathematical Foundations

Models used or planned:

- Hawkes process for self-exciting event intensity
- Avellaneda-Stoikov quoting for inventory-aware market making
- Hidden Markov Models for regime classification
- Yang-Zhang realized volatility for OHLC-based volatility
- Kelly-style sizing with conservative fractional caps
- Circuit breakers for stale data, volatility spikes, signal conflict, and risk
  budget violations

## Help Wanted

Useful contributions right now:

- review the C11/Java shared-memory bridge design
- improve the backtesting assumptions and transaction cost model
- add broker and data-provider adapters behind common interfaces
- add tests for market-data edge cases
- review risk controls before any live execution path is enabled
- improve docs where the current status is unclear

## Contributing

Small commits are preferred. One logical change per commit. If a change touches
strategy math and broker execution, it is probably two commits.

Good commit messages:

```text
backtest: charge commission on position changes
bridge: parse tick flags from shared memory slot
risk: cap Kelly sizing during high-vol regimes
docs: explain Python-only and systems-track workflows
```

## License

Apache License 2.0. See `LICENSE`.
