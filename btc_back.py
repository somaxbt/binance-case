import json,urllib.request,time,glob,os,re,sqlite3,sys
get=lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
# known BTC addresses from every case + engine roots
known={}
for f in glob.glob(os.path.expanduser("~/cases/*/**/*.*"),recursive=True)+glob.glob(os.path.expanduser("~/traversal-engine/data/*.tsv"))+glob.glob(os.path.expanduser("~/traversal-engine/btc-engine/**/*.tsv"),recursive=True):
    if "/cases/binance/" in f or os.path.getsize(f)>200_000_000 or not f.endswith((".json",".tsv",".csv",".md",".txt")): continue
    case=f.split("/cases/")[1].split("/")[0] if "/cases/" in f else os.path.basename(f)
    try:
        for a in set(re.findall(r"\b(?:bc1q[0-9a-z]{38,58}|bc1p[0-9a-z]{58}|[13][1-9A-HJ-NP-Za-km-z]{25,34})\b",open(f,errors="ignore").read())): known.setdefault(a,set()).add(case)
    except Exception: pass
L=sqlite3.connect(os.path.expanduser("~/traversal-engine/data/labels.db"))
P=sqlite3.connect(os.path.expanduser("~/traversal-engine/timing-correlation/data/por-wallets.db"))
def label(a):
    r=L.execute("select name from labels where address=?",(a,)).fetchone(); p=P.execute("select exchange,wallet_type from por_wallets where address=?",(a,)).fetchone()
    return (r[0][:40] if r else "")+(f" PoR:{p[0]}/{p[1]}" if p else "")
print("known BTC addrs from cases:",len(known),file=sys.stderr)
info={}
def ainfo(a):
    if a not in info:
        s=get(f"https://blockstream.info/api/address/{a}")["chain_stats"]; time.sleep(0.45); info[a]=(s["tx_count"],s["funded_txo_sum"]/1e8)
    return info[a]
SERVICE_TX=150
start=sys.argv[1]; maxcalls=int(sys.argv[2])
rows=[]; seen=set(); q=[(start,0)]; calls=0; hits=[]
while q and calls<maxcalls:
    txid,dep=q.pop(0)
    if txid in seen: continue
    seen.add(txid)
    t=get(f"https://blockstream.info/api/tx/{txid}"); calls+=1; time.sleep(0.45)
    ts=time.strftime('%m-%d %H:%M',time.gmtime(t["status"].get("block_time",0)))
    for v in sorted(t["vin"],key=lambda v:-v["prevout"]["value"]):
        a=v["prevout"]["scriptpubkey_address"]; val=v["prevout"]["value"]/1e8
        n,tot=ainfo(a); calls+=1
        lb=label(a); kc=",".join(sorted(known.get(a,[])))
        svc = n>SERVICE_TX or bool(lb)
        rows.append((dep,ts,txid,a,round(val,8),n,round(tot,4),lb,kc,svc))
        flag=("  <<< IN CASE: "+kc) if kc else ""; flag+=("  [SERVICE? stop]" if svc else "")
        print(f"{dep:2} {ts} {a} in={val:.4f} txs={n} total_recv={tot:.2f} {lb}{flag}")
        if kc: hits.append((a,kc))
        if not svc and not kc and val>=0.2: q.append((v["txid"],dep+1))
json.dump({"rows":rows,"hits":hits},open(f"raw/btc_back_{start[:10]}.json","w"))
print("calls",calls,"hits",hits)
