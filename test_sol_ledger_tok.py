# offline check of sol_ledger.read() token legs on cached Jupiter Lend txs (no RPC)
import json, os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
src = open('sol_ledger.py').read().split('# ---- pass 1')[0].replace("os.chdir(os.path.dirname(os.path.abspath(__file__)))", "")
g = {}; exec(src, g)
def fake(sigs): g['sigs'] = lambda a, since=0, **kw: [{'signature': s, 'blockTime': 1, 'err': None} for s in sigs]
fake(['2dhZGqfsKX9fM4zwtDLtwwfLXSPc7RTvhj5q422JvPPSPpUxY98jtkB4eR8SHwbux8qdKJnsPmfWo9CC5yTDYgfU'])
# find full addresses from the tx
t = json.load(open('raw/sol/tx_2dhZGqfsKX9fM4zwtDLtwwfLXSPc7RTvhj5q422JvPPSPpUxY98jtkB4eR8SHwbux8qdKJnsPmfWo9CC5yTDYgfU.json'))
dep = t['transaction']['message']['accountKeys'][0]['pubkey']
R = g['read'](dep); print('deposit', dep[:8], [(k, c[:8], round(v, 4), s) for _, _, k, c, v, s in R])
assert any(k == 'out' and c == '5JP5zgYCb9W37QQLgAHRHuinFLrKt87akDY1CgZoTPzr' and s == 'SOL' and abs(v - 6201.47) < 0.01 for _, _, k, c, v, s in R)
assert any(k == 'in' and c == 'mint' and s == 'jlWSOL' and abs(v - 5909.6372) < 0.001 for _, _, k, c, v, s in R)
red = '5s2qR2aDAEje9LXyMpVS'; f = [x for x in os.listdir('raw/sol') if x.startswith('tx_' + red)][0][3:-5]
fake([f]); t = json.load(open(f'raw/sol/tx_{f}.json')); w = t['transaction']['message']['accountKeys'][0]['pubkey']
R = g['read'](w); print('redeem ', w[:8], [(k, c[:8], round(v, 4), s) for _, _, k, c, v, s in R])
assert any(k == 'out' and c == 'burn' and s == 'jlWSOL' and abs(v - 1188.3473) < 0.001 for _, _, k, c, v, s in R)
assert any(k == 'in' and c == '5JP5zgYCb9W37QQLgAHRHuinFLrKt87akDY1CgZoTPzr' and s == 'SOL' and abs(v - 1247.0) < 0.01 for _, _, k, c, v, s in R)
print('OK')
# swap SOL -> USDC with the USDC paid to a 3rd wallet (Fw9P2sFu 10k SOL -> ARk92box, 11-02 04:49)
s = '43C5oRRLS4acjm8Lfo6HNzm2hFsbyHsBLFwhrDMvWDdw7CYViqmXme8vZcd2U9DHhrUvJbon6wpt2SVu9XZfguWv'; fake([s])
R = g['read']('Fw9P2sFuSRg5VC3nGyh7tx9F76TYVDvQWpaazWpp6848')
print('swap   ', [(k, c[:8], round(v, 2), x) for _, _, k, c, v, x in R if v > 1])
assert any(k == 'swapto' and c.startswith('ARk92box') and x == 'USDC' and v > 900000 for _, _, k, c, v, x in R)
R = g['read']('ARk92boxCbssS2p8AL3x9GvLzZYxcRFueXvpUnGGZciQ')
print('recv   ', [(k, c[:8], round(v, 2), x) for _, _, k, c, v, x in R if v > 1]); assert any(k == 'in' and x == 'USDC' for _, _, k, c, v, x in R)
print('OK swap')
