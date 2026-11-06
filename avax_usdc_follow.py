import json,urllib.request,time,os,sys,collections
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
U=f"https://avax-mainnet.g.alchemy.com/v2/{K}"
def rpc(m,p):
    for i in range(6):
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request(U,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json"}),timeout=60))
            if "error" in j: raise RuntimeError(j["error"])
            return j["result"]
        except Exception as e: err=e; time.sleep(2)
    raise err
T="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DFB={"0x2fa9ca894982930190727e75500a97d8dc500233a5065e0f3126c48fbe0343c0":"CCTPv1 DepositForBurn","0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5":"CCTPv2 DepositForBurn"}
DOM={0:"Ethereum",1:"Avalanche",2:"OP",3:"Arbitrum",5:"Solana",6:"Base",7:"Polygon",10:"Unichain",11:"Linea",13:"Sonic",14:"World Chain",19:"HyperEVM"}
USDC="0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
hi=int(rpc("eth_blockNumber",[]),16)
nonce=lambda a,b:int(rpc("eth_getTransactionCount",[a,hex(b)]),16)
def sent(a,lo=98950000):
    out=[]
    for k in range(nonce(a,lo),nonce(a,hi)):
        l,h=lo,hi
        while h-l>1:
            m=(l+h)//2
            if nonce(a,m)>k: h=m
            else: l=m
        blk=rpc("eth_getBlockByNumber",[hex(h),True])
        for t in blk["transactions"]:
            if t["from"].lower()==a and int(t["nonce"],16)==k: out.append((int(blk["timestamp"],16),t))
        lo=h-1
    return out
agg=collections.Counter()
for a in sys.argv[1:]:
    a=a.lower(); print(f"\n== {a}")
    for ts,t in sent(a):
        rc=rpc("eth_getTransactionReceipt",[t["hash"]]); notes=[]
        for l in rc["logs"]:
            t0=l["topics"][0]
            if t0==T and l["address"].lower()==USDC and ("0x"+l["topics"][1][26:])==a:
                notes.append(f"USDC {int(l['data'],16)/1e6:,.2f} -> 0x{l['topics'][2][26:]}")
            if t0 in DFB:
                w=[l["data"][2+i*64:2+(i+1)*64] for i in range((len(l["data"])-2)//64)]
                if t0.startswith("0x0c8c"):   # v2: data = amount, mintRecipient, destinationDomain, ...
                    amt=int(w[0],16)/1e6; rcp="0x"+w[1][24:]; dom=int(w[2],16)
                else:                          # v1: data = amount, mintRecipient, destinationDomain, destinationTokenMessenger, destinationCaller
                    amt=int(w[0],16)/1e6; rcp="0x"+w[1][24:]; dom=int(w[2],16)
                notes.append(f"{DFB[t0]} {amt:,.2f} USDC -> {DOM.get(dom,dom)} recipient {rcp}"); agg[(DOM.get(dom,dom),rcp)]+=amt
        print(f"  {time.strftime('%m-%d %H:%M:%S',time.gmtime(ts))} to {t['to']} sel {t['input'][:10]} status {rc['status']} | {'; '.join(notes) or ('AVAX '+str(int(t['value'],16)/1e18))}  {t['hash'][:16]}")
print("\nCCTP destinations:",{f"{k[0]}:{k[1]}":round(v,2) for k,v in agg.items()})
