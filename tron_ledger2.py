"""Binance case, TRON leg — conservation ledger v2 (pinned snapshot).
  python3 tron_ledger2.py run [CUTOFF_UNIX_MS]   default cutoff = now
  python3 tron_ledger2.py inc BASE_RUN [CUTOFF_UNIX_MS]   incremental: opening = BASE closing, books only (base cutoff, cutoff]
  python3 tron_ledger2.py show [run_id]
What v1 got wrong and v2 fixes:
  1. Wallets moved while v1 ran, so history and balance were read at different moments. v2 PINS a cutoff: only
     txs at/before the cutoff count, and each wallet's cutoff balance is DERIVED from its own history
     (in - out - fees). A wallet's live balance is used as a CHECK only if it has had no activity after the cutoff.
  2. TronGrid's account history omits internal TRX transfers sent to a wallet in another party's tx (e.g. Symbiosis
     refunds). Wallets whose derived balance disagrees with a quiet live balance get their internal transfers from
     Tronscan, and those are added as 'in:internal'.
  3. Fees are stored per tx (cls 'fee') so a cutoff can be applied to them too.
Storage: binance-live.db, run ids 'tron2-…' (v1 runs untouched)."""
import json, sys, time, hashlib, sqlite3, os, urllib.request, urllib.error, gzip
from collections import defaultdict
import tron_ledger as v1                                   # reuse constants, base58 helpers, endpoints, schema
from tron_ledger import h2b, b2h, ROOT, SOURCE, USDT, TG, ENDPOINT, VAULTS, T0, DB

C = None
ENVF = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
TG_KEY = ENVF.get('TRONGRID_API_KEY')
TS_KEY = ENVF.get('TRONSCAN_API_KEY')                       # Tronscan is keyless-throttled to death; with a key it answers
QPS = 8                                                    # same cap as tron/lib/tronSource.ts (TronGrid allows 15/s with a key)
import http.client as httpclient, threading as _th
_tls = _th.local()
def tg_request(path, body=None):
  """keep-alive HTTPS to TronGrid: one persistent connection per thread (urllib re-handshakes TLS on every call)"""
  for attempt in range(3):
    conn = getattr(_tls, 'conn', None)
    if conn is None: conn = _tls.conn = httpclient.HTTPSConnection('api.trongrid.io', timeout=40)
    h = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0', 'Connection': 'keep-alive'}
    if TG_KEY: h['TRON-PRO-API-KEY'] = TG_KEY
    try:
      conn.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, h)
      r = conn.getresponse(); raw = r.read()
      if r.status >= 400: raise urllib.error.HTTPError(path, r.status, r.reason, None, None)
      return raw
    except (httpclient.HTTPException, ConnectionError, TimeoutError, OSError):
      try: conn.close()
      except Exception: pass
      _tls.conn = None
      if attempt == 2: raise
def http(u, body=None, headers=None):
  waits = tries = 0
  while True:
    try:
      keyed = u.startswith(TG)
      if keyed:
        raw = tg_request(u[len(TG):], body); time.sleep(1.0 / QPS)
      else:
        h = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0', **(headers or {})}
        raw = urllib.request.urlopen(urllib.request.Request(u, json.dumps(body).encode() if body is not None else None, h), timeout=40).read()
        time.sleep(1.1)
      C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), u + (' ' + json.dumps(body) if body else ''), gzip.compress(raw))); C.commit()
      return json.loads(raw)
    except urllib.error.HTTPError as e:
      tries += 1
      if (e.code == 429 or e.code >= 500) and tries <= 8: time.sleep(10 * tries); continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
      waits += 1
      if waits > 30: raise
      print(f'   network down ({getattr(e, "reason", e)}), waiting 30s [{waits}/30]', flush=True); time.sleep(30)

import threading
from concurrent.futures import ThreadPoolExecutor
_gate = threading.Lock(); _last = [0.0]
def _fetch_info(txid):
  """one receipt, rate-gated across threads (<= QPS); returns (txid, raw bytes) — DB writes stay on the main thread"""
  body = json.dumps({'value': txid}).encode()
  for i in range(8):
    with _gate:
      wait = _last[0] + 1.0 / QPS - time.time()
      if wait > 0: time.sleep(wait)
      _last[0] = time.time()
    try:
      return txid, tg_request('/wallet/gettransactioninfobyid', {'value': txid})
    except urllib.error.HTTPError as e:
      if e.code == 429 or e.code >= 500: time.sleep(3 * (i + 1)); continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(10 * (i + 1))
  raise RuntimeError(f'receipt fetch failed {txid}')
def prefetch_infos(txids):
  out = {}
  with ThreadPoolExecutor(max_workers=8) as ex:
    for txid, raw in ex.map(_fetch_info, txids):
      C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), f'{TG}/wallet/gettransactioninfobyid {txid}', gzip.compress(raw)))
      out[txid] = json.loads(raw)
  C.commit(); return out

def pages(path, cutoff):
  out, fp = [], None
  sep = '&' if '?' in path else '?'
  while True:
    d = http(f'{TG}{path}{sep}limit=200&max_timestamp={cutoff}' + (f'&fingerprint={fp}' if fp else ''))
    out += d.get('data', []); fp = d.get('meta', {}).get('fingerprint')
    if not fp or len(out) >= 20000: return out

def account(a):
  d = (http(f'{TG}/v1/accounts/{a}').get('data') or [{}])[0]
  staked = sum(f.get('amount', 0) for f in d.get('frozenV2', [])) / 1e6
  return d.get('balance', 0) / 1e6 + staked, d.get('create_time')

def usdt_balance(a):
  d = http(f'{TG}/wallet/triggerconstantcontract', {'owner_address': 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', 'contract_address': USDT,
           'function_selector': 'balanceOf(address)', 'parameter': b2h(a)[2:].rjust(64, '0'), 'visible': True})
  r = (d.get('constant_result') or [''])[0]; return int(r[-64:], 16) / 1e6 if r else 0.0
def usdt_frozen(a):
  d = http(f'{TG}/wallet/triggerconstantcontract', {'owner_address': 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', 'contract_address': USDT,
           'function_selector': 'isBlackListed(address)', 'parameter': b2h(a)[2:].rjust(64, '0'), 'visible': True})
  r = (d.get('constant_result') or [''])[0]; return int(r[-64:], 16) if r else 0

def active_after(a, cutoff):
  """any non-dust tx touching a after the cutoff? (dust/poisoning inbound is ignored)"""
  d = http(f'{TG}/v1/accounts/{a}/transactions?min_timestamp={cutoff + 1}&limit=50')
  for t in d.get('data', []):
    if 'raw_data' not in t: return True
    c = t['raw_data']['contract'][0]; p = c['parameter']['value']
    if c['type'] == 'TransferContract' and h2b(p['owner_address']) != a and p['amount'] < 1e6: continue
    return True
  d = http(f'{TG}/v1/accounts/{a}/transactions/trc20?min_timestamp={cutoff + 1}&limit=20')
  return any(t.get('type') == 'Transfer' and t['token_info']['address'] == USDT for t in d.get('data', []))

def tronscan_internal_in(a, cutoff, lo=T0):
  """internal TRX transfers INTO a (from contracts, in other parties' txs), in (lo, cutoff]"""
  out, start = [], 0
  H = {'Referer': 'https://tronscan.org/', **({'TRON-PRO-API-KEY': TS_KEY} if TS_KEY else {})}
  while True:
    d = http(f'https://apilist.tronscanapi.com/api/internal-transaction?address={a}&start={start}&limit=50', headers=H)
    rows = d.get('data', []) or []
    for x in rows:
      ts = x.get('timestamp', 0)
      if ts < lo or ts > cutoff or x.get('to') != a: continue
      tok = x.get('tokenInfo') or {}
      if tok and tok.get('tokenId') not in (None, '_'): continue
      v = float(x.get('call_value', x.get('value', 0)) or 0) / 1e6
      if v > 0 and not x.get('rejected', False): out.append((x.get('hash'), ts, x.get('from'), v))
    start += 50
    if len(rows) < 50 or start > 1000: return out

def opening_of(c, base):
  """closing book of a finished run = opening book of an incremental run: {(address, asset): bal}, its cutoff"""
  op = {(a, s): b or 0.0 for a, s, b in c.execute('SELECT address, asset, bal FROM ledger_node WHERE run_id=?', (base,))}
  return op, json.loads(c.execute('SELECT params FROM ledger_run WHERE run_id=?', (base,)).fetchone()[0])['cutoff']

def run():
  global C
  C = sqlite3.connect(DB, timeout=600); C.execute('PRAGMA journal_mode=WAL'); C.executescript(v1.SCHEMA)
  prev = C.execute("SELECT run_id, params FROM ledger_run WHERE leg='tron2' AND finished IS NULL ORDER BY started DESC LIMIT 1").fetchone() if 'resume' in sys.argv else None
  # incremental: `inc BASE_RUN [CUTOFF]` books only (base cutoff, cutoff]; base closing balances are the opening balances
  base = sys.argv[2] if sys.argv[1] == 'inc' else (json.loads(prev[1]).get('base') if prev else None)
  opening, lo = opening_of(C, base) if base else ({}, T0 - 1)
  lo += 1
  if prev:                                     # resume: SAME run and SAME cutoff; skip finished wallets; drop the half-written one
    run_id, cutoff = prev[0], json.loads(prev[1])['cutoff']
    done = {r[0] for r in C.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
    C.execute("""DELETE FROM ledger_edge WHERE run_id=:r AND (
                   (cls LIKE 'in:%' AND too NOT IN (SELECT address FROM ledger_node WHERE run_id=:r)) OR
                   ((cls LIKE 'out:%' OR cls LIKE 'stake:%' OR cls='fee') AND frm NOT IN (SELECT address FROM ledger_node WHERE run_id=:r)))""", {'r': run_id}); C.commit()
    attacker = {ROOT} | done | {a for a, _ in opening} | {r[0] for r in C.execute("SELECT DISTINCT too FROM ledger_edge WHERE run_id=? AND cls='out:attacker'", (run_id,))}
    queue = sorted(attacker - done); ctype = {}
    print(f'resuming {run_id}: cutoff {time.strftime("%F %T UTC", time.gmtime(cutoff/1000))}, {len(done)} done, {len(queue)} queued, key={"yes" if TG_KEY else "no"} @ {QPS}/s', flush=True)
  else:
    arg = sys.argv[3 if base else 2] if len(sys.argv) > (3 if base else 2) else ''
    cutoff = int(arg) if arg.isdigit() else int(time.time() * 1000)
    run_id = 'tron2-' + time.strftime('%Y%m%dT%H%M%S')
    C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?,?)', (run_id, 'tron2', time.strftime('%FT%T'), None, json.dumps({'T0': T0, 'cutoff': cutoff, 'root': ROOT, **({'base': base, 'from': lo} if base else {})}), 0)); C.commit()
    print(f'{run_id}: cutoff {time.strftime("%F %T UTC", time.gmtime(cutoff/1000))}, key={"yes" if TG_KEY else "no"}' + (f', incremental from {base}' if base else ''), flush=True)
    attacker, queue, done, ctype = {ROOT}, [ROOT], set(), {}
    if base: attacker |= {a for a, _ in opening}; queue = sorted({a for a, _ in opening})
  E = lambda *r: C.execute('INSERT INTO ledger_edge VALUES(?,?,?,?,?,?,?,?,?)', (run_id, *r))
  def classify(to, txid=None, memo=''):
    if to in attacker: return 'attacker', ''
    if to in ENDPOINT: return ENDPOINT[to].split(':')[0], ENDPOINT[to]
    if to in VAULTS or memo.startswith(('=', 'SWAP:', 's:', 'swap:')):
      if memo == '' and txid:
        t = http(f'{TG}/wallet/gettransactionbyid', {'value': txid}); d = t.get('raw_data', {}).get('data', '')
        memo = bytes.fromhex(d).decode('utf8', 'ignore') if d else ''
      VAULTS.add(to); return 'thorchain', memo
    if to not in ctype: ctype[to] = 'contract' if http(f'{TG}/wallet/getcontract', {'value': to, 'visible': True}).get('bytecode') else 'eoa'
    if ctype[to] == 'contract': return 'unknown_contract', ''
    _, created = account(to)
    if created and T0 <= created <= cutoff: return 'new_attacker', ''
    return 'external', f'created {time.strftime("%F", time.gmtime((created or 0)/1000))}'
  while queue:
    a = queue.pop(0)
    if a in done: continue
    done.add(a)
    txs = pages(f'/v1/accounts/{a}/transactions?min_timestamp={lo}', cutoff)
    t20 = [t for t in pages(f'/v1/accounts/{a}/transactions/trc20?min_timestamp={lo}', cutoff) if t.get('type') == 'Transfer']
    o_trx, o_usdt = opening.get((a, 'TRX'), 0.0), opening.get((a, 'USDT'), 0.0)
    n = {'TRX': defaultdict(float), 'USDT': defaultdict(float)}
    need = [t['txID'] for t in txs if 'raw_data' in t and t['raw_data']['contract'][0]['type'] == 'TriggerSmartContract'
            and h2b(t['raw_data']['contract'][0]['parameter']['value']['owner_address']) == a
            and h2b(t['raw_data']['contract'][0]['parameter']['value'].get('contract_address', '41' + '0' * 40)) != USDT]
    infos = prefetch_infos(need) if need else {}
    for t in txs:
      if 'raw_data' not in t: continue
      c = t['raw_data']['contract'][0]; p = c['parameter']['value']; owner = h2b(p['owner_address'])
      memo = bytes.fromhex(t['raw_data'].get('data', '')).decode('utf8', 'ignore') if t['raw_data'].get('data') else ''
      if owner == a:
        fee = sum(r.get('fee', 0) for r in t.get('ret', [])) / 1e6
        if fee: n['TRX']['fees'] += fee; E(t['txID'], t['block_timestamp'], a, a, 'TRX', fee, 'fee', '')
      if (t.get('ret') or [{}])[0].get('contractRet', 'SUCCESS') != 'SUCCESS': continue   # failed tx (e.g. OUT_OF_ENERGY): fee paid, value reverted
      if c['type'] == 'TransferContract':
        v = p['amount'] / 1e6; to = h2b(p['to_address'])
        if to == a and owner != a:
          n['TRX']['in'] += v; cls = 'in:root' if owner == SOURCE else ('in:attacker' if owner in attacker else ('in:dust' if v < 1 else 'in:foreign'))
          E(t['txID'], t['block_timestamp'], owner, a, 'TRX', v, cls, memo)
        elif owner == a:
          n['TRX']['out'] += v; cls, det = classify(to, t['txID'], memo)
          if cls == 'new_attacker': attacker.add(to); queue.append(to); cls = 'attacker'
          E(t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out:' + cls, det or memo)
      elif c['type'] == 'TriggerSmartContract' and owner == a:
        v = p.get('call_value', 0) / 1e6; to = h2b(p['contract_address'])
        if to != USDT:
          info = infos.get(t['txID']) or http(f'{TG}/wallet/gettransactioninfobyid', {'value': t['txID']})
          for it in info.get('internal_transactions', []):
            iv = sum(x.get('callValue', 0) for x in it.get('callValueInfo', []) if not x.get('tokenId')) / 1e6
            if iv > 0 and h2b(it['transferTo_address']) == a:
              n['TRX']['in'] += iv; E(t['txID'], t['block_timestamp'], h2b(it['caller_address']), a, 'TRX', iv, 'in:swap_proceeds', ENDPOINT.get(to, to))
        if v > 0:
          n['TRX']['out'] += v; cls, det = classify(to, t['txID'], memo)
          E(t['txID'], t['block_timestamp'], a, to, 'TRX', v, 'out:' + cls, det or memo)
    for t in t20:
      if t['token_info']['address'] != USDT: continue
      v = int(t['value']) / 1e6
      if t['to'] == a and t['from'] != a:
        n['USDT']['in'] += v; cls = 'in:root' if t['from'] == SOURCE else ('in:attacker' if t['from'] in attacker else 'in:foreign')
        E(t['transaction_id'], t['block_timestamp'], t['from'], a, 'USDT', v, cls, '')
      elif t['from'] == a:
        n['USDT']['out'] += v; cls, det = classify(t['to'], t['transaction_id'])
        if cls == 'new_attacker': attacker.add(t['to']); queue.append(t['to']); cls = 'attacker'
        E(t['transaction_id'], t['block_timestamp'], a, t['to'], 'USDT', v, 'out:' + cls, det)
    # cutoff balance is DERIVED; the live balance is only a check, and only if the wallet has been quiet since the cutoff
    quiet = not active_after(a, cutoff)
    live_trx, created = account(a); live_usdt = usdt_balance(a); frozen = usdt_frozen(a)
    note = 'quiet' if quiet else 'moved after cutoff'
    d_trx = o_trx + n['TRX']['in'] - n['TRX']['out'] - n['TRX']['fees']
    if quiet and abs(live_trx - d_trx) > 1:                       # missing inflows: fetch internal transfers from Tronscan
      try: internals = tronscan_internal_in(a, cutoff, lo)
      except Exception as ex:                                      # Tronscan rate-limits hard: never let it kill the run
        internals = []; note += f' | internal transfers UNRESOLVED (tronscan: {str(ex)[:40]})'
      for h, ts, frm, v in internals:
        if C.execute('SELECT 1 FROM ledger_edge WHERE run_id=? AND hash=? AND too=? AND asset="TRX" AND amount=?', (run_id, h, a, v)).fetchone(): continue
        n['TRX']['in'] += v; E(h, ts, frm, a, 'TRX', v, 'in:internal', 'tronscan'); note += ' +internal'
      d_trx = o_trx + n['TRX']['in'] - n['TRX']['out'] - n['TRX']['fees']
    for asset, derived, live in (('TRX', d_trx, live_trx), ('USDT', o_usdt + n['USDT']['in'] - n['USDT']['out'], live_usdt)):
      x = n[asset]; chk = (live - derived) if quiet else None
      C.execute('INSERT OR REPLACE INTO ledger_node VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (run_id, a, asset, x['in'], x['out'], x['fees'], derived,
                chk if chk is not None else 0.0, len(txs) + len(t20), time.strftime('%F %T', time.gmtime((created or 0)/1000)), frozen,
                note + (f' | live-derived {chk:,.6f}' if chk is not None else '')))
    C.commit()
    print(f"[{len(done)}/{len(done)+len(queue)}] {a} TRX derived {d_trx:,.2f} ({note}{'' if quiet is False else f', live-derived {live_trx-d_trx:,.4f}'}) | USDT derived {o_usdt+n['USDT']['in']-n['USDT']['out']:,.2f}{' FROZEN' if frozen else ''}", flush=True)
  C.execute('UPDATE ledger_run SET finished=?, n_nodes=? WHERE run_id=?', (time.strftime('%FT%T'), len(done), run_id)); C.commit()
  show(run_id)

def show(run_id=None):
  c = sqlite3.connect(DB, timeout=600)
  run_id = run_id or c.execute("SELECT run_id FROM ledger_run WHERE leg='tron2' ORDER BY started DESC LIMIT 1").fetchone()[0]
  nodes = {r[0] for r in c.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
  P = json.loads(c.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0]); cut = P['cutoff']
  opening = opening_of(c, P['base'])[0] if P.get('base') else {}
  print(f'\n=== {run_id}  cutoff {time.strftime("%F %T UTC", time.gmtime(cut/1000))}  wallets {len(nodes)} ===' +
        (f"\n    incremental: opening = closing of {P['base']}, window from {time.strftime('%F %T UTC', time.gmtime(P['from']/1000))}" if opening else ''))
  for asset in ('TRX', 'USDT'):
    S, U = defaultdict(float), defaultdict(float)
    if opening: S['opening (base run closing)'] = sum(v for (a, s), v in opening.items() if s == asset)
    for f, t, v, cls, det in c.execute('SELECT frm, too, amount, cls, detail FROM ledger_edge WHERE run_id=? AND asset=?', (run_id, asset)):
      if cls.startswith('in:') and f not in nodes: S[cls[3:]] += v
      elif cls.startswith('out:') and t not in nodes:
        k = cls[4:] + (':' + det.split(':')[2][:12] if cls == 'out:thorchain' and det.count(':') >= 2 else ''); U[k] += v
      elif cls == 'fee': U['fees'] += v
    held, frz = c.execute('SELECT SUM(CASE WHEN frozen=0 THEN bal ELSE 0 END), SUM(CASE WHEN frozen=1 THEN bal ELSE 0 END) FROM ledger_node WHERE run_id=? AND asset=?', (run_id, asset)).fetchone()
    U['held (derived at cutoff)'] += held or 0; U['frozen'] += frz or 0
    s, u = sum(S.values()), sum(U.values())
    print(f'\n{asset} SOURCES {s:,.6f}'); [print(f'   + {k:30} {v:>22,.6f}') for k, v in sorted(S.items(), key=lambda x: -x[1])]
    print(f'{asset} USES    {u:,.6f}'); [print(f'   - {k:30} {v:>22,.6f}') for k, v in sorted(U.items(), key=lambda x: -x[1])]
    print(f'{asset} UNEXPLAINED {s - u:,.6f}')
  bad = c.execute("SELECT address, asset, bal, resid, note FROM ledger_node WHERE run_id=? AND note LIKE 'quiet%' AND ABS(resid) > 1 ORDER BY ABS(resid) DESC LIMIT 20", (run_id,)).fetchall()
  print(f'\nquiet wallets whose live balance != derived (>1 unit): {len(bad)}'); [print('  ', b) for b in bad]
  moved = c.execute("SELECT COUNT(DISTINCT address) FROM ledger_node WHERE run_id=? AND note LIKE 'moved%'", (run_id,)).fetchone()[0]
  print(f'wallets that moved after the cutoff (balance derived, live check skipped): {moved}')
  # MIXED HERE: non-attacker money entering an attacker wallet (excluding dust, bridge/THORChain refunds and swap proceeds,
  # which are the attacker's own value coming back). Stolen value is never inflated by these: they are reported, not traced as stolen.
  print('\nMIXED HERE (foreign value entering attacker wallets; stolen amount at that wallet shown for scale):')
  for a, asset, foreign, n, srcs in c.execute("""SELECT too, asset, SUM(amount), COUNT(*), GROUP_CONCAT(DISTINCT frm) FROM ledger_edge
        WHERE run_id=? AND cls IN ('in:foreign','in:internal') GROUP BY too, asset HAVING SUM(amount) > 1 ORDER BY 3 DESC""", (run_id,)):
    stolen_in = c.execute("SELECT SUM(amount) FROM ledger_edge WHERE run_id=? AND too=? AND asset=? AND cls IN ('in:root','in:attacker','in:swap_proceeds')",
                          (run_id, a, asset)).fetchone()[0] or 0
    vault = any(s in VAULTS for s in (srcs or '').split(','))
    tag = 'THORChain refund (own value back)' if vault else ('internal transfer (check: refund or payout)' if 'internal' in str(srcs) else 'MIXED: outside money')
    print(f'   {a} {asset}: foreign {foreign:,.4f} in {n} txs vs stolen-in {stolen_in:,.4f} | {tag} | from {(srcs or "")[:120]}')

if __name__ == '__main__':
  {'run': run, 'inc': run, 'show': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None)}[sys.argv[1]]()
