"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Trade = {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: string;
  pnl: number | null;
  net_pnl: number | null;
  ai_confidence: number | null;
  strategy: string | null;
  entry_time: string | null;
  exit_time: string | null;
  exit_reason: string | null;
};

function cn(...c: (string | boolean | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

function PnlCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="text-slate-600">—</span>;
  const positive = value >= 0;
  return (
    <span className={cn("font-semibold", positive ? "text-emerald-400" : "text-rose-400")}>
      {positive ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    open: "bg-blue-900/50 text-blue-300 border-blue-700/50",
    closed: "bg-slate-800 text-slate-400 border-slate-700/50",
    target_hit: "bg-emerald-900/50 text-emerald-400 border-emerald-700/50",
    stopped_out: "bg-rose-900/50 text-rose-400 border-rose-700/50",
    cancelled: "bg-slate-800 text-slate-500 border-slate-700/50",
  };
  return (
    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium border", classes[status] || classes.closed)}>
      {status.replace(/_/g, " ").toUpperCase()}
    </span>
  );
}

export default function TradeMonitor() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [filter, setFilter] = useState<"today" | "open" | "all">("today");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        let url = `${API}/api/trades/today`;
        if (filter === "open") url = `${API}/api/trades?status=open`;
        if (filter === "all") url = `${API}/api/trades?limit=50`;
        const res = await fetch(url, { cache: "no-store" });
        if (res.ok) setTrades(await res.json());
      } catch (_) {}
      setLoading(false);
    }
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, [filter]);

  async function closePosition(id: number) {
    if (!confirm(`Close trade #${id}?`)) return;
    await fetch(`${API}/api/trades/${id}/close`, { method: "POST" });
  }

  const openCount = trades.filter((t) => t.status === "open").length;
  const totalPnl = trades.reduce((sum, t) => sum + (t.net_pnl || t.pnl || 0), 0);

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Trade Monitor</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">
            {trades.length} trades &nbsp;•&nbsp; {openCount} open &nbsp;•&nbsp; Net:{" "}
            <span className={totalPnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
              {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
            </span>
          </p>
        </div>
        <div className="flex gap-1">
          {(["today", "open", "all"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-2.5 py-1 rounded text-xs transition",
                filter === f
                  ? "bg-slate-600 text-white"
                  : "text-slate-500 hover:text-slate-300"
              )}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-600 text-sm">Loading...</div>
      ) : trades.length === 0 ? (
        <div className="text-center py-8 text-slate-600 text-sm">No trades found</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-3">#</th>
                <th className="text-left py-2 pr-3">Symbol</th>
                <th className="text-left py-2 pr-3">Side</th>
                <th className="text-right py-2 pr-3">Qty</th>
                <th className="text-right py-2 pr-3">Entry</th>
                <th className="text-right py-2 pr-3">Exit</th>
                <th className="text-right py-2 pr-3">Stop</th>
                <th className="text-right py-2 pr-3">Target</th>
                <th className="text-right py-2 pr-3">Net P&L</th>
                <th className="text-center py-2 pr-3">Status</th>
                <th className="text-right py-2 pr-3">AI</th>
                <th className="text-right py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-slate-800/40 hover:bg-slate-800/20 transition">
                  <td className="py-2 pr-3 text-slate-600">{t.id}</td>
                  <td className="py-2 pr-3 font-semibold text-white">{t.symbol}</td>
                  <td className={cn("py-2 pr-3 font-medium", t.side === "long" ? "text-emerald-400" : "text-rose-400")}>
                    {t.side.toUpperCase()}
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-300">{t.qty}</td>
                  <td className="py-2 pr-3 text-right text-slate-300">{t.entry_price?.toFixed(2)}</td>
                  <td className="py-2 pr-3 text-right text-slate-400">{t.exit_price?.toFixed(2) || "—"}</td>
                  <td className="py-2 pr-3 text-right text-rose-400/70">{t.stop_loss?.toFixed(2) || "—"}</td>
                  <td className="py-2 pr-3 text-right text-emerald-400/70">{t.take_profit?.toFixed(2) || "—"}</td>
                  <td className="py-2 pr-3 text-right">
                    <PnlCell value={t.net_pnl ?? t.pnl} />
                  </td>
                  <td className="py-2 pr-3 text-center">
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="py-2 pr-3 text-right text-slate-500">
                    {t.ai_confidence ? `${Math.round(t.ai_confidence * 100)}%` : "—"}
                  </td>
                  <td className="py-2 text-right">
                    {t.status === "open" && (
                      <button
                        onClick={() => closePosition(t.id)}
                        className="px-2 py-0.5 rounded text-[10px] bg-rose-900/40 text-rose-400 hover:bg-rose-800 border border-rose-700/40 transition"
                      >
                        Close
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
