"""Prove (or refute) Tron → Bitget Wallet Swap Bridge → Ethereum: match every Tron tree deposit to TZG47zhb (Bitget Wallet Swap
Bridge, user-identified) to the Bitget router 0xbc1d9760 ETH payouts into the feeder wallets found by eth_foreign_backtrack.py.
Read-only on every DB. Output raw/bitget_match.json.   python3 bitget_match.py"""
import json, os, sys, collections, time
os.chdir(os.path.dirname(os.path.abspath(__file__))); _a = sys.argv; sys.argv = ['x']; import eth_hs as H; sys.argv = _a
import tron_graph as g, sqlite3
ROUTER = '0xbc1d9760bd6ca468ca9fb5ff2cfbeac35d86c973'; BRIDGE = 'TZG47zhb8kcriWQ2rE719yHs1KqgzwMrvF'
# ---- Tron side: tree deposits to the bridge, one per (tx, sender), over the valid run chain
T = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(T)]; q = ','.join('?' * len(chain))
dep = {}
for h, ts, f, asset, v in T.execute(f"SELECT hash, ts, frm, asset, amount FROM ledger_edge WHERE run_id IN ({q}) AND too=? AND amount>0", chain + [BRIDGE]):
    dep[(h, f)] = {'tron_tx': h, 'ts': ts // 1000, 'from': f, 'asset': asset, 'amount': v}
dep = sorted(dep.values(), key=lambda d: d['ts'])
# ---- ETH side: router payouts (ETH, top-level or internal) into every feeder wallet of a Bitget-ending backtrack walk
W = json.load(open('raw/eth_foreign_backtrack.json'))['walks']
feed = sorted({c['to'] for w in W if w['end'].startswith('Bitget') for c in w['chain'] if c['from'] == ROUTER})
head = json.load(H.urllib.request.urlopen(H.urllib.request.Request(H.HS.replace('/query', '/height'), headers=H.HS_H), timeout=30))['height']
r = H.hs(H.HST, {'traces': [{'from': [ROUTER], 'to': feed}], 'field_selection': {'trace': ['transaction_hash', 'block_number', 'to', 'value', 'error', 'call_type'],
                 'block': ['number', 'timestamp']}}, H.HACK_BLOCK, head + 1)
bt = {H.num(x['number']): H.num(x['timestamp']) for x in r.get('blocks', [])}
pay = {}
for t in r['traces']:
    if H.num(t.get('value')) and not t.get('error'):
        pay[(t['transaction_hash'], t['to'].lower())] = {'eth_tx': t['transaction_hash'], 'block': H.num(t['block_number']), 'ts': bt.get(H.num(t['block_number'])), 'to': t['to'].lower(), 'eth': H.num(t['value']) / 1e18}
pay = sorted(pay.values(), key=lambda p: p['block'])
print(f"TRON deposits to Bitget bridge: {len(dep)} · {sum(d['amount'] for d in dep):,.2f} {collections.Counter(d['asset'] for d in dep)} · "
      f"{time.strftime('%m-%d %H:%M', time.gmtime(dep[0]['ts']))} → {time.strftime('%m-%d %H:%M', time.gmtime(dep[-1]['ts']))} UTC")
print(f"ETH router payouts to {len(feed)} feeder wallets: {len(pay)} · {sum(p['eth'] for p in pay):,.4f} ETH · "
      f"{time.strftime('%m-%d %H:%M', time.gmtime(pay[0]['ts']))} → {time.strftime('%m-%d %H:%M', time.gmtime(pay[-1]['ts']))} UTC")
json.dump({'deposits': dep, 'payouts': pay}, open('raw/bitget_match_inputs.json', 'w'))
# ---- one-to-one match. Bitget Wallet DEDUCTS ITS FEE from the payout: measured on the first 188 pairs (11-04) received/sent 0.995–0.997,
# delay 26–60 s ⇒ band LO..HI and <= MAXD. The fee is booked per pair (native USDT in − USD value of ETH out), never dropped.
LO, HI, MAXD = 0.985, 1.003, 900
PX = {int(k): v for k, v in json.load(open('raw/ethusdt_1m.json')).items()}
px = lambda ts: PX.get(ts - ts % 60) or PX.get(ts - ts % 60 - 60)
def match(pay, dep):
    used, M = set(), []
    for p in pay:
        usd = p['eth'] * px(p['ts']); best = None
        for i, d in enumerate(dep):
            if i in used or not (0 <= p['ts'] - d['ts'] <= MAXD): continue
            r_ = usd / d['amount']
            if LO <= r_ <= HI and (best is None or abs(0.996 - r_) < abs(0.996 - best[1])): best = (i, r_)
        if best: used.add(best[0]); d = dep[best[0]]; M.append({**p, 'usd': round(usd, 2), 'ratio': round(best[1], 5), 'fee_usd': round(d['amount'] - usd, 2), 'delay_s': p['ts'] - d['ts'], 'deposit': d})
    return M, used
M, used = match(pay, dep)
mk = lambda m: m['eth_tx'] + m['to']
un = [p for p in pay if mk(p) not in {mk(m) for m in M}]
# ---- payouts with no deposit in our Tron ledger: ask TronGrid for USDT deposits into the bridge in the MAXD window before each payout
import threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
TE = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
TH = {'TRON-PRO-API-KEY': TE['TRONGRID_API_KEY'], 'User-Agent': 'Mozilla/5.0', 'accept-encoding': 'identity'}; _lk = threading.Lock(); _t = [0.0]   # never print
def tg(u):
    for i in range(6):
        with _lk:
            w = _t[0] + 0.13 - time.time()
            if w > 0: time.sleep(w)
            _t[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=TH), timeout=40))
        except Exception: time.sleep(2 * (i + 1))
    return {'data': []}
def window(p):
    u = (f"https://api.trongrid.io/v1/accounts/{BRIDGE}/transactions/trc20?only_to=true&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
         f"&min_timestamp={(p['ts'] - MAXD) * 1000}&max_timestamp={p['ts'] * 1000}&limit=200")
    return [{'tron_tx': x['transaction_id'], 'ts': x['block_timestamp'] // 1000, 'from': x['from'], 'asset': 'USDT', 'amount': int(x['value']) / 1e6}
            for x in tg(u).get('data', []) if x.get('type') == 'Transfer' and int(x['value'])]
with ThreadPoolExecutor(8) as ex: cand = {d['tron_tx'] + d['from']: d for w in ex.map(window, un) for d in w}
known = {d['tron_tx'] + d['from'] for d in dep}
extra = sorted((d for k, d in cand.items() if k not in known), key=lambda d: d['ts'])
M2, _ = match(un, extra)
TW = {a for (a,) in T.execute('SELECT DISTINCT address FROM ledger_node')}
for m in M2: m['depositor_in_tron_tree'] = m['deposit']['from'] in TW
rest = [p for p in un if mk(p) not in {mk(m) for m in M2}]
def line(tag, X): return (f"{tag}: {len(X)} payouts · {sum(m['eth'] for m in X):,.4f} ETH ≈ ${sum(m['usd'] for m in X):,.0f} ← {sum(m['deposit']['amount'] for m in X):,.2f} USDT"
                         f" · fee {sum(m['fee_usd'] for m in X):,.2f} USD ({sum(m['fee_usd'] for m in X) / max(1, sum(m['deposit']['amount'] for m in X)) * 100:.3f}%)"
                         f" · delay median {sorted(m['delay_s'] for m in X)[len(X) // 2] if X else '-'} s")
print('\n' + line('A. deposit in our Tron ledger', M))
print(line('B. deposit found on TronGrid, NOT in our ledger', M2))
ins = [m for m in M2 if m['depositor_in_tron_tree']]; outs = [m for m in M2 if not m['depositor_in_tron_tree']]
print(f"     depositor is a Tron tree wallet: {len(ins)} ({sum(m['eth'] for m in ins):,.4f} ETH) · depositor NEW to us: {len(outs)} ({sum(m['eth'] for m in outs):,.4f} ETH, {len({m['deposit']['from'] for m in outs})} addrs)")
print(f"C. no Bitget USDT deposit on Tron within {MAXD} s: {len(rest)} payouts · {sum(p['eth'] for p in rest):,.4f} ETH")
print(f"Tron ledger deposits never paid out to a feeder: {len(dep) - len(used)} · {sum(d['amount'] for i, d in enumerate(dep) if i not in used):,.2f} USDT (→ tree seeds / other chains)")
json.dump({'band': [LO, HI, MAXD], 'A_ledger': M, 'B_trongrid': M2, 'C_unmatched': rest}, open('raw/bitget_match.json', 'w'), indent=1)
# ---- tie each TM8uyBjR deposit (Bitget Wallet swap→bridge settlement, carries other users' money too) to ONE tree bwswap/SunSwap swap
# that paid it (raw/tron/swap_redirects.json): same USDT within 0.1 %, deposit <= 1 h after the swap. Only tied deposits count as proven.
TM8 = 'TM8uyBjRKzFtQdMC7tQLvKeeWieaFvXDyc'
sw = {k: x[2] for k, v in json.load(open('raw/tron/swap_redirects.json')).items() for x in v if x[1] == TM8}
sts = {h: t // 1000 for h, t in T.execute(f"SELECT hash, MIN(ts) FROM ledger_edge WHERE run_id IN ({q}) GROUP BY hash", chain) if h in sw}
S = sorted((sts[h], v, h) for h, v in sw.items() if h in sts); su = set()
for m in sorted((m for m in M2 if m['deposit']['from'] == TM8), key=lambda m: m['deposit']['ts']):
    dt, amt = m['deposit']['ts'], m['deposit']['amount']; best = None
    for i, (t, v, h) in enumerate(S):
        if i not in su and 0 <= dt - t <= 3600 and abs(v - amt) <= max(0.01, amt * 0.001) and (best is None or abs(v - amt) < abs(S[best][1] - amt)): best = i
    if best is not None: su.add(best); t, v, h = S[best]; m['tree_swap'] = {'tron_tx': h, 'ts': t, 'usdt': v}
proven = M + [m for m in M2 if 'tree_swap' in m]; pk = {mk(m) for m in proven}
print(line('PROVEN (A + B tied to a tree swap)', proven))
# feeder = ETH wallet that got router payouts; proven feeder = EVERY router payout it got is proven → its sends into the tree are Tron-tree money
byf = collections.defaultdict(list)
for p in pay: byf[p['to']].append(mk(p) in pk)
PF = sorted(f for f, v in byf.items() if all(v))
print(f"proven feeders: {len(PF)}/{len(byf)} (wallets whose every Bitget payout is proven) → eth_hs.reclass relabels their tree sends")
json.dump({'band': [LO, HI, MAXD], 'A_ledger': M, 'B_trongrid': M2, 'C_unmatched': rest}, open('raw/bitget_match.json', 'w'), indent=1)
json.dump({'note': 'bitget_match.py 2026-11-04: ETH wallets whose every Bitget router payout matches a Tron tree deposit (A) or a TM8uyBjR deposit tied to a tree swap (B)',
           'feeders': PF}, open('raw/bitget_proven_feeders.json', 'w'), indent=1)
