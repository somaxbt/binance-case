"""PARALLEL twin of btc_ledger.py (11-04) — SAME decisions in the SAME order, only the network is parallel.
Per wave: (1) QuickNode gettxout in batches → coins still unspent need no Esplora call; (2) the rest → Esplora /outspend in parallel over
mempool.space + Blockstream (per-host pacing, rotate on 429); (3) every spender tx body in parallel (cached, confirmed bodies reused);
then the ORIGINAL sequential logic runs on that prefetched data. Roots: every seed's address pages fetched in parallel.
Writes ONLY to BTC_FAST_DB (required) and refuses the production DBs; an optional BTC_FAST_CACHE_FROM=<db> copies its raw_payload
(API replies only) into the new DB first. Verify against btc_ledger.py: identical utxo + btx tables (cmp_btc_runs in NOTES).
  BTC_FAST_DB=/path/new.db BTC_TIP=974511 python3 btc_ledger_fast.py bridged|run|bshow|show"""
import json, os, re, sys, time, sqlite3, gzip, threading, urllib.request, urllib.error, socket
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
PROD = {os.path.realpath(os.path.join(HERE, f)) for f in ('binance-btc-ledger.db', 'binance-btc-bridged-ledger.db')}
DBP = os.environ.get('BTC_FAST_DB') or sys.exit('set BTC_FAST_DB=<path> (never a production DB)')
if os.path.realpath(DBP) in PROD: sys.exit('refusing: BTC_FAST_DB is a production BTC ledger DB')
HACK_TS = 1793304000; MAX_PAGES = 20
HOT = 'bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h'; COLLECT = 'bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm'
_gai = socket.getaddrinfo                                                   # mempool.space IPv4 is blackholed here → IPv6 for it only
socket.getaddrinfo = lambda h, *a, **k: ([r for r in _gai(h, *a, **k) if r[0] == socket.AF_INET6] or _gai(h, *a, **k)) if 'mempool.space' in str(h) else _gai(h, *a, **k)
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"').strip("'") for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l and not l.startswith('#')}
QB = (E['QUICKNODE_BTC_URL'].rstrip('/') + '/' + E['QUICKNODE_BTC_TOKEN'].strip() + '/') if E.get('QUICKNODE_BTC_URL') and E.get('QUICKNODE_BTC_TOKEN') else None   # never print
WORKERS = int(os.environ.get('BTC_FAST_WORKERS', 8))
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payload(id INTEGER PRIMARY KEY, ts TEXT, url TEXT, body BLOB);
CREATE INDEX IF NOT EXISTS raw_payload_url ON raw_payload(url);
CREATE TABLE IF NOT EXISTS ledger_run(run_id TEXT PRIMARY KEY, started TEXT, finished TEXT, tip INTEGER, params TEXT);
CREATE TABLE IF NOT EXISTS utxo(run_id TEXT, txid TEXT, vout INTEGER, address TEXT, sats INTEGER, owner TEXT, status TEXT,
  spent_by TEXT, spent_height INTEGER, note TEXT, PRIMARY KEY(run_id, txid, vout));
CREATE TABLE IF NOT EXISTS btx(run_id TEXT, txid TEXT PRIMARY KEY, height INTEGER, ts INTEGER, fee INTEGER, n_in INTEGER, n_out INTEGER,
  attacker_in INTEGER, foreign_in INTEGER, kind TEXT);
"""
C = None; MEM = {}; STATS = {'esplora': 0, 'cache': 0, 'gettxout_unspent': 0}
class Host:
    def __init__(s, base, qps): s.base, s.dt, s.lock, s.next, s.cool = base, 1 / qps, threading.Lock(), 0.0, 0.0
    def slot(s):
        with s.lock: t = max(time.time(), s.next, s.cool); s.next = t + s.dt
        time.sleep(max(0, t - time.time()))
HOSTS = [Host('https://mempool.space/api', float(os.environ.get('BTC_FAST_MEMPOOL_QPS', 5))), Host('https://blockstream.info/api', float(os.environ.get('BTC_FAST_BSTREAM_QPS', 1.5)))]
_rr = [0]; _rl = threading.Lock()
def fetch(path, raw_text=False):
    """one Esplora reply (thread-safe, no DB access) — round-robin over hosts, a 429'd host rests 60 s"""
    for i in range(24):
        with _rl: h = HOSTS[_rr[0] % len(HOSTS)]; _rr[0] += 1
        if h.cool > time.time() and any(x.cool <= time.time() for x in HOSTS): continue
        h.slot()
        try:
            b = urllib.request.urlopen(urllib.request.Request(h.base + path, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read()
            STATS['esplora'] += 1; return path, b
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503): h.cool = time.time() + 60; continue
            if e.code == 404: return path, None
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(2 + i % 4)
    raise RuntimeError('esplora failed ' + path)
def cached_tx(path):
    r = C.execute('SELECT body FROM raw_payload WHERE url=? ORDER BY id DESC LIMIT 1', (path,)).fetchone()
    if r:
        j = json.loads(gzip.decompress(r[0]))
        if (j.get('status') or {}).get('confirmed'): return j
    return None
def prefetch(paths):
    """fill MEM for paths in parallel; confirmed tx bodies come from raw_payload; every fresh reply is stored like btc_ledger.py does"""
    todo = []
    for p in dict.fromkeys(paths):
        if p in MEM: continue
        if re.fullmatch(r'/tx/[0-9a-f]{64}', p):
            j = cached_tx(p)
            if j is not None: MEM[p] = j; STATS['cache'] += 1; continue
        todo.append(p)
    if not todo: return
    with ThreadPoolExecutor(WORKERS) as ex:
        for p, b in ex.map(fetch, todo):
            if b is None: MEM[p] = None; continue
            C.execute('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', (time.strftime('%FT%T'), p, gzip.compress(b)))
            MEM[p] = b.decode() if p.endswith('/height') else json.loads(b)
    C.commit()
def get(path, raw_text=False):
    if path not in MEM: prefetch([path])
    return MEM[path]
def unspent_now(coins):
    """QuickNode gettxout (batched): coins still unspent at the node tip (≥ pinned tip) → unspent at the pinned tip too. Others → None."""
    if not QB or not coins: return set()
    def batch(part):
        for i in range(6):
            try:
                rs = json.load(urllib.request.urlopen(urllib.request.Request(QB, json.dumps([{"jsonrpc": "2.0", "id": j, "method": "gettxout", "params": [t, v, True]} for j, (t, v) in enumerate(part)]).encode(),
                                                                            {'Content-Type': 'application/json'}), timeout=60))
                got = {r['id']: r for r in rs if isinstance(r, dict) and r.get('error') is None and 'id' in r}
                if len(got) == len(part): return {part[j] for j in range(len(part)) if got[j].get('result') is not None}
            except Exception: pass
            time.sleep(2 * (i + 1))
        return set()                                                          # QuickNode unavailable → ask Esplora for all (same answer, slower)
    with ThreadPoolExecutor(4) as ex: return set().union(*ex.map(batch, [coins[i:i + 50] for i in range(0, len(coins), 50)]))

LB = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/data/labels.db') + '?mode=ro', uri=True)
POR = sqlite3.connect('file:' + os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db') + '?mode=ro', uri=True)
def label(a):
    p = POR.execute('SELECT exchange, wallet_type FROM por_wallets WHERE address=?', (a,)).fetchone()
    if p: return f'cex:{p[0]}/{p[1]}'
    r = LB.execute('SELECT name FROM labels WHERE address=?', (a,)).fetchone()
    return f'label:{r[0][:40]}' if r else ''

def run(bridged=False):
    global C
    t0 = time.time()
    C = sqlite3.connect(DBP, timeout=600); C.execute('PRAGMA journal_mode=WAL'); C.executescript(SCHEMA)
    src = os.environ.get('BTC_FAST_CACHE_FROM')
    if src and not C.execute('SELECT 1 FROM raw_payload LIMIT 1').fetchone():
        S = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
        C.executemany('INSERT INTO raw_payload(ts,url,body) VALUES(?,?,?)', S.execute("SELECT ts,url,body FROM raw_payload WHERE url GLOB '/tx/[0-9a-f]*' AND url NOT LIKE '%outspend%'")); C.commit()
        print(f'cache: copied {C.execute("SELECT COUNT(*) FROM raw_payload").fetchone()[0]} tx bodies from {os.path.basename(src)} (API replies only)', flush=True)
    tip = int(os.environ.get('BTC_TIP') or get('/blocks/tip/height', raw_text=True))
    run_id = ('btcb-' if bridged else 'btc-') + time.strftime('%Y%m%dT%H%M%S')
    seeds = json.load(open(os.path.join(HERE, 'raw/btc_bridged_seeds.json'))) if bridged else {}
    C.execute('INSERT INTO ledger_run VALUES(?,?,?,?,?)', (run_id, time.strftime('%FT%T'), None, tip, json.dumps({'seeds': seeds, 'tool': 'btc_ledger_fast'} if bridged else {'hot': HOT, 'collect': COLLECT, 'tool': 'btc_ledger_fast'}))); C.commit()
    print(f'{run_id}: pinned at tip {tip} → {DBP}', flush=True)
    if bridged:
        attacker, seen = set(seeds), set()
        def pages_on(h, a):                                                 # one seed's pages from ONE host (consistent cursor)
            txs, last, n = [], None, 0
            while n < MAX_PAGES:
                page = None
                for i in range(12):
                    h.slot()
                    try: page = json.loads(urllib.request.urlopen(urllib.request.Request(h.base + f'/address/{a}/txs' + (f'/chain/{last}' if last else ''), headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read()); break
                    except urllib.error.HTTPError as e:
                        if e.code in (429, 500, 502, 503): time.sleep(5 * (i + 1)); continue
                        raise
                    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(3 + i)
                if page is None: return None, n                                  # this host failed → the other host's view is used
                n += 1; STATS['esplora'] += 1
                if not page: break
                txs += page; last = page[-1]['txid']
                if len(page) < 25 or (page[-1]['status'].get('block_time') or 1e12) < HACK_TS: break
            return txs, n
        def first_page(h, a):                                              # the second host's NEWEST page only (≤3 tries)
            for i in range(3):
                h.slot()
                try: return json.loads(urllib.request.urlopen(urllib.request.Request(h.base + f'/address/{a}/txs', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read())
                except Exception: time.sleep(3 * (i + 1))
            return None
        def pages(a):
            """11-04 fix: a free host served a STALE page (2 payouts at block 974488 missing in the first test). An index that lags can only
            miss the NEWEST blocks, which are on page 1 → full history from the primary host + page 1 from the other host, merged by txid."""
            txs, n = pages_on(HOSTS[0], a)
            if txs is None: txs, n = pages_on(HOSTS[1], a)
            if txs is None: raise RuntimeError(f'no host answered for {a}')
            other = first_page(HOSTS[1], a) or []
            ids = {t['txid'] for t in txs}; extra = [t for t in other if t['txid'] not in ids]
            return a, extra + txs, n, ([len(ids), len(ids) + len(extra)] if extra else [len(ids)])
        with ThreadPoolExecutor(WORKERS) as ex: R_ = list(ex.map(pages, list(seeds)))
        PAGES = {a: (txs, n) for a, txs, n, _ in R_}
        dis = [(a, sz) for a, _, _, sz in R_ if len(set(x for x in sz if x is not None)) > 1]
        print(f'roots: {len(seeds)} seeds read on {len(HOSTS)} hosts · hosts disagreed on {len(dis)} seed(s){": " + str(dis[:6]) if dis else ""}', flush=True)
        for a, sd in seeds.items():                                          # ORIGINAL logic, original order
            txs, n = PAGES[a]
            if n >= MAX_PAGES: print(f'  BUSY {a}: stopped at {MAX_PAGES} pages, check by hand', flush=True)
            for t in txs:
                if not t['status'].get('confirmed') or t['status']['block_height'] > tip or t['status']['block_time'] < HACK_TS: continue
                if any(v['prevout']['scriptpubkey_address'] in seeds for v in t['vin']): continue
                for i, o in enumerate(t['vout']):
                    if o.get('scriptpubkey_address') == a:
                        C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], i, a, o['value'], 'attacker', 'pending', None, None, f"bridged:{'+'.join(sd['origin'])}:{'+'.join(sd['via'])}"))
                C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status']['block_height'], t['status']['block_time'], t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'bridge payout (service-signed)'))
        C.commit()
        got = C.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note LIKE 'bridged%'", (run_id,)).fetchone()
        print(f'bridged roots: {(got[0] or 0)/1e8:,.8f} BTC in {got[1]} payouts to {len(seeds)} seeds  [{time.time() - t0:.0f}s]', flush=True)
    txs, last = [], None
    if bridged: txs = None
    while txs is not None:
        page = get(f'/address/{COLLECT}/txs' + (f'/chain/{last}' if last else ''))
        if not page: break
        txs += page; last = page[-1]['txid']
        if len(page) < 25: break
    if not bridged: attacker, seen = {COLLECT}, set()
    drained = 0
    for t in txs or []:
        if any(v['prevout']['scriptpubkey_address'] == HOT for v in t['vin']):
            for i, o in enumerate(t['vout']):
                if o.get('scriptpubkey_address') == COLLECT:
                    drained += o['value']; C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], i, COLLECT, o['value'], 'attacker', 'pending', None, None, 'drain'))
            C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, t['txid'], t['status'].get('block_height'), t['status'].get('block_time'), t['fee'], len(t['vin']), len(t['vout']), 0, len(t['vin']), 'drain (victim-signed)'))
    if not bridged: print(f'drain: {drained/1e8:,.8f} BTC in {sum(1 for t in txs if any(v["prevout"]["scriptpubkey_address"]==HOT for v in t["vin"]))} txs', flush=True)
    def book_untracked(t, st):
        for v in t['vin']:
            if v['prevout']['scriptpubkey_address'] in attacker and not C.execute("SELECT 1 FROM utxo WHERE run_id=? AND txid=? AND vout=? AND owner='attacker'", (run_id, v['txid'], v['vout'])).fetchone():
                C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, v['txid'], v['vout'], v['prevout']['scriptpubkey_address'], v['prevout']['value'], 'attacker', 'spent', st, None, 'untracked-in'))
    def recheck_mixed():
        promoted = 0
        mixed = [st for (st,) in C.execute("SELECT txid FROM btx WHERE run_id=? AND kind LIKE 'MIXED%'", (run_id,)).fetchall()]
        prefetch([f'/tx/{st}' for st in mixed])
        for st in mixed:
            t = get(f'/tx/{st}')
            ok = all(C.execute("SELECT 1 FROM utxo WHERE run_id=? AND txid=? AND vout=? AND owner='attacker'", (run_id, v['txid'], v['vout'])).fetchone()
                     or v['prevout']['scriptpubkey_address'] in attacker for v in t['vin'])
            if ok:
                C.execute("UPDATE btx SET kind='attacker-signed', attacker_in=n_in, foreign_in=0 WHERE run_id=? AND txid=?", (run_id, st))
                book_untracked(t, st)
                for (vout, ad, nt) in C.execute("SELECT vout, address, note FROM utxo WHERE run_id=? AND txid=? AND owner LIKE 'unattributed%'", (run_id, st)).fetchall():
                    if nt: C.execute("UPDATE utxo SET owner='exit' WHERE run_id=? AND txid=? AND vout=?", (run_id, st, vout)); continue
                    C.execute("UPDATE utxo SET owner='attacker', status='pending' WHERE run_id=? AND txid=? AND vout=?", (run_id, st, vout)); attacker.add(ad)
                promoted += 1
        C.commit(); return promoted
    wave = 0
    while True:
        pend = C.execute("SELECT txid, vout, address, sats FROM utxo WHERE run_id=? AND owner='attacker' AND status='pending'", (run_id,)).fetchall()
        if not pend:
            if recheck_mixed(): continue
            break
        wave += 1; tw = time.time()
        # ---- parallel prefetch for this wave (network only; no decisions)
        still = unspent_now([(t, v) for t, v, _, _ in pend]); STATS['gettxout_unspent'] += len(still)
        for t, v in still: MEM[f'/tx/{t}/outspend/{v}'] = {'spent': False}
        prefetch([f'/tx/{t}/outspend/{v}' for t, v, _, _ in pend if (t, v) not in still])
        if QB:                                                               # 11-04 guard: node says spent but a host says unspent → stale host, re-ask
            for t, v, _, _ in pend:
                k = f'/tx/{t}/outspend/{v}'
                if (t, v) not in still and MEM.get(k) is not None and not MEM[k].get('spent'):
                    for h in HOSTS:
                        try:
                            h.slot(); j = json.loads(urllib.request.urlopen(urllib.request.Request(h.base + k, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40).read())
                            if j.get('spent'): MEM[k] = j; STATS['stale_fixed'] = STATS.get('stale_fixed', 0) + 1; break
                        except Exception: pass
        prefetch([f"/tx/{MEM[f'/tx/{t}/outspend/{v}']['txid']}" for t, v, _, _ in pend
                  if (MEM.get(f'/tx/{t}/outspend/{v}') or {}).get('spent') and ((MEM[f'/tx/{t}/outspend/{v}'].get('status') or {}).get('confirmed'))])
        # ---- ORIGINAL sequential logic, original order, on the prefetched data
        for txid, vout, addr, sats in pend:
            os_ = get(f'/tx/{txid}/outspend/{vout}')
            if not os_.get('spent'):
                C.execute("UPDATE utxo SET status='unspent' WHERE run_id=? AND txid=? AND vout=?", (run_id, txid, vout)); continue
            sh = (os_.get('status') or {}).get('block_height')
            if not (os_.get('status') or {}).get('confirmed') or (sh and sh > tip):
                C.execute("UPDATE utxo SET status=?, spent_by=? WHERE run_id=? AND txid=? AND vout=?",
                          ('unspent (spend in mempool)' if not (os_.get('status') or {}).get('confirmed') else 'unspent at tip (spent later)', os_['txid'], run_id, txid, vout)); continue
            C.execute("UPDATE utxo SET status='spent', spent_by=?, spent_height=? WHERE run_id=? AND txid=? AND vout=?", (os_['txid'], sh, run_id, txid, vout))
            st = os_['txid']
            if st in seen: continue
            seen.add(st)
            t = get(f'/tx/{st}')
            ins = [(v['txid'], v['vout'], v['prevout']['scriptpubkey_address'], v['prevout']['value']) for v in t['vin']]
            a_in = sum(1 for _, _, ad, _ in ins if ad in attacker); f_in = len(ins) - a_in
            kind = 'attacker-signed' if f_in == 0 else 'MIXED (foreign inputs)'
            if f_in == 0: book_untracked(t, st)
            C.execute('INSERT OR REPLACE INTO btx VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, st, sh, t['status'].get('block_time'), t['fee'], len(ins), len(t['vout']), a_in, f_in, kind))
            for i, o in enumerate(t['vout']):
                ad = o.get('scriptpubkey_address') or o.get('scriptpubkey_type'); lb = label(ad) if ad else ''
                if f_in == 0 and lb: owner, note = 'exit', lb
                elif f_in == 0: owner, note = 'attacker', ''; attacker.add(ad)
                else: owner, note = 'unattributed (mixed tx)', lb
                C.execute('INSERT OR IGNORE INTO utxo VALUES(?,?,?,?,?,?,?,?,?,?)', (run_id, st, i, ad, o['value'], owner, 'pending' if owner == 'attacker' else 'n/a', None, None, note))
                if owner == 'attacker': C.execute("UPDATE utxo SET note='' WHERE run_id=? AND txid=? AND vout=? AND note='untracked-in'", (run_id, st, i))
        C.commit()
        print(f'  wave {wave}: {len(pend)} coins ({len(still)} unspent via gettxout) in {time.time() - tw:.0f}s · esplora {STATS["esplora"]} · cache {STATS["cache"]}', flush=True)
    C.execute('UPDATE ledger_run SET finished=? WHERE run_id=?', (time.strftime('%FT%T'), run_id)); C.commit()
    print(f'FINISHED in {time.time() - t0:.0f}s · {STATS}', flush=True)
    show(run_id, bridged)

def show(run_id=None, bridged=False):
    c = sqlite3.connect(DBP, timeout=600)
    run_id = run_id or c.execute('SELECT run_id FROM ledger_run ORDER BY started DESC LIMIT 1').fetchone()[0]
    tip = c.execute('SELECT tip FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0]
    drained = c.execute("SELECT SUM(sats) FROM utxo WHERE run_id=? AND (note='drain' OR note LIKE 'bridged%')", (run_id,)).fetchone()[0] or 0
    unspent = c.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='attacker' AND status LIKE 'unspent%'", (run_id,)).fetchone()
    exits = c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND owner='exit' GROUP BY note", (run_id,)).fetchall()
    untr = c.execute("SELECT SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note='untracked-in'", (run_id,)).fetchone()
    drained += untr[0] or 0
    unatt = c.execute("SELECT SUM(u.sats) FROM utxo u JOIN btx b ON b.run_id=u.run_id AND b.txid=u.spent_by WHERE u.run_id=? AND u.owner='attacker' AND b.kind LIKE 'MIXED%'", (run_id,)).fetchone()[0] or 0
    fees = c.execute("SELECT SUM(fee) FROM btx WHERE run_id=? AND kind='attacker-signed'", (run_id,)).fetchone()[0] or 0
    mixed = c.execute("SELECT txid, height, attacker_in, foreign_in FROM btx WHERE run_id=? AND kind LIKE 'MIXED%'", (run_id,)).fetchall()
    mem = c.execute("SELECT txid, vout, address, sats, spent_by FROM utxo WHERE run_id=? AND status LIKE '%mempool%'", (run_id,)).fetchall()
    uses = (unspent[0] or 0) + sum(s for _, s, _ in exits) + unatt + fees
    print(f'\n=== {run_id} | pinned tip {tip} ===')
    if not bridged: print(f'SOURCES  drained from Binance hot wallet   {drained/1e8:>18,.8f} BTC')
    else:
        seeds = json.loads(c.execute('SELECT params FROM ledger_run WHERE run_id=?', (run_id,)).fetchone()[0])['seeds']
        for n, s, k in c.execute("SELECT note, SUM(sats), COUNT(*) FROM utxo WHERE run_id=? AND note LIKE 'bridged%' GROUP BY note", (run_id,)):
            print(f'SOURCES  {n:36} {s/1e8:>18,.8f} BTC ({k} payouts)')
        got = dict(c.execute("SELECT address, SUM(sats) FROM utxo WHERE run_id=? AND note LIKE 'bridged%' GROUP BY address", (run_id,)).fetchall())
        diff = [(a, sd['expected_btc'], got.get(a, 0) / 1e8) for a, sd in seeds.items() if abs(got.get(a, 0) / 1e8 - sd['expected_btc']) > 1e-6]
        if untr[1]: print(f'SOURCES  UNTRACKED inputs at attacker addresses {(untr[0] or 0)/1e8:>12,.8f} BTC ({untr[1]}) — resolve: who paid them?')
        print(f'SEEDS    received vs bridge records: {len(seeds) - len(diff)}/{len(seeds)} exact')
        for a, e, g in diff: print(f'         ≠ {a} expected {e:.8f} got {g:.8f} ({g - e:+.8f})')
    print(f'USES     unspent at attacker ({unspent[1]} UTXOs)  {(unspent[0] or 0)/1e8:>18,.8f}')
    for n, s, k in exits: print(f'         exit {n:28} {s/1e8:>18,.8f} ({k})')
    print(f'         into MIXED txs (attacker share) {unatt/1e8:>18,.8f}\n         miner fees (attacker txs)       {fees/1e8:>18,.8f}')
    print(f'UNEXPLAINED (sats)                       {drained - uses}')
    print(f'MIXED spends: {mixed or "none"}  | spends waiting in mempool: {mem or "none"}')

if __name__ == '__main__':
    {'run': run, 'show': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None),
     'bridged': lambda: run(True), 'bshow': lambda: show(sys.argv[2] if len(sys.argv) > 2 else None, True)}[sys.argv[1]]()
