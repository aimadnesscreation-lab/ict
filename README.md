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
| **Total Trades** | 733 | 998 | **1,731** |
| **Win Rate** | 42.6% | 40.2% | **41.2%** |
| **Total P&L** | +$11,220.56 | +$11,115.87 | **+$22,336.43** |
| **Total Return** | — | — | **+446.7%** |
| **Avg Monthly P&L** | $935.05 | $926.32 | **$1,861.37** |
| **Avg R:R** | ~1.40 | ~1.40 | **~1.40** |
| **Avg Max DD** | ~7.5% | ~8.5% | **~8.0%** |

*Run: `python backtest_okx.py --months 12 --spot-only --capital 5000`*

### Futures-Enabled (LONG + SHORT — Binance Futures) — 12 Months

*Results pending — the HTF alignment fix affects futures results too. Re-run with `python backtest_okx.py --months 12 --capital 5000` to update.*

#### Per-Month Breakdown (Spot-Only)

| Month | BTC Trades | BTC WR | BTC P&L | ETH Trades | ETH WR | ETH P&L | Combined P&L |
|-------|:---------:|:------:|:-------:|:---------:|:------:|:-------:|:-----------:|
| Jul 2025 | 66 | 39.4% | +$597.35 | 85 | 35.3% | +$210.88 | **+$808.23** |
| Aug 2025 | 43 | 39.5% | +$391.23 | 217 | 38.7% | +$1,932.11 | **+$2,323.34** |
| Sep 2025 | 51 | 47.1% | +$1,130.90 | 130 | 43.9% | +$2,422.48 | **+$3,553.38** |
| Oct 2025 | 174 | 41.4% | +$2,464.01 | 121 | 38.8% | +$1,028.13 | **+$3,492.14** |
| Nov 2025 | 72 | 40.3% | +$763.53 | 59 | 45.8% | +$1,187.30 | **+$1,950.83** |
| Dec 2025 | 82 | 50.0% | +$2,457.96 | 74 | 46.0% | +$1,558.18 | **+$4,016.14** |
| Jan 2026 | 44 | 52.3% | +$1,384.30 | 34 | 29.4% | -$211.31 | **+$1,172.99** |
| Feb 2026 | 23 | 39.1% | +$191.16 | 33 | 51.5% | +$961.23 | **+$1,152.39** |
| Mar 2026 | 83 | 41.0% | +$991.01 | 133 | 39.1% | +$1,203.40 | **+$2,194.41** |
| Apr 2026 | 49 | 36.7% | +$229.55 | 62 | 35.5% | +$171.08 | **+$400.63** |
| May 2026 | 27 | 55.6% | +$964.79 | 25 | 48.0% | +$564.54 | **+$1,529.33** |
| Jun 2026 | 19 | 21.1% | -$345.23 | 25 | 36.0% | +$87.85 | **-$257.38** |

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

# 2. Set environment
cp .env.example .env  # Add your Binance API keys

# 3. Start everything (API + Dashboard) with one command
chmod +x start.sh
./start.sh
```

The script will create a virtual environment, install all deps, verify your connection, and start both the API server (port 8000) and Vite dev server (port 5173). Press `Ctrl+C` to stop both.

### Dashboard (standalone)
```bash
cd dashboard
npm install
npm run dev          # dev server at http://localhost:5173
```

### Running in the Background

Keep the platform running 24/7 without an open terminal:

#### Option 1: `nohup` (quickest)
```bash
cd /path/to/ict
nohup ./start.sh > trading.log 2>&1 &
```
Logs stream to `trading.log`. To stop:
```bash
pkill -f uvicorn
pkill -f vite
```

#### Option 2: `tmux` (best for monitoring)
```bash
# Start a detached session
tmux new-session -d -s trading './start.sh'

# Reattach to see logs
tmux attach -t trading
# Detach with Ctrl+B then D

# Stop the session
tmux kill-session -t trading
```

#### Option 3: `systemd` service (auto-start on boot)
```bash
# Replace YOUR_USER with your Linux username and edit the WorkingDirectory/ExecStart paths
sudo tee /etc/systemd/system/trading.service << 'EOF'
[Unit]
Description=ICT Trading Platform
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/ict
ExecStart=/home/YOUR_USER/ict/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now trading.service
```
This runs only the API (no dashboard dev server). Access the pre-built dashboard at `http://localhost:8000/dashboard/`.

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
