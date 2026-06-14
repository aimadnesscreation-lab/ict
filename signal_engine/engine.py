import polars as pl
from typing import Dict, List, Optional
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector


def determine_bias_from_swings(df: pl.DataFrame) -> str:
    """
    Determine trend bias from swing structure in a dataframe.
    The dataframe must have swing_high and swing_low columns.

    Bullish: series of HH + HL (higher highs + higher lows)
    Bearish: series of LL + LH (lower lows + lower highs)
    Neutral: no clear structure or insufficient data
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


class SignalEngine:
    """
    Dual-scoring ICT confluence engine.

    Instead of a single score (where a low score could mean "no patterns"
    OR "bearish patterns"), this engine tracks bullish and bearish scores
    independently. The net difference determines signal direction.

    Each ICT pattern contributes to one side:
      BULLISH Side:                     BEARISH Side:
        Bullish HTF bias   (20 pts)       Bearish HTF bias   (20 pts)
        Bullish MSS        (20 pts)       Bearish MSS        (20 pts)
        Bullish sweep      (20 pts)       Bearish sweep      (20 pts)
        Bullish FVG        (15 pts)       Bearish FVG        (15 pts)
        Bullish OB         (15 pts)       Bearish OB         (15 pts)
        Premium/Discount   (10 pts)       Premium/Discount   (10 pts)
        OTE Zone           (10 pts)       OTE Zone           (10 pts)
        Session/Kill Zone  (10 pts)       Session/Kill Zone  (10 pts)
        Bullish news       (10 pts)       Bearish news       (10 pts)
        ──────────────────────────       ──────────────────────────
        Max ~130 (capped 100)

    Signal type from net score (bullish - bearish):
      net >= 60  → STRONG_BUY
      net >= 30  → BUY
      net >  -30 → NEUTRAL
      net <= -30 → SELL
      net <= -60 → STRONG_SELL
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

    def generate_signal(
        self,
        df: pl.DataFrame,
        mss_type: Optional[str] = None,
        sweep_type: Optional[str] = None,
        news_sentiment: float = 0.0,
        timeframe: str = "1h",
        htf_bias: Optional[str] = None,
    ) -> Dict:
        """
        Generate a signal using dual-scoring (bullish vs bearish confluences).

        Args:
            df: Candle data with ICT detection columns
            mss_type: Type of MSS detected ("BULLISH_MSS" / "BEARISH_MSS" / None)
            sweep_type: Type of sweep detected ("BULLISH" / "BEARISH" / None)
            news_sentiment: News sentiment score (-1 to 1)
            timeframe: Candle timeframe label
            htf_bias: Higher timeframe bias ("bullish"/"bearish"/"neutral")
        """
        current_candle = df.tail(1).to_dicts()[0]
        current_price = current_candle.get("close", 0)

        bullish_score = 0
        bearish_score = 0

        # 1. Bias / HTF Alignment
        if htf_bias is not None:
            bias = htf_bias
        else:
            bias = determine_bias_from_swings(df)

        if bias == "bullish":
            bullish_score += self.weights["bias"]
        elif bias == "bearish":
            bearish_score += self.weights["bias"]

        # 2. MSS — directional
        if mss_type == "BULLISH_MSS":
            bullish_score += self.weights["mss"]
        elif mss_type == "BEARISH_MSS":
            bearish_score += self.weights["mss"]

        # 3. Liquidity Sweep — directional
        if sweep_type == "BULLISH":
            bullish_score += self.weights["liquidity_sweep"]
        elif sweep_type == "BEARISH":
            bearish_score += self.weights["liquidity_sweep"]

        # 4. FVG — directional
        has_bullish_fvg = "fvg_type" in df.columns and (df["fvg_type"].tail(5) == "BULLISH").any()
        has_bearish_fvg = "fvg_type" in df.columns and (df["fvg_type"].tail(5) == "BEARISH").any()
        if has_bullish_fvg:
            bullish_score += self.weights["fvg"]
        if has_bearish_fvg:
            bearish_score += self.weights["fvg"]

        # 5. Order Block — directional
        has_bullish_ob = "ob_type" in df.columns and (df["ob_type"].tail(5) == "BULLISH").any()
        has_bearish_ob = "ob_type" in df.columns and (df["ob_type"].tail(5) == "BEARISH").any()
        if has_bullish_ob:
            bullish_score += self.weights["order_block"]
        if has_bearish_ob:
            bearish_score += self.weights["order_block"]

        # 6. News — directional
        if news_sentiment > 0.5:
            bullish_score += self.weights["news"]
        elif news_sentiment < -0.5:
            bearish_score += self.weights["news"]

        # 7. Premium/Discount Zone + OTE — aligned to trend bias
        if "zone" not in df.columns or "in_ote" not in df.columns:
            df = self.pd_detector.compute_zones(df)

        latest = df.tail(1).to_dicts()[0]
        in_discount = latest.get("in_discount", False)
        in_ote = latest.get("in_ote", False)

        # Discount zone favours bullish entry (buying undervalued)
        # Premium zone favours bearish entry (selling overvalued)
        if bias == "bullish" and in_discount:
            bullish_score += self.weights["discount_zone"]
        elif bias == "bearish" and not in_discount:
            bearish_score += self.weights["discount_zone"]
        else:
            # Without a clear bias, being in discount is slightly bullish
            if in_discount:
                bullish_score += self.weights["discount_zone"] // 2
            else:
                bearish_score += self.weights["discount_zone"] // 2

        # OTE is neutral — it's a good entry zone for either direction
        if in_ote:
            # Split OTE points based on bias, or evenly if no bias
            if bias == "bullish":
                bullish_score += self.weights["ote"]
            elif bias == "bearish":
                bearish_score += self.weights["ote"]
            else:
                bullish_score += self.weights["ote"] // 2
                bearish_score += self.weights["ote"] // 2

        # 8. Session / Kill Zone — bonus to the dominant bias direction
        in_kill_zone = False
        active_kill_zones: List[str] = []
        active_sessions: List[str] = []
        if "timestamp" in current_candle:
            ts = current_candle["timestamp"]
            session_info = self.session_detector.get_current_session_info(ts)
            score_bonus = session_info.get("score_bonus", 0)
            in_kill_zone = session_info.get("in_kill_zone", False)
            active_kill_zones = session_info.get("active_kill_zones", [])
            active_sessions = session_info.get("active_sessions", [])

            # Allocate session bonus proportionally to the current direction
            # If bias is bullish, session bonus goes to bullish side
            if bias == "bullish":
                bullish_score += score_bonus
            elif bias == "bearish":
                bearish_score += score_bonus
            else:
                # Neutral bias — split session bonus evenly
                bullish_score += score_bonus // 2
                bearish_score += score_bonus // 2

        # Cap individual scores at 100
        bullish_score = min(bullish_score, 100)
        bearish_score = min(bearish_score, 100)

        # Net score determines direction: bullish - bearish
        net_score = bullish_score - bearish_score
        # Overall confidence = the stronger side's score
        confidence_strength = max(bullish_score, bearish_score)

        # Determine signal type from net score
        if net_score >= 60:
            signal_type = "STRONG_BUY"
        elif net_score >= 30:
            signal_type = "BUY"
        elif net_score > -30:
            signal_type = "NEUTRAL"
        elif net_score > -60:
            signal_type = "SELL"
        else:
            signal_type = "STRONG_SELL"

        # HTF alignment check
        htf_aligned = True
        if htf_bias is not None and htf_bias != "neutral":
            if htf_bias == "bullish" and "SELL" in signal_type:
                htf_aligned = False
            elif htf_bias == "bearish" and "BUY" in signal_type:
                htf_aligned = False

        return {
            "score": confidence_strength,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "net_score": net_score,
            "signal_type": signal_type,
            "timestamp": current_candle.get("timestamp"),
            "price": current_price,
            "timeframe": timeframe,
            "bias": bias,
            "htf_bias": htf_bias if htf_bias is not None else bias,
            "htf_aligned": htf_aligned,
            "in_kill_zone": in_kill_zone,
            "details": {
                "mss": mss_type is not None,
                "mss_type": mss_type,
                "sweep": sweep_type is not None,
                "sweep_type": sweep_type,
                "bullish_fvg": has_bullish_fvg,
                "bearish_fvg": has_bearish_fvg,
                "bullish_ob": has_bullish_ob,
                "bearish_ob": has_bearish_ob,
                "news_sentiment": news_sentiment,
                "discount": in_discount,
                "ote": in_ote,
                "bias": bias,
                "htf_bias": htf_bias if htf_bias is not None else bias,
                "htf_aligned": htf_aligned,
                "in_kill_zone": in_kill_zone,
                "active_sessions": active_sessions,
                "active_kill_zones": active_kill_zones,
            },
        }
