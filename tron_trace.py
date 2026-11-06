import json,urllib.request,time,hashlib,collections
B58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def h2b(h):
    b=bytes.fromhex(h); b+=hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]; n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=B58[r]+s
    return s
def b2h(a):
    n=0
    for c in a: n=n*58+B58.index(c)
    return n.to_bytes(25,"big")[:21].hex()
def get(u,data=None):
    err=None
    for i in range(4):
        try:
            r=urllib.request.Request(u,json.dumps(data).encode() if data else None,{"User-Agent":"Mozilla/5.0","Content-Type":"application/json"})
            return json.load(urllib.request.urlopen(r,timeout=60))
        except Exception as e: time.sleep(3*(i+1)); err=e
    print("ERR",u[:70],err); return {}
USDT="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"; JUSDT="TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"
def const(contract,sel,addr):
    d=get("https://api.trongrid.io/wallet/triggerconstantcontract",{"owner_address":"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb","contract_address":contract,"function_selector":sel,"parameter":b2h(addr)[2:].rjust(64,"0"),"visible":True})
    r=(d.get("constant_result") or [None])[0]; time.sleep(1.1); return int(r,16) if r else None
def pull(a,direction):
    res=[];fp=None
    while True:
        u=f"https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_{direction}=true&min_timestamp=1793304000000&limit=200"+(f"&fingerprint={fp}" if fp else "")
        d=get(u); time.sleep(1.1); res+=d.get("data",[]); fp=d.get("meta",{}).get("fingerprint")
        if not fp or len(res)>2000: break
    return res
TRXR=h2b("41430b9b4a60d18affe500b731a97b5aa622c7863f"); print("TRX receiver:",TRXR)
seen=set(); q=[("TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi",0),(TRXR,0)]; rows=[]
while q:
    a,dep=q.pop(0)
    if a in seen or dep>4: continue
    seen.add(a)
    acc=(get(f"https://api.trongrid.io/v1/accounts/{a}").get("data") or [{}])[0]; time.sleep(1.1)
    trx=acc.get("balance",0)/1e6
    code=get("https://api.trongrid.io/wallet/getcontract",{"value":a,"visible":True}); time.sleep(1.1)
    isc=bool(code.get("bytecode")); name=code.get("name","")
    bal=const(USDT,"balanceOf(address)",a); bl=const(USDT,"isBlackListed(address)",a); j=const(JUSDT,"balanceOf(address)",a)
    o=pull(a,"from"); json.dump(o,open(f"raw/tron/{a}_out.json","w"))
    g=collections.defaultdict(float); first={}
    for t in o:
        if t["token_info"]["address"]==USDT: g[t["to"]]+=int(t["value"])/1e6; first.setdefault(t["to"],time.strftime('%H:%M',time.gmtime(t["block_timestamp"]/1000)))
    oth=collections.Counter(t["token_info"]["symbol"] for t in o if t["token_info"]["address"]!=USDT)
    lab=f"{'  '*dep}{a}{' [CONTRACT '+name+']' if isc else ''} USDT={bal/1e6 if bal is not None else -1:,.2f} frozen={bool(bl)} jUSDT={j or 0} TRX={trx:,.0f} usdt_out={sum(g.values()):,.0f}->{len(g)} other={dict(oth.most_common(3))}"
    print(lab); rows.append(lab)
    if isc: continue
    for to,v in sorted(g.items(),key=lambda x:-x[1])[:8]:
        if v>=1e6: print(f"{'  '*dep}   -> {to} {v:,.0f} @{first[to]}"); q.append((to,dep+1))
json.dump(rows,open("raw/tron/trace.json","w"))
