Yes. If you're going to use an AI coding agent (Claude Code, OpenAI Codex, Gemini CLI, Cursor, Windsurf, Bolt, Lovable, etc.), you need a prompt that describes the entire system architecture, coding standards, database schema, deployment strategy, and implementation phases.

Use the prompt below as the master project specification.

# PROJECT: Institutional AI Trading Intelligence Platform

You are a senior quantitative developer, machine learning engineer, DevOps engineer, and system architect.

Your task is to build a complete production-ready AI-powered trading intelligence platform from scratch.

IMPORTANT:

This is NOT a simple trading bot.

This system must:

* Run 24/7 on a server
* Continuously collect market data
* Detect ICT trading concepts
* Analyze news
* Store historical memory
* Learn from historical performance
* Generate trading signals
* Explain every signal
* Provide a dashboard
* Send Telegram alerts
* Support future broker integration

The system should initially run in signal-only mode.

No live trade execution should be enabled by default.

---

## TECH STACK

Backend:

* Python 3.12+
* FastAPI
* SQLAlchemy
* PostgreSQL
* Redis
* Celery

Data Analysis:

* Pandas
* NumPy
* Polars

Machine Learning:

* XGBoost
* LightGBM
* CatBoost
* Scikit-Learn

Visualization:

* Plotly
* TradingView Lightweight Charts

Frontend:

* React
* TypeScript
* Tailwind CSS

Deployment:

* Docker
* Docker Compose

Messaging:

* Telegram Bot API

Logging:

* Loguru

Configuration:

* Pydantic Settings
* Environment Variables

---

## SYSTEM ARCHITECTURE

Create the following modules:

market_data/
ict_engine/
news_engine/
signal_engine/
ml_engine/
database/
api/
dashboard/
telegram/
backtesting/
risk/
analytics/

Each module must be isolated and documented.

---

## DATABASE DESIGN

Create PostgreSQL tables.

candles

id
symbol
timeframe
timestamp
open
high
low
close
volume

signals

id
symbol
timestamp
signal_type
score
entry
stop_loss
take_profit
confidence

trades

id
signal_id
entry_time
exit_time
profit
rr
result

liquidity_zones

id
symbol
timestamp
price
zone_type

fvg_zones

id
symbol
timestamp
top_price
bottom_price
status

order_blocks

id
symbol
timestamp
high_price
low_price
type

news_articles

id
title
source
published_at
sentiment

model_predictions

id
timestamp
symbol
probability
prediction

---

## MARKET DATA ENGINE

Build market data collectors.

Requirements:

* WebSocket support
* REST fallback
* Multi-symbol support
* Multi-timeframe support

Supported timeframes:

1m
5m
15m
1h
4h
1d

Store all candles.

Handle reconnects automatically.

Maintain data integrity.

---

## ICT ENGINE

Implement:

1. Swing High Detection
2. Swing Low Detection
3. Break of Structure
4. Market Structure Shift
5. Liquidity Sweep Detection
6. Equal High Detection
7. Equal Low Detection
8. Fair Value Gap Detection
9. Order Block Detection
10. Premium Discount Zones

All concepts must be rule-based and fully configurable.

No subjective logic.

---

## LIQUIDITY ENGINE

Detect:

Equal Highs
Equal Lows

Previous:

Day High
Day Low
Week High
Week Low

Session Highs
Session Lows

Generate liquidity maps.

---

## FVG ENGINE

Bullish FVG:

Candle1 High < Candle3 Low

Bearish FVG:

Candle1 Low > Candle3 High

Track:

Open
Touched
Filled

Store every FVG.

---

## ORDER BLOCK ENGINE

Bullish OB:

Last bearish candle before expansion.

Bearish OB:

Last bullish candle before expansion.

Expansion threshold:

2 x ATR

Store all valid blocks.

---

## NEWS ENGINE

Collect financial news.

Sources should be configurable.

For every article:

1. Clean text
2. Extract entities
3. Determine affected currencies/assets
4. Generate sentiment score
5. Store result

Sentiment scale:

-1.0 to +1.0

---

## SIGNAL ENGINE

Create a weighted scoring system.

Example:

HTF Bias = 20
MSS = 20
Liquidity Sweep = 20
FVG = 15
Order Block = 15
News = 10

Maximum score:

100

Signal Rules:

80+ Strong Buy

60-79 Buy

40-59 Neutral

20-39 Sell

0-19 Strong Sell

All weights configurable.

---

## MACHINE LEARNING ENGINE

DO NOT train immediately.

Create training pipeline.

Features:

MSS
BOS
Liquidity Sweep
FVG Size
ATR
Volume
Spread
Session
News Sentiment

Target:

Win/Loss

Models:

XGBoost
LightGBM
CatBoost

Implement:

train.py
predict.py
evaluate.py

Metrics:

Accuracy
Precision
Recall
F1
AUC

---

## MEMORY SYSTEM

The system must remember every setup.

Store:

Signal
Market State
Outcome

Allow future model training.

Build feature generation pipeline.

---

## BACKTESTING ENGINE

Create historical testing framework.

Features:

Historical replay
Signal generation
Performance analysis

Metrics:

Win Rate
Profit Factor
Sharpe Ratio
Drawdown
Average RR

Export reports.

---

## TELEGRAM ALERTS

Generate messages.

Example:

EURUSD BUY

Bias: Bullish

Liquidity Sweep: YES

MSS: YES

FVG: YES

Score: 87

Entry: 1.1050

SL: 1.1020

TP: 1.1120

Confidence: 92%

Include chart screenshot if available.

---

## API

Create FastAPI backend.

Endpoints:

/signals
/trades
/candles
/news
/performance
/models

Use OpenAPI documentation.

---

## DASHBOARD

Build modern trading dashboard.

Pages:

Overview

Signals

Trades

Performance

News

Models

Settings

Charts must update in real time.

---

## RISK MANAGEMENT

Implement:

Max risk per trade

Max daily loss

Max weekly loss

Max open positions

Position sizing calculator

---

## DEVOPS

Create:

Dockerfile

docker-compose.yml

.env.example

Automatic database migrations

Health checks

Restart policies

Structured logging

---

## TESTING

Create:

Unit tests

Integration tests

Backtesting tests

Database tests

Coverage target:

80%+

---

## DOCUMENTATION

Generate:

README.md

Installation guide

Deployment guide

Architecture diagrams

Developer documentation

API documentation

---

## IMPLEMENTATION ORDER

Phase 1

Database
Market Data
ICT Engine

Phase 2

Signal Engine
Telegram Alerts
Backtesting

Phase 3

News Engine
Dashboard
Analytics

Phase 4

Machine Learning

Phase 5

Optimization
Paper Trading

Phase 6

Optional Live Trading

Build the project step-by-step.

After completing each phase:

1. Run tests
2. Fix errors
3. Refactor
4. Update documentation
5. Commit changes

Never skip phases.

Never generate placeholder code.

Produce production-ready code only.

One additional recommendation: before asking an AI builder to generate everything, ask it to build **Phase 1 only** (Database + Market Data + ICT Engine). A single prompt requesting the entire platform often produces a huge codebase with many bugs. Building one phase at a time gives much better results and makes it easier to verify that the ICT detection logic is actually working before you add ML, news analysis, and autonomous decision-making.
