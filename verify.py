import json,os,urllib.request
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}.get('ALCHEMY_API_KEY'); U=f"https://eth-mainnet.g.alchemy.com/v2/{K}" if K else "https://ethereum-rpc.publicnode.com"
def rpc(m,p):
    r=urllib.request.Request(U,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=60)).get('result')
TX="0xad99264d5532ae0dd04b2004eebda05f25657e70dacb764f7ac8d4ccd051298b"
B14="0x28C6c06298d514Db089934071355E5743bf21d60"; ATK_ETH="0x8532FA14ACAf483729C449b8458aedDb900543D4"; FRZ="0x5227f603C1eE34CE3C06eFe6477003BDfCCB2f8c"
USDT="0xdAC17F958D2ee523a2206206994597C13D831ec7"; USDC="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
tx=rpc("eth_getTransactionByHash",[TX]); rc=rpc("eth_getTransactionReceipt",[TX])
json.dump({"tx":tx,"rc":rc},open("raw/attack_tx.json","w"))
if tx:
    blk=rpc("eth_getBlockByNumber",[tx["blockNumber"],False])
    print("type",tx["type"],"from",tx["from"],"to",tx["to"],"block",int(tx["blockNumber"],16),"ts",int(blk["timestamp"],16),"status",rc and rc["status"],"logs",rc and len(rc["logs"]))
    al=tx.get("authorizationList") or []
    print("auths",len(al),"targets",{a["address"] for a in al},"nonces",min(int(a["nonce"],16) for a in al) if al else None,"-",max(int(a["nonce"],16) for a in al) if al else None)
    print("selector",tx["input"][:10],"inputlen",len(tx["input"]))
    print("B14 nonce at block-1",int(rpc("eth_getTransactionCount",[B14,hex(int(tx["blockNumber"],16)-1)]),16))
else: print("TX NOT FOUND")
print("B14 code now",rpc("eth_getCode",[B14,"latest"])[:60],"nonce",int(rpc("eth_getTransactionCount",[B14,"latest"]),16),"ETH",int(rpc("eth_getBalance",[B14,"latest"]),16)/1e18)
print("0x8532 ETH",int(rpc("eth_getBalance",[ATK_ETH,"latest"]),16)/1e18,"nonce",int(rpc("eth_getTransactionCount",[ATK_ETH,"latest"]),16),"code",rpc("eth_getCode",[ATK_ETH,"latest"])[:50])
pad=lambda a:a[2:].lower().rjust(64,"0")
for n,t,d,sel in [("USDT",USDT,6,"0xe47d6060"),("USDC",USDC,6,"0xfe575a87")]:
    bal=int(rpc("eth_call",[{"to":t,"data":"0x70a08231"+pad(FRZ)},"latest"]),16)/10**d
    bl=int(rpc("eth_call",[{"to":t,"data":sel+pad(FRZ)},"latest"]),16)
    print("0x5227",n,bal,"blacklisted",bool(bl))
