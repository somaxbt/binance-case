import json,urllib.request,time,collections
W="TAzsQ9Gx8eqFNFSKbeXrbi45CuVPHzA8wr TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY9 TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G TQrY8tryqsYVCYS3MFbtffiPp2ccyn4STm TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb TYASr5UV6HEcXatwdFQfmLVUqQQQMUxHLS TCEn8ogRSiqdqv26UhsJmQQemrgJS56ZBD TCLgK89AnXbC9rewvhNb9UgXCc2qJJpBXh TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf TJ5usJLLwjwn7Pw3TPbdzreG7dvgKzfQ5y TJCo98saj6WND61g1uuKwJ9GMWMT9WkJFo TJqwA7SoZnERE4zW5uDEiPkbz4B66h9TFj TK4ykR48cQQoyFcZ5N4xZCbsBaHcg6n3gJ TMwf7KT8CCdUKuZfKNPTTjbYkFb3eGRbzY TPtW5TEHhouj6KGshVu5ZQSKZA48QPBnXG TRGCqsUXeynKTgynp2j9g3sg7Nux2KtB3u".split()
T0,T1=1793304000000,1793314800000   # 20:00 -> 23:00 UTC 10-29
def get(u):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=60))
        except Exception as e: time.sleep(3*(i+1)); err=e
    print("ERR",u[:80],err); return {}
big=[]
for a in W:
    u=f"https://api.trongrid.io/v1/accounts/{a}/transactions/trc20?only_from=true&min_timestamp={T0}&max_timestamp={T1}&limit=200"
    d=get(u).get("data",[]); time.sleep(1.1)
    for t in d:
        v=int(t["value"])/10**t["token_info"]["decimals"]
        if v>=1e6: big.append(("trc20",a,t["to"],t["token_info"]["symbol"],v,t["block_timestamp"],t["transaction_id"]))
    u=f"https://api.trongrid.io/v1/accounts/{a}/transactions?only_from=true&min_timestamp={T0}&max_timestamp={T1}&limit=200"
    d=get(u).get("data",[]); time.sleep(1.1)
    for t in d:
        c=t["raw_data"]["contract"][0]
        if c["type"]=="TransferContract":
            v=c["parameter"]["value"]["amount"]/1e6
            if v>=1e5: big.append(("trx",a,c["parameter"]["value"]["to_address"],"TRX",v,t["block_timestamp"],t["txID"]))
json.dump(big,open("raw/tron/big_outs.json","w"))
dest=collections.defaultdict(lambda:collections.defaultdict(float))
for k,a,to,s,v,ts,h in big: dest[to][s]+=v
print(len(big),"big outs")
for to,s in sorted(dest.items(),key=lambda x:-sum(x[1].values()))[:15]: print(to,{k:round(v) for k,v in s.items()})
for r in sorted(big,key=lambda r:-r[4])[:12]: print(r[0],r[1][:8],"->",r[2],r[3],f"{r[4]:,.0f}",time.strftime('%H:%M:%S',time.gmtime(r[5]/1000)),r[6][:16])
