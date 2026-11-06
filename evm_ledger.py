"""Binance case — EVM side-chain ledgers (AVAX/ARB/OP/POL/Base), same method as eth_ledger2 (pinned block).
  python3 evm_ledger.py run CHAIN|all      python3 evm_ledger.py show CHAIN
Original ETH v2 doc: Reuses v1's destination classes; fixes v1's known defects.
  python3 eth_ledger2.py run [BLOCK]     default = latest
  python3 eth_ledger2.py show [run_id]
Fixes vs v1: (1) one pinned block for transfers AND balances (eth_call/eth_getBalance at that block);
(2) every stolen asset (all victim-sent contracts) tracked from the start — nothing becomes 'spam'/'untracked' by order;
(3) transfers de-duplicated by Alchemy uniqueId; (4) decimals from each contract; (5) gas from receipts of txs the wallet sent.
Writes run 'eth2-…' into binance-eth-ledger.db (v1 rows untouched)."""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
CHAINS = {  # alchemy net, categories Alchemy supports there, extra known attacker roots
  'avax':    ('avax-mainnet',  ['external', 'erc20'],             ['0x80358c5b8f9b2cc27147a1e0f2a6c9a30eb2c397']),
  'arb':     ('arb-mainnet',   ['external', 'erc20'],             ['0x3e2bf1ac6bf0934bbba6456c341c2ecbced632d5']),
  'opt':     ('opt-mainnet',   ['external', 'erc20'],             []),
  'polygon': ('matic-mainnet', ['external', 'internal', 'erc20'], []),
  'base':    ('base-mainnet',  ['external', 'internal', 'erc20'], []),
  'bsc':     ('bnb-mainnet',   ['external', 'erc20'],             []),          # 11-04: SOL Layerswap/Relay arrivals
}
# 11-04: bridge arrivals (SOL/ETH legs → this chain) as extra roots; their payout inflow = 'in:bridge (…)' (CCTP mint from 0x0, or a
# known payout tx). raw/evm_bridge_seeds.json {chain: {addr: {via, origin, amount, payout_txs}}}. EVM_CUTOFF_TS = pin at that time.
ZERO = '0x0000000000000000000000000000000000000000'
BSEED, PAYOUTS = {}, set()
CHAIN = None; DB = None; CATS = None
K = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
URL = None
FROM = 0
VICTIMS = {}; ROOTS = []
def setup(chain):
  global CHAIN, DB, CATS, URL, VICTIMS, ROOTS
  net, cats, extra = CHAINS[chain]
  CHAIN, CATS, URL = chain, cats, f'https://{net}.g.alchemy.com/v2/{K}'
  DB = os.path.join(HERE, f'binance-{chain}-ledger.db')
  P = sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
  VICTIMS = {a: f'Binance PoR ({w})' for a, w in P.execute("SELECT address_lc, wallet_type FROM por_wallets WHERE exchange='binance' AND chain=?", (chain,))}
  ROOTS = ['0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c'] + extra
  bs = json.load(open(os.path.join(HERE, 'raw/evm_bridge_seeds.json'))).get(chain, {}) if os.path.exists(os.path.join(HERE, 'raw/evm_bridge_seeds.json')) else {}
  BSEED.clear(); PAYOUTS.clear(); BSEED.update({a: v['via'] for a, v in bs.items()}); PAYOUTS.update(t for v in bs.values() for t in v['payout_txs'])
  ROOTS += [a for a in bs if a not in ROOTS]
NOT_ATTACKER = {'0xbeef02961503351625926ea9a11ae13b29f5c555'}
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
def post(body):
  for i in range(8):
    try: return json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {'Content-Type': 'application/json', 'User-Agent': 'x'}), timeout=120))
    except urllib.error.HTTPError as e:
      if e.code in (429, 500, 502, 503): time.sleep(4 * (i + 1)); continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(15 * (i + 1))
  raise RuntimeError('alchemy failed')
def rpc(m, p):
  j = post({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p})
  if 'error' in j: raise RuntimeError(f'{m}: {j["error"]}')
  return j['result']
def batch(calls):
  out = []
  for i in range(0, len(calls), 50):
    out += [x.get('result') for x in sorted(post([{'jsonrpc': '2.0', 'id': k, 'method': m, 'params': p} for k, (m, p) in enumerate(calls[i:i + 50])]), key=lambda x: x['id'])]
  return out
def transfers(B, one_page=False, **q):
  out, pk, seen = [], None, set()
  while True:
    qq = {'fromBlock': hex(FROM), 'toBlock': hex(B), 'category': CATS, 'withMetadata': False, 'excludeZeroValue': True, 'maxCount': '0x3e8', **q}
    if pk: qq['pageKey'] = pk
    r = rpc('alchemy_getAssetTransfers', [qq]); pk = r.get('pageKey')
    for t in r['transfers']:
      if t['uniqueId'] in seen: continue
      seen.add(t['uniqueId']); out.append(t)
    if not pk or one_page: return out
pad = lambda a: a[2:].lower().rjust(64, '0')

def run():
  c = sqlite3.connect(DB, timeout=600); c.execute('PRAGMA journal_mode=WAL')
  c.executescript("""CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, leg TEXT, started TEXT, finished TEXT, params TEXT, n_nodes INTEGER);
  CREATE TABLE IF NOT EXISTS eth_node(run_id TEXT, address TEXT, asset TEXT, symbol TEXT, inn REAL, out REAL, gas REAL, bal REAL, resid REAL, frozen INTEGER, why TEXT, PRIMARY KEY(run_id, address, asset));
  CREATE TABLE IF NOT EXISTS eth_edge(run_id TEXT, hash TEXT, block INTEGER, frm TEXT, too TEXT, asset TEXT, symbol TEXT, amount REAL, cls TEXT, detail TEXT);""")
  v1 = None
  B = int(rpc('eth_blockNumber', []), 16)
  if os.environ.get('EVM_CUTOFF_TS'):                                   # last block with timestamp <= the common cutoff
    T = int(os.environ['EVM_CUTOFF_TS']); lo, hi = 0, B
    while lo < hi:
      m = (lo + hi + 1) // 2
      if int(rpc('eth_getBlockByNumber', [hex(m), False])['timestamp'], 16) <= T: lo = m
      else: hi = m - 1
    B = lo
  run_id = CHAIN + '-' + time.strftime('%Y%m%dT%H%M%S')
  c.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?,?)', (run_id, CHAIN, time.strftime('%FT%T'), None, json.dumps({'block': B, 'from': FROM, 'reuses': v1, 'cutoff_ts': os.environ.get('EVM_CUTOFF_TS'), 'bridge_roots': len(BSEED)}), 0)); c.commit()
  print(f'{run_id}: pinned at block {B}', flush=True)
  # (2) all stolen assets tracked from the start
  tracked = {'ETH'}                     # native; victim-sent tokens become tracked on sight (victims → 0x5227 are the first inflows processed)
  # reuse v1 classes for known destinations (attacker set grows as we go)
  v1cls = {}
  v1nodes = set()
  attacker = set(ROOTS); queue = list(ROOTS); done = set(); kind = {}
  dec = {'ETH': 18}
  def decimals(tok):
    if tok not in dec:
      r = rpc('eth_call', [{'to': tok, 'data': '0x313ce567'}, 'latest']); dec[tok] = int(r, 16) if r and r != '0x' else 18
    return dec[tok]
  def classify(to):
    if to in attacker: return 'attacker'
    if to in VICTIMS: return 'victim'
    if to in NOT_ATTACKER: return 'external'
    if to in v1nodes: return 'new_attacker'                         # v1 already proved it attacker-funded
    if to in v1cls and v1cls[to] != 'attacker': return v1cls[to]
    if to not in kind: kind[to] = 'contract' if len(rpc('eth_getCode', [to, hex(B)])) > 50 else 'eoa'
    if kind[to] == 'contract': return 'contract'
    first = [t for t in transfers(B, one_page=True, toAddress=to, order='asc', maxCount='0x5') if (t['asset'] == 'ETH' and t['category'] != 'erc20') or ((t.get('rawContract') or {}).get('address') in tracked)]
    if first and first[0]['from'] in attacker: return 'new_attacker'
    return 'external'
  ins_by = {}
  while queue:
    a = queue.pop(0)
    if a in done: continue
    done.add(a)
    ins, outs = transfers(B, toAddress=a), transfers(B, fromAddress=a)
    flows = defaultdict(lambda: {'in': 0.0, 'out': 0.0}); sent = set(); edges = []
    for t in ins + outs:
      if t['category'] == 'erc20':
        key = (t.get('rawContract') or {}).get('address')
        if not key: continue
        raw = int(t['rawContract']['value'], 16) if t['rawContract'].get('value') else 0
        v = raw / 10 ** decimals(key) if raw else (t['value'] or 0)          # (4) decimals from the contract, not Alchemy's guess
      else:
        key = 'ETH'; v = t['value'] or 0
      if v == 0: continue
      inbound = t['to'] == a; other = t['from'] if inbound else t['to']
      if inbound:
        if other in VICTIMS: cls = 'in:victim'; tracked.add(key)
        elif other in attacker: cls = 'in:attacker'
        elif a in BSEED and (other == ZERO or t['hash'].lower() in PAYOUTS): cls = 'in:bridge (' + BSEED[a] + ')'; tracked.add(key)
        elif key not in tracked: cls = 'in:spam'
        else: cls = 'in:' + ('swap_or_contract' if classify(other) in ('contract', 'dex', 'wrap', 'lending', 'bridge') else 'other')
      else:
        sent.add(t['hash'])
        if key not in tracked:
          if classify(other) in ('contract', 'dex', 'wrap', 'lending', 'bridge'): tracked.add(key)   # never lose an asset the wallet actually spent
          else: cls = 'out:untracked'
        if key in tracked:
          k2 = classify(other)
          if k2 == 'new_attacker': attacker.add(other); queue.append(other); k2 = 'attacker'
          cls = 'out:' + k2
      if inbound and key not in tracked and cls != 'in:spam': tracked.add(key)
      if (inbound and cls == 'in:spam'): continue
      flows[key]['in' if inbound else 'out'] += v
      edges.append((run_id, t['hash'], int(t['blockNum'], 16), t['from'], t['to'], key, t['asset'], v, cls, t['uniqueId']))
    c.executemany('INSERT INTO eth_edge VALUES(?,?,?,?,?,?,?,?,?,?)', edges)
    gas = 0.0
    for r in batch([('eth_getTransactionReceipt', [h]) for h in sorted(sent)]):
      if r and r['from'] == a: gas += int(r['gasUsed'], 16) * int(r.get('effectiveGasPrice', '0x0'), 16) / 1e18
    keys = [k for k in flows if k in tracked]
    toks = [k for k in keys if k != 'ETH']
    bal = {'ETH': int(rpc('eth_getBalance', [a, hex(B)]), 16) / 1e18}
    for k, r in zip(toks, batch([('eth_call', [{'to': k, 'data': '0x70a08231' + pad(a)}, hex(B)]) for k in toks])):
      bal[k] = int(r, 16) / 10 ** decimals(k) if r and r != '0x' else 0.0
    for k in keys:
      f = flows[k]; g = gas if k == 'ETH' else 0.0; b = bal.get(k, 0.0); frozen = 0
      if k != 'ETH' and b > 0:
        j = post({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'from': a, 'to': k, 'data': '0xa9059cbb' + pad('0x000000000000000000000000000000000000dEaD') + '1'.rjust(64, '0')}, hex(B)]})
        frozen = 1 if 'error' in j else 0
      sym = next((t['asset'] for t in ins + outs if ((t.get('rawContract') or {}).get('address') or 'ETH') == k), k)
      c.execute('INSERT OR REPLACE INTO eth_node VALUES(?,?,?,?,?,?,?,?,?,?,?)', (run_id, a, k, sym, f['in'], f['out'], g, b, f['in'] - f['out'] - g - b, frozen, ''))
    c.commit()
    e = flows.get('ETH', {'in': 0, 'out': 0})
    worst = max(((abs(flows[k]['in'] - flows[k]['out'] - (gas if k == 'ETH' else 0) - bal.get(k, 0)), k) for k in keys), default=(0, ''))
    print(f"[{len(done)}/{len(done)+len(queue)}] {a} | ETH in {e['in']:,.4f} out {e['out']:,.4f} gas {gas:.4f} bal {bal['ETH']:,.4f} | tokens {len(toks)} | worst resid {worst[0]:,.6f} {worst[1][:10]}", flush=True)
  c.execute('UPDATE ledger_run SET finished=?, n_nodes=? WHERE run_id=?', (time.strftime('%FT%T'), len(done), run_id)); c.commit()
  show(run_id)

def show(run_id=None):
  c = sqlite3.connect(DB, timeout=600)
  run_id = run_id or c.execute("SELECT run_id FROM ledger_run WHERE leg=? ORDER BY started DESC LIMIT 1", (CHAIN,)).fetchone()[0]
  B = json.loads(c.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0])['block']
  nodes = {r[0] for r in c.execute('SELECT DISTINCT address FROM eth_node WHERE run_id=?', (run_id,))}
  assets = [r[0] for r in c.execute("SELECT DISTINCT asset FROM eth_edge WHERE run_id=? AND cls='in:victim'", (run_id,))]
  print(f'\n=== {run_id} | block {B} | wallets {len(nodes)} ===')
  bad = []
  for k in ['ETH'] + [a for a in assets if a != 'ETH']:
    S, U = defaultdict(float), defaultdict(float)
    for f, t, v, cls in c.execute('SELECT frm, too, amount, cls FROM eth_edge WHERE run_id=? AND asset=?', (run_id, k)):
      if cls.startswith('in:') and f not in nodes: S[cls[3:]] += v
      elif cls.startswith('out:') and t not in nodes: U[cls[4:]] += v
    held, frz, gas = c.execute('SELECT SUM(CASE WHEN frozen=0 THEN bal ELSE 0 END), SUM(CASE WHEN frozen=1 THEN bal ELSE 0 END), SUM(gas) FROM eth_node WHERE run_id=? AND asset=?', (run_id, k)).fetchone()
    U['held'] += held or 0; U['frozen'] += frz or 0
    if k == 'ETH': U['gas'] += gas or 0
    s, u = sum(S.values()), sum(U.values()); d = s - u
    sym = (c.execute('SELECT symbol FROM eth_node WHERE run_id=? AND asset=? LIMIT 1', (run_id, k)).fetchone() or [k])[0]
    if k == 'ETH' or abs(d) > max(1e-6, 1e-6 * s): bad.append((sym, k, s, u, d, dict(S), dict(U)))
  for sym, k, s, u, d, S, U in bad:
    print(f'{sym:8} SOURCES {s:,.6f} USES {u:,.6f} UNEXPLAINED {d:,.6f}')
    if sym != 'ETH' or abs(d) > 0.01: print(f'      sources {{{", ".join(f"{a}: {v:,.4f}" for a, v in S.items())}}} | uses {{{", ".join(f"{a}: {v:,.4f}" for a, v in U.items())}}}')
  print(f'assets balanced: {len(assets) - (len(bad) - 1)} of {len(assets)}')

if __name__ == '__main__':
  todo = list(CHAINS) if sys.argv[2] == 'all' else [sys.argv[2]]
  for ch in todo:
    setup(ch); print(f'\n##### {ch}: {len(VICTIMS)} Binance PoR victim wallets, roots {ROOTS}', flush=True)
    try: (run if sys.argv[1] == 'run' else show)()
    except Exception as ex: print(f'!!! {ch} FAILED: {ex}', flush=True)
