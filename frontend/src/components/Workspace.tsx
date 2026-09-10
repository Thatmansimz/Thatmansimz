"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  FlaskConical,
  LayoutDashboard,
  BookOpen,
  ListChecks,
  Radio,
  ShieldCheck,
  Briefcase,
  LockKeyhole,
  RefreshCw,
  ChevronRight,
  HelpCircle,
} from "lucide-react";
import {
  evidenceDate,
  experiments,
  gates,
  masterDoc,
  tests,
} from "../data/evidence";

const navigation = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "evidence", label: "Research evidence", icon: BookOpen },
  { id: "tests", label: "Test plan", icon: ListChecks },
  { id: "paper", label: "Paper monitor", icon: Radio },
  { id: "readiness", label: "Live-pilot gates", icon: ShieldCheck },
  { id: "service", label: "Service & pricing", icon: Briefcase },
] as const;
type Section = (typeof navigation)[number]["id"];
type Runtime = {
  observed_at: string;
  broker: string;
  trading_enabled: boolean;
  scheduler_running: boolean;
  strategy: string;
  symbols: string[];
  closed_trades: number;
  open_positions: number;
  recorded_net_pnl: number;
  scope: string;
  reconciliation_issues?: { order_id: string; reason: string }[];
  readiness: { live_pilot_available: boolean; verified_gates: number };
};
const money = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

function DocLink({
  children = "Open master plan",
}: {
  children?: React.ReactNode;
}) {
  return (
    <a className="button" href={masterDoc} target="_blank" rel="noreferrer">
      {children}
      <ArrowUpRight size={16} />
    </a>
  );
}
function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function PageHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <header className="page-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{children}</p>
    </header>
  );
}

export default function Workspace() {
  const [section, setSection] = useState<Section>("overview");
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const response = await fetch("/api/workspace", {
        cache: "no-store",
        signal,
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Engine status unavailable.");
      setRuntime(result);
      setError("");
    } catch (e) {
      if (signal?.aborted) return;
      setRuntime(null);
      setError(e instanceof Error ? e.message : "Engine status unavailable.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const syncHash = () => {
      const id = window.location.hash.slice(1);
      if (navigation.some((n) => n.id === id)) setSection(id as Section);
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => {
      controller.abort();
      window.removeEventListener("hashchange", syncHash);
    };
  }, [refresh]);
  function go(id: Section) {
    setSection(id);
    window.location.hash = id;
    window.scrollTo({ top: 0 });
  }

  return (
    <div className="workspace">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#overview"
          onClick={() => go("overview")}
          aria-label="Tajari overview"
        >
          <span className="brand-mark">t.</span>
          <span>
            tajari<span className="brand-caption">EVIDENCE WORKSPACE</span>
          </span>
        </a>
        <div className="workspace-label">
          PARTNER WORKSPACE <span>01</span>
        </div>
        <nav aria-label="Workspace">
          {navigation.map(({ id, label, icon: Icon }) => (
            <a
              key={id}
              href={`#${id}`}
              onClick={() => go(id)}
              aria-current={section === id ? "page" : undefined}
            >
              <Icon size={18} />
              {label}
              {id === "readiness" && (
                <LockKeyhole size={12} className="nav-lock" />
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="research-label">
            <span />
            Research stage
          </div>
          <p>
            Build the evidence.
            <br />
            Earn the next step.
          </p>
          <a href={masterDoc} target="_blank" rel="noreferrer">
            Shared plan with Taj <ArrowUpRight size={14} />
          </a>
          <div className="partner">
            <span className="avatar">M</span>
            <div>
              Michael & Taj<small>Working plan · proposals to test</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <div className="topbar">
          <span>
            Tajari <ChevronRight size={14} />{" "}
            {navigation.find((n) => n.id === section)?.label}
          </span>
          <div>
            <span className="topbar-note">Evidence before exposure</span>
            <Badge tone="amber">
              <LockKeyhole size={12} /> Live pilot blocked
            </Badge>
          </div>
        </div>
        <main id="content" tabIndex={-1}>
          {section === "overview" && (
            <>
              <PageHeading
                eyebrow="THE NEXT CHAPTER"
                title="Make the next decision clearer."
              >
                One place for the evidence, the business plan and the
                requirements to move forward.
              </PageHeading>
              <section className="hero">
                <div>
                  <span className="eyebrow">OUR WORKING DIRECTION</span>
                  <h2>
                    Build a service.
                    <br />
                    Keep research disciplined.
                  </h2>
                  <p>
                    Start with paid technical evaluations. Keep a smaller,
                    bounded trading research track. No current strategy has
                    established an edge for real capital.
                  </p>
                  <div className="hero-actions">
                    <button
                      className="button primary"
                      onClick={() => go("service")}
                    >
                      Explore the first offer <ArrowRight size={16} />
                    </button>
                    <DocLink />
                  </div>
                </div>
                <div
                  className="allocation"
                  aria-label="Suggested effort: 80 percent service and harness reliability, 20 percent trading research"
                >
                  <div className="allocation-ring">
                    <strong>
                      80<span>%</span>
                    </strong>
                    <small>service & reliability</small>
                  </div>
                  <p>
                    <span />
                    20% bounded research
                  </p>
                  <small>
                    Suggested time allocation
                    <br />
                    Not investment allocation
                  </small>
                </div>
              </section>
              <div className="metric-grid">
                <article className="metric">
                  <span>Next commercial milestone</span>
                  <strong>2 paid pilots</strong>
                  <p>A target to validate buyer demand.</p>
                </article>
                <article className="metric">
                  <span>Proposed first offer</span>
                  <strong>
                    $1,500 <small>/ evaluation</small>
                  </strong>
                  <p>One strategy. One reviewed report.</p>
                </article>
                <article className="metric">
                  <span>Live-pilot readiness</span>
                  <strong>
                    0 <small>of 6 gates verified</small>
                  </strong>
                  <p>Every gate requires reviewable evidence.</p>
                </article>
              </div>
              <div className="section-title">
                <div>
                  <h2>What the evidence tells us</h2>
                  <p>Reviewed {evidenceDate} · historical snapshot</p>
                </div>
                <button className="text-button" onClick={() => go("evidence")}>
                  View evidence <ArrowRight size={16} />
                </button>
              </div>
              <EvidenceTable compact />
              <div className="two-column lower-grid">
                <section className="panel">
                  <p className="eyebrow">NEXT ACTION</p>
                  <h3>Make one evaluation reproducible.</h3>
                  <p>
                    Repair the evidence and simulator defects. Demonstrate the
                    failures with regression tests, then produce one reviewable
                    case study.
                  </p>
                  <button className="text-button" onClick={() => go("tests")}>
                    Open the test plan <ArrowRight size={16} />
                  </button>
                </section>
                <section className="panel tinted">
                  <HelpCircle size={20} />
                  <h3>A passing test is not a trading edge.</h3>
                  <p>
                    The original 292 test cases passed while independent probes
                    exposed consequential defects. Software correctness, trading
                    evidence and buyer demand need separate tests.
                  </p>
                </section>
              </div>
            </>
          )}
          {section === "evidence" && (
            <>
              <PageHeading
                eyebrow="RESEARCH RECORD"
                title="Results you can trace."
              >
                A dated assessment with the source beside each claim. Positive
                averages and small paper gains are not established
                profitability.
              </PageHeading>
              <div className="notice">
                <BookOpen size={19} />
                <p>
                  <strong>Snapshot · {evidenceDate}</strong>
                  <br />
                  Saved V2 files were totaled; the FOMC result was reproduced.
                  Previously inspected periods stay research data. These are not
                  current account balances.
                </p>
              </div>
              <EvidenceTable />
              <section className="panel lower-grid">
                <h3>Read the underlying findings</h3>
                <div className="resource-grid">
                  <a
                    href="/evidence/ASSESSMENT.md"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Full assessment <ArrowUpRight size={16} />
                  </a>
                  <a
                    href="/evidence/research-probes.json"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Harness defect probes <ArrowUpRight size={16} />
                  </a>
                  <a
                    href="/evidence/app-probes.json"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Simulator defect probes <ArrowUpRight size={16} />
                  </a>
                  <a
                    href="/evidence/fomc-rerun.txt"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Reproduced FOMC output <ArrowUpRight size={16} />
                  </a>
                </div>
                <p className="small">
                  Probe files preserve the original failures. Repairs do not
                  retroactively validate historical results. Use the master plan
                  for the archive, version rules and current decisions.
                </p>
                <DocLink />
              </section>
            </>
          )}
          {section === "tests" && <TestPlan />}
          {section === "paper" && (
            <>
              <PageHeading
                eyebrow="OBSERVATION ONLY"
                title="Paper is an execution experiment."
              >
                Watch the connected engine without confusing simulated P&L with
                broker-confirmed performance or validation.
              </PageHeading>
              <div className="section-title">
                <h2>Connected engine</h2>
                <button
                  className="button"
                  disabled={loading}
                  onClick={() => void refresh()}
                >
                  <RefreshCw size={15} />
                  {loading ? "Checking…" : "Refresh status"}
                </button>
              </div>
              <div aria-live="polite">
                {loading ? (
                  <div className="notice">Checking the connected backend…</div>
                ) : error ? (
                  <div className="notice amber">
                    <Radio size={20} />
                    <p>{error}</p>
                  </div>
                ) : (
                  runtime && (
                    <>
                      <div className="notice">
                        <Radio size={20} />
                        <p>
                          <strong>
                            {runtime.broker === "paper"
                              ? "Paper broker"
                              : `Configured broker: ${runtime.broker}`}{" "}
                            ·{" "}
                            {runtime.trading_enabled
                              ? "Entries enabled"
                              : "Entries disabled"}
                          </strong>
                          <br />
                          Observed{" "}
                          {new Date(runtime.observed_at).toLocaleString()} ·
                          Refresh to update. This describes the connected
                          checkout only.
                        </p>
                      </div>
                      <div className="metric-grid">
                        <article className="metric">
                          <span>Recorded net P&L</span>
                          <strong>{money(runtime.recorded_net_pnl)}</strong>
                          <p>Simulation ledger · all recorded trades</p>
                        </article>
                        <article className="metric">
                          <span>Closed / open</span>
                          <strong>
                            {runtime.closed_trades}{" "}
                            <small>/ {runtime.open_positions}</small>
                          </strong>
                          <p>Trade and position records</p>
                        </article>
                        <article className="metric">
                          <span>Scheduler</span>
                          <strong>
                            {runtime.scheduler_running ? "Running" : "Stopped"}
                          </strong>
                          <p>
                            {runtime.strategy} · {runtime.symbols.join(", ")}
                          </p>
                        </article>
                      </div>
                      <p className="small">{runtime.scope}</p>
                      {!!runtime.reconciliation_issues?.length && (
                        <div className="notice amber">
                          <p>
                            <strong>Reconciliation required</strong>
                            <br />
                            {runtime.reconciliation_issues.length} unresolved
                            market-history or fill issue(s). The affected exits
                            are not finalized as verified P&L.
                          </p>
                        </div>
                      )}
                    </>
                  )
                )}
              </div>
              <div className="two-column lower-grid">
                <section className="panel">
                  <h3>A frozen run comes next.</h3>
                  <p>
                    New forward runs are blocked in this release until a
                    registered protocol and credible research evidence are
                    reviewed. Restarts leave entries disabled.
                  </p>
                  <p>
                    The legacy engine may be running in a different checkout.
                    Its status is not inferred from this preview.
                  </p>
                  <button
                    className="text-button"
                    onClick={() => go("readiness")}
                  >
                    Review the requirements <ArrowRight size={16} />
                  </button>
                </section>
                <section className="panel tinted">
                  <p className="eyebrow">WHAT COUNTS</p>
                  <h3>Opportunities, not a countdown.</h3>
                  <p>
                    Reconcile generated orders → eligible market events → fills
                    → positions → P&L. Explain every difference. Duration
                    depends on independent opportunities and market conditions.
                  </p>
                  <p>
                    Eight FOMC events per year cannot quickly provide a rich
                    validation sample.
                  </p>
                </section>
              </div>
            </>
          )}
          {section === "readiness" && (
            <>
              <PageHeading
                eyebrow="ALL SIX ARE REQUIRED"
                title="Earn the right to pilot."
              >
                Evidence review controls progression. A checkbox, a bigger
                contract or a calendar milestone cannot authorize real trading.
              </PageHeading>
              <div className="notice amber">
                <LockKeyhole size={21} />
                <p>
                  <strong>Live routing is blocked in this release.</strong>
                  <br />
                  No gate is verified. There is no live activation button or
                  environment override. Any eventual pilot requires separate
                  authorization after the evidence and execution requirements
                  are met.
                </p>
              </div>
              <div className="gate-list">
                {gates.map((g, i) => (
                  <details key={g.title} className="gate" open={i === 0}>
                    <summary>
                      <span className="gate-number">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <h3>{g.title}</h3>
                      <Badge tone="amber">{g.status}</Badge>
                      <ChevronRight size={18} />
                    </summary>
                    <div className="gate-body">
                      <p>{g.detail}</p>
                      <div>
                        <strong>Evidence required</strong>
                        <p>{g.evidence}</p>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
              <section className="panel lower-grid">
                <h3>Contract size cannot validate a signal.</h3>
                <p>
                  NQ reduces commission expressed in index points compared with
                  MNQ, but changes dollar risk and margin. The reproduced FOMC
                  mean, at eight events and 0.725 points of friction,
                  mechanically implies about{" "}
                  <strong>$12.70 per NQ contract per year</strong> before
                  overhead.
                </p>
                <p>
                  This is conditional arithmetic from an unestablished mean, not
                  a return forecast. Leverage does not fix the uncertainty.
                </p>
                <a
                  className="text-button"
                  href="/evidence/fomc-independent-check.json"
                  target="_blank"
                  rel="noreferrer"
                >
                  Inspect the arithmetic <ArrowUpRight size={15} />
                </a>
              </section>
            </>
          )}
          {section === "service" && <Service />}
          <footer>
            <span>TAJARI / NULLIUS</span>
            <p>
              Traceable evidence. Explicit assumptions. One decision at a time.
            </p>
            <a href={masterDoc} target="_blank" rel="noreferrer">
              Shared master plan <ArrowUpRight size={13} />
            </a>
          </footer>
        </main>
      </div>
    </div>
  );
}

function EvidenceTable({ compact = false }: { compact?: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const active = experiments.find((e) => e.id === selected);
  return (
    <div className="evidence-panel">
      <div className="table-scroll">
        <table>
          <caption className="sr-only">
            Historical evidence reviewed September 10, 2026
          </caption>
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Sample</th>
              <th>Observed result</th>
              <th>Assessment</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {experiments
              .filter((e) => !compact || e.id !== "reverse")
              .map((e) => (
                <tr key={e.id}>
                  <td>
                    <strong>{e.name}</strong>
                    <small>{e.method}</small>
                  </td>
                  <td>{e.sample}</td>
                  <td className="result">{e.result}</td>
                  <td>
                    <Badge tone={e.verdict === "Failed" ? "red" : "amber"}>
                      {e.verdict}
                    </Badge>
                  </td>
                  <td>
                    <button
                      aria-label={`Details for ${e.name}`}
                      aria-expanded={selected === e.id}
                      className="icon-button"
                      onClick={() =>
                        setSelected(selected === e.id ? null : e.id)
                      }
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {active && (
        <div className="evidence-detail" aria-live="polite">
          <h3>{active.name}</h3>
          <p>{active.detail}</p>
          <a href={active.source} target="_blank" rel="noreferrer">
            Open source evidence <ArrowUpRight size={15} />
          </a>
        </div>
      )}
    </div>
  );
}

function TestPlan() {
  const [track, setTrack] = useState("All tests");
  return (
    <>
      <PageHeading
        eyebrow="THREE DISTINCT TEST TRACKS"
        title="Define what would change our mind."
      >
        Every test has a purpose and an acceptance condition. These are
        recommended tests, not a record of completed validation.
      </PageHeading>
      <div className="filter-bar" aria-label="Filter tests">
        {[
          "All tests",
          "Engineering",
          "Trading research",
          "Customer demand",
        ].map((t) => (
          <button
            key={t}
            aria-pressed={track === t}
            onClick={() => setTrack(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="test-grid">
        {tests
          .filter((t) => track === "All tests" || t.track === track)
          .map((t) => (
            <article className="panel test-card" key={t.title}>
              <Badge>{t.track}</Badge>
              <h3>{t.title}</h3>
              <p>{t.detail}</p>
              <div className="acceptance">
                <span>ACCEPTANCE CONDITION</span>
                <p>{t.pass}</p>
              </div>
            </article>
          ))}
      </div>
      <div className="notice lower-grid">
        <FlaskConical size={20} />
        <p>
          Keep engineering results, trading experiments and commercial outcomes
          separate. A passing result in one track cannot substitute for another.
        </p>
      </div>
    </>
  );
}

function Service() {
  const [price, setPrice] = useState(1500);
  const [hours, setHours] = useState(8);
  const [hourly, setHourly] = useState(75);
  const [tools, setTools] = useState(100);
  const contribution = price - hours * hourly - tools;
  const margin =
    price > 0 ? `${((contribution / price) * 100).toFixed(1)}%` : "—";
  return (
    <>
      <PageHeading
        eyebrow="COMMERCIAL HYPOTHESIS"
        title="Sell one useful evaluation."
      >
        Help a trading-software team reproduce its claims and identify data
        leakage, unrealistic fills and execution discrepancies.
      </PageHeading>
      <section className="offer">
        <div>
          <Badge>Proposed founding offer</Badge>
          <h2>Strategy evaluation</h2>
          <p>
            One strategy. One instrument. One agreed historical dataset.
            <br />
            One reproducible, human-reviewed report and a review call.
          </p>
          <ul>
            <li>Original claim and reproduced net result</li>
            <li>Demonstrated failures and prioritized repairs</li>
            <li>Explicit assumptions and limitations</li>
          </ul>
          <p className="small">
            An evaluation is valuable even when the strategy fails. No
            profitability guarantee or account management.
          </p>
        </div>
        <div className="offer-price">
          <strong>$1,500</strong>
          <span>fixed scope · price to test</span>
          <DocLink>Review the offer</DocLink>
          <small>Next milestone: two independent paying buyers</small>
        </div>
      </section>
      <div className="section-title">
        <div>
          <h2>Does the scope pay for itself?</h2>
          <p>
            Change the assumptions. This is contribution before sales, overhead
            and tax.
          </p>
        </div>
        <Badge>Illustrative calculator</Badge>
      </div>
      <section className="calculator">
        <div className="calc-inputs">
          {[
            { name: "Evaluation price ($)", value: price, set: setPrice },
            { name: "Delivery hours", value: hours, set: setHours },
            { name: "Labor cost per hour ($)", value: hourly, set: setHourly },
            { name: "Variable tools & data ($)", value: tools, set: setTools },
          ].map((i) => (
            <label key={i.name}>
              {i.name}
              <input
                type="number"
                min="0"
                step="any"
                value={i.value}
                onChange={(e) =>
                  i.set(
                    Math.max(0, Math.min(1000000, Number(e.target.value) || 0)),
                  )
                }
              />
            </label>
          ))}
        </div>
        <div className="calc-output">
          <span>Contribution per evaluation</span>
          <strong className={contribution < 0 ? "loss" : ""}>
            {money(contribution)}
          </strong>
          <p>{margin} contribution margin</p>
          <small>Price − delivery hours × labor cost − variable tooling</small>
        </div>
      </section>
      <div className="two-column lower-grid">
        <section className="panel">
          <h3>Expand only after paid demand.</h3>
          <dl className="price-list">
            <div>
              <dt>Repeatable standard evaluation</dt>
              <dd>$2,500</dd>
            </div>
            <div>
              <dt>Complex evaluation, scoped</dt>
              <dd>From $5,000</dd>
            </div>
            <div>
              <dt>Change monitoring · up to 2 reruns</dt>
              <dd>$750 / mo</dd>
            </div>
          </dl>
          <p>
            All prices are hypotheses. Data purchases, production incident
            response, broker onboarding and unlimited revisions are outside the
            initial scope.
          </p>
        </section>
        <section className="panel tinted">
          <h3>Keep the income arithmetic honest.</h3>
          <p>
            $50,000 earning an illustrative 20% net return produces $10,000 a
            year. This project has not established that return.
          </p>
          <p>
            Service revenue requires buyers and useful delivery. It gives us
            more controllable variables to test now. Record paid demand, hours
            and actual costs before scaling.
          </p>
        </section>
      </div>
    </>
  );
}
