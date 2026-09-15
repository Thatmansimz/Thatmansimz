#!/usr/bin/env python3
"""Verify all files in a stopped coherent backup before transferring/restoring it."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def verify(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    required = {'receipts.sqlite', 'baseline-worker.sqlite', 'baseline-simulator.sqlite',
                'worse_costs-worker.sqlite', 'worse_costs-simulator.sqlite', 'registration.json', 'protocol.json'}
    files = manifest.get('files', {})
    if not required <= files.keys(): raise ValueError('Incomplete backup file set')
    for name, expected in files.items():
        p = root/name
        if Path(name).name != name or p.is_symlink() or not p.is_file(): raise ValueError('Unsafe or missing backup member')
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected: raise ValueError('Backup hash mismatch: '+name)
        if name.endswith('.sqlite'):
            with closing(sqlite3.connect(f'file:{p}?mode=ro&immutable=1', uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise ValueError('Database corruption')
    registration = json.loads((root/'registration.json').read_text())
    for item in registration.get('implementation_amendments', []):
        name = item['previous_registration']
        if name not in files: raise ValueError('Missing registration lineage archive')
    return {'run_id': registration['run_id'], 'registered_at': registration['registered_at'],
            'files_verified': len(files), 'manifest_sha256': hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(verify(parser.parse_args().directory), indent=2))
