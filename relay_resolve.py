"""Resolve every tree deposit into Relay's RelayDepository on Tron (TXtEs6t2) to its Relay request: destination chain,
recipient, currency, amount, out tx.  Cache: raw/tron/relay_requests.json (hash -> request).  python3 relay_resolve.py"""
import json, os, sqlite3, time, urllib.request, urllib.error
from collections import defaultdict
DEP = 'TXtEs6t2oUWQsNos7m68gbHdE9Q5n6x2oN'; CACHE = 'raw/tron/relay_requests.json'
C = sqlite3.connect('binance-live.db')
edges = {}
for h, ts, frm, asset, amt in C.execute("SELECT hash, ts, frm, asset, amount FROM ledger_edge WHERE too=? AND cls LIKE 'out:%' AND run_id IN "
                                        "(SELECT run_id FROM ledger_run WHERE leg='tron2' AND finished GLOB '2026*')", (DEP,)):
    edges[h] = (ts, frm, asset, amt)
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}      # hash -> request
users = sorted({frm for h, (ts, frm, a, v) in edges.items() if h not in cache})
print(f'{len(edges)} deposit txs from {len({e[1] for e in edges.values()})} senders; {len(users)} senders to query (v2, by user)', flush=True)
def fetch(u):
    out, cont = [], None
    while True:
        url = f'https://api.relay.link/requests/v2?user={u}&limit=50' + (f'&continuation={cont}' if cont else '')
        for k in range(8):
            try: r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)); break
            except urllib.error.HTTPError as e:
                if e.code == 429: print(f'  429, backing off {60*(k+1)}s', flush=True); time.sleep(60 * (k + 1))
                else: raise
        else: raise RuntimeError('429 persists')
        out += r.get('requests') or []; cont = r.get('continuation'); time.sleep(6)
        if not cont: return out
for i, u in enumerate(users):
    for q in fetch(u):
        for t in (q.get('data', {}).get('inTxs') or []):
            if t.get('hash') in edges: cache[t['hash']] = q
    json.dump(cache, open(CACHE, 'w'))
    if i % 10 == 9: print(f'  {i+1}/{len(users)} senders, {len(cache)} deposits resolved', flush=True)
agg = defaultdict(lambda: [0, 0.0, 0.0, set()]); status = defaultdict(int); miss = 0; tot = defaultdict(float)
for h, (ts, frm, asset, amt) in edges.items():
    q = cache.get(h); tot[asset] += amt
    if not q: miss += 1; continue
    status[q.get('status')] += 1
    for o in (q.get('data', {}).get('outTxs') or [{}]):
        m = q['data'].get('metadata', {}).get('currencyOut', {}); cur = (m.get('currency') or {}).get('symbol', '?')
        key = (o.get('chainId'), q.get('recipient'), cur)
        a = agg[key]; a[0] += 1; a[1] += amt if asset == 'USDT' else 0; a[2] += amt if asset == 'TRX' else 0
        a[3].add(o.get('hash'))
        try: a.append(float(m.get('amountFormatted') or 0))
        except Exception: pass
print('in:', {k: round(v, 2) for k, v in tot.items()}, '| status', dict(status), '| unresolved', miss)
print('chain | recipient | out currency | n | USDT in | TRX in | out amount')
for (ch, rc, cur), a in sorted(agg.items(), key=lambda x: -(x[1][1] + x[1][2] * 0.3)):
    print(ch, '|', rc, '|', cur, '|', a[0], '|', f'{a[1]:,.0f}', '|', f'{a[2]:,.0f}', '|', f'{sum(a[4:]):,.4f}')
