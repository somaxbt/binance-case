"""Local page: Solana PHASE B (3 Nov 02:18–05:10 UTC) — Jupiter Lend redeem → SOL peel chain → round-chunk sells via Jupiter RFQ
(market makers fill + pay the fees) → CCTP burn of the exact USDC seconds later → Noble forwarding → dYdX. Read-only: pinned 05:29 ledger
(raw/sol_ledger_eagle_0529.json), raw/sol/tx_*.json, burns_resolved.json, noble_forwarding.json. Writes raw/graph/sol_automation.html
(wave-1 page kept as raw/graph/sol_automation_wave1.html).   python3 sol_phaseb_page.py"""
import json, os, time, base64, collections, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
ECH, AV, OUT = 'raw/tron/graph/echarts-5.5.1.min.js', 'raw/tron/graph/avatar.jpg', 'raw/graph/sol_automation.html'
PX = 99.03; T_LO, T_HI = 1793664000 + 2 * 3600, 1793664000 + 5 * 3600 + 30 * 60          # 11-03 02:00 → 05:30 UTC
L = json.load(open('raw/sol_ledger_eagle_0529.json')); W = L['wallets']; RFQ = '61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH'
BR = {r[0]: r for r in json.load(open('raw/sol/burns_resolved.json'))}; FW = json.load(open('raw/sol/noble_forwarding.json'))
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58d(s):
    n = 0
    for c in s: n = n * 58 + B58.index(c)
    return n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
def txm(sig):
    t = json.load(open(f'raw/sol/tx_{sig}.json')); m = t['transaction']['message']; p = lim = None
    for i in m['instructions']:
        if i.get('programId', '').startswith('ComputeBudget') and 'data' in i:
            d = b58d(i['data'])
            if d[:1] == b'\x03': p = int.from_bytes(d[1:9], 'little')
            if d[:1] == b'\x02': lim = int.from_bytes(d[1:5], 'little')
    k = m['accountKeys'][0]; return {'slot': t['slot'], 'signer': k['pubkey'] if isinstance(k, dict) else k, 'cu': p, 'lim': lim}
sh = lambda a: a[:6]
sh2 = lambda a: a[:6]          # screenshot-friendly: first 6 + last 4
# ---- the pieces
swaps = sorted([e for e in L['edges_tok'] if e[6] == 'in: swap (DEX)' and e[5] == 'USDC' and T_LO <= e[1] <= T_HI and e[4] >= 50000], key=lambda e: e[1])
burns = sorted([e for e in L['edges_tok'] if e[6] == 'out: burned' and T_LO <= e[1] <= T_HI], key=lambda e: e[1])
sellers = sorted({e[3] for e in swaps}, key=lambda a: min(e[1] for e in swaps if e[3] == a))
gave = collections.defaultdict(float)
for sig, t, f, to, v, cls in L['edges']:
    if cls == 'out: swap (DEX)' and f in sellers and T_LO <= t <= T_HI: gave[sig] += v
redeem = {}
for e in sorted(L['edges'], key=lambda e: e[1]):
    if e[5] == 'redeem Jupiter Lend' and e[3] in sellers and T_LO - 3600 <= e[1] <= T_HI:
        t0, v0 = redeem.get(e[3], (e[1], 0)); redeem[e[3]] = (t0, v0 + e[4])     # first time, summed SOL (CyBgxHUK had 2)
peel = sorted([e for e in L['edges'] if e[5] == 'out: tree' and e[2] in sellers and e[3] in sellers and e[4] >= 100 and T_LO <= e[1] <= T_HI], key=lambda e: e[1])
T0 = swaps[0][1]
M = {e[0]: txm(e[0]) for e in swaps + burns + peel}
# ---- evidence
lag = []                                                  # swap → first burn by the same wallet
for e in swaps:
    b = next((x for x in burns if x[2] == e[3] and x[1] >= e[1]), None)
    if b: lag.append((b[1] - e[1], abs(b[4] - e[4]) < 1))
cu = collections.Counter((M[b[0]]['cu'], M[b[0]]['lim']) for b in burns); top_cu, top_n = cu.most_common(1)[0]
mm = collections.Counter(M[e[0]]['signer'] for e in swaps)
dydx = {(FW.get(BR[b[0]][5]) or {}).get('recipient') for b in burns if b[0] in BR and BR[b[0]][4] == 'Noble'} - {None}
to_dydx = sum(b[4] for b in burns if b[0] in BR and BR[b[0]][4] == 'Noble'); to_arb = sum(b[4] for b in burns if b[0] in BR and BR[b[0]][4] == 'Arbitrum')
sold = sum(gave.values()); usdc = sum(e[4] for e in swaps)
lot = [e[1] for e in swaps if e[3] in sellers[:3]]
loop = [round((b - a) / 60, 1) for a, b in zip(sorted(set(e[1] for e in swaps if e[3] in (sellers[1], sellers[2]))), sorted(set(e[1] for e in swaps if e[3] in (sellers[1], sellers[2])))[1:])]
minus2 = sum(1 for b in burns if abs((b[4] + 0.02) - round(b[4] + 0.02)) < 0.005)
wallet_dydx = {}
for b in burns:
    if b[0] in BR and BR[b[0]][4] == 'Noble': wallet_dydx.setdefault(b[2], set()).add((FW.get(BR[b[0]][5]) or {}).get('recipient'))
one2one = sum(1 for w, s in wallet_dydx.items() if len(s) == 1)
chain1 = [e for e in peel]; balances = [round(e[4], 2) for e in peel]
f_utc = lambda t: time.strftime('%H:%M', time.gmtime(t))
EVI = {'swaps': len(swaps), 'burns': len(burns), 'sold': sold, 'usdc': usdc, 'dydx': len(dydx), 'to_dydx': to_dydx, 'to_arb': to_arb,
       'lag_min': min(l for l, _ in lag), 'lag_max': max(l for l, _ in lag), 'lag_med': st.median(l for l, _ in lag), 'exact': sum(1 for _, x in lag if x), 'n_lag': len(lag),
       'cu': top_cu, 'cu_n': top_n, 'mm': mm.most_common(), 'loop': loop, 'minus2': minus2, 'one2one': one2one, 'sellers': len(sellers), 'redeems': len(redeem)}
# ---- loading: FBI-listed pot → layering hops → deposit wallet → Jupiter Lend (deposit) → receipt to fresh seller → redeem
VAULT = '5JP5zgYCb9W37QQLgAHRHuinFLrKt87akDY1CgZoTPzr'
jl = [e for e in L['edges_tok'] if e[5] == 'jlWSOL']
parL = collections.defaultdict(list)
HOPS = []                                                      # (t, sender, sig) of every layering hop on the pot→depositor paths
for e in L['edges']:
    if e[5] == 'out: tree': parL[e[3]].append((e[1], e[2], e[4], e[0]))
for e in jl:
    if e[6] == 'out: tree': parL[e[3]].append((e[1], e[2], e[4], e[0]))
def potpath(w, t):
    out, cur = [], w
    for _ in range(20):
        if cur == L['root']: return out
        c = [x for x in parL.get(cur, []) if x[0] <= t]
        if not c: return None
        x = max(c, key=lambda x: x[2]); t, cur = x[0], x[1]; out.append(cur); HOPS.append((x[0], x[1], x[3]))
    return None
LOAD = {}                                                      # chain-start seller -> loading facts
for e in jl:
    if e[6] == 'out: tree' and e[3] in sellers:
        d = next((x for x in jl if x[3] == e[2] and x[6] == 'in: lend receipt'), None)
        if not d: continue
        deps = sorted([(x[1], x[4], x[0]) for x in L['edges'] if x[2] == e[2] and x[3] == VAULT and d[1] - 5 <= x[1] <= e[1]]); dep_sol = sum(x[1] for x in deps)   # 2 deposits: round chunk, then the rest
        red = min([x for x in L['edges'] if x[3] == e[3] and x[5] == 'redeem Jupiter Lend' and x[1] >= e[1]], key=lambda x: x[1], default=None)
        pp = potpath(e[2], d[1])
        LOAD[e[3]] = {'dep': e[2], 't_dep': d[1], 'dep_sol': dep_sol, 'deps': deps, 'rcpt_sig': e[0], 'cu_dep': txm(d[0])['cu'], 't_rcpt': e[1], 'cu_rcpt': txm(e[0])['cu'],
                      't_red': red[1] if red else None, 'red_sol': red[4] if red else None, 'hops': len(pp) if pp else None, 'path': pp or []}
peel_cu = collections.Counter(M[e[0]]['cu'] for e in peel)
W0 = 1793664000 + 5400                                           # 11-03 01:30 UTC: window for the loading stages (one path also hops 11-02 10:01–10:47)
red_ev = sorted([x for x in L['edges'] if x[5] == 'redeem Jupiter Lend' and x[3] in sellers and x[1] >= W0], key=lambda x: x[1])
STG = [('Layering hop', [(t, w, sg) for t, w, sg in sorted(set(HOPS)) if t >= W0]),
       ('Lend deposit', [(x[0], v['dep'], x[2]) for v in LOAD.values() for x in v['deps']]),
       ('Receipt hand-off', [(v['t_rcpt'], v['dep'], v['rcpt_sig']) for v in LOAD.values()]),
       ('Lend redeem', [(x[1], x[3], x[0]) for x in red_ev]),
       ('SOL passed on', [(e[1], e[2], e[0]) for e in peel]),
       ('SOL → USDC (RFQ)', [(e[1], e[3], e[0]) for e in swaps]),
       ('CCTP burn → Noble', [(e[1], e[2], e[0]) for e in burns])]
STAGES = []
for name, evs in STG:
    fs = [(txm(sg)['cu'], txm(sg)['lim']) for _, _, sg in evs]; main = collections.Counter(c for c, _ in fs).most_common(1)[0][0] if fs else None
    STAGES.append({'stage': name, 'n': len(fs), 'main': main, 'n_main': sum(1 for c, _ in fs if c == main), 'mm': name.startswith('SOL → USDC'),
                   'items': [{'k': 'main' if c == main else 'none' if c is None else 'other', 'cu': c, 'lim': l, 't': time.strftime('%H:%M:%S', time.gmtime(t)), 'w': w[:8]} for (c, l), (t, w, _) in zip(fs, evs)]})
# ---- timeline events [lane, t_ms, slot, usd, err, wallet, label, sig, cu_price]
LANES = ['Layering hop', 'Lend deposit', 'Receipt hand-off', 'Lend redeem', 'SOL passed on', 'SOL → USDC (RFQ)', 'CCTP burn → Noble']
ev = []
for name, evs in STG[:4]:
    for t, w, sg in evs:
        ev.append([name, t * 1000, txm(sg)['slot'], 0, 0, w, name.lower(), sg, None])
for e in peel: ev.append(['SOL passed on', e[1] * 1000, M[e[0]]['slot'], e[4] * PX, 0, e[2], f'pass {e[4]:,.2f} SOL → {sh(e[3])}', e[0], None])
for e in swaps: ev.append(['SOL → USDC (RFQ)', e[1] * 1000, M[e[0]]['slot'], e[4], 0, e[3], f"sell {gave.get(e[0], 0):,.0f} SOL → {e[4]:,.0f} USDC (filled by {sh(M[e[0]]['signer'])})", e[0], None])
for e in burns:
    r = BR.get(e[0]); dst = 'Arbitrum' if r and r[4] == 'Arbitrum' else 'dYdX ' + sh((FW.get(r[5]) or {}).get('recipient', '?')[4:]) if r else '?'
    ev.append(['CCTP burn → Noble', e[1] * 1000, M[e[0]]['slot'], e[4], 0, e[2], f'CCTP burn {e[4]:,.2f} USDC → {dst}', e[0], None])
for e in ev: e[2] = e[2] or 0
ev.sort(key=lambda e: e[1])
# ---- graph (fixed layout): 4 peel chains on top, RFQ → CCTP → dYdX underneath
par = {e[3]: e[2] for e in peel}
roots = [a for a in sellers if a not in par]
chains = []
for r in roots:
    c = [r]
    while True:
        nx = next((e[3] for e in peel if e[2] == c[-1]), None)
        if not nx or nx in c: break
        c.append(nx)
    chains.append(c)
chains.sort(key=lambda c: -len(c))
CAT = ['attacker wallet', 'still holds funds', 'bot wallet', 'bot mesh (merged)', 'protocol / service', 'exchange', 'gas / ops wallet']
def nd(i, name, cat, x, y, size=30, addr='', sub=''): return {'id': i, 'name': name, 'category': CAT.index(cat), 'x': x, 'y': y, 'symbolSize': size, 'addr': addr, 'sub': sub}
GN, GE = [], []
sold_by = collections.defaultdict(float); usdc_by = collections.defaultdict(float)
for e in swaps: sold_by[e[3]] += gave.get(e[0], 0); usdc_by[e[3]] += e[4]
GN.append(nd('lend', 'Jupiter Lend', 'protocol / service', -120, 255, 40, '', 'shared pool'))
mid = {w for v in LOAD.values() for w in v['path']} - {L['root']} - {v['dep'] for v in LOAD.values()}
hh = sorted(v['hops'] for v in LOAD.values() if v['hops'])
GN += [nd('pot', 'FBI-listed wallet ' + sh2(L['root']), 'still holds funds', -1180, 255, 50, L['root'], 'starting point'),
       nd('hops', 'layering hops', 'attacker wallet', -930, 255, 30, '', f"{hh[0]}–{hh[-1]} hops")]
GE.append({'source': 'pot', 'target': 'hops', 'label': '', 'gas': False, 'curve': 0})
for ci, c in enumerate(chains):
    y = ci * 170
    for k, a in enumerate(c):
        GN.append(nd(a, sh2(a), 'attacker wallet', 280 + k * 280, y, 30, a, 'selling wallet'))
        if k == 0 and a in redeem: GE.append({'source': 'lend', 'target': a, 'label': 'redeem (bot)' if ci == 0 else '', 'gas': False, 'curve': 0, 'kind': 'bot'})
        if k == 0 and a in LOAD:
            v = LOAD[a]; dn = 'dep_' + v['dep']
            GN.append(nd(dn, sh2(v['dep']), 'attacker wallet', -660, y, 24, v['dep'], 'deposit wallet'))
            GE.append({'source': 'hops', 'target': dn, 'label': '', 'gas': False, 'curve': 0})
            GE.append({'source': dn, 'target': 'lend', 'label': 'deposit (bot)' if ci == 0 else '', 'gas': False, 'curve': 0, 'kind': 'bot'})
            GE.append({'source': dn, 'target': a, 'label': 'receipt handed over (bot)' if ci == 0 else '', 'gas': False, 'curve': -.12, 'kind': 'bot'})
    for e in peel:
        if e[2] in c and e[3] in c: GE.append({'source': e[2], 'target': e[3], 'label': 'passes the rest on' if (ci == 0 and e[2] == c[0]) else '', 'gas': False, 'curve': 0})
xs = 280 + max(len(c) for c in chains) * 280
GN += [nd('rfq', 'sold for dollars (USDC)', 'protocol / service', 420, 780, 40, RFQ, 'Jupiter RFQ'),
       nd('cctp', 'sent to another blockchain', 'protocol / service', 1120, 780, 40, '', 'CCTP → Noble'),
       nd('dydx', f'{len(dydx)} dYdX trading accounts', 'still holds funds', 1640, 700, 46, '', 'one per selling wallet'),
       nd('arb', 'Arbitrum 0x86fd', 'still holds funds', 1640, 900, 30, '', 'CCTP v2 (other tool)')]
nlots = collections.Counter(e[3] for e in swaps)
for k, a in enumerate(sellers): GE.append({'source': a, 'target': 'rfq', 'label': '', 'gas': False, 'curve': 0, 'kind': 'human'})
GE += [{'source': 'rfq', 'target': 'cctp', 'label': 'bot bridges the exact USDC out', 'gas': False, 'curve': 0, 'kind': 'bot'},
       {'source': 'cctp', 'target': 'dydx', 'label': 'bot: same dYdX account every time', 'gas': False, 'curve': 0, 'kind': 'bot'},
       {'source': 'cctp', 'target': 'arb', 'label': 'CCTP v2 (other tool)', 'gas': False, 'curve': 0}]
loopers = [a for a in sellers if nlots[a] >= 3]                       # the timer loop: next lot ~8–9 min (dashed, back to the seller)
for k, a in enumerate(loopers): GE.append({'source': 'cctp', 'target': a, 'label': 'bot repeats: next sale' if k == 0 else '', 'gas': True, 'kind': 'bot', 'curve': -.25 - .08 * k})
for n in GN:
    n['sub'] = n['sub'].replace('sold 0 SOL', 'passes SOL on')
    if nlots.get(n['id'], 0) > 1: n['sub'] += f" · {nlots[n['id']]} sales"
    if n['id'] == 'rfq': n['sub'] += ' · a person picks each chunk size'
    n['sub'] = n['sub'].replace('passes SOL on', 'selling wallet')
# ---- why: outrun screening (fresh wallets, FBI-listed pot never touches a screened service, Jupiter Lend vault as the cleaning step)
import sqlite3 as _sq
FBI = {a for (a,) in _sq.connect('file:' + os.path.expanduser('~/traversal-engine/data/attrib.db') + '?mode=ro', uri=True).execute("SELECT address FROM attrib_v WHERE source='fbi:psa:2026-10-31'")}
FSn = L.get('first_seen') or {}
fresh = [(min(e[1] for e in swaps if e[3] == a) - FSn[a]) / 60 for a in sellers if FSn.get(a)]
life = [(max([b[1] for b in burns if b[2] == a] or [0]) - FSn[a]) / 60 for a in sellers if FSn.get(a)]
parT = collections.defaultdict(list)
for e in L['edges']:
    if e[5] == 'out: tree': parT[e[3]].append((e[1], e[2], e[4]))
def hops(w, t):
    n, cur = 0, w
    while cur != L['root'] and n < 15:
        c = [x for x in parT.get(cur, []) if x[0] <= t]
        if not c: return None
        t, cur, _ = max(c, key=lambda x: x[2]); n += 1
    return n
jl = [e for e in L['edges_tok'] if e[5] == 'jlWSOL']; dep_h = []
for e in jl:
    if e[3] in sellers and e[6] == 'out: tree':
        d = next((x for x in jl if x[3] == e[2] and x[6] == 'in: lend receipt'), None)
        if d: dep_h.append(hops(e[2], d[1]))
dep_h = sorted(h for h in dep_h if h)
WHY = {'fresh_med': st.median(fresh), 'fresh_max': max(fresh), 'life_min': min(life), 'life_max': max(life), 'pot_fbi': L['root'] in FBI,
       'sell_fbi': sum(a in FBI for a in sellers), 'burn_fbi': sum(b[2] in FBI for b in burns), 'dep_h': dep_h}
# ---- text
PROOF = [['Swap → burn', f"first burn {EVI['lag_min']}–{EVI['lag_max']} s after each swap (median {EVI['lag_med']:.0f} s); {EVI['exact']} of {EVI['n_lag']} burn the exact USDC just received", 'reacts to its own balance — scripted hand-off'],
         ['Same burn settings', f"{top_n} of {len(burns)} transfers out use identical software settings", 'one tool signing every burn'],
         ['Sale rhythm', 'one sale every ~' + (f"{st.median(loop):.0f} min ({', '.join(f'{x}' for x in loop[:6])} min)" if loop else '—'), 'a timer, not a person reacting'],
         ['Pass-along chain', ' → '.join(f'{e[4]:,.2f}' for e in peel if e[2] in chains[0] and e[3] in chains[0]) + ' SOL (main chain)', 'each hop keeps a round chunk (1,200 / 1,500 / 2,000 SOL) to sell, passes the rest'],
         ['Swaps signed by market makers', ' · '.join(f'{sh(a)} {n}×' for a, n in EVI['mm']), 'Jupiter RFQ: the filler submits and pays the fees'],
         ['One dYdX account per seller', f"{one2one} of {len(wallet_dydx)} seller wallets always burn to the same dYdX account", 'routes set up in advance (one Noble forwarding address each)'],
         ['Loading uses the same tool', f"each step uses its own fixed settings on every wallet (deposits {STAGES[1]['n_main']}/{STAGES[1]['n']}, hand-offs {STAGES[2]['n_main']}/{STAGES[2]['n']}, pass-ons {STAGES[4]['n_main']}/{STAGES[4]['n']}); deposit → receipt {min(v['t_rcpt'] - v['t_dep'] for v in LOAD.values())}–{max(v['t_rcpt'] - v['t_dep'] for v in LOAD.values())} s, receipt → redeem {min(v['t_red'] - v['t_rcpt'] for v in LOAD.values() if v['t_red'])}–{max(v['t_red'] - v['t_rcpt'] for v in LOAD.values() if v['t_red'])} s", 'one toolset loads every wallet — the same settings also appear in the 2 Nov wave'],
         ['Outrun screening', f"sellers sell {WHY['fresh_med']:.0f} min (max {WHY['fresh_max']:.0f}) after their first activity and are done in {WHY['life_min']:.0f}–{WHY['life_max']:.0f} min; starting wallet FBI-listed; selling wallets on the FBI list: {WHY['sell_fbi']} of {len(sellers)}; Jupiter Lend deposit wallets {'/'.join(map(str, WHY['dep_h']))} hops from it", 'faster than any label; screened services only ever see clean-looking fresh wallets'],
         ['Human-set sizes', f"{minus2} of {len(burns)} burns are a whole number − 0.02 USDC; sells in round SOL chunks", 'a person sets the amounts the script uses']]
CARDS = [[f"{EVI['lag_min']}–{EVI['lag_max']} s swap → burn", f"USDC never sat in a freezable wallet for long: each sale was bridged out within seconds to two minutes (median {EVI['lag_med']:.0f} s), {EVI['exact']} of {EVI['n_lag']} times for the exact amount received."],
         [f"{top_n} of {len(burns)} burns, one setting", 'Identical software settings on almost every transfer out — the same tool. The 2 transfers to Arbitrum use different settings (another tool).'],
         ['Pass-along chains after Jupiter Lend', f"All {len(chains)} chains start with a Jupiter Lend redemption; each wallet sells a round SOL chunk and passes the rest to a fresh wallet."],
         ['Market makers fill the swaps', "Swaps went through Jupiter's RFQ engine: a market maker signs, submits and pays for the transaction — the attacker wallet never pays the fee."],
         [f"{len(dydx)} dYdX accounts, one per seller", 'Every seller wallet bridges to its own dYdX account through its own Noble forwarding address — set up before the run.'],
         ['Why: outrun screening', f"The starting wallet is FBI-listed, so it never touches a screened service. Value goes {'–'.join(map(str, WHY['dep_h'][:1] + WHY['dep_h'][-1:]))} hops out, through Jupiter Lend's shared vault (the redeemed SOL comes from the protocol, not the attacker), into fresh wallets that sell and bridge out within {WHY['life_min']:.0f}–{WHY['life_max']:.0f} min — before screening services can label them. Each hop also slows investigators."],
         ['A person sets the sizes', 'Round SOL chunks and whole-dollar burn sizes (− 0.02) point to a human choosing the amounts; the script does the rest. Circle froze nothing.']]
KPIS = [[f"{usdc:,.0f} dollars (USDC)", f"made by selling {sold:,.0f} stolen SOL in {len(swaps)} sales"], [f"{to_dydx:,.0f} dollars", f"moved to {len(dydx)} trading accounts on another blockchain (dYdX)"],
        [f"~{EVI['lag_med']:.0f} seconds", 'from each sale until the dollars leave Solana'], [f"{top_n} of {len(burns)}", 'transfers out with identical software settings (one program)']]
held = [[sh(a), a, W[a]['held']] for a in sellers if W.get(a)]
KEYS = [['Jupiter RFQ program (Order Engine)', RFQ]] + [[f'Market maker that filled {n} swaps', a] for a, n in EVI['mm']] + [['Arbitrum recipient (CCTP v2)', '0x86fdce16181761efeb8acd256cc3d4c9852851f6']] + [['dYdX account', d] for d in sorted(dydx)]
# ---- "How the laundering appears to have been automated": (A) one real lot step by step, (B) every lot on one clock, (C) burn fingerprint strip
chain_of = {a: ci for ci, c in enumerate(chains) for a in c}
LOTS = []
for k, e in enumerate(swaps):
    b = next((x for x in burns if x[2] == e[3] and x[1] >= e[1]), None)
    nxt = next((x for x in swaps[k + 1:] if chain_of.get(x[3]) == chain_of.get(e[3])), None)
    LOTS.append({'label': f"{f_utc(e[1])} · {sh(e[3])}", 'sol': round(gave.get(e[0], 0)), 'usdc': round(e[4]), 'lag': (b[1] - e[1]) if b else None,
                 'exact': bool(b and abs(b[4] - e[4]) < 1), 'gap_min': round((nxt[1] - e[1]) / 60, 1) if nxt else None})
ex = [e for e in swaps if e[3].startswith('aNbFweuP')]; ex = ex[1] if len(ex) > 1 else swaps[0]
exb = next(x for x in burns if x[2] == ex[3] and x[1] >= ex[1]); exn = next((x for x in swaps if x[3] in chains[chain_of[ex[3]]] and x[1] > ex[1]), None)
exd = (FW.get(BR[exb[0]][5]) or {}).get('recipient', '?') if exb[0] in BR else '?'; red = redeem.get(chains[chain_of[ex[3]]][0])
lo = LOAD.get(chains[chain_of[ex[3]]][0], {})
CYCLE = ([[f_utc(lo['t_dep']), f"FBI-listed wallet → {lo['hops']} layering hops → deposit wallet {sh(lo['dep'])}", 'source'],
          [time.strftime('%H:%M:%S', time.gmtime(lo['t_dep'])), f"deposits {' + '.join(f'{x[1]:,.0f}' for x in lo['deps'])} SOL into Jupiter Lend ({len(lo['deps'])} deposits {lo['deps'][-1][0] - lo['deps'][0][0]} s apart: round chunk, then the rest)", 'script'],
          [f"+{lo['t_rcpt'] - lo['deps'][-1][0]} s", f"hands the whole receipt to fresh wallet {sh(chains[chain_of[ex[3]]][0])}", 'script'],
          [f"+{lo['t_red'] - lo['t_rcpt']} s" if lo.get('t_red') else '', f"{sh(chains[chain_of[ex[3]]][0])} redeems {lo['red_sol']:,.0f} SOL — it now comes from the shared vault, not the attacker", 'script']] if lo else []) + [
         ['', f"{sh(ex[3])} now holds clean-looking SOL", 'source'],
         [time.strftime('%H:%M:%S', time.gmtime(ex[1])), f"SELL {gave.get(ex[0], 0):,.0f} SOL → {ex[4]:,.2f} USDC — Jupiter RFQ; market maker {sh(M[ex[0]]['signer'])} signs and pays the fee", 'human sets size'],
         [f"+{exb[1] - ex[1]} s", f"BURN {exb[4]:,.2f} USDC via CCTP — the amount just received; identical configuration to {top_n} of {len(burns)} transfers out", 'script'],
         ['~1 min', f"Noble forwarding address → dYdX {exd[:12]}… — this wallet always lands in this account", 'route set up in advance'],
         [f"+{round((exn[1] - ex[1]) / 60)} min" if exn else '', f"next sale ({time.strftime('%H:%M:%S', time.gmtime(exn[1]))}) — same steps, same timings" if exn else 'next sale — same steps', 'timer'],
         ['', 'when the wallet runs low it passes the rest of its SOL to a fresh wallet → the loop continues there', 'passes it on']]
FP = [{'k': ('main' if (M[b[0]]['cu'], M[b[0]]['lim']) == top_cu else 'v2' if b[0] in BR and BR[b[0]][4] == 'Arbitrum' else 'other'), 't': time.strftime('%H:%M:%S', time.gmtime(b[1])), 'usdc': round(b[4], 2),
       'cu': M[b[0]]['cu'], 'lim': M[b[0]]['lim']} for b in burns]
# ---- plain-language layer for non-specialists (all numbers from the data above)
hh2 = sorted(v['hops'] for v in LOAD.values() if v['hops'])
PLAIN = [{'n': '1', 'title': 'Stolen coins sit in a flagged wallet', 'big': f"{W[L['root']]['held']:,.0f} SOL", 'text': 'The FBI has listed this wallet. Any service that checks wallets would refuse it, so it never deals with one directly.', 'who': 'start'},
         {'n': '2', 'title': 'Shuffled through throwaway wallets', 'big': f"{hh2[0]}-{hh2[-1]} hops", 'text': f"A program passes the coins through {len(mid)} brand-new wallets, often one every minute or two.", 'who': 'program'},
         {'n': '3', 'title': 'Washed through a shared savings pool', 'big': f"{sum(v['dep_sol'] for v in LOAD.values()):,.0f} SOL", 'text': 'The coins go into Jupiter Lend, a big pool many people use. A fresh wallet takes them out a minute later. Now they look like they came from the pool, not the thief.', 'who': 'program'},
         {'n': '4', 'title': 'Sold for dollars, in chunks', 'big': f"{usdc:,.0f} USDC", 'text': f"{len(swaps)} sales of round amounts of SOL. A person picks the size; a market maker fills the order and even pays the fee.", 'who': 'person'},
         {'n': '5', 'title': 'Sent to another blockchain in seconds', 'big': f"~{EVI['lag_med']:.0f} s", 'text': f"A program moves the dollars to dYdX (another blockchain) about {EVI['lag_med']:.0f} seconds after each sale, to the same account every time, then starts the next sale about every {st.median(loop):.0f} minutes.", 'who': 'program'}]
PROOFS = [['Same settings, every time', f"Every transaction carries settings picked by the software that sent it. Here they are identical across many different wallets: {STAGES[1]['n_main']} of {STAGES[1]['n']} pool deposits, {STAGES[2]['n_main']} of {STAGES[2]['n']} hand-offs, {STAGES[6]['n_main']} of {STAGES[6]['n']} transfers out. Like the same handwriting on every letter: one program wrote them."],
          ['Faster than a person', f"Dollars leave {EVI['lag_min']}-{EVI['lag_max']} seconds after each sale, the pool round trip takes about a minute, and new sales start on a steady ~{st.median(loop):.0f}-minute rhythm."],
          ['Brand-new wallets, used once', f"Each selling wallet starts selling about {WHY['fresh_med']:.0f} minutes after it first appears and is finished within {WHY['life_min']:.0f}-{WHY['life_max']:.0f} minutes, too fast for watch-lists to catch. None of them is on the FBI list; the flagged wallet is {hh2[0]}-{hh2[-1]} steps behind."]]
# ---- every address on the page, full (for screenshots: nothing depends on hover)
KEYS = [['FBI-listed wallet (where the stolen SOL sits)', L['root']]]
KEYS += [['Layering wallet', w] for w in sorted(mid)]
KEYS += [[f"Jupiter Lend deposit wallet → seller {sh2(a)}", v['dep']] for a, v in LOAD.items()]
for ci, c in enumerate(chains):
    KEYS += [[f"Selling wallet · chain {ci + 1}, step {k + 1}", a] for k, a in enumerate(c)]
KEYS += [['dYdX trading account', d] for d in sorted(dydx)] + [['Arbitrum wallet (CCTP v2)', '0x86fdce16181761efeb8acd256cc3d4c9852851f6']]
KEYS += [['Jupiter RFQ program (Order Engine)', RFQ]] + [[f'Market maker (filled {n} sales)', a] for a, n in EVI['mm']]
for g in STAGES:
    for it in g['items']: it.pop('cu', None); it.pop('lim', None)
    g['main'] = None if g['main'] is None else 'set'
FP = [{k: v for k, v in f.items() if k not in ('cu', 'lim')} for f in FP]
_built = time.strftime('%F %H:%M UTC', time.gmtime()); _n_att = 1 + len(mid) + len(LOAD) + len(sellers)
TAIL = (f"<b>Data as of 05:29 UTC</b> (activity since {f_utc(min(e[1] for e in ev) / 1000)} UTC)<br>{_n_att} attacker wallets traced · page built {_built}<br>"
        "Amounts in native units · USD at theft-time prices, for scale only<br>Built from raw on-chain data. Automation is inferred from timing and repeated transaction settings — not confirmed.")
D_ = ' <b>•</b> '
GHOW = ('<div style="margin-bottom:4px;max-width:520px"><b>How to read:</b> money moves left to right, from the FBI-listed wallet to the dYdX accounts' + D_ +
        'line colours show who did each step (legend, top right)' + D_ + 'full addresses are in the table at the bottom</div>' + TAIL)
MHOW = ('<div style="margin-bottom:4px;max-width:900px"><b>How to read:</b> left — one real sale, step by step, tagged with who did it' + D_ +
        'right — every sale lined up at 0 s: dot = seconds until the dollars left Solana, bar = minutes until the next sale' + D_ +
        'bottom — share of transactions in each step with an identical configuration</div>' + TAIL)
THOW = ('<div style="margin-bottom:4px;max-width:520px"><b>How to read:</b> each row is one step, each dot one transaction (bigger = more value)' + D_ +
        'left to right is time, in minutes from the first sale at ' + f_utc(T0) + ' UTC</div>' + TAIL)
DATA = {'built': time.strftime('%F %H:%M UTC', time.gmtime()), 'events': ev, 'evi': {'fees': []}, 'nodes': [], 'links': [],
        'steps': [[e[2], e[1], e[5], e[6], e[3], None, e[7]] for e in ev if e[7]], 'lanes': LANES, 'laneVars': ['--mesh', '--svc', '--exch', '--gas', '--ops', '--att', '--bot'], 'stages': STAGES,
        'gkey': '<b>How to read:</b> <span style="color:var(--bot);font-weight:600">purple = done automatically by a script</span> · <span style="color:var(--exch);font-weight:600">orange = a person decided</span> · grey = plain transfers', 'graph': {'nodes': GN, 'edges': GE}, 'proof': PROOF, 't0': T0, 'cats': CAT, 'legend': sorted({CAT[n['category']] for n in GN}, key=CAT.index), 'foot': 'Solid arrows = funds (repeated transactions merged; N sales = separate sales by that wallet). Dashed = the loop: the script starts that wallet\'s next sale. Timings and amounts are in "How the laundering appears to have been automated" and Key steps; full addresses are in the table at the bottom.', 'keys': KEYS, 'held': held, 'kpis': KPIS, 'cards': CARDS, 'ghow': GHOW, 'thow': THOW, 'mhow': MHOW, 'plain': PLAIN, 'proofs': PROOFS, 'lots': LOTS, 'cycle': CYCLE, 'fp': FP,
        'sub': f"3 Nov {f_utc(T0)}–{f_utc(burns[-1][1])} UTC. How stolen SOL was cleaned, sold for dollars and moved to another blockchain by a program, minutes at a time, before anyone could flag the wallets. Data as of 05:29 UTC; built from raw on-chain data, indexed independently; automation is inferred from timing and transaction settings, not confirmed. Amounts in native units; dollar values for scale only.",
        'tlTitle': f"Timeline — every transaction in this wave (3 Nov, {f_utc(min(e[1] for e in ev) / 1000)}–{f_utc(burns[-1][1])} UTC)", 'heldTitle': 'Left in the seller wallets at 05:29 UTC',
        'axis': {'name': 'minutes from the first sale', 'min': round((min(e[1] for e in ev) / 1000 - T0) / 60) - 3, 'max': round((max(e[1] for e in ev) / 1000 - T0) / 60) + 3},
        'marks': [['first sale', T0], ['last burn', burns[-1][1]]]}
uri = 'data:image/jpeg;base64,' + base64.b64encode(open(AV, 'rb').read()).decode() if os.path.exists(AV) else ''
HTML = open('sol_phaseb_template.html').read().replace('/*__ECHARTS__*/', open(ECH).read()).replace('/*__DATA__*/null', json.dumps(__import__('tron_graph').safe(DATA))).replace('__AVATAR__', uri)
open(OUT, 'w').write(HTML)
print('wrote', OUT, '| events', collections.Counter(e[0] for e in ev), '| sellers', len(sellers), 'chains', [len(c) for c in chains], '| dydx', len(dydx), '| KPIs', KPIS)
