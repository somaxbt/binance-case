import json,urllib.request,time
get=lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
TARGET=set(json.load(open("raw/btc_eeld_funding.json"))["srcs"])|{"bc1qeeld470e89fuuqtce7wc2jy457z8e8nr82atq5","bc1qxtl05lnr7jewlcg95yjq8k8llenyhsem0hdpp0"}
START="bc1qvmnnu4jxrmgc2n3u7ph234hmc9hp2a3rk6hf9e"
# spends of START from Sep 26 on: follow outputs forward (UTXO walk), depth<=8, cap 120 tx fetches
calls=0
def addr_txs(a):
    global calls; out=[];last=None
    while True:
        b=get(f"https://blockstream.info/api/address/{a}/txs"+(f"/chain/{last}" if last else "")); calls+=1; time.sleep(0.5)
        if not b: break
        out+=b; last=b[-1]["txid"]
        if len(b)<25 or len(out)>=100: break
    return out
def outspends(txid):
    global calls; calls+=1; time.sleep(0.5); return get(f"https://blockstream.info/api/tx/{txid}/outspends")
txs=addr_txs(START)
sends=[t for t in txs if any(v["prevout"].get("scriptpubkey_address")==START for v in t["vin"])]
print(START,"spending txs:",len(sends))
frontier=[(t["txid"],0,[START]) for t in sends]; seen=set(); found=[]
while frontier and calls<160:
    txid,dep,path=frontier.pop(0)
    if txid in seen or dep>8: continue
    seen.add(txid)
    t=get(f"https://blockstream.info/api/tx/{txid}"); calls+=1; time.sleep(0.5)
    sp=outspends(txid)
    for i,o in enumerate(t["vout"]):
        a=o.get("scriptpubkey_address"); v=o["value"]/1e8
        if not a or v<0.5: continue
        if a in TARGET:
            found.append((path+[a],txid,v,time.strftime('%m-%d %H:%M',time.gmtime(t["status"].get("block_time",0)))))
            print("HIT",a,v,"via",txid[:16],"path len",len(path)); continue
        if i<len(sp) and sp[i].get("spent"): frontier.append((sp[i]["txid"],dep+1,path+[a]))
print("calls",calls,"found",len(found))
json.dump(found,open("raw/bitget_link_found.json","w"))
for p,tx,v,ts in found[:5]: print(ts,v,"BTC  path:"," -> ".join(x[:12] for x in p))
