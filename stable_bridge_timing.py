"""Tron STABLECOIN (USDT) bridge deposits: timing, signing fingerprints, same-block bursts — automation test. Read-only (ledger + raw store)."""
import json,sqlite3,zlib,gzip,collections,statistics as st,time,os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
db=sqlite3.connect('file:binance-live.db?mode=ro',uri=True)
RUNS=[r for (r,) in db.execute("SELECT run_id FROM ledger_run WHERE leg='tron2' AND finished GLOB '2026*'")]
CF=set(json.load(open('raw/tron/bridge_cf.json')))                         # Chainflip deposit tx hashes (channel deposits)
ROUTE={'TXtEs6t2oUWQsNos7m68gbHdE9Q5n6x2oN':'Relay','TFG4wBaDQ8sHWWP1ACeSGnoNR6RRzevLPt':'USDT0','TB6QHSqmof2ssxoKkWwabTbvDbCxydZ23a':'Across',
       'TZG47zhb8kcriWQ2rE719yHs1KqgzwMrvF':'Bitget Wallet bridge','TM8uyBjRKzFtQdMC7tQLvKeeWieaFvXDyc':'Bitget Wallet (swap→bridge)'}
inb=collections.defaultdict(list); D={}
for h,ts,f,t,a,amt,c in db.execute("SELECT DISTINCT hash,ts,frm,too,asset,amount,cls FROM ledger_edge WHERE run_id IN (%s)"%','.join('?'*len(RUNS)),RUNS):
    if a=='USDT' and c.startswith('in:') and c not in ('in:dust',) and (amt or 0)>=1: inb[t].append(ts/1000)
    if a!='USDT' or not c.startswith('out:'): continue
    r=ROUTE.get(t) or ('Chainflip' if h.lower() in CF else 'THORChain' if c=='out:thorchain' else None)
    if r: D[h]=(r,ts/1000,f,amt)
raw=sqlite3.connect('file:binance-live-raw.db?mode=ro',uri=True); FP={}
for u,b in raw.execute("SELECT url,body FROM raw_payload WHERE url LIKE '%/transactions%' AND url NOT LIKE '%trc20%'"):
    d=None
    for fn in (lambda x:x,zlib.decompress,gzip.decompress):
        try: d=json.loads(fn(b)); break
        except Exception: pass
    for t in (d or {}).get('data') or []:
        if t.get('txID') in D and t['txID'] not in FP:
            rd=t.get('raw_data') or {}; FP[t['txID']]=((rd.get('fee_limit') or 0)/1e6, round((rd.get('expiration',0)-rd.get('timestamp',0))/1000), (t.get('block_timestamp',0)-rd.get('timestamp',0))/1000 if rd.get('timestamp') else None)
def q(xs):
    xs=sorted(x for x in xs if x is not None)
    if not xs: return 'n=0'
    p=lambda f: xs[min(len(xs)-1,int(f*len(xs)))]
    return f"p10 {p(.1):.0f}s · median {st.median(xs):.0f}s · p90 {p(.9):.0f}s"
print(f'USDT bridge deposits: {len(D)} | with raw signing data: {len(FP)}')
blocks=collections.defaultdict(set)
for h,(r,ts,f,amt) in D.items(): blocks[(r,int(ts//3))].add(f)
for r in sorted({v[0] for v in D.values()},key=lambda r:-sum(v[3] or 0 for v in D.values() if v[0]==r)):
    H=[h for h,v in D.items() if v[0]==r]; vol=sum(D[h][3] or 0 for h in H); W={D[h][2] for h in H}
    lag=[]
    for h in H:
        _,ts,f,_=D[h]; prev=[x for x in inb.get(f,[]) if x<=ts]
        if prev: lag.append(ts-max(prev))
    fl=collections.Counter(FP[h][0] for h in H if h in FP); s2b=[FP[h][2] for h in H if h in FP]
    multi=sum(1 for (rr,_),ws in blocks.items() if rr==r and len(ws)>=2)
    am=[D[h][3] or 0 for h in H]; rnd=sum(1 for a in am if a>=1000 and a%1000==0)/len(am); odd=sum(1 for a in am if a!=int(a))/len(am)
    bot=sum(n for k,n in fl.items() if k in (50.0,100.0)); op=fl.get(500.0,0); tot=sum(fl.values())
    print(f"\n{r}: {len(H)} deposits · {vol:,.0f} USDT · {len(W)} wallets · {time.strftime('%m-%d %H:%M',time.gmtime(min(D[h][1] for h in H)))}→{time.strftime('%m-%d %H:%M',time.gmtime(max(D[h][1] for h in H)))}")
    print(f"   USDT arrives → deposit: {q(lag)} · within 35 s {sum(1 for x in lag if x<=35)/len(lag) if lag else 0:.0%} · within 120 s {sum(1 for x in lag if x<=120)/len(lag) if lag else 0:.0%}")
    print(f"   signing: fee_limit {dict(fl.most_common(4))} → bot-config {bot}/{tot}, operator-500 {op}/{tot} · sign→block {q(s2b)}")
    print(f"   amounts: round-1000 {rnd:.0%} · with decimals {odd:.0%} · blocks with ≥2 wallets depositing together: {multi}")
