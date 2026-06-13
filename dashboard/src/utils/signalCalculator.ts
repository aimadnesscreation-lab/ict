import type { PriceTick } from '../hooks/usePriceStream';
import type { SignalWeights } from '../services/settingsService';

// ── Types ──────────────────────────────────────────────────────────────

export interface SignalFlags {
  bias: 'bullish' | 'bearish' | 'neutral';
  mss: boolean;
  sweep: boolean;
  fvg: boolean;
  ob: boolean;
  news_sentiment: number;
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

  // MSS: significant directional impulse (>1.2% change signals structure shift)
  const mss = Math.abs(change) > 1.2;

  // Liquidity Sweep: price near the 24h high or low extremes
  const sweep = posInRange < 0.08 || posInRange > 0.92;

  // FVG: rapid move of >0.8% implies an imbalance window
  const fvg = Math.abs(change) > 0.8;

  // Order Block: price hovering near the middle of range (institutional zone)
  const ob = posInRange > 0.35 && posInRange < 0.65;

  // News sentiment: deterministic from price data (no randomness)
  // Uses volatility magnitude and position-in-range as a stable seed
  const volatility = Math.min(Math.abs(change) / 5, 1);
  const direction = change >= 0 ? 1 : -1;
  // posInRange gives a deterministic 0-1 value, use it to add subtle nuance
  const nuance = (posInRange * 2 - 1) * 0.1; // -0.1 to 0.1
  const news_sentiment = Math.round(
    Math.max(-1, Math.min(1, direction * (0.2 + volatility * 0.6) + nuance)) * 100,
  ) / 100;

  return { bias, mss, sweep, fvg, ob, news_sentiment };
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
  // (the engine treats bias as bullish → add, bearish → 0)
  if (flags.bias === 'bullish') {
    score += weights.bias;
  }

  if (flags.mss) score += weights.mss;
  if (flags.sweep) score += weights.liquidity_sweep;
  if (flags.fvg) score += weights.fvg;
  if (flags.ob) score += weights.order_block;
  if (flags.news_sentiment > 0.5) score += weights.news;

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
