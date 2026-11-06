"""Attacker SOL into swap-service hot wallet 6H7GCfCx -> per deposit: the swap (SOL -> USDC/USDT, seconds later) and the stablecoin exit
(CCTP DepositForBurn, or a token transfer). CCTP burns resolved via Circle Iris (/v1/messages/5/<sig>): destination domain + mintRecipient.
Matching rule: the first SOL->stable swap after a tree deposit whose SOL-out equals the deposit, then the next stable-out of that amount (±0.2%).
Cache raw/sol/cctp.json.   python3 sol_cctp.py"""
import json, glob, os, time, urllib.request, urllib.error
os.chdir(os.path.dirname(os.path.abspath(__file__)))
A = '6H7GCfCx8JMUACbmSYZjConeJGzViPHhMvvYak5SDDBe'
TREE = set(json.load(open('raw/sol_ledger.json'))['wallets'])
MINT = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT'}
CCTP = 'CCTPiPYPc6AsJuwueEnWgSgucamXDZwBd53dQ11YiKX3'
DOM = {0: 'Ethereum', 1: 'Avalanche', 2: 'Optimism', 3: 'Arbitrum', 5: 'Solana', 6: 'Base', 7: 'Polygon', 10: 'Unichain', 11: 'Linea', 14: 'World Chain', 19: 'HyperEVM'}

T = []
for f in glob.glob('raw/sol/tx_*.json'):
    t = json.load(open(f))
    if not t or t['meta'].get('err'): continue
    keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
    if A not in keys: continue
    i = keys.index(A); pre, post = t['meta']['preBalances'], t['meta']['postBalances']
    tok = {}
    for b in t['meta'].get('postTokenBalances') or []:
        if b.get('owner') == A and b['mint'] in MINT: tok[MINT[b['mint']]] = tok.get(MINT[b['mint']], 0) + float(b['uiTokenAmount']['uiAmount'] or 0)
    for b in t['meta'].get('preTokenBalances') or []:
        if b.get('owner') == A and b['mint'] in MINT: tok[MINT[b['mint']]] = tok.get(MINT[b['mint']], 0) - float(b['uiTokenAmount']['uiAmount'] or 0)
    src = [keys[j] for j in range(len(keys)) if j != i and post[j] < pre[j]]
    progs = {ix.get('programId') for ix in t['transaction']['message']['instructions']}
    # token receiver (owner) for plain transfers out
    rcv = sorted({b.get('owner') for b in t['meta'].get('postTokenBalances') or [] if b.get('owner') not in (A, None) and b['mint'] in MINT})
    T.append({'t': t['blockTime'], 'sig': t['transaction']['signatures'][0], 'sol': (post[i] - pre[i]) / 1e9, 'tok': tok,
              'from_tree': any(s in TREE for s in src), 'cctp': CCTP in progs, 'rcv': rcv})
T.sort(key=lambda x: x['t'])

cache = json.load(open('raw/sol/cctp.json')) if os.path.exists('raw/sol/cctp.json') else {}
def iris(sig):
    if sig in cache: return cache[sig]
    for k in range(6):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(f'https://iris-api.circle.com/v1/messages/5/{sig}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)); break
        except urllib.error.HTTPError as e:
            if e.code == 404: r = {'messages': []}; break
            time.sleep(5 * (k + 1))
    m = (r.get('messages') or [{}])[0]; msg = bytes.fromhex((m.get('message') or '0x')[2:])
    out = {'attestation': m.get('attestation', '')[:12], 'status': 'complete' if m.get('attestation', 'PENDING') not in ('PENDING', '') else 'pending'}
    if len(msg) >= 116 + 132:
        b = msg[116:]
        out.update({'dest_domain': int.from_bytes(msg[8:12], 'big'), 'nonce': int.from_bytes(msg[12:20], 'big'),
                    'mint_recipient': b[36:68].hex(), 'amount': int.from_bytes(b[68:100], 'big') / 1e6})
    cache[sig] = out; json.dump(cache, open('raw/sol/cctp.json', 'w'), indent=1); time.sleep(1)
    return out

res, used = [], set()
for k, d in enumerate(T):
    if not (d['from_tree'] and d['sol'] > 0.5): continue
    sw = next((x for x in T[k + 1:k + 8] if x['t'] - d['t'] < 120 and abs(x['sol'] + d['sol']) < 0.01 and any(v > 0 for v in x['tok'].values())), None)
    if not sw: res.append((d, None, None)); continue
    cur, amt = next((c, v) for c, v in sw['tok'].items() if v > 0)
    ex = next((x for x in T if x['t'] >= sw['t'] and x['sig'] not in used and x['t'] - sw['t'] < 300 and x['tok'].get(cur, 0) < 0 and abs(-x['tok'][cur] - amt) <= amt * 0.002), None)
    if ex: used.add(ex['sig'])
    res.append((d, (cur, amt, sw['sig']), ex))

tot = {}; print('time      SOL in  -> swapped         -> exit')
for d, sw, ex in res:
    tm = time.strftime('%m-%d %H:%M:%S', time.gmtime(d['t']))
    if not sw: print(tm, f"{d['sol']:8.2f}  NO SWAP MATCHED"); continue
    cur, amt, _ = sw
    if not ex: print(tm, f"{d['sol']:8.2f} -> {amt:>10,.2f} {cur} -> NO EXIT MATCHED"); continue
    if ex['cctp']:
        c = iris(ex['sig']); dst = DOM.get(c.get('dest_domain'), c.get('dest_domain')); rc = c.get('mint_recipient', '')
        rcp = ('0x' + rc[-40:]) if dst != 'Solana' else rc
        key = f'CCTP -> {dst} {rcp}'; note = f"{c.get('amount', 0):,.2f} USDC minted? {c.get('status')}"
    else:
        key = f'{cur} transfer -> {",".join(r[:8] for r in ex["rcv"]) or "?"}'; note = ''
    tot.setdefault(key, [0.0, 0.0, 0]); tot[key][0] += d['sol']; tot[key][1] += -ex['tok'][cur]; tot[key][2] += 1
    print(tm, f"{d['sol']:8.2f} -> {amt:>10,.2f} {cur} -> {key} {note}  [{ex['sig'][:10]}]")
print('\nBY EXIT (SOL in, stable out, n):')
for k, (s, v, n) in sorted(tot.items(), key=lambda x: -x[1][0]): print(f'  {s:9.2f} SOL -> {v:>12,.2f}  ({n})  {k}')
print(f"  attacker SOL into {A[:8]}: {sum(d['sol'] for d, _, _ in res):,.2f} in {len(res)} deposits; matched to an exit: {sum(d['sol'] for d, s, e in res if e):,.2f}")
json.dump([{'t': d['t'], 'sol': d['sol'], 'dep': d['sig'], 'swap': s, 'exit': e and {'sig': e['sig'], 'cctp': e['cctp'], 'rcv': e['rcv'], 'iris': cache.get(e['sig'])}} for d, s, e in res],
          open('raw/sol/6H7GCfCx_exits.json', 'w'), indent=1)
