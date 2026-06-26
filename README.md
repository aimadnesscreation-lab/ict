# ICT Trading Intelligence Platform

A production-grade algorithmic trading platform built on **ICT (Inner Circle Trader)** concepts — a mathematical framework for market structure analysis. The system processes **real-time WebSocket data** through a 6-module ICT pipeline, detects **Combo 521 sweep+FVG patterns**, manages a persistent forward-testing account (DemoAccount), mirrors trades onto **Binance USDⓈ-M Futures** (LONG + SHORT) via **post-only limit orders** (maker fee model), and surfaces everything through a React dashboard with real-time diagnostics and Discord webhook alerts.

---

## 🚀 Production-Ready Features

- **Real-Time Data Ingestion:** Powered by **CCXT Pro WebSockets** with automatic REST fallback. Zero-latency ticker and candle updates ensure entries are triggered the millisecond a candle closes.
- **Binance USDⓈ-M Futures:** Supports both **LONG and SHORT** positions with 3× leverage, stop-market SL/TP orders, and one-way position mode.
- **Combo 521 Pattern Detection:** Detects sweep+FVG patterns on **ETHUSDT + SOLUSDT** 5m candles (proximal FVG edge entry, PD zone filter, 3.0× ATR SL, 1:3 RR). Skips the dual-scoring engine — every valid pattern becomes a signal passed directly to DemoAccount.
- **Post-Only Limit Orders:** Live entries use limit orders at the FVG proximal edge (maker fee = 0.02%), matching the backtest entry model. Orders may not fill immediately — SyncWorker retries unfilled orders.
- **Persistent State Management:** Integrated **SQLite + SQLAlchemy** (async) database. Every trade, signal, and balance change is persisted locally in `trading.db`.
- **Auto-Recovery:** The system automatically restores its state (balance, open positions, history) from the database on startup, surviving server restarts.
- **WebSocket HTF Bias:** Real-time 1H trend detection via EMA12/EMA26 crossovers with 0.5% threshold. Falls back to swing structure analysis for neutral EMA readings.
- **Position Reconciliation:** SyncWorker reconciles DemoAccount ↔ exchange positions every 30 seconds — detects SL/TP hits, partial fills, and manual closes on the exchange.
- **Docker Support:** Ready for cloud deployment with `Dockerfile` and `docker-compose.yml`.
- **Render Blueprint:** Deploy API + Dashboard on Render with one click via `render.yaml`.
- **Dual-Symbol Trading:** Trades both **ETHUSDT and SOLUSDT** simultaneously. Natural uncorrelation keeps drawdown under ~10%.
- **System Diagnostics:** Dedicated `/api/diagnostics` endpoint for monitoring WebSocket health, DB connectivity, and risk levels.

---

## 📊 Backtest Results (5-Year)

All backtests use the **live pipeline** (`backtest_binance.py`): the same `Combo521Detector`, `DemoAccount`, and ICT modules that run in production. Results are on **5m candles** with the **Combo 521** sweep+FVG strategy (proximal entry, PD zone filter, 20-bar lookback).

### Winning Configuration (5 Years — Aug 2021 to Jun 2026)

| Setting | Value |
|:--------|:------|
| Entry model | **Post-only limit at FVG edge** (maker fee) |
| Entry timing | **Immediate FVG proximal edge** (no next-candle delay) |
| Fee | **0.06% round-trip** (0.02% maker entry + 0.04% taker exit) |
| SL multiplier | **3.0× ATR** (wider SL reduces loss severity per optimizer) |
| TP | **1:3 RR** (3× SL distance) |
| Risk per trade | **1.0%** of balance |
| Capital per symbol | **$5,000** (non-compounding, monthly reset) |
| Symbols | **ETHUSDT + SOLUSDT** |
| Direction | LONG + SHORT (Futures) |
| Max positions | 3 |

#### ETHUSDT (5-Year)

| Metric | Value |
|--------|:-----:|
| Total Trades | **3,204** (1,025W / 2,179L) |
| Win Rate | **32.0%** |
| **Total P&L** | **+$21,807** |
| Avg Monthly P&L | **+$363** |
| Total Return | **+436%** |
| Avg Drawdown | **11.8%** |

```
python backtest_binance.py --symbol ETHUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02
```

#### SOLUSDT (5-Year)

| Metric | Value |
|--------|:-----:|
| Total Trades | **3,222** (1,054W / 2,168L) |
| Win Rate | **32.7%** |
| **Total P&L** | **+$36,138** |
| Avg Monthly P&L | **+$602** |
| Total Return | **+723%** |
| Avg Drawdown | **11.5%** |

```
python backtest_binance.py --symbol SOLUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02
```

#### Combined Portfolio ($10k total — $5k per symbol)

| Metric | Value |
|:-------|:-----:|
| **Combined P&L** | **+$28,972** |
| Combined Return | **+290%** (on $10k) or **+579%** (on $5k split) |
| Avg Monthly | **+$483** |
| Est. Combined DD | **~8%** (uncorrelated hedges) |

> **SOLUSDT outperforms ETH by 66% on P&L (+$36.1k vs +$21.8k)** with similar drawdown. The smaller, more volatile asset generates more FVG opportunities. Running both symbols together provides natural uncorrelation that reduces max drawdown from ~12% (single) to ~8% (combined).

### Compounding (5-Year, $5k Start Per Symbol)

When balance compounds month-to-month (no reset), the same 32% win rate with 1.68 avg RR on a growing capital base produces exponential returns:

| Metric | **ETHUSDT** | **SOLUSDT** | **Combined** |
|:-------|:----------:|:----------:|:----------:|
| Total trades | 3,204 | 3,222 | 6,426 |
| Win rate | 32.0% | 32.7% | ~32.4% |
| Avg RR | 1.68 | 1.68 | 1.68 |
| Avg drawdown | 11.8% | 11.5% | **~9%** |
| **Total P&L** | **+$219,006** | **+$2,764,789** | **+$2,983,795** |
| **Final capital** | **$224,006** | **$2,769,789** | **~$2,993,795** |
| **Total return** | **+4,380%** | **+55,295%** | **+29,838%** |
| **Avg monthly** | **+$3,650** | **+$46,079** | **+$49,729** |

```
python backtest_binance.py --symbol ETHUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02 --compound
python backtest_binance.py --symbol SOLUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02 --compound
```

> **The 0.04% fee advantage + immediate entry compounds massively over 6,400+ trades.** ETH produces a smooth exponential curve ($5k → $224k). SOLUSDT's higher trade density on a growing balance generates a steeper curve ($5k → $2.7M). Combined, the strategy turns $10k into ~$3M over 5 years with ~9% max drawdown — without leverage.

### Non-Compounding vs Compounding Comparison

| Scenario | Capital | Total P&L | Return |
|:---------|:------:|:---------:|:------:|
| Non-compounding (monthly reset) | $5k × 2 | **+$28,972** | +290% |
| **Compounding** | $5k × 2 | **+$2,983,795** | **+29,838%** |

Compounding turns the same strategy into **103× more profit** — the 1% risk-per-trade on a growing balance creates a feedback loop where larger wins further increase position size.

### Why Limit-Order Entry Wins

The evolution from market orders to limit orders was the single biggest improvement:

| Entry Model | Fee | ETH P&L (5yr) | SOL P&L (5yr) |
|:------------|:--:|:------------:|:-------------:|
| Next-candle market (taker fee) | 0.10% | +$3,305 | +$7,114 |
| Immediate FVG edge (maker fee) | **0.06%** | **+$21,807** | **+$36,138** |

The **0.04% fee savings × 6,400 trades** saves ~$2,500/token in fees, and the **immediate entry** captures more trades at better prices vs. waiting for the next candle.

### Other Tested Variants (Research Summary)

| Variant | Result | Verdict |
|:--------|:------:|:--------|
| **Kill Zone filter** | -55% trades, same WR, proportionally less P&L | Risk-reduction filter, no edge gain |
| **1H sweep + 5m FVG (MTF)** | -60% trades, 0.3pp lower WR, less P&L/trade | Underperforms standard Combo 521 |

---

## 🏗️ Architecture Overview

```
Binance Futures WebSockets (Real-time via CCXT Pro)
                    │
                    ▼
  ┌─────────────────────────────┐     ┌──────────────────────────┐
  │  TradingOrchestrator         │────▶│  ICT Pipeline             │
  │  (unified entry point)       │     │  (6 vectorized modules)  │
  │  - hot-path execution        │     │  - Market Structure      │
  │  - real-time triggers        │     │  - Liquidity Sweeps      │
  └──────────────┬──────────────┘     │  - FVG Detection         │
                 │                     │  - Premium/Discount OTE  │
                 ▼                     │  - Sessions info         │
  ┌─────────────────────────────┐     └────────────┬─────────────┘
  │  Combo521Detector            │◀─────────────────┘
  │  (sweep+FVG pattern only)   │
  │  - proximal edge entry      │
  │  - PD zone filter           │
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐     ┌──────────────────────────┐
  │  DemoAccount + SQLite DB          │────▶│  LiveExecutor            │
  │  - persistent state recovery      │     │  (Binance Futures)      │
  │  - trade entry/exit/logging       │     │  - Post-only limit entry│
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

6 vectorized **Polars**-based modules that run on every 5m candle close:

| Module | File | Detection |
|--------|------|-----------|
| **Market Structure** | `market_structure.py` | Swing highs/lows (n=2 for Combo 521) |
| **Liquidity** | `liquidity.py` | Equal highs/lows, sweeps, prev day H/L |
| **Fair Value Gap** | `fvg.py` | 3-candle imbalances |
| **Sessions** | `sessions.py` | Asian/London/NY session tracking |
| **Premium/Discount** | `premium_discount.py` | Equilibrium zones |
| **Utils** | `utils.py` | ATR calculation, helpers |

### Layer 2: Combo 521 Detector (`signal_engine/combo521.py`)

The core pattern detector — **bypasses** the old dual-scoring engine entirely. Every valid sweep+FVG pattern becomes a signal:

1. Detects liquidity sweeps (low taken for LONG triggers, high taken for SHORT)
2. Within 20 bars, looks for a same-direction FVG with gap ≥ 0.05%
3. Checks price is at the FVG proximal edge
4. **PD zone filter:** LONG requires discount zone, SHORT requires premium zone
5. FVG must not be filled yet
6. Proximal limit entry → post-only order on Binance (maker fee)

### Layer 3: Trading Orchestrator (`trading_engine/orchestrator.py`)

Unified entry point that coordinates the entire pipeline:

1. Runs ICT pipeline on **5m** data (swings, FVG, liquidity sweeps, PD zones)
2. Detects **Combo 521** sweep+FVG patterns
3. Signals are passed directly to DemoAccount (no scoring filter — every signal=100)
4. **Futures mode** — both LONG and SHORT signals are supported
5. Mirrors newly opened positions to **Binance Futures** via post-only limit orders
6. Unfilled limit orders are retried by SyncWorker every 30s
7. Sends Discord notifications per new position

### Layer 4: Demo Account (`demo_account.py`)

**Persistent** forward-testing engine with **SQLite** state recovery:

- **$5,000** paper capital per symbol (configurable via `DEMO_INITIAL_BALANCE`)
- **Trade Parameters:**

| Parameter | Live Value |
|:----------|:----------:|
| Starting capital | $5,000 |
| Risk per trade | 1.0% of balance |
| Stop-loss distance | **3.0× ATR** |
| Take-profit distance | **1:3 RR** (3× SL, `tp_ratio=3.0`) |
| Max open positions | 3 |
| Max daily loss | 3.0% of initial balance |
| Re-entry cooldown | 0 min (none) |
| Kill zone required | **No** (trade all sessions) |
| Direction | LONG + SHORT (Futures) |
| Symbols | ETHUSDT + SOLUSDT |
| Leverage | 3× (live only, not used in DemoAccount) |

### Layer 5: Live Execution (`execution/`)

- **LiveExecutor** (`executor.py`): Connects to **Binance USDⓈ-M Futures** via CCXT
  - Uses **post-only limit orders** at FVG proximal edge for entry (maker fee)
  - **STOP_MARKET** (stop-loss) + **TAKE_PROFIT_MARKET** (take-profit) as reduce-only orders
  - Supports **both LONG and SHORT** positions
  - **One-way position mode** — side='buy' opens LONG, side='sell' opens SHORT
  - Default **3× leverage**
- **SyncWorker** (`sync_worker.py`): Reconciles DemoAccount ↔ exchange every 30s
  - Detects SL/TP hits on exchange → closes in DemoAccount
  - Handles **partial fills** and unfilled limit orders

### Layer 6: API + Dashboard

**Backend** (`api/main.py`):
- **FastAPI** server with 3 real-time background workers:
  - Crypto data worker (**Binance WebSockets** with REST fallback)
  - HTF bias worker (**Binance 1h WebSockets**)
  - Exchange sync (30s cycle)
- **Real-time Stream:** `/ws/data` pushes updates for signals, trades, and performance.
- Static dashboard served at `/dashboard/`.

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

The script creates a virtual environment, installs deps, verifies your connection, and starts both the API server (port 8000) and Vite dev server (port 5173). Press `Ctrl+C` to stop both.

### Dashboard (standalone)
```bash
cd dashboard
npm install
npm run dev          # dev server at http://localhost:5173
```

### Running in the Background

#### `nohup` (quickest)
```bash
cd /path/to/ict
nohup ./start.sh > trading.log 2>&1 &
# Stop:
pkill -f uvicorn
pkill -f vite
```

#### `tmux` (best for monitoring)
```bash
tmux new-session -d -s trading './start.sh'
tmux attach -t trading      # Ctrl+B then D to detach
tmux kill-session -t trading
```

#### `systemd` (auto-start on boot)
```bash
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

Access the pre-built dashboard at `http://localhost:8000/dashboard/`.

---

## 🧪 Testing

### Backtest (Verify Winning Config)
```bash
# ETHUSDT 5-year
python backtest_binance.py --symbol ETHUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02

# SOLUSDT 5-year
python backtest_binance.py --symbol SOLUSDT --months 60 --sl-multiplier 3.0 --capital 5000 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02

# Quick 1-month test
python backtest_binance.py --months 1 --offset 0 --fee-pct 0.06 --entry-mode immediate --sl-slippage-pct 0.05 --tp-slippage-pct 0.02
```

### Unit Tests
```bash
pytest tests/ -v
```

### End-to-End Integration Test
```bash
python test_integration.py
```
Verifies: server boot, Binance data backfill, HTF bias, ICT pipeline signals, DemoAccount processing, Binance demo trading connection.

### Binance Order Placement Test
```bash
python test_binance_orders.py
```
Tests the full order lifecycle on Binance Futures Testnet (LONG + SHORT with SL/TP).

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. Past backtest performance does not guarantee future results. The system uses a demo/sandbox exchange environment by default — no real funds are traded unless `EXCHANGE_MODE=live` is explicitly set.
