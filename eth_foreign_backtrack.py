"""ETH twin of foreign_backtrack.py, HOP-SYNCHRONOUS: backtrack every 'in:outside' sender of the CURRENT ETH snapshot along its LARGEST
inflow (ETH incl. internal / WETH / USDC / USDT / DAI; stables at a fixed 2,300 USD/ETH only to RANK inflows), <= 8 hops, before the
block it paid onward, until: a tree wallet (own money returning) · FBI-listed · a NAMED attrib.db entity · a contract · a hub (>2,000
tx sent) · an aged wallet (sent txs before the hack = someone else's money) · no inflow. Per hop ONE bulk step for all walks:
eth_hs.screen() (code + nonce now + nonce at hack, Alchemy + QuickNode lanes in parallel) then ONE HyperSync inflow query (traces +
Transfer logs) for every frontier wallet. Heuristic per hop (largest inflow), like the SOL version. v1 (1 Alchemy call/addr, ~40 min)
→ raw/eth_foreign_backtrack_v1_alchemy.py.bak.   python3 eth_foreign_backtrack.py [MIN_ETH_EQ=0.1]  → raw/eth_foreign_backtrack.json"""
import json, os, sys, time, sqlite3, collections
from concurrent.futures import ThreadPoolExecutor
os.chdir(os.path.dirname(os.path.abspath(__file__))); _argv = sys.argv; sys.argv = ['eth_hs']; import eth_hs as H; sys.argv = _argv
MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1
TOK = {H.WETH: (18, 1.0), H.USDC: (6, 1 / 2300), '0xdac17f958d2ee523a2206206994597c13d831ec7': (6, 1 / 2300), '0x6b175474e89094c44da98b954eedeac495271d0f': (18, 1 / 2300)}
B = H.C; R = B.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%' ORDER BY run_id DESC LIMIT 1").fetchone()[0]
TREE = {a for (a,) in B.execute("SELECT address FROM wallet WHERE run_id=? AND status='tree'", (R,))}
FBI = {a.lower() for a in open('raw/fbi/fbi_eth.txt').read().split()}
A = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db'))
def labels(addrs):
    out = {}
    for i in range(0, len(addrs), 500):
        p = addrs[i:i + 500]
        for a, e, c in A.execute(f"SELECT address, entity, category FROM attrib_v WHERE chain='eth' AND address IN ({','.join('?' * len(p))})", p):
            if a not in out or c != 'hack': out[a] = f'{e} ({c})'
    return out
def inflows(addrs, a, b):
    """{addr: [(from, eth_eq, hash, block)]} over [a, b) — HyperSync traces (ETH, top-level + internal) + Transfer logs of TOK"""
    out = collections.defaultdict(list)
    for i in range(0, len(addrs), H.CHUNK):
        part = addrs[i:i + H.CHUNK]; pads = [H.pad(x) for x in part]
        def q_tr(): return H.hs(H.HST, {'traces': [{'to': part}], 'field_selection': {'trace': ['transaction_hash', 'block_number', 'from', 'to', 'value', 'call_type', 'error']}}, a, b)['traces']
        def q_lg(): return H.hs(H.HS, {'logs': [{'address': list(TOK), 'topics': [[H.TR], [], pads]}], 'field_selection': {'log': ['transaction_hash', 'block_number', 'address', 'topic1', 'topic2', 'data']}}, a, b)['logs']
        with ThreadPoolExecutor(2) as ex: f1, f2 = ex.submit(q_tr), ex.submit(q_lg)
        for t in f1.result():
            v = H.num(t.get('value'))
            if v and not t.get('error') and t.get('call_type') in ('call', None):
                out[(t.get('to') or '').lower()].append(((t.get('from') or '').lower(), v / 1e18, t['transaction_hash'], H.num(t['block_number'])))
        for l in f2.result():
            d, k = TOK[l['address'].lower()]; v = H.num(l.get('data') or '0x0') / 10 ** d * k
            if v: out['0x' + l['topic2'][-40:].lower()].append(('0x' + l['topic1'][-40:].lower(), v, l['transaction_hash'], H.num(l['block_number'])))
    return out

q = B.execute("""SELECT frm, SUM(CASE asset WHEN 'ETH' THEN amount WHEN ? THEN amount WHEN ? THEN amount/2300 WHEN '0xdac17f958d2ee523a2206206994597c13d831ec7' THEN amount/2300
                 WHEN '0x6b175474e89094c44da98b954eedeac495271d0f' THEN amount/2300 ELSE 0 END), MAX(block) FROM edge WHERE run_id=? AND cls='in:outside' GROUP BY frm""", (H.WETH, H.USDC, R)).fetchall()
W = [{'sender': s, 'eth_eq': round(v, 6), 'cur': s, 'b': blk, 'chain': [], 'seen': set()} for s, v, blk in sorted(q, key=lambda z: -z[1]) if v >= MIN]
print(f'{R}: {len(q)} foreign senders, {len(W)} >= {MIN} ETH-eq ({sum(w["eth_eq"] for w in W):,.1f} of {sum(v for _, v, _ in q):,.1f}) · state lanes {len(H.LANES)} · HyperSync', flush=True)
t0 = time.time(); SC, LB = {}, {}
def end(w, why): w['end'] = why; w['at'] = w['cur']
active = W
for hop in range(9):
    new = sorted({w['cur'] for w in active} - set(SC)); LB.update(labels(new))
    need = [x for x in new if not (x in TREE or x in FBI or x in LB)]
    if need: SC.update(H.screen(need))
    nxt = []
    for w in active:
        x = w['cur']
        if x in w['seen']: end(w, 'loop'); continue
        w['seen'].add(x)
        if hop and x in TREE: end(w, 'tree (own money returning)')
        elif x in FBI: end(w, 'FBI-listed')
        elif hop and x in LB: end(w, LB[x])
        elif x in SC and SC[x][0] != 'fresh': end(w, {'contract': 'contract', 'hub': 'hub (>2,000 tx sent)', 'aged': 'aged wallet (active before the hack)'}[SC[x][0]] + (f' · {LB[x]}' if x in LB else ''))
        elif hop == 8: end(w, 'max hops (8)')
        else: nxt.append(w)
    print(f'  hop {hop}: {len(active)} walks, {len(active) - len(nxt)} ended, {len(need)} screened · {time.time() - t0:.0f}s', flush=True)
    if not nxt: break
    IN = inflows(sorted({w['cur'] for w in nxt}), H.HACK_BLOCK, max(w['b'] for w in nxt) + 1)
    for w in nxt:
        src = collections.defaultdict(lambda: [0.0, None, 0])
        for f, v, h, bn in IN.get(w['cur'], []):
            if bn <= w['b'] and v >= 0.01: s = src[f]; s[0] += v; s[1] = s[1] or h; s[2] = max(s[2], bn)
        if not src: end(w, 'no inflow since the hack (dead end)'); continue
        f, (v, h, bn) = max(src.items(), key=lambda z: z[1][0])
        w['chain'].append({'from': f, 'to': w['cur'], 'eth_eq': round(v, 4), 'hash': h, 'block': bn}); w['cur'], w['b'] = f, bn
    active = [w for w in nxt if 'end' not in w]
summ = collections.defaultdict(lambda: [0, 0.0])
for w in W: w.pop('seen'); w.pop('cur'); w.pop('b'); summ[w['end']][0] += 1; summ[w['end']][1] += w['eth_eq']
json.dump({'run': R, 'min_eth_eq': MIN, 'summary': {k: [n, round(v, 4)] for k, (n, v) in summ.items()}, 'walks': W}, open('raw/eth_foreign_backtrack.json', 'w'), indent=1)
print(f'\nENDPOINTS of {len(W)} foreign senders ({time.time() - t0:.0f}s):')
for k, (n, v) in sorted(summ.items(), key=lambda z: -z[1][1]): print(f'  {v:>10,.2f} ETH-eq  {n:>4}  {k}')
