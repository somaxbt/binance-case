import json,os,urllib.request,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
pad=lambda a:a[2:].lower().rjust(64,"0")
def call(t,data):
    try:
        r=rpc("eth_call",[{"to":t,"data":data},"latest"]); return int(r,16) if r and r!="0x" and len(r)<=66 else None
    except Exception: return None
SELS={"isBlackListed":"0xe47d6060","isBlacklisted":"0xfe575a87","isFrozen":"0xe5839836","frozen":"0xd0516650","blacklisted":"0xdbac26e9","isBlocked":"0xfbac3951","isAddressFrozen":"0x46267a93","isBanned":"0x97f735d5"}
A="0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c"
XAUT="0x68749665ff8d2d112fa859aa293f07a622782f38"
print("XAUt on 0x5227:",{n:call(XAUT,s+pad(A)) for n,s in SELS.items()})
d=json.load(open("raw/0x5227.json"))["out"]
WATCH={"RLUSD","WBETH","USDe","USDT","USDC","XAUt","PAXG","FDUSD","USD1","PYUSD","USDS","DAI","WBTC"}
g=collections.defaultdict(float); dec={}; con={}
for t in d:
    if t["asset"] in WATCH:
        c=t["rawContract"]["address"]; g[(t["asset"],c,t["to"])]+=t["value"]; dec[c]=int(t["rawContract"]["decimal"],16)
for (s,c,to),v in sorted(g.items(),key=lambda x:-x[1]):
    b=call(c,"0x70a08231"+pad(to)); fz=[n for n,sl in SELS.items() if call(c,sl+pad(to))==1]
    code=len(rpc("eth_getCode",[to,"latest"]))//2
    print(f"{s:6} {v:>16,.2f} -> {to} now {b/10**dec[c] if b is not None else '?':>16} frozen={fz} code={code}")
