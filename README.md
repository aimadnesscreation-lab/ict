# Institutional AI Trading Intelligence Platform

A production-ready algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes real-time OHLCV data through a 7-module ICT pipeline, scores confluences with a dual-scoring signal engine, manages a forward-testing demo account, and surfaces everything through a React dashboard and Discord webhook alerts.

**12-Month Backtest Result (BTC + ETH, Jul 2025 – Jun 2026): +384% return on $10k capital**

---

## 🏗️ Architecture Overview

```
OKX REST API (15s poll)
        │
        ▼
  ┌─────────────────┐     ┌──────────────────────────┐
  │  ICT Engine      │────▶│  Signal Engine            │
  │  (7 modules)     │     │  (dual-scoring 0-100)    │
  └─────────────────┘     └────────────┬─────────────┘
            ▲                          │
            │                          ▼
  ┌─────────────────┐     ┌──────────────────────────┐
  │  Candle Buffers  │     │  Demo Account            │
  │  (5m / 15m)     │     │  ($10k, forward-test)    │
  └─────────────────┘     └────────────┬─────────────┘
            ▲                          │
            │                          ▼
  ┌─────────────────┐     ┌──────────────────────────┐
  │  HTF Bias Worker│     │  Discord Bot + API       │
  │  (1h EMA, 15min)│     │  (alerts + dashboard)    │
  └─────────────────┘     └──────────────────────────┘
```

### Layer 1: ICT Engine (`ict_engine/`)

7 vectorized Polars-based modules that run on every 5m candle close:

| Module | File | Detection | Confluence Pts |
|---|---|---|---|
| **Market Structure** | `market_structure.py` | Swing highs/lows, Break of Structure (BOS), Market Structure Shift (MSS) | 20 |
| **Liquidity** | `liquidity.py` | Equal highs/lows, liquidity sweeps | 20 |
| **Fair Value Gap** | `fvg.py` | 3-candle imbalances (bullish/bearish) | 15 |
| **Order Blocks** | `order_blocks.py` | Last candle before >2× ATR impulse | 15 |
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
- **$10,000** paper capital
- **1% risk** per trade (of current balance)
- **0.5× ATR** stop loss, **1:2** risk-reward (TP = 2 × SL distance)
- **0 min** re-entry cooldown (was 60 min for ETH, optimized away)
- **min_score = 70** for entries (was 80 for ETH, optimized away)
- Max **3 open positions** across all symbols
- **3% daily loss limit** (circuit breaker)
- Tracks P&L, win rate, profit factor, max drawdown, average R:R

### Layer 4: API + Dashboard

**Backend** (`api/main.py`):
- **FastAPI** server with OKX REST API (15s polling, no API key needed)
- Background workers: crypto data fetcher + HTF bias updater
- WebSocket endpoint (`/ws/prices`) for live streaming
- Endpoints: `/signals`, `/trades`, `/performance`, `/demo/account`, `/risk/status`, `/candles/{symbol}`, `/backtest-data/{symbol}`
- Self-contained: mounts dashboard static build at `/dashboard`

**Frontend** (`dashboard/`):
- React 19 + TypeScript + Vite + Tailwind CSS v4
- 6 pages: Overview, Signals, Charts, Trade Log, Risk Center, Settings
- Lightweight Charts (TradingView) for candlestick visualization
- TanStack Query for data fetching
- WebSocket price stream with auto-reconnect

**Discord Bot** (`discord/bot.py`):
- Sends formatted embedded messages via webhook
- Triggers on signals with **score ≥ 80 AND in kill zone**
- Shows confluence breakdown, price levels, trend bias

---

## 📊 Current Configuration (Optimized)

| Parameter | BTCUSDT | ETHUSDT |
|---|---|---|
| **ATR SL Multiplier** | 0.5× | 0.5× |
| **Min Score Threshold** | 70 | 70 |
| **Re-entry Cooldown** | 0 min | 0 min |
| **Risk Per Trade** | 1% | 1% |
| **Max Positions** | 3 (shared) | 3 (shared) |
| **Kill Zone Required** | Yes | Yes |
| **HTF Alignment** | Yes | Yes |
| **Data Source** | OKX REST (15s) | OKX REST (15s) |

### Optimization History

| Config | ETH P&L (12mo) | BTC P&L (12mo) | Combined |
|---|---|---|---|
| Original (BTC 1.0×/0cd/70, ETH 2.0×/60cd/80) | +$2,147 | +$3,867 | **+$6,013** |
| Tight SL (both 0.5×, ETH 60cd/80) | +$5,135 | +$19,786 | **+$24,921** |
| **Unified (both 0.5×/0cd/70)** | **+$18,635** | **+$19,786** | **+$38,421** |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+ (for dashboard)
- Docker & Docker Compose (optional, for PostgreSQL)

### Backend Setup

```bash
# Virtual environment
python3 -m venv .venv
source .venv/bin/activate

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

### Running Backtests

```bash
# 12-month rolling backtest (all months)
python backtest_okx.py

# Single month (offset 0 = newest, 11 = oldest)
python backtest_okx.py --offset 3

# Parallel symbol processing (faster)
python backtest_okx.py --parallel

# Per-trade forensic debug analysis
python debug_backtest.py --symbol ETHUSDT --offset 2
```

---

## 🧪 Testing

```bash
# Run ICT engine unit tests
pytest tests/test_ict_engine.py -v

# Smoke test (requires API server running)
python smoke_test.py
```

---

## 🐳 Deployment

The system is designed to run on **Railway** (or any cloud host):

```bash
# Deploy with Docker
docker-compose up -d

# Or use the render.yaml for Railway deployment
```

Environment variables:
- `DISCORD_WEBHOOK_URL` — Discord channel webhook for signal alerts

The live deployment is at: `https://ict-production-b1a8.up.railway.app`

---

## 📈 Backtesting Framework

### `backtest_okx.py`
- Fetches 30 days of 5m data per month via OKX history API
- Pre-computes all 7 ICT modules once (vectorized Polars)
- Walks candle-by-candle to match live system logic
- Tracks signals generated, kept, bias changes, and trade execution
- Outputs per-month results and 12-month aggregate summary
- Supports `--months N`, `--offset N`, and `--parallel` flags

### `debug_backtest.py`
- Re-runs the full ICT pipeline on every candle (slower but matches live exactly)
- Captures every trade with full metadata: entry/exit time, SL distance, ATR, held candles, consecutive loss streaks
- Outputs detailed analysis: trade density, re-entry patterns, top losses
- Saves raw trade log as JSON for further analysis

---

## 📁 Project Structure

```
├── ict_engine/              # ICT mathematical core (7 modules)
│   ├── market_structure.py   # Swing highs/lows, BOS, MSS
│   ├── liquidity.py          # Equal highs/lows, sweeps
│   ├── fvg.py                # Fair Value Gaps
│   ├── order_blocks.py       # Order block detection
│   ├── premium_discount.py   # Equilibrium, OTE zones
│   ├── sessions.py           # Trading sessions, kill zones
│   ├── breaker_block.py      # Breaker blocks
│   └── utils.py              # Shared utilities
├── signal_engine/
│   └── engine.py             # Dual-scoring confluence engine
├── api/
│   ├── main.py               # FastAPI server + background workers
│   └── static/               # Dashboard build output
├── dashboard/                # React frontend
│   └── src/
│       ├── pages/            # Overview, Signals, Charts, etc.
│       ├── components/       # Layout, ICTChart, EMABiasChart
│       ├── services/         # api.ts, settingsService.ts
│       └── hooks/            # usePriceStream
├── discord/
│   └── bot.py                # Discord webhook notifier
├── risk/
│   └── manager.py            # Risk management rules
├── tests/
│   └── test_ict_engine.py    # Unit tests
├── backtest_okx.py           # 12-month rolling backtest
├── debug_backtest.py         # Per-trade forensic debug
├── demo_account.py           # Forward-testing engine
└── main.py                   # Deprecated (use API instead)
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
- **Previous Day/Week levels**: High, low, open, close

### Fair Value Gaps
- **Bullish FVG**: Candle1 high < Candle3 low (gap upward)
- **Bearish FVG**: Candle1 low > Candle3 high (gap downward)
- Status tracking: OPEN → TOUCHED → PARTIALLY FILLED → FILLED

### Order Blocks
- **Bullish OB**: Last bearish candle before >2× ATR bullish impulse
- **Bearish OB**: Last bullish candle before >2× ATR bearish impulse
- Status tracking: UNTOUCHED → TOUCHED → MITIGATED → INVALIDATED

### Premium / Discount
- **Equilibrium**: (high + low) / 2 over recent range
- **Premium**: Price above equilibrium (overvalued)
- **Discount**: Price below equilibrium (undervalued)
- **OTE Zone**: 62%–79% Fibonacci retracement

### Sessions & Kill Zones (Crypto)
- **Asian Session**: 00:00–08:00 UTC (crypto 24h markets)
- **London Session**: 08:00–16:00 UTC
- **New York Session**: 13:00–21:00 UTC
- **London Kill Zone**: 08:00–10:00 UTC
- **New York Kill Zone**: 13:00–15:00 UTC

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. No live trade execution is enabled by default. Trading financial markets involves significant risk of loss. Past backtest performance does not guarantee future results.
