import json,os,urllib.request,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    j=json.load(urllib.request.urlopen(r,timeout=120)); return j.get('result'),j.get('error')
OP="0x7c8601d4645b93cea45f71e118a729332e6b5ca0"
# all B14 erc20+external outflows since delegation; group by tx; multi-asset txs are sweep candidates
out=[];pk=None;pages=0
while True:
    q={"fromBlock":hex(26300753),"fromAddress":"0x28c6c06298d514db089934071355e5743bf21d60","category":["external","erc20"],"withMetadata":True,"excludeZeroValue":True,"maxCount":"0x3e8"}
    if pk:q["pageKey"]=pk
    r,e=rpc("alchemy_getAssetTransfers",[q]); out+=r["transfers"]; pk=r.get("pageKey"); pages+=1
    if not pk or pages>=40: break
print("B14 transfers since delegation:",len(out),"pages",pages,"more" if pk else "complete","last",out[-1]["metadata"]["blockTimestamp"])
by=collections.defaultdict(list)
for t in out: by[t["hash"]].append(t)
cand=[h for h,ts in by.items() if len(ts)>=3 or any((t["value"] or 0)>1e6 and t["asset"] in("USDT","USDC") for t in ts)]
sweeps=[]
for h in cand:
    tx,_=rpc("eth_getTransactionByHash",[h])
    if tx["from"].lower()==OP or tx["input"][:10]=="0x8a179be4":
        ts=by[h]; sweeps.append(h)
        print("SWEEP",h,ts[0]["metadata"]["blockTimestamp"],len(ts),"assets ->",collections.Counter(t["to"] for t in ts).most_common(2),"from",tx["from"])
json.dump({"sweeps":sweeps},open("raw/b14_sweeps.json","w"))
# when was delegation removed? find B14 code over time: check current + note
print("B14 code now:",rpc("eth_getCode",["0x28c6c06298d514db089934071355e5743bf21d60","latest"])[0])
