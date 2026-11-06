import json,os,urllib.request,datetime,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U=f"https://eth-mainnet.g.alchemy.com/v2/{K}"
def rpc(m,p):
    r=urllib.request.Request(U,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
B14="0x28C6c06298d514Db089934071355E5743bf21d60"; B0=26300753
print("delegation ts",datetime.datetime.utcfromtimestamp(1793305259))
out=[];pk=None
while True:
    q={"fromBlock":hex(B0),"toBlock":hex(B0+60),"fromAddress":B14,"category":["external","internal","erc20"],"withMetadata":True,"excludeZeroValue":True,"maxCount":"0x3e8"}
    if pk:q["pageKey"]=pk
    r=rpc("alchemy_getAssetTransfers",[q]); out+=r["transfers"]; pk=r.get("pageKey")
    if not pk:break
json.dump(out,open("raw/b14_out.json","w"))
by=collections.defaultdict(list)
for t in out: by[t["hash"]].append(t)
for h,ts in by.items():
    tos=collections.Counter(t["to"] for t in ts)
    print(h,int(ts[0]["blockNum"],16),ts[0]["metadata"]["blockTimestamp"],len(ts),"transfers; to:",dict(tos.most_common(4)))
agg=collections.defaultdict(float)
for t in out: agg[(t["to"],t["asset"],(t.get("rawContract") or {}).get("address"))]+=t["value"] or 0
for k,v in sorted(agg.items(),key=lambda x:-x[1])[:15]: print(k,round(v,4))
sw=[h for h in by if len(by[h])>5]
if sw:
    tx=rpc("eth_getTransactionByHash",[sw[0]]); print("sweep tx from",tx["from"],"to",tx["to"],"type",tx["type"],"sel",tx["input"][:10])
print("contract 0x63e8 codelen",len(rpc("eth_getCode",["0x63e842b054bd624a465454d533c33f573e9c6fae","latest"]))//2)
r=rpc("alchemy_getAssetTransfers",[{"toAddress":"0x7c8601d4645b93cea45f71e118a729332e6b5ca0","category":["external","internal"],"order":"asc","maxCount":"0x5","withMetadata":True}])
for t in r["transfers"]: print("fund 0x7c86 <-",t["from"],t["value"],t["metadata"]["blockTimestamp"],t["hash"])
