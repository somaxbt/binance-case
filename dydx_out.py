import json,subprocess,sys,time,urllib.parse
nf=json.load(open('/Users/somuknr/cases/binance/raw/sol/noble_forwarding.json'))
B='https://dydx-rest.publicnode.com/cosmos/tx/v1beta1/txs'
out={}
for nob,v in nf.items():
    a=v['recipient']; txs=[]
    for q in (f"message.sender='{a}'", f"transfer.recipient='{a}'"):
        for page in range(1,6):
            u=B+'?'+urllib.parse.urlencode({'query':q,'pagination.limit':100,'page':page,'order_by':'ORDER_BY_ASC'})
            r=json.loads(subprocess.run(['curl','-s','-m','40','-H','accept-encoding: gzip','--compressed',u],capture_output=True,text=True).stdout or '{}')
            tr=r.get('tx_responses',[]); txs+= [(q[:7],t) for t in tr]
            if len(tr)<100: break
            time.sleep(0.3)
    out[a]=[(k,t['txhash'],t['timestamp'],[m for m in t['tx']['body']['messages']]) for k,t in txs]
    print(a, v['usdc'], len(txs), file=sys.stderr)
json.dump(out,open(sys.argv[1],'w'))
