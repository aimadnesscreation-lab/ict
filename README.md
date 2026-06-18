# ICT Trading Intelligence Platform

A production-grade algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes **real-time WebSocket data** through a 7-module ICT pipeline, scores confluences with a dual-scoring signal engine, manages a persistent forward-testing account, mirrors trades onto Binance Spot (LONG only), and surfaces everything through a React dashboard with real-time diagnostics and Discord webhook alerts.

---

## 🚀 Production-Ready Features

- **Real-Time Data Ingestion:** Powered by **CCXT Pro WebSockets**. Zero-latency ticker and candle updates ensure entries are triggered the millisecond a candle closes.
- **Persistent State Management:** Integrated **SQLite + SQLAlchemy** database. Every trade, signal, and balance change is persisted locally in `trading.db`.
- **Auto-Recovery:** The system automatically restores its state (balance, open positions, history) from the database on startup, surviving server restarts.
- **WebSocket HTF Bias:** Real-time 1H trend detection via EMA crossovers. Shifts in higher-timeframe bias are detected instantly.
- **Docker Support:** Ready for cloud deployment with `Dockerfile` and `docker-compose.yml`.
- **System Diagnostics:** Dedicated `/api/diagnostics` endpoint for monitoring WebSocket health, DB connectivity, and risk levels.

---

## 📊 Backtest Results

### Spot-Only (LONG Only — Matches Binance Spot) — 12 Months

| Metric | BTCUSDT | ETHUSDT | **Combined** |
|--------|---------|---------|-------------|
| **Total Trades** | 470 | 846 | **1,316** |
| **Win Rate** | 41.9% | 38.4% | **39.7%** |
| **Total P&L** | +$6,413.58 | +$6,919.30 | **+$13,332.88** |
| **Total Return** | — | — | **+266.7%** |
| **Avg Monthly P&L** | $534.47 | $576.61 | **$1,111.07** |
| **Avg R:R** | 1.42 | 1.38 | **1.40** |
| **Avg Max DD** | 8.0% | 7.6% | **~7.8%** |

*Run: `python backtest_okx.py --months 12 --spot --capital 5000`*

### Futures-Enabled (LONG + SHORT — Binance Futures) — 12 Months

| Metric | BTCUSDT | ETHUSDT | **Combined** |
|--------|---------|---------|-------------|
| **Total Trades** | 1,012 | 1,648 | **2,660** |
| **Win Rate** | 41.1% | 38.2% | **38.2%** |
| **Total P&L** | +$8,267.58 | +$14,023.60 | **+$22,291.12** |
| **Total Return** | — | — | **+445.8%** |
| **Avg Monthly P&L** | $688.97 | $1,168.63 | **$1,857.59** |
| **Avg R:R** | 1.40 | 1.38 | **1.39** |
| **Avg Max DD** | 13.6% | 10.9% | **~12.3%** |

*Run: `python backtest_okx.py --months 12 --capital 5000`*

### Spot vs Futures — Trade Quality Comparison

| Metric | **Spot (LONG Only)** | **Futures (LONG+SHORT)** | Delta |
|--------|:-------------------:|:------------------------:|:-----:|
| **Total Trades** | 1,316 | 2,660 | **+102%** |
| **Combined P&L** | **+$13,332.88** | **+$22,291.12** | **+67%** |
| **Total Return** | **+266.7%** | **+445.8%** | **+179pp** |
| **Win Rate** | 39.7% | 38.2% | -1.5pp |
| **Avg R:R** | 1.40 | 1.39 | -0.01 |
| **Avg Max DD** | 7.8% | 12.3% | **+4.5pp** |
| **Avg Held (Wins)** | 10 min | 10 min | Same |
| **Avg Held (Losses)** | 9 min | 9 min | Same |
| **Avg ATR (BTC)** | $70.91 | $170.93 (SHORT-heavy) | +141% |
| **Max Consec Losses** | 7–8 | 7–8 | Same |
| **Trades/Day (BTC)** | 1.3 | 2.8 | +115% |
| **Trades/Day (ETH)** | 2.3 | 4.5 | +96% |

#### Per-Month Breakdown

| Month | Spot P&L | Futures P&L | Spot Trades | Futures Trades |
|-------|:-------:|:----------:|:----------:|:-------------:|
| Jul 2025 | +$1,123.84 | +$1,123.84 | 267 | 267 |
| Aug 2025 | +$665.22 | +$1,645.91 | 145 | 244 |
| Sep 2025 | -$26.75 | -$563.77 | 54 | 117 |
| Oct 2025 | +$365.68 | +$535.04 | 82 | 165 |
| Nov 2025 | +$1,788.65 | +$1,836.25 | 127 | 230 |
| Dec 2025 | +$1,842.44 | +$2,578.91 | 208 | 394 |
| Jan 2026 | +$1,643.84 | +$1,643.84 | 71 | 71 |
| Feb 2026 | +$805.57 | +$64.44 | 68 | 424 |
| Mar 2026 | +$4,288.74 | +$4,343.78 | 182 | 275 |
| Apr 2026 | +$381.42 | +$725.79 | 64 | 123 |
| May 2026 | +$454.23 | +$642.88 | 48 | 68 |
| Jun 2026 | $0.00 | +$7,714.21 | 0 | 282 |

#### Key Findings

1. **SHORT trades add 102% more trade volume** but only **67% more profit** — SHORTs are less efficient per-trade than LONGs
2. **Win rate drops 1.5pp** when including SHORTs (39.7% → 38.2%) — SHORT signals are slightly less reliable
3. **Max DD increases 4.5pp** (7.8% → 12.3%) — SHORT trades add meaningful tail risk
4. **R:R is nearly identical** (1.40 vs 1.39) — the strategy's edge is consistent across both directions
5. **All trades scalp-style**: held 9–12 min average, regardless of direction or symbol
6. **Consecutive loss streaks are identical** (7–8) — the daily 3% circuit breaker is the real risk control
7. **June 2026** is the most dramatic gap: BEARISH bias all month. Spot filtered all SHORTs → $0. Futures took 282 SHORT trades → +$7,714.21
8. **September 2025** is the worst month in both modes: futures lost -$563.77 vs spot -$26.75. The daily 3% circuit breaker saved spot from further damage

---

## 🏗️ Architecture Overview

```
Binance WebSockets (Real-time via CCXT Pro)
                    │
                    ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  TradingOrchestrator         │────▶│  ICT Pipeline             │
  │  (unified entry point)       │     │  (7 vectorized modules)  │
  │  - hot-path execution        │     │  - Market Structure      │
  │  - real-time triggers        │     │  - Liquidity             │
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
  │  DemoAccount + SQLite DB     │────▶│  LiveExecutor            │
  │  - persistent state recovery │     │  (Binance Spot via CCXT) │
  │  - trade entry/exit logging  │     │  - Market buy + OCO SL/TP│
  │  - equity snapshotting       │     │  - 30s sync reconciliation│
  └──────────────┬──────────────┘     └────────────┬─────────────┘
                 │                                   │
                 ▼                                   ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  FastAPI (REST + WebSocket)  │     │  Discord Bot             │
  │  - /ws/prices (live ticks)  │     │  (webhook alerts)        │
  │  - /ws/data (full snapshot) │     └──────────────────────────┘
  │  - /api/diagnostics         │
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
3. **HTF alignment filter** — signals must align with **Real-time WebSocket 1h EMA bias**
4. **Spot-only filter** — removes ALL SHORT signals (Binance Spot only supports LONG)
5. Feeds qualifying signals to DemoAccount (requires: score ≥ min_score AND kill zone AND HTF aligned)
6. Mirrors newly opened positions to Binance via LiveExecutor (market buy + OCO SL/TP)
7. Sends Discord notifications per new position

### Layer 3: Demo Account + Database (`demo_account.py`, `database/`)

**Persistent** forward-testing engine:
- **$5,000** paper capital (configurable via `DEMO_INITIAL_BALANCE`)
- **SQLite Persistence:** Uses `SQLAlchemy` + `aiosqlite` for asynchronous DB operations.
- **State Recovery:** Restores balance and positions on startup from `trading.db`.
- **1% risk** per trade (of current balance)
- **0.5× ATR** stop loss, **1:2** risk-reward
- Max **3 open positions** across all symbols
- **3% daily loss limit** (circuit breaker)

### Layer 4: Live Execution (`execution/`)

- **LiveExecutor** (`executor.py`): Connects to Binance Spot via CCXT (demo/testnet/live)
  - Places market buy orders with **OCO (One-Cancels-Other)** for SL + TP
  - **Spot-only**: SHORT signals filtered upstream by orchestrator
- **SyncWorker** (`sync_worker.py`): Reconciles DemoAccount ↔ exchange every 30s
  - Detects SL/TP hits on exchange → closes in DemoAccount

### Layer 5: API + Dashboard

**Backend** (`api/main.py`):
- **FastAPI** server with 3 real-time background workers:
  - Crypto data worker (**WebSockets**) — real-time ticker + candles
  - HTF bias worker (**WebSockets**) — real-time 1h bias tracking
  - Exchange sync (30s)
- **Diagnostics:** `/api/diagnostics` for monitoring system latency and health.
- **Real-time Stream:** `/ws/data` pushes updates for signals, trades, and performance.

---

## 🚀 Quick Start

### Docker (Recommended)
```bash
docker-compose up --build
```
Deploy the platform instantly with zero configuration.

### Manual Setup
```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install sqlalchemy aiosqlite

# 2. Set environment
cp .env.example .env # Add your Binance API keys

# 3. Start the API
uvicorn api.main:app --port 8000
```

### Dashboard
```bash
cd dashboard
npm install
npm run dev          # dev server at http://localhost:5173
```

---

## 🧪 Testing

```bash
# ICT engine unit tests
pytest tests/test_ict_engine.py -v

# Binance connection test
python test_live_connection.py

# End-to-end integration test
python test_integration.py
```

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. Past backtest performance does not guarantee future results. The system uses a demo/sandbox exchange environment by default — no real funds are traded unless `EXCHANGE_MODE=live` is explicitly set.
