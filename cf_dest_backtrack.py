"""Chainflip swaps INTO given destination addresses -> Tron depositor -> one page of its USDT funders, each checked against the Tron ledger.
Use when a BTC address shows untracked inputs paid by Chainflip's taproot vault: proves whose money it was.
  python3 cf_dest_backtrack.py DEST [DEST ...]     cache raw/cf_dest_cache.json · out raw/cf_dest_<first8>.json"""
import collections, hashlib, json, os, sqlite3, sys, time, urllib.request
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
TH = {'TRON-PRO-API-KEY': E['TRONGRID_API_KEY']}
CF = 'raw/cf_dest_cache.json'; cache = json.load(open(CF)) if os.path.exists(CF) else {}
B = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58(h):
    raw = bytes.fromhex('41' + h[-40:]); raw += hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    n, s = int.from_bytes(raw, 'big'), ''
    while n: n, r = divmod(n, 58); s = B[r] + s
    return s
def get(u, h={}, data=None, wait=1.5):
    if data is None and u in cache: return cache[u]
    for i in range(8):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(u, data, {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json', **h}), timeout=60))
            time.sleep(wait)
            if data is None: cache[u] = r; json.dump(cache, open(CF, 'w'))
            return r
        except Exception: time.sleep(10 * (i + 1))
    raise RuntimeError('failed ' + u.split('?')[0][:60])
C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
EB = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True); ER = EB.execute("SELECT run_id FROM run WHERE finished IS NOT NULL AND (run_id LIKE 'eth-hs-full-%' OR run_id LIKE 'eth-hs-inc-%') ORDER BY started DESC LIMIT 1").fetchone()[0]   # 11-05: latest ETH tree (was pinned to 11-02)
in_tree = lambda a: (EB.execute("SELECT 1 FROM wallet WHERE run_id=? AND lower(address)=lower(?) AND status='tree'", (ER, a)).fetchone() is not None) if a.startswith('0x') \
    else C.execute('SELECT 1 FROM ledger_node WHERE address=? LIMIT 1', (a,)).fetchone() is not None
ETH = f"https://eth-mainnet.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"
Q = '{allSwapRequests(condition:{destinationAddress:"%s"},first:200){nodes{nativeId}}}'
rows = []
for dest in sys.argv[1:]:
    ids = [n['nativeId'] for n in get('https://explorer-service-processor.chainflip.io/graphql', data=json.dumps({'query': Q % dest}).encode())['data']['allSwapRequests']['nodes']]
    for i in ids:
        s = get(f'https://chainflip-swap.chainflip.io/v2/swaps/{i}', wait=2.0)
        h = (s.get('deposit') or {}).get('txRef')
        ch = (s.get('depositChannel') or {}).get('id', '').split('-')[1:2] or ['?']
        snd = []                       # 11-05: sender only on the deposit's own chain (a Solana sig was sent to TronGrid and crashed the run)
        if h and ch[0] == 'Ethereum':  # Ethereum deposit: tx sender (key in URL -> never cached/printed)
            t = json.load(urllib.request.urlopen(urllib.request.Request(ETH, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getTransactionByHash', 'params': [h]}).encode(), {'Content-Type': 'application/json'}), timeout=60))['result']
            snd = [t['from']] if t else []
        elif h and ch[0] == 'Tron':
            ev = get(f'https://api.trongrid.io/v1/transactions/{h}/events', TH, wait=0.15)
            snd = [b58(e['result']['from']) for e in ev.get('data', []) if e.get('event_name') == 'Transfer']
        rows.append(dict(id=i, dest=dest, src=ch[0], asset=s.get('srcAsset') or s.get('sourceAsset'), dep_tx=h, sender=snd[0] if snd else None,
                         usdt=int((s.get('deposit') or {}).get('amount', 0)) / 1e6, btc=int((s.get('swapEgress') or {}).get('amount', 0)) / 1e8,
                         egress=(s.get('swapEgress') or {}).get('txRef'), refund=(s.get('fillOrKillParams') or {}).get('refundAddress'), state=s.get('state')))
print('by source chain', dict(collections.Counter(r['src'] for r in rows)))
print(f"swaps {len(rows)} · USDT {sum(r['usdt'] for r in rows):,.2f} · BTC {sum(r['btc'] for r in rows):.8f} · states {dict(collections.Counter(r['state'] for r in rows))}")
fund = {}
for a, n in collections.Counter(r['sender'] for r in rows if r['sender']).items():
    if a.startswith('0x'):
        fund[a] = {'swaps': n, 'in_tree': in_tree(a), 'funders': []}; print(f"\nDEPOSITOR {a} (Ethereum)  swaps {n}  in_eth_tree={fund[a]['in_tree']}"); continue
    d = get(f'https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_to=true&limit=50&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', TH, wait=0.15)
    fr = collections.Counter()
    for t in d.get('data', []): fr[t['from']] += int(t['value']) / 1e6
    fund[a] = {'swaps': n, 'in_tree': in_tree(a), 'funders': [(f, v, in_tree(f)) for f, v in fr.most_common(8)]}
    print(f"\nDEPOSITOR {a}  swaps {n}  in_tree={fund[a]['in_tree']}")
    for f, v, t in fund[a]['funders'][:5]: print(f'   <- {f} {v:>16,.2f} USDT  in_tree={t}')
json.dump({'swaps': rows, 'depositors': fund}, open(f'raw/cf_dest_{sys.argv[1][:8]}.json', 'w'), indent=1)
