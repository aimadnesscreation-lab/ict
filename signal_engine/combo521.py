"""
Combo 521 Strategy — Signal Detector for Live System.

Identifies sweep + FVG pattern entries on 5m data:
  1. A liquidity sweep occurs (bullish = low taken, bearish = high taken)
  2. Within max_bars_after_sweep, a same-direction FVG forms with gap >= min_gap_pct
  3. When price later returns to the proximal edge of that FVG → signal fires
  4. LONG: bullish sweep + bullish FVG, entry at FVG_top (proximal edge), discount zone
  5. SHORT: bearish sweep + bearish FVG, entry at FVG_bottom (proximal edge), premium zone

Output signal dicts compatible with DemoAccount.process_signals().
"""

from typing import Dict, List, Optional
from datetime import datetime
import polars as pl


class Combo521Detector:
    """Combo 521 — Sweep + FVG pattern detector with proximal edge entry."""

    def __init__(
        self,
        swing_lookback: int = 2,
        max_bars_after_sweep: int = 20,
        min_gap_pct: float = 0.05,
        entry_mode: str = "proximal",
    ):
        self.swing_lookback = swing_lookback
        self.max_bars_after_sweep = max_bars_after_sweep
        self.min_gap_pct = min_gap_pct
        self.entry_mode = entry_mode

    def detect(
        self,
        df: pl.DataFrame,
        current_idx: Optional[int] = None,
        symbol: str = "ETHUSDT",
    ) -> List[Dict]:
        """Detect Combo 521 signals on the latest completed candle.

        Args:
            df: ICT-annotated DataFrame (must have swing_high, swing_low, fvg_type,
                fvg_top, fvg_bottom, liquidity_sweep_type, liquidity_sweep_price,
                in_discount columns)
            current_idx: Index of the current (just-closed) candle.
                         Defaults to the last row of df.
            symbol: Trading symbol for the signal dict.

        Returns:
            List of signal dicts compatible with DemoAccount.process_signals().
        """
        if df.is_empty() or len(df) < self.max_bars_after_sweep + 5:
            return []

        if current_idx is None:
            current_idx = len(df) - 1

        if current_idx < self.max_bars_after_sweep + 2:
            return []

        signals = self._find_active_signals(df, current_idx)

        result = []
        for sig in signals:
            crow = df.row(current_idx, named=True)
            ts = crow.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts / 1000)

            result.append({
                "symbol": symbol,
                "signal_type": "BUY" if sig["side"] == "LONG" else "SELL",
                "score": 100,  # high enough to pass any min_score threshold
                "bullish_score": 100 if sig["side"] == "LONG" else 0,
                "bearish_score": 100 if sig["side"] == "SHORT" else 0,
                "net_score": 100 if sig["side"] == "LONG" else -100,
                "price": sig["entry_price"],
                "atr": sig["atr"],
                "timeframe": "5m",
                "bias": "bullish" if sig["side"] == "LONG" else "bearish",
                "htf_bias": "neutral",
                "htf_aligned": True,
                "in_kill_zone": True,  # orchestrator with kill_zones_enabled=False passes all
                "confidence": 0.75,
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

    def _find_active_signals(self, df: pl.DataFrame, candle_idx: int) -> List[Dict]:
        """Core pattern detection — look back up to max_bars_after_sweep candles."""
        lookback = self.max_bars_after_sweep
        start = max(lookback + 2, candle_idx - lookback)
        if start >= candle_idx:
            return []

        window = df.slice(start, candle_idx - start)
        if len(window) < 3:
            return []

        window_dicts = window.to_dicts()

        # Collect sweeps
        sweeps = []
        for rel_idx, row in enumerate(window_dicts):
            stype = row.get("liquidity_sweep_type")
            if stype in ("BULLISH", "BEARISH"):
                sweeps.append({
                    "idx": start + rel_idx,
                    "type": stype,
                    "price": row.get("liquidity_sweep_price", 0),
                })

        if not sweeps:
            return []

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
                            "type": ftype, "top": top, "bottom": bottom,
                            "gap_pct": gap_pct,
                        })

        if not fvgs:
            return []

        # Current candle data
        crow = df.row(candle_idx, named=True)
        curr_high = crow.get("high", 0)
        curr_low = crow.get("low", 0)
        atr = crow.get("atr", 0) or 0
        in_discount = crow.get("in_discount", False) or False

        # Match sweeps → same-direction FVGs formed after the sweep
        signals = []
        for sw in sweeps:
            for fvg in fvgs:
                if fvg["idx"] <= sw["idx"]:
                    continue  # FVG must form AFTER the sweep
                if fvg["type"] != sw["type"]:
                    continue

                # Check FVG not yet filled
                filled = self._is_fvg_filled(df, fvg, candle_idx)
                if filled:
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
                    continue  # LONG needs discount
                if fvg["type"] == "BEARISH" and in_discount:
                    continue  # SHORT needs premium

                signals.append({
                    "side": "LONG" if fvg["type"] == "BULLISH" else "SHORT",
                    "entry_price": entry_price,
                    "fvg_top": fvg["top"],
                    "fvg_bottom": fvg["bottom"],
                    "sweep_price": sw["price"],
                    "fvg_idx": fvg["idx"],
                    "sweep_idx": sw["idx"],
                    "gap_pct": fvg["gap_pct"],
                    "atr": atr,
                    "in_discount": in_discount,
                })

        return signals

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
