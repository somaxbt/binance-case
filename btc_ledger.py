"""Binance case, BITCOIN leg: UTXO conservation ledger (satoshis), pinned to one block height. Own DB: binance-btc-ledger.db.
  python3 btc_ledger.py run      follow every attacker output from the drain txs; classify; check conservation
  python3 btc_ledger.py show
  python3 btc_ledger.py bridged       same ledger for BTC bridged in from other legs (roots = payouts into raw/btc_bridged_seeds.json,
  python3 btc_ledger.py bshow         built by btc_seeds.py). Own DB binance-btc-bridged-ledger.db, so Eagle Eye's direct pot is untouched.
Rule: BTC drained = unspent at attacker addresses + exits + miner fees (to the satoshi). Every UTXO is stored.
Attacker-owned = outputs of the drain txs to the collection address, then every output of any tx whose inputs are ALL
attacker-owned (the attacker signed it), unless the output goes to a labelled service. A spend mixing attacker and
non-attacker inputs is flagged MIXED. Unconfirmed (mempool) spends are flagged, not counted."""
import json, os, re, sys, time, sqlite3, gzip, urllib.request, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); DB = os.path.join(HERE, 'binance-btc-ledger.db')
BDB = os.path.join(HERE, 'binance-btc-bridged-ledger.db')
HACK_TS = 1793304000   # 2026-10-29 20:00 UTC; bridged roots are payouts after this
MAX_PAGES = 20         # busy-address guard: never pull full history
API = os.environ.get('BTC_API', 'https://blockstream.info/api')
APIS = [x.strip().rstrip('/') for x in os.environ.get('BTC_APIS', 'https://mempool.space/api,' + API).split(',') if x.strip()]   # 11-04: lanes, first = preferred
_lane, _n = 0, 0
if 'mempool.space' in API:   # mempool.space IPv4 is blackholed here -> resolve IPv6 only
  import socket; _gai = socket.getaddrinfo
  socket.getaddrinfo = lambda h, *a, **k: [r for r in _gai(h, *a, **k) if r[0] == socket.AF_INET6] or _gai(h, *a, **k)
HOT = 'bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h'          # Binance hot wallet (victim)
COLLECT = 'bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm'      # attacker collection address
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB);
CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, started TEXT, finished TEXT, tip INTEGER, params TEXT);
CREATE TABLE IF NOT EXISTS utxo(run_id TEXT, txid TEXT, vout INTEGER, address TEXT, sats INTEGER, owner TEXT, status TEXT,
  spent_by TEXT, spent_height INTEGER, note TEXT, PRIMARY KEY(run_id, txid, vout));
CREATE TABLE IF NOT EXISTS btx(run_id TEXT, txid TEXT PRIMARY KEY, height INTEGER, ts INTEGER, fee INTEGER, n_in INTEGER, n_out INTEGER,
  attacker_in INTEGER, foreign_in INTEGER, kind TEXT);
"""
C = None
def get(path, raw_text=False):
  if re.fullmatch(r'/tx/[0-9a-f]{64}', path):          # 11-03: confirmed tx bodies never change -> reuse raw_payload (was archive-only; a 429 retry re-fetched 1,322)
    r = C.execute('SELECT body FROM raw_payload WHERE url=? ORDER BY id DESC LIMIT 1', (path,)).fetchone()
    if r:
      j = json.loads(gzip.decompress(r[0]))
      if (j.get('status') or {}).get('confirmed'): return j
  global _lane, _n
  for i in range(16):   # 11-04: two Esplora hosts; on 429/5xx ROTATE at once (Blockstream 429'd us into ~2 req/min), back off only when both are throttled
    base = APIS[_lane % len(APIS)]
    try:
      b = urllib.request.urlopen(urllib.request.Request(base + path, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read()
      C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), path, gzip.compress(b))); time.sleep(0.4)
      _n += 1
      if _n % 50 == 0: C.commit()                      # 11-04: persist the payload cache as we go (a killed run lost 40 min)
      return b.decode() if raw_text else json.loads(b)
    except urllib.error.HTTPError as e:
      if e.code in (429, 500, 502, 503):
        _lane += 1
        if i % len(APIS) == len(APIS) - 1: time.sleep(min(15 * (i + 1), 120))   # every host throttled → wait
        continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
      _lane += 1; time.sleep(5 * (i % 3 + 1))
  raise RuntimeError('esplora failed ' + path)

# 11-04: (a) CoinJoin = an EXIT on Bitcoin, detected STRUCTURALLY with the engine's own rules (btc-engine/scripts/coinjoin-coordinators.py
# classify_tx, imported from that file — no copy) and named from LiquiSabi/Wasabi maps when the round is listed ('unnamed' otherwise);
# (b) HUB STOP: an output address with > BTC_HUB_TX txs is an unlabelled service/hub → exit, never attacker (the 11-04 run walked into a
# service wallet, bc1qrqlamjhy… 3,260.97 BTC 'attacker' > the 905.53 BTC that came in).
import importlib.util
_cj = importlib.util.spec_from_file_location('cjc', os.path.expanduser('~/traversal-engine/btc-engine/scripts/coinjoin-coordinators.py'))
CJ = importlib.util.module_from_spec(_cj); _cj.loader.exec_module(CJ)
CJ_COORDS = CJ.load_coords()[0]
HUB_TX = int(os.environ.get('BTC_HUB_TX', 1000)); _hub = {}
def hub_txs(a):
  """total tx count of an address (Esplora /address) or None if small; cached per run"""
  if a not in _hub:
    try:
      st = get(f'/address/{a}'); n = (st.get('chain_stats') or {}).get('tx_count', 0) + (st.get('mempool_stats') or {}).get('tx_count', 0)
    except Exception: n = 0
    _hub[a] = n if n > HUB_TX else None
  return _hub[a]
def coinjoin(t):
  typ, conf, anon = CJ.classify_tx(t)
  return f"{CJ_COORDS.get(t['txid'], 'coordinator unnamed')} ({conf}, anon set {anon})" if typ == 'coinjoin' else None

LB = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/labels.db'))
POR = sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
def label(a):
  p = POR.execute('SELECT exchange, wallet_type FROM por_wallets WHERE address=?', (a,)).fetchone()
  if p: return f'cex:{p[0]}/{p[1]}'
  r = LB.execute('SELECT name FROM labels WHERE address=?', (a,)).fetchone()
  return f'label:{r[0][:40]}' if r else ''

def run(bridged=False):
  global C
  C = sqlite3.connect(BDB if bridged else DB, timeout=600); C.execute('PRAGMA journal_mode=WAL'); C.executescript(SCHEMA)
  tip = int(os.environ.get('BTC_TIP') or get('/blocks/tip/height', raw_text=True))   # 11-04: BTC_TIP=<height> pins a common cutoff (e.g. 974511 = 11-04 09:05:42)
  run_id = ('btcb-' if bridged else 'btc-') + time.strftime('%Y%m%dT%H%M%S')
  seeds = json.load(open(os.path.join(HERE, 'raw/btc_bridged_seeds.json'))) if bridged else {}
  C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?)', (run_id, time.strftime('%FT%T'), None, tip, json.dumps({'seeds': seeds} if bridged else {'hot': HOT, 'collect': COLLECT}))); C.commit()
  print(f'{run_id}: pinned at tip {tip}', flush=True)
  if bridged:
    attacker, seen = set(seeds), set()
    for a, sd in seeds.items():
      txs, last, n = [], None, 0
      while n < MAX_PAGES:
        page = get(f'/address/{a}/txs' + (f'/chain/{last}' if last else '')); n += 1
        if not page: break
        txs += page; last = page[-1]['txid']
        if len(page) < 25 or (page[-1]['status'].get('block_time') or 1e12) < HACK_TS: break
      if n >= MAX_PAGES: print(f'  BUSY {a}: stopped at {MAX_PAGES} pages, check by hand', flush=True)
      for t in txs:
        if not t['status'].get('confirmed') or t['status']['block_height'] > tip or t['status']['block_time'] < HACK_TS: continue
        if any(v['prevout']['scriptpubkey_address'] in seeds for v in t['vin']): continue   # seed->seed: reached by the follow, not a root
        for i, o in enumerate(t['vout']):
          if o.get('scriptpubkey_address') == a:
            C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], i, a, o['value'], 'attacker', 'pending', None, None, f"bridged:{'+'.join(sd['origin'])}:{'+'.join(sd['via'])}"))
        C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status']['block_height'], t['status']['block_time'], t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'bridge payout (service-signed)'))
    C.commit()
    got = C.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note LIKE 'bridged%'", (run_id,)).fetchone()
    print(f'bridged roots: {(got[0] or 0)/1e8:,.8f} BTC in {got[1]} payouts to {len(seeds)} seeds', flush=True)
  # roots: every tx where the hot wallet pays the collection address
  txs, last = [], None
  if bridged: txs = None
  while txs is not None:
    page = get(f'/address/{COLLECT}/txs' + (f'/chain/{last}' if last else ''))
    if not page: break
    txs += page; last = page[-1]['txid']
    if len(page) < 25: break
  if not bridged: attacker, seen = {COLLECT}, set()
  drained = 0
  for t in txs or []:
    if any(v['prevout']['scriptpubkey_address'] == HOT for v in t['vin']):
      for i, o in enumerate(t['vout']):
        if o.get('scriptpubkey_address') == COLLECT:
          drained += o['value']; C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], i, COLLECT, o['value'], 'attacker', 'pending', None, None, 'drain'))
      C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status'].get('block_height'), t['status'].get('block_time'), t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'drain (victim-signed)'))
  if not bridged: print(f'drain: {drained/1e8:,.8f} BTC in {sum(1 for t in txs if any(v["prevout"]["scriptpubkey_address"]==HOT for v in t["vin"]))} txs', flush=True)
  # follow: resolve each attacker UTXO's spend
  def book_untracked(t, st):
    for v in t['vin']:
      if v['prevout']['scriptpubkey_address'] in attacker and not C.execute("SELECT 1 FROM utxo WHERE run_id=? AND txid=? AND vout=? AND owner='attacker'", (run_id, v['txid'], v['vout'])).fetchone():
        C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, v['txid'], v['vout'], v['prevout']['scriptpubkey_address'], v['prevout']['value'], 'attacker', 'spent', st, None, 'untracked-in'))
  def recheck_mixed():
    """a spend is only 'MIXED' if an input is truly foreign; inputs from attacker branches not yet walked at the time
    made it look mixed. Re-test every MIXED tx against the full attacker-UTXO set; promote and keep following."""
    promoted = 0
    for (st,) in C.execute("SELECT txid FROM btx WHERE run_id=? AND kind LIKE 'MIXED%' AND kind NOT LIKE 'MIXED (CoinJoin%'", (run_id,)).fetchall():
      t = get(f'/tx/{st}')
      ok = all(C.execute("SELECT 1 FROM utxo WHERE run_id=? AND txid=? AND vout=? AND owner='attacker'", (run_id, v['txid'], v['vout'])).fetchone()
               or v['prevout']['scriptpubkey_address'] in attacker for v in t['vin'])
      if ok:
        C.execute("UPDATE btx SET kind='attacker-signed', attacker_in=n_in, foreign_in=0 WHERE run_id=? AND txid=?", (run_id, st))
        book_untracked(t, st)
        for (vout, ad, nt) in C.execute("SELECT vout, address, note FROM utxo WHERE run_id=? AND txid=? AND owner LIKE 'unattributed%'", (run_id, st)).fetchall():
          if nt: C.execute("UPDATE utxo SET owner='exit' WHERE run_id=? AND txid=? AND vout=?", (run_id, st, vout)); continue
          C.execute("UPDATE utxo SET owner='attacker', status='pending' WHERE run_id=? AND txid=? AND vout=?", (run_id, st, vout)); attacker.add(ad)
        promoted += 1
    C.commit(); return promoted
  while True:
    pend = C.execute("SELECT txid, vout, address, sats FROM utxo WHERE run_id=? AND owner='attacker' AND status='pending'", (run_id,)).fetchall()
    if not pend:
      if recheck_mixed(): continue
      break
    for txid, vout, addr, sats in pend:
      os_ = get(f'/tx/{txid}/outspend/{vout}')
      if not os_.get('spent'):
        C.execute("UPDATE utxo SET status='unspent' WHERE run_id=? AND txid=? AND vout=?", (run_id, txid, vout)); continue
      sh = (os_.get('status') or {}).get('block_height')
      if not (os_.get('status') or {}).get('confirmed') or (sh and sh > tip):
        C.execute("UPDATE utxo SET status=?, spent_by=? WHERE run_id=? AND txid=? AND vout=?",
                  ('unspent (spend in mempool)' if not (os_.get('status') or {}).get('confirmed') else 'unspent at tip (spent later)', os_['txid'], run_id, txid, vout)); continue
      C.execute("UPDATE utxo SET status='spent', spent_by=?, spent_height=? WHERE run_id=? AND txid=? AND vout=?", (os_['txid'], sh, run_id, txid, vout))
      st = os_['txid']
      if st in seen: continue
      seen.add(st)
      t = get(f'/tx/{st}')
      ins = [(v['txid'], v['vout'], v['prevout']['scriptpubkey_address'], v['prevout']['value']) for v in t['vin']]
      a_in = sum(1 for _, _, ad, _ in ins if ad in attacker); f_in = len(ins) - a_in   # same key => attacker-signed
      cj = coinjoin(t)
      kind = f'MIXED (CoinJoin: {cj})' if cj else 'attacker-signed' if f_in == 0 else 'MIXED (foreign inputs)'
      if cj: f_in = max(f_in, 1)                                                    # a CoinJoin is never attacker-signed: stop here
      if f_in == 0: book_untracked(t, st)
      C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, st, sh, t['status'].get('block_time'), t['fee'], len(ins), len(t['vout']), a_in, f_in, kind))
      for i, o in enumerate(t['vout']):
        ad = o.get('scriptpubkey_address') or o.get('scriptpubkey_type'); lb = label(ad) if ad else ''
        if f_in == 0 and lb: owner, note = 'exit', lb
        elif f_in == 0 and ad and ad in attacker: owner, note = 'attacker', ''
        elif f_in == 0 and ad and not ad.startswith('op_') and hub_txs(ad): owner, note = 'exit', f'hub/service (unlabelled, {hub_txs(ad):,} txs)'
        elif f_in == 0: owner, note = 'attacker', ''; attacker.add(ad)
        else: owner, note = 'unattributed (mixed tx)', lb
        C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, st, i, ad, o['value'], owner, 'pending' if owner == 'attacker' else 'n/a', None, None, note))
        # an output booked earlier as 'untracked-in' (its spender was processed first) is internal: not a source
        if owner == 'attacker': C.execute("UPDATE utxo SET note='' WHERE run_id=? AND txid=? AND vout=? AND note='untracked-in'", (run_id, st, i))
    C.commit()
  C.execute('UPDATE ledger_run SET finished=? WHERE run_id=?', (time.strftime('%FT%T'), run_id)); C.commit()
  show(run_id, bridged)

def show(run_id=None, bridged=False):
  c = sqlite3.connect(BDB if bridged else DB, timeout=600)
  run_id = run_id or c.execute('SELECT run_id FROM ledger_run ORDER BY started DESC LIMIT 1').fetchone()[0]
  tip = c.execute('SELECT tip FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0]
  drained = c.execute("SELECT SUM(sats) FROM utxo WHERE run_id=? AND (note='drain' OR note LIKE 'bridged%')", (run_id,)).fetchone()[0] or 0
  unspent = c.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='attacker' AND status LIKE 'unspent%'", (run_id,)).fetchone()
  exits = c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='exit' GROUP BY note", (run_id,)).fetchall()
  untr = c.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note='untracked-in'", (run_id,)).fetchone()
  drained += untr[0] or 0
  unatt = c.execute("SELECT SUM(u.sats) FROM utxo u JOIN btx b ON b.run_id=u.run_id AND b.txid=u.spent_by WHERE u.run_id=? AND u.owner='attacker' AND b.kind LIKE 'MIXED%'", (run_id,)).fetchone()[0] or 0
  fees = c.execute("SELECT SUM(fee) FROM btx WHERE run_id=? AND kind='attacker-signed'", (run_id,)).fetchone()[0] or 0
  mixed = c.execute("SELECT txid, height, attacker_in, foreign_in FROM btx WHERE run_id=? AND kind LIKE 'MIXED%'", (run_id,)).fetchall()
  mem = c.execute("SELECT txid, vout, address, sats, spent_by FROM utxo WHERE run_id=? AND status LIKE '%mempool%'", (run_id,)).fetchall()
  uses = (unspent[0] or 0) + sum(s for _, s, _ in exits) + unatt + fees
  print(f'\n=== {run_id} | pinned tip {tip} ===')
  if not bridged: print(f'SOURCES  drained from Binance hot wallet   {drained/1e8:>18,.8f} BTC')
  else:
    seeds = json.loads(c.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0])['seeds']
    for n, s, k in c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note LIKE 'bridged%' GROUP BY note", (run_id,)):
      print(f'SOURCES  {n:36} {s/1e8:>18,.8f} BTC ({k} payouts)')
    got = dict(c.execute("SELECT address, SUM(sats) FROM utxo WHERE run_id=? AND note LIKE 'bridged%' GROUP BY address", (run_id,)).fetchall())
    diff = [(a, sd['expected_btc'], got.get(a, 0) / 1e8) for a, sd in seeds.items() if abs(got.get(a, 0) / 1e8 - sd['expected_btc']) > 1e-6]
    if untr[1]: print(f'SOURCES  UNTRACKED inputs at attacker addresses {(untr[0] or 0)/1e8:>12,.8f} BTC ({untr[1]}) — resolve: who paid them?')
    print(f'SEEDS    received vs bridge records: {len(seeds) - len(diff)}/{len(seeds)} exact')
    for a, e, g in diff: print(f'         ≠ {a} expected {e:.8f} got {g:.8f} ({g - e:+.8f})')
  print(f'USES     unspent at attacker ({unspent[1]} UTXOs)  {(unspent[0] or 0)/1e8:>18,.8f}')
  for n, s, k in exits: print(f'         exit {n:28} {s/1e8:>18,.8f} ({k})')
  cjs = c.execute("SELECT SUM(u.sats), COUNT(DISTINCT b.txid) FROM utxo u JOIN btx b ON b.run_id=u.run_id AND b.txid=u.spent_by WHERE u.run_id=? AND u.owner='attacker' AND b.kind LIKE 'MIXED (CoinJoin%'", (run_id,)).fetchone()
  print(f'         into CoinJoins (exit, {cjs[1] or 0} txs) {(cjs[0] or 0)/1e8:>18,.8f}\n         into other MIXED txs            {(unatt - (cjs[0] or 0))/1e8:>18,.8f}\n         miner fees (attacker txs)       {fees/1e8:>18,.8f}')
  print(f'UNEXPLAINED (sats)                       {drained - uses}')
  print(f'MIXED spends: {mixed or "none"}  | spends waiting in mempool: {mem or "none"}')
  print('\nunspent attacker UTXOs:')
  for r in c.execute("SELECT address, sats, txid, vout, status FROM utxo WHERE run_id=? AND owner='attacker' AND status LIKE 'unspent%' ORDER BY sats DESC", (run_id,)):
    print(f'   {r[0]} {r[1]/1e8:>14,.8f} {r[2]}:{r[3]} {r[4]}')

if __name__ == '__main__':
  {'run': run, 'show': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None),
   'bridged': lambda: run(True), 'bshow': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None, True)}[sys.argv[1]]()
