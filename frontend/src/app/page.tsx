"use client";
import { useEffect, useState, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell, ComposedChart, Line, CartesianGrid, Legend,
} from "recharts";
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
  strategy?: string;
  daily_target: number;
  max_stop_dollars: number;
  ai_threshold: number;
  sessions?: SessionInfo[];
  now_et?: string;
  orb_window_active?: boolean;
  orb_after_cutoff?: boolean;
  orb_opens_in_min?: number | null;
  data_feed?: { healthy: boolean; consecutive_failures: number; last_success: string | null };
  cycles_today?: number;
  signals_today?: number;
  scan_status?: string;
  last_cycle?: string;
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
type FwtSnapshot = {
  date: string; balance: number; equity: number;
  unrealized_pnl: number; cycles: number; uptime_pct: number;
};
type ForwardTest = {
  active: boolean;
  start_date?: string; strategy?: string; symbols?: string[];
  day?: number; target_days?: number; days_remaining?: number; pct_complete?: number;
  start_equity?: number; current_equity?: number; total_pnl?: number;
  trades_closed?: number; wins?: number; losses?: number; win_rate?: number;
  uptime_today_pct?: number;
  snapshots?: FwtSnapshot[];
};
type FunnelStage = { bars: number; signals: number; rejected: number; taken: number };
type Funnel = {
  scope?: string;
  campaign: FunnelStage;
  today: FunnelStage;
  conversion_pct: number;
  rejection_reasons: Record<string, number>;
  last_rejection?: string | null;
  verdict: string;
};
type RecordPoint = { n: number; date: string; equity: number; drawdown: number; pnl: number; r?: number | null };
type RecordGroup = { trades: number; wins: number; pnl: number; win_rate: number; expectancy: number };
type TradeRecord = {
  scope?: string;
  start_date?: string;
  days_elapsed?: number;
  target_days?: number;
  start_equity: number;
  summary: {
    trades: number; wins: number; losses: number; win_rate: number;
    net_pnl: number; profit_factor: number; expectancy: number;
    avg_win: number; avg_loss: number; payoff: number;
    max_drawdown: number; max_drawdown_pct: number;
    avg_r?: number | null; return_pct: number;
  };
  curve: RecordPoint[];
  r_distribution: { bucket: string; count: number }[];
  by_session: Record<string, RecordGroup>;
  by_direction: Record<string, RecordGroup>;
  by_symbol: Record<string, RecordGroup>;
  baseline?: { total_trades: number; win_rate: number; profit_factor?: number | null;
               total_pnl: number; days: number; period?: string; symbol?: string } | null;
  expected?: { per_day: number; to_date: number; trades_per_day: number;
               win_rate?: number; profit_factor?: number | null; expectancy: number } | null;
};
type Insights = {
  total_trades: number;
  scope?: string;
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
/* ── Scan activity widget for the AI Signals panel ── */
function ScanActivity({ status }: { status?: Status | null }) {
  const running = !!status?.scheduler_running;
  const enabled = !!status?.trading_enabled;
  const cycles = status?.cycles_today ?? 0;
  const signals = status?.signals_today ?? 0;
  const raw = status?.scan_status ?? "";
  const lastCycle = status?.last_cycle;

  // Derive a clean one-liner from the scan_status string
  let pulse = false;
  let label = "IDLE";
  let color = "#475569";
  if (!running) {
    label = "ENGINE OFF";
  } else if (raw.startsWith("DATA OUTAGE") || status?.data_feed?.healthy === false) {
    // Blind engine — the worst state there is. Red, pulsing, unmissable.
    label = "🚨 DATA OUTAGE"; color = "#ff3366"; pulse = true;
  } else if (!enabled) {
    label = "NOT ARMED";
  } else if (raw.startsWith("trade taken")) {
    label = "TRADE TAKEN ✓"; color = "#00ff88"; pulse = true;
  } else if (raw.startsWith("signal found")) {
    label = "SIGNAL SEEN ●"; color = "#00d4ff"; pulse = true;
  } else if (raw === "scanning") {
    label = "SCANNING ●"; color = "#00d4ff"; pulse = true;
  } else if (raw === "Market closed") {
    label = "MARKET CLOSED";
  } else if (raw.includes("no setup")) {
    label = "NO SETUP YET";  color = "#64748b";
  } else if (raw) {
    label = raw.toUpperCase().slice(0, 22);
  }

  // Format last cycle time as HH:MM:SS from ISO string
  let lastScan = "—";
  if (lastCycle) {
    try { lastScan = new Date(lastCycle).toLocaleTimeString("en-US", { hour12: false }); } catch { /* */ }
  }

  return (
    <div className="flex flex-col items-end gap-1 min-w-[120px]">
      <div className="flex items-center gap-1.5">
        <span
          style={{
            width: 6, height: 6, borderRadius: "50%", background: color,
            boxShadow: pulse ? `0 0 8px ${color}` : "none",
            animation: pulse ? "green-pulse 1.5s infinite" : "none",
          }}
        />
        <span className="text-[9px] font-mono-hud font-bold tracking-wider" style={{ color }}>{label}</span>
      </div>
      <div className="flex items-center gap-3 text-[9px] font-mono-hud" style={{ color: "#334155" }}>
        <span>{cycles} scans</span>
        <span style={{ color: signals > 0 ? "#00d4ff" : "#334155" }}>{signals} signals</span>
      </div>
      {lastCycle && (
        <span className="text-[9px] font-mono-hud" style={{ color: "#1e3a5f" }}>last: {lastScan}</span>
      )}
    </div>
  );
}

/* ── Engine state pill: DISARMED / ARMED / LIVE ── */
function fmtMins(m?: number | null): string {
  if (m == null || m < 0) return "";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
}

function EngineStatePill({ status }: { status?: Status | null }) {
  // DISARMED  — trading off (engine watching only, no trades possible)
  // LIVE      — trading on AND inside the strategy's trade window: taking trades
  // ARMED     — trading on but outside the window: watching, waiting
  const v2 = status?.strategy === "multi_session";
  let label = "DISARMED", color = "#475569", pulse = false, title = "Trading is off. Click START TRADING to arm the engine.";
  if (status?.trading_enabled) {
    if (status?.orb_window_active) {
      label = "LIVE"; color = "#00ff88"; pulse = true;
      title = v2
        ? "A V2 trade window is open (Asia kill zone / London / NY) — the engine is actively taking paper trades."
        : "ORB window is open (9:35–14:00 ET) — the engine is actively taking paper trades.";
    } else if (status?.orb_after_cutoff) {
      // Past 14:00 ET today — done trading for the day, NY session still open
      const eta = fmtMins(status?.orb_opens_in_min);
      label = eta ? `ARMED · NEXT OPEN ${eta}` : "ARMED · DONE TODAY";
      color = "#ffaa00";
      title = "ORB entry window closed at 14:00 ET. Done trading for today — engine re-arms tomorrow at 9:35 AM ET.";
    } else {
      const eta = fmtMins(status?.orb_opens_in_min);
      label = eta ? `ARMED · ${v2 ? "NEXT WINDOW" : "OPENS IN"} ${eta}` : "ARMED";
      color = "#ffaa00";
      title = v2
        ? "Engine armed. Between V2 trade windows — next one is the Asia kill zone (8 PM ET), London (4 AM ET), or NY (9 AM ET)."
        : "Engine armed. ORB window opens at 9:35 AM ET — idle through Asia/London by design.";
    }
  }
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs font-mono-hud"
      title={title}
      style={{ border: `1px solid ${color}44` }}
    >
      <span
        style={{
          width: 7, height: 7, borderRadius: "50%", background: color,
          boxShadow: `0 0 8px ${color}`,
          animation: pulse ? "green-pulse 2s infinite" : "none",
        }}
      />
      <span style={{ color, fontWeight: 700 }}>{label}</span>
    </div>
  );
}

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

/* ── Head-to-head instrument comparison: WHERE is the edge? ── */
function InstrumentCompare({ bySymbol }: { bySymbol: Record<string, Bucket> }) {
  const entries = Object.entries(bySymbol).filter(([, b]) => b.trades > 0);
  if (entries.length === 0) return null;

  // Rank by expectancy ($/trade) — the number that scales when you add size.
  const ranked = [...entries].sort((a, b) => b[1].expectancy - a[1].expectancy);
  const leader = ranked.length > 1 ? ranked[0][0] : null;
  const maxAbsPnl = Math.max(...entries.map(([, b]) => Math.abs(b.pnl)), 1);
  const accents = ["#00d4ff", "#7c3aed", "#00ff88", "#ffaa00"];

  return (
    <div className="mt-5 pt-4" style={{ borderTop: "1px solid #1a2d4a" }}>
      <div className="flex items-center justify-between mb-3">
        <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>
          By Instrument · where the edge lives
        </p>
        <span className="text-[9px] font-mono-hud" style={{ color: "#334155" }}>ranked by $/trade</span>
      </div>
      <div className={cn("grid gap-3", ranked.length >= 2 ? "sm:grid-cols-2" : "grid-cols-1")}>
        {ranked.map(([sym, b], i) => {
          const pos = b.pnl >= 0;
          const isLeader = sym === leader;
          const accent = accents[i % accents.length];
          const barPct = Math.min(100, (Math.abs(b.pnl) / maxAbsPnl) * 100);
          return (
            <div
              key={sym}
              className="rounded-xl p-3 relative overflow-hidden"
              style={{
                background: "#0a1525",
                border: `1px solid ${isLeader ? "#00ff8855" : "#1a2d4a"}`,
                boxShadow: isLeader ? "0 0 24px #00ff8814" : "none",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: accent, boxShadow: `0 0 8px ${accent}` }} />
                  <span className="font-display font-bold text-sm tracking-wider" style={{ color: "#e2e8f0" }}>{sym}</span>
                  {isLeader && (
                    <span className="px-1.5 py-0.5 rounded text-[8px] font-mono-hud font-bold tracking-widest"
                      style={{ background: "#00ff8822", border: "1px solid #00ff8844", color: "#00ff88" }}>
                      ◆ LEADING
                    </span>
                  )}
                </div>
                <span className="text-[10px] font-mono-hud" style={{ color: "#475569" }}>{b.trades} trades</span>
              </div>

              <div className="flex items-end justify-between mb-2">
                <div>
                  <div className="font-mono-hud font-bold text-lg leading-none" style={{ color: pos ? "#00ff88" : "#ff3366" }}>
                    {pos ? "+" : ""}${b.pnl.toFixed(0)}
                  </div>
                  <div className="text-[9px] font-mono-hud mt-0.5" style={{ color: "#475569" }}>net P&amp;L</div>
                </div>
                <div className="text-right">
                  <div className="font-mono-hud font-bold text-sm leading-none" style={{ color: b.win_rate >= 50 ? "#00ff88" : "#ffaa00" }}>
                    {b.win_rate}%
                  </div>
                  <div className="text-[9px] font-mono-hud mt-0.5" style={{ color: "#475569" }}>{b.wins}W · {b.losses}L</div>
                </div>
              </div>

              {/* P&L magnitude bar (relative to the strongest instrument) */}
              <div className="h-1.5 rounded-full overflow-hidden mb-2" style={{ background: "#0f1d33" }}>
                <div style={{ width: `${barPct}%`, height: "100%", background: pos ? "#00ff88" : "#ff3366", boxShadow: `0 0 8px ${pos ? "#00ff88" : "#ff3366"}` }} />
              </div>

              <div className="flex items-center justify-between text-[9px] font-mono-hud" style={{ color: "#64748b" }}>
                <span>exp <span style={{ color: b.expectancy >= 0 ? "#00ff88" : "#ff3366", fontWeight: 700 }}>{b.expectancy >= 0 ? "+" : ""}${b.expectancy.toFixed(0)}/t</span></span>
                <span>payoff <span style={{ color: "#94a3b8" }}>{b.payoff.toFixed(2)}x</span></span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InsightsPanel({ insights, onRun, onReset, running }: {
  insights: Insights | null; onRun: () => void; onReset: () => void; running: boolean;
}) {
  if (!insights || insights.total_trades === 0) {
    return (
      <div className="glass-bright rounded-2xl p-5">
        <SectionHeader title="Trade Insights" sub="strengths & weaknesses · auto-learned" />
        <div className="py-10 flex flex-col items-center gap-3 text-center">
          <div className="text-3xl" style={{ color: "#1a2d4a" }}>◍</div>
          <p className="text-xs font-mono-hud tracking-wide max-w-md" style={{ color: "#475569" }}>
            {insights?.note ?? "Insights unlock as trades close — your best direction, session, and instrument will surface here automatically."}
          </p>
          <button onClick={onRun} disabled={running} className="btn-cyan px-5 py-2.5 rounded-lg disabled:opacity-50 mt-1">
            {running ? "RUNNING FORWARD-TEST..." : "▶ RUN PAPER FORWARD-TEST"}
          </button>
          <p className="text-[10px] font-mono-hud max-w-sm" style={{ color: "#334155" }}>
            Replays the validated ORB edge over the last 30 days as paper trades — zero risk, fills this panel instantly.
          </p>
        </div>
      </div>
    );
  }
  const dirEntries = Object.entries(insights.by_direction);
  const sessEntries = Object.entries(insights.by_session).filter(([k]) => k !== "Unknown");
  return (
    <div className="glass-bright rounded-2xl p-5">
      <div className="flex items-start justify-between">
        <SectionHeader title="Trade Insights" sub={`${insights.total_trades} trades · ${insights.scope ?? "all-time"} · expectancy $${insights.overall.expectancy.toFixed(0)}/trade`} />
        <div className="flex items-center gap-2">
          <button onClick={onRun} disabled={running} className="btn-cyan px-3 py-1.5 rounded-lg text-[10px] disabled:opacity-50">
            {running ? "RUNNING..." : "↻ RE-RUN"}
          </button>
          <button onClick={onReset} disabled={running} className="px-3 py-1.5 rounded-lg text-[10px] font-mono-hud disabled:opacity-50"
            style={{ background: "#0a1525", border: "1px solid #1a2d4a", color: "#475569" }}>
            CLEAR
          </button>
        </div>
      </div>
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
      {/* Head-to-head: which instrument is carrying the edge */}
      <InstrumentCompare bySymbol={insights.by_symbol} />

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

/* ── THE FUNNEL ──
   bars evaluated → setups found → rejected → trades taken.
   Exists because "no trades" has two causes that used to look identical:
   a quiet market, and an engine silently discarding every setup it found.
   One of those cost this project 25 days. The middle number is the point. */
function FunnelPanel({ f }: { f: Funnel | null }) {
  if (!f) return null;
  const c = f.campaign;
  const warn = f.verdict.startsWith("⚠");
  const stages = [
    { label: "BARS EVALUATED", value: c.bars, color: "#475569",
      hint: "completed 5m candles the strategy judged" },
    { label: "SETUPS FOUND", value: c.signals, color: "#00d4ff",
      hint: "two-indications patterns that fired" },
    { label: "REJECTED", value: c.rejected, color: c.rejected > 0 ? "#ffaa00" : "#334155",
      hint: "turned away by a risk gate — reasons below" },
    { label: "TRADES TAKEN", value: c.taken, color: c.taken > 0 ? "#00ff88" : "#334155",
      hint: "actually sent to the broker" },
  ];
  const max = Math.max(1, c.bars);

  return (
    <div className="glass-bright rounded-2xl p-5">
      <div className="flex items-start justify-between flex-wrap gap-2 mb-4">
        <div>
          <span className="font-display text-xs font-bold tracking-[0.3em] uppercase" style={{ color: "#00d4ff" }}>
            ◆ The Funnel
          </span>
          <p className="text-[10px] font-mono-hud mt-1" style={{ color: "#475569" }}>
            why the engine is or isn&apos;t trading · {f.scope}
          </p>
        </div>
        <div className="text-right">
          <span className="text-[9px] tracking-widest uppercase font-mono-hud block" style={{ color: "#334155" }}>
            conversion
          </span>
          <span className="text-lg font-bold font-mono-hud" style={{ color: "#00d4ff" }}>
            {f.conversion_pct}%
          </span>
        </div>
      </div>

      <div className="space-y-2 mb-4">
        {stages.map((s) => (
          <div key={s.label} className="flex items-center gap-3" title={s.hint}>
            <span className="text-[9px] font-mono-hud tracking-widest w-32 shrink-0" style={{ color: "#475569" }}>
              {s.label}
            </span>
            <div className="flex-1 h-6 rounded-md overflow-hidden relative" style={{ background: "#0a1525" }}>
              <div style={{
                width: `${Math.max(s.value > 0 ? 4 : 0, (s.value / max) * 100)}%`,
                height: "100%",
                background: `linear-gradient(90deg, ${s.color}55, ${s.color})`,
                boxShadow: s.value > 0 ? `0 0 10px ${s.color}66` : "none",
                borderRadius: 6, transition: "width 0.8s ease",
              }} />
              <span className="absolute inset-0 flex items-center px-2 text-[11px] font-mono-hud font-bold"
                    style={{ color: s.value > 0 ? "#fff" : "#334155" }}>
                {s.value.toLocaleString()}
              </span>
            </div>
            <span className="text-[9px] font-mono-hud w-16 text-right shrink-0" style={{ color: "#334155" }}>
              today {(f.today as any)[s.label === "BARS EVALUATED" ? "bars"
                : s.label === "SETUPS FOUND" ? "signals"
                : s.label === "REJECTED" ? "rejected" : "taken"]}
            </span>
          </div>
        ))}
      </div>

      <div className="rounded-xl p-3 mb-3" style={{
        background: warn ? "#ffaa0012" : "#00ff8810",
        border: `1px solid ${warn ? "#ffaa0044" : "#00ff8833"}`,
      }}>
        <p className="text-[11px] font-mono-hud leading-relaxed" style={{ color: warn ? "#ffaa00" : "#00ff88" }}>
          {f.verdict}
        </p>
      </div>

      {Object.keys(f.rejection_reasons || {}).length > 0 && (
        <div>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud mb-1.5" style={{ color: "#334155" }}>
            why signals were turned away
          </p>
          <div className="space-y-1">
            {Object.entries(f.rejection_reasons).map(([reason, n]) => (
              <div key={reason} className="flex items-center justify-between text-[10px] font-mono-hud">
                <span style={{ color: "#94a3b8" }}>{reason}</span>
                <span style={{ color: "#ffaa00" }}>×{n}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── LIVE POSITION — when a trade is open, it should dominate ── */
function LivePositionCard({ trades }: { trades: Trade[] }) {
  const open = trades.filter((t) => t.status === "open");
  if (open.length === 0) return null;

  return (
    <div className="space-y-3">
      {open.map((t) => {
        const long = t.side === "long";
        const risk = Math.abs((t.entry_price ?? 0) - (t.stop_loss ?? 0));
        const cur = t.exit_price ?? t.entry_price ?? 0;
        const move = long ? cur - (t.entry_price ?? 0) : (t.entry_price ?? 0) - cur;
        const r = risk > 0 ? move / risk : 0;
        const target = t.take_profit ?? 0;
        const targetR = risk > 0 ? Math.abs(target - (t.entry_price ?? 0)) / risk : 2;
        const pct = Math.max(0, Math.min(100, (r / (targetR || 2)) * 100));
        const good = r >= 0;
        const color = good ? "#00ff88" : "#ff3366";
        return (
          <div key={t.id} className="rounded-2xl p-5"
               style={{ background: "radial-gradient(ellipse at 20% 0%, #10243f 0%, #080e1a 70%)",
                        border: `1px solid ${color}44`, boxShadow: `0 0 40px ${color}18` }}>
            <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
              <div className="flex items-center gap-3">
                <span className="px-2.5 py-1 rounded-lg text-[11px] font-display font-bold"
                      style={{ background: `${color}22`, border: `1px solid ${color}55`, color }}>
                  {long ? "▲ LONG" : "▼ SHORT"}
                </span>
                <span className="text-xl font-bold font-mono-hud text-white">{t.symbol}</span>
                <span className="text-[11px] font-mono-hud" style={{ color: "#475569" }}>×{t.qty}</span>
                <span className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
                      style={{ background: "#00d4ff18", border: "1px solid #00d4ff44", color: "#00d4ff",
                               animation: "green-pulse 2s infinite" }}>
                  POSITION OPEN
                </span>
              </div>
              <div className="text-right">
                <span className="text-2xl font-bold font-mono-hud" style={{ color, textShadow: `0 0 16px ${color}88` }}>
                  {r >= 0 ? "+" : ""}{r.toFixed(2)}R
                </span>
              </div>
            </div>

            <div className="h-3 rounded-full overflow-hidden mb-2 relative" style={{ background: "#0a1525" }}>
              <div style={{ width: `${pct}%`, height: "100%",
                            background: `linear-gradient(90deg, ${color}66, ${color})`,
                            boxShadow: `0 0 10px ${color}`, borderRadius: 9999,
                            transition: "width 1s ease" }} />
            </div>
            <div className="flex justify-between text-[9px] font-mono-hud mb-4" style={{ color: "#334155" }}>
              <span>STOP {t.stop_loss?.toFixed(2)}</span>
              <span>ENTRY {t.entry_price?.toFixed(2)}</span>
              <span>TARGET {target.toFixed(2)} ({targetR.toFixed(1)}R)</span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { l: "Entry", v: `$${t.entry_price?.toFixed(2)}` },
                { l: "Current", v: `$${cur.toFixed(2)}` },
                { l: "Unrealized", v: `${(t.pnl ?? 0) >= 0 ? "+" : ""}$${(t.pnl ?? 0).toFixed(2)}`,
                  c: (t.pnl ?? 0) >= 0 ? "#00ff88" : "#ff3366" },
                { l: "Risk", v: `$${(risk * (t.symbol === "MNQ" ? 2 : 5) * t.qty).toFixed(0)}` },
              ].map((x) => (
                <div key={x.l} className="rounded-xl py-2 px-3" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
                  <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>{x.l}</p>
                  <p className="text-sm font-bold font-mono-hud mt-0.5" style={{ color: x.c ?? "#e2e8f0" }}>{x.v}</p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
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

/* ── 60-day forward-test campaign tracker ── */
function ForwardTestCard({ fwt }: { fwt: ForwardTest | null }) {
  if (!fwt?.active) return null;
  const day = fwt.day ?? 1;
  const target = fwt.target_days ?? 60;
  const pct = Math.min(100, fwt.pct_complete ?? 0);
  const pnl = fwt.total_pnl ?? 0;
  const pnlColor = pnl >= 0 ? "#00ff88" : "#ff3366";
  const uptime = fwt.uptime_today_pct ?? 0;
  const uptimeColor = uptime >= 90 ? "#00ff88" : uptime >= 50 ? "#ffaa00" : "#ff3366";
  const curve = (fwt.snapshots ?? []).map((s) => ({ date: s.date, equity: s.equity }));

  return (
    <div className="glass-bright rounded-2xl p-5">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <div className="flex items-center gap-3">
          <span className="font-display text-xs font-bold tracking-[0.3em] uppercase" style={{ color: "#00d4ff" }}>
            ◆ Forward Test · {target}-Day Track Record
          </span>
          <span
            className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
            style={{ background: "#7c3aed22", border: "1px solid #7c3aed44", color: "#a78bfa" }}
            title={`Campaign started ${fwt.start_date}. The start date never moves — that's what makes this an audited record.`}
          >
            DAY {day} / {target}
          </span>
          {fwt.strategy && (
            <span className="text-[9px] font-mono-hud tracking-widest uppercase" style={{ color: "#475569" }}>
              {fwt.strategy} · {(fwt.symbols ?? []).join(" + ")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-[10px] font-mono-hud">
          <span style={{ color: "#475569" }}>
            since {fwt.start_date} · uptime today{" "}
            <span style={{ color: uptimeColor, fontWeight: 700 }}>{uptime.toFixed(0)}%</span>
          </span>
        </div>
      </div>

      {/* Day progress bar */}
      <div className="h-2 rounded-full overflow-hidden mb-4" style={{ background: "#0a1525" }}>
        <div
          style={{
            width: `${pct}%`, height: "100%",
            background: "linear-gradient(90deg,#7c3aed,#00d4ff)",
            boxShadow: "0 0 8px #00d4ff",
            borderRadius: "9999px",
            transition: "width 0.8s ease",
          }}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-xl py-3 px-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>Campaign P&L</p>
          <p className="text-lg font-bold font-mono-hud mt-0.5" style={{ color: pnlColor, textShadow: `0 0 12px ${pnlColor}88` }}>
            {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
          </p>
        </div>
        <div className="rounded-xl py-3 px-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>Equity</p>
          <p className="text-lg font-bold font-mono-hud mt-0.5" style={{ color: "#00d4ff" }}>
            ${(fwt.current_equity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </p>
        </div>
        <div className="rounded-xl py-3 px-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
          <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>Trades · Win Rate</p>
          <p className="text-lg font-bold font-mono-hud mt-0.5" style={{ color: "#a78bfa" }}>
            {fwt.trades_closed ?? 0} · {(fwt.win_rate ?? 0).toFixed(0)}%
          </p>
        </div>
        <div className="rounded-xl py-2 px-2" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
          {curve.length > 1 ? (
            <ResponsiveContainer width="100%" height={56}>
              <AreaChart data={curve} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="fwtGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#7c3aed" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={["dataMin", "dataMax"]} />
                <Tooltip
                  contentStyle={{ background: "#0d1525", border: "1px solid #1a2d4a", borderRadius: 10, fontSize: 10, fontFamily: "JetBrains Mono" }}
                  formatter={(v: number) => [`$${v.toFixed(0)}`, "equity"]}
                />
                <Area type="monotone" dataKey="equity" stroke="#a78bfa" strokeWidth={1.5} fill="url(#fwtGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-[9px] font-mono-hud" style={{ color: "#334155" }}>
              EQUITY CURVE BUILDS DAILY
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   THE RECORD — the credible view.
   No gauges, no telemetry, no live drama. Just the numbers someone with money
   asks for: equity curve, drawdown, R distribution, session breakdown, and
   the backtest baseline this campaign exists to test. Boring on purpose;
   boring is what credible looks like.
   ══════════════════════════════════════════════════════════════════════════ */
function StatCell({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl py-3 px-4" style={{ background: "#0a1525", border: "1px solid #1a2d4a" }}>
      <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>{label}</p>
      <p className="text-lg font-bold font-mono-hud mt-0.5" style={{ color: color ?? "#e2e8f0" }}>{value}</p>
      {sub && <p className="text-[9px] font-mono-hud mt-0.5" style={{ color: "#334155" }}>{sub}</p>}
    </div>
  );
}

function GroupTable({ title, groups }: { title: string; groups: Record<string, RecordGroup> }) {
  const rows = Object.entries(groups).sort((a, b) => b[1].pnl - a[1].pnl);
  if (!rows.length) return null;
  return (
    <div>
      <p className="text-[9px] tracking-widest uppercase font-mono-hud mb-2" style={{ color: "#475569" }}>{title}</p>
      <div className="rounded-xl overflow-hidden" style={{ border: "1px solid #1a2d4a" }}>
        <table className="w-full text-[11px] font-mono-hud">
          <thead>
            <tr style={{ background: "#0a1525", color: "#334155" }}>
              <th className="text-left px-3 py-2 font-normal">Group</th>
              <th className="text-right px-3 py-2 font-normal">Trades</th>
              <th className="text-right px-3 py-2 font-normal">Win %</th>
              <th className="text-right px-3 py-2 font-normal">Net P&L</th>
              <th className="text-right px-3 py-2 font-normal">$/trade</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, g]) => (
              <tr key={k} style={{ borderTop: "1px solid #1a2d4a" }}>
                <td className="px-3 py-2" style={{ color: "#e2e8f0" }}>{k}</td>
                <td className="px-3 py-2 text-right" style={{ color: "#94a3b8" }}>{g.trades}</td>
                <td className="px-3 py-2 text-right" style={{ color: "#94a3b8" }}>{g.win_rate}%</td>
                <td className="px-3 py-2 text-right font-bold" style={{ color: g.pnl >= 0 ? "#00ff88" : "#ff3366" }}>
                  {g.pnl >= 0 ? "+" : ""}${g.pnl.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: g.expectancy >= 0 ? "#00ff88" : "#ff3366" }}>
                  {g.expectancy >= 0 ? "+" : ""}${g.expectancy.toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RecordView({ rec }: { rec: TradeRecord | null }) {
  if (!rec) {
    return <div className="glass-bright rounded-2xl p-10 text-center text-xs font-mono-hud"
                style={{ color: "#334155" }}>LOADING RECORD…</div>;
  }
  const s = rec.summary;
  const n = s.trades;

  // Live vs backtest expectation, drawn on the same axis. This is the single
  // question the whole 60-day campaign exists to answer.
  const curve = rec.curve.map((p) => ({
    ...p,
    expected: rec.expected
      ? rec.start_equity + (rec.expected.expectancy * p.n)
      : undefined,
  }));

  const pf = s.profit_factor;
  const pfStr = Number.isFinite(pf) ? pf.toFixed(2) : "∞";
  const sampleWarn = n < 30;

  return (
    <div className="space-y-6">
      {/* Header + honesty banner */}
      <div className="glass-bright rounded-2xl p-5">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <h2 className="font-display text-sm font-bold tracking-[0.25em] uppercase" style={{ color: "#e2e8f0" }}>
              Forward-Test Record
            </h2>
            <p className="text-[11px] font-mono-hud mt-1" style={{ color: "#475569" }}>
              {rec.scope} · day {rec.days_elapsed} of {rec.target_days} · paper · MNQ
            </p>
          </div>
          <div className="text-right">
            <p className="text-[9px] tracking-widest uppercase font-mono-hud" style={{ color: "#334155" }}>net p&l</p>
            <p className="text-2xl font-bold font-mono-hud"
               style={{ color: s.net_pnl >= 0 ? "#00ff88" : "#ff3366" }}>
              {s.net_pnl >= 0 ? "+" : ""}${s.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
            <p className="text-[10px] font-mono-hud" style={{ color: "#475569" }}>
              {s.return_pct >= 0 ? "+" : ""}{s.return_pct}% on ${rec.start_equity.toLocaleString()}
            </p>
          </div>
        </div>
        {sampleWarn && (
          <div className="mt-4 rounded-xl p-3" style={{ background: "#ffaa0010", border: "1px solid #ffaa0033" }}>
            <p className="text-[11px] font-mono-hud" style={{ color: "#ffaa00" }}>
              ⚠ SAMPLE TOO SMALL — {n} trade{n === 1 ? "" : "s"}. At a ~41% win rate these figures are
              dominated by variance, not edge. Treat as provisional until ~40 trades.
            </p>
          </div>
        )}
      </div>

      {/* The numbers */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCell label="Trades" value={`${n}`} sub={`${s.wins}W / ${s.losses}L`} />
        <StatCell label="Win Rate" value={`${s.win_rate}%`} color="#00d4ff" />
        <StatCell label="Profit Factor" value={pfStr} color={pf >= 1 ? "#00ff88" : "#ff3366"}
                  sub="gross win ÷ gross loss" />
        <StatCell label="Expectancy" value={`${s.expectancy >= 0 ? "+" : ""}$${s.expectancy.toFixed(0)}`}
                  color={s.expectancy >= 0 ? "#00ff88" : "#ff3366"} sub="per trade" />
        <StatCell label="Max Drawdown" value={`-$${s.max_drawdown.toFixed(0)}`} color="#ff3366"
                  sub={`${s.max_drawdown_pct}% of account`} />
        <StatCell label="Payoff" value={`${s.payoff.toFixed(2)}x`} color="#a78bfa"
                  sub={`avg win $${s.avg_win.toFixed(0)} / loss $${Math.abs(s.avg_loss).toFixed(0)}`} />
      </div>

      {/* Equity + expectation overlay */}
      <div className="glass-bright rounded-2xl p-5">
        <SectionHeader
          title="Equity Curve vs Backtest Expectation"
          sub={rec.expected
            ? `dashed = what the backtest predicts ($${rec.expected.expectancy.toFixed(0)}/trade)`
            : "run scripts/v2_backtest.py --save-baseline to overlay the backtest"}
        />
        {curve.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={curve} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00ff88" stopOpacity={0.28} />
                  <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#12213a" strokeDasharray="3 3" />
              <XAxis dataKey="n" tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }}
                     label={{ value: "trade #", position: "insideBottom", offset: -2,
                              style: { fontSize: 9, fill: "#334155" } }} />
              <YAxis tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }}
                     domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "#0d1525", border: "1px solid #1a2d4a",
                                       borderRadius: 10, fontSize: 11, fontFamily: "JetBrains Mono" }}
                       formatter={(v: number, name: string) => [`$${Number(v).toFixed(2)}`, name]} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <ReferenceLine y={rec.start_equity} stroke="#334155" strokeDasharray="4 4" />
              <Area type="monotone" dataKey="equity" name="live" stroke="#00ff88" strokeWidth={2}
                    fill="url(#eqGrad)" dot={{ r: 2, fill: "#00ff88" }} />
              {rec.expected && (
                <Line type="monotone" dataKey="expected" name="backtest expectation" stroke="#a78bfa"
                      strokeWidth={1.5} strokeDasharray="5 4" dot={false} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-52 flex items-center justify-center text-xs font-mono-hud" style={{ color: "#1a2d4a" }}>
            NO CLOSED TRADES YET
          </div>
        )}
      </div>

      {/* Underwater + R distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="glass-bright rounded-2xl p-5">
          <SectionHeader title="Drawdown (Underwater)" sub="distance below the equity high-water mark" />
          {curve.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={curve} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff3366" stopOpacity={0} />
                    <stop offset="95%" stopColor="#ff3366" stopOpacity={0.35} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#12213a" strokeDasharray="3 3" />
                <XAxis dataKey="n" tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }} />
                <YAxis tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }} />
                <Tooltip contentStyle={{ background: "#0d1525", border: "1px solid #1a2d4a",
                                         borderRadius: 10, fontSize: 11, fontFamily: "JetBrains Mono" }}
                         formatter={(v: number) => [`$${Number(v).toFixed(2)}`, "drawdown"]} />
                <ReferenceLine y={0} stroke="#334155" />
                <Area type="monotone" dataKey="drawdown" stroke="#ff3366" strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-48 flex items-center justify-center text-xs font-mono-hud" style={{ color: "#1a2d4a" }}>—</div>
          )}
        </div>

        <div className="glass-bright rounded-2xl p-5">
          <SectionHeader title="R-Multiple Distribution"
                         sub={rec.summary.avg_r != null ? `average ${rec.summary.avg_r}R per trade` : "shape of the edge"} />
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={rec.r_distribution} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid stroke="#12213a" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 8, fill: "#334155", fontFamily: "JetBrains Mono" }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 9, fill: "#334155", fontFamily: "JetBrains Mono" }} />
              <Tooltip cursor={{ fill: "#ffffff08" }}
                       contentStyle={{ background: "#0d1525", border: "1px solid #1a2d4a",
                                       borderRadius: 10, fontSize: 11, fontFamily: "JetBrains Mono" }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {rec.r_distribution.map((d, i) => (
                  <Cell key={i} fill={d.bucket.startsWith("-") || d.bucket.startsWith("≤") ? "#ff3366" : "#00ff88"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Breakdowns */}
      <div className="glass-bright rounded-2xl p-5 space-y-5">
        <SectionHeader title="Breakdown" sub="where the record comes from" />
        <GroupTable title="By Session" groups={rec.by_session} />
        <GroupTable title="By Direction" groups={rec.by_direction} />
        <GroupTable title="By Instrument" groups={rec.by_symbol} />
      </div>

      {/* Baseline */}
      {rec.baseline && (
        <div className="glass-bright rounded-2xl p-5">
          <SectionHeader title="Backtest Baseline"
                         sub={`${rec.baseline.symbol ?? "MNQ"} · ${rec.baseline.period ?? "30d"} · the target this record is measured against`} />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCell label="Trades" value={`${rec.baseline.total_trades}`} sub={`over ${rec.baseline.days} days`} />
            <StatCell label="Win Rate" value={`${rec.baseline.win_rate}%`} color="#a78bfa" />
            <StatCell label="Profit Factor" value={rec.baseline.profit_factor?.toFixed(2) ?? "—"} color="#a78bfa" />
            <StatCell label="Net P&L" value={`$${rec.baseline.total_pnl.toLocaleString()}`} color="#a78bfa" />
          </div>
        </div>
      )}
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
  const [fwt,          setFwt]          = useState<ForwardTest | null>(null);
  const [funnel,       setFunnel]       = useState<Funnel | null>(null);
  const [rec,          setRec]          = useState<TradeRecord | null>(null);
  const [view,         setView]         = useState<"cockpit" | "record">("cockpit");
  const [trading,      setTrading]      = useState(false);
  const [closing,      setClosing]      = useState(false);
  const [fwRunning,    setFwRunning]    = useState(false);
  const [now,          setNow]          = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, t, tr, sg, ps, pf, dh, ins, fw, fn, rc] = await Promise.allSettled([
        api("/api/status"), api("/api/stats/today"), api("/api/trades/today"),
        api("/api/signals?limit=10"), api("/api/prop-firm/status"),
        api("/api/stats/performance"), api("/api/stats/daily"),
        api("/api/stats/insights"), api("/api/forward-test/status"),
        api("/api/funnel"), api("/api/record"),
      ]);
      if (s.status  === "fulfilled") setStatus(s.value);
      if (t.status  === "fulfilled") setTodayStats(t.value);
      if (tr.status === "fulfilled") setTrades(tr.value);
      if (sg.status === "fulfilled") setSignals(sg.value);
      if (ps.status === "fulfilled") setPropStatus(ps.value);
      if (pf.status === "fulfilled") setPerf(pf.value);
      if (dh.status === "fulfilled") setDailyHistory(dh.value.slice(0, 30).reverse());
      if (ins.status === "fulfilled") setInsights(ins.value);
      if (fw.status === "fulfilled") setFwt(fw.value);
      if (fn.status === "fulfilled") setFunnel(fn.value);
      if (rc.status === "fulfilled") setRec(rc.value);
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

  async function runForwardTest() {
    setFwRunning(true);
    try {
      const res = await fetch(`${API}/api/forward-test/run?period=30d`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`Forward-test failed: ${err.detail ?? "see backend logs (market data must be reachable)"}`);
      }
      await load();
    } catch (e) {
      alert("Forward-test request failed — is the backend running with market-data access?");
    } finally { setFwRunning(false); }
  }

  async function resetForwardTest() {
    if (!confirm("Clear all paper forward-test trades?")) return;
    setFwRunning(true);
    try {
      const res = await fetch(`${API}/api/forward-test/reset`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail ?? "Reset refused.");
      }
      await load();
    } finally { setFwRunning(false); }
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
            <EngineStatePill status={status} />
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

      {/* ── View switcher: two audiences, two screens ──
           COCKPIT = "is my machine healthy?"  (operator)
           RECORD  = "is this strategy credible?" (partner / prop firm) */}
      <div className="max-w-screen-2xl mx-auto px-4 md:px-6 pt-4">
        <div className="flex items-center gap-2">
          {([
            { id: "cockpit", label: "COCKPIT", sub: "live telemetry" },
            { id: "record",  label: "THE RECORD", sub: "the audited case" },
          ] as const).map((v) => {
            const on = view === v.id;
            return (
              <button
                key={v.id}
                onClick={() => setView(v.id)}
                className="px-4 py-2 rounded-xl text-left transition-all"
                style={{
                  background: on ? "#00d4ff14" : "#0a1525",
                  border: `1px solid ${on ? "#00d4ff55" : "#1a2d4a"}`,
                  boxShadow: on ? "0 0 20px #00d4ff22" : "none",
                }}
              >
                <span className="block text-[11px] font-display font-bold tracking-[0.2em]"
                      style={{ color: on ? "#00d4ff" : "#475569" }}>
                  {v.label}
                </span>
                <span className="block text-[9px] font-mono-hud" style={{ color: on ? "#00d4ff88" : "#334155" }}>
                  {v.sub}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {view === "record" ? (
        <main className="max-w-screen-2xl mx-auto px-4 md:px-6 py-6">
          <RecordView rec={rec} />
        </main>
      ) : (
      <>
      {/* ── Global session clock ── */}
      <div className="max-w-screen-2xl mx-auto px-4 md:px-6 pt-4">
        <SessionBar sessions={status?.sessions} nowEt={status?.now_et} />
      </div>

      {/* ── Main content ── */}
      <main className="max-w-screen-2xl mx-auto px-4 md:px-6 py-6 space-y-6">

        {/* ── Live position — dominates when a trade is working ── */}
        <LivePositionCard trades={trades} />

        {/* ── The Funnel — why the engine is or isn't trading ── */}
        <FunnelPanel f={funnel} />

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
                status?.orb_window_active ? (
                  <span
                    className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
                    style={{ background: "#00ff8822", border: "1px solid #00ff8844", color: "#00ff88", animation: "green-pulse 2s infinite" }}
                  >
                    {status?.strategy === "multi_session" ? "LIVE · SESSION WINDOW" : "LIVE · NY SESSION"}
                  </span>
                ) : status?.orb_after_cutoff ? (
                  <span
                    className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
                    style={{ background: "#ffaa0018", border: "1px solid #ffaa0044", color: "#ffaa00" }}
                    title="ORB cutoff reached (14:00 ET). No new entries today — re-arms tomorrow at 9:35 AM ET."
                  >
                    ARMED · DONE FOR TODAY
                  </span>
                ) : (
                  <span
                    className="px-2 py-0.5 rounded-full text-[9px] font-mono-hud font-bold tracking-widest"
                    style={{ background: "#ffaa0018", border: "1px solid #ffaa0044", color: "#ffaa00" }}
                    title={status?.strategy === "multi_session"
                      ? "Engine armed — waiting for the next V2 window (Asia kill zone 8 PM / London 4 AM / NY 9 AM ET)."
                      : "Engine armed — ORB window opens at 9:35 AM ET."}
                  >
                    {status?.strategy === "multi_session" ? "ARMED · NEXT WINDOW SOON" : "ARMED · WAITING FOR ORB OPEN"}
                  </span>
                )
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

        {/* ── 60-Day Forward Test ── */}
        <ForwardTestCard fwt={fwt} />

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
            <div className="flex items-start justify-between">
              <SectionHeader title="AI Signals" sub="latest high-confidence setups" />
              <ScanActivity status={status} />
            </div>
            {signals.length === 0 ? (
              <div className="h-40 flex flex-col items-center justify-center gap-2">
                <div className="text-2xl" style={{ color: "#1a2d4a" }}>◉</div>
                <p className="text-xs font-mono-hud tracking-widest" style={{ color: "#1a2d4a" }}>
                  {status?.trading_enabled
                    ? status?.orb_window_active
                      ? status?.strategy === "multi_session"
                        ? "WATCHING FOR TWO-INDICATIONS SETUP..."
                        : "WATCHING FOR ORB SETUP..."
                      : status?.orb_after_cutoff
                        ? "ORB CUTOFF · DONE FOR TODAY · RE-ARMS 9:35 AM ET"
                        : status?.strategy === "multi_session"
                          ? "ARMED · NEXT WINDOW: ASIA 8PM / LONDON 4AM / NY 9AM ET"
                          : "ARMED · ORB OPENS AT 9:35 AM ET"
                    : "ENGINE NOT ARMED · CLICK START TRADING"}
                </p>
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
        <InsightsPanel insights={insights} onRun={runForwardTest} onReset={resetForwardTest} running={fwRunning} />

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
      </>
      )}
    </div>
  );
}
