#!/usr/bin/env python3
"""Coherent off-host backup after the session. Never resumes an operator STOP."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tarfile
import time
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

RUN = Path('/var/lib/tajari/runs/mnq-forward-20260915')
CODE = Path('/opt/tajari/current')
BACKUPS = Path('/var/lib/tajari/backups')
CONFIG = Path('/etc/tajari/backup.json')
MAINTENANCE_LOCK = Path('/run/lock/tajari-paper-maintenance.lock')
MAINTENANCE_MARKER = Path('/etc/tajari/maintenance-in-progress')
BACKUP_REPORT = Path('/etc/tajari/last-backup.json')
PROTOCOL = '517fe4c2af9f031e8d40cd841d8caa51aa15fe48deeaba3373d250481f41f412'


def execute(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=90).stdout


def is_active():
    return subprocess.run(['systemctl', 'is-active', '--quiet', 'tajari-paper'], timeout=10).returncode == 0


def flat(snapshot):
    return (snapshot['protocol_sha256'] == PROTOCOL and not snapshot['hard_halt']
            and len(snapshot['scenarios']) == 2
            and all(s['account']['position'] == 0 and s['reconciliation'] == 'pass' for s in snapshot['scenarios']))


def no_pending():
    for scenario in ['baseline', 'worse_costs']:
        for suffix, table in [('simulator', 'orders'), ('worker', 'intents')]:
            with closing(sqlite3.connect(f'file:{RUN}/{scenario}-{suffix}.sqlite?mode=ro', uri=True)) as db:
                if db.execute(f"SELECT COUNT(*) FROM {table} WHERE state IN ('pending','accepted','partially_filled')").fetchone()[0]:
                    return False
    return True


def upload(archive, bucket, name):
    # Instance identity only; no downloadable service-account key or SDK login.
    with urlopen(Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                         headers={'Metadata-Flavor': 'Google'}), timeout=10) as response:
        token = json.load(response)['access_token']
    if archive.stat().st_size > 128 * 1024 * 1024: raise ValueError('Backup exceeds reviewed upload memory limit')
    url = f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&ifGenerationMatch=0&name={quote(name, safe="")}'
    request = Request(url, data=archive.read_bytes(), method='POST',
                      headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/gzip'})
    with urlopen(request, timeout=90) as response:
        obj = json.load(response)
    md5 = base64.b64encode(hashlib.md5(archive.read_bytes(), usedforsecurity=False).digest()).decode()
    if obj.get('name') != name or int(obj['size']) != archive.stat().st_size or obj.get('md5Hash') != md5:
        raise ValueError('Upload identity or checksum mismatch')
    return obj['generation']


def package_upload(destination, bucket):
    # This entry point must run as the unprivileged service user. User-writable
    # archive paths can never redirect a root write through a symlink.
    if os.geteuid() == 0: raise ValueError('Archive and upload must be unprivileged')
    destination = Path(destination)
    if destination.parent != BACKUPS or not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', destination.name):
        raise ValueError('Unexpected backup directory')
    archive = destination.with_suffix('.tar.gz')
    with archive.open('xb') as out:
        with tarfile.open(fileobj=out, mode='w:gz', dereference=False) as pack:
            pack.add(destination, arcname=destination.name)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    generation = upload(archive, bucket, f'mnq-forward-20260915/{destination.name}-{sha}.tar.gz')
    return {'at': datetime.now(timezone.utc).isoformat(), 'archive_sha256': sha,
            'object_generation': generation, 'status': 'uploaded', 'backup': destination.name}


def main():
    os.umask(0o077)
    if os.geteuid() != 0: raise ValueError('Root maintenance runner required')
    config = json.loads(CONFIG.read_text())
    bucket = config['bucket']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket): raise ValueError('Invalid private bucket')
    # A restart invalidates its New York date. Never move this job before the
    # opening window, and never catch up missed timers during the next session.
    ny = datetime.now(ZoneInfo('America/New_York'))
    if not 17 <= ny.hour < 23: raise ValueError('Maintenance allowed only 17:00–22:59 New York')
    with MAINTENANCE_LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (RUN/'STOP').exists() or not is_active(): raise ValueError('Operator stop or inactive worker; no automatic resume')
        snapshot = json.loads((RUN/'status.json').read_text())
        age = time.time() - datetime.fromisoformat(snapshot['observed_at']).timestamp()
        if not 0 <= age <= 150 or not flat(snapshot) or not no_pending(): raise ValueError('Fresh, flat, audited state required')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        destination = BACKUPS/stamp
        owner = str(uuid.uuid4())
        # Root-owned persistent fencing precedes stop. SIGKILL, service timeout
        # and power loss cannot run cleanup; systemd must still refuse restart.
        with MAINTENANCE_MARKER.open('x') as marker:
            marker.write(owner+'\n'); marker.flush(); os.fsync(marker.fileno())
        directory = os.open(MAINTENANCE_MARKER.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        try:
            execute('systemctl', 'stop', 'tajari-paper')
            stopped = json.loads((RUN/'status.json').read_text())
            if stopped['connection'] != 'stopped' or not flat(stopped) or not no_pending():
                raise ValueError('Stopped ledger failed verification; leave worker stopped')
            if (RUN/'STOP').exists(): raise ValueError('Operator STOP present; leave worker stopped')
            execute('runuser', '-u', 'tajari', '--', str(CODE/'.venv-paper/bin/python'),
                    str(CODE/'scripts/continuous_paper.py'), 'backup', '--run-dir', str(RUN), '--output', str(destination))
            execute('runuser', '-u', 'tajari', '--', '/usr/bin/python3', '/opt/tajari/operations/verify-backup.py', str(destination))
            record = json.loads(execute('runuser', '-u', 'tajari', '--', '/usr/bin/python3',
                                '/opt/tajari/operations/maintenance-backup.py', '--package-upload', str(destination), bucket))
            if record.get('status') != 'uploaded' or record.get('backup') != stamp: raise ValueError('Invalid upload receipt')
            pending = BACKUP_REPORT.with_suffix('.writing')
            with pending.open('w') as out:
                out.write(json.dumps(record)+'\n'); out.flush(); os.fsync(out.fileno())
            os.replace(pending, BACKUP_REPORT)
            # Resume only after verification and successful off-host upload.
            # All failure paths deliberately remain stopped for investigation.
            if (RUN/'STOP').exists(): raise ValueError('Operator STOP appeared during backup')
            if MAINTENANCE_MARKER.read_text() != owner+'\n': raise ValueError('Maintenance ownership changed')
            MAINTENANCE_MARKER.unlink()
            execute('systemctl', 'start', 'tajari-paper')
            print(json.dumps(record))
        except Exception:
            # Preserve the root fence on failure, including failed restart.
            if not MAINTENANCE_MARKER.exists():
                with MAINTENANCE_MARKER.open('x') as marker:
                    marker.write(owner+'\n'); marker.flush(); os.fsync(marker.fileno())
                directory = os.open(MAINTENANCE_MARKER.parent, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            print(json.dumps({'status': 'failed_worker_left_stopped', 'at': datetime.now(timezone.utc).isoformat()}), flush=True)
            raise


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--package-upload':
        os.umask(0o077)
        print(json.dumps(package_upload(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 1: main()
    else: raise SystemExit('Unsupported invocation')
