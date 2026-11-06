import json,os,urllib.request,time,re
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def post(u,d,h={}):
    return json.load(urllib.request.urlopen(urllib.request.Request(u,json.dumps(d).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0",**h}),timeout=60))
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
eth=lambda net,a:int(post(f"https://{net}.g.alchemy.com/v2/{K}",{"jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":[a,"latest"]})["result"],16)/1e18
R={}
for a in ["0x8532fa14acaf483729c449b8458aeddb900543d4","0xc887af690e0301cd4edbbce8f8d31b4ec65b286a","0x79e70d139fc05aa75f75611fdf2680e9952b544a","0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c","0xcf4ca2bdf21bc3a467a00b6afe72b833982723e0","0xb3ddec0ccc5c3ba733fcdf5a15f98c95ec5a5fdb","0x06ea1ab3ecf570029eb1f94dbb9eac06bc79685f"]: R["ETH "+a[:8]]=eth("eth-mainnet",a)
R["AVAX 0x5227"]=eth("avax-mainnet","0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c"); R["AVAX 0x80358c"]=int(post("https://api.avax.network/ext/bc/C/rpc",{"jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":["0x80358c5b8f9b2cc27147a1e0f2a6c9a30eb2c397","latest"]})["result"],16)/1e18
R["POL 0x5227"]=eth("matic-mainnet","0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c")
R["OP-token 0x5227"]=int(post(f"https://opt-mainnet.g.alchemy.com/v2/{K}",{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x4200000000000000000000000000000000000042","data":"0x70a08231"+"5227f603c1ee34ce3c06efe6477003bdfccb2f8c".rjust(64,"0")},"latest"]})["result"],16)/1e18
# Aave
r=post(f"https://eth-mainnet.g.alchemy.com/v2/{K}",{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2","data":"0xbf92857c"+"8d53903625b8e839b9df4bd28b0efb1cd6b8639a".rjust(64,"0")},"latest"]})["result"]
R["Aave HF"]=int(r[2+5*64:2+6*64],16)/1e18
R["XRP rK21"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP ryB7NE"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"ryB7NESZcttqzRioiD5L6Kf5tFL87ktmx","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP rKxwzj"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rKxwzjpZj5r9eXnCJQvLVUnebpGEHTDH1F","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP rhfA8Q"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rhfA8QzpcDPYX3safySLrvT5afnNjHc9XB","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP rsNoNk"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rsNoNkb1zqMBR1rjbrasUzExqjCDXseisW","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP rhXtRt"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rhXtRtpfZRAKVayWd5Z5kRJ2YXYkcuxNRD","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP raoMrx"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"raoMrxbMFo5xpVfE9VPoEuVpv1CTtebm5t","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["XRP rJheAA"]=int(post("https://s2.ripple.com:51234",{"method":"account_info","params":[{"account":"rJheAAxFoWNoTrfrt8N5GyAJLa559jWh4b","ledger_index":"validated"}]})["result"]["account_data"]["Balance"])/1e6
R["SOL Affz"]=post("https://api.mainnet-beta.solana.com",{"jsonrpc":"2.0","id":1,"method":"getBalance","params":["AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU"]})["result"]["value"]/1e9
for a in ["TSpe5HC3PRD2svJcr1YoGszhHk2mtkyZ8A","TRBdWqHnDVSZCVGfgHdKFLQPirQcA2PRki"]:
    R["TRX "+a[:8]]=((get(f"https://api.trongrid.io/v1/accounts/{a}").get("data") or [{}])[0].get("balance",0))/1e6; time.sleep(1.1)
md="" if os.environ.get("MC_SKIP_BTC") else open("agents/btc.md").read()   # MC_SKIP_BTC=1: Blockstream busy/rate-limited
addrs=sorted(set(re.findall(r"\bbc1q[0-9a-z]{38,58}\b",md))-{"bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h","bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm"})
btc=0;n=0
for a in addrs:
    try:
        s=get(f"https://blockstream.info/api/address/{a}")["chain_stats"]; b=(s["funded_txo_sum"]-s["spent_txo_sum"])/1e8
        if b>0: btc+=b;n+=1
    except Exception as e: pass
    time.sleep(0.6)
R[f"BTC unspent ({n} addrs of {len(addrs)} listed)"]=btc
ids="coingecko:ethereum,coingecko:bitcoin,coingecko:ripple,coingecko:solana,coingecko:tron,coingecko:avalanche-2,coingecko:optimism,coingecko:polygon-ecosystem-token"
p=get(f"https://coins.llama.fi/prices/historical/1793305463/{ids}")["coins"]
R["_px"]={k.split(':')[1]:v["price"] for k,v in p.items()}
json.dump(R,open("raw/refresh_latest.json","w"),indent=1)
for k,v in R.items(): print(k, f"{v:,.2f}" if isinstance(v,float) else v)
