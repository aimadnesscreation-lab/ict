"""
Combo 521 MTF — Multi-Timeframe Sweep + FVG Detector for Live System.

Detects liquidity sweeps on the 1H timeframe, then looks for same-direction
5m FVGs to enter. This produces fewer, higher-confluence signals compared
to the 5m-only Combo 521.

Signal logic:
  1. A liquidity sweep occurs on the 1H timeframe (bullish = low taken/reclaimed,
     bearish = high taken/reclaimed)
  2. Within the last max_5m_bars_after_sweep 5m candles (~4h), a same-direction
     FVG forms with gap >= min_gap_pct
  3. When 5m price returns to the proximal edge of that FVG → signal fires
  4. LONG: 1H bullish sweep + 5m bullish FVG, entry at FVG_top (proximal), discount
  5. SHORT: 1H bearish sweep + 5m bearish FVG, entry at FVG_bottom (proximal), premium

The detector does NOT try to map exact 1H → 5m indices. Instead it:
  - Checks if a 1H sweep occurred in the last N 1H candles
  - Then within the last M 5m candles, looks for FVGs matching the sweep direction
  - This is simpler and avoids index-mapping edge cases
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
import polars as pl


class Combo521MTFDetector:
    """Multi-timeframe Combo 521 — 1H sweeps + 5m FVGs."""

    def __init__(
        self,
        max_1h_bars_after_sweep: int = 12,   # 12 1H bars = 12 hours of sweep relevance
        max_5m_bars_after_sweep: int = 48,    # 48 5m bars = 4 hours to look for FVGs
        min_gap_pct: float = 0.05,
    ):
        self.max_1h_bars_after_sweep = max_1h_bars_after_sweep
        self.max_5m_bars_after_sweep = max_5m_bars_after_sweep
        self.min_gap_pct = min_gap_pct

    def detect(
        self,
        df_5m: pl.DataFrame,
        df_1h: pl.DataFrame,
        current_idx_5m: Optional[int] = None,
        symbol: str = "ETHUSDT",
    ) -> List[Dict]:
        """Detect MTF Combo 521 signals.

        Args:
            df_5m: ICT-annotated 5m DataFrame (must have fvg_type, fvg_top,
                   fvg_bottom, atr, in_discount).
            df_1h: ICT-annotated 1H DataFrame (must have liquidity_sweep_type,
                   liquidity_sweep_price).
            current_idx_5m: Index of the current (just-closed) 5m candle.
                            Defaults to the last row of df_5m.
            symbol: Trading symbol for the signal dict.

        Returns:
            List of signal dicts compatible with DemoAccount.process_signals().
        """
        if df_5m.is_empty() or len(df_5m) < 50 or df_1h.is_empty() or len(df_1h) < 20:
            return []

        if current_idx_5m is None:
            current_idx_5m = len(df_5m) - 1

        if current_idx_5m < 50:
            return []

        # ── Step 1: Check which sweep directions occurred on 1H recently ──
        bullish_sweep_on_1h = False
        bearish_sweep_on_1h = False

        lookback_1h_start = max(0, len(df_1h) - self.max_1h_bars_after_sweep - 2)
        for idx in range(lookback_1h_start, len(df_1h)):
            row = df_1h.row(idx, named=True)
            stype = row.get("liquidity_sweep_type")
            if stype == "BULLISH":
                bullish_sweep_on_1h = True
            elif stype == "BEARISH":
                bearish_sweep_on_1h = True
            if bullish_sweep_on_1h and bearish_sweep_on_1h:
                break  # both directions found, no need to scan more

        if not bullish_sweep_on_1h and not bearish_sweep_on_1h:
            return []  # No 1H sweeps → no MTF signals

        # ── Step 2: Look for 5m FVGs in the lookback window ──────────────
        # We look at the last max_5m_bars_after_sweep 5m candles (up to ~4h
        # of 5m data) for FVGs matching the sweep direction(s)
        start = max(0, current_idx_5m - self.max_5m_bars_after_sweep)
        if start >= current_idx_5m:
            return []

        window = df_5m.slice(start, current_idx_5m - start)
        if len(window) < 3:
            return []

        window_dicts = window.to_dicts()

        # Collect FVGs with gap >= min_gap_pct
        fvgs = []
        for rel_idx, row in enumerate(window_dicts):
            ftype = row.get("fvg_type")
            if ftype in ("BULLISH", "BEARISH"):
                top = row.get("fvg_top", 0) or 0
                bottom = row.get("fvg_bottom", 0) or 0
                if top > 0 and bottom > 0:
                    gap_pct = (top - bottom) / bottom * 100
                    if gap_pct >= self.min_gap_pct:
                        fvgs.append({
                            "idx": start + rel_idx,
                            "type": ftype,
                            "top": top,
                            "bottom": bottom,
                            "gap_pct": gap_pct,
                        })

        if not fvgs:
            return []

        # Current candle data
        crow = df_5m.row(current_idx_5m, named=True)
        curr_high = crow.get("high", 0)
        curr_low = crow.get("low", 0)
        atr = crow.get("atr", 0) or 0
        in_discount = crow.get("in_discount", False) or False

        # ── Step 3: Match FVGs with 1H sweep direction ──────────────────
        signals = []
        for fvg in fvgs:
            # Direction must match a 1H sweep
            if fvg["type"] == "BULLISH" and not bullish_sweep_on_1h:
                continue
            if fvg["type"] == "BEARISH" and not bearish_sweep_on_1h:
                continue

            # Check FVG not yet filled
            if self._is_fvg_filled(df_5m, fvg, current_idx_5m):
                continue

            # Check price at proximal edge
            if fvg["type"] == "BULLISH":
                prox = fvg["top"]
                if not (curr_low <= prox * 1.001 and curr_high >= prox * 0.999):
                    continue
                entry_price = prox
            else:
                prox = fvg["bottom"]
                if not (curr_low <= prox * 1.001 and curr_high >= prox * 0.999):
                    continue
                entry_price = prox

            # Premium/discount zone filter
            if fvg["type"] == "BULLISH" and not in_discount:
                continue
            if fvg["type"] == "BEARISH" and in_discount:
                continue

            signals.append({
                "side": "LONG" if fvg["type"] == "BULLISH" else "SHORT",
                "entry_price": entry_price,
                "fvg_top": fvg["top"],
                "fvg_bottom": fvg["bottom"],
                "sweep_price": 0.0,  # No single sweep price in MTF mode
                "fvg_idx": fvg["idx"],
                "sweep_idx": 0,
                "gap_pct": fvg["gap_pct"],
                "atr": atr,
                "in_discount": in_discount,
            })

        if not signals:
            return []

        # ── Build output ──────────────────────────────────────────────
        result = []
        for sig in signals[:1]:  # max 1 signal per cycle
            ts = crow.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts / 1000)

            result.append({
                "symbol": symbol,
                "signal_type": "BUY" if sig["side"] == "LONG" else "SELL",
                "score": 100,
                "bullish_score": 100 if sig["side"] == "LONG" else 0,
                "bearish_score": 100 if sig["side"] == "SHORT" else 0,
                "net_score": 100 if sig["side"] == "LONG" else -100,
                "price": sig["entry_price"],
                "atr": sig["atr"],
                "timeframe": "5m",
                "bias": "bullish" if sig["side"] == "LONG" else "bearish",
                "htf_bias": "neutral",
                "htf_aligned": True,
                "in_kill_zone": True,
                "confidence": 0.80,
                "timestamp": ts,
                "details": {
                    "sweep": True,
                    "sweep_type": "BULLISH" if sig["side"] == "LONG" else "BEARISH",
                    "bullish_fvg": sig["side"] == "LONG",
                    "bearish_fvg": sig["side"] == "SHORT",
                    "fvg": True,
                    "ob": False,
                    "mss": False,
                    "discount": sig["in_discount"],
                    "ote": False,
                    "bias": "bullish" if sig["side"] == "LONG" else "bearish",
                    "htf_bias": "neutral",
                    "htf_aligned": True,
                    "in_kill_zone": True,
                    "active_sessions": [],
                    "active_kill_zones": [],
                    "mtf_sweep": True,
                    "mtf_timeframe": "1H",
                },
                "trigger_price": sig["entry_price"],
                "fvg_top": sig["fvg_top"],
                "fvg_bottom": sig["fvg_bottom"],
                "sweep_price": sig["sweep_price"],
                "gap_pct": sig["gap_pct"],
                "fvg_idx": sig["fvg_idx"],
                "sweep_idx": sig["sweep_idx"],
            })

        return result

    @staticmethod
    def _is_fvg_filled(df: pl.DataFrame, fvg: Dict, candle_idx: int) -> bool:
        """Check if an FVG has been fully filled (price passed through)."""
        start = fvg["idx"]
        length = candle_idx - start + 1
        if length < 1:
            return False
        seg = df.slice(start, length)
        if fvg["type"] == "BULLISH":
            return seg["low"].min() <= fvg["bottom"]
        else:
            return seg["high"].max() >= fvg["top"]
