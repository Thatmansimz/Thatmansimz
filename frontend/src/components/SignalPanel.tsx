"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Signal = {
  id: number;
  symbol: string;
  direction: string;
  confidence: number;
  long_probability: number;
  short_probability: number;
  entry_price: number;
  entry_zone_low: number;
  entry_zone_high: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  risk_reward_ratio: number;
  risk_amount: number;
  timeframe: string;
  strategy: string;
  status: string;
  outcome: string | null;
  created_at: string;
  expires_at: string | null;
  indicators: {
    rsi?: number;
    macd_hist?: number;
    adx?: number;
    bb_pct?: number;
    rel_volume?: number;
    stoch_k?: number;
    atr?: number;
  };
};

function cn(...c: (string | boolean | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

function ConfBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? "#00ff88" : pct >= 65 ? "#ffaa00" : "#ff3366";
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
        <span>{label}</span>
        <span style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div style={{ width: `${pct}%`, background: color }} className="h-full rounded-full transition-all duration-500" />
      </div>
    </div>
  );
}

function IndicatorBadge({ label, value, good }: { label: string; value: number; good: boolean }) {
  return (
    <div className={cn("px-2 py-1 rounded text-[10px]", good ? "bg-emerald-900/30 text-emerald-400" : "bg-slate-800 text-slate-400")}>
      <span className="text-slate-500">{label}: </span>
      <span className="font-mono">{value?.toFixed(1)}</span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome || outcome === "pending") return null;
  const map: Record<string, string> = {
    win: "bg-emerald-900/50 text-emerald-400",
    loss: "bg-rose-900/50 text-rose-400",
    breakeven: "bg-slate-800 text-slate-400",
  };
  return (
    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", map[outcome] || "bg-slate-800 text-slate-400")}>
      {outcome.toUpperCase()}
    </span>
  );
}

function timeAgo(isoStr: string): string {
  if (!isoStr) return "";
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function SignalPanel() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<Record<string, boolean>>({});

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/signals?limit=15`, { cache: "no-store" });
        if (res.ok) setSignals(await res.json());
      } catch (_) {}
      setLoading(false);
    }
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, []);

  async function generateNow(symbol: string) {
    setGenerating((g) => ({ ...g, [symbol]: true }));
    try {
      await fetch(`${API}/api/signals/generate?symbol=${symbol}`, { method: "POST" });
      const res = await fetch(`${API}/api/signals?limit=15`, { cache: "no-store" });
      if (res.ok) setSignals(await res.json());
    } catch (_) {}
    setGenerating((g) => ({ ...g, [symbol]: false }));
  }

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-white">AI Signal Panel</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">Last {signals.length} signals from ML ensemble</p>
        </div>
        <div className="flex gap-2">
          {["MES", "MNQ"].map((sym) => (
            <button
              key={sym}
              onClick={() => generateNow(sym)}
              disabled={generating[sym]}
              className="px-2.5 py-1 rounded text-xs bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-700 transition disabled:opacity-50"
            >
              {generating[sym] ? "..." : `Scan ${sym}`}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-600 text-sm">Loading signals...</div>
      ) : signals.length === 0 ? (
        <div className="text-center py-8 text-slate-600 text-sm">
          No signals yet. Click Scan to generate one manually.
        </div>
      ) : (
        <div className="space-y-3 overflow-y-auto max-h-[600px] pr-1">
          {signals.map((sig) => (
            <div
              key={sig.id}
              className={cn(
                "rounded-xl border p-3 transition",
                sig.direction === "long"
                  ? "border-emerald-800/40 bg-emerald-900/10"
                  : "border-rose-800/40 bg-rose-900/10"
              )}
            >
              {/* Header row */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded font-bold text-xs",
                      sig.direction === "long"
                        ? "bg-emerald-900/60 text-emerald-400"
                        : "bg-rose-900/60 text-rose-400"
                    )}
                  >
                    {sig.direction.toUpperCase()}
                  </span>
                  <span className="text-sm font-semibold text-white">{sig.symbol}</span>
                  <span className="text-[10px] text-slate-500 uppercase">{sig.timeframe}</span>
                </div>
                <div className="flex items-center gap-2">
                  <OutcomeBadge outcome={sig.outcome} />
                  <span className="text-[10px] text-slate-600">{timeAgo(sig.created_at)}</span>
                </div>
              </div>

              {/* Confidence bars */}
              <div className="space-y-1 mb-3">
                <ConfBar value={sig.confidence} label="Overall confidence" />
                <div className="grid grid-cols-2 gap-2">
                  <ConfBar value={sig.long_probability || 0} label="Long prob." />
                  <ConfBar value={sig.short_probability || 0} label="Short prob." />
                </div>
              </div>

              {/* Price levels */}
              <div className="grid grid-cols-3 gap-2 text-[10px] mb-2">
                <div className="bg-slate-800/50 rounded p-1.5">
                  <p className="text-slate-500">Entry</p>
                  <p className="font-mono text-white">{sig.entry_price?.toFixed(2)}</p>
                  <p className="text-slate-600 text-[9px]">
                    {sig.entry_zone_low?.toFixed(2)} – {sig.entry_zone_high?.toFixed(2)}
                  </p>
                </div>
                <div className="bg-rose-900/20 rounded p-1.5">
                  <p className="text-rose-400/70">Stop Loss</p>
                  <p className="font-mono text-rose-400">{sig.stop_loss?.toFixed(2)}</p>
                  <p className="text-slate-600 text-[9px]">Risk ${sig.risk_amount?.toFixed(0)}</p>
                </div>
                <div className="bg-emerald-900/20 rounded p-1.5">
                  <p className="text-emerald-400/70">Target</p>
                  <p className="font-mono text-emerald-400">{sig.target_1?.toFixed(2)}</p>
                  <p className="text-slate-600 text-[9px]">
                    T2: {sig.target_2?.toFixed(2)} | R:R {sig.risk_reward_ratio?.toFixed(1)}
                  </p>
                </div>
              </div>

              {/* Indicator badges */}
              <div className="flex flex-wrap gap-1">
                <IndicatorBadge label="RSI" value={sig.indicators?.rsi || 0} good={(sig.indicators?.rsi || 50) < 70 && (sig.indicators?.rsi || 50) > 30} />
                <IndicatorBadge label="ADX" value={sig.indicators?.adx || 0} good={(sig.indicators?.adx || 0) > 20} />
                <IndicatorBadge label="Vol" value={sig.indicators?.rel_volume || 0} good={(sig.indicators?.rel_volume || 0) > 1.2} />
                <IndicatorBadge label="Stoch" value={sig.indicators?.stoch_k || 0} good={(sig.indicators?.stoch_k || 50) < 80} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
