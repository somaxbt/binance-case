"""Resolve the ETH tree's Chainflip / Relay / Maya deposits (run eth-hs-full-20261102T170619) to destination + status.
Cache raw/eth_xchain.json (hash -> API reply). Keyless public APIs, read-only.   python3 xchain_resolve.py"""
import json, os, time, sqlite3, urllib.request, urllib.error, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
C = sqlite3.connect('binance-bridged.db'); C.execute(f"attach '{os.path.expanduser('~/traversal-engine/data/attrib.db')}' as a")
RUN = C.execute("SELECT run_id FROM run WHERE params LIKE '%CURRENT%' ORDER BY started DESC LIMIT 1").fetchone()[0]   # 11-05: was pinned to eth-hs-full-20261102T170619
L = C.execute("""select v.entity, e.hash, e.frm, e.amount, e.block from edge e join a.attrib_v v on v.address=e.too and v.chain='eth'
                 and v.source='analyst:binance-eth-contracts:2026-11-02' where e.run_id=? and e.asset='ETH'
                 and (v.entity like 'Chainflip%' or v.entity like 'Relay%' or v.entity like 'Maya%')""", (RUN,)).fetchall()
CF = 'raw/eth_xchain.json'; cache = json.load(open(CF)) if os.path.exists(CF) else {}
def get(u):
    for k in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 404: return {'_notfound': True}
            time.sleep(20 * (k + 1) if e.code == 429 else 4)
        except Exception: time.sleep(4 * (k + 1))
    return {'_err': True}
for i, (ent, h, f, v, b) in enumerate(L):
    if h in cache: continue
    if ent.startswith('Chainflip'): cache[h] = get(f'https://chainflip-swap.chainflip.io/v2/swaps/{h}'); time.sleep(1.5)
    elif ent.startswith('Relay'): cache[h] = get(f'https://api.relay.link/requests/v2?hash={h}'); time.sleep(0.5)
    elif ent.startswith('Maya'):
        cache[h] = {'midgard': get(f'https://midgard.mayachain.info/v2/actions?txid={h[2:].upper()}'),
                    'node': get(f'https://mayanode.mayachain.info/mayachain/tx/status/{h[2:].upper()}')}; time.sleep(0.5)
    if i % 10 == 9: json.dump(cache, open(CF, 'w')); print(f'  {i + 1}/{len(L)}', flush=True)
json.dump(cache, open(CF, 'w'))
agg = collections.defaultdict(lambda: [0, 0.0]); rows = []
for ent, h, f, v, b in L:
    r = cache.get(h) or {}
    if ent.startswith('Chainflip'):
        st, dest = r.get('state'), f"{r.get('destChain')}:{r.get('destAsset')} {r.get('destAddress')}"
        if r.get('refundEgress') or st == 'FAILED': dest += f" | refund {(r.get('refundEgress') or {}).get('amount')} to {r.get('refundAddress')}"
    elif ent.startswith('Relay'):
        q = (r.get('requests') or [{}])[0]; d = q.get('data') or {}
        st = f"{q.get('status')} {d.get('failReason') or ''}".strip()
        dest = f"chain {(d.get('outTxs') or [{}])[0].get('chainId')} {q.get('recipient')} | outTx {[(o.get('hash') or '')[:14] for o in d.get('outTxs') or []]}"
    else:
        acts = [a for a in (r.get('midgard') or {}).get('actions') or [] if any(i.get('txID', '').upper() == h[2:].upper() for i in a.get('in') or [])]
        if acts:
            a = acts[0]; md = a.get('metadata') or {}
            st = f"{a.get('status')}/{a.get('type')}"
            outs = [(o.get('address'), [c['asset'] + ' ' + str(int(c['amount']) / 1e8) for c in o.get('coins', [])]) for o in a.get('out') or []]
            dest = f"memo {(md.get('swap') or md.get('refund') or {}).get('memo', '')[:70]} | out {outs[:2]}"
        else:
            obs = ((r.get('node') or {}).get('stages') or {}).get('inbound_observed', {}).get('completed')
            st, dest = f"not in Midgard (node: {'observed' if obs else 'not observed'})", ''
    k = (ent.split(':')[0], st); agg[k][0] += 1; agg[k][1] += v; rows.append((ent, h, f, v, st, dest))
json.dump(rows, open('raw/eth_xchain_rows.json', 'w'), indent=1)
for (e, s), (n, v) in sorted(agg.items()): print(f'{e:10} {s:44} {n:>3} deposits {v:10.4f} ETH')
print()
for ent, h, f, v, st, dest in sorted(rows, key=lambda r: -r[3])[:30]: print(f'{ent[:9]:9} {v:8.4f} {st[:26]:26} {h[:12]} from {f[:10]} → {dest[:150]}')
