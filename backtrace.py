"""Back-trace a Tron wallet's funding, hop by hop (USDT + TRX), time-bounded: each hop only looks at the sender's inflows in the
WINDOW days before it paid the next wallet (one page per sender; never full histories of busy addresses). Every address is checked against
our Binance tree, the Xinbi case crawl (~/cases/xinbi/xinbi.db), attrib.db labels and known exchange hot wallets.
  python3 backtrace.py ADDR [HOPS=2] [WINDOW_DAYS=7] [MAX_TS_ms]   -> raw/tron/backtrace_<ADDR>.json"""
import json, os, sys, time, sqlite3, urllib.request, threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
A = sys.argv[1]; HOPS = int(sys.argv[2]) if len(sys.argv) > 2 else 2; WIN = (int(sys.argv[3]) if len(sys.argv) > 3 else 7) * 86400000
MAXTS = int(sys.argv[4]) if len(sys.argv) > 4 else None
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K = E['TRONGRID_API_KEY']; USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
HOT = {'TJ7hhYhVhaxNx6BPyq7yFpqZrQULL3JSdb': 'Bitget hot wallet', 'TJbZXZR9Hru126DiYevDiwVeP1sGoigvU9': 'HitBTC hot wallet',
       'TDoXUNZ6PajKuiUkcYg3EDSV9bnqGqsbcf': 'FixedFloat hot wallet', 'TX5XiRXdyz7sdFwF5mnhT1QoGCpbkncpke': 'NEAR Intents hot wallet'}
L = threading.Lock(); last = [0.0]
def get(p):
    for i in range(5):
        with L:
            w = last[0] + 0.13 - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io' + p, headers={'TRON-PRO-API-KEY': K}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
import hashlib
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58(h):
    a = bytes.fromhex(h); c = hashlib.sha256(hashlib.sha256(a).digest()).digest()[:4]; n = int.from_bytes(a + c, 'big'); s = ''
    while n: n, r = divmod(n, 58); s = B58[r] + s
    return s
def inflows(a, lo, hi):
    """value inflows to a in (lo, hi]: [(sender, usd, ts, asset)] — USDT >= 20, TRX >= 100"""
    out = []
    for t in get(f'/v1/accounts/{a}/transactions/trc20?only_to=true&limit=200&contract_address={USDT}&min_timestamp={lo}&max_timestamp={hi}').get('data', []):
        v = int(t['value']) / 1e6
        if t.get('type') == 'Transfer' and v >= 20 and t['from'] != a: out.append((t['from'], v, t['block_timestamp'], 'USDT'))
    for t in get(f'/v1/accounts/{a}/transactions?only_to=true&limit=200&min_timestamp={lo}&max_timestamp={hi}').get('data', []):
        c = (t.get('raw_data') or {}).get('contract', [{}])[0]; p = (c.get('parameter') or {}).get('value') or {}
        if c.get('type') == 'TransferContract' and p.get('amount', 0) >= 100e6 and b58(p['owner_address']) != a: out.append((b58(p['owner_address']), p['amount'] / 1e6 * 0.12, t['block_timestamp'], 'TRX'))  # TRX ~$0.12 in 2024
    return out
def profile(a):
    d = (get(f'/v1/accounts/{a}').get('data') or [{}])[0]
    return {'created': time.strftime('%F', time.gmtime(d.get('create_time', 0) / 1000)) if d.get('create_time') else '?', 'usdt_now': sum(int(v) for t in d.get('trc20', []) for k, v in t.items() if k == USDT) / 1e6, 'contract': d.get('type') == 'Contract'}
X = sqlite3.connect(os.path.expanduser('file:~/cases/xinbi/xinbi.db?mode=ro'.replace('~', os.path.expanduser('~'))), uri=True)
xcore = {a: d for a, d in X.execute('SELECT addr, depth FROM addr')}
def xedge(a):
    r = X.execute('SELECT SUM(usdt), COUNT(*) FROM edge WHERE src=? OR dst=?', (a, a)).fetchone(); return (r[0] or 0, r[1] or 0)
lab = {a: f'{n} ({c})' for a, n, c in sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db')).execute('SELECT a.address, e.name, a.category FROM attrib a JOIN entity_ref e ON e.id=a.entity_id WHERE a.address LIKE "T%"')}
C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True); tree = {a for (a,) in C.execute("SELECT DISTINCT address FROM ledger_node WHERE run_id LIKE 'tron2-%' AND (inn>0 OR out>0 OR bal>0)")}
def tags(a):
    t = []
    if a in HOT: t.append(HOT[a])
    if a in lab: t.append('label: ' + lab[a])
    if a in xcore: t.append(f'XINBI CRAWL core (depth {xcore[a]})')
    else:
        s, n = xedge(a)
        if n: t.append(f'in Xinbi crawl edges ({n} edges, {s:,.0f} USDT)')
    if a in tree: t.append('BINANCE TREE')
    return t
from tron_ledger import T0
hi0 = MAXTS or T0                                                  # by default: funding BEFORE the hack only
nodes = {A: {'hop': 0, 'tags': tags(A)}}; edges = []; frontier = [(A, 0, hi0)]
for hop in range(1, HOPS + 1):
    nxt = {}
    def work(x): a, lo, hi = x; return a, inflows(a, lo, hi)
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(work, [(a, (0 if hop == 1 else hi - WIN), hi) for a, _, hi in frontier]))
    for a, ins in res:
        agg = defaultdict(lambda: [0.0, 0, 9e15, 0, set()])
        for s, v, ts, asset in ins: g = agg[s]; g[0] += v; g[1] += 1; g[2] = min(g[2], ts); g[3] = max(g[3], ts); g[4].add(asset)
        for s, (v, n, f, l, assets) in sorted(agg.items(), key=lambda kv: -kv[1][0])[:8]:          # top 8 senders per wallet
            edges.append({'from': s, 'to': a, 'usd': round(v, 2), 'n': n, 'first': f, 'last': l, 'assets': sorted(assets), 'hop': hop})
            if s not in nodes:
                nodes[s] = {'hop': hop, 'tags': tags(s)}
                if s not in HOT and not any('label' in t for t in nodes[s]['tags']): nxt[s] = (s, hop, l)   # stop at exchanges / labelled entities
    frontier = list(nxt.values())
    print(f'hop {hop}: {len(frontier)} wallets to expand next', flush=True)
with ThreadPoolExecutor(6) as ex:
    for a, p in zip(list(nodes), ex.map(profile, list(nodes))): nodes[a].update(p)
json.dump({'root': A, 'nodes': nodes, 'edges': edges}, open(f'raw/tron/backtrace_{A}.json', 'w'), indent=1, default=list)
print(f'\nBACK-TRACE of {A} (funding before {time.strftime("%F", time.gmtime(hi0/1000))}, {HOPS} hops, {WIN // 86400000}-day window per hop)')
for e in sorted(edges, key=lambda e: (e['hop'], -e['usd'])):
    n = nodes[e['from']]
    print(f"  hop {e['hop']}  {e['from']} → {e['to'][:10]}  ${e['usd']:>12,.2f}  ({e['n']} tx, {'/'.join(e['assets'])}, {time.strftime('%Y-%m-%d', time.gmtime(e['last']/1000))})  "
          f"created {n.get('created')} holds {n.get('usdt_now', 0):,.0f} USDT{' CONTRACT' if n.get('contract') else ''}  {' | '.join(n['tags'])}")
hits = {a: n['tags'] for a, n in nodes.items() if any('XINBI' in t or 'Xinbi' in t or 'label' in t or 'TREE' in t for t in n['tags']) and a != A}
print('\nCONNECTIONS FOUND:', json.dumps(hits, indent=1) if hits else 'none')
