"""Resolve the Tron tree's Symbiosis, Chainflip and USDT0 (LayerZero) deposits to their destination (chain, address, asset, amount, out tx).
  python3 bridge_resolve.py sym|cf|usdt0      cache raw/tron/bridge_<kind>.json (hash -> API reply); prints a destination summary
Symbiosis: api.symbiosis.finance/crosschain/v1/tx/728126428/{hash}. Chainflip: chainflip-swap.chainflip.io/v2/swaps/{hash} (rate-limits hard)."""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
from collections import defaultdict
K = sys.argv[1]; CACHE = f'raw/tron/bridge_{K}.json'
SYM = 'TPuaJ6gnYfE9gLUDFrbWbPx3tMnjG8max1'; TEC = 'TEcDijvKSXcfWT7S6rd44H5vNgufm7Y4XC'
C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
runs = "SELECT run_id FROM ledger_run WHERE leg='tron2' AND finished GLOB '2026*'"
where = {'sym': "too=?", 'cf': "(too=? OR detail LIKE 'bridge:chainflip%' OR detail='CreatedByContract')",
         'usdt0': "(too=? OR detail LIKE 'bridge:usdt0%' OR detail LIKE 'bridge:layerzero%' OR detail='UsdtOFT' OR too='TWPziSAroSacAjDuL52ByQzU86s9mP2gPr')"}[K]
edges = {h: (ts, f, t, s, v) for h, ts, f, t, s, v in C.execute(f"SELECT hash, ts, frm, too, asset, amount FROM ledger_edge WHERE cls LIKE 'out:%' AND {where} AND run_id IN ({runs})", ({'sym': SYM, 'cf': TEC, 'usdt0': 'TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt'}[K],))}
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
todo = [h for h in edges if h not in cache]; print(f'{K}: {len(edges)} deposits, {len(todo)} to fetch', flush=True)
url = {'sym': lambda h: f'https://api.symbiosis.finance/crosschain/v1/tx/728126428/{h}', 'cf': lambda h: f'https://chainflip-swap.chainflip.io/v2/swaps/{h}',
       'usdt0': lambda h: f'https://scan.layerzero-api.com/v1/messages/tx/0x{h}'}[K]
gap = {'sym': 0.4, 'cf': 1.5, 'usdt0': 0.6}[K]
for i, h in enumerate(todo):
    for k in range(8):
        try: cache[h] = json.load(urllib.request.urlopen(urllib.request.Request(url(h), headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)); break
        except urllib.error.HTTPError as e:
            if e.code == 404: cache[h] = {'_notfound': True}; break
            time.sleep(30 * (k + 1) if e.code == 429 else 5)
        except Exception: time.sleep(5 * (k + 1))
    time.sleep(gap)
    if i % 50 == 49: json.dump(cache, open(CACHE, 'w')); print(f'  {i+1}/{len(todo)}', flush=True)
json.dump(cache, open(CACHE, 'w'))
LZ = {30101: 'Ethereum', 30110: 'Arbitrum', 30111: 'Optimism', 30184: 'Base', 30109: 'Polygon', 30102: 'BNB Chain', 30106: 'Avalanche', 30168: 'Solana',
      30420: 'Tron', 30367: 'HyperEVM', 30332: 'Sonic', 30320: 'Unichain', 30362: 'Berachain', 30339: 'Ink', 30280: 'Sei', 30295: 'Flare', 30383: 'Plasma', 30183: 'Linea', 30181: 'Mantle'}
agg = defaultdict(lambda: [0, defaultdict(float), 0.0]); st = defaultdict(int)
for h, (ts, f, t, s, v) in edges.items():
    d = cache.get(h) or {}
    if K == 'usdt0':
        m = ((d.get('data') or [{}])[0]) if isinstance(d.get('data'), list) else {}; pl = ((m.get('source') or {}).get('tx') or {}).get('payload', '')[2:]
        state = m.get('status', {}).get('name') if isinstance(m.get('status'), dict) else (m.get('status') or 'notfound')
        to = '0x' + pl[4 + 24:4 + 64] if len(pl) >= 84 else '?'; amt = int(pl[68:84], 16) / 1e6 if len(pl) >= 84 else 0
        key = (LZ.get((m.get('pathway') or {}).get('dstEid'), (m.get('pathway') or {}).get('dstEid')), to, 'USDT0')
    elif K == 'sym':
        o = d.get('tx') or {}; ta = o.get('tokenAmount') or {}; state = (d.get('status') or {}).get('text', 'notfound')
        key = (o.get('chainId'), o.get('address'), ta.get('symbol')); amt = int(ta.get('amount') or 0) / 10 ** int(ta.get('decimals') or 0) if ta else 0
    else:
        state = d.get('state', 'notfound'); eg = d.get('swapEgress') or {}
        key = (d.get('destChain'), d.get('destAddress'), d.get('destAsset')); amt = float(eg.get('amount') or 0) / (1e18 if d.get('destAsset') in ('ETH', 'FLIP') else 1e8 if d.get('destAsset') == 'BTC' else 1e9 if d.get('destAsset') == 'SOL' else 1e6) if eg else 0
    st[state] += 1; a = agg[key]; a[0] += 1; a[1][s] += v; a[2] += amt
print(f'states: {dict(st)}')
print('dest chain | dest address | asset | n | in (Tron) | out amount')
for (ch, ad, sy), (n, i, o) in sorted(agg.items(), key=lambda x: -(x[1][1]['TRX'] * 0.3 + x[1][1]['USDT'])):
    print(ch, '|', ad, '|', sy, '|', n, '|', ', '.join(f'{v:,.0f} {k}' for k, v in i.items()), '|', f'{o:,.6f}')
