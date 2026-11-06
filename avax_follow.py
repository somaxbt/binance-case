import json,urllib.request,time,os,sys
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U=f"https://avax-mainnet.g.alchemy.com/v2/{K}"
def rpc(m,p):
    for i in range(6):
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request(U,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json"}),timeout=60))
            if "error" in j: raise RuntimeError(j["error"])
            return j["result"]
        except Exception as e: err=e; time.sleep(2)
    raise err
hi=int(rpc("eth_blockNumber",[]),16)
nonce=lambda a,b:int(rpc("eth_getTransactionCount",[a,hex(b)]),16)
bal=lambda a,b:int(rpc("eth_getBalance",[a,hex(b)]),16)/1e18
def sent_txs(a,lo):
    n_hi=nonce(a,hi); out=[]
    for k in range(nonce(a,lo),n_hi):
        l,h=lo,hi
        while h-l>1:
            m=(l+h)//2
            if nonce(a,m)>k: h=m
            else: l=m
        blk=rpc("eth_getBlockByNumber",[hex(h),True])
        for t in blk["transactions"]:
            if t["from"].lower()==a.lower() and int(t["nonce"],16)==k:
                out.append((h,int(blk["timestamp"],16),t["hash"],t["to"],int(t["value"],16)/1e18,t["input"][:10])); lo=h-1
    return out
seen=set(); q=[(a,0) for a in sys.argv[1:]]; res=[]
while q:
    a,dep=q.pop(0)
    if a in seen or dep>5: continue
    seen.add(a)
    code=rpc("eth_getCode",[a,"latest"])
    if len(code)>50: print(f"{'  '*dep}{a} CONTRACT ({(len(code)-2)//2}B) — stop"); continue
    txs=sent_txs(a,98941961)
    print(f"{'  '*dep}{a} AVAX now {bal(a,hi):,.2f} sent {len(txs)} txs since 09:12")
    for b,ts,h,to,v,sel in txs:
        print(f"{'  '*dep}   {time.strftime('%m-%d %H:%M:%S',time.gmtime(ts))} {v:>14,.2f} AVAX -> {to} sel {sel} {h}")
        res.append((a,b,ts,h,to,v,sel))
        if v>=1000 and to: q.append((to.lower(),dep+1))
json.dump(res,open("raw/avax_follow.json","w"))
