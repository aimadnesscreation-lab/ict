# Institutional AI Trading Intelligence Platform

A production-ready algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes real-time OHLCV data through a 7-module ICT pipeline, scores confluences with a dual-scoring signal engine, manages a forward-testing demo account, mirrors trades onto Binance Spot (LONG only), and surfaces everything through a React dashboard and Discord webhook alerts.

---

## 📊 Backtest Results

### Full Strategy (LONG + SHORT) — 12 Months

| Metric | BTCUSDT | ETHUSDT | **Combined** |
|--------|---------|---------|-------------|
| **Total Trades** | 936 | 1,584 | **2,520** |
| **Win Rate** | 37.8% | 39.0% | **38.6%** |
| **Total P&L** | $6,397.05 | $14,599.89 | **$20,996.94** |
| **Total Return** | — | — | **419.94%** |
| **Avg Monthly P&L** | $533.09 | $1,216.66 | **$1,749.74** |
| **Avg R:R** | 1.38 | 1.39 | **1.39** |

### Spot-Only (LONG Only — Matches Binance Spot) — 12 Months

| Metric | BTCUSDT | ETHUSDT | **Combined** |
|--------|---------|---------|-------------|
| **Total LONG Trades** | 749 | 1,412 | **2,161** |
| **Win Rate** | 37.5% | 39.4% | **38.7%** |
| **Total P&L** | $4,771.43 | $14,334.84 | **$19,106.27** |
| **Total Return** | — | — | **382.13%** |

> **Note:** Results vary by ~10-15% between runs due to live-fetched data and shifting 30-day month boundaries. Run `python backtest_okx.py --months 12` to get current numbers.

---

## 🏗️ Architecture Overview

```
OKX REST API / Binance REST + WebSocket (15s poll)
                    │
                    ▼
  ┌─────────────────────────┐     ┌──────────────────────────┐
  │    ICT Engine            │────▶│  Signal Engine            │
  │  (7 vectorized modules)  │     │  (dual-scoring 0-100)    │
  └─────────────────────────┘     └────────────┬─────────────┘
            ▲                                   │
            │                                   ▼
  ┌─────────────────────────┐     ┌──────────────────────────┐
  │   Candle Buffers         │     │  Demo Account ($5,000)   │
  │  (5m / 15m / 1m)        │     │  (forward-testing)       │
  └─────────────────────────┘     └────────────┬─────────────┘
            ▲                                   │
            │                                   ▼
  ┌─────────────────────────┐     ┌──────────────────────────┐
  │  HTF Bias Worker         │     │  LiveExecutor + SyncWorker│
  │  (1h EMA, 15min cycle)   │     │  (Binance Spot, 30s sync)│
  └─────────────────────────┘     └────────────┬─────────────┘
            ▲                                   │
            │                                   ▼
  ┌─────────────────────────┐     ┌──────────────────────────┐
  │  OKX ↔ Binance Fallback  │     │  Discord Bot + FastAPI   │
  │  (no API key needed)     │     │  (alerts + dashboard)    │
  └─────────────────────────┘     └──────────────────────────┘
```

### Layer 1: ICT Engine (`ict_engine/`)

7 vectorized **Polars**-based modules that run on every 5m candle close:

| Module | File | Detection | Confluence Pts |
|---|---|---|---|
| **Market Structure** | `market_structure.py` | Swing highs/lows, Break of Structure (BOS), Market Structure Shift (MSS) | 20 |
| **Liquidity** | `liquidity.py` | Equal highs/lows, liquidity sweeps, previous day high/low | 20 |
| **Fair Value Gap** | `fvg.py` | 3-candle imbalances (bullish/bearish) with status tracking | 15 |
| **Order Blocks** | `order_blocks.py` | Last candle before >2× ATR impulse, with validity tracking | 15 |
| **Premium/Discount** | `premium_discount.py` | Equilibrium zones + OTE (62-79% fib) | 10 + 10 |
| **Sessions** | `sessions.py` | Asian/London/NY sessions + Kill Zones | 10 |
| **Breaker Blocks** | `breaker_block.py` | Order block failures that reverse role | — |

### Layer 2: Signal Engine (`signal_engine/engine.py`)

Unique **dual-scoring** system (bullish vs. bearish independently, 0-100 each):

- `net = bullish - bearish` determines signal direction
- `confidence = max(bullish, bearish)` determines signal strength
- **net ≥ 60** → STRONG_BUY, **net ≥ 30** → BUY, **net > -30** → NEUTRAL, etc.
- HTF alignment: signals must align with 1h EMA bias (12/26, 0.5% threshold)
- Entry requires: **score ≥ min_score AND inside a kill zone AND HTF aligned**

### Layer 3: Demo Account (`demo_account.py`)

Stateful forward-testing engine:
- **$5,000** paper capital (configurable via `DEMO_INITIAL_BALANCE` env var)
- **1% risk** per trade (of current balance)
- **0.5× ATR** stop loss (per-symbol via `symbol_sl_multipliers`), **1:2** risk-reward
- **0 min** re-entry cooldown
- **min_score = 60** for entries (per-symbol via `symbol_min_scores`)
- Max **3 open positions** across all symbols
- **3% daily loss limit** (circuit breaker, auto-resets at UTC day change)
- Tracks P&L, win rate, profit factor, max drawdown, average R:R

### Layer 4: Live Execution (`execution/`)

- **LiveExecutor** (`executor.py`): Connects to Binance Spot via CCXT (demo trading portal or testnet)
  - Places market buy orders with OCO (One-Cancels-Other) for SL + TP
  - **Spot-only: SHORT signals are filtered upstream** — DemoAccount never opens SHORT positions when an exchange is connected
  - Caps position sizes to available USDT balance (spot is 1:1, no leverage)
- **SyncWorker** (`sync_worker.py`): Reconciles DemoAccount with exchange positions every 30s
  - Detects SL/TP hits on exchange → closes in DemoAccount
  - Detects manual closes → records with SYNC_ prefix
  - Logs quantity/side discrepancies

### Layer 5: API + Dashboard

**Backend** (`api/main.py`):
- **FastAPI** server with dual data source (OKX REST ↔ Binance REST, no API key needed)
- 3 background workers: crypto data fetcher (15s poll), HTF bias updater (15min), exchange sync (30s)
- WebSocket endpoint (`/ws/prices`) for live streaming with mock fallback
- **Smart fallback**: silently probes OKX and Binance on startup, uses the working source, re-probes fallback every 30min
- Endpoints: `/signals`, `/trades`, `/performance`, `/demo/account`, `/risk/status`, `/candles/{symbol}`, `/backtest-data/{symbol}`, `/reset`, `/sync`, `/api/health`
- Self-contained: mounts dashboard static build at `/dashboard`
- `POST /reset` — clears all DemoAccount state, signals, trades for a fresh start

**Frontend** (`dashboard/`):
- React 19 + TypeScript + Vite + Tailwind CSS v4
- 6 pages: Overview, Signals (with detail panel), Charts (with EMA bias), Trade Log (with open positions), Risk Center (with position sizing calculator), Settings (with live signal weight config)
- Lightweight Charts (TradingView) for candlestick visualization
- TanStack Query for data fetching with auto-refresh
- WebSocket price stream with auto-reconnect and exponential backoff → mock fallback
- Unit tested: `usePriceStream.test.ts` covers connect, reconnect, backoff, fallback, malformed messages

**Discord Bot** (`discord/bot.py`):
- Sends formatted embedded messages via webhook
- Triggers on signals with **score ≥ 80 AND in kill zone**
- Shows confluence breakdown, price levels, trend bias, price movement from trigger

---

## 📊 Current Configuration (Optimized)

| Parameter | BTCUSDT | ETHUSDT |
|---|---|---|
| **ATR SL Multiplier** | 0.5× | 0.5× |
| **Min Score Threshold** | 60 | 60 |
| **Re-entry Cooldown** | 0 min | 0 min |
| **Risk Per Trade** | 1% | 1% |
| **Max Positions** | 3 (shared) | 3 (shared) |
| **Kill Zone Required** | Yes | Yes |
| **HTF Alignment** | Yes | Yes |
| **Data Source** | OKX / Binance (auto-fallback) | OKX / Binance (auto-fallback) |

### Optimization History

| Config | ETH P&L (12mo) | BTC P&L (12mo) | Combined |
|---|---|---|---|
| Original (BTC 1.0×/0cd/70, ETH 2.0×/60cd/80) | +$2,147 | +$3,867 | **+$6,013** |
| Tight SL (both 0.5×, ETH 60cd/80) | +$5,135 | +$19,786 | **+$24,921** |
| **Unified (both 0.5×/0cd/70)** | **+$18,635** | **+$19,786** | **+$38,421** |
| **Optimized (both 0.5×/0cd/60)** | **+$25,582** | **+$23,042** | **+$48,624** |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+ (for dashboard)
- Binance API keys (for exchange execution — optional, signals work without them)

### One-Command Start

```bash
./start.sh
```

This runs the full stack: Python venv setup → pip install → npm install → connection test → API server → dashboard.

### Manual Backend Setup

```bash
# Virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start API server
uvicorn api.main:app --reload --port 8000
```

### Dashboard Setup

```bash
cd dashboard
npm install
npm run dev
```

Then open `http://localhost:5173/dashboard/` (or `http://localhost:8000/dashboard` if using the API server's static mount).

### Running Backtests

```bash
# 12-month rolling backtest (all months, sequential)
python backtest_okx.py

# 12-month spot-only backtest (LONG only, matches Binance Spot)
python backtest_okx.py --spot

# Single month (offset 0 = newest, 11 = oldest)
python backtest_okx.py --offset 3

# Parallel symbol processing (faster but both symbols at once)
python backtest_okx.py --parallel

# Custom capital (default: $5,000)
python backtest_okx.py --capital 10000

# Single symbol
python backtest_okx.py --symbol ETHUSDT

# Per-trade forensic debug analysis
python backtest_okx.py --debug --offset 2
```

---

## 🧪 Testing

```bash
# ICT engine unit tests (Python)
pytest tests/test_ict_engine.py -v

# Dashboard unit tests (Vitest)
cd dashboard && npm test

# Connection test (verifies Binance demo credentials)
python test_live_connection.py

# Integration test (starts server, monitors data flow)
python test_integration.py
```

---

## 🐳 Deployment

The system is designed to run on **Railway** (or any cloud host):

```bash
# Use the render.yaml for Railway deployment
```

Environment variables (see `.env.example`):
- `BINANCE_API_KEY` / `BINANCE_SECRET` — Binance exchange credentials (optional)
- `DISCORD_WEBHOOK_URL` — Discord channel webhook for signal alerts (optional)
- `DEMO_INITIAL_BALANCE` — Paper trading starting capital (default: 5000)
- `EXCHANGE_MODE` — `demo` (default) or `live`
- `EXCHANGE_NAME` — `binance` (default) or `okx`

---

## 📈 Backtesting Framework

### `backtest_okx.py`
- Fetches 30 days of 5m data per month via OKX history API (falls back to Binance klines)
- **Key optimization**: pre-computes all 7 ICT modules once (vectorized Polars) instead of re-running per candle
- Walks candle-by-candle to match live system logic exactly
- Tracks signals generated, kept, bias changes, and trade execution
- Outputs per-month results and N-month aggregate summary
- Supports `--months N`, `--offset N`, `--parallel`, `--symbol S`, `--capital N`, `--spot`, `--debug` flags
- `--debug` flag enables per-trade forensic analysis: held candles, SL/TP distances, consecutive loss streaks, re-entry patterns
- Saves trade log as JSON when `--debug` is used

---

## 🔐 Risk Management

The system enforces multiple layers of risk controls:

| Control | Value | Description |
|---------|-------|-------------|
| **Risk Per Trade** | 1% | Fixed % of current account balance |
| **Daily Loss Limit** | 3% | Circuit breaker — stops trading after this loss |
| **Max Open Positions** | 3 | Shared across all symbols |
| **Re-entry Cooldown** | 0 min | No wait between same-direction entries |
| **Stop Loss** | 0.5× ATR | Per-symbol ATR multiplier |
| **Take Profit** | 2× SL distance | Fixed 1:2 risk-reward |

The **Risk Center** dashboard page includes a Position Sizing Calculator that computes position size, risk amount, potential profit, and R:R ratio from account balance, risk %, entry, and stop/target prices.

---

## 🔧 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Root — status + version |
| `GET /api/health` | System health — prices, bias, uptime, cycle counts |
| `GET /signals?limit=N` | Recent ICT-generated signals |
| `GET /signals/{id}` | Single signal detail |
| `GET /candles/{symbol}?timeframe=X&limit=N` | OHLCV candles from OKX/Binance |
| `GET /backtest-data/{symbol}?days=N&bar=X` | Paginated historical OHLCV for backtesting |
| `GET /trades?limit=N&result=X&symbol=Y` | Closed trades from DemoAccount |
| `GET /performance` | Computed performance metrics |
| `GET /demo/account` | Demo account — balance, open positions, P&L |
| `GET /risk/status` | Current risk management state |
| `POST /reset` | Clear all DemoAccount state for fresh start |
| `POST /sync` | Manually trigger exchange position reconciliation |
| `WS /ws/prices` | WebSocket live price stream |

---

## 📁 Project Structure

```
├── ict_engine/              # ICT mathematical core (7 modules)
│   ├── market_structure.py   # Swing highs/lows, BOS, MSS
│   ├── liquidity.py          # Equal highs/lows, sweeps, prev day levels
│   ├── fvg.py                # Fair Value Gaps with status tracking
│   ├── order_blocks.py       # Order block detection with validity
│   ├── premium_discount.py   # Equilibrium, OTE (62-79% fib) zones
│   ├── sessions.py           # Trading sessions, kill zones
│   ├── breaker_block.py      # Breaker blocks
│   └── utils.py              # ATR, SMMA calculations
├── signal_engine/
│   └── engine.py             # Dual-scoring confluence engine (0-100)
├── execution/
│   ├── executor.py           # Binance Spot demo trading (CCXT, OCO orders)
│   └── sync_worker.py        # DemoAccount ↔ exchange reconciliation
├── api/
│   ├── main.py               # FastAPI server + 3 background workers
│   └── static/               # Dashboard build output (auto-built)
├── dashboard/                # React 19 frontend
│   └── src/
│       ├── pages/            # Overview, Signals, Charts, TradeLog, RiskCenter, Settings
│       ├── components/       # Layout, ICTChart, EMABiasChart
│       ├── services/         # api.ts, settingsService.ts (localStorage persisted)
│       ├── utils/            # signalCalculator.ts (heuristic signal inference)
│       └── hooks/            # usePriceStream.ts (WS + mock fallback)
├── discord/
│   └── bot.py                # Discord webhook notifier (rich embeds)
├── risk/
│   └── manager.py            # Risk management rules engine
├── tests/
│   └── test_ict_engine.py    # ICT engine unit tests
├── backtest_okx.py           # 12-month rolling backtest
├── demo_account.py           # Forward-testing engine
├── test_live_connection.py   # Binance demo connection test
├── test_integration.py       # End-to-end integration test
├── start.sh                  # One-command startup script
└── render.yaml               # Railway deployment blueprint
```

---

## 📚 ICT Concepts Implemented

### Market Structure
- **Swing High/Low**: N-candle lookback (default N=3) peak/trough detection
- **Break of Structure (BOS)**: Close above swing high (bullish) or below swing low (bearish)
- **Market Structure Shift (MSS)**: Previous swing taken + close beyond recent opposing swing
- **Trend Bias**: HH+HL sequence = bullish, LL+LH = bearish

### Liquidity
- **Equal Highs/Lows**: Within ATR × 0.10 threshold
- **Liquidity Sweeps**: Break below/above liquidity then close back above/below
- **Previous Day levels**: High, low, open, close (computed from daily aggregation)

### Fair Value Gaps
- **Bullish FVG**: Candle1 high < Candle3 low (gap upward)
- **Bearish FVG**: Candle1 low > Candle3 high (gap downward)
- Status tracking: OPEN → TOUCHED → FILLED

### Order Blocks
- **Bullish OB**: Last bearish candle before >2× ATR bullish impulse
- **Bearish OB**: Last bullish candle before >2× ATR bearish impulse
- Validity tracking: UNTOUCHED → TOUCHED → MITIGATED → INVALIDATED

### Premium / Discount
- **Equilibrium**: (high + low) / 2 over recent range (swing-based, falls back to 20-candle range)
- **Premium**: Price above equilibrium (overvalued — bearish bias)
- **Discount**: Price below equilibrium (undervalued — bullish bias)
- **OTE Zone**: 62%–79% Fibonacci retracement (optimal trade entry)

### Sessions & Kill Zones (Crypto)
- **Asian Session**: 00:00–09:00 UTC
- **London Session**: 08:00–17:00 UTC
- **New York Session**: 13:00–22:00 UTC
- **London Kill Zone**: 07:00–09:00 UTC
- **New York Kill Zone**: 13:00–15:00 UTC
- **London Close**: 17:00–18:00 UTC

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. No live trade execution is enabled by default. Trading financial markets involves significant risk of loss. Past backtest performance does not guarantee future results. The system uses a demo/sandbox exchange environment by default — no real funds are traded unless `EXCHANGE_MODE=live` is explicitly set.
