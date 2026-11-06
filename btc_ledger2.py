"""BTC ledger v2 (11-05): the same bookkeeping as btc_ledger.py with three principle fixes and a node data path.
  BTC2_DB=<path> [BTC_TIP=<height>] [BTC2_SEEDS_RUN=<bridged run id>] python3 btc_ledger2.py run|bridged|show [run]|bshow [run]
RULE (to the satoshi, at one pinned tip): sats in (roots) = unspent at the attacker + exits + the attacker share sent into MIXED/CoinJoin
txs + fees of attacker-signed txs.
FIX 1 — ownership by OUTPOINT: an input is the attacker's only if that exact coin is an attacker coin of this run. Any other input, even at
  an address the attacker used, is FOREIGN → the tx is MIXED (stop). Nothing becomes a new source ('untracked-in' is gone); foreign coins at
  attacker addresses are printed as LEADS (a bridge payout we lack, or a service address).
FIX 2 — bridged roots = the bridge's exact payout txids (seed payout_txids) → their outputs to the seed address. Seeds without a payout txid
  fall back to the address history after HACK_TS and are booked 'bridged-byaddr' so they show apart.
FIX 3 — btx keyed by (run_id, txid) (the old table is keyed by txid → a later run overwrote earlier runs' tx rows).
DATA: tx bodies + 'still unspent?' from QuickNode BTC in batches of 50 (getrawtransaction v2 carries prevouts; gettxout); Esplora only for
'spent by whom' (/tx/{id}/outspends = every vout in one call), address tx counts (hub stop) and fallback address pages.
Writes ONLY to BTC2_DB (refuses the production BTC DBs). Every API reply is stored (raw_payload)."""
import json, os, re, sys, time, sqlite3, gzip, socket, threading, importlib.util, urllib.request, urllib.error
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
PROD = {os.path.realpath(os.path.join(HERE, f)) for f in ('binance-btc-ledger.db', 'binance-btc-bridged-ledger.db')}
HACK_TS = 1793304000; MAX_PAGES = 20
HOT = 'bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h'; COLLECT = 'bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm'
HUB_TX = int(os.environ.get('BTC_HUB_TX', 1000))
_gai = socket.getaddrinfo                                     # mempool.space IPv4 is blackholed here → IPv6 for it only
socket.getaddrinfo = lambda h, *a, **k: ([r for r in _gai(h, *a, **k) if r[0] == socket.AF_INET6] or _gai(h, *a, **k)) if 'mempool.space' in str(h) else _gai(h, *a, **k)
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"').strip("'") for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l and not l.startswith('#')}
QB = (E['QUICKNODE_BTC_URL'].rstrip('/') + '/' + E['QUICKNODE_BTC_TOKEN'].strip() + '/') if E.get('QUICKNODE_BTC_URL') and E.get('QUICKNODE_BTC_TOKEN') else None   # never print
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB);
CREATE INDEX IF NOT EXISTS raw_payload_url ON raw_payload(url);
CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, started TEXT, finished TEXT, tip INTEGER, params TEXT);
CREATE TABLE IF NOT EXISTS utxo(run_id TEXT, txid TEXT, vout INTEGER, address TEXT, sats INTEGER, owner TEXT, status TEXT,
  spent_by TEXT, spent_height INTEGER, note TEXT, PRIMARY KEY(run_id, txid, vout));
CREATE TABLE IF NOT EXISTS btx(run_id TEXT, txid TEXT, height INTEGER, ts INTEGER, fee INTEGER, n_in INTEGER, n_out INTEGER,
  attacker_in INTEGER, foreign_in INTEGER, kind TEXT, PRIMARY KEY(run_id, txid));
CREATE TABLE IF NOT EXISTS lead(run_id TEXT, txid TEXT, vin INTEGER, prev_txid TEXT, prev_vout INTEGER, address TEXT, sats INTEGER, why TEXT);
"""
C = None; STATS = {'qn_calls': 0, 'qn_items': 0, 'esplora': 0, 'cache': 0}

# ---------- data: QuickNode (batched JSON-RPC) ----------
QN_RPS = float(os.environ.get('BTC2_QN_RPS', 45))     # QuickNode plan: 50 requests/s, every item of a batch counts
_qn_lock, _qn_next = threading.Lock(), [0.0]
def qn_slot(n):
    with _qn_lock: t = max(time.time(), _qn_next[0]); _qn_next[0] = t + n / QN_RPS
    time.sleep(max(0, t - time.time()))
def qn(calls):
    """[(method, params)] → results in order (None = null result or 'not found' -5). Fails loudly on anything else."""
    out = [None] * len(calls)
    def batch(i0):
        part = calls[i0:i0 + 50]
        body = json.dumps([{"jsonrpc": "2.0", "id": j, "method": m, "params": p} for j, (m, p) in enumerate(part)]).encode()
        err = None
        for k in range(8):
            qn_slot(len(part))
            try:
                r = urllib.request.urlopen(urllib.request.Request(QB, body, {'Content-Type': 'application/json', 'Accept-Encoding': 'gzip'}), timeout=120)
                b = r.read(); b = gzip.decompress(b) if r.headers.get('Content-Encoding') == 'gzip' else b
                got = {x['id']: x for x in json.loads(b, parse_float=Decimal) if isinstance(x, dict) and 'id' in x}
                bad = [x['error'] for x in got.values() if x.get('error') and x['error'].get('code') != -5]
                if len(got) == len(part) and not bad:
                    STATS['qn_calls'] += 1; STATS['qn_items'] += len(part)
                    for j in range(len(part)): out[i0 + j] = got[j].get('result')
                    return
                err = bad[:1] or f'{len(got)}/{len(part)} replies'
            except Exception as e: err = e
            time.sleep(2 * (k + 1))
        raise RuntimeError(f'QuickNode batch failed: {err}')
    with ThreadPoolExecutor(3) as ex: list(ex.map(batch, range(0, len(calls), 50)))
    return out

def sats(d): return int((Decimal(str(d)) * 100000000).to_integral_value())
HEIGHT = {}
def esp_shape(t):
    """QuickNode verbose-2 tx → Esplora-shaped dict in satoshis (what label/CoinJoin code and the old ledger read)."""
    vin = []
    for v in t['vin']:
        if 'coinbase' in v: vin.append({'is_coinbase': True, 'txid': None, 'vout': None, 'prevout': {}}); continue
        po = v['prevout']; spk = po['scriptPubKey']
        vin.append({'txid': v['txid'], 'vout': v['vout'], 'prevout': {'scriptpubkey_address': spk.get('address'), 'scriptpubkey_type': spk.get('type'), 'value': sats(po['value'])}})
    vout = [{'scriptpubkey_address': o['scriptPubKey'].get('address'), 'scriptpubkey_type': o['scriptPubKey'].get('type'), 'value': sats(o['value'])} for o in t['vout']]
    fee = 0 if any(v.get('is_coinbase') for v in vin) else sum(v['prevout']['value'] for v in vin) - sum(o['value'] for o in vout)
    if t.get('fee') is not None: assert fee == sats(t['fee']), f"fee mismatch {t['txid']}"
    return {'txid': t['txid'], 'vin': vin, 'vout': vout, 'fee': fee,
            'status': {'confirmed': bool(t.get('blockhash')), 'block_height': HEIGHT.get(t.get('blockhash')), 'block_time': t.get('blocktime')}}

TXS = {}
def txs(ids):
    """tx bodies (cache: this DB's raw_payload, then QuickNode in batches); block heights from getblockheader by blockhash (exact)."""
    need = []
    for t in dict.fromkeys(ids):
        if t in TXS: continue
        r = C.execute("SELECT body FROM raw_payload WHERE url=? ORDER BY id DESC LIMIT 1", ('qn:tx/' + t,)).fetchone()
        if r: TXS[t] = json.loads(gzip.decompress(r[0]), parse_float=Decimal); STATS['cache'] += 1
        else: need.append(t)
    if need:
        for t, res in zip(need, qn([('getrawtransaction', [t, 2]) for t in need])):
            if res is None: raise RuntimeError(f'QuickNode has no tx {t}')
            res.pop('hex', None)
            if not res.get('blockhash'): TXS[t] = res; continue                               # mempool: never cached
            C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), 'qn:tx/' + t, gzip.compress(json.dumps(res, default=str).encode())))
            TXS[t] = res
    hs = sorted({TXS[t].get('blockhash') for t in ids if TXS[t].get('blockhash')} - set(HEIGHT))
    for h, res in zip(hs, qn([('getblockheader', [h, True]) for h in hs])): HEIGHT[h] = res['height']
    C.commit()
    return {t: esp_shape(TXS[t]) for t in ids}

def unspent_now(coins):
    """gettxout(include_mempool) not null → the coin is unspent NOW, so also at the (earlier) pinned tip."""
    return {c for c, r in zip(coins, qn([('gettxout', [t, v, True]) for t, v in coins])) if r is not None}

# ---------- data: Esplora (spent-by-whom, address stats, fallback pages) ----------
class Host:
    def __init__(s, base, qps): s.base, s.dt, s.lock, s.next, s.cool = base, 1 / qps, threading.Lock(), 0.0, 0.0
    def slot(s):
        with s.lock: t = max(time.time(), s.next, s.cool); s.next = t + s.dt
        time.sleep(max(0, t - time.time()))
HOSTS = [Host('https://mempool.space/api', float(os.environ.get('BTC2_MEMPOOL_QPS', 3))), Host('https://blockstream.info/api', float(os.environ.get('BTC2_BSTREAM_QPS', 1)))]
_rr = [0]; _rl = threading.Lock()
def esplora(path, host=None):
    for i in range(30):
        with _rl: h = host or HOSTS[_rr[0] % len(HOSTS)]; _rr[0] += 1
        if host is None and h.cool > time.time() and any(x.cool <= time.time() for x in HOSTS): continue
        h.slot()
        try:
            b = urllib.request.urlopen(urllib.request.Request(h.base + path, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read()
            STATS['esplora'] += 1; return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503): h.cool = time.time() + 60; continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(2 + i % 4)
    raise RuntimeError('esplora failed ' + path)
def esplora_many(paths):
    with ThreadPoolExecutor(4) as ex: res = dict(zip(paths, ex.map(esplora, paths)))
    for p, j in res.items(): C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), p, gzip.compress(json.dumps(j).encode())))
    C.commit(); return res

HUB = {}
def hubs(addrs):
    """address total tx count > HUB_TX → unlabelled service/hub (an exit, never attacker)."""
    todo = sorted(set(a for a in addrs if a and a not in HUB))
    for p, st in esplora_many([f'/address/{a}' for a in todo]).items():
        n = (st.get('chain_stats') or {}).get('tx_count', 0) + (st.get('mempool_stats') or {}).get('tx_count', 0)
        HUB[p.split('/')[-1]] = n if n > HUB_TX else None

DISAGREE = []
def addr_pages(a):
    """network only (safe in a worker thread); the caller stores the replies via keep_pages().
    One address = one host per walk (a cursor across hosts skipped mid-history pages: 4 roots at bc1qdrj6cs, 11-05), and the walk is done on
    BOTH hosts and merged by txid (a lagging host index served stale pages on 11-04). Disagreements are reported."""
    walks, raw, n = [], [], 0
    for h in HOSTS:
        txl, last, k = [], None, 0
        while k < MAX_PAGES:
            path = f'/address/{a}/txs' + (f'/chain/{last}' if last else '')
            page = esplora(path, h); k += 1; raw.append((path + '@' + h.base.split('/')[2], page))
            if not page: break
            txl += page; last = page[-1]['txid']
            if len(page) < 25 or (page[-1]['status'].get('block_time') or 1e12) < HACK_TS: break
        walks.append(txl); n = max(n, k)
    ids = [{t['txid'] for t in w} for w in walks]
    if ids[0] != ids[1]: DISAGREE.append((a, len(ids[0] - ids[1]), len(ids[1] - ids[0])))
    merged = {t['txid']: t for w in walks for t in w if t['status'].get('confirmed')}
    return list(merged.values()), n, raw
def keep_pages(raw):
    for p, j in raw: C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), p, gzip.compress(json.dumps(j).encode())))
    C.commit()

# ---------- labels, CoinJoin (the engine's own rules, imported — no copy) ----------
_cj = importlib.util.spec_from_file_location('cjc', os.path.expanduser('~/traversal-engine/btc-engine/scripts/coinjoin-coordinators.py'))
CJ = importlib.util.module_from_spec(_cj); _cj.loader.exec_module(CJ); CJ_COORDS = CJ.load_coords()[0]
def coinjoin(t):
    typ, conf, anon = CJ.classify_tx(t)
    return f"{CJ_COORDS.get(t['txid'], 'coordinator unnamed')} ({conf}, anon set {anon})" if typ == 'coinjoin' else None
LB = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/labels.db') + '?mode=ro', uri=True)
POR = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db') + '?mode=ro', uri=True)
def label(a):
    if not a: return ''
    p = POR.execute('SELECT exchange, wallet_type FROM por_wallets WHERE address=?', (a,)).fetchone()
    if p: return f'cex:{p[0]}/{p[1]}'
    r = LB.execute('SELECT name FROM labels WHERE address=?', (a,)).fetchone()
    return f'label:{r[0][:40]}' if r else ''

# ---------- the ledger ----------
def run(bridged=False):
    global C
    dbp = os.environ.get('BTC2_DB') or sys.exit('set BTC2_DB=<path> (never a production DB)')
    if os.path.realpath(dbp) in PROD: sys.exit('refusing: BTC2_DB is a production BTC ledger DB')
    if not QB: sys.exit('QuickNode BTC env missing')
    t0 = time.time()
    C = sqlite3.connect(dbp, timeout=600); C.execute('PRAGMA journal_mode=WAL'); C.executescript(SCHEMA)
    tip = int(os.environ.get('BTC_TIP') or qn([('getblockcount', [])])[0])
    run_id = ('btcb2-' if bridged else 'btc2-') + time.strftime('%Y%m%dT%H%M%S')
    seeds = {}
    if bridged:
        sr = os.environ.get('BTC2_SEEDS_RUN')
        if sr: seeds = json.loads(sqlite3.connect(os.path.join(HERE, 'binance-btc-bridged-ledger.db')).execute('SELECT params FROM ledger_run WHERE run_id=?', (sr,)).fetchone()[0])['seeds']
        else: seeds = json.load(open(os.path.join(HERE, 'raw/btc_bridged_seeds.json')))
    C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?)', (run_id, time.strftime('%FT%T'), None, tip, json.dumps({'tool': 'btc_ledger2', 'seeds': seeds, 'seeds_run': os.environ.get('BTC2_SEEDS_RUN')} if bridged else {'tool': 'btc_ledger2', 'hot': HOT, 'collect': COLLECT}))); C.commit()
    print(f'{run_id}: pinned at tip {tip} → {dbp}', flush=True)
    ATT = set()                                                     # attacker coins (txid, vout) — THE ownership test
    def put(txid, vout, addr, s, owner, status, note):
        C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, txid, vout, addr, s, owner, status, None, None, note))
        if owner == 'attacker': ATT.add((txid, vout))
    def btx(t, kind, a_in, f_in):
        C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status']['block_height'], t['status']['block_time'], t['fee'], len(t['vin']), len(t['vout']), a_in, f_in, kind))
    # ---- roots
    if bridged:
        exact = {}                                                   # payout txid → every seed it pays (one bridge tx can pay several seeds)
        for a, sd in seeds.items():
            for t in sd.get('payout_txids') or []: exact.setdefault(t, set()).add(a)
        body = txs(list(exact))
        miss = []
        for t, addrs in exact.items():
            b = body[t]
            if not b['status']['confirmed'] or b['status']['block_height'] > tip: continue
            for a in sorted(addrs):
                outs = [(i, o) for i, o in enumerate(b['vout']) if o['scriptpubkey_address'] == a]
                if not outs: miss.append((t, a))
                for i, o in outs:
                    sd = seeds[a]; put(t, i, a, o['value'], 'attacker', 'pending', f"bridged:{'+'.join(sd['origin'])}:{'+'.join(sd['via'])}")
            btx(b, 'bridge payout (service-signed)', 0, len(b['vin']))
        if miss: print(f'  ⚠ {len(miss)} payout txids pay nothing to their seed address: {miss[:5]}', flush=True)
        byaddr = [a for a, sd in seeds.items() if not sd.get('payout_txids')]
        with ThreadPoolExecutor(3) as ex: pages = dict(zip(byaddr, ex.map(addr_pages, byaddr)))
        for a in byaddr:
            pl, n, raw = pages[a]; keep_pages(raw)
            if n >= MAX_PAGES: print(f'  BUSY {a}: stopped at {MAX_PAGES} pages, check by hand', flush=True)
            for t in pl:
                if not t['status'].get('confirmed') or t['status']['block_height'] > tip or t['status']['block_time'] < HACK_TS: continue
                if any(v['prevout']['scriptpubkey_address'] in seeds for v in t['vin']): continue      # seed→seed: reached by the follow
                for i, o in enumerate(t['vout']):
                    if o.get('scriptpubkey_address') == a:
                        sd = seeds[a]; put(t['txid'], i, a, o['value'], 'attacker', 'pending', f"bridged-byaddr:{'+'.join(sd['origin'])}:{'+'.join(sd['via'])}")
                C.execute('INSERT OR IGNORE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status']['block_height'], t['status']['block_time'], t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'bridge payout (service-signed)'))
        C.commit()
        if DISAGREE: print(f'  hosts disagreed on {len(DISAGREE)} address histories (merged): {DISAGREE[:6]}', flush=True)
        g = C.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note LIKE 'bridged%'", (run_id,)).fetchone()
        print(f'roots: {(g[0] or 0)/1e8:,.8f} BTC in {g[1]} payouts · exact txids {len(exact)} · by-address seeds {len(byaddr)}  [{time.time()-t0:.0f}s]', flush=True)
    else:
        pl, _, raw = addr_pages(COLLECT); keep_pages(raw); drained = 0
        for t in pl:
            if not t['status'].get('confirmed') or t['status']['block_height'] > tip: continue
            if any(v['prevout']['scriptpubkey_address'] == HOT for v in t['vin']):
                for i, o in enumerate(t['vout']):
                    if o.get('scriptpubkey_address') == COLLECT: drained += o['value']; put(t['txid'], i, COLLECT, o['value'], 'attacker', 'pending', 'drain')
                C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status']['block_height'], t['status']['block_time'], t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'drain (victim-signed)'))
        C.commit(); print(f'drain: {drained/1e8:,.8f} BTC', flush=True)
    # ---- follow
    seen, att_addr = set(), set(a for (a,) in C.execute("SELECT DISTINCT address FROM utxo WHERE run_id=? AND owner='attacker'", (run_id,)))
    def outputs(t, signed):
        """book every output of a decided tx. signed=True: attacker-signed → exit (label / hub) or attacker; else unattributed."""
        if signed: hubs([o['scriptpubkey_address'] for o in t['vout'] if o['scriptpubkey_address'] and o['scriptpubkey_address'] not in att_addr and not label(o['scriptpubkey_address'])])
        for i, o in enumerate(t['vout']):
            ad = o['scriptpubkey_address'] or o['scriptpubkey_type']; lb = label(o['scriptpubkey_address'])
            if not signed: own, nt = 'unattributed (mixed tx)', lb
            elif lb: own, nt = 'exit', lb
            elif o['scriptpubkey_address'] and o['scriptpubkey_address'] not in att_addr and HUB.get(o['scriptpubkey_address']): own, nt = 'exit', f"hub/service (unlabelled, {HUB[o['scriptpubkey_address']]:,} txs)"
            elif not o['scriptpubkey_address']: own, nt = 'exit', f"non-address output ({o['scriptpubkey_type']})"
            else: own, nt = 'attacker', ''; att_addr.add(ad)
            ex = C.execute('SELECT owner FROM utxo WHERE run_id=? AND txid=? AND vout=?', (run_id, t['txid'], i)).fetchone()
            if ex and ex[0].startswith('unattributed') and signed:                                  # promotion of a re-checked MIXED tx
                C.execute("UPDATE utxo SET owner=?, status=?, note=? WHERE run_id=? AND txid=? AND vout=?", (own, 'pending' if own == 'attacker' else 'n/a', nt, run_id, t['txid'], i))
                if own == 'attacker': ATT.add((t['txid'], i))
            else: put(t['txid'], i, ad, o['value'], own, 'pending' if own == 'attacker' else 'n/a', nt)
    def decide(t):
        a_in = sum(1 for v in t['vin'] if (v['txid'], v['vout']) in ATT); f_in = len(t['vin']) - a_in
        if f_in == 0: btx(t, 'attacker-signed', a_in, 0); outputs(t, True); return
        cj = coinjoin(t)
        btx(t, f'MIXED (CoinJoin: {cj})' if cj else 'MIXED (foreign inputs)', a_in, f_in)
        for j, v in enumerate(t['vin']):                                                          # LEADS: foreign coins at attacker addresses
            if (v['txid'], v['vout']) not in ATT and v['prevout'].get('scriptpubkey_address') in att_addr:
                C.execute('INSERT INTO lead VALUES(?,?,?,?,?,?,?,?)', (run_id, t['txid'], j, v['txid'], v['vout'], v['prevout']['scriptpubkey_address'], v['prevout']['value'], 'foreign coin at an attacker address'))
        outputs(t, False)
    def recheck():
        """a MIXED tx whose 'foreign' inputs are attacker coins found later (spender seen before producer) → attacker-signed."""
        n = 0
        mixed = [x for (x,) in C.execute("SELECT txid FROM btx WHERE run_id=? AND kind='MIXED (foreign inputs)'", (run_id,))]
        for st, t in txs(mixed).items():
            if all((v['txid'], v['vout']) in ATT for v in t['vin']):
                C.execute('DELETE FROM lead WHERE run_id=? AND txid=?', (run_id, st)); btx(t, 'attacker-signed', len(t['vin']), 0); outputs(t, True); n += 1
        C.commit(); return n
    wave = 0
    while True:
        pend = C.execute("SELECT txid, vout FROM utxo WHERE run_id=? AND owner='attacker' AND status='pending' ORDER BY rowid", (run_id,)).fetchall()
        if not pend:
            if recheck(): continue
            break
        wave += 1; tw = time.time()
        coins = [tuple(x) for x in pend]; still = unspent_now(coins)
        for t, v in still: C.execute("UPDATE utxo SET status='unspent' WHERE run_id=? AND txid=? AND vout=?", (run_id, t, v))
        spent = [c for c in coins if c not in still]
        OS = esplora_many(sorted({f'/tx/{t}/outspends' for t, _ in spent}))
        spenders = []
        for t, v in spent:
            o = OS[f'/tx/{t}/outspends'][v]
            if not o.get('spent'):                                                                # node says spent, host says not → stale host: ask the other
                for h in HOSTS:
                    j = esplora(f'/tx/{t}/outspend/{v}', h)
                    if j.get('spent'): o = j; break
            if not o.get('spent'):
                C.execute("UPDATE utxo SET status='CHECK: node spent, esplora unspent' WHERE run_id=? AND txid=? AND vout=?", (run_id, t, v)); continue
            sh = (o.get('status') or {}).get('block_height')
            if not (o.get('status') or {}).get('confirmed') or (sh and sh > tip):
                C.execute("UPDATE utxo SET status=?, spent_by=? WHERE run_id=? AND txid=? AND vout=?",
                          ('unspent (spend in mempool)' if not (o.get('status') or {}).get('confirmed') else 'unspent at tip (spent later)', o['txid'], run_id, t, v)); continue
            C.execute("UPDATE utxo SET status='spent', spent_by=?, spent_height=? WHERE run_id=? AND txid=? AND vout=?", (o['txid'], sh, run_id, t, v))
            if o['txid'] not in seen: seen.add(o['txid']); spenders.append(o['txid'])
        bodies = txs(spenders)
        hubs([o['scriptpubkey_address'] for t in bodies.values() if all((v['txid'], v['vout']) in ATT for v in t['vin'])   # hub counts for this wave in parallel
              for o in t['vout'] if o['scriptpubkey_address'] and o['scriptpubkey_address'] not in att_addr and not label(o['scriptpubkey_address'])])
        for st, t in bodies.items(): decide(t)                                                    # dict keeps spender order
        C.commit()
        print(f'  wave {wave}: {len(coins)} coins ({len(still)} unspent) · {len(spenders)} spends in {time.time()-tw:.0f}s · {STATS}', flush=True)
    C.execute('UPDATE ledger_run SET finished=? WHERE run_id=?', (time.strftime('%FT%T'), run_id)); C.commit()
    print(f'FINISHED in {time.time()-t0:.0f}s', flush=True)
    show(run_id, bridged, dbp)

def show(run_id=None, bridged=False, dbp=None):
    c = sqlite3.connect(dbp or os.environ['BTC2_DB'], timeout=600)
    run_id = run_id or c.execute('SELECT run_id FROM ledger_run ORDER BY started DESC LIMIT 1').fetchone()[0]
    tip = c.execute('SELECT tip FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0]
    q = lambda s, *a: c.execute(s, (run_id,) + a).fetchone()
    src = q("SELECT SUM(sats) FROM utxo WHERE run_id=? AND (note='drain' OR note LIKE 'bridged%')")[0] or 0
    uns = q("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='attacker' AND status LIKE 'unspent%'")
    exits = c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='exit' GROUP BY note ORDER BY 2 DESC", (run_id,)).fetchall()
    share = lambda k: q(f"SELECT SUM(u.sats), COUNT(DISTINCT b.txid) FROM utxo u JOIN btx b ON b.run_id=u.run_id AND b.txid=u.spent_by WHERE u.run_id=? AND u.owner='attacker' AND u.status='spent' AND b.kind LIKE '{k}'")
    cjs, mix = share('MIXED (CoinJoin%'), share('MIXED (foreign%')
    fees = q("SELECT SUM(fee) FROM btx WHERE run_id=? AND kind='attacker-signed'")[0] or 0
    pend = q("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='attacker' AND (status='pending' OR status LIKE 'CHECK%')")
    uses = (uns[0] or 0) + sum(s for _, s, _ in exits) + (cjs[0] or 0) + (mix[0] or 0) + fees
    print(f'\n=== {run_id} | pinned tip {tip} ===')
    for n, s, k in c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND (note='drain' OR note LIKE 'bridged%') GROUP BY note", (run_id,)):
        print(f'SOURCES  {n:44} {s/1e8:>18,.8f} BTC ({k})')
    if bridged:
        seeds = json.loads(q('SELECT params FROM ledger_run WHERE run_id=?')[0])['seeds']
        got = dict(c.execute("SELECT address, SUM(sats) FROM utxo WHERE run_id=? AND note LIKE 'bridged%' GROUP BY address", (run_id,)).fetchall())
        diff = [(a, sd['expected_btc'], got.get(a, 0) / 1e8, 'txid' if sd.get('payout_txids') else 'addr') for a, sd in seeds.items() if abs(got.get(a, 0) / 1e8 - sd['expected_btc']) > 1e-6]
        print(f'SEEDS    received vs bridge records: {len(seeds) - len(diff)}/{len(seeds)} exact · expected {sum(v["expected_btc"] for v in seeds.values()):,.8f}')
        for a, e, g, how in sorted(diff, key=lambda x: -abs(x[2] - x[1]))[:15]: print(f'         ≠ [{how}] {a} expected {e:.8f} got {g:.8f} ({g - e:+.8f})')
    print(f'USES     unspent at attacker ({uns[1]} UTXOs)          {(uns[0] or 0)/1e8:>18,.8f}')
    for n, s, k in exits: print(f'         exit {n[:44]:44} {s/1e8:>18,.8f} ({k})')
    print(f'         into CoinJoins ({cjs[1] or 0} txs)                 {(cjs[0] or 0)/1e8:>18,.8f}')
    print(f'         into other MIXED txs ({mix[1] or 0} txs)           {(mix[0] or 0)/1e8:>18,.8f}')
    print(f'         miner fees (attacker-signed txs)          {fees/1e8:>18,.8f}')
    print(f'UNEXPLAINED (sats) {src - uses}   · still pending/CHECK {pend[1]} coins ({(pend[0] or 0)/1e8:,.8f})')
    ld = c.execute("SELECT address, SUM(sats), COUNT(*) FROM lead WHERE run_id=? GROUP BY address ORDER BY 2 DESC", (run_id,)).fetchall()
    if ld:
        print(f'LEADS    foreign coins spent from attacker addresses (a bridge payout we lack, or a service address): {sum(x[1] for x in ld)/1e8:,.8f} BTC')
        for a, s, k in ld[:12]: print(f'         {a} {s/1e8:,.8f} ({k})')

if __name__ == '__main__':
    a = sys.argv[1:]
    {'run': lambda: run(False), 'bridged': lambda: run(True),
     'show': lambda: show(a[1] if len(a) > 1 else None, False), 'bshow': lambda: show(a[1] if len(a) > 1 else None, True)}[a[0]]()
