import json,os,urllib.request,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p,net="eth-mainnet"):
    r=urllib.request.Request(f"https://{net}.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    j=json.load(urllib.request.urlopen(r,timeout=90)); return j.get('result')
pad=lambda a:a[2:].lower().rjust(64,"0")
def call(t,data,net="eth-mainnet"):
    try:
        r=rpc("eth_call",[{"to":t,"data":data},"latest"],net); return int(r,16) if r and r!="0x" and len(r)<=66 else None
    except Exception: return None
A="0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c"
BIN={"0x28c6c06298d514db089934071355e5743bf21d60","0xdfd5293d8e347dfe59e90efd55b2956a1343963d","0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055"}
d=json.load(open("raw/0x5227.json"))
stolen=collections.defaultdict(float); sym={}; dec={}
for t in d["in"]:
    if t["from"] in BIN:
        c=(t.get("rawContract") or {}).get("address") or "eth"; stolen[c]+=t["value"] or 0; sym[c]=t["asset"]
        if t.get("rawContract",{}).get("decimal"): dec[c]=int(t["rawContract"]["decimal"],16)
outs=collections.defaultdict(float)
for t in d["out"]:
    c=(t.get("rawContract") or {}).get("address") or "eth"; outs[c]+=t["value"] or 0
# prices at sweep time
ts=1793305463
keys=",".join("coingecko:ethereum" if c=="eth" else f"ethereum:{c}" for c in stolen)
px=json.load(urllib.request.urlopen(urllib.request.Request(f"https://coins.llama.fi/prices/historical/{ts}/{keys}",headers={"User-Agent":"Mozilla/5.0"}),timeout=60))["coins"]
P={c:(px.get("coingecko:ethereum" if c=="eth" else f"ethereum:{c}") or {}).get("price") for c in stolen}
SELS={"isBlackListed":"0xe47d6060","isBlacklisted":"0xfe575a87","isFrozen":"0xe5839836","frozen":"0xd0516650","blacklisted":"0xdbac26e9"}
rows=[]
for c,v in stolen.items():
    if c=="eth": now=int(rpc("eth_getBalance",[A,"latest"]),16)/1e18; fz=None
    else:
        b=call(c,"0x70a08231"+pad(A)); now=b/10**dec.get(c,18) if b is not None else None
        fz=[n for n,s in SELS.items() if call(c,s+pad(A))==1] or None
    rows.append((sym[c],c,v,now,P[c],fz))
json.dump(rows,open("raw/recon.json","w"))
tot=sum(v*(p or 0) for _,_,v,_,p,_ in rows); priced=sum(1 for r in rows if r[4])
print(f"ETH-side stolen into 0x5227: {len(rows)} assets, ≈${tot/1e6:,.1f}M at theft-time prices ({priced} priced)")
print(f"{'sym':8}{'stolen':>20}{'still@0x5227':>20}{'$M stolen':>11}  freeze")
for s,c,v,now,p,fz in sorted(rows,key=lambda r:-(r[2]*(r[4] or 0)))[:30]:
    print(f"{s[:8]:8}{v:>20,.2f}{(now if now is not None else -1):>20,.2f}{v*(p or 0)/1e6:>11,.2f}  {fz or ''}")
unp=[(s,c) for s,c,v,n,p,f in rows if not p]; print("unpriced:",unp)
