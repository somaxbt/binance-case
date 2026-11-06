import json,sys,subprocess,time,datetime as dt,collections
S=sys.argv[1]; own=json.load(open(S+'/dydx_owners.json'))
USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
PROG={'CCTPiPYPc6AsJuwueEnWgSgucamXDZwBd53dQ11YiKX3':'CCTP-v1 TokenMessenger','CCTPV2vPZJS2u2BBsUoscuikbYjnpFmbFsvVuJdgUMQe':'CCTP-v2','JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4':'Jupiter v6','61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH':'Jupiter RFQ','jup3YeL8QhtSx1e253b2FDvsMNC87fDrgQZivbrndc9':'Jupiter Lend'}
def rpc(m,p):
    b=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p})
    for i in range(6):
        o=subprocess.run(['curl','-s','-m','40','-H','content-type: application/json','-H','accept-encoding: gzip','--compressed','-d',b,'https://api.mainnet-beta.solana.com'],capture_output=True,text=True).stdout
        try:
            j=json.loads(o)
            if 'result' in j: return j['result']
        except Exception: pass
        time.sleep(2+2*i)
cache={}
summary=collections.Counter(); out=[]
for ta,(owner,_,_) in own.items():
    sigs=rpc('getSignaturesForAddress',[ta,{"limit":50}]) or []
    for s in reversed(sigs):
        t=rpc('getTransaction',[s['signature'],{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]); time.sleep(0.5)
        if not t or t['meta']['err']: continue
        pre={(b['owner'],b['mint']):float(b['uiTokenAmount']['uiAmount'] or 0) for b in t['meta']['preTokenBalances']}
        post={(b['owner'],b['mint']):float(b['uiTokenAmount']['uiAmount'] or 0) for b in t['meta']['postTokenBalances']}
        keys=set(pre)|set(post)
        dl={k:round(post.get(k,0)-pre.get(k,0),4) for k in keys}
        mine=dl.get((owner,USDC),0)
        if mine>=-1: continue   # only outflows
        progs={i.get('programId') for i in t['transaction']['message']['instructions']}
        for ii in t['meta'].get('innerInstructions',[]):
            progs|={i.get('programId') for i in ii['instructions']}
        tag=[PROG[p] for p in progs if p in PROG]
        recv=[(k[0][:10],('USDC' if k[1]==USDC else k[1][:5]),v) for k,v in dl.items() if v>0 and k[0]!=owner]
        mychg=[(('USDC' if k[1]==USDC else k[1][:5]),v) for k,v in dl.items() if k[0]==owner and v!=0]
        solchg=None
        ak=[a['pubkey'] for a in t['transaction']['message']['accountKeys']]
        if owner in ak: i=ak.index(owner); solchg=round((t['meta']['postBalances'][i]-t['meta']['preBalances'][i])/1e9,3)
        k='+'.join(sorted(tag)) or 'plain transfer'
        summary[k]+=-mine
        out.append((dt.datetime.fromtimestamp(t['blockTime'],dt.UTC).strftime('%m-%d %H:%M:%S'),owner[:10],mine,k,recv[:3],mychg,solchg,s['signature']))
for o in sorted(out): print(o[:7])
print(summary)
json.dump(out,open(S+'/next_hops.json','w'))
