import json,os,urllib.request,collections,sys
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
meta={}
def md(c):
    if c not in meta: meta[c]=rpc("alchemy_getTokenMetadata",[c]) or {}
    return meta[c]
for a in sys.argv[1:]:
    io={}
    for k in("fromAddress","toAddress"):
        io[k]=rpc("alchemy_getAssetTransfers",[{"fromBlock":"0x1915000",k:a,"category":["external","internal","erc20"],"withMetadata":True,"excludeZeroValue":True,"maxCount":"0x3e8"}])["transfers"]
    json.dump(io,open(f"raw/{a[:6]}_io.json","w"))
    print(f"\n== {a}")
    for k,lab,f in (("toAddress","IN ","from"),("fromAddress","OUT","to")):
        g=collections.defaultdict(lambda:[0,0,""])
        for t in io[k]: x=g[(t["asset"],t[f])]; x[0]+=t["value"] or 0; x[1]+=1; x[2]=x[2] or t["metadata"]["blockTimestamp"][5:16]
        for (s,cp),(v,n,ts) in sorted(g.items(),key=lambda x:-x[1][1])[:9]: print(f"  {lab} {s:8} {v:>16,.2f} n={n:<3} {ts} {cp}")
    bals=[b for b in rpc("alchemy_getTokenBalances",[a])["tokenBalances"] if int(b["tokenBalance"],16)>0]
    eth=int(rpc("eth_getBalance",[a,"latest"]),16)/1e18
    print("  HOLDS ETH",round(eth,3),[(md(b["contractAddress"]).get("symbol"),round(int(b["tokenBalance"],16)/10**(md(b["contractAddress"]).get("decimals") or 18),2)) for b in bals][:10])
