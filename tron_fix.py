import json,urllib.request,time,collections,hashlib
exec(open("tron_trace.py").read().split("TRXR=")[0])   # reuse helpers
def const_last(contract,sel,addr):
    d=get("https://api.trongrid.io/wallet/triggerconstantcontract",{"owner_address":"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb","contract_address":contract,"function_selector":sel,"parameter":b2h(addr)[2:].rjust(64,"0"),"visible":True})
    r=(d.get("constant_result") or [""])[0]; time.sleep(1.1); return int(r[-64:],16) if r else None
def tx(a,d):
    return [t for t in pull(a,d) if t.get("type")=="Transfer" and t["token_info"]["address"]==USDT]
# 1) TPBkSj real Transfers out + JustLend
o=tx("TPBkSjkCMn2ckrMuAP8n2J1jdjbw76bKN4","from"); i=tx("TPBkSjkCMn2ckrMuAP8n2J1jdjbw76bKN4","to")
g=collections.defaultdict(float)
for t in o: g[t["to"]]+=int(t["value"])/1e6
print("TPBkSj USDT in",sum(int(t["value"])/1e6 for t in i),"out:",{k:round(v) for k,v in g.items()})
for a in ["TPBkSjkCMn2ckrMuAP8n2J1jdjbw76bKN4","TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi","TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx"]:
    j=const_last(JUSDT,"balanceOf(address)",a); bb=const_last(JUSDT,"borrowBalanceStored(address)",a)
    print(a[:8],"jUSDT",j/1e8 if j else 0,"borrowUSDT",bb/1e6 if bb else 0)
# 2) TSUUVj profile: who else sends to it, since when
ii=pull("TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx","to")
srcs=collections.Counter(t["from"] for t in ii if t.get("type")=="Transfer")
d=get("https://api.trongrid.io/v1/accounts/TSUUVjysXV8YqHytSNjfkNXnnB49QDvZpx/transactions?limit=1&order_by=block_timestamp,asc"); time.sleep(1.1)
first=d.get("data",[{}])[0].get("block_timestamp")
print("TSUUVj first tx",time.strftime('%Y-%m-%d %H:%M',time.gmtime(first/1000)) if first else "?","| distinct trc20 senders since 20:00:",len(srcs),srcs.most_common(5))
ins=[(time.strftime('%H:%M',time.gmtime(t["block_timestamp"]/1000)),t["from"][:8],t["token_info"]["symbol"],int(t["value"])/10**t["token_info"]["decimals"]) for t in ii if t.get("type")=="Transfer"]
print(" big ins:",[x for x in ins if x[3]>=1e5][:10])
# 3) TG5iBM native TRX outs (46.38M TRX)
d=get("https://api.trongrid.io/v1/accounts/TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi/transactions?only_from=true&limit=200"); time.sleep(1.1)
for t in d.get("data",[]):
    c=t["raw_data"]["contract"][0]; p=c["parameter"]["value"]
    if c["type"]=="TransferContract" and p["amount"]>1e11: print(" TRX out",p["amount"]/1e6,"->",h2b(p["to_address"]),time.strftime('%H:%M',time.gmtime(t["block_timestamp"]/1000)),t["txID"][:16])
    elif c["type"]!="TransferContract": print(" other",c["type"],time.strftime('%H:%M',time.gmtime(t["block_timestamp"]/1000)))
