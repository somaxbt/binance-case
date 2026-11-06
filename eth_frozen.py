import sqlite3,json,os,urllib.request,urllib.error,time
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U=f"https://eth-mainnet.g.alchemy.com/v2/{K}"
def post(body):
    for i in range(8):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(U,json.dumps(body).encode(),{"Content-Type":"application/json","User-Agent":"x"}),timeout=90))
        except urllib.error.HTTPError as e:
            if e.code in (429,503): time.sleep(3*(i+1)); continue
            raise
pad=lambda a:a[2:].lower().rjust(64,"0")
c=sqlite3.connect("binance-eth-ledger.db"); r=c.execute("select run_id from ledger_run where leg='eth' order by started desc limit 1").fetchone()[0]
nodes=sorted({x[0] for x in c.execute("select distinct address from eth_node where run_id=?",(r,))})
tracked=[x[0] for x in c.execute("select distinct asset from eth_edge where run_id=? and cls='in:victim' and asset!='ETH'",(r,))]
sym={a:s for a,s in c.execute("select asset,max(symbol) from eth_edge where run_id=? group by asset",(r,))}
dres=post([{"jsonrpc":"2.0","id":i,"method":"eth_call","params":[{"to":t,"data":"0x313ce567"},"latest"]} for i,t in enumerate(tracked)])
dec={tracked[x["id"]]:(int(x["result"],16) if x.get("result") and x["result"]!="0x" else 18) for x in dres}
rows=[]
for n in nodes:
    res=[]
    for i in range(0,len(tracked),50):
        res+=post([{"jsonrpc":"2.0","id":j,"method":"eth_call","params":[{"to":t,"data":"0x70a08231"+pad(n)},"latest"]} for j,t in enumerate(tracked[i:i+50],start=i)])
    for x in res:
        v=x.get("result"); t=tracked[x["id"]]
        if not v or v=="0x" or int(v,16)==0: continue
        b=int(v,16)/10**dec[t]
        sim=post({"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"from":n,"to":t,"data":"0xa9059cbb"+pad("0x000000000000000000000000000000000000dEaD")+"1".rjust(64,"0")},"latest"]})
        rows.append((n,t,sym.get(t,"?"),b,1 if "error" in sim else 0))
json.dump(rows,open("raw/eth_token_holdings_live.json","w"))
blk=post({"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})["result"]
print("as of block",int(blk,16),"| token holdings > 0 at attacker wallets:",len(rows))
for n,t,s,b,f in sorted(rows,key=lambda x:(-x[4],x[2])):
    print(f"  {'FROZEN ' if f else 'movable'} {s:8} {b:>24,.6f}  at {n}  [{t}]")
