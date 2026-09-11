# Tajari Master Plan

## Purpose and decision

This is the shared operating document for Tajari and its Nullius evaluation harness. It explains what we have, what the evidence supports, what we intend to sell, how we will test the business, and what must change before any real trading. Use it as the starting point for decisions and follow the evidence links for underlying results and code.

Project lead: Michael Williams. Partner reviewer: Taj. Engineering and research support: Codex. The proposed responsibilities below are for discussion; they do not assume Taj has accepted an assignment.

Evidence reviewed: September 10, 2026. Initial assessment commit: 72f37c4. This is a snapshot, not a live trading-status page.

Our working direction is to build a paid technical evaluation service first and keep trading research as a smaller internal track. A suggested effort split is 80% commercial validation and harness reliability, 20% bounded research. This describes time allocation, not an investment allocation. No current strategy has earned deployment with real capital.

Our next commercial milestone is two customers paying for a repeatable evaluation. Our next trading milestone is one frozen strategy with credible new evidence and trustworthy execution. Neither milestone has been achieved yet. Prices, timelines and conversion goals below are proposals to test, not established demand or promised returns.

## What exists and what the results mean

Tajari includes a FastAPI backend, SQLite records, a Next.js dashboard, scheduling and restart tools, paper execution, risk controls, several strategies and broker adapters. Nullius adds data validation, adversarial checks, experiment registration, holdout tracking, economics, verdicts and reports. The two systems are not yet a verified end-to-end pipeline.

The active V2 strategy is rule-based. Its displayed confidence is a manually constructed score, not a calibrated win probability. The optional ML implementation is separate and has its own defects. Adding a newer AI model does not establish profitability.

| Experiment | Observed result | What we conclude |
| --- | --- | --- |
| V2 New York without costs | 1,050 trades; −$15,543.15 | Costs alone do not explain failure |
| Reversed V2 with modeled costs | 1,082 trades; −$59,475.09 | Reversing signals did not rescue it |
| CPI holdout | 18 observations; +8.08 points; t 0.60 | Positive average, inconclusive evidence |
| FOMC older unseen period | 23 observations; +0.8043 points; t 0.468 | Fitted magnitude did not generalize |
| Current V2 paper record at review | Six trades; +$362.80 | Too small and affected by simulation defects |

The V2 totals were added from saved experiment outputs, not regenerated as full new backtests. The FOMC script was rerun and matched its saved result. Its corrected two-sided 90% interval is approximately −2.15 to +3.75 points. Several ordinary cost-inclusive quarterly files are empty, so a complete historical total cannot be independently recovered from those files alone.

The earlier four-trade paper gain of $886 became $362.80 after two further losses. At review, the old paper engine was still enabled and running despite the prior campaign being described as halted. We have not changed that process in this document task. The archived assessment distinguishes paper records from broker-confirmed profits.

These findings mean the tested rules have not demonstrated a durable, economically usable edge. They do not prove every possible strategy is unprofitable. Previously inspected data remains research data; renaming a strategy does not create a fresh holdout.

Sources: [Historical results and test inventory](https://drive.google.com/file/d/1e1vskFs2tBrtgvbUF52BG6VmeAEVVY4X/view?usp=drivesdk), [FOMC reproduced output](https://drive.google.com/file/d/1lCGU_l1kHur4sGe0TOKRmYRja8fACdKI/view?usp=drivesdk), [FOMC independent arithmetic](https://drive.google.com/file/d/18udh2_FNJiBfmYE5xZbNSH5-IkgumGop/view?usp=drivesdk).

## Consequential findings and repair order

Fix the ability to produce trustworthy evidence before adding strategies or selling a passing verdict. The existing 292 test cases all passed, while independent probes reproduced the defects below. Test count is not the acceptance criterion.

1. Research data can be labeled unseen and receive a tradeable verdict. Bind sample status to sealed data boundaries, observation identities and recorded access. Reject overlapping research and holdout evidence.
2. A stronger unseen result can be incorrectly labeled refuted. Base economic decisions on unseen net performance and its uncertainty. Analyze deterioration separately rather than requiring exact agreement with a fitted point estimate.
3. An executable with unreadable source can receive an intact seal. Verify immutable code, configuration and input manifests; refuse claims whose executable cannot be verified.
4. The paper broker can close a new position using a bar from before entry. Enforce event ordering, eligible timestamps and replay of missed events after interruptions.
5. EMA trailing starts before the documented +1R trigger. Share one exit implementation between replay and paper operation, with boundary tests.
6. Submitted broker orders may escape the local ledger. Persist pending, partial and filled states; reconcile on restart; handle rejected stop changes. The Tradovate integration is not ready for real capital.
7. The API still listens on all interfaces without application authentication. Restrict binding and authenticate mutations. Verify the running configuration after a restart; the existence of a patch file is not deployment evidence.

Next, address test discovery, stale data detection, calendar freshness, contradictory prop-firm settings, ML labeling, multiplicity defaults and holdout-ledger integrity. One existing uncommitted economics patch correctly rejects fitted-only economics and non-finite volume, but does not fix the separate verdict and CLI pathways. It is captured in the evidence snapshot, not silently committed as a production change.

Sources: [Research defect probes](https://drive.google.com/file/d/139l1xVElkJATIJ9PDEoaRN-PEU8VAY3u/view?usp=drivesdk), [Application defect probes](https://drive.google.com/file/d/1V6Iz98AFyVEMXO_rZzR9Y5yrv0RhV6Z1/view?usp=drivesdk), and the full review in the evidence map.

## The service we would sell

We independently reproduce automated-strategy results and identify data leakage, unrealistic fills and discrepancies between backtests and paper execution before deployment.

Start with small trading-software teams, systematic strategy developers and AI-finance product teams that have Python code and a real deployment or review decision. Qualify on a concrete problem, an accountable buyer, authorized access to inputs and willingness to pay. Buyer demand has not yet been validated.

The first engagement covers one strategy, one instrument, one agreed historical dataset and one reproducible report. Deliver the original claim, reproduced result, assumptions, demonstrated failures, prioritized repairs and explicit limitations. A human reviews the report. We are selling a defined technical evaluation, not a guarantee of profitability, a regulatory certification or account management.

Require a scoped intake: code version, data rights, instrument, sampling frequency, order rules, original performance claim, all known experiments, expected deliverable and decision deadline. If inputs are insufficient, the correct deliverable is a documented inability to reproduce—not an invented pass.

The method should work with existing research engines. [QuantConnect LEAN](https://github.com/QuantConnect/Lean) already provides research and execution infrastructure; its [slippage documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) addresses realistic fills. Our differentiation to test is forensic reproduction and evidence another person can inspect.

## Pricing and monetization

These are proposed launch offers. Begin by selling the first row; expand only when paid work reveals repeatable demand. Do not build four products in advance.

| Offer | Proposed price | Scope boundary |
| --- | --- | --- |
| Founding pilot | $1,500 fixed | One strategy and instrument, one report, one review call |
| Standard evaluation | $2,500 fixed | Same defined workflow after repeatability is demonstrated |
| Complex evaluation | From $5,000 quoted | Additional integrations or data complexity; separately scoped |
| Change monitoring | $750 per month | One frozen baseline, up to two agreed reruns and a monthly change report |

The earlier suggested pilot range was $1,000–$2,500. Use $1,500 as the opening hypothesis so offers are comparable. Discuss scope before discounting. A proposed payment structure is 50% at an agreed start and 50% at delivery; payment buys the evaluation regardless of whether the strategy passes. These are draft commercial terms, not an executed contract.

Exclude data purchases, broker onboarding, strategy development, trading advice, unlimited revisions and production incident response unless separately quoted. A monitoring retainer should not imply continuous market surveillance or a safety guarantee. Use customer-authorized data and agree on retention, confidentiality and deletion.

Evaluate unit economics with an explicit labor cost. At an assumed $75 per delivery hour plus $100 of variable tooling, an eight-hour $1,500 pilot leaves $800, or 53.3%, before sales work, fixed overhead and tax. The same eight-hour job at $2,500 leaves $1,800, or 72%. A twenty-hour $1,500 pilot loses $100 on that model. Record actual hours and costs; these assumptions are not forecasts.

For a $750 monitoring account, an assumed 1.5 hours of work plus $75 of tooling leaves $562.50, or 75%, before acquisition and overhead. Five hours instead leaves $300, or 40%. The operational question is whether the workflow stays within the priced scope. Ten such customers would represent $7,500 monthly revenue, not $7,500 profit and not an expected outcome.

Monetization sequence: paid evaluation first; repeat evaluations second; limited change monitoring third; hosted software only after repeated workflows justify it. Avoid compensation tied to a passing result and avoid profit-sharing fees at launch. Those incentives would undermine an independent technical review and can introduce additional legal complexity.

Before offering tailored futures recommendations or managing accounts, have qualified counsel assess the proposed service under the [NFA CTA framework](https://www.nfa.futures.org/members/cta/index.html). Verify dataset-specific rights through [Databento licensing information](https://databento.com/pricing/) and [CME data licensing](https://www.cmegroup.com/market-data/license-data.html). The evidence archive excludes licensed price bars, credentials and trading databases.

## Tests we should run before selling conclusions

Use three separate test tracks. Passing an engineering test does not prove an edge; passing a trading experiment does not prove customer demand.

### Software and evidence integrity

- Leakage test: supply the same observations as research and holdout. Expected: reject the holdout, name the overlap, and never emit tradeable. Repeat with partial overlap and date-boundary overlap.
- Decision test: give the system known profitable unseen data, stronger-than-fitted data, pure noise and an effect below costs. Expected: consistent decisions based on economic evidence, with uncertainty; improvement must not itself cause refutation.
- Provenance test: change a hypothesis field, sample flag, code body, dataset digest or stored search count after registration. Expected: refuse incompatible evidence and preserve the earlier record. Unreadable executable source must not receive an unqualified intact seal.
- History test: truncate or delete a ledger, retry after a crash and rename a previously evaluated hypothesis. Expected: no automatic restoration of a pristine holdout. Use independently anchored history for stronger custody claims; local hashes alone are insufficient.
- Timing test: feed pre-entry bars, duplicate bars, a missing interval, out-of-order data, a market gap and a daylight-saving boundary. Expected: eligible events processed once, no retrospective exits, visible refusal on stale inputs.
- Execution test: simulate pending and partial fills, rejection, duplicate submission, stop-update failure, disconnect and restart. Expected: no unmanaged orders or positions, no invented fills and reconciliation against broker state. Perform with mocks and broker sandbox facilities first.
- Exit test: test below, exactly at and above +1R; then compare replay and paper outcomes using identical events. Expected: identical eligible exits and no premature trail.
- Whole-workflow test: run registration through report on a fresh checkout, then intentionally break each critical guard. Expected: all test modules are discovered, each targeted mutation causes a meaningful failure, and the report agrees with the underlying verdict.

Repair acceptance: convert the reproduced defects into regression tests, make those tests fail on the archived buggy implementation, pass them on the repair, and review one complete result from input to report. Do not substitute another test-count target for this gate.

### Trading research

Freeze no more than three initial mechanism-based hypotheses, each with a named economic rationale, instrument, exact entry and exit rules, cost model, research span, untouched evaluation plan and stopping rule. Do not select the three by searching the holdout.

- Reproduction: first recover existing results from pinned code and inputs. Explain discrepancies before new discovery work.
- Baselines and controls: compare with no-trade and appropriate time/session controls; use matched placebo dates or windows when relevant. Keep risk and exposure comparable.
- Costs and execution: evaluate normal assumptions and materially worse spreads, slippage, fees and latency. Model gaps, missing fills, capacity and contract rolls. Reject results that depend on implausible fills.
- Generalization: use a prespecified forward or walk-forward design, purge overlapping label horizons, account for dependent observations and record the complete search family. A window that has been inspected becomes research data.
- Uncertainty: predeclare alpha, relevant effect size and target power using plausible variability. Use a lower confidence bound on net economics appropriate to dependence and selection. The old 2 × standard-error heuristic is not a complete power design.
- Stability: inspect years/regimes and outlier concentration without using those diagnostics to repeatedly refit the final holdout. Report what removal of the best observations changes.
- Forward execution: only after a candidate survives research, run a frozen paper version and reconcile every order, position and fill. Choose duration based on independent opportunities and precision, not merely 60 calendar days.

No universal observation count guarantees an edge. Rare events can require years to accumulate adequate evidence. A negative or inconclusive result closes that experiment under its declared rules; it does not authorize repeated attempts on the same holdout. Any eventual live pilot requires a separate decision, a predefined loss budget and a completed broker integration.

### Customer demand and pricing

- Problem interviews: speak with ten qualified prospects about their most recent deployment or validation problem. Record current workaround, cost of failure, buying authority and access constraints. Do not count friendly enthusiasm as demand.
- Paid offer: present the same $1,500 scope to qualified buyers and seek two paid pilots. Track offers, objections, deposits and time to decision. Ten conversations are a discovery target, not a statistically valid conversion study.
- Delivery test: complete pilots within the scoped hours, record variable cost, and ask which findings changed an engineering decision. Do not promise a prescribed financial outcome.
- Repeat-use test: offer a defined rerun or monitoring engagement only when the customer has a real recurring need. A paid renewal is stronger evidence than a survey response.

Business gate: continue the current offer if two independent customers pay, the work is useful and delivery economics have a credible path to the proposed standard price. If qualified prospects will not pay or provide usable inputs, revise the buyer/scope hypothesis before investing in a platform. If work regularly exceeds its estimate, narrow scope or raise price before scaling sales.

## Six gates before any live pilot

All six gates are required. They are evidence requirements, not a calendar countdown or a checklist that can be satisfied by clicking a button. No gate is currently certified complete.

1. Freeze the strategy, economic hurdle, experiment family and data-access record before evaluation. Previously observed periods stay research data. Record immutable code and input versions and every selection attempt.
2. Reproduce net-of-cost performance with uncertainty and multiple-search handling appropriate to the actual selection process. Use dependence-aware inference when observations overlap or cluster. A positive average alone does not pass.
3. Stress fills, latency, spreads, missed data, roll dates and costs. Report results under materially worse execution assumptions. A result that depends on one favorable setting does not pass.
4. Complete a frozen forward paper run with no unexplained differences between generated orders, eligible market events, fills, positions and P&L. Duration depends on independent opportunities and market conditions, not merely 60 days. Eight FOMC events a year cannot quickly produce a rich validation sample.
5. Complete one broker adapter, exchange-held protective orders where supported, restart reconciliation and strict loss/exposure limits. Demonstrate behavior under disconnects and rejected orders. Paper profitability does not establish broker readiness.
6. Obtain separate authorization for the smallest viable live pilot, with a predefined loss budget and no expectation of income. Scale only against observed execution and drawdown evidence. This plan does not authorize a live order.

Switching MNQ to NQ reduces commission expressed in index points, but changes dollar risk and margin requirements. It does not validate the signal. The reproduced FOMC mean, mechanically annualized at eight events and 0.725 points of friction, is about $12.70 per NQ contract per year before overhead. That is conditional arithmetic from an unestablished mean, not a return forecast. Increasing leverage does not fix the uncertainty.

For perspective, $50,000 earning an illustrative 20% net return produces $10,000 a year. This project has not established that return. Small starting capital combined with urgent income expectations encourages dangerous sizing. Service revenue still requires finding buyers and delivering value, but gives us more controllable variables to test now.

## First month and proposed responsibilities

| Sequence | Deliverable and completion test | Proposed lead |
| --- | --- | --- |
| Week 1 | Repair core evidence and simulator failures; regressions demonstrate the fixes | Codex implementation with partner review |
| Week 2 | One reproducible case study, one known-positive control, scoped offer and intake | Codex and Michael |
| Weeks 2 and 3 | Ten buyer conversations; seek two paid pilot agreements | Michael; Taj introductions if desired |
| Week 4 | Deliver pilots, review hours and costs, decide whether to continue the offer | Michael and Taj |

This is a proposed sequence, not a guarantee of revenue within a month. Fixes and paid pilots are not yet completed. The old paper process needs an explicit operational decision; a durable stop must account for restart configuration.

Michael should own buyer discovery, scope and commercial decisions. Codex can prepare code changes, tests, evidence and draft reports during authorized work. Taj can challenge the assumptions, review the evidence and help qualify buyers. Proposed budget, commitments to customers and any future live trading should be agreed by the partners.

For each working review, record: decision made, supporting evidence ID, owner, next action and what would change the decision. Track qualified conversations, offers, paid pilots, delivery hours, variable costs, renewals and unresolved critical defects. Keep trading performance separate from service revenue.

## Evidence map and version rules

E1 — [Full assessment](https://drive.google.com/file/d/1QZukgVU4bJVrKocChyE8hxiPOyrJ3Kp-/view?usp=drivesdk). Detailed architecture, source locations, limitations, findings and strategic recommendation. Local paths inside it refer to files also identified in the snapshot; they are not browser links that will work on Taj’s computer.

E2 — [Historical totals and test inventory](https://drive.google.com/file/d/1e1vskFs2tBrtgvbUF52BG6VmeAEVVY4X/view?usp=drivesdk). File-by-file arithmetic and the 292-case inventory. Original tests passed; independent probes demonstrate gaps outside their assertions.

E3 — [Nullius defect probes](https://drive.google.com/file/d/139l1xVElkJATIJ9PDEoaRN-PEU8VAY3u/view?usp=drivesdk). Reused-data promotion, stronger-result refutation, contradictory small-sample wording and unreadable-source seal acceptance; also verifies the existing economics fixes.

E4 — [Application defect probes](https://drive.google.com/file/d/1V6Iz98AFyVEMXO_rZzR9Y5yrv0RhV6Z1/view?usp=drivesdk). Pre-entry-bar exit, premature trailing and the optional ML short-label failure. Inputs are synthetic, not broker trades.

E5 — [FOMC rerun](https://drive.google.com/file/d/1lCGU_l1kHur4sGe0TOKRmYRja8fACdKI/view?usp=drivesdk) and [independent arithmetic](https://drive.google.com/file/d/18udh2_FNJiBfmYE5xZbNSH5-IkgumGop/view?usp=drivesdk). Already-used older data, no newly opened holdout. Use the corrected interval from the independent calculation.

E6 — [Downloadable code and evidence snapshot](https://drive.google.com/file/d/1qoeCQ7D926SwHUSyhCfC2Aje5ojJ2BuU/view?usp=drivesdk). Contains 171 files: reviewed application and harness source, existing test sources, historical output files, synthetic reproduction scripts, prior review notes and a SHA256 manifest. Start with START_HERE.txt. Dependencies and licensed price bars are not bundled. Scripts may require local-path changes and should run in an isolated environment.

Archive SHA256: 746ee678fd2892e566a8ead74eb0452f10b7604b1970f1d9045b18077f0e6046. This establishes the identity of this snapshot, not independent custody or proof that data was unseen.

Application base: 9808b0e. Harness base: 16d758b plus the captured economics working-tree patch. Assessment record: 72f37c4. The research repository has no Git remote configured, so these commits are local until a destination is selected. The Drive snapshot gives the partners access without requiring GitHub.

This master document is the working plan. Keep each evidence release immutable, create a new dated snapshot for material changes and record the new commit and changed conclusions. Never overwrite a failed experiment with a passing rerun. Comments can challenge the plan; a changed conclusion must point to changed evidence.


## Implementation update

The shared native document is [Tajari — Master Plan, Pricing & Evidence](https://docs.google.com/document/d/1lgEJ4ND83JNOWouX8QoYAcEl_BB4NahogO3FElErMsY/edit). Taj has commenter access and read access to the original evidence artifacts.

### Internal paper milestone — September 11, 2026

The new isolated execution core reconciles all ten predeclared engineering cases on 315 already-observed MNQ minutes from January 3–7, 2022. Starting simulated balance: $50,000. Baseline: five completed round trips, $20.80 net after declared simulation assumptions. Worse costs: $5.60 net. Both actual process-crash cases restart with identical baseline accounting. These are engineering results, not a validated trading edge or a broker-connected forward run. No new data was purchased and no new holdout was opened. All six live-pilot requirements remain unverified.

Read the [full internal evaluation](https://tajari.vercel.app/evidence/paper-milestone-report.md), [aggregate results](https://tajari.vercel.app/evidence/paper-milestone-summary.json), and [proposed $1,500 pilot package](https://tajari.vercel.app/evidence/evaluation-pilot.md). The scope, intake, delivery criteria, buyer interview and empty tracker are prepared. No outreach, revenue or paid demand is claimed. Full licensed input and private ledgers remain local; the public workspace contains summaries only. The next trading step is an entitled streaming feed and complete paper-broker adapter with actual contract mapping, followed by a separate registered real-time run.

### Production workspace — September 10, 2026

The approved layout is live at **[tajari.vercel.app](https://tajari.vercel.app)**. Share this stable link with Taj; it does not require Vercel login or the local computer to remain online. Frontend release `138b0e7` is deployed to Vercel project `tajari`. The hosted workspace includes historical evidence, the test plan, the six live-pilot requirements and pricing tools. Its paper monitor explicitly reports that the local engine is not connected. No broker, account database or trading control was published. All six live-pilot gates remain unverified. The existing local paper engine was not replaced. The workspace is accessible to anyone with the URL; Google Doc and Drive permissions are unchanged.

A separate application checkout now implements the evidence workspace, six blocked live-pilot gates, pricing calculator, test guidance and selected simulator/API repairs. The release notes distinguish those repairs from remaining Nullius provenance/statistics work and incomplete broker integration. The original paper engine was not replaced. All six live gates remain unverified; no live order is authorized.
