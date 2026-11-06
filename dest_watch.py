"""Destination watcher for funds that LEFT Tron through bridges (seeds: raw/tron/carry_over_seeds.csv).
Per destination address: what arrived from Tron (via which service), what it holds NOW, and whether it has moved funds on.
  python3 dest_watch.py            -> snapshot raw/watch/dest_snapshot_<ts>.json + baseline raw/watch/dest_watch.json (first run)
  python3 dest_watch.py --check    -> compare live balances with the baseline; print only what changed
Chains: Ethereum / Arbitrum / Base (Alchemy: native + USDT/USDC), Bitcoin (Blockstream esplora), Lighter (account API)."""
import csv, json, os, sys, time, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
AK = E['ALCHEMY_API_KEY']; OUT = 'raw/watch'; os.makedirs(OUT, exist_ok=True)
CHN = {'ETH': 'Ethereum', 'Ethereum': 'Ethereum', 'BTC': 'Bitcoin', 'Bitcoin': 'Bitcoin', 'BASE': 'Base', 'Base': 'Base', 'Arbitrum': 'Arbitrum', 'Lighter': 'Lighter', 'ZEC': 'Zcash'}
NET = {'Ethereum': 'eth', 'Arbitrum': 'arb', 'Base': 'base', 'BSC': 'bnb'}
TOK = {'Ethereum': {'USDT': ('0xdac17f958d2ee523a2206206994597c13d831ec7', 6), 'USDC': ('0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 6)},
       'Arbitrum': {'USDT': ('0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9', 6), 'USDC': ('0xaf88d065e77c8cc2239327c5edb3a432268e5831', 6)},
       'Base': {'USDC': ('0x833589fcd6edb6e08f4c7c32d4f71b54bda02913', 6)},
       'BSC': {'USDT': ('0x55d398326f99059ff775485246999027b3197955', 18), 'USDC': ('0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d', 18)}}
def post(u, body):
    for i in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, json.dumps(body).encode(), {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return []
def get(u):
    for i in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60))
        except Exception: time.sleep(3 * (i + 1))
    return {}
# ---- seeds: what arrived where ----
arr = defaultdict(lambda: {'via': set(), 'got': defaultdict(float)})
for r in [r for f in ('raw/tron/carry_over_seeds.csv', 'raw/eth_dest_seeds.csv') if os.path.exists(f) for r in csv.DictReader(open(f))]:   # eth_dest_seeds = ETH-side exits (hand-resolved, 11-03)
    ch = CHN.get(r['dest_chain'].split(' ')[0], r['dest_chain']); a = r['address'].strip()
    if not a or ch not in ('Ethereum', 'Arbitrum', 'Base', 'Bitcoin', 'Lighter'): continue
    asset = {'USDT0': 'USDT'}.get(r['asset'], r['asset'].replace(' (Perp)', ''))
    k = (ch, a.lower() if a.startswith('0x') else a); arr[k]['via'].add(r['via']); arr[k]['got'][asset] += float(r['amount'] or 0)
# Solana-origin destinations: Layerswap payouts (raw/sol/layerswap.json, from the SOL ledger's Layerswap exits)
if os.path.exists('raw/sol/layerswap.json'):
    for v in json.load(open('raw/sol/layerswap.json')).values():
        sw = v['data'][0]['swap']; o = next((t for t in sw['transactions'] if t.get('type') == 'output'), {})
        ch = sw['destination_network']['display_name'].replace(' One', ''); a = sw['destination_address'].lower()
        k = (ch, a); arr[k]['via'].add('Layerswap (from Solana)'); arr[k]['got'][sw['destination_token']['symbol']] += float(o.get('amount') or 0)
by = defaultdict(list)
for (ch, a) in arr: by[ch].append(a)
print('destination addresses:', {k: len(v) for k, v in by.items()}, flush=True)
# ---- live state ----
def evm(ch, addrs):
    u = f'https://{NET[ch]}-mainnet.g.alchemy.com/v2/{AK}'; res = {}
    for i in range(0, len(addrs), 40):
        part = addrs[i:i + 40]; calls = []
        for j, a in enumerate(part):
            calls += [{'jsonrpc': '2.0', 'id': j * 10, 'method': 'eth_getBalance', 'params': [a, 'latest']},
                      {'jsonrpc': '2.0', 'id': j * 10 + 1, 'method': 'eth_getTransactionCount', 'params': [a, 'latest']}]
            for t, (sym, (ca, dec)) in enumerate(TOK.get(ch, {}).items()):
                calls.append({'jsonrpc': '2.0', 'id': j * 10 + 2 + t, 'method': 'eth_call', 'params': [{'to': ca, 'data': '0x70a08231' + a[2:].rjust(64, '0')}, 'latest']})
        r = {x['id']: x.get('result') for x in post(u, calls) or []}
        for j, a in enumerate(part):
            h = {'ETH': int(r.get(j * 10) or '0x0', 16) / 1e18}; nonce = int(r.get(j * 10 + 1) or '0x0', 16)
            for t, (sym, (ca, dec)) in enumerate(TOK.get(ch, {}).items()): h[sym] = int((r.get(j * 10 + 2 + t) or '0x0') or '0x0', 16) / 10 ** dec
            res[a] = {'held': h, 'nonce': nonce}
    return res
def btc(a):
    d = get(f'https://blockstream.info/api/address/{a}'); cs = d.get('chain_stats', {}); ms = d.get('mempool_stats', {})
    bal = (cs.get('funded_txo_sum', 0) - cs.get('spent_txo_sum', 0) + ms.get('funded_txo_sum', 0) - ms.get('spent_txo_sum', 0)) / 1e8
    return a, {'held': {'BTC': bal}, 'nonce': cs.get('spent_txo_count', 0) + ms.get('spent_txo_count', 0)}
def lighter(a):
    d = get(f'https://mainnet.zklighter.elliot.ai/api/v1/account?by=index&value={a}'); x = (d.get('accounts') or [d])[0] if d else {}
    return a, {'held': {'USDC': float(x.get('collateral') or 0)}, 'nonce': int(x.get('total_order_count') or 0), 'l1_address': x.get('l1_address')}
live = {}
for ch in ('Ethereum', 'Arbitrum', 'Base', 'BSC'):
    if by.get(ch): live.update({(ch, a): v for a, v in evm(ch, by[ch]).items()})
with ThreadPoolExecutor(4) as ex:
    if by.get('Bitcoin') and not os.environ.get('MC_SKIP_BTC'): live.update({('Bitcoin', a): v for a, v in ex.map(btc, by['Bitcoin'])})
    if by.get('Lighter'): live.update({('Lighter', a): v for a, v in ex.map(lighter, by['Lighter'])})
PX = {'ETH': 2313.26, 'BTC': 80244.08, 'USDT': 1, 'USDC': 1}
snap = {f'{ch}|{a}': {'via': sorted(v['via']), 'got': dict(v['got']), **live.get((ch, a), {})} for (ch, a), v in arr.items()}
ts = time.strftime('%Y%m%dT%H%M%S'); json.dump(snap, open(f'{OUT}/dest_snapshot_{ts}.json', 'w'), indent=1)
if '--check' in sys.argv and os.path.exists(f'{OUT}/dest_watch.json'):
    base = json.load(open(f'{OUT}/dest_watch.json')); ch_ = []
    for k, v in snap.items():
        b = (base.get(k) or {}).get('held', {})
        for s, x in (v.get('held') or {}).items():
            if abs(x - b.get(s, 0)) > max(0.0001 if s in ('ETH', 'BTC') else 1, abs(b.get(s, 0)) * 1e-4): ch_.append((k, s, b.get(s, 0), x))
    print(f'CHANGED since baseline: {len(ch_)}'); [print('  ', k, s, f'{a:,.4f} -> {b:,.4f}') for k, s, a, b in sorted(ch_, key=lambda c: -abs(c[3] - c[2]) * PX.get(c[1], 1))[:40]]
else:
    json.dump(snap, open(f'{OUT}/dest_watch.json', 'w'), indent=1); print('baseline written: raw/watch/dest_watch.json')
# ---- summary: still held vs moved on, per chain ----
print(f'\nSNAPSHOT {ts} — funds that left Tron, per destination chain (value at theft-time prices)')
for ch in ('Ethereum', 'Bitcoin', 'Lighter', 'Arbitrum', 'Base', 'BSC'):
    ks = [k for k in snap if k.startswith(ch + '|')]
    if not ks: continue
    got = sum(sum(v * PX.get(s, 1) for s, v in snap[k]['got'].items()) for k in ks)
    held = sum(sum(v * PX.get(s, 1) for s, v in (snap[k].get('held') or {}).items()) for k in ks)
    moved = [k for k in ks if (snap[k].get('nonce') or 0) > 0 or sum(v * PX.get(s, 1) for s, v in (snap[k].get('held') or {}).items()) < 0.5 * sum(v * PX.get(s, 1) for s, v in snap[k]['got'].items())]
    print(f'  {ch:9} {len(ks):5} addresses | arrived ≈${got/1e6:,.2f}M | still held ≈${held/1e6:,.2f}M ({held/got*100 if got else 0:.0f}%) | moved on: {len(moved)} addresses')
top = sorted(snap.items(), key=lambda kv: -sum(v * PX.get(s, 1) for s, v in (kv[1].get('held') or {}).items()))[:10]
print('\nlargest current holders among destinations:')
for k, v in top: print(f"  {k}  holds {', '.join(f'{x:,.2f} {s}' for s, x in (v.get('held') or {}).items() if x > 0.01)}  (via {', '.join(v['via'])})")
