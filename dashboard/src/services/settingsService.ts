import { useState, useCallback, useEffect } from 'react';

// ── Types ────────────────────────────────────────────────────────────────

export interface SignalWeights {
  bias: number;
  mss: number;
  liquidity_sweep: number;
  order_block: number;
  fvg: number;
  news: number;
}

export interface RiskSettings {
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_weekly_loss_pct: number;
  max_open_positions: number;
}

export interface AppSettings {
  signalWeights: SignalWeights;
  risk: RiskSettings;
}

export interface SettingsService {
  settings: AppSettings;
  updateSignalWeight: (key: keyof SignalWeights, value: number) => void;
  updateRiskSetting: (key: keyof RiskSettings, value: number) => void;
  resetToDefaults: () => void;
}

const STORAGE_KEY = 'ict-trading-settings';

// ── Defaults (mirrors signal_engine/engine.py and risk/manager.py) ─────

const DEFAULT_SETTINGS: AppSettings = {
  signalWeights: {
    bias: 20,
    mss: 20,
    liquidity_sweep: 20,
    order_block: 15,
    fvg: 15,
    news: 10,
  },
  risk: {
    max_risk_per_trade_pct: 1.0,
    max_daily_loss_pct: 3.0,
    max_weekly_loss_pct: 6.0,
    max_open_positions: 3,
  },
};

// ── Persistence helpers ─────────────────────────────────────────────────

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS, signalWeights: { ...DEFAULT_SETTINGS.signalWeights }, risk: { ...DEFAULT_SETTINGS.risk } };
    const parsed = JSON.parse(raw);
    // Merge with defaults to handle new keys that may not exist in old saves
    return {
      signalWeights: { ...DEFAULT_SETTINGS.signalWeights, ...parsed.signalWeights },
      risk: { ...DEFAULT_SETTINGS.risk, ...parsed.risk },
    };
  } catch {
    return { ...DEFAULT_SETTINGS, signalWeights: { ...DEFAULT_SETTINGS.signalWeights }, risk: { ...DEFAULT_SETTINGS.risk } };
  }
}

function saveSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable or full — silently ignore
  }
}

// ── React hook ──────────────────────────────────────────────────────────

export function useSettings(): SettingsService {
  const [settings, setSettings] = useState<AppSettings>(loadSettings);

  // Persist on every change
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const updateSignalWeight = useCallback((key: keyof SignalWeights, value: number) => {
    setSettings(prev => ({
      ...prev,
      signalWeights: { ...prev.signalWeights, [key]: Math.max(0, Math.min(100, value)) },
    }));
  }, []);

  const updateRiskSetting = useCallback((key: keyof RiskSettings, value: number) => {
    setSettings(prev => ({
      ...prev,
      risk: { ...prev.risk, [key]: Math.max(0, value) },
    }));
  }, []);

  const resetToDefaults = useCallback(() => {
    setSettings({
      signalWeights: { ...DEFAULT_SETTINGS.signalWeights },
      risk: { ...DEFAULT_SETTINGS.risk },
    });
  }, []);

  return { settings, updateSignalWeight, updateRiskSetting, resetToDefaults };
}

// ── Direct access (for non-React contexts) ─────────────────────────────

export function getSettings(): AppSettings {
  return loadSettings();
}

export { DEFAULT_SETTINGS };
