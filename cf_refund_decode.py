"""Decode Chainflip refund recipients (refundEgress txRef on Tron) not yet in raw/tron/cf_refunds.json; append them. Prints tree / outside split."""
import json, sqlite3, time, urllib.request, collections, hashlib, os
E = {l.split('=',1)[0]: l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
K = E['TRONGRID_API_KEY']; B = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'; TEC = 'TEcDijvKSXcfWT7S6rd44H5vNgufm7Y4XC'
def b58(h):
    a = bytes.fromhex('41' + h[-40:]); c = hashlib.sha256(hashlib.sha256(a).digest()).digest()[:4]; n = int.from_bytes(a + c, 'big'); s = ''
    while n: n, r = divmod(n, 58); s = B[r] + s
    return s
c = json.load(open('raw/tron/bridge_cf.json')); out = json.load(open('raw/tron/cf_refunds.json'))
C = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
tree = {a for (a,) in C.execute("select distinct address from ledger_node where run_id like 'tron2-%' and (inn>0 or out>0 or bal>0)")}
agg = collections.defaultdict(float); new = 0
for h, r in c.items():
    if not isinstance(r, dict) or not r.get('refundEgress') or h in out: continue
    rf = r['refundEgress']; new += 1
    d = json.load(urllib.request.urlopen(urllib.request.Request('https://api.trongrid.io/wallet/gettransactioninfobyid', json.dumps({'value': rf['txRef']}).encode(), {'TRON-PRO-API-KEY': K, 'Content-Type': 'application/json'}), timeout=30)); time.sleep(0.15)
    for l in d.get('log', []):
        if l['topics'][0].startswith('ddf252ad') and l['address'].endswith('a614f803b6fd780986a42c78ec9c7f77e6ded13c'):
            to = b58(l['topics'][2]); v = int(l['data'], 16) / 1e6
            if to != TEC: out[h] = (to, v, rf['txRef'], d.get('blockTimeStamp')); agg[to] += v
json.dump(out, open('raw/tron/cf_refunds.json', 'w'))
inn = sum(v for a, v in agg.items() if a in tree)
print(f'decoded {new} new refunds: {sum(agg.values()):,.2f} USDT to {len(agg)} addresses | in tree {inn:,.2f} | OUTSIDE {sum(agg.values()) - inn:,.2f} ({sum(1 for a in agg if a not in tree)} addrs)')
