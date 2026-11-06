"""Binance case — Ethereum clean-up + stolen/frozen summary (reads binance-eth-ledger.db; writes raw/eth_cleanup.json).
Logs come from publicnode (Alchemy free tier caps eth_getLogs at 10 blocks); everything else from Alchemy.
  A. freeze/blacklist event for every frozen holding (tx, block, time, admin, event)
  B. admin seizures: token outflows from attacker wallets NOT signed by the attacker
  C. destinations of tokens that left 0x5227 while still 'untracked' (DAR, FAB, PUNDIX, EURI, …)
  D. group-B recount from raw Transfer logs (OGN, G, MANA, CAKE)
  E. stolen on Ethereum per asset with the victim tx hashes"""
import json, os, time, sqlite3, urllib.request, urllib.error
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
K = {l.split('=', 1)[0]: l.split('=', 1)[1].strip().strip('"') for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l}['ALCHEMY_API_KEY']
ALC, PUB = f'https://eth-mainnet.g.alchemy.com/v2/{K}', 'https://ethereum-rpc.publicnode.com'
FROM = 26300700
def post(url, body):
  for i in range(8):
    try: return json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}), timeout=90))
    except urllib.error.HTTPError as e:
      if e.code in (403, 429, 500, 502, 503, 525): time.sleep((15 if e.code == 403 else 4) * (i + 1)); continue
      raise
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError): time.sleep(10 * (i + 1))
  raise RuntimeError('rpc failed')
def rpc(m, p, url=ALC):
  if url == PUB: time.sleep(1.0)                      # publicnode 403s on bursts
  j = post(url, {'jsonrpc': '2.0', 'id': 1, 'method': m, 'params': p})
  if 'error' in j: raise RuntimeError(f'{m}: {j["error"]}')
  return j['result']
def batch(calls, url=ALC):
  out = []
  for i in range(0, len(calls), 50):
    out += [x.get('result') for x in sorted(post(url, [{'jsonrpc': '2.0', 'id': k, 'method': m, 'params': p} for k, (m, p) in enumerate(calls[i:i + 50])]), key=lambda x: x['id'])]
  return out
pad = lambda a: '0x' + a[2:].lower().rjust(64, '0')
T_TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
T_APPROVAL = '0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925'
SIGS = ['AddedBlackList(address)', 'BlockPlaced(address)', 'Blacklisted(address)', 'AddressFrozen(address)', 'Frozen(address)', 'Freeze(address)',
        'AccountFrozen(address)', 'Blocked(address)', 'BlacklistAdded(address)', 'AddedToBlacklist(address)', 'AddedBlacklist(address)', 'BlackListed(address)',
        'AddressBlacklisted(address)', 'UserBlacklisted(address)', 'FrozenFunds(address,bool)', 'Blacklist(address,bool)', 'SetBlacklist(address,bool)',
        'BlacklistUpdated(address,bool)', 'DestroyedBlackFunds(address,uint256)', 'Wipe(address,uint256)', 'FrozenAddressWiped(address)', 'AddressFrozen(address,bool)',
        'Frozen(address,bool)', 'BlockedAccount(address)', 'Restricted(address)']
def main():
  log = lambda *a: print(*a, flush=True)
  c = sqlite3.connect(os.path.join(HERE, 'binance-eth-ledger.db'))
  r = c.execute("SELECT run_id FROM ledger_run WHERE leg='eth' ORDER BY started DESC LIMIT 1").fetchone()[0]
  nodes = {x[0] for x in c.execute('SELECT DISTINCT address FROM eth_node WHERE run_id=?', (r,))}
  sym = {a: s for a, s in c.execute('SELECT asset, MAX(symbol) FROM eth_edge WHERE run_id=? GROUP BY asset', (r,))}
  head = int(rpc('eth_blockNumber', []), 16)
  sighash = {rpc('web3_sha3', ['0x' + s.encode().hex()]): s for s in SIGS}
  out = {'run': r, 'head': head, 'generated': time.strftime('%F %T')}
  ts_cache = {}
  def bts(bn):
    if bn not in ts_cache: ts_cache[bn] = int(rpc('eth_getBlockByNumber', [hex(bn), False])['timestamp'], 16)
    return time.strftime('%F %T UTC', time.gmtime(ts_cache[bn]))

  # ---------- E. stolen per asset ----------
  log('E. stolen on Ethereum per asset')
  st = defaultdict(lambda: [0.0, set(), set()])
  for a, s, v, h, f in c.execute("SELECT asset, symbol, amount, hash, frm FROM eth_edge WHERE run_id=? AND cls='in:victim'", (r,)):
    x = st[a]; x[0] += v; x[1].add(h); x[2].add(f)
  out['stolen'] = [{'asset': a, 'symbol': sym.get(a), 'amount': x[0], 'txs': sorted(x[1]), 'victims': sorted(x[2])} for a, x in sorted(st.items(), key=lambda kv: -kv[1][0])]
  log(f'   {len(st)} assets; victim txs: {len({h for x in st.values() for h in x[1]})}')

  # ---------- A. freeze events ----------
  log('A. freeze/blacklist events for frozen holdings')
  hold = json.load(open(os.path.join(HERE, 'raw/eth_token_holdings_live.json')))
  frozen = [(n, t, s, b) for n, t, s, b, f in hold if f and b > 0.01]
  fr = []
  for n, t, s, b in frozen:
    found = []
    for topics in ([None, pad(n)], [None, None, pad(n)], [None, None, None, pad(n)]):
      for lg in rpc('eth_getLogs', [{'address': t, 'fromBlock': hex(FROM), 'toBlock': hex(head), 'topics': topics}], PUB):
        if lg['topics'][0] in (T_TRANSFER, T_APPROVAL): continue
        found.append(lg)
    data_sigs = [h for h in sighash]
    for lg in rpc('eth_getLogs', [{'address': t, 'fromBlock': hex(FROM), 'toBlock': hex(head), 'topics': [data_sigs]}], PUB):
      if n[2:].lower() in lg['data'].lower(): found.append(lg)
    ev = []
    for lg in {(l['transactionHash'], l['logIndex']): l for l in found}.values():
      tx = rpc('eth_getTransactionByHash', [lg['transactionHash']]); bn = int(lg['blockNumber'], 16)
      ev.append({'event': sighash.get(lg['topics'][0], lg['topics'][0][:18]), 'tx': lg['transactionHash'], 'block': bn, 'time': bts(bn),
                 'sender': tx['from'], 'tx_to': tx['to']})
    fr.append({'wallet': n, 'token': t, 'symbol': s, 'frozen_amount': b, 'events': sorted(ev, key=lambda e: e['block'])})
    log(f'   {s:7} {b:>22,.4f} at {n[:10]} -> {len(ev)} event(s) ' + ('; '.join(f"{e['event']} {e['tx'][:12]} {e['time']}" for e in ev[:2]) if ev else 'NONE FOUND'))
  out['frozen'] = fr

  # ---------- B. admin seizures ----------
  log('B. admin seizures (outflows not signed by the attacker)')
  edges = c.execute("SELECT hash, frm, too, asset, symbol, amount, cls FROM eth_edge WHERE run_id=? AND cls LIKE 'out:%' AND asset!='ETH'", (r,)).fetchall()
  hashes = sorted({e[0] for e in edges if e[1] in nodes})
  txs = dict(zip(hashes, batch([('eth_getTransactionByHash', [h]) for h in hashes])))
  sz = defaultdict(lambda: [0.0, set(), set()])
  for h, f, t, a, s, v, cls in edges:
    tx = txs.get(h)
    if not tx or f not in nodes: continue
    if tx['from'].lower() in nodes or (tx['to'] or '').lower() in nodes: continue          # attacker signed (directly or via its own 7702 wallet)
    sz[(a, s, f, t, tx['from'].lower(), (tx['to'] or '').lower())][0] += v
    sz[(a, s, f, t, tx['from'].lower(), (tx['to'] or '').lower())][1].add(h)
  seize = []
  for (a, s, f, t, sender, to), (v, hs, _) in sorted(sz.items(), key=lambda kv: kv[0][1]):
    seize.append({'asset': a, 'symbol': s, 'from_attacker': f, 'to': t, 'tx_sender': sender, 'tx_to': to, 'amount': v, 'txs': sorted(hs)})
  out['not_signed_by_attacker'] = seize
  log(f'   {len(seize)} groups of token outflows not signed by the attacker (solver fills and seizures; classified in the summary)')

  # ---------- C. untracked outflows from 0x5227 ----------
  log('C. destinations of tokens that left attacker wallets as "untracked"')
  unt = defaultdict(float)
  for h, f, t, a, s, v, cls in c.execute("SELECT hash, frm, too, asset, symbol, amount, cls FROM eth_edge WHERE run_id=? AND cls='out:untracked'", (r,)):
    if a in st: unt[(s, a, f, t)] += v
  out['untracked_outflows'] = [{'symbol': s, 'asset': a, 'from': f, 'to': t, 'amount': v} for (s, a, f, t), v in sorted(unt.items(), key=lambda kv: kv[0][0])]
  for (s, a, f, t), v in sorted(unt.items(), key=lambda kv: kv[0][0])[:40]: log(f'   {s:8} {v:>22,.4f} {f[:10]} -> {t}')

  # ---------- D. group-B recount ----------
  log('D. group-B recount from Transfer logs')
  rec = []
  for a, s, w in [('0x8207c1ffc5b6804f6024322ccf34f29c3541ae26', 'OGN', '0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c'), ('0x9c7beba8f6ef6643abd725e45a4e8387ef260649', 'G', '0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c'),
                  ('0x0f5d2fb29fb7d3cfee444a200298f468908cc942', 'MANA', '0xa97bf7836f8a08f9ed91d41453d371493fae8d10'), ('0x152649ea73beab28c5b49b26eb48f7ead6d4c898', 'CAKE', '0xa97bf7836f8a08f9ed91d41453d371493fae8d10')]:
    dec = int(rpc('eth_call', [{'to': a, 'data': '0x313ce567'}, 'latest']), 16)
    li = rpc('eth_getLogs', [{'address': a, 'fromBlock': hex(FROM), 'toBlock': hex(head), 'topics': [T_TRANSFER, None, pad(w)]}], PUB)
    lo = rpc('eth_getLogs', [{'address': a, 'fromBlock': hex(FROM), 'toBlock': hex(head), 'topics': [T_TRANSFER, pad(w)]}], PUB)
    senders = defaultdict(float)
    for l in li: senders['0x' + l['topics'][1][26:]] += int(l['data'], 16) / 10 ** dec
    led_in = c.execute("SELECT SUM(amount) FROM eth_edge WHERE run_id=? AND asset=? AND too=? AND cls LIKE 'in:%'", (r, a, w)).fetchone()[0] or 0
    rec.append({'symbol': s, 'wallet': w, 'logs_in': sum(senders.values()), 'logs_out': sum(int(l['data'], 16) / 10 ** dec for l in lo), 'ledger_in': led_in,
                'senders': sorted(senders.items(), key=lambda kv: -kv[1])[:6]})
    log(f"   {s}: logs IN {rec[-1]['logs_in']:,.4f} vs ledger IN {led_in:,.4f} | OUT {rec[-1]['logs_out']:,.4f} | senders {[(k[:10], round(v, 2)) for k, v in rec[-1]['senders'][:4]]}")
  out['groupB'] = rec
  json.dump(out, open(os.path.join(HERE, 'raw/eth_cleanup.json'), 'w'), indent=1)
  log('DONE -> raw/eth_cleanup.json')

if __name__ == '__main__':
  main()
