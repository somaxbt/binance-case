import json,os,urllib.request,glob
K={l.split('=',1)[0]:l.split('=',1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
def rpc(m,p):
    r=urllib.request.Request(f"https://eth-mainnet.g.alchemy.com/v2/{K}",json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r,timeout=90)).get('result')
pad=lambda a:a[2:].lower().rjust(64,"0")
def bal(t,a,d):
    r=rpc("eth_call",[{"to":t,"data":"0x70a08231"+pad(a)},"latest"]); return int(r,16)/10**d if r and r!="0x" else 0
known="7c8601d4645b93cea45f71e118a729332e6b5ca0 5227f603c1ee34ce3c06efe6477003bdfccb2f8c 8532fa14acaf483729c449b8458aeddb900543d4 9749292d74fd460982d0912ea9515ea24736c762 0ddf0480016e6bcb2c1f5d190d221fba1320697e 811f15855476156ebf86ba3b84fafb8ceaa4e84c aa246bf639586a6ba46762d378ce50ca4fc654a0 beef02961503351625926ea9a11ae13b29f5c555 0000000000be226afde21672a5e4adc45692e69d 8d53903625b8e839b9df4bd28b0efb1cd6b8639a 77edef23fbd05921c26fe29fcc3a65e14d2ac3eb 7aa4d3029e4c6a8e916300014ad95b6d6c03bfd1 ccbef95633adb5cd2b5038db5a38d77e726ca263 b3ddec0ccc5c3ba733fcdf5a15f98c95ec5a5fdb 5c23023ca6633f91ded909b4a753a3ca00fea4fc 008f06f04b72da2621a4f37f5531cc7352187dcd e7024ab80143b1ef843efe6a58368696cb87958d c887af690e0301cd4edbbce8f8d31b4ec65b286a 79e70d139fc05aa75f75611fdf2680e9952b544a 7f9dc988b46336ad536828fad50fa8fa1e5415e3".split()
S={"0x"+a for a in known}
for t in json.load(open("raw/0x5227.json"))["out"]:
    if t["asset"]=="ETH" and (t["value"] or 0)<=2: S.add(t["to"])
print("attacker set size",len(S))
T={"aUSDT":("0x23878914efe38d27c4d67ab83ed1b93a74d4086a",6),"aWETH":("0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8",18),"debtWETH":("0xea51d7853eefb32b6ee06b1c12e6dcca88be0ffe",18),"USDT":("0xdac17f958d2ee523a2206206994597c13d831ec7",6),"USDC":("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",6),"WETH":("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",18)}
rows=[];tot={k:0 for k in ["ETH",*T]}
for a in sorted(S):
    r={"ETH":int(rpc("eth_getBalance",[a,"latest"]),16)/1e18}
    for k,(c,d) in T.items(): r[k]=bal(c,a,d)
    for k in tot: tot[k]+=r[k]
    if any(v>1 for v in r.values()): rows.append((a,{k:round(v,2) for k,v in r.items() if v>1}))
json.dump({"set":sorted(S),"rows":rows},open("raw/attacker_holdings.json","w"))
for a,r in sorted(rows,key=lambda x:-x[1].get("ETH",0)): print(a,r)
print("TOTAL",{k:round(v,2) for k,v in tot.items()})
