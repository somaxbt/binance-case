"""Who got the output of the tree's swaps that paid OUTSIDE the tree ('Swaps (output to be traced)' on the Eagle Eye SOL tab).
Same GOT rule as incident_graph.sol_tree: a swap is churn only if a tree wallet received its output in the same tx.
Per swap tx (cache raw/sol/tx_<sig>.json): every owner's net gain per mint + SOL lamports; drop the tree, the sender and
non-wallets (PDA/program/token accounts; owner probe cached in raw/sol/probe_cache.json) -> the real recipient(s).
  python3 sol_swap_trace.py  -> raw/sol/swap_outside.json + summary"""
import json, os, sys, time, collections, sqlite3, urllib.request
os.chdir(os.path.dirname(os.path.abspath(__file__)))
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
U = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"
SYS = '11111111111111111111111111111111'
MINTS = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
         'So11111111111111111111111111111111111111112': 'wSOL', '2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU': 'jlWSOL'}
L = json.load(open('raw/sol_ledger.json')); T = set(L['wallets'])
PXS = 99.03                                                                     # SOL theft-time px (Eagle Eye) — display only
GOT = {e[0] for e in L['edges'] if e[5] in ('swap (DEX)', 'swap output (tree tx)', 'redeem Jupiter Lend')} | \
      {e[0] for e in L['edges_tok'] if e[6] in ('in: swap (DEX)', 'in: swap output (tree tx)', 'swap output to tree wallet', 'in: lend receipt')}
gave = collections.defaultdict(lambda: collections.defaultdict(float)); sender = {}
for sig, t, f, to, v, cls in L['edges']:
    if cls == 'out: swap (DEX)' and sig not in GOT: gave[sig]['SOL'] += v; sender[sig] = (f, t)
for sig, t, f, to, v, a, cls in L['edges_tok']:
    if a in ('USDC', 'USDT') and (cls.startswith('out: external') or (cls == 'out: swap (DEX)' and sig not in GOT)): gave[sig][a] += v; sender[sig] = (f, t)
PC = 'raw/sol/probe_cache.json'; PROBE = json.load(open(PC)) if os.path.exists(PC) else {}
def rpc(m, p):
    for i in range(6):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=40))
            if 'error' in r: raise RuntimeError(str(r['error'])[:80])
            time.sleep(0.15); return r['result']
        except Exception as e: err = e; time.sleep(3 * (i + 1))
    raise err
def owner(a):                                                # cached [first_seen, owner] like sol_ledger; no account = system wallet
    if a in PROBE and PROBE[a][1]: return PROBE[a][1]
    o = ((rpc('getAccountInfo', [a, {'encoding': 'base64'}]) or {}).get('value') or {}).get('owner', SYS)
    PROBE[a] = [PROBE.get(a, [None, None])[0], o]; return o
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f): return json.load(open(f))
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 1}]); json.dump(t, open(f, 'w')); return t
AT = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db'))
lab = lambda a: (AT.execute("SELECT entity||' ('||category||')' FROM attrib_v WHERE address=? LIMIT 1", (a,)).fetchone() or [''])[0]
rows, rec = [], collections.defaultdict(lambda: {'got': collections.defaultdict(float), 'n': 0, 'from': set(), 'sigs': []})
for sig in sorted(gave, key=lambda s: sender[s][1]):
    t = tx(sig); m = t['meta']; keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
    f = sender[sig][0]; d = collections.defaultdict(float)
    for j, k in enumerate(keys): d[(k, 'SOL')] += (m['postBalances'][j] - m['preBalances'][j]) / 1e9
    for sgn, bl in ((-1, m.get('preTokenBalances') or []), (1, m.get('postTokenBalances') or [])):
        for b in bl:
            if b.get('owner'): d[(b['owner'], MINTS.get(b['mint'], b['mint'][:8]))] += sgn * float(b['uiTokenAmount']['uiAmount'] or 0)
    gain = [(o, a, v) for (o, a), v in d.items() if v > (0.01 if a in ('SOL', 'wSOL') else 1) and o != f and o not in T]
    wallets = [(o, a, v) for o, a, v in gain if owner(o) == SYS]
    rows.append({'sig': sig, 't': sender[sig][1], 'from': f, 'gave': dict(gave[sig]), 'to': [[o, a, round(v, 6)] for o, a, v in wallets],
                 'non_wallet_gains': [[o, a, round(v, 6)] for o, a, v in gain if (o, a, v) not in wallets][:6], 'signer': keys[0]})
    for o, a, v in wallets:
        r = rec[o]; r['got'][a] += v; r['n'] += 1; r['from'].add(f); r['sigs'].append(sig)
json.dump(PROBE, open(PC, 'w')); json.dump({'swaps': rows, 'recipients': {k: {**v, 'from': sorted(v['from']), 'got': dict(v['got'])} for k, v in rec.items()}},
                                           open('raw/sol/swap_outside.json', 'w'), indent=1)
usd = lambda g: sum(v * (PXS if a in ('SOL', 'wSOL') else 1 if a in ('USDC', 'USDT') else 0) for a, v in g.items())
gv = collections.defaultdict(float)
for r in rows:
    for a, v in r['gave'].items(): gv[a] += v
print(f"{len(rows)} swaps paid outside the tree · gave {dict((a, round(v, 2)) for a, v in gv.items())} · ≈${usd(gv):,.0f}")
print(f"  {sum(1 for r in rows if not r['to'])} with NO wallet recipient (output stayed in pools/programs?)")
for o, r in sorted(rec.items(), key=lambda kv: -usd(kv[1]['got']))[:25]:
    print(f"  {o}  ≈${usd(r['got']):>12,.0f}  {', '.join(f'{v:,.2f} {a}' for a, v in r['got'].items())}  · {r['n']} tx from {len(r['from'])} tree wallets · {lab(o) or ''}")
