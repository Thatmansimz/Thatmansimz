"use client";
/**
 * Dashboard component — composites all sub-panels into the main trading view.
 * Used as an importable component; the main page.tsx renders this directly.
 */
import { Suspense } from "react";
import TradeMonitor from "./TradeMonitor";
import SignalPanel from "./SignalPanel";
import PnLChart from "./PnLChart";
import RiskGauge from "./RiskGauge";
import PropFirmConfig from "./PropFirmConfig";

function LoadingCard({ height = "h-48" }: { height?: string }) {
  return (
    <div
      className={[
        "bg-slate-900 border border-slate-700/50 rounded-xl",
        height,
        "flex items-center justify-center text-slate-700 text-sm animate-pulse",
      ].join(" ")}
    >
      Loading...
    </div>
  );
}

export default function Dashboard() {
  return (
    <div className="space-y-5">
      {/* Row 1 — P&L chart + Risk gauge */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2">
          <Suspense fallback={<LoadingCard height="h-64" />}>
            <PnLChart />
          </Suspense>
        </div>
        <Suspense fallback={<LoadingCard height="h-64" />}>
          <RiskGauge />
        </Suspense>
      </div>

      {/* Row 2 — Trade monitor (full width) */}
      <Suspense fallback={<LoadingCard height="h-48" />}>
        <TradeMonitor />
      </Suspense>

      {/* Row 3 — AI signals + Prop firm config */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Suspense fallback={<LoadingCard height="h-96" />}>
          <SignalPanel />
        </Suspense>
        <PropFirmConfig />
      </div>
    </div>
  );
}
