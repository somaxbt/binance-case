"""Separate local page: Solana laundering automation (11-02 04:14→05:09 UTC wave). Reads raw/sol/branch_Fw9P2sFu_*.json + raw/sol/tx_*.json
(read-only, no API, no DB writes). Writes raw/graph/sol_automation.html.   python3 sol_automation_page.py"""
import json, glob, os, time, base64, collections, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
ECH = 'raw/tron/graph/echarts-5.5.1.min.js'; AV = 'raw/tron/graph/avatar.jpg'; OUT = 'raw/graph/sol_automation.html'
PX = 99.03                                                    # SOL display price (theft-time, same as Eagle Eye)
B = json.load(open(sorted(glob.glob('raw/sol/branch_Fw9P2sFu_*.json'))[-1])); T = B['tree']
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58d(s):
    n = 0
    for c in s: n = n * 58 + B58.index(c)
    return n.to_bytes((n.bit_length() + 7) // 8, 'big')
TX = {}
def tx(sig):
    if sig not in TX:
        f = f'raw/sol/tx_{sig}.json'; x = json.load(open(f)) if os.path.exists(f) else None; price = None
        if x:
            for ix in x['transaction']['message']['instructions']:
                if ix.get('programId', '').startswith('ComputeBudget') and 'data' in ix:
                    d = b58d(ix['data'])
                    if d[:1] == b'\x03': price = int.from_bytes(d[1:9], 'little')
        TX[sig] = (x['slot'], x['blockTime'], price) if x else (None, None, None)
    return TX[sig]
FW, ARK, SPR, D99, W4, R2, DJ = ('Fw9P2sFuSRg5VC3nGyh7tx9F76TYVDvQWpaazWpp6848', 'ARk92boxCbssS2p8AL3x9GvLzZYxcRFueXvpUnGGZciQ', '6nBooPf9yUnp3JiuuNpdhFG4BCyHzxEEUUL41hsQc1Jb',
                                 'D99xhiyDjChgMaBEG3nrMnSVyzWcvFtEtKptpEAi9FGd', '4wWwZsntVqgrLeVeZ1fRYYpqxxEidHnpHrNtGfiWjWfy', '2DgwmjsfBkftaeLzN7btQedp8p3wS5qcCxbzHdLPXy4v', 'DjCoWxLLtNNhYVMjbwiquFehGz5dnFa2y7JVUdGZ6vxs')
GAS, OPS = '71thkNU69ZjohtzFoNGkBDHcrkN4WE76FaxBPUbZmAnt', 'G7VLTXkMVaG9NtpvX9gNuMpTPnfQRkyAwWT7LPnaSWVN'
OPER = {FW, ARK, D99, W4}
# ---- timeline events (lane, time, slot, usd, failed, wallet, label, sig)
ev, seen = [], set()
def add(lane, sig, usd, err, wallet, label):
    if (lane, sig) in seen: return
    s, t, p = tx(sig)
    if t: seen.add((lane, sig)); ev.append([lane, t * 1000, s, round(usd, 2), int(err), wallet, label, sig, p])
for a, w in T.items():
    for r in w['flows']:
        usd = sum(v * (PX if s == 'SOL' else 1) for _, s, v in r['out']) or abs(r['dSOL']) * PX + sum(abs(v) for v in r['dTok'].values())
        if r['signer'] == a and a in OPER and (r['out'] or r['dTok']) and not r['err']:
            u = r['dTok'].get('USDC', 0); outs = {to for to, _, _ in r['out']}
            lab = ('Jupiter Lend deposit (SOL → jlWSOL)' if a == W4 and r['dSOL'] < -100 else
                   ('test swap ' if usd < 10000 else 'swap ') + f"{abs(r['dSOL']):,.0f} SOL → USDC" if a == FW else
                   f"swap {abs(u):,.0f} USDC → SOL" if u < -1000 and r['dSOL'] > 1 else
                   f"swap {abs(u):,.0f} USDC → 1,247 SOL" if u < -1000 and W4 in outs else
                   f"{abs(u):,.0f} USDC → bot wallet" if u < -1000 and SPR in outs else
                   'gas refill → bot wallet' if SPR in outs and r['dSOL'] < 0 else 'move')
            add('Operator swaps', r['sig'], usd, 0, a, lab)
        elif r['signer'] == a and a == SPR and (r['out'] or r['err']): add('Bot sprayer', r['sig'], usd, r['err'], a, 'USDC spray' if not r['err'] else 'failed send')
        elif r['signer'] == a and w['depth'] >= 3 and r['out'] and not r['err']: add('Mesh wallets', r['sig'], usd, 0, a, 'mesh pass')
        if r['signer'] == GAS and 0 < r['dSOL'] < 0.2: add('Gas funder', r['sig'], r['dSOL'] * PX, 0, a, 'gas top-up')
        if r['signer'] == OPS and 0 < r['dSOL'] < 0.5: add('Ops wallet', r['sig'], r['dSOL'] * PX, 0, a, 'gas top-up')
for p, lab in (('5xofsbAVP9', 'jlWSOL receipt → new wallet'), ('5s2qR2aDAE', 'Jupiter Lend redeem 1,247 SOL'), ('bf5DrEWWXT', 'send 1,247.1 SOL'), ('3b2CAd1UoX', 'gas top-up')):
    f = glob.glob(f'raw/sol/tx_{p}*.json')
    if f: s = os.path.basename(f[0])[3:-5]; add('Ops wallet' if lab == 'gas top-up' else 'Operator swaps', s, 1247.1 * PX if 'SOL' in lab or 'receipt' in lab else 16, 0, W4 if 'receipt' in lab else R2, lab)
ev.sort(key=lambda e: e[1])
# ---- evidence numbers
sp = sorted((e[2], e[1] / 1000, e[4]) for e in ev if e[0] == 'Bot sprayer'); gaps = [b[0] - a[0] for a, b in zip(sp, sp[1:])]
gas_lead = []
for a, w in T.items():
    fl = sorted(w['flows'], key=lambda r: r['t'])
    g = next((r for r in fl if r['signer'] == GAS and 0 < r['dSOL'] < 0.2), None); u = next((r for r in fl if r['dTok'] or abs(r['dSOL']) >= 0.2), None)
    if g and u and g['t'] <= u['t']: gas_lead.append(u['t'] - g['t'])
mesh = [a for a, w in T.items() if w['depth'] >= 3]
fees = collections.defaultdict(set)
for e in ev:
    if e[0] in ('Operator swaps', 'Ops wallet') and e[8]: fees[e[8]].add(e[5])
EVI = {'spray_sends': len(sp), 'spray_s': round(sp[-1][1] - sp[0][1]), 'spray_same_slot': sum(1 for g in gaps if g == 0), 'spray_le2': sum(1 for g in gaps if g <= 2), 'spray_fail': sum(1 for x in sp if x[2]),
       'gas_wallets': len(gas_lead), 'gas_lead_min': round(st.median(gas_lead) / 60) if gas_lead else 0, 'mesh_wallets': len(mesh),
       'fees': sorted([[p, len(ws)] for p, ws in fees.items() if len(ws) >= 2], key=lambda x: -x[1])}
# ---- flow (sankey, USD widths, native labels)
N = lambda name, sub: {'name': name, 'sub': sub}
nodes = [N('Pot AffzFDKZ', '−13,633 SOL'), N('Fw9P2sFu', '13,464 SOL'), N('Jupiter: SOL → USDC', '10,018 SOL'), N('ARk92box', '948,842 USDC'),
         N('Back to SOL (held)', '830k USDC → 8,716.7 SOL'), N('Bot spray + mesh', '118,842 USDC · ~100 wallets'),
         N('Jupiter Lend hop → DjCoWxLL (held)', '1,247.1 SOL, via lend receipt'),
         N('Fw9P2sFu still holds', '3,446 SOL'), N('Side wallets', 'OKX test 16 · Fz1iggGi 152.8 SOL')]
L = lambda s, t, v: {'source': s, 'target': t, 'value': round(v, 2)}
links = [L('Pot AffzFDKZ', 'Fw9P2sFu', 13464 * PX), L('Pot AffzFDKZ', 'Side wallets', 168.8 * PX),
         L('Fw9P2sFu', 'Jupiter: SOL → USDC', 10018 * PX), L('Fw9P2sFu', 'Fw9P2sFu still holds', 3446 * PX), L('Jupiter: SOL → USDC', 'ARk92box', 948842),
         L('ARk92box', 'Back to SOL (held)', 830000), L('ARk92box', 'Bot spray + mesh', 118842), L('Bot spray + mesh', 'Jupiter Lend hop → DjCoWxLL (held)', 118775)]
# ---- key steps
steps = []
for e in ev:
    if e[0] == 'Operator swaps' or (e[0] == 'Bot sprayer' and not steps or False): steps.append(e)
steps = [e for e in ev if e[0] == 'Operator swaps']
first_spray = next((e for e in ev if e[0] == 'Bot sprayer'), None)
if first_spray: steps.append(first_spray); steps.sort(key=lambda e: e[1])
# ---- investigation graph (TRM / Reactor style): nodes at fixed positions, arrows = amount · time · gap
T0 = 1793592852                                              # pot → Fw9P2sFu (start of the wave); every time below is relative to this
def rel(sec):
    sec = int(round(sec)); m, s_ = divmod(abs(sec), 60)
    return f"{m} min {s_:02d} s" if m else f"{s_} s"
CAT = ['attacker wallet', 'still holds funds', 'bot wallet', 'bot mesh (merged)', 'protocol / service', 'exchange', 'gas / ops wallet']
def nd(i, name, cat, x, y, size=34, addr='', sub=''): return {'id': i, 'name': name, 'category': CAT.index(cat), 'x': x, 'y': y, 'symbolSize': size, 'addr': addr, 'sub': sub}
GN = [nd('pot', 'Pot AffzFDKZ', 'attacker wallet', 0, 263, 56, 'AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU', '453,061 SOL left'),
      nd('fz', 'Fz1iggGi', 'attacker wallet', 262, 46, 26, 'Fz1iggGioypykdhtxKt6a5gKHciuceps6pZrGK93q8WE', 'holds 152.8 SOL'),
      nd('okx', 'OKX', 'exchange', 537, 46, 30, 'FoxKvLEytmFo281TqfYjFAaAPGJakmkr9npwTXK3o8qP', 'test deposit'),
      nd('fw', 'Fw9P2sFu', 'attacker wallet', 262, 263, 40, FW, 'holds 3,446 SOL'),
      nd('dex1', 'Jupiter + DEX', 'protocol / service', 537, 263, 36, '', '5 swaps (merged)'),
      nd('ark', 'ARk92box', 'still holds funds', 812, 263, 50, ARK, 'holds 8,716 SOL'),
      nd('ops', 'G7VLTXkM', 'gas / ops wallet', 1162, 46, 24, OPS, 'ops wallet'),
      nd('spr', '6nBooPf9', 'bot wallet', 1000, 527, 34, SPR, 'bot sprayer'),
      nd('mesh', 'Bot mesh', 'bot mesh (merged)', 1287, 527, 48, '', '101 wallets'),
      nd('gas', '71thkNU6', 'gas / ops wallet', 1137, 775, 26, GAS, 'gas funder'),
      nd('d99', 'D99xhiyD', 'attacker wallet', 1575, 527, 34, D99, 'consolidation'),
      nd('dex2', 'Jupiter', 'protocol / service', 1675, 263, 30, '', 'swap'),
      nd('lend', 'Jupiter Lend hop', 'protocol / service', 1950, 263, 34, R2, '3 steps, 2 wallets (merged)'),
      nd('dj', 'DjCoWxLL', 'still holds funds', 2125, 527, 40, DJ, 'holds 1,247.1 SOL')]
try:                                                           # FBI-listed addresses (attrib.db) → mark nodes
    import sqlite3 as _sq
    _FBI = {a for (a,) in _sq.connect('file:' + os.path.expanduser('~/traversal-engine/data/attrib.db') + '?mode=ro', uri=True).execute("SELECT address FROM attrib_v WHERE source='fbi:psa:2026-10-31'")}
except Exception: _FBI = set()
for _n in GN:
    if _n['addr'] in _FBI: _n['sub'] += ' · FBI-listed'; _n['fbi'] = 1
def ed(a, b, label, gas=False, curve=0): return {'source': a, 'target': b, 'label': label, 'gas': gas, 'curve': curve}
GE = [ed('pot', 'fw', '13,464 SOL'), ed('pot', 'fz', '168.8 SOL'), ed('fz', 'okx', '16 SOL · swept +1 min'),
      ed('fw', 'dex1', '10,018 SOL · +35 min'), ed('dex1', 'ark', '948,842 USDC', curve=.2), ed('ark', 'dex1', '830k USDC → SOL', curve=.2),
      ed('ark', 'spr', '118,842 USDC · +29 s'), ed('spr', 'mesh', f"{EVI['spray_sends']} tx in {rel(EVI['spray_s'])}"),
      ed('mesh', 'd99', '118,775 USDC · ~8 min'), ed('d99', 'dex2', '+4 min'), ed('dex2', 'lend', '1,247 SOL'),
      ed('lend', 'dj', '1,247 SOL · 81 s'),
      ed('gas', 'mesh', f"gas ~{EVI['gas_lead_min']} min early", True), ed('gas', 'spr', '', True, .2),
      ed('ark', 'spr', 'refill', True, -.3), ed('ops', 'ark', 'gas 9 min early', True),
      ed('ops', 'lend', 'gas 2 min early', True, -.1)]
PROOF = [['USDC lands → bot starts spraying', '34 s', 'reacts to its own balance change'],
         ['Spray cadence', f"{EVI['spray_sends']} sends in {rel(EVI['spray_s'])}; {EVI['spray_le2']} of {EVI['spray_sends']-1} gaps under 1 s; {EVI['spray_same_slot']} in the same block", 'parallel signing — no human clicks twice per second'],
         ['Fail → refill → resume', f"{EVI['spray_fail']} fails in 12 s, refill, resumed 33 s later", 'retry loop with automatic top-up'],
         ['Gas before use', f"{EVI['gas_wallets']} wallets funded ~{EVI['gas_lead_min']} min before first use", 'wallets created in bulk before the swap'],
         ['Mesh hold times', '20 s to 12 min, random', 'randomised delays to look like separate users'],
         ['Receipt chain', 'swap → 37 s deposit → 20 s receipt → 24 s redeem → 97 s send', 'four contract steps in 81 s across two wallets'],
         ['Same priority fees on different wallets', '40,000 · 100,000 · 133,333,334', 'one toolset signing for many wallets']]
DATA = {'built': time.strftime('%F %H:%M UTC', time.gmtime()), 'events': ev, 'evi': EVI, 'nodes': nodes, 'links': links,
        'steps': [[e[2], e[1], e[5], e[6], e[3], e[8], e[7]] for e in steps], 'lanes': ['Operator swaps', 'Bot sprayer', 'Mesh wallets', 'Gas funder', 'Ops wallet'],
        'held': [['ARk92box…ZciQ', ARK, 8716.29], ['Fw9P2sFu…6848', FW, 3445.95], ['DjCoWxLL…6vxs', DJ, 1247.1], ['Fz1iggGi…q8WE', 'Fz1iggGioypykdhtxKt6a5gKHciuceps6pZrGK93q8WE', 152.8]],
        'graph': {'nodes': GN, 'edges': GE}, 'proof': PROOF, 't0': T0, 'cats': CAT, 'keys': [['Gas funder (bot farm)', GAS], ['Ops wallet (just-in-time gas)', OPS], ['OKX deposit address (test)', 'FoxKvLEytmFo281TqfYjFAaAPGJakmkr9npwTXK3o8qP']]}
uri = 'data:image/jpeg;base64,' + base64.b64encode(open(AV, 'rb').read()).decode() if os.path.exists(AV) else ''
HTML = open(os.path.join(HERE, 'sol_automation_template.html')).read().replace('/*__ECHARTS__*/', open(ECH).read()).replace('/*__DATA__*/null', json.dumps(__import__('tron_graph').safe(DATA))).replace('__AVATAR__', uri)
os.makedirs('raw/graph', exist_ok=True); open(OUT, 'w').write(HTML)
print('wrote', OUT, '| events', len(ev), collections.Counter(e[0] for e in ev), '| evidence', EVI)
