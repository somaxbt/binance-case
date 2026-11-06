"""Binance — ETHEREUM tree ledger on Envio HyperSync (scales to tens of thousands of wallets).
Flows from HyperSync only: transactions (value, gas, status) · internal ETH (eth-traces endpoint, depth>0 calls) · ERC-20 Transfer
logs · WETH Deposit/Withdrawal. ~1,000 addresses per query, paged by next_block. Balances DERIVED from complete flows, then CHECKED
in bulk via Multicall3 (one eth_call per ~400 checks, Alchemy). New receivers classified: attrib.db label → endpoint (FBI 'hack'
→ joins tree) · code check (7702 delegated EOAs count as EOAs) · nonce at hack block > 0 → aged (external) · fresh EOA → joins.
Busy wallets (>2,000 tx in window, or outside money > tree money) → hub, not followed. Origin tags per seed (TRON/SOL/ETH/FBI).
DB: binance-bridged.db (append-only runs).   python3 eth_hs.py test | run [TO_BLOCK] | inc
CHAIN-AWARE (11-05): EVM_CHAIN=eth|avax|arb|opt|polygon|base|bsc (default eth = the original ETH ledger, re-run-validated unchanged).
Side chains: native asset is booked under its symbol (AVAX/BNB/POL/ETH); internal transfers per chain (see NETS 'internal'); seeds =
0x5227 + chain roots · the SAME EOA key = tree wallets of every other chain's CURRENT run (origin KEY) · bridge arrivals to this chain ·
FBI EVM list. Binance PoR wallets (all chains) + the ETH-ledger victims are SOURCES ('in:victim') and endpoints, never followed.
TO_BLOCK is exclusive: pass cutoff block + 1."""
import json, urllib.parse, os, sys, time, sqlite3, csv, random, urllib.request, collections
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"').strip("'") for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
HS_H = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + E['ENVIO_API_TOKEN'].strip()}   # never print
CH = os.environ.get('EVM_CHAIN', 'eth')
# hack = last block ≤ 2026-10-29 20:00 UTC (ETH keeps its original 26300700). internal = where depth>0 native moves come from:
# hs = HyperSync traces · addr:routescan / addr:alchemy = per-address index · txtrace = debug_traceTransaction (QuickNode) of every
# tx that a tree wallet sent or received (trace_filter is capped at 100 blocks there). bs = Blockscout PRO chain id (reverted parents).
NETS = {
  'eth':     dict(hs='eth', internal='hs', al='eth-mainnet', qn=('QUICKNODE_BASE_URL', 'QUICKNODE_TOKEN'), hack=26300700, native='ETH', bs=1, attrib='eth', por='eth',
                  wrapped='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', usdc='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                  majors=['0xdac17f958d2ee523a2206206994597c13d831ec7', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', '0x6b175474e89094c44da98b954eedeac495271d0f', '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599']),
  'avax':    dict(hs='avalanche', internal='addr:routescan', al='avax-mainnet', qn=('QUICKNODE_AVAX_URL', 'QUICKNODE_AVAX_TOKEN'), hack=98891474, native='AVAX', bs=None, attrib='avax', por='avax',
                  wrapped='0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7', usdc='0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e',
                  majors=['0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7', '0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e']),
  'arb':     dict(hs='arbitrum', internal='hs', al='arb-mainnet', qn=None, hack=519455845, native='ETH', bs=42161, attrib='arb', por='arb',
                  wrapped='0x82af49447d8a07e3bd95bd0d56f35241523fbab1', usdc='0xaf88d065e77c8cc2239327c5edb3a432268e5831',
                  majors=['0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9', '0xaf88d065e77c8cc2239327c5edb3a432268e5831', '0xff970a61a04b1ca14834a43f5de4533ebddb5cc8', '0x912ce59144191c1204e64559fe8253a0e49e6548']),
  'opt':     dict(hs='optimism', internal='txtrace', al='opt-mainnet', qn=('QUICKNODE_OP_URL', 'QUICKNODE_OP_TOKEN'), hack=158852611, native='ETH', bs=10, attrib='opt', por='opt',
                  wrapped='0x4200000000000000000000000000000000000006', usdc='0x0b2c639c533813f4aa9d7837caf62653d097ff85',
                  majors=['0x94b008aa00579c1307b0ef2c499ad98a8ce58e58', '0x01bff41798a0bcf287b996046ca68b395dbc1071', '0x0b2c639c533813f4aa9d7837caf62653d097ff85', '0x7f5c764cbc14f9669b88837ca1490cca17c31607', '0x4200000000000000000000000000000000000042']),
  'polygon': dict(hs='polygon', internal='addr:alchemy', al='polygon-mainnet', qn=('QUICKNODE_POLYGON_URL', 'QUICKNODE_POLYGON_TOKEN'), hack=96399047, native='POL', bs=None, attrib='polygon', por='polygon',
                  wrapped='0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270', usdc='0x3c499c542cef5e3811e1192ce70d8cc03d5c3359',
                  majors=['0xc2132d05d31c914a87c6611c10748aeb04b58e8f', '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359', '0x2791bca1f2de4661ed88a30c99a7a9449aa84174', '0x7ceb23fd6bc0add59e62ac25578270cff1b9f619']),
  'base':    dict(hs='base', internal='hs', al='base-mainnet', qn=None, hack=53257326, native='ETH', bs=None, attrib='base', por='base',
                  wrapped='0x4200000000000000000000000000000000000006', usdc='0x833589fcd6edb6e08f4c7c32d4f71b54bda02913',
                  majors=['0x833589fcd6edb6e08f4c7c32d4f71b54bda02913', '0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b', '0xfde4c96c8593536e31f229ea8f37b2ada2699bb2']),
  'bsc':     dict(hs='bsc', internal='txtrace', al='bnb-mainnet', qn=('QUICKNODE_BSC_URL', 'QUICKNODE_BSC_TOKEN'), hack=130533352, native='BNB', bs=None, attrib='bsc', por='bnb',
                  wrapped='0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c', usdc='0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d',
                  majors=['0x55d398326f99059ff775485246999027b3197955', '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d', '0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c', '0x2170ed0880ac9a755fd29b2688956bd959f933f8']),
}
N = NETS[CH]; NATIVE = N['native']; INTERNAL = N['internal']; BS_ID = N['bs']; L1FEE = CH in ('opt', 'base')   # OP-stack: receipt l1Fee is extra gas
AL = f"https://{N['al']}.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"                                      # never print
# state-call pool (pre-screen, Multicall): KEYED endpoints only — every ALCHEMY_API_KEY* (user 11-02: public nodes later, not now).
LANES = [(f"https://{N['al']}.g.alchemy.com/v2/{v}", 100) for k, v in sorted(E.items()) if k.startswith('ALCHEMY_API_KEY') and v]
QNU = None
if N['qn'] and E.get(N['qn'][0]) and E.get(N['qn'][1]):             # 11-04 (user): paid QuickNode = a second state lane (50 req/s)
    u, t = E[N['qn'][0]].rstrip('/'), E[N['qn'][1]].strip()           # AVAX: token goes BEFORE /ext/bc/C/rpc (rstrip first, else HTTP 307)
    QNU = u[:-len('/ext/bc/C/rpc')].rstrip('/') + '/' + t + '/ext/bc/C/rpc' if u.endswith('/ext/bc/C/rpc') else u + '/' + t + '/'
    LANES.append((QNU, 100))
LAST = None
BSK = E.get('BLOCKSCOUT_API_KEY', '').strip(); import threading; _lk = threading.Lock()
HS, HST = f"https://{N['hs']}.hypersync.xyz/query", f"https://{N['hs']}-traces.hypersync.xyz/query"
HACK_BLOCK = N['hack']; TR = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
WETH = N['wrapped']; WDEP = '0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c'; WWD = '0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65'
MC3 = '0xca11bde05977b3631167028862be2a173976ca11'; CHUNK = 1000; HUB_TX = 2000
pad = lambda a: '0x' + a[2:].lower().rjust(64, '0')
num = lambda v: (int(v, 16) if len(v) > 2 else 0) if isinstance(v, str) and v.startswith('0x') else int(v or 0)
DB = os.path.join(HERE, 'binance-bridged.db')
C = sqlite3.connect(DB); C.executescript('''
CREATE TABLE IF NOT EXISTS run(run_id TEXT PRIMARY KEY, chain TEXT, from_block INT, to_block INT, started TEXT, finished TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS wallet(run_id TEXT, address TEXT, status TEXT, origin TEXT, label TEXT, PRIMARY KEY(run_id, address));
CREATE TABLE IF NOT EXISTS edge(run_id TEXT, hash TEXT, block INT, kind TEXT, frm TEXT, too TEXT, asset TEXT, amount REAL, cls TEXT);
CREATE TABLE IF NOT EXISTS node(run_id TEXT, address TEXT, asset TEXT, inn REAL, out REAL, gas REAL, derived REAL, live REAL, unexplained REAL, PRIMARY KEY(run_id, address, asset));''')

def post(url, body, headers, tries=8):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), headers), timeout=120))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise RuntimeError(f'{url.split("/")[2]} HTTP {e.code}')
            time.sleep(min(60, 4 * (i + 1)))
        except Exception: time.sleep(min(60, 4 * (i + 1)))
    raise RuntimeError('request failed: ' + url.split('/')[2])
_last = [0.0]
def hs(url, q, a, b):
    """page through [a, b) — HyperSync returns next_block when a response is partial. ~150 req/min ceiling."""
    out = collections.defaultdict(list); cur = a
    while cur < b:
        with _lk:
            w = _last[0] + 0.4 - time.time()
            if w > 0: time.sleep(w)
            _last[0] = time.time()
        d = post(url, {**q, 'from_block': cur, 'to_block': b}, HS_H)
        for blk in d.get('data', []):
            for k, v in blk.items(): out[k] += v
        nb = d.get('next_block') or b
        if nb <= cur: break
        cur = nb
    return out
def fetch(addrs, a, b):
    """all flows touching addrs in [a, b)"""
    tx, tr, lg = [], [], []
    for i in range(0, len(addrs), CHUNK):
        part = addrs[i:i + CHUNK]; pads = [pad(x) for x in part]
        from concurrent.futures import ThreadPoolExecutor
        def q_tx(): return hs(HS, {'transactions': [{'from': part}, {'to': part}], 'field_selection': {'transaction': ['hash', 'block_number', 'from', 'to', 'value', 'gas_used', 'effective_gas_price', 'status'] + (['l1_fee'] if L1FEE else [])}}, a, b)['transactions']
        def q_tr():
            if INTERNAL != 'hs': return []                                    # per-address / per-tx sources run after q_tx (below)
            try: return hs(HST, {'traces': [{'from': part}, {'to': part}], 'field_selection': {'trace': ['transaction_hash', 'block_number', 'from', 'to', 'value', 'call_type', 'type', 'error', 'trace_address']}}, a, b)['traces']
            except RuntimeError: return blockscout_internal(part, a, b) if BS_ID else alchemy_internal(part, a, b)   # second lane if the traces endpoint fails
        def q_lg(): return hs(HS, {'logs': [{'topics': [[TR], pads]}, {'topics': [[TR], [], pads]}, {'address': [WETH], 'topics': [[WDEP, WWD], pads]}],
                                   'field_selection': {'log': ['transaction_hash', 'block_number', 'log_index', 'address', 'topic0', 'topic1', 'topic2', 'data']}}, a, b)['logs']
        with ThreadPoolExecutor(3) as ex: f1, f2, f3 = ex.submit(q_tx), ex.submit(q_tr), ex.submit(q_lg)
        tx += f1.result(); tr += f2.result(); lg += f3.result()
        if INTERNAL == 'txtrace': tr += tx_internal(part, f1.result()) + extra_internal(part, a, b)
        elif INTERNAL.startswith('addr:'):
            # an EOA only gets an internal native inflow that matters if it later sends (→ a tx) or still holds it (→ balance);
            # querying only those keeps the per-address index to the active wallets. Anything missed still fails the balance check.
            seen_ = {(t.get('from') or '').lower() for t in f1.result()} | {(t.get('to') or '').lower() for t in f1.result()}
            bal = multicall([(MC3, '0x4d2301cc' + x[2:].rjust(64, '0')) for x in part], hex(b - 1))
            act = [x for x, r in zip(part, bal) if x in seen_ or (r and num(r))]
            tr += (routescan_internal if INTERNAL == 'addr:routescan' else alchemy_internal)(act, a, b)
        print(f'    fetched {min(i + CHUNK, len(addrs))}/{len(addrs)} addrs: {len(tx)} tx · {len(tr)} traces · {len(lg)} logs', flush=True)
    return tx, tr, lg

def blockscout_internal(addrs, a, b):
    """fallback: internal ETH transfers per address from Blockscout PRO (5 req/s), shaped like HyperSync traces"""
    out = []
    for x in addrs:
        time.sleep(0.21)
        r = json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.blockscout.com/{BS_ID}/api?module=account&action=txlistinternal&address={x}&startblock={a}&endblock={b}',
                                                                   headers={'Authorization': BSK, 'User-Agent': 'Mozilla/5.0'}), timeout=60))
        for t in r.get('result') or [] if isinstance(r.get('result'), list) else []:
            out.append({'transaction_hash': t['hash'], 'block_number': int(t['blockNumber']), 'from': t['from'], 'to': t['to'], 'value': int(t['value']),
                        'call_type': 'call', 'type': t.get('type', 'call'), 'error': None if t.get('isError') == '0' else 'err', 'trace_address': [t.get('traceId', '0')]})
    return out
def _get(url, headers=None):
    for i in range(8):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', **(headers or {})}), timeout=60))
        except Exception: time.sleep(min(60, 4 * (i + 1)))
    raise RuntimeError('request failed: ' + url.split('/')[2])
def routescan_internal(addrs, a, b):
    """AVAX: internal native transfers per address (Routescan, Etherscan-style, endblock inclusive → b-1), shaped like HyperSync traces"""
    out = []
    for x in addrs:
        page = 1
        while True:
            time.sleep(0.5)
            r = _get(f'https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api?module=account&action=txlistinternal&address={x}&startblock={a}&endblock={b - 1}&page={page}&offset=10000&sort=asc')
            res = r.get('result') if isinstance(r.get('result'), list) else []
            if r.get('status') != '1' and r.get('message') != 'No transactions found': raise RuntimeError(f'routescan {x}: {str(r)[:120]}')
            for t in res:
                ty = (t.get('type') or 'call').lower()
                out.append({'transaction_hash': t['hash'], 'block_number': int(t['blockNumber']), 'from': t['from'], 'to': t['to'] or t.get('contractAddress'), 'value': int(t['value']),
                            'call_type': 'call' if ty == 'call' else None, 'type': 'create' if ty.startswith('create') else ty,
                            'error': None if str(t.get('isError')) == '0' else 'err', 'trace_address': [t.get('traceId') or '0']})
            if len(res) < 10000: break
            page += 1
    print(f'      routescan internal: {len(addrs)} active wallets → {len(out)} frames', flush=True)
    return out
def alchemy_internal(addrs, a, b):
    """Polygon/Base: internal native transfers per address (alchemy_getAssetTransfers 'internal', toBlock inclusive → b-1)"""
    out, seen = [], set()
    for x in addrs:
        for side in ('fromAddress', 'toAddress'):
            pk = None
            while True:
                q = {'fromBlock': hex(a), 'toBlock': hex(b - 1), side: x, 'category': ['internal'], 'excludeZeroValue': True, 'withMetadata': False, 'maxCount': '0x3e8', **({'pageKey': pk} if pk else {})}
                j = post(AL, {'jsonrpc': '2.0', 'id': 1, 'method': 'alchemy_getAssetTransfers', 'params': [q]}, {'Content-Type': 'application/json'})
                if 'error' in j: raise RuntimeError(f"alchemy internal {x}: {j['error']}")
                for t in j['result']['transfers']:
                    if t['uniqueId'] in seen: continue
                    seen.add(t['uniqueId'])
                    out.append({'transaction_hash': t['hash'], 'block_number': int(t['blockNum'], 16), 'from': t['from'], 'to': t['to'], 'value': int(t['rawContract']['value'], 16),
                                'call_type': 'call', 'type': 'call', 'error': None, 'trace_address': [t['uniqueId']]})
                pk = j['result'].get('pageKey')
                if not pk: break
    print(f'      alchemy internal: {len(addrs)} active wallets → {len(out)} frames', flush=True)
    return out
_TRACED = {}
def tx_internal(part, txs):
    """OP/BSC: debug_traceTransaction (callTracer, QuickNode) of every successful tx that a wallet in `part` sent or received.
    Value frames under a reverted frame are marked error (= never happened). Misses only internal inflows inside txs the wallet
    neither sent nor received (e.g. a bridge relayer's payout) → those show up as derived ≠ live and are reported."""
    P = set(part); hs_ = sorted({t['hash'] for t in txs if num(t.get('status', 1)) == 1})
    todo = [h for h in hs_ if h not in _TRACED]
    for i in range(0, len(todo), 20):
        part_ = todo[i:i + 20]
        for attempt in range(8):
            try:
                r = post(QNU, [{'jsonrpc': '2.0', 'id': k, 'method': 'debug_traceTransaction', 'params': [h, {'tracer': 'callTracer'}]} for k, h in enumerate(part_)], {'Content-Type': 'application/json'}, tries=2)
                got = {x['id']: x['result'] for x in r if isinstance(x, dict) and 'result' in x}
                if len(got) == len(part_): break
            except Exception: pass
            time.sleep(min(30, 2 * (attempt + 1)))
        else: raise RuntimeError(f'debug_traceTransaction failed for {len(part_)} txs')
        for k, h in enumerate(part_): _TRACED[h] = got[k]
    blk = {t['hash']: num(t['block_number']) for t in txs}; out = []
    for h in hs_:
        def walk(f, path, dead):
            dead = dead or bool(f.get('error'))
            ty = (f.get('type') or '').upper(); v = int(f.get('value') or '0x0', 16)
            if path and v and ty in ('CALL', 'CREATE', 'CREATE2', 'SELFDESTRUCT') and ((f.get('from') or '').lower() in P or (f.get('to') or '').lower() in P):
                out.append({'transaction_hash': h, 'block_number': blk[h], 'from': f.get('from'), 'to': f.get('to'), 'value': v,
                            'call_type': 'call' if ty == 'CALL' else None, 'type': {'CREATE': 'create', 'CREATE2': 'create', 'SELFDESTRUCT': 'suicide'}.get(ty, 'call'),
                            'error': 'reverted' if dead else None, 'trace_address': path})
            for j, c in enumerate(f.get('calls') or []): walk(c, path + [j], dead)
        walk(_TRACED[h], [], False)
    print(f'      debug traces: {len(todo)} new txs traced ({len(hs_)} in batch) → {len(out)} value frames', flush=True)
    return out
EXTRA_F = os.path.join(HERE, 'raw', 'internal_extra.json')   # {chain: [trace frames]} written by locate() — payouts inside OTHER people's txs
def extra_internal(part, a, b):
    """txtrace chains: frames found by locate() (balance bisection) for wallets in `part`, inside the block window [a, b)"""
    if not os.path.exists(EXTRA_F): return []
    P = set(part); return [t for t in json.load(open(EXTRA_F)).get(CH, []) if a <= t['block_number'] < b and ((t['from'] or '').lower() in P or (t['to'] or '').lower() in P)]
def locate(addr, a, b):
    """find native inflows/outflows of addr in [a, b) that tx_internal cannot see (payout inside a tx the wallet neither sent nor received):
    bisect eth_getBalance over blocks → debug_traceBlockByNumber (callTracer) at each change block → depth>0 value frames touching addr.
    Saved to raw/internal_extra.json, so every later run (full or inc) books them. Returns the new frames."""
    addr = addr.lower()
    # state = (balance, nonce): a balance that comes back to the same value (0 → 1.3 → 0) still moves the nonce if the wallet sent it on
    def bal(blk): return tuple(num(r['result']) for r in sorted(_lane_post([{'jsonrpc': '2.0', 'id': 0, 'method': 'eth_getBalance', 'params': [addr, hex(blk)]},
                                                                    {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_getTransactionCount', 'params': [addr, hex(blk)]}], len(LANES) - 1), key=lambda r: r['id']))
    chg, st = [], [(a - 1, b - 1, bal(a - 1), bal(b - 1))]
    while st:
        l, h, bl, bh = st.pop()
        if bl == bh: continue
        if h - l == 1: chg.append(h); continue
        m = (l + h) // 2; bm = bal(m); st += [(l, m, bl, bm), (m, h, bm, bh)]
    new = []
    for blk in sorted(chg):
        for x in _lane_post({'jsonrpc': '2.0', 'id': 1, 'method': 'debug_traceBlockByNumber', 'params': [hex(blk), {'tracer': 'callTracer'}]}, len(LANES) - 1)['result']:
            h = x.get('txHash'); top = x.get('result') or {}
            if (top.get('from') or '').lower() == addr or (top.get('to') or '').lower() == addr: continue   # the wallet's own / received tx: tx_internal has it
            def walk(f, path, dead):
                dead = dead or bool(f.get('error')); ty = (f.get('type') or '').upper(); v = int(f.get('value') or '0x0', 16)
                if path and v and ty in ('CALL', 'CREATE', 'CREATE2', 'SELFDESTRUCT') and addr in ((f.get('from') or '').lower(), (f.get('to') or '').lower()):
                    new.append({'transaction_hash': h, 'block_number': blk, 'from': f.get('from'), 'to': f.get('to'), 'value': v, 'call_type': 'call' if ty == 'CALL' else None,
                                'type': {'CREATE': 'create', 'CREATE2': 'create', 'SELFDESTRUCT': 'suicide'}.get(ty, 'call'), 'error': 'reverted' if dead else None, 'trace_address': path})
                for j, c in enumerate(f.get('calls') or []): walk(c, path + [j], dead)
            walk(top, [], False)
    OUTF = os.environ.get('LOCATE_OUT') or EXTRA_F                    # parallel runs: one file per wallet, merged afterwards (11-05)
    d = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    have = {(t['transaction_hash'], str(t['trace_address'])) for t in d.get(CH, [])}
    add = [t for t in new if (t['transaction_hash'], str(t['trace_address'])) not in have]
    d.setdefault(CH, []).extend(add); json.dump(d, open(OUTF, 'w'), indent=1)
    print(f'  locate {addr} on {CH}: {len(chg)} balance-change blocks → {len(add)} new frames ({sum(t["value"] for t in add if not t["error"]) / 1e18:.6f} {NATIVE}) saved to {os.path.basename(OUTF)}', flush=True)
    return add
def reverted_frames(h):
    """value frames that never happened (the frame or an ancestor reverted) from debug_traceTransaction callTracer, any lane that has it"""
    r = _lane_post({'jsonrpc': '2.0', 'id': 1, 'method': 'debug_traceTransaction', 'params': [h, {'tracer': 'callTracer'}]}, len(LANES) - 1)['result']; out = set()
    def walk(f, dead):
        dead = dead or bool(f.get('error')); v = int(f.get('value') or '0x0', 16)
        if dead and v: out.add((h, (f.get('from') or '').lower(), (f.get('to') or '').lower(), v / 1e18))
        for c in f.get('calls') or []: walk(c, dead)
    walk(r, False); return out
def _lane_post(body, k):
    """try keyed lanes starting at k (round-robin); returns parsed JSON"""
    order = LANES[k % len(LANES):] + LANES[:k % len(LANES)] + ([LAST] if LAST else [])
    for url, cap in order:
        try:
            if isinstance(body, list) and len(body) > cap:                 # lane can't batch this size → split
                out = []
                for i in range(0, len(body), cap): out += post(url, body[i:i + cap], {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, tries=2)
                return out
            r = post(url, body, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, tries=2)
            if isinstance(r, list) and any('error' in x and 'result' not in x for x in r): continue
            if isinstance(r, dict) and 'error' in r: continue
            return r
        except Exception: continue
    raise RuntimeError('all state lanes failed')
def rpc_batch(calls):
    """keyed Alchemy lanes, one paced stream per key (≈1,000 CU/s free budget; getCode/getTransactionCount ≈26 CU → batches of 20,
    ~0.6 s apart). Items that come back rate-limited inside a batch are retried alone with back-off (up to 8 attempts)."""
    from concurrent.futures import ThreadPoolExecutor
    out = [None] * len(calls); todo = list(range(len(calls)))
    def stream(lane_i, idxs):
        url = LANES[lane_i][0]
        for s0 in range(0, len(idxs), 20):
            part = idxs[s0:s0 + 20]
            for attempt in range(8):
                t = time.time()
                try:
                    r = post(url, [{'jsonrpc': '2.0', 'id': k, 'method': calls[k][0], 'params': calls[k][1]} for k in part], {'Content-Type': 'application/json'}, tries=2)
                    r = r if isinstance(r, list) else []
                except Exception: r = []
                got = {x.get('id'): x for x in r if isinstance(x, dict)}
                left = []
                for k in part:
                    x = got.get(k)
                    if x is not None and 'result' in x: out[k] = x['result']
                    else: left.append(k)
                part = left
                if not part: break
                time.sleep(min(30, 2 * (attempt + 1)))
            if part: raise RuntimeError(f'{len(part)} state calls still failing after retries')
            w = 0.6 - (time.time() - t)
            if w > 0: time.sleep(w)
    groups = [todo[i::len(LANES)] for i in range(len(LANES))]
    with ThreadPoolExecutor(len(LANES)) as ex: list(ex.map(lambda g: stream(*g), enumerate(groups)))
    return out
ALCHEMY_ONLY = [False]
def multicall(calls, block='latest'):
    """calls = [(target, calldata_hex)] → list of returnData hex (None if failed). Multicall3.aggregate3, allowFailure=true."""
    res = []
    for i in range(0, len(calls), 400):
        part = calls[i:i + 400]; n = len(part)
        head, tail = [], []; off = 32 * n
        for t, data in part:
            body = bytes.fromhex(data[2:]); enc = t[2:].rjust(64, '0') + '1'.rjust(64, '0') + hex(96)[2:].rjust(64, '0') + hex(len(body))[2:].rjust(64, '0') + body.hex().ljust(((len(body) + 31) // 32) * 64, '0')
            head.append(hex(off)[2:].rjust(64, '0')); tail.append(enc); off += len(enc) // 2
        data = '0x82ad56cb' + hex(32)[2:].rjust(64, '0') + hex(n)[2:].rjust(64, '0') + ''.join(head) + ''.join(tail)
        r = '0x'
        for attempt in range(8):
            j = post(LANES[(i // 400) % len(LANES)][0], {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'to': MC3, 'data': data}, block]}, {'Content-Type': 'application/json'})
            if 'result' in j: r = j['result'] or '0x'; break
            time.sleep(min(30, 2 * (attempt + 1)))
        raw = bytes.fromhex(r[2:]); base = 32; m = int.from_bytes(raw[base:base + 32], 'big'); arr = base + 32
        for k in range(m):
            o = arr + int.from_bytes(raw[arr + 32 * k: arr + 32 * k + 32], 'big'); ok = int.from_bytes(raw[o:o + 32], 'big')
            bo = o + int.from_bytes(raw[o + 32:o + 64], 'big'); ln = int.from_bytes(raw[bo:bo + 32], 'big')
            res.append('0x' + raw[bo + 32:bo + 32 + ln].hex() if ok else None)
    return res

def screen(addrs):
    """Alchemy pre-screen BEFORE any HyperSync fetch: code, nonce now, nonce at hack block → {addr: kind}.
    kind: contract (non-7702 code) · hub (> HUB_TX sent txs) · aged (sent before the hack) · fresh"""
    out = {}; addrs = list(addrs)
    res = rpc_batch([c for r in addrs for c in (('eth_getCode', [r, 'latest']), ('eth_getTransactionCount', [r, 'latest']), ('eth_getTransactionCount', [r, hex(HACK_BLOCK)]))])
    for k, r in enumerate(addrs):
        code, n_now, n_hack = res[3 * k] or '0x', num(res[3 * k + 1] or '0x0'), num(res[3 * k + 2] or '0x0')
        out[r] = ('contract' if len(code) > 2 and not code.startswith('0xef0100') else 'hub' if n_now > HUB_TX else 'aged' if n_hack > 0 else 'fresh', n_now)
    return out

def labels(addrs):
    A = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db')); out = {}
    for i in range(0, len(addrs), 500):
        part = addrs[i:i + 500]
        for a, e, cat in A.execute(f"SELECT address, entity, category FROM attrib_v WHERE chain=? AND address IN ({','.join('?' * len(part))})", [N['attrib']] + part):
            if a not in out or cat == 'hack': out[a] = (e, cat)
    if os.path.exists(f'binance-{CH}-ledger.db'):                     # exit classes from the theft ledger (side chains: the old evm_ledger runs)
        old = sqlite3.connect(f'binance-{CH}-ledger.db')
        for t, c in old.execute("SELECT too, cls FROM eth_edge WHERE cls LIKE 'out:%' AND cls NOT IN ('out:attacker','out:untracked','out:external')"):
            if t in addrs and t not in out: out[t] = (c[4:], c[4:])
    for a in addrs:
        if a in VICTIMS and a not in out: out[a] = ('Binance PoR', 'victim')
    return out

# side chains: every Binance PoR EVM wallet (any chain — one key can lose assets on many chains) + the ETH-ledger victims.
# ETH keeps its original rules (its victims reach the tree as 'in:seed/bridge' through the old theft ledger's seeds).
VICTIMS = set()
if CH != 'eth':
    VICTIMS = {a for (a,) in sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db')).execute(
        "SELECT address_lc FROM por_wallets WHERE exchange='binance' AND address_lc LIKE '0x%'")}
    VICTIMS |= {a for (a,) in sqlite3.connect('binance-eth-ledger.db').execute("SELECT DISTINCT frm FROM eth_edge WHERE cls='in:victim'")}
ROOTS = {'avax': ['0x80358c5b8f9b2cc27147a1e0f2a6c9a30eb2c397'], 'arb': ['0x3e2bf1ac6bf0934bbba6456c341c2ecbced632d5']}   # + 0x5227 on every chain
NAMES = {'avax': {'AVAX', 'AVAX_MAINNET', 'AVALANCHE', '43114'}, 'arb': {'ARBITRUM', 'ARBITRUM_MAINNET', 'ARB', '42161'}, 'opt': {'OPTIMISM', 'OPTIMISM_MAINNET', 'OP', '10'},
         'polygon': {'POLYGON', 'POLYGON_MAINNET', 'POL', 'MATIC', '137'}, 'base': {'BASE', 'BASE_MAINNET', '8453'}, 'bsc': {'BSC', 'BSC_MAINNET', 'BNB', '56'}}
def current_run(ch):
    r = C.execute(f"SELECT run_id FROM run WHERE finished GLOB '2026*' AND params NOT LIKE '%validation%' AND params NOT LIKE '%INVALID%' AND params NOT LIKE '%aborted%' AND params NOT LIKE '%superseded%' AND (run_id LIKE '{ch}-hs-full-%' OR run_id LIKE '{ch}-hs-inc-%') ORDER BY started DESC LIMIT 1").fetchone()
    return r[0] if r else None
def seeds_side():
    S = {}; add = lambda a, o: S.setdefault(a.lower(), set()).add(o)
    for a in ['0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c'] + ROOTS.get(CH, []): add(a, CH.upper())
    for ch in NETS:                                                   # the SAME EOA key: tree wallets (screened EOAs/7702, never contracts) of every other chain
        r = current_run(ch) if ch != CH else None
        if r:
            for (x,) in C.execute("SELECT address FROM wallet WHERE run_id=? AND status='tree'", (r,)): add(x, 'KEY')
    for a, v in (json.load(open('raw/evm_bridge_seeds.json')).get(CH, {}) if os.path.exists('raw/evm_bridge_seeds.json') else {}).items(): add(a, v['origin'])
    ok = {'success', 'COMPLETED', 'completed', 'Fulfilled', 'SentUnlock', 'ClaimedUnlock', 'done', 'done+partial refund', 'payout', 'Success', 'DELIVERED'}
    for f in ('raw/sol/bridge_dest.json', 'raw/sol/debridge_dest.json'):
        for r in json.load(open(f)) if os.path.exists(f) else []:
            if r.get('status') in ok and str(r.get('chain')).upper() in NAMES[CH] and str(r.get('address') or '').startswith('0x'): add(r['address'], 'SOL')
    for f in ('raw/eth_vault_dest.json', 'raw/eth_thor_dest.json'):
        for r in (json.load(open(f))['rows'].values() if os.path.exists(f) else []):
            if r.get('status') in ok and str(r.get('chain')).upper() in NAMES[CH] and str(r.get('address') or '').startswith('0x'): add(r['address'], 'ETH')
    for x in csv.DictReader(open('raw/tron/carry_over_seeds.csv')):
        if x['dest_chain'].upper() in NAMES[CH] and x['address'].startswith('0x'): add(x['address'], 'TRON')
    for a in open('raw/fbi/fbi_eth.txt').read().split(): add(a, 'FBI')
    for v in VICTIMS: S.pop(v, None)                                   # a victim is a source, never a seed
    return S

def seeds():
    S = {}
    old = sqlite3.connect('binance-eth-ledger.db'); r = old.execute("SELECT run_id FROM ledger_run WHERE leg='eth2' AND finished GLOB '2026*' ORDER BY started DESC LIMIT 1").fetchone()[0]
    for (a,) in old.execute('SELECT DISTINCT address FROM eth_node WHERE run_id=?', (r,)): S.setdefault(a.lower(), set()).add('ETH')
    for x in csv.DictReader(open('raw/tron/carry_over_seeds.csv')):
        if x['dest_chain'] in ('Ethereum', 'ETH') and x['address'].startswith('0x'): S.setdefault(x['address'].lower(), set()).add('TRON')
    for v in json.load(open('raw/sol/layerswap.json')).values():
        sw = v['data'][0]['swap']
        if sw['destination_network']['display_name'] == 'Ethereum': S.setdefault(sw['destination_address'].lower(), set()).add('SOL')
    # 11-05: SOL bridge payouts to Ethereum from the shared resolver (Relay / Chainflip / Layerswap; raw/sol/bridge_dest.json) and the deBridge
    # orders found inside SOL 'swap' txs (raw/sol/debridge_dest.json). Before this only the old layerswap.json was read -> 67 Relay receivers
    # (502.93 ETH) + every deBridge receiver were outside the tree and their BTC payouts showed up as 'outside senders'.
    ok = {'success', 'COMPLETED', 'completed', 'Fulfilled', 'SentUnlock', 'ClaimedUnlock'}
    for f in ('raw/sol/bridge_dest.json', 'raw/sol/debridge_dest.json'):
        if not os.path.exists(f): continue
        for r in json.load(open(f)):
            if r.get('status') in ok and str(r.get('chain')).upper() in ('ETHEREUM', 'ETHEREUM_MAINNET', '1') and str(r.get('address') or '').startswith('0x'):
                S.setdefault(r['address'].lower(), set()).add('SOL')
    for a in open('raw/fbi/fbi_eth.txt').read().split(): S.setdefault(a.lower(), set()).add('FBI')
    return S

ZERO, USDC = '0x' + '0' * 40, N['usdc']
def reclass(E, W, lab, KO=frozenset()):
    """'in:outside' is FOREIGN money only after the SOL-ledger rules (sol_ledger.py) say it is not ours changing form:
    USDC minted from 0x0 = CCTP arrival · the receiving wallet also SENDS in that tx = swap output · sender is a NAMED service
    (attrib.db / exit class) = service payout. What is left stays 'in:outside' → eth_foreign_backtrack.py."""
    outs = {(e[1], e[4]) for e in E if e[4] in W}
    paid = {(e[1], e[5]) for e in E if e[4] in W}                        # (tx, contract) that a tree wallet paid
    snd = sorted({e[4] for e in E if e[8] == 'in:outside'}); L = labels(snd) if snd else {}
    if CH != 'eth' and snd:                                            # bridges deploy at the same address on many chains → ETH 'bridge' labels count here too
        A = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db'))
        for i in range(0, len(snd), 500):
            for a_, e_ in A.execute(f"SELECT address, entity FROM attrib_v WHERE chain='eth' AND category='bridge' AND address IN ({','.join('?' * len(snd[i:i + 500]))})", snd[i:i + 500]):
                L.setdefault(a_, (e_, 'bridge'))
    anon = ('contract', 'aged wallet', 'hub/service', 'endpoint', 'hub', 'tree')
    PF = set(json.load(open('raw/bitget_proven_feeders.json'))['feeders']) if CH == 'eth' and os.path.exists('raw/bitget_proven_feeders.json') else set()   # proven on ETH only
    def c(e):
        if e[8] != 'in:outside': return e
        h, f, to, asset = e[1], e[4], e[5], e[6]
        if f == ZERO: k = 'in:bridge (CCTP mint)' if asset == USDC else 'in:mint'
        elif (h, to) in outs: k = 'in:swap output (tree tx)'
        # 11-05 (user, all chains incl. ETH): swap with the recipient set to ANOTHER tree wallet — the contract that pays us was paid by a tree
        # wallet in the same tx (AVAX: 0xad456c79/0x2ef0f69c → 0x6a000f20 2.06M AVAX → 16.28M USDC to 7 other tree wallets). Bridges excluded
        # (same-tx return from a bridge can be a refund — keep it visible).
        elif (h, f) in paid and not (L.get(f, ('', ''))[1] == 'bridge' or '(bridge)' in lab.get(f, '')): k = 'in:swap output (tree tx)'
        elif f in PF: k = 'in:bridge (Bitget Wallet ← Tron tree)'          # proven by bitget_match.py (deposit ↔ payout, fee 0.4–0.5 %)
        elif f in L and L[f][1] != 'hack': k = f'in:{L[f][0]} ({L[f][1]})'
        elif lab.get(f) and not lab[f].startswith(anon): k = 'in:' + lab[f]
        else: return e
        # 11-05 (user): the attacker moves funds with ONE wallet across many EVM chains → a bridge payout into a SAME-KEY-only wallet is the
        # attacker's own money arriving from another chain: neither new stolen (the source chain booked it as a bridge exit) nor foreign.
        if to in KO and ('(bridge)' in k or k.startswith('in:bridge')): k = 'in:bridge (same key) · ' + k[3:]
        return e[:8] + (k,)
    return [c(e) for e in E]

def run(seed, a, b, tag, max_rounds=99, base=None):
    """base=None: full ledger over [a, b). base=<run_id>: INCREMENTAL — the base run's tree is re-fetched only over [a, b)
    (a = base to_block) and the result is a COMPLETE snapshot under a new run_id (base edges copied, node rows cumulative),
    so every consumer of the CURRENT run keeps working. Seeds and wallets new to the tree get the full window from the hack block."""
    run_id = f'{CH}-hs-{tag}-' + time.strftime('%Y%m%dT%H%M%S')
    BN, long = {}, set(); tree = dict(seed); lab = {}
    if base:
        BN = {(x, s): r for x, s, *r in C.execute('SELECT address, asset, inn, out, gas, derived FROM node WHERE run_id=?', (base,))}
        bt = {x: set(filter(None, o.split(','))) for x, o in C.execute("SELECT address, origin FROM wallet WHERE run_id=? AND status='tree'", (base,))}
        lab = {x: l for x, l in C.execute("SELECT address, label FROM wallet WHERE run_id=? AND status!='tree'", (base,))}
        long = {x for x in seed if x not in bt and x not in lab}; tree = {**{x: seed[x] for x in long}, **bt}
        for x in bt: tree[x] = bt[x] | seed.get(x, set())
    C.execute('INSERT INTO run VALUES(?,?,?,?,?,?,?)', (run_id, CH, HACK_BLOCK if base else a, b, time.strftime('%FT%T'), None,
              json.dumps({'seeds': len(seed), **({'base': base, 'inc_from': a, 'new_seeds': len(long)} if base else {})}))); C.commit()
    print(f'{run_id}: blocks {a}→{b}, {len(seed)} seeds' + (f' · INCREMENTAL on {base}: {len(tree) - len(long)} base tree wallets, {len(long)} new seeds (full window)' if base else ''), flush=True)
    status = {x: 'tree' for x in tree}; done = set(); TX, TRC, LG = [], [], []
    for x, (kind, n) in screen(sorted(long if base else tree)).items():   # seeds are screened too — no exemption (base wallets were screened in the base run)
        if kind == 'contract': status[x] = 'endpoint'; lab[x] = 'contract (seed)'
        elif kind == 'hub': status[x] = 'hub'; lab[x] = f'hub/service ({n:,} tx sent)'
    print(f"  seed screen: {sum(1 for v in status.values() if v == 'hub')} hubs · {sum(1 for v in status.values() if v == 'endpoint')} contracts · {sum(1 for v in status.values() if v == 'tree')} followed", flush=True)
    rounds = 0
    while True:
        todo = sorted(x for x in tree if x not in done and status[x] == 'tree')
        if not todo or rounds >= max_rounds: break
        rounds += 1; _t = time.time()
        tx, tr, lg = fetch([x for x in todo if x not in long], a, b) if any(x not in long for x in todo) else ([], [], [])
        if any(x in long for x in todo):
            t2 = fetch([x for x in todo if x in long], HACK_BLOCK, b); tx += t2[0]; tr += t2[1]; lg += t2[2]
        done |= set(todo); TX += tx; TRC += tr; LG += lg
        print(f'  [round {rounds}] HyperSync fetch {len(todo)} wallets in {time.time() - _t:.1f}s', flush=True); _t = time.time()
        T = set(todo); ntx = collections.Counter(); recv = collections.defaultdict(lambda: collections.defaultdict(int))
        signed = {t['hash'] for t in tx if (t.get('from') or '').lower() in T}   # txs our wallets signed (token sends must be inside one)
        for t in tx:
            f, to = (t.get('from') or '').lower(), (t.get('to') or '').lower()
            for x in (f, to):
                if x in T: ntx[x] += 1
            if f in T and num(t.get('status', 1)) == 1 and num(t.get('value')) > 0 and to: recv[to][f] += 1
        for t in tr:
            f, to = (t.get('from') or '').lower(), (t.get('to') or '').lower()
            if f in T and t.get('trace_address') and not t.get('error') and t.get('call_type') == 'call' and num(t.get('value')) > 0 and to: recv[to][f] += 1
        for l in lg:
            if (l.get('topic0') or '').lower() != TR or not l.get('topic2'): continue
            f, to = '0x' + l['topic1'][-40:].lower(), '0x' + l['topic2'][-40:].lower()
            if f in T and to and l['transaction_hash'] in signed: recv[to][f] += 1
        for x in T:                                                    # safety valve: receive-heavy wallets that send little
            if ntx[x] > HUB_TX: status[x] = 'hub'; lab[x] = f'hub/service ({ntx[x]:,} tx in window)'
        new = [r for r in recv if r not in tree and r not in lab and r != '0x0000000000000000000000000000000000000000']
        if not new: continue
        L = labels(new); SC = screen([r for r in new if r not in L or L[r][1] == 'hack'])
        org = lambda r: set().union(*(tree[s] for s in recv[r] if s in tree))
        for r in new:
            if r in L and L[r][1] != 'hack': lab[r] = f'{L[r][0]} ({L[r][1]})'; continue
            kind, n = SC[r]
            if kind == 'contract': lab[r] = 'contract'
            elif kind == 'hub': lab[r] = f'hub/service ({n:,} tx sent)'
            elif kind == 'aged' and r not in L: lab[r] = 'aged wallet'
            else:
                tree[r] = org(r) | ({'FBI'} if r in L else set()); status[r] = 'tree'
                if base: long.add(r)                                    # new to the tree → full window (it may have pre-window history, e.g. 0xc8a5a620)
            if r in L and r not in tree: lab[r] += ' · FBI-listed'
        print(f'  [round {rounds}] screen+classify {len(new)} receivers in {time.time() - _t:.1f}s: +{sum(1 for r in new if status.get(r) == "tree")} joined · {len(lab)} endpoints · tree {len(tree)}', flush=True)
    # ---- book flows per wallet / asset
    W = {x for x in tree if status[x] == 'tree'};                    # hubs/contracts are endpoints, never booked as tree money
    for x in tree:
        if status[x] != 'tree' and x not in lab: lab[x] = status[x]
    flows = collections.defaultdict(lambda: collections.defaultdict(float)); gas = collections.defaultdict(float)
    tok, edges = set(), []
    def book(h, blk, kind, f, to, asset, v):
        if blk < a and f not in long and to not in long: return           # before the window: only full-window wallets' flows
        for x, side in ((f, 'out'), (to, 'in')):
            if x in W and (blk >= a or x in long): flows[(x, asset)][side] += v   # a base wallet's pre-window flows are in the base
        # a SAME-KEY-only seed was never paid by the theft → outside money into it is FOREIGN ('in:outside' → reclass names swaps/services), never a source
        cls = 'tree' if (f in W and to in W) else ('in:' + ('victim' if f in VICTIMS else 'seed/bridge' if to in seed and f not in W and seed[to] != {'KEY'} else 'outside') if to in W else 'out:' + lab.get(to, 'external'))
        edges.append((run_id, h, blk, kind, f, to, asset, v, cls))
    seen = set(); toplevel = set(); sent_by = collections.defaultdict(set)   # sent_by[hash] = tree wallets that SIGNED that tx
    for t in TX:
        f0, to0 = (t.get('from') or '').lower(), (t.get('to') or '').lower()
        toplevel.add((t['hash'], f0, to0, num(t.get('value'))))
        if f0 in W: sent_by[t['hash']].add(f0)
    for t in TX:
        h = t['hash']
        if h in seen: continue
        seen.add(h); f, to = (t.get('from') or '').lower(), (t.get('to') or '').lower()
        if f in W and (num(t['block_number']) >= a or f in long): gas[f] += num(t.get('gas_used')) * num(t.get('effective_gas_price')) / 1e18 + (num(t.get('l1_fee')) / 1e18 if L1FEE else 0)
        if num(t.get('status', 1)) == 1 and num(t.get('value')) > 0: book(h, num(t['block_number']), 'tx', f, to, NATIVE, num(t['value']) / 1e18)
    seen = set()
    for t in TRC:
        k = (t['transaction_hash'], str(t.get('trace_address')))
        if k in seen or t.get('error') or num(t.get('value')) == 0 or t.get('call_type') not in ('call', None) and t.get('type') not in ('create', 'suicide'): continue
        if (t['transaction_hash'], (t.get('from') or '').lower(), (t.get('to') or '').lower(), num(t.get('value'))) in toplevel: continue   # = the tx itself, already booked
        seen.add(k); book(t['transaction_hash'], num(t['block_number']), 'trace', (t.get('from') or '').lower(), (t.get('to') or '').lower(), NATIVE, num(t['value']) / 1e18)
    seen = set(); raw_tok = []
    for l in LG:
        k = (l['transaction_hash'], num(l.get('log_index')))
        if k in seen: continue
        seen.add(k); t0 = (l.get('topic0') or '').lower(); tk = l['address'].lower()
        if t0 == TR and l.get('topic2'): raw_tok.append((l['transaction_hash'], num(l['block_number']), '0x' + l['topic1'][-40:].lower(), '0x' + l['topic2'][-40:].lower(), tk, num(l.get('data') or '0x0')))
        elif t0 == WDEP: raw_tok.append((l['transaction_hash'], num(l['block_number']), WETH, '0x' + l['topic1'][-40:].lower(), WETH, num(l.get('data') or '0x0')))
        elif t0 == WWD: raw_tok.append((l['transaction_hash'], num(l['block_number']), '0x' + l['topic1'][-40:].lower(), WETH, WETH, num(l.get('data') or '0x0')))
    # tracked tokens: majors always; others only if a tree wallet SENT them in a tx it SIGNED (fake-token poisoning emits
    # Transfer(from=our wallet) inside the spammer's tx → ignored); airdrop spam inbound is never tracked
    MAJORS = set(N['majors']) | {WETH}
    tok |= MAJORS | {s for x, s in BN if s != NATIVE}                    # incremental: keep every token the base tracked
    for h, blk, f, to, tk, v in raw_tok:
        if v and f in W and f in sent_by.get(h, ()): tok.add(tk)
    # NOTE: outflows of TRACKED tokens always count, whoever submitted the tx — intent/gasless swaps (CoW, 1inch Fusion, UniswapX)
    # are submitted by a solver, not the wallet. Poisoning is excluded by the tracking rule (fake tokens never qualify) + v>0.
    toks = sorted(tok); dec = dict(zip(toks, [num(r) if r and len(r) > 2 else 18 for r in multicall([(t, '0x313ce567') for t in toks], hex(b))]))
    for h, blk, f, to, tk, v in raw_tok:
        if tk in tok and v: book(h, blk, 'log', f, to, tk, v / 10 ** dec[tk])
    allE = edges
    if base:                                                              # snapshot = base edges + window edges (a pre-window edge
        pre = {(e[1], e[4], e[5], e[6]) for e in edges if e[2] < a}       # re-read for a full-window wallet replaces its base copy)
        allE = [(run_id, *r) for r in C.execute('SELECT hash, block, kind, frm, too, asset, amount, cls FROM edge WHERE run_id=?', (base,)).fetchall()
                if (r[0], r[3], r[4], r[5]) not in pre] + edges
    allE = reclass(allE, W, lab, {x for x, o in seed.items() if o == {'KEY'}})
    print('  in:outside reclassified:', dict(collections.Counter(e[8] for e in allE if e[8].startswith('in:') and e[8] != 'in:seed/bridge').most_common(8)), flush=True)
    C.executemany('INSERT INTO edge VALUES(?,?,?,?,?,?,?,?,?)', allE)
    # ---- derived vs live. Flows cover blocks [a, b) → live = state after block b-1, opening = state after block a-1
    keys = sorted({(x, NATIVE) for x in W} | set(flows) | {k for k in BN if k[0] in W})
    if base:
        miss = sorted({s for x, s in keys if s != NATIVE and s not in dec})
        dec.update(zip(miss, [num(r) if r and len(r) > 2 else 18 for r in multicall([(t, '0x313ce567') for t in miss], hex(b - 1))]))
    def mc_calls(blk, ks=None):
        return multicall([(MC3, '0x4d2301cc' + x[2:].rjust(64, '0')) if asset == NATIVE else (asset, '0x70a08231' + x[2:].rjust(64, '0')) for x, asset in (ks or keys)], blk)
    live = [num(r) if r else None for r in mc_calls(hex(b - 1))]
    opening = [num(r) if r else 0 for r in mc_calls(hex(a - 1))]
    if long:                                                              # full-window wallets open at the hack block
        lk = [k for k in keys if k[0] in long]; lo = dict(zip(lk, [num(r) if r else 0 for r in mc_calls(hex(HACK_BLOCK - 1), lk)]))
        opening = [lo.get(k, op) for k, op in zip(keys, opening)]
    rows, bad = [], []
    for (x, asset), lv, op in zip(keys, live, opening):
        d = dec.get(asset, 18) if asset != NATIVE else 18; f = flows[(x, asset)]; g = gas[x] if asset == NATIVE else 0.0
        if (x, asset) in BN:                                              # incremental: cumulative since the hack = base + window
            bi, bo, bg, bd = BN[(x, asset)]; fi, fo, gg, der = bi + f['in'], bo + f['out'], bg + g, bd + f['in'] - f['out'] - g
        else: fi, fo, gg, der = f['in'], f['out'], g, op / 10 ** d + f['in'] - f['out'] - g
        lvv = lv / 10 ** d if lv is not None else None
        un = (lvv - der) if lvv is not None else None
        rows.append((run_id, x, asset, fi, fo, gg, der, lvv, un))
        if un is not None and abs(un) > max(1e-6, abs(der) * 1e-6, (f['in'] + f['out']) * 1e-12): bad.append((x, asset, der, lvv, un))   # last term: float64 rounding on huge-supply tokens (PEPE ~1e13)
    if bad:                                                               # never trust a public lane alone: re-read mismatches on Alchemy
        ALCHEMY_ONLY[0] = True; bk = [(x, asset) for x, asset, *_ in bad]
        rr = multicall([(MC3, '0x4d2301cc' + x[2:].rjust(64, '0')) if asset == NATIVE else (asset, '0x70a08231' + x[2:].rjust(64, '0')) for x, asset in bk], hex(b - 1)); ALCHEMY_ONLY[0] = False
        fix = {k: num(v) if v else None for k, v in zip(bk, rr)}; nb = []
        for i, row in enumerate(rows):
            k = (row[1], row[2])
            if k in fix and fix[k] is not None:
                d = dec.get(row[2], 18) if row[2] != NATIVE else 18; lv = fix[k] / 10 ** d; rows[i] = row[:7] + (lv, lv - row[6])
                if abs(lv - row[6]) > max(1e-6, abs(row[6]) * 1e-6): nb.append((row[1], row[2], row[6], lv, lv - row[6]))
        print(f'  re-checked {len(bk)} mismatches on Alchemy → {len(nb)} remain', flush=True); bad = nb
    # an internal call can succeed while an ANCESTOR frame reverts (try/catch) → the value never moved. HyperSync omits the reverted
    # parent frame, so for ETH mismatches only, ask keyed Blockscout PRO (per-frame `success` includes "Parent reverted").
    badw = {x for x, asset, *_ in bad if asset == NATIVE}
    # side chains: no Blockscout → debug_traceTransaction (QuickNode lane); txtrace chains already drop reverted frames at fetch time.
    if badw and INTERNAL != 'txtrace' and not BS_ID and not QNU: print(f'  reverted-subtree check: no trace source on {CH} — {len(badw)} native mismatches left as they are', flush=True)
    if badw and INTERNAL != 'txtrace' and (BS_ID or QNU):
        rev = set()
        for h in sorted({e[1] for e in edges if e[3] == 'trace' and e[6] == NATIVE and (e[4] in badw or e[5] in badw)}):
            if not BS_ID: rev |= reverted_frames(h); continue
            q = ''
            while True:
                time.sleep(0.21)
                r = json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.blockscout.com/{BS_ID}/api/v2/transactions/{h}/internal-transactions{q}',
                                                                           headers={'Authorization': BSK, 'User-Agent': 'Mozilla/5.0'}), timeout=60))
                for x in r.get('items') or []:
                    if not x.get('success') and int(x.get('value') or 0):
                        rev.add((h, ((x.get('from') or {}).get('hash') or '').lower(), ((x.get('to') or {}).get('hash') or '').lower(), int(x['value']) / 1e18))
                np_ = r.get('next_page_params')
                if not np_: break
                q = '?' + urllib.parse.urlencode(np_)
        drop = [e for e in edges if e[3] == 'trace' and e[6] == NATIVE and any(e[1] == h and e[4] == f and e[5] == to and abs(e[7] - v) < 1e-12 for h, f, to, v in rev)]
        adj = collections.defaultdict(float)
        for e in drop:
            edges.remove(e); C.execute("DELETE FROM edge WHERE run_id=? AND hash=? AND kind='trace' AND frm=? AND too=? AND asset=?", (run_id, e[1], e[4], e[5], NATIVE))
            if e[4] in W: adj[(e[4], 'out')] += e[7]
            if e[5] in W: adj[(e[5], 'in')] += e[7]
        for i, row in enumerate(rows):
            if row[2] == NATIVE and ((row[1], 'in') in adj or (row[1], 'out') in adj):
                fi, fo = row[3] - adj[(row[1], 'in')], row[4] - adj[(row[1], 'out')]; der = row[6] - adj[(row[1], 'in')] + adj[(row[1], 'out')]
                rows[i] = row[:3] + (fi, fo, row[5], der, row[7], (row[7] - der) if row[7] is not None else None)
        bad = [(r[1], r[2], r[6], r[7], r[8]) for r in rows if r[8] is not None and abs(r[8]) > max(1e-6, abs(r[6]) * 1e-6)]
        print(f'  reverted-subtree check: {len(drop)} trace edges dropped → {len(bad)} mismatches remain', flush=True)
    if INTERNAL == 'txtrace':                                         # per-tx traces miss payouts inside other people's txs → find them for the next run
        for x in sorted({x for x, asset, *_ in bad if asset == NATIVE}): locate(x, HACK_BLOCK if x in long or not base else a, b)
        if any(asset == NATIVE for x, asset, *_ in bad): print('  → frames saved: RE-RUN this chain to book them', flush=True)
    C.executemany('INSERT OR REPLACE INTO node VALUES(?,?,?,?,?,?,?,?,?)', rows)
    C.executemany('INSERT OR REPLACE INTO wallet VALUES(?,?,?,?,?)', [(run_id, x, status[x], ','.join(sorted(tree[x])), lab.get(x, '')) for x in tree] +
                  [(run_id, x, 'endpoint', '', l) for x, l in lab.items() if x not in tree])
    C.execute('UPDATE run SET finished=? WHERE run_id=?', (time.strftime('%FT%T'), run_id)); C.commit()
    held = collections.defaultdict(float)
    for (x, asset), lv in zip(keys, live):
        if lv: held[asset] += lv / 10 ** (dec.get(asset, 18) if asset != NATIVE else 18)
    print(f'\n=== {run_id}: {len(tree)} wallets ({sum(1 for s in status.values() if s == "hub")} hubs), {len(lab)} endpoints, {len(edges)} edges, {len(toks)} tracked tokens')
    print(f'  held {NATIVE} {held[NATIVE]:,.4f} | wallet×asset balances checked {len(keys)} | mismatches (derived ≠ live) {len(bad)}')
    for x, asset, der, lv, un in sorted(bad, key=lambda z: -abs(z[4]))[:12]: print(f'   ! {x} {asset[:10]} derived {der:,.6f} live {lv:,.6f} diff {un:,.6f}')
    ex = collections.defaultdict(float)
    for e in edges:
        if e[8].startswith('out:') and e[6] == NATIVE: ex[e[8]] += e[7]
    print(f'  {NATIVE} out to endpoints:', {k: round(v, 2) for k, v in sorted(ex.items(), key=lambda kv: -kv[1])[:10]})
    return run_id, bad

if __name__ == '__main__':
    head = post(HS.replace('/query', '/height'), {}, HS_H) if False else json.load(urllib.request.urlopen(urllib.request.Request(HS.replace('/query', '/height'), headers=HS_H), timeout=30))['height']
    S = seeds() if CH == 'eth' else seeds_side(); print(f'{CH} seeds:', len(S), collections.Counter(o for v in S.values() for o in v), '| chain head', head, flush=True)
    if sys.argv[1] == 'lean':
        rnd = random.Random(3); pick = dict(rnd.sample(sorted((k, v) for k, v in S.items() if v == {'TRON'} or CH != 'eth'), 3))
        t0 = time.time(); run(pick, HACK_BLOCK, HACK_BLOCK + 2000, 'lean', max_rounds=1); print(f'lean test wall time {time.time() - t0:.1f}s')
    elif sys.argv[1] == 'test':
        rnd = random.Random(7); pick = dict(rnd.sample(sorted((k, v) for k, v in S.items() if 'TRON' in v), 15) + [(k, v) for k, v in S.items() if 'ETH' in v][:5])
        run(pick, HACK_BLOCK, min(head, HACK_BLOCK + 15000), 'test')
    elif sys.argv[1] == 'run':
        run(S, HACK_BLOCK, int(sys.argv[2]) if len(sys.argv) > 2 else head, 'full')
    elif sys.argv[1] == 'locate':                                         # locate WALLET [FROM_BLOCK TO_BLOCK] — txtrace chains (OP/BSC)
        locate(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else HACK_BLOCK, int(sys.argv[4]) if len(sys.argv) > 4 else head)
    elif sys.argv[1] == 'inc':                                            # inc [BASE_RUN] [TO_BLOCK] — default base: latest finished full/inc run
        base = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != '-' else current_run(CH)
        a = C.execute('SELECT to_block FROM run WHERE run_id=?', (base,)).fetchone()[0]
        run(S, a, int(sys.argv[3]) if len(sys.argv) > 3 else head, 'inc', base=base)
