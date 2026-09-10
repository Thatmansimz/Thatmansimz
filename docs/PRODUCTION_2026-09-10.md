# Tajari production workspace · September 10, 2026

- Stable URL: https://tajari.vercel.app
- Deployed frontend commit: `138b0e7769f2eb2035aa101432db4e6a059ae568`
- Vercel team/project: `storm-booked/tajari`
- Project ID: `prj_FlMj44NxiXkA9WtuCbekgCWEbA9f`
- Deployment ID: `dpl_2ESSHSPUoKfpeSzQdRf45N7S1aJs`
- State: READY; target: production; source: CLI; Next.js 15.5.25.
- Vercel install/build succeeded; dependency audit: zero known vulnerabilities. The local production build and TypeScript checks also pass.

## Production verification

A clean browser opened the stable URL without logging into Vercel. The desktop navigation and pricing calculator work: changing the default eight delivery hours to twenty produces negative $100 contribution. At 390px, all six navigation links remain available and document width is 390px, with no horizontal overflow. No browser errors were reported.

The production `/api/workspace` and `/api/status` endpoints return HTTP 200 with `connection_status: not_connected`. The monitor displays “Local engine not connected” and no fabricated P&L metric. The FOMC source artifact returns HTTP 200 and preserves the independently calculated interval. Search-engine exclusion is present in metadata and response headers. The deployed functions had no error/fatal logs in the post-deploy scan; this is a point-in-time check, not a monitoring service.

## Operating boundary

This is the production **frontend workspace**. The Python engine remains local and was not replaced or exposed. No broker credentials, trading database, licensed price bars or live order controls are deployed. Current hosting has no `TAJARI_API_URL` configured. All six requirements remain unverified in the workspace and live routing remains blocked in the canonical backend release.

The stable production URL is shareable without authentication. Deployment-specific and team aliases may require Vercel authentication; share the stable URL above. Linked Google Docs and Drive files retain their separate sharing permissions. No custom domain was purchased or configured.

Deployments are currently manual. Re-run the documented frontend verification before a subsequent `vercel deploy --prod --scope storm-booked`; publish from the approved Git revision. A later authenticated engine connection is separate work and must preserve observation-only access and all existing live-pilot requirements.
