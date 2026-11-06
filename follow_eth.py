# Follow ETH forward from seeds until it rests (EOA holding), hits a contract (labelled via Blockscout), or splits < MIN.
import json, urllib.request, os, sys
from collections import defaultdict
E = {l.split('=',1)[0]: l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
U = f"https://eth-mainnet.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"
import time
def rpc(m, p):
  for i in range(6):
    try:
      r = json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=90))
      if 'result' in r: return r['result']
      err = RuntimeError(f"{m} {p[0]}: {r.get('error')}"); print('  rpc error', err, file=sys.stderr); time.sleep(2 + 3 * i)
    except (OSError, ValueError) as e: err = e; time.sleep(2 + 3 * i)
  raise err
def label(a):
  try:
    d = json.load(urllib.request.urlopen(urllib.request.Request(f"https://eth.blockscout.com/api/v2/addresses/{a}?apikey={E['BLOCKSCOUT_API_KEY']}", headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
    return d.get('name') or ','.join(t.get('name', '') for t in ((d.get('metadata') or {}).get('tags') or [])) or '?'
  except Exception: return '?'
MIN = 0.5
seeds = sys.argv[1:]
seen, ends, q = set(), defaultdict(float), [(s, 0) for s in seeds]
while q:
  a, depth = q.pop(0)
  if a in seen or depth > 8: continue
  seen.add(a)
  code = rpc('eth_getCode', [a, 'latest'])
  if len(code) > 50:   # contract (23-byte 7702 delegation counts as EOA)
    print(f"{'  '*depth}{a} CONTRACT [{label(a)}]"); continue
  bal = int(rpc('eth_getBalance', [a, 'latest']), 16) / 1e18
  outs = defaultdict(float)
  for t in rpc('alchemy_getAssetTransfers', [{'fromBlock': '0x18F0000', 'fromAddress': a, 'category': ['external'], 'maxCount': '0x3e8', 'withMetadata': True}])['transfers']:
    if (t['value'] or 0) >= MIN: outs[t['to']] += t['value']
  print(f"{'  '*depth}{a} held {bal:,.4f} ETH | outs {len(outs)}")
  if bal >= MIN: ends[('HELD', a)] += bal
  for to, v in sorted(outs.items(), key=lambda x: -x[1]):
    print(f"{'  '*depth}  -> {to} {v:,.4f}")
    q.append((to, depth + 1))
print('\nRESTING (EOA, ≥0.5 ETH):'); [print(f'  {a} {v:,.4f}') for (_, a), v in sorted(ends.items(), key=lambda x: -x[1])]
print('total resting', round(sum(ends.values()), 4))
