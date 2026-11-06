import json,os,urllib.request,sqlite3,sys
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"x"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get("result")
L=sqlite3.connect(os.path.expanduser("~/traversal-engine/data/labels.db"))
lab=lambda a:(L.execute("select name from labels where lower(address)=?",(a.lower(),)).fetchone() or [""])[0][:40]
KNOWN=set(json.load(open("raw/attacker_holdings.json"))["set"])|{x.lower() for x in "0xa97bf7836f8a08f9ed91d41453d371493fae8d10 0xc2096a12ebe0944f4d39e59979f485afd92d850a 0x15104a9ce0f08a8f0075a0869ae80e795fe0feb7 0xe88089b3d7aab7e89470753b3cb8511a7f9325ee 0xcf4ca2bdf21bc3a467a00b6afe72b833982723e0 0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c 0xb196981c37cfe105506613d1bd4153b9e63df92e 0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146".split()}
def real_in(a):
    i=rpc("alchemy_getAssetTransfers",[{"fromBlock":"0x0","toAddress":a,"category":["external","internal","erc20"],"withMetadata":True,"order":"asc","maxCount":"0x64","excludeZeroValue":True}])["transfers"]
    out=[]
    for t in i:
        if t["asset"]!="ETH" and t["asset"] not in("USDT","USDC","WETH","DAI"): continue
        if (t["value"] or 0)<0.01: continue
        out.append(t)
    return out
for a in sys.argv[1:]:
    a=a.lower(); ins=real_in(a)
    print(f"\n== {a} ETH {int(rpc('eth_getBalance',[a,'latest']),16)/1e18:,.3f} nonce {int(rpc('eth_getTransactionCount',[a,'latest']),16)}")
    for t in ins:
        f=t["from"]; tag="ATTACKER" if f in KNOWN else ("label:"+lab(f) if lab(f) else "FOREIGN?")
        print(f"   IN {t['metadata']['blockTimestamp'][5:19]} {t['value']:>12,.4f} {t['asset']:5} from {f} [{tag}] {t['category']}")
    o=rpc("alchemy_getAssetTransfers",[{"fromBlock":"0x0","fromAddress":a,"category":["external","internal","erc20"],"withMetadata":True,"order":"asc","maxCount":"0x32","excludeZeroValue":True}])["transfers"]
    for t in o:
        if (t["value"] or 0)<0.01: continue
        tx=rpc("eth_getTransactionByHash",[t["hash"]])
        if t["category"]=="external" and tx["from"].lower()!=a: continue
        print(f"   OUT {t['metadata']['blockTimestamp'][5:19]} {t['value']:>12,.4f} {t['asset']:5} -> {t['to']} [{lab(t['to'])}] tx.to={tx['to'][:12]} sel={tx['input'][:10]}")
