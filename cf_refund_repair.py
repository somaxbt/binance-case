"""Add refund/revert recipients (default raw/tron/cf_refunds.json; or pass another file, e.g. raw/tron/sym_reverts.json, decoded refundEgress txs) to the Tron ledger chain:
each recipient joins the window where its first refund landed and is carried (re-added) through every later window,
together with any new wallets the repair finds. Uses tron_fast.py --add per run.  python3 cf_refund_repair.py"""
import json, sqlite3, subprocess, sys, time
ARGS = sys.argv[1:]; sys.argv = ['x'] + ARGS
import tron_graph as g
from tron_ledger import T0
TEC = 'TEcDijvKSXcfWT7S6rd44H5vNgufm7Y4XC'
C = sqlite3.connect('binance-live.db')
chain = g.run_chain(C)
ref = {}
SRC = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith('.json') else 'raw/tron/cf_refunds.json'
for h, (to, v, tx, ts) in json.load(open(SRC)).items():
    if to != TEC: ref[to] = min(ref.get(to, ts), ts)
carry = set()
for i, (r, p) in enumerate(chain):
    lo = p.get('from', T0) if i else T0; hi = p['cutoff']
    nodes = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (r,))}
    new = {a for a, ts in ref.items() if lo < ts <= hi and a not in nodes}
    todo = sorted((carry | new) - (nodes - carry))
    print(f'== {r}: window {time.strftime("%m-%d %H:%M", time.gmtime(lo/1000))}→{time.strftime("%m-%d %H:%M", time.gmtime(hi/1000))} | {len(new)} refund wallets land here, {len(carry)} carried in -> add {len(todo)}', flush=True)
    if not todo: continue
    pr = subprocess.run(['python3', '-u', 'tron_fast.py', '--add', r, *todo], capture_output=True, text=True); out = pr.stdout
    if pr.returncode: print(f'ERROR --add failed on {r} (exit {pr.returncode}):\n' + pr.stderr[-1500:], flush=True); sys.exit(1)
    print('\n'.join(l for l in out.splitlines() if 'UNEXPLAINED' in l or 'ERROR' in l or 'NOTE' in l or 'wallets in' in l), flush=True)
    after = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (r,))}
    carry |= (after - nodes) | set(todo)
print('carried set size', len(carry))
