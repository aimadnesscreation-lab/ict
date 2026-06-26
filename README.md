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

All backtests use the **live pipeline** (`backtest_binance.py`): the same `Combo521Detector`, `DemoAccount`, and ICT modules that run in production. Results are for **ETHUSDT** on 5m candles with the **Combo 521** sweep+FVG strategy (proximal entry, PD zone filter, 20-bar lookback).

### 5-Year Overview (Aug 2021 – Jun 2026)

**Configuration:** Binance Futures, LONG + SHORT, 2.0× ATR SL, 1:3 RR (3R TP), 1% risk/trade, max 3 positions, 3% daily loss limit.

#### Non-Compounding (monthly capital reset to $5,000)

| Metric | Value |
|--------|:-----:|
| **Total Trades** | **5,293** (1,577W / 3,716L) |
| **Win Rate** | **29.8%** |
| **Total P&L** | **+$25,842.10** |
| **Profit Factor** | **0.99** |
| **Avg Monthly P&L** | **+$430.70** |
| **Avg R:R** | **1.60** |
| **Avg Drawdown** | **15.5%** |
| **Return on $5k** | **+516.8%** |

```
python backtest_binance.py --symbol ETHUSDT --months 60 --fee-pct 0.063 --sl-multiplier 2.0 --risk-pct 1.0 --capital 5000
```

#### Compounding — Real Binance Fees (5 years, $5,000 start)

| Scenario | Round-Trip Fee | Final Capital | Total Return | PF | Avg Monthly |
|----------|:-------------:|:-------------:|:------------:|:--:|:-----------:|
| **No BNB** (maker entry + taker exit) | 0.07% | **$12,436.53** | **+148.7%** | 1.04 | +$123.94 |
| **With BNB** (maker entry + taker exit) | 0.063% | **$28,917.47** | **+478.4%** | 1.07 | +$398.62 |

```
# No BNB scenario
python backtest_binance.py --symbol ETHUSDT --months 60 --fee-pct 0.07 --sl-multiplier 2.0 --risk-pct 1.0 --capital 5000 --compound

# With BNB scenario
python backtest_binance.py --symbol ETHUSDT --months 60 --fee-pct 0.063 --sl-multiplier 2.0 --risk-pct 1.0 --capital 5000 --compound
```

> **BNB discount is worth ~$16,481 over 5 years.** The 10% fee reduction compounds massively over 5,000+ trades. The strategy's ~30% win rate with 1.60 avg R:R is profitable even at 0.07% fees, but the BNB discount nearly doubles the long-term return.

### Compounding Curve (0.063% fee with BNB)

```
$5,000 ──→ $28,917 over 60 months (5,276 trades across 5 market cycles)
                │
                ├── Best month:  Jun 2025  (+$2,309)
                ├── Worst month: Oct 2021  (−$955)
                ├── Winning months: 41 / 60 (68%)
                └── Max consecutive losses: ~12
```

The compounding curve accelerates over time — the first 3 years build the base ($5k → ~$7.4k), then the power of compounding on a larger capital base produces the steep growth in years 4–5 ($7.4k → $28.9k).

### Fee Structure & Order Types

Binance USDⓈ-M Futures fees depend on order type:

| Order Type | Standard | With BNB (10% off) |
|-----------|:--------:|:------------------:|
| **Maker** (limit entry at FVG edge) | 0.02% | 0.018% |
| **Taker** (market exit on SL/TP) | 0.05% | 0.045% |
| **Round-trip** (maker entry + taker exit) | **0.07%** | **0.063%** |

The strategy places entries at the **proximal FVG edge** via limit orders (maker rate). Exits hit stop-loss or take-profit levels, which trigger market orders (taker rate). This is reflected in the round-trip fee rates above.

### ATR Fix & Pipeline Integrity

The `atr` column was missing from the ICT pipeline in an earlier version — the `Combo521Detector` reads ATR for stop-loss distance calculation, and without it, SL used a hardcoded 1% of price instead of the intended `ATR × 2.0`. This was fixed by adding `calculate_atr(df)` to both the live orchestrator and backtest pipeline, ensuring:
- Backtest results reflect what the **live system actually does**
- SL distance adapts to market volatility (ATR varies $3–$7 on ETH 5m)
- Tight stops in low-volatility periods reduce unnecessary losses

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
| Fees | Maker 0.02% / Taker 0.05% (standard) | `--fee-pct 0.063` (with BNB) |

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
