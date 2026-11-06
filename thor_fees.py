"""What THORChain itself earned on the Tron tree's swaps: liquidity fees (RUNE) + outbound/network fees (asset), per deposit, from Midgard
actions; affiliate fees shown separately. USD at the hourly price of each action (Binance spot). Cache raw/tron/midgard_actions.json.
  python3 thor_fees.py"""
import json, os, sys, time, sqlite3, urllib.request, threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.argv = ['x']; import tron_graph as g
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(C)]
hs = sorted({h for (h,) in C.execute(f"SELECT DISTINCT hash FROM ledger_edge WHERE cls='out:thorchain' AND run_id IN ({','.join('?'*len(chain))})", chain)})
CACHE = 'raw/tron/midgard_actions.json'; cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
L = threading.Lock(); last = [0.0]
def get(h):
    for i in range(6):
        with L:
            w = last[0] + 0.25 - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return h, json.load(urllib.request.urlopen(urllib.request.Request(f'https://gateway.liquify.com/chain/thorchain_midgard/v2/actions?txid={h}', headers={'x-client-id': 'binance-trace', 'User-Agent': 'Mozilla/5.0'}), timeout=60)).get('actions', [])
        except Exception: time.sleep(5 * (i + 1))
    return h, None
todo = [h for h in hs if h not in cache]; print(f'{len(hs)} THORChain deposits, {len(todo)} to fetch', flush=True); t0 = time.time()
with ThreadPoolExecutor(4) as ex:
    for i, (h, a) in enumerate(ex.map(get, todo)):
        if a is not None: cache[h] = a
        if i % 200 == 199: json.dump(cache, open(CACHE, 'w')); print(f'  {i + 1}/{len(todo)} | {time.time() - t0:.0f}s', flush=True)
json.dump(cache, open(CACHE, 'w'))
def kl(sym):
    for u in (f'https://api.binance.com/api/v3/klines?symbol={sym}&interval=1h&startTime=1793304000000&limit=1000', f'https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1h&startTime=1793304000000&limit=1000'):
        try: return {int(r[0]): (float(r[1]) + float(r[4])) / 2 for r in json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))}
        except Exception: pass
    return {}
PX = {s: kl(s + 'USDT') for s in ('RUNE', 'ETH', 'BTC', 'TRX', 'ZEC')}
def px(sym, ms):
    if sym.startswith('USD'): return 1.0
    d = PX.get(sym) or {}; k = ms // 3600000 * 3600000
    return d.get(k) or (d[min(d, key=lambda x: abs(x - ms))] if d else 0.0)
liq_r = liq_u = 0.0; net = defaultdict(float); net_u = 0.0; aff = defaultdict(lambda: [0, 0.0]); seen = set(); n_sw = n_rf = 0; miss = 0
for h, acts in cache.items():
    if not acts: miss += 1; continue
    for a in acts:
        key = (a.get('type'), a.get('date'), json.dumps(a.get('in', []))[:200])
        if key in seen: continue
        seen.add(key); ms = int(a.get('date', 0)) // 1_000_000; m = (a.get('metadata') or {}); md = m.get('swap') or m.get('refund') or {}
        if a.get('type') == 'swap':
            n_sw += 1; r = int(md.get('liquidityFee') or 0) / 1e8; liq_r += r; liq_u += r * px('RUNE', ms)
            if md.get('affiliateAddress'): x = aff[md['affiliateAddress']]; x[0] += 1; x[1] += int(md.get('affiliateFee') or 0)
        elif a.get('type') == 'refund': n_rf += 1
        for f in md.get('networkFees') or []:
            sym = f['asset'].split('.')[-1].split('-')[0]; v = int(f['amount']) / 1e8; net[sym] += v; net_u += v * px(sym, ms)
print(f'\nactions: {n_sw} swaps, {n_rf} refunds (deposits without data: {miss})')
print(f'LIQUIDITY FEES (to THORChain pools / LPs): {liq_r:,.2f} RUNE ≈ ${liq_u:,.0f}')
print(f'OUTBOUND / NETWORK FEES: ' + ', '.join(f'{v:,.6f} {k}' for k, v in sorted(net.items(), key=lambda kv: -kv[1] * px(kv[0], 1793400000000))) + f'  ≈ ${net_u:,.0f}')
print(f'THORCHAIN TOTAL EARNED ≈ ${liq_u + net_u:,.0f}')
print('affiliates seen in swap metadata:', {k: (n, f'{bps/max(n,1):.0f} bps avg') for k, (n, bps) in aff.items()})
