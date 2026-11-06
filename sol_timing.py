import json,glob,collections,statistics,time,os
os.chdir(os.path.expanduser('~/cases/binance'))
B58='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58d(s):
    n=0
    for c in s: n=n*58+B58.index(c)
    b=n.to_bytes((n.bit_length()+7)//8,'big'); return b'\x00'*(len(s)-len(s.lstrip('1')))+b
B=json.load(open(sorted(glob.glob('raw/sol/branch_Fw9P2sFu_*.json'))[-1])); T=B['tree']
C={}
def info(sig):
    if sig in C: return C[sig]
    x=json.load(open(f'raw/sol/tx_{sig}.json')); lim=price=None
    for ix in x['transaction']['message']['instructions']:
        if ix.get('programId','').startswith('ComputeBudget') and 'data' in ix:
            d=b58d(ix['data'])
            if d[:1]==b'\x02': lim=int.from_bytes(d[1:5],'little')
            if d[:1]==b'\x03': price=int.from_bytes(d[1:9],'little')
    C[sig]=(x['slot'],x['blockTime'],lim,price,x['meta']['fee']); return C[sig]
key={'Fw9P2sFu':'Fw9P2sFuSRg5VC3nGyh7tx9F76TYVDvQWpaazWpp6848','ARk92box':'ARk92boxCbssS2p8AL3x9GvLzZYxcRFueXvpUnGGZciQ','6nBooPf9':'6nBooPf9yUnp3JiuuNpdhFG4BCyHzxEEUUL41hsQc1Jb','D99xhiyD':'D99xhiyDjChgMaBEG3nrMnSVyzWcvFtEtKptpEAi9FGd','4wWwZsnt':'4wWwZsntVqgrLeVeZ1fRYYpqxxEidHnpHrNtGfiWjWfy'}
ev={}
for name,a in key.items():
    for r in T[a]['flows']:
        if r['err'] or (name=='6nBooPf9' and r['signer']==a): continue
        if (r['signer']==a and (r['out'] or r['dTok'])) or r['inn']:
            ev[(r['sig'],name)]=(info(r['sig']),name,'SEND' if r['signer']==a else 'recv',r['dTok'],r['dSOL'])
# add the jlWSOL receipt hops + final send (cached files)
for sig,name,act in [('5xofsbAVP9','4wWwZsnt','SEND jlWSOL'),('5s2qR2aDAE','2Dgwmjsf','REDEEM'),('bf5DrEWWXT','2Dgwmjsf','SEND SOL')]:
    f=glob.glob(f'raw/sol/tx_{sig}*.json')[0]; s=os.path.basename(f)[3:-5]; ev[(s,name)]=(info(s),name,act,{},0)
print('KEY STEPS  (slot | +slots since previous step | UTC | wallet | action | cu_price µlamports)')
prev=None
for (sig,_),(i,name,act,tok,sol) in sorted(ev.items(),key=lambda kv:kv[1][0][0]):
    d=i[0]-prev if prev else 0; prev=i[0]
    print(f"  {i[0]}  +{d:>5}  {time.strftime('%H:%M:%S',time.gmtime(i[1]))}  {name:9} {act:11} SOL {sol:>10.2f}  {({k:round(v) for k,v in tok.items()})}  cu_price {i[3]}")
sp=[]
for r in T[key['6nBooPf9']]['flows']:
    if r['signer']==key['6nBooPf9'] and (r['out'] or r['err']): sp.append(info(r['sig'])+(r['err'],))
sp.sort(); gaps=[b[0]-a[0] for a,b in zip(sp,sp[1:])]
print(f"\nSPRAY 6nBooPf9: {len(sp)} send attempts, slots {sp[0][0]}→{sp[-1][0]} ({sp[-1][0]-sp[0][0]} slots ≈ {(sp[-1][1]-sp[0][1])} s)")
print('  slot gap histogram (gap: count):',sorted(collections.Counter(min(g,30) for g in gaps).items())[:16])
print('  same-slot pairs:',sum(1 for g in gaps if g==0),'| gap ≤2 slots:',sum(1 for g in gaps if g<=2),'of',len(gaps),'| median',statistics.median(gaps))
print('  compute (limit, price) used:',collections.Counter((x[2],x[3]) for x in sp).most_common(4))
fl=[x for x in sp if x[5]]; print(f'  failed: {len(fl)} attempts in slots {fl[0][0]}→{fl[-1][0]}' if fl else '  failed: 0')
cs=collections.Counter(); react=[]
for a,w in T.items():
    if w['depth']<3: continue
    fls=sorted(w['flows'],key=lambda r:r['t']); first_in=next((r for r in fls if r['dTok'].get('USDC',0)>1),None); done=False
    for r in fls:
        if r['signer']==a and r['out'] and not r['err']:
            i=info(r['sig']); cs[(i[2],i[3])]+=1
            if first_in and not done: react.append(i[0]-info(first_in['sig'])[0]); done=True
print(f"\nMESH: compute (limit, price) on sends:",cs.most_common(4))
print(f"  slots from first USDC in → first send: median {statistics.median(react)} | min {min(react)} | max {max(react)} | n {len(react)}")
print('\nGAS PRE-FUNDING (slots between gas top-up and first value movement)')
pf=[]
for a,w in T.items():
    fls=sorted(w['flows'],key=lambda r:r['t'])
    g=next((r for r in fls if r['signer']!=a and 0<r['dSOL']<0.2 and not r['dTok']),None); u=next((r for r in fls if r['dTok'] or abs(r['dSOL'])>=0.2),None)
    if g and u and g['t']<=u['t']: pf.append((info(u['sig'])[0]-info(g['sig'])[0],g['signer'],a))
fc=collections.Counter(s for _,s,_ in pf)
print('  gas funders:',[(s,n) for s,n in fc.most_common(4)])
print('  slots gas→use: median',statistics.median([d for d,_,_ in pf]),'| min',min(d for d,_,_ in pf),'| max',max(d for d,_,_ in pf),'| n',len(pf))
