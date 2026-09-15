"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, Radio, RefreshCw, ShieldCheck } from "lucide-react";
import { isStale, type PaperStatus } from "../lib/paper-status";

const dollars = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
const date = (value: string | null) => value ? new Date(value).toLocaleString() : "Not received yet";
const stateLabels: Record<string, string> = {
  starting: "Starting", connecting: "Connecting to market data", connected_waiting_for_bar: "Connected · waiting for a minute bar",
  streaming: "Receiving live market data", data_review: "Data needs review · entries paused", disconnected: "Feed disconnected · entries paused",
  halted: "Stopped for review", stopped: "Worker stopped",
};

export default function ContinuousPaper() {
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [message, setMessage] = useState("Checking the continuous paper service…");
  const [refresh, setRefresh] = useState(0);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    const update = async () => {
      if (running) return;
      running = true;
      try {
        const response = await fetch("/api/paper-service", { cache: "no-store", signal: controller.signal });
        const result = await response.json();
        if (controller.signal.aborted) return;
        if (response.ok && result.status) { setStatus(result.status); setMessage(""); }
        else { setStatus(null); setMessage(result.message || "Paper service status unavailable."); }
      } catch {
        if (!controller.signal.aborted) { setStatus(null); setMessage("Could not refresh the paper service. Current status is unavailable."); }
      } finally { running = false; setClock(Date.now()); }
    };
    void update();
    const timer = setInterval(() => { setClock(Date.now()); void update(); }, 30_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [refresh]);
  const stale = status ? isStale(status, clock) : false;
  const needsReview = status?.scenarios.some(s => s.reconciliation === "fail") || ["data_review", "disconnected", "halted", "stopped"].includes(status?.connection || "");
  const baseline = status?.scenarios.find(s => s.name === "baseline");
  return (
    <section className="panel continuous-paper" aria-labelledby="continuous-title">
      <div className="section-title">
        <div><p className="eyebrow">CONTINUOUS PAPER SERVICE</p><h2 id="continuous-title">Real market data. Simulated execution.</h2></div>
        <button className="button" onClick={() => setRefresh(x => x + 1)} aria-label="Refresh continuous paper status"><RefreshCw size={15} /> Refresh</button>
      </div>
      <p>The registered rule observes MNQ minute bars from Databento and records simulated orders in two persistent ledgers. The baseline and worse-cost account use the same arriving events.</p>
      <div className={`notice ${stale || status?.hard_halt || needsReview ? "amber" : ""}`} aria-live="polite">
        <Radio size={20} />
        <p><strong>{status ? (stale ? "Worker report is stale" : stateLabels[status.connection] || "Status unavailable") : "Worker connection"}</strong><br />
          {status ? `Last report: ${date(status.observed_at)}. ${stale ? "These are last-known values; the worker may be offline." : "This view refreshes every 30 seconds."}` : message}
        </p>
      </div>
      {status && baseline && <>
        <div className="metric-grid">
          <article className="metric"><span>Simulated equity · baseline</span><strong>{dollars(baseline.account.equity_cents)}</strong><p>Starting balance {dollars(status.initial_balance_cents)} · last recorded mark</p></article>
          <article className="metric"><span>Completed round trips</span><strong>{baseline.completed_contract_units}</strong><p>{baseline.orders} orders · {baseline.fills} fills · {baseline.account.position} contracts open</p></article>
          <article className="metric"><span>Complete opening opportunities</span><strong>{status.complete_opening_opportunities}</strong><p>{status.observed_opening_dates} opening dates observed · review at 20, without automatic promotion</p></article>
        </div>
        <div className="two-column lower-grid">
          <div><h3>Execution comparison</h3><div className="paper-comparison">
            {status.scenarios.map(s => <article key={s.name}><strong>{s.name === "baseline" ? "Baseline assumptions" : "Worse execution costs"}</strong><b>{dollars(s.account.net_pnl_cents)}</b><span>Realized P&L after all recorded fees</span><span>Reconciliation: {s.reconciliation}{s.risk_halted ? " · risk halt" : ""}</span></article>)}
          </div></div>
          <div><h3>Data and evidence</h3><dl className="paper-facts">
            <div><dt>Contract</dt><dd>{status.contract?.symbol || "Waiting for mapped bars"}</dd></div>
            <div><dt>Last minute bar received</dt><dd>{date(status.last_bar_received_at)}</dd></div>
            <div><dt>Recorded / excluded bars</dt><dd>{status.receipts} / {status.excluded_receipts}</dd></div>
            <div><dt>Last successful reconciliation</dt><dd>{date(status.last_reconciled_at)}</dd></div>
            <div><dt>Latest audit attempt</dt><dd>{date(status.last_audit_attempt_at)}</dd></div>
            <div><dt>Run registered</dt><dd>{date(status.registered_at)}</dd></div>
          </dl></div>
        </div>
        {status.hard_halt && <p className="notice amber">Review required: {status.hard_halt.replaceAll("_", " ")}. This run cannot automatically resume entries.</p>}
      </>}
      <div className="notice amber"><ShieldCheck size={20} /><p><strong>Internal paper simulation · no real-money route</strong><br />The worker runs on the configured host; sleep or loss of connectivity creates a recorded interruption. Fills and protective stops are simulated, with no external broker confirmation. Profitability and all six live-pilot requirements remain unverified.</p></div>
      <div className="hero-actions"><a className="text-button" href="/evidence/continuous-paper-protocol.json" target="_blank" rel="noreferrer">Read the frozen protocol <ArrowUpRight size={15} /></a><a className="text-button" href="/evidence/continuous-paper-service.md" target="_blank" rel="noreferrer">Service guide and current setup <ArrowUpRight size={15} /></a></div>
    </section>
  );
}
