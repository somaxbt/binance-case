"""Classify the latest external_resolve result into groups and write the fresh attacker hops to raw/tron/external_add_auto.json
(for cf_refund_repair.py). Rules as used on 11-01: fresh EOA (created after the hack) that forwards into the tree / DeFi / bridges,
fresh layering wallets, fresh holders > $100. Service hubs and deposit addresses (sweep to a known hub) are NOT added.  python3 ext_add.py"""
import json, sys, time, sqlite3, collections
sys.argv = ['x']; import tron_graph as g, tron_fast as tf
from tron_ledger import T0
R = json.load(open(f'raw/tron/external_resolve_{time.strftime("%Y%m%d")}.json')); PX = g.PX
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(C)]
tree = {a for (a,) in C.execute("SELECT DISTINCT address FROM ledger_node WHERE run_id=?", (chain[-1],))}
HUBS = {a for a, lab in tf.EP.items() if lab.startswith(('exchange:', 'service:', 'bridge:'))}
grp = collections.defaultdict(list); out = {}
day = time.strftime('%F', time.gmtime(T0 / 1000))
for r in R:
    a = r['address']
    if a in tree or a in tf.EP: continue
    v = r['got_trx'] * PX['TRX'] + r['got_usdt']; fresh = r['created'] != '?' and r['created'] >= day
    on = r['onward_top'][0][0] if r['onward_top'] else None
    if on in HUBS: k = 'deposit address → service'
    elif fresh and (on in tree or (on and on in tf.EP)): k = 'add: fresh hop → tree/DeFi'
    elif fresh and on: k = 'add: fresh layering'
    elif fresh and r['role'].startswith('HOLDING') and v > 100: k = 'add: fresh holder'
    elif not fresh: k = 'older address (service candidate)'
    else: k = 'skip'
    grp[k].append(a)
    if k.startswith('add'):
        h, ts, amt = C.execute("SELECT hash, MIN(ts), amount FROM ledger_edge WHERE too=? AND cls='out:external'", (a,)).fetchone()
        if ts: out[h] = (a, amt, h, ts)
json.dump(out, open('raw/tron/external_add_auto.json', 'w')); json.dump(grp, open('raw/tron/external_groups_auto.json', 'w'), indent=1)
print({k: len(v) for k, v in grp.items()}, '| to add:', len(out))
