"""CCTP round trip -> Solana return wallets (11-04). Burns booked 'out: burned' in a SOL ledger are followed:
  Circle Iris (dest + mint_recipient) -> Noble forwarding account (auth/accounts: channel + dYdX recipient) -> dYdX account
  -> its IBC MsgTransfer back through Noble Orbiter (memo: CCTP destination_domain 5 + mint_recipient = Solana USDC account) -> owner.
Output raw/sol/cctp_returns.json: 'seeds' = Solana owners that received USDC minted from OUR dYdX accounts (+ evidence), plus what
left the dYdX accounts any other way. sol_ledger.py reads the seeds (SOL_SEEDS). Caches: raw/sol/cctp.json (Iris, shared),
raw/sol/noble_forwarding.json, raw/sol/dydx_txs/<acct>.json.
  SOL_LEDGER=raw/sol_ledger_next.json SOL_END=2026-11-04T01:32:07Z python3 cctp_return.py"""
import json, os, time, base64, collections, calendar, subprocess, urllib.parse, urllib.request
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from sol_burns import iris, bech32, DOM
LEDGER = os.environ.get('SOL_LEDGER', 'raw/sol_ledger_next.json')
_e = os.environ.get('SOL_END'); END = calendar.timegm(time.strptime(_e, '%Y-%m-%dT%H:%M:%SZ')) if _e else None
E = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}
HEL = f"https://mainnet.helius-rpc.com/?api-key={E['HELIUS_API_KEY']}"                                 # never print
NOBLE = 'https://noble-api.polkachu.com'; DYDX = 'https://dydx-rest.publicnode.com'
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def b58(b):
    n = int.from_bytes(b, 'big'); s = ''
    while n: n, r = divmod(n, 58); s = B58[r] + s
    return '1' * (len(b) - len(b.lstrip(b'\0'))) + s
def get(url):                                                   # curl: gzip on the hotspot, retries
    for i in range(6):
        o = subprocess.run(['curl', '-s', '-m', '40', '-H', 'accept-encoding: gzip', '--compressed', url], capture_output=True, text=True).stdout
        try: return json.loads(o)
        except Exception: time.sleep(2 + 3 * i)
    return {}
def rpc(m, p):
    for i in range(5):
        o = urllib.request.urlopen(urllib.request.Request(HEL, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p}).encode(), {'Content-Type': 'application/json'}), timeout=40).read().decode()   # 11-04: urllib, never curl — key is in the URL
        try: return json.loads(o)['result']
        except Exception: time.sleep(2 + 2 * i)

L = json.load(open(LEDGER))
burns = [e for e in L['edges_tok'] if e[6] == 'out: burned' and e[5] == 'USDC']
# 1. burns -> destination
dest = collections.defaultdict(lambda: [0, 0.0]); noble_in = collections.defaultdict(float); other = collections.defaultdict(float)
for sig, t, frm, _, amt, _, _ in burns:
    c = iris(sig); d = DOM.get(c.get('dest_domain'), c.get('dest_domain', 'not CCTP?')); rc = c.get('mint_recipient', '')
    if d == 'Noble' and rc: noble_in[bech32('noble', bytes.fromhex(rc[24:]))] += amt
    else: other[f'{d} {rc[:16]}'] += amt
    dest[d][0] += 1; dest[d][1] += amt
print(f'1. {len(burns)} burns {sum(e[4] for e in burns):,.2f} USDC ->', {k: (v[0], round(v[1], 2)) for k, v in dest.items()}, flush=True)
# 2. Noble recipient -> forwarding account -> dYdX (or other) recipient
NF = 'raw/sol/noble_forwarding.json'; nf = json.load(open(NF)) if os.path.exists(NF) else {}
for a, v in noble_in.items():
    if a not in nf or nf[a].get('usdc') != round(v, 2):
        acc = get(f'{NOBLE}/cosmos/auth/v1beta1/accounts/{a}').get('account') or {}
        nf[a] = {'usdc': round(v, 2), 'type': acc.get('@type'), 'channel': acc.get('channel'), 'recipient': acc.get('recipient')}
        json.dump(nf, open(NF, 'w'), indent=1); time.sleep(0.3)
dydx = collections.defaultdict(float); not_fwd = {}
for a, v in noble_in.items():
    x = nf[a]
    if (x.get('type') or 'ForwardingAccount').endswith('ForwardingAccount') and (x.get('recipient') or '').startswith('dydx1'): dydx[x['recipient']] += v   # 11-03 cache rows have no 'type' (all were ForwardingAccount)
    else: not_fwd[a] = x
print(f'2. {len(noble_in)} Noble recipients -> {len(dydx)} dYdX accounts ({sum(dydx.values()):,.2f} USDC); not forwarding to dYdX: {len(not_fwd)}', flush=True)
# 3. dYdX account -> outgoing IBC transfers (Orbiter CCTP memo -> Solana mint_recipient), other outflows
DT = 'raw/sol/dydx_txs'; os.makedirs(DT, exist_ok=True)
ret = collections.defaultdict(lambda: {'usdc': 0.0, 'n': 0, 'first': None, 'dydx': set()}); outs = collections.defaultdict(float); tx_out = []
for acct in dydx:
    txs = []
    for page in range(1, 11):
        r = get(f'{DYDX}/cosmos/tx/v1beta1/txs?' + urllib.parse.urlencode({'query': f"message.sender='{acct}'", 'pagination.limit': 100, 'page': page, 'order_by': 'ORDER_BY_ASC'}))
        tr = r.get('tx_responses') or []; txs += [[t['txhash'], t['timestamp'], t['tx']['body']['messages'], t.get('code', 0)] for t in tr]
        if len(tr) < 100: break
        time.sleep(0.3)
    json.dump(txs, open(f'{DT}/{acct}.json', 'w'))
    for h, ts, msgs, code in txs:
        tt = calendar.timegm(time.strptime(ts, '%Y-%m-%dT%H:%M:%SZ'))
        if code or (END and tt > END): continue
        for m in msgs:
            ty = m.get('@type', '')
            if ty.endswith('MsgTransfer'):
                amt = int(m['token']['amount']) / 1e6
                try: fw = json.loads(m.get('memo') or '{}')['orbiter']['forwarding']['attributes']
                except Exception: fw = {}
                if fw.get('destination_domain') == 5:
                    ta = b58(base64.b64decode(fw['mint_recipient'])); r_ = ret[ta]
                    r_['usdc'] += amt; r_['n'] += 1; r_['dydx'].add(acct); r_['first'] = min(filter(None, [r_['first'], ts]))
                    tx_out.append([ts, acct, amt, ta, h])
                else: outs[f"IBC {m.get('receiver', '')[:12]} domain {fw.get('destination_domain')}"] += amt
            elif ty.endswith('MsgSend'): outs['MsgSend ' + m.get('to_address', '')[:14]] += sum(int(c['amount']) for c in m.get('amount', []) if 'ibc/' in c['denom']) / 1e6
    print(f'   {acct} in {dydx[acct]:,.2f} | {len(txs)} txs', flush=True)
print(f'3. returns to Solana: {sum(v["usdc"] for v in ret.values()):,.2f} USDC to {len(ret)} USDC accounts; other outflows:', {k: round(v, 2) for k, v in outs.items()}, flush=True)
# 4. USDC token account -> owner
owners = collections.defaultdict(lambda: {'usdc': 0.0, 'n': 0, 'first': None, 'dydx': set(), 'token_accounts': []}); ta = list(ret)
for i in range(0, len(ta), 100):
    for a, v in zip(ta[i:i + 100], rpc('getMultipleAccounts', [ta[i:i + 100], {'encoding': 'jsonParsed'}])['value']):
        o = (((v or {}).get('data') or {}).get('parsed') or {}).get('info', {}).get('owner') or f'?closed:{a}'
        w = owners[o]; r_ = ret[a]; w['usdc'] += r_['usdc']; w['n'] += r_['n']; w['dydx'] |= r_['dydx']; w['token_accounts'].append(a)
        w['first'] = min(filter(None, [w['first'], r_['first']]))
seeds = {o: {**w, 'dydx': sorted(w['dydx']), 'usdc': round(w['usdc'], 6)} for o, w in owners.items()}
out = {'ledger': LEDGER, 'end': _e, 'made': time.strftime('%FT%TZ', time.gmtime()), 'burns': {k: [v[0], round(v[1], 6)] for k, v in dest.items()},
       'burns_not_noble': {k: round(v, 6) for k, v in other.items()}, 'noble_not_dydx': not_fwd, 'dydx_in': {k: round(v, 6) for k, v in dydx.items()},
       'dydx_other_out': {k: round(v, 6) for k, v in outs.items()}, 'returns': sorted(tx_out), 'seeds': seeds}
json.dump(out, open('raw/sol/cctp_returns.json', 'w'), indent=1)
print(f'4. {len(seeds)} Solana return owners (seeds), {sum(s["usdc"] for s in seeds.values()):,.2f} USDC -> raw/sol/cctp_returns.json')
