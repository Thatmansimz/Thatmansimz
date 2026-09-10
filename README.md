# Tajari · Evidence workspace

Tajari is a research and technical evaluation workspace. It brings historical evidence, a scoped service offer, a test plan, paper-engine observation and six live-pilot requirements into one interface. No current strategy has established a deployable edge.

Start with the [shared master plan](https://docs.google.com/document/d/1lgEJ4ND83JNOWouX8QoYAcEl_BB4NahogO3FElErMsY/edit), its [repository copy](docs/TAJARI_MASTER_PLAN.md), and the [release notes](docs/RELEASE_2026-09-10.md).

## Current operating boundary

- This release starts disarmed, even if an old environment has `TRADING_ENABLED=true`.
- Broker construction and order submission reject Alpaca, Tradovate and unknown adapters. There is no live activation override.
- Starting trading, starting a forward campaign, replaying into the forward ledger and resetting that ledger are blocked. Historical observations cannot be promoted by renaming or resetting them.
- All HTTP mutations require a server-side `API_TOKEN`. An unset token disables mutations. Read endpoints are local observation surfaces.
- Historical evidence is labeled as a dated snapshot. The paper monitor shows only the connected checkout's database and reports unavailable status explicitly.
- No prop-firm eligibility, income target, score or small paper gain is treated as validation.

## Local preview

Use a separate checkout and a fresh data directory. Do not copy an existing engine's `.env`, paper state or trading database into a preview.

Install Python requirements in your preferred isolated environment, then start the backend from the repository root:

```bash
python3 -m pip install -r requirements.txt
BROKER=paper TRADING_ENABLED=false python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8011
```

In a second terminal:

```bash
cd frontend
npm ci
TAJARI_API_URL=http://127.0.0.1:8011 npm run dev -- --hostname 127.0.0.1 --port 3011
```

Open [the local workspace](http://127.0.0.1:3011). The frontend uses a server-side read-only proxy. `TAJARI_API_URL` is the upstream address; trading credentials never belong in browser environment variables.

For a production build, run `npm run build`. The existing Docker image uses Next.js standalone output. To run that output locally, copy `public` and `.next/static` into `.next/standalone` at the same relative paths, then run `HOSTNAME=127.0.0.1 PORT=3011 TAJARI_API_URL=http://127.0.0.1:8011 node .next/standalone/server.js`.

## Hosted partner workspace

Open or share **[Tajari production](https://tajari.vercel.app)**. The frontend release is commit `138b0e7`, deployed September 10, 2026.

The production frontend is deployed to the `tajari` project in the `storm-booked` Vercel team. Deploy from `frontend/`, using the committed `vercel.json` and lockfile. This serves the same evidence workspace as the local app, including the downloadable historical evidence, the test plan, live-pilot requirements and pricing calculator.

The hosted workspace does not contain the Python engine, trading database, broker credentials or licensed price bars. With no `TAJARI_API_URL` configured on Vercel, the monitor explicitly reports that the local engine is not connected. It does not invent a zero P&L or stopped-engine status. All trading protections remain in the canonical backend code; publishing the frontend does not activate or replace a running engine.

For an authorized release, run `npx vercel@59.15.1 deploy --prod --scope storm-booked` from `frontend/` after verification. Check the returned production URL in a clean browser, including the paper-monitor state and source-evidence links. The project currently uses manual deployments, not an automatic Git deployment. Search-engine indexing is disabled; this is a shareable URL, not an access-controlled workspace. The linked Google Doc and Drive evidence retain their existing sharing permissions.

## Verification

```bash
python3 scripts/test_isolated.py
cd frontend
npm run build
npm audit
```

The test runner changes into a temporary directory before discovery and forces paper mode with an isolated database. It never touches the running engine's state. Browser checks should cover all six views, evidence expansion, filter behavior, calculator economics, connected/offline status, keyboard access and mobile layout.

## Evidence and next milestones

The original evidence files in `frontend/public/evidence` preserve the assessment of application base `9808b0e`; new synthetic repair results live in `docs/repair-probes-2026-09-10.json`. Repairs do not rewrite historical results or certify a strategy.

The next commercial milestone is two independent paying customers for a defined evaluation, proposed at $1,500. This is a pricing hypothesis. The next research milestone is a frozen specification and a reproducible case study with honest uncertainty, costs and provenance. Critical Nullius integrity work, a completed broker adapter, realistic execution validation and all six live gates remain outstanding.
