"""Binance case — TRON leg graph built FROM THE LEDGER (classified, balanced books), not from raw transactions.
  python3 tron_graph.py        writes raw/tron/graph/tron_leg.html (called automatically at the end of tron_fast.py runs)
Wallets = ledger_node rows of every window in the run chain; links = internal ledger transfers merged per wallet pair;
exits = the ledger's classified outflows; THORChain payouts = CARRY-OVER sections of raw/tron/report_<run>.txt.
USD = theft-time display prices only; every figure is also shown in native units."""
import json, os, re, sqlite3, time
from collections import defaultdict
from tron_ledger import ENDPOINT, SOURCE, ROOT, T0
HERE = os.path.dirname(os.path.abspath(__file__)); DB = os.path.join(HERE, 'binance-live.db')
OUT = os.path.join(HERE, 'raw', 'tron', 'graph', 'tron_leg.html')
PX = {'TRX': 0.331, 'USDT': 1.0, 'ETH': 2313.26, 'BTC': 80244.08, 'ZEC': 0.0, 'USDC': 1.0}   # theft-time (refresh_latest _px); display only
TEC = 'TEcDijvKSXcfWT7S6rd44H5vNgufm7Y4XC'      # Chainflip vault on Tron (user-identified 2026-10-31)
CH = 'TKfz7Pu3jtxWrfHzVeozQjXsb3RfuUHGE2'       # ChangeHero hot wallet (user-identified 2026-10-31)
RELAY = 'TXtEs6t2oUWQsNos7m68gbHdE9Q5n6x2oN'    # Relay RelayDepository on Tron (ABI-identified 2026-11-01)
JTRXV = 'TMDENHFSiRzmJNSEBAFmrDbLkQ672iPN8H'    # JustLend TRX vault TrxProviderProxy (2026-11-01): pass-through, redeems pay fresh wallets
UNL = 'TZG47zhb8kcriWQ2rE719yHs1KqgzwMrvF'      # Bitget Wallet: Swap Bridge (user-identified 2026-10-31)
from tron_ledger import VAULTS
# swap routers / pools / makers and THORChain vaults send the attacker's OWN value back (swap legs, refunds): not outside money
NOT_OUTSIDE = set(ENDPOINT) | set(VAULTS) | {'TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx', 'TD4tamFrCq7KvQEB1LArNXr9sKFC6GaAmt', 'TH1YKH9MUuJtDmekPia4x9fZXAcpPrMv8B',
                                            'TLKfB2goHRY1SykEpVbiGdsesACrkCxCeW', 'TGPwgFpJcJHQUDWScySg9gkvB7EXs54rbd', 'TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd'}
ROLES = {ROOT: 'theft wallet', 'TPBkSjkCMn2ckrMuAP8n2J1jdjbw76bKN4': 'theft 2nd hop (sold USDT)',
         'TSpe5HC3PRD2svJcr1YoGszhHk2mtkyZ8A': 'pot (TRX bought with stolen USDT)', 'TRBdWqHnDVSZCVGfgHdKFLQPirQcA2PRki': 'distribution wallet',
         'TCzBTkqn66yApqbYoPezaEQosM5DAd7Y62': 'frozen', 'TNh7oqQN9WfdJvYyZDHh8pRk21mfUP8wf1': 'collection point',
         'TFYy3SQT5DC2Qm9Piya8HuQRGLQz9sH6dr': 'collection point', 'TDNF7CwfcKvgtaRPrMg4isijtf73kr8uRA': 'consolidation (THORChain)'}
for t in ('TAk1xJNWuBYvJHLsUiBFLeuK6xvpQUFYP5', 'TCBAz7itvtX5CjBzVMPQdrbwQLN63ao1fk', 'TL2F4GhnaFVZBZPncHYjwfYZFW44NcfVwj',
          'TJajtPqDqUGh1Sr1j8ugHoSXBVpaFLLHKT', 'TKkH2vH6kyi2QKcMbqym53WMuvdd1xvw6K'): ROLES[t] = 'tranche'

def category(cls, to, det):
  c, det = cls[4:], det or ''
  if to == TEC or det.startswith('bridge:chainflip'): return 'Chainflip'
  if det.startswith('bridge:usdt0') or det.startswith('bridge:layerzero'): return 'USDT0 bridge'
  if to == 'TUyTiAkE5R5GF9MrDW9oTWPCqYai42ngTc': return 'Unidentified services'   # 11-03: the ONE contract-created deposit addr (of 542) that sweeps to TD4tamFr, not TEcDij (101,315.76 USDT)
  if det == 'CreatedByContract': return 'Chainflip'     # 542 checked 11-03 (raw/tron/createdbycontract_sweeps.json): 541 sweep to TEcDij = Chainflip vault (user-identified 10-31)
  if to == CH: return 'ChangeHero'
  if to == UNL: return 'Bitget Wallet Swap Bridge'
  if to == 'TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt' or det == 'UsdtOFT' or c == 'usdt0': return 'USDT0 bridge'
  if c == 'thorchain': return 'THORChain'
  if c == 'symbiosis' or det.startswith('bridge:symbiosis'): return 'Symbiosis'
  if to == RELAY or det.startswith('bridge:relay'): return 'Relay'
  if det.startswith('exchange:hitbtc'): return 'HitBTC (via a service account)'
  if det.startswith('exchange:gate'): return 'Gate (via a service account)'
  if det.startswith('exchange:fixedfloat'): return 'FixedFloat'
  if det.startswith('bridge:near-intents'): return 'NEAR Intents'
  if det.startswith('bridge:across'): return 'Across'
  if det.startswith('bridge:'): return 'Bridgers'
  if c == 'swap' or to == JTRXV: return 'Swaps (churn)'      # JustLend TRX vault: deposit -> redeem to a fresh receiver = pass-through
  if det.startswith('defi:usdd-psm'): return 'USDD (USDT→USDD swap)'
  if c == 'defi' or 'justlend' in det: return 'JustLend'
  if det.startswith('service:unidentified'): return 'Unidentified services'
  if c == 'external': return 'External wallets'
  return 'Other contracts'

def run_chain(C):
  ok = [(r, json.loads(p)) for r, p, f in C.execute("SELECT run_id, params, finished FROM ledger_run WHERE leg='tron2' ORDER BY started")
        if f and not f.startswith(('ABANDONED', 'STOPPED', 'TEST'))]
  cur, by = ok[-1], dict(ok); out = []
  while cur:
    out.append(cur); b = cur[1].get('base'); cur = (b, by[b]) if b in by else None
  return out[::-1]

def payouts(run):
  f = os.path.join(HERE, 'raw', 'tron', f'report_{run}.txt'); res = []
  if not os.path.exists(f): return res
  on = False
  for line in open(f):
    if 'CARRY-OVER' in line: on = True; continue
    if on and line.startswith('3) MIXING'): break
    m = re.match(r'\s+(\w+)\s+(\S+)\s+(\S+)\s+([\d,\.]+)\s*$', line) if on else None
    if m: res.append({'chain': m[1], 'to': m[2], 'asset': m[3].split('-')[0].split('.')[-1], 'amt': float(m[4].replace(',', ''))})
  return res

CHAIN_NAME = {1: 'Ethereum', 8453: 'Base', 42161: 'Arbitrum', 10: 'Optimism', 56: 'BNB Chain', 137: 'Polygon', 43114: 'Avalanche', 728126428: 'Tron',
              792703809: 'Solana', 8253038: 'Bitcoin', 3586256: 'Lighter', 1337: 'Hyperliquid', 999: 'HyperEVM', 59144: 'Linea',
              324: 'zkSync', 534352: 'Scroll', 81457: 'Blast', 5000: 'Mantle', 146: 'Sonic', 130: 'Unichain', 13863860: 'Symbiosis chain'}
LZ_EID = {30101: 'Ethereum', 30110: 'Arbitrum', 30111: 'Optimism', 30184: 'Base', 30109: 'Polygon', 30102: 'BNB Chain', 30106: 'Avalanche', 30168: 'Solana',
          30420: 'Tron', 30367: 'HyperEVM', 30332: 'Sonic', 30320: 'Unichain', 30362: 'Berachain', 30339: 'Ink', 30280: 'Sei', 30295: 'Flare', 30383: 'Plasma', 30183: 'Linea', 30181: 'Mantle'}
def lz_parse(d):
  """LayerZero Scan reply -> (status, dest chain, receiver 0x.., amount USDT0 6dp)"""
  m = (d.get('data') or [{}])[0] if isinstance(d.get('data'), list) else {}; s = m.get('status')
  pl = ((m.get('source') or {}).get('tx') or {}).get('payload', '')[2:]; eid = (m.get('pathway') or {}).get('dstEid')
  return (s.get('name') if isinstance(s, dict) else s), LZ_EID.get(eid, f'eid {eid}'), ('0x' + pl[28:68] if len(pl) >= 84 else ''), (int(pl[68:84], 16) / 1e6 if len(pl) >= 84 else 0.0)

def bridge_out(C, runs):
  """[via, dest chain, recipient, asset, amount out, USD in (Tron side, theft-time px), state] per resolved bridge deposit (Relay / Symbiosis / Chainflip caches)."""
  tr = lambda name: json.load(open(os.path.join(HERE, 'raw', 'tron', name))) if os.path.exists(os.path.join(HERE, 'raw', 'tron', name)) else {}
  dep = {}
  q = ','.join('?' * len(runs))
  src = {}
  for h, t, s, v, det, f, ts in C.execute(f"SELECT hash, too, asset, amount, detail, frm, ts FROM ledger_edge WHERE cls LIKE 'out:%' AND run_id IN ({q})", runs):
    if h not in dep or v * PX[s] > dep[h][2] * PX[dep[h][1]]: dep[h] = (t, s, v, det or ''); src[h] = (f, int(ts / 1000))   # one tx can carry a fee edge too: keep the value edge
  cn = lambda c: CHAIN_NAME.get(int(c), f'chain {c}') if str(c).lstrip('-').isdigit() else (c or '?')
  rows = []
  for h, r in tr('relay_requests.json').items():
    if h not in dep or not r: continue
    t, s, v, _ = dep[h]; d = r.get('data') or {}; m = (d.get('metadata') or {}).get('currencyOut') or {}; o = (d.get('outTxs') or [{}])[0]
    ok = r.get('status') == 'success'
    rows.append(['Relay', cn(o.get('chainId')) if ok else 'refunded / failed', r.get('recipient') if ok else '', ((m.get('currency') or {}).get('symbol') or '?') if ok else s,
                 float(m.get('amountFormatted') or 0) if ok else v, round(v * PX[s], 2), r.get('status'), h, *src.get(h, ('', 0)), o.get('hash') or '', s, v])
  for h, r in tr('bridge_sym.json').items():
    if h not in dep or not r or dep[h][0] != 'TPuaJ6gnYfE9gLUDFrbWbPx3tMnjG8max1': continue      # only real Symbiosis bridge deposits
    t, s, v, _ = dep[h]; o = r.get('tx') or {}; ta = o.get('tokenAmount') or {}; ok = (r.get('status') or {}).get('text') == 'Success'
    rows.append(['Symbiosis', cn(o.get('chainId')) if ok else 'refunded / pending', o.get('address', '') if ok else '', ta.get('symbol', '?') if ok else s,
                 int(ta.get('amount') or 0) / 10 ** int(ta.get('decimals') or 0) if ok and ta else v, round(v * PX[s], 2), (r.get('status') or {}).get('text', '?'), h, *src.get(h, ('', 0)), o.get('hash') or '', s, v])
  for h, r in tr('bridge_usdt0.json').items():
    if h not in dep or not r: continue
    t, s, v, _ = dep[h]; st, ch, to, amt = lz_parse(r)
    dtx = ((((r.get('data') or [{}])[0].get('destination') or {}).get('tx') or {}).get('txHash')) if isinstance(r.get('data'), list) else ''
    rows.append(['USDT0 bridge', ch if st == 'DELIVERED' else 'held in bridge — not delivered (likely frozen)', to if st == 'DELIVERED' else '', 'USDT0', amt, round(v * PX[s], 2), st, h, *src.get(h, ('', 0)), dtx or '', s, v])   # INFLIGHT for days, DVN 'WAITING', receivers got nothing (checked 11-01)
  for h, r in tr('bridge_across.json').items():             # Across V5: final payees decoded from the fill tx (executor actions)
    if h not in dep or not r or r.get('status') != 'filled': continue
    t, s, v, _ = dep[h]; fin = r.get('final') or ([{'to': r.get('recipient'), 'asset': r.get('out_token'), 'amount': r.get('out_amount')}] if r.get('recipient') else [])
    w = [(f['amount'] or 0) * PX.get(f['asset'], 1.0 if str(f['asset']).startswith('USD') else 0) for f in fin]; tw = sum(w) or 1
    for f, wi in zip(fin, w): rows.append(['Across', 'Ethereum', f['to'], f['asset'], f['amount'] or 0, round(v * PX[s] * wi / tw, 2), 'filled', h, *src.get(h, ('', 0)), r.get('fill_tx') or '', s, v * wi / tw])
  DEC = {'ETH': 18, 'BTC': 8, 'SOL': 9, 'FLIP': 18, 'DOT': 10, 'HUB': 10}
  for h, r in tr('bridge_cf.json').items():
    if h not in dep or not r or r.get('_notfound'): continue
    t, s, v, _ = dep[h]; st = r.get('state'); a = r.get('destAsset') or '?'
    if int((r.get('swapEgress') or {}).get('amount') or 0) > 0:
      rows.append(['Chainflip', r.get('destChain', '?'), r.get('destAddress', ''), a, int((r.get('swapEgress') or {}).get('amount') or 0) / 10 ** DEC.get(a, 6), round(v * PX[s], 2), st, h, *src.get(h, ('', 0)), (r.get('swapEgress') or {}).get('txRef') or '', s, v])
    else:
      rows.append(['Chainflip', 'refunded to Tron' if r.get('refundEgress') else (st or '?').lower(), '', s, v, round(v * PX[s], 2), st])
  return rows

PUBLIC_RX = [(r'carried \(recheck: unchanged, no send\)', 'no activity in window'), (r' \| live-derived -?[\d,\.]+', ''), (r'( \+internal)+', ''),
             (r' \| STOP: outside inflow > attacker inflow \(not followed\)', ' | mixed with outside funds'), (r' \| FIXED [^"]*', ''),
             (r'\bquiet\b', 'settled at cutoff'), (r' \(user-identified [^)"]*\)', ''), (r' \(RelayDepository; resolve via [^)"]*\)', ''),
             (r'; memo to resolve on THORNode', ''), (r' \((?:tx|ABI)-verified[^)"]*\)', ''), (r'"tronscan"', '""'),
             (r' of a SERVICE account \([^)"]*\)', ' (service account)'), (r' \(older address, to check\)', ''), (r' \(inferred:[^)"]*\)', ''),
             (r' \(deployed by [^)"]*\)', ''), (r' \(probably a service[^)"]*\)', ' (probably a service)'), (r' \(TrxProviderProxy[^)"]*\)', ''),
             (r' \(-> TTWd2hBK[^)"]*\)', ''), (r' \(RelayDepository[^)"]*\)', ''), (r' \(Tron_(?:PrefundedAdapter|Executor)\)', ''), (r'"CreatedByContract"', '"deposit channel"'), (r' PoR\b', '')]
# 11-05 SECURITY: every page inserts data with innerHTML/attributes and never escapes; token symbols and labels can come from attacker-made
# contracts. safe() swaps the 5 characters that can open a tag, end a <script> or break out of an attribute for look-alikes, in every string
# (keys too: symbols are dict keys). Addresses / hashes / numbers never contain them. Apply to the data object before json.dumps, always.
_SAFE = str.maketrans({'<': '\u2039', '>': '\u203a', '"': '\u201d', "'": '\u2019', '`': '\u02bc'})
def safe(o):
  if isinstance(o, str): return o.translate(_SAFE)
  if isinstance(o, dict): return {safe(k) if isinstance(k, str) else k: safe(v) for k, v in o.items()}
  if isinstance(o, (list, tuple)): return [safe(v) for v in o]
  return o
assert safe({'a<b': ['x"y', 1, "</script><img onerror='1'>", '`']}) == {'a\u2039b': ['x\u201dy', 1, '\u2039/script\u203a\u2039img onerror=\u20191\u2019\u203a', '\u02bc']}

def public(js):
  """strip internal method notes from the page data (the DB keeps them)"""
  for a, b in PUBLIC_RX: js = re.sub(a, b, js)
  return js

def collect():
  C = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
  chain = run_chain(C)
  wins = []
  for i, (r, p) in enumerate(chain):
    lo = p.get('from', T0) if i else T0
    wins.append({'run': r, 'from': time.strftime('%m-%d %H:%M', time.gmtime(lo / 1000)), 'to': time.strftime('%m-%d %H:%M', time.gmtime(p['cutoff'] / 1000))})
  W = {}; nodes_by_run = {}
  for wi, (r, _) in enumerate(chain):
    nodes_by_run[r] = set()
    for a, s, i, o, f, b, chk, ntx, cr, fz, note in C.execute('SELECT address, asset, inn, out, fees, bal, resid, n_tx, created, frozen, note FROM ledger_node WHERE run_id=?', (r,)):
      nodes_by_run[r].add(a)
      w = W.setdefault(a, {'id': a, 'role': ROLES.get(a, 'layering'), 'created': '', 'first': wi, 'win': {}, 'frozen': 0})
      if cr and cr > '2000': w['created'] = cr
      if fz: w['frozen'] = 1
      w['first'] = min(w['first'], wi)
      w['win'].setdefault(wi, {})[s] = [round(i, 6), round(o, 6), round(f, 6), round(b, 6), (note or '')[:90]]
  for a, w in W.items():
    if w['frozen'] and w['role'] == 'layering': w['role'] = 'frozen'
  links = defaultdict(lambda: [0.0, 0.0, 0, set()])            # (frm, to) -> [TRX, USDT, txs, windows]
  exits = defaultdict(lambda: [0.0, 0.0, 0, set()])            # (frm, endpoint) -> ...
  exit_rows = defaultdict(lambda: [0.0, 0, set(), ''])          # (category, dest, asset) -> [amt, txs, windows, detail]
  inflow = defaultdict(lambda: [0.0, 0.0, 0, set()])           # (outside sender, wallet)
  parent = defaultdict(lambda: defaultdict(float)); thru = defaultdict(float)
  top_tx = defaultdict(list); by_win_cat = defaultdict(float)
  for wi, (r, _) in enumerate(chain):
    nb = nodes_by_run[r]
    for h, ts, f, t, s, v, cls, det in C.execute('SELECT hash, ts, frm, too, asset, amount, cls, detail FROM ledger_edge WHERE run_id=?', (r,)):
      k = 0 if s == 'TRX' else 1; usd = v * PX[s]
      if cls == 'out:attacker':
        L = links[(f, t)]; L[k] += v; L[2] += 1; L[3].add(wi); parent[t][f] += usd; thru[f] += usd
        top_tx[f].append((usd, h, t, s, v))
      elif cls.startswith('out:') and t not in nb:
        cat = category(cls, t, det)
        ep = f'X:{cat}' if (cat != 'External wallets' or usd < 0) else f'X:ext:{t}'
        X = exits[(f, ep)]; X[k] += v; X[2] += 1; X[3].add(wi); thru[f] += usd
        R = exit_rows[(cat, t, s)]; R[0] += v; R[1] += 1; R[2].add(wi); R[3] = det or ''
        if cat != 'Swaps (churn)': by_win_cat[(wi, cat)] += usd
        top_tx[f].append((usd, h, t, s, v))
      elif cls == 'in:root':
        I = inflow[('SRC', t)]; I[k] += v; I[2] += 1; I[3].add(wi)
      elif cls == 'in:foreign' and f not in nb and v >= 1 and f not in NOT_OUTSIDE:
        I = inflow[(f, t)]; I[k] += v; I[2] += 1; I[3].add(wi)
  ext_tot = defaultdict(float)
  for (cat, t, s), (v, n, ws, d) in exit_rows.items():
    if cat == 'External wallets': ext_tot[t] += v * PX[s]
  for (f, ep), X in list(exits.items()):                       # small external destinations share one node
    if ep.startswith('X:ext:') and ext_tot[ep[6:]] < 50000:
      Y = exits[(f, 'X:External wallets')]; Y[0] += X[0]; Y[1] += X[1]; Y[2] += X[2]; Y[3] |= X[3]; del exits[(f, ep)]
  out_tot = defaultdict(float)
  for (f, t), I in inflow.items(): out_tot[f] += I[0] * PX['TRX'] + I[1]
  last = chain[-1][0]
  held = {s: (h or 0, z or 0) for s, h, z in C.execute('SELECT asset, SUM(CASE WHEN frozen=0 THEN bal ELSE 0 END), SUM(CASE WHEN frozen=1 THEN bal ELSE 0 END) FROM ledger_node WHERE run_id=? GROUP BY asset', (last,))}
  stolen = {s: v for s, v in C.execute("SELECT asset, SUM(amount) FROM ledger_edge WHERE run_id=? AND cls='in:root' GROUP BY asset", (chain[0][0],))}
  pay = []
  for wi, (r, _) in enumerate(chain):
    for p in payouts(r): p['win'] = wi; pay.append(p)
  # tree wallets that sweep >=90% of their outflow into one service are that service's DEPOSIT addresses, not launderer wallets
  sw = defaultdict(lambda: defaultdict(float))
  for (f, ep), X in exits.items(): sw[f][ep] += X[0] * PX['TRX'] + X[1]
  for (f, t), L in links.items(): sw[f]['int'] += L[0] * PX['TRX'] + L[1]
  DEP = {}
  for a, o in sw.items():
    tot = sum(o.values())
    for ep, v in o.items():
      if tot > 100 and v >= 0.9 * tot and ep in (f'X:ext:{CH}', 'X:ChangeHero', f'X:ext:{UNL}', 'X:Bitget Wallet Swap Bridge'):
        DEP[a] = 'ChangeHero deposit address' if CH in ep or 'ChangeHero' in ep else 'Bitget Wallet Swap Bridge deposit address'
        if a in W: W[a]['role'] = 'service deposit address'
  for a, w in W.items():
    if parent[a]: w['parent'] = max(parent[a].items(), key=lambda x: x[1])[0]
    w['thru'] = round(thru[a], 2); w['held'] = [round(w['win'].get(len(chain) - 1, {}).get(s, [0, 0, 0, 0])[3], 6) if a in nodes_by_run[last] else 0 for s in ('TRX', 'USDT')]
    w['tx'] = [[round(u, 2), h, t, s, round(v, 6)] for u, h, t, s, v in sorted(top_tx[a], reverse=True)[:8]]
  # ---- every address involved + labels, every booked transaction (Wallets / Txs tabs) ----
  A, idx = [], {}
  def ix(a):
    if a not in idx: idx[a] = len(A); A.append(a)
    return idx[a]
  CLS, cix = [], {}
  def cx(c):
    if c not in cix: cix[c] = len(CLS); CLS.append(c)
    return cix[c]
  txs, kind, recv, sent, ntx, cname = [], {}, defaultdict(float), defaultdict(float), defaultdict(int), {}
  for wi, (r, _) in enumerate(chain):
    nb = nodes_by_run[r]
    for h, ts, f, t, s, v, cls, det in C.execute('SELECT hash, ts, frm, too, asset, amount, cls, detail FROM ledger_edge WHERE run_id=?', (r,)):
      if cls == 'fee' or cls == 'in:dust' or v <= 0: continue
      if cls.startswith('in:') and f in nb: continue                     # internal transfer: already booked by the sender's out row
      usd = v * PX[s]
      if cls.startswith('out:') and t not in nb:
        cat = category(cls, t, det); kind.setdefault(t, 'exit'); cname.setdefault(t, 'JustLend TRX vault (pass-through)' if t == JTRXV else cat if cat != 'Other contracts' or not det else det)
        recv[t] += usd
      elif cls.startswith('in:') and f not in nb:
        kind.setdefault(f, 'source' if f == SOURCE else 'outside' if cls == 'in:foreign' else 'service'); sent[f] += usd
      ntx[f] += 1; ntx[t] += 1
      txs.append([h, int(ts / 1000), ix(f), ix(t), 0 if s == 'TRX' else 1, round(v, 6), cx(cls[cls.index(':') + 1:]), wi, (det or '')[:60] if cls == 'out:thorchain' else ''])
  for a in W: ix(a)
  lab = {}
  try:
    AT = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/attrib.db') + '?mode=ro', uri=True)
    for a, n, c in AT.execute('SELECT a.address, e.name, a.category FROM attrib a JOIN entity_ref e ON e.id=a.entity_id'):
      if a in idx: lab.setdefault(a, f'{n} ({c})')
  except Exception: pass
  try:
    LB = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/labels.db') + '?mode=ro', uri=True)
    for a, n, t, c in LB.execute('SELECT address, name, nameTag, category FROM labels'):
      if a in idx: lab.setdefault(a, ' · '.join(x for x in (n, t, c) if x))
  except Exception: pass
  try:
    PR = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/por-wallets.db') + '?mode=ro', uri=True)
    for a, e, w in PR.execute('SELECT address, exchange, wallet_type FROM por_wallets'):
      if a in idx: lab.setdefault(a, f'{e} ({w})')
  except Exception: pass
  CONTRACTS = {'TKWqpzNucNNBMpfaE47F8CLhA8vzfNndH4': 'Meson (directExecuteSwap)', 'TX2Ut1reF59i2WPzsYVoMfA25EkUkavnd5': 'deBridge DLN (createSaltedOrder)',
               'TTRmy12BMrWt68drXQfn3YpC8B5TVFuyyW': 'Hyperlane warp route (transferRemote)', 'TZ9grqg3LwBKiddGra3WGHPdddJz3tow8N': 'Wanchain bridge CrossProxy (userLock)',
               'TWPziSAroSacAjDuL52ByQzU86s9mP2gPr': 'LayerZero OftBridge', 'TSkq7SwpgNt7jHtRtCZVVAfVMnEhzezMRL': 'HieSwap',
               'TB6QHSqmof2ssxoKkWwabTbvDbCxydZ23a': 'Tron_PrefundedAdapter (unidentified, store())', 'TMviNfNmwfefUXdhGQaDzbo5NiEVTZTqHM': 'OnchainGateway (unidentified, onswap())',
               'TXtEs6t2oUWQsNos7m68gbHdE9Q5n6x2oN': 'unidentified bridge (depositErc20)', 'TZG47zhb8kcriWQ2rE719yHs1KqgzwMrvF': 'Bitget Wallet: Swap Bridge',
               'TKfz7Pu3jtxWrfHzVeozQjXsb3RfuUHGE2': 'ChangeHero hot wallet',
               'TFGDbUyP8xez44C76fin3bn3Ss6jugoUwJ': 'SunSwap v1 USDT-TRX pool (S-USDT-TRX)',
               'TX5XiRXdyz7sdFwF5mnhT1QoGCpbkncpke': 'unlabelled busy service (EOA, ~2.7M txs)', 'TCPPRajgXVBkR5Qvpd3RHh4xUvibhzrqSa': 'unlabelled busy service (EOA, ~664k txs)',
               'TErYb1JEuEmxs31XUFcieCbygVHhPrPZAN': 'likely energy/bandwidth rental (tiny fee payments)', 'TKzuFJfw8YcCmLhmmT85ccwZFyYefoaTUz': 'likely energy/bandwidth rental (tiny fee payments)',
               'TLgTYgG5bD9crpYqVED3MGvWuAUvdoFYEa': 'likely energy/bandwidth rental (tiny fee payments)', 'TYahQiPuzkLtqF87JDrz6sMjLCWwWtQXxB': 'likely energy/bandwidth rental (tiny fee payments)'}
  def label(a):
    if a in ROLES: return ROLES[a]
    if a in CONTRACTS: return CONTRACTS[a]
    if a == SOURCE: return 'Binance (victim)'
    if a == TEC: return 'Chainflip vault (Tron)'
    if a in ENDPOINT: return ENDPOINT[a]
    if a in VAULTS or a in ('TH1YKH9MUuJtDmekPia4x9fZXAcpPrMv8B', 'TLKfB2goHRY1SykEpVbiGdsesACrkCxCeW'): return 'THORChain vault'
    if a in lab: return lab[a]
    if cname.get(a) == 'Chainflip' and a != TEC: return 'Chainflip deposit channel'
    if a in DEP: return DEP[a]
    if a in W: return W[a]['role']
    return '' if cname.get(a) in (None, 'External wallets', 'Other contracts') else cname[a]
  for a in list(kind):                                   # known routers / pools / vaults are services, whatever side they were seen on
    if a in NOT_OUTSIDE or a in ENDPOINT or a in VAULTS: kind[a] = 'service'
  wl = []
  for i, a in enumerate(A):
    w = W.get(a)
    wl.append([i, label(a), 'operator' if w else kind.get(a, 'counterparty'), (w or {}).get('created', ''),
               (w or {}).get('first', -1), round(w['thru'] if w else recv[a] + sent[a], 2),
               (w or {}).get('held', [0, 0])[0] if w else 0, (w or {}).get('held', [0, 0])[1] if w else 0, ntx[a],
               1 if (w or {}).get('frozen') else 0])
  data = {
    'addr': A, 'cls': CLS, 'txs': txs, 'wl': wl,
    'built': time.strftime('%F %T UTC', time.gmtime()), 'windows': wins, 'px': PX,
    'wallets': list(W.values()),
    'links': [[f, t, round(L[0], 6), round(L[1], 6), L[2], sorted(L[3])] for (f, t), L in links.items()],
    'exits': [[f, ep, round(X[0], 6), round(X[1], 6), X[2], sorted(X[3])] for (f, ep), X in exits.items()],
    'inflows': [[f if (f == 'SRC' or out_tot[f] >= 10000) else 'O:small', t, round(I[0], 6), round(I[1], 6), I[2], sorted(I[3])] for (f, t), I in inflow.items()],
    'exit_rows': sorted([[cat, t, s, round(v, 6), n, sorted(ws), d] for (cat, t, s), (v, n, ws, d) in exit_rows.items() if cat != 'Swaps (churn)'], key=lambda r: -r[3] * PX[r[2]]),
    'payouts': pay, 'stolen': stolen, 'held': held, 'bridge_out': bridge_out(C, [r for r, _ in chain]),
    'accounting': json.load(open(os.path.join(HERE, 'raw', 'tron', 'exit_accounting.json'))) if os.path.exists(os.path.join(HERE, 'raw', 'tron', 'exit_accounting.json')) else None,
    'by_win_cat': [[wi, cat, round(v, 2)] for (wi, cat), v in by_win_cat.items()],
  }
  return data

def build():
  data = collect(); W = data['wallets']
  os.makedirs(os.path.dirname(OUT), exist_ok=True)
  html = open(os.path.join(HERE, 'tron_graph_template.html')).read()
  html = html.replace('/*__ECHARTS__*/', open(os.path.join(os.path.dirname(OUT), 'echarts-5.5.1.min.js')).read())   # inlined: works offline
  html = html.replace('/*__DATA__*/null', public(json.dumps(safe(data), separators=(',', ':'))))
  # credit avatar: raw/tron/graph/avatar.(jpg|jpeg|png|webp) embedded as a data URI; else a neutral initial
  import base64, glob
  av = sorted(glob.glob(os.path.join(os.path.dirname(OUT), 'avatar.*')))
  if av:
    ext = av[0].rsplit('.', 1)[1].lower(); mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else f'image/{ext}'
    uri = f'data:{mime};base64,' + base64.b64encode(open(av[0], 'rb').read()).decode()
  else:
    uri = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><circle cx='12' cy='12' r='12' fill='%2352514e'/><text x='12' y='16.5' text-anchor='middle' font-family='Helvetica,Arial' font-size='12' font-weight='700' fill='white'>S</text></svg>"
  html = html.replace('/*__AVATAR__*/', uri)
  open(OUT, 'w').write(html)
  return OUT, len(W), len(data['links']), len(data['exits'])

if __name__ == '__main__':
  print('wrote %s | %d wallets, %d merged links, %d exit links' % build())
