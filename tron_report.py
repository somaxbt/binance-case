"""Binance case — TRON ledger report on top of a tron_ledger2 run (reads the DB only; THORNode for unresolved deposits).
  python3 tron_report.py [run_id]
Adds what the ledger run itself doesn't:
  1. LOOPS: wallets that send value back to each other (strongly connected groups), refills, re-entries, turnover.
  2. EXIT LABELS: exchange / service labels (local stores), USDT0-LayerZero and other bridge contracts.
  3. MIXING: inflows from swaps/bridges/THORChain vaults are the attacker's own value coming back; only true outside value is MIXED.
  4. THORCHAIN: every deposit resolved to its actual payout (THORNode tx/status); refunds return to Tron; RUNE = fees;
     everything else becomes a CARRY-OVER line (chain, address, asset, exact amount) for the next chain's ledger.
Stolen value is never inflated: internal attacker->attacker flows net to zero; only boundary crossings count."""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
from collections import defaultdict
from tron_ledger import ENDPOINT, VAULTS, DB

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGES = {'TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt': 'bridge:usdt0-layerzero', 'TPuaJ6gnYfE9gLUDFrbWbPx3tMnjG8max1': 'bridge:symbiosis',
           'TZ9grqg3LwBKiddGra3WGHPdddJz3tow8N': 'bridge?:CrossProxy (unidentified)'}
OWN_BACK = set(ENDPOINT) | set(BRIDGES) | {'TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx', 'TVjuTE3V5bMVdpfNhid8kD2v35T2k1u1Br', 'TQqgNg13s2DjvXhW1ky4v6TsR8wZGvb7Y4'}
TL = json.load(open(os.path.expanduser('~/traversal-engine/tron/data/tron-labels.json')))
POR = sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
def tron_label(a):
  p = POR.execute('SELECT exchange, wallet_type FROM por_wallets WHERE address=?', (a,)).fetchone()
  if p: return f'cex:{p[0]}/{p[1]}'
  v = TL.get(a) if isinstance(TL, dict) else None
  return f'label:{str(v)[:50]}' if v else ''

CACHE = os.path.join(HERE, 'raw/tron/thornode_cache.json')
def thornode(h, cache):
  if h in cache: return cache[h]
  for i in range(5):
    try:
      r = urllib.request.Request(f'https://gateway.liquify.com/chain/thorchain_api/thorchain/tx/status/{h.upper()}', headers={'User-Agent': 'Mozilla/5.0', 'x-client-id': 'binance-trace'})
      d = json.load(urllib.request.urlopen(r, timeout=40)); time.sleep(1.0)
      cache[h] = {'outs': [{'chain': o.get('chain'), 'to': o.get('to_address'), 'coins': o.get('coins'), 'id': o.get('id')} for o in (d.get('out_txs') or [])],
                  'done': ((d.get('stages') or {}).get('outbound_signed') or {}).get('completed')}
      return cache[h]
    except urllib.error.HTTPError as e:
      if e.code in (429, 502, 503): time.sleep(5 * (i + 1)); continue
      return {'outs': [], 'err': e.code}
    except Exception: time.sleep(3)
  return {'outs': [], 'err': 'fail'}

def scc(nodes, adj):
  """iterative Tarjan: strongly connected components"""
  idx, low, on, st, out, i = {}, {}, set(), [], [], 0
  for s in nodes:
    if s in idx: continue
    work = [(s, iter(adj[s]))]; idx[s] = low[s] = i; i += 1; st.append(s); on.add(s)
    while work:
      v, it = work[-1]; nxt = next(it, None)
      if nxt is not None:
        if nxt not in idx: idx[nxt] = low[nxt] = i; i += 1; st.append(nxt); on.add(nxt); work.append((nxt, iter(adj[nxt])))
        elif nxt in on: low[v] = min(low[v], idx[nxt])
      else:
        work.pop()
        if work: low[work[-1][0]] = min(low[work[-1][0]], low[v])
        if low[v] == idx[v]:
          comp = []
          while True:
            w = st.pop(); on.discard(w); comp.append(w)
            if w == v: break
          out.append(comp)
  return out

def main(run_id=None):
  c = sqlite3.connect(DB, timeout=600)
  run_id = run_id or c.execute("SELECT run_id FROM ledger_run WHERE leg='tron2' ORDER BY started DESC LIMIT 1").fetchone()[0]
  fin, params = c.execute('SELECT finished, params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()
  cut = json.loads(params)['cutoff']
  nodes = {r[0] for r in c.execute('SELECT DISTINCT address FROM ledger_node WHERE run_id=?', (run_id,))}
  E = c.execute('SELECT hash, ts, frm, too, asset, amount, cls, detail FROM ledger_edge WHERE run_id=?', (run_id,)).fetchall()
  print(f'=== {run_id} | cutoff {time.strftime("%F %T UTC", time.gmtime(cut/1000))} | wallets {len(nodes)} | {"FINISHED" if fin else "STILL RUNNING (partial)"} ===')

  # ---------- 1. LOOPS ----------
  adj, vol = defaultdict(set), defaultdict(float)
  internal = [(h, ts, f, t, a, v) for h, ts, f, t, a, v, cls, d in E if cls == 'out:attacker' and f in nodes and t in nodes]
  for h, ts, f, t, a, v in internal: adj[f].add(t); vol[a] += v
  comps = [k for k in scc(sorted(nodes), adj) if len(k) > 1]
  stolen_in = {a: sum(v for h, ts, f, t, aa, v, cls, d in E if aa == a and cls == 'in:root') for a in ('TRX', 'USDT')}
  print('\n1) LOOPS / CIRCULATION')
  for a in ('TRX', 'USDT'):
    if stolen_in[a]: print(f'   {a}: internal attacker->attacker volume {vol[a]:,.0f} vs stolen in {stolen_in[a]:,.0f}  => turnover x{vol[a]/stolen_in[a]:.2f}')
  print(f'   loop groups (wallets that send value back to each other): {len(comps)}')
  for k in sorted(comps, key=len, reverse=True)[:8]:
    kv = sum(v for h, ts, f, t, a, v in internal if f in k and t in k and a == 'TRX')
    print(f'     size {len(k)}: TRX circulated inside {kv:,.0f} | e.g. {", ".join(sorted(k)[:4])}{" …" if len(k) > 4 else ""}')
  pairs = {(f, t) for h, ts, f, t, a, v in internal}
  back = sorted({tuple(sorted(p)) for p in pairs if (p[1], p[0]) in pairs})
  print(f'   two-way pairs (A->B and B->A): {len(back)}' + (f'  e.g. {back[:3]}' if back else ''))
  refills = defaultdict(int)
  for h, ts, f, t, a, v in internal: refills[t] += 1
  top = sorted(refills.items(), key=lambda x: -x[1])[:5]
  print(f'   most-refilled wallets: {top}')

  # ---------- 2+4. EXITS (labelled, THORChain resolved) ----------
  cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
  old = os.path.join(HERE, 'raw/tron/wave1_thorchain_resolved.json')
  if os.path.exists(old):
    for x in json.load(open(old)): cache.setdefault(x['in_hash'], {'outs': x['outs'], 'done': x.get('done')})
  exits, carry, refunds, fees = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
  for h, ts, f, t, a, v, cls, d in E:
    if not cls.startswith('out:') or t in nodes: continue
    kind = cls[4:]
    if t in BRIDGES: kind = BRIDGES[t]
    elif kind in ('external', 'unknown_contract'):
      lb = tron_label(t); kind = lb if lb else (f'{kind}:{t}')
    if cls == 'out:thorchain':
      s = thornode(h, cache)
      if not s['outs']: exits[('thorchain:UNRESOLVED', a)] += v; continue
      exits[('thorchain', a)] += v
      for o in s['outs']:
        for cn in (o['coins'] or []):
          amt = int(cn['amount']) / 1e8
          if cn['asset'].startswith('THOR.RUNE'): fees[('thorchain fee (RUNE)', cn['asset'])] += amt
          elif o['chain'] == 'TRON' and o['to'] in nodes: refunds[(o['to'], cn['asset'])] += amt
          else: carry[(o['chain'], o['to'], cn['asset'])] += amt
      continue
    exits[(kind, a)] += v
  json.dump(cache, open(CACHE, 'w'))
  print('\n2) EXITS from the Tron tree (stolen value leaving; internal flows netted)')
  for (k, a), v in sorted(exits.items(), key=lambda x: -x[1]): print(f'   {k:58} {a:5} {v:>18,.4f}')
  print('\n4) THORCHAIN resolved:')
  print('   refunds back into the Tron tree (own value, re-enters):'); [print(f'     {k[0]} {k[1]:40} {v:,.4f}') for k, v in refunds.items()]
  print('   THORChain fees:'); [print(f'     {k[0]} {v:,.4f}') for k, v in fees.items()]
  print('   CARRY-OVER to other chains (exact payouts = seeds for the next ledger):')
  for (ch, to, asset), v in sorted(carry.items(), key=lambda x: (x[0][0], -x[1])): print(f'     {ch:5} {to:44} {asset[:24]:24} {v:,.6f}')
  json.dump([[ch, to, asset, v] for (ch, to, asset), v in carry.items()], open(os.path.join(HERE, f'raw/tron/carryover_{run_id}.json'), 'w'))

  # ---------- 3. MIXING ----------
  print('\n3) MIXING (value entering attacker wallets from outside the tree)')
  # own value coming back, by evidence rather than by address list:
  #   (a) THORChain refunds: THORNode says this wallet was refunded this amount (vaults rotate, so match on wallet+amount)
  #   (b) swap counter-legs: the inflow is in the SAME tx as this wallet's own swap / bridge / THORChain deposit (RFQ makers pay from EOAs)
  refund_amts = defaultdict(list)
  for (w, asset), _ in refunds.items(): pass
  for h0, s in cache.items():
    for o in s.get('outs', []):
      for cn in (o.get('coins') or []):
        if o.get('chain') == 'TRON': refund_amts[o['to']].append(int(cn['amount']) / 1e8)
  own_tx = defaultdict(set)
  for h, ts, f, t, a, v, cls, d in E:
    if cls.startswith('out:') and cls not in ('out:attacker', 'out:external'): own_tx[f].add(h)
  mix = defaultdict(lambda: [0.0, 0, set()])
  for h, ts, f, t, a, v, cls, d in E:
    if cls in ('in:foreign', 'in:internal') and t in nodes and f not in nodes and v >= 1:
      if f in OWN_BACK or f in VAULTS: tag = 'own value back (swap/bridge/THORChain)'
      elif any(abs(v - x) <= max(0.01, x * 1e-6) for x in refund_amts.get(t, [])): tag = 'own value back (THORChain refund, rotated vault)'
      elif h in own_tx[t]: tag = 'own value back (swap counter-leg, same tx)'
      else: tag = 'MIXED: outside money'
      m = mix[(t, a, tag)]; m[0] += v; m[1] += 1; m[2].add(f)
  for (t, a, tag), (v, n, s) in sorted(mix.items(), key=lambda x: (x[0][2], -x[1][0])):
    sin = sum(vv for h, ts, f, tt, aa, vv, cls, d in E if tt == t and aa == a and cls in ('in:root', 'in:attacker', 'in:swap_proceeds'))
    print(f'   {tag:48} {t} {a}: {v:,.4f} in {n} txs (stolen-in here {sin:,.4f}) from {", ".join(sorted(s)[:3])}')

if __name__ == '__main__':
  main(sys.argv[1] if len(sys.argv) > 1 else None)
  try:                                   # THORChain payouts feed the graph: rebuild it
    import tron_graph; tron_graph.build()
    import incident_graph; incident_graph.build()
  except Exception as e: print(f'graph: FAILED {e}')
