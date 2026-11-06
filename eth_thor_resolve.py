"""ETH tree → THORChain deposits of the CURRENT snapshot → payouts via the SHARED resolver (~/cases/_bridges, kind 'thorchain', THORNode).
Writes raw/eth_thor_dest.json (deposit → destination row). Re-run any time: cached deposits cost nothing.   python3 eth_thor_resolve.py"""
import os, sys, json, sqlite3, collections
os.chdir(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
C = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True); R = C.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%'").fetchone()[0]
D = C.execute("SELECT hash, frm, SUM(amount), MIN(block) FROM edge WHERE run_id=? AND cls LIKE 'out:THORChain%' AND asset='ETH' GROUP BY hash, frm", (R,)).fetchall()
for h, *_ in D: BR.lookup('thorchain', h)                 # synchronous + cached (THORNode ~1 s); pending swaps stay uncached -> next run
rows = {h: {'from': f, 'eth': v, 'block': b, **(BR.row('thorchain', h) or {'status': 'pending/unresolved'})} for h, f, v, b in D}
json.dump({'run': R, 'rows': rows}, open('raw/eth_thor_dest.json', 'w'), indent=1)
by = collections.defaultdict(lambda: [0, 0.0, 0.0])
for r in rows.values(): k = (r.get('status'), r.get('chain'), r.get('asset')); by[k][0] += 1; by[k][1] += r['eth']; by[k][2] += r.get('amount') or 0
print(f'{R}: {len(D)} THORChain deposits, {sum(r["eth"] for r in rows.values()):,.4f} ETH')
for k, (n, e, o) in sorted(by.items(), key=lambda z: -z[1][1]): print(f'  {k}: {n} deposits · {e:,.4f} ETH in → {o:,.8f} out')
top = collections.Counter()
for r in rows.values():
    if r.get('chain') == 'BTC': top[r['address']] += r.get('amount') or 0
print('  top BTC destinations:', [(a, round(v, 4)) for a, v in top.most_common(8)], '·', len(top), 'addresses')
