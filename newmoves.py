import json,os,urllib.request,sqlite3,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"x"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get("result")
L=sqlite3.connect(os.path.expanduser("~/traversal-engine/data/labels.db"))
lab=lambda a:(L.execute("select name from labels where lower(address)=?",(a.lower(),)).fetchone() or [""])[0][:40]
FROM=hex(26302600)  # ~10-30 00:00
W={"0x5227":"0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c","0xcf4c":"0xcf4ca2bdf21bc3a467a00b6afe72b833982723e0","0x1510":"0x15104a9ce0f08a8f0075a0869ae80e795fe0feb7","0xe880":"0xe88089b3d7aab7e89470753b3cb8511a7f9325ee"}
for k,a in W.items():
    o=rpc("alchemy_getAssetTransfers",[{"fromBlock":FROM,"fromAddress":a,"category":["external","internal"],"withMetadata":True,"order":"desc","maxCount":"0x32","excludeZeroValue":True}])["transfers"]
    real=[]
    for t in o:
        if (t["value"] or 0)<1: continue
        tx=rpc("eth_getTransactionByHash",[t["hash"]])
        if t["category"]=="external" and tx["from"].lower()!=a: continue   # poisoning
        real.append(t)
    print(f"\n== {k} real ETH outs since 00:00 (>=1 ETH):")
    for t in real[:10]:
        to=t["to"]; code=len(rpc("eth_getCode",[to,"latest"]))//2; bal=int(rpc("eth_getBalance",[to,"latest"]),16)/1e18; n=int(rpc("eth_getTransactionCount",[to,"latest"]),16)
        print(f"  {t['metadata']['blockTimestamp'][11:19]} {t['value']:>12,.3f} ETH -> {to} [{lab(to)}] code={code} bal={bal:,.2f} nonce={n}")
