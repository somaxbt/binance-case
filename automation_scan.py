"""Automation fingerprints across the Binance Tron + Solana ledgers (read-only, no API calls: binance-live.db, binance-live-raw.db, raw/sol/*).
Tron: per-window bot signals, activation/gas funders, client-software fingerprints from raw txs (expiration-timestamp window, fee_limit,
sign->block latency). Solana: compute-budget fingerprints, gas funders, receive->send delays, same-slot sends. Cross-chain hour profile.
  python3 automation_scan.py   -> raw/automation_scan_<ts>.json + printed report"""
import sqlite3, json, zlib, gzip, glob, os, time, random, statistics as st, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
T0 = 1793304000 * 1000                                          # 2026-10-29 20:00 UTC (ms)
db = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
RUNS = [r for (r,) in db.execute("SELECT run_id FROM ledger_run WHERE leg='tron2' AND finished GLOB '2026*' ORDER BY started")]
print('tron runs:', len(RUNS), RUNS[0], '→', RUNS[-1], flush=True)
med = lambda xs: st.median(xs) if xs else None
OUT = {}

# ---------------- TRON A: per-window bot signals
win = {}
for r in RUNS:
    rows = db.execute("SELECT DISTINCT hash, ts, frm, too, asset, amount, cls FROM ledger_edge WHERE run_id=? AND cls NOT IN ('in:dust')", (r,)).fetchall()
    sends, ins = {}, collections.defaultdict(list)
    for h, ts, f, t, a, amt, c in rows:
        if c.startswith('out:'): sends.setdefault(h, (ts // 1000, f, t, a, amt or 0, c))
        elif c.startswith('in:') and c != 'in:own_back': ins[t].append(ts // 1000)
    if not sends: continue
    S = list(sends.values()); ts_ = [s[0] for s in S]
    blk = collections.defaultdict(set)
    for s in S: blk[s[0] // 3].add(s[1])
    multi = sum(1 for v in blk.values() if len(v) >= 3)
    sh = [random.Random(i).randrange(min(ts_) // 3, max(ts_) // 3 + 1) for i in range(len(S))]       # shuffle baseline: same sends, random blocks
    sb = collections.defaultdict(set)
    for i, s in enumerate(S): sb[sh[i]].add(s[1])
    lag = []
    for s in S:
        prev = [x for x in ins.get(s[1], []) if x <= s[0]]
        if prev: lag.append(s[0] - max(prev))
    rnd = sum(1 for s in S if s[4] >= 100 and s[4] % 100 == 0)
    mins = len({t // 60 for t in ts_}); span = (max(ts_) - min(ts_)) / 60
    win[r] = {'sends': len(S), 'wallets': len({s[1] for s in S}), 'active_min': mins, 'span_min': round(span), 'max_per_min': max(collections.Counter(t // 60 for t in ts_).values()),
              'blocks_3plus_wallets': multi, 'baseline_3plus': sum(1 for v in sb.values() if len(v) >= 3), 'lag_median_s': med(lag),
              'lag_15_35s_share': round(sum(1 for x in lag if 15 <= x <= 35) / len(lag), 3) if lag else None, 'round_share': round(rnd / len(S), 3)}
    print(f"  {r}: {win[r]}", flush=True)
OUT['tron_windows'] = win

# ---------------- TRON B: activation / gas funders (first small TRX into each attacker wallet)
first_in, first_out = {}, {}
for h, ts, f, t, a, amt, c in db.execute("SELECT hash, ts, frm, too, asset, amount, cls FROM ledger_edge WHERE run_id IN (%s)" % ','.join('?' * len(RUNS)), RUNS):
    if a == 'TRX' and c == 'in:attacker' and amt and amt < 50 and (t not in first_in or ts < first_in[t][0]): first_in[t] = (ts, f, amt)   # tree-internal gas only (dust/poisoning excluded)
    if c.startswith('out:') and amt and amt >= 50 and (f not in first_out or ts < first_out[f]): first_out[f] = ts
fund = collections.Counter(v[1] for v in first_in.values()); lead = [(first_out[w] - v[0]) / 1000 for w, v in first_in.items() if w in first_out and first_out[w] >= v[0]]
amts = collections.Counter(round(v[2], 6) for v in first_in.values())
OUT['tron_gas'] = {'wallets_with_small_first_in': len(first_in), 'top_funders': fund.most_common(10), 'top_first_amounts': amts.most_common(8),
                   'lead_s_median': med(lead), 'lead_s_p10_p90': (sorted(lead)[len(lead) // 10], sorted(lead)[9 * len(lead) // 10]) if len(lead) > 10 else None}
print('  tron gas:', OUT['tron_gas'], flush=True)

# ---------------- TRON C: client-software fingerprints from raw txs
att_send = {h: f for (h, f) in db.execute("SELECT DISTINCT hash, frm FROM ledger_edge WHERE cls LIKE 'out:%%' AND run_id IN (%s)" % ','.join('?' * len(RUNS)), RUNS)}
raw = sqlite3.connect('file:binance-live-raw.db?mode=ro', uri=True); fp = collections.defaultdict(set); lat = []; seen = set(); nraw = 0
for u, b in raw.execute("SELECT url, body FROM raw_payload WHERE url LIKE '%/transactions%' AND url NOT LIKE '%trc20%'"):
    d = None
    for fn in (lambda x: x, zlib.decompress, gzip.decompress):
        try: d = json.loads(fn(b)); break
        except Exception: pass
    for t in (d or {}).get('data') or []:
        h = t.get('txID'); rd = t.get('raw_data') or {}
        if h not in att_send or h in seen: continue
        seen.add(h); nraw += 1
        ctype = ((rd.get('contract') or [{}])[0]).get('type', '?')
        win_s = round((rd.get('expiration', 0) - rd.get('timestamp', 0)) / 1000) if rd.get('timestamp') else None
        fp[(ctype, win_s, rd.get('fee_limit'))].add(att_send[h])
        if rd.get('timestamp') and t.get('block_timestamp'): lat.append((t['block_timestamp'] - rd['timestamp']) / 1000)
top = sorted(fp.items(), key=lambda kv: -len(kv[1]))[:12]
OUT['tron_fingerprints'] = {'attacker_sends_with_raw': nraw, 'of_total': len(att_send),
                            'top': [{'contract': k[0], 'expiration_window_s': k[1], 'fee_limit_trx': (k[2] or 0) / 1e6 if k[2] else None, 'wallets': len(v)} for k, v in top],
                            'sign_to_block_s_median': med(lat), 'sign_to_block_s_p90': sorted(lat)[9 * len(lat) // 10] if len(lat) > 10 else None}
print('  tron fingerprints:', json.dumps(OUT['tron_fingerprints'])[:900], flush=True)

# ---------------- SOLANA: whole tree + branches (cached txs)
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58d(s):
    n = 0
    for c in s: n = n * 58 + B58.index(c)
    return n.to_bytes((n.bit_length() + 7) // 8, 'big')
SL = json.load(open('raw/sol_ledger.json')); wallets = set(SL['wallets'])
for f in glob.glob('raw/sol/branch_*.json'): wallets |= set(json.load(open(f))['tree'])
sfp = collections.defaultdict(set); sgas = {}; sfirst_val = {}; sslots = collections.defaultdict(list); shours = collections.Counter()
for f in glob.glob('raw/sol/tx_*.json'):
    try: t = json.load(open(f))
    except Exception: continue
    if not t or t['meta'].get('err'): continue
    keys = [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
    signer = keys[0]; pre, post = t['meta']['preBalances'], t['meta']['postBalances']
    if signer in wallets:
        lim = price = None
        for ix in t['transaction']['message']['instructions']:
            if ix.get('programId', '').startswith('ComputeBudget') and 'data' in ix:
                d = b58d(ix['data'])
                if d[:1] == b'\x02': lim = int.from_bytes(d[1:5], 'little')
                if d[:1] == b'\x03': price = int.from_bytes(d[1:9], 'little')
        sfp[(lim, price)].add(signer); sslots[signer].append(t['slot']); shours[time.strftime('%H', time.gmtime(t['blockTime']))] += 1
    for j, k in enumerate(keys):
        if k in wallets and k != signer:
            d = (post[j] - pre[j]) / 1e9
            if 0 < d < 0.2 and (k not in sgas or t['blockTime'] < sgas[k][0]): sgas[k] = (t['blockTime'], signer)
            if d >= 0.2 and (k not in sfirst_val or t['blockTime'] < sfirst_val[k]): sfirst_val[k] = t['blockTime']
same_slot = sum(sum(c - 1 for c in collections.Counter(v).values() if c > 1) for v in sslots.values())
slead = [sfirst_val[w] - g[0] for w, g in sgas.items() if w in sfirst_val and sfirst_val[w] >= g[0]]
OUT['sol'] = {'tree_wallets': len(wallets), 'signed_txs': sum(len(v) for v in sslots.values()), 'same_slot_extra_sends': same_slot,
              'fingerprints': [{'cu_limit': k[0], 'cu_price': k[1], 'wallets': len(v)} for k, v in sorted(sfp.items(), key=lambda kv: -len(kv[1]))[:10]],
              'gas_funders': collections.Counter(g[1] for g in sgas.values()).most_common(6), 'gas_lead_s_median': med(slead)}
print('  sol:', json.dumps(OUT['sol'])[:900], flush=True)

# ---------------- cross-chain hour-of-day profile
th = collections.Counter()
for (ts,) in db.execute("SELECT DISTINCT ts FROM ledger_edge WHERE cls LIKE 'out:%%' AND run_id IN (%s)" % ','.join('?' * len(RUNS)), RUNS): th[time.strftime('%H', time.gmtime(ts // 1000))] += 1
OUT['hours'] = {'tron': dict(sorted(th.items())), 'sol': dict(sorted(shours.items()))}
ts = time.strftime('%Y%m%dT%H%M%S', time.gmtime()); json.dump(OUT, open(f'raw/automation_scan_{ts}.json', 'w'), indent=1, default=str)
print('\n=== AUTOMATION SCAN done', ts)
print('TRON hours (UTC) sends:', OUT['hours']['tron']); print('SOL hours (UTC) signed txs:', OUT['hours']['sol'])
