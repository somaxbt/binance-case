"""11-05: classify SOL-ledger swap txs whose output did NOT come back to a tree wallet (raw/sol/swap_no_return_*.json), from the
tx cache only (raw/sol/tx_<sig>.json, no RPC). Per tx: top-level + inner programs, and every NON-SOL token gain by owner.
  python3 sol_noreturn_classify.py [ledger.json] [no_return.json]   -> raw/sol/swap_no_return_classified.json"""
import json, sys, os, collections
LJ = sys.argv[1] if len(sys.argv) > 1 else 'raw/sol_ledger_next.json'; NR = sys.argv[2] if len(sys.argv) > 2 else 'raw/sol/swap_no_return_20261105.json'
S = json.load(open(LJ)); W = set(S['wallets'])
BRIDGE = {'src5qyZHqTqecJV4aY6Cb6zDZLMDzrDKKezs22MPHr4': 'deBridge DLN', 'DEbrdGj3HsRsAzx6uH4MKyREKxVAfBydijLUF3ygsFfh': 'deBridge',
          'BLZRi6frs4X4DNLw56V4EXai1b6QVESN1BhHBTYM9VcY': 'Mayan', 'FC4eXxkyrMPTjiYUpp4EAnkmwMbQyZ6NDCh1kfLn6vsf': 'Mayan Swift',
          'wormDTUJ6AWPNvk59vGQbDvGJmqbDTdgWgAqcLBCgUb': 'Wormhole', 'BrdgN2RPzEMWF96ZbnnJaUMQDsN3ZpqaGsvKkTNyjEr5': 'Allbridge',
          'CCTPiPYPc6AsJuwueEnWgSgucamXDZwBd53dQ11YiKX3': 'CCTP', 'CCTPmbSD7gX1bxKPAmg77w8oFzNFpaQiQUWD43TKaecd': 'CCTP'}
SWAP = {'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4': 'Jupiter', 'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc': 'Orca', '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8': 'Raydium',
        'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK': 'Raydium CLMM', 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo': 'Meteora DLMM'}
WSOL = 'So11111111111111111111111111111111111111112'; TRACKED = {'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'}
nr = json.load(open(NR)); out = []; agg = collections.defaultdict(lambda: [0, 0.0]); miss = 0
for sig, sol in nr:
    f = f'raw/sol/tx_{sig}.json'
    if not os.path.exists(f): miss += 1; agg[('no cached tx',)][0] += 1; agg[('no cached tx',)][1] += sol; continue
    t = json.load(open(f)); m = t['transaction']['message']; meta = t['meta']
    progs = {i.get('programId') for i in m['instructions']} | {i.get('programId') for x in meta.get('innerInstructions') or [] for i in x['instructions']}
    br = sorted({BRIDGE[p] for p in progs if p in BRIDGE}); sw = sorted({SWAP[p] for p in progs if p in SWAP})
    pre = {(b['accountIndex']): float(b['uiTokenAmount']['uiAmount'] or 0) for b in meta.get('preTokenBalances') or []}
    gains = []
    for b in meta.get('postTokenBalances') or []:
        d = float(b['uiTokenAmount']['uiAmount'] or 0) - pre.get(b['accountIndex'], 0)
        if d > 0 and b['mint'] != WSOL: gains.append((b.get('owner'), b['mint'], d))
    tree_gain = [g for g in gains if g[0] in W]
    if br: k = ('bridge: ' + '+'.join(br),)
    elif tree_gain and all(g[1] not in TRACKED for g in tree_gain): k = ('output to TREE in an untracked token (not an exit)',)
    elif tree_gain: k = ('output to TREE in a tracked token (ledger missed the edge?)',)
    elif gains: k = ('output to a NON-tree owner (third-party payout)',)
    else: k = ('no token gain (SOL out only: wrap/LP/other)',)
    agg[k][0] += 1; agg[k][1] += sol
    out.append(dict(sig=sig, sol=sol, kind=k[0], bridges=br, swaps=sw, gains=[(o, mt[:6], round(d, 6)) for o, mt, d in gains if o not in W][:4], progs=sorted(p for p in progs if p)[:12]))
print(f'{len(nr)} no-return swap txs · {sum(s for _, s in nr):,.2f} SOL · tx not cached {miss}')
for k, (n, v) in sorted(agg.items(), key=lambda x: -x[1][1]): print(f'  {v:12,.2f} SOL  {n:5} txs  {k[0]}')
tp = collections.Counter(); [tp.update([p]) for r in out if r['kind'].startswith('output to a NON') for p in r['progs']]
print('programs in the third-party-payout txs:', tp.most_common(12))
json.dump(out, open('raw/sol/swap_no_return_classified.json', 'w'), indent=0)
