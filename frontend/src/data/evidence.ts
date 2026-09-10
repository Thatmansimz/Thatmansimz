export const masterDoc =
  "https://docs.google.com/document/d/1lgEJ4ND83JNOWouX8QoYAcEl_BB4NahogO3FElErMsY/edit";
export const evidenceDate = "September 10, 2026";
export const experiments = [
  {
    id: "v2",
    name: "V2 · New York",
    method: "Historical replay · no costs",
    sample: "1,050 trades",
    result: "−$15,543.15",
    verdict: "Failed",
    detail:
      "The saved quarterly results lose money even without trading costs. Costs alone do not explain the failure.",
    source: "/evidence/saved-results-summary.json",
  },
  {
    id: "reverse",
    name: "V2 · Reversed signals",
    method: "Historical replay · modeled costs",
    sample: "1,082 trades",
    result: "−$59,475.09",
    verdict: "Failed",
    detail:
      "Reversing the entry direction did not rescue the strategy. These totals were reconstructed from saved files, not a new backtest.",
    source: "/evidence/saved-results-summary.json",
  },
  {
    id: "fomc",
    name: "FOMC · Pre-decision",
    method: "Reproduced older evaluation period",
    sample: "23 events",
    result: "+0.8043 points",
    verdict: "Inconclusive",
    detail:
      "Corrected two-sided 90% interval: −2.15 to +3.75 points. The fitted magnitude did not generalize. This period has now been observed and remains research data.",
    source: "/evidence/fomc-independent-check.json",
  },
  {
    id: "paper",
    name: "V2 · Legacy paper record",
    method: "Snapshot · simulation defects identified",
    sample: "6 trades",
    result: "+$362.80",
    verdict: "Unverified",
    detail:
      "The earlier four-trade gain of $886 fell to $362.80 after two further losses. This is a small, compromised paper record, not broker-confirmed profit.",
    source: "/evidence/ASSESSMENT.md",
  },
];
export const gates = [
  {
    title: "Freeze the experiment",
    status: "Missing",
    detail:
      "Freeze the strategy, economic hurdle, complete experiment family and data-access record before evaluation. Previously observed periods remain research data.",
    evidence:
      "Versioned rules, code and data manifests, access history, selection log and a stopping rule.",
  },
  {
    title: "Establish net economics",
    status: "Not established",
    detail:
      "Reproduce performance net of costs, with uncertainty and search correction appropriate to the actual selection process. Account for overlapping or clustered observations.",
    evidence:
      "Reproducible report, dependence-aware inference, full search family and an economic lower bound.",
  },
  {
    title: "Survive execution stress",
    status: "Missing",
    detail:
      "Stress fills, latency, spreads, missing data, roll dates and costs. Show materially worse execution assumptions, not one favorable setting.",
    evidence:
      "Prespecified stress matrix and results for every scenario, including failures.",
  },
  {
    title: "Reconcile a frozen paper run",
    status: "Unverified",
    detail:
      "Explain every difference between generated orders, eligible market events, fills, positions and P&L. Duration depends on independent opportunities and market conditions, not 60 days.",
    evidence:
      "Frozen forward protocol, opportunity count, event ledger, reconciliation and stopping analysis.",
  },
  {
    title: "Prove broker readiness",
    status: "Incomplete",
    detail:
      "Complete one broker adapter, exchange-held protection where supported, restart reconciliation and strict loss/exposure limits. Demonstrate disconnect and rejection behavior.",
    evidence:
      "Sandbox execution records, protective-order acknowledgments and fault/restart tests.",
  },
  {
    title: "Authorize a bounded live pilot",
    status: "Not authorized",
    detail:
      "Separately authorize the smallest viable size and a predefined loss budget, with no expectation of income. Scale only against observed execution and drawdown evidence.",
    evidence:
      "Partner authorization naming strategy version, size, loss budget, stop conditions and review owner.",
  },
];
export const tests = [
  {
    track: "Engineering",
    title: "Leakage and provenance",
    detail:
      "Reuse and partially overlap research observations; change code, data digest, sample flag and search count after registration.",
    pass: "Reject incompatible evidence, identify the overlap and never emit tradeable. Unreadable executable source must not receive an intact seal.",
  },
  {
    track: "Engineering",
    title: "Timing and execution",
    detail:
      "Replay pre-entry, duplicate, missing and out-of-order bars. Simulate gaps, disconnects, pending fills, rejected orders and restart.",
    pass: "No retrospective or invented fills; each eligible event processed once; unresolved gaps visible. Pending and partial orders reconcile to broker state.",
  },
  {
    track: "Engineering",
    title: "Exits and decision logic",
    detail:
      "Test below, at and above +1R; stop-change rejection; compare paper and replay. Exercise known-positive unseen data, noise and effects below costs.",
    pass: "No premature trail or unacknowledged stop changes. Stronger unseen performance is not itself refutation. Decisions agree with the final report.",
  },
  {
    track: "Trading research",
    title: "Freeze up to three hypotheses",
    detail:
      "Choose mechanisms using research data. Declare instrument, exact entry/exit, cost model, economic hurdle, family, untouched evaluation span and stopping rule.",
    pass: "A reviewer can reproduce the specification before any evaluation data is accessed. Every attempted selection is recorded.",
  },
  {
    track: "Trading research",
    title: "Costs, controls and uncertainty",
    detail:
      "Use matched placebos, exposure-comparable baselines and materially worse costs. Purge overlapping label horizons; account for clustered opportunities and selection.",
    pass: "Net economics clear the predeclared hurdle under the registered design. Report intervals, concentration and all stress results, including inconclusive findings.",
  },
  {
    track: "Trading research",
    title: "Forward opportunity test",
    detail:
      "Run a frozen candidate only after credible research evidence. Reconcile orders through P&L and evaluate precision across relevant conditions.",
    pass: "No unexplained ledger differences. Sample sufficiency follows independent opportunities; eight FOMC events a year cannot quickly establish a rich sample.",
  },
  {
    track: "Customer demand",
    title: "Ten buyer conversations",
    detail:
      "Talk to qualified strategy developers and trading-software teams about a recent validation problem, their workaround, buying authority and data access.",
    pass: "Document a concrete problem and an accountable buyer. Friendly interest alone is not demand.",
  },
  {
    track: "Customer demand",
    title: "Two paid evaluations",
    detail:
      "Offer one strategy, one instrument, one dataset and one reviewed report for a proposed $1,500. Track offers, deposits, delivery hours and variable costs.",
    pass: "Two independent buyers pay; the work changes an engineering decision; scope has viable delivery economics. Revise the offer if those conditions fail.",
  },
];
