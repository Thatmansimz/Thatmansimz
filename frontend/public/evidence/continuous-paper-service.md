# Tajari continuous paper service · September 14, 2026

The new service connects the existing Databento account to an isolated, persistent internal paper ledger. It uses real arriving MNQ minute bars and simulated execution. It cannot submit an order to a broker or exchange. The earlier engine and its historical campaign remain separate.

## Installed run and verification

Run `mnq-forward-20260915` was registered at **2026-09-15 02:31:49 UTC** (September 14 evening in Arizona) and installed as the current user's supervised macOS service. It runs immutable backend release `16f6d3c411602bd6686a21372942db5948a2ac53`. Live minute bars arrived and the service resolved MNQU6. Both simulated accounts start at $50,000. The startup observation occurred outside the rule's trading window, with no orders or fills; it is not a performance result.

All **128 backend tests** pass. The production frontend build and TypeScript checks pass. Browser verification reached the actual worker through its authenticated status API, with HTTP 401 without the private token and HTTP 200 with it. Desktop and 390px mobile layouts passed; no browser errors or horizontal overflow were observed. The [bounded smoke-test record](https://tajari.vercel.app/evidence/continuous-paper-smoke.json) preserves the connection and interface checks. A coherent backup of that completed smoke run was created separately; the operating run was not reset.

## Access and budget

A bounded check of the existing Databento key authenticated to GLBX.MDP3, resolved the continuous MNQ input to an actual contract and received a live `ohlcv-1m` bar. The check retained timestamps and counts, not prices, and was not a strategy evaluation. No subscription or plan was changed. Raw data and private ledgers stay on the worker host.

The budget for new services is at most $100/month. No new Databento plan was purchased. Databento currently advertises a Standard live-data plan at $199/month, so buying it would exceed that budget; existing technical access is already working. Existing account billing has not been independently reconciled. [Provider pricing](https://databento.com/pricing), [live API documentation](https://databento.com/docs/api-reference-live).

The selected partner-dashboard status store is Upstash Redis on its free plan, with automatic upgrades disabled. Vercel requires the account owner to accept the integration terms before provisioning can finish. Until then, the production website explicitly reports the continuous worker as unconnected. The authenticated local status endpoint can already observe the real worker; no public tunnel or trade-control endpoint is required.

## Registered operating rule

The [frozen protocol](https://tajari.vercel.app/evidence/continuous-paper-protocol.json) retains the opening-impulse engineering rule: observe all fifteen positive-volume opening minutes from 09:30 through 09:44 New York; buy if the last close is above the first open, sell if below, skip if equal. One MNQ contract maximum. At completion of 10:14, submit a reduce-only time exit for remaining inventory. Each simulated entry has an 80-tick stop.

The baseline starts with simulated $50,000 and declares one adverse tick plus $0.62 commission per side. A simultaneous second ledger uses four adverse ticks and $1.24 per side. These are explicit test assumptions, not verified broker quotes. Neither result establishes profitability. The economic hurdle for this run is operational qualification only; efficacy testing requires a separate frozen hurdle and appropriate uncertainty/search treatment.

The runtime records the protocol hash, source-file hashes, Python/Databento versions, registration time and preflight provenance before subscribing. Only subsequently arriving intervals are eligible. It never imports old paper balances, requests replay, backfills missed events or resets the ledger. A changed implementation or protocol cannot silently resume the same run.

## Failure and reconciliation behavior

- Record each provider receipt before processing either scenario. Restart can finish an interrupted receipt; order and fill identities remain stable.
- Reject stale, incomplete, conflicting, out-of-order or unmapped data. Processing delay is checked separately from network arrival time. New order eligibility cannot precede the actual decision time.
- Cancel unfilled entries before processing a post-gap event. Disconnects, missed opening minutes and risk limits suppress new entries. Outages remain in the evidence even when later data arrives.
- Resolve dated instrument IDs to actual contracts. Switch only while both scenarios are flat with no pending order, and suppress that day's entry. A contract roll with inventory hard-halts instead of carrying a lot into a different contract.
- Recompute orders, eligible events, fills, FIFO P&L and fees independently from the two ledgers. Daily close reports preserve unresolved inventory instead of claiming a clean session. Data gaps cannot receive invented fills.
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

Do not delete a STOP marker or alter a frozen registration to force a failed run to pass. Inspect failures and make any continuation decision explicit. Real-money trading still requires separate authorization after all six evidence and execution requirements are met.
