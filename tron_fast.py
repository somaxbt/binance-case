"""Binance case, TRON — fast incremental ledger: seeds only, wallets in parallel, both API keys.
  python3 tron_fast.py BASE_RUN RECHECK_JSON [--limit N]      --limit = test run, stops after N wallets (run marked TEST)
Opening = BASE closing; cutoff = the recheck's check time, so every base wallet the recheck saw unchanged (and not
sending) is CARRIED forward with zero calls. Only the flagged wallets (+ new wallets they fund) are read.
Join rule: a new wallet joins only if it is an EOA created after the hack whose FIRST funder is an attacker wallet;
a wallet whose outside inflow exceeds its attacker inflow is booked but NOT followed (its fresh payees become leads).
TronGrid (8/s): tx + trc20 history, receipts, first-funder. Tronscan (3/s, bursts get 429): account profile.
Writes a normal 'tron2-…' run (params base/from/cutoff) so `tron_ledger2.py show` and `tron_report.py` work on it."""
import json, sys, time, calendar, sqlite3, gzip, threading, urllib.request, urllib.error, os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
import tron_ledger as v1
from tron_ledger import h2b, b2h, SOURCE, USDT, TG, ENDPOINT, VAULTS, T0, DB
from tron_ledger2 import opening_of, show

def tronscan_internal_in(a, hi, lo):
  """internal TRX transfers INTO a (from contracts, in other parties' txs), in [lo, hi] — Tronscan, paced by its gate"""
  out, start = [], 0
  while True:
    rows = get(f'{TS}/api/internal-transaction?address={a}&start={start}&limit=50', ts=True).get('data', []) or []
    for x in rows:
      ts, tok = x.get('timestamp', 0), x.get('tokenInfo') or {}
      if lo <= ts <= hi and x.get('to') == a and tok.get('tokenId') in (None, '_') and not x.get('rejected', False):
        v = float(x.get('call_value', x.get('value', 0)) or 0) / 1e6
        if v > 0: out.append((x.get('hash'), ts, x.get('from'), v))
    start += 50
    if len(rows) < 50 or start > 1000: return out

ENVF = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
TGH = {'TRON-PRO-API-KEY': ENVF['TRONGRID_API_KEY'], 'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}
TSH = {'TRON-PRO-API-KEY': ENVF['TRONSCAN_API_KEY'], 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://tronscan.org/'}
TS = 'https://apilist.tronscanapi.com'
WORKERS = 8
EXTRA = {'TGPwgFpJcJHQUDWScySg9gkvB7EXs54rbd': 'swap:usdt-trx-router (unverified, via SunSwap pool)',
         'TEcDijvKSXcfWT7S6rd44H5vNgufm7Y4XC': 'bridge:chainflip-vault (user-identified 10-31)',
         'TZG47zhb8kcriWQ2rE719yHs1KqgzwMrvF': 'bridge:bitget-wallet-swap-bridge (user-identified 10-31)',
         'TKfz7Pu3jtxWrfHzVeozQjXsb3RfuUHGE2': 'service:changehero-hot-wallet (user-identified 10-31)',
         'TFGDbUyP8xez44C76fin3bn3Ss6jugoUwJ': 'swap:sunswap-v1 S-USDT-TRX pool',
         'TKWqpzNucNNBMpfaE47F8CLhA8vzfNndH4': 'bridge:meson', 'TX2Ut1reF59i2WPzsYVoMfA25EkUkavnd5': 'bridge:debridge-dln',
         'TTRmy12BMrWt68drXQfn3YpC8B5TVFuyyW': 'bridge:hyperlane-warp', 'TZ9grqg3LwBKiddGra3WGHPdddJz3tow8N': 'bridge:wanchain-crossproxy',
         'TWPziSAroSacAjDuL52ByQzU86s9mP2gPr': 'bridge:layerzero-oftbridge', 'TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt': 'bridge:usdt0-layerzero',
         'TSVLdWvSWK2z8uQ1P1kwGvNLvLvwNRb15Y': 'bridge:bridgers', 'TRmmbf5ubQvHnMsazNKPEoJyj9acBP6KbY': 'bridge:bridgers',
         'TGKCgwjZo3QajwUASFHVWusJyZy7ESiMBZ': 'bridge:bridgers', 'TXejU9jmd1ooQyY3Zmpo15yN7MjSFYUESg': 'defi:justlend-jusdtv2',
         'TGnC7LMji8hBpyvZt1TTEJhVpAZ5HFyJ3r': 'swap:sunswap-smart-router (old)',
         'TRsqznGXF7mSYhRxU49L3HY13QW1v9yBZa': 'swap:aggregator (-> TTWd2hBK -> WTRX -> SunSwap pool TSUUVjys; tx-verified 11-01)',
         'TDJ5TQBsWVzRneXbgz1KDVdo4WQbArfR6M': 'bridge:chainflip-channel (deployed by Chainflip vault TEcDij)',
         'TCpsYi5Pqdmt1RmRZE6JkXLASgEZaZDP3e': 'service:unidentified S2 (hub TWBUvUJm -> TBA6CypY)',
         'TJbZXZR9Hru126DiYevDiwVeP1sGoigvU9': 'exchange:hitbtc-hot-wallet (user-identified 11-01)',
         'TD64NDwZfQB6UASW2Xz6hWrz1T12p1pxL7': 'exchange:hitbtc-deposit of a SERVICE account (shared, 150-300 other senders; likely instant exchange) (user-identified 11-01)',
         'TRLWnRCwWyJ76WdwNKvawVq3x6k2Y4EuEg': 'exchange:hitbtc-deposit of a SERVICE account (shared, 150-300 other senders; likely instant exchange) (user-identified 11-01)',
         'TAvk2T3bybK8W12iuHyWfwfJzPjWhabbuC': 'exchange:hitbtc-deposit of a SERVICE account (shared, 150-300 other senders; likely instant exchange) (user-identified 11-01)',
         'TBtfrdjXumsQ9Kxm2Zbvvu14ER16regLxX': 'exchange:hitbtc-deposit of a SERVICE account (shared, 150-300 other senders; likely instant exchange) (user-identified 11-01)',
         'TSc4Bc4CNuDJZYwzgZhueqXbmyT89xCYqD': 'exchange:hitbtc-deposit of a SERVICE account (shared, 150-300 other senders; likely instant exchange) (inferred: same pattern, sweeps to HitBTC hot wallet)',
         'TWBUvUJmkLDQdreRArnFkm9yVMkgQH9aXh': 'exchange:gate-deposit of a SERVICE account (shared, $27M from other senders; OTC/instant exchange) (user-identified 11-01)',
         'TX5XiRXdyz7sdFwF5mnhT1QoGCpbkncpke': 'bridge:near-intents-hot-wallet (user-identified 11-01)',
         'TDoXUNZ6PajKuiUkcYg3EDSV9bnqGqsbcf': 'exchange:fixedfloat-hot-wallet (user-identified 11-01)',
         'TCPPRajgXVBkR5Qvpd3RHh4xUvibhzrqSa': 'service:unidentified (probably a service — user 11-01)',
         'TB6QHSqmof2ssxoKkWwabTbvDbCxydZ23a': 'bridge:across-v5 (Tron_PrefundedAdapter)',
         'TANdmAmc5jyNEFB1gXbEBfaG7Ftj1XNUG1': 'bridge:across-v5 (Tron_Executor)',
         'TSUYvQ5tdd3DijCD1uGunGLpftHuSZ12sQ': 'defi:usdd-psm (USDT->USDD)',
         'TE2RzoSV3wFK99w6J9UnnZ4vLfXYoxvRwP': 'defi:justlend-jtrx',
         'TS7JGXEiLfMUrRB9xRXuRSR6JdrPEHj7ph': 'bridge:bridgers',
         'TVb1VKz7ca5RRDTqGssxACqL4HSg3H959y': 'bridge:bridgers',
         'TSHvXqsFUyFAinV9akM36ygtPnqskCin6h': 'bridge:bridgers',
         'THDghuD2M8ZSCZGLEufGMXaB13D4zeCfxu': 'bridge:bridgers',
         'TKFB2tZZS7bD5adq6sP8QJZf5AJ1zC7C2d': 'bridge:bridgers',
         'TMviNfNmwfefUXdhGQaDzbo5NiEVTZTqHM': 'swap:symbiosis-onchain-gateway (same-chain swap on Tron)',
         'TXtEs6t2oUWQsNos7m68gbHdE9Q5n6x2oN': 'bridge:relay-depository (RelayDepository; resolve via relay_resolve.py)',
         'TMDENHFSiRzmJNSEBAFmrDbLkQ672iPN8H': 'defi:justlend-trx-vault (TrxProviderProxy -> jTRXv2 THpxp8Rp; redeem pays a chosen receiver)'}
EP = {**ENDPOINT, **EXTRA}
VAULTS |= {'TH1YKH9MUuJtDmekPia4x9fZXAcpPrMv8B', 'TLKfB2goHRY1SykEpVbiGdsesACrkCxCeW'}   # THORChain vaults seen via memos 10-30

class Gate:
  def __init__(s, qps): s.dt, s.lock, s.last, s.n, s.waiting = 1 / qps, threading.Lock(), 0.0, 0, 0
  def backlog(s): return (s.waiting + 1) * s.dt          # expected wait for a new caller (seconds)
  def wait(s):
    s.waiting += 1
    with s.lock:
      w = s.last + s.dt - time.time()
      if w > 0: time.sleep(w)
      s.last = time.time(); s.n += 1
    s.waiting -= 1
GTG, GTS = Gate(8), Gate(3)
C = sqlite3.connect(DB, timeout=600, check_same_thread=False); C.execute('PRAGMA journal_mode=WAL'); C.executescript(v1.SCHEMA)
DBL = threading.Lock()
# raw API responses are saved from worker threads on their OWN connection: sharing C with the main thread's ledger writes
# raised 'cannot start a transaction within a transaction' (10-31 run, wallet TM9Mcv49 lost). WAL + busy timeout serialises the two writers.
# 10-31 eve: RAW on the SAME file deadlocked — the main thread calls the API while its ledger txn is open, so the RAW insert waited
# on that txn while holding DBL. Raw payloads now go to their own file; nothing else reads them from binance-live.db.
RAW = sqlite3.connect(DB.replace('.db', '-raw.db'), timeout=600, check_same_thread=False)
RAW.execute('CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB)'); RAW.commit()

def get(url, body=None, ts=False):
  gate, h = (GTS, TSH) if ts else (GTG, TGH)
  for i in range(8):
    gate.wait()
    try:
      raw = urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, h), timeout=40).read()
      with DBL: RAW.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), url + (' ' + json.dumps(body) if body else ''), gzip.compress(raw))); RAW.commit()
      return json.loads(raw)
    except urllib.error.HTTPError as e:
      if e.code == 429 or e.code >= 500: time.sleep((6 if ts else 2) * (i + 1)); continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(5 * (i + 1))
  raise RuntimeError(f'gave up: {url}')

def pages(path, lo, hi):
  out, fp = [], None
  while True:
    d = get(f'{TG}{path}{"&" if "?" in path else "?"}limit=200&min_timestamp={lo}&max_timestamp={hi}' + (f'&fingerprint={fp}' if fp else ''))
    out += d.get('data', []); fp = d.get('meta', {}).get('fingerprint')
    if not fp or len(out) >= 20000: return out

_prof, _ff, _cl, BASE = {}, {}, threading.Lock(), set()
def profile(a):
  """one call, from whichever key has the shorter queue: live TRX (incl. staked), USDT, contract?, name/tag, created, last op.
  Tronscan accountv2 (also tags + tx count) or TronGrid /v1/accounts (same facts, no tags)."""
  with _cl:
    if a in _prof: return _prof[a]
  if GTS.backlog() <= GTG.backlog():
    d = get(f'{TS}/api/accountv2?address={a}', ts=True)
    usdt = sum(int(x.get('balance') or 0) for x in d.get('withPriceTokens', []) if x.get('tokenId') == USDT) / 1e6
    p = {'trx': ((d.get('balance') or 0) + (d.get('totalFrozenV2') or 0)) / 1e6, 'usdt': usdt, 'contract': d.get('accountType') == 2,
         'name': d.get('name') or d.get('publicTag') or (d.get('addressTag') or ''), 'created': d.get('date_created') or 0,
         'last_op': d.get('latest_operation_time') or 0, 'ntx': d.get('totalTransactionCount') or 0}
  else:
    d = (get(f'{TG}/v1/accounts/{a}').get('data') or [{}])[0]
    nm = d.get('account_name') or ''
    try: nm = bytes.fromhex(nm).decode('utf8', 'ignore')
    except ValueError: pass
    p = {'trx': (d.get('balance', 0) + sum(f.get('amount', 0) for f in d.get('frozenV2', []))) / 1e6,
         'usdt': sum(int(v) for t in d.get('trc20', []) for k, v in t.items() if k == USDT) / 1e6, 'contract': d.get('type') == 'Contract',
         'name': nm, 'created': d.get('create_time') or 0, 'last_op': d.get('latest_opration_time') or 0, 'ntx': None}
  with _cl: _prof[a] = p
  return p
def first_funder(a):
  """sender of the first VALUE inflow (>= 10 TRX or >= 1 USDT). Tron accounts are usually activated by a tiny payment
  from an energy/gas service; counting that as the funder booked real launderer wallets as 'external' (10-31 run)."""
  with _cl:
    if a in _ff: return _ff[a]
  best = None
  for t in get(f'{TG}/v1/accounts/{a}/transactions?only_to=true&order_by=block_timestamp,asc&limit=50').get('data', []):
    if 'raw_data' not in t: continue
    c = t['raw_data']['contract'][0]
    if c['type'] == 'TransferContract' and c['parameter']['value']['amount'] >= 10e6:
      best = (t['block_timestamp'], h2b(c['parameter']['value']['owner_address'])); break
  for t in get(f'{TG}/v1/accounts/{a}/transactions/trc20?only_to=true&order_by=block_timestamp,asc&limit=50').get('data', []):
    if t.get('type') == 'Transfer' and t['token_info']['address'] == USDT and int(t['value']) >= 1e6:
      if best is None or t['block_timestamp'] < best[0]: best = (t['block_timestamp'], t['from'])
      break
  f = best[1] if best else None
  with _cl: _ff[a] = f
  return f

_share = {}
def tree_share(a, tree):
  """share of a's value inflow (TRX >= 10, USDT >= 1, first 200 of each) that is tree money or THORChain refunds (own value).
  Catches launderer wallets whose first funder is a sibling branch we have not seen yet."""
  if a in _share: return _share[a]
  own = tot = 0.0
  for t in get(f'{TG}/v1/accounts/{a}/transactions?only_to=true&limit=200&order_by=block_timestamp,asc').get('data', []):
    if 'raw_data' not in t: continue
    c = t['raw_data']['contract'][0]; p = c['parameter']['value']
    if c['type'] == 'TransferContract' and p['amount'] >= 10e6:
      v = p['amount'] / 1e6; tot += v; f = h2b(p['owner_address'])
      if f in tree or f in VAULTS: own += v
  for t in get(f'{TG}/v1/accounts/{a}/transactions/trc20?only_to=true&limit=200&order_by=block_timestamp,asc').get('data', []):
    if t.get('type') == 'Transfer' and t['token_info']['address'] == USDT and int(t['value']) >= 1e6:
      v = int(t['value']) / 1e6 * 3; tot += v                     # USDT weighted ~3 TRX for a common scale (display only)
      if t['from'] in tree or t['from'] in VAULTS: own += v
  _share[a] = own / tot if tot else 0.0
  return _share[a]
def joins(a, tree):
  return first_funder(a) in tree or tree_share(a, tree) >= 0.5

PENDING = defaultdict(list)     # receiver -> [(hash, ts, payer, TRX)] for contract redirects
IO = ThreadPoolExecutor(16)      # per-wallet sub-calls (receipts, destination profiles) run here, so one busy wallet isn't serial
def read_wallet(a, lo, hi):
  """worker: everything about wallet a in (lo, hi] — raw movements, receipts, live profile, destination profiles"""
  txs = pages(f'/v1/accounts/{a}/transactions', lo, hi)
  t20 = [t for t in pages(f'/v1/accounts/{a}/transactions/trc20', lo, hi) if t.get('type') == 'Transfer' and (t.get('token_info') or {}).get('address') == USDT]   # spam tokens can lack token_info.address
  need = [t['txID'] for t in txs if 'raw_data' in t and t['raw_data']['contract'][0]['type'] == 'TriggerSmartContract'
          and h2b(t['raw_data']['contract'][0]['parameter']['value']['owner_address']) == a
          and h2b(t['raw_data']['contract'][0]['parameter']['value'].get('contract_address', '41' + '0' * 40)) != USDT]
  infos = dict(zip(need, IO.map(lambda h: get(f'{TG}/wallet/gettransactioninfobyid', {'value': h}), need)))
  mv, dests = [], set()           # mv: (hash, ts, frm, to, asset, amount, kind, memo)
  for t in txs:
    if 'raw_data' not in t: continue
    c = t['raw_data']['contract'][0]; p = c['parameter']['value']; owner = h2b(p['owner_address'])
    memo = bytes.fromhex(t['raw_data'].get('data', '')).decode('utf8', 'ignore') if t['raw_data'].get('data') else ''
    if owner == a:
      fee = sum(r.get('fee', 0) for r in t.get('ret', [])) / 1e6
      if fee: mv.append((t['txID'], t['block_timestamp'], a, a, 'TRX', fee, 'fee', ''))
    if (t.get('ret') or [{}])[0].get('contractRet', 'SUCCESS') != 'SUCCESS': continue   # failed: fee only
    if c['type'] == 'TransferContract':
      v, to = p['amount'] / 1e6, h2b(p['to_address'])
      if to == a and owner != a: mv.append((t['txID'], t['block_timestamp'], owner, a, 'TRX', v, 'in', memo))
      elif owner == a: mv.append((t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out', memo)); dests.add(to)
    elif c['type'] == 'TriggerSmartContract' and owner == a:
      v, to = p.get('call_value', 0) / 1e6, h2b(p['contract_address'])
      if to != USDT:
        info = infos[t['txID']]
        for it in info.get('internal_transactions', []):
          iv = sum(x.get('callValue', 0) for x in it.get('callValueInfo', []) if not x.get('tokenId')) / 1e6
          if iv > 0 and h2b(it['transferTo_address']) == a:
            mv.append((t['txID'], t['block_timestamp'], h2b(it['caller_address']), a, 'TRX', iv, 'proceeds', EP.get(to, to)))
          elif iv > 0 and h2b(it['caller_address']) == to and h2b(it['transferTo_address']) not in EP and h2b(it['transferTo_address']) not in VAULTS:
            r = h2b(it['transferTo_address'])      # the called contract paid a THIRD address in a's tx (e.g. vault redeem to a receiver)
            mv.append((t['txID'], t['block_timestamp'], to, r, 'TRX', iv, 'redirect', EP.get(to, to))); dests.add(r)   # frm = paying contract
      if v > 0: mv.append((t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out', memo)); dests.add(to)
      for lg in info.get('log', []) if to != USDT else []:                       # TRC20 swap output paid to a THIRD address (swap 'recipient' param)
        tp = lg.get('topics') or []
        if len(tp) == 3 and tp[0].startswith('ddf252ad') and h2b('41' + lg.get('address', '')[-40:]) == USDT:
          r = h2b('41' + tp[2][-40:])
          if r != a and r not in EP and r not in VAULTS and h2b('41' + tp[1][-40:]) != a:
            mv.append((t['txID'], t['block_timestamp'], to, r, 'USDT', int(lg['data'], 16) / 1e6, 'redirect_usdt', EP.get(to, to))); dests.add(r)
  for t in t20:
    v = int(t['value']) / 1e6
    if t['to'] == a and t['from'] != a: mv.append((t['transaction_id'], t['block_timestamp'], t['from'], a, 'USDT', v, 'in', ''))
    elif t['from'] == a:
      memo = ''
      if t['to'] in VAULTS:
        r = get(f'{TG}/wallet/gettransactionbyid', {'value': t['transaction_id']}); d = r.get('raw_data', {}).get('data', '')
        memo = bytes.fromhex(d).decode('utf8', 'ignore') if d else ''
      mv.append((t['transaction_id'], t['block_timestamp'], a, t['to'], 'USDT', v, 'out', memo)); dests.add(t['to'])
  live = profile(a)
  def resolve(d):                                  # pre-resolve destinations (parallel); classification stays in main thread
    pr = profile(d)
    if not pr['contract'] and pr['created'] >= T0: first_funder(d)
  list(IO.map(resolve, [d for d in dests if d not in EP and d not in VAULTS and d not in BASE]))
  return a, mv, live, len(txs) + len(t20)

def main():
  limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
  if sys.argv[1] == '--repair': return repair(sys.argv[2])
  if sys.argv[1] == '--add': return add(sys.argv[2], sys.argv[3:])
  base, rj = sys.argv[1], json.load(open(sys.argv[2]))
  opening, lo = opening_of(C, base); lo += 1
  hi = int(calendar.timegm(time.strptime(rj['checked_utc'], '%Y-%m-%d %H:%M:%S')) * 1000)
  if os.environ.get('TRON_CUTOFF'):              # 11-05: common cutoff in the PAST (UTC 'YYYY-MM-DDTHH:MM:SSZ'); recheck flags are a superset of the moves up to it
    c = int(calendar.timegm(time.strptime(os.environ['TRON_CUTOFF'], '%Y-%m-%dT%H:%M:%SZ')) * 1000)
    assert lo <= c <= hi, f'TRON_CUTOFF must be between the base cutoff and the recheck time'; hi = c
  checked = {w['address'] for w in rj['wallets']}
  base_w = {a for a, _ in opening}; BASE.update(base_w); frozen0 = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=? AND frozen=1', (base,))}
  # seeds = flagged by the recheck + any base wallet the recheck never saw (e.g. added later by --repair)
  seeds = {w['address'] for w in rj['wallets'] if abs(w['trx_diff']) > 1 or abs(w['usdt_diff']) > 1 or w['sent_after_cutoff']} | (base_w - checked)
  run_id = ('test-' if limit else 'tron2-') + time.strftime('%Y%m%dT%H%M%S')
  C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?,?)', (run_id, 'test' if limit else 'tron2', time.strftime('%FT%T'), None,
            json.dumps({'T0': T0, 'cutoff': hi, 'base': base, 'from': lo, 'tool': 'tron_fast', 'seeds': len(seeds)}), 0)); C.commit()
  print(f'{run_id}: window {time.strftime("%F %T", time.gmtime(lo/1000))} -> {time.strftime("%F %T", time.gmtime(hi/1000))} UTC | '
        f'{len(base_w)} base wallets: {len(seeds)} seeds, {len(base_w - seeds)} carried | {WORKERS} workers', flush=True)
  for a in sorted(base_w - seeds):                 # carry forward, zero calls (recheck proved no change up to hi)
    for asset in ('TRX', 'USDT'): node(run_id, a, asset, 0, 0, 0, opening.get((a, asset), 0.0), 0.0, 0, '', 1 if a in frozen0 else 0, 'carried (recheck: unchanged, no send)')
  C.commit()
  n_done, stopped = follow(run_id, lo, hi, opening, set(base_w), set(), frozen0, base_w, sorted(seeds)[:limit], limit)
  C.execute('UPDATE ledger_run SET finished=?, n_nodes=? WHERE run_id=?', (time.strftime('%FT%T') if not limit else 'TEST (limit)', n_done + len(base_w - seeds), run_id)); C.commit()
  print(f'=== {run_id} done: {n_done} wallets read, {len(stopped)} stopped as outside-majority ===', flush=True)
  if not limit: show(run_id); graph()

def repair(run_id):
  """re-test a finished run's 'external' fresh EOAs with the corrected first-funder rule; those that pass become attacker
  wallets of THAT run (edges relabelled) and are followed inside the run's own window, so its book is corrected in place."""
  P = json.loads(C.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0])
  lo, hi = P.get('from', T0), P['cutoff']; opening = opening_of(C, P['base'])[0] if P.get('base') else {}   # first run (tron_ledger2) has no 'from': hack start
  base_w = {a for a, _ in opening}; BASE.update(base_w)
  nodes = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
  frozen0 = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=? AND frozen=1', (run_id,))}
  ext = sorted({t for (t,) in C.execute("SELECT DISTINCT too FROM ledger_edge WHERE run_id=? AND cls='out:external'", (run_id,))} - nodes)
  def test(t):
    pr = profile(t)
    return (t, pr['created']) if (not pr['contract'] and pr['created'] >= T0 and joins(t, nodes)) else None
  hits = [r for r in IO.map(test, ext) if r]
  fix = [t for t, cr in hits if cr >= lo]          # created inside this window => opening 0 is exact
  older = [t for t, cr in hits if cr < lo]         # existed before the window: their earlier history is in an earlier run
  print(f'repair {run_id}: {len(ext)} external destinations, {len(hits)} pass the corrected join rule '
        f'({len(fix)} fixed here, {len(older)} created before this window -> need the earlier run repaired: {older[:10]})', flush=True)
  for t in fix: C.execute("UPDATE ledger_edge SET cls='out:attacker', detail='repaired 10-31: first VALUE funder is attacker' WHERE run_id=? AND too=? AND cls='out:external'", (run_id, t))
  C.commit()
  n_done, stopped = follow(run_id, lo, hi, opening, set(nodes) | set(fix), set(nodes), frozen0, base_w, fix, None)
  # any other 'external' edge that points at a wallet now in the tree is internal, not an exit (else it is counted twice)
  r = C.execute("""UPDATE ledger_edge SET cls='out:attacker', detail='repaired 10-31: receiver is a tree wallet' WHERE run_id=:r AND cls='out:external'
                   AND too IN (SELECT address FROM ledger_node WHERE run_id=:r)""", {'r': run_id}).rowcount
  C.execute("UPDATE ledger_run SET n_nodes=n_nodes+?, params=json_set(params,'$.repaired',?) WHERE run_id=?", (n_done, time.strftime('%FT%T'), run_id)); C.commit()
  print(f'   relabelled {r} more external edges that point into the tree', flush=True)
  print(f'=== repair {run_id}: {n_done} wallets added, {len(stopped)} stopped ===', flush=True); show(run_id); graph()

def graph():
  try:
    import tron_graph; print('graph: wrote %s | %d wallets, %d links, %d exit links' % tron_graph.build(), flush=True)
    import incident_graph; print('incident page: wrote %s' % incident_graph.build()[0], flush=True)
  except Exception as e: print(f'graph: FAILED {e}', flush=True)

def add(run_id, addrs):
  """(re)process given wallets inside an existing run's window (e.g. one lost to an error); its edges are replaced"""
  P = json.loads(C.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0])
  lo, hi = P.get('from', T0), P['cutoff']; opening = opening_of(C, P['base'])[0] if P.get('base') else {}   # first run (tron_ledger2) has no 'from': hack start
  base_w = {a for a, _ in opening}; BASE.update(base_w)
  nodes = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
  frozen0 = {a for (a,) in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=? AND frozen=1', (run_id,))}
  for h, ts, fr, to, v in C.execute("SELECT hash, ts, frm, too, amount FROM ledger_edge WHERE run_id=? AND cls='out:attacker' AND detail LIKE 'redirect via%'", (run_id,)).fetchall():
    if to in addrs and fr not in addrs: PENDING[to].append((h, ts, fr, v))   # redirects booked by payers we are NOT re-reading
  for a in addrs:                                  # drop whatever this wallet booked itself; senders' rows stay
    C.execute("DELETE FROM ledger_edge WHERE run_id=? AND ((frm=? AND (cls LIKE 'out:%' OR cls='fee')) OR (too=? AND cls LIKE 'in:%'))", (run_id, a, a))
    C.execute('DELETE FROM ledger_node WHERE run_id=? AND address=?', (run_id, a))
  C.commit()
  n_done, _ = follow(run_id, lo, hi, opening, nodes | set(addrs), nodes - set(addrs), frozen0, base_w, list(addrs), None)
  print(f'=== add {run_id}: {n_done} wallets (re)processed ===', flush=True); show(run_id); graph()

def node(run_id, a, asset, i, o, f, b, chk, ntx, cr, fz, note):
  C.execute('INSERT OR REPLACE INTO ledger_node VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (run_id, a, asset, i, o, f, b, chk, ntx, cr, fz, note))

def follow(run_id, lo, hi, opening, attacker, done, frozen0, base_w, start, limit):
  """read the start wallets in parallel, book every movement, and follow new attacker wallets until the tree closes"""
  E = lambda *r: C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, *r))
  NODE = lambda *r: node(run_id, *r)
  stopped = set(); t0 = time.time(); n_done = 0
  with ThreadPoolExecutor(WORKERS) as ex:
    fut = {ex.submit(read_wallet, a, lo, hi): a for a in start}
    while fut:
      fin, _ = wait(fut, return_when=FIRST_COMPLETED)
      for f in fin:
        a = fut.pop(f)
        try: a, mv, live, ntx = f.result()
        except Exception as e: print(f'  ERROR {a}: {e}', flush=True); continue
        done.add(a); n_done += 1
        mv += [(h, ts, fr, a, 'TRX', v, 'in', 'redirect') for h, ts, fr, v in PENDING.pop(a, [])]   # TRX paid to a by a contract in a tree wallet's tx
        n = {'TRX': defaultdict(float), 'USDT': defaultdict(float)}
        att_in = sum(v for h, ts, fr, to, s, v, k, m in mv if k == 'in' and fr in attacker and v >= 1)
        out_in = sum(v for h, ts, fr, to, s, v, k, m in mv if k == 'in' and fr not in attacker and fr not in VAULTS and fr not in EP and v >= 1)
        own_tx = {h for h, ts, fr, to, s, v, k, m in mv if k == 'out' and (to in EP or to in VAULTS or profile(to)['contract'])}
        stop = a not in base_w and out_in > att_in + 1000
        if stop: stopped.add(a)
        for h, ts, fr, to, s, v, k, m in mv:
          if k == 'fee': n['TRX']['fees'] += v; E(h, ts, a, a, 'TRX', v, 'fee', ''); continue
          if k == 'proceeds': n['TRX']['in'] += v; E(h, ts, fr, a, 'TRX', v, 'in:swap_proceeds', m); continue
          if k == 'redirect_usdt':                                                   # receiver books the USDT itself (TRC20 is in its own history): only discover + follow it
            pr = profile(to)
            if not (pr['contract'] or pr['created'] < T0 or stop or to in attacker):
              attacker.add(to)
              if to not in done and to not in fut.values(): fut[ex.submit(read_wallet, to, lo, hi)] = to
            continue
          if k == 'redirect':
            pr = profile(to)
            if pr['contract'] or pr['created'] < T0 or stop: continue      # contract plumbing / old address: not followed (as before)
            if to in done: print(f'  NOTE redirect to already-read {to} ({v:,.2f} TRX): left to its own internal-inflow check', flush=True); continue
            n['TRX']['in'] += v; n['TRX']['out'] += v
            E(h, ts, fr, a, 'TRX', v, 'in:own_back', m); E(h, ts, a, to, 'TRX', v, 'out:attacker', 'redirect via ' + m)
            attacker.add(to); PENDING[to].append((h, ts, a, v))
            if to not in done and to not in fut.values(): fut[ex.submit(read_wallet, to, lo, hi)] = to
            continue
          if k == 'in':
            n[s]['in'] += v
            cls = 'in:root' if fr == SOURCE else 'in:attacker' if fr in attacker else 'in:dust' if v < 1 and s == 'TRX' else \
                  'in:own_back' if (fr in VAULTS or fr in EP or h in own_tx) else 'in:foreign'
            E(h, ts, fr, a, s, v, cls, m); continue
          n[s]['out'] += v
          if to in attacker: cls, det = 'attacker', ''
          elif to in EP: cls, det = EP[to].split(':')[0], EP[to]
          elif to in VAULTS or m.startswith(('=', 'SWAP:', 's:', 'swap:')): VAULTS.add(to); cls, det = 'thorchain', m
          else:
            pr = profile(to)
            if pr['contract']: cls, det = 'unknown_contract', pr['name']
            elif pr['created'] >= T0 and not stop and (first_funder(to) == a or joins(to, attacker)):
              cls, det = 'attacker', 'new'; attacker.add(to)
              if to not in done and to not in fut.values() and (not limit or n_done + len(fut) < limit):
                fut[ex.submit(read_wallet, to, lo, hi)] = to
            else: cls, det = 'external', f'created {time.strftime("%F", time.gmtime(pr["created"]/1000))} ntx {pr["ntx"]}' + (' | payee of outside-majority wallet' if stop else '')
          E(h, ts, a, to, s, v, 'out:' + cls, det or m)
        o = {s: opening.get((a, s), 0.0) for s in ('TRX', 'USDT')}
        d = {'TRX': o['TRX'] + n['TRX']['in'] - n['TRX']['out'] - n['TRX']['fees'], 'USDT': o['USDT'] + n['USDT']['in'] - n['USDT']['out']}
        quiet = live['last_op'] <= hi
        note = ('quiet' if quiet else 'moved after cutoff') + (' | STOP: outside inflow > attacker inflow (not followed)' if stop else '')
        if quiet and (abs(live['trx'] - d['TRX']) > 1 or abs(live['usdt'] - d['USDT']) > 1):
          # receiving does not bump last_op: look for inflows after the cutoff first, then internal transfers in the window
          late = get(f'{TG}/v1/accounts/{a}/transactions?min_timestamp={hi + 1}&limit=20').get('data', []) + \
                 get(f'{TG}/v1/accounts/{a}/transactions/trc20?min_timestamp={hi + 1}&limit=20').get('data', [])
          if late: quiet = False; note = 'received after cutoff' + note[5:]
          elif abs(live['trx'] - d['TRX']) > 1:
            try:
              booked = {x[0] for x in mv if x[3] == a and x[6] == 'in'}           # skip internal inflows already booked (redirects)
              for h, ts, fr, v in tronscan_internal_in(a, hi, lo):
                if h in booked: continue
                n['TRX']['in'] += v; d['TRX'] += v; E(h, ts, fr, a, 'TRX', v, 'in:internal', 'tronscan'); note += ' +internal'
            except Exception as ex: note += f' | internal UNRESOLVED ({str(ex)[:30]})'
        for s, lv in (('TRX', live['trx']), ('USDT', live['usdt'])):
          chk = (lv - d[s]) if quiet else 0.0
          NODE(a, s, n[s]['in'], n[s]['out'], n[s]['fees'], d[s], chk, ntx, time.strftime('%F %T', time.gmtime(live['created']/1000)),
               1 if a in frozen0 else 0, note + (f' | live-derived {chk:,.6f}' if quiet else ''))
        C.commit()
        el = time.time() - t0
        if n_done % 10 == 0 or not fut:
          print(f'[{n_done} done, {len(fut)} in flight] {el:,.0f}s | {n_done/el*60:,.1f} wallets/min | calls TronGrid {GTG.n} ({GTG.n/el:.1f}/s) '
                f'Tronscan {GTS.n} ({GTS.n/el:.1f}/s) | last {a} TRX {d["TRX"]:,.2f} ({note[:40]})', flush=True)
  print(f'   ({n_done} wallets in {time.time()-t0:,.0f}s)', flush=True)
  return n_done, stopped

if __name__ == '__main__': main()
