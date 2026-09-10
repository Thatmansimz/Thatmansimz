**Tajari / Nullius assessment — September 10, 2026**

**Recommendation: pursue a small paid evaluation service, retain tightly bounded trading research, and do not deploy this version with real capital.**

There is substantial reusable work here. There is not yet a demonstrated trading edge or a commercially reliable certification product. My recommendation is approximately 80% of Tajari effort on validating and delivering the harness business and 20% on research. That is an allocation of time, not of trading capital. Neither route currently supports a promise of quick wealth.

The fastest credible commercial experiment is selling a defined technical review with reproducible evidence. Building another broad trading platform or restarting a long paper campaign on the old strategy would postpone the decision that matters: whether a buyer will pay for the specific problem you can solve.

**What I actually inspected and verified**

- Original application: `/Users/michaelwilliamsii/Thatmansimz`, commit `9808b0e`, dated August 9. Its tracked working tree was clean.
- Research and harness: `/Users/Backpack/tajari-research`, commit `16d758b`, dated September 1. An existing, uncommitted change to `nullius/economics.py` fixes two previously identified issues. I preserved it.
- Reviewed repository inventories, architecture, critical strategy/data/execution/risk/broker paths, test code, frontend components, saved research outputs, the campaign backup, current database records, and the previous Tajari task history. This was a focused engineering and commercial assessment, not a claim that every line received exhaustive formal review.
- Reran 83 application tests safely in a disposable working directory; all passed. Reran all 209 existing harness test cases through their applicable runners; all passed.
- Independently reproduced several serious defects using synthetic inputs. These probes are alongside this document and do not contact brokers.
- Reran the already-used 2019–2021 FOMC analysis. Its output matched the committed result exactly. Independently recomputed its mean and uncertainty from the same already-used data.
- Read the running application's status and SQLite database without changing trading settings. No orders, customer messages, new market-data purchases, deployments, or new holdout experiments were initiated. I did not perform a frontend browser acceptance test or a real-broker integration test.

**Where the project actually stands**

There are two different products, and they are not yet joined into a verified pipeline.

| Component | What exists | Assessment |
|---|---|---|
| Trading application | FastAPI backend; SQLite trades, signals, accounts and equity records; Next.js dashboard | Useful local prototype and operating history |
| Strategies | ORB, momentum, optional ML and V2 multi-session logic | Active V2 is rule-based; none reviewed here establishes a deployable edge |
| Execution | Paper brackets, commissions, slippage, position monitoring and trailing stops | Useful simulation infrastructure with material correctness gaps |
| Risk controls | Daily-loss checks, projected open-risk checks, drawdown checks, position limits | A real starting point; passing unit tests is not exchange-level protection |
| Operations | Scheduler, feed-health reporting, restart scripts, watchdog and persistence | Operational work exists, but a stopped campaign did not remain stopped |
| Broker adapters | Paper, Alpaca and Tradovate classes | Tradovate lacks a complete order lifecycle; no TopstepX adapter found |
| Research | Historical MNQ files, result matrices, frictionless and inversion experiments, FOMC script | Valuable negative evidence; some original scripts and artifacts were lost from temporary storage |
| Nullius | 8,348 lines across contracts, data, economics, attacks, spec seals, holdout ledger, verdicts, CLI and HTML report | Substantial research prototype; its central evidence guarantees remain bypassable |

The active V2 confidence score is manually assembled from a base of 0.55 and bonuses for conditions. It is not a calibrated probability of winning and is not an LLM prediction. The optional ML implementation trains a gradient-boosting classifier. Adding a newer AI model to the existing loop would not repair an absent edge or an incorrect fill model.

At approximately 14:32 ET on September 10, `/api/status` reported `broker=paper`, `trading_enabled=true`, `strategy=multi_session`, `scheduler_running=true`, and symbols `[MNQ]`. The configuration restricts V2 to New York. The original July 28 campaign file is still present. Startup explicitly starts the scheduler when the environment enables trading and creates a campaign when one is missing. Therefore an earlier statement that the campaign was halted does not describe current operation.

The current database contains 14 closed trades in total, including old ORB trades. The six V2 trades since July 28 total **+$362.80**, versus the earlier four-trade V2 result of **+$886.00**. The two later trades, August 21 and August 24, total **−$523.20**. These are local paper records, not broker-confirmed profits, and their measurement defects limit what can be inferred. No open trade rows were present in the snapshot inspected.

**What the strategy evidence supports**

| Experiment | Evidence available | Decision implication |
|---|---|---|
| V2, New York, zero commissions/slippage, 2022–2024 | 12 saved quarterly outputs; 1,050 trades; **−$15,543.15**, or **−$14.80/trade** | Transaction costs alone do not explain the failure |
| V2, all sessions, zero friction | 12 saved quarterly outputs; 2,036 trades; **−$40,362.92** | Broadening the session set did not rescue this version |
| Inverted V2, New York, modeled costs | 12 saved outputs; 1,082 trades; **−$59,475.09**, or **−$54.97/trade** | Simply reversing entries was not a solution |
| Earlier condition scan | Historical record reports 285 tests and zero survivors of its correction | No validated candidate emerged; this was an exploratory screen, not proof that every possible MNQ edge is absent |
| CPI pre-release drift | Findings document: fitted n=36, +20.11 points, t=4.29; holdout n=18, +8.08 points, t=0.60 | Positive average but too uncertain to establish the proposed edge; result is ambiguous |
| FOMC pre-decision drift | Fitted n=24, +11.18 points; independently reproduced older test n=23, **+0.8043 points**, t=0.468, 47.8% positive | The attractive fitted magnitude did not generalize to this period |

The saved frictionless and inversion totals above were independently added from existing text outputs; they were not regenerated as fresh full strategy backtests. For the ordinary cost-inclusive matrix, only four complete New York quarterly outputs survive, all in 2022. Several later files are empty. I would not repeat a purported complete 12-quarter cost-inclusive total as independently verified.

The FOMC script reproduces, but it prints a “90% CI” using 1.34 standard errors. A two-sided 90% Student-t interval at 22 degrees of freedom uses about 1.717. The independently corrected interval is approximately **[−2.15, +3.75] points**, wider than the saved interval. This correction does not make FOMC tradeable. It makes the uncertainty clearer. The script also uses 0.72 points of NQ friction while the shared contract definition calculates 0.725. Small here, but evidence of inconsistent definitions.

I would change the earlier language that these tests “proved it was noise” or proved there is no edge. The defensible conclusion is narrower: **the tested rules have not demonstrated a durable, economically usable edge under credible validation.** FOMC could reflect regime dependence, chance, or other model/data limitations; these observations do not distinguish them conclusively.

The 2025–2026 data must not be advertised as globally pristine. The findings say CPI already consumed that holdout, and older work inspected parts of the later market history. The FOMC script's final “untouched” line only reflects that script's date range. A different hypothesis name or a one-minute window change does not make previously inspected outcomes unseen again.

**Application defects that matter before another campaign**

| Priority | Finding | Evidence and practical fix |
|---|---|---|
| P1 | Trading API still listens on all interfaces without application authentication | `backend/config.py:97`, `backend/main.py:240`, `scripts/run_engine.sh:25`; the environment also says `0.0.0.0`, and `netstat` showed `*.8000 LISTEN`. Restrict binding, authenticate mutations and protect browser requests. LAN listening is confirmed; public internet exposure was not tested. CORS alone is not authentication. |
| P1 | Submitted broker orders can escape the local trade ledger | Tradovate returns `status="submitted"`; `backend/services/execution.py:220` only records immediate `filled` results. A pending limit order may later fill while the engine has no corresponding managed trade. Implement persisted pending/partial/filled/rejected/cancelled states, idempotent client IDs and reconciliation. |
| P1 | Tradovate adapter is incomplete | Numeric contract IDs are compared with a root symbol string, fill lookup and stop updates inherit base stubs, and root-to-expiry mapping is absent. Stop-update return values/errors are not enforced by the execution layer. Complete one broker integration and test lifecycle failures before enabling it. |
| P1 | Paper exit can use a bar that happened before entry | `backend/brokers/paper_broker.py:143` checks whether a bar differs from the last checked bar, but never whether it occurred after entry. Synthetic probe: an order opened today was stopped out by a 2020 bar. Track execution timestamps and process only eligible subsequent market events. Do not retroactively reinterpret existing P&L as accurate. |
| P1 | EMA trailing begins before the documented +1R trigger | `backend/services/execution.py:364`. With entry 100, initial stop 90 and current price 102, the probe moved the stop to 99.5 even though +1R is 110. The existing trail patch has not landed in this checkout. Share one tested exit rule between replay and paper execution. |
| P2 | Data and simulation are insufficient for executable fills | The active feed maps MNQ to Yahoo's NQ continuous feed, polls bars, and permits cached fallback for an hour. A newly fetched but stale series can still count as a successful fetch. Validate actual exchange timestamps and use broker/exchange data for execution validation. Process missed bars after gaps rather than only the latest one. |
| P2 | News and prop-firm configuration are stale or contradictory | The event file only contains three June/July events. Backend and frontend disagree about Topstep automation. Use dated authoritative rules and refreshed calendars, with visible freshness. Topstep's current API page confirms personal-device restrictions; firm-specific rules need account/product-specific verification. |
| P2 | Optional ML training is not credible validation yet | `_label_trades` breaks on the long stop before a short target can be assigned. A steadily falling synthetic series produced zero short labels. Labels look six bars ahead, while the train/test split has no purge at the boundary. Repair labels, purge overlapping label horizons and evaluate net trading outcomes, not classification accuracy alone. This ML path is not the active V2 strategy. |
| P2 | Display language overstates evidence | V2 “AI confidence” is a heuristic score. Display-only price functions add random jitter. These are not the fill path, but should be explicitly labeled or removed from a serious evidence product. README “validated” claims and old positive-baseline references should be corrected. |

The old security and trailing patches exist under `patches/`, but their presence is not evidence of deployment. I did not apply them as part of this assessment.

**The harness is promising, but not yet a trustworthy seal**

September 1's internal review recorded 30 high-severity findings. They are review findings, not 30 independently re-proven defects in this assessment. I verified the following consequential cases against today's code:

1. **Reused data can become “tradeable.”** `nullius/verdict.py:384` trusts `was_fitted_on` rather than validating observation provenance against research boundaries. Supplying the same 24 observations twice, with opposite flags, yielded `PAYS`, `tradeable=True`, and a claim of 24 unseen observations. Persisted CLI samples carry this flag in editable JSON (`nullius/cli.py:395`).
2. **Better unseen performance can be falsely rejected.** `nullius/verdict.py:492` tests whether a fitted point estimate lies inside the unseen confidence interval. A synthetic fitted mean of +3 and an unseen mean of +14, with 120 observations, returned `REFUTED`. Evaluate net economics on unseen data; separately analyze deterioration with appropriate uncertainty in both samples. Improvement is not automatically refutation.
3. **An unverified executable can receive an intact seal.** `nullius/spec.py:822` records unreadable source as a note instead of a failure. An impostor callable with the same identity but different behavior received `seal_ok=True` in the probe. Seal immutable code/config/data manifests, and refuse execution certification when they cannot be verified.
4. **Minimum-evidence wording conflicts with the decision.** Five synthetic observations yielded both `PAYS` and an “UNDERPOWERED ... not tradeable” explanation. Fix the decision policy and wording together. I would not adopt the earlier review's suggestion to automatically reject every result from a low-power design: a larger-than-anticipated effect can legitimately clear a prespecified confidence bound. The current `2*SE` heuristic is not a full prospective power calculation with a stated alternative, alpha and target power.
5. **Experiment integrity is incomplete beyond the verdict.** Inspection confirms mutable live hypothesis fields feed the holdout path, saved multiplicity can be replaced by a default of one, and an absent/empty local ledger reads as a new experiment history. A local unkeyed hash chain cannot establish independent custody. These need end-to-end tests and externally anchored history before any commercial attestation claim.

The existing uncommitted economics patch does correctly reject a fitted mean as tradeable and reject non-finite capacity inputs. Those two checks passed my probes. They do **not** fix the separate `verdict.py` and CLI provenance paths.

There is also an important distinction between a reproducible file and credible evidence. A hash can show that a particular file matches a particular digest. It cannot establish that a researcher never saw the holdout, that all failed experiments were disclosed, or that an external broker filled an order. Marketing must reflect that distinction.

**Test results and their limits**

| Suite | Cases rerun | Result |
|---|---:|---|
| Original app unittest suite | 83 | Passed |
| Nullius unittest discovery: data, economics, holdout | 97 | Passed |
| Nullius attacks standalone runner | 16 | Passed |
| Nullius verdict standalone runner, including parameter cases | 32 | Passed |
| Nullius report standalone runner | 19 | Passed |
| Nullius spec functions, invoked with isolated temporary-path fixtures | 45 | Passed |
| **Total existing cases exercised** | **292** | **Passed, despite the reproduced defects** |

The advertised “97 tests” only exercised three of the seven test modules. Four modules use plain functions, which unittest discovery does not execute. All of those additional cases also pass, so this is both a test-discovery problem and an assertion-quality problem. No dedicated CLI test module was present. Adopt one runner and make it exercise the full register → research → holdout → verdict → report workflow, including intentional attempts to violate its guarantees.

High-value tests should assert correct behavior for known data leakage, contradictory metadata, empty samples, event-time boundaries, broker disconnects, delayed fills, partial fills, rejected stop changes and restarts. A green test count is useful only when breaking the behavior makes a meaningful test fail.

**The business I would try to sell**

Start with: **“We independently reproduce your automated strategy's results and identify data leakage, unrealistic fills, and discrepancies between backtests and paper execution before deployment.”**

Initial buyer hypothesis: small trading-software teams, independent systematic strategy developers and AI-finance product teams with Python code, a working experiment and an upcoming deployment or review. Qualify on a concrete decision, access to code/data, an accountable technical owner and willingness to pay. These are proposed buyers; I found no evidence of paying Nullius customers or validated demand.

The first offering should be a narrowly scoped engineering evaluation: one strategy, one instrument, a specified data period and one reproducible report. Deliver the original claim, reproduced result, execution assumptions, provenance inventory, failure demonstrations, prioritized repairs and explicit limitations. Use client-authorized data in an isolated environment. A human reviews every finding. Do not initially sell a general “safe to trade” certificate or a performance guarantee.

I would test **$1,000–$2,500 per pilot**, with fixed scope and a deposit, as a pricing hypothesis—not a discovered market rate. Ten focused buyer conversations and two paid pilots would be a better next milestone than more dashboard features. Track actual delivery hours and cloud/data/model costs. At $1,500 and 20 hours, gross revenue is $75/hour before every expense; at five hours, it is $300/hour. The repeatability of delivery determines whether this becomes a business.

If the same monitoring needs recur, test a monthly service for reproducibility checks and change reports. Build hosted self-service tooling only after several customers repeatedly request the same workflow. A service can generate revenue before a platform is complete; it is not automatically scalable, and it still requires credible technical delivery.

Claude's harness recommendation is directionally sensible. I disagree with treating a signed report or an interesting origin story as a ready-made attestation business. Institutional trust requires methodology, independent verification and demonstrated reliability. I also would not claim competitors ignore honest testing: [QuantConnect LEAN](https://github.com/QuantConnect/Lean) already provides an open-source research/trading engine, and its [reality-modeling documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) explicitly addresses fills and slippage. [QuantRocket](https://www.quantrocket.com/pricing/) sells an established software/data offering. Build an evaluation layer that works with existing engines instead of trying to replace all of them.

The differentiation to test is the combination of forensic reproducibility, adversarial failure cases, immutable experiment records and a report someone else can review. The long-term asset would be trusted delivery and a library of real failure patterns, not the number of agents or source-code lines.

The AI-trading activity you see is real, but availability is not evidence of profitability. For example, [TradingAgents' own documentation](https://github.com/TauricResearch/TradingAgents#reproducibility) describes nondeterministic decisions, live news/social inputs that can reflect the present even for a historical analysis date, and non-guaranteed backtest reproduction. That suggests an evaluation problem worth interviewing buyers about; it does not prove demand for Nullius. The [CFTC's AI trading advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html) also cautions against assuming automation generates unusually high or guaranteed returns.

Two commercial boundaries require real work before selling: data licenses and the scope of advice. [Databento](https://databento.com/pricing/) directs users to dataset-specific licensing and redistribution rights, while [CME](https://www.cmegroup.com/market-data/license-data.html) provides market-data licensing requirements. Do not bundle acquired CME data into a product merely because the original pull used credits. [NFA's CTA description](https://www.nfa.futures.org/members/cta/index.html) covers compensated advice about futures trading. Have qualified counsel assess the actual proposed service before offering tailored trading recommendations or account management; calling something a harness does not determine its regulatory treatment.

**How I would preserve the trading opportunity**

Use the repaired harness internally, with a small, prespecified research budget and a capped number of hypotheses. Stop treating additional agents or longer searches as evidence. The question is whether a mechanism survives genuinely new observations after realistic costs and at useful capacity.

For any eventual live pilot, require all of these:

- A frozen strategy, economic hurdle, experiment family and data-access record before evaluation; previously observed periods stay research data.
- A reproducible, net-of-cost result with uncertainty and multiple-search handling appropriate to the actual selection process. Use dependence-aware inference where observations overlap or cluster.
- Stress on fills, latency, spreads, missed data, roll dates and costs; show results under materially worse execution assumptions rather than one favorable setting.
- A frozen forward paper run with no unexplained differences between generated orders, eligible market events, fills, positions and P&L. Duration depends on independent opportunities and market conditions—not merely “60 days.” Eight FOMC events per year cannot quickly generate a rich validation sample.
- One completed broker adapter, exchange-held protective orders where supported, restart reconciliation, strict loss/exposure limits and demonstrated behavior under disconnects and rejected orders.
- Only then, a separately authorized pilot at the smallest viable size, with a predefined loss budget and no expectation that it provides income. Scale only against observed execution and drawdown evidence.

Switching MNQ to NQ reduces commission expressed in index points, but NQ also changes dollar risk and margin requirements. It does not validate the signal. Likewise, a positive average on rare events may be economically trivial: the reproduced FOMC mean, mechanically annualized at eight events and 0.725 points of friction, is about **$12.70 per NQ contract per year** before overhead. That is a conditional arithmetic illustration from an unestablished mean, not a return forecast. Increasing leverage does not fix the uncertainty.

For perspective on the wealth target, $50,000 earning an illustrative 20% net return produces $10,000 a year. This project has not established that return; the arithmetic simply explains why small starting capital plus urgent income expectations pushes traders toward dangerous sizing. Service revenue depends on finding buyers and delivering value, so it gives you more controllable variables to test now.

**A concrete next month**

1. **First week:** deliberately resolve whether the old paper process should remain on; repair the proven paper-time and trailing defects; restrict/authenticate the API; fix harness provenance, decision semantics, seal verification and test discovery. Preserve the old records with their limitations.
2. **Second week:** produce one independently recomputed case study and one known-positive synthetic control. Package an installable, version-pinned local runner with inputs, outputs and a manifest. Restore broken temporary paths. No multi-tenant SaaS build yet.
3. **Weeks two and three:** conduct ten buyer interviews and propose two paid, fixed-scope pilots. Investigate their actual deployment mistakes, current review process, cost of errors and purchasing authority. Do not pitch guaranteed returns.
4. **Fourth week:** deliver pilots, measure effort and costs, request feedback and decide whether there is a repeatable paid workflow. If qualified prospects will not pay or share the required inputs, revise or stop the business experiment instead of compensating with more features.

My first commercial milestone would be **two customers paying for repeatable technical evaluation**. My first trading milestone would be **one genuinely new, frozen, economically meaningful result plus trustworthy execution**. Both are concrete. Neither is presently achieved.

**Evidence files**

- [Saved-result totals and test inventory](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/saved-results-summary.json)

- [Research probes and spec-test results](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/research-probes.json)
- [Application probes](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/app-probes.json)
- [Reproduced FOMC output](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/fomc-rerun.txt)
- [Independent FOMC arithmetic](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/fomc-independent-check.json)
- [Research reproduction script](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/reproduce_research_findings.py)
- [Application reproduction script](/Users/Backpack/tajari-research/docs/assessment-2026-09-10/reproduce_app_findings.py)
- [Previous research findings](/Users/Backpack/tajari-research/docs/FINDINGS.md)

Production source and settings were left unchanged. The new files are assessment artifacts only. No new unseen market period was opened to select or retest a strategy.
