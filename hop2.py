import json,os,urllib.request,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U=f"https://eth-mainnet.g.alchemy.com/v2/{K}"
def rpc(m,p):
    r=urllib.request.Request(U,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
sw=[t for t in json.load(open("raw/b14_out.json")) if t["hash"].startswith("0x53bd")]
print("sweep ETH:",[t["value"] for t in sw if t["asset"]=="ETH"],"| assets:",len(sw))
def pull(**q):
    out=[];pk=None
    while True:
        qq={"fromBlock":"0x1915000","category":["external","internal","erc20"],"withMetadata":True,"excludeZeroValue":True,"maxCount":"0x3e8",**q}
        if pk:qq["pageKey"]=pk
        r=rpc("alchemy_getAssetTransfers",[qq]); out+=r["transfers"]; pk=r.get("pageKey")
        if not pk or len(out)>5000:break
    return out
for name,a in [("0x5227","0x5227f603C1eE34CE3C06eFe6477003BDfCCB2f8c"),("0x8532","0x8532FA14ACAf483729C449b8458aedDb900543D4")]:
    o=pull(fromAddress=a); i=pull(toAddress=a)
    json.dump({"out":o,"in":i},open(f"raw/{name}.json","w"))
    agg=collections.defaultdict(lambda:[0.0,0,None,None])
    for t in o:
        k=(t["to"],t["asset"]); g=agg[k]; g[0]+=t["value"] or 0; g[1]+=1; g[2]=g[2] or t["metadata"]["blockTimestamp"]; g[3]=t["metadata"]["blockTimestamp"]
    print(f"\n{name} OUT ({len(o)} transfers) top by count/value:")
    for k,v in sorted(agg.items(),key=lambda x:-(x[1][0] if x[0][1] in("ETH","USDT","USDC","WETH") else 0))[:14]: print(" ",k,round(v[0],2),f"n={v[1]}",v[2][11:19],"->",v[3][11:19])
    ia=collections.defaultdict(float)
    for t in i: ia[(t["from"],t["asset"])]+=t["value"] or 0
    print(f"{name} IN top:")
    for k,v in sorted(ia.items(),key=lambda x:-x[1] if x[0][1] in("ETH","USDT","USDC","WETH") else 0)[:6]: print(" ",k,round(v,2))
