# ICT Trading Intelligence Platform

A production-ready algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes real-time Binance OHLCV data through a 7-module ICT pipeline, scores confluences with a dual-scoring signal engine, manages a forward-testing demo account, mirrors trades onto Binance Spot (LONG only), and surfaces everything through a React dashboard with real-time WebSocket updates and Discord webhook alerts.

---

## 📊 Backtest Results

### Spot-Only (LONG Only — Matches Binance Spot) — 12 Months

| Metric | BTCUSDT | ETHUSDT | **Combined** |
|--------|---------|---------|-------------|
| **Total Trades** | 840 | 1,413 | **2,253** |
| **Win Rate** | 38.7% | 38.6% | **38.6%** |
| **Total P&L** | +$7,012.73 | +$12,252.21 | **+$19,264.94** |
| **Total Return** | — | — | **+385.3%** |
| **Avg Monthly P&L** | $584.39 | $1,021.02 | **$1,605.41** |
| **Avg R:R** | 1.39 | 1.38 | **1.38** |
| **Avg Max DD** | 9.5% | 9.6% | **~9.5%** |

> Run `python backtest_okx.py --months 12 --spot` to get current numbers. Results vary by ~5-10% between runs due to live-fetched data and shifting 30-day month boundaries.

---

## 🏗️ Architecture Overview

```
Binance REST API (public, 15s poll)
                    │
                    ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  TradingOrchestrator         │────▶│  ICT Pipeline             │
  │  (unified entry point)       │     │  (7 vectorized modules)  │
  │  - runs per candle close     │     │  - Market Structure      │
  │  - coordinates all steps     │     │  - Liquidity             │
  └──────────────┬──────────────┘     │  - FVG / Order Blocks    │
                 │                     │  - Premium/Discount OTE  │
                 ▼                     │  - Sessions / Kill Zones │
  ┌─────────────────────────────┐     └────────────┬─────────────┘
  │  Signal Engine               │◀─────────────────┘
  │  (dual-scoring 0-100)       │
  │  - HTF alignment filter     │
  │  - Spot-only SHORT filter   │
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  DemoAccount ($5,000)        │────▶│  LiveExecutor            │
  │  - forward-testing engine    │     │  (Binance Spot via CCXT) │
  │  - SL/TP check each cycle    │     │  - Market buy + OCO SL/TP│
  │  - performance tracking      │     │  - 30s sync reconciliation│
  └──────────────┬──────────────┘     └────────────┬─────────────┘
                 │                                   │
                 ▼                                   ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  FastAPI (REST + WebSocket)  │     │  Discord Bot             │
  │  - /ws/prices (live ticks)  │     │  (webhook alerts)        │
  │  - /ws/data (full snapshot) │     └──────────────────────────┘
  │  - REST endpoints           │
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │  React Dashboard            │
  │  - real-time via useDataStream (WS + REST fallback)  │
  │  - 6 pages: Overview, Signals, Charts, TradeLog,    │
  │    RiskCenter, Settings                              │
  └─────────────────────────────┘
```

### Layer 1: ICT Engine (`ict_engine/`)

7 vectorized **Polars**-based modules that run on every 5m candle close:

| Module | File | Detection | Confluence Pts |
|---|---|---|---|
| **Market Structure** | `market_structure.py` | Swing highs/lows, BOS, MSS | 20 |
| **Liquidity** | `liquidity.py` | Equal highs/lows, sweeps, prev day H/L | 20 |
| **Fair Value Gap** | `fvg.py` | 3-candle imbalances with status tracking | 15 |
| **Order Blocks** | `order_blocks.py` | Last candle before >2× ATR impulse | 15 |
| **Premium/Discount** | `premium_discount.py` | Equilibrium zones + OTE (62-79% fib) | 10 + 10 |
| **Sessions** | `sessions.py` | Asian/London/NY sessions + Kill Zones | 10 |

### Layer 2: Trading Orchestrator (`trading_engine/orchestrator.py`)

Unified entry point that coordinates the entire pipeline:

1. Runs ICT pipeline on both 5m and 15m data
2. Generates signals via **dual-scoring** engine (bullish vs. bearish independently)
3. **HTF alignment filter** — signals must align with 1h EMA bias (12/26, 0.5% threshold)
4. **Spot-only filter** — removes ALL SHORT signals (Binance Spot only supports LONG)
5. Feeds qualifying signals to DemoAccount (requires: score ≥ min_score AND kill zone AND HTF aligned)
6. Mirrors newly opened positions to Binance via LiveExecutor (market buy + OCO SL/TP)
7. Sends Discord notifications per new position

**Dual-scoring signal types:**
- `net = bullish - bearish` determines direction
- `confidence = max(bullish, bearish)` determines strength
- **net ≥ 60** → STRONG_BUY, **net ≥ 30** → BUY, **net > -30** → NEUTRAL
- **net ≤ -30** → SELL, **net ≤ -60** → STRONG_SELL

### Layer 3: Demo Account (`demo_account.py`)

Stateful forward-testing engine:
- **$5,000** paper capital (configurable via `DEMO_INITIAL_BALANCE`)
- **1% risk** per trade (of current balance)
- **0.5× ATR** stop loss (per-symbol via `symbol_sl_multipliers`), **1:2** risk-reward
- **0 min** re-entry cooldown
- **min_score = 60** for entries (per-symbol via `symbol_min_scores`)
- Max **3 open positions** across all symbols
- **3% daily loss limit** (circuit breaker, auto-resets at UTC day change)
- Tracks P&L, win rate, profit factor, max drawdown, average R:R

### Layer 4: Live Execution (`execution/`)

- **LiveExecutor** (`executor.py`): Connects to Binance Spot via CCXT (demo/testnet/live)
  - Places market buy orders with OCO (One-Cancels-Other) for SL + TP
  - **Spot-only**: SHORT signals filtered upstream by orchestrator
  - Caps position sizes to available USDT balance (spot is 1:1, no leverage)
- **SyncWorker** (`sync_worker.py`): Reconciles DemoAccount ↔ exchange every 30s
  - Detects SL/TP hits on exchange → closes in DemoAccount
  - Handles partial fills, manual closes, quantity/side discrepancies

### Layer 5: API + Dashboard

**Backend** (`api/main.py`):
- **FastAPI** server with 3 background workers:
  - Crypto data fetcher (Binance REST, 15s poll) — ticker + candles → ICT pipeline
  - HTF bias updater (1h EMA, 15min cycle)
  - Exchange sync (30s, only if credentials available)
- WebSocket endpoints:
  - `/ws/prices` — live BTC/ETH tick stream (250ms updates)
  - `/ws/data` — full state snapshot (signals, trades, demo, risk, performance, health) on connect + push on data change + 30s heartbeat
- REST endpoints: `/signals`, `/trades`, `/performance`, `/demo/account`, `/risk/status`, `/candles/{symbol}`, `/backtest-data/{symbol}`, `/reset`, `/sync`, `/api/health`
- Dashboard build mounted at `/dashboard`

**Frontend** (`dashboard/`):
- React 19 + TypeScript + Vite + Tailwind CSS v4
- **6 pages**: Overview, Signals, Charts (Lightweight Charts), Trade Log, Risk Center (with position sizing calculator), Settings
- **Real-time data**: `useDataStream` hook connects to `/ws/data` for instant updates, falls back to REST polling every 15s with periodic WS retry every ~60s
- **Live prices**: `usePriceStream` WebSocket hook with mock fallback
- Unit tested: 13 tests via Vitest

**Discord Bot** (`discord/bot.py`):
- Sends formatted embedded messages via webhook (10s timeout)
- Triggers on signals that DemoAccount actually opened
- Shows confluence breakdown, price levels, trend bias, price movement from trigger

---

## ⚙️ Current Configuration

| Parameter | BTCUSDT | ETHUSDT |
|---|---|---|
| **ATR SL Multiplier** | 0.5× | 0.5× |
| **Min Score Threshold** | 60 | 60 |
| **Re-entry Cooldown** | 0 min | 0 min |
| **Risk Per Trade** | 1% | 1% |
| **Max Positions** | 3 (shared) | 3 (shared) |
| **Kill Zone Required** | Yes | Yes |
| **HTF Alignment** | Yes | Yes |
| **Data Source** | Binance (public REST, no API key) | Binance (public REST, no API key) |
| **Allowed Sides** | LONG only (spot) | LONG only (spot) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+ (for dashboard)
- Binance API keys (optional — for exchange execution only, signals work without them)

### One-Command Start
```bash
./start.sh
```
Runs: Python venv → pip install → npm install → connection test → API server → dashboard.

### Manual Backend
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

### Dashboard
```bash
cd dashboard
npm install
npm run dev          # dev server at http://localhost:5173
# OR
npm run build        # static build served at http://localhost:8000/dashboard
```

### Running Backtests
```bash
# 12-month spot-only backtest (LONG only — matches Binance Spot)
python backtest_okx.py --months 12 --spot

# Single month (offset 0 = newest)
python backtest_okx.py --offset 3 --spot

# Debug mode with per-trade forensic analysis
python backtest_okx.py --debug --offset 2 --spot

# Custom capital
python backtest_okx.py --months 12 --spot --capital 10000
```

---

## 🧪 Testing

```bash
# ICT engine unit tests
pytest tests/test_ict_engine.py -v

# Dashboard tests
cd dashboard && npm test

# Binance connection test
python test_live_connection.py

# End-to-end integration test
python test_integration.py
```

---

## 🌐 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Root — status + version |
| `GET /api/health` | System health — prices, bias, uptime, cycle counts |
| `GET /signals?limit=N` | Recent ICT-generated signals |
| `GET /signals/{id}` | Single signal detail |
| `GET /candles/{symbol}?timeframe=X&limit=N` | OHLCV candles from Binance |
| `GET /backtest-data/{symbol}?days=N&bar=X` | Paginated historical OHLCV |
| `GET /trades?limit=N&result=X&symbol=Y` | Closed DemoAccount trades |
| `GET /performance` | Performance metrics |
| `GET /demo/account` | Demo account state |
| `GET /risk/status` | Risk management state |
| `POST /reset` | Clear all state for fresh start |
| `POST /sync` | Trigger exchange reconciliation |
| `WS /ws/prices` | Live BTC/ETH price stream (250ms) |
| `WS /ws/data` | Full state snapshot stream (real-time + 30s heartbeat) |

### WebSocket `/ws/data` Message Format
```json
{
  "type": "snapshot",
  "signals": [...],
  "trades": [...],
  "demo_account": {...},
  "health": {...},
  "risk_status": {...},
  "performance": {...}
}
```

---

## 🔐 Risk Management

| Control | Value | Description |
|---------|-------|-------------|
| **Risk Per Trade** | 1% | Fixed % of current balance |
| **Daily Loss Limit** | 3% | Circuit breaker — stops trading after this loss |
| **Max Open Positions** | 3 | Shared across all symbols |
| **Stop Loss** | 0.5× ATR | Per-symbol ATR multiplier |
| **Take Profit** | 2× SL distance | Fixed 1:2 risk-reward |

---

## 📁 Project Structure

```
├── trading_engine/
│   └── orchestrator.py         # Unified signal pipeline coordinator
├── ict_engine/                 # ICT mathematical core (6 modules)
│   ├── market_structure.py     # Swing highs/lows, BOS, MSS
│   ├── liquidity.py            # Equal highs/lows, sweeps, prev day levels
│   ├── fvg.py                  # Fair Value Gaps
│   ├── order_blocks.py         # Order block detection
│   ├── premium_discount.py     # Equilibrium, OTE (62-79% fib) zones
│   ├── sessions.py             # Trading sessions, kill zones
│   └── utils.py                # ATR, SMMA calculations
├── signal_engine/
│   └── engine.py               # Dual-scoring confluence engine
├── execution/
│   ├── executor.py             # Binance Spot demo trading (CCXT, OCO)
│   └── sync_worker.py          # DemoAccount ↔ exchange reconciliation
├── api/
│   ├── main.py                 # FastAPI + 3 background workers + WebSockets
│   └── static/                 # Dashboard build output
├── dashboard/
│   └── src/
│       ├── pages/              # Overview, Signals, Charts, TradeLog, RiskCenter, Settings
│       ├── components/         # Layout, ICTChart, EMABiasChart, SignalBadge
│       ├── hooks/              # useDataStream.ts (WS + REST fallback), usePriceStream.ts
│       ├── services/           # api.ts, settingsService.ts
│       ├── utils/              # format.ts, signalCalculator.ts
│       └── types.ts            # Shared TypeScript interfaces
├── discord/
│   └── bot.py                  # Discord webhook notifier
├── risk/
│   └── manager.py              # Risk management rules
├── tests/
│   └── test_ict_engine.py      # ICT engine unit tests
├── backtest_okx.py             # 12-month rolling backtest
├── demo_account.py             # Forward-testing engine
├── test_live_connection.py     # Binance demo connection test
├── test_integration.py         # E2E integration test
├── start.sh                    # One-command startup
└── render.yaml                 # Railway deployment blueprint
```

---

## 📚 ICT Concepts Implemented

### Market Structure
- **Swing High/Low**: N-candle lookback (N=3) peak/trough detection
- **Break of Structure (BOS)**: Close above/below last swing
- **Market Structure Shift (MSS)**: Previous swing taken + close beyond opposing swing
- **Trend Bias**: HH+HL = bullish, LL+LH = bearish

### Liquidity
- **Equal Highs/Lows**: Within ATR × 0.10 threshold
- **Liquidity Sweeps**: Break below/above then close back above/below
- **Previous Day levels**: High, low from daily aggregation

### Fair Value Gaps
- **Bullish FVG**: Candle1 high < Candle3 low (gap upward)
- **Bearish FVG**: Candle1 low > Candle3 high (gap downward)
- Status tracking: OPEN → TOUCHED → FILLED

### Order Blocks
- **Bullish OB**: Last bearish candle before >2× ATR bullish impulse
- **Bearish OB**: Last bullish candle before >2× ATR bearish impulse

### Premium / Discount / OTE
- **Equilibrium**: (high + low) / 2 over swing range
- **Premium**: Price above equilibrium (overvalued)
- **Discount**: Price below equilibrium (undervalued)
- **OTE Zone**: 62%–79% Fibonacci retracement

### Sessions & Kill Zones (UTC)
| Zone | Time (UTC) |
|------|-----------|
| Asian Session | 00:00–09:00 |
| London Session | 08:00–17:00 |
| New York Session | 13:00–22:00 |
| London Kill Zone | 07:00–09:00 |
| NY Kill Zone | 13:00–15:00 |
| London Close | 17:00–18:00 |

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. No live trade execution is enabled by default. Trading financial markets involves significant risk of loss. Past backtest performance does not guarantee future results. The system uses a demo/sandbox exchange environment by default — no real funds are traded unless `EXCHANGE_MODE=live` is explicitly set.
