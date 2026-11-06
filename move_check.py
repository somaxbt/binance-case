# Movement check: live balances vs the LATEST ledger runs (ETH v2 incl. unfrozen tokens, ETH tree, EVM side-chain trees [11-05], Tron v2, SOL tree, BTC bridged UTXOs,
# NEAR tree) + other pots via refresh.py. Extra ETH watch addresses go in raw/watch_eth.json {"addr": expected_eth}.
# 11-04 SPEED REWRITE (same checks, same thresholds, same output): written for free keys, now uses the paid ones —
#   ETH balances + token balances via Multicall3 (~400 per eth_call) · ETH nonces as JSON-RPC batches on Alchemy + QuickNode in parallel ·
#   Tron rows in parallel on BOTH keys (TronGrid 8/s + Tronscan 3/s) · SOL getMultipleAccounts chunks in parallel (Helius paid) ·
#   BTC: QuickNode gettxout (batched, spent = null) then Esplora outspend ONLY for spent coins (mempool.space first, Blockstream fallback) ·
#   NEW: NEAR tree (raw/near_ledger.json) via RPC. Old version: raw/move_check.py.bak-*-prespeed.
import json, os, urllib.request, urllib.error, time, sqlite3, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"').strip("'") for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l and not l.startswith('#')}
K = E['ALCHEMY_API_KEY']; TH = {"TRON-PRO-API-KEY": E['TRONGRID_API_KEY']}                                   # never print keys / URLs
TSH = {"TRON-PRO-API-KEY": E['TRONSCAN_API_KEY'], "Referer": "https://tronscan.org/"} if E.get('TRONSCAN_API_KEY') else None
def post(u, d, h={}):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, json.dumps(d).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0", **h}), timeout=60))
        except (urllib.error.HTTPError, OSError) as e:
            err = e; time.sleep(4 * (i + 1))
    raise err
def get(u, h={}):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", **h}), timeout=60))
        except (urllib.error.HTTPError, OSError) as e:
            err = e; time.sleep(6 * (i + 1))
    raise err
ETH = f"https://eth-mainnet.g.alchemy.com/v2/{K}"
LANES = [ETH] + ([E['QUICKNODE_BASE_URL'].rstrip('/') + '/' + E['QUICKNODE_TOKEN'].strip() + '/'] if E.get('QUICKNODE_BASE_URL') and E.get('QUICKNODE_TOKEN') else [])
MC3 = '0xca11bde05977b3631167028862be2a173976ca11'
out = {"ts": time.strftime('%F %T'), "changed": []}; T = {}
def timed(f):
    def w(*a):
        t = time.time(); r = f(*a); T[f.__name__] = round(time.time() - t, 1); return r
    w.__name__ = f.__name__; return w

def multicall(calls, lane=0, lanes=None):
    """[(target, calldata)] → [returnData hex | None]; Multicall3.aggregate3(allowFailure=true), 400 per eth_call, chunks spread over lanes"""
    def one(k_part):
        k, part = k_part; n = len(part); head, tail = [], []; off = 32 * n
        for t, data in part:
            body = bytes.fromhex(data[2:]); enc = t[2:].rjust(64, '0') + '1'.rjust(64, '0') + hex(96)[2:].rjust(64, '0') + hex(len(body))[2:].rjust(64, '0') + body.hex().ljust(((len(body) + 31) // 32) * 64, '0')
            head.append(hex(off)[2:].rjust(64, '0')); tail.append(enc); off += len(enc) // 2
        data = '0x82ad56cb' + hex(32)[2:].rjust(64, '0') + hex(n)[2:].rjust(64, '0') + ''.join(head) + ''.join(tail)
        for i in range(8):
            L = lanes or LANES; j = post(L[(k + i) % len(L)], {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'to': MC3, 'data': data}, 'latest']})
            if j.get('result'): break
            time.sleep(2 * (i + 1))
        raw = bytes.fromhex((j.get('result') or '0x')[2:]); res = []
        if not raw: raise RuntimeError('multicall failed')
        m = int.from_bytes(raw[32:64], 'big'); arr = 64
        for q in range(m):
            o = arr + int.from_bytes(raw[arr + 32 * q: arr + 32 * q + 32], 'big'); ok = int.from_bytes(raw[o:o + 32], 'big')
            bo = o + int.from_bytes(raw[o + 32:o + 64], 'big'); ln = int.from_bytes(raw[bo:bo + 32], 'big')
            res.append('0x' + raw[bo + 32:bo + 32 + ln].hex() if ok else None)
        return res
    parts = [(k, calls[i:i + 400]) for k, i in enumerate(range(0, len(calls), 400))]
    with ThreadPoolExecutor(min(4, len(parts) or 1)) as ex: return [r for chunk in ex.map(one, parts) for r in chunk]
num = lambda r: int(r, 16) if r and len(r) > 2 else 0
bal_call = lambda a: (MC3, '0x4d2301cc' + a[2:].rjust(64, '0'))
tok_call = lambda tok, a: (tok, '0x70a08231' + a[2:].rjust(64, '0'))

@timed
def eth():
    # ETH v2 ledger: native ETH + every unfrozen token with a balance (Multicall: was 1 call per token balance + per decimals)
    e = sqlite3.connect("file:binance-eth-ledger.db?mode=ro", uri=True); er = e.execute("select run_id from ledger_run where leg='eth2' and finished glob '2026*' order by started desc limit 1").fetchone()[0]
    eth_nodes = e.execute("select address, bal from eth_node where run_id=? and asset='ETH'", (er,)).fetchall()
    watch = json.load(open("raw/watch_eth.json")) if os.path.exists("raw/watch_eth.json") else {}
    eth_nodes += [(a, v) for a, v in watch.items() if a not in {x for x, _ in eth_nodes}]
    for (a, lb), r in zip(eth_nodes, multicall([bal_call(a) for a, _ in eth_nodes])):
        now = num(r) / 1e18
        if abs(now - (lb or 0)) > 0.05: out["changed"].append(("ETH", a, "ETH", lb, now))
    toks = e.execute("select address, asset, symbol, bal from eth_node where run_id=? and asset!='ETH' and bal>0 and frozen=0", (er,)).fetchall()
    uniq = sorted({t for _, t, _, _ in toks}); dec = dict(zip(uniq, [num(r) for r in multicall([(t, '0x313ce567') for t in uniq])]))
    for (a, tok, sym, lb), r in zip(toks, multicall([tok_call(tok, a) for a, tok, _, _ in toks])):
        now = num(r) / 10 ** dec[tok]
        if abs(now - lb) > max(1e-6, lb * 1e-4): out["changed"].append(("ETH", a, sym, lb, now))
    print(f"ETH: {len(eth_nodes)} wallets ({er}, +{len(watch)} watch), {len(toks)} unfrozen token balances")
    # ETH HyperSync tree (binance-bridged.db, run marked CURRENT): balance (Multicall) + NONCE (batched, both lanes in parallel)
    EB = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True)
    ER = (EB.execute("select run_id from run where params like '%CURRENT%' order by run_id desc limit 1").fetchone() or ['eth-hs-full-20261102T170619'])[0]
    tw = EB.execute("select n.address,n.live from node n join wallet w on w.run_id=n.run_id and w.address=n.address where n.run_id=? and w.status='tree' and n.asset='ETH'", (ER,)).fetchall()
    NF = 'raw/watch/eth_tree_nonce.json'; os.makedirs('raw/watch', exist_ok=True); nb = json.load(open(NF)) if os.path.exists(NF) else {}
    A = [a for a, _ in tw]; bal = dict(zip(A, [num(r) for r in multicall([bal_call(a) for a in A])]))
    non = {}; lk = threading.Lock()
    def nonces(k_ch):
        k, ch = k_ch; left = list(ch)
        for i in range(8):
            if not left: return
            try: rs = post(LANES[(k + i) % len(LANES)], [{"jsonrpc": "2.0", "id": j, "method": "eth_getTransactionCount", "params": [a, "latest"]} for j, a in enumerate(left)])
            except Exception: rs = []
            got = {r["id"]: r["result"] for r in rs if isinstance(r, dict) and "result" in r}
            with lk: non.update({left[j]: int(v or "0x0", 16) for j, v in got.items()})
            left = [a for j, a in enumerate(left) if j not in got]
            if left: time.sleep(1 + i)
        if left: raise RuntimeError(f'{len(left)} nonces failed')
    with ThreadPoolExecutor(2 * len(LANES)) as ex: list(ex.map(nonces, [(k, A[i:i + 50]) for k, i in enumerate(range(0, len(A), 50))]))
    for a, lb in tw:
        now = bal[a] / 1e18
        if a in nb and non[a] != nb[a]: out["changed"].append(("ETH-tree", a, f"ETH (nonce {nb[a]}->{non[a]})", lb or 0, now))
        elif abs(now - (lb or 0)) > 0.05: out["changed"].append(("ETH-tree", a, "ETH", lb or 0, now))
    json.dump({**nb, **non}, open(NF, 'w'))
    print(f"ETH tree: {len(tw)} wallets ({ER}), balance + nonce{' — NONCE BASELINE written (first run)' if not nb else ''}")

class Gate:                                   # per-key pacing shared by threads
    def __init__(s, qps): s.dt, s.lock, s.next = 1 / qps, threading.Lock(), 0.0
    def wait(s):
        with s.lock: t = max(time.time(), s.next); s.next = t + s.dt
        time.sleep(max(0, t - time.time()))
GTG, GTS = Gate(8), Gate(3)
@timed
def tron():
    # Tron v2 ledger holders: TRX (incl. staked) + USDT — rows in parallel; TRX on whichever key is free, USDT = live contract call (TronGrid)
    t = sqlite3.connect("file:binance-live.db?mode=ro", uri=True); tr = t.execute("select run_id from ledger_run where leg='tron2' and finished glob '2026*' order by started desc limit 1").fetchone()[0]
    rows = t.execute("select address,asset,bal from ledger_node where run_id=? and ((asset='TRX' and bal>100) or (asset='USDT' and bal>1))", (tr,)).fetchall()
    B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"; turn = [0]; tl = threading.Lock()
    def one(row):
        a, asset, lb = row
        if asset == "TRX":
            with tl: use_ts = TSH is not None and turn[0] % 11 >= 8; turn[0] += 1          # ≈ 8:3 split = the two keys' rates
            if use_ts:
                GTS.wait(); d = get(f"https://apilist.tronscanapi.com/api/accountv2?address={a}", TSH); now = ((d.get('balance') or 0) + (d.get('totalFrozenV2') or 0)) / 1e6
            else:
                GTG.wait(); acc = (get(f"https://api.trongrid.io/v1/accounts/{a}", TH).get("data") or [{}])[0]; now = (acc.get("balance", 0) + sum(f.get("amount", 0) for f in acc.get("frozenV2", []))) / 1e6
        else:
            n = 0
            for ch in a: n = n * 58 + B58.index(ch)
            GTG.wait(); d = post("https://api.trongrid.io/wallet/triggerconstantcontract", {"owner_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "function_selector": "balanceOf(address)", "parameter": n.to_bytes(25, "big")[1:21].hex().rjust(64, "0"), "visible": True}, TH)
            now = int((d.get("constant_result") or ["0"])[0][-64:], 16) / 1e6
        return a, asset, lb, now
    with ThreadPoolExecutor(8) as ex:
        for a, asset, lb, now in ex.map(one, rows):
            if abs(now - lb) > max(1, lb * 1e-6): out["changed"].append(("TRON", a, asset, lb, now))
    print(f"TRON: {len(rows)} holder balances ({tr})")

@timed
def sol():
    # Solana tree wallets (Helius getMultipleAccounts, 100 per call — chunks in parallel). MC_SOL_LEDGER picks the baseline file.
    LF = os.environ.get('MC_SOL_LEDGER', 'raw/sol_ledger_next.json')   # 11-04: baseline = SOL END ledger at the common cutoff (old pushed ledger: MC_SOL_LEDGER=raw/sol_ledger.json)
    if os.path.exists(LF):
        SL = json.load(open(LF)); HU = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}" if E.get('HELIUS_API_KEY') else None
        if HU and SL.get('kind') == 'tree':
            ws = list(SL['wallets'])
            def chunk(ch): return ch, post(HU, {"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts", "params": [ch, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}]})["result"]["value"]
            with ThreadPoolExecutor(8) as ex:
                for ch, v in ex.map(chunk, [ws[i:i + 100] for i in range(0, len(ws), 100)]):
                    for a, acc in zip(ch, v):
                        now = (acc or {}).get("lamports", 0) / 1e9; w = SL['wallets'][a]
                        if abs(now - w['held']) > 0.001: out["changed"].append(("SOL", a, "SOL", w['held'], now))
            print(f"SOL: {len(SL['wallets'])} tree wallets (ledger {LF} at {SL['at']})")
    print("SOL/XRP watch (sol_watch.py):\n" + subprocess.run(["python3", "sol_watch.py"], capture_output=True, text=True).stdout)

@timed
def btc():
    # BTC bridged ledger: every unspent attacker UTXO of the latest FINISHED bridged run; spent = moved (outpoint-level).
    # QuickNode gettxout (null = spent, mempool included) in batches → Esplora outspend only for the spent ones (to name the spender).
    if os.path.exists("binance-btc-bridged-ledger.db") and not os.environ.get("MC_SKIP_BTC"):
        BB = sqlite3.connect('file:binance-btc-bridged-ledger.db?mode=ro', uri=True)
        br = BB.execute("select run_id from ledger_run where finished is not null order by started desc limit 1").fetchone()
        if br:
            us = BB.execute("select txid,vout,address,sats from utxo where run_id=? and owner='attacker' and status like 'unspent%'", (br[0],)).fetchall()
            QB = (E['QUICKNODE_BTC_URL'].rstrip('/') + '/' + E['QUICKNODE_BTC_TOKEN'].strip() + '/') if E.get('QUICKNODE_BTC_URL') and E.get('QUICKNODE_BTC_TOKEN') else None
            spent = []
            if QB:
                def qn(part):
                    for i in range(6):
                        try:
                            rs = post(QB, [{"jsonrpc": "2.0", "id": j, "method": "gettxout", "params": [t, v, True]} for j, (t, v, _, _) in enumerate(part)])
                            got = {r["id"]: r for r in rs if isinstance(r, dict) and "id" in r and r.get("error") is None}
                            if len(got) == len(part): return [part[j] for j in range(len(part)) if got[j].get("result") is None]
                        except Exception: pass
                        time.sleep(2 * (i + 1))
                    raise RuntimeError('gettxout batch failed')
                with ThreadPoolExecutor(4) as ex: spent = [x for s in ex.map(qn, [us[i:i + 50] for i in range(0, len(us), 50)]) for x in s]
            else: spent = list(us)                                           # no QuickNode BTC → old path: ask Esplora for every coin
            def outspend(row):
                t, v, a, sats = row
                for base in ('https://mempool.space/api', 'https://blockstream.info/api'):
                    try: return row, json.load(urllib.request.urlopen(urllib.request.Request(f"{base}/tx/{t}/outspend/{v}", headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
                    except Exception: time.sleep(1)
                return row, {"spent": True, "txid": "?" * 12}
            with ThreadPoolExecutor(4) as ex:
                for (t, v, a, sats), o in ex.map(outspend, spent):
                    if o.get("spent"): out["changed"].append(("BTC-bridged", a, f"UTXO {t[:12]}:{v} spent by {(o.get('txid') or '?')[:12]}", sats / 1e8, 0.0))
            print(f"BTC bridged: {len(us)} unspent UTXOs checked ({br[0]}){' via QuickNode gettxout' if QB else ''}, {len(spent)} spent")

@timed
def near():
    # NEW 11-04: NEAR tree wallets (raw/near_ledger.json) — live balance vs ledger 'held'
    if os.path.exists("raw/near_ledger.json"):
        NL = json.load(open("raw/near_ledger.json"))
        NR = (E['QUICKNODE_NEAR_URL'].rstrip('/') + '/' + E['QUICKNODE_NEAR_TOKEN'].strip() + '/') if E.get('QUICKNODE_NEAR_URL') and E.get('QUICKNODE_NEAR_TOKEN') else 'https://rpc.mainnet.fastnear.com'
        def one(a): return a, int((post(NR, {'jsonrpc': '2.0', 'id': 1, 'method': 'query', 'params': {'request_type': 'view_account', 'finality': 'final', 'account_id': a}}).get('result') or {}).get('amount', 0)) / 1e24
        with ThreadPoolExecutor(8) as ex:
            for a, now in ex.map(one, list(NL['wallets'])):
                lb = NL['wallets'][a]['held']
                if abs(now - lb) > 0.01: out["changed"].append(("NEAR", a, "NEAR", lb, now))
        print(f"NEAR: {len(NL['wallets'])} tree wallets (ledger {NL['at']})")

# NEW 11-05: EVM SIDE-CHAIN TREES (binance-bridged.db, CURRENT run per chain — eth_hs.py EVM_CHAIN runs): every tree wallet's native +
# token balances vs node.live at the cutoff (Multicall3 on that chain) + NONCE vs the last check (raw/watch/<chain>_tree_nonce.json).
# Lanes = that chain's Alchemy + QuickNode (if keyed); chains run side by side (different providers).
SIDE = {'avax': ('avax-mainnet', 'AVAX', 1.0), 'arb': ('arb-mainnet', None, 0.01), 'opt': ('opt-mainnet', 'OP', 0.01),
        'polygon': ('polygon-mainnet', 'POLYGON', 50.0), 'base': ('base-mainnet', None, 0.01), 'bsc': ('bnb-mainnet', 'BSC', 0.05)}   # (alchemy net, QuickNode env prefix, native threshold)
def side_lanes(ch):
    net, qp, _ = SIDE[ch]; L = [f"https://{net}.g.alchemy.com/v2/{K}"]
    u, t = E.get(f'QUICKNODE_{qp}_URL', '').rstrip('/'), E.get(f'QUICKNODE_{qp}_TOKEN', '').strip()
    if qp and u and t: L.append(u[:-len('/ext/bc/C/rpc')].rstrip('/') + '/' + t + '/ext/bc/C/rpc' if u.endswith('/ext/bc/C/rpc') else u + '/' + t + '/')
    return L
def side_one(ch):
    EB = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True)
    r = EB.execute(f"SELECT run_id FROM run WHERE finished GLOB '2026*' AND params NOT LIKE '%validation%' AND params NOT LIKE '%INVALID%' AND params NOT LIKE '%aborted%' "
                   f"AND params NOT LIKE '%superseded%' AND (run_id LIKE '{ch}-hs-full-%' OR run_id LIKE '{ch}-hs-inc-%') ORDER BY started DESC LIMIT 1").fetchone()
    if not r: return f"{ch}: no current run"
    R = r[0]; L = side_lanes(ch); th = SIDE[ch][2]
    rows = EB.execute("SELECT n.address, n.asset, n.live FROM node n JOIN wallet w ON w.run_id=n.run_id AND w.address=n.address WHERE n.run_id=? AND w.status='tree'", (R,)).fetchall()
    nat = [(a, lv) for a, s_, lv in rows if not s_.startswith('0x')]; tok = [(a, s_, lv) for a, s_, lv in rows if s_.startswith('0x') and (lv or 0) > 0]
    natsym = next((s_ for _, s_, _ in rows if not s_.startswith('0x')), '?')
    nb_now = multicall([bal_call(a) for a, _ in nat], lanes=L)
    for (a, lb), x in zip(nat, nb_now):
        if abs(num(x) / 1e18 - (lb or 0)) > th: out["changed"].append((ch.upper() + "-tree", a, natsym, lb or 0, num(x) / 1e18))
    if tok:
        uniq = sorted({t_ for _, t_, _ in tok}); dec = dict(zip(uniq, [num(x) or 18 for x in multicall([(t_, '0x313ce567') for t_ in uniq], lanes=L)]))
        for (a, t_, lb), x in zip(tok, multicall([tok_call(t_, a) for a, t_, _ in tok], lanes=L)):
            now = num(x) / 10 ** dec[t_]
            if abs(now - lb) > max(1e-6, lb * 1e-4): out["changed"].append((ch.upper() + "-tree", a, t_, lb, now))
    NF = f'raw/watch/{ch}_tree_nonce.json'; os.makedirs('raw/watch', exist_ok=True); nb = json.load(open(NF)) if os.path.exists(NF) else {}
    A = [a for a, _ in nat]; non = {}
    for k, i in enumerate(range(0, len(A), 50)):
        left = A[i:i + 50]
        for j in range(8):
            if not left: break
            try: rs = post(L[(k + j) % len(L)], [{"jsonrpc": "2.0", "id": q, "method": "eth_getTransactionCount", "params": [a, "latest"]} for q, a in enumerate(left)])
            except Exception: rs = []
            got = {x["id"]: x["result"] for x in rs if isinstance(x, dict) and "result" in x}
            non.update({left[q]: int(v or "0x0", 16) for q, v in got.items()}); left = [a for q, a in enumerate(left) if q not in got]
            if left: time.sleep(1 + j)
        if left: raise RuntimeError(f'{ch}: {len(left)} nonces failed')
    for a in A:
        if a in nb and non[a] != nb[a]: out["changed"].append((ch.upper() + "-tree", a, f"{natsym} (nonce {nb[a]}->{non[a]})", 0, 0))
    json.dump({**nb, **non}, open(NF, 'w'))
    return f"{ch}: {len(A)} tree wallets, {len(tok)} token balances ({R}){' — NONCE BASELINE written (first run)' if not nb else ''}"
@timed
def evm_side():
    with ThreadPoolExecutor(len(SIDE)) as ex:
        for msg in ex.map(side_one, SIDE): print(msg)

@timed
def pots():
    # other pots
    prev = json.load(open("raw/refresh_latest.json"))
    os.system("python3 refresh.py > /dev/null 2>&1")
    cur = json.load(open("raw/refresh_latest.json"))
    for k in cur:
        if k.startswith(("BTC", "XRP", "SOL", "AVAX", "POL", "OP-")) and abs(cur[k] - prev.get(k, cur[k])) > 0.01: out["changed"].append(("OTHER", k, "", prev.get(k), cur[k]))
    return cur
# one thread per API provider family (legs use different providers, so they run side by side)
ST = {"eth": eth, "evm": evm_side, "tron": tron, "sol": sol, "btc": btc, "near": near, "pots": pots}
if os.environ.get("MC_ONLY"): ST = {k: v for k, v in ST.items() if k in os.environ["MC_ONLY"].split(",")}   # e.g. MC_ONLY=eth
t0 = time.time()
with ThreadPoolExecutor(len(ST)) as ex: F = {k: ex.submit(f) for k, f in ST.items()}
for k, f in F.items():
    if f.exception(): print(f"!! {k} FAILED: {f.exception()!r}"); out.setdefault("failed", []).append(k)
cur = {} if "pots" not in F or F["pots"].exception() else F["pots"].result()
out["timing_s"] = {**T, "total": round(time.time() - t0, 1)}
json.dump(out, open("raw/move_check_latest.json", "w"), indent=1)
blk = post(ETH, {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": ["latest", False]})["result"]
print("as of", time.strftime('%m-%d %H:%M UTC', time.gmtime(int(blk['timestamp'], 16))), "block", int(blk['number'], 16), "· timing (s):", out["timing_s"])
print("\nCHANGED since ledger / last check:")
for c in out["changed"]: print("  ", c[0], c[1], c[2], f"{c[3]:,.4f}" if isinstance(c[3], (int, float)) else c[3], "->", f"{c[4]:,.4f}")
if "pots" in F:
    print("\nBRIDGE DESTINATIONS (funds that left Tron) — changes since baseline:")
    os.system("python3 dest_watch.py --check 2>&1 | sed -n '/CHANGED since baseline/,/^$/p' | head -25")
    print("other pots now:", {k: round(v, 2) for k, v in cur.items() if k.startswith(("BTC", "XRP", "SOL", "AVAX", "Aave"))})
