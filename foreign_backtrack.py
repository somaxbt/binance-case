"""Backtrack every 'foreign' SOL sender of a SOL ledger along its LARGEST SOL inflow (<= 8 hops, txs <= END) until it reaches
a tree wallet, a labelled exit (sol_ledger.EXITS) or a busy wallet (>=100 txs). Chains that start at a labelled MIXER become seeds:
the first wallet after the pool = 'withdrawal -> lands in tree' (de-mixed by destination). Output raw/sol/mixer_seeds.json
(+ every chain, for review). Heuristic per hop (largest inflow) -> the ledger's MIXED flag still catches wallets with other money.
  SOL_LEDGER=raw/sol_ledger_next.json SOL_END=2026-11-04T01:32:07Z python3 foreign_backtrack.py"""
import json, os, time, calendar, collections, subprocess, re, urllib.request
os.chdir(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get('SOL_LEDGER', 'raw/sol_ledger_next.json'); _e = os.environ['SOL_END']; END = calendar.timegm(time.strptime(_e, '%Y-%m-%dT%H:%M:%SZ'))
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
HEL = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"                                 # never print
import ast; EXITS = next(ast.literal_eval(n.value) for n in ast.parse(open('sol_ledger.py').read()).body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'EXITS')   # single source of labels
def rpc(m, p):
    for i in range(5):
        o = urllib.request.urlopen(urllib.request.Request(HEL, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=40).read().decode()   # 11-04: urllib, never curl — key is in the URL
        try: return json.loads(o)['result']
        except Exception: time.sleep(2 + 2 * i)
K = lambda t: [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f): return json.load(open(f))
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 1}])
    if t: json.dump(t, open(f, 'w'))
    return t
def biggest_in(a):                                           # -> (sender, SOL, sig) | None, n_sigs
    sg = rpc('getSignaturesForAddress', [a, {'limit': 100}]) or []
    if len(sg) >= 100: return None, len(sg)
    best = collections.defaultdict(lambda: [0.0, None])
    for s in sg:
        if s.get('err') or (s.get('blockTime') or 0) > END: continue
        t = tx(s['signature'])
        if not t or a not in K(t): continue
        k = K(t); i = k.index(a); d = (t['meta']['postBalances'][i] - t['meta']['preBalances'][i]) / 1e9
        if d > 1:
            oth = [(k[j], (t['meta']['postBalances'][j] - t['meta']['preBalances'][j]) / 1e9) for j in range(len(k)) if j != i]
            s0 = min(oth, key=lambda x: x[1])[0]; best[s0][0] += d; best[s0][1] = best[s0][1] or s['signature']
    if not best: return None, len(sg)
    s0, (v, sig) = max(best.items(), key=lambda x: x[1][0]); return (s0, v, sig), len(sg)
L = json.load(open(LEDGER)); T = set(L['wallets'])
snd = collections.defaultdict(float)
for sig, t, frm, to, v, cls in L['edges']:
    if cls == 'foreign': snd[frm] += v
OUT = 'raw/sol/mixer_seeds.json'
prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
chains, seeds, by = list(prev.get('chains', [])), dict(prev.get('seeds', {})), collections.defaultdict(float)   # 11-04: CUMULATIVE — once a seed's chain joins the tree it is no longer 'foreign', so it must not be dropped
for a, amt in sorted(snd.items(), key=lambda x: -x[1]):
    path, cur, end = [a], a, '8 hops, still fresh'
    if a in EXITS: end = 'EXIT ' + EXITS[a]
    else:
        for _ in range(8):
            r, n = biggest_in(cur)
            if r is None: end = f'busy/none at {cur}'; break
            prev, (cur, v, sig) = cur, r; path.append(cur)
            if cur in T: end = 'TREE ' + cur; break
            if cur in EXITS:
                end = 'EXIT ' + EXITS[cur]
                if 'mixer' in EXITS[cur]:
                    w = seeds.setdefault(prev, {'via': EXITS[cur], 'withdrawal_sol': 0.0, 'withdrawal_sig': sig, 'reaches_tree_via': [], 'foreign_sol_explained': 0.0})
                    w['withdrawal_sol'] = round(v, 6); w['reaches_tree_via'].append(a); w['foreign_sol_explained'] += round(amt, 6)
                break
    by[end.split(' at ')[0] if end.startswith('busy') else end] += amt
    chains.append({'sender': a, 'foreign_sol': round(amt, 6), 'path': path, 'end': end}); print(f'{amt:>10,.2f} {a[:10]} <- ' + ' <- '.join(p[:6] for p in path[1:]) + f' => {end}', flush=True)
json.dump({'ledger': LEDGER, 'end': _e, 'made': time.strftime('%FT%TZ', time.gmtime()), 'seeds': seeds, 'chains': chains,
           'by_origin': {k: round(v, 6) for k, v in by.items()}}, open(OUT, 'w'), indent=1)
print('\nBY ORIGIN:'); [print(f'  {v:>11,.2f} SOL  {k}') for k, v in sorted(by.items(), key=lambda x: -x[1])]
print(f'MIXER SEEDS: {len(seeds)} withdrawal wallets, explaining {sum(s["foreign_sol_explained"] for s in seeds.values()):,.2f} SOL of foreign -> raw/sol/mixer_seeds.json')
