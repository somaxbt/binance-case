# Formal native ledgers for the single-wallet legs (XRP rK21, SOL Affz): IN(stolen)+IN(foreign) = OUT + fees + balance
import json, urllib.request, os, sys, time
from collections import defaultdict
K = {l.split('=',1)[0]: l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
def post(url, m, p):
  for i in range(6):
    try:
      r = json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=90))
      if 'error' in r: raise RuntimeError(r['error'])
      return r['result']
    except Exception as e: err = e; time.sleep(2 + 2 * i)
  raise err

def report(name, unit, S, U, live):
  s, u = sum(S.values()), sum(U.values())
  out = {'leg': name, 'at': time.strftime('%FT%TZ', time.gmtime()), 'sources': dict(S), 'uses': dict(U), 'live_balance': live, 'unexplained': s - u}
  print(f"\n=== {name} ===\n  sources {{{', '.join(f'{k}: {v:,.6f}' for k, v in S.items())}}}\n  uses    {{{', '.join(f'{k}: {v:,.6f}' for k, v in U.items())}}}\n  live balance {live:,.6f} {unit} | UNEXPLAINED {s - u:,.6f} {unit}")
  json.dump(out, open(f'raw/{name}_ledger.json', 'w'), indent=1)
  return out

def xrp():
  A = 'rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx'; X = 'https://s2.ripple.com:51234'
  por = set(open('agents/por_xrp.txt').read().split())
  S, U, marker, n = defaultdict(float), defaultdict(float), None, 0
  while True:
    r = post(X, 'account_tx', [{'account': A, 'ledger_index_min': -1, 'ledger_index_max': -1, 'limit': 400, **({'marker': marker} if marker else {})}])
    for t in r['transactions']:
      tx, meta = t['tx'], t['meta']; n += 1
      if meta['TransactionResult'] != 'tesSUCCESS': continue
      if tx['Account'] == A: U['fees'] += int(tx['Fee']) / 1e6
      d = meta.get('delivered_amount')
      if tx['TransactionType'] != 'Payment' or not isinstance(d, str): continue   # IOUs/checks don't move XRP
      v = int(d) / 1e6
      if tx.get('Destination') == A and tx['Account'] != A: S['stolen (Binance PoR)' if tx['Account'] in por else 'foreign: ' + tx['Account'][:8]] += v
      elif tx['Account'] == A: U['out: ' + tx['Destination']] += v
    marker = r.get('marker')
    if not marker: break
  info = post(X, 'account_info', [{'account': A, 'ledger_index': 'validated'}])['account_data']
  live = int(info['Balance']) / 1e6; U['held'] = live
  print(f'xrp: {n} txs, sequence {info["Sequence"]}')
  return report('xrp', 'XRP', S, U, live)

def sol():
  A = 'AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU'; R = f"https://solana-mainnet.g.alchemy.com/v2/{K['ALCHEMY_API_KEY']}"
  DRAIN = '5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'; por = set(open('agents/por_sol.txt').read().split()) | {DRAIN}
  sigs, before = [], None
  while True:
    page = post(R, 'getSignaturesForAddress', [A, {'limit': 1000, **({'before': before} if before else {})}])
    sigs += page
    if len(page) < 1000: break
    before = page[-1]['signature']
  S, U = defaultdict(float), defaultdict(float)
  for s in sigs:
    if s['err']: continue
    tx = post(R, 'getTransaction', [s['signature'], {'maxSupportedTransactionVersion': 1, 'encoding': 'json'}])
    keys = tx['transaction']['message']['accountKeys'] + (tx['meta'].get('loadedAddresses') or {}).get('writable', []) + (tx['meta'].get('loadedAddresses') or {}).get('readonly', [])
    i = keys.index(A); d = (tx['meta']['postBalances'][i] - tx['meta']['preBalances'][i]) / 1e9
    signer = keys[0]
    if signer == A: U['fees'] += tx['meta']['fee'] / 1e9; d += tx['meta']['fee'] / 1e9
    if d > 0: S['stolen (Binance PoR)' if signer in por else 'foreign: ' + signer[:8]] += d
    elif d < 0: U['out (signed by ' + signer[:8] + ')'] += -d
  live = post(R, 'getBalance', [A])['value'] / 1e9; U['held'] = live
  print(f'sol: {len(sigs)} signatures')
  return report('sol', 'SOL', S, U, live)

if __name__ == '__main__':
  for leg in sys.argv[1:] or ['xrp', 'sol']: {'xrp': xrp, 'sol': sol}[leg]()
