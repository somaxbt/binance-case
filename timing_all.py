"""Automation from TIMING, all chains, same metrics, local data only (no API): Tron ledger (valid run chain), ETH bridged tree (CURRENT run),
SOL tree ledger (pinned 05:29 copy), BTC bridged ledger. Dust and fee-only edges excluded (reporting only; ledgers untouched).
Per chain: receive->first-send delay, same-block parallel sends by different wallets, hour-of-day profile + longest quiet gap,
per-wallet cadence (gap regularity), wallet lifetime.   python3 timing_all.py -> raw/timing_all_<ts>.json"""
import json, sqlite3, statistics as st, collections, time, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ro = lambda f: sqlite3.connect(f'file:{f}?mode=ro', uri=True)
med = lambda xs: round(st.median(xs), 1) if xs else None

def metrics(sends, recvs, blk):
    """sends/recvs: [(t_sec, wallet)] ; blk: {tx-time-key -> block id} via the send tuples' 3rd field"""
    S = sorted(sends); out = {'sends': len(S), 'wallets': len({w for _, w, _ in S})}
    if not S: return out
    first_in = {}
    for t, w in sorted(recvs): first_in.setdefault(w, t)
    first_out = {}
    for t, w, _ in S:
        if w in first_in and t >= first_in[w]: first_out.setdefault(w, t)
    d = [first_out[w] - first_in[w] for w in first_out]
    out['recv_to_send_s'] = {'median': med(d), 'le_60s': round(sum(x <= 60 for x in d) / len(d), 3) if d else None,
                             'le_10min': round(sum(x <= 600 for x in d) / len(d), 3) if d else None, 'n': len(d)}
    by_blk = collections.defaultdict(set)
    for t, w, b in S: by_blk[b].add(w)
    out['parallel_share'] = round(sum(1 for t, w, b in S if len(by_blk[b]) > 1) / len(S), 3)
    out['max_wallets_one_block'] = max(len(v) for v in by_blk.values())
    hrs = collections.Counter(time.gmtime(t).tm_hour for t, _, _ in S); out['hour_utc'] = [hrs.get(h, 0) for h in range(24)]
    ts = [t for t, _, _ in S]; gaps = sorted((b - a for a, b in zip(ts, ts[1:])), reverse=True)
    out['span_h'] = round((ts[-1] - ts[0]) / 3600, 1); out['longest_quiet_h'] = round(gaps[0] / 3600, 2) if gaps else 0
    per = collections.defaultdict(list)
    for t, w, _ in S: per[w].append(t)
    cad = []
    for w, x in per.items():
        if len(x) >= 5:
            g = [b - a for a, b in zip(x, x[1:])]; m = st.mean(g)
            cad.append((st.median(g), (st.pstdev(g) / m) if m else 0))
    out['cadence'] = {'wallets_5plus_sends': len(cad), 'median_gap_s': med([c[0] for c in cad]),
                      'steady_fast_share': round(sum(1 for g, cv in cad if g <= 60 and cv < 0.5) / len(cad), 3) if cad else None}
    life = [per[w][-1] - first_in.get(w, per[w][0]) for w in per]
    out['wallet_life_s'] = {'median': med(life), 'le_1h_share': round(sum(x <= 3600 for x in life) / len(life), 3)}
    return out

R = {}
# ---- TRON (valid run chain; ts in ms; block id = timestamp, 3 s blocks)
import tron_graph as g
C = ro(g.DB); chain = [r for r, _ in g.run_chain(C)]; q = ','.join('?' * len(chain))
TW = {a for (a,) in C.execute(f'SELECT DISTINCT address FROM ledger_node WHERE run_id IN ({q})', chain)}
s, r = [], []
for h, ts, f, t, cls, v in C.execute(f"SELECT hash, ts, frm, too, cls, amount FROM ledger_edge WHERE run_id IN ({q}) AND cls NOT IN ('fee','in:dust') AND amount > 0", chain):
    if cls.startswith('out:') and f in TW: s.append((h, (ts // 1000, f, ts)))
    elif cls.startswith('in:') and t in TW: r.append((ts // 1000, t))
R['tron'] = metrics(list({(h, x[1]): x for h, x in s}.values()), r, None)          # one send per (tx, wallet)
# ---- ETH bridged tree (block -> time: 12 s slots from a reference block; same-block = exact)
B = ro('binance-bridged.db'); ER = B.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%' ORDER BY run_id DESC LIMIT 1").fetchone()[0]
EW = {a for (a,) in B.execute("SELECT address FROM wallet WHERE run_id=? AND status='tree'", (ER,))}
BREF, TREF = 26331481, 1793682480                        # move_check 11-03: block 26331481 = 03:08 UTC
bt = lambda b: TREF + (b - BREF) * 12
s, r = [], []
for h, b, f, t, cls, v in B.execute("SELECT hash, block, frm, too, cls, amount FROM edge WHERE run_id=? AND amount > 0", (ER,)):
    if f in EW and (cls.startswith('out:') or cls == 'tree'): s.append((h, (bt(b), f, b)))
    if t in EW and (cls.startswith('in:') or cls == 'tree') and not (cls not in ('tree', 'in:seed/bridge') and v < 0.001)   # 11-04: in:outside is split into named classes (eth_hs.reclass) — same dust rule for all of them: r.append((bt(b), t))
R['eth_tree'] = metrics(list({(h, x[1]): x for h, x in s}.values()), r, None)
# ---- SOL tree ledger (pinned 05:29; t = blockTime s; block id = second)
L = json.load(open('raw/sol_ledger_eagle_0529.json')); SW = set(L['wallets'])
s, r = [], []
for sig, t, f, to, v, cls in L['edges']:
    if f in SW and v >= 0.01: s.append((sig, (t, f, t)))
    if to in SW and v >= 0.01: r.append((t, to))
for sig, t, f, to, v, a, cls in L['edges_tok']:
    if v < 1 or cls.startswith('swap output'): continue
    if f in SW and not cls.startswith('in'): s.append((sig, (t, f, t)))
    if to in SW and cls.startswith('in') and cls != 'in: foreign': r.append((t, to))
R['sol'] = metrics(list({(h, x[1]): x for h, x in s}.values()), r, None)
# ---- BTC bridged ledger (tx ts; block id = height)
Q = ro('binance-btc-bridged-ledger.db'); BR = Q.execute('SELECT run_id FROM ledger_run WHERE finished IS NOT NULL ORDER BY started DESC LIMIT 1').fetchone()[0]
TX = {t: (h, ts) for t, h, ts in Q.execute('SELECT txid, height, ts FROM btx')}
s, r = [], []
for txid, a, sb, own in Q.execute("SELECT txid, address, spent_by, owner FROM utxo WHERE run_id=? AND owner='attacker'", (BR,)):
    if txid in TX: r.append((TX[txid][1], a))
    if sb and sb in TX: s.append((TX[sb][1], a, TX[sb][0]))
R['btc_bridged'] = metrics(list(set(s)), r, None)

ts = time.strftime('%Y%m%dT%H%M%S'); json.dump(R, open(f'raw/timing_all_{ts}.json', 'w'), indent=1)
print(f"{'chain':12} {'sends':>7} {'wallets':>7} {'recv→send med':>13} {'≤60s':>6} {'≤10m':>6} {'parallel':>8} {'max/blk':>7} {'quiet h':>7} {'steady-fast':>11} {'life med':>9} {'life≤1h':>7}")
for c, m in R.items():
    if not m.get('sends'): print(f'{c:12} no sends'); continue
    rs, cd, lf = m['recv_to_send_s'], m['cadence'], m['wallet_life_s']
    print(f"{c:12} {m['sends']:>7,} {m['wallets']:>7,} {str(rs['median'])+'s':>13} {rs['le_60s']:>6} {rs['le_10min']:>6} {m['parallel_share']:>8} {m['max_wallets_one_block']:>7} {m['longest_quiet_h']:>7} {str(cd['steady_fast_share']):>11} {str(lf['median'])+'s':>9} {lf['le_1h_share']:>7}")
print('\nhour-of-day (UTC) sends:')
for c, m in R.items():
    if m.get('hour_utc'): mx = max(m['hour_utc']) or 1; print(f"  {c:12} " + ''.join(' ▁▂▃▄▅▆▇█'[min(8, round(8 * x / mx))] for x in m['hour_utc']) + f"   span {m['span_h']} h")
