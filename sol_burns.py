"""Resolve USDC the SOL tree ledger booked as 'out: burned' (CCTP DepositForBurn) via Circle Iris -> destination chain + mint recipient.
Reads raw/sol_ledger.json edges_tok; Iris cache shared with sol_cctp.py (raw/sol/cctp.json).   python3 sol_burns.py"""
import json, os, time, collections, urllib.request, urllib.error
os.chdir(os.path.dirname(os.path.abspath(__file__)))
DOM = {0: 'Ethereum', 1: 'Avalanche', 4: 'Noble', 2: 'Optimism', 3: 'Arbitrum', 5: 'Solana', 6: 'Base', 7: 'Polygon', 10: 'Unichain', 11: 'Linea', 14: 'World Chain', 19: 'HyperEVM'}
C = 'raw/sol/cctp.json'; cache = json.load(open(C)) if os.path.exists(C) else {}
def iris(sig):                                   # same decode as sol_cctp.iris (CCTP v1 message: dest domain @8, burn body @116)
    if sig in cache: return cache[sig]
    for k in range(6):
        try: r = json.load(urllib.request.urlopen(urllib.request.Request(f'https://iris-api.circle.com/v1/messages/5/{sig}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30)); break
        except urllib.error.HTTPError as e:
            if e.code == 404: r = {'messages': []}; break
            time.sleep(5 * (k + 1))
    v2 = not r.get('messages')                    # 11-03: CCTP v2 burns are only on /v2 (CyBgxHUK, 183,777 USDC)
    if v2: r = json.load(urllib.request.urlopen(urllib.request.Request(f'https://iris-api.circle.com/v2/messages/5?transactionHash={sig}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
    m = (r.get('messages') or [{}])[0]; msg = bytes.fromhex((m.get('message') or '0x')[2:]); H = 148 if v2 else 116   # v2 header: +32B nonce/caller fields
    out = {'attestation': m.get('attestation', '')[:12], 'status': 'complete' if m.get('attestation', 'PENDING') not in ('PENDING', '') else 'pending', 'cctp': 'v2' if v2 else 'v1'}
    if len(msg) >= H + 100:
        b = msg[H:]
        out.update({'dest_domain': int.from_bytes(msg[8:12], 'big'), 'nonce': int.from_bytes(msg[12:20], 'big'),
                    'mint_recipient': b[36:68].hex(), 'amount': int.from_bytes(b[68:100], 'big') / 1e6})
    cache[sig] = out; json.dump(cache, open(C, 'w'), indent=1); time.sleep(1)
    return out
def bech32(hrp, data):                          # BIP-173 encode (Noble = Cosmos SDK, 20-byte account)
    CS = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'; G = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    acc = bits = 0; d5 = []
    for b in data:
        acc = (acc << 8) | b; bits += 8
        while bits >= 5: bits -= 5; d5.append((acc >> bits) & 31)
    if bits: d5.append((acc << (5 - bits)) & 31)
    def pm(v):
        c = 1
        for x in v:
            t = c >> 25; c = (c & 0x1ffffff) << 5 ^ x
            for i in range(5): c ^= G[i] if (t >> i) & 1 else 0
        return c
    e = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]; m = pm(e + d5 + [0] * 6) ^ 1
    return hrp + '1' + ''.join(CS[x] for x in d5 + [(m >> 5 * (5 - i)) & 31 for i in range(6)])
if __name__ == '__main__':                       # 11-04: importable (cctp_return.py reuses iris/bech32); SOL_LEDGER picks the ledger
    B = [e for e in json.load(open(os.environ.get('SOL_LEDGER', 'raw/sol_ledger.json')))['edges_tok'] if e[6] == 'out: burned' and e[5] == 'USDC']
    agg = collections.defaultdict(lambda: [0, 0.0]); rows = []
    for sig, t, frm, _, amt, _, _ in B:
        c = iris(sig); dst = DOM.get(c.get('dest_domain'), c.get('dest_domain', 'NOT CCTP?')); rc = c.get('mint_recipient', '')
        rc = bech32('noble', bytes.fromhex(rc[24:])) if rc and dst == 'Noble' else '0x' + rc[24:] if rc and dst != 'Solana' else rc
        agg[(dst, rc)][0] += 1; agg[(dst, rc)][1] += amt; rows.append([sig, t, frm, amt, dst, rc, c.get('status')])
    json.dump(rows, open('raw/sol/burns_resolved.json', 'w'), indent=1)
    print(f'{len(B)} burns, {sum(r[3] for r in rows):,.2f} USDC')
    for (d, r), (n, v) in sorted(agg.items(), key=lambda x: -x[1][1]): print(f'  {d:10} {r:44} {n:3} tx {v:14,.2f} USDC')
