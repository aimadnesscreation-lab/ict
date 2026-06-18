"""
ICT Session & Kill Zone Module.

References: ict.md — Session Module, Kill Zones

Sessions:
  - Asian:   00:00 – 09:00 UTC
  - London:  08:00 – 17:00 UTC
  - New York: 13:00 – 22:00 UTC

Kill Zones:
  - London Kill Zone (LKZ): 07:00 – 09:00 UTC (covers London open year-round)
  - New York Kill Zone (NYKZ): 13:00 – 15:00 UTC (covers NY open year-round)
  - London Close: 17:00 – 18:00 UTC
"""

import polars as pl
from datetime import datetime, time, timedelta, timezone
from typing import Dict, Optional, Tuple


# ── Session time windows (UTC) ──────────────────────────────────────────

SESSION_WINDOWS = {
    "asian":    (time(0, 0),  time(9, 0)),
    "london":   (time(8, 0),  time(17, 0)),
    "new_york": (time(13, 0), time(22, 0)),
}

# Kill Zones (UTC, standard/winter time)
KILL_ZONE_WINDOWS = {
    "london_kill_zone":   (time(7, 0),  time(9, 0)),    # 07:00–09:00 UTC (London open)
    "new_york_kill_zone": (time(13, 0), time(15, 0)),   # 13:00–15:00 UTC
    "london_close":       (time(17, 0), time(18, 0)),   # 17:00–18:00 UTC
}


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def is_in_window(candle_time: datetime, window_start: time, window_end: time) -> bool:
    """Check if a candle's timestamp falls within a given time window."""
    t = candle_time.time()
    if window_start <= window_end:
        return window_start <= t < window_end
    else:
        # Wraps past midnight (e.g. 22:00 – 02:00)
        return t >= window_start or t < window_end


def get_active_sessions(candle_time: datetime) -> Dict[str, bool]:
    """Return which sessions are active for a given timestamp."""
    return {
        name: is_in_window(candle_time, start, end)
        for name, (start, end) in SESSION_WINDOWS.items()
    }


def get_active_kill_zones(candle_time: datetime) -> Dict[str, bool]:
    """Return which kill zones are active for a given timestamp."""
    return {
        name: is_in_window(candle_time, start, end)
        for name, (start, end) in KILL_ZONE_WINDOWS.items()
    }


def get_session_high_low(df: pl.DataFrame, session_name: str) -> Tuple[Optional[float], Optional[float]]:
    """Get the high and low of the most recent session window."""
    if "timestamp" not in df.columns:
        return (None, None)

    start, end = SESSION_WINDOWS.get(session_name, (None, None))
    if start is None:
        return (None, None)

    # Filter candles within the session window using vectorized hour check
    ts = df["timestamp"]
    if ts.dtype == pl.Utf8:
        ts = ts.str.to_datetime()
    session_hour = ts.dt.hour()

    if start <= end:
        mask = (session_hour >= start.hour) & (session_hour < end.hour)
    else:
        mask = (session_hour >= start.hour) | (session_hour < end.hour)

    session_candles = df.filter(mask)

    if session_candles.is_empty():
        return (None, None)

    return (
        session_candles["high"].max(),
        session_candles["low"].min(),
    )


class SessionDetector:
    """Detect sessions, kill zones, and track session highs/lows."""

    def detect_sessions(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add session and kill zone columns to the dataframe using vectorized
        hour-of-day comparisons (no row-by-row apply).
        Returns df with columns: session_asian, session_london, session_new_york,
        killzone_london, killzone_new_york, killzone_london_close.
        """
        if "timestamp" not in df.columns:
            return df

        # Ensure timestamp is datetime
        ts = df["timestamp"]
        if ts.dtype == pl.Utf8:
            ts = ts.str.to_datetime()
        hour = ts.dt.hour()

        # Vectorized session detection (no apply, no lambda)
        session_asian   = (hour >= 0) & (hour < 9)
        session_london  = (hour >= 8) & (hour < 17)
        session_ny      = (hour >= 13) & (hour < 22)
        kz_london       = (hour >= 7) & (hour < 9)
        kz_ny           = (hour >= 13) & (hour < 15)
        london_close    = (hour >= 17) & (hour < 18)

        return df.with_columns([
            session_asian.alias("session_asian"),
            session_london.alias("session_london"),
            session_ny.alias("session_new_york"),
            kz_london.alias("killzone_london"),
            kz_ny.alias("killzone_new_york"),
            london_close.alias("killzone_london_close"),
        ])

    def get_current_session_info(self, candle_time: datetime) -> Dict:
        """Return a dict with current session and kill zone info."""
        sessions = get_active_sessions(candle_time)
        kill_zones = get_active_kill_zones(candle_time)

        active_sessions = [name for name, active in sessions.items() if active]
        active_kill_zones = [name for name, active in kill_zones.items() if active]

        return {
            "active_sessions": active_sessions,
            "in_kill_zone": any(active_kill_zones),
            "active_kill_zones": active_kill_zones,
            "score_bonus": 10 if any(active_kill_zones) else 5 if len(active_sessions) >= 2 else 0,
        }
