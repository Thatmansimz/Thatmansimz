"use client";
import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DailyPoint = {
  date: string;
  pnl: number;
  trades_count: number;
  wins: number;
  losses: number;
  win_rate: number;
};

type ViewMode = "daily" | "cumulative";

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0]?.value;
  const positive = value >= 0;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs shadow-xl">
      <p className="text-slate-400 mb-1">{label}</p>
      <p className={positive ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
        {positive ? "+" : ""}${value?.toFixed(2)}
      </p>
    </div>
  );
};

export default function PnLChart() {
  const [data, setData] = useState<DailyPoint[]>([]);
  const [mode, setMode] = useState<ViewMode>("daily");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/stats/daily`, { cache: "no-store" });
        if (res.ok) {
          const raw: DailyPoint[] = await res.json();
          setData(raw.slice(0, 30).reverse());
        }
      } catch (_) {}
      setLoading(false);
    }
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);

  const chartData = (() => {
    if (mode === "cumulative") {
      let cum = 0;
      return data.map((d) => ({ ...d, value: (cum += d.pnl) }));
    }
    return data.map((d) => ({ ...d, value: d.pnl }));
  })();

  const totalPnl = data.reduce((s, d) => s + d.pnl, 0);
  const bestDay = data.reduce((b, d) => (d.pnl > b ? d.pnl : b), -Infinity);
  const worstDay = data.reduce((w, d) => (d.pnl < w ? d.pnl : w), Infinity);
  const positive = totalPnl >= 0;

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-white">P&L Chart</h2>
          <div className="flex items-center gap-3 text-[10px] text-slate-500 mt-0.5">
            <span>
              Total:{" "}
              <span className={positive ? "text-emerald-400" : "text-rose-400"}>
                {positive ? "+" : ""}${totalPnl.toFixed(2)}
              </span>
            </span>
            <span>Best: <span className="text-emerald-400">${bestDay === -Infinity ? "—" : bestDay.toFixed(2)}</span></span>
            <span>Worst: <span className="text-rose-400">${worstDay === Infinity ? "—" : worstDay.toFixed(2)}</span></span>
          </div>
        </div>
        <div className="flex gap-1">
          {(["daily", "cumulative"] as ViewMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={[
                "px-2.5 py-1 rounded text-xs transition",
                mode === m ? "bg-slate-600 text-white" : "text-slate-500 hover:text-slate-300",
              ].join(" ")}
            >
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-48 flex items-center justify-center text-slate-600 text-sm">Loading...</div>
      ) : data.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-slate-600 text-sm">No data yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData} margin={{ top: 8, right: 4, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="pnlGradientNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 9, fill: "#64748b" }}
              tickFormatter={(v) => v.slice(5)}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: "#64748b" }}
              tickFormatter={(v) => `$${v}`}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0} stroke="#334155" strokeDasharray="4 4" />
            <Area
              type="monotone"
              dataKey="value"
              stroke={positive ? "#34d399" : "#f43f5e"}
              strokeWidth={2}
              fill={positive ? "url(#pnlGradient)" : "url(#pnlGradientNeg)"}
              dot={false}
              activeDot={{ r: 4, fill: positive ? "#34d399" : "#f43f5e" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
