"""Bridge timing on the Tron leg: (1) attacker side: funds arrive at the depositing wallet -> bridge deposit (poll-loop test);
(2) bridge settling: deposit -> payout on the destination (from each bridge's own record); (3) destination side: payout lands ->
attacker's first onward move (Ethereum sample, Alchemy). Read-only.   python3 bridge_timing.py [N_DEST_SAMPLE=120]"""
import json, os, sys, sqlite3, time, statistics as st, collections, csv, urllib.request, datetime as dt
os.chdir(os.path.dirname(os.path.abspath(__file__)))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
iso = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
def q(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return 'n=0'
    p = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]
    return f'n={len(xs)} p10={p(.1):.0f}s median={st.median(xs):.0f}s p90={p(.9):.0f}s'
def band(xs, lo=15, hi=35): xs = [x for x in xs if x is not None]; return f'{sum(1 for x in xs if lo <= x <= hi) / len(xs):.0%}' if xs else '-'

# ---- deposits per bridge (Tron tx hash -> record), with settling time + payout time
dep = {}                                                   # hash -> [bridge, settle_s, payout_ts]
for h, r in json.load(open('raw/tron/relay_requests.json')).items():
    i = (r['data'].get('inTxs') or [{}])[0].get('timestamp'); o = [x.get('timestamp') for x in r['data'].get('outTxs') or [] if x.get('timestamp')]
    if r.get('status') == 'success' and i and o: dep[h.lower()] = ['Relay', min(o) - i, min(o)]
for h, r in json.load(open('raw/tron/bridge_cf.json')).items():
    d, e = (r.get('deposit') or {}).get('witnessedAt'), (r.get('swapEgress') or {}).get('witnessedAt')
    if d and e: dep[h.lower()] = ['Chainflip', (e - d) / 1000, e / 1000]
for h, r in json.load(open('raw/tron/bridge_sym.json')).items():
    a, b = (r.get('txIn') or {}).get('time'), (r.get('tx') or {}).get('time')
    if a and b: dep[h.lower()] = ['Symbiosis', iso(b) - iso(a), iso(b)]
for h, r in json.load(open('raw/tron/bridge_usdt0.json')).items():
    m = (r.get('data') or [{}])[0]
    if m.get('destination', {}).get('status') == 'SUCCEEDED': dep[h.lower().removeprefix('0x')] = ['USDT0', iso(m['updated']) - iso(m['created']), iso(m['updated'])]
for h, acts in json.load(open('raw/tron/midgard_actions.json')).items():
    for a in acts if isinstance(acts, list) else []:
        outs = [int(o['height']) for o in a.get('out') or [] if not o.get('affiliate') and o.get('height')]
        if a.get('status') == 'success' and outs and a.get('type', 'swap') != 'refund':
            t0 = int(a['date']) / 1e9; dep[h.lower()] = ['THORChain', (max(outs) - int(a['height'])) * 6.0, t0 + (max(outs) - int(a['height'])) * 6.0]; break
print('bridge records with timing:', collections.Counter(v[0] for v in dep.values()), flush=True)

# ---- (1) attacker side: arrival -> deposit (ledger)
db = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
RUNS = [r for (r,) in db.execute("SELECT run_id FROM ledger_run WHERE leg='tron2' AND finished GLOB '2026*'")]
inb = collections.defaultdict(list); deps = {}
for h, ts, f, t, c, amt in db.execute("SELECT DISTINCT hash, ts, frm, too, cls, amount FROM ledger_edge WHERE run_id IN (%s)" % ','.join('?' * len(RUNS)), RUNS):
    if c in ('in:attacker', 'in:swap_proceeds', 'in:own_back', 'in:internal') and (amt or 0) >= 1: inb[t].append(ts / 1000)
    if h.lower() in dep and c.startswith('out:'): deps[h.lower()] = (ts / 1000, f, amt)
lag = collections.defaultdict(list); amts = collections.defaultdict(list); per_wallet = collections.defaultdict(list)
for h, (ts, f, amt) in deps.items():
    prev = [x for x in inb.get(f, []) if x <= ts]
    if prev: lag[dep[h][0]].append(ts - max(prev))
    amts[dep[h][0]].append(amt or 0); per_wallet[(dep[h][0], f)].append(ts)
print('\n(1) ATTACKER SIDE — funds arrive → bridge deposit')
for b in sorted(lag, key=lambda b: -len(lag[b])):
    rnd = sum(1 for a in amts[b] if a >= 1000 and a % 1000 == 0) / len(amts[b])
    gaps = [y - x for k, v in per_wallet.items() if k[0] == b for x, y in zip(sorted(v), sorted(v)[1:])]
    print(f'  {b:10} {q(lag[b])} | in 15–35 s band {band(lag[b])} | round-1000 amounts {rnd:.0%} | repeat-deposit gaps {q(gaps)}')

# ---- (2) bridge settling
print('\n(2) BRIDGE SETTLING — deposit → payout on destination (bridge records)')
for b in ('Relay', 'Chainflip', 'Symbiosis', 'USDT0', 'THORChain'):
    xs = [v[1] for h, v in dep.items() if v[0] == b and h in deps]
    print(f'  {b:10} {q(xs)}')

# ---- (3) destination side: payout lands -> first onward move (Ethereum sample)
K = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U = f'https://eth-mainnet.g.alchemy.com/v2/{K}'
def rpc(m, p):
    for i in range(6):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=60))
            if 'result' in r: return r['result']
        except Exception: pass
        time.sleep(3 * (i + 1))
    return None
pay = {}                                                    # (via, address) -> earliest payout ts on Ethereum
for r in csv.DictReader(open('raw/tron/carry_over_seeds.csv')):
    if r['dest_chain'].split(' ')[0] not in ('Ethereum', 'ETH') or not r['address'].startswith('0x'): continue
    v = dep.get(r['source'].lower().removeprefix('0x'))
    if v: k = (v[0], r['address'].lower()); pay[k] = min(pay.get(k, 9e18), v[2]); pay[(k, 'amt')] = pay.get((k, 'amt'), 0) + float(r['amount'] or 0) * (2300 if r['asset'] == 'ETH' else 1)
keys = sorted([k for k in pay if isinstance(k[0], str) and k[0] != 'amt' and len(k) == 2 and isinstance(k[1], str)], key=lambda k: -pay[(k, 'amt')])[:N]
blk = lambda ts: hex(int(26300753 + (ts - 1793325659) / 12) - 50)
react = collections.defaultdict(list); never = collections.Counter()
for i, (via, a) in enumerate(keys):
    r = rpc('alchemy_getAssetTransfers', [{'fromAddress': a, 'fromBlock': blk(pay[(via, a)]), 'category': ['external', 'erc20'], 'order': 'asc', 'maxCount': '0x5', 'withMetadata': True}])
    ts = [iso(t['metadata']['blockTimestamp']) for t in (r or {}).get('transfers', []) if t.get('metadata')]
    ts = [x for x in ts if x >= pay[(via, a)] - 30]
    if ts: react[via].append(ts[0] - pay[(via, a)])
    else: never[via] += 1
    if i % 30 == 29: print(f'  … {i + 1}/{len(keys)} destinations checked', flush=True)
print(f'\n(3) DESTINATION SIDE — payout lands on Ethereum → attacker\'s first onward move (top {len(keys)} destinations by value)')
for b in sorted(react, key=lambda b: -len(react[b])):
    xs = react[b]; print(f'  {b:10} {q(xs)} | within 60 s {sum(1 for x in xs if x <= 60) / len(xs):.0%} | within 10 min {sum(1 for x in xs if x <= 600) / len(xs):.0%} | not moved yet {never[b]}')
json.dump({'lag': lag, 'settle': {b: [v[1] for h, v in dep.items() if v[0] == b and h in deps] for b in ('Relay', 'Chainflip', 'Symbiosis', 'USDT0', 'THORChain')}, 'react': react, 'never': never},
          open(f'raw/tron/bridge_timing_{time.strftime("%Y%m%dT%H%M%S", time.gmtime())}.json', 'w'))
