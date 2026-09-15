# Continuous internal paper worker on Google Cloud

This directory prepares one dedicated Compute Engine worker. It is **not a
completed deployment** and never enables real-money routing. The deployment
operator must record actual resource IDs, test results and cutover evidence in
the private operations record. Do not put credentials, paid market data or
private ledgers in this repository.

## Reviewed shape and prerequisites

- Company-owned project, an explicitly verified organization parent and linked
  billing account. Use the official Google Cloud SDK with the company account.
- Iowa `us-central1-a`, standard `e2-small`, Debian 13, 20 GB balanced boot disk
  and a separate 30 GB balanced data disk retained on instance deletion.
- A dedicated VPC permits inbound SSH only from IAP. OS Login is required.
  The ephemeral external IPv4 is intentional for outbound Databento and HTTPS;
  there is no public application port and no extra Cloud NAT gateway.
- Dedicated worker identity with `storage.objectCreator` on one private bucket;
  no service-account key and no bucket read/delete permission for the worker.
- Confirm company/cloud/non-display data rights and the existing data invoice
  before moving the feed. Do not purchase a duplicate data subscription.
- Recheck pricing before provisioning. The approved plan targets $25–$40 per
  month for hosting, disks, backup storage and monitoring. Project budget alerts
  are notifications, not a Compute Engine spending cap. Include all data and
  hosting subscriptions when checking the combined budget.

## Provision infrastructure

`provision.py` defaults to a dry run and does not call Google. Supply the actual
reviewed company values; the example placeholders are not runnable credentials.

```sh
python3 deploy/gcp/provision.py \
  --project COMPANY_PROJECT_ID \
  --account COMPANY_ACCOUNT_EMAIL \
  --organization COMPANY_ORGANIZATION_ID \
  --bucket COMPANY_PRIVATE_BACKUP_BUCKET
```

Inspect the plan, verify the account/project/billing, then add `--apply`. This
is a one-time provisioner. A partial failure deliberately stops. Inspect existing
resources and continue only the missing commands; do not rerun blindly or delete
resources just to make provisioning pass.

Create a project-scoped $40 monthly billing budget with notifications at 50%,
80% and 100%, subject to the owner's current budget. Record who receives it.
Verify the VM's network, IAP firewall, service-account roles, persistent-disk
attachment and public-access prevention on the bucket.

Copy `prepare-host.sh` over `gcloud compute scp --tunnel-through-iap`, using the
explicit project, company account and zone on every command. Execute it with
sudo only on the new dedicated VM. It refuses an existing installation and
formats only the designated blank data disk. It installs a **disabled** service;
it does not copy credentials, subscribe to data, or start a worker.

## Install the frozen worker without starting it

1. Archive the reviewed immutable backend commit, verify the archive SHA256
   after transfer, and extract it into `/opt/tajari/releases/COMMIT`. Keep the
   entire code/release ancestor chain root-owned and not writable by `tajari`.
   Use `/opt/tajari/current` as a root-owned symlink to that release.
2. Create `.venv-paper` inside the release using the reviewed Python version.
   Install `requirements-paper.lock`, run `pip check`, and execute the dedicated
   paper tests on Linux. Record Python, Databento and DBN versions. A different
   Linux runtime requires an explicit registration amendment, even when code
   and strategy are identical. Do not silently re-register the run.
3. Install `verify-backup.py` and `maintenance-backup.py` under the root-owned
   `/opt/tajari/operations` directory. Install the backup service/timer files
   in `/etc/systemd/system`, reload systemd, and leave the timer disabled until
   the real backup/upload/restore drill passes.
4. Privately transfer the environment file using IAP/SCP. Install it as
   `/etc/tajari/paper.env`, root:`tajari`, mode 0640, inside root-owned
   `/etc/tajari` (0750). It contains the existing Databento key and independent
   local/status tokens. Never print it, put it in a command argument, upload it
   to the public site, or commit it.
5. Install `/etc/tajari/backup.json` as root-owned mode 0600 with exactly the
   reviewed private bucket name, for example `{"bucket":"PRIVATE_BUCKET"}`.
   Metadata credentials supply bucket access at runtime; no SDK user login is
   needed inside the VM.

## Transfer the existing run: exactly one writer

This is an operator-controlled migration, not an unattended import script.
It must preserve failed observations and the original registration.

1. Read fresh source state. Require both scenarios flat, no accepted/partial/
   pending orders or intents, no hard halt and a current successful audit. If
   any check fails, investigate before a planned cutover. A safety stop remains
   available for an incident.
2. Deliberately stop the source through the registered CLI. Disable and unload
   its Mac LaunchAgent. Preserve its `STOP` and verify the process is gone.
   Never alter unrelated legacy services.
3. Take the source CLI's coherent backup after the worker releases its lock.
   Capture source balances, receipt/order/fill counts, original registration,
   protocol hash, implementation hashes and all registration amendments.
   Run `verify-backup.py` and retain the manifest and transfer checksum.
4. Create the cloud destination directory with **STOP already present** while
   the service remains disabled. The backup intentionally does not include
   STOP; restoring files alone must never authorize a start. Copy the verified
   backup to `/var/lib/tajari/runs/mnq-forward-20260915`, owned by `tajari`.
5. Confirm destination manifest and source counts/balances match exactly. Run
   `amend-registration` as `tajari`, using the Linux runtime, a new backup output
   path and a reason documenting the host/runtime migration. Preserve the
   original registration, frozen protocol, journals and amendment archives.
6. Audit the amended run without opening a feed. Construct `ContinuousPaper`
   under the exact release/runtime, reconcile, inspect the snapshot and close
   all handles. This records a process-start audit; the subsequent worker
   restart deliberately excludes the interrupted New York date. Never treat
   that date as a complete forward opportunity.
7. Only after the stopped source, destination audit and matching evidence are
   verified, remove the destination operator STOP and enable/start the cloud
   service. Do not remove a maintenance marker as part of a routine start.
8. Verify actual fresh public reports, the same registration and balances,
   increasing receipt counts during active markets, actual publisher success,
   and no second source process. Test a flat VM restart and repeat those checks.

The relay rejects decreasing receipt/order/fill counters, but **is not a lease
or cross-host lock**. A healthy-looking timestamp alone does not authorize a
restored backup. If recent history is lost, leave the restored worker stopped;
recover the missing history or explicitly register a replacement experiment.

## Backup, restore and independent alert proof

The timer runs weekdays at 17:15 New York time and does not catch up missed
runs. Restarting the frozen worker excludes its current New York date, so do
not move scheduled maintenance into the next opening window.

Maintenance requires fresh, flat, audited state with no pending orders. A
root-owned persistent marker is fsynced **before** stop. Systemd refuses to start
while that marker or operator STOP exists. Backup verification, packaging and
upload execute as the unprivileged user. Cloud Storage uses a unique object name
and `ifGenerationMatch=0`; the returned size and checksum are verified. The
root-owned `/etc/tajari/last-backup.json` stores the upload receipt. Failure or
abrupt termination leaves the persistent fence for investigation. Archive
uploads larger than 128 MiB deliberately fail closed pending a reviewed streaming
uploader; monitor growth. No retention deletion is automated by this package.

Before enabling the timer:

- Perform a real coherent backup and upload during the allowed maintenance
  window, or a separately controlled stopped-run migration backup. Check the
  real object generation and SHA256 against the source record.
- With an authorized human/operator identity, download that object into an
  isolated directory with STOP. Do not grant bucket read access to the worker
  merely to perform this drill. Verify safe archive members before extraction.
- Verify the manifest, all five databases, protocol and registration archives;
  run the exact-runtime `ContinuousPaper` audit without starting a feed.
  Record the restored counts and balances. A valid SQLite file alone is not
  proof of journal lineage or a safe continuation point.
- Configure an external Google Cloud uptime check for the deployed
  `/api/paper-service/health` endpoint and an alert policy with tested delivery.
  A normal `/api/paper-service` HTTP 200 can contain stale evidence and is not a
  health check. Inspect JSON `ok` or the health endpoint's HTTP 200/503 result.
- The health endpoint checks current worker reporting and reconciliation. It
  intentionally accepts a closed-market `data_review` state with current
  audits. It does not certify feed continuity or market-data coverage. Track
  those separately through receipts, connection state and exclusions.
- Add disk-space and backup-age monitoring, record notification recipients,
  verify a deliberate alert reaches them, then enable the backup timer. Do not
  mark monitoring complete merely because a configuration exists.

## Incidents

Preserve `STOP` and `/etc/tajari/maintenance-in-progress`. Inspect the journal,
publisher status, current audit, pending orders and last backup. Do not start
another host or replace current ledgers with an older backup. An engineer may
clear the owned maintenance marker only after explaining the failure, verifying
the current run and confirming no operator STOP or second writer. Missing data
and interrupted opportunities remain excluded evidence.

## Local verification

```sh
python3 -m unittest discover -s tests -p test_cloud_operations.py -v
bash -n deploy/gcp/prepare-host.sh
```

The frontend relay tests exercise the real Lua script against an isolated Redis
when `TAJARI_TEST_REDIS_BIN` identifies its binaries. No synthetic reports or
fault-injection switches are installed in the production endpoint. Unit tests
do not establish a real VM deployment, backup restore, data entitlement or
trading profitability.
