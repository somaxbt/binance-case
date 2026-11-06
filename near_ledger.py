"""NEAR TREE ledger at a fixed cutoff (default = common cutoff 2026-11-04 09:05:48 UTC). Root = efd22425… (fresh implicit account that got
the 3 Binance PoR hot-wallet drains 10-29 20:15–20:22). Follows every NEAR transfer out; a receiver JOINS the tree if it was
created after the hack (first-ever tx after 10-29 20:00 UTC), else it is an endpoint. Per wallet: in (stolen / tree / outside) − out (tree /
endpoints) − fees = balance at the cutoff block (archival RPC). Fees = what a signed tx took beyond its deposit (QuickNode tx_status).
Read-only: QuickNode NEAR archive ONLY (11-05: history rebuilt by state bisection, see acts()).   python3 near_ledger.py [CUTOFF_UTC]  → raw/near_ledger.json"""
import json, os, sys, time, calendar, collections, urllib.request, urllib.error
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ROOT = 'efd224256518a7cacd209867963276efed302a8e222c013c43f4b1bd369ae5af'
VICTIMS = {l.strip() for l in open('raw/near/near_por.txt') if l.strip()}                      # Binance PoR NEAR accounts
CUT_S = sys.argv[1] if len(sys.argv) > 1 else '2026-11-04 09:05:48'; CUT = calendar.timegm(time.strptime(CUT_S, '%Y-%m-%d %H:%M:%S'))
# 11-05 (user): paid QuickNode NEAR (archive; tested block 223100761 = 11-05 02:02:23) replaces the public fastnear archival node. Key lives in
# the URL → never print RPC. 11-05: history also from QuickNode (acts() bisects the archive) — no nearblocks.
_E = {l.split('=', 1)[0].strip(): l.split('=', 1)[1].strip().strip('"\'') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
RPC = (_E['QUICKNODE_NEAR_URL'].rstrip('/') + '/' + _E['QUICKNODE_NEAR_TOKEN'] + '/') if _E.get('QUICKNODE_NEAR_URL') and _E.get('QUICKNODE_NEAR_TOKEN') else 'https://archival-rpc.mainnet.fastnear.com'
def get(u, body=None):
    for i in range(8):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, json.dumps(body).encode() if body else None, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(15 * (i + 1)); continue
            if e.code in (400, 404): return {}
            time.sleep(5)
        except Exception: time.sleep(5)
    # 11-05 fix: FAIL CLOSED. Returning {} here made 5 tree wallets read as "0 events" when nearblocks rate-limited us (HTTP 429)
    # → 28,902 NEAR they received were never followed (tree UNEXPLAINED 28,900.36 while every wallet looked balanced).
    raise RuntimeError(f'{u.split("/")[2]}: still failing after 8 tries (rate limit?) — refusing to treat it as empty')
def rpc(m, p): return get(RPC, {'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).get('result')
def block_at(ts):
    head = rpc('block', {'finality': 'final'})['header']; lo, hi = head['height'] - int((int(head['timestamp']) / 1e9 - ts) / 0.4) - 300000, head['height']
    while lo < hi:
        m = (lo + hi + 1) // 2; b = rpc('block', {'block_id': m})
        if b is None: lo = m; continue                                                   # skipped height
        if int(b['header']['timestamp']) / 1e9 <= ts: lo = m
        else: hi = m - 1
    return lo
def balance(a, h):
    r = rpc('query', {'request_type': 'view_account', 'block_id': h, 'account_id': a}); return int(r['amount']) / 1e24 if r else 0.0
HACK = calendar.timegm((2026, 10, 29, 20, 0, 0))
def q(m, p): return get(RPC, {'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p})
def state(a, h):
    """account state after block h (a skipped height = the block before it): (amount, storage, signed-tx nonce sum), None = did not exist"""
    for hh in range(h, h - 60, -1):
        r = q('query', {'request_type': 'view_account', 'block_id': hh, 'account_id': a}); name = ((r.get('error') or {}).get('cause') or {}).get('name')
        if name == 'UNKNOWN_BLOCK': continue
        if name == 'UNKNOWN_ACCOUNT': return None
        if 'result' not in r: raise RuntimeError(f'view_account {a[:16]} @{hh}: {str(r)[:160]}')
        k = q('query', {'request_type': 'view_access_key_list', 'block_id': hh, 'account_id': a}).get('result') or {}
        return (r['result']['amount'], r['result']['storage_usage'], sum(int(x['access_key']['nonce']) for x in k.get('keys', [])))
    raise RuntimeError(f'no block found below {h}')
def states(a, hs):
    """state() for many heights as PARALLEL single requests (QuickNode NEAR archive: a JSON-RPC batch is served slowly, parallel singles
    are ~5x faster — 11-05 test: 40 reads in 2.6 s)"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(12) as ex: return list(ex.map(lambda h: state(a, h), hs))
def change_blocks(a, lo, hi, K=8):
    """every block in (lo, hi] where a's state changed — K-ary search, ALL open intervals probed together each round (one batch per
    ≤50 heights, run in parallel) → ~7 round trips per wallet whatever its event count. A debit needs a signed tx (nonce moves) and a
    credit raises the amount, so an A→B→A amount round trip still changes the state tuple."""
    out, cur = [], [(lo, hi, *states(a, [lo, hi]))]
    while cur:
        nxt, probes = [], []
        for l, h, sl, sh in cur:
            if sl == sh: continue
            if h - l == 1: out.append(h); continue
            pts = sorted({l + (h - l) * j // K for j in range(1, K)} - {l, h}); probes.append((l, h, sl, sh, pts))
        allp = sorted({p for *_, pts in probes for p in pts}); S_ = dict(zip(allp, states(a, allp)))
        for l, h, sl, sh, pts in probes:
            P, S = [l] + pts + [h], [sl] + [S_[p] for p in pts] + [sh]
            nxt += [(P[k], P[k + 1], S[k], S[k + 1]) for k in range(len(P) - 1) if S[k] != S[k + 1]]
        cur = nxt
    return sorted(out)
def _deposit(actions):
    v = [next(iter(x.values())) for x in actions or [] if isinstance(x, dict)]
    return sum(int(y.get('deposit', 0)) for y in v if isinstance(y, dict)) / 1e24
def created_after_hack(a):
    """join = account did not exist at the hack block (11-04 rule: attacker accounts are created after 10-29 20:00 UTC)"""
    return state(a, H0) is None
def acts(a):
    """11-05: every balance change of a from the hack block to the cutoff from the QuickNode NEAR ARCHIVE only (user: no open endpoint;
    nearblocks' free tier 429s read as 'no history' and lost 28,902 NEAR). Bisect the account state → EXPERIMENTAL_changes names each
    change's cause → tx_status (own tx: receiver + deposit) / EXPERIMENTAL_receipt (credit: sender). Returns (events, deposit_by_tx)."""
    out, dep_by_tx = [], {}; s0 = state(a, H0); prev = int(s0[0]) if s0 else 0
    if prev: out.append(((H0, -1), 'INBOUND', 'opening', '(balance at the hack block)', prev / 1e24, None))
    for b in change_blocks(a, H0, H):
        r = q('EXPERIMENTAL_changes', {'changes_type': 'account_changes', 'account_ids': [a], 'block_id': b}).get('result')
        if r is None: raise RuntimeError(f'EXPERIMENTAL_changes {a[:16]} @{b} failed')
        for i, c in enumerate(x for x in r['changes'] if x['type'] in ('account_update', 'account_deletion')):
            amt = int(c['change'].get('amount', 0)) if c['type'] == 'account_update' else 0; d = amt - prev; cause = c['cause']; t = cause['type']
            tx, inv = cause.get('tx_hash') or cause.get('receipt_hash'), None
            if t == 'transaction_processing':
                x = q('EXPERIMENTAL_tx_status', {'tx_hash': cause['tx_hash'], 'sender_account_id': a, 'wait_until': 'NONE'}).get('result')
                if not x: raise RuntimeError(f'tx_status {cause["tx_hash"]} failed')
                inv = x['transaction']['receiver_id']; dep_by_tx[tx] = _deposit(x['transaction']['actions'])
            elif t == 'receipt_processing':
                x = q('EXPERIMENTAL_receipt', {'receipt_id': cause['receipt_hash']}).get('result')
                if not x: raise RuntimeError(f'receipt {cause["receipt_hash"]} failed')
                inv = (x['predecessor_id'] if d >= 0 else x['receiver_id']) if x['predecessor_id'] != 'system' else None
            out.append(((b, i), 'INBOUND' if d >= 0 else 'OUTBOUND', t, inv, amt / 1e24, tx)); prev = amt
    return sorted(out), dep_by_tx
def is_contract(a):
    r = rpc('query', {'request_type': 'view_account', 'block_id': H, 'account_id': a}); return bool(r) and r.get('code_hash') != '11111111111111111111111111111111'
MIN_JOIN = 100.0    # NEAR from the tree; smaller payouts are booked as endpoints, not followed (11-04: 72 of 92 wallets were < 30 NEAR)

H = block_at(CUT); H0 = block_at(HACK); print(f'NEAR tree ledger at {CUT_S} UTC = block {H} (activities = every balance change; receipts included)', flush=True)
tree, queue, endpoints, W = {ROOT}, [ROOT], {}, {}
while queue:
    a = queue.pop(0); A, dep_by_tx = acts(a)
    L = collections.defaultdict(float); edges = []; prev = 0.0; recv = collections.defaultdict(float)
    for ev, d_, cause, inv, after, tx in A:
        delta = after - prev; prev = after
        if d_ == 'INBOUND':
            if inv is None: L['fees'] -= delta; continue                                   # system gas refund
            k = 'in: stolen (Binance PoR hot wallet)' if inv in VICTIMS else 'in: tree' if inv in tree else f'in: outside {inv[:24]}'
            L[k] += delta; edges.append((tx, ev, inv, a, delta))
        else:
            amt = -delta; v = min(amt, dep_by_tx.get(tx, amt)); L['fees'] += amt - v
            if v <= 0: continue
            if inv and inv not in tree and inv not in endpoints: recv[inv] += v
            L['out: tree' if inv in tree else f'out: {inv}'] += v; edges.append((tx, ev, a, inv, v))
    src_tree = L.get('in: tree', 0) + L.get('in: stolen (Binance PoR hot wallet)', 0); src_out = sum(v for k, v in L.items() if k.startswith('in: outside'))
    stop = a != ROOT and src_out > src_tree
    for r, v in recv.items():
        if stop: endpoints.setdefault(r, f'not followed (sender {a[:12]} is outside-majority)'); continue
        if is_contract(r): endpoints[r] = f'contract: {r}'
        elif v < MIN_JOIN: endpoints[r] = f'small payout {v:,.2f} NEAR (< {MIN_JOIN:.0f}, not followed)'
        elif created_after_hack(r): tree.add(r); queue.append(r)
        else: endpoints[r] = 'endpoint (account existed before the hack)'
    bal = balance(a, H); srcs = sum(v for k, v in L.items() if k.startswith('in:')); uses = sum(v for k, v in L.items() if k.startswith('out:')) + L['fees']
    W[a] = {'held': round(bal, 6), 'ledger': {k: round(v, 6) for k, v in L.items()}, 'unexplained': round(srcs - uses - bal, 6), 'stopped_outside_majority': stop, 'n_events': len(A), 'edges': edges}
    print(f'  {a[:16]}…  in {srcs:,.4f}  out {uses - L["fees"]:,.4f}  fees {L["fees"]:.6f}  held {bal:,.4f}  UNEXPLAINED {srcs - uses - bal:,.6f}{"  STOP outside-majority" if stop else ""}  ({len(A)} ev)', flush=True)
# 11-04 fix: totals from the FINAL tree — an 'out: <addr>' booked before <addr> joined is internal, not 'left the tree'
# (first summary read UNEXPLAINED −153,050.99 while every wallet balanced). Endpoint labels from TOTAL received from the tree.
left_by = collections.Counter(); stolen = held = fees = outside = 0.0
for a, w in W.items():
    held += w['held']
    for k, v in w['ledger'].items():
        if k.startswith('in: stolen'): stolen += v
        elif k.startswith('in: outside'): outside += v
        elif k == 'fees': fees += v
        elif k.startswith('out: ') and k != 'out: tree' and k[5:] not in tree: left_by[k[5:]] += v
left = sum(left_by.values())
for r, v in left_by.items():
    lab = endpoints.get(r, '')
    if lab.startswith('small payout') and v >= MIN_JOIN: endpoints[r] = f'received {v:,.2f} NEAR in total (first payment was small)'
json.dump({'leg': 'near', 'kind': 'tree', 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(CUT)), 'block': H, 'root': ROOT, 'stolen': stolen, 'held': held,
           'left_tree': left, 'left_by': dict(left_by.most_common()), 'fees': fees, 'outside_in': outside, 'unexplained': round(stolen + outside - held - left - fees, 6), 'wallets': W, 'endpoints': endpoints},
          open('raw/near_ledger.json', 'w'), indent=1)
print(f'\nNEAR TREE {CUT_S}: {len(W)} wallets | stolen {stolen:,.6f} | outside in {outside:,.6f} | held {held:,.6f} | left the tree {left:,.6f} | fees {fees:.6f} | '
      f'UNEXPLAINED {stolen + outside - held - left - fees:,.6f} NEAR · endpoints {len(endpoints)}')
for a, l in sorted(endpoints.items(), key=lambda z: z[1]): print('   endpoint', a[:40], '·', l)
