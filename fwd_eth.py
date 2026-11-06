import json,os,urllib.request,sqlite3,sys,time
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"x"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get("result")
L=sqlite3.connect(os.path.expanduser("~/traversal-engine/data/labels.db")); P=sqlite3.connect(os.path.expanduser("~/traversal-engine/timing-correlation/data/por-wallets.db"))
def lab(a):
    r=L.execute("select name from labels where lower(address)=?",(a.lower(),)).fetchone(); p=P.execute("select exchange,wallet_type from por_wallets where address_lc=?",(a.lower(),)).fetchone()
    return (r[0][:45] if r else "")+(f" PoR:{p[0]}/{p[1]}" if p else "")
seen=set(); q=[(sys.argv[1].lower(),0)]; calls=0
while q and calls<120:
    a,dep=q.pop(0)
    if a in seen or dep>6: continue
    seen.add(a)
    n=int(rpc("eth_getTransactionCount",[a,"latest"]),16); code=len(rpc("eth_getCode",[a,"latest"]))//2; bal=int(rpc("eth_getBalance",[a,"latest"]),16)/1e18; calls+=3
    lb=lab(a)
    print(f"{'  '*dep}{a} nonce={n} code={code} bal={bal:,.3f} {('['+lb+']') if lb else ''}")
    if lb or (code>30): continue
    if n>300: print(f"{'  '*dep}   (busy wallet, nonce {n}: treat as service, stop)"); continue
    o=rpc("alchemy_getAssetTransfers",[{"fromBlock":"0x0","fromAddress":a,"category":["external","erc20"],"withMetadata":True,"order":"asc","maxCount":"0x64","excludeZeroValue":True}])["transfers"]; calls+=1
    agg={}
    for t in o:
        if t["asset"] not in ("ETH","USDT","USDC","WETH","DAI") or (t["value"] or 0)<1: continue
        tx=rpc("eth_getTransactionByHash",[t["hash"]]); calls+=1
        if tx["from"].lower()!=a: continue                      # poisoning / not signed by a
        k=(t["to"],t["asset"]); x=agg.setdefault(k,[0,0,t["metadata"]["blockTimestamp"][:16],tx["to"],tx["input"][:10]]); x[0]+=t["value"]; x[1]+=1
    for (to,asset),(v,cnt,ts,txto,sel) in sorted(agg.items(),key=lambda x:x[1][2]):
        tl=lab(to)
        print(f"{'  '*dep}   -> {ts} {v:,.3f} {asset} x{cnt} {to} {('['+tl+']') if tl else ''} via {txto[:12]} {sel}")
        q.append((to,dep+1))
