# Local Setup Guide

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- Git

## 1. Clone the Repository

```bash
git clone <repo-url> trading
cd trading
```

## 2. Python Virtual Environment

Create and activate a virtual environment:

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (CMD):**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

## 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Install Dashboard Dependencies

```bash
cd dashboard
npm install
cd ..
```

## 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your Binance Demo Trading Portal API credentials:

```env
BINANCE_API_KEY=your_binance_demo_api_key
BINANCE_SECRET=your_binance_demo_secret
EXCHANGE_NAME=binance
EXCHANGE_MODE=demo
LEVERAGE=10
DEMO_INITIAL_BALANCE=5000
```

> **Getting Binance Demo credentials:** Go to [Binance Demo Trading Portal](https://testnet.binancefuture.com/), log in, create a demo account, and generate API keys from the dashboard. These are separate from your live Binance API keys.

## 6. Verify Connection

```bash
python test_live_connection.py
```

Expected output:
```
✅ ALL 15 TESTS PASSED
✅ USDT free balance: $5,000.00
```

## 7. Start the API Server

With virtual environment activated:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

This starts all background workers:
- OKX data polling (15s cycle)
- ICT signal generation
- Demo account position management
- Binance trade mirroring
- Exchange position sync (30s cycle)

Health check: `http://localhost:8000/api/health`

## 8. Start the Dashboard (separate terminal)

Activate the virtual environment in a new terminal, then:

```bash
cd dashboard
VITE_API_URL=http://localhost:8000 npm run dev
```

> **⚠️ Important:** The `VITE_API_URL` env var tells the dashboard where your API server is.
> Without it, dashboard requests go to `http://localhost:5173` (the Vite dev server itself)
> and will fail — causing it to show mock/fallback data instead of real data.

Opens at `http://localhost:5173` and connects to your local API at `http://localhost:8000`.

## 9. Run a Backtest

```bash
# 12-month backtest with $5k starting capital
python backtest_okx.py --parallel --capital 5000
```

## Quick Start (all commands)

```bash
# Terminal 1 — API Server
source venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Dashboard
cd dashboard
VITE_API_URL=http://localhost:8000 npm run dev

# Open http://localhost:5173
# Or just visit http://localhost:8000/dashboard (no VITE_API_URL needed)
```

> **💡 Tip:** You can skip the Vite dev server entirely and access the dashboard at
> `http://localhost:8000/dashboard` after running `cd dashboard && npm run build`.
> The API serves the built dashboard directly — no VITE_API_URL needed.

## Stopping

Press `Ctrl+C` in each terminal to stop the server and dashboard.
