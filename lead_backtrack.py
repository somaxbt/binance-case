"""BTC lead backtrack (11-05; replaces the inline rounds 1-2): which money are the LEADS of a btc_ledger2 bridged run?
  BTC2_DB=raw/btc2/btc2-bridged-cutoff.db python3 lead_backtrack.py <run_id> [--apply]
LEAD = a foreign coin spent from an attacker address. For each lead coin, its CREATING tx P:
  memo OUT:<H>             -> THORChain payout of inbound H (hop 1)
  egress of a known Chainflip swap (raw/cf_dest_*.json) -> Chainflip
  else one hop back, value-weighted over P's inputs: attacker coin of this run / THORChain OUT (hop 2) / Chainflip / other memo /
  untracked coin at an attacker address / batch payout (>=10 outs) / unknown.
Every THORChain inbound H is resolved via the shared resolver (~/cases/_bridges, THORNode = truth) and its SENDER checked against the trees
(EVM -> latest ETH tree run, same key on AVAX/Base/BSC; Tron -> Tron ledger nodes). --apply adds tree-sender deposits not yet seeded to
raw/btc2/extra_thor_deposits.json (backup first). Non-tree senders stay leads (attribution open). Read-only on BTC2_DB except tx cache."""
import collections, glob, json, os, shutil, sqlite3, sys, time
import btc_ledger2 as BL
sys.path.insert(0, os.path.expanduser('~/cases/_bridges')); import bridges as BR
RUN = sys.argv[1]; APPLY = '--apply' in sys.argv
BL.C = sqlite3.connect(os.environ['BTC2_DB'], timeout=600)
C = BL.C
ATT = set(C.execute("SELECT txid, vout FROM utxo WHERE run_id=? AND owner='attacker'", (RUN,)).fetchall())
AADDR = {a for (a,) in C.execute("SELECT DISTINCT address FROM utxo WHERE run_id=? AND owner='attacker'", (RUN,))}
LEADS = C.execute("SELECT DISTINCT prev_txid, prev_vout, address, sats FROM lead WHERE run_id=?", (RUN,)).fetchall()
CF = {}                                                                     # Chainflip egress txid -> swap row
for f in glob.glob('raw/cf_dest_*.json'):
    if f.endswith('cache.json'): continue
    for r in json.load(open(f)).get('swaps', []):
        if r.get('egress'): CF[r['egress'].lower()] = r
EB = sqlite3.connect('file:binance-bridged.db?mode=ro', uri=True)
ER = EB.execute("SELECT run_id FROM run WHERE finished IS NOT NULL AND (run_id LIKE 'eth-hs-full-%' OR run_id LIKE 'eth-hs-inc-%') ORDER BY started DESC LIMIT 1").fetchone()[0]
LV = sqlite3.connect('file:binance-live.db?mode=ro', uri=True)
def in_tree(a):
    if not a: return False
    if a.startswith('0x'): return EB.execute("SELECT 1 FROM wallet WHERE run_id=? AND lower(address)=lower(?) AND status='tree'", (ER, a)).fetchone() is not None
    return LV.execute('SELECT 1 FROM ledger_node WHERE address=? LIMIT 1', (a,)).fetchone() is not None
EXTRA_P = 'raw/btc2/extra_thor_deposits.json'; EXTRA = json.load(open(EXTRA_P))
SEEDED = {h.upper() for h in EXTRA} | {s.upper().removeprefix('0X') for sd in json.load(open('raw/btc_bridged_seeds.json')).values() for s in (sd.get('src') or [])}

def memo(t):
    for o in BL.TXS[t]['vout']:
        asm = o['scriptPubKey'].get('asm', '')
        if asm.startswith('OP_RETURN '):
            try: return bytes.fromhex(asm.split()[1]).decode('utf-8', 'replace')
            except (ValueError, IndexError): return asm
    return ''
def kind_of(t):
    """what produced tx t's money as a source: (label, THORChain inbound or None)."""
    m = memo(t)
    if m.upper().startswith('OUT:'): return 'THORChain OUT', m[4:].strip().upper()
    if t.lower() in CF: return 'Chainflip payout', None
    if m: return 'other memo', None
    if len(BL.TXS[t]['vout']) >= 10: return f"batch payout ({len(BL.TXS[t]['vout'])} outs) — exchange/service withdrawal?", None
    return None, None

P = BL.txs(sorted({t for t, *_ in LEADS}))
hop1 = collections.defaultdict(int); THOR = collections.defaultdict(int)     # inbound H -> lead sats it explains
for t, v, a, s in LEADS:
    k, h = kind_of(t)
    if k: hop1[k] += s
    if h: THOR[h] += s
need = sorted({v['txid'] for t, v_, a, s in LEADS if not kind_of(t)[0] for v in P[t]['vin'] if v['txid'] and (v['txid'], v['vout']) not in ATT})
Q = BL.txs(need)
split = collections.defaultdict(lambda: [0, 0, set()])
for t, vo, a, s in LEADS:
    if kind_of(t)[0]: continue
    tot = sum(v['prevout']['value'] for v in P[t]['vin']) or 1
    for v in P[t]['vin']:
        if (v['txid'], v['vout']) in ATT: k, h = 'attacker coin (in our set)', None
        else:
            k, h = kind_of(v['txid'])
            if not k: k = 'from an attacker address (untracked coin)' if v['prevout'].get('scriptpubkey_address') in AADDR else f"unknown ({len(P[t]['vin'])} in/{len(P[t]['vout'])} out)"
        w = s * v['prevout']['value'] // tot; split[k][0] += w; split[k][1] += 1; split[k][2].add(a)
        if h: THOR[h] += w
print(f"{RUN}: {len(LEADS)} lead coins {sum(x[3] for x in LEADS)/1e8:,.8f} BTC · ETH tree {ER}")
print('\nby the CREATING tx itself:')
for k, s in sorted(hop1.items(), key=lambda x: -x[1]): print(f'  {s/1e8:14.8f}  {k}')
print('\nthe rest, one hop back (value-weighted over the creating tx inputs):')
for k, (s, n, ad) in sorted(split.items(), key=lambda x: -x[1][0]): print(f'  {s/1e8:14.8f}  {n:4} inputs {len(ad):3} addrs  {k}')

print(f'\nTHORChain inbounds behind the leads: {len(THOR)} (shared resolver, ~1 s each uncached)')
cache = BR.load('thorchain'); rows = []
for h in sorted(THOR):
    if h not in cache: BR.lookup('thorchain', h); cache = BR.load('thorchain')
    tx = (cache.get(h) or {}).get('tx') or {}
    rows.append((h, tx.get('chain'), tx.get('from_address'), in_tree(tx.get('from_address')), h in SEEDED, THOR[h]))
add = {}
for h, ch, fr, tr, sd, s in sorted(rows, key=lambda r: (not r[3], r[4], -r[5])):
    tag = 'SEEDED already' if sd else ('TREE KEY → seed' if tr else ('unresolved' if not fr else 'NOT in tree → lead'))
    print(f'  {h[:16]} {str(ch):5} {str(fr):44} {s/1e8:12.8f}  {tag}')
    if tr and not sd: add[h] = {'chain': ch, 'sender': fr, 'origin': 'TRON' if not fr.startswith('0x') else 'ETH',
                                'why': f'sender in a tree (same key on {ch}); payout behind a BTC lead coin, {RUN}'}
by = collections.defaultdict(float)
for h, ch, fr, tr, sd, s in rows:
    if not tr and fr: by[(ch, fr)] += s / 1e8
print(f'\nnew tree-key deposits to seed: {len(add)} · non-tree senders (attribution open):')
for (ch, fr), b in sorted(by.items(), key=lambda x: -x[1]): print(f'  {ch:5} {fr} {b:.8f} BTC of leads')
if APPLY and add:
    shutil.copy(EXTRA_P, EXTRA_P + '.bak-' + time.strftime('%Y%m%dT%H%M%S')); EXTRA.update(add); json.dump(EXTRA, open(EXTRA_P, 'w'), indent=1)
    print(f'APPLIED: {EXTRA_P} now {len(EXTRA)} deposits → re-run btc_seeds.py, then the cutoff run')
