"""Binance case, ETHEREUM leg: native-unit conservation ledger, every asset, stored in binance-live.db.
  python3 eth_ledger.py run     follow every attacker wallet from the victim transfers, classify every movement, check every wallet
  python3 eth_ledger.py show    sources = uses per asset, open residuals, leads, unknown contracts
Rules: no size cutoff. A token is tracked by CONTRACT (symbol is forgeable); spam tokens are counted but not traced.
Per wallet and asset: IN = OUT + GAS(ETH only) + BALANCE. Anything else is a named residual."""
import json, os, sys, time, sqlite3, gzip, urllib.request, urllib.error
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); DB = os.path.join(HERE, 'binance-eth-ledger.db')
ENV = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
URL = f"https://eth-mainnet.g.alchemy.com/v2/{ENV['ALCHEMY_API_KEY']}"
FROM_BLOCK = hex(26300700)                                   # just before the 7702 delegation (20:20:59 10-29)
VICTIMS = {'0x28c6c06298d514db089934071355e5743bf21d60': 'Binance 14', '0xdfd5293d8e347dfe59e90efd55b2956a1343963d': 'Binance 16',
           '0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055': 'Binance Hot Wallet 34'}
ROOTS = ['0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c', '0xa97bf7836f8a08f9ed91d41453d371493fae8d10', '0x7c8601d4645b93cea45f71e118a729332e6b5ca0']
NOT_ATTACKER = {'0xbeef02961503351625926ea9a11ae13b29f5c555': 'MM/UniswapX filler (seen in 9 cases)'}
ENDPOINTS = {   # verified this case or well-known; value = class
  '0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146': 'bridge:thorchain', '0xb8f275fbf7a959f4bce59999a2ef122a099e81a8': 'bridge:symbiosis',
  '0x5523985926aa12ba58dc5ad00ddca99678d7227e': 'bridge:symbiosis', '0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2': 'lending:aave-v3',
  '0x23878914efe38d27c4d67ab83ed1b93a74d4086a': 'lending:aave-aUSDT', '0x9008d19f58aabd9ed0d60971565aa8510560ab41': 'dex:cow',
  '0x000000000004444c5dc75cb358380d2e3de08a90': 'dex:uniswap-v4', '0x66a9893cc07d91d95644aedd05d03f95e1dba8af': 'dex:uniswap-universal',
  '0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45': 'dex:uniswap-v3-router2', '0x7a250d5630b4cf539739df2c5dacb4c659f2488d': 'dex:uniswap-v2-router',
  '0x111111125421ca6dc452d289314280a0f8842a65': 'dex:1inch', '0x0000000000bbf5c5fd284e657f01bd000933c96d': 'dex:paraswap-delta',
  '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': 'wrap:weth', '0x0000000000000000000000000000000000000000': 'burn',
}
FREEZABLE_CHECK = True
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB);
CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, leg TEXT, started TEXT, finished TEXT, params TEXT, n_nodes INTEGER);
CREATE TABLE IF NOT EXISTS eth_node(run_id TEXT, address TEXT, asset TEXT, symbol TEXT, inn REAL, out REAL, gas REAL, bal REAL, resid REAL,
  frozen INTEGER, why TEXT, PRIMARY KEY(run_id, address, asset));
CREATE TABLE IF NOT EXISTS eth_edge(run_id TEXT, hash TEXT, block INTEGER, frm TEXT, too TEXT, asset TEXT, symbol TEXT, amount REAL, cls TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ee_run ON eth_edge(run_id, cls);
"""
C = None
def http(body):
  tries = waits = 0
  while True:
    try:
      raw = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {'Content-Type': 'application/json', 'User-Agent': 'x'}), timeout=90).read()
      C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), 'alchemy ' + json.dumps(body)[:300], gzip.compress(raw)))
      return json.loads(raw)
    except urllib.error.HTTPError as e:
      tries += 1
      if e.code in (429, 500, 502, 503) and tries <= 6: time.sleep(5 * tries); continue
      raise
    except urllib.error.URLError as e:
      waits += 1
      if waits > 30: raise
      print(f'   network down ({e.reason}), waiting 30s', flush=True); time.sleep(30)
def rpc(m, p):
  j = http({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p})
  if 'error' in j: raise RuntimeError(j['error'])
  return j['result']
def batch(calls):
  out = []
  for i in range(0, len(calls), 50):
    j = http([{'jsonrpc': '2.0', 'id': k, 'method': m, 'params': p} for k, (m, p) in enumerate(calls[i:i + 50])])
    out += [x.get('result') for x in sorted(j, key=lambda x: x['id'])]
  return out
def transfers(one_page=False, **q):
  out, pk = [], None
  while True:
    qq = {'fromBlock': FROM_BLOCK, 'category': ['external', 'internal', 'erc20'], 'withMetadata': False, 'excludeZeroValue': True, 'maxCount': '0x3e8', **q}
    if pk: qq['pageKey'] = pk
    r = rpc('alchemy_getAssetTransfers', [qq]); out += r['transfers']; pk = r.get('pageKey')
    if not pk or one_page: return out

LB = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/labels.db'))
POR = sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
def label(a):
  r = LB.execute('SELECT name, category FROM labels WHERE lower(address)=?', (a,)).fetchone()
  p = POR.execute('SELECT exchange, wallet_type FROM por_wallets WHERE address_lc=?', (a,)).fetchone()
  if p: return f'cex:{p[0]}/{p[1]}'
  if r: return (r[1] or 'label') + ':' + (r[0] or '')[:40]
  return ''

def run():
  global C
  C = sqlite3.connect(DB, timeout=600); C.execute('PRAGMA journal_mode=WAL'); C.executescript(SCHEMA)
  run_id = 'eth-' + time.strftime('%Y%m%dT%H%M%S')
  C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?,?)', (run_id, 'eth', time.strftime('%FT%T'), None, json.dumps({'from': FROM_BLOCK, 'roots': ROOTS}), 0)); C.commit()
  attacker = {r: 'root' for r in ROOTS}; queue = list(ROOTS); done = set()
  tracked = {'ETH'}                                     # asset keys: 'ETH' or token contract
  sym = {'ETH': 'ETH'}
  kind = {}                                             # address -> 'contract'|'eoa'
  def is_contract(a):
    if a not in kind: kind[a] = 'contract' if len(rpc('eth_getCode', [a, 'latest'])) > 50 else 'eoa'   # 7702 stub (23 bytes) counts as EOA
    return kind[a] == 'contract'
  def classify(to):
    if to in attacker: return 'attacker', attacker[to]
    if to in VICTIMS: return 'victim', VICTIMS[to]
    if to in NOT_ATTACKER: return 'external', NOT_ATTACKER[to]
    if to in ENDPOINTS: return ENDPOINTS[to].split(':')[0], ENDPOINTS[to]
    lb = label(to)
    if lb: return lb.split(':')[0], lb
    if is_contract(to): return 'contract', ''
    nonce = int(rpc('eth_getTransactionCount', [to, 'latest']), 16)
    if nonce > 2000: return 'service', f'busy EOA nonce {nonce}'
    first = transfers(one_page=True, toAddress=to, order='asc', maxCount='0x5', category=['external', 'internal', 'erc20'])
    first = [t for t in first if (t['asset'] == 'ETH' and t['category'] != 'erc20') or (t.get('rawContract') or {}).get('address') in tracked]
    if first and first[0]['from'] in attacker: return 'new_attacker', f'first funded by {first[0]["from"]}'
    return 'external', 'first funded by ' + (first[0]['from'] if first else '?')
  while queue:
    a = queue.pop(0)
    if a in done: continue
    done.add(a)
    ins = transfers(toAddress=a); outs = transfers(fromAddress=a)
    flows = defaultdict(lambda: {'in': 0.0, 'out': 0.0}); hashes = set()
    for t in ins + outs:
      if t['category'] == 'erc20':
        key = (t.get('rawContract') or {}).get('address');
        if not key: continue
      else: key = 'ETH'
      v = t['value'] or 0
      if v == 0: continue
      inbound = t['to'] == a
      other = t['from'] if inbound else t['to']
      if not inbound: hashes.add(t['hash'])           # gas is paid only on txs this wallet sent; inbound spam needs no receipt
      if inbound:
        if other in VICTIMS:
          cls = 'in:victim'; tracked.add(key)
        elif other in attacker: cls = 'in:attacker'
        elif key not in tracked and other not in ENDPOINTS and not label(other): cls = 'in:spam'
        else:
          c, det = classify(other); cls = 'in:' + ('swap_or_contract' if c in ('dex', 'contract', 'wrap', 'lending', 'bridge') else c)
          if c in ('dex', 'contract', 'wrap', 'lending', 'bridge'): tracked.add(key)
      else:
        if key not in tracked: cls = 'out:untracked'
        else:
          c, det = classify(other)
          if c == 'new_attacker': attacker[other] = det; queue.append(other); c = 'attacker'
          cls = 'out:' + c
      sym[key] = t['asset'] or sym.get(key, '?')
      flows[key]['in' if inbound else 'out'] += v
      C.execute('INSERT INTO eth_edge VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['hash'], int(t['blockNum'], 16), t['from'], t['to'], key, sym[key], v, cls, ''))
    # gas: receipts of every tx this wallet sent (receipt.from == a)
    gas = 0.0
    for r in batch([('eth_getTransactionReceipt', [h]) for h in sorted(hashes)]):
      if r and r['from'] == a: gas += int(r['gasUsed'], 16) * int(r.get('effectiveGasPrice', '0x0'), 16) / 1e18
    nonce = int(rpc('eth_getTransactionCount', [a, 'latest']), 16)
    keys = [k for k in flows if k in tracked]
    bals = {}
    if 'ETH' in keys: bals['ETH'] = int(rpc('eth_getBalance', [a, 'latest']), 16) / 1e18
    tok = [k for k in keys if k != 'ETH']
    for k, r in zip(tok, batch([('eth_call', [{'to': k, 'data': '0x70a08231' + a[2:].rjust(64, '0')}, 'latest']) for k in tok])):
      dec = next((t['rawContract'].get('decimal') for t in ins + outs if (t.get('rawContract') or {}).get('address') == k and t['rawContract'].get('decimal')), None)
      d = int(dec, 16) if dec else 18
      bals[k] = (int(r, 16) / 10 ** d) if r and r != '0x' else 0.0
    for k in keys:
      f = flows[k]; g = gas if k == 'ETH' else 0.0; b = bals.get(k, 0.0)
      frozen = 0
      if FREEZABLE_CHECK and k != 'ETH' and b > 0:
        j = http({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'from': a, 'to': k, 'data': '0xa9059cbb' + '000000000000000000000000000000000000000000000000000000000000dead'.rjust(64, '0') + '1'.rjust(64, '0')}, 'latest']})
        frozen = 1 if 'error' in j else 0
      C.execute('INSERT OR REPLACE INTO eth_node VALUES(?,?,?,?,?,?,?,?,?,?,?)', (run_id, a, k, sym.get(k), f['in'], f['out'], g, b, f['in'] - f['out'] - g - b, frozen, attacker.get(a, '')))
    C.commit()
    e = flows.get('ETH', {'in': 0, 'out': 0})
    print(f"[{len(done)}/{len(done)+len(queue)}] {a} nonce {nonce} | ETH in {e['in']:,.4f} out {e['out']:,.4f} gas {gas:.4f} bal {bals.get('ETH',0):,.4f} resid {e['in']-e['out']-gas-bals.get('ETH',0):,.4f} | tokens {len(tok)} | new attacker wallets queued {len(queue)}", flush=True)
  C.execute('UPDATE ledger_run SET finished=?, n_nodes=? WHERE run_id=?', (time.strftime('%FT%T'), len(done), run_id)); C.commit()
  show(run_id)

def show(run_id=None):
  c = sqlite3.connect(DB)
  run_id = run_id or c.execute("SELECT run_id FROM ledger_run WHERE leg='eth' ORDER BY started DESC LIMIT 1").fetchone()[0]
  print(f'\n=== {run_id} ===  wallets: {c.execute("SELECT COUNT(DISTINCT address) FROM eth_node WHERE run_id=?", (run_id,)).fetchone()[0]}')
  assets = [r[0] for r in c.execute("SELECT asset FROM eth_edge WHERE run_id=? AND cls='in:victim' GROUP BY asset ORDER BY SUM(amount) DESC", (run_id,))]
  for k in ['ETH'] + [x for x in assets if x != 'ETH']:
    s = c.execute("SELECT symbol FROM eth_node WHERE run_id=? AND asset=? LIMIT 1", (run_id, k)).fetchone()
    src = c.execute("SELECT cls, SUM(amount) FROM eth_edge WHERE run_id=? AND asset=? AND cls LIKE 'in:%' AND cls NOT IN ('in:attacker','in:spam') GROUP BY cls", (run_id, k)).fetchall()
    use = c.execute("SELECT cls, SUM(amount) FROM eth_edge WHERE run_id=? AND asset=? AND cls LIKE 'out:%' AND cls NOT IN ('out:attacker','out:untracked') GROUP BY cls", (run_id, k)).fetchall()
    held, frz, gas, res = c.execute("SELECT SUM(CASE WHEN frozen=0 THEN bal END), SUM(CASE WHEN frozen=1 THEN bal END), SUM(gas), SUM(resid) FROM eth_node WHERE run_id=? AND asset=?", (run_id, k)).fetchone()
    S = sum(v for _, v in src); U = sum(v for _, v in use) + (held or 0) + (frz or 0) + (gas or 0)
    print(f"\n{(s[0] if s else k)} [{k}]  SOURCES {S:,.6f} = USES {U:,.6f}  -> UNEXPLAINED {S-U:,.6f}")
    for cl, v in src: print(f"   + {cl:24} {v:>22,.6f}")
    for cl, v in use: print(f"   - {cl:24} {v:>22,.6f}")
    print(f"   - {'held':24} {held or 0:>22,.6f}\n   - {'frozen':24} {frz or 0:>22,.6f}" + (f"\n   - {'gas':24} {gas or 0:>22,.6f}" if k == 'ETH' else ''))
  print('\nopen per-wallet residuals (|resid| > 1e-6 of asset):')
  for r in c.execute("SELECT address, symbol, inn, out, gas, bal, resid FROM eth_node WHERE run_id=? AND ABS(resid) > 0.000001 ORDER BY ABS(resid) DESC LIMIT 30", (run_id,)): print('  ', r)
  print('\nleads: external wallets / unknown contracts / services (by amount):')
  for r in c.execute("SELECT cls, too, symbol, SUM(amount), COUNT(*) FROM eth_edge WHERE run_id=? AND cls IN ('out:external','out:contract','out:service','out:cex') GROUP BY cls, too, symbol ORDER BY 4 DESC LIMIT 40", (run_id,)): print('  ', r)

if __name__ == '__main__':
  {'run': run, 'show': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None)}[sys.argv[1]]()
