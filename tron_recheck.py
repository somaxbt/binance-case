# Live recheck of EVERY wallet in a Tron v2 ledger run vs its closing balance at the cutoff (TRX incl. staked + USDT).
#   python3 tron_recheck.py [run_id]      default tron2-20261030T160703 (last COMPLETE run)
# One TronGrid account call per wallet (balance, frozenV2, trc20, latest_opration_time); frozen USDT holders re-tested.
# Writes raw/tron/recheck_<run>_<UTC>.json.
import json, os, sys, time, sqlite3, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
H = {'TRON-PRO-API-KEY': E['TRONGRID_API_KEY'], 'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}
USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'; QPS = 8
RUN = sys.argv[1] if len(sys.argv) > 1 else 'tron2-20261030T160703'
gate, last = threading.Lock(), [0.0]

def call(path, body=None):
    for i in range(12):                                  # ~6 min of retries: the link drops for a minute at a time
        with gate:
            w = last[0] + 1 / QPS - time.time()
            if w > 0: time.sleep(w)
            last[0] = time.time()
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io' + path,
                             json.dumps(body).encode() if body else None, H), timeout=40))
        except OSError:
            time.sleep(min(60, 5 * (i + 1)))
    raise RuntimeError(path)

def b58hex(a):
    n = 0
    for ch in a: n = n * 58 + '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'.index(ch)
    return n.to_bytes(25, 'big')[1:21].hex().rjust(64, '0')

# 11-04 (user): BOTH Tron keys — TronGrid (8/s) + Tronscan (3/s, accountv2: same facts), each wallet to the gate with the shorter queue
TSH = {'TRON-PRO-API-KEY': E['TRONSCAN_API_KEY'], 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://tronscan.org/'} if E.get('TRONSCAN_API_KEY') else None
tgate, tlast, TQPS, qlen = threading.Lock(), [0.0], 3, {'g': 0, 's': 0}
def call_ts(path):
    for i in range(12):
        with tgate:
            w = tlast[0] + 1 / TQPS - time.time()
            if w > 0: time.sleep(w)
            tlast[0] = time.time()
        try: return json.load(urllib.request.urlopen(urllib.request.Request('https://apilist.tronscanapi.com' + path, headers=TSH), timeout=40))
        except OSError: time.sleep(min(60, 5 * (i + 1)))
    raise RuntimeError(path)
def live(a):
    with gate: use_ts = TSH is not None and qlen['s'] * QPS < qlen['g'] * TQPS; qlen['s' if use_ts else 'g'] += 1
    try:
        if use_ts:
            d = call_ts(f'/api/accountv2?address={a}')
            return a, ((d.get('balance') or 0) + (d.get('totalFrozenV2') or 0)) / 1e6, \
                   sum(int(x.get('balance') or 0) for x in d.get('withPriceTokens', []) if x.get('tokenId') == USDT) / 1e6, d.get('latest_operation_time') or 0
        acc = (call(f'/v1/accounts/{a}').get('data') or [{}])[0]
        trx = (acc.get('balance', 0) + sum(f.get('amount', 0) for f in acc.get('frozenV2', []))) / 1e6
        usdt = sum(int(v) for t in acc.get('trc20', []) for k, v in t.items() if k == USDT) / 1e6
        return a, trx, usdt, acc.get('latest_opration_time', 0)
    finally:
        with gate:
            qlen['s' if use_ts else 'g'] -= 1; qlen['n'] = qlen.get('n', 0) + 1
            if qlen['n'] % 500 == 0: print(f"  {qlen['n']} wallets checked · {time.strftime('%H:%M:%S')}", flush=True)   # 11-04: progress line

C = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'binance-live.db'))
cutoff = json.loads(C.execute('SELECT params FROM ledger_run WHERE run_id=?', (RUN,)).fetchone()[0])['cutoff']
led = {}
for a, asset, bal, frozen in C.execute('SELECT address, asset, bal, frozen FROM ledger_node WHERE run_id=?', (RUN,)):
    led.setdefault(a, {'TRX': 0.0, 'USDT': 0.0, 'frozen': 0})[asset] = bal or 0.0
    if frozen: led[a]['frozen'] = 1
with ThreadPoolExecutor(12) as ex: rows = list(ex.map(live, sorted(led)))

out = {'run': RUN, 'cutoff_utc': time.strftime('%F %T', time.gmtime(cutoff / 1000)), 'checked_utc': time.strftime('%F %T', time.gmtime()), 'wallets': []}
for a, trx, usdt, op in rows:
    L = led[a]
    w = {'address': a, 'trx_ledger': round(L['TRX'], 6), 'trx_live': trx, 'trx_diff': round(trx - L['TRX'], 6),
         'usdt_ledger': round(L['USDT'], 6), 'usdt_live': usdt, 'usdt_diff': round(usdt - L['USDT'], 6),
         'sent_after_cutoff': op > cutoff, 'last_send_utc': time.strftime('%F %T', time.gmtime(op / 1000)) if op else None}
    if L['frozen'] or L['USDT'] > 1:
        r = call('/wallet/triggerconstantcontract', {'owner_address': 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', 'contract_address': USDT,
                 'function_selector': 'isBlackListed(address)', 'parameter': b58hex(a), 'visible': True})
        w['usdt_blacklisted'] = int((r.get('constant_result') or ['0'])[0] or '0', 16) == 1
    out['wallets'].append(w)
os.makedirs('raw/tron', exist_ok=True)
fn = f"raw/tron/recheck_{RUN}_{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}.json"
json.dump(out, open(fn, 'w'), indent=1)

W = out['wallets']; chg = [w for w in W if abs(w['trx_diff']) > 1 or abs(w['usdt_diff']) > 1 or w['sent_after_cutoff']]
print(f"{RUN}: cutoff {out['cutoff_utc']} UTC -> live {out['checked_utc']} UTC | {len(W)} wallets | {len(chg)} changed/active -> {fn}")
print(f"TRX  ledger {sum(w['trx_ledger'] for w in W):,.2f}  live {sum(w['trx_live'] for w in W):,.2f}  diff {sum(w['trx_diff'] for w in W):,.2f}")
print(f"USDT ledger {sum(w['usdt_ledger'] for w in W):,.2f}  live {sum(w['usdt_live'] for w in W):,.2f}  diff {sum(w['usdt_diff'] for w in W):,.2f}")
for w in sorted(chg, key=lambda w: -abs(w['trx_diff']) - abs(w['usdt_diff'])):
    print(f"  {w['address']}  TRX {w['trx_ledger']:,.2f} -> {w['trx_live']:,.2f} ({w['trx_diff']:+,.2f})  USDT {w['usdt_ledger']:,.2f} -> {w['usdt_live']:,.2f}"
          f"  last send {w['last_send_utc']}" + (f"  blacklisted={w['usdt_blacklisted']}" if 'usdt_blacklisted' in w else ''))
for w in W:
    if 'usdt_blacklisted' in w and w not in chg: print(f"  (unchanged) {w['address']} USDT {w['usdt_live']:,.2f} blacklisted={w['usdt_blacklisted']}")
