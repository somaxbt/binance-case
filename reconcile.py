"""Binance case, TRON exits: does what LEFT match what was RECEIVED?
  1. UNITS: every deposit sent into a bridge is classified completed / refunded / failed / unresolved; the four must add up to SENT.
  2. VALUE (completed swaps only, swap-time prices from the bridge's own record): USD in vs USD out, the gap vs the bridge's stated fees.
  python3 reconcile.py
Relay: currencyIn/Out.amountUsd + feesUsd. Symbiosis: txIn/tx priceUsd. Chainflip: fees[] (USDC/ETH), ETH priced at the median
Symbiosis ETH payout price of the same hour (Chainflip records carry no USD). THORChain: report aggregates only (approx, flagged)."""
import json, os, sqlite3, statistics, sys
from collections import defaultdict
sys.argv = sys.argv[:1]
import tron_graph as g
RAW = os.path.join(g.HERE, 'raw', 'tron'); load = lambda n: json.load(open(os.path.join(RAW, n))) if os.path.exists(os.path.join(RAW, n)) else {}
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True); chain = [r for r, _ in g.run_chain(C)]
dep = {}
for r in chain:
    nb = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (r,))}
    for h, t, s, v, cls, det in C.execute("SELECT hash, too, asset, amount, cls, detail FROM ledger_edge WHERE run_id=? AND cls LIKE 'out:%' AND cls!='out:attacker'", (r,)):
        if t not in nb and (h not in dep or v * g.PX[s] > dep[h][2] * g.PX[dep[h][1]]): dep[h] = (g.category(cls, t, det), s, v)
U = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))     # route -> class -> asset -> amount sent
V = defaultdict(lambda: [0.0, 0.0, 0.0, 0])                         # route -> [usd in, usd out, stated fees usd, n]
RF = defaultdict(lambda: [0.0, 0.0])
VS = defaultdict(lambda: [0.0, 0.0])                                 # Symbiosis: same swaps at Symbiosis's own stamped prices (for comparison)                                 # route -> [sent into refunded deposits, refunded back] (USDT/TRX native, same asset)
rel, sym, cf, load_u = load('relay_requests.json'), load('bridge_sym.json'), load('bridge_cf.json'), load('bridge_usdt0.json')
# hourly ETH reference price from Symbiosis payouts (for Chainflip)
eth_h = defaultdict(list)
for q in sym.values():
    t = (q or {}).get('tx') or {}; ta = t.get('tokenAmount') or {}
    if ta.get('symbol') == 'ETH' and ta.get('priceUsd'): eth_h[(t.get('time') or '')[:13]].append(float(ta['priceUsd']))
eth_all = statistics.median([p for v in eth_h.values() for p in v]) if eth_h else 2300.0
PXH = load('px_hourly_binance.json')                                   # independent hourly mid prices (Binance spot)
import calendar
def hp(sym, ms):
    d = PXH.get(sym) or {}; k = str(int(ms // 3600000 * 3600000)); return d.get(k) or (d[min(d, key=lambda x: abs(int(x) - ms))] if d else None)
iso_ms = lambda iso: calendar.timegm(__import__('time').strptime(iso[:19], '%Y-%m-%dT%H:%M:%S')) * 1000
eth_at_ms = lambda ms: hp('ETHUSDT', ms) or eth_all
eth_at = lambda iso: statistics.median(eth_h[iso[:13]]) if eth_h.get(iso[:13]) else eth_all
for h, (route, s, v) in dep.items():
    if route == 'Relay':
        q = rel.get(h)
        if not q: U[route]['unresolved'][s] += v; continue
        st = q.get('status')
        if st == 'success':
            U[route]['completed'][s] += v; m = q['data'].get('metadata', {}); f = q['data'].get('feesUsd') or {}
            x = V[route]; x[0] += float(m.get('currencyIn', {}).get('amountUsd') or 0); x[1] += float(m.get('currencyOut', {}).get('amountUsd') or 0); x[2] += sum(float(f.get(k) or 0) for k in ('gas', 'fixed', 'price', 'gateway')); x[3] += 1
        elif st == 'refund': U[route]['refunded'][s] += v
        else: U[route][f'failed ({st})'][s] += v
    elif route == 'Symbiosis':
        q = sym.get(h)
        if not q: U[route]['unresolved'][s] += v; continue
        if (q.get('status') or {}).get('text') == 'Success':
            U[route]['completed'][s] += v; i, o = q['txIn']['tokenAmount'], q['tx']['tokenAmount']
            ia, oa = int(i['amount']) / 10 ** int(i['decimals']), int(o['amount']) / 10 ** int(o['decimals'])
            ip = hp('TRXUSDT', iso_ms(q['txIn']['time'])) if i.get('symbol') == 'TRX' else 1.0
            op = eth_at_ms(iso_ms(q['tx']['time'])) if o.get('symbol') == 'ETH' else 1.0
            x = V[route]; x[0] += ia * ip; x[1] += oa * op; x[3] += 1
            W = VS[route]; W[0] += ia * float(i.get('priceUsd') or 0); W[1] += oa * float(o.get('priceUsd') or 0)
        else: U[route][f"failed ({(q.get('status') or {}).get('text')})"][s] += v
    elif route == 'Chainflip':
        q = cf.get(h)
        if not q or q.get('_notfound'): U[route]['unresolved'][s] += v; continue
        sw = q.get('swap') or {}; out = int((q.get('swapEgress') or {}).get('amount') or 0); ref = int((q.get('refundEgress') or {}).get('amount') or 0) / 1e6
        swapped = int(sw.get('swappedInputAmount') or 0) / 1e6
        if out:
            U[route]['completed'][s] += swapped; a = q.get('destAsset')
            px = eth_at_ms((q.get('swapEgress') or {}).get('witnessedAt') or (q.get('deposit') or {}).get('witnessedAt', 0)) if a == 'ETH' else 1.0
            fees = sum(int(f['amount']) / (1e18 if f['asset'] == 'ETH' else 1e6) * (px if f['asset'] == 'ETH' else 1.0) for f in q.get('fees') or [] if f.get('type') != 'INGRESS')
            x = V[route]; x[0] += swapped; x[1] += out / (1e18 if a == 'ETH' else 1e6) * px; x[2] += fees; x[3] += 1
            if ref: U[route]['refunded'][s] += v - swapped; RF[route][0] += v - swapped; RF[route][1] += ref
            elif v - swapped > 0.01: U[route]['ingress fee / dust'][s] += v - swapped
        elif ref: U[route]['refunded'][s] += v; RF[route][0] += v; RF[route][1] += ref
        else: U[route][f"failed ({q.get('state')})"][s] += v
    elif route == 'USDT0 bridge':
        q = load_u.get(h)
        if not q: U[route]['unresolved'][s] += v; continue
        st, ch, to, a = g.lz_parse(q); U[route]['completed' if st == 'DELIVERED' else 'held in bridge (likely frozen)'][s] += v
        if st == 'DELIVERED': x = V[route]; x[0] += v; x[1] += a; x[3] += 1
    elif route == 'THORChain': U[route]['see per-window reports'][s] += v
print('1) UNITS — every unit sent is classified; the classes must add up to SENT (native)\n')
for route in ('THORChain', 'Relay', 'Chainflip', 'Symbiosis', 'USDT0 bridge'):
    sent = defaultdict(float)
    for h, (r, s, v) in dep.items():
        if r == route: sent[s] += v
    tot = defaultdict(float)
    print(f'== {route}: SENT ' + ' + '.join(f'{v:,.2f} {k}' for k, v in sent.items()))
    for cl, d in U[route].items():
        for k, v in d.items(): tot[k] += v
        print(f'     {cl:<26} ' + ' + '.join(f'{v:,.2f} {k}' for k, v in d.items()))
    print('     CHECK sent − classified: ' + ', '.join(f'{sent[k] - tot[k]:+,.6f} {k}' for k in sent))
print('\n2) VALUE — completed swaps, swap-time USD from each bridge record\n')
print(f'{"route":<11}{"swaps":>7}{"USD in":>16}{"USD out":>16}{"gap":>14}{"gap %":>8}{"stated fees":>14}{"unexplained":>14}')
for route, (i, o, f, n) in V.items():
    print(f'{route:<11}{n:>7}{i:>16,.2f}{o:>16,.2f}{i-o:>14,.2f}{(i-o)/i*100 if i else 0:>7.2f}%{f:>14,.2f}{i-o-f:>14,.2f}' + ('   (no fee split: gap = fees + slippage)' if route == 'Symbiosis' else ''))
for route, (i, o) in VS.items(): print(f'   ({route} at its OWN stamped prices: in {i:,.2f} out {o:,.2f} gap {(i-o)/i*100 if i else 0:.2f}% — stamped TRX price is stale)')
for route, (s_, r_) in RF.items(): print(f'\n{route} refunds: sent into refunded deposits {s_:,.2f} USDT, refunded back {r_:,.2f} USDT → refund cost {s_-r_:,.2f} ({(s_-r_)/s_*100 if s_ else 0:.3f}%)')
print('\n(Symbiosis and Chainflip valued at independent hourly mid prices, Binance spot TRXUSDT/ETHUSDT; Relay at its own amountUsd)')
