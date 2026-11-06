"""11-05: ETH tree deposits that eth_thor_resolve.py (THORChain Router edges only) and the hard-coded ETH_BTC rows never saw:
THORChain VAULT EOAs (booked 'out:hub/service (5,xxx tx sent)'), Chainflip deposit CHANNELS (booked 'out:contract'), labelled Chainflip /
Relay edges. Each deposit hash of the CURRENT ETH run -> shared resolver (THORNode, then Chainflip, then Relay).   python3 eth_vault_resolve.py
-> raw/eth_vault_dest.json {hash: {from, eth, cls, kind, status, chain, asset, address, amount, out_tx}} (btc_seeds.py reads BTC payouts)."""
import os, sys, json, sqlite3, collections
os.chdir(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
C = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True); R = C.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%'").fetchone()[0]
D = C.execute("""SELECT hash, frm, SUM(amount), MIN(cls) FROM edge WHERE run_id=? AND asset='ETH' AND (cls LIKE 'out:hub/service%' OR cls='out:contract'
                 OR cls LIKE 'out:Chainflip%' OR cls LIKE 'out:Relay%') GROUP BY hash, frm""", (R,)).fetchall()
print(f'{R}: {len(D)} deposits {sum(x[2] for x in D):,.2f} ETH', flush=True)
OK = lambda k, r: r and r.get('status') not in (None, 'not found') and (k != 'thorchain' or str(r['status']).startswith(('done', 'refund')))
rows = {}
for i, (h, f, v, cls) in enumerate(D):
    hit = None
    for k in (('relay',) if 'Relay' in cls else ('chainflip',) if 'Chainflip' in cls else ('thorchain', 'chainflip')):
        r = BR.lookup(k, h)
        if OK(k, r): hit = (k, r); break
    rows[h] = {'from': f, 'eth': v, 'cls': cls, **({'kind': hit[0], **hit[1]} if hit else {'kind': None, 'status': 'not a bridge deposit / unresolved'})}
    if i % 25 == 0: print(f'  {i}/{len(D)}', flush=True)
json.dump({'run': R, 'rows': rows}, open('raw/eth_vault_dest.json', 'w'), indent=1)
agg = collections.defaultdict(lambda: [0, 0.0, 0.0])
for r in rows.values(): k = (r['kind'], str(r['status'])[:22], r.get('chain')); agg[k][0] += 1; agg[k][1] += r['eth']; agg[k][2] += float(r.get('amount') or 0) if r.get('chain') in ('BTC', 'Bitcoin') else 0
for k, (n, e, b) in sorted(agg.items(), key=lambda x: -x[1][1]): print(f'  {str(k[0]):9} {k[1]:22} {str(k[2]):9} {n:4} deposits {e:10,.2f} ETH' + (f' → {b:,.8f} BTC' if b else ''))
