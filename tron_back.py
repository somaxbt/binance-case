import json,urllib.request,time,hashlib,sqlite3,collections,sys
B58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def h2b(h):
    b=bytes.fromhex(h); b+=hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]; n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=B58[r]+s
    return s
def get(u,data=None):
    for i in range(6):
        try:
            r=urllib.request.Request(u,json.dumps(data).encode() if data else None,{"User-Agent":"Mozilla/5.0","Content-Type":"application/json"})
            x=json.load(urllib.request.urlopen(r,timeout=60)); time.sleep(1.6); return x
        except urllib.error.HTTPError as e:
            if e.code in (429,503): time.sleep(8*(i+1)); continue
            raise
    return {}
c=sqlite3.connect("binance-live.db")
ATK={r[0] for r in c.execute("select distinct address from ledger_node")}|{r[0] for r in c.execute("select distinct too from ledger_edge where cls='out:attacker'")}
SWAP={"TTu9T4ff4zvNPz1dfAd36gUeB3xJgYz4G9":"BWSwapRouterV1","TQqgNg13s2DjvXhW1ky4v6TsR8wZGvb7Y4":"SunSwap UniversalRouter","TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx":"SunSwap WTRX-USDT pool","TVjuTE3V5bMVdpfNhid8kD2v35T2k1u1Br":"SunSwap v4 PoolManager"}
T0=1793304000000
def inflows(a):
    res=[]
    d=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_to=true&min_timestamp={T0}&limit=200")
    for t in d.get("data",[]):
        if t.get("type")=="Transfer" and t["token_info"]["address"]=="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": res.append(("USDT",t["from"],int(t["value"])/1e6,t["block_timestamp"],t["transaction_id"]))
    d=get(f"https://api.trongrid.io/v1/accounts/{a}/transactions?only_to=true&min_timestamp={T0}&limit=200")
    for t in d.get("data",[]):
        if "raw_data" not in t: continue
        cc=t["raw_data"]["contract"][0]; p=cc["parameter"]["value"]
        if cc["type"]=="TransferContract" and p["amount"]>=1e6: res.append(("TRX",h2b(p["owner_address"]),p["amount"]/1e6,t["block_timestamp"],t["txID"]))
    return res
def swap_initiator(txid):
    t=get("https://api.trongrid.io/wallet/gettransactionbyid",{"value":txid})
    try: return h2b(t["raw_data"]["contract"][0]["parameter"]["value"]["owner_address"]), h2b(t["raw_data"]["contract"][0]["parameter"]["value"].get("contract_address","41"+"0"*40))
    except Exception: return None,None
seen=set(); q=[(a,0) for a in sys.argv[1:]]
while q:
    a,dep=q.pop(0)
    if a in seen or dep>4: continue
    seen.add(a)
    acc=(get(f"https://api.trongrid.io/v1/accounts/{a}").get("data") or [{}])[0]
    created=time.strftime('%m-%d %H:%M',time.gmtime(acc.get("create_time",0)/1000))
    print(f"{'  '*dep}{a} created {created} TRX bal {acc.get('balance',0)/1e6:,.0f} {'[ATTACKER per ledger]' if a in ATK else ''}")
    ins=inflows(a)
    agg=collections.defaultdict(lambda:[0,0,None])
    for asset,f,v,ts,h in ins: x=agg[(asset,f)]; x[0]+=v; x[1]+=1; x[2]=x[2] or h
    for (asset,f),(v,n,h) in sorted(agg.items(),key=lambda x:-x[1][0])[:8]:
        tag="[ATTACKER per ledger]" if f in ATK else (f"[{SWAP[f]}]" if f in SWAP else "")
        extra=""
        if f in SWAP or (asset=="USDT" and f not in ATK):
            ini,ct=swap_initiator(h)
            if ini and ini!=f: extra=f" | tx sent by {ini}{' [ATTACKER per ledger]' if ini in ATK else ''} to {SWAP.get(ct,ct)}"
            if ini in ATK: tag+=" ⇐ swap initiated by attacker"
        print(f"{'  '*dep}   <- {asset} {v:>14,.2f} x{n} from {f} {tag}{extra}")
        if f not in ATK and f not in SWAP and v>=1000 and (not extra or "ATTACKER" not in extra): q.append((f,dep+1))
