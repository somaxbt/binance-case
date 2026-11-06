# Forward trace from attacker hop-1 txs, highest-value first, cap MAXTX traced txs. Raw cached in tx/.
import json,time,urllib.request,os,heapq,sqlite3
B='https://blockstream.info/api'; os.makedirs('tx',exist_ok=True)
MAXTX=int(os.environ.get('MAXTX',40))
def get(p,cache=None):
    if cache and os.path.exists(cache): return json.load(open(cache))
    for i in range(5):
        try:
            time.sleep(1.0)
            with urllib.request.urlopen(urllib.request.Request(B+p,headers={'User-Agent':'x'}),timeout=30) as r: d=json.load(r)
            if cache: json.dump(d,open(cache,'w'))
            return d
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(10*(i+1)); continue
            raise
        except Exception: time.sleep(5*(i+1))
    raise SystemExit('fail '+p)
lab=sqlite3.connect(os.path.expanduser('~/traversal-engine/data/labels.db'))
att=sqlite3.connect(os.path.expanduser('~/traversal-engine/data/attrib.db'))
por=sqlite3.connect(os.path.expanduser('~/traversal-engine/timing-correlation/data/por-wallets.db'))
def label(a):
    r=lab.execute('select name,nameTag,category from labels where address=?',(a,)).fetchone()
    if r: return 'labels:'+'/'.join(r)
    r=att.execute('select e.name,a.category,a.confidence from attrib a join entity_ref e on e.id=a.entity_id where a.address=? ',(a,)).fetchone() if True else None
    if r: return 'attrib:'+'/'.join(map(str,r))
    r=por.execute('select exchange,wallet_type from por_wallets where address=?',(a,)).fetchone()
    if r: return 'por:'+'/'.join(r)
    return ''
X='bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm'
seed=[t['txid'] for t in json.load(open('a_X_txs.json')) if any(v['prevout']['scriptpubkey_address']==X for v in t['vin'])]
pq=[(0,t,None) for t in seed]; seen=set(); edges=[]; rests=[]; leads=[]; ends=[]; n=0
while pq:
    negv,txid,parent=heapq.heappop(pq)
    if txid in seen: continue
    if n>=MAXTX: leads.append(dict(txid=txid,from_out=parent,btc=-negv/1e8)); continue
    seen.add(txid); n+=1
    t=get(f'/tx/{txid}',f'tx/{txid}.json'); os_=get(f'/tx/{txid}/outspends',f'tx/{txid}_os.json') if t['status'].get('confirmed') else get(f'/tx/{txid}/outspends')
    ins={}
    for v in t['vin']: a=v['prevout']['scriptpubkey_address']; ins[a]=ins.get(a,0)+v['prevout']['value']
    bt=t['status'].get('block_time'); ts=time.strftime('%m-%d %H:%M',time.gmtime(bt)) if bt else 'mempool'
    edges.append(dict(txid=txid,time=ts,block=t['status'].get('block_height'),nin=len(t['vin']),ins={a:v/1e8 for a,v in ins.items()},fee=t['fee'],
        outs=[(o.get('scriptpubkey_address'),o['value']/1e8,s.get('spent'),s.get('txid')) for o,s in zip(t['vout'],os_)]))
    for i,(o,s) in enumerate(zip(t['vout'],os_)):
        a=o.get('scriptpubkey_address'); v=o['value']; L=label(a) if a else ''
        if v<10_000_000: continue   # <0.1 BTC dust/fee change ignored (ponytail: report if many)
        if L: ends.append(dict(txid=txid,vout=i,addr=a,btc=v/1e8,label=L,spent=s.get('spent'))); continue
        if not s.get('spent'): rests.append(dict(txid=txid,vout=i,addr=a,btc=v/1e8,time=ts)); continue
        heapq.heappush(pq,(-v,s['txid'],f'{txid}:{i}'))
json.dump(dict(edges=edges,rests=rests,leads=leads,ends=ends),open('trace_result.json','w'),indent=1)
print('traced',n,'rests',len(rests),round(sum(r['btc'] for r in rests),4),'leads',len(leads),round(sum(l['btc'] for l in leads),4),'ends',len(ends))
