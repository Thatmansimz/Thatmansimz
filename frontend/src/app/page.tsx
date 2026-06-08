"use client";
import { useEffect, useState, useCallback } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { Speedometer } from "../components/Speedometer";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function api(path: string) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`API ${path} failed`);
  return res.json();
}

type SessionInfo = {
  name: string;
  label: string;
  hours: string;
  open: boolean;
  kill_zone: boolean;
};
type Status = {
  trading_enabled: boolean;
  market_open: boolean;
  scheduler_running: boolean;
  broker: string;
  prop_firm: string;
  daily_target: number;
  max_stop_dollars: number;
  ai_threshold: number;
  sessions?: SessionInfo[];
  now_et?: string;
};
type Stats = { pnl: number; trades_count: number; wins: number; losses: number; win_rate: number };
type Trade = {
  id: number; symbol: string; side: string; qty: number;
  entry_price: number; exit_price: number; stop_loss: number; take_profit: number;
  status: string; pnl: number; net_pnl: number; ai_confidence: number;
  entry_time: string; exit_reason: string;
};
type Signal = {
  id: number; symbol: string; direction: string; confidence: number;
  entry_price: number; stop_loss: number; target_1: number;
  risk_reward_ratio: number; risk_amount: number; status: string;
  created_at: string; indicators: Record<string, number>;
};
type PropStatus = {
  firm: string; daily_loss_limit: number; daily_loss_used: number;
  daily_loss_remaining: number; max_drawdown_limit: number; max_drawdown_used: number;
  profit_target: number; cumulative_profit: number; profit_progress_pct: number;
  allows_automation: boolean; evaluation_passed: boolean; evaluation_failed: boolean;
};
type Perf = {
  total_trades: number; win_rate: number; avg_win: number;
  avg_loss: number; profit_factor: number; total_pnl: number;
  wins?: number; losses?: number; expectancy?: number;
};
type Bucket = {
  trades: number; wins: number; losses: number; win_rate: number;
  pnl: number; avg_win: number; avg_loss: number; payoff: number; expectancy: number;
};
type Insights = {
  total_trades: number;
  overall: Bucket;
  win_loss_ratio: number;
  by_direction: Record<string, Bucket>;
  by_symbol: Record<string, Bucket>;
  by_session: Record<string, Bucket>;
  by_exit: Record<string, Bucket>;
  by_confidence: Record<string, Bucket>;
  strengths: string[];
  weaknesses: string[];
  note?: string;
};

function cn(...c: (string | boolean | undefined)[]) { return c.filter(Boolean).join(" "); }

function PnlBadge({ value }: { value: number }) {
  const pos = value >= 0;
  return (
    <span
      className={cn("font-mono-hud font-bold text-xs", pos ? "text-glow-green" : "text-glow-red")}
      style={{ color: pos ? "#00ff88" : "#ff3366" }}
    >
      {pos ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? "#00ff88" : pct >= 65 ? "#ffaa00" : "#ff3366";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "#1a2d4a" }}>
        <div style={{ width: `${pct}%`, background: color, height: "100%", borderRadius: "9999px", boxShadow: `0 0 6px ${color}`, transition: "width 0.6s ease" }} />
      </div>
      <span className="text-[10px] font-mono-hud w-7 text-right" style={{ color }}>{pct}%</span>
    </div>
  );
}

function LiveDot({ active, warn }: { active: boolean; warn?: boolean }) {
  if (!active) return <span className="dot-dead" />;
  if (warn)    return <span className="dot-warn" />;
  return <span className="dot-live" />;
}

/* ── Ticker tape ── */
const TICKER_ITEMS = [
  "MES · MICRO S&P 500","MNQ · MICRO NASDAQ","ES · S&P 500 FUTURES",
  "NQ · NASDAQ FUTURES","RTY · RUSSELL 2000","YM · DOW FUTURES",
  "TAJARI AI TRADING","PAPER MODE · NO RISK","AI ENGINE ACTIVE",
];

function Ticker() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <div className="ticker-wrap py-1.5" style={{ background: "#0a0e1a", borderTop: "1px solid #1a2d4a", borderBottom: "1px solid #1a2d4a" }}>
      <div className="ticker-inner">
        {items.map((item, i) => (
          <span key={i} className="inline-flex items-center gap-2 mx-6 text-[10px] font-mono-hud" style={{ color: "#00d4ff88" }}>
            <span style={{ color: "#00d4ff" }}>◆</span>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ── Global session clock bar ── */
function SessionBar({ sessions, nowEt }: { sessions?: SessionInfo[]; nowEt?: string }) {
  const fallback: SessionInfo[] = [
    { name: "ASIA", label: "Asia · Tokyo", hours: "8:00 PM – 4:00 AM ET", open: false, kill_zone: false },
    { name: "LONDON", label: "London", hours: "4:00 AM – 12:00 PM ET", open: false, kill_zone: false },
    { name: "NEW_YORK", label: "New York", hours: "9:00 AM – 6:00 PM ET", open: false, kill_zone: false },
  ];
  const list = sessions && sessions.length ? sessions : fallback;
  return (
    <div className="flex items-center gap-2 flex-wrap px-1">
      <span className="text-[9px] tracking-[0.3em] uppercase font-mono-hud mr-1" style={{ color: "#475569" }}>
        ◆ Global Sessions
      </span>
      {list.map((s) => {
        const color = s.kill_zone ? "#ffaa00" : s.open ? "#00ff88" : "#475569";
        return (
          <div
            key={s.name}
            title={`${s.label} · ${s.hours}${s.kill_zone ? " · PEAK VOLATILITY" : ""}`}
            className={cn(
              "session-chip flex items-center gap-2 px-3 py-1.5 rounded-full text-[10px] font-mono-hud",
              s.kill_zone && "session-chip-kill",
            )}
            style={{
              background: s.open ? `${color}14` : "#0a1525",
              border: `1px solid ${s.open ? `${color}55` : "#1a2d4a"}`,
            }}
          >
            <span
              style={{
                width: 7, height: 7, borderRadius: "50%", background: color,
                boxShadow: s.open ? `0 0 8px ${color}` : "none",
              }}
            />
            <span style={{ color: s.open ? color : "#475569", fontWeight: s.open ? 700 : 400 }}>
              {s.label}
            </span>
            <span style={{ color: s.open ? `${color}aa` : "#334155" }}>
              {s.kill_zone ? "PEAK" : s.open ? "OPEN" : "CLOSED"}
            </span>
          </div>
        );
      })}
      {nowEt && (
        <span className="text-[10px] font-mono-hud ml-auto" style={{ color: "#475569" }}>
          {nowEt} ET
        </span>
      )}
    </div>
  );
}

/* ── Max Stop adjustment control ── */
function MaxStopControl({ value, onCommit }: { value: number; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState(value);
  const [synced, setSynced] = useState(true);

  // keep in sync when the server value changes (and we're not mid-drag)
  useEffect(() => { if (synced) setDraft(value); }, [value, synced]);

  const MIN = 50, MAX = 2000;
  const pct = ((draft - MIN) / (MAX - MIN)) * 100;
  const presets = [100, 250, 500, 1000];

  function commit(v: number) {
    const clamped = Math.max(MIN, Math.min(MAX, v));
    setDraft(clamped);
    setSynced(true);
    onCommit(clamped);
  }

  return (
    <div className="rounded-xl p-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span style={{ color: "#ffaa00" }}>◆</span>
          <span className="text-[10px] tracking-widest uppercase font-mono-hud" style={{ color: "#475569" }}>
            Max Stop / Trade
          </span>
        </div>
        <span className="text-2xl font-bold font-mono-hud" style={{ color: "#ffaa00", textShadow: "0 0 14px #ffaa0088" }}>
          ${draft}
        </span>
      </div>

      <div className="relative">
        <input
          type="range" min={MIN} max={MAX} step={25} value={draft}
          onChange={(e) => { setSynced(false); setDraft(Number(e.target.value)); }}
          onMouseUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
          onTouchEnd={(e) => commit(Number((e.target as HTMLInputElement).value))}
          onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
          className="hud-range"
          style={{ background: `linear-gradient(90deg, #ffaa00 ${pct}%, #0d1a2e ${pct}%)` }}
        />
      </div>

      <div className="flex items-center justify-between mt-3">
        <div className="flex gap-1.5">
          {presets.map((p) => (
            <button
              key={p}
              onClick={() => commit(p)}
              className="px-2.5 py-1 rounded-md text-[10px] font-mono-hud transition-colors"
              style={
                draft === p
                  ? { background: "#ffaa0022", border: "1px solid #ffaa0055", color: "#ffaa00" }
                  : { background: "#0d1a2e", border: "1px solid #1a2d4a", color: "#475569" }
              }
            >
              ${p}
            </button>
          ))}
        </div>
        <span className="text-[9px] font-mono-hud" style={{ color: synced ? "#334155" : "#ffaa00" }}>
          {synced ? "applied to live engine" : "release to apply"}
        </span>
      </div>
    </div>
  );
}

/* ── Win / Loss ratio card ── */
function WinLossCard({ perf }: { perf: Perf | null }) {
  const wins = perf?.wins ?? 0;
  const losses = perf?.losses ?? 0;
  const total = wins + losses;
  const winPct = total ? (wins / total) * 100 : 0;
  const wl = losses ? wins / losses : wins;
  const payoff = perf && perf.avg_loss ? Math.abs(perf.avg_win / perf.avg_loss) : 0;
  const GREEN = "#00ff88", RED = "#ff3366";
  return (
    <div className="rounded-xl p-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span style={{ color: "#00d4ff" }}>◆</span>
          <span className="text-[10px] tracking-widest uppercase font-mono-hud" style={{ color: "#475569" }}>
            Win / Loss Ratio
          </span>
        </div>
        <span className="text-2xl font-bold font-mono-hud" style={{ color: "#00d4ff", textShadow: "0 0 14px #00d4ff88" }}>
          {wl.toFixed(2)}<span className="text-sm" style={{ color: "#475569" }}> : 1</span>
        </span>
      </div>
      <div className="flex h-3 rounded-full overflow-hidden" style={{ background: "#0d1a2e" }}>
        <div style={{ width: `${winPct}%`, background: `linear-gradient(90deg,${GREEN}88,${GREEN})`, boxShadow: `0 0 8px ${GREEN}`, transition: "width 0.6s ease" }} />
        <div style={{ flex: 1, background: `linear-gradient(90deg,${RED},${RED}88)` }} />
      </div>
      <div className="flex items-center justify-between mt-2 text-[10px] font-mono-hud">
        <span style={{ color: GREEN }}>{wins}W</span>
        <span style={{ color: "#475569" }}>payoff <span style={{ color: payoff >= 1 ? GREEN : "#ffaa00" }}>{payoff.toFixed(2)}x</span></span>
        <span style={{ color: RED }}>{losses}L</span>
      </div>
    </div>
  );
}

/* ── Trade insights (strengths / weaknesses) ── */
function EdgeRow({ name, b }: { name: string; b: Bucket }) {
  const pos = b.pnl >= 0;
  return (
    <div className="flex items-center justify-between py-1.5 px-2 rounded-lg" style={{ background: "#0a1525" }}>
      <span className="text-[10px] font-mono-hud" style={{ color: "#94a3b8" }}>{name}</span>
      <div className="flex items-center gap-3 text-[10px] font-mono-hud">
        <span style={{ color: "#475569" }}>{b.trades}t</span>
        <span style={{ color: b.win_rate >= 50 ? "#00ff88" : "#ffaa00" }}>{b.win_rate}%</span>
        <span className="w-16 text-right font-bold" style={{ color: pos ? "#00ff88" : "#ff3366" }}>
          {pos ? "+" : ""}${b.pnl.toFixed(0)}
        </span>
      </div>
    </div>
  );
}

function InsightsPanel({ insights }: { insights: Insights | null }) {
  if (!insights || insights.total_trades === 0) {
    return (
      <div className="glass-bright rounded-2xl p-5">
        <SectionHeader title="Trade Insights" sub="strengths & weaknesses · auto-learned" />
        <div className="py-10 flex flex-col items-center gap-2 text-center">
          <div className="text-3xl" style={{ color: "#1a2d4a" }}>◍</div>
          <p className="text-xs font-mono-hud tracking-wide max-w-md" style={{ color: "#475569" }}>
            {insights?.note ?? "Insights unlock as trades close — your best direction, session, and instrument will surface here automatically."}
          </p>
        </div>
      </div>
    );
  }
  const dirEntries = Object.entries(insights.by_direction);
  const sessEntries = Object.entries(insights.by_session).filter(([k]) => k !== "Unknown");
  return (
    <div className="glass-bright rounded-2xl p-5">
      <SectionHeader title="Trade Insights" sub={`${insights.total_trades} trades analyzed · expectancy $${insights.overall.expectancy.toFixed(0)}/trade`} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Strengths */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span style={{ color: "#00ff88" }}>▲</span>
            <span className="text-[10px] tracking-widest uppercase font-mono-hud" style={{ color: "#00ff88" }}>Strengths</span>
          </div>
          <div className="space-y-2">
            {insights.strengths.map((s, i) => (
              <div key={i} className="flex gap-2 text-[11px] leading-snug p-2 rounded-lg" style={{ background: "#00ff8808", border: "1px solid #00ff8822" }}>
                <span style={{ color: "#00ff88" }}>✓</span>
                <span style={{ color: "#cbd5e1" }}>{s}</span>
              </div>
            ))}
          </div>
        </div>
        {/* Weaknesses */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span style={{ color: "#ff3366" }}>▼</span>
            <span className="text-[10px] tracking-widest uppercase font-mono-hud" style={{ color: "#ff3366" }}>Weaknesses</span>
          </div>
          <div className="space-y-2">
            {insights.weaknesses.map((w, i) => (
              <div key={i} className="flex gap-2 text-[11px] leading-snug p-2 rounded-lg" style={{ background: "#ff336608", border: "1px solid #ff336622" }}>
                <span style={{ color: "#ff3366" }}>!</span>
                <span style={{ color: "#cbd5e1" }}>{w}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {/* Edge map */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-5 pt-4" style={{ borderTop: "1px solid #1a2d4a" }}>
        <div>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud mb-2" style={{ color: "#334155" }}>By Direction</p>
          <div className="space-y-1.5">
            {dirEntries.map(([k, b]) => <EdgeRow key={k} name={k.toUpperCase()} b={b} />)}
          </div>
        </div>
        <div>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud mb-2" style={{ color: "#334155" }}>By Session</p>
          <div className="space-y-1.5">
            {sessEntries.map(([k, b]) => <EdgeRow key={k} name={k} b={b} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Section header ── */
function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div style={{ width: 3, height: 18, background: "linear-gradient(180deg,#00d4ff,#7c3aed)", borderRadius: 2, boxShadow: "0 0 8px #00d4ff" }} />
      <div>
        <h2 className="text-sm font-semibold text-white font-display tracking-wider">{title}</h2>
        {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [status,       setStatus]       = useState<Status | null>(null);
  const [todayStats,   setTodayStats]   = useState<Stats | null>(null);
  const [trades,       setTrades]       = useState<Trade[]>([]);
  const [signals,      setSignals]      = useState<Signal[]>([]);
  const [propStatus,   setPropStatus]   = useState<PropStatus | null>(null);
  const [perf,         setPerf]         = useState<Perf | null>(null);
  const [insights,     setInsights]     = useState<Insights | null>(null);
  const [dailyHistory, setDailyHistory] = useState<{ date: string; pnl: number }[]>([]);
  const [trading,      setTrading]      = useState(false);
  const [closing,      setClosing]      = useState(false);
  const [now,          setNow]          = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, t, tr, sg, ps, pf, dh, ins] = await Promise.allSettled([
        api("/api/status"), api("/api/stats/today"), api("/api/trades/today"),
        api("/api/signals?limit=10"), api("/api/prop-firm/status"),
        api("/api/stats/performance"), api("/api/stats/daily"),
        api("/api/stats/insights"),
      ]);
      if (s.status  === "fulfilled") setStatus(s.value);
      if (t.status  === "fulfilled") setTodayStats(t.value);
      if (tr.status === "fulfilled") setTrades(tr.value);
      if (sg.status === "fulfilled") setSignals(sg.value);
      if (ps.status === "fulfilled") setPropStatus(ps.value);
      if (pf.status === "fulfilled") setPerf(pf.value);
      if (dh.status === "fulfilled") setDailyHistory(dh.value.slice(0, 30).reverse());
      if (ins.status === "fulfilled") setInsights(ins.value);
    } catch (_) {}
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [load]);

  useEffect(() => {
    setNow(new Date());
    const iv = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(iv);
  }, []);

  async function toggleTrading() {
    setTrading(true);
    try {
      await fetch(`${API}${status?.trading_enabled ? "/api/trading/stop" : "/api/trading/start"}`, { method: "POST" });
      await load();
    } finally { setTrading(false); }
  }

  async function closeAll() {
    if (!confirm("Emergency close ALL open positions?")) return;
    setClosing(true);
    try {
      await fetch(`${API}/api/trading/close-all`, { method: "POST" });
      await load();
    } finally { setClosing(false); }
  }

  async function saveMaxStop(v: number) {
    // optimistic update so the gauge + stat reflect it instantly
    setStatus((prev) => (prev ? { ...prev, max_stop_dollars: v } : prev));
    try {
      await fetch(`${API}/api/settings/max-stop?value=${v}`, { method: "POST" });
      await load();
    } catch (_) {}
  }

  const dailyPnl  = todayStats?.pnl ?? 0;
  const openTrades = trades.filter((t) => t.status === "open");
  const riskValue = propStatus && propStatus.daily_loss_limit > 0
    ? propStatus.daily_loss_used
    : Math.abs(Math.min(0, dailyPnl));
  const riskMax = propStatus && propStatus.daily_loss_limit > 0
    ? propStatus.daily_loss_limit
    : (status?.max_stop_dollars ?? 250);

  return (
    <div className="min-h-screen relative">
      {/* ── Top header bar ── */}
      <header style={{ background: "linear-gradient(180deg,#0d1a2e,#080f1c)", borderBottom: "1px solid #1a2d4a" }}>
        <div className="max-w-screen-2xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div
              className="flex items-center justify-center font-display font-black text-xl rounded-lg"
              style={{
                width: 44, height: 44,
                background: "linear-gradient(135deg,#00d4ff,#7c3aed)",
                boxShadow: "0 0 24px #00d4ff66, 0 0 48px #7c3aed44",
                color: "#fff",
                letterSpacing: "-0.05em",
              }}
            >
              T
            </div>
            <div>
              <h1
                className="font-display font-bold text-xl tracking-widest leading-none"
                style={{
                  background: "linear-gradient(90deg,#00d4ff,#7c3aed,#00ff88)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  textShadow: "none",
                }}
              >
                TAJARI
              </h1>
              <p className="text-[9px] tracking-[0.35em] font-mono-hud" style={{ color: "#00d4ff88" }}>
                AI TRADING PLATFORM
              </p>
            </div>
          </div>

          {/* Live clock */}
          <div className="hidden md:block font-mono-hud text-xs text-center" style={{ color: "#00d4ff88" }}>
            <div className="font-bold text-sm" style={{ color: "#00d4ff" }}>
              {now ? now.toLocaleTimeString("en-US", { hour12: false }) : "--:--:--"}
            </div>
            <div>{now ? now.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "---"}</div>
          </div>

          {/* Status pills */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs font-mono-hud">
              <LiveDot active={!!status?.market_open} />
              <span style={{ color: status?.market_open ? "#00ff88" : "#475569" }}>
                {status?.market_open ? "MARKET OPEN" : "MARKET CLOSED"}
              </span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs font-mono-hud">
              <LiveDot active={!!status?.scheduler_running} />
              <span style={{ color: status?.scheduler_running ? "#00d4ff" : "#475569" }}>
                AI {status?.scheduler_running ? "ACTIVE" : "IDLE"}
              </span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full glass text-[10px] font-mono-hud" style={{ color: "#7c3aed88" }}>
              <span style={{ color: "#7c3aed" }}>◆</span>
              {(status?.broker ?? "PAPER").toUpperCase()}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button onClick={closeAll} disabled={closing} className="btn-red px-4 py-2 rounded-lg disabled:opacity-50">
              {closing ? "CLOSING..." : "⚠ EMERGENCY STOP"}
            </button>
            <button onClick={toggleTrading} disabled={trading} className={status?.trading_enabled ? "btn-red px-4 py-2 rounded-lg disabled:opacity-50" : "btn-green px-4 py-2 rounded-lg disabled:opacity-50"}>
              {trading ? "..." : status?.trading_enabled ? "⏸ PAUSE" : "▶ START TRADING"}
            </button>
          </div>
        </div>
      </header>

      {/* ── Ticker ── */}
      <Ticker />

      {/* ── Global session clock ── */}
      <div className="max-w-screen-2xl mx-auto px-4 md:px-6 pt-4">
        <SessionBar sessions={status?.sessions} nowEt={status?.now_et} />
      </div>

      {/* ── Main content ── */}
      <main className="max-w-screen-2xl mx-auto px-4 md:px-6 py-6 space-y-6">

        {/* ── Instrument Cluster ── */}
        <div
          className="shimmer-border rounded-2xl p-6"
          style={{
            background: "radial-gradient(ellipse at 50% 0%, #0f2040 0%, #080e1a 65%)",
            boxShadow: "0 0 80px #00d4ff18, 0 0 160px #7c3aed10, inset 0 1px 0 #1a2d4a",
          }}
        >
          {/* Cluster label */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <span
                className="font-display text-xs font-bold tracking-[0.3em] uppercase"
                style={{ color: "#00d4ff" }}
              >
                ◆ Instrument Cluster
              </span>
              {status?.trading_enabled && (
                <span
                  className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
                  style={{ background: "#00ff8822", border: "1px solid #00ff8844", color: "#00ff88", animation: "green-pulse 2s infinite" }}
                >
                  LIVE
                </span>
              )}
            </div>
            <div className="hidden sm:flex items-center gap-4 text-[10px] font-mono-hud" style={{ color: "#475569" }}>
              <span>{perf?.wins ?? 0}W <span style={{ color: "#00ff88" }}>wins</span></span>
              <span>{perf?.losses ?? 0}L <span style={{ color: "#ff3366" }}>losses</span></span>
              <span>PF <span style={{ color: "#00d4ff" }}>{perf?.profit_factor?.toFixed(2) ?? "—"}</span></span>
              <span>{openTrades.length} open</span>
            </div>
          </div>

          {/* Four gauges */}
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 place-items-center">
            <Speedometer
              value={Math.max(0, dailyPnl)}
              max={status?.daily_target ?? 1000}
              label="Daily P&L"
              sublabel={`${dailyPnl >= 0 ? "+" : ""}$${dailyPnl.toFixed(0)} · target $${status?.daily_target?.toLocaleString() ?? 1000}`}
              colorMode="profit"
              size={195}
              formatCenter={(v) => `$${v.toFixed(0)}`}
            />
            <Speedometer
              value={perf?.win_rate ?? 0}
              max={100}
              label="Win Rate"
              sublabel={`avg win $${perf?.avg_win?.toFixed(0) ?? "0"} · avg loss $${perf?.avg_loss?.toFixed(0) ?? "0"}`}
              colorMode="confidence"
              unit="%"
              size={195}
              formatCenter={(v) => `${v.toFixed(1)}%`}
            />
            <Speedometer
              value={(status?.ai_threshold ?? 0.65) * 100}
              max={100}
              label="AI Threshold"
              sublabel={`signals above this confidence only`}
              colorMode="confidence"
              unit="%"
              size={195}
              formatCenter={(v) => `${v.toFixed(0)}%`}
            />
            <Speedometer
              value={riskValue}
              max={riskMax}
              label="Risk Exposure"
              sublabel={`max stop $${status?.max_stop_dollars ?? 250} per trade`}
              colorMode="risk"
              size={195}
              formatCenter={(v) => `$${v.toFixed(0)}`}
            />
          </div>

          {/* Stat strip + risk control */}
          <div className="mt-6 pt-4 grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ borderTop: "1px solid #1a2d4a" }}>
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4 text-center">
                {[
                  { label: "Trades Today", value: `${todayStats?.trades_count ?? 0}`,          color: "#00d4ff" },
                  { label: "Total P&L",    value: `$${(perf?.total_pnl ?? 0).toFixed(0)}`,     color: (perf?.total_pnl ?? 0) >= 0 ? "#00ff88" : "#ff3366" },
                  { label: "Profit Factor",value: perf?.profit_factor?.toFixed(2) ?? "—",      color: "#7c3aed" },
                ].map((s) => (
                  <div key={s.label} className="rounded-xl py-3 px-4 flex flex-col justify-center" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
                    <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>{s.label}</p>
                    <p className="text-lg font-bold font-mono-hud mt-0.5" style={{ color: s.color, textShadow: `0 0 12px ${s.color}88` }}>
                      {s.value}
                    </p>
                  </div>
                ))}
              </div>
              {/* Win/Loss ratio — second row, left of Max Stop */}
              <WinLossCard perf={perf} />
            </div>
            <MaxStopControl value={status?.max_stop_dollars ?? 250} onCommit={saveMaxStop} />
          </div>
        </div>

        {/* ── Prop Firm Progress ── */}
        {propStatus && propStatus.firm !== "None" && (
          <div className="glass-bright rounded-2xl p-5">
            <SectionHeader
              title={`${propStatus.firm} · Evaluation`}
              sub={propStatus.allows_automation ? "✓ AI automation allowed" : "⚠ Manual trading only"}
            />
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              {[
                { label: "Profit Target", pct: propStatus.profit_progress_pct, cur: propStatus.cumulative_profit, max: propStatus.profit_target, color: "#00ff88" },
                { label: "Daily Loss Used", pct: propStatus.daily_loss_limit > 0 ? (propStatus.daily_loss_used / propStatus.daily_loss_limit) * 100 : 0, cur: propStatus.daily_loss_used, max: propStatus.daily_loss_limit, color: "#ff3366" },
                { label: "Max Drawdown", pct: propStatus.max_drawdown_limit > 0 ? (propStatus.max_drawdown_used / propStatus.max_drawdown_limit) * 100 : 0, cur: propStatus.max_drawdown_used, max: propStatus.max_drawdown_limit, color: "#ffaa00" },
              ].map((bar) => (
                <div key={bar.label}>
                  <div className="flex justify-between mb-2">
                    <span className="text-[10px] font-mono-hud tracking-wider uppercase" style={{ color: "#475569" }}>{bar.label}</span>
                    <span className="text-[10px] font-mono-hud font-bold" style={{ color: bar.color }}>{bar.pct.toFixed(1)}%</span>
                  </div>
                  <div className="h-2 rounded-full overflow-hidden" style={{ background: "#0a1525" }}>
                    <div
                      style={{
                        width: `${Math.min(100, bar.pct)}%`, height: "100%",
                        background: `linear-gradient(90deg, ${bar.color}88, ${bar.color})`,
                        boxShadow: `0 0 8px ${bar.color}`,
                        borderRadius: "9999px",
                        transition: "width 0.8s ease",
                      }}
                    />
                  </div>
                  <p className="text-[10px] font-mono-hud mt-1" style={{ color: "#334155" }}>
                    ${bar.cur.toFixed(0)} / ${bar.max.toLocaleString()}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Chart + Signals ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* P&L Chart */}
          <div className="glass-bright rounded-2xl p-5">
            <SectionHeader title="P&L History" sub="30-day equity curve" />
            {dailyHistory.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={dailyHistory} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#00d4ff" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }} />
                  <Tooltip
                    contentStyle={{ background: "#0d1525", border: "1px solid #1a2d4a", borderRadius: 10, fontSize: 11, fontFamily: "JetBrains Mono" }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, "P&L"]}
                    labelStyle={{ color: "#00d4ff" }}
                  />
                  <ReferenceLine y={0} stroke="#1a2d4a" strokeDasharray="4 4" />
                  <Area type="monotone" dataKey="pnl" stroke="#00d4ff" strokeWidth={2} fill="url(#pnlGrad)" dot={false} activeDot={{ r: 4, fill: "#00d4ff" }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-xs font-mono-hud" style={{ color: "#1a2d4a" }}>
                NO HISTORY · START TRADING TO BUILD EQUITY CURVE
              </div>
            )}
          </div>

          {/* AI Signals */}
          <div className="glass-bright rounded-2xl p-5">
            <SectionHeader title="AI Signals" sub="latest high-confidence setups" />
            {signals.length === 0 ? (
              <div className="h-48 flex flex-col items-center justify-center gap-2">
                <div className="text-2xl">◉</div>
                <p className="text-xs font-mono-hud tracking-widest" style={{ color: "#1a2d4a" }}>SCANNING MARKETS...</p>
              </div>
            ) : (
              <div className="space-y-2 overflow-y-auto max-h-52 pr-1">
                {signals.map((sig) => (
                  <div
                    key={sig.id}
                    className="flex items-center gap-3 p-2.5 rounded-xl tr-hover"
                    style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}
                  >
                    <div
                      className="w-14 text-center text-[10px] font-display font-bold py-1.5 rounded-lg"
                      style={sig.direction === "long"
                        ? { background: "#00ff8822", border: "1px solid #00ff8844", color: "#00ff88" }
                        : { background: "#ff336622", border: "1px solid #ff336644", color: "#ff3366" }
                      }
                    >
                      {sig.direction === "long" ? "▲ LONG" : "▼ SHORT"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-bold font-mono-hud text-white">{sig.symbol}</span>
                        <span className="text-[10px] font-mono-hud" style={{ color: "#475569" }}>R:R {sig.risk_reward_ratio?.toFixed(1)}x</span>
                      </div>
                      <ConfidenceBar value={sig.confidence} />
                    </div>
                    <div className="text-right text-[10px] font-mono-hud">
                      <p style={{ color: "#00d4ff" }}>@ {sig.entry_price?.toFixed(2)}</p>
                      <p style={{ color: "#ff3366" }}>SL {sig.stop_loss?.toFixed(2)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Trade Insights ── */}
        <InsightsPanel insights={insights} />

        {/* ── Open Positions ── */}
        <div className="glass-bright rounded-2xl p-5">
          <SectionHeader title="Open Positions" sub={`${openTrades.length} active · auto-managed`} />
          {openTrades.length === 0 ? (
            <div className="py-10 flex flex-col items-center gap-2">
              <div className="text-3xl" style={{ color: "#1a2d4a" }}>◎</div>
              <p className="text-xs font-mono-hud tracking-widest" style={{ color: "#1a2d4a" }}>NO OPEN POSITIONS</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono-hud">
                <thead>
                  <tr style={{ borderBottom: "1px solid #1a2d4a" }}>
                    {["Symbol","Side","Qty","Entry","Stop","Target","P&L","Conf."].map((h) => (
                      <th key={h} className="text-left py-2 pr-4 font-medium tracking-wider" style={{ color: "#334155" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {openTrades.map((t) => (
                    <tr key={t.id} className="tr-hover" style={{ borderBottom: "1px solid #0d1a2e" }}>
                      <td className="py-2.5 pr-4 font-bold font-display text-xs tracking-wider" style={{ color: "#00d4ff" }}>{t.symbol}</td>
                      <td className="py-2.5 pr-4 font-bold" style={{ color: t.side === "long" ? "#00ff88" : "#ff3366" }}>
                        {t.side === "long" ? "▲" : "▼"} {t.side.toUpperCase()}
                      </td>
                      <td className="py-2.5 pr-4 text-slate-400">{t.qty}</td>
                      <td className="py-2.5 pr-4 text-slate-300">{t.entry_price?.toFixed(2)}</td>
                      <td className="py-2.5 pr-4" style={{ color: "#ff3366" }}>{t.stop_loss?.toFixed(2)}</td>
                      <td className="py-2.5 pr-4" style={{ color: "#00ff88" }}>{t.take_profit?.toFixed(2)}</td>
                      <td className="py-2.5 pr-4"><PnlBadge value={t.pnl ?? 0} /></td>
                      <td className="py-2.5 pr-4" style={{ color: "#7c3aed" }}>
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
        <div className="glass-bright rounded-2xl p-5">
          <SectionHeader title="Trade History" sub="closed trades today" />
          {trades.filter((t) => t.status !== "open").length === 0 ? (
            <div className="py-10 flex flex-col items-center gap-2">
              <p className="text-xs font-mono-hud tracking-widest" style={{ color: "#1a2d4a" }}>NO CLOSED TRADES YET TODAY</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono-hud">
                <thead>
                  <tr style={{ borderBottom: "1px solid #1a2d4a" }}>
                    {["Symbol","Side","Entry","Exit","Net P&L","Result","Conf."].map((h) => (
                      <th key={h} className="text-left py-2 pr-4 font-medium tracking-wider" style={{ color: "#334155" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.filter((t) => t.status !== "open").slice(0, 20).map((t) => (
                    <tr key={t.id} className="tr-hover" style={{ borderBottom: "1px solid #0d1a2e" }}>
                      <td className="py-2.5 pr-4 font-bold font-display text-xs tracking-wider" style={{ color: "#00d4ff" }}>{t.symbol}</td>
                      <td className="py-2.5 pr-4 font-bold" style={{ color: t.side === "long" ? "#00ff88" : "#ff3366" }}>
                        {t.side === "long" ? "▲" : "▼"} {t.side.toUpperCase()}
                      </td>
                      <td className="py-2.5 pr-4 text-slate-400">{t.entry_price?.toFixed(2)}</td>
                      <td className="py-2.5 pr-4 text-slate-400">{t.exit_price?.toFixed(2) ?? "—"}</td>
                      <td className="py-2.5 pr-4"><PnlBadge value={t.net_pnl ?? 0} /></td>
                      <td className="py-2.5 pr-4">
                        <span
                          className="px-2 py-0.5 rounded-md text-[9px] font-bold tracking-widest font-display"
                          style={
                            t.status === "target_hit"
                              ? { background: "#00ff8822", border: "1px solid #00ff8844", color: "#00ff88" }
                              : t.status === "stopped_out"
                              ? { background: "#ff336622", border: "1px solid #ff336644", color: "#ff3366" }
                              : { background: "#1a2d4a", color: "#475569" }
                          }
                        >
                          {t.status === "target_hit" ? "✓ TARGET" : t.status === "stopped_out" ? "✗ STOPPED" : t.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-2.5 pr-4" style={{ color: "#7c3aed" }}>
                        {t.ai_confidence ? `${Math.round(t.ai_confidence * 100)}%` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="flex items-center justify-between pb-6 px-2">
          <div className="flex items-center gap-2">
            <span className="font-display text-xs font-bold" style={{ color: "#00d4ff44" }}>TAJARI</span>
            <span className="text-[10px] font-mono-hud" style={{ color: "#1a2d4a" }}>
              AI TRADING · PAPER MODE · NOT FINANCIAL ADVICE
            </span>
          </div>
          <span className="text-[10px] font-mono-hud" style={{ color: "#1a2d4a" }}>
            auto-refresh 10s
          </span>
        </div>
      </main>
    </div>
  );
}
