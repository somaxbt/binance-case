"""Binance case, TRON: exit accounting. For every route out of the Tron tree: what LEFT (native, Tron side) vs what was RECEIVED
on the other side (native, per destination chain/asset), what was REFUNDED back to Tron, and what is NOT RESOLVED yet.
  python3 exit_accounting.py        -> prints the statement, writes raw/tron/exit_accounting.json + raw/tron/carry_over_seeds.csv
Sources: ledger edges of the run chain (sent), raw/tron/report_<run>.txt (THORChain), raw/tron/relay_requests.json (Relay),
raw/tron/bridge_sym.json (Symbiosis), raw/tron/bridge_cf.json (Chainflip). Native units throughout; USD (theft-time px) only for the rate check."""
import csv, json, os, re, sqlite3, sys
from collections import defaultdict
sys.argv = sys.argv[:1]
import tron_graph as g
HERE = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(HERE, 'raw', 'tron')
PX = dict(g.PX, USDC=1.0, DAI=1.0, USDT=1.0)
C = sqlite3.connect(f'file:{g.DB}?mode=ro', uri=True)
chain = [r for r, _ in g.run_chain(C)]
load = lambda n: json.load(open(os.path.join(RAW, n))) if os.path.exists(os.path.join(RAW, n)) else {}

# ---- SENT: every exit edge of the run chain, by route ----
sent = defaultdict(lambda: defaultdict(float)); n_sent = defaultdict(int); dep = {}
for r in chain:
    nb = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (r,))}
    for h, t, s, v, cls, det in C.execute("SELECT hash, too, asset, amount, cls, detail FROM ledger_edge WHERE run_id=? AND cls LIKE 'out:%' AND cls!='out:attacker'", (r,)):
        if t in nb: continue
        route = g.category(cls, t, det); sent[route][s] += v; n_sent[route] += 1
        if h not in dep or v * PX.get(s, 0) > dep[h][2] * PX.get(dep[h][1], 0): dep[h] = (route, s, v)   # tx with a fee edge: keep the value edge

# ---- RECEIVED / REFUNDED per route ----
recv = defaultdict(lambda: defaultdict(lambda: [0.0, set(), 0.0]))   # route -> (chain, asset) -> [amount, recipients, USD in]
refd = defaultdict(lambda: defaultdict(float)); fees = defaultdict(lambda: defaultdict(float)); other = defaultdict(lambda: defaultdict(float))
matched = defaultdict(lambda: defaultdict(float)); seeds = []; held_b = defaultdict(lambda: defaultdict(float))
def got(route, h, ch, asset, amt, to, status):
    _, s, v = dep[h]; matched[route][s] += v
    R = recv[route][(ch, asset)]; R[0] += amt; R[2] += v * PX.get(s, 0)
    if to: R[1].add(to); seeds.append([route, ch, to, asset, amt, h, status])
cn = lambda c: g.CHAIN_NAME.get(int(c), f'chain {c}') if str(c).lstrip('-').isdigit() else (c or '?')
for h, q in load('relay_requests.json').items():
    if h not in dep or not q: continue
    _, s, v = dep[h]; st = q.get('status'); d = q.get('data') or {}
    if st == 'success':
        m = (d.get('metadata') or {}).get('currencyOut') or {}; o = (d.get('outTxs') or [{}])[0]
        got('Relay', h, cn(o.get('chainId')), (m.get('currency') or {}).get('symbol', '?'), float(m.get('amountFormatted') or 0), q.get('recipient'), st)
    elif st == 'refund': matched['Relay'][s] += v; refd['Relay'][s] += v
    else: matched['Relay'][s] += v; other['Relay'][f'{st}'] += v * PX[s]
for h, q in load('bridge_sym.json').items():
    if h not in dep or not q: continue
    _, s, v = dep[h]; st = (q.get('status') or {}).get('text'); o = q.get('tx') or {}; ta = o.get('tokenAmount') or {}
    if st == 'Success' and ta: got('Symbiosis', h, cn(o.get('chainId')), ta.get('symbol', '?'), int(ta.get('amount') or 0) / 10 ** int(ta.get('decimals') or 0), o.get('address'), st)
    else: matched['Symbiosis'][s] += v; other['Symbiosis'][f'{st}'] += v * PX[s]
for h, q in load('bridge_usdt0.json').items():
    if h not in dep or not q: continue
    st, ch, to, a = g.lz_parse(q)
    if st == 'DELIVERED': got('USDT0 bridge', h, ch, 'USDT0', a, to, st)
    else: matched['USDT0 bridge'][dep[h][1]] += dep[h][2]; held_b['USDT0 bridge']['USDT0'] += a      # not delivered for days; receivers checked empty → held in bridge — not delivered (likely frozen)
ACROSS_EXEC = '0x9e64d18073cd8ec20e2680124d0551ba1629fa20'     # Across V5 executor on Ethereum: swaps + re-deposits into the SpokePool (multi-step route)
for h, q in load('bridge_across.json').items():
    if h not in dep or not q: continue
    if q.get('status') == 'filled' and q.get('recipient'):
        if q['recipient'].lower() == ACROSS_EXEC and q.get('final'):          # executor ran the route's actions (swap/unwrap) in the fill tx: book the real payees
            fin = q['final']; tot = sum(f['amount'] or 0 for f in fin) or 1
            for i, f in enumerate(fin):
                if i == 0: got('Across', h, 'Ethereum', f['asset'], f['amount'] or 0, f['to'], 'filled → payee')
                else: R = recv['Across'][('Ethereum', f['asset'])]; R[0] += f['amount'] or 0; R[1].add(f['to']); seeds.append(['Across', 'Ethereum', f['to'], f['asset'], f['amount'], h, 'filled → payee'])
        elif q['recipient'].lower() == ACROSS_EXEC:
            matched['Across'][dep[h][1]] += dep[h][2]; R = recv['Across'][('Ethereum → Across V5 executor (in transit, onward step pending)', q['out_token'])]; R[0] += q['out_amount']; R[2] += dep[h][2]
        else: got('Across', h, {1: 'Ethereum'}.get(q.get('dst_chain'), f"chain {q.get('dst_chain')}"), q['out_token'], q['out_amount'], q['recipient'], 'filled')
    elif q.get('refund_tx'): matched['Across'][dep[h][1]] += dep[h][2]; refd['Across'][dep[h][1]] += dep[h][2]
SR = load('swap_redirects.json'); BWSETTLE = 'TM8uyBjRKzFtQdMC7tQLvKeeWieaFvXDyc'   # Bitget Wallet swap→bridge settlement (service; forwards to TZG47zhb)
for h, outs in SR.items():
    for s_, r_, v_ in outs:
        if r_ == BWSETTLE: sent['Bitget Wallet swap → bridge (via TM8uyBjR)']['USDT'] += v_; n_sent['Bitget Wallet swap → bridge (via TM8uyBjR)'] += 1
DEC = {'ETH': 18, 'BTC': 8, 'SOL': 9, 'FLIP': 18, 'DOT': 10}
for h, q in load('bridge_cf.json').items():
    if h not in dep or not q or q.get('_notfound'): continue
    _, s, v = dep[h]; st = q.get('state'); a = q.get('destAsset') or '?'
    out_amt = int((q.get('swapEgress') or {}).get('amount') or 0) / 10 ** DEC.get(a, 6)
    ref_amt = int((q.get('refundEgress') or {}).get('amount') or 0) / 1e6          # refunds are paid in the source asset (USDT, 6 dp)
    if out_amt > 0:                                                                  # what was actually swapped out (partial swaps: rest refunded)
        sw = q.get('swap') or {}; frac = min(1.0, int(sw.get('swappedInputAmount') or 0) / max(1, int(sw.get('originalInputAmount') or 1)))
        got('Chainflip', h, q.get('destChain', '?'), a, out_amt, q.get('destAddress'), st)
        if ref_amt: refd['Chainflip'][s] += ref_amt
    elif ref_amt: matched['Chainflip'][s] += v; refd['Chainflip'][s] += ref_amt
    else: matched['Chainflip'][s] += v; other['Chainflip'][f'{st}'] += v * PX[s]
# THORChain: aggregates from the per-window reports (payouts, refunds into the tree, RUNE fees)
th_reports = 0
for r in chain:
    f = os.path.join(RAW, f'report_{r}.txt')
    if not os.path.exists(f): continue
    th_reports += 1; sec = None
    for line in open(f):
        if 'refunds back into the Tron tree' in line: sec = 'ref'; continue
        if 'THORChain fees' in line: sec = 'fee'; continue
        if 'CARRY-OVER' in line: sec = 'pay'; continue
        if line.startswith('3) MIXING') or (line[:2].strip().endswith(')') and sec): sec = None
        m = re.match(r'\s+(\S+)\s+(\S+)\s+(\S+)\s+([\d,\.]+)\s*$', line)
        m3 = re.match(r'\s+(T\S+)\s+TRON\.(\S+)\s+([\d,\.]+)\s*$', line)
        if sec == 'ref' and m3: refd['THORChain'][m3[2].split('-')[0]] += float(m3[3].replace(',', ''))
        elif sec == 'fee' and 'RUNE' in line: fees['THORChain']['RUNE'] += float(line.split()[-1].replace(',', ''))
        elif sec == 'pay' and m:
            a = m[3].split('-')[0].split('.')[-1]; amt = float(m[4].replace(',', ''))
            R = recv['THORChain'][(m[1], a)]; R[0] += amt; R[1].add(m[2]); seeds.append(['THORChain', m[1], m[2], a, amt, f'report_{r}', 'payout'])

# ---- STATEMENT ----
amt = lambda d: ' + '.join(f'{v:,.2f} {k}' for k, v in sorted(d.items(), key=lambda x: -x[1] * PX.get(x[0], 0)) if v > 0.005) or '—'
usd = lambda d: sum(v * PX.get(k, 0) for k, v in d.items())
routes = sorted(sent, key=lambda r: -usd(sent[r]))
import time
out = {'chain': chain, 'routes': {}, 'built': time.strftime('%F %H:%M UTC', time.gmtime())}
print(f'EXIT ACCOUNTING — Tron tree, {len(chain)} windows to {chain[-1]} | native units; USD = theft-time px (rate check only)\n')
for r in routes:
    if r in ('Swaps (churn)',): continue
    S = sent[r]; M = matched[r]; un = {k: S[k] - M.get(k, 0) for k in S}
    if r == 'USDT0 bridge' and un.get('TRX'): fees[r]['TRX (LayerZero messaging fee)'] += un.pop('TRX')
    print(f'== {r}: SENT {amt(S)}  ({n_sent[r]} transfers, ≈${usd(S)/1e6:,.2f}M)')
    for (ch, a), (v, rc, u) in sorted(recv[r].items(), key=lambda x: -x[1][0] * PX.get(x[0][1], 0)):
        rate = f' | implied ${u / v:,.2f}/{a}' if u and v else ''
        print(f'     RECEIVED {v:>18,.6f} {a:<6} on {ch:<24} {len(rc):>4} recipients{rate}')
    if refd[r]: print(f'     REFUNDED to Tron   {amt(refd[r])}')
    if held_b[r]: print(f'     HELD IN BRIDGE     {amt(held_b[r])}  — not delivered (likely frozen)')
    if fees[r]: print(f'     FEES               {amt(fees[r])}')
    for k, v in other[r].items(): print(f'     {k.upper():<18} ≈${v:,.0f} (sent)')
    if r == 'THORChain': print(f'     (aggregate from {th_reports}/{len(chain)} window reports; per-deposit matching is in each report)')
    elif r in ('Relay', 'Symbiosis', 'Chainflip', 'USDT0 bridge', 'Across'): print(f'     NOT RESOLVED YET   {amt({k: v for k, v in un.items() if v > 0.005})}')
    else: print('     (Tron-side destination; no cross-chain resolver for this route)')
    out['routes'][r] = {'sent': S, 'received': [[ch, a, v, len(rc)] for (ch, a), (v, rc, u) in recv[r].items()], 'refunded': refd[r], 'fees': fees[r], 'held_in_bridge': held_b[r],
                        'other': other[r], 'unresolved': {k: v for k, v in un.items() if v > 0.005} if r in ('Relay', 'Symbiosis', 'Chainflip', 'USDT0 bridge', 'Across') else None}
held = C.execute('SELECT asset, SUM(CASE WHEN frozen=0 THEN bal ELSE 0 END), SUM(CASE WHEN frozen=1 THEN bal ELSE 0 END) FROM ledger_node WHERE run_id=? GROUP BY asset', (chain[-1],)).fetchall()
print('\n== STILL ON TRON (last cutoff): ' + ' · '.join(f'{a} held {h:,.2f} / frozen {z:,.2f}' for a, h, z in held))
print(f'== churn (swaps, not exits): {amt(sent["Swaps (churn)"])}')
out['held'] = held
json.dump(out, open(os.path.join(RAW, 'exit_accounting.json'), 'w'), indent=1, default=list)
with open(os.path.join(RAW, 'carry_over_seeds.csv'), 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['via', 'dest_chain', 'address', 'asset', 'amount', 'source', 'status']); w.writerows(seeds)
g.build()
try:
    import incident_graph; incident_graph.build()
except Exception as e: print('incident page FAILED', e)
print(f'\nwrote raw/tron/exit_accounting.json and raw/tron/carry_over_seeds.csv ({len(seeds)} seed rows)')
