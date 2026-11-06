"""Binance SOL glue for the shared bridge resolver ~/cases/_bridges/bridges.py (11-04): which SOL ledger edges are bridge deposits.
Relay / Layerswap: the exit tx itself. Chainflip: the tree->channel tx (the channel is the sender of the sweep into the vault).
  drain backlog:  SOL_LEDGER=raw/sol_ledger_next.json python3 sol_bridge_resolve.py   -> raw/sol/bridge_dest.json + summary
  from sol_ledger.py: enqueue_from_edges(EDGES) then BR.wait(secs)  (background; the ledger never waits longer than secs)"""
import json, os, sys, time, collections
sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
os.chdir(os.path.dirname(os.path.abspath(__file__)))
VAULT = {'relay': 'exit: Relay (solver)', 'layerswap': 'exit: Layerswap', 'chainflip': 'exit: Chainflip (vault)'}

def deposits(edges):
    into = collections.defaultdict(list)
    for e in edges: into[e[3]].append(e)
    out = []
    for kind, cls in VAULT.items():
        if kind != 'chainflip': out += [(kind, e[0], e[4], e[2], None) for e in edges if e[5] == cls]
        else: out += [(kind, x[0], x[4], x[2], e[2]) for e in edges if e[5] == cls for x in into.get(e[2], [])]   # (.., tree payer, channel)
    return out

def enqueue_from_edges(edges): return collections.Counter(k for k, s, *_ in deposits(edges) if BR.enqueue(k, s))

def destinations(edges):
    C = {k: BR.load(k) for k in VAULT}
    return [{'kind': k, 'sig': s, 'from': f, **({'channel': ch} if ch else {}), 'sol': v, **(BR.row(k, s, C[k]) or {'status': 'unresolved'})} for k, s, v, f, ch in deposits(edges)]

if __name__ == '__main__':
    L = json.load(open(os.environ.get('SOL_LEDGER', 'raw/sol_ledger_next.json')))
    n = enqueue_from_edges(L['edges']); print('to resolve:', dict(n), '| Relay key:', 'yes (v3)' if BR.RK else 'no (public v2, slow)', flush=True)
    t0 = time.time()
    while any(BR.pending().values()):
        time.sleep(60); print(f'  {int(time.time() - t0) // 60} min: done {dict(BR.DONE)} left {BR.pending()} not resolved {dict(BR.MISS)}', flush=True)
    BR.wait()
    rows = destinations(L['edges']); json.dump(rows, open('raw/sol/bridge_dest.json', 'w'), indent=1)
    agg = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows: k = (r['kind'], r['status'], r.get('chain'), r.get('asset')); agg[k][0] += 1; agg[k][1] += r['sol']; agg[k][2] += float(r.get('amount') or 0)
    print('\nDESTINATIONS (bridge, status, chain, asset): deposits | SOL in | amount out')
    for k, v in sorted(agg.items(), key=lambda x: -x[1][1]): print(f'  {str(k):70} {v[0]:>4} | {v[1]:>11,.2f} SOL | {v[2]:,.6f}')
