# Tajari paper milestone · internal evaluation

**Engineering result: 10 of 10 registered scenarios reconciled. Trading profitability: not established. Buyer demand: not tested yet.**

This is the first internal demonstration of the proposed technical evaluation service. It uses a new isolated paper execution core, an independent accounting verifier and an existing paid-data export. It does not turn on a broker connection or replace the old local paper process.

## What was tested

A simulated $50,000 starting balance, one MNQ research instrument, five previously observed sessions from January 3–7, 2022, and 315 one-minute bars. The strategy takes the direction of the first fifteen minutes, waits a full minute before the first eligible simulated fill, uses a fixed protective stop and a time exit. Its purpose is to exercise an execution cycle, not to assert an alpha mechanism. The exact strategy, input digest, window, costs, stopping rule and ten scenarios were committed in `c33915e` before the research price slice was read. No new holdout, additional dates or parameter search was opened.

The existing Databento export contains 1,628,841 MNQ minute bars. Source SHA256: `fe416a569cde0cadb4660a85b17cc7a68558183878908c9fdfee268c1f2d2043`. The fetched source used `GLBX.MDP3`, `MNQ.v.0` and `ohlcv-1m`. The retained OHLCV export lacks actual contract identifiers and quotes; it is a continuous research series, not an executable contract or a live feed. Do not assume it is back-adjusted merely because the old fetch script said so.

The protocol uses a 0.25-point tick worth $0.50, consistent with [CME's MNQ specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.html). The $0.62 per-contract, per-side commission assumption is a test input, not a verified broker quote. One adverse tick per fill is embedded in baseline prices. Slippage, spread and queue realism remain unproven.

## Results

| Scenario | Completed contract round trips | Net simulated P&L | Reconciliation |
|---|---:|---:|---|
| Baseline, one contract | 5 | $20.80 | Pass |
| Process crash after order acceptance | 5 | $20.80 | Pass |
| Process crash after simulator fill | 5 | $20.80 | Pass |
| Worker transport disconnected | 5 | $20.80 | Pass; missed events recorded |
| Entry rejected | 0 | $0.00 | Pass; no exposure |
| Protective bracket rejected | 0 | $0.00 | Pass; no exposure |
| Partial fills, two-contract test | 10 | $50.10 | Pass |
| Double assumed commissions, four adverse ticks | 5 | $5.60 | Pass |
| Three full minutes of order delay | 5 | $58.30 | Pass |
| One opening minute removed | 4 | $62.54 | Pass; one entry suppressed |

Baseline price P&L was $27.00 after simulated fills and before commissions. Declared commissions were $6.20; final equity was $50,020.80. The worse-cost case finished at $50,005.60. All cases ended flat with no pending orders or unexplained reconciliation differences. Rejected-order cases demonstrate safe behavior, not completed trading opportunities.

Longer delays or missing data can improve a short replay by changing execution or removing a losing trade. Those larger numbers are not better strategies and were not used to select a new rule. The partial-fill case doubles quantity for a specific engineering test and is not directly comparable with one-contract returns. Five old sessions cannot establish an economic edge, a dependable return or an independent validation sample. No annualized return or confidence claim is made.

## What the engineering proof covers

- Intents are committed before submission. Stable client IDs prevent retries from creating duplicate orders; a conflicting request under the same ID is rejected.
- Simulator and worker have separate durable SQLite databases. Orders remain accepted or partially filled until actual simulator events move them to filled, expired, cancelled or rejected.
- Two scenarios terminate the actual worker process with exit code 87. Each restarts successfully with exit code 0 and recovers the baseline fills, orders and cents-level accounting.
- During injected transport failures, simulated protective stops remain active in the separate simulator. Reconnection retrieves fills and explicitly records missed worker market events.
- A separate verifier recalculates fill eligibility, adverse prices, fees, positions and FIFO P&L. It compares raw fills with both journals and detects altered fill tables or a fabricated account balance.
- Synthetic acceptance tests cover adverse gap fills, partial-entry cancellation after a stop, expiry of unfilled quantities, duplicate/out-of-order events, unknown broker orders, protocol drift, non-paper mode rejection and a drawdown halt that persists into the next session.

All 113 isolated backend tests pass, including 15 new paper-lab tests. The paid-data run is reproduced with implementation commit `80fc011`. Its pre-execution source fingerprints are preserved in `paper-milestone-execution-manifest.json`. The initial run is preserved separately; an unchanged-window repeat added implementation fingerprints and acceptance coverage, with the same scenario economics. Local hashes detect file changes but are not independent custody or proof of unseen data.

## Reproduce

Use a separate output directory outside the repository and the user's existing research Python environment for Parquet preparation:

```bash
/Users/Backpack/tajari-research/venv/bin/python scripts/paper_milestone.py prepare \
  --dataset /Users/Backpack/tajari-research/mnq_1m.parquet \
  --output /absolute/path/to/new-paper-run
python3 scripts/paper_milestone.py run --output /absolute/path/to/new-paper-run
python3 scripts/verify_paper_milestone.py /absolute/path/to/new-paper-run
python3 scripts/test_isolated.py
```

On another machine, use Python 3.11+ and install pandas plus pyarrow for the preparation step; the execution core and verifier use the standard library. Obtain data through an authorized source, not the public site. The full source digest must match before any price rows are read. The access record is written first. Existing execution folders cannot be overwritten. Preparation materializes only the registered date slice as research input. The script does not load API keys, purchase data or route broker orders.

Full private run records are in `/Users/Backpack/.local/share/tajari/paperlab/2026-09-11-verified-milestone/`; the initial attempt remains in the sibling `2026-09-11-first-milestone/`. Those folders contain paid research bars, simulator/worker databases, account files, process exits and audits. They are not included in the public deployment. Public artifacts contain the protocol, aggregate results, data hashes, code fingerprints and acceptance evidence.

## Evaluation finding and next build

The old broker path still lacks a complete asynchronous order lifecycle; this release adds an isolated replacement core rather than claiming the old runtime is repaired or broker-ready. The next milestone is a registered real-time paper run against a completed broker demo adapter or a separately validated streaming simulator, using an entitled feed and actual contract mapping. It needs authenticated operator access, supervised hosting, stale-feed detection, restart reconciliation, backups and observed broker rejection/protection behavior.

Historical data ownership does not establish current streaming entitlements. [Databento documents historical and live services separately](https://databento.com/docs/getting-started/build-first-app). A paid feed or broker account has not been activated by this work. The existing local engine remains unchanged and the hosted monitor remains explicitly disconnected.

This internal case supplies a reproducible sample report for the proposed $1,500 offer. The pilot scope, intake, interview questions and empty buyer tracker are ready. No buyer has been contacted, charged or counted as a paid pilot by this work. The broader Nullius provenance and inference defects remain open; no commercial attestation or profitability claim is justified.
