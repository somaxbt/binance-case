import json,os,urllib.request,collections,sys
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    j=json.load(urllib.request.urlopen(r,timeout=90)); return j.get('result'), j.get('error')
pad=lambda a:a[2:].lower().rjust(64,"0")
TOK={"USDT":"0xdac17f958d2ee523a2206206994597c13d831ec7","USDC":"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48","RLUSD":"0x8292bb45bf1ee4d140127049757c2e0ff06317ed"}
DEC={"USDT":6,"USDC":6,"RLUSD":18}
def bal(s,a): r,_=rpc("eth_call",[{"to":TOK[s],"data":"0x70a08231"+pad(a)},"latest"]); return int(r,16)/10**DEC[s] if r else None
def can_move(s,a):  # simulate transfer of 1 unit from a; revert => frozen
    r,e=rpc("eth_call",[{"from":a,"to":TOK[s],"data":"0xa9059cbb"+pad("0x000000000000000000000000000000000000dEaD")+hex(1)[2:].rjust(64,"0")},"latest"]); return e is None
seen=set(); queue=[(a,s,0) for a,s in [(x.split(":")[0],x.split(":")[1]) for x in sys.argv[1:]]]
holds=[]
while queue:
    a,s,dep=queue.pop(0)
    if (a,s) in seen or dep>3: continue
    seen.add((a,s))
    code=len(rpc("eth_getCode",[a,"latest"])[0])//2
    b=bal(s,a); mv=can_move(s,a) if b else None
    outs=rpc("alchemy_getAssetTransfers",[{"fromBlock":"0x1915000","fromAddress":a,"contractAddresses":[TOK[s]],"category":["erc20"],"withMetadata":True,"maxCount":"0x3e8"}])[0]["transfers"]
    g=collections.defaultdict(float)
    for t in outs: g[t["to"]]+=t["value"] or 0
    print(f"{'  '*dep}{a} [{s}] code={code} holds={b:,.2f} {'FROZEN' if mv is False else ('MOVABLE' if mv else '')} out={sum(g.values()):,.0f} to {len(g)}")
    if b and b>10000: holds.append((a,s,b,mv,code))
    if code>30: continue   # contract (pool/protocol): stop
    for to,v in sorted(g.items(),key=lambda x:-x[1])[:8]:
        if v>=1e6: queue.append((to,s,dep+1))
json.dump(holds,open("raw/hop4_holds.json","w"))
print("\nHOLDINGS >10k:"); [print(" ",h) for h in holds]
