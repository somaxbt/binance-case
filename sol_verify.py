"""Exact balance-delta audit of Solana wallets: per tx, the wallet's SOL change (pre/postBalances) and token changes of token accounts it OWNS
(pre/postTokenBalances), plus the counterparties that moved the opposite way. Since SINCE (UTC s). Alchemy RPC; tx cache raw/sol/tx_<sig>.json.
  python3 sol_verify.py SINCE ADDR [ADDR...]"""
import json, os, sys, time, urllib.request, collections
from concurrent.futures import ThreadPoolExecutor
SINCE = int(sys.argv[1]); ADDRS = sys.argv[2:]
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
U = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}" if E.get('HELIUS_API_KEY') else f"https://solana-mainnet.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"   # Helius = Solana RPC; never print
def rpc(m, p):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=60)).get('result')
        except Exception: time.sleep(2 * (i + 1))
def sigs(a):
    out, before = [], None
    while True:
        r = rpc('getSignaturesForAddress', [a, {'limit': 1000, **({'before': before} if before else {})}]) or []
        out += [s for s in r if (s.get('blockTime') or 0) >= SINCE]
        if not r or (r[-1].get('blockTime') or 0) < SINCE or len(r) < 1000: return out
        before = r[-1]['signature']
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f): return json.load(open(f))
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 0}])
    if t: json.dump(t, open(f, 'w'))
    return t
for A in ADDRS:
    S = sigs(A)
    with ThreadPoolExecutor(6) as ex: T = list(ex.map(lambda s: tx(s['signature']), S))
    sol_in = collections.Counter(); sol_out = collections.Counter(); tok = collections.defaultdict(float); n_err = 0; net = 0.0; rows = []
    for s, t in sorted(zip(S, T), key=lambda x: x[0]['blockTime'] or 0):
        if not t: continue
        if t['meta'].get('err'): n_err += 1; continue
        keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
        pre, post = t['meta']['preBalances'], t['meta']['postBalances']
        if A not in keys: continue
        i = keys.index(A); d = (post[i] - pre[i]) / 1e9; net += d
        fee = t['meta']['fee'] / 1e9 if i == 0 else 0
        others = [(keys[j], (post[j] - pre[j]) / 1e9) for j in range(len(keys)) if j != i and abs(post[j] - pre[j]) > 1000]
        if d + fee > 0.001:                                  # received: the biggest loser in the tx is the source
            src = min(others, key=lambda x: x[1])[0] if others else '?'; sol_in[src] += d + fee
        elif d + fee < -0.001:
            for k, v in others:
                if v > 0: sol_out[k] += v
        tb = collections.defaultdict(float)
        for b in t['meta'].get('postTokenBalances') or []:
            if b.get('owner') == A: tb[b['mint']] += float(b['uiTokenAmount']['uiAmount'] or 0)
        for b in t['meta'].get('preTokenBalances') or []:
            if b.get('owner') == A: tb[b['mint']] -= float(b['uiTokenAmount']['uiAmount'] or 0)
        for m, v in tb.items():
            if abs(v) > 0: tok[m] += v
        if abs(d) >= 1: rows.append((s['blockTime'], round(d, 4), s['signature']))
    bal = (rpc('getBalance', [A]) or {}).get('value', 0) / 1e9
    print(f'\n=== {A}  ({len(S)} txs since {time.strftime("%m-%d %H:%M", time.gmtime(SINCE))} UTC, {n_err} failed) | balance now {bal:,.4f} SOL | net SOL change {net:,.4f}')
    print('  SOL IN  by source:', [(k, round(v, 4)) for k, v in sol_in.most_common(6)], f'(total {sum(sol_in.values()):,.4f})')
    print('  SOL OUT by receiver (top 6 of', len(sol_out), '):', [(k, round(v, 4)) for k, v in sol_out.most_common(6)], f'(total {sum(sol_out.values()):,.4f})')
    big = {m: round(v, 4) for m, v in tok.items() if abs(v) > 1e-6}
    print('  token changes (owned accounts):', big if big else 'none')
    print('  moves >= 1 SOL:', [(time.strftime('%m-%d %H:%M', time.gmtime(t)), d) for t, d, _ in rows[:12]], '...' if len(rows) > 12 else '')
