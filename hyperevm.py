import json,urllib.request,time,sys
R="https://rpc.hyperliquid.xyz/evm"
def rpc(m,p):
    for i in range(5):
        try:
            r=urllib.request.Request(R,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"x"})
            j=json.load(urllib.request.urlopen(r,timeout=60)); time.sleep(0.25)
            if "error" in j: raise Exception(j["error"])
            return j["result"]
        except Exception as e:
            err=e; time.sleep(2*(i+1))
    raise err
head=int(rpc("eth_blockNumber",[]),16)
ts=lambda n:int(rpc("eth_getBlockByNumber",[hex(n),False])["timestamp"],16)
def find(t):
    lo,hi=1,head
    while lo<hi:
        mid=(lo+hi)//2
        if ts(mid)<t: lo=mid+1
        else: hi=mid
    return lo
A=sys.argv[1].lower(); t0=int(sys.argv[2]); hours=float(sys.argv[3])
b0=find(t0); b1=min(head,find(t0+int(hours*3600)))
print("head",head,"window blocks",b0,b1)
T="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"; pad="0x"+A[2:].rjust(64,"0")
out=[]
step=1000
for s in range(b0,b1,step):
    e=min(b1,s+step-1)
    for top in ([T,None,pad],[T,pad]):
        for lg in rpc("eth_getLogs",[{"fromBlock":hex(s),"toBlock":hex(e),"topics":top}]):
            out.append(lg)
seen=set()
for lg in sorted(out,key=lambda l:(int(l["blockNumber"],16),int(l["logIndex"],16))):
    k=(lg["transactionHash"],lg["logIndex"])
    if k in seen: continue
    seen.add(k)
    frm="0x"+lg["topics"][1][26:]; to="0x"+lg["topics"][2][26:]; v=int(lg["data"],16) if lg["data"]!="0x" else 0
    print(time.strftime('%m-%d %H:%M:%S',time.gmtime(ts(int(lg["blockNumber"],16)))),"token",lg["address"],"from",frm,"to",to,"raw",v,"tx",lg["transactionHash"])
json.dump(out,open(f"raw/hyperevm_{A[:8]}.json","w"))
