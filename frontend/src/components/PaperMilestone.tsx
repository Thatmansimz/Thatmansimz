import { ArrowUpRight, CheckCircle2, FlaskConical } from "lucide-react";
import milestone from "../data/paper-milestone.json";

const titles: Record<string, string> = {
  baseline: "Baseline · 1 contract",
  crash_after_accept: "Crash after order acceptance",
  crash_after_fill: "Crash after simulator fill",
  disconnect: "Worker disconnected",
  entry_rejected: "Entry rejected",
  protection_rejected: "Protective bracket rejected",
  partial_fills: "Partial fills · 2-contract test",
  worse_costs: "Higher fees + worse slippage",
  longer_latency: "Longer order delay",
  missing_market_event: "Missing opening minute",
};
const usd = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );

export default function PaperMilestone() {
  const baseline = milestone.scenarios.find((row) => row.case === "baseline")!;
  const passed = milestone.scenarios.filter(
    (row) => row.status === "pass",
  ).length;
  return (
    <section
      className="panel paper-milestone"
      aria-labelledby="milestone-title"
    >
      <div className="section-title">
        <div>
          <p className="eyebrow">ENGINEERING RESULT · SEPTEMBER 11, 2026</p>
          <h2 id="milestone-title">The first paper cycle reconciles.</h2>
        </div>
        <span className="badge neutral">
          <FlaskConical size={14} /> Historical replay
        </span>
      </div>
      <p>
        We tested a frozen rule on paid MNQ research data from January 3–7,
        2022. A separate verifier checked order eligibility, fills, positions
        and every cent against the simulator’s ledger. This is an internal
        engineering test, not a broker-connected forward run.
      </p>
      <div className="metric-grid">
        <article className="metric">
          <span>Reconciliation scenarios</span>
          <strong>
            {passed} <small>/ {milestone.scenarios.length}</small>
          </strong>
          <p>Includes real process crashes and restarts</p>
        </article>
        <article className="metric">
          <span>Baseline round trips</span>
          <strong>{baseline.completed_contract_units}</strong>
          <p>
            {baseline.fills} fills · {milestone.data_access.selected_bars}{" "}
            research minutes
          </p>
        </article>
        <article className="metric">
          <span>Unexplained differences</span>
          <strong>
            {milestone.scenarios.reduce(
              (count, row) => count + row.errors.length,
              0,
            )}
          </strong>
          <p>Under the registered simulator assumptions</p>
        </article>
      </div>
      <div className="notice amber">
        <p>
          <strong>
            Engineering progress does not establish a trading edge.
          </strong>
          <br />
          The simulated starting balance was{" "}
          {usd(milestone.initial_balance_cents)}. The baseline ended at{" "}
          {usd(baseline.account.equity_cents)}, including declared commission
          assumptions and adverse simulated fills. Five already-observed
          sessions cannot validate profitability. All six live-pilot
          requirements remain unverified.
        </p>
      </div>
      <details className="milestone-details">
        <summary>Inspect all ten scenarios and their simulated net P&L</summary>
        <div className="milestone-scenarios">
          {milestone.scenarios.map((row) => (
            <article key={row.case}>
              <div>
                <CheckCircle2 size={16} />
                <strong>{titles[row.case] || row.case}</strong>
              </div>
              <span>
                {row.status === "pass" ? "Reconciled" : "Needs review"}
              </span>
              <b>{usd(row.account.net_pnl_cents)}</b>
            </article>
          ))}
        </div>
        <p className="small">
          Amounts are net simulated P&L, not earnings. Partial fills use two
          contracts to exercise that lifecycle. Missing data changes the trades
          taken; longer delays can change outcomes in either direction. Higher
          P&L in either scenario is not evidence of a better strategy. Nothing
          here measures actual bid/ask spreads, queue position or broker
          latency.
        </p>
      </details>
      <div className="hero-actions">
        <a
          className="button"
          href="/evidence/paper-milestone-report.md"
          target="_blank"
          rel="noreferrer"
        >
          Read the evaluation <ArrowUpRight size={15} />
        </a>
        <a
          className="text-button"
          href="/evidence/paper-milestone-summary.json"
          target="_blank"
          rel="noreferrer"
        >
          Inspect the result file <ArrowUpRight size={15} />
        </a>
      </div>
    </section>
  );
}
