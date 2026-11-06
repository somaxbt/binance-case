"""Solana TREE ledger (native SOL) from pre/postBalances, root = pot AffzFDKZ. Replaces the single-wallet sol leg of single_ledger.py.
Per wallet: stolen + in_tree + in_foreign = out_tree + exits + external + rent/dust + fees + held  (start balance must be ~0 -> else UNEXPLAINED).
Join rule: a receiver joins the tree if its first-ever tx is after SINCE and it is a system-owned wallet; a joined wallet with real foreign
inflow is flagged MIXED at the end (judged against the FINAL tree; returns from its own hops are not foreign). Only a clear service
(>10 SOL and >50% of its inflow from outside, judged during discovery) or a wallet with >300 receivers is not followed -> booked as an exit. Relay solver deposits resolved via
Relay v2 ?user=<sender> (v2 retires 2026-11-24). Cache raw/sol/tx_<sig>.json, raw/sol/relay_requests.json.   python3 sol_ledger.py"""
import json, os, time, shutil, urllib.request, urllib.error, collections, threading
from concurrent.futures import ThreadPoolExecutor
os.chdir(os.path.dirname(os.path.abspath(__file__)))
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
# Helius is THE Solana RPC (user 11-02); Alchemy only takes overflow: when Helius is >1 s backed up or just 429'd. Never print these URLs.
EPS = ([f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"] if E.get('HELIUS_API_KEY') else []) + [f"https://solana-mainnet.g.alchemy.com/v2/{E['ALCHEMY_API_KEY']}"]
ROOT = 'AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU'; SINCE = 1793232000                      # 2026-10-29 00:00 UTC
# 11-04 (user): fixed END cutoff. SOL_END='2026-11-04T01:32:07Z' (or unix) -> txs after END ignored, held = balance AT END (from the
# wallet's last tx <= END), so the ledger is a snapshot of one moment instead of chasing live moves. Unset = old live behaviour.
import calendar
_e = os.environ.get('SOL_END'); END = (int(_e) if _e.isdigit() else calendar.timegm(time.strptime(_e, '%Y-%m-%dT%H:%M:%SZ'))) if _e else None
RUN_STARTED = time.strftime('%FT%TZ', time.gmtime())
inwin = lambda s: END is None or (s.get('blockTime') or 0) <= END
SIGL, ACC, SKIP = {}, {}, set()                                                       # addr -> its sig list (newest first) / owner -> {token account: mint}
# 11-04: extra roots = Solana wallets that received USDC minted (CCTP) from OUR dYdX accounts (cctp_return.py). Without them the
# SOL->USDC->CCTP->Noble->dYdX->CCTP->Solana loop re-enters the tree as 'foreign' (≈ most of 18.9k SOL at END 01:32).
SEEDS = {a: v for f in os.environ.get('SOL_SEEDS', '').split(',') if f and os.path.exists(f) for a, v in json.load(open(f))['seeds'].items() if not a.startswith('?')}   # comma list: cctp_returns.json,mixer_seeds.json
POR = set(open('agents/por_sol.txt').read().split()) | {'5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'}
EXITS = {'7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ': 'Relay (solver)',
         'F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe': 'Relay (solver)',
         '6H7GCfCx8JMUACbmSYZjConeJGzViPHhMvvYak5SDDBe': 'Layerswap',
         'FoxKvLEytmFo281TqfYjFAaAPGJakmkr9npwTXK3o8qP': 'OKX (deposit address)',   # fresh 11-02 04:21, swept to OKX in 1 min
         'J1QUUqWHE39CHN6iep8EmrXS4EnMexULZHKxSiZa9ZLp': 'Chainflip (vault)',   # user 11-04: Chainflip SOL vault — exit, never follow
         '4AV2Qzp3N4c9RfzyEbNZs2wqWfW4EwKnnxFAZCndvfGh': 'Privacy Cash (mixer pool)',   # user 11-04: Solana mixer pool (program 9fhQBbumKE…); deposits = exit, payouts = withdrawals
         '5cMKyZ58Z3nCMPenf1HiANGkbBfZE8GCtPD1kzZwo2jb': 'shielded pool mixpx (mixer pool)',   # 11-05: program mixpxDk31h3jFV8t42vfmRqwq7sESDMrtsKQeyrjRmL (Shield/Unshield, relayer-paid unshields); tree in 9,067 / back 4,495 were 'external' / 'foreign'
         '7fs5cKGNPvgWmALvbHfMmqZpomTjP236JeBuNKNzTWQo': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         '6KdE45WpeThZFRBFoyTo9hR7bWQYzrFG9HrP4xUWdyEE': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         '9RtpqByKqVEBvpicKinExtd3g8pY6P8qCQjzjuGwH9Rc': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         'Cm5DV5BAvJR6bH1gt4j9n5XQciNWH6AoRgzXdFBwBibc': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         'EqqmUXwTBN9x1LNeq9VU5nhocLLqdXG7JoDEzL566PUU': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         'FohjdfQUNbUnfEaH7ux6o7FCuRnLs7WtcC7dd4xpsmvn': 'privacy pool (unconfirmed) 7fs5cKGN',   # user 11-05: keep as privacy pool, demix later; reused deposit addrs swept to 7fs5cKGN in 1-3 min (9 other payers)
         'is6MTRHEgyFLNTfYcuV4QBWLjrZBfmhVNYR6ccgr8KV': 'OKX'}                     # por-wallets.db okx/reserves (DefiLlama, community)       # user 11-02, confirmed by Layerswap explorer API (raw/sol/layerswap.json)   # refund payer: Relay request of CBoBp7P1, refund out tx 5vvJwevi (11-01 12:38)
# 11-05: a bridge PROGRAM in the tx makes the wallet's out-legs a bridge exit. deBridge preswaps SOL->USDC and opens the order in ONE tx, so the
# legs looked like 'out: swap (DEX)' (516 txs / 56,126 SOL hidden). Orders -> destinations: sol_debridge_resolve.py (raw/sol/debridge_dest.json).
BRIDGE_PROG = {'src5qyZHqTqecJV4aY6Cb6zDZLMDzrDKKezs22MPHr4': 'deBridge DLN'}; BSIG = {}
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'                   # SOL to/from a wSOL token account we don't own = a DEX swap leg
SYS = '11111111111111111111111111111111'; DUST = 0.01
# (B) 11-03: tokens are ledgered too (by OWNER), so swap outputs and the Jupiter Lend receipt round trip stay in the tree. Native units per asset.
MINT = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
        '2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU': 'jlWSOL'}          # Jupiter Lend receipt: minted on deposit, burned on redeem
TMIN = {'SOL': DUST, 'USDC': 1, 'USDT': 1, 'jlWSOL': 0.01}
PROTO = {'5JP5zgYCb9W37QQLgAHRHuinFLrKt87akDY1CgZoTPzr': 'Jupiter Lend'}    # wSOL vault (program jup3YeL8…); was read as 'swap (DEX)'
SIGNER = {}                                                              # sig -> fee payer

import threading
_lk = threading.Lock(); _next = [0.0] * len(EPS)
HRPS = float(os.environ.get('HELIUS_RPS', '8'))           # 11-04: Helius Developer plan = 50 req/s; run at HELIUS_RPS=40
_hot = [0.0]                                     # Helius 429'd until this time -> overflow to Alchemy
def rpc(m, p):                                   # ~8 req/s per key; Helius first, Alchemy only as overflow; 429 backs off up to ~6 min
    for i in range(12):
        with _lk:
            j = 0 if len(EPS) == 1 or (_next[0] - time.time() < 1 and time.time() > _hot[0]) else min(range(len(EPS)), key=lambda x: _next[x])
            w = _next[j] - time.time()
            if w > 0: time.sleep(w)
            _next[j] = max(_next[j], time.time()) + (1 / HRPS if j == 0 and EPS[0].startswith('https://mainnet.helius') else 0.125)
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(EPS[j], json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=60))
            if 'error' in r: raise RuntimeError(r['error'])
            return r.get('result')
        except Exception as e:
            err = e
            if j == 0 and getattr(e, 'code', None) == 429 and len(EPS) > 1: _hot[0] = time.time() + 30; continue
            time.sleep(min(60, 5 * (i + 1)))
    raise err
SG = 'raw/sol/sigs'; os.makedirs(SG, exist_ok=True)
def sigs(a, since=SINCE, cached=False):
    """Signatures since SINCE, newest first. Cached per address (11-03): a later run asks only for sigs NEWER than the cached
    newest ('until'), so an unchanged wallet costs one empty call and its txs come from the tx cache."""
    f = f'{SG}/{a}.json'; old = []
    for _ in range(5):
        try: old = json.load(open(f)) if os.path.exists(f) else []; break
        except ValueError: time.sleep(0.2)                              # file mid-write
    if (cached or a in SKIP) and os.path.exists(f): return old                 # 11-04 SOL_BASE: proven unchanged since the base END -> no RPC
    if END and os.path.exists(f) and os.path.getmtime(f) >= END: return old   # FIX A (11-04): cache saved after END already holds every sig <= END -> no RPC
    out, before = [], None
    while True:
        r = rpc('getSignaturesForAddress', [a, {'limit': 1000, **({'before': before} if before else {}), **({'until': old[0]['signature']} if old else {})}]) or []
        out += [{'signature': x['signature'], 'blockTime': x.get('blockTime'), 'err': x.get('err')} for x in r if (x.get('blockTime') or 0) >= since]
        if len(r) < 1000 or (r[-1].get('blockTime') or 0) < since: break
        before = r[-1]['signature']
    out += old; json.dump(out, open(f, 'w'))
    return out
def tx(sig):
    f = f'raw/sol/tx_{sig}.json'
    if os.path.exists(f):
        for _ in range(5):
            try: return json.load(open(f))
            except ValueError: time.sleep(0.2)                          # file mid-write (prefetch thread)
    t = rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 1}])
    if t: json.dump(t, open(f, 'w'))
    return t
PC = 'raw/sol/probe_cache.json'; _plk = threading.Lock(); PROBE = json.load(open(PC)) if os.path.exists(PC) else {}
def probe(a):
    if a not in PROBE or PROBE[a][0] is None:                         # 11-03: never cache an empty first_seen (an empty RPC answer hid 40.5k SOL of swap recipients)
        PROBE[a] = [first_seen(a), owner(a)]
        if PROBE[a][0] is not None:
            with _plk: json.dump(dict(PROBE), open(PC, 'w'))   # prefetch threads write too
    return PROBE[a]
def first_seen(a):                       # oldest tx time; None = never used; 0 = >5,000 txs since SINCE (busy -> service, not followed)
    before, last = None, None
    for _ in range(5):
        r = rpc('getSignaturesForAddress', [a, {'limit': 1000, **({'before': before} if before else {})}]) or []
        if not r: return last
        last = r[-1].get('blockTime'); before = r[-1]['signature']
        if len(r) < 1000 or last < SINCE: return last
    return 0
def owner(a): return ((rpc('getAccountInfo', [a, {'encoding': 'base64'}]) or {}).get('value') or {}).get('owner', SYS)

K = lambda t: [k['pubkey'] if isinstance(k, dict) else k for k in t['transaction']['message']['accountKeys']]
# 11-04 (user): INCREMENTAL run on top of the previous END ledger (SOL_BASE=raw/sol_ledger_<prev>.json; it becomes the base of the next run).
# A base tree wallet whose SOL balance now equals its balance at the base END, and that held no tokens then, had no tx it paid for ->
# its sigs (and its token accounts') come from cache, no RPC (11-04: 9,583 of 9,875 skipped). Closure: every NEW tx of a wallet that is read
# un-skips any skipped wallet it lists (account key or token-balance owner); repeat until stable.
# ponytail: misses activity on an old zero-token tree wallet that is funded AND fee-paid from outside and nets to zero (foreign
#           pass-through, not our funds); a run without SOL_BASE is the full check — do one now and then.
_b = os.environ.get('SOL_BASE')
if END and _b and os.path.exists(_b):
    BL = json.load(open(_b)); BW = BL['wallets']; BEND = calendar.timegm(time.strptime(BL['window']['end'], '%Y-%m-%dT%H:%M:%SZ'))
    assert BEND < END, 'SOL_BASE must be an earlier END ledger'
    ws, nowl = list(BW), {}
    for i in range(0, len(ws), 100):
        for a, x in zip(ws[i:i + 100], rpc('getMultipleAccounts', [ws[i:i + 100], {'encoding': 'base64', 'dataSlice': {'offset': 0, 'length': 0}}])['value']):
            nowl[a] = (x or {}).get('lamports', 0)
    SKIP |= {a for a in ws if nowl[a] == round(BW[a]['held'] * 1e9) and not any(v.get('held', 0) > 0 for v in (BW[a].get('tok') or {}).values())}
    front, nb = [a for a in ws if a not in SKIP], len(SKIP)
    while front:
        with ThreadPoolExecutor(32) as ex: new = [x['signature'] for L in ex.map(sigs, front) for x in L if not x.get('err') and inwin(x) and (x.get('blockTime') or 0) > BEND]
        with ThreadPoolExecutor(32) as ex: TT = [t for t in ex.map(tx, set(new)) if t]
        hit = {k for t in TT for k in K(t) + [b.get('owner') for b in (t['meta'].get('preTokenBalances') or []) + (t['meta'].get('postTokenBalances') or [])] if k in SKIP}
        SKIP -= hit; front = list(hit)
    print(f'  SOL_BASE {_b} (END {BL["window"]["end"]}): {len(SKIP)} of {len(ws)} base wallets unchanged -> cache only ({nb - len(SKIP)} un-skipped by closure)', flush=True)
def at_end_sol(a):                                   # SOL balance right after a's last tx <= END (failed txs count: they still charge fees)
    for s in SIGL.get(a) or sigs(a):                 # newest first, in chain order (safe for same-second txs)
        if not inwin(s): continue
        t = tx(s['signature'])
        if t and a in K(t): return t['meta']['postBalances'][K(t).index(a)] / 1e9
    return 0.0
def at_end_tok(a):                                   # per asset: sum over a's known token accounts of the amount after the account's last tx <= END
    h = {s: 0.0 for s in MINT.values()}
    for x, m in (ACC.get(a) or {}).items():
        for s in SIGL.get(x) or sigs(x):
            if not inwin(s): continue
            t = tx(s['signature'])
            if not t or x not in K(t): continue
            j = K(t).index(x); b = [b for b in t['meta'].get('postTokenBalances') or [] if b['accountIndex'] == j]
            h[MINT[m]] += float(b[0]['uiTokenAmount']['uiAmount'] or 0) if b else 0.0   # absent in post = account closed -> 0
            break
    return h

def read(a):
    """flows of wallet a: list of (t, sig, kind, counterparty, amount, asset). kind in in / out / fee / unattr / swapto
    swapto = a SIGNED a tx that paid another wallet an asset a did not send itself (swap output to a 3rd address, lend receipt minted to it)"""
    SIGL[a] = sigs(a)
    S = {s['signature']: s for s in SIGL[a] if not s.get('err') and inwin(s)}
    with ThreadPoolExecutor(8) as ex: T = dict(zip(S, ex.map(tx, S)))
    # tokens sent to an EXISTING token account don't list its owner (11-03: ARk92box's 947k USDC was invisible) -> also read a's token accounts.
    # ponytail: accounts are found from a's own txs (ATA creation lists the owner); a non-ATA account created by a 3rd party would be missed.
    ac = {K(t)[b['accountIndex']]: b['mint'] for t in T.values() if t for b in (t['meta'].get('preTokenBalances') or []) + (t['meta'].get('postTokenBalances') or [])
          if b.get('owner') == a and b['mint'] in MINT}
    ACC[a] = ac
    for x in ac: SIGL[x] = sigs(x, cached=a in SKIP)
    extra = {s['signature']: s for x in ac for s in SIGL[x] if not s.get('err') and inwin(s) and s['signature'] not in S}
    with ThreadPoolExecutor(8) as ex: T.update(zip(extra, ex.map(tx, extra)))
    S.update(extra)
    rows = []
    for s in sorted(S.values(), key=lambda s: s.get('blockTime') or 0):
        t = T[s['signature']]
        if not t or t['meta'].get('err'): continue
        keys = K(t); bt, sg = s['blockTime'], s['signature']; SIGNER[sg] = keys[0]
        cctp = any(str(x.get('programId', '')).startswith(('CCTPmbSD', 'CCTPV2Sm', 'CCTPiPYP', 'CCTPV2vP')) for x in t['transaction']['message']['instructions'] + [y for ii in (t['meta'].get('innerInstructions') or []) for y in ii['instructions']])   # 11-04: CCTP MessageTransmitter (v1/v2) = USDC mint; a custody/fee owner in the tx must not make it 'foreign'
        bp = [BRIDGE_PROG[x['programId']] for x in t['transaction']['message']['instructions'] + [y for ii in (t['meta'].get('innerInstructions') or []) for y in ii['instructions']] if x.get('programId') in BRIDGE_PROG]
        if bp: BSIG[sg] = bp[0]
        i = keys.index(a) if a in keys else -1
        pre, post = t['meta']['preBalances'], t['meta']['postBalances']
        d = (post[i] - pre[i]) / 1e9 if i >= 0 else 0.0; fee = t['meta']['fee'] / 1e9 if i == 0 else 0.0
        oth = [(keys[j], (post[j] - pre[j]) / 1e9) for j in range(len(keys)) if j != i and post[j] != pre[j]]
        if fee: rows.append((bt, sg, 'fee', '', fee, 'SOL'))
        v = d + fee
        if i < 0: pass                                                     # a only appears via its token account: no SOL leg
        elif v > 1e-9:
            src = min(oth, key=lambda x: x[1])[0] if oth else '?'; rows.append((bt, sg, 'in', src, v, 'SOL'))
        elif v < -1e-9:
            pos = [(k, x) for k, x in oth if x > 0]; tot = sum(x for _, x in pos)
            neg = -v + sum(-x for k, x in oth if x < 0 and not (k == keys[0] and -x <= t['meta']['fee'] / 1e9 + 1e-12))
            f = min(1.0, -v / neg) if neg > 0 else 1.0                  # share of the receivers paid by a (other senders in the same tx)
            for k, x in pos: rows.append((bt, sg, 'out', k, x * f, 'SOL'))
            if abs(-v - tot * f) > 1e-6: rows.append((bt, sg, 'unattr', '', -v - tot * f, 'SOL'))
        if i == 0:                                                         # a SIGNED: any other wallet gaining real SOL is a candidate (swap output to a 3rd wallet).
            booked = {r[3] for r in rows if r[1] == sg and r[2] == 'out' and r[4] >= DUST}   # 11-03: was only when a's SOL change was exactly 0 -> a 0.002 SOL rent
            rows += [(bt, sg, 'swapto', k, x, 'SOL') for k, x in oth if x > DUST and k not in booked]   # scaled 40.5k SOL of outputs to dust (6 wallets missed)
        tok = collections.defaultdict(float)                              # (owner, asset) -> delta
        for sgn, bl in ((-1, t['meta'].get('preTokenBalances') or []), (1, t['meta'].get('postTokenBalances') or [])):
            for b in bl:
                if b['mint'] in MINT and b.get('owner'): tok[(b['owner'], MINT[b['mint']])] += sgn * float(b['uiTokenAmount']['uiAmount'] or 0)
        for asset in {x for _, x in tok}:
            dt = tok.get((a, asset), 0); ot = [(o, x) for (o, x2), x in tok.items() if x2 == asset and o != a and abs(x) > 1e-9]
            if dt > 1e-9:
                ng = [(o, x) for o, x in ot if x < 0]
                rows.append((bt, sg, 'in', 'mint' if cctp and asset == 'USDC' else min(ng, key=lambda z: z[1])[0] if ng else 'mint', dt, asset))
            elif dt < -1e-9:
                ps = [(o, x) for o, x in ot if x > 0]; tp = sum(x for _, x in ps); tn = -dt + sum(-x for _, x in ot if x < 0)
                f = min(-dt / tn, -dt / tp) if tp > 0 else 0               # a's share when several owners send in one tx
                rows += [(bt, sg, 'out', o, x * f, asset) for o, x in ps]
                if -dt - tp * f > 1e-6: rows.append((bt, sg, 'out', 'burn', -dt - tp * f, asset))
            elif i == 0:
                rows += [(bt, sg, 'swapto', o, x, asset) for o, x in ot if x > TMIN[asset]]
    return rows

# ---- pass 1: discover the tree (BFS)
tree, mixed, external, rows, q, seen = [], {}, {}, {}, [ROOT] + list(SEEDS), {ROOT} | set(SEEDS); SWAP = set(a for a, (f, o) in PROBE.items() if o == TOKEN)
# FIX B (11-04): with END the data is fixed, so read() of queued wallets (+ probes of their receivers) runs ahead in 8 threads;
# the BFS below stays serial and makes every decision itself -> identical result (tested vs the 01:39 END-08:08 run: all fields equal).
PRE, PX = {}, ThreadPoolExecutor(int(os.environ.get('SOL_PREFETCH', '8')))   # 32 with the paid key
def _pre(c):
    R = read(c)
    for _, _, k, x, v, s in R:
        if k in ('out', 'swapto') and x not in ('mint', 'burn') and x not in EXITS and x not in PROTO and v >= TMIN[s]: probe(x)
    return R
def svc(a, R):                                                           # service test; 'known' grows during the walk
    recv, rtok = collections.defaultdict(float), set()                   # SOL receivers (may become external) / token + swap-output receivers (join or ignore)
    for _, _, k, c, v, s in R:
        if k == 'out' and s == 'SOL' and v >= DUST: recv[c] += v
        elif k in ('out', 'swapto') and v >= TMIN[s] and c not in ('mint', 'burn'): rtok.add(c)
    rtok -= set(recv)
    known = set(tree) | seen | set(recv) | rtok
    tin = sum(v for _, _, k, c, v, s in R if k == 'in' and s == 'SOL' and c in known)
    ttin = any(k == 'in' and s != 'SOL' and c in known for _, _, k, c, v, s in R)    # got tokens from the tree (lend receipt / USDC)
    # SOL a got in its OWN tx (swap, lend redeem) or from a vault/pool is not foreign (11-03: jlWSOL redeemers read as services, 26,975 SOL unfollowed)
    foreign = sum(v for _, sg, k, c, v, s in R if k == 'in' and s == 'SOL' and c not in known and c not in POR and c not in EXITS
                  and c not in PROTO and c not in SWAP and SIGNER.get(sg) not in known and SIGNER.get(sg) != a)
    flag = a != ROOT and a not in SEEDS and (foreign > 10 and foreign > tin and not ttin or len(recv) + len(rtok) > 300)
    return flag, foreign, tin, recv, rtok
# FIX 1 (11-04): a 'SERVICE?' verdict made mid-walk depends on reading order (a tree sender not yet discovered counts as foreign;
# B5ho8kam / FoRNTjJm / 9aB9pNRB were dropped that way). Verdicts are now provisional: when the queue empties, every deferred wallet
# is re-judged against the FINAL tree; those that pass are re-queued and walked; repeat until nothing changes. Order-independent.
deferred, rounds = {}, 0
while True:
  while q:
    if END:
        for c in q[:int(os.environ.get('SOL_LOOKAHEAD', '64'))]:
            if c not in PRE and c not in rows: PRE[c] = PX.submit(_pre, c)
    a = q.pop(0); R = PRE.pop(a).result() if a in PRE else rows[a] if a in rows else read(a); rows[a] = R
    flag, foreign, tin, recv, rtok = svc(a, R)
    if flag:
        mixed[a] = round(foreign, 4); deferred[a] = 1
        print(f'  SERVICE? {a} foreign in {foreign:,.2f} vs tree in {tin:,.2f}, {len(recv) + len(rtok)} receivers -> deferred', flush=True); continue
    tree.append(a)
    for c in list(recv) + list(rtok):
        if c in seen or c in EXITS or c in PROTO: continue
        seen.add(c); fs, ow = probe(c)
        if ow == TOKEN: SWAP.add(c); continue
        if ow == SYS and (fs is None or (fs and fs >= SINCE)): q.append(c)   # None = no history seen, yet it received from a tree tx in-window -> fresh
        elif c in recv: external[c] = {'first_seen': time.strftime('%F', time.gmtime(fs)) if fs else None, 'owner': ow}
    print(f'  read {a[:8]}: {len(R)} flows, tree {len(tree)}, queue {len(q)}', flush=True)
  rounds += 1
  back = [a for a in deferred if not svc(a, rows[a])[0]]
  if not back: break
  for a in back:
    del deferred[a]; mixed.pop(a, None); q.append(a)
    print(f'  RE-JUDGED {a}: passes against the final tree (round {rounds}) -> followed', flush=True)
print(f'  pass 1 done: {len(tree)} tree wallets, {len(mixed)} services/mixed not followed, {rounds} round(s)', flush=True)

# ---- pass 2: classify with the final tree
T = set(tree); W = {}; ex_tot = collections.defaultdict(float); relay_users = collections.defaultdict(list)
EDGES = []                                           # tx-level edges for Eagle Eye: [sig, t, from, to, SOL, cls]; tree->tree booked once (sender side)
EDGES_TOK = []                                       # token edges: [sig, t, from, to, amount, asset, cls] (Eagle Eye does not read these yet)
TOK = collections.defaultdict(lambda: collections.defaultdict(float))  # asset -> class -> total (tree-external flows only)
SWAPS = collections.defaultdict(lambda: [collections.defaultdict(float), collections.defaultdict(float), 0])  # sig -> [gave, got, t]
SWAPOUT, SWAPOUT_N = collections.defaultdict(lambda: collections.defaultdict(float)), collections.defaultdict(set)   # unfollowed swap-output receiver -> asset -> amount
def tok_held(a):
    return {s: sum(x['account']['data']['parsed']['info']['tokenAmount']['uiAmount'] or 0
                   for x in rpc('getTokenAccountsByOwner', [a, {'mint': m}, {'encoding': 'jsonParsed'}])['value']) for m, s in MINT.items()}
raw_unexp = lambda R, h: sum(v if k == 'in' else -v for _, _, k, _, v, s in R if s == 'SOL' and k != 'swapto') - h
HELD = {}                                                            # 11-03: SOL balances 100 per call (was one getBalance per wallet)
if END: HELD = {a: at_end_sol(a) for a in tree}                       # 11-04: snapshot at END, not live
else:
  for i in range(0, len(tree), 100):
    for a, x in zip(tree[i:i + 100], rpc('getMultipleAccounts', [tree[i:i + 100], {'encoding': 'base64', 'dataSlice': {'offset': 0, 'length': 0}}])['value']):
        HELD[a] = (x or {}).get('lamports', 0) / 1e9                    # closed account = 0, same as getBalance
for a in tree:
    held = HELD[a]
    if not END and abs(raw_unexp(rows[a], held)) > 1e-3:                 # live wallet moved after pass 1 read it -> re-read once, then balance
        rows[a] = read(a); held = rpc('getBalance', [a])['value'] / 1e9
    L = collections.defaultdict(float); LT = collections.defaultdict(lambda: collections.defaultdict(float))
    legs = collections.defaultdict(set)                                  # sig -> {(dir, asset)} of a, to spot same-tx swaps
    for t, sig, k, c, v, s in rows[a]:
        if k in ('in', 'out', 'swapto'): legs[sig].add(('in' if k == 'swapto' else k, s))   # swapto: a's swap paid out elsewhere = still a swap
    for t, sig, k, c, v, s in rows[a]:
        if k == 'swapto':                                                # not a's money; edge only (receiver books it as 'in: swap output')
            if c in T: EDGES_TOK.append([sig, t, a, c, round(v, 9), s, 'swap output to tree wallet'])
            elif c not in EXITS and (PROBE.get(c) or [0, ''])[1] == SYS: SWAPOUT[c][s] += v; SWAPOUT_N[c].add(sig)   # 11-05: unfollowed wallet got the output (busy hub 5jahCqsA $3.83M was invisible)
            continue
        if k == 'fee': L['fees'] += v; continue
        if k == 'unattr': L['unattributed'] += v; continue
        swap = any(d != k and x != s for d, x in legs[sig])              # a gave one asset and got another in this tx
        theirs = SIGNER.get(sig) in T and SIGNER.get(sig) != a and c not in T   # another tree wallet's swap paid a
        if k == 'in':
            key = ('in: stolen' if c in POR else 'in: tree' if c in T else ('in: withdrawal ' if 'mixer' in EXITS[c] else 'in: refund ') + EXITS[c] if c in EXITS else
                   ('in: CCTP mint (dYdX return)' if a in SEEDS else 'in: CCTP mint') if c == 'mint' and s == 'USDC' else 'in: lend receipt' if c == 'mint' else 'in: redeem ' + PROTO[c] if c in PROTO else
                   'in: swap output (tree tx)' if theirs else 'in: swap (DEX)' if swap or c in SWAP else 'in: foreign')
        elif c in T: key = 'out: tree'
        elif c in EXITS:
            key = 'exit: ' + EXITS[c]
            if EXITS[c].startswith('Relay') and s == 'SOL': relay_users[a].append(sig)
        elif sig in BSIG and c != 'burn': key = 'exit: ' + BSIG[sig]
        elif c == 'burn': key = 'out: lend redeem (burn)' if s == 'jlWSOL' else 'out: burned'
        elif c in PROTO: key = 'out: deposit ' + PROTO[c]
        elif c in mixed: key = 'exit: mixed/service ' + c[:8]
        elif swap or c in SWAP: key = 'out: swap (DEX)'
        elif v < TMIN[s]: key = 'rent/dust'
        else: key = 'out: external ' + c[:8]
        if key.startswith(('in: swap', 'out: swap', 'in: lend', 'out: lend', 'out: deposit', 'in: redeem')):
            SWAPS[sig][1 if k == 'in' else 0][s] += v; SWAPS[sig][2] = t
        if s == 'SOL':
            L[key] += v
            if key != 'rent/dust' and (k == 'out' or (key != 'in: tree' and v >= DUST)): EDGES.append([sig, t, c, a, round(v, 9), key[4:]] if k == 'in' else [sig, t, a, c, round(v, 9), key])
        else:
            LT[s][key] += v
            if key != 'rent/dust' and (k == 'out' or key != 'in: tree'): EDGES_TOK.append([sig, t, c, a, round(v, 9), s, key] if k == 'in' else [sig, t, a, c, round(v, 9), s, key])
    srcs = sum(v for k, v in L.items() if k.startswith('in'))
    uses = sum(v for k, v in L.items() if not k.startswith('in'))
    fx = L.get('in: foreign', 0); flag = a != ROOT and fx > 1 and fx > 0.01 * L.get('in: tree', 0)
    W[a] = {'flows': {k: round(v, 9) for k, v in L.items()}, 'held': held, 'unexplained': round(srcs - uses - held, 9), 'mixed': flag}
    if LT:                                                               # per-asset conservation, native units
        th = at_end_tok(a) if END else tok_held(a); W[a]['tok'] = {}
        for s, fl in LT.items():
            un = sum(v for k, v in fl.items() if k.startswith('in')) - sum(v for k, v in fl.items() if not k.startswith('in')) - th[s]
            W[a]['tok'][s] = {'flows': {k: round(v, 6) for k, v in fl.items()}, 'held': th[s], 'unexplained': round(un, 6)}
            for k, v in fl.items():
                if not k.startswith(('in: tree', 'out: tree')): TOK[s][k] += v
            TOK[s]['held'] += th[s]; TOK[s]['unexplained'] += un
    if flag: print(f'  MIXED flag {a}: foreign in {fx:,.2f} vs tree in {L.get("in: tree", 0):,.2f}', flush=True)
    for k, v in L.items():
        if not k.startswith(('in: tree', 'out: tree')): ex_tot[k] += v

# ---- Relay: resolve solver deposits
# 11-04 (user): bridge deposits -> destinations are resolved ON DISCOVERY, in the background, by the shared resolver ~/cases/_bridges
# (Relay / Chainflip / Layerswap; one cache for every case). The ledger waits at most SOL_BRIDGE_WAIT s (default 60); leftovers are
# picked up by the next run. Balances never depend on it.
import sol_bridge_resolve as SBR
_bq = SBR.enqueue_from_edges(EDGES); print(f'  bridges: queued {dict(_bq)} new lookups', flush=True)
SBR.BR.wait(float(os.environ.get('SOL_BRIDGE_WAIT', '60')))
RC = SBR.BR.path('relay'); cache = SBR.BR.load('relay')
need = [u for u, ss in relay_users.items() if any(s not in cache for s in ss)]
if os.environ.get('SOL_RELAY') == 'cache': need = []          # 11-04: Relay 429s must not block the ledger; balances don't depend on it -> resolve later
for u in need:
    cont = None
    while True:
        url = f'https://api.relay.link/requests/v2?user={u}&limit=50' + (f'&continuation={cont}' if cont else '')
        for k in range(6):
            try: r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)); break
            except urllib.error.HTTPError as e:
                if e.code != 429: raise
                time.sleep(60 * (k + 1))
        for rq in r.get('requests') or []:
            for it in rq.get('data', {}).get('inTxs') or []: cache[it.get('hash')] = rq
        cont = r.get('continuation'); time.sleep(6)
        if not cont: break
    SBR.BR.save('relay', cache)
relay = collections.defaultdict(lambda: [0, 0.0, set()]); unres = 0
for u, ss in relay_users.items():
    for s in ss:
        rq = cache.get(s)
        if not rq: unres += 1; continue
        m = rq['data'].get('metadata', {}).get('currencyOut', {}); out = rq['data'].get('outTxs') or [{}]
        key = (rq.get('status'), out[0].get('chainId'), rq.get('recipient'), (m.get('currency') or {}).get('symbol'))
        relay[key][0] += 1; relay[key][1] += float(m.get('amountFormatted') or 0); relay[key][2].update(o.get('hash') for o in out if o.get('hash'))

# ---- report + save (page reads sources / uses / live_balance / unexplained)
held = sum(w['held'] for w in W.values()); unexp = sum(w['unexplained'] for w in W.values())
sources = {k[4:]: v for k, v in ex_tot.items() if k.startswith('in: ')}; sources['stolen (Binance PoR)'] = sources.pop('stolen', 0)
uses = {k: v for k, v in ex_tot.items() if not k.startswith('in')}; uses['held'] = held
now = time.strftime('%FT%TZ', time.gmtime(END)) if END else time.strftime('%FT%TZ', time.gmtime())   # 'at' = the moment the ledger describes
out = {'leg': 'sol', 'at': now, 'kind': 'tree', 'root': ROOT, 'sources': sources, 'uses': uses, 'live_balance': held, 'unexplained': unexp,
       'window': {'since': time.strftime('%FT%TZ', time.gmtime(SINCE)), 'end': now if END else None, 'held_is': 'balance at END' if END else 'live',
                  'run_started': RUN_STARTED, 'run_finished': time.strftime('%FT%TZ', time.gmtime())},
       'wallets': W, 'mixed': mixed, 'external': external, 'edges': EDGES,
       'first_seen': {a: min((t for t, *_ in rows[a]), default=0) for a in tree},
       'relay': [{'status': k[0], 'chain': k[1], 'recipient': k[2], 'currency': k[3], 'n': v[0], 'amount_out': v[1], 'out_txs': sorted(v[2])} for k, v in relay.items()],
       'relay_unresolved': unres, 'bridges': SBR.destinations(EDGES),
       'tokens': {s: {k: round(v, 6) for k, v in d.items()} for s, d in TOK.items()}, 'edges_tok': EDGES_TOK, 'swaps': {}}
pair = collections.defaultdict(lambda: [collections.defaultdict(float), collections.defaultdict(float), 0])   # 'SOL -> USDC' -> totals, n
for sig, (gave, got, t) in SWAPS.items():
    if not gave and not got: continue
    k = '+'.join(sorted(gave)) + ' -> ' + '+'.join(sorted(got)); p = pair[k]; p[2] += 1
    for s, v in gave.items(): p[0][s] += v
    for s, v in got.items(): p[1][s] += v
out['swaps'] = {k: {'gave': dict(v[0]), 'got': dict(v[1]), 'n': v[2]} for k, v in pair.items()}
out['swap_out_outside'] = {c: {'assets': {s: round(v, 6) for s, v in d.items()}, 'txs': len(SWAPOUT_N[c]), 'first_seen': (PROBE.get(c) or [None])[0],
                               'why_unfollowed': 'busy hub (>5,000 txs since hack)' if (PROBE.get(c) or [None])[0] == 0 else 'aged / not fresh'} for c, d in SWAPOUT.items()}
if not os.path.exists('raw/sol_ledger_20261030.json'): shutil.copy('raw/sol_ledger.json', 'raw/sol_ledger_20261030.json')
json.dump(out, open(os.environ.get('SOL_OUT', 'raw/sol_ledger.json'), 'w'), indent=1);   # SOL_OUT=raw/sol_ledger_next.json keeps Eagle Eye pinned (11-03)
json.dump(out, open(f'raw/sol/ledger_{now[:16].replace(":", "")}' + (f'_END_run{out["window"]["run_finished"][:16].replace(":", "")}' if END else '') + '.json', 'w'), indent=1)   # END runs never overwrite a live archive
print(f'\n=== SOL TREE LEDGER as of {now} ({"fixed END" if END else "live"}; run {RUN_STARTED} -> {out["window"]["run_finished"]}): {len(tree)} wallets, {len(mixed)} mixed (not followed), {len(external)} external receivers')
print('  sources:', {k: round(v, 4) for k, v in sources.items()})
print('  uses   :', {k: round(v, 4) for k, v in sorted(uses.items(), key=lambda x: -x[1])})
print(f'  HELD {held:,.4f} SOL | UNEXPLAINED {unexp:,.6f} SOL')
for s, d in TOK.items():
    print(f'  {s}: held {d["held"]:,.4f} | unexplained {d["unexplained"]:,.6f} |', {k: round(v, 2) for k, v in sorted(d.items(), key=lambda x: -x[1]) if k not in ('held', 'unexplained')})
print('  CONVERSIONS (same-tx, native units; gave includes slippage/fees):')
for k, v in sorted(out['swaps'].items(), key=lambda x: -x[1]['n']):
    print(f"   {k:28} x{v['n']:>4}  gave " + ', '.join(f'{x:,.4f} {s}' for s, x in v['gave'].items()) + '  got ' + ', '.join(f'{x:,.4f} {s}' for s, x in v['got'].items()))
for a, w in W.items():
    for s, x in (w.get('tok') or {}).items():
        if abs(x['unexplained']) > 0.01: print(f'   ! unexplained {x["unexplained"]:,.6f} {s} at {a}')
for a, w in sorted(W.items(), key=lambda x: -x[1]['held'])[:8]: print(f'   held {w["held"]:>14,.4f}  {a}')
for a, w in W.items():
    if abs(w['unexplained']) > 1e-4: print(f'   ! unexplained {w["unexplained"]:,.6f} at {a}')
print(f'  RELAY: {sum(len(s) for s in relay_users.values())} deposits from {len(relay_users)} wallets, unresolved {unres}')
for k, v in sorted(relay.items(), key=lambda x: -x[1][1]): print(f'   {k[0]} chain {k[1]} -> {k[2]}  {v[1]:,.8f} {k[3]} ({v[0]} req)')
for c, x in external.items(): print(f'  external {c} first {x["first_seen"]} owner {x["owner"][:10]}')
for c, x in sorted(out['swap_out_outside'].items(), key=lambda z: -sum(v for k, v in z[1]['assets'].items() if k != 'SOL'))[:15]:
    print(f"  SWAP OUTPUT TO UNFOLLOWED {c} {x['txs']} txs {x['assets']} ({x['why_unfollowed']})")
