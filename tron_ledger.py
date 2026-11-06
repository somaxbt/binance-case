"""Binance case, TRON leg: native-unit conservation ledger (TRX + USDT), stored in binance-live.db.
  python3 tron_ledger.py run      follow the money from the root, classify every movement, check every wallet
  python3 tron_ledger.py show     print the latest run's sources = uses table and the open lines
Rule: for every attacker wallet, IN = OUT + FEES + BALANCE, per asset, with no size cutoff. Every unit ends as
held / frozen / named endpoint (THORChain memo, Symbiosis, swap) / external wallet (lead), or as a named residual.
Every API response is kept in raw_payload."""
import json, sys, time, hashlib, sqlite3, os, urllib.request, urllib.error, gzip
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'binance-live.db')
T0 = 1793304000000                     # 2026-10-29 20:00 UTC (ms)
ROOT = 'TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi'
SOURCE = 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf'     # Binance PoR reserve wallet (victim)
USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
TG = 'https://api.trongrid.io'
# known contracts / endpoints (verified this session)
ENDPOINT = {
  'TPuaJ6gnYfE9gLUDFrbWbPx3tMnjG8max1': 'symbiosis',          # MetaRouterGateway
  'TTu9T4ff4zvNPz1dfAd36gUeB3xJgYz4G9': 'swap:bwswap',        # BWSwapRouterV1
  'TQqgNg13s2DjvXhW1ky4v6TsR8wZGvb7Y4': 'swap:sunswap-router',
  'TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx': 'swap:sunswap-wtrx-usdt',
  'TVjuTE3V5bMVdpfNhid8kD2v35T2k1u1Br': 'swap:sunswap-v4-poolmanager',
  'TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd': 'defi:justlend-jusdt',
}
VAULTS = {'THPaGKe6aZkUcNht24hcscZPLwtcJAbpun', 'TGSNahJvAdh86aR5pdcxiep1mBWSRK3HHL', 'TBAPnuwEht65McDbxDvDYs2XLRSSbYQMUM'}  # THORChain Tron vaults (memos prove it)

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB);
CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, leg TEXT, started TEXT, finished TEXT, params TEXT, n_nodes INTEGER);
CREATE TABLE IF NOT EXISTS ledger_node(run_id TEXT, address TEXT, asset TEXT, inn REAL, out REAL, fees REAL, bal REAL, resid REAL,
  n_tx INTEGER, created TEXT, frozen INTEGER, note TEXT, PRIMARY KEY(run_id, address, asset));
CREATE TABLE IF NOT EXISTS ledger_edge(run_id TEXT, hash TEXT, ts INTEGER, frm TEXT, too TEXT, asset TEXT, amount REAL, cls TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS le_run ON ledger_edge(run_id, cls);
"""
def db():
  c = sqlite3.connect(DB, timeout=600); c.execute('PRAGMA journal_mode=WAL'); c.executescript(SCHEMA); return c

B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def h2b(h):
  b = bytes.fromhex(h); b += hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]; n = int.from_bytes(b, 'big'); s = ''
  while n: n, r = divmod(n, 58); s = B58[r] + s
  return s
def b2h(a):
  n = 0
  for ch in a: n = n * 58 + B58.index(ch)
  return n.to_bytes(25, 'big')[:21].hex()

C = None
def http(u, body=None):
  waits = tries = 0
  while True:
    try:
      req = urllib.request.Request(u, json.dumps(body).encode() if body is not None else None, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
      raw = urllib.request.urlopen(req, timeout=40).read(); time.sleep(1.1)       # TronGrid keyless ~1 req/s
      C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), u + (' ' + json.dumps(body) if body else ''), gzip.compress(raw))); C.commit()
      return json.loads(raw)
    except urllib.error.HTTPError as e:
      tries += 1
      if e.code == 429 or e.code >= 500:
        if tries > 6: raise
        time.sleep(10 * tries); continue                                        # back off, never hot-loop
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:   # resets can surface mid-read, not only as URLError
      waits += 1
      if waits > 30: raise
      print(f'   network down ({getattr(e, "reason", e)}), waiting 30s [{waits}/30]', flush=True); time.sleep(30)

def pages(path):
  out, fp = [], None
  while True:
    d = http(f'{TG}{path}{"&" if "?" in path else "?"}limit=200' + (f'&fingerprint={fp}' if fp else ''))
    out += d.get('data', []); fp = d.get('meta', {}).get('fingerprint')
    if not fp or len(out) >= 20000: return out

def account(a):
  d = (http(f'{TG}/v1/accounts/{a}').get('data') or [{}])[0]
  staked = sum(f.get('amount', 0) for f in d.get('frozenV2', [])) / 1e6
  return d.get('balance', 0) / 1e6, staked, d.get('create_time'), d.get('type', 'Normal')

def const(contract, sel, a):
  d = http(f'{TG}/wallet/triggerconstantcontract', {'owner_address': 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', 'contract_address': contract,
           'function_selector': sel, 'parameter': b2h(a)[2:].rjust(64, '0'), 'visible': True})
  r = (d.get('constant_result') or [''])[0]
  return int(r[-64:], 16) if r else 0

def is_contract(a):
  return bool(http(f'{TG}/wallet/getcontract', {'value': a, 'visible': True}).get('bytecode'))

def memo_of(txid):
  t = http(f'{TG}/wallet/gettransactionbyid', {'value': txid})
  d = t.get('raw_data', {}).get('data', '')
  return bytes.fromhex(d).decode('utf8', 'ignore') if d else ''

def run():
  global C
  C = db()
  prev = C.execute("SELECT run_id FROM ledger_run WHERE leg='tron' AND finished IS NULL ORDER BY started DESC LIMIT 1").fetchone() if 'resume' in sys.argv else None
  if prev:                                             # resume: keep the run, skip finished wallets, rebuild the queue from saved edges
    run_id = prev[0]
    done = {r[0] for r in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
    attacker = {ROOT} | done | {r[0] for r in C.execute("SELECT DISTINCT too FROM ledger_edge WHERE run_id=? AND cls='out:attacker'", (run_id,))}
    # drop the half-written edges of the wallet that was in progress (in-edges are keyed by too, out/stake edges by frm)
    C.execute("""DELETE FROM ledger_edge WHERE run_id=:r AND (
                   (cls LIKE 'in:%' AND too NOT IN (SELECT address FROM ledger_node WHERE run_id=:r)) OR
                   ((cls LIKE 'out:%' OR cls LIKE 'stake:%') AND frm NOT IN (SELECT address FROM ledger_node WHERE run_id=:r)))""", {'r': run_id}); C.commit()
    queue = sorted(attacker - done); print(f'resuming {run_id}: {len(done)} wallets done, {len(queue)} queued', flush=True)
  else:
    run_id = 'tron-' + time.strftime('%Y%m%dT%H%M%S')
    C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?,?)', (run_id, 'tron', time.strftime('%FT%T'), None, json.dumps({'T0': T0, 'root': ROOT}), 0)); C.commit()
    attacker, queue, done = {ROOT}, [ROOT], set()
  ctype = {}
  def classify(to, txid=None, memo=''):
    if to in attacker: return 'attacker', ''
    if to in ENDPOINT: return ENDPOINT[to].split(':')[0], ENDPOINT[to]
    if to in VAULTS or memo.startswith(('=', 'SWAP:', 's:', 'swap:')):
      if memo == '' and txid: memo = memo_of(txid)
      VAULTS.add(to); return 'thorchain', memo
    if to not in ctype: ctype[to] = 'contract' if is_contract(to) else 'eoa'
    if ctype[to] == 'contract': return 'unknown_contract', ''
    bal, staked, created, _ = account(to)
    if created and created >= T0:                     # created after the hack and paid by an attacker wallet ⇒ attacker hop
      return 'new_attacker', ''
    return 'external', f'created {time.strftime("%F", time.gmtime((created or 0)/1000))}'
  while queue:
    a = queue.pop(0)
    if a in done: continue
    done.add(a)
    txs = pages(f'/v1/accounts/{a}/transactions?min_timestamp={T0}')
    t20 = [t for t in pages(f'/v1/accounts/{a}/transactions/trc20?min_timestamp={T0}') if t.get('type') == 'Transfer']
    node = {'TRX': defaultdict(float), 'USDT': defaultdict(float)}
    for t in txs:
      if 'internal_tx_id' in t:                         # internal TRX (e.g. swap output paid in TRX)
        v = sum(x.get('call_value', {}).get('_', 0) for x in [t.get('data', {})]) / 1e6
        frm, to = h2b(t['from_address']) if len(t['from_address']) == 42 else t['from_address'], h2b(t['to_address']) if len(t['to_address']) == 42 else t['to_address']
        if v <= 0: continue
        if to == a: node['TRX']['in'] += v; C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['tx_id'], t['block_timestamp'], frm, a, 'TRX', v, 'in:internal', ''))
        elif frm == a: node['TRX']['out'] += v; C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['tx_id'], t['block_timestamp'], a, to, 'TRX', v, 'out:internal', ''))
        continue
      c = t['raw_data']['contract'][0]; p = c['parameter']['value']; owner = h2b(p['owner_address'])
      memo = bytes.fromhex(t['raw_data'].get('data', '')).decode('utf8', 'ignore') if t['raw_data'].get('data') else ''
      if owner == a:
        node['TRX']['fees'] += sum(r.get('fee', 0) for r in t.get('ret', [])) / 1e6
      if c['type'] == 'TransferContract':
        v = p['amount'] / 1e6; to = h2b(p['to_address'])
        if to == a and owner != a:
          node['TRX']['in'] += v; cls = 'in:root' if owner == SOURCE else ('in:attacker' if owner in attacker else ('in:dust' if v < 1 else 'in:foreign'))
          C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['txID'], t['block_timestamp'], owner, a, 'TRX', v, cls, memo))
        elif owner == a:
          node['TRX']['out'] += v; cls, det = classify(to, t['txID'], memo)
          if cls == 'new_attacker': attacker.add(to); queue.append(to); cls = 'attacker'
          C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out:' + cls, det or memo))
      elif c['type'] == 'TriggerSmartContract' and owner == a:
        v = p.get('call_value', 0) / 1e6; to = h2b(p['contract_address'])
        if to != USDT:                                   # swap/bridge calls can pay TRX back via internal txs, which the account list omits
          info = http(f'{TG}/wallet/gettransactioninfobyid', {'value': t['txID']})
          for it in info.get('internal_transactions', []):
            iv = sum(x.get('callValue', 0) for x in it.get('callValueInfo', []) if not x.get('tokenId')) / 1e6
            if iv > 0 and h2b(it['transferTo_address']) == a:
              node['TRX']['in'] += iv
              C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['txID'], t['block_timestamp'], h2b(it['caller_address']), a, 'TRX', iv, 'in:swap_proceeds', ENDPOINT.get(to, to)))
        if v > 0:
          node['TRX']['out'] += v; cls, det = classify(to, t['txID'], memo)
          C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out:' + cls, det or memo))
      elif owner == a and c['type'] in ('FreezeBalanceV2Contract', 'DelegateResourceContract', 'UnfreezeBalanceV2Contract'):
        C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['txID'], t['block_timestamp'], a, a, 'TRX', p.get('frozen_balance', p.get('balance', p.get('unfreeze_balance', 0))) / 1e6, 'stake:' + c['type'], ''))
    for t in t20:
      if t['token_info']['address'] != USDT: continue                    # symbol is forgeable, contract is not
      v = int(t['value']) / 1e6
      if t['to'] == a and t['from'] != a:
        node['USDT']['in'] += v; cls = 'in:root' if t['from'] == SOURCE else ('in:attacker' if t['from'] in attacker else 'in:foreign')
        C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['transaction_id'], t['block_timestamp'], t['from'], a, 'USDT', v, cls, ''))
      elif t['from'] == a:
        node['USDT']['out'] += v; cls, det = classify(t['to'], t['transaction_id'])
        if cls == 'new_attacker': attacker.add(t['to']); queue.append(t['to']); cls = 'attacker'
        C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, t['transaction_id'], t['block_timestamp'], a, t['to'], 'USDT', v, 'out:' + cls, det))
    bal, staked, created, _ = account(a)
    ub = const(USDT, 'balanceOf(address)', a) / 1e6; frozen = const(USDT, 'isBlackListed(address)', a)
    for asset, b in (('TRX', bal + staked), ('USDT', ub)):
      n = node[asset]; resid = n['in'] - n['out'] - n['fees'] - b
      C.execute('INSERT OR REPLACE INTO ledger_node VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (run_id, a, asset, n['in'], n['out'], n['fees'], b, resid, len(txs) + len(t20),
                time.strftime('%F %T', time.gmtime((created or 0) / 1000)), frozen, f'staked {staked}' if staked else ''))
    C.commit()
    print(f"[{len(done)}/{len(done)+len(queue)}] {a} TRX in {node['TRX']['in']:,.0f} out {node['TRX']['out']:,.0f} bal {bal+staked:,.0f} | USDT in {node['USDT']['in']:,.0f} out {node['USDT']['out']:,.0f} bal {ub:,.0f}{' FROZEN' if frozen else ''}", flush=True)
  C.execute('UPDATE ledger_run SET finished=?, n_nodes=? WHERE run_id=?', (time.strftime('%FT%T'), len(done), run_id)); C.commit()
  show(run_id)

def show(run_id=None):
  c = db()
  run_id = run_id or c.execute("SELECT run_id FROM ledger_run WHERE leg='tron' ORDER BY started DESC LIMIT 1").fetchone()[0]
  print(f'\n=== {run_id} ===')
  for asset in ('TRX', 'USDT'):
    src = c.execute("SELECT cls, SUM(amount) FROM ledger_edge WHERE run_id=? AND asset=? AND cls LIKE 'in:%' AND cls!='in:attacker' GROUP BY cls", (run_id, asset)).fetchall()
    use = c.execute("SELECT cls, SUM(amount) FROM ledger_edge WHERE run_id=? AND asset=? AND cls LIKE 'out:%' AND cls!='out:attacker' GROUP BY cls", (run_id, asset)).fetchall()
    held = c.execute("SELECT SUM(bal) FROM ledger_node WHERE run_id=? AND asset=? AND frozen=0", (run_id, asset)).fetchone()[0] or 0
    frz = c.execute("SELECT SUM(bal) FROM ledger_node WHERE run_id=? AND asset=? AND frozen=1", (run_id, asset)).fetchone()[0] or 0
    fees = c.execute("SELECT SUM(fees) FROM ledger_node WHERE run_id=? AND asset=?", (run_id, asset)).fetchone()[0] or 0
    resid = c.execute("SELECT SUM(resid) FROM ledger_node WHERE run_id=? AND asset=?", (run_id, asset)).fetchone()[0] or 0
    S = sum(v for _, v in src); U = sum(v for _, v in use) + held + frz + fees
    print(f'\n{asset}  SOURCES {S:,.6f}'); [print(f'   {k:28} {v:>22,.6f}') for k, v in src]
    print(f'{asset}  USES    {U:,.6f}'); [print(f'   {k:28} {v:>22,.6f}') for k, v in use]
    print(f'   {"held (attacker wallets)":28} {held:>22,.6f}\n   {"frozen":28} {frz:>22,.6f}\n   {"fees burned":28} {fees:>22,.6f}')
    print(f'   UNEXPLAINED (sources-uses) {S-U:>22,.6f}   | per-wallet residual sum {resid:,.6f}')
  print('\nopen per-wallet residuals (|resid| > 0.01):')
  for r in c.execute("SELECT address, asset, inn, out, fees, bal, resid FROM ledger_node WHERE run_id=? AND ABS(resid)>0.01 ORDER BY ABS(resid) DESC LIMIT 25", (run_id,)):
    print('  ', r)
  print('\nTHORChain memo destinations:')
  for r in c.execute("SELECT asset, detail, COUNT(*), SUM(amount) FROM ledger_edge WHERE run_id=? AND cls='out:thorchain' GROUP BY asset, detail ORDER BY 4 DESC", (run_id,)): print('  ', r)
  print('\nexternal wallets (leads) and unknown contracts:')
  for r in c.execute("SELECT cls, too, asset, SUM(amount), COUNT(*), MAX(detail) FROM ledger_edge WHERE run_id=? AND cls IN ('out:external','out:unknown_contract') GROUP BY cls, too, asset ORDER BY 4 DESC LIMIT 30", (run_id,)): print('  ', r)

if __name__ == '__main__':
  {'run': run, 'show': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None)}[sys.argv[1]]()
