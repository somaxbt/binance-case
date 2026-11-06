# Tron→ETH carry-over: THORChain payouts of stolen TRX landing on ETH. Per address: payout in, other in, outs, live balance.
import json, urllib.request, os, sys
from collections import defaultdict
K = {l.split('=',1)[0]: l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U = f'https://eth-mainnet.g.alchemy.com/v2/{K}'
def rpc(m, p): return json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=90))['result']
ROUTER = '0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146'   # THORChain router v4 (payouts = transferOut from router)
USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
def xfers(**q):
  out, key = [], None
  while True:
    r = rpc('alchemy_getAssetTransfers', [{'fromBlock': '0x18F0000', 'category': ['external', 'internal'], 'withMetadata': True, 'maxCount': '0x3e8', **q, **({'pageKey': key} if key else {})}])
    out += r['transfers']; key = r.get('pageKey')
    if not key: return out
seed = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'raw/tron/carryover_tron2-20261030T160703.json'))
want = defaultdict(float)
for ch, a, asset, amt in seed: want[(a.lower(), asset)] += amt
rows, dest = [], defaultdict(float)
for (a, asset), amt in sorted(want.items(), key=lambda x: -x[1]):
  usdc = asset != 'ETH.ETH'
  q = {'category': ['erc20'], 'contractAddresses': [USDC]} if usdc else {}
  ins = [t for t in xfers(toAddress=a, **q) if (t['value'] or 0) >= 0.001]
  outs = [t for t in xfers(fromAddress=a, **q) if (t['value'] or 0) >= 0.001]
  bal = int(rpc('eth_call', [{'to': USDC, 'data': '0x70a08231' + a[2:].rjust(64, '0')}, 'latest']), 16) / 1e6 if usdc else int(rpc('eth_getBalance', [a, 'latest']), 16) / 1e18
  tc_in = sum(t['value'] for t in ins if t['from'] == ROUTER)
  by = defaultdict(float)
  for t in ins:
    if t['from'] != ROUTER: by[t['from']] += t['value']
  other = max(0.0, tc_in - amt) + sum(by.values())   # foreign = other THORChain payouts to this address + non-router inflows
  tc = tc_in >= amt * 0.995
  for t in outs: dest[t['to']] += t['value']
  rows.append({'asset': 'USDC' if usdc else 'ETH', 'thor_in_total': round(tc_in, 6), 'non_router_in': {k: round(v, 6) for k, v in by.items()}, 'addr': a, 'thor_expected': amt, 'thor_seen': bool(tc), 'other_in': round(other, 6), 'out': round(sum(t['value'] for t in outs), 6), 'bal': round(bal, 6),
               'outs': [(t['metadata']['blockTimestamp'][5:16], t['to'], round(t['value'], 4), t['hash']) for t in outs]})
  r = rows[-1]
  print(f"{r['asset']} {a} stolen {amt:,.4f} | router in {tc_in:,.4f} {'✓' if tc else '✗ SHORT'} | other in {r['other_in']:,.4f}{' ⚠ MIXED' if r['other_in'] > 0.01 else ''} | out {r['out']:,.4f} | held {bal:,.4f}")
  for k, v in by.items(): print(f"    IN  from {k} {v:,.4f}")
  for o in r['outs']: print(f"    {o[0]} -> {o[1]} {o[2]:,.4f} {o[3][:16]}")
for u in ('ETH', 'USDC'):
  R = [r for r in rows if r['asset'] == u]
  print(f"\nTOTAL {u}: stolen payouts {sum(r['thor_expected'] for r in R):,.4f} | foreign in {sum(r['other_in'] for r in R):,.4f} | out {sum(r['out'] for r in R):,.4f} | held {sum(r['bal'] for r in R):,.4f}")
print('top destinations:', sorted(((round(v, 4), k) for k, v in dest.items()), reverse=True)[:15])
json.dump({'rows': rows, 'dest': dest}, open('raw/tron/carry_eth.json', 'w'), indent=1)
