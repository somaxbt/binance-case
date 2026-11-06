"""Compare two BTC ledger runs coin by coin (read-only on both DBs). Used to verify btc_ledger_fast.py against btc_ledger.py.
  python3 cmp_btc_runs.py OLD_DB [OLD_RUN] NEW_DB [NEW_RUN]      (run ids default to the latest run in each DB)
Compares: roots (bridged payouts) · every coin both runs have RESOLVED (status not 'pending'): owner, status class, spent_by, spent_height,
address, sats, note · every spend tx both have: kind, fee, inputs. 'unspent', 'unspent at tip (spent later)' and 'unspent (spend in mempool)'
are one class (all = unspent at the pinned tip); the text can differ only because the runs happened at different times."""
import sqlite3, sys
def latest(c): return c.execute('SELECT run_id FROM ledger_run ORDER BY started DESC LIMIT 1').fetchone()[0]
a = sys.argv[1:]
if len(a) == 2: (odb, ndb), orun, nrun = a, None, None
elif len(a) == 3: (odb, orun, ndb), nrun = a, None
else: odb, orun, ndb, nrun = a
O = sqlite3.connect(f'file:{odb}?mode=ro', uri=True); N = sqlite3.connect(f'file:{ndb}?mode=ro', uri=True)
orun, nrun = orun or latest(O), nrun or latest(N)
cls = lambda s: 'unspent' if (s or '').startswith('unspent') else s
def coins(c, r): return {(t, v): (ad, s, ow, st, sb, sh, nt) for t, v, ad, s, ow, st, sb, sh, nt in c.execute('SELECT txid,vout,address,sats,owner,status,spent_by,spent_height,note FROM utxo WHERE run_id=?', (r,))}
oc, nc = coins(O, orun), coins(N, nrun)
print(f'OLD {orun}: {len(oc)} coins · NEW {nrun}: {len(nc)} coins')
ro = {k for k, v in oc.items() if (v[6] or '').startswith('bridged')}; rn = {k for k, v in nc.items() if (v[6] or '').startswith('bridged')}
print(f'ROOTS  old {len(ro)} ({sum(oc[k][1] for k in ro)/1e8:,.8f} BTC) · new {len(rn)} ({sum(nc[k][1] for k in rn)/1e8:,.8f} BTC) · only-old {len(ro - rn)} · only-new {len(rn - ro)}')
for k in sorted(ro - rn)[:10]: print('   only OLD root', k, oc[k][:2])
for k in sorted(rn - ro)[:10]: print('   only NEW root', k, nc[k][:2])
both = [k for k in oc.keys() & nc.keys() if oc[k][3] != 'pending' and nc[k][3] != 'pending']
bad = []
for k in both:
    x, y = oc[k], nc[k]
    same = (x[0], x[1], x[2], cls(x[3]), x[6]) == (y[0], y[1], y[2], cls(y[3]), y[6]) and (cls(x[3]) == 'unspent' or (x[4], x[5]) == (y[4], y[5]))
    if not same: bad.append((k, x, y))
print(f'RESOLVED in both: {len(both)} coins · differences: {len(bad)}')
for k, x, y in bad[:12]: print(f'   {k[0][:16]}:{k[1]}\n      old {x}\n      new {y}')
ot = {t: r for t, *r in O.execute('SELECT txid,height,fee,n_in,n_out,attacker_in,foreign_in,kind FROM btx WHERE run_id=?', (orun,))}
nt = {t: r for t, *r in N.execute('SELECT txid,height,fee,n_in,n_out,attacker_in,foreign_in,kind FROM btx WHERE run_id=?', (nrun,))}
tb = [t for t in ot.keys() & nt.keys() if ot[t] != nt[t]]
print(f'TXS in both: {len(ot.keys() & nt.keys())} · differences: {len(tb)} · only-old {len(ot.keys() - nt.keys())} · only-new {len(nt.keys() - ot.keys())}')
for t in tb[:8]: print(f'   {t[:16]} old {ot[t]} new {nt[t]}')
pend_o = sum(1 for v in oc.values() if v[3] == 'pending'); pend_n = sum(1 for v in nc.values() if v[3] == 'pending')
print(f'still pending: old {pend_o} · new {pend_n}' + ('   (partial comparison — runs not finished)' if pend_o or pend_n else '   (both finished)'))
