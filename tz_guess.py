"""Time-zone guess from OPERATOR decisions (not bot fill): (1) sends out of the pots / first-hop theft wallets, (2) wave starts = first
send after >= 45 min chain-wide silence. Score every UTC offset by the share of events in local 08:00–23:00. Local data only.
A guess, not attribution: UTC+8 and UTC+9 (and neighbours) are hard to separate.   python3 tz_guess.py"""
import json, sqlite3, collections, time, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ro = lambda f: sqlite3.connect(f'file:{f}?mode=ro', uri=True)
EV = collections.defaultdict(list)                                   # source -> [utc seconds]
# Tron: first-hop theft wallets (received stolen funds directly) -> their sends; plus all sends for wave starts
import tron_graph as g
C = ro(g.DB); chain = [r for r, _ in g.run_chain(C)]; q = ','.join('?' * len(chain))
first = {t for (t,) in C.execute(f"SELECT DISTINCT too FROM ledger_edge WHERE run_id IN ({q}) AND cls IN ('in:victim','in:stolen')", chain)}
allt = []
for ts, f, cls in C.execute(f"SELECT ts, frm, cls FROM ledger_edge WHERE run_id IN ({q}) AND cls LIKE 'out:%' AND amount > 0", chain):
    allt.append(ts // 1000)
    if f in first: EV['tron pot sends'].append(ts // 1000)
# SOL: pot (root) sends
L = json.load(open('raw/sol_ledger_eagle_0529.json')); sol_all = []
for sig, t, f, to, v, cls in L['edges']:
    if v >= 0.01 and f in L['wallets']: sol_all.append(t)
    if f == L['root'] and v >= 1: EV['sol pot sends'].append(t)
# ETH tree: sends by the big origin pots (ETH / ETH,FBI) — block -> time from a reference block (12 s)
B = ro('binance-bridged.db'); ER = B.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%' ORDER BY run_id DESC LIMIT 1").fetchone()[0]
pots = {a for (a,) in B.execute("SELECT address FROM wallet WHERE run_id=? AND status='tree' AND origin IN ('ETH','ETH,FBI')", (ER,))}
bt = lambda b: 1793682480 + (b - 26331481) * 12; eth_all = []
for b, f, cls in B.execute("SELECT block, frm, cls FROM edge WHERE run_id=? AND amount > 0 AND (cls LIKE 'out:%' OR cls='tree')", (ER,)):
    eth_all.append(bt(b))
    if f in pots: EV['eth pot sends'].append(bt(b))
# wave starts: first send after >= 45 min silence, per chain
for name, xs in (('tron', allt), ('sol', sol_all), ('eth', eth_all)):
    xs = sorted(set(xs)); EV[f'{name} wave starts'] += [b for a, b in zip(xs, xs[1:]) if b - a >= 2700]
dedup = lambda xs: sorted({x // 600 * 600 for x in xs})              # one event per 10-min bucket (a burst = one decision)
E = {k: dedup(v) for k, v in EV.items()}
ALL = sorted({x for v in E.values() for x in v})
print('operator events (10-min buckets):', {k: len(v) for k, v in E.items()}, '· total', len(ALL))
hr = collections.Counter(time.gmtime(t).tm_hour for t in ALL)
print('UTC hour  ' + ' '.join(f'{h:02d}' for h in range(24))); print('events    ' + ' '.join(f'{hr.get(h, 0):2d}' for h in range(24)))
q6 = min(range(24), key=lambda h: sum(hr.get((h + i) % 24, 0) for i in range(6)))
print(f'quietest 6-hour window: {q6:02d}:00–{(q6 + 6) % 24:02d}:00 UTC ({sum(hr.get((q6 + i) % 24, 0) for i in range(6))} events)')
sc = sorted(((sum(1 for t in ALL if 8 <= (time.gmtime(t).tm_hour + o) % 24 <= 23) / len(ALL), o) for o in range(-12, 15)), reverse=True)
print('best-fitting UTC offsets (share of events in local 08–23):', ', '.join(f'UTC{o:+d} {s:.0%}' for s, o in sc[:6]))
print('worst:', ', '.join(f'UTC{o:+d} {s:.0%}' for s, o in sc[-3:]))
for o in (8, 9, 3, 0, -5):
    print(f'  if UTC{o:+d}: quiet window = {(q6 + o) % 24:02d}:00–{(q6 + 6 + o) % 24:02d}:00 local')
