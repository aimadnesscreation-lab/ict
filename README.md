# ICT Trading Intelligence Platform

A production-grade algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes **real-time WebSocket data** through a 7-module ICT pipeline, scores confluences with a dual-scoring signal engine, manages a persistent forward-testing account (DemoAccount), mirrors trades onto **Binance USDⓈ-M Futures** (LONG + SHORT), and surfaces everything through a React dashboard with real-time diagnostics and Discord webhook alerts.

---

## 🚀 Production-Ready Features

- **Real-Time Data Ingestion:** Powered by **CCXT Pro WebSockets**. Zero-latency ticker and candle updates ensure entries are triggered the millisecond a candle closes.
- **Binance USDⓈ-M Futures:** Supports both **LONG and SHORT** positions with 3× leverage, stop-market SL/TP orders, and one-way position mode.
- **Dual-Scoring Signal Engine:** Tracks bullish and bearish confluences independently (not a single ambiguous score) — net difference determines signal direction.
- **Persistent State Management:** Integrated **SQLite + SQLAlchemy** (async) database. Every trade, signal, and balance change is persisted locally in `trading.db`.
- **Auto-Recovery:** The system automatically restores its state (balance, open positions, history) from the database on startup, surviving server restarts.
- **WebSocket HTF Bias:** Real-time 1H trend detection via EMA12/EMA26 crossovers with 0.5% threshold. Falls back to swing structure analysis for neutral EMA readings.
- **Position Reconciliation:** SyncWorker reconciles DemoAccount ↔ exchange positions every 30 seconds — detects SL/TP hits, partial fills, and manual closes on the exchange.
- **Docker Support:** Ready for cloud deployment with `Dockerfile` and `docker-compose.yml`.
- **Render Blueprint:** Deploy API + Dashboard on Render with one click via `render.yaml`.
- **ETH-only Optimized:** Focused on ETHUSDT with `kill_zones_enabled=False` (trade all sessions) and `symbol_min_scores={"ETHUSDT": 60}`.
- **System Diagnostics:** Dedicated `/api/diagnostics` endpoint for monitoring WebSocket health, DB connectivity, and risk levels.

---

## 📊 Backtest Results

### Live Config — ETHUSDT — 12 Months (Jul 2025 – Jun 2026)

**Configuration:** Binance Futures, LONG + SHORT, 2.0× ATR SL, 1:2 RR, 1% risk, 0.04% round-trip fee, no kill zone requirement, min score=60.

| Metric | Value |
|--------|:-----:|
| **Total Trades** | **1,517** (588 W / 929 L) |
| **Win Rate** | **38.8%** |
| **Total P&L** | **+$5,077.67** |
| **Total Return** | **+101.6%** |
| **Avg Monthly P&L** | **+$423.14** |
| **Avg R:R** | **1.39** |
| **Avg Max Drawdown** | **14.3%** |
| **Profit Factor** | **1.08** |

*Run: `python backtest_binance.py --symbol ETHUSDT --months 12 --no-kill-zone --fee-pct 0.04 --sl-multiplier 2.0 --capital 5000`*

#### Per-Month Breakdown

| Month | Trades | WR | P&L | PF | DD |
|-------|:-----:|:--:|:---:|:--:|:--:|
| Jul 2025 | 200 | 36.0% | -$172 | 0.97 | 19.6% |
| Aug 2025 | 109 | 41.3% | **+$883** | 1.22 | 11.4% |
| Sep 2025 | 102 | 36.3% | -$203 | 0.94 | 15.2% |
| Oct 2025 | 147 | 39.5% | **+$689** | 1.13 | 11.4% |
| Nov 2025 | 114 | 33.3% | -$505 | 0.86 | 19.6% |
| Dec 2025 | 124 | 43.5% | **+$1,395** | 1.28 | 10.9% |
| Jan 2026 | 97 | 40.2% | **+$326** | 1.10 | 13.1% |
| Feb 2026 | 172 | 37.2% | **+$320** | 1.05 | 12.9% |
| Mar 2026 | 152 | 40.1% | **+$938** | 1.16 | 11.3% |
| Apr 2026 | 112 | 33.0% | -$623 | 0.83 | 17.8% |
| May 2026 | 80 | 41.2% | **+$373** | 1.14 | 14.9% |
| Jun 2026 | 108 | 46.3% | **+$1,658** | 1.47 | 13.2% |

#### Fee Impact Comparison (12 months)

| Config | Trades | Annual P&L | Return | Max DD |
|---|---:|---:|---:|---:|
| **Live config** (2.0× SL + 0.04% fee) | 1,517 | **+$5,078** | **+102%** | 14.3% |
| Tight SL + fees (0.5× SL + 0.04% fee) | 3,316 | -$22,106 | -442% | 44.4% |
| Tight SL, no fees (0.5× SL, 0% fee) | 998 | +$11,116 | +222% | 8.5% |

> **Key insight:** Fees have a massive impact on this high-frequency strategy. The wider 2.0× ATR stop-loss is essential — it cuts trade frequency by more than half (1,517 vs 3,316) and makes the strategy profitable with realistic Binance Futures fees. The 3% daily loss limit serves as a critical circuit breaker, preventing runaway losses in unfavorable market conditions.

---

## 🏗️ Architecture Overview

```
Binance Futures WebSockets (Real-time via CCXT Pro)
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
  │  - Futures: LONG + SHORT    │
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐     ┌──────────────────────────┐
  │  DemoAccount + SQLite DB          │────▶│  LiveExecutor            │
  │  - persistent state recovery      │     │  (Binance Futures)      │
  │  - trade entry/exit/logging       │     │  - Market entry + SL/TP │
  │  - 30s exchange sync reconciliation│     │  - STOP_MARKET / TAKE_PROFIT_MARKET │
  └──────────────┬───────────────────┘     │  - LONG + SHORT support │
                 │                           └────────────┬─────────────┘
                 ▼                                        │
  ┌─────────────────────────────┐              ┌──────────┘
  │  FastAPI (REST + WebSocket)  │              │
  │  - /ws/prices (live ticks)  │     ┌────────▼──────────┐
  │  - /ws/data (full snapshot) │     │  Discord Bot       │
  │  - /api/diagnostics         │     │  (webhook alerts)  │
  └──────────────┬──────────────┘     └───────────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │  React Dashboard            │
  │  - real-time via useDataStream (WS + REST fallback)  │
  │  - 6 pages: Overview, Signals, Charts, TradeLog,    │
  │    RiskCenter, Settings                              │
  │  - lightweight-charts candlestick + EMA bias charts  │
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

1. Runs ICT pipeline on both **5m and 15m** data
2. Generates signals via **dual-scoring** engine (bullish vs. bearish independently)
3. **HTF alignment filter** — signals must align with **Real-time WebSocket 1h EMA bias** (neutral bias lets all signals pass)
4. **Futures mode** — both LONG and SHORT signals are supported
5. Feeds qualifying signals to DemoAccount (requires: score ≥ min_score AND in kill zone AND HTF aligned)
6. Mirrors newly opened positions to **Binance Futures** via LiveExecutor (LONG → buy, SHORT → sell)
7. Sends Discord notifications per new position

### Layer 3: Demo Account + Database (`demo_account.py`, `database/`)

**Persistent** forward-testing engine:
- **$5,000** paper capital (configurable via `DEMO_INITIAL_BALANCE`)
- **SQLite Persistence:** Uses `SQLAlchemy` + `aiosqlite` for asynchronous DB operations.
- **State Recovery:** Restores balance and positions on startup from `trading.db`.

#### Trade Parameters

| Parameter | Live Value | Backtest Default |
|---|---:|---:|
| Starting capital | $5,000 | $5,000 (`--capital`) |
| Risk per trade | 1.0% of balance | 1.0% |
| Stop-loss distance | **2.0× ATR** | **2.0× ATR** (`--sl-multiplier`) |
| Take-profit distance | 1:2 RR (2× SL distance) | 1:2 RR |
| Max open positions | 3 | 3 |
| Max daily loss | 3.0% of initial balance | 3.0% |
| Re-entry cooldown after SL | 0 min (none) | 0 min |
| Min score to trade (ETHUSDT) | **60** | 60 (`--symbol-min-score`) |
| Kill zone required | **No** (trade all sessions) | `--no-kill-zone` flag |
| Direction | LONG + SHORT (Futures) | LONG + SHORT |
| Leverage | 3× (live only, not used in DemoAccount) | N/A |
| Fees | Maker 0.02% / Taker 0.04% | `--fee-pct 0.04` |

### Layer 4: Live Execution (`execution/`)

- **LiveExecutor** (`executor.py`): Connects to **Binance USDⓈ-M Futures** via CCXT (demo/testnet/live)
  - Uses **market entry orders** + **STOP_MARKET** (stop-loss) + **TAKE_PROFIT_MARKET** (take-profit) as reduce-only orders
  - Supports **both LONG and SHORT** positions
  - **One-way position mode** (no hedge mode) — side='buy' opens LONG, side='sell' opens SHORT
  - Default **3× leverage**
  - Demo mode uses `enable_demo_trading(True)` for Binance Futures Testnet
  - `has_position()` and `get_open_positions()` via `fetch_positions()`
  - Handles precision rounding, min/max amount validation, and `set_leverage()`
- **SyncWorker** (`sync_worker.py`): Reconciles DemoAccount ↔ exchange every 30s
  - Detects SL/TP hits on exchange → closes in DemoAccount
  - Handles **partial fills** (exchange qty < DemoAccount qty → records partial trade)
  - Logs **side mismatches** and quantity discrepancies
  - Propagates `_last_sl` cooldown tracking

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

### Unit Tests (23 tests)

```bash
# Run all unit tests
pytest tests/ -v

# Individual test suites
pytest tests/test_ict_engine.py -v           # 3 ICT module tests (swings, FVG, OB)
pytest tests/test_orchestrator_mirror.py -v  # 7 orchestrator pipeline tests (mirror, KZ, HTF, risk)
pytest tests/test_sync_worker.py -v          # 13 sync reconciliation tests (SL/TP, partial fills, multi-symbol)
```

### End-to-End Integration Test

```bash
python test_integration.py
```
Starts the API server, monitors data flow for 3 minutes, and verifies:
- Server boots and responds to health checks
- Binance data backfill succeeds (candle buffers populated)
- HTF bias is computed
- ICT pipeline generates signals
- DemoAccount processes signals
- Binance demo trading connection is active

### Binance Order Placement Test

```bash
python test_binance_orders.py
```
Tests the full order lifecycle on Binance Futures Testnet:
- Exchange connection and market loading
- Balance check and market precision
- Leverage setting (3×)
- LONG market entry with STOP_MARKET SL + TAKE_PROFIT_MARKET TP
- Position verification on exchange
- Position close and cleanup

### All Tests (Quick Verification)

```bash
python -m pytest tests/ -v && python test_binance_orders.py
```

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. Past backtest performance does not guarantee future results. The system uses a demo/sandbox exchange environment by default — no real funds are traded unless `EXCHANGE_MODE=live` is explicitly set.
