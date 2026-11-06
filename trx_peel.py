import json,urllib.request,time,hashlib,collections,os
B58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def h2b(h):
    b=bytes.fromhex(h); b+=hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]; n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=B58[r]+s
    return s
def get(u):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
        except Exception: time.sleep(3*(i+1))
    return {}
T0=1793318400000  # 10-30 00:00 UTC
def outs(a):
    res=[]
    d=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions?only_from=true&min_timestamp={T0}&limit=200"); time.sleep(1.1)
    for t in d.get("data",[]):
        c=t["raw_data"]["contract"][0]; p=c["parameter"]["value"]
        if c["type"]=="TransferContract": res.append(("TRX",h2b(p["to_address"]),p["amount"]/1e6,t["block_timestamp"],t["txID"]))
        elif c["type"]=="TriggerSmartContract": res.append(("CALL",h2b(p["contract_address"]),p.get("call_value",0)/1e6,t["block_timestamp"],t["txID"]))
    d=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_from=true&min_timestamp={T0}&limit=200"); time.sleep(1.1)
    for t in d.get("data",[]):
        if t.get("type")=="Transfer": res.append((t["token_info"]["symbol"],t["to"],int(t["value"])/10**t["token_info"]["decimals"],t["block_timestamp"],t["transaction_id"]))
    return res
def info(a):
    x=(get(f"https://api.trongrid.io/v1/accounts/{a}").get("data") or [{}])[0]; time.sleep(1.1)
    return x.get("balance",0)/1e6, x.get("type","Normal"), time.strftime('%Y-%m-%d',time.gmtime(x.get("create_time",0)/1000)) if x.get("create_time") else "?"
roots=["TYZ8AP4caGYmccXwexziAgr2x5CsGTxFws","TUoVsNvkSbCQFty1tLViCgvMjNRGGEK6eM","TDNF7CwfcKvgtaRPrMg4isijtf73kr8uRA","TYZ98phfoPWmiQhfHrYHvLW6jgnRXGuKpw","TXsZPPBhnnjdJcVASFTu633NXuhs3AXE9V"]
seen={}; parents=collections.defaultdict(set); edges=[]
q=[(r,0,r) for r in roots]
while q:
    a,dep,root=q.pop(0)
    parents[a].add(root)
    if a in seen or dep>5: continue
    bal,typ,created=info(a)
    o=outs(a); seen[a]=(dep,bal,typ,created,len(o))
    g=collections.defaultdict(float)
    for s,to,v,ts,h in o:
        g[(s,to)]+=v; edges.append((a,to,s,v,ts,h))
    print(f"{'  '*dep}{a} [{typ}, created {created}] bal {bal:,.0f} TRX | outs {len(o)}")
    if typ=="Contract" or len(o)>40: print(f"{'  '*dep}   (stop: contract/busy)"); continue
    for (s,to),v in sorted(g.items(),key=lambda x:-x[1])[:6]:
        if (s=="TRX" and v>=50000) or (s in("USDT","USDD","USDC") and v>=10000) or s=="CALL":
            print(f"{'  '*dep}   -> {s} {v:,.0f} {to}")
            if s!="CALL": q.append((to,dep+1,root))
json.dump({"seen":seen,"edges":edges,"parents":{k:list(v) for k,v in parents.items()}},open("raw/tron/trx_peel.json","w"))
conv={k:v for k,v in parents.items() if len(v)>1}
print("\nCONVERGENCE (nodes reached from >1 root):",conv)
