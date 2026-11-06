# fetch esplora paths -> raw json (1 req/s, 429 backoff). usage: fetch.py name path [name path ...]
import json,time,urllib.request,sys,os
B='https://blockstream.info/api'
def get(p):
    for i in range(5):
        try:
            time.sleep(1.0)
            with urllib.request.urlopen(urllib.request.Request(B+p,headers={'User-Agent':'x'}),timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(10*(i+1)); continue
            if e.code==404: return None
            raise
        except Exception: time.sleep(5*(i+1))
    raise SystemExit('fail '+p)
a=sys.argv[1:]
for n,p in zip(a[::2],a[1::2]):
    r=get(p); 
    if r is None: print('404',p); continue
    json.dump(r,open(n+'.json','w'))
    print('ok',n)
