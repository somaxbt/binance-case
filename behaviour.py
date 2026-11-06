# Binance case, TRON — automation vs manual: timing/amount behaviour of attacker-sent txs across the 5 chained ledger windows (read-only on binance-live.db).
import sqlite3, collections, datetime as dt, statistics as st
RUNS=('tron2-20261030T160703','tron2-20261030T213835','tron2-20261031T070701','tron2-20261031T102403','tron2-20261031T142107')
db=sqlite3.connect('file:/Users/somuknr/cases/binance/binance-live.db?mode=ro',uri=True)
q=f"select distinct hash,ts,frm,too,asset,amount,cls from ledger_edge where run_id in ({','.join('?'*len(RUNS))}) and cls not in ('in:dust')"
rows=db.execute(q,RUNS).fetchall()
# attacker-sent = out:* plus fee rows; keep sends with a distinct hash
sends={}
for h,ts,f,t,a,amt,c in rows:
    if c.startswith('out:') or c.startswith('failed:'):
        sends.setdefault(h,(ts//1000,f,t,a,amt,c))
print('distinct attacker sends',len(sends))
by_hour=collections.Counter(dt.datetime.utcfromtimestamp(v[0]).strftime('%m-%d %H') for v in sends.values())
for k in sorted(by_hour): print(k, by_hour[k], '#'*(by_hour[k]//20))

print('\n==== per-hour behaviour ====')
INC=('in:attacker','in:swap_proceeds','in:root','in:own_back','in:foreign')
inb=collections.defaultdict(list)
for h,ts,f,t,a,amt,c in rows:
    if c in INC: inb[t].append((ts//1000,h))
for k in inb: inb[k].sort()
def lastin(f,ts,h):
    L=inb.get(f,[]); i=bisect.bisect_right(L,(ts,'~'))-1
    while i>=0 and L[i][1]==h: i-=1
    return ts-L[i][0] if i>=0 else None
import bisect
blk=collections.defaultdict(set)   # 3s block bucket -> sender wallets
for ts,f,*_ in sends.values(): blk[ts//3].add(f)
def rnd(a,amt): return amt>=100 and (amt%100==0)
H=collections.defaultdict(lambda: collections.defaultdict(list))
for h,(ts,f,t,a,amt,c) in sends.items():
    lag=lastin(f,ts,h)
    hr=dt.datetime.fromtimestamp(ts,dt.UTC).strftime('%m-%d %H')
    d=H[hr]; d['lag'].append(lag); d['multi'].append(len(blk[ts//3])>=3); d['round'].append(rnd(a,amt)); d['cls'].append(c); d['w'].append(f)
print('hour      sends wallets  medLag  lag<=6s  lag>5m  sameBlk3+  round')
for hr in sorted(H):
    d=H[hr]; lags=[x for x in d['lag'] if x is not None]; n=len(d['lag'])
    if n<10: continue
    print(f"{hr}  {n:5d} {len(set(d['w'])):6d} {st.median(lags) if lags else -1:7.0f} {sum(x<=6 for x in lags)/max(1,len(lags)):7.0%} {sum(x>300 for x in lags)/max(1,len(lags)):7.0%} {sum(d['multi'])/n:8.0%} {sum(d['round'])/n:6.0%}")

print('\n==== by class ====')
C=collections.defaultdict(lambda: collections.defaultdict(list))
for h,(ts,f,t,a,amt,c) in sends.items():
    d=C[c]; d['lag'].append(lastin(f,ts,h)); d['multi'].append(len(blk[ts//3])>=3); d['round'].append(rnd(a,amt))
print('class                 n   medLag  lag<=6s  sameBlk3+ round')
for c,d in sorted(C.items(), key=lambda x:-len(x[1]['lag'])):
    lags=[x for x in d['lag'] if x is not None]; n=len(d['lag'])
    print(f"{c:20s} {n:5d} {st.median(lags) if lags else -1:7.0f} {sum(x<=6 for x in lags)/max(1,len(lags)):7.0%} {sum(d['multi'])/n:8.0%} {sum(d['round'])/n:6.0%}")

print('\n==== same-block fan-out vs chance (shuffle ts within hour, 20x) ====')
import random
random.seed(1)
def frac_multi(ts_list):
    b=collections.defaultdict(set)
    for ts,f in ts_list: b[ts//3].add(f)
    return sum(len(b[ts//3])>=3 for ts,f in ts_list)/len(ts_list)
byhr=collections.defaultdict(list)
for ts,f,*_ in sends.values(): byhr[ts//3600].append((ts,f))
print('hour     obs   chance')
for hk in sorted(byhr):
    L=byhr[hk]
    if len(L)<200: continue
    obs=frac_multi(L); ch=[]
    for _ in range(20):
        ch.append(frac_multi([(hk*3600+random.randrange(3600),f) for ts,f in L]))
    print(dt.datetime.fromtimestamp(hk*3600,dt.UTC).strftime('%m-%d %H'), f"{obs:5.0%} {st.mean(ch):6.0%}", '<<< BATCH' if obs>2*st.mean(ch)+0.05 else '')

print('\n==== biggest same-block batches ====')
B=collections.defaultdict(list)
for h,(ts,f,t,a,amt,c) in sends.items(): B[ts//3].append((f,t,a,amt,c,h))
big=sorted(B.items(), key=lambda x:-len({r[0] for r in x[1]}))[:12]
for b,L in big:
    ws={r[0] for r in L}; dests=collections.Counter(r[1] for r in L); cls=collections.Counter(r[4] for r in L)
    amts=collections.Counter((r[2],round(r[3],2)) for r in L).most_common(3)
    print(dt.datetime.fromtimestamp(b*3,dt.UTC).strftime('%m-%d %H:%M:%S'), f"txs={len(L)} senders={len(ws)} dests={len(dests)}", dict(cls), 'topdest', dests.most_common(1)[0], 'amts', amts)

print('\n==== repeated exact amounts (same asset+amount sent >=8 times) by class ====')
R=collections.Counter((c,a,round(amt,6)) for ts,f,t,a,amt,c in sends.values())
for (c,a,amt),n in R.most_common(40):
    if n<8: break
    nw=len({f for ts,f,t,aa,am,cc in sends.values() if cc==c and aa==a and round(am,6)==amt})
    print(f"{c:18s} {a:5s} {amt:>16,.6f} x{n:<4d} from {nw} wallets")

print('\n==== fixed-fee externals: who receives ====')
for want in (9.07782,9.30207,20.0,15.0):
    d=collections.Counter(t for ts,f,t,a,amt,c in sends.values() if c=='out:external' and abs(amt-want)<1e-6)
    tss=[ts for ts,f,t,a,amt,c in sends.values() if c=='out:external' and abs(amt-want)<1e-6]
    print(want, d.most_common(3), 'span', dt.datetime.fromtimestamp(min(tss),dt.UTC).strftime('%m-%d %H:%M'), '->', dt.datetime.fromtimestamp(max(tss),dt.UTC).strftime('%m-%d %H:%M'))

print('\n==== cadence of repeat senders (same class, >=15 sends): gap stats ====')
S=collections.defaultdict(list)
for ts,f,t,a,amt,c in sends.values(): S[(f,c)].append((ts,amt,t))
out=[]
for (f,c),L in S.items():
    if len(L)<15: continue
    L.sort(); g=[b[0]-a[0] for a,b in zip(L,L[1:])]
    cv=st.pstdev(g)/st.mean(g) if st.mean(g)>0 else 0
    amts=collections.Counter(round(x[1],2) for x in L).most_common(1)[0]
    out.append((cv,f,c,len(L),st.median(g),min(g),amts,len({x[2] for x in L}),dt.datetime.fromtimestamp(L[0][0],dt.UTC).strftime('%m-%d %H:%M'),dt.datetime.fromtimestamp(L[-1][0],dt.UTC).strftime('%m-%d %H:%M')))
out.sort()
print('CV    wallet       class            n  medGap minGap topAmt(xN) dests  span')
for r in out[:25]+[None]+out[-8:]:
    if r is None: print('...'); continue
    cv,f,c,n,mg,mn,amts,nd,s0,s1=r
    print(f"{cv:4.2f}  {f[:10]}  {c:16s} {n:3d} {mg:6.0f} {mn:5d}  {amts[0]:>10}x{amts[1]:<3d} {nd:4d}  {s0}->{s1}")
print('n repeat-sender series', len(out), ' CV<0.5:', sum(r[0]<0.5 for r in out))

print('\n==== energy-fee setup step ====')
fee=[(ts,f) for ts,f,t,a,amt,c in sends.values() if t=='TErYb1JEuEmxs31XUFcieCbygVHhPrPZAN']
per=collections.Counter(f for ts,f in fee); print('payers',len(per),'max payments per wallet',max(per.values()))
lag=[]; nxt=[]
for ts,f in fee:
    L=inb.get(f,[]); lag.append(ts-L[0][0] if L else None)
    later=sorted(x for x,ff,*_ in sends.values() if ff==f and x>=ts and x-ts<3600)
    nxt.append(later[1]-ts if len(later)>1 else None)
lg=[x for x in lag if x is not None]; nx=[x for x in nxt if x is not None]
print('fee paid after wallet first funded: median %ds, <=30s %.0f%%'%(st.median(lg),100*sum(x<=30 for x in lg)/len(lg)))
print('next send after fee: median %ds, <=6s %.0f%%'%(st.median(nx),100*sum(x<=6 for x in nx)/len(nx)))

print('\n==== classify each send ====')
prev={}
for (f,c),L in S.items(): pass
bywal=collections.defaultdict(list)
for h,(ts,f,t,a,amt,c) in sends.items(): bywal[f].append((ts,h))
for f in bywal: bywal[f].sort()
gapprev={}
for f,L in bywal.items():
    for (a,_),(b,h) in zip(L,L[1:]): gapprev[h]=b-a
lab={}
for h,(ts,f,t,a,amt,c) in sends.items():
    lag=lastin(f,ts,h); lag=9e9 if lag is None else lag
    if len(blk[ts//3])>=5: lab[h]='A batch(>=5 wallets/block)'
    elif lag<=6: lab[h]='B react<=6s of inflow'
    elif gapprev.get(h,9e9)<=6: lab[h]='C rapid serial<=6s'
    elif t=='TErYb1JEuEmxs31XUFcieCbygVHhPrPZAN': lab[h]='D fixed setup fee'
    else: lab[h]='E paced (manual OR slow bot)'
print(collections.Counter(lab.values()))
cats=sorted(set(lab.values()))
print('hour     n   '+'  '.join(c[0] for c in cats))
for hr in sorted(H):
    hs=[h for h,v in sends.items() if dt.datetime.fromtimestamp(v[0],dt.UTC).strftime('%m-%d %H')==hr]
    if len(hs)<10: continue
    cc=collections.Counter(lab[h] for h in hs)
    print(hr, f"{len(hs):5d}", '  '.join(f"{cc[c]/len(hs):3.0%}" for c in cats))

print('\n==== E-sends: reaction-lag histogram (s) ====')
bins=[0,6,15,30,45,60,90,120,180,300,600,1800,3600,1e9]
def per(ts):
    if ts<1793354400: return 'P1 10-30 02-09'   # before 10-30 10:00 UTC (approx)
    return 'P2 10-30 10->'
P1c=dt.datetime(2026,10,30,10,tzinfo=dt.UTC).timestamp()
for name,cond in (('P1 (to 10-30 10:00)',lambda ts: ts<P1c),('P2 (10-30 10:00 ->)',lambda ts: ts>=P1c)):
    hist=collections.Counter()
    for h,(ts,f,t,a,amt,c) in sends.items():
        if lab[h][0]!='E' or not cond(ts): continue
        lag=lastin(f,ts,h)
        if lag is None: continue
        hist[next(j for j in range(len(bins)-1) if bins[j]<=lag<bins[j+1])]+=1
    tot=sum(hist.values()); print(name, tot)
    for j in range(len(bins)-1): print(f"  {bins[j]:>5.0f}-{bins[j+1]:<6.0f} {hist[j]/tot:5.1%} "+'#'*int(200*hist[j]/tot/2))
print('\n==== concurrency: distinct sending wallets per minute (P2), and max sends/min ====')
pm=collections.defaultdict(set); pc=collections.Counter()
for ts,f,*_ in sends.values():
    if ts>=P1c: pm[ts//60].add(f); pc[ts//60]+=1
v=[len(s) for s in pm.values()]
print('minutes active',len(pm),'of',int((max(pm)-min(pm))+1),' median wallets/min',st.median(v),' p90',sorted(v)[int(.9*len(v))],' max sends/min',max(pc.values()))
gaps=sorted(pm); mx=max(b-a for a,b in zip(gaps,gaps[1:])); print('longest silent gap in P2 (min):',mx)

print('\n==== P2 fine lag 6-60s (3s bins = Tron blocks) ====')
fh=collections.Counter()
for h,(ts,f,t,a,amt,c) in sends.items():
    if ts<P1c: continue
    lag=lastin(f,ts,h)
    if lag is None: continue
    if 6<lag<=60: fh[(lag//3)*3]+=1
for k in sorted(fh): print(f"  {k:3d}s {fh[k]:4d} "+'#'*(fh[k]//10))
print('\n==== BIG sends (>=1M TRX or >=100k USDT): the decision layer ====')
for h,(ts,f,t,a,amt,c) in sorted(sends.items(), key=lambda x:x[1][0]):
    if (a=='TRX' and amt>=1e6) or (a=='USDT' and amt>=1e5):
        lag=lastin(f,ts,h)
        print(dt.datetime.fromtimestamp(ts,dt.UTC).strftime('%m-%d %H:%M:%S'), f"{f[:8]}->{t[:8]} {a:4s} {amt:>15,.2f} {c:16s} lag={lag} {lab[h][0]}")
