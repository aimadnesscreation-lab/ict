import polars as pl
from typing import Dict, List, Optional
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector


class SignalEngine:
    """
    Full ICT confluence scoring engine.

    Weights (from full.md):
      - Bias / HTF Alignment    = 20
      - MSS                     = 20
      - Liquidity Sweep         = 20
      - FVG                     = 15
      - Order Block             = 15
      - News                    = 10
      - Discount Zone           = 10  ← added
      - OTE Zone                = 10  ← added
      - Session / Kill Zone     = 10  ← added
      ──────────────────────────────
        Maximum                 = 130 (capped at 100)

    Score thresholds:
      80+  → Strong Buy (or Strong Sell)
      60–79 → Buy (or Sell)
      40–59 → Neutral
      20–39 → (weak, likely no signal)
       0–19 → (no confluence)
    """

    def __init__(self, weights: Optional[Dict[str, int]] = None):
        self.weights = weights or {
            "bias": 20,
            "mss": 20,
            "liquidity_sweep": 20,
            "fvg": 15,
            "order_block": 15,
            "news": 10,
            "discount_zone": 10,
            "ote": 10,
            "session": 10,
        }
        self.session_detector = SessionDetector()
        self.pd_detector = PremiumDiscountDetector()
        self.breaker_detector = BreakerBlockDetector()

    def _determine_bias(self, df: pl.DataFrame) -> str:
        """
        Determine trend bias from swing structure.
        Bullish: series of HH + HL (higher highs + higher lows)
        Bearish: series of LL + LH (lower lows + lower highs)
        Neutral: no clear structure
        """
        if "swing_high" not in df.columns or "swing_low" not in df.columns:
            return "neutral"

        recent_highs = df["swing_high"].drop_nulls().tail(4).to_list()
        recent_lows = df["swing_low"].drop_nulls().tail(4).to_list()

        if len(recent_highs) < 2 or len(recent_lows) < 2:
            return "neutral"

        # Check for HH + HL (bullish)
        hh = all(recent_highs[i] > recent_highs[i - 1] for i in range(1, len(recent_highs)))
        hl = all(recent_lows[i] > recent_lows[i - 1] for i in range(1, len(recent_lows)))

        if hh and hl:
            return "bullish"

        # Check for LL + LH (bearish)
        ll = all(recent_lows[i] < recent_lows[i - 1] for i in range(1, len(recent_lows)))
        lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, len(recent_highs)))

        if ll and lh:
            return "bearish"

        return "neutral"

    def generate_signal(
        self,
        df: pl.DataFrame,
        mss: bool = False,
        sweep: bool = False,
        news_sentiment: float = 0.0,
        timeframe: str = "1h",
    ) -> Dict:
        """
        Generate a signal based on full ICT confluence scoring.
        """
        score = 0
        current_candle = df.tail(1).to_dicts()[0]
        current_price = current_candle.get("close", 0)

        # 1. Bias / HTF Alignment
        bias = self._determine_bias(df)
        if bias != "neutral":
            score += self.weights["bias"]

        # 2. MSS
        if mss:
            score += self.weights["mss"]

        # 3. Liquidity Sweep
        if sweep:
            score += self.weights["liquidity_sweep"]

        # 4. FVG
        has_fvg = "fvg_type" in df.columns and df["fvg_type"].tail(5).is_not_null().any()
        if has_fvg:
            score += self.weights["fvg"]

        # 5. Order Block
        has_ob = "ob_type" in df.columns and df["ob_type"].tail(5).is_not_null().any()
        if has_ob:
            score += self.weights["order_block"]

        # 6. News
        if news_sentiment > 0.5:
            score += self.weights["news"]

        # 7. Premium/Discount Zone + OTE
        pd_scores = self.pd_detector.get_score_contribution(df, bias)
        score += pd_scores.get("total", 0)

        # 8. Session / Kill Zone alignment
        in_kill_zone = False
        active_kill_zones: List[str] = []
        active_sessions: List[str] = []
        if "timestamp" in current_candle:
            ts = current_candle["timestamp"]
            session_info = self.session_detector.get_current_session_info(ts)
            score += session_info.get("score_bonus", 0)
            in_kill_zone = session_info.get("in_kill_zone", False)
            active_kill_zones = session_info.get("active_kill_zones", [])
            active_sessions = session_info.get("active_sessions", [])

        # Cap score at 100
        score = min(score, 100)

        # Categorize
        if score >= 80:
            signal_type = "STRONG_BUY"
        elif score >= 60:
            signal_type = "BUY"
        elif score >= 40:
            signal_type = "NEUTRAL"
        elif score >= 20:
            signal_type = "SELL"
        else:
            signal_type = "STRONG_SELL"

        return {
            "score": score,
            "signal_type": signal_type,
            "timestamp": current_candle.get("timestamp"),
            "price": current_price,
            "timeframe": timeframe,
            "bias": bias,
            "in_kill_zone": in_kill_zone,
            "details": {
                "mss": mss,
                "sweep": sweep,
                "fvg": has_fvg,
                "ob": has_ob,
                "news_sentiment": news_sentiment,
                "discount": current_candle.get("in_discount", False),
                "ote": current_candle.get("in_ote", False),
                "bias": bias,
                "in_kill_zone": in_kill_zone,
                "active_sessions": active_sessions,
                "active_kill_zones": active_kill_zones,
            },
        }
