"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type PropStatus = {
  firm: string;
  daily_loss_limit: number;
  daily_loss_used: number;
  daily_loss_remaining: number;
  daily_loss_pct?: number;
  max_drawdown: number;
  drawdown_from_peak: number;
  drawdown_pct?: number;
  profit_target: number;
  cumulative_pnl: number;
  profit_progress_pct: number;
  allows_automation: boolean;
  trailing_drawdown: boolean;
  violations: string[];
  status: string;
};

function Arc({
  pct,
  color,
  label,
  value,
  max,
  size = 120,
}: {
  pct: number;
  color: string;
  label: string;
  value: number;
  max: number;
  size?: number;
}) {
  const r = size / 2 - 12;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = Math.PI * r; // half circle
  const fill = Math.min(1, pct / 100);
  const offset = circumference * (1 - fill);

  // Color transitions: green -> yellow -> red
  const gaugeColor = pct < 50 ? "#34d399" : pct < 80 ? "#fbbf24" : "#f43f5e";

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size / 2 + 8 }}>
        <svg width={size} height={size / 2 + 12} viewBox={`0 0 ${size} ${size / 2 + 12}`}>
          {/* Track */}
          <path
            d={`M 12 ${cy} A ${r} ${r} 0 0 1 ${size - 12} ${cy}`}
            fill="none"
            stroke="#1e293b"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Fill */}
          <path
            d={`M 12 ${cy} A ${r} ${r} 0 0 1 ${size - 12} ${cy}`}
            fill="none"
            stroke={gaugeColor}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${circumference}`}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.3s" }}
          />
          {/* Center value */}
          <text x={cx} y={cy - 4} textAnchor="middle" fill="white" fontSize="14" fontWeight="bold">
            {pct.toFixed(0)}%
          </text>
          <text x={cx} y={cy + 10} textAnchor="middle" fill="#64748b" fontSize="8">
            ${value.toFixed(0)} / ${max.toLocaleString()}
          </text>
        </svg>
      </div>
      <p className="text-[10px] text-slate-500 text-center mt-1">{label}</p>
    </div>
  );
}

export default function RiskGauge() {
  const [status, setStatus] = useState<PropStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/prop-firm/status`, { cache: "no-store" });
        if (res.ok) setStatus(await res.json());
      } catch (_) {}
      setLoading(false);
    }
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  if (loading) {
    return (
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4 flex items-center justify-center h-48 text-slate-600 text-sm">
        Loading...
      </div>
    );
  }

  if (!status) {
    return (
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4 flex items-center justify-center h-48 text-slate-600 text-sm">
        Risk data unavailable
      </div>
    );
  }

  const lossUsedPct = status.daily_loss_limit > 0
    ? (status.daily_loss_used / status.daily_loss_limit) * 100
    : 0;

  const drawdownPct = status.max_drawdown > 0
    ? (status.drawdown_from_peak / status.max_drawdown) * 100
    : 0;

  const statusColor =
    status.violations.length > 0
      ? "text-rose-400"
      : status.status === "PASSED"
      ? "text-emerald-400"
      : "text-slate-400";

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Risk Gauge</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">{status.firm}</p>
        </div>
        <div className="flex items-center gap-2">
          {status.trailing_drawdown && (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-900/40 text-amber-400 border border-amber-700/40">
              TRAILING DD
            </span>
          )}
          <span className={["text-xs font-semibold", statusColor].join(" ")}>
            {status.status}
          </span>
        </div>
      </div>

      {status.violations.length > 0 && (
        <div className="mb-4 p-2 rounded-lg bg-rose-900/20 border border-rose-700/40">
          {status.violations.map((v) => (
            <p key={v} className="text-xs text-rose-400">
              VIOLATION: {v.replace(/_/g, " ").toUpperCase()}
            </p>
          ))}
        </div>
      )}

      <div className="flex justify-around flex-wrap gap-4">
        <Arc
          pct={lossUsedPct}
          color="#f43f5e"
          label="Daily Loss Used"
          value={status.daily_loss_used}
          max={status.daily_loss_limit}
        />
        <Arc
          pct={drawdownPct}
          color="#fbbf24"
          label="Max Drawdown Used"
          value={status.drawdown_from_peak}
          max={status.max_drawdown}
        />
        <Arc
          pct={status.profit_progress_pct}
          color="#34d399"
          label="Profit Target Progress"
          value={status.cumulative_pnl}
          max={status.profit_target}
        />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-[10px]">
        <div className="bg-slate-800/50 rounded p-2">
          <p className="text-slate-500">Daily Loss Remaining</p>
          <p className="text-emerald-400 font-mono">${status.daily_loss_remaining.toFixed(2)}</p>
        </div>
        <div className="bg-slate-800/50 rounded p-2">
          <p className="text-slate-500">Allows Automation</p>
          <p className={status.allows_automation ? "text-emerald-400" : "text-rose-400"}>
            {status.allows_automation ? "YES" : "NO — Manual only"}
          </p>
        </div>
      </div>
    </div>
  );
}
