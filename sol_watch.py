"""One-shot movement check for the live Solana + XRP holders (read-only). Watches every SOL tree wallet holding > 1 SOL, the gas
wallets, and the XRP tree. Prints one line per change vs the last run (state raw/watch/live_state.json); exit code 10 if anything
moved, 0 if quiet.   python3 sol_watch.py"""
import json, os, sys, time, urllib.request
os.chdir(os.path.dirname(os.path.abspath(__file__)))
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
H = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"; X = 'https://s2.ripple.com:51234'
def post(u, d):
    for i in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, json.dumps(d).encode(), {'Content-Type': 'application/json'}), timeout=40))
        except Exception: time.sleep(3 * (i + 1))
    return {}
SL = json.load(open('raw/sol_ledger.json'))
sol = {a for a, w in SL['wallets'].items() if w['held'] > 1} | {'71thkNU69ZjohtzFoNGkBDHcrkN4WE76FaxBPUbZmAnt', 'G7VLTXkMVaG9NtpvX9gNuMpTPnfQRkyAwWT7LPnaSWVN',
       'HR7VsZjoe6QfMUfKHbdV2v2J8BDAFcLS4cLzTTX61NCf', 'ARk92boxCbssS2p8AL3x9GvLzZYxcRFueXvpUnGGZciQ', 'DjCoWxLLtNNhYVMjbwiquFehGz5dnFa2y7JVUdGZ6vxs',
       'B6cv44NfQcupManfMeRSg3cdcDYwCadg7FCsCUkVWFSm', 'FKhC8omjcMAjZdNBSr6ufR5E69vd6CwjAtT99XpTgkvr'}   # wave-2 receivers (11-02)
xrp = set(json.load(open('raw/xrp_ledger.json')).get('wallets', {}))
now = {}
S = sorted(sol)   # 11-04: 100 balances per call (getMultipleAccounts; no account = 0); a failed chunk is skipped, as a failed getBalance was
for i in range(0, len(S), 100):
    v = (post(H, {'jsonrpc': '2.0', 'id': 1, 'method': 'getMultipleAccounts', 'params': [S[i:i + 100], {'encoding': 'base64', 'dataSlice': {'offset': 0, 'length': 0}}]}).get('result') or {}).get('value')
    for a, acc in zip(S[i:i + 100], v or []): now['SOL ' + a] = (acc or {}).get('lamports', 0) / 1e9
for a in sorted(xrp):
    r = post(X, {'method': 'account_info', 'params': [{'account': a, 'ledger_index': 'validated'}]}).get('result', {}).get('account_data', {}).get('Balance')
    if r is not None: now['XRP ' + a] = int(r) / 1e6
SF = 'raw/watch/live_state.json'; os.makedirs('raw/watch', exist_ok=True)
prev = json.load(open(SF)) if os.path.exists(SF) else {}
moved = [(k, prev[k], v) for k, v in now.items() if k in prev and abs(v - prev[k]) > (0.5 if k.startswith('SOL') else 5)]
json.dump({**prev, **now}, open(SF, 'w'))
stamp = time.strftime('%H:%M UTC', time.gmtime())
for k, a, b in sorted(moved, key=lambda m: -abs(m[2] - m[1])):
    print(f"MOVED {stamp} {k.split()[0]} {k.split()[1]} {a:,.2f} → {b:,.2f} ({b - a:+,.2f})", flush=True)
if not prev: print(f"baseline {stamp}: {len(now)} wallets", flush=True)
sys.exit(10 if moved else 0)
