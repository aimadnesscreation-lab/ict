import type { PriceTick } from '../hooks/usePriceStream';
import type { SignalWeights } from '../services/settingsService';

// ── Types ──────────────────────────────────────────────────────────────

export interface SignalFlags {
  bias: 'bullish' | 'bearish' | 'neutral';
  sweep: boolean;
  fvg: boolean;
}

export interface ComputedSignal {
  symbol: string;
  price: number;
  change_24h: number;
  score: number;
  signalType: 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL';
  flags: SignalFlags;
}

// ── Heuristic detection from price data ───────────────────────────────
// These mimic the ICT detection logic without requiring full on-chain data.

export function deriveFlags(tick: PriceTick): SignalFlags {
  const change = tick.change_24h;
  const range = tick.high_24h - tick.low_24h || 1;
  const posInRange = (tick.price - tick.low_24h) / range;

  // Bias: derived from 24h change direction (threshold 0.3% to avoid noise)
  const bias: SignalFlags['bias'] =
    change > 0.3 ? 'bullish' : change < -0.3 ? 'bearish' : 'neutral';

  // Liquidity Sweep: price near the 24h high or low extremes
  const sweep = posInRange < 0.08 || posInRange > 0.92;

  // FVG: rapid move of >0.8% implies an imbalance window
  const fvg = Math.abs(change) > 0.8;

  return { bias, sweep, fvg };
}

// ── Weighted scoring ──────────────────────────────────────────────────
// Mirrors signal_engine/engine.py generate_signal() logic.

const SCORE_THRESHOLDS = [
  { min: 80, type: 'STRONG_BUY' as const },
  { min: 60, type: 'BUY' as const },
  { min: 40, type: 'NEUTRAL' as const },
  { min: 20, type: 'SELL' as const },
  { min: 0, type: 'STRONG_SELL' as const },
];

function categorizeScore(score: number): ComputedSignal['signalType'] {
  for (const t of SCORE_THRESHOLDS) {
    if (score >= t.min) return t.type;
  }
  return 'STRONG_SELL';
}

export function computeSignal(
  tick: PriceTick,
  weights: SignalWeights,
): ComputedSignal {
  const flags = deriveFlags(tick);
  let score = 0;

  // Bias is directional — only add weight if direction matches
  if (flags.bias === 'bullish') {
    score += weights.bias;
  }

  if (flags.sweep) score += weights.liquidity_sweep;
  if (flags.fvg) score += weights.fvg;

  // Invert for bearish bias: score becomes "strength of bearish signal"
  if (flags.bias === 'bearish') {
    // A lower raw score → stronger sell
    // Keep a bearish score positive but the type will be SELL/STRONG_SELL
    score = Math.max(0, score - 20);
  }

  return {
    symbol: tick.symbol,
    price: tick.price,
    change_24h: tick.change_24h,
    score,
    signalType: categorizeScore(score),
    flags,
  };
}
