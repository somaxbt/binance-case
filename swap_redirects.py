"""Find USDT swap outputs that the Tron tree's swaps paid to THIRD addresses (swap 'recipient' != sender), for all swap-router txs in the
run chain. Output: raw/tron/swap_redirects.json (per tx) + raw/tron/swap_redirect_add.json ({key: (recipient, usdt, tx, ts)} for
cf_refund_repair.py, fresh non-tree EOAs only) + a summary with the shared-address test for big recipients.  python3 swap_redirects.py"""
import json, os, sqlite3, sys, time, urllib.request, threading, hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.argv = sys.argv[:1]
import tron_graph as g
from tron_ledger import T0
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K = E['TRONGRID_API_KEY']; USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58(h):
    a = bytes.fromhex('41' + h[-40:]); c = hashlib.sha256(hashlib.sha256(a).digest()).digest()[:4]; n = int.from_bytes(a + c, 'big'); s = ''
    while n: n, r = divmod(n, 58); s = B58[r] + s
    return s
L = threading.Lock(); last = [0.0]
def get(p):
    for i in range(6):
        with L:
            w = last[0] + 0.125 - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io' + p, headers={'TRON-PRO-API-KEY': K}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(C)]; q = ','.join('?' * len(chain))
tree = {a for (a,) in C.execute("SELECT DISTINCT address FROM ledger_node WHERE run_id LIKE 'tron2-%' AND (inn>0 OR out>0 OR bal>0)")}
txs = {}
for h, frm, too, v, ts in C.execute(f"SELECT hash, frm, too, amount, ts FROM ledger_edge WHERE cls='out:swap' AND run_id IN ({q})", chain): txs.setdefault(h, (frm, too, v, ts))
CACHE = 'raw/tron/swap_redirects.json'; cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
todo = [h for h in txs if h not in cache]; print(f'{len(txs)} swap txs from the tree, {len(todo)} to scan', flush=True)
def scan(h):
    frm = txs[h][0]; out = []
    for lg in (get(f'/wallet/gettransactioninfobyid?value={h}') if False else get_info(h)).get('log', []):
        tp = lg.get('topics') or []
        if len(tp) == 3 and tp[0].startswith('ddf252ad') and lg.get('address', '').lower().endswith('a614f803b6fd780986a42c78ec9c7f77e6ded13c'):
            s, r = b58(tp[1]), b58(tp[2])
            if r != frm and s != frm: out.append((s, r, int(lg['data'], 16) / 1e6))
    return h, out
def get_info(h):
    for i in range(6):
        with L:
            w = last[0] + 0.125 - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io/wallet/gettransactioninfobyid', json.dumps({'value': h}).encode(), {'TRON-PRO-API-KEY': K, 'Content-Type': 'application/json'}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
t0 = time.time()
with ThreadPoolExecutor(8) as ex:
    for i, (h, out) in enumerate(ex.map(scan, todo)):
        cache[h] = out
        if i % 250 == 249: json.dump(cache, open(CACHE, 'w')); print(f'  {i + 1}/{len(todo)} | {time.time() - t0:.0f}s', flush=True)
json.dump(cache, open(CACHE, 'w'))
# recipients that are not the sender, not a pool hop (a pool sends to the next pool), not in the tree
pools = set(g.NOT_OUTSIDE) | {a for a in __import__('tron_fast').EP}
rec = defaultdict(lambda: [0.0, 0, 9e15, set(), set()])
for h, out in cache.items():
    if h not in txs: continue
    senders_in_tx = {s for s, r, v in out}
    for s, r, v in out:
        if r in senders_in_tx or r in pools or r in tree: continue          # intermediate hop / known contract / already traced
        x = rec[r]; x[0] += v; x[1] += 1; x[2] = min(x[2], txs[h][3]); x[3].add(txs[h][1]); x[4].add(h)
tot = sum(x[0] for x in rec.values())
print(f'\nUSDT swap outputs paid to {len(rec)} NON-tree third addresses: {tot:,.2f} USDT')
via = defaultdict(float)
for r, x in rec.items():
    for rt in x[3]: via[rt] += x[0] / len(x[3])
print('by router:', {k[:10]: round(v) for k, v in sorted(via.items(), key=lambda kv: -kv[1])})
def prof(a):
    d = (get(f'/v1/accounts/{a}').get('data') or [{}])[0]
    n_in = len({t['from'] for t in get(f'/v1/accounts/{a}/transactions/trc20?only_to=true&limit=200&contract_address={USDT}').get('data', []) if t.get('type') == 'Transfer'})
    return a, d.get('create_time', 0), d.get('type') == 'Contract', n_in
top = sorted(rec, key=lambda a: -rec[a][0])
with ThreadPoolExecutor(6) as ex: P = {a: (ct, ctr, n) for a, ct, ctr, n in ex.map(prof, top)}
add, shared = {}, []
for a in top:
    ct, ctr, n = P[a]; x = rec[a]; fresh = ct >= T0
    tag = 'CONTRACT' if ctr else 'SHARED (service?)' if n > 30 and len([h for h in x[4]]) < n / 2 else 'fresh' if fresh else 'older'
    if tag == 'fresh': add[sorted(x[4])[0]] = (a, x[0], sorted(x[4])[0], int(x[2]))
    elif tag != 'CONTRACT': shared.append((a, round(x[0]), x[1], tag, n))
json.dump(add, open('raw/tron/swap_redirect_add.json', 'w'))
print(f'fresh third-party recipients to add to the tree: {len(add)} ({sum(v[1] for v in add.values()):,.2f} USDT)')
print('NOT added (older / shared — check):'); [print('  ', s) for s in shared[:15]]
