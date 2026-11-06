# Tron ledger USDT0 (LayerZero OFT, TFG4wBaD) exits → LayerZero Scan → destination chain + receiver
import json, sqlite3, urllib.request, time, sys
from collections import defaultdict
RUN = sys.argv[1] if len(sys.argv) > 1 else 'tron2-20261030T160703'
db = sqlite3.connect('binance-live.db')
rows = db.execute("SELECT hash, frm, amount FROM ledger_edge WHERE run_id=? AND too='TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt' AND asset='USDT'", (RUN,)).fetchall()
print(RUN, len(rows), 'USDT0 sends', f'{sum(r[2] for r in rows):,.2f} USDT')
out, dst = [], defaultdict(float)
for h, frm, amt in rows:
  m = {}
  for pre in ('0x', ''):
    try:
      d = json.load(urllib.request.urlopen(urllib.request.Request(f'https://scan.layerzero-api.com/v1/messages/tx/{pre}{h}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
      if d.get('data'): m = d['data'][0]; break
    except Exception as e: pass
  time.sleep(0.4)
  p, de = m.get('pathway', {}), m.get('destination', {}).get('tx', {})
  rec = {'tron_tx': h, 'from': frm, 'usdt': amt, 'dst_chain': p.get('receiver', {}).get('chain'), 'dst_tx': de.get('txHash'), 'status': (m.get('status') or {}).get('name'), 'guid': m.get('guid')}
  out.append(rec)
print(f"resolved {sum(1 for r in out if r['dst_tx'])}/{len(out)}")
json.dump(out, open(f'raw/tron/usdt0_carry_{RUN}.json', 'w'), indent=1)
for r in out: dst[r['dst_chain']] += r['usdt']
print('by destination chain:', {k: round(v, 2) for k, v in dst.items()})

# ---- ETH side: receiver of each OFT credit, then that receiver's USDT/ETH legs
import os
K = {l.split('=',1)[0]: l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U = f'https://eth-mainnet.g.alchemy.com/v2/{K}'
def rpc(m, p): return json.load(urllib.request.urlopen(urllib.request.Request(U, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=90))['result']
OFT, USDT = '0x1f748c76de468e9d11bd340fa9d5cbadf315dfb0', '0xdac17f958d2ee523a2206206994597c13d831ec7'
T = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
recv = defaultdict(float)
for r in out:
  if not r['dst_tx']: print('PENDING', r['tron_tx'][:14], r['from'], f"{r['usdt']:,.2f}", r['status']); continue
  for l in rpc('eth_getTransactionReceipt', [r['dst_tx']])['logs']:
    tp = l['topics']
    if l['address'] == USDT and tp and tp[0] == T and '0x' + tp[1][26:] == OFT:
      r['eth_receiver'] = '0x' + tp[2][26:]; r['eth_usdt'] = int(l['data'], 16) / 1e6; recv[r['eth_receiver']] += r['eth_usdt']
json.dump(out, open(f'raw/tron/usdt0_carry_{RUN}.json', 'w'), indent=1)
print('\nETH receivers (USDT credited):')
for a, v in sorted(recv.items(), key=lambda x: -x[1]):
  q = lambda d, cat, **x: [t for t in rpc('alchemy_getAssetTransfers', [{'fromBlock': '0x18F0000', d: a, 'category': cat, 'maxCount': '0x3e8', **x}])['transfers'] if (t['value'] or 0) >= 0.01]
  uin = sum(t['value'] for t in q('toAddress', ['erc20'], contractAddresses=[USDT]))
  uout = defaultdict(float)
  for t in q('fromAddress', ['erc20'], contractAddresses=[USDT]): uout[t['to']] += t['value']
  ein = sum(t['value'] for t in q('toAddress', ['external', 'internal']))
  eout = defaultdict(float)
  for t in q('fromAddress', ['external', 'internal']): eout[t['to']] += t['value']
  ub = int(rpc('eth_call', [{'to': USDT, 'data': '0x70a08231' + a[2:].rjust(64, '0')}, 'latest']), 16) / 1e6
  eb = int(rpc('eth_getBalance', [a, 'latest']), 16) / 1e18
  print(f"\n {a} stolen USDT {v:,.2f} | USDT in {uin:,.2f}{' ⚠ MIXED +' + format(uin - v, ',.2f') if uin - v > 1 else ''} held {ub:,.2f} | ETH in {ein:,.4f} held {eb:,.4f}")
  for k, x in sorted(uout.items(), key=lambda y: -y[1])[:6]: print(f"    USDT -> {k} {x:,.2f}")
  for k, x in sorted(eout.items(), key=lambda y: -y[1])[:6]: print(f"    ETH  -> {k} {x:,.4f}")
