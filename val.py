import json,os,urllib.request,collections,glob
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
pad=lambda a:a[2:].lower().rjust(64,"0")
def call(t,d):
    try: r=rpc("eth_call",[{"to":t,"data":d},"latest"]); return int(r,16) if r and r!="0x" and len(r)<=66 else None
    except Exception: return None
BL={"USDT":"0xe47d6060","USDC":"0xfe575a87","RLUSD":None}
for f in ["0x9749_io","0x0ddf_io","0xb3dd_io","0x008f_io"]:
    io=json.load(open(f"raw/{f}.json"))
    print(f"\n== {f[:6]}")
    for s in ("USDT","USDC","RLUSD","ETH","WETH"):
        i=sum(t["value"] or 0 for t in io["toAddress"] if t["asset"]==s); o=collections.defaultdict(float)
        for t in io["fromAddress"]:
            if t["asset"]==s: o[t["to"]]+=t["value"] or 0
        if not i and not o: continue
        print(f"  {s}: in {i:,.2f} out {sum(o.values()):,.2f}")
        for to,v in sorted(o.items(),key=lambda x:-x[1])[:6]:
            if v<1 and s in("ETH","WETH") or v<100000 and s not in("ETH","WETH"): continue
            c=next(t["rawContract"]["address"] for t in io["fromAddress"] if t["to"]==to and t["asset"]==s)
            extra=""
            if s in("USDT","USDC","RLUSD") and c:
                b=call(c,"0x70a08231"+pad(to)); fz=[n for n,sl in {"isBlackListed":"0xe47d6060","isBlacklisted":"0xfe575a87","isFrozen":"0xe5839836","frozen":"0xd0516650"}.items() if call(c,sl+pad(to))==1]
                extra=f"now {b/1e6 if b is not None and s!='RLUSD' else (b/1e18 if b is not None else '?'):,.2f} frozen={fz}"
            else: extra=f"now ETH {int(rpc('eth_getBalance',[to,'latest']),16)/1e18:,.2f}"
            print(f"     -> {to} {v:,.2f} code={len(rpc('eth_getCode',[to,'latest']))//2} {extra}")
