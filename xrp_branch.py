"""XRP branch trace from the pot rK21 (read-only, public XRPL full-history node s2.ripple.com). Follows XRP payments since SINCE into
receivers that were created after the hack (first tx >= 2026-10-29) up to DEPTH hops; a payment WITH a destination tag, or to a
labelled / pre-existing account, is an endpoint (likely exchange deposit). Writes raw/xrp_branch_<ts>.json + summary.
  python3 xrp_branch.py [SINCE_UNIX=1793592600] [DEPTH=4]"""
import json, os, sys, time, sqlite3, urllib.request, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
X = 'https://s2.ripple.com:51234'; ROOT = 'rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx'
SINCE = int(sys.argv[1]) if len(sys.argv) > 1 else 1793592600; DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 4
HACK = 1793232000; RIPPLE = 946684800
AT = sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db'))
def label(a):
    r = AT.execute("SELECT entity||' ('||category||')' FROM attrib_v WHERE address=? LIMIT 1", (a,)).fetchone(); return r[0] if r else ''
def rpc(m, p):
    for i in range(8):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(X, json.dumps({'method': m, 'params': [p]}).encode(), {'Content-Type': 'application/json'}), timeout=60))['result']
            if r.get('status') == 'error' and r.get('error') in ('actNotFound',): return r
            return r
        except Exception: time.sleep(3 * (i + 1))
    return {}
def txs(a, since):
    out, marker = [], None
    while True:
        r = rpc('account_tx', {'account': a, 'limit': 400, 'forward': False, **({'marker': marker} if marker else {})})
        page = r.get('transactions') or []
        for t in page:
            if t['tx'].get('date', 0) + RIPPLE >= since: out.append(t)
        if not page or page[-1]['tx'].get('date', 0) + RIPPLE < since or not r.get('marker'): return out
        marker = r['marker']
FIRST = {}
def first_seen(a):                       # oldest tx time of an account (one page, ascending)
    if a not in FIRST:
        r = rpc('account_tx', {'account': a, 'limit': 1, 'forward': True}); t = (r.get('transactions') or [{}])[0].get('tx', {})
        FIRST[a] = t.get('date', 0) + RIPPLE if t else 0
    return FIRST[a]
def bal(a):
    r = rpc('account_info', {'account': a, 'ledger_index': 'validated'}); return int(r.get('account_data', {}).get('Balance', 0)) / 1e6
edges, depth, q, ends = [], {ROOT: 0}, [ROOT], {}
while q:
    a = q.pop(0)
    for t in sorted(txs(a, SINCE), key=lambda t: t['tx']['date']):
        tx, m = t['tx'], t['meta']
        if tx.get('TransactionType') != 'Payment' or tx.get('Account') != a or m.get('TransactionResult') != 'tesSUCCESS': continue
        d = m.get('delivered_amount')
        if not isinstance(d, str): continue                     # IOU, not XRP
        to, v, tag = tx['Destination'], int(d) / 1e6, tx.get('DestinationTag')
        edges.append({'t': tx['date'] + RIPPLE, 'from': a, 'to': to, 'xrp': v, 'tag': tag, 'hash': tx['hash']})
        if to in depth or to in ends: continue
        fs = first_seen(to); lab = label(to)
        if tag is None and not lab and fs >= HACK and depth[a] < DEPTH: depth[to] = depth[a] + 1; q.append(to)
        else: ends[to] = {'label': lab, 'tag': tag, 'first_seen': time.strftime('%Y-%m-%d', time.gmtime(fs)) if fs else '?'}
    print(f'  read {a[:10]} depth {depth[a]} | tree {len(depth)} queue {len(q)} endpoints {len(ends)}', flush=True)
held = {a: bal(a) for a in depth}
endv = collections.defaultdict(float); endtags = collections.defaultdict(set)
for e in edges:
    if e['to'] in ends: endv[e['to']] += e['xrp']; endtags[e['to']].add(e['tag'])
ts = time.strftime('%Y%m%dT%H%M%S', time.gmtime())
json.dump({'root': ROOT, 'since': SINCE, 'edges': edges, 'tree': {a: {'depth': d, 'held': held[a]} for a, d in depth.items()}, 'endpoints': ends}, open(f'raw/xrp_branch_{ts}.json', 'w'), indent=1)
print(f'\n=== XRP BRANCH from {ROOT} since {time.strftime("%m-%d %H:%M", time.gmtime(SINCE))} UTC: {len(depth)} attacker wallets, {len(ends)} endpoints, {len(edges)} payments')
print(f'  HELD now in tree: {sum(held.values()):,.2f} XRP')
for a, v in sorted(held.items(), key=lambda kv: -kv[1])[:10]: print(f'    {a}  {v:,.2f} XRP  (depth {depth[a]})')
print('  ENDPOINTS (received):')
for a, v in sorted(endv.items(), key=lambda kv: -kv[1])[:15]:
    e = ends[a]; print(f"    {a}  {v:,.2f} XRP  tags {sorted(t for t in endtags[a] if t is not None)[:3] or '-'}  first seen {e['first_seen']}  {e['label'] or ''}")
