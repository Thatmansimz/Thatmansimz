"use client";
import { useEffect, useState, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { Speedometer } from "../components/Speedometer";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function api(path: string) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`API ${path} failed`);
  return res.json();
}

type Status = {
  trading_enabled: boolean;
  market_open: boolean;
  scheduler_running: boolean;
  broker: string;
  prop_firm: string;
  daily_target: number;
  max_stop_dollars: number;
  ai_threshold: number;
};

type Stats = {
  pnl: number;
  trades_count: number;
  wins: number;
  losses: number;
  win_rate: number;
};

type Trade = {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  stop_loss: number;
  take_profit: number;
  status: string;
  pnl: number;
  net_pnl: number;
  ai_confidence: number;
  entry_time: string;
  exit_reason: string;
};

type Signal = {
  id: number;
  symbol: string;
  direction: string;
  confidence: number;
  entry_price: number;
  stop_loss: number;
  target_1: number;
  risk_reward_ratio: number;
  risk_amount: number;
  status: string;
  created_at: string;
  indicators: Record<string, number>;
};

type PropStatus = {
  firm: string;
  daily_loss_limit: number;
  daily_loss_used: number;
  daily_loss_remaining: number;
  max_drawdown_limit: number;
  max_drawdown_used: number;
  profit_target: number;
  cumulative_profit: number;
  profit_progress_pct: number;
  allows_automation: boolean;
  evaluation_passed: boolean;
  evaluation_failed: boolean;
};

type Perf = {
  total_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  total_pnl: number;
};

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

function PnlBadge({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span className={cn("font-bold", positive ? "text-emerald-400" : "text-rose-400")}>
      {positive ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? "#00ff88" : pct >= 65 ? "#ffaa00" : "#ff3366";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div style={{ width: `${pct}%`, background: color }} className="h-full rounded-full transition-all" />
      </div>
      <span className="text-xs font-mono w-8 text-right" style={{ color }}>{pct}%</span>
    </div>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        "inline-block w-2.5 h-2.5 rounded-full",
        active ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-slate-600"
      )}
    />
  );
}

export default function Dashboard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [todayStats, setTodayStats] = useState<Stats | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [propStatus, setPropStatus] = useState<PropStatus | null>(null);
  const [perf, setPerf] = useState<Perf | null>(null);
  const [dailyHistory, setDailyHistory] = useState<{ date: string; pnl: number }[]>([]);
  const [trading, setTrading] = useState(false);
  const [closing, setClosing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, t, tr, sg, ps, pf, dh] = await Promise.allSettled([
        api("/api/status"),
        api("/api/stats/today"),
        api("/api/trades/today"),
        api("/api/signals?limit=10"),
        api("/api/prop-firm/status"),
        api("/api/stats/performance"),
        api("/api/stats/daily"),
      ]);
      if (s.status === "fulfilled") setStatus(s.value);
      if (t.status === "fulfilled") setTodayStats(t.value);
      if (tr.status === "fulfilled") setTrades(tr.value);
      if (sg.status === "fulfilled") setSignals(sg.value);
      if (ps.status === "fulfilled") setPropStatus(ps.value);
      if (pf.status === "fulfilled") setPerf(pf.value);
      if (dh.status === "fulfilled") setDailyHistory(dh.value.slice(0, 20).reverse());
    } catch (_) {}
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [load]);

  async function toggleTrading() {
    setTrading(true);
    try {
      const endpoint = status?.trading_enabled ? "/api/trading/stop" : "/api/trading/start";
      await fetch(`${API}${endpoint}`, { method: "POST" });
      await load();
    } finally {
      setTrading(false);
    }
  }

  async function closeAll() {
    if (!confirm("Close ALL open positions immediately?")) return;
    setClosing(true);
    try {
      await fetch(`${API}/api/trading/close-all`, { method: "POST" });
      await load();
    } finally {
      setClosing(false);
    }
  }

  const dailyPnl = todayStats?.pnl ?? 0;
  const targetPct = status ? Math.min(100, (dailyPnl / status.daily_target) * 100) : 0;
  const openTrades = trades.filter((t) => t.status === "open");

  return (
    <div className="min-h-screen p-4 md:p-6 space-y-5 max-w-screen-2xl mx-auto">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">
            AI Trading Platform
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {status?.broker?.toUpperCase()} &nbsp;•&nbsp; {status?.prop_firm?.toUpperCase() || "NO PROP FIRM"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-sm">
            <StatusDot active={!!status?.market_open} />
            <span className="text-slate-400">{status?.market_open ? "Market Open" : "Market Closed"}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <StatusDot active={!!status?.scheduler_running} />
            <span className="text-slate-400">AI {status?.scheduler_running ? "Active" : "Idle"}</span>
          </div>
          <button
            onClick={closeAll}
            disabled={closing}
            className="px-3 py-1.5 rounded-lg bg-rose-900/60 border border-rose-700 text-rose-300 text-xs font-medium hover:bg-rose-800 transition disabled:opacity-50"
          >
            {closing ? "Closing..." : "Emergency Stop"}
          </button>
          <button
            onClick={toggleTrading}
            disabled={trading}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-semibold transition disabled:opacity-50",
              status?.trading_enabled
                ? "bg-slate-700 border border-slate-600 text-slate-300 hover:bg-slate-600"
                : "bg-emerald-700 border border-emerald-600 text-white hover:bg-emerald-600"
            )}
          >
            {trading ? "..." : status?.trading_enabled ? "Pause Trading" : "Start Trading"}
          </button>
        </div>
      </div>

      {/* ── Instrument Cluster ── */}
      <div
        className="rounded-2xl border border-slate-700/60 p-6"
        style={{
          background: "radial-gradient(ellipse at 50% 0%, #0f1e35 0%, #080e1a 70%)",
          boxShadow: "0 0 60px #0ea5e920, inset 0 1px 0 #334155",
        }}
      >
        {/* Cluster label strip */}
        <div className="flex items-center justify-between mb-4 px-2">
          <span
            className="text-[10px] font-bold tracking-[0.25em] uppercase"
            style={{ color: "#0ea5e9" }}
          >
            Instrument Cluster
          </span>
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            <span>{perf?.wins ?? 0}W / {perf?.losses ?? 0}L</span>
            <span>•</span>
            <span>PF {perf?.profit_factor?.toFixed(2) ?? "—"}</span>
            <span>•</span>
            <span>{openTrades.length} open positions</span>
          </div>
        </div>

        {/* Four gauges */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 place-items-center">
          {/* 1. Daily P&L */}
          <Speedometer
            value={Math.max(0, dailyPnl)}
            max={status?.daily_target ?? 1000}
            label="Daily P&L"
            sublabel={`${dailyPnl >= 0 ? "+" : ""}$${dailyPnl.toFixed(0)} today`}
            colorMode="profit"
            size={190}
            formatCenter={(v) => `$${v.toFixed(0)}`}
          />

          {/* 2. Win Rate */}
          <Speedometer
            value={perf?.win_rate ?? 0}
            max={100}
            label="Win Rate"
            sublabel={`avg win $${perf?.avg_win?.toFixed(0) ?? "0"}`}
            colorMode="confidence"
            unit="%"
            size={190}
            formatCenter={(v) => `${v.toFixed(1)}%`}
          />

          {/* 3. AI Confidence */}
          <Speedometer
            value={(status?.ai_threshold ?? 0.65) * 100}
            max={100}
            label="AI Threshold"
            sublabel={`stop ≤ $${status?.max_stop_dollars ?? 250}`}
            colorMode="confidence"
            unit="%"
            size={190}
            formatCenter={(v) => `${v.toFixed(0)}%`}
          />

          {/* 4. Risk Level */}
          <Speedometer
            value={
              propStatus && propStatus.daily_loss_limit > 0
                ? propStatus.daily_loss_used
                : Math.abs(Math.min(0, dailyPnl))
            }
            max={
              propStatus && propStatus.daily_loss_limit > 0
                ? propStatus.daily_loss_limit
                : status?.max_stop_dollars ?? 250
            }
            label="Risk Used"
            sublabel={
              propStatus && propStatus.daily_loss_limit > 0
                ? `$${propStatus.daily_loss_remaining.toFixed(0)} remaining`
                : "daily loss exposure"
            }
            colorMode="risk"
            size={190}
            formatCenter={(v) => `$${v.toFixed(0)}`}
          />
        </div>

        {/* Bottom stat strip */}
        <div className="mt-5 grid grid-cols-4 gap-2 text-center border-t border-slate-800 pt-4">
          {[
            { label: "Trades Today", value: todayStats?.trades_count ?? 0 },
            { label: "Total P&L",    value: `$${(perf?.total_pnl ?? 0).toFixed(0)}` },
            { label: "Avg Win",      value: `$${(perf?.avg_win ?? 0).toFixed(0)}` },
            { label: "Avg Loss",     value: `$${(perf?.avg_loss ?? 0).toFixed(0)}` },
          ].map((s) => (
            <div key={s.label}>
              <p className="text-[10px] text-slate-600 uppercase tracking-wider">{s.label}</p>
              <p className="text-sm font-bold text-white font-mono">{s.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Prop Firm Progress ── */}
      {propStatus && propStatus.firm !== "None" && (
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white">
              {propStatus.firm} — Evaluation Progress
            </h2>
            <div className="flex gap-2">
              {propStatus.allows_automation && (
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/50 text-emerald-400 border border-emerald-700/50">
                  AI ALLOWED
                </span>
              )}
              {propStatus.evaluation_passed && (
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/50 text-emerald-400 border border-emerald-700/50">
                  PASSED
                </span>
              )}
              {propStatus.evaluation_failed && (
                <span className="px-2 py-0.5 rounded text-[10px] bg-rose-900/50 text-rose-400 border border-rose-700/50">
                  FAILED
                </span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-[10px] text-slate-500 mb-1">Profit Target</p>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-1">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${propStatus.profit_progress_pct}%` }}
                />
              </div>
              <p className="text-xs text-slate-400">
                ${propStatus.cumulative_profit.toFixed(0)} / ${propStatus.profit_target.toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500 mb-1">Daily Loss Used</p>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-1">
                <div
                  className="h-full bg-rose-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, (propStatus.daily_loss_used / propStatus.daily_loss_limit) * 100)}%` }}
                />
              </div>
              <p className="text-xs text-slate-400">
                ${propStatus.daily_loss_used.toFixed(0)} / ${propStatus.daily_loss_limit.toLocaleString()} remaining: ${propStatus.daily_loss_remaining.toFixed(0)}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500 mb-1">Max Drawdown</p>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-1">
                <div
                  className="h-full bg-amber-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, (propStatus.max_drawdown_used / propStatus.max_drawdown_limit) * 100)}%` }}
                />
              </div>
              <p className="text-xs text-slate-400">
                ${propStatus.max_drawdown_used.toFixed(0)} / ${propStatus.max_drawdown_limit.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* ── P&L Chart ── */}
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-white mb-3">30-Day P&L History</h2>
          {dailyHistory.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={dailyHistory} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 9, fill: "#64748b" }} />
                <Tooltip
                  contentStyle={{ background: "#0f1629", border: "1px solid #334155", borderRadius: 8, fontSize: 11 }}
                  formatter={(v: number) => [`$${v.toFixed(2)}`, "P&L"]}
                />
                <ReferenceLine y={0} stroke="#334155" strokeDasharray="3 3" />
                <Line
                  type="monotone"
                  dataKey="pnl"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-44 flex items-center justify-center text-slate-600 text-sm">No history yet</div>
          )}
        </div>

        {/* ── AI Signals ── */}
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-white mb-3">Recent AI Signals</h2>
          {signals.length === 0 ? (
            <p className="text-slate-600 text-sm text-center py-8">No signals yet — market may be closed</p>
          ) : (
            <div className="space-y-2 overflow-y-auto max-h-52">
              {signals.map((sig) => (
                <div
                  key={sig.id}
                  className="flex items-center gap-3 p-2 rounded-lg bg-slate-800/60 border border-slate-700/30"
                >
                  <div
                    className={cn(
                      "w-12 text-center text-[10px] font-bold py-1 rounded",
                      sig.direction === "long" ? "bg-emerald-900/60 text-emerald-400" : "bg-rose-900/60 text-rose-400"
                    )}
                  >
                    {sig.direction.toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-white">{sig.symbol}</span>
                      <span className="text-[10px] text-slate-500">R:R {sig.risk_reward_ratio?.toFixed(1)}</span>
                    </div>
                    <ConfidenceBar value={sig.confidence} />
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] text-slate-500">@ {sig.entry_price?.toFixed(2)}</p>
                    <p className="text-[10px] text-rose-400">SL {sig.stop_loss?.toFixed(2)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Open Positions ── */}
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-3">
          Open Positions <span className="text-slate-500 font-normal">({openTrades.length})</span>
        </h2>
        {openTrades.length === 0 ? (
          <p className="text-slate-600 text-sm text-center py-6">No open positions</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2 pr-4">Symbol</th>
                  <th className="text-left py-2 pr-4">Side</th>
                  <th className="text-right py-2 pr-4">Qty</th>
                  <th className="text-right py-2 pr-4">Entry</th>
                  <th className="text-right py-2 pr-4">Stop</th>
                  <th className="text-right py-2 pr-4">Target</th>
                  <th className="text-right py-2 pr-4">P&L</th>
                  <th className="text-right py-2 pr-4">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {openTrades.map((t) => (
                  <tr key={t.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
                    <td className="py-2 pr-4 font-semibold text-white">{t.symbol}</td>
                    <td className={cn("py-2 pr-4 font-medium", t.side === "long" ? "text-emerald-400" : "text-rose-400")}>
                      {t.side.toUpperCase()}
                    </td>
                    <td className="py-2 pr-4 text-right text-slate-300">{t.qty}</td>
                    <td className="py-2 pr-4 text-right text-slate-300">{t.entry_price?.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right text-rose-400">{t.stop_loss?.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right text-emerald-400">{t.take_profit?.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right">
                      <PnlBadge value={t.pnl ?? 0} />
                    </td>
                    <td className="py-2 pr-4 text-right text-slate-400">
                      {t.ai_confidence ? `${Math.round(t.ai_confidence * 100)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Trade History ── */}
      <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-3">Today's Trades</h2>
        {trades.filter((t) => t.status !== "open").length === 0 ? (
          <p className="text-slate-600 text-sm text-center py-6">No closed trades today</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2 pr-4">Symbol</th>
                  <th className="text-left py-2 pr-4">Side</th>
                  <th className="text-right py-2 pr-4">Entry</th>
                  <th className="text-right py-2 pr-4">Exit</th>
                  <th className="text-right py-2 pr-4">Net P&L</th>
                  <th className="text-right py-2 pr-4">Status</th>
                  <th className="text-right py-2 pr-4">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {trades
                  .filter((t) => t.status !== "open")
                  .slice(0, 20)
                  .map((t) => (
                    <tr key={t.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
                      <td className="py-2 pr-4 font-semibold text-white">{t.symbol}</td>
                      <td className={cn("py-2 pr-4", t.side === "long" ? "text-emerald-400" : "text-rose-400")}>
                        {t.side.toUpperCase()}
                      </td>
                      <td className="py-2 pr-4 text-right text-slate-300">{t.entry_price?.toFixed(2)}</td>
                      <td className="py-2 pr-4 text-right text-slate-300">{t.exit_price?.toFixed(2) ?? "—"}</td>
                      <td className="py-2 pr-4 text-right">
                        <PnlBadge value={t.net_pnl ?? 0} />
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <span
                          className={cn(
                            "px-1.5 py-0.5 rounded text-[10px] font-medium",
                            t.status === "target_hit"
                              ? "bg-emerald-900/50 text-emerald-400"
                              : t.status === "stopped_out"
                              ? "bg-rose-900/50 text-rose-400"
                              : "bg-slate-800 text-slate-400"
                          )}
                        >
                          {t.status.replace("_", " ").toUpperCase()}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-right text-slate-400">
                        {t.ai_confidence ? `${Math.round(t.ai_confidence * 100)}%` : "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-center text-[10px] text-slate-700 pb-4">
        AI Trading Platform &nbsp;•&nbsp; Paper trading by default &nbsp;•&nbsp; Not financial advice
      </p>
    </div>
  );
}
