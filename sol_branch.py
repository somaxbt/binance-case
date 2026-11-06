"""Trace ONE Solana branch in SOL + USDC/USDT (by OWNER, so swap outputs paid to a 3rd address are followed) and measure automation.
Follow rule: receiver joins if it is a system-owned wallet whose first tx is >= FRESH (default 11-02 00:00 UTC); everything else is an
endpoint (pool/aggregator/CEX/old wallet; labelled from attrib.db + por-wallets.db). Helius RPC (never print URLs). Cache raw/sol/tx_<sig>.json.
  python3 sol_branch.py ROOT SINCE_UNIX [MAX_DEPTH=6]      -> raw/sol/branch_<root8>_<ts>.json + summary"""
import json, os, sys, time, sqlite3, statistics, urllib.request, collections
from concurrent.futures import ThreadPoolExecutor
os.chdir(os.path.dirname(os.path.abspath(__file__)))
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
U = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"
ROOT, SINCE = sys.argv[1], int(sys.argv[2]); DEPTH = int(sys.argv[3]) if len(sys.argv) > 3 else 6
FRESH = 1793577600                                                     # 2026-11-02 00:00 UTC
SYS = '11111111111111111111111111111111'
MINT = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
        '2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU': 'jlWSOL'}   # Jupiter Lend receipt: deposit -> move receipt -> redeem elsewhere (11-02)
MIN = {'SOL': 0.05, 'USDC': 5, 'USDT': 5, 'jlWSOL': 0.05}
AT = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db')); PO = sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
def label(a):
    r = AT.execute("SELECT entity||' ('||category||')' FROM attrib_v WHERE address=? LIMIT 1", (a,)).fetchone() or \
        PO.execute("SELECT exchange||' ('||wallet_type||')' FROM por_wallets WHERE address=? LIMIT 1", (a,)).fetchone()
    return r[0] if r else ''
import threading
_lk = threading.Lock(); _nx = [0.0]
def rpc(m, p):
    for i in range(8):
        with _lk:
            w = _nx[0] - time.time()
            if w > 0: time.sleep(w)
            _nx[0] = max(_nx[0], time.time()) + 0.11                  # ~9 req/s (Helius free tier 10/s)
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=40))
            if 'error' in r: raise RuntimeError(str(r['error'])[:80])
            return r['result']
        except Exception as e: err = e; time.sleep(min(30, 3 * (i + 1)))
    raise err
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f): return json.load(open(f))
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 1}])
    if t: json.dump(t, open(f, 'w'))
    return t
PROBE = {}
def probe(a):                     # (system_owned, first_tx_time, n_txs_page)
    if a in PROBE: return PROBE[a]
    ai = (rpc('getAccountInfo', [a, {'encoding': 'base64'}]) or {}).get('value')
    s = rpc('getSignaturesForAddress', [a, {'limit': 1000}]) or []
    first = min((x['blockTime'] for x in s if x.get('blockTime')), default=0) if len(s) < 1000 else 0
    # no account = emptied/closed -> a system wallet (pools/programs don't vanish); was misread as 'program acct' (B6cv44Nf 13,508 SOL, 11-02)
    PROBE[a] = (ai is None or ai.get('owner') == SYS, first, len(s)); return PROBE[a]

def flows(a):
    """all txs of a since SINCE -> list of dicts: t, sig, err, signer, fee, dSOL(a), dTok(a), out[(to, asset, amt)], inn[(from, asset, amt)]"""
    S = [s for s in (rpc('getSignaturesForAddress', [a, {'limit': 1000}]) or []) if (s.get('blockTime') or 0) >= SINCE]
    with ThreadPoolExecutor(4) as ex: T = list(ex.map(lambda s: tx(s['signature']), S))
    R = []
    for s, t in sorted(zip(S, T), key=lambda z: z[0]['blockTime']):
        if not t: continue
        keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
        pre, post = t['meta']['preBalances'], t['meta']['postBalances']
        dsol = {keys[j]: (post[j] - pre[j]) / 1e9 for j in range(len(keys))}
        tok = collections.defaultdict(float)
        for b in t['meta'].get('postTokenBalances') or []:
            if b['mint'] in MINT and b.get('owner'): tok[(b['owner'], MINT[b['mint']])] += float(b['uiTokenAmount']['uiAmount'] or 0)
        for b in t['meta'].get('preTokenBalances') or []:
            if b['mint'] in MINT and b.get('owner'): tok[(b['owner'], MINT[b['mint']])] -= float(b['uiTokenAmount']['uiAmount'] or 0)
        r = {'t': s['blockTime'], 'sig': s['signature'], 'err': bool(t['meta'].get('err')), 'signer': keys[0], 'fee': t['meta']['fee'] / 1e9 if keys[0] == a else 0,
             'dSOL': dsol.get(a, 0) + (t['meta']['fee'] / 1e9 if keys[0] == a else 0), 'dTok': {k[1]: v for k, v in tok.items() if k[0] == a and abs(v) > 1e-6},
             'progs': sorted({ix.get('programId', '') for ix in t['transaction']['message']['instructions']}), 'out': [], 'inn': []}
        if not r['err']:
            lost = r['dSOL'] < -MIN['SOL'] or any(v < -MIN[k] for k, v in r['dTok'].items())
            gained = r['dSOL'] > MIN['SOL'] or any(v > MIN[k] for k, v in r['dTok'].items())
            if lost:                       # receivers: anyone (not a) gaining SOL or USDC/USDT in this tx
                r['out'] += [(k, 'SOL', v) for k, v in dsol.items() if k != a and v > MIN['SOL']]
                r['out'] += [(o, asset, v) for (o, asset), v in tok.items() if o != a and v > MIN[asset]]
            if gained:
                r['inn'] += [(k, 'SOL', -v) for k, v in dsol.items() if k != a and v < -MIN['SOL'] and not (k == keys[0] and -v < 0.01)]
                r['inn'] += [(o, asset, -v) for (o, asset), v in tok.items() if o != a and v < -MIN[asset]]
        R.append(r)
    return R

tree, depth, q, ends, F = [], {ROOT: 0}, [ROOT], {}, {}
while q:
    a = q.pop(0); F[a] = flows(a); tree.append(a)
    for r in F[a]:
        for to, asset, v in r['out']:
            if to in depth or to in ends: continue
            so, first, n = probe(to)
            if so and first and first >= FRESH and depth[a] < DEPTH: depth[to] = depth[a] + 1; q.append(to)
            else: ends[to] = {'label': label(to), 'system_owned': so, 'first': first, 'txs_page': n}
    print(f'  [{len(tree)} read, {len(q)} queued, {len(ends)} endpoints] {a[:8]} depth {depth[a]}: {len(F[a])} txs', flush=True)

def bal(a):
    sol = rpc('getBalance', [a])['value'] / 1e9; out = {'SOL': sol}
    for m, s in MINT.items():
        v = rpc('getTokenAccountsByOwner', [a, {'mint': m}, {'encoding': 'jsonParsed'}])['value']
        out[s] = sum(x['account']['data']['parsed']['info']['tokenAmount']['uiAmount'] or 0 for x in v)
    return out
with ThreadPoolExecutor(4) as ex: HELD = dict(zip(tree, ex.map(bal, tree)))

# automation profile per wallet that sent things
AUTO = {}
for a in tree:
    sends = [r for r in F[a] if r['signer'] == a and (r['out'] or r['err'])]
    if len(sends) < 3: continue
    ok = [r for r in sends if not r['err']]; ts = [r['t'] for r in sends]
    gaps = [b - x for x, b in zip(ts, ts[1:])]
    first_in = min((r['t'] for r in F[a] if r['inn']), default=None)
    amts = [v for r in ok for _, asset, v in r['out'] if asset in ('USDC', 'USDT')]
    AUTO[a] = {'sends': len(sends), 'failed': len(sends) - len(ok), 'span_s': ts[-1] - ts[0], 'per_min': round(len(sends) / max(1, (ts[-1] - ts[0]) / 60), 1),
               'median_gap_s': statistics.median(gaps) if gaps else None, 'first_send_after_funding_s': (ts[0] - first_in) if first_in else None,
               'whole_dollar_amounts': (sum(1 for v in amts if abs(v - round(v)) < 1e-6), len(amts)),
               'fee_payers': sorted({r['signer'] for r in F[a]} - {a})[:5]}
# totals
held = collections.defaultdict(float)
for a, h in HELD.items():
    for k, v in h.items(): held[k] += v
endv = collections.defaultdict(lambda: collections.defaultdict(float))
for a in tree:
    for r in F[a]:
        for to, asset, v in r['out']:
            if to in ends: endv[to][asset] += v
ts = time.strftime('%Y%m%dT%H%M%S', time.gmtime())
json.dump({'root': ROOT, 'since': SINCE, 'built': ts, 'tree': {a: {'depth': depth[a], 'held': HELD[a], 'flows': F[a]} for a in tree},
           'endpoints': {k: {**v, 'got': dict(endv[k])} for k, v in ends.items()}, 'automation': AUTO}, open(f'raw/sol/branch_{ROOT[:8]}_{ts}.json', 'w'))
print(f'\n=== BRANCH {ROOT} since {time.strftime("%m-%d %H:%M", time.gmtime(SINCE))} UTC: {len(tree)} attacker wallets, {len(ends)} endpoints')
print('  HELD now in branch:', {k: round(v, 2) for k, v in held.items()})
print('  biggest holders:'); [print(f'    {a}  ' + ', '.join(f'{v:,.2f} {k}' for k, v in h.items() if v > 0.01)) for a, h in sorted(HELD.items(), key=lambda kv: -(kv[1]['SOL'] * 99 + kv[1]['USDC'] + kv[1]['USDT']))[:8]]
print('  endpoints that received value:')
for k, v in sorted(endv.items(), key=lambda kv: -(kv[1].get('SOL', 0) * 99 + kv[1].get('USDC', 0) + kv[1].get('USDT', 0)))[:15]:
    e = ends[k]; print(f"    {k}  {', '.join(f'{x:,.2f} {s}' for s, x in v.items())}  | {e['label'] or ('old wallet' if e['system_owned'] else 'program/pool/token acct')} | txs {e['txs_page']}{'+' if e['txs_page'] >= 1000 else ''}")
print('  AUTOMATION (wallets with 3+ sends):')
for a, x in sorted(AUTO.items(), key=lambda kv: -kv[1]['sends'])[:12]:
    print(f"    {a[:10]} sends {x['sends']} (failed {x['failed']}) in {x['span_s']}s = {x['per_min']}/min, median gap {x['median_gap_s']}s, first send {x['first_send_after_funding_s']}s after funding, whole-$ {x['whole_dollar_amounts'][0]}/{x['whole_dollar_amounts'][1]}, other signers {x['fee_payers']}")
