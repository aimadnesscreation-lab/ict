from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict
from database.config import settings
from database.models import Candle, Signal, Trade, NewsArticle
# In a real app, we'd have a database/session.py to provide get_db
# For now, we mock the responses or assume DB connectivity

app = FastAPI(title="Institutional Trading Intelligence Platform API")

@app.get("/")
async def root():
    return {"status": "online", "version": "0.1.0"}

from sqlalchemy import select
from database.session import get_db

@app.get("/signals")
async def get_signals(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """
    Fetch recent trading signals from the database.
    """
    result = await db.execute(select(Signal).order_by(Signal.timestamp.desc()).limit(limit))
    return result.scalars().all()

@app.get("/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "1h", limit: int = 100, db: AsyncSession = Depends(get_db)):
    """
    Fetch historical candles for a symbol from the database.
    """
    result = await db.execute(
        select(Candle)
        .where(Candle.symbol == symbol.upper(), Candle.timeframe == timeframe)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()

@app.get("/news")
async def get_news(limit: int = 10):
    """
    Fetch recent financial news and sentiment.
    """
    return []

from analytics.performance import PerformanceAnalytics
from risk.manager import RiskManager

# Global state for demonstration (in real app use DB/Redis)
risk_manager = RiskManager()
trades_history = [] 

@app.get("/performance")
async def get_performance():
    """
    Fetch backtesting and trade performance metrics.
    """
    metrics = PerformanceAnalytics.calculate_metrics(trades_history)
    return metrics or {
        "win_rate": 0,
        "total_pnl": 0,
        "profit_factor": 0,
        "max_drawdown": 0,
        "status": "No trades yet"
    }

@app.get("/risk/status")
async def get_risk_status():
    """
    Fetch current risk management status.
    """
    return {
        "max_risk_per_trade": risk_manager.max_risk_per_trade_pct,
        "daily_loss_limit": risk_manager.max_daily_loss_pct,
        "current_daily_loss": risk_manager.current_daily_loss,
        "open_positions": risk_manager.open_positions_count
    }
