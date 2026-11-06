import json,os,urllib.request,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(net,m,p):
    r=urllib.request.Request(f"https://{net}.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    j=json.load(urllib.request.urlopen(r,timeout=90)); return j.get('result'),j.get('error')
A="0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c"
for net in ["opt-mainnet","arb-mainnet","avax-mainnet","base-mainnet","bnb-mainnet","matic-mainnet"]:
    cats=["external","erc20"]
    res={}
    for k in("toAddress","fromAddress"):
        r,e=rpc(net,"alchemy_getAssetTransfers",[{"fromBlock":"0x0",k:A,"category":cats,"withMetadata":True,"excludeZeroValue":True,"maxCount":"0x3e8"}])
        res[k]=(r or {}).get("transfers",[]) if not e else f"ERR {e.get('message','')[:60]}"
    json.dump(res,open(f"raw/l2_{net}.json","w"))
    bal,_=rpc(net,"eth_getBalance",[A,"latest"])
    print(f"\n== {net} native bal {int(bal,16)/1e18 if bal else '?'}")
    for k,lab,f in(("toAddress","IN ","from"),("fromAddress","OUT","to")):
        if isinstance(res[k],str): print(" ",lab,res[k]); continue
        g=collections.defaultdict(lambda:[0,0,""])
        for t in res[k]: x=g[(t["asset"],t[f])]; x[0]+=t["value"] or 0; x[1]+=1; x[2]=x[2] or ((t.get("metadata") or {}).get("blockTimestamp") or "?"*16)[5:16]
        for (s,cp),(v,n,ts) in sorted(g.items(),key=lambda x:-x[1][0])[:10]: print(f"  {lab} {s:8} {v:>16,.2f} n={n:<3} {ts} {cp}")
    tb,_=rpc(net,"alchemy_getTokenBalances",[A])
    if tb: print("  HOLDS tokens:",[(b["contractAddress"],int(b["tokenBalance"],16)) for b in tb["tokenBalances"] if int(b["tokenBalance"],16)>0][:8])
