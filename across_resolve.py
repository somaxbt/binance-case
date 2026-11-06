"""Resolve the Tron tree's Across Protocol V5 deposits (Tron_PrefundedAdapter TB6QHSqm, two-step; Tron_Executor TANdmAmc) to the destination fill.
  deposit tx -> PrefundingStored witness -> PrefundedFunding exec tx (same witness, seconds later) -> Across /deposit/status (by exec tx) ->
  fill tx on the destination chain -> FilledRelay event (updated recipient + output amount, read on-chain).
  python3 across_resolve.py     cache raw/tron/bridge_across.json (deposit hash -> record)"""
import json, os, sqlite3, time, urllib.request, urllib.error, threading
from concurrent.futures import ThreadPoolExecutor
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K, AK = E['TRONGRID_API_KEY'], E['ALCHEMY_API_KEY']
ADAPTER, EXECUTOR = 'TB6QHSqmof2ssxoKkWwabTbvDbCxydZ23a', 'TANdmAmc5jyNEFB1gXbEBfaG7Ftj1XNUG1'
NET = {1: 'eth', 42161: 'arb', 8453: 'base', 10: 'opt', 137: 'polygon', 59144: 'linea', 324: 'zksync', 534352: 'scroll', 81457: 'blast', 130: 'unichain', 56: 'bnb'}
TOK = {'dac17f958d2ee523a2206206994597c13d831ec7': ('USDT', 6), 'a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': ('USDC', 6), 'c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': ('ETH', 18),
       '82af49447d8a07e3bd95bd0d56f35241523fbab1': ('ETH', 18), 'af88d065e77c8cc2239327c5edb3a432268e5831': ('USDC', 6), 'fd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9': ('USDT', 6),
       '833589fcd6edb6e08f4c7c32d4f71b54bda02913': ('USDC', 6), '4200000000000000000000000000000000000006': ('ETH', 18), '0b2c639c533813f4aa9d7837caf62653d097ff85': ('USDC', 6)}
FILLED = '0x44b559f101f8fbcc8a0ea43fa91a05a729a5ea6e14a7c75aa750374690137208'          # FilledRelay (Across V3+)
L = threading.Lock(); last = [0.0]
def req(url, body=None, h=None, gap=0.25):
    for i in range(6):
        with L:
            w = last[0] + gap - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode() if body else None, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0', **(h or {})}), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): return json.loads(e.read() or b'{}')
            time.sleep(5 * (i + 1))
        except Exception: time.sleep(3 * (i + 1))
    return {}
TG = lambda p: req('https://api.trongrid.io' + p, h={'TRON-PRO-API-KEY': K})
def across(h): return req(f'https://app.across.to/api/deposit/status?originChainId=728126428&depositTxHash={h}', gap=0.5)
def fill(chain, tx):
    net = NET.get(chain)
    if not net: return {}
    r = req(f'https://{net}-mainnet.g.alchemy.com/v2/{AK}', {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getTransactionReceipt', 'params': [tx]}).get('result') or {}
    for lg in r.get('logs', []):
        if len(lg['topics']) == 4 and int(lg['topics'][1], 16) == 728126428 and (len(lg['data']) - 2) // 64 >= 15:   # FilledRelay: indexed originChainId = Tron
            w = [lg['data'][2 + 64 * i: 2 + 64 * (i + 1)] for i in range((len(lg['data']) - 2) // 64)]
            tok = w[1][-40:]; sym, dec = TOK.get(tok, ('0x' + tok, 18))
            recip = '0x' + (w[11][-40:] if int(w[11], 16) else w[9][-40:])                        # relayExecutionInfo.updatedRecipient, else recipient
            amt = int(w[13] if int(w[13], 16) else w[3], 16) / 10 ** dec                            # updatedOutputAmount, else outputAmount
            return {'recipient': recip, 'out_token': sym, 'out_amount': amt}
    return {'fill_receipt_without_FilledRelay': True}
SWAPPERS = {'0x0cef320d0c5793ade37964e2661a033771e53cd5', '0x000000000004444c5dc75cb358380d2e3de08a90'}   # solver / Uniswap v4 PoolManager: swap legs, never payees
EXEC = '0x9e64d18073cd8ec20e2680124d0551ba1629fa20'          # Across V5 executor (Ethereum): runs the route's actions (swap/unwrap/forward) inside the fill tx
def final(chain, tx):
    """payees of the executor inside the fill tx (internal ETH + ERC20), excluding the executor itself, the swap solver and the relayer"""
    net = NET.get(chain)
    if not net: return {}
    u = f'https://{net}-mainnet.g.alchemy.com/v2/{AK}'
    rc = req(u, {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getTransactionReceipt', 'params': [tx]}).get('result') or {}
    if not rc: return {}
    tr = req(u, {'jsonrpc': '2.0', 'id': 1, 'method': 'alchemy_getAssetTransfers', 'params': [{'fromBlock': rc['blockNumber'], 'toBlock': rc['blockNumber'], 'fromAddress': EXEC, 'category': ['internal', 'external', 'erc20']}]}).get('result', {}).get('transfers', [])
    tr = [t for t in tr if t['hash'] == tx]
    inb = [t for t in req(u, {'jsonrpc': '2.0', 'id': 1, 'method': 'alchemy_getAssetTransfers', 'params': [{'fromBlock': rc['blockNumber'], 'toBlock': rc['blockNumber'], 'toAddress': EXEC, 'category': ['internal', 'external', 'erc20']}]}).get('result', {}).get('transfers', []) if t['hash'] == tx]
    relayer = (rc.get('from') or '').lower()
    got_back = {t['asset'] for t in inb if t['from'] not in (EXEC, relayer)}           # swap output assets returned to the executor (from a pool / solver)
    swap_cp = SWAPPERS | {t['from'] for t in inb if t['from'] not in (EXEC, relayer)}           # anyone who sent value back to the executor = swap counterparty
    tr = [t for t in tr if t['to'] not in swap_cp]
    if got_back: pay = [t for t in tr if t['to'] not in (EXEC, relayer) and (t['category'] == 'internal' or t['asset'] in got_back or (t['asset'] == 'WETH' and 'WETH' in got_back))]
    else: pay = [t for t in tr if t['to'] not in (EXEC, relayer)]                       # no swap: plain forward
    if any(t['category'] == 'internal' for t in pay): pay = [t for t in pay if t['category'] == 'internal' or t['asset'] not in ('WETH',)]
    return {'final': [{'to': t['to'], 'asset': t['asset'], 'amount': t['value'], 'kind': t['category']} for t in pay]}
def resolve(h, to, ts):
    rec = {'deposit': h, 'via': 'adapter' if to == ADAPTER else 'executor'}
    st = across(h)
    if st.get('error') and to == ADAPTER:                                                    # two-step: find the execution tx by the prefund witness
        ev = TG(f'/v1/transactions/{h}/events').get('data', [])
        wit = next((e['result'].get('witness') for e in ev if e.get('event_name') == 'PrefundingStored'), None); rec['witness'] = wit
        if wit:
            for e in TG(f'/v1/contracts/{ADAPTER}/events?event_name=PrefundedFunding&min_block_timestamp={ts}&max_block_timestamp={ts + 3600000}&limit=200&order_by=block_timestamp,asc').get('data', []):
                if e['result'].get('witness') == wit: rec['exec'] = e['transaction_id']; break
        if rec.get('exec'): st = across(rec['exec'])
    rec['status'] = st.get('status') or st.get('error'); rec['dst_chain'] = st.get('destinationChainId'); rec['fill_tx'] = st.get('fillTx'); rec['refund_tx'] = st.get('depositRefundTxHash')
    if rec['fill_tx']: rec.update(fill(rec['dst_chain'], rec['fill_tx']))
    if (rec.get('recipient') or '').lower() == EXEC: rec.update(final(rec['dst_chain'], rec['fill_tx']))
    return h, rec
if __name__ == '__main__':
    C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
    dep = {h: (t, ts) for h, t, ts in C.execute("SELECT hash, too, MIN(ts) FROM ledger_edge WHERE cls LIKE 'out:%' AND too IN (?,?) AND run_id LIKE 'tron2-%' GROUP BY hash", (ADAPTER, EXECUTOR))}
    CACHE = 'raw/tron/bridge_across.json'; cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [h for h in dep if h not in cache or cache[h].get('status') not in ('filled', 'refunded', 'expired') or ((cache[h].get('recipient') or '').lower() == EXEC and ('final' not in cache[h] or any(f['to'] in SWAPPERS for f in cache[h]['final'])))]
    print(f'across: {len(dep)} deposits, {len(todo)} to fetch', flush=True); t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        for i, (h, rec) in enumerate(ex.map(lambda h: resolve(h, *dep[h]), todo)):
            cache[h] = rec
            if i % 25 == 24: json.dump(cache, open(CACHE, 'w')); print(f'  {i + 1}/{len(todo)} | {time.time() - t0:.0f}s', flush=True)
    json.dump(cache, open(CACHE, 'w'))
    from collections import Counter, defaultdict
    print('status:', dict(Counter(r.get('status') for r in cache.values())))
    agg = defaultdict(lambda: [0, 0.0, set()])
    for r in cache.values():
        for f in (r.get('final') or ([{'to': r['recipient'], 'asset': r['out_token'], 'amount': r['out_amount']}] if r.get('recipient') else [])):
            a = agg[(r['dst_chain'], f['asset'])]; a[0] += 1; a[1] += f['amount'] or 0; a[2].add(f['to'])
    for (c, t), (n, v, rc) in sorted(agg.items(), key=lambda x: -x[1][1]): print(f'  chain {c} {t}: {v:,.4f} from {n} fills to {len(rc)} recipients')
