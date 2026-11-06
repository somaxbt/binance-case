"""Bridged-in BTC seed list (BTC that reached Bitcoin from the Tron / SOL / ETH legs). Local files only, no API.
  python3 btc_seeds.py   -> raw/btc_bridged_seeds.json  {address: {origin, via, expected_btc, payout_txids, src}}
Origin tag = the chain the stolen funds came from (stolen is counted there, not here)."""
import csv, json, re
from collections import defaultdict
S = defaultdict(lambda: {'origin': set(), 'via': set(), 'expected_btc': 0.0, 'payout_txids': set(), 'src': []})
def add(a, origin, via, amt, src, txids=()):
    s = S[a]; s['origin'].add(origin); s['via'].add(via); s['expected_btc'] += amt; s['src'].append(src); s['payout_txids'] |= {t for t in txids if t}
# Tron -> BTC (exit_accounting carry-over seeds). 11-05: every seed gets its EXACT payout txids (btc_ledger2 roots = those outputs only):
# THORChain rows are per-address aggregates from the window reports -> payouts from the Tron THORNode cache (raw/tron/thornode_cache.json,
# every BTC out to the address; sums matched the reports 46/46 on 11-05) · Relay -> outTxs on Bitcoin in raw/tron/relay_requests.json ·
# Chainflip -> egress txRef from the shared ~/cases/_bridges cache (local read, no network).
import os, sys
sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
THOR_OUT = defaultdict(set); TRON_TC = json.load(open('raw/tron/thornode_cache.json'))
for v in TRON_TC.values():
    for x in (v or {}).get('outs') or []:
        if x.get('chain') == 'BTC' and x.get('to'): THOR_OUT[x['to']].add(x['id'].lower())
RELAY = json.load(open('raw/tron/relay_requests.json')); CF = BR.load('chainflip')
def tron_txids(r):
    if r['via'] == 'THORChain': return THOR_OUT.get(r['address'].strip(), set())
    if r['via'] == 'Relay': return {o.get('hash') for o in ((RELAY.get(r['source']) or {}).get('data') or {}).get('outTxs') or [] if o.get('chainId') == 8253038}
    if r['via'] == 'Chainflip': return {(BR.row('chainflip', r['source'], CF) or {}).get('out_tx')}
    return set()
for r in csv.DictReader(open('raw/tron/carry_over_seeds.csv')):
    if r['dest_chain'].split(' ')[0] in ('BTC', 'Bitcoin') and r['asset'] == 'BTC':
        add(r['address'].strip(), 'TRON', r['via'], float(r['amount']), r['source'], tron_txids(r))
# 11-05: Tron THORChain deposits the Tron cache holds as NOT done (cached while pending: 114, their payouts were in no report) → payouts
# from the shared resolver cache (THORNode tx/status, refreshed 11-05). Additive: the reports only counted done payouts (46/46 match above).
SH = BR.load('thorchain'); SHL = {k.lower(): v for k, v in SH.items()}
btc_amt = lambda x: sum(int(c.get('amount') or 0) for c in x.get('coins') or []) / 1e8
for k, v in TRON_TC.items():
    if (v or {}).get('done'): continue
    for x in (SHL.get(k.lower()) or {}).get('out_txs') or []:
        # a 'not done' entry can already list its payout (pending flag, out present) → the report counted it; add only NEW payout txids
        if x.get('chain') == 'BTC' and x.get('to_address') and x['id'].lower() not in THOR_OUT.get(x['to_address'], ()):
            add(x['to_address'], 'TRON', 'THORChain', btc_amt(x), k, [x['id'].lower()])
# 11-05: THORChain deposits found FROM THE BTC END (raw/btc2/extra_thor_deposits.json; only senders proven in a tree — AVAX/ETH deposits by
# ETH-tree keys). Senders NOT in a tree stay leads.
if os.path.exists('raw/btc2/extra_thor_deposits.json'):
    for h, o in json.load(open('raw/btc2/extra_thor_deposits.json')).items():
        for x in (SHL.get(h.lower()) or {}).get('out_txs') or []:
            if x.get('chain') == 'BTC' and x.get('to_address'): add(x['to_address'], o['origin'], f"THORChain ({o['chain']}, found from BTC end)", btc_amt(x), h, [x['id'].lower()])
# 11-05: Tron USDD/jUSDD branch (outside the TRX+USDT ledger; NOTES 11-02) -> 29 Chainflip swaps to 19ZQnV/19G8Gy (raw/cf_dest_19ZQnVpr.json,
# COMPLETED, egress = BTC payout). 27 Tron depositors (USDD-PSM funded) + 2 Ethereum depositors NOT in the ETH tree -> tagged apart.
for r in json.load(open('raw/cf_dest_19ZQnVpr.json'))['swaps']:
    if r['state'] == 'COMPLETED':
        add(r['dest'], 'TRON' if r['src'] == 'Tron' else 'ETH', 'Chainflip (USDD branch)' if r['src'] == 'Tron' else 'Chainflip (ETH sender not in tree)', r['btc'], r['dep_tx'], [r['egress']])
# SOL -> BTC: 11-04 — every bridge (Relay / Chainflip / Layerswap) of the SOL ledger via the shared resolver (raw/sol/bridge_dest.json from
# sol_bridge_resolve.py on the END ledger); fallback = the old pushed ledger's Relay rows. Successful BTC payouts only.
import os
OK = {'success', 'completed', 'complete', 'done'}
if os.path.exists('raw/sol/bridge_dest.json'):
    for r in json.load(open('raw/sol/bridge_dest.json')):
        if r.get('chain') in ('Bitcoin', 'BTC') and str(r.get('status', '')).lower() in OK and r.get('address') and float(r.get('amount') or 0) > 0:
            add(r['address'], 'SOL', r['kind'].capitalize(), float(r['amount']), r['sig'], [r.get('out_tx')])
else:
    for r in json.load(open('raw/sol_ledger.json'))['relay']:
        if r['status'] == 'success' and r['currency'] == 'BTC':
            add(r['recipient'], 'SOL', 'Relay', r['amount_out'], 'relay', r['out_txs'])
# ETH -> BTC via THORChain (11-04; eth_thor_resolve.py → shared resolver, THORNode tx/status; refunds excluded)
if os.path.exists('raw/eth_thor_dest.json'):
    for h, r in json.load(open('raw/eth_thor_dest.json'))['rows'].items():
        if str(r.get('status', '')).startswith('done') and r.get('chain') == 'BTC' and r.get('address'):
            add(r['address'], 'ETH', 'THORChain', float(r['amount']), h, [(r.get('out_tx') or '').lower()])
# ETH -> BTC (xchain_resolve rows; COMPLETED/success only; BTC amounts from the bridge records, see NOTES 11-02)
ETH_BTC = {'bc1qdrj6cs5gdq7dmuem56ptlqznmcs26rgtcj2qcv': 1.10481616, '1Hs7DhKgKt8nwLHRwd7Rg8JXy7myQXybu9': 0.66712052,
           'bc1qpgsju2n99ta5l5xp0rly3mka57uv66cxt64cuv': 0.0868036}
for svc, tx, frm, eth, status, dest in json.load(open('raw/eth_xchain_rows.json')):
    m = re.search(r'\b(bc1[0-9a-z]{25,62}|[13][1-9A-HJ-NP-Za-km-z]{25,34})\b', dest or '')
    if m and m.group(1) in ETH_BTC and ('COMPLETED' in status or status.startswith('success')):
        S[m.group(1)]['src'].append(tx)
for a, v in ETH_BTC.items(): S[a]['origin'].add('ETH'); S[a]['via'].add('Chainflip' if not a.endswith('cuv') else 'Relay'); S[a]['expected_btc'] += v
# ETH -> BTC via Symbiosis (OnchainGateway 0xe7e68d33; raw/eth_bridge_sym.json from the Symbiosis API, 11-03). tx = the BTC payout.
for h, r in json.load(open('raw/eth_bridge_sym.json')).items():
    t = r.get('tx') or {}
    if (r.get('status') or {}).get('text') == 'Success' and t.get('chainId') == 3652501241 and t.get('address'):
        add(t['address'], 'ETH', 'Symbiosis', int(t['tokenAmount']['amount']) / 1e8, h, [t.get('hash')])
# 11-05: ETH -> BTC via THORChain VAULT EOAs / Chainflip deposit CHANNELS / Relay (eth_vault_resolve.py on the CURRENT ETH run). Skip a deposit
# whose hash or payout txid is already seeded (BTC-end extra deposits, hard-coded ETH_BTC rows) -> no double expected_btc.
if os.path.exists('raw/eth_vault_dest.json'):
    seen_src = {str(x).lower().removeprefix('0x') for v in S.values() for x in v['src']}; seen_out = {t for v in S.values() for t in v['payout_txids']}
    for h, r in json.load(open('raw/eth_vault_dest.json'))['rows'].items():
        ok = r.get('kind') and r.get('chain') in ('BTC', 'Bitcoin') and r.get('address') and r.get('out_tx') and \
             (str(r.get('status')).startswith('done') or r.get('status') in ('COMPLETED', 'success'))
        if not ok or h.lower().removeprefix('0x') in seen_src or r['out_tx'].lower() in seen_out: continue
        add(r['address'], 'ETH', {'thorchain': 'THORChain (vault)', 'chainflip': 'Chainflip (channel)', 'relay': 'Relay'}[r['kind']], float(r['amount']), h, [r['out_tx'].lower()])
out = {a: {**v, 'origin': sorted(v['origin']), 'via': sorted(v['via']), 'payout_txids': sorted(v['payout_txids']), 'expected_btc': round(v['expected_btc'], 8)} for a, v in S.items()}
json.dump(out, open('raw/btc_bridged_seeds.json', 'w'), indent=1)
tot = defaultdict(lambda: [0, 0.0])
for v in out.values():
    k = '+'.join(v['origin']) + ' via ' + '+'.join(v['via']); tot[k][0] += 1; tot[k][1] += v['expected_btc']
for k, (n, b) in sorted(tot.items()): print(f'{k:28} {n:3} addrs {b:14.8f} BTC')
print(f'TOTAL {len(out)} addrs {sum(v["expected_btc"] for v in out.values()):.8f} BTC · with payout txid: {sum(1 for v in out.values() if v["payout_txids"])}')
assert all(v['expected_btc'] > 0 for v in out.values()), 'seed with no amount'
