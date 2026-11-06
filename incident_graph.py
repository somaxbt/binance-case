"""Binance case — WHOLE-INCIDENT graph: every chain on one page, each built from that chain's ledger.
  python3 incident_graph.py        writes raw/graph/binance_fund_flow.html (called after ledger runs)
Every chain dataset has one schema (any set of assets): wallets (per-window ledger rows), merged wallet->wallet links,
exits, outside inflows, exit rows, booked transactions, labelled address list. The 'All' view adds per-chain totals and
the cross-chain hops (bridge deposit on one chain matched to its payout on another). USD = theft-time display prices."""
import json, os, re, sqlite3, time, base64, glob
from collections import defaultdict
import tron_graph as TGR

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'raw', 'graph', 'binance_fund_flow.html')
ECH = os.path.join(HERE, 'raw', 'tron', 'graph', 'echarts-5.5.1.min.js')
AVATAR = os.path.join(HERE, 'raw', 'tron', 'graph', 'avatar.jpg')
PX = {'TRX': 0.331, 'USDT': 1.0, 'USDC': 1.0, 'USDt': 1.0, 'USDT0': 1.0, 'ETH': 2313.26, 'WETH': 2313.26, 'BTC': 80244.08,
      'XRP': 1.270179, 'SOL': 99.03, 'AVAX': 8.744, 'OP': 0.1083, 'POL': 0.09156, 'MATIC': 0.09156, 'VIRTUAL': 0.59, 'ARB': 0.168,
      'NEAR': 4.3991, 'BNB': 744.12}                    # 11-05: NEAR + BNB = DefiLlama coingecko price at 10-29 20:00 UTC (T0)
T0 = 1793304000  # 2026-10-29 20:00 UTC
ro = lambda p: sqlite3.connect(f'file:{os.path.join(HERE, p)}?mode=ro', uri=True)
fmt_t = lambda s: time.strftime('%m-%d %H:%M', time.gmtime(s))

def blank(cid, name, native, addr_url, tx_url):
  return {'id': cid, 'name': name, 'native': native, 'addr_url': addr_url, 'tx_url': tx_url, 'assets': [], 'px': {}, 'windows': [],
          'wallets': [], 'links': [], 'exits': [], 'inflows': [], 'exit_rows': [], 'payouts': [], 'stolen': {}, 'held': {},
          'by_win_cat': [], 'addr': [], 'cls': [], 'txs': [], 'wl': [], 'note': '', 'status': 'unmoved'}

# ------------------------------------------------------------------ TRON (existing ledger chain; already the richest)
def tron():
  d = TGR.collect()
  g = blank('tron', 'Tron', 'TRX', 'https://tronscan.org/#/address/{}', 'https://tronscan.org/#/transaction/{}')
  g['assets'] = ['TRX', 'USDT']; g['px'] = {'TRX': PX['TRX'], 'USDT': 1.0}
  am = lambda tr, us: {k: v for k, v in (('TRX', tr), ('USDT', us)) if v}
  usd = lambda tr, us: round(tr * PX['TRX'] + us, 2)
  for w in d['wallets']: w['held'] = {k: v for k, v in zip(('TRX', 'USDT'), w['held']) if v}
  g['wallets'] = d['wallets']
  for k in ('links', 'exits', 'inflows'):
    g[k] = [[f, t, usd(tr, us), am(tr, us), n, ws] for f, t, tr, us, n, ws in d[k]]
  for k in ('exit_rows', 'payouts', 'stolen', 'held', 'by_win_cat', 'addr', 'cls', 'txs', 'windows', 'bridge_out', 'accounting'): g[k] = d[k]
  g['wl'] = [[i, lab, ty, cr, fi, mv, {k: v for k, v in (('TRX', ht), ('USDT', hu)) if v}, n, fz] for i, lab, ty, cr, fi, mv, ht, hu, n, fz in d['wl']]
  g['status'] = 'laundering'
  return g

# ------------------------------------------------------------------ EVM ledgers (Ethereum + side chains; eth_node/eth_edge)
EVM_CAT = {'dex': 'Swaps (churn)', 'contract': 'Swaps (churn)', 'swap': 'Swaps (churn)', 'defi': 'DeFi (Aave)', 'lending': 'DeFi (Aave)',
           'bridge': 'Bridges', 'burn': 'Burned / seized', 'service': 'Services', 'external': 'External wallets'}
VICTIM_LABEL = {'0x28c6c06298d514db089934071355e5743bf21d60': 'Binance 14 (victim)', '0xdfd5293d8e347dfe59e90efd55b2956a1343963d': 'Binance 16 (victim)'}
EVM_ROLES = {'0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c': 'theft collection wallet', '0x7c8601d4645b93cea45f71e118a729332e6b5ca0': 'operator',
             '0xa97bf7836f8a08f9ed91d41453d371493fae8d10': 'theft collection wallet (late sweeps)', '0x8d53903625b8e839b9df4bd28b0efb1cd6b8639a': 'Aave position',
             '0x294828705974ad04d86a24a2ff6efe762505a0ed': 'holding wallet (AVAX proceeds)'}

def evm(cid, name, native, db, addr_url, tx_url, prices, base_block=None, note=''):
  C = ro(db)
  runs = [(r, json.loads(p or '{}'), st, fi) for r, p, st, fi in C.execute("SELECT run_id, params, started, finished FROM ledger_run ORDER BY started")
          if fi and not str(fi).startswith(('ABANDONED', 'STOPPED')) and not str(json.loads(p or '{}').get('status', '')).startswith('INVALID') and C.execute('SELECT 1 FROM eth_node WHERE run_id=? LIMIT 1', (r,)).fetchone()]
  g = blank(cid, name, native, addr_url, tx_url); g['note'] = note
  if not runs: g['status'] = 'no ledger'; return g
  run, P, started, finished = runs[-1]
  cut = int(time.mktime(time.strptime(finished[:19], '%Y-%m-%dT%H:%M:%S')))       # ledger finish (local) ~ data cutoff
  g['windows'] = [{'run': run, 'from': fmt_t(T0), 'to': fmt_t(cut - time.timezone if False else cut)}]
  tracked = {a for (a,) in C.execute("SELECT DISTINCT asset FROM eth_edge WHERE run_id=? AND cls='in:victim'", (run,))} | {'ETH'}
  sym = {}
  for a, s in C.execute('SELECT DISTINCT asset, symbol FROM eth_node WHERE run_id=?', (run,)): sym[a] = s or a[:8]
  for a, s in C.execute('SELECT DISTINCT asset, symbol FROM eth_edge WHERE run_id=?', (run,)): sym.setdefault(a, s or a[:8])
  if 'ETH' in sym or 'ETH' in tracked: sym['ETH'] = native
  seen = {}
  for a in sorted(tracked):                                    # unique display names (homoglyph/duplicate symbols get a suffix)
    s = sym.get(a, a[:8]); s = s if s not in seen else f'{s}·{a[2:6]}'; seen[s] = a; sym[a] = s
  price = lambda a: prices.get(a) or prices.get(sym.get(a)) or 0.0          # unpriced tokens (e.g. IDRT) count as $0, shown in native units
  nodes = defaultdict(lambda: {'win': {0: {}}, 'frozen': 0})
  for a, asset, i, o, gas, b, res, fz, why in C.execute('SELECT address, asset, inn, out, gas, bal, resid, frozen, why FROM eth_node WHERE run_id=?', (run,)):
    if asset not in tracked: continue
    n = nodes[a]; n['win'][0][sym[asset]] = [round(i or 0, 6), round(o or 0, 6), round(gas or 0, 6), round(b or 0, 6), (why or '')[:90]]
    if fz: n['frozen'] = 1
  links = defaultdict(lambda: [0.0, defaultdict(float), 0]); exits = defaultdict(lambda: [0.0, defaultdict(float), 0])
  inflows = defaultdict(lambda: [0.0, defaultdict(float), 0]); exrows = defaultdict(lambda: [0.0, 0, ''])
  parent = defaultdict(lambda: defaultdict(float)); thru = defaultdict(float); top = defaultdict(list); bwc = defaultdict(float)
  A, ix = [], {}
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  CLS, cx = [], {}
  def c(k):
    if k not in cx: cx[k] = len(CLS); CLS.append(k)
    return cx[k]
  assets = sorted({sym[a] for a in tracked}, key=lambda s: (s != native, s))
  aidx = {s: i for i, s in enumerate(assets)}
  txs, kind, ntx, sells = [], {}, defaultdict(int), set()
  bt = lambda b: (1793325659 + (b - 26300753) * 12) if (base_block and b) else 0      # ETH block -> ~unix time (12 s blocks)
  for h, blk, f, t, asset, amt, cls, det in C.execute('SELECT hash, block, frm, too, asset, amount, cls, detail FROM eth_edge WHERE run_id=?', (run,)):
    if asset not in tracked or not amt or amt <= 0: continue
    s = sym[asset]; u = amt * price(asset)
    if cls == 'out:attacker' and t in nodes:
      L = links[(f, t)]; L[0] += u; L[1][s] += amt; L[2] += 1; parent[t][f] += u; thru[f] += u; top[f].append((u, h, t, s, amt))
    elif cls.startswith('out:') and t not in nodes:
      k = cls[4:]; cat = EVM_CAT.get(k, 'Other')
      if k in ('dex', 'contract'): sells.add(f)
      X = exits[(f, f'X:{cat}' if cat != 'External wallets' or u < 50000 else f'X:ext:{t}')]; X[0] += u; X[1][s] += amt; X[2] += 1; thru[f] += u
      R = exrows[(cat, t, s)]; R[0] += amt; R[1] += 1; R[2] = det or R[2]; kind.setdefault(t, 'exit'); top[f].append((u, h, t, s, amt))
      if cat != 'Swaps (churn)': bwc[(0, cat)] += u
    elif cls == 'in:victim':
      I = inflows[('SRC', t)]; I[0] += u; I[1][s] += amt; I[2] += 1; kind.setdefault(f, 'source')
    elif cls in ('in:other',) and f not in nodes and u >= 100:
      I = inflows[(f, t)]; I[0] += u; I[1][s] += amt; I[2] += 1; kind.setdefault(f, 'outside')
    else:
      continue
    if cls.startswith('in:') and f in nodes: continue
    ntx[f] += 1; ntx[t] += 1
    txs.append([h, bt(blk), x(f), x(t), aidx[s], round(amt, 6), c(cls.split(':', 1)[1]), 0, ''])
  W = []
  for a, n in nodes.items():
    held = {s: r[3] for s, r in n['win'][0].items() if r[3] > 0}
    hu = sum(v * prices.get(s, PX.get(s, 0)) for s, v in held.items())
    role = EVM_ROLES.get(a) or ('frozen' if n['frozen'] else 'holding wallet' if hu >= 1e6 else 'seller' if a in sells else 'layering')
    w = {'id': a, 'role': role, 'created': '', 'first': 0, 'win': n['win'], 'frozen': n['frozen'], 'thru': round(thru[a], 2), 'held': held,
         'tx': [[round(u, 2), h, t, s, round(v, 6)] for u, h, t, s, v in sorted(top[a], reverse=True)[:8]]}
    if parent[a]: w['parent'] = max(parent[a].items(), key=lambda kv: kv[1])[0]
    W.append(w); x(a)
  g.update({'assets': assets, 'px': {s: price(a) for a, s in sym.items() if a in tracked}, 'wallets': W,
            'links': [[f, t, round(L[0], 2), {k: round(v, 6) for k, v in L[1].items()}, L[2], [0]] for (f, t), L in links.items()],
            'exits': [[f, ep, round(X[0], 2), {k: round(v, 6) for k, v in X[1].items()}, X[2], [0]] for (f, ep), X in exits.items()],
            'inflows': [[f, t, round(I[0], 2), {k: round(v, 6) for k, v in I[1].items()}, I[2], [0]] for (f, t), I in inflows.items()],
            'exit_rows': sorted([[cat, t, s, round(v, 6), n, [0], d[:60]] for (cat, t, s), (v, n, d) in exrows.items() if cat != 'Swaps (churn)'],
                                key=lambda r: -r[3] * g['px'].get(r[2], 0) if False else -r[3]),
            'addr': A, 'cls': CLS, 'txs': txs, 'by_win_cat': [[wi, cat, round(v, 2)] for (wi, cat), v in bwc.items()]})
  st = defaultdict(float)
  for asset, amt in C.execute("SELECT asset, SUM(amount) FROM eth_edge WHERE run_id=? AND cls='in:victim' GROUP BY asset", (run,)): st[sym.get(asset, asset)] += amt
  g['stolen'] = dict(st)
  hd = defaultdict(lambda: [0.0, 0.0])
  for w in W:
    for s, v in w['held'].items(): hd[s][1 if w['frozen'] and s not in (native,) else 0] += v
  g['held'] = {k: v for k, v in hd.items()}
  for i, a in enumerate(A):
    w = next((y for y in W if y['id'] == a), None)
    lab = VICTIM_LABEL.get(a) or (w['role'] if w else '')
    g['wl'].append([i, lab, 'operator' if w else kind.get(a, 'counterparty'), '', 0 if w else -1, round(w['thru'] if w else 0, 2),
                    (w or {}).get('held', {}), ntx[a], (w or {}).get('frozen', 0)])
  g['status'] = 'moving' if (bwc or links) else 'unmoved'                 # any move out of the theft wallet counts, not only exits
  return g

# ------------------------------------------------------------------ EVM HyperSync tree ledgers (eth_hs.py: binance-bridged.db wallet/edge/node), 11-05
# One reader for ETH + every side chain at the common cutoff. Same output shape as evm(). Rules (RENDER.md C):
#  · stolen = inflows FROM a victim (Binance PoR on any chain + the ETH-ledger victims), whatever the ledger class
#  · ETH: held for the overview counts ONLY wallets whose origin includes 'ETH' — TRON / SOL / FBI-only wallets hold money that arrived
#    from Tron/Solana (already 'Moved to Ethereum' there; FBI-only wallets were 82% Tron-funded). They are still drawn in the tab.
#  · exits by ledger label: '(bridge)' → bridge name · dex/contract → swap churn (not an exit) · hub → Unidentified services · aged/external → External wallets
FROZEN_TOK = {'avax': {'0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7'}, 'polygon': {'0xc2132d05d31c914a87c6611c10748aeb04b58e8f'}}   # TRM / NOTES 10-30: frozen at 0x5227
HS_RUN = {}                                                    # cid → run_id override (else the CURRENT/valid run, as eth_hs.current_run)
TOKMETA = json.load(open(os.path.join(HERE, 'raw', 'evm_token_meta.json'))) if os.path.exists(os.path.join(HERE, 'raw', 'evm_token_meta.json')) else {}
def hs_victims():
  P = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db') + '?mode=ro', uri=True)
  V = {a for (a,) in P.execute("SELECT address_lc FROM por_wallets WHERE exchange='binance' AND address_lc LIKE '0x%'")}
  return V | {a for (a,) in ro('binance-eth-ledger.db').execute("SELECT DISTINCT frm FROM eth_edge WHERE cls='in:victim'")}
def hs_cat(label):
  l = label or ''
  m = re.match(r'^(.*) \((\w+)\)$', l)
  if m and m.group(1).strip().lower() == m.group(2).lower():                # generic old-ledger class carried as 'x (x)'
    return {'bridge': 'Bridges', 'other': 'Other', 'defi': 'DeFi', 'dex': 'Swaps (churn)', 'contract': 'Swaps (churn)', 'swap': 'Swaps (churn)', 'service': 'Services', 'lending': 'DeFi (lending)', 'mixer': 'Mixers'}.get(m.group(2).lower(), m.group(2).title())
  if l.endswith('(mixer)'): return l[:-len('(mixer)')].strip().split(' router')[0].title().replace('Tornado Cash', 'Tornado Cash') + ' (mixer)'
  if 'victim' in l: return 'Returned to Binance'
  if l.endswith('(dex)') or l.startswith('contract'): return 'Swaps (churn)'
  if '(bridge)' in l: return l.split(':')[0].split(' (')[0].strip()
  if '(defi)' in l or 'Aave' in l: return 'DeFi (Aave)' if 'Aave' in l else l.split(':')[0].strip()
  if '(cex)' in l or '(exchange)' in l: return l.split(':')[0].split(' (')[0].strip() + ' (exchange)'
  if l.startswith('hub'): return 'Unidentified services'
  if l in ('lending',) or 'lending' in l: return 'DeFi (lending)'
  if 'defi' in l.lower(): return 'DeFi'
  if l in ('other',): return 'Other'
  if l in ('service',): return 'Services'
  if l.startswith(('aged', 'external', 'endpoint')) or not l: return 'External wallets'
  return l.split(':')[0].split(' (')[0].strip() or 'Other'
hs_word = lambda k: k.replace('seed/bridge', 'arrival / swap output').replace(' (seed)', '')   # internal ledger words never reach the page (RENDER.md D)
def evm_hs(cid, name, native, addr_url, tx_url, prices, note=''):
  C = ro('binance-bridged.db')
  run = HS_RUN.get(cid) or (C.execute(f"SELECT run_id FROM run WHERE finished GLOB '2026*' AND params NOT LIKE '%validation%' AND params NOT LIKE '%INVALID%' AND params NOT LIKE '%aborted%' "
                                      f"AND params NOT LIKE '%superseded%' AND (run_id LIKE '{cid}-hs-full-%' OR run_id LIKE '{cid}-hs-inc-%') ORDER BY started DESC LIMIT 1").fetchone() or [None])[0]
  g = blank(cid, name, native, addr_url, tx_url); g['note'] = note
  if not run: g['status'] = 'no ledger'; return g
  V = hs_victims(); meta = TOKMETA.get(cid, {})
  W0 = {a: (st, set(filter(None, (o or '').split(','))), lab) for a, st, o, lab in C.execute('SELECT address, status, origin, label FROM wallet WHERE run_id=?', (run,))}
  tree = {a for a, (st, o, l) in W0.items() if st == 'tree'}
  # wallets whose holdings count for THIS chain in the overview: descended from this chain's own theft root (origin tag ETH / AVAX / ARB …);
  # KEY / TRON / SOL / FBI-only wallets hold money that arrived from another chain (counted there as 'moved'). No theft on a chain → nothing counts.
  side = {a for a in tree if ('ETH' if cid == 'eth' else cid.upper()) in W0[a][1]}
  frozen = {(a, t) for a in tree for t in FROZEN_TOK.get(cid, ())}           # side chains: issuer-frozen stables (USDt AVAX, USDT0 Polygon at 0x5227)
  if cid == 'eth':                                                       # issuer-frozen balances (old theft ledger flags: USDT/USDC blacklist checks)
    frozen = set(); O = ro('binance-eth-ledger.db'); r0 = O.execute("SELECT run_id FROM ledger_run WHERE leg='eth2' AND finished GLOB '2026*' ORDER BY started DESC LIMIT 1").fetchone()[0]
    frozen = {(a, t) for a, t in O.execute('SELECT address, asset FROM eth_node WHERE run_id=? AND frozen=1', (r0,))}
  sym, seen = {}, {}
  for a in sorted({x for (x,) in C.execute('SELECT DISTINCT asset FROM node WHERE run_id=? UNION SELECT DISTINCT asset FROM edge WHERE run_id=?', (run, run))}):
    s0 = native if not a.startswith('0x') else ((meta.get(a) or {}).get('symbol') or a[:8])
    s1 = s0 if s0 not in seen else f'{s0}·{a[2:6]}'; seen[s1] = a; sym[a] = s1
  price = lambda a: prices.get(a) or PX.get(sym.get(a, a)) or (1.0 if str(sym.get(a, a)).upper().startswith('USD') else 0.0)
  nodes = defaultdict(lambda: {'win': {0: {}}, 'frozen': 0})
  for a, asset, i, o, gas, der, live, un in C.execute('SELECT address, asset, inn, out, gas, derived, live, unexplained FROM node WHERE run_id=?', (run,)):
    if a not in tree: continue
    n = nodes[a]; n['win'][0][sym[asset]] = [round(i or 0, 6), round(o or 0, 6), round(gas or 0, 6), round(live or 0, 6), '']
    if (a, asset) in frozen and (live or 0) > 0: n['frozen'] = 1
  links = defaultdict(lambda: [0.0, defaultdict(float), 0]); exits = defaultdict(lambda: [0.0, defaultdict(float), 0])
  inflows = defaultdict(lambda: [0.0, defaultdict(float), 0]); exrows = defaultdict(lambda: [0.0, 0, ''])
  parent = defaultdict(lambda: defaultdict(float)); thru = defaultdict(float); top = defaultdict(list); bwc = defaultdict(float)
  A, ix, CLS, cx = [], {}, [], {}
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  def c(k):
    if k not in cx: cx[k] = len(CLS); CLS.append(k)
    return cx[k]
  assets = sorted({sym[a] for a in sym}, key=lambda s_: (s_ != native, s_)); aidx = {s_: i for i, s_ in enumerate(assets)}
  txs, kind, ntx, sells, st, exside = [], {}, defaultdict(int), set(), defaultdict(float), defaultdict(float)
  t_at = lambda b: 0
  # 'out:external' = receiver eth_hs never classified (only receivers of TREE-SIGNED txs are; solver-submitted trades — CoW, 1inch Fusion — pay
  # contracts it never screened). Name them like the live page did: label store (same chain) → old theft-ledger class → External wallets.
  extx = sorted({t for (t,) in C.execute("SELECT DISTINCT too FROM edge WHERE run_id=? AND cls='out:external'", (run,))}); EXT = {}
  if extx:
    AT = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/attrib.db') + '?mode=ro', uri=True); ach = {'eth': 'eth', 'arb': 'arb', 'opt': 'opt', 'base': 'base', 'bsc': 'bsc'}.get(cid)
    for i in range(0, len(extx), 500):
      part = extx[i:i + 500]
      for a_, e_, c_ in (AT.execute(f"SELECT address, entity, category FROM attrib_v WHERE chain=? AND address IN ({','.join('?' * len(part))})", [ach] + part) if ach else []):
        if c_ != 'hack': EXT.setdefault(a_, f'{e_} ({c_})')
    oldf = 'binance-eth-ledger.db' if cid == 'eth' else f'binance-{cid}-ledger.db'
    if os.path.exists(os.path.join(HERE, oldf)):
      OLDC = {'out:service': 'service', 'out:contract': 'contract', 'out:dex': 'contract', 'out:defi': 'lending', 'out:lending': 'lending', 'out:bridge': 'bridge (bridge)'}
      for a_, c_ in ro(oldf).execute('SELECT too, cls FROM eth_edge WHERE cls IN (%s)' % ','.join('?' * len(OLDC)), list(OLDC)):
        if a_ in extx: EXT.setdefault(a_, OLDC[c_])
  for h, blk, k_, f, t, asset, amt, cls in C.execute('SELECT hash, block, kind, frm, too, asset, amount, cls FROM edge WHERE run_id=?', (run,)):
    if not amt or amt <= 0: continue
    s_ = sym[asset]; u = amt * price(asset)
    if f in V and t in tree and cls.startswith('in:'):
      st[s_] += amt; I = inflows[('SRC', t)]; I[0] += u; I[1][s_] += amt; I[2] += 1; kind.setdefault(f, 'source')
    elif cls == 'tree':
      L = links[(f, t)]; L[0] += u; L[1][s_] += amt; L[2] += 1; parent[t][f] += u; thru[f] += u; top[f].append((u, h, t, s_, amt))
    elif cls.startswith('out:'):
      if cls == 'out:external' and t in EXT: cls = 'out:' + EXT[t]
      cat = hs_cat(cls[4:])
      if cat == 'Swaps (churn)': sells.add(f)
      X = exits[(f, f'X:{cat}' if cat != 'External wallets' or u < 50000 else f'X:ext:{t}')]; X[0] += u; X[1][s_] += amt; X[2] += 1; thru[f] += u
      R = exrows[(cat, t, s_)]; R[0] += amt; R[1] += 1; R[2] = cls[4:][:60]; kind.setdefault(t, 'exit'); top[f].append((u, h, t, s_, amt))
      if f in side: exside[(cat, s_)] += amt                                  # overview: only exits of this chain's own theft money (arrivals left on their source chain)
      if cat != 'Swaps (churn)' and f in side: bwc[(0, cat)] += u
    elif cls.startswith('in:') and cls != 'in:swap output (tree tx)' and u >= 100:
      I = inflows[(f, t)]; I[0] += u; I[1][s_] += amt; I[2] += 1; kind.setdefault(f, 'outside')
    else: continue
    ntx[f] += 1; ntx[t] += 1
    txs.append([h, t_at(blk), x(f), x(t), aidx[s_], round(amt, 6), c(hs_word(cls.split(':', 1)[1] if ':' in cls else cls)), 0, ''])
  W = []
  for a, n in nodes.items():
    held = {s_: r[3] for s_, r in n['win'][0].items() if r[3] > 0}
    if not ntx[a] and not held: continue                                   # same-key seed with no activity on this chain: not an attacker wallet HERE
    hu = sum(v * price(seen.get(s_, s_)) for s_, v in held.items())
    o = W0[a][1]
    role = EVM_ROLES.get(a) or ('frozen' if n['frozen'] else 'holding wallet' if hu >= 1e6 else 'seller' if a in sells else
                                'arrival from Tron' if cid == 'eth' and 'TRON' in o and 'ETH' not in o else 'arrival from Solana' if cid == 'eth' and 'SOL' in o and 'ETH' not in o else 'layering')
    w = {'id': a, 'role': role, 'created': '', 'first': 0, 'win': n['win'], 'frozen': n['frozen'], 'thru': round(thru[a], 2), 'held': held,
         'tx': [[round(u, 2), h, t, s_, round(v, 6)] for u, h, t, s_, v in sorted(top[a], reverse=True)[:8]]}
    if parent[a]: w['parent'] = max(parent[a].items(), key=lambda kv: kv[1])[0]
    W.append(w); x(a)
  g.update({'assets': assets, 'px': {s_: price(a) for a, s_ in sym.items()}, 'wallets': W,
            'links': [[f, t, round(L[0], 2), {k: round(v, 6) for k, v in L[1].items()}, L[2], [0]] for (f, t), L in links.items()],
            'exits': [[f, ep, round(X[0], 2), {k: round(v, 6) for k, v in X[1].items()}, X[2], [0]] for (f, ep), X in exits.items()],
            'inflows': [[f, t, round(I[0], 2), {k: round(v, 6) for k, v in I[1].items()}, I[2], [0]] for (f, t), I in inflows.items()],
            'exit_rows': sorted([[cat, t, s_, round(v, 6), n, [0], d[:60]] for (cat, t, s_), (v, n, d) in exrows.items() if cat != 'Swaps (churn)'], key=lambda r: -r[3] * g['px'].get(r[2], 0)),
            'addr': A, 'cls': CLS, 'txs': txs, 'by_win_cat': [[wi, cat, round(v, 2)] for (wi, cat), v in bwc.items()], 'stolen': dict(st),
            'exit_rows_ov': [[cat, '', s_, round(v, 6), 0, [0], ''] for (cat, s_), v in exside.items() if cat != 'Swaps (churn)']})
  hd, ha = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
  for w in W:
    for s_, v in w['held'].items():
      k_ = 1 if w['frozen'] and s_ != native else 0; ha[s_][k_] += v
      if w['id'] in side and st: hd[s_][k_] += v                              # no theft on this chain (BSC) → nothing counts in the overview
  g['held_ov'] = {k: v for k, v in hd.items()}                            # overview: this chain's own theft money only (no double count)
  g['held'] = g['held_ov'] if st else {k: v for k, v in ha.items()}         # tab: own-theft view; a no-theft chain shows what its wallets hold
  b_ = C.execute('SELECT to_block FROM run WHERE run_id=?', (run,)).fetchone()[0]
  g['windows'] = [{'run': run, 'from': fmt_t(T0), 'to': '11-05 02:02'}]
  for i, a in enumerate(A):
    w = next((y for y in W if y['id'] == a), None)
    lab = VICTIM_LABEL.get(a) or (w['role'] if w else hs_word(W0.get(a, ('', set(), ''))[2] or ''))
    g['wl'].append([i, lab, 'operator' if w else kind.get(a, 'counterparty'), '', 0 if w else -1, round(w['thru'] if w else 0, 2), (w or {}).get('held', {}), ntx[a], (w or {}).get('frozen', 0)])
  if cid == 'eth':                                               # ETH → other chains: THORChain + vault/channel payouts (eth_thor_dest / eth_vault_dest), RENDER.md B
    BO, agg = [], defaultdict(float)
    for f_, via0 in (('eth_thor_dest.json', 'THORChain'), ('eth_vault_dest.json', None)):
      p_ = os.path.join(HERE, 'raw', f_)
      for h, r in (json.load(open(p_))['rows'].items() if os.path.exists(p_) else []):
        via = via0 or {'relay': 'Relay', 'chainflip': 'Chainflip', 'thorchain': 'THORChain', 'thor': 'THORChain'}.get(str(r.get('kind')).lower(), str(r.get('kind') or 'Bridge'))
        ok = str(r.get('status', '')).lower() in ('done', 'done+partial refund', 'completed', 'success')
        ch = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'BASE': 'Base', 'ZEC': 'Zcash', 'TRON': 'Tron'}.get(str(r.get('chain')), str(r.get('chain'))) if ok else 'refunded / failed'
        a_ = str(r.get('asset') or '').split('.')[-1] or 'ETH'; amt = float(r.get('amount') or 0) if ok else float(r.get('eth') or 0)
        BO.append([via, ch, r.get('address', '') if ok else '', a_ if ok else 'ETH', amt, round(amt * PX.get(a_, 1.0 if a_.startswith('USD') else 0), 2) if ok else 0,
                   'success' if ok else str(r.get('status')), h, r.get('from', ''), 0, r.get('out_tx', ''), 'ETH', float(r.get('eth') or 0)])
        if ok and r.get('address'): agg[(via, ch, a_)] += amt
    g['bridge_out'] = BO
    g['hops_out'] = [{'from': 'Ethereum', 'via': via, 'to': ch, 'asset': a_, 'amount': round(v, 8), 'usd': round(v * PX.get(a_, 1.0 if a_.startswith('USD') else 0), 2)}
                     for (via, ch, a_), v in agg.items() if PX.get(a_) or a_.startswith('USD')]
  g['status'] = 'moving' if (bwc or links) else 'unmoved'
  return g

# ------------------------------------------------------------------ NEAR (near_ledger.py tree: per-wallet flows + edges), 11-05
def near_tree():
  p = os.path.join(HERE, 'raw', 'near_ledger.json'); g = blank('near', 'NEAR', 'NEAR', 'https://explorer.near.org/accounts/{}', 'https://explorer.near.org/transactions/{}')
  if not os.path.exists(p): g['status'] = 'no ledger'; return g
  L = json.load(open(p)); px = PX['NEAR']; T = set(L['wallets']); EP = L.get('endpoints') or {}
  V = {l.strip() for l in open(os.path.join(HERE, 'raw', 'near', 'near_por.txt')) if l.strip()} if os.path.exists(os.path.join(HERE, 'raw', 'near', 'near_por.txt')) else set()
  g['assets'] = ['NEAR']; g['px'] = {'NEAR': px}; g['windows'] = [{'run': L['at'], 'from': fmt_t(T0), 'to': L['at'][5:16].replace('T', ' ')}]
  A, ix = [], {}
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  def ncat(a):
    lab = EP.get(a, '')
    return 'NEAR bridge (bridge-mng.near)' if a == 'bridge-mng.near' else 'NEAR Omni bridge' if a == 'omni.bridge.near' else 'Wrapped NEAR (wrap.near)' if a == 'wrap.near' else 'External wallets'
  links, exits, inflows, exrows, parent, thru, top, ntx, txs = (defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]),
                                                                defaultdict(lambda: defaultdict(float)), defaultdict(float), defaultdict(list), defaultdict(int), [])
  seen = set()
  for a, w in L['wallets'].items():
    for tx, ev, f, t, v in w['edges']:
      k = (tx, ev, f, t)
      if k in seen or not v or v <= 0: continue
      seen.add(k)
      if f in V: inflows[('SRC', t)][0] += v; inflows[('SRC', t)][1] += 1; cl = 'stolen'
      elif f in T and t in T: links[(f, t)][0] += v; links[(f, t)][1] += 1; parent[t][f] += v; thru[f] += v; top[f].append((v * px, tx, t, 'NEAR', v)); cl = 'tree'
      elif f in T: cat = ncat(t); exits[(f, 'X:' + cat)][0] += v; exits[(f, 'X:' + cat)][1] += 1; exrows[(cat, t)][0] += v; exrows[(cat, t)][1] += 1; thru[f] += v; top[f].append((v * px, tx, t, 'NEAR', v)); cl = 'exit'
      elif v * px >= 100: inflows[(f, t)][0] += v; inflows[(f, t)][1] += 1; cl = 'outside'
      else: continue
      ntx[f] += 1; ntx[t] += 1; txs.append([tx or '', 0, x(f), x(t), 0, round(v, 6), 0, 0, ''])
  W = []
  for a, w in L['wallets'].items():
    held = w['held']; x(a)
    W.append({'id': a, 'role': 'theft collection wallet' if a == L['root'] else 'holding wallet' if held * px >= 1e6 else 'layering', 'created': '', 'first': 0, 'frozen': 0,
              'thru': round(thru[a] * px, 2), 'held': {'NEAR': round(held, 6)} if held > 1e-6 else {},
              'win': {0: {'NEAR': [round(sum(v for k, v in w['ledger'].items() if k.startswith('in:')), 6), round(sum(v for k, v in w['ledger'].items() if k.startswith('out:')), 6),
                                   round(w['ledger'].get('fees', 0), 6), round(held, 6), f"unexplained {w['unexplained']:.6f}"]}},
              'tx': [[round(u, 2), h, t, s_, round(v, 6)] for u, h, t, s_, v in sorted(top[a], key=lambda z: -z[0])[:8]]})
    if parent[a]: W[-1]['parent'] = max(parent[a].items(), key=lambda kv: kv[1])[0]
  g.update({'wallets': W, 'addr': A, 'cls': ['transfer'], 'txs': txs,
            'links': [[f, t, round(v * px, 2), {'NEAR': round(v, 6)}, n, [0]] for (f, t), (v, n) in links.items()],
            'exits': [[f, ep, round(v * px, 2), {'NEAR': round(v, 6)}, n, [0]] for (f, ep), (v, n) in exits.items()],
            'inflows': [[f, t, round(v * px, 2), {'NEAR': round(v, 6)}, n, [0]] for (f, t), (v, n) in inflows.items()],
            'exit_rows': sorted([[cat, t, 'NEAR', round(v, 6), n, [0], (EP.get(t) or '')[:60]] for (cat, t), (v, n) in exrows.items()], key=lambda r: -r[3]),
            'by_win_cat': [[0, cat, round(sum(v for (c2, _), (v, n) in exrows.items() if c2 == cat) * px, 2)] for cat in {c2 for c2, _ in exrows}],
            'stolen': {'NEAR': round(L['stolen'], 6)}, 'held': {'NEAR': [round(L['held'], 6), 0]}, 'status': 'moving'})
  g['wl'] = [[i, next((w['role'] for w in W if w['id'] == a), 'Binance PoR (victim)' if a in V else EP.get(a, '')), 'operator' if a in T else 'source' if a in V else 'exit', '', 0 if a in T else -1,
              round(thru[a] * px, 2), next((w['held'] for w in W if w['id'] == a), {}), ntx[a], 0] for i, a in enumerate(A)]
  return g

# ------------------------------------------------------------------ BITCOIN (UTXO ledger)
def btc():
  C = ro('binance-btc-ledger.db'); run = C.execute('SELECT run_id FROM utxo ORDER BY run_id DESC LIMIT 1').fetchone()[0]
  g = blank('btc', 'Bitcoin', 'BTC', 'https://mempool.space/address/{}', 'https://mempool.space/tx/{}')
  g['assets'] = ['BTC']; g['px'] = {'BTC': PX['BTC']}; HOT = 'bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h'
  U = C.execute("SELECT txid, vout, address, sats, owner, status, spent_by FROM utxo WHERE run_id=?", (run,)).fetchall()
  kinds = dict(C.execute('SELECT txid, kind FROM btx WHERE run_id=?', (run,)).fetchall())
  ins = defaultdict(list)
  for txid, vout, ad, sats, own, st, sb in U:
    if sb: ins[sb].append((ad, sats))
  nodes, links, inflows, txs, A, ix, held = {}, defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]), [], [], {}, defaultdict(float)
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  for txid, vout, ad, sats, own, st, sb in U:
    if own != 'attacker': continue
    v = sats / 1e8; nodes.setdefault(ad, {'in': 0.0, 'out': 0.0})['in'] += v
    if st == 'unspent': held[ad] += v
    src = ins.get(txid) or ([(HOT, sats)] if 'drain' in kinds.get(txid, '') else [])
    f = src[0][0] if src else HOT
    if f == HOT: inflows[('SRC', ad)][0] += v; inflows[('SRC', ad)][1] += 1
    else: links[(f, ad)][0] += v; links[(f, ad)][1] += 1
    txs.append([txid, 0, x(f), x(ad), 0, round(v, 8), 0, 0, ''])
  for (f, t), (v, n) in links.items(): nodes.setdefault(f, {'in': 0.0, 'out': 0.0})['out'] += v
  g['cls'] = ['peel / split']
  W = []
  for a, n in nodes.items():
    W.append({'id': a, 'role': 'collection wallet' if a == 'bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm' else 'holding output' if held.get(a) else 'peel hop',
              'created': '', 'first': 0, 'frozen': 0, 'thru': round(n['out'] * PX['BTC'], 2), 'held': {'BTC': round(held[a], 8)} if held.get(a) else {},
              'win': {0: {'BTC': [round(n['in'], 8), round(n['out'], 8), 0, round(held.get(a, 0), 8), 'unspent' if held.get(a) else 'spent']}}, 'tx': []})
    x(a)
  g.update({'windows': [{'run': run, 'from': fmt_t(T0), 'to': 'pinned tip'}], 'wallets': W,
            'links': [[f, t, round(v * PX['BTC'], 2), {'BTC': round(v, 8)}, n, [0]] for (f, t), (v, n) in links.items()],
            'inflows': [[f, t, round(v * PX['BTC'], 2), {'BTC': round(v, 8)}, n, [0]] for (f, t), (v, n) in inflows.items()],
            'addr': A, 'txs': txs, 'stolen': {'BTC': round(sum(v for (f, t), (v, n) in inflows.items()), 8)}, 'held': {'BTC': [round(sum(held.values()), 8), 0]}})
  g['wl'] = [[i, 'Binance hot wallet (victim)' if a == HOT else next((w['role'] for w in W if w['id'] == a), ''), 'operator' if a in nodes else 'source', '', 0,
              round(nodes.get(a, {}).get('out', 0) * PX['BTC'], 2), {'BTC': round(held[a], 8)} if held.get(a) else {}, sum(1 for t in txs if A[t[2]] == a or A[t[3]] == a), 0]
             for i, a in enumerate(A)]
  return g

# ------------------------------------------------------------------ single-wallet ledgers (XRP, SOL)
def single(cid, name, native, path, holder, addr_url, tx_url):
  L = json.load(open(os.path.join(HERE, 'raw', path)))
  g = blank(cid, name, native, addr_url, tx_url); g['assets'] = [native]; g['px'] = {native: PX[native]}
  stolen = sum(v for k, v in L['sources'].items() if k.startswith('stolen')); held = L['live_balance']
  foreign = sum(v for k, v in L['sources'].items() if not k.startswith('stolen'))
  g['windows'] = [{'run': L['at'], 'from': fmt_t(T0), 'to': L['at'][5:16].replace('T', ' ')}]
  g['wallets'] = [{'id': holder, 'role': 'holding wallet', 'created': '', 'first': 0, 'frozen': 0, 'thru': 0, 'held': {native: held}, 'tx': [],
                   'win': {0: {native: [stolen + foreign, 0, 0, held, f"unexplained {L['unexplained']}"]}}}]
  g['inflows'] = [['SRC', holder, round(stolen * PX[native], 2), {native: stolen}, 1, [0]]]
  g['addr'] = [holder]; g['stolen'] = {native: stolen}; g['held'] = {native: [held, 0]}
  g['wl'] = [[0, 'holding wallet', 'operator', '', 0, 0, {native: held}, 1, 0]]
  return g

# ------------------------------------------------------------------ SOLANA (tree ledger from sol_ledger.py: per-wallet flows + tx edges)
# 11-03: service names follow the Tron tab (service node → drill to chain → wallets via bridge_out); internal ledger words never reach the page
SOL_EXIT = {'exit: Relay (solver)': 'Relay', 'exit: Layerswap': 'Layerswap', 'out: swap (DEX)': 'Swaps (churn)',
            'out: deposit Jupiter Lend': 'Swaps (churn)',                       # lend round trip: redeemed back into the tree, NOT an exit
            'exit: OKX (deposit address)': 'OKX (exchange)', 'exit: OKX': 'OKX (exchange)',
            # 11-05 SOL push: classes of the 02:02:23 ledger (internal words like 'mixpx' / '(mixer pool)' never reach the page)
            'exit: deBridge DLN': 'deBridge', 'exit: Chainflip (vault)': 'Chainflip', 'exit: Privacy Cash (mixer pool)': 'Privacy Cash (mixer)',
            'exit: shielded pool mixpx (mixer pool)': 'Shielded pool (mixer)', 'exit: privacy pool (unconfirmed) 7fs5cKGN': 'Privacy pool (unconfirmed)'}
SOL_LEDGER = os.path.join(HERE, 'raw', 'sol_ledger.json')                      # test builds point this at raw/sol_ledger_next.json
SOL_TOKX = {'out: burned': 'CCTP (Circle)', 'exit: Relay (solver)': 'Relay'}   # USDC/USDT exits of the token-aware ledger
def sol_cat(cls):
  return SOL_EXIT.get(cls) or ('External wallets' if cls.startswith('out: external') else 'Unidentified services' if cls.startswith('exit: mixed') else
                               'Swaps (output to be traced)' if cls == 'exit: swap → outside' else cls[6:])
def sol_tree():
  L = json.load(open(SOL_LEDGER))
  if L.get('kind') != 'tree': return single('sol', 'Solana', 'SOL', 'sol_ledger.json', L.get('root', ''), 'https://solscan.io/account/{}', 'https://solscan.io/tx/{}')
  g = blank('sol', 'Solana', 'SOL', 'https://solscan.io/account/{}', 'https://solscan.io/tx/{}'); px = PX['SOL']
  g['assets'] = ['SOL', 'USDC']; g['px'] = {'SOL': px, 'USDC': 1.0, 'USDT': 1.0}; T = set(L['wallets'])
  g['windows'] = [{'run': L['at'], 'from': fmt_t(T0), 'to': L['at'][5:16].replace('T', ' ')}]
  A, ix, CLS, cx = [], {}, [], {}
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  def c(k):
    if k not in cx: cx[k] = len(CLS); CLS.append(k)
    return cx[k]
  links, exits, inflows = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
  exrows, parent, thru, top, ntx, txs = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: defaultdict(float)), defaultdict(float), defaultdict(list), defaultdict(int), []
  # a swap is churn only if a tree wallet got its output in the same tx; else the output left the tree (11-03: 2.98M USDC hid as churn)
  GOT = {e[0] for e in L['edges'] if e[5] in ('swap (DEX)', 'swap output (tree tx)', 'redeem Jupiter Lend')} | \
        {e[0] for e in L.get('edges_tok') or [] if e[6] in ('in: swap (DEX)', 'in: swap output (tree tx)', 'swap output to tree wallet', 'in: lend receipt')}
  RET = defaultdict(float)                                    # money that came BACK from a service (mixer withdrawal, bridge refund) → net it off that exit
  for sig, t, f, to, v, cls in L['edges']:
    if cls.startswith(('withdrawal ', 'refund ')): RET[sol_cat('exit: ' + cls.split(' ', 1)[1])] += v
    if cls == 'out: swap (DEX)' and sig not in GOT: cls = 'exit: swap → outside'   # routed below as 'Swaps (output to be traced)'
    if cls == 'out: tree':
      links[(f, to)][0] += v; links[(f, to)][1] += 1; parent[to][f] += v; thru[f] += v; top[f].append((v * px, sig, to, 'SOL', v))
    elif cls in SOL_EXIT or cls.startswith(('exit:', 'out: external')):
      cat = sol_cat(cls)
      exits[(f, 'X:' + cat)][0] += v; exits[(f, 'X:' + cat)][1] += 1; exrows[(cat, to)][0] += v; exrows[(cat, to)][1] += 1
      thru[f] += v; top[f].append((v * px, sig, to, 'SOL', v))
    elif cls == 'stolen':
      inflows[('SRC', to)][0] += v; inflows[('SRC', to)][1] += 1
    elif v * px >= 100:                                       # foreign / Relay refunds / swap-backs entering the tree
      inflows[(f, to)][0] += v; inflows[(f, to)][1] += 1
    ntx[f] += 1; ntx[to] += 1
    txs.append([sig, t, x(f), x(to), 0, round(v, 9), c(cls.replace('out: ', '').replace('exit: ', '')), 0, ''])
  # token exits (USDC/USDT, USD = amount): CCTP burns, Relay, swaps whose output went to a wallet not traced yet
  tex, texr = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])          # (from, cat, asset) / (cat, to, asset)
  RETU, RETA = defaultdict(float), defaultdict(float)          # USD per route / native per (route, asset)
  for sig, t, f, to, v, a, cls in L.get('edges_tok') or []:
    if a not in ('USDC', 'USDT'): continue
    if cls in ('in: CCTP mint (dYdX return)', 'in: refund Relay (solver)'): RETU['CCTP (Circle)' if 'CCTP' in cls else 'Relay'] += v; RETA[('CCTP (Circle)' if 'CCTP' in cls else 'Relay', a)] += v
    cat = SOL_TOKX.get(cls) or ('Swaps (output to be traced)' if cls.startswith('out: external') or (cls == 'out: swap (DEX)' and sig not in GOT) else None)
    if not cat: continue
    tex[(f, cat, a)][0] += v; tex[(f, cat, a)][1] += 1; texr[(cat, to, a)][0] += v; texr[(cat, to, a)][1] += 1; thru[f] += v / px
    top[f].append((v, sig, to, a, v)); ntx[f] += 1; txs.append([sig, t, x(f), x(to), 0, round(v, 6), c(cls.replace('out: ', '').replace('exit: ', '')), 0, ''])
  # bridge_out rows, same shape as Tron: [via, dest chain, recipient, asset, amount out, USD, state, src tx, from, ts, out tx, src asset, src amount]
  pxa = lambda s: PX.get(s) or (1.0 if str(s).startswith('USD') else 0)
  BO = []; det = {}; hops = []
  # 11-05: one row per bridge order from the ledger's own 'bridges' list (Relay / Layerswap / Chainflip — matches its exit totals; the old
  # 'relay' list held 156 of 507 Relay rows) + deBridge DLN orders (raw/sol/debridge_dest.json, native ETH/BNB, 18 decimals)
  CN = {'ETHEREUM_MAINNET': 'Ethereum', 'AVAX_MAINNET': 'Avalanche', 'ARBITRUM_MAINNET': 'Arbitrum', 'BSC_MAINNET': 'BSC', 'BASE_MAINNET': 'Base', 'OPTIMISM_MAINNET': 'Optimism', 'TRON_MAINNET': 'Tron', 'SOLANA_MAINNET': 'Solana'}
  OKS = {'success', 'COMPLETED', 'completed', 'ClaimedUnlock', 'Fulfilled'}
  for r in L.get('bridges') or []:
    ok = r['status'] in OKS; via = {'relay': 'Relay', 'layerswap': 'Layerswap', 'chainflip': 'Chainflip'}.get(r['kind'], r['kind'])
    ch = ((TGR.CHAIN_NAME.get(int(r['chain']), f"chain {r['chain']}") if str(r['chain']).lstrip('-').isdigit() else CN.get(r['chain'], r['chain'])) if ok else 'refunded / failed')
    amt = float(r.get('amount') or 0)
    BO.append([via, ch, r['address'] if ok else '', r['asset'] if ok else 'SOL', amt if ok else r.get('sol', 0), round(amt * pxa(r['asset']), 2) if ok else 0,
               'success' if ok else r['status'], r.get('sig', ''), r.get('from', ''), 0, r.get('out_tx') or '', 'SOL', r.get('sol', 0)])
  DB_ = os.path.join(HERE, 'raw', 'sol', 'debridge_dest.json')
  for r in json.load(open(DB_)) if os.path.exists(DB_) else []:
    ok = r['status'] in OKS; tk = {'Ethereum': 'ETH', 'BSC': 'BNB'}.get(r['chain'], 'ETH') if r['asset'] == '0x' + '0' * 40 else r['asset']; amt = int(r['amount_raw'] or 0) / 1e18
    st = 'success' if ok else 'refund' if 'Cancel' in r['status'] else 'pending'
    BO.append(['deBridge', r['chain'] if ok else 'refunded / failed', r['address'] if ok else '', tk if ok else 'SOL', amt if ok else r.get('sol', 0), round(amt * pxa(tk), 2) if ok else 0,
               st, r.get('sig', ''), r.get('from', ''), 0, '', 'SOL', r.get('sol', 0)])
  BR, NF = os.path.join(HERE, 'raw', 'sol', 'burns_resolved.json'), os.path.join(HERE, 'raw', 'sol', 'noble_forwarding.json')
  if os.path.exists(BR):
    fw = json.load(open(NF)) if os.path.exists(NF) else {}
    for sig, t, frm, amt, dst, rc, st in json.load(open(BR)):
      if dst == 'Noble' and (fw.get(rc) or {}).get('recipient'): dst, rc = 'dYdX (via Noble)', fw[rc]['recipient']      # Noble forwarding account → IBC channel-33
      BO.append(['CCTP (Circle)', dst, rc, 'USDC', amt, round(amt, 2), st, sig, frm, t, '', 'USDC', amt])
  g['bridge_out'] = BO
  # 11-05: ACCOUNTING tab, same shape as Tron's exit_accounting.json — per route: sent / received [chain, asset, amount, recipients] /
  # refunded (refunds + mixer withdrawals + dYdX return) / fees / held_in_bridge / other / unresolved (None = no other side → 'n/a')
  RT = defaultdict(lambda: {'sent': defaultdict(float), 'received': [], 'refunded': defaultdict(float), 'fees': {}, 'held_in_bridge': {}, 'other': defaultdict(float), 'unresolved': None})
  for (cat, _), (v, n) in exrows.items():
    if cat != 'Swaps (churn)': RT[cat]['sent']['SOL'] += v
  for (cat, _, a), (v, n) in texr.items(): RT[cat]['sent'][a] += v
  for cat, v in RET.items(): RT[cat]['refunded']['SOL'] += v
  for (cat, a), v in RETA.items(): RT[cat]['refunded'][a] += v
  rec = defaultdict(lambda: [0.0, set()])
  for via, ch, rc, a, amt, usd_, st, *_ in BO:
    if via not in RT: continue
    if st in ('success', 'complete') and rc: rec[(via, ch, a)][0] += amt; rec[(via, ch, a)][1].add(rc)
    elif st == 'failure': RT[via]['other']['failure'] += amt * pxa(a)          # failed rows carry the SOL sent in 'amount'
    elif st == 'pending': RT[via]['unresolved'] = RT[via]['unresolved'] or defaultdict(float); RT[via]['unresolved'][a] += amt
  for (via, ch, a), (amt, rcs) in rec.items(): RT[via]['received'].append([ch, a, amt, len(rcs)])
  for cat, r in RT.items():
    if r['received'] and r['unresolved'] is None: r['unresolved'] = {}
  if 'CCTP (Circle)' in RT:                                    # USDC burned whose mint (destination) is not in burns_resolved.json yet
    c = RT['CCTP (Circle)']; left = sum(c['sent'].get(a, 0) for a in ('USDC',)) - c['refunded'].get('USDC', 0) - sum(x[2] for x in c['received'] if x[1] == 'USDC')
    c['unresolved'] = {'USDC': left} if left > 0.005 else {}
  g['accounting'] = {'built': L['at'][:16].replace('T', ' ') + ' UTC', 'routes': {k: {kk: (dict(vv) if isinstance(vv, defaultdict) else vv) for kk, vv in r.items()} for k, r in RT.items()},
                     'held': [['SOL', L['live_balance'], 0]] + [[t, v.get('held', 0), 0] for t, v in (L.get('tokens') or {}).items() if t in ('USDC', 'USDT') and v.get('held', 0) > 0.005]}
  agg = defaultdict(float)
  for r in BO:
    if r[6] in ('success', 'complete') and r[2]: agg[(r[0], r[1], r[3])] += r[4]
  for (via, ch, tk), v in agg.items():
    if not pxa(tk): continue                                  # unpriced token (11-05: 9.78M 'Jesus' on chain 4663 from 2.4 SOL) must not top a label
    hops.append({'from': 'Solana', 'via': via, 'to': ch, 'asset': tk, 'amount': round(v, 8), 'usd': round(v * pxa(tk), 2)})
    det[via] = (det.get(via, '→') + f' {v:,.4f} {tk} on {ch} ·')[:90]
  rs = [r for r in L.get('relay') or [] if r['status'] == 'success' and r['currency'] == 'BTC']
  g['hops_out'] = hops
  W = []
  for a, w in L['wallets'].items():
    fl = w['flows']; held = w['held']; x(a)
    win_in = sum(v for k, v in fl.items() if k.startswith('in')); win_out = sum(v for k, v in fl.items() if not k.startswith('in') and k not in ('fees', 'rent/dust', 'unattributed'))
    tree_out = fl.get('out: tree', 0); ex_out = sum(v for k, v in fl.items() if k.startswith('exit:'))
    role = ('theft collection wallet' if a == L['root'] else 'holding wallet' if held * px >= 1e6 else
            'distribution wallet' if tree_out > ex_out and tree_out * px >= 250000 else
            'Relay hop' if fl.get('exit: Relay (solver)') else 'Layerswap sender' if fl.get('exit: Layerswap') else 'layering')
    ww = {'id': a, 'role': role, 'created': '', 'first': (L.get('first_seen') or {}).get(a, 0), 'frozen': 0, 'thru': round(thru[a] * px, 2),
          'held': {'SOL': round(held, 9)} if held > 1e-6 else {},
          'win': {0: {'SOL': [round(win_in, 6), round(win_out, 6), round(fl.get('fees', 0) + fl.get('rent/dust', 0), 6), round(held, 6),
                              'mixed: outside inflow' if w.get('mixed') else f"unexplained {w['unexplained']:.6f}"]}},
          'tx': [[round(u, 2), h, t, s, round(v, 9)] for u, h, t, s, v in sorted(top[a], reverse=True)[:8]]}
    if parent[a]: ww['parent'] = max(parent[a].items(), key=lambda kv: kv[1])[0]
    W.append(ww)
  for k, v in RET.items(): det[k] = f'{v:,.2f} SOL came back into tree wallets (netted in the totals)'
  for k, v in RETU.items(): det[k] = (det.get(k, '') + ' · ' if k in RET else '') + f'{v:,.0f} USDC came back into tree wallets (netted in the totals)'
  usd = lambda v: round(v * px, 2)
  g.update({'wallets': W, 'addr': A, 'cls': CLS, 'txs': txs,
            'links': [[f, t, usd(v), {'SOL': round(v, 9)}, n, [0]] for (f, t), (v, n) in links.items()],
            'exits': [[f, ep, usd(v), {'SOL': round(v, 9)}, n, [0]] for (f, ep), (v, n) in exits.items()] +
                     [[f, 'X:' + cat, round(v, 2), {a: round(v, 6)}, n, [0]] for (f, cat, a), (v, n) in tex.items()],
            'inflows': [[f, t, usd(v), {'SOL': round(v, 9)}, n, [0]] for (f, t), (v, n) in inflows.items()],
            'exit_rows': sorted([[cat, t, 'SOL', round(v, 9), n, [0], det.get(cat, '')[:90]] for (cat, t), (v, n) in exrows.items() if cat != 'Swaps (churn)'] +
                                [[cat, t, a, round(v, 6), n, [0], det.get(cat, '')[:90]] for (cat, t, a), (v, n) in texr.items()], key=lambda r: -r[3] * pxa(r[2])),
            'by_win_cat': [[0, cat, round(v, 2)] for cat, v in
                           {k: sum(r[0] * px for (c2, _), r in exrows.items() if c2 == k) + sum(r[0] for (c2, _, _), r in texr.items() if c2 == k)
                            for k in {c2 for c2, _ in exrows} | {c2 for c2, _, _ in texr}}.items() if cat != 'Swaps (churn)'],
            'stolen': {'SOL': round(sum(v for k, v in L['sources'].items() if k.startswith('stolen')), 9)}, 'held': {'SOL': [round(L['live_balance'], 9), 0]},
            'returns_usd': {k: round(RET.get(k, 0) * px + RETU.get(k, 0), 2) for k in set(RET) | set(RETU)}})
  lab = {L['root']: 'theft collection wallet', '7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ': 'Relay solver', 'F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe': 'Relay solver (refunds)',
         '6H7GCfCx8JMUACbmSYZjConeJGzViPHhMvvYak5SDDBe': 'Layerswap deposit wallet', 'FoxKvLEytmFo281TqfYjFAaAPGJakmkr9npwTXK3o8qP': 'OKX deposit address',
         'is6MTRHEgyFLNTfYcuV4QBWLjrZBfmhVNYR6ccgr8KV': 'OKX', '5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9': 'Binance hot wallet (victim)'}
  for i, a in enumerate(A):
    w = next((y for y in W if y['id'] == a), None)
    g['wl'].append([i, lab.get(a) or (w['role'] if w else ''), 'operator' if w else 'exit' if a in lab else 'counterparty', '', 0 if w else -1,
                    w['thru'] if w else 0, (w or {}).get('held', {}), ntx[a], 0])
  g['status'] = 'moving'
  return g

# ------------------------------------------------------------------ XRP (tree ledger from xrp_tree.py)
def xrp_tree():
  L = json.load(open(os.path.join(HERE, 'raw', 'xrp_ledger.json')))
  if L.get('kind') != 'tree': return single('xrp', 'XRP Ledger', 'XRP', 'xrp_ledger.json', 'rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx', 'https://xrpscan.com/account/{}', 'https://xrpscan.com/tx/{}')
  g = blank('xrp', 'XRP Ledger', 'XRP', 'https://xrpscan.com/account/{}', 'https://xrpscan.com/tx/{}'); px = PX['XRP']
  g['assets'] = ['XRP']; g['px'] = {'XRP': px}; g['windows'] = [{'run': L['at'], 'from': fmt_t(T0), 'to': L['at'][5:16].replace('T', ' ')}]
  A, ix = [], {}
  def x(a):
    if a not in ix: ix[a] = len(A); A.append(a)
    return ix[a]
  T = set(L['wallets']); links = defaultdict(lambda: [0.0, 0]); parent = {}; thru = defaultdict(float); txs = []
  for h, t, f, to, v in L['edges']:
    if f in T and to in T: links[(f, to)][0] += v; links[(f, to)][1] += 1; parent[to] = f; thru[f] += v
    txs.append([h, t, x(f), x(to), 0, round(v, 6), 0, 0, ''])
  stolen = sum(v for k, v in L['sources'].items() if k.startswith('stolen'))
  W = []
  for a, w in L['wallets'].items():
    fl = w['flows']; x(a)
    win_in = sum(v for k, v in fl.items() if k.startswith('in')); win_out = sum(v for k, v in fl.items() if k.startswith('out'))
    ww = {'id': a, 'role': w['role'], 'created': '', 'first': 0, 'frozen': 0, 'thru': round(thru[a] * px, 2), 'held': {'XRP': round(w['held'], 6)} if w['held'] > 1e-6 else {},
          'win': {0: {'XRP': [round(win_in, 6), round(win_out, 6), round(fl.get('fees', 0), 6), round(w['held'], 6), f"unexplained {w['unexplained']}"]}}, 'tx': []}
    if a in parent: ww['parent'] = parent[a]
    W.append(ww)
  g.update({'wallets': W, 'addr': A, 'cls': ['transfer'], 'txs': txs,
            'links': [[f, t, round(v * px, 2), {'XRP': round(v, 6)}, n, [0]] for (f, t), (v, n) in links.items()],
            'inflows': [['SRC', L['root'], round(stolen * px, 2), {'XRP': stolen}, 1, [0]]],
            'stolen': {'XRP': stolen}, 'held': {'XRP': [round(L['live_balance'], 6), 0]}})
  for i, a in enumerate(A):
    w = next((y for y in W if y['id'] == a), None)
    g['wl'].append([i, w['role'] if w else '', 'operator' if w else 'counterparty', '', 0 if w else -1, w['thru'] if w else 0, (w or {}).get('held', {}), sum(1 for t in txs if A[t[2]] == a or A[t[3]] == a), 0])
  g['status'] = 'moving' if links else 'unmoved'
  return g

# ------------------------------------------------------------------ overview: per-chain totals + cross-chain hops
STOLEN_USD = {'eth': 3792130042.86}          # eth_stolen_frozen_summary.json stolen_usd_fixed (186 assets, theft prices)
FROZEN_USD = {'eth': 2418570845.62 + 8810000, 'avax': 8409928.4, 'polygon': 6185900.1}   # ETH frozen + seized (summary); USDt / USDT0 frozen
RECOVERED = {'arb': 74559805 * PX['ARB'] + 8426 * PX['ETH']}                                # force-moved back by Arbitrum Security Council
STOLEN_FIX = {'avax': {'AVAX': 2258636, 'USDt': 8409928.4}, 'arb': {'ARB': 74559805, 'ETH': 8426}, 'polygon': {'POL': 46626593, 'USDT0': 6185900.1},
              'opt': {'OP': 44231858.7}, 'base': {'VIRTUAL': 4735627}}

def overview(chains):
  ov = {'chains': [], 'hops': []}
  for cid, g in chains.items():
    px = lambda s: g['px'].get(s, PX.get(s, 0))
    stolen = STOLEN_USD.get(cid) or sum(v * PX.get(k, px(k)) for k, v in (STOLEN_FIX.get(cid) or g['stolen']).items())
    H_ = g.get('held_ov', g['held'])                                    # 11-05: EVM HS chains give the own-theft-only holdings
    frozen = FROZEN_USD.get(cid, sum(v[1] * px(k) for k, v in H_.items()))
    held = sum(v[0] * px(k) for k, v in H_.items())
    exited = defaultdict(float)
    for r in g.get('exit_rows_ov', g['exit_rows']):                    # 11-05: EVM HS chains give the side-only list (no double count with Tron/SOL)
      if r[0] in ('Burned / seized', 'Swaps (churn)'): continue          # seized is already in FROZEN_USD; churn is not an exit
      if cid in RECOVERED: continue                                     # Arbitrum: the only 'exit' is the Security Council clawback
      exited[r[0]] += r[3] * px(r[2])
    for cat, v in (g.get('returns_usd') or {}).items():                 # SOL 11-05: withdrawals / refunds back into the tree are not exits
      if cat in exited: exited[cat] = max(0.0, exited[cat] - v)
    held_n = sorted(((k, v[0]) for k, v in H_.items() if v[0] * px(k) >= 1 or not px(k) and v[0]), key=lambda kv: -kv[1] * px(kv[0]))
    ov['chains'].append({'id': cid, 'name': g['name'], 'native': g['native'], 'stolen': round(stolen, 2), 'frozen': round(frozen, 2), 'recovered': round(RECOVERED.get(cid, 0), 2),
                         'held': round(held, 2), 'exited': {k: round(v, 2) for k, v in exited.items()}, 'status': g['status'], 'asof': g['windows'][-1]['to'] if g['windows'] else '',
                         'held_native': {k: round(v, 4) for k, v in held_n}, 'note': g.get('note', '')})
  pay = defaultdict(float)
  for p in chains['tron']['payouts']: pay[(p['chain'], p['asset'])] += p['amt']
  for (ch, asset), v in pay.items():
    ov['hops'].append({'from': 'Tron', 'via': 'THORChain', 'to': {'ETH': 'Ethereum', 'BTC': 'Bitcoin', 'BASE': 'Base', 'ZEC': 'Zcash'}.get(ch, ch), 'asset': asset, 'amount': round(v, 6),
                       'usd': round(v * PX.get(asset, 1.0 if asset.startswith('USD') else 0), 2)})
  CHN = {'ETH': 'Ethereum', 'BTC': 'Bitcoin', 'BASE': 'Base', 'ZEC': 'Zcash'}
  agg = defaultdict(float)                                    # resolved bridge destinations (Relay / Symbiosis / Chainflip / USDT0 / Across)
  for via, ch, to, asset, amt, usd_in, st, *_ in chains['tron'].get('bridge_out') or []:
    if any(w in str(ch).lower() for w in ('refund', 'held', 'fail', 'pending', 'flight', 'transit', 'revert')): continue
    agg[(via, CHN.get(str(ch).split(' ')[0], str(ch).split(' ')[0]), asset)] += amt or 0
  for (via, ch, asset), v in agg.items():
    a2 = {'USDT0': 'USDT', 'USDC (Perp)': 'USDC'}.get(asset, asset)
    ov['hops'].append({'from': 'Tron', 'via': via, 'to': ch, 'asset': asset, 'amount': round(v, 6), 'usd': round(v * PX.get(a2, 1.0 if a2.startswith('USD') else 0), 2)})
  cus = defaultdict(float)
  for r in chains['tron']['exit_rows']:
    if r[0] in ('Bitget Wallet Swap Bridge', 'Bridgers', 'NEAR Intents'): cus[r[0]] += r[3] * chains['tron']['px'].get(r[2], 0)
  for via, usd in cus.items(): ov['hops'].append({'from': 'Tron', 'via': via, 'to': 'unresolved', 'asset': 'USD', 'amount': round(usd, 2), 'usd': round(usd, 2)})
  ov['hops'].append({'from': 'Avalanche', 'via': 'ParaSwap → CCTP v2', 'to': 'Ethereum', 'asset': 'ETH', 'amount': 7242.76, 'usd': round(7242.76 * PX['ETH'], 2)})
  # ETH tree cross-chain exits (xchain_resolve.py): Chainflip / Relay → BTC as received; failed, blocked and unseen ones listed as such
  XR, XC = os.path.join(HERE, 'raw', 'eth_xchain_rows.json'), os.path.join(HERE, 'raw', 'eth_xchain.json')
  if os.path.exists(XR) and os.path.exists(XC) and not chains['eth'].get('hops_out'):   # 11-05: stale file, only if the HS reader gave no hops
    rows, cache = json.load(open(XR)), json.load(open(XC)); got = defaultdict(float); other = defaultdict(float)
    for ent, h, f, v, st, dest in rows:
      r = cache.get(h) or {}
      if ent.startswith('Chainflip') and st == 'COMPLETED': got[('Chainflip', r.get('destChain'), r.get('destAsset'))] += int((r.get('swapEgress') or {}).get('amount') or 0) / 1e8
      elif ent.startswith('Relay') and st.startswith('success'):
        btc = sum(o['value'] for t in ((r.get('requests') or [{}])[0].get('data') or {}).get('outTxs') or [] for o in (t.get('data') or {}).get('vout') or []
                  if (o.get('scriptPubKey') or {}).get('address') == ((r.get('requests') or [{}])[0].get('recipient')))
        if btc: got[('Relay', 'Bitcoin', 'BTC')] += btc / 1e8
      else:
        why = ('blocked by Relay' if 'BLOCKED' in st else 'refunded / failed' if 'FAIL' in st.upper() else
               'not yet seen by Maya' if ent.startswith('Maya Protocol') else 'not resolved yet')
        other[(ent.split(':')[0], why)] += v
    for (via, ch, asset), amt in got.items():
      ov['hops'].append({'from': 'Ethereum', 'via': via, 'to': ch, 'asset': asset, 'amount': round(amt, 8), 'usd': round(amt * PX.get(asset, 0), 2)})
    for (via, why), v in other.items():
      if v >= 0.01: ov['hops'].append({'from': 'Ethereum', 'via': via, 'to': why, 'asset': 'ETH', 'amount': round(v, 6), 'usd': round(v * PX['ETH'], 2)})
  for g in chains.values(): ov['hops'] += g.get('hops_out') or []                # e.g. Solana → Relay (BTC), Solana → Layerswap
  return ov

def all_chains():
  ethpx = {**{c: p for _, c, _, p, *_ in json.load(open(os.path.join(HERE, 'raw', 'eth_stolen_frozen_summary.json')))['stolen']}, 'ETH': PX['ETH'], '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': PX['ETH']}
  chains = {'tron': tron(),
            'eth': evm_hs('eth', 'Ethereum', 'ETH', 'https://etherscan.io/address/{}', 'https://etherscan.io/tx/{}', ethpx),
            'btc': btc(),
            'xrp': xrp_tree(),
            'sol': sol_tree(),
            'avax': evm_hs('avax', 'Avalanche', 'AVAX', 'https://snowtrace.io/address/{}', 'https://snowtrace.io/tx/{}', {},
                           note='AVAX was swapped (ParaSwap) to USDC and bridged by CCTP v2 to Ethereum → 7,242.76 ETH at 0x2948…05a0ed (see All).'),
            'opt': evm_hs('opt', 'Optimism', 'ETH', 'https://optimistic.etherscan.io/address/{}', 'https://optimistic.etherscan.io/tx/{}', {}),
            'polygon': evm_hs('polygon', 'Polygon', 'POL', 'https://polygonscan.com/address/{}', 'https://polygonscan.com/tx/{}', {}),
            'base': evm_hs('base', 'Base', 'ETH', 'https://basescan.org/address/{}', 'https://basescan.org/tx/{}', {}),
            'arb': evm_hs('arb', 'Arbitrum', 'ETH', 'https://arbiscan.io/address/{}', 'https://arbiscan.io/tx/{}', {},
                          note='74.56M ARB + 8,426 ETH were force-moved back by the Arbitrum Security Council (10-30 00:18 UTC).'),
            'bsc': evm_hs('bsc', 'BNB Chain', 'BNB', 'https://bscscan.com/address/{}', 'https://bscscan.com/tx/{}', {}),
            'near': near_tree()}
  # FBI-listed addresses (attrib.db, source fbi:psa:2026-10-31) → flag wallets + label every listed address on every chain
  try:
    AT = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/attrib.db') + '?mode=ro', uri=True)
    FBI = {a.lower() if a.startswith('0x') else a for (a,) in AT.execute("SELECT address FROM attrib_v WHERE source='fbi:psa:2026-10-31'")}
  except Exception: FBI = set()
  key = lambda a: a.lower() if str(a).startswith('0x') else a
  for g in chains.values():
    for w in g['wallets']:
      if key(w['id']) in FBI: w['fbi'] = 1
    for r in g['wl']:
      if key(g['addr'][r[0]]) in FBI: r[1] = (r[1] + ' · ' if r[1] else '') + 'FBI-listed (Binance hacker)'
  return chains

# ---------- 'Where it is now' (all-chains holders network, 11-05) ----------
MIN_USD = 1000
BTC2 = (os.path.join(HERE, 'raw', 'btc2', 'btc2-bridged-cutoff.db'), 'btcb2-20261105T113257')   # bridged BTC (not in Eagle Eye's BTC tab)
GROUP = {'eth': 'Ethereum', 'btc': 'Bitcoin', 'tron': 'Tron', 'xrp': 'XRP Ledger', 'sol': 'Solana', 'near': 'NEAR'}   # rest → 'Other EVM chains'
HOPNAME = {'Ethereum': 'eth', 'Bitcoin': 'btc', 'Tron': 'tron', 'Solana': 'sol', 'Avalanche': 'avax', 'Arbitrum': 'arb', 'Base': 'base', 'BSC': 'bsc'}
PRIV = ('mixer', 'privacy', 'tornado', 'shielded', 'railgun')

def holders(C, ov):
  """'Where it is now' view: wallets holding >= $1k on every chain + cross-chain bridge routes + privacy pools (entered − withdrawn back)."""
  nodes, links, chains = [], [], {}
  hub = lambda cid: 'C:' + cid
  for cid, g in C.items():
    px = lambda s: g['px'].get(s, PX.get(s, 0))
    grp = GROUP.get(cid, 'Other EVM chains'); n = usd = 0
    for w in g['wallets']:
      held = {k: v for k, v in (w.get('held') or {}).items() if v > 0}
      u = sum(v * px(k) for k, v in held.items())
      if u < MIN_USD: continue
      n += 1; usd += u
      nodes.append({'id': f'{cid}:{w["id"]}', 'k': 'w', 'cat': grp, 'chain': g['name'], 'addr': w['id'], 'url': g['addr_url'].format(w['id']),
                    'role': w.get('role', ''), 'frozen': w.get('frozen', 0), 'fbi': w.get('fbi', 0), 'usd': round(u, 2), 'held': {k: round(v, 6) for k, v in held.items()}})
      links.append({'s': f'{cid}:{w["id"]}', 't': hub(cid), 'k': 'm'})
    chains[cid] = [g['name'], grp, n, usd]
  # bridged BTC: payouts the attacker received on Bitcoin, still unspent at the cutoff
  db, run = BTC2; seen = {x['addr'] for x in nodes if x['id'].startswith('btc:')}
  for a, s in sqlite3.connect(f'file:{db}?mode=ro', uri=True).execute(
      "SELECT address, sum(sats) FROM utxo WHERE run_id=? AND owner='attacker' AND status LIKE 'unspent%' GROUP BY 1", (run,)):
    b = s / 1e8; u = b * PX['BTC']
    if u < MIN_USD or a in seen: continue
    nodes.append({'id': 'btc:' + a, 'k': 'w', 'cat': 'Bitcoin', 'chain': 'Bitcoin', 'addr': a, 'url': C['btc']['addr_url'].format(a),
                  'role': 'received from a bridge', 'frozen': 0, 'fbi': 0, 'usd': round(u, 2), 'held': {'BTC': round(b, 8)}})
    links.append({'s': 'btc:' + a, 't': hub('btc'), 'k': 'm'}); chains['btc'][2] += 1; chains['btc'][3] += u
  for cid, (name, grp, n, usd) in chains.items():
    nodes.append({'id': hub(cid), 'k': 'c', 'cat': grp, 'name': name, 'n': n, 'usd': round(usd, 2)})
  # bridges: from-chain → service → to-chain (same-chain legs are swaps, not moves)
  E = defaultdict(lambda: {'usd': 0.0, 'am': defaultdict(float)}); svc = defaultdict(lambda: {'usd': 0.0, 'routes': []}); ext = {}
  for h in ov['hops']:
    f, t = HOPNAME.get(h['from']), HOPNAME.get(h['to'])
    if not f or h['from'] == h['to']: continue
    if not t:
      t = 'X:unresolved' if h['to'] == 'unresolved' else 'X:' + h['to']
      ext[t] = 'destination not resolved yet' if h['to'] == 'unresolved' else h['to']
    tid = t if t.startswith('X:') else hub(t); s_ = 'B:' + h['via']
    for k in ((hub(f), s_), (s_, tid)):
      E[k]['usd'] += h['usd']; E[k]['am'][h['asset']] += h['amount']
    svc[h['via']]['usd'] += h['usd']; svc[h['via']]['routes'].append([h['from'], ext.get(t, h['to']), h['asset'], round(h['amount'], 6), round(h['usd'], 2)])
  for v, x in svc.items(): nodes.append({'id': 'B:' + v, 'k': 'b', 'cat': 'Bridge / swap service', 'name': v, 'usd': round(x['usd'], 2), 'routes': x['routes']})
  for t, name in ext.items(): nodes.append({'id': t, 'k': 'x', 'cat': 'Outside these ledgers', 'name': name})
  for (s_, t), e in E.items(): links.append({'s': s_, 't': t, 'k': 'h', 'usd': round(e['usd'], 2), 'am': {k: round(v, 6) for k, v in e['am'].items()}})
  # privacy pools: entered minus what came back out to the tree = can't be followed now
  pools = []
  for cid, g in C.items():
    px = lambda s: g['px'].get(s, PX.get(s, 0)); P = defaultdict(lambda: defaultdict(float))
    for cat, _, s, amt, *_ in g['exit_rows']:
      if any(k in cat.lower() for k in PRIV): P[cat][s] += amt
    for cat, am in P.items():
      back = (g.get('returns_usd') or {}).get(cat, 0)
      if back:                                                             # returns are USD; net them off the native amount
        s0 = max(am, key=lambda s: am[s] * px(s)); am[s0] = max(0.0, am[s0] - back / px(s0)) if px(s0) else am[s0]
      u = sum(v * px(s) for s, v in am.items()); nm = cat.replace(' (mixer)', '').replace(' (unconfirmed)', ' (unconfirmed)')
      pid = f'P:{cid}:{cat}'
      nodes.append({'id': pid, 'k': 'p', 'cat': 'Privacy pool (untraceable)', 'name': nm, 'chain': g['name'], 'usd': round(u, 2), 'am': {k: round(v, 4) for k, v in am.items()}})
      links.append({'s': hub(cid), 't': pid, 'k': 'p', 'usd': round(u, 2), 'am': {k: round(v, 4) for k, v in am.items()}})
      pools.append([g['name'], nm, {k: round(v, 4) for k, v in am.items()}, round(u, 2)])
  W = [x for x in nodes if x['k'] == 'w']
  return {'asof': '11-05 02:02 UTC', 'min': MIN_USD, 'n': len(W), 'usd': round(sum(x['usd'] for x in W), 2), 'nodes': nodes, 'links': links,
          'chains': [[v[0], v[1], v[2], round(v[3], 2)] for v in sorted(chains.values(), key=lambda v: -v[3])], 'pools': pools}

def build():
  chains = all_chains(); ov = overview(chains)
  data = {'built': time.strftime('%F %T UTC', time.gmtime()), 'px': PX, 'order': list(chains), 'chains': chains, 'overview': ov, 'holders': holders(chains, ov)}
  os.makedirs(os.path.dirname(OUT), exist_ok=True)
  html = open(os.path.join(HERE, 'incident_template.html')).read().replace('/*__ECHARTS__*/', open(ECH).read())
  uri = 'data:image/jpeg;base64,' + base64.b64encode(open(AVATAR, 'rb').read()).decode() if os.path.exists(AVATAR) else ''
  CREDIT = ('<a class="credit" href="https://x.com/SomaXBT" target="_blank" rel="noopener"><img class="av" src="' + uri + '" alt="SomaXBT"><span class="h">'
            '<svg class="xl" viewBox="0 0 24 24" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>SomaXBT</span></a>')
  html = html.replace('/*CREDIT*/', CREDIT).replace('/*__DATA__*/null', TGR.public(json.dumps(TGR.safe(data), separators=(',', ':'))))
  open(OUT, 'w').write(html)
  return OUT, {k: len(v['wallets']) for k, v in chains.items()}

if __name__ == '__main__':
  print('wrote %s | wallets per chain %s' % build())
