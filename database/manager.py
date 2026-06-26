import asyncio
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from loguru import logger

Base = declarative_base()

class DBTrade(Base):  # type: ignore[valid-type,misc]
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    signal_type = Column(String)
    side = Column(String)
    entry_time = Column(DateTime)
    exit_time = Column(DateTime)
    entry_price = Column(Float)
    exit_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    quantity = Column(Float)
    profit = Column(Float)
    profit_pct = Column(Float)
    rr = Column(Float)
    result = Column(String)
    exit_reason = Column(String)

class DBSignal(Base):  # type: ignore[valid-type,misc]
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String)
    signal_type = Column(String)
    score = Column(Integer)
    bullish_score = Column(Integer, default=0)
    bearish_score = Column(Integer, default=0)
    net_score = Column(Integer, default=0)
    price = Column(Float)
    timeframe = Column(String)
    bias = Column(String, default="neutral")
    htf_bias = Column(String, default="neutral")
    htf_aligned = Column(Boolean, default=True)
    in_kill_zone = Column(Boolean, default=False)
    details = Column(Text) # JSON string

class DBAccountState(Base):  # type: ignore[valid-type,misc]
    __tablename__ = 'account_state'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    balance = Column(Float)
    equity = Column(Float)
    peak_balance = Column(Float)

class DBPosition(Base):  # type: ignore[valid-type,misc]
    __tablename__ = 'positions'
    symbol = Column(String, primary_key=True)
    side = Column(String)
    signal_type = Column(String)
    entry_time = Column(DateTime)
    entry_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    quantity = Column(Float)
    risk_amount = Column(Float)
    atr = Column(Float)

class DatabaseManager:
    def __init__(self, db_url="sqlite+aiosqlite:///trading.db"):
        self.engine = create_async_engine(db_url)
        self.async_session = sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save_trade(self, trade_data: Dict):
        async with self.async_session() as session:
            db_trade = DBTrade(**trade_data)
            session.add(db_trade)
            await session.commit()

    async def save_signal(self, signal_data: Dict):
        async with self.async_session() as session:
            # Extract details
            details = signal_data.pop('details', {})
            
            # Identify columns that exist on DBSignal
            valid_columns = {
                "timestamp", "symbol", "signal_type", "score",
                "bullish_score", "bearish_score", "net_score",
                "price", "timeframe", "bias", "htf_bias",
                "htf_aligned", "in_kill_zone",
            }
            
            # Any field not in valid_columns and not 'details' should be moved into details
            for key, value in list(signal_data.items()):
                if key not in valid_columns:
                    details[key] = signal_data.pop(key)
            
            filtered = {k: v for k, v in signal_data.items() if k in valid_columns}
            db_signal = DBSignal(
                **filtered,
                details=json.dumps(details)
            )
            session.add(db_signal)
            await session.commit()

    async def update_account_state(self, balance: float, equity: float, peak_balance: float):
        async with self.async_session() as session:
            state = DBAccountState(
                balance=balance,
                equity=equity,
                peak_balance=peak_balance,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            session.add(state)
            await session.commit()

    async def save_position(self, pos_data: Dict):
        async with self.async_session() as session:
            db_pos = DBPosition(**pos_data)
            await session.merge(db_pos)
            await session.commit()

    async def remove_position(self, symbol: str):
        async with self.async_session() as session:
            from sqlalchemy import delete
            await session.execute(delete(DBPosition).where(DBPosition.symbol == symbol))
            await session.commit()

    async def load_positions(self) -> List[Dict]:
        from sqlalchemy import select
        async with self.async_session() as session:
            result = await session.execute(select(DBPosition))
            return [dict(r._mapping['DBPosition'].__dict__) for r in result.all()]

    async def get_recent_trades(self, limit=200) -> List[Dict]:
        from sqlalchemy import select
        async with self.async_session() as session:
            result = await session.execute(select(DBTrade).order_by(DBTrade.exit_time.desc()).limit(limit))
            return [dict(r._mapping['DBTrade'].__dict__) for r in result.all()]

    async def clear_all_data(self):
        """Wipe all tables for a fresh start."""
        from sqlalchemy import delete
        async with self.async_session() as session:
            await session.execute(delete(DBTrade))
            await session.execute(delete(DBSignal))
            await session.execute(delete(DBPosition))
            await session.execute(delete(DBAccountState))
            await session.commit()
        logger.info("Database: All tables wiped for fresh start.")


    async def load_last_state(self) -> Optional[Dict]:
        from sqlalchemy import select
        async with self.async_session() as session:
            result = await session.execute(select(DBAccountState).order_by(DBAccountState.timestamp.desc()).limit(1))
            row = result.first()
            return dict(row._mapping['DBAccountState'].__dict__) if row else None
