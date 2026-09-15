# Tajari continuous paper service · September 15, 2026

The new service connects the existing Databento account to an isolated, persistent internal paper ledger. It uses real arriving MNQ minute bars and simulated execution. It cannot submit an order to a broker or exchange. The earlier engine and its historical campaign remain separate.

## Installed run and verification

Run `mnq-forward-20260915` was registered at **2026-09-15 02:31:49 UTC**, before its first subscription, and installed as a supervised macOS service. The first immutable backend was `16f6d3c411602bd6686a21372942db5948a2ac53`. Real MNQ minute bars arrived and mapped to MNQU6. Both simulated accounts began at $50,000; the initial check occurred outside the opening window and created no orders.

**The overnight run was interrupted.** The host's lid/sleep and network history coincided with long heartbeat gaps and DNS failures. Only two bars had been recorded before the interruption, and the worker paused entries. This failed continuity observation is retained. It is not a completed forward trading sample.

An adversarial review reproduced four defects: active protective-lot corruption could escape reconciliation; deleted materialized orders could escape journal checks; heartbeats could indefinitely postpone the first-price timeout; and a failed audit could still show a previous “pass.” All four were fixed. Initial hardening release `9e99c78317f716849c149a3d02b9c610c244c945` also moves DNS/authentication off the supervisor thread and safely cancels an unfinished connection. Synthetic STOP testing returned in under one second while connection setup was deliberately stalled.

The same run was deliberately stopped, coherently backed up, independently reconciled, and explicitly amended to the new code. The original registration time, frozen strategy/cost assumptions, prior receipts, outage exclusions and both account balances remain unchanged. The old registration and STOP decision are archived. Live bars resumed after the upgrade. No historical backfill, reset, external broker order or performance claim was introduced.

A second review added an amendment-lineage startup guard, complete registration archives in backups, and a bounded cleanup deadline for stalled connectors. Current immutable backend release is `3842bee8afcaf1b60942cb673d13a1c3473ce0e0`. A deliberately interrupted amendment blocks before ledger recovery, and a restored amended backup passes the new lineage checks.

All **150 backend tests** pass in the development environment. All **52 paper-core tests** also pass in the dedicated locked paper runtime. The full legacy suite requires additional packages such as `pytz`; it is not installed or claimed to pass in the minimal paper-only environment. Coverage includes real subprocess crashes, partial fills, protection, journal/table tampering, late/missing data, contract rolls, restart recovery and registration amendments.

The frontend build and TypeScript checks passed for the initial monitor. Browser checks reached the actual authenticated status API (401 without its token; 200 with it), including desktop and 390px mobile layouts. See the [initial connectivity record](https://tajari.vercel.app/evidence/continuous-paper-smoke.json) and the [hardening/recovery record](https://tajari.vercel.app/evidence/continuous-paper-hardening.json). These verify specified engineering behavior, not profitability or enterprise uptime.

## Access and budget

A bounded check of the existing Databento key authenticated to GLBX.MDP3, resolved the continuous MNQ input to an actual contract and received a live `ohlcv-1m` bar. The check retained timestamps and counts, not prices, and was not a strategy evaluation. No subscription or plan was changed. Raw data and private ledgers stay on the worker host.

The updated ceiling for new recurring data/hosting charges is **$200/month**. No new subscription or paid hosting was purchased. Databento advertises Standard at $199/month, but current technical access already works; account billing and the subscriber's permitted company/non-display use still need verification. A plan payment alone does not establish all rights. [Pricing](https://databento.com/pricing), [licensing guide](https://databento.com/docs/api-reference-live/basics/metered-pricing).

The selected partner-dashboard store is Upstash Redis on its free plan, with automatic upgrades disabled. Vercel requires the account owner to accept integration terms before it can be provisioned. The relay code supports authenticated, bounded, allowlisted reports, pins the expected run, and atomically refuses an older or conflicting report. It remains unconnected until real credentials are provisioned and the flow is tested end to end. Production explicitly reports that current worker values are unavailable.

For a persistent cloud worker, see the [cutover runbook](https://tajari.vercel.app/evidence/cloud-paper-runbook.md). A proposed 1 GiB DigitalOcean VM lists at $6/month before extras. A new $199 data plan plus that host is $205, so that combination exceeds the current combined ceiling. Confirm existing billing before selecting any new charges. No cloud host, off-host restore drill or independent alert delivery has been demonstrated.

## Registered operating rule

The [frozen protocol](https://tajari.vercel.app/evidence/continuous-paper-protocol.json) retains the opening-impulse engineering rule: observe all fifteen positive-volume opening minutes from 09:30 through 09:44 New York; buy if the last close is above the first open, sell if below, skip if equal. One MNQ contract maximum. At completion of 10:14, submit a reduce-only time exit for remaining inventory. Each simulated entry has an 80-tick stop.

The baseline starts with simulated $50,000 and declares one adverse tick plus $0.62 commission per side. A simultaneous second ledger uses four adverse ticks and $1.24 per side. These are explicit test assumptions, not verified broker quotes. Neither result establishes profitability. The economic hurdle for this run is operational qualification only; efficacy testing requires a separate frozen hurdle and appropriate uncertainty/search treatment.

The runtime records the protocol hash, source-file hashes, Python/Databento versions, registration time and preflight provenance before subscribing. Only subsequently arriving intervals are eligible. It never imports old paper balances, requests replay, backfills missed events or resets the ledger. A changed implementation or protocol cannot silently resume the same run.

## Failure and reconciliation behavior

- Record each provider receipt before processing either scenario. Restart can finish an interrupted receipt; order and fill identities remain stable.
- Reject stale, incomplete, conflicting, out-of-order or unmapped data. Processing delay is checked separately from network arrival time. New order eligibility cannot precede the actual decision time.
- Cancel unfilled entries before processing a post-gap event. Disconnects, missed opening minutes and risk limits suppress new entries. Outages remain in the evidence even when later data arrives.
- Resolve dated instrument IDs to actual contracts. Switch only while both scenarios are flat with no pending order, and suppress that day's entry. A contract roll with inventory hard-halts instead of carrying a lot into a different contract.
- Reconstruct order identities, requests and lifecycle from journals; compare every current protective lot against fills, then independently recompute eligible events, FIFO P&L and fees. Daily close reports preserve unresolved inventory instead of claiming a clean session. Data gaps cannot receive invented fills.
- Count opening opportunities as they stood at decision time. Twenty complete opportunities call for an engineering review, not automatic validation or scaling.

Simulated stops cannot operate on prices that were never received, and they are not exchange-held orders. Loss limits are triggers, not guaranteed maximum losses through gaps. An external futures paper adapter and all six live-pilot requirements remain unfinished.

## Run and inspect

Use the dedicated locked dependencies and an environment file outside Git with mode 600. The environment template is `deploy/paper.env.example`; never put credentials in browser variables. From the application repository:

```bash
python3 -m venv .venv-paper
.venv-paper/bin/python -m pip install -r requirements-paper.lock
.venv-paper/bin/python scripts/continuous_paper.py register --run-dir /absolute/private/path/new-run
.venv-paper/bin/python scripts/continuous_paper.py run --run-dir /absolute/private/path/new-run --env-file /absolute/private/path/paper.env
.venv-paper/bin/python scripts/continuous_paper.py status --run-dir /absolute/private/path/new-run
```

The local read endpoint listens only on `127.0.0.1:8022/status` and requires the private `TAJARI_PAPER_LOCAL_TOKEN`. The Next.js server uses `TAJARI_PAPER_SERVICE_URL` and that token; browsers never receive it. Public responses use a field allowlist and show stale status after 150 seconds without a new report. The optional publisher sends aggregate simulated values, counts and operational state; it excludes licensed prices and private ledgers.

macOS supervision is installed using `scripts/install_paper_service.py` against a registered run and an immutable release directory. It restarts abnormal exits, preserves the run directory, and inhibits idle sleep while running. Closing the lid, logging out, power loss and network failure still interrupt the service. This is a supervised local worker, not a cloud-hosted uptime guarantee. A Linux systemd unit is included for a separately provisioned persistent host; no cloud worker account was purchased.

For a deliberate stop, write the persistent STOP marker using the command below. The service exits successfully and its supervisor does not restart it automatically. Preserve the run and logs. A backup requires the worker to be stopped so all ledgers represent one coherent cut.

```bash
.venv-paper/bin/python scripts/continuous_paper.py stop --run-dir /absolute/private/path/new-run
.venv-paper/bin/python scripts/continuous_paper.py backup --run-dir /absolute/private/path/new-run --output /absolute/private/path/new-backup
```

For a reviewed code/runtime fix, `amend-registration --run-dir … --output /new/backup --reason …` requires a stopped run and an unchanged protocol. It preserves the old registration, creates a coherent backup and appends a journal amendment. It leaves STOP in place; a continuation is a separate recorded operational decision. Any cloud copy must preserve registration archives and have only one active worker owner.

Do not delete a STOP marker or alter a frozen registration to force a failed run to pass. Inspect failures and make any continuation decision explicit. Real-money trading still requires separate authorization after all six evidence and execution requirements are met.
