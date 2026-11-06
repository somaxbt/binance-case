import json,urllib.request,time,hashlib,collections,re
B58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def h2b(h):
    b=bytes.fromhex(h); b+=hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]; n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=B58[r]+s
    return s
def get(u):
    for i in range(3):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
        except Exception: time.sleep(3)
    return {}
VAULTS={"THPaGKe6aZkUcNht24hcscZPLwtcJAbpun","TGSNahJvAdh86aR5pdcxiep1mBWSRK3HHL","TBAPnuwEht65McDbxDvDYs2XLRSSbYQMUM"}
T0=1793318400000
seen=set(); q=[("TRBdWqHnDVSZCVGfgHdKFLQPirQcA2PRki",0)]; memos=collections.Counter(); newaddr=[]
while q:
    a,dep=q.pop(0)
    if a in seen or dep>6 or a in VAULTS: continue
    seen.add(a)
    d=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions?only_from=true&min_timestamp={T0}&limit=200"); time.sleep(1.1)
    for t in d.get("data",[]):
        c=t["raw_data"]["contract"][0]; p=c["parameter"]["value"]
        memo=bytes.fromhex(t["raw_data"].get("data","")).decode("utf8","ignore") if t["raw_data"].get("data") else ""
        if memo.startswith("=") or memo.startswith("SWAP") or memo.startswith("s:"):
            dst=memo.split(":")[2] if memo.count(":")>=2 else memo
            memos[(memo.split(":")[1] if ':' in memo else '?',dst)]+=1
        if c["type"]=="TransferContract":
            to=h2b(p["to_address"]); v=p["amount"]/1e6
            if v>=50000 and to not in VAULTS: q.append((to,dep+1)); newaddr.append((a,to,v,time.strftime('%H:%M',time.gmtime(t["block_timestamp"]/1000))))
    u=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_from=true&min_timestamp={T0}&limit=200"); time.sleep(1.1)
    for t in u.get("data",[]):
        if t.get("type")=="Transfer" and int(t["value"])/1e6>=10000 and t["to"] not in VAULTS and t["token_info"]["symbol"]=="USDT": q.append((t["to"],dep+1))
print("wallets walked:",len(seen))
print("THORChain memo destinations:"); [print(" ",n,"x",k) for k,n in memos.most_common()]
json.dump({"seen":sorted(seen),"memos":[[k[0],k[1],n] for k,n in memos.items()]},open("raw/tron/trx_new.json","w"))
