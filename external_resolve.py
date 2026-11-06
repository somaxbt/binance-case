"""Who are the Tron 'external wallets' the tree paid? Per destination: what it got from the tree, age, LIVE holding, onward destinations
(one recent page only), labels (local stores first, then Tronscan tags). Read-only.
  python3 external_resolve.py [N]   -> top N by value (default 30); writes raw/tron/external_resolve_<date>.json"""
import json, os, sqlite3, sys, time, urllib.request, threading
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30; sys.argv = sys.argv[:1]
import tron_graph as g
from tron_ledger import T0
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K = E['TRONGRID_API_KEY']; USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'; PX = g.PX
L = threading.Lock(); last = [0.0]
def get(url, h=None, gap=0.15):                 # ~4/s: shares the key with running jobs
    for i in range(5):
        with L:
            w = last[0] + gap - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h or {'TRON-PRO-API-KEY': K}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(C)]
X = defaultdict(lambda: {'TRX': 0.0, 'USDT': 0.0, 'n': 0, 'senders': set(), 'first': 9e15, 'last': 0})
for r in chain:
    nb = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (r,))}
    for f, t, s, v, ts in C.execute("SELECT frm, too, asset, amount, ts FROM ledger_edge WHERE run_id=? AND cls='out:external'", (r,)):
        if t in nb: continue
        x = X[t]; x[s] += v; x['n'] += 1; x['senders'].add(f); x['first'] = min(x['first'], ts); x['last'] = max(x['last'], ts)
top = sorted(X, key=lambda a: -(X[a]['TRX'] * PX['TRX'] + X[a]['USDT']))[:N]
tot = sum(x['TRX'] * PX['TRX'] + x['USDT'] for x in X.values())
lab = {}
for db, q in ((os.path.expanduser('~/traversal-engine/data/por-wallets.db'), 'SELECT address, name || " / " || nameTag || " (" || category || ")" FROM labels'),
              (os.path.expanduser('~/traversal-engine/data/attrib.db'), 'SELECT a.address, e.name || " (" || a.category || ")" FROM attrib a JOIN entity_ref e ON e.id=a.entity_id')):
    try: lab.update({a: n for a, n in sqlite3.connect(f'file:{db}?mode=ro', uri=True).execute(q) if a in set(top)})
    except Exception as e: print('label store', os.path.basename(db), 'skipped:', e)
tree = {a for (a,) in C.execute("SELECT DISTINCT address FROM ledger_node WHERE run_id=?", (chain[-1],))}
def look(a):
    acc = (get(f'https://api.trongrid.io/v1/accounts/{a}').get('data') or [{}])[0]
    trx = (acc.get('balance', 0) + sum(f.get('amount', 0) for f in acc.get('frozenV2', []))) / 1e6
    usdt = sum(int(v) for t in acc.get('trc20', []) for k, v in t.items() if k == USDT) / 1e6
    out = Counter()                                                          # one recent page of outgoing value (TRX + USDT)
    for t in get(f'https://api.trongrid.io/v1/accounts/{a}/transactions?only_from=true&limit=50').get('data', []):
        c = (t.get('raw_data') or {}).get('contract', [{}])[0]; p = (c.get('parameter') or {}).get('value') or {}
        if c.get('type') == 'TransferContract': out[h2b(p['to_address'])] += p['amount'] / 1e6 * PX['TRX']
    for t in get(f'https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_from=true&limit=50&contract_address={USDT}').get('data', []):
        out[t['to']] += int(t['value']) / 1e6
    tag = {} if os.environ.get('NO_TRONSCAN') else get(f'https://apilist.tronscanapi.com/api/accountv2?address={a}', {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://tronscan.org/'}, gap=1.0)
    return a, trx, usdt, out, acc.get('create_time', 0), (tag.get('addressTag') or tag.get('publicTag') or tag.get('name') or ''), tag.get('totalTransactionCount') or len(get(f'https://api.trongrid.io/v1/accounts/{a}/transactions?limit=200&max_timestamp={T0}').get('data', []))
from tron_ledger import h2b
with ThreadPoolExecutor(6) as ex: R = list(ex.map(look, top))
res = []
print(f"External destinations: {len(X)} addresses, ≈${tot/1e6:,.2f}M in total from the tree; top {N} = ≈${sum(X[a]['TRX']*PX['TRX']+X[a]['USDT'] for a in top)/1e6:,.2f}M\n")
for a, trx, usdt, out, ct, tag, ntx in R:
    x = X[a]; got = x['TRX'] * PX['TRX'] + x['USDT']; o = out.most_common(2)
    to_tree = sum(v for d, v in out.items() if d in tree); fresh = ct >= T0
    role = ('exchange/service (labelled)' if (lab.get(a) or tag) else
            'HOLDING (attacker-style)' if fresh and (trx * PX['TRX'] + usdt) > 0.5 * got else
            'pass-through → tree' if to_tree > 0.5 * sum(out.values() or [0]) else
            'busy service (old, many txs)' if (ntx or 0) > 5000 else
            'pass-through → elsewhere' if out else 'holding / inactive')
    res.append({'address': a, 'got_trx': x['TRX'], 'got_usdt': x['USDT'], 'txs': x['n'], 'senders': len(x['senders']), 'created': time.strftime('%F', time.gmtime(ct / 1000)) if ct else '?',
                'ntx': ntx, 'holds_trx': trx, 'holds_usdt': usdt, 'label': lab.get(a) or tag, 'onward_top': o, 'role': role})
    print(f"{a}  got {x['TRX']:>13,.0f} TRX {x['USDT']:>10,.0f} USDT  ({x['n']} txs from {len(x['senders'])} tree wallets)  created {res[-1]['created']} ntx {ntx}")
    print(f"    holds {trx:>13,.2f} TRX {usdt:>10,.2f} USDT | {role}{' | label: ' + (lab.get(a) or tag) if (lab.get(a) or tag) else ''}")
    print(f"    onward (recent page): " + ', '.join(f"{d} ${v:,.0f}{' [tree]' if d in tree else ''}" for d, v in o))
json.dump(res, open(f'raw/tron/external_resolve_{time.strftime("%Y%m%d")}.json', 'w'), indent=1, default=list)
print('\nroles:', dict(Counter(r['role'] for r in res)))
