"""Where did the attacker's SOL go? All txs of the SOL pot since SINCE (UTC epoch s), native + SPL outflows per destination, then each
destination's current balance + its own latest txs (one page). Alchemy Solana RPC. Cache raw/sol/tx_<sig>.json.
  python3 sol_out.py [ADDR] [SINCE]"""
import json, os, sys, time, urllib.request, collections
from concurrent.futures import ThreadPoolExecutor
A = sys.argv[1] if len(sys.argv) > 1 else 'AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU'
SINCE = int(sys.argv[2]) if len(sys.argv) > 2 else 1793491200          # 2026-11-01 00:00 UTC
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
U = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}" if E.get('HELIUS_API_KEY') else f"https://solana-mainnet.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"   # Helius = Solana RPC; never print
def rpc(m, p):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=60)).get('result')
        except Exception: time.sleep(2 * (i + 1))
def sigs(a, since, cap=5000):
    out, before = [], None
    while len(out) < cap:
        p = {'limit': 1000, **({'before': before} if before else {})}; r = rpc('getSignaturesForAddress', [a, p]) or []
        if not r: break
        out += [s for s in r if (s.get('blockTime') or 0) >= since]
        if (r[-1].get('blockTime') or 0) < since: break
        before = r[-1]['signature']
    return out
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f): return json.load(open(f))
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 0}])
    if t: json.dump(t, open(f, 'w'))
    return t
S = [s for s in sigs(A, SINCE) if not s.get('err')]
print(f'{len(S)} successful txs on {A[:8]} since {time.strftime("%m-%d %H:%M", time.gmtime(SINCE))} UTC', flush=True)
with ThreadPoolExecutor(6) as ex: T = list(ex.map(lambda s: tx(s['signature']), S))
out = collections.defaultdict(lambda: collections.defaultdict(float)); first = {}; last = {}; progs = collections.Counter(); delta = 0.0
for s, t in zip(S, T):
    if not t: continue
    keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
    i = keys.index(A) if A in keys else None
    if i is not None: delta += (t['meta']['postBalances'][i] - t['meta']['preBalances'][i]) / 1e9
    ixs = t['transaction']['message']['instructions'] + [x for g in (t['meta'].get('innerInstructions') or []) for x in g['instructions']]
    for ix in ixs:
        progs[ix.get('program') or ix.get('programId')] += 1; p = ix.get('parsed')
        if not isinstance(p, dict): continue
        info = p.get('info', {})
        if p.get('type') in ('transfer', 'transferWithSeed') and info.get('source') == A and 'lamports' in info:
            d = info['destination']; out[d]['SOL'] += info['lamports'] / 1e9
        elif p.get('type') in ('transfer', 'transferChecked') and (info.get('authority') == A or info.get('owner') == A):
            d = info.get('destination'); amt = float((info.get('tokenAmount') or {}).get('uiAmount') or info.get('amount') or 0)
            out[d][(info.get('mint') or 'SPL')[:6]] += amt
        else: continue
        first.setdefault(d, s['blockTime']); last[d] = max(last.get(d, 0), s['blockTime'])
tot = sum(v.get('SOL', 0) for v in out.values())
print(f'net SOL change of the pot over these txs: {delta:,.4f} | SOL sent out by transfer: {tot:,.4f} to {len(out)} destinations')
print('programs touched:', dict(progs.most_common(8)))
top = sorted(out, key=lambda d: -out[d].get('SOL', 0))
def prof(d):
    b = (rpc('getBalance', [d]) or {}).get('value', 0) / 1e9; ai = (rpc('getAccountInfo', [d, {'encoding': 'jsonParsed'}]) or {}).get('value') or {}
    nx = rpc('getSignaturesForAddress', [d, {'limit': 1000}]) or []
    return d, b, ai.get('owner'), ai.get('executable'), len(nx), (nx[-1].get('blockTime') if nx else None)
with ThreadPoolExecutor(6) as ex: P = {d: r for d, *r in ex.map(prof, top[:40])}
res = []
for d in top[:40]:
    b, owner, exe, nx, oldest = P[d]; v = out[d]
    age = time.strftime('%Y-%m-%d', time.gmtime(oldest)) if oldest else '?'
    res.append({'to': d, 'got': dict(v), 'first': first[d], 'last': last[d], 'holds_sol': b, 'owner': owner, 'n_txs_page': nx, 'oldest_on_page': age})
    print(f"{d}  got {', '.join(f'{x:,.2f} {k}' for k, x in v.items())}  ({time.strftime('%H:%M', time.gmtime(first[d]))}→{time.strftime('%H:%M', time.gmtime(last[d]))})  holds {b:,.2f} SOL | txs {nx}{'+' if nx == 1000 else ''} since {age} | owner {str(owner)[:12]}")
json.dump({'pot': A, 'since': SINCE, 'net_change': delta, 'out': res, 'run_at': time.time()}, open(f'raw/sol/sol_out_{time.strftime("%Y%m%dT%H%M")}.json', 'w'), indent=1)
