"""SOL tree DEX swaps -> what came OUT (token, amount, receiving OWNER — can be a 3rd address). Cache only (raw/sol/tx_<sig>.json), no API.
  python3 sol_swap_out.py   -> raw/sol/swap_outputs.json {per_swap: [...], by_recipient: {owner: {mint: amt}}} + summary
Conservation per swap: SOL in (ledger edge) vs token out; token deltas read from pre/postTokenBalances by owner (pool vaults excluded:
an owner whose balance of that mint goes DOWN in the tx is the pool/vault side)."""
import json, os, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
MINT = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
        'So11111111111111111111111111111111111111112': 'wSOL'}
L = json.load(open('raw/sol_ledger.json')); tree = set(L['wallets'])
per, by = [], collections.defaultdict(lambda: collections.defaultdict(float)); miss = 0
for sig, ts, frm, to, sol, cls in L['edges']:
    if cls != 'out: swap (DEX)': continue
    f = f'raw/sol/tx_{sig}.json'
    if not os.path.exists(f): miss += 1; continue
    t = json.load(open(f)); m = t['meta']
    d = collections.defaultdict(float)
    for side, sgn in (('preTokenBalances', -1), ('postTokenBalances', 1)):
        for b in m.get(side) or []:
            d[(b.get('owner'), b['mint'])] += sgn * int(b['uiTokenAmount']['amount']) / 10 ** b['uiTokenAmount']['decimals']
    outs = [(o, mi, v) for (o, mi), v in d.items() if v > 1e-6 and o and mi != 'So11111111111111111111111111111111111111112']
    for o, mi, v in outs: by[o][MINT.get(mi, mi[:6])] += v
    per.append({'sig': sig, 'ts': ts, 'from': frm, 'sol_in': sol, 'outs': [(o, MINT.get(mi, mi[:6]), round(v, 6), o in tree) for o, mi, v in outs]})
json.dump({'per_swap': per, 'by_recipient': by}, open('raw/sol/swap_outputs.json', 'w'), indent=1)
tok = collections.defaultdict(float)
for o, x in by.items():
    for s, v in x.items(): tok[s] += v
print(f"swaps decoded {len(per)} (missing cache {miss}) · SOL in {sum(p['sol_in'] for p in per):,.2f} · out: {dict((k, round(v, 2)) for k, v in sorted(tok.items(), key=lambda x: -x[1]))}")
print(f"swaps with no token out (SOL→SOL / unread): {sum(1 for p in per if not p['outs'])}")
print('recipients (owner · in tree?):')
for o, x in sorted(by.items(), key=lambda kv: -sum(kv[1].values()))[:25]:
    print(f"  {o}  tree={o in tree}  " + ', '.join(f'{v:,.2f} {s}' for s, v in x.items()))
assert per, 'no swap edges decoded'
