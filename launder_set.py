import json,urllib.request,time,re
get=lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
def txs(a,cap=300):
    out=[];last=None
    while True:
        b=get(f"https://blockstream.info/api/address/{a}/txs"+(f"/chain/{last}" if last else "")); time.sleep(0.5)
        if not b: break
        out+=b; last=b[-1]["txid"]
        if len(b)<25 or len(out)>=cap: break
    return out
S={}; memos=[]
for hub in ["bc1qxtl05lnr7jewlcg95yjq8k8llenyhsem0hdpp0","bc1qeeld470e89fuuqtce7wc2jy457z8e8nr82atq5"]:
    for t in txs(hub):
        ins={v["prevout"].get("scriptpubkey_address") for v in t["vin"]}
        for a in ins:
            if a and a!=hub: S.setdefault(a,set()).add(f"in:{hub[:10]}")
        if hub in ins:
            for o in t["vout"]:
                a=o.get("scriptpubkey_address")
                if a and a!=hub: S.setdefault(a,set()).add(f"out:{hub[:10]}")
                if o["scriptpubkey_type"]=="op_return":
                    m=bytes.fromhex(o["scriptpubkey"][4:]).decode("ascii","ignore"); memos.append((hub[:10],t["txid"],m))
dest=set()
for h,tx,m in memos:
    for x in re.findall(r"0x[0-9a-fA-F]{40}|bc1[0-9a-z]{25,62}|T[1-9A-HJ-NP-Za-km-z]{33}",m): dest.add(x)
print("counterparties",len(S),"memos",len(memos),"memo destinations",dest)
import collections; print("memo types",collections.Counter(m.split(':')[0]+':'+(m.split(':')[1] if ':' in m else '') for _,_,m in memos).most_common(8))
json.dump({"cp":{k:sorted(v) for k,v in S.items()},"memos":memos,"dest":sorted(dest)},open("raw/launder_set.json","w"))
