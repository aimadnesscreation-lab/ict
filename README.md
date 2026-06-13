# Institutional AI Trading Intelligence Platform

A production-ready algorithmic trading platform built on mathematical ICT (Inner Circle Trader) concepts, Machine Learning, and Real-time Data Analytics.

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.12+**
- **Node.js 18+**
- **Docker & Docker Compose**

### 2. Environment Setup
```bash
# Clone the repository
git clone <repo-url>
cd trading-prompt

# Setup Python Virtual Environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r pyproject.toml # Or use the one-liner in implementation notes
```

### 3. Infrastructure
Start the database and messaging services:
```bash
docker-compose up -d
```

### 4. Running the Platform

#### Step A: Start the Intelligence Engine
The engine handles data collection, ICT analysis, news sentiment, and signal generation.

**To run with Mock Data (Default):**
```bash
python main.py
```

**To run with Real Market Data (Binance):**
```bash
LIVE_DATA=true python main.py
```
*(Note: Ensure your internet connection is active for Binance API access)*

#### Step B: Start the API Backend
Serves data to the dashboard.
```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

#### Step C: Launch the Dashboard
Modern React interface for real-time monitoring.
```bash
cd dashboard
npm install
npm run dev
```

---

## 🏗️ System Architecture

### Core Modules
- **`ict_engine/`**: The mathematical core. Detects Swings, BOS, MSS, FVGs, and Order Blocks.
- **`market_data/`**: Connectors for Binance and Mock data sources.
- **`signal_engine/`**: Weighted confluence scoring system (0-100).
- **`ml_engine/`**: XGBoost pipeline for predicting signal success probability.
- **`risk/`**: Automated position sizing and safety limits.
- **`api/`**: FastAPI backend with OpenAPI documentation.
- **`dashboard/`**: React/TS dashboard with TradingView charts.

### Database Schema (PostgreSQL)
- `candles`: Historical price data.
- `signals`: Generated trading signals and confluences.
- `trades`: Execution logs and performance results.
- `fvg_zones` / `order_blocks`: Tracked ICT levels.

---

## 🧪 Testing
The system includes a suite of unit tests and an end-to-end smoke test.
```bash
# Run unit tests
pytest tests/test_ict_engine.py

# Run E2E smoke test (verifies Binance -> ICT -> Signal wiring)
python smoke_test.py
```

## 🛠️ Configuration
Edit `database/config.py` or create a `.env` file to configure:
- `POSTGRES_URL`: Database connection string.
- `TELEGRAM_BOT_TOKEN`: For real-time alerts.
- `BINANCE_API_KEY`: (Optional) for authenticated requests.

---

## ⚖️ Disclaimer
This software is for **educational and research purposes only**. No live trade execution is enabled by default. Trading financial markets involves significant risk.
