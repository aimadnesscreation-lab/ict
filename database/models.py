from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Candle(Base):
    __tablename__ = "candles"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    timeframe = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

class Signal(Base):
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    signal_type = Column(String, nullable=False) # BUY, SELL, STRONG_BUY, etc.
    score = Column(Integer)
    entry = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    confidence = Column(Float)
    meta_data = Column(JSON) # To store ICT reasons

class Trade(Base):
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    entry_time = Column(DateTime)
    exit_time = Column(DateTime)
    entry_price = Column(Float)
    exit_price = Column(Float)
    profit = Column(Float)
    rr = Column(Float) # Risk/Reward
    result = Column(String) # WIN, LOSS, BREAK_EVEN

class LiquidityZone(Base):
    __tablename__ = "liquidity_zones"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime)
    price = Column(Float)
    zone_type = Column(String) # EQL, EQH, PDH, PDL, etc.
    is_swept = Column(Boolean, default=False)

class FVGZone(Base):
    __tablename__ = "fvg_zones"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime)
    top_price = Column(Float)
    bottom_price = Column(Float)
    midpoint = Column(Float)
    fvg_type = Column(String) # BULLISH, BEARISH
    status = Column(String, default="OPEN") # OPEN, TOUCHED, FILLED

class OrderBlock(Base):
    __tablename__ = "order_blocks"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timestamp = Column(DateTime)
    high_price = Column(Float)
    low_price = Column(Float)
    ob_type = Column(String) # BULLISH, BEARISH
    status = Column(String, default="UNTOUCHED") # UNTOUCHED, TOUCHED, MITIGATED, INVALIDATED

class NewsArticle(Base):
    __tablename__ = "news_articles"
    
    id = Column(Integer, primary_key=True)
    title = Column(String)
    source = Column(String)
    published_at = Column(DateTime)
    content = Column(String)
    sentiment = Column(Float) # -1.0 to 1.0
    entities = Column(JSON) # Currencies affected

class ModelPrediction(Base):
    __tablename__ = "model_predictions"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String)
    probability = Column(Float)
    prediction = Column(Integer) # 1 for Win, 0 for Loss
