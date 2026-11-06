"""Follow JustLend jUSDT receipts out of the Tron tree: deposit (tree) -> jUSDT transfers (hops) -> redemption (USDT paid by the jUSDT market).
The ledger tracks TRX/USDT only, so a receipt that changes hands is a blind spot; this finds the redeemers and what still sits as jUSDT.
  python3 jusdt_trace.py   -> raw/tron/jusdt_flow.json (per wallet) + raw/tron/jusdt_redeems.json ({key: (redeemer, USDT, tx, ts)}, for cf_refund_repair.py)"""
import json, os, sqlite3, time, urllib.request, threading
from concurrent.futures import ThreadPoolExecutor
from tron_ledger import T0
from collections import defaultdict, deque
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K = E['TRONGRID_API_KEY']; JU = 'TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd'; USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'; ZERO = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb'
LOCK = threading.Lock(); LAST = [0.0]
def get(path):
    for i in range(6):
        with LOCK:
            w = LAST[0] + 0.125 - time.time()
            if w > 0: time.sleep(w)
            LAST[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io' + path, headers={'TRON-PRO-API-KEY': K, 'User-Agent': 'Mozilla/5.0'}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
def t20(a, token, extra=''):
    out, fp = [], None
    while True:
        d = get(f'/v1/accounts/{a}/transactions/trc20?contract_address={token}&limit=200&min_timestamp={T0}{extra}' + (f'&fingerprint={fp}' if fp else ''))
        out += [t for t in d.get('data', []) if t.get('type') == 'Transfer']; fp = (d.get('meta') or {}).get('fingerprint')
        if not fp: return out
C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
tree = {a for (a,) in C.execute("SELECT DISTINCT address FROM ledger_node WHERE run_id LIKE 'tron2-%' AND (inn>0 OR out>0 OR bal>0)")}
deps = {a for (a,) in C.execute("SELECT DISTINCT frm FROM ledger_edge WHERE too=? AND cls LIKE 'out:%'", (JU,))}
print(f'{len(deps)} tree wallets deposited into jUSDT; following receipts', flush=True)
W = defaultdict(lambda: {'ju_in': 0.0, 'ju_out': 0.0, 'redeemed': 0.0, 'first_redeem': None, 'in_tree': False, 'from': set()})
redeems = {}
def read(a):                                   # worker: one wallet's jUSDT moves (+ USDT redemptions only if it is NOT a tree wallet: tree redemptions are in the ledger)
    ju = t20(a, JU); us = t20(a, USDT, '&only_to=true') if a not in tree else []
    return a, ju, us
seen, level, t0 = set(), set(deps), time.time()
with ThreadPoolExecutor(8) as ex:
    while level:
        seen |= level; nxt = set()
        for a, ju, us in ex.map(read, sorted(level)):
            w = W[a]; w['in_tree'] = a in tree
            for t in ju:
                v = int(t['value']) / 1e8                                   # jUSDT: 8 decimals
                if t['to'] == a and t['from'] != a: w['ju_in'] += v; w['from'].add(t['from'])
                elif t['from'] == a:
                    w['ju_out'] += v
                    if t['to'] not in (ZERO, JU) and t['to'] not in seen: nxt.add(t['to'])   # receipt handed on: follow
            for t in us:
                if t['from'] == JU:                                          # redemption: the market pays USDT out
                    v = int(t['value']) / 1e6; w['redeemed'] += v; ts = t['block_timestamp']
                    w['first_redeem'] = min(w['first_redeem'] or ts, ts); redeems[t['transaction_id']] = (a, v, t['transaction_id'], ts)
        print(f'  hop done: {len(seen)} wallets read, {len(nxt)} new receipt holders next | {time.time() - t0:.0f}s', flush=True)
        level = nxt
live = {}
for a, w in W.items():
    if w['ju_in'] - w['ju_out'] > 1:
        d = (get(f'/v1/accounts/{a}').get('data') or [{}])[0]
        live[a] = sum(int(v) for x in d.get('trc20', []) for k, v in x.items() if k == JU) / 1e8
json.dump({a: dict(w, **{'from': sorted(w['from']), 'jusdt_held_live': live.get(a, 0.0)}) for a, w in W.items()}, open('raw/tron/jusdt_flow.json', 'w'), indent=1)
json.dump(redeems, open('raw/tron/jusdt_redeems.json', 'w'))
out_tree = {a: w for a, w in W.items() if not w['in_tree']}
print(f'\nwallets in the receipt chain: {len(W)} ({len(W) - len(out_tree)} in tree, {len(out_tree)} outside)')
print(f'redeemed by tree wallets:    {sum(w["redeemed"] for w in W.values() if w["in_tree"]):,.2f} USDT')
print(f'redeemed OUTSIDE the tree:   {sum(w["redeemed"] for w in out_tree.values()):,.2f} USDT by {sum(1 for w in out_tree.values() if w["redeemed"])} wallets ({len(redeems)} redemptions)')
print(f'jUSDT still held (live):     {sum(live.values()):,.2f} jUSDT in {sum(1 for v in live.values() if v > 1)} wallets: ' + ', '.join(f'{a} {v:,.2f}' for a, v in sorted(live.items(), key=lambda x: -x[1])[:5] if v > 1))
