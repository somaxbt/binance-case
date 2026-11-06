"""11-05: deBridge DLN orders hidden inside SOL-ledger 'out: swap (DEX)' txs (raw/sol/swap_bridge_hidden_*.json from the 516-tx scan)
-> creation sig -> orderIds -> order (shared resolver kinds debridge_tx + debridge) -> dest chain / receiver / amount.
  python3 sol_debridge_resolve.py [hidden.json]  -> raw/sol/debridge_dest.json (rows like bridge_dest.json, kind 'debridge')"""
import json, os, sys, collections
sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
H = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'raw/sol/swap_bridge_hidden_20261105.json'))
rows, miss = [], []
for i, (sig, frm, sol, _) in enumerate(H):
    r = BR.lookup('debridge_tx', sig)
    if not r or r.get('status') == 'not found': miss.append(sig); continue
    for oid in r['order_ids']:
        o = BR.lookup('debridge', oid)
        if not o or o.get('status') == 'not found': miss.append(sig + ':' + oid); continue
        rows.append(dict(kind='debridge', sig=sig, order=oid, **{'from': frm}, sol=sol, status=o['status'], chain=o['chain'], asset=o['asset'],
                         address=o['address'], amount_raw=o['amount'], src_token=o['src_token'], src_amount_raw=o['src_amount']))
    if i % 50 == 0: print(f'  {i}/{len(H)} sigs · {len(rows)} orders · {len(miss)} unresolved', flush=True)
json.dump(rows, open('raw/sol/debridge_dest.json', 'w'), indent=0)
by = collections.defaultdict(lambda: [0, 0.0, set()])
for r in rows: k = (r['chain'], r['asset']); by[k][0] += 1; by[k][1] += r['sol']; by[k][2].add((r['address'] or '').lower())
print(f'{len(rows)} orders from {len(H)} txs · unresolved {len(miss)} {miss[:3]}')
for (c, a), (n, s, ad) in sorted(by.items(), key=lambda x: -x[1][1]): print(f'  {str(c):10} {str(a)[:12]:12} {n:4} orders {s:12,.2f} SOL in · {len(ad)} receivers')
st = collections.Counter(r['status'] for r in rows); print('states', dict(st))
