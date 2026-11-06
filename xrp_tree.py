"""XRP TREE ledger: pot rK21 (from single_ledger.py xrp → raw/xrp_ledger.json) + every wallet it paid, with each child's own
conservation (in from pot + other in = out + fees + live balance). Writes raw/xrp_ledger.json with kind 'tree' (old single-wallet
file kept as raw/xrp_ledger_single_<date>.json). Read-only, public XRPL node.   python3 single_ledger.py xrp && python3 xrp_tree.py"""
import json, os, time, shutil, urllib.request, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
X = 'https://s2.ripple.com:51234'; ROOT = 'rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx'; RIPPLE = 946684800
def rpc(m, p):
    for i in range(8):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(X, json.dumps({'method': m, 'params': [p]}).encode(), {'Content-Type': 'application/json'}), timeout=60))['result']
        except Exception: time.sleep(3 * (i + 1))
    return {}
L = json.load(open('raw/xrp_ledger.json'))
if L.get('kind') == 'tree': L = json.load(open(sorted(f for f in os.listdir('raw') if f.startswith('xrp_ledger_single_'))[-1].join(['raw/', ''])))
else: shutil.copy('raw/xrp_ledger.json', f"raw/xrp_ledger_single_{time.strftime('%Y%m%d')}.json")
kids = [k[5:] for k in L['uses'] if k.startswith('out: ')]
W = {ROOT: {'held': L['live_balance'], 'flows': {**{'in: ' + k: v for k, v in L['sources'].items()}, **{k: v for k, v in L['uses'].items() if k != 'held'}},
            'unexplained': L['unexplained'], 'role': 'theft collection wallet'}}
edges = []
for k in kids:
    fl = collections.defaultdict(float); marker = None
    while True:
        r = rpc('account_tx', {'account': k, 'limit': 400, **({'marker': marker} if marker else {})})
        for t in r.get('transactions') or []:
            tx, m = t['tx'], t['meta']
            if m.get('TransactionResult') != 'tesSUCCESS': continue
            if tx.get('Account') == k: fl['fees'] += int(tx['Fee']) / 1e6
            d = m.get('delivered_amount')
            if tx.get('TransactionType') != 'Payment' or not isinstance(d, str): continue
            v = int(d) / 1e6
            if tx.get('Destination') == k and tx['Account'] != k:
                fl['in: tree' if tx['Account'] == ROOT else 'in: foreign ' + tx['Account'][:8]] += v
                if tx['Account'] == ROOT: edges.append([tx['hash'], tx['date'] + RIPPLE, ROOT, k, v])
            elif tx['Account'] == k: fl['out: ' + tx['Destination']] += v; edges.append([tx['hash'], tx['date'] + RIPPLE, k, tx['Destination'], v])
        marker = r.get('marker')
        if not marker: break
    bal = int(rpc('account_info', {'account': k, 'ledger_index': 'validated'}).get('account_data', {}).get('Balance', 0)) / 1e6
    src = sum(v for n, v in fl.items() if n.startswith('in')); use = sum(v for n, v in fl.items() if not n.startswith('in'))
    W[k] = {'held': bal, 'flows': dict(fl), 'unexplained': round(src - use - bal, 6), 'role': 'holding wallet' if bal >= 1e6 else 'test / small'}
held = sum(w['held'] for w in W.values())
# whole-tree conservation: stolen + foreign = left the tree (outs to non-tree) + fees + held
T = set(W); out_ext = sum(v for a, w in W.items() for n, v in w['flows'].items() if n.startswith('out: ') and n[5:] not in T)
fees = sum(w['flows'].get('fees', 0) for w in W.values())
srcs = {k: v for k, v in L['sources'].items()}
for a, w in W.items():
    for n, v in w['flows'].items():
        if n.startswith('in: foreign') and a != ROOT: srcs['foreign (tree)'] = srcs.get('foreign (tree)', 0) + v
uses = {'held': held, 'fees': fees, 'left the tree': out_ext}
out = {'leg': 'xrp', 'kind': 'tree', 'at': time.strftime('%FT%TZ', time.gmtime()), 'root': ROOT, 'sources': srcs, 'uses': uses, 'live_balance': held,
       'unexplained': round(sum(srcs.values()) - sum(uses.values()), 6), 'wallets': W, 'edges': edges}
json.dump(out, open('raw/xrp_ledger.json', 'w'), indent=1)
print(f"XRP TREE {out['at']}: {len(W)} wallets | stolen {srcs.get('stolen (Binance PoR)', 0):,.2f} | held {held:,.2f} | left the tree {out_ext:,.2f} | fees {fees:.6f} | UNEXPLAINED {out['unexplained']}")
for a, w in sorted(W.items(), key=lambda kv: -kv[1]['held']): print(f"   {a}  held {w['held']:>16,.6f}  unexplained {w['unexplained']}  {w['role']}")
