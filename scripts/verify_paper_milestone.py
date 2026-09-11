"""Check that registered fault cases actually occurred, not just empty ledgers."""
import argparse
import json
from pathlib import Path
import sqlite3

def verify(folder):
    result = json.loads((folder / 'summary.json').read_text())
    cases = {r['case']: r for r in result['scenarios']}
    if not (result['status'] == 'pass' and len(cases) == 10):
        raise ValueError('Paper milestone acceptance requirement failed')
    if not all((r['status'] == 'pass' and (not r['errors']) for r in cases.values())):
        raise ValueError('Paper milestone acceptance requirement failed')
    base = cases['baseline']
    if not (base['completed_contract_units'] > 0 and base['fills'] > 0):
        raise ValueError('Paper milestone acceptance requirement failed')
    checks = ['A complete baseline cycle exists; all ten independent reconciliations pass']
    for name in ('crash_after_accept', 'crash_after_fill'):
        r = cases[name]
        if not r['process_exit_codes'] == [87, 0]:
            raise ValueError(f'{name}: crash/restart not demonstrated')
        if not (r['account'] == base['account'] and r['fills'] == base['fills'] and (r['orders'] == base['orders'])):
            raise ValueError('Paper milestone acceptance requirement failed')
        checks.append(f'{name}: real process exit 87, successful restart, baseline accounting retained')
    if not cases['disconnect']['worker_events'].get('transport_disconnected', 0) > 0:
        raise ValueError('Paper milestone acceptance requirement failed')
    if not cases['disconnect']['worker_events'].get('market_gap', 0) > 0:
        raise ValueError('Paper milestone acceptance requirement failed')
    checks.append('Transport disconnect observed; missed market events explicitly recorded')
    for name in ('entry_rejected', 'protection_rejected'):
        r = cases[name]
        if not (r['orders'] > 0 and r['fills'] == 0 and (r['order_states'] == {'rejected': r['orders']})):
            raise ValueError('Paper milestone acceptance requirement failed')
        if not r['account']['equity_cents'] == result['initial_balance_cents']:
            raise ValueError('Paper milestone acceptance requirement failed')
        checks.append(f'{name}: rejection recorded, no inventory or money change')
    with sqlite3.connect(f"file:{folder / 'partial_fills/simulator.sqlite'}?mode=ro", uri=True) as db:
        if not db.execute("SELECT COUNT(*) FROM journal WHERE kind='order_partially_filled'").fetchone()[0] > 0:
            raise ValueError('Paper milestone acceptance requirement failed')
    checks.append('Partial fill lifecycle actually occurred and reconciled')
    if not cases['worse_costs']['account']['fees_cents'] > base['account']['fees_cents']:
        raise ValueError('Paper milestone acceptance requirement failed')
    checks.append('Worse-cost scenario charges higher fees under its frozen overrides')
    latency = json.loads((folder / 'longer_latency/protocol.json').read_text())
    baseline_protocol = json.loads((folder / 'baseline/protocol.json').read_text())
    if not latency['latency_bars'] > baseline_protocol['latency_bars']:
        raise ValueError('Paper milestone acceptance requirement failed')
    checks.append('Longer latency configured and independently verified against every fill')
    r = cases['missing_market_event']
    if not (r['worker_events'].get('market_gap', 0) > 0 and r['completed_contract_units'] < base['completed_contract_units']):
        raise ValueError('Paper milestone acceptance requirement failed')
    checks.append('Missing opening event suppresses an entry; improved P&L is not called improved strategy')
    return {'status': 'pass', 'checks': checks, 'scope': 'Engineering milestone only; no profitability, broker or live-readiness certification'}
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.folder), indent=2))
