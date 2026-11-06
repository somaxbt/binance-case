# Scan Binance PoR BTC wallets for >=50 BTC outputs to non-PoR addrs in 2026-10-29 20:00-23:59 UTC.
import json, time, urllib.request, sys, os
B='https://blockstream.info/api'; OUT=os.path.expanduser('~/cases/binance/raw/btc')
T0,T1=1793304000,1793318400; MAXPAGES=int(os.environ.get('MAXPAGES',30))
por=[l.strip() for l in open(os.path.expanduser('~/cases/binance/agents/por_btc.txt')) if l.strip()]
P=set(por)
def get(p):
    for i in range(5):
        try:
            time.sleep(1.0)
            with urllib.request.urlopen(urllib.request.Request(B+p,headers={'User-Agent':'x'}),timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(10*(i+1)); continue
            raise
        except Exception as e: time.sleep(5*(i+1))
    raise SystemExit('fail '+p)
stats={}
sf=f'{OUT}/stats.json'
if os.path.exists(sf): stats=json.load(open(sf))
for a in por:
    if a not in stats:
        s=get(f'/address/{a}'); stats[a]={'tx':s['chain_stats']['tx_count'],'bal':(s['chain_stats']['funded_txo_sum']-s['chain_stats']['spent_txo_sum'])/1e8}
json.dump(stats,open(sf,'w'))
order=sorted(por,key=lambda a:stats[a]['tx'])
hits=[]; summary={}
for a in order:
    fn=f'{OUT}/txs_{a}.json'
    if os.path.exists(fn): txs=json.load(open(fn))
    else:
        txs=get(f'/address/{a}/txs'); txs=[t for t in txs if t['status'].get('confirmed')]
        pages=1
        while txs and len(txs)%25==0 and txs[-1]['status']['block_time']>=T0 and pages<MAXPAGES:
            nxt=get(f"/address/{a}/txs/chain/{txs[-1]['txid']}");
            if not nxt: break
            txs+=nxt; pages+=1
        reached = (not txs) or txs[-1]['status']['block_time']<T0 or len(txs)%25!=0
        json.dump({'reached_window_start':reached,'txs':[t for t in txs if t['status']['block_time']>=T0-3600]},open(fn,'w'))
        txs=json.load(open(fn))
    reached=txs['reached_window_start']; tl=txs['txs']
    n=0
    for t in tl:
        bt=t['status']['block_time']
        if not (T0<=bt<T1): continue
        if not any(v['prevout'] and v['prevout'].get('scriptpubkey_address')==a for v in t['vin']): continue
        n+=1
        for i,o in enumerate(t['vout']):
            d=o.get('scriptpubkey_address'); v=o['value']/1e8
            if v>=50 and d not in P:
                hits.append(dict(txid=t['txid'],vout=i,time=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(bt)),block=t['status']['block_height'],src=a,dst=d,btc=v))
    summary[a]=dict(tx=stats[a]['tx'],bal=stats[a]['bal'],spends_in_window=n,reached=reached)
    print(a,stats[a]['tx'],round(stats[a]['bal'],2),'spends',n,'reached',reached,flush=True)
json.dump({'summary':summary,'hits':hits},open(f'{OUT}/scan_result.json','w'),indent=1)
print('HITS',len(hits),sum(h['btc'] for h in hits))
