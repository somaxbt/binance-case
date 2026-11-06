"""Label the ETH-side contracts the Binance tree paid into (resolved 2026-11-02: user cross-check + Blockscout verified names /
on-chain forwarding). Writes the durable ~/traversal-engine/data/attrib-verified.json (idempotent via note) AND live attrib.db.
  python3 contract_attrib.py          (dry run)      python3 contract_attrib.py --write"""
import json, os, sys, shutil, sqlite3, time
LEDGER = os.path.expanduser('~/traversal-engine/data/attrib-verified.json'); DB = os.path.expanduser('~/traversal-engine/data/attrib.db')
TAG, SRC, CONF, ADDED = 'binance-eth-contracts', 'analyst:binance-eth-contracts:2026-11-02', 'attested', time.strftime('%Y-%m-%d')
U, B = 'user cross-check 2026-11-02', 'Blockscout verified name + on-chain forwarding'
ROWS = [  # address, entity, category, how
    ('0xe7e68d336f90f98d22a479253eafa5f2424acad8', 'Symbiosis: OnchainGateway', 'bridge', U + ' (probable); same creator as MetaRouterGateway'),
    ('0xb4769e9c5be31199a25ecd1b0c6609183fa72521', 'Symbiosis: MetaRouterGateway', 'bridge', U),
    ('0xbc1d9760bd6ca468ca9fb5ff2cfbeac35d86c973', 'Bitget Wallet: swap router', 'dex', U),
    ('0x0ba6d224169bbfad4eb2d38c500d2c8e8ede696c', 'Bitget Wallet: swap', 'dex', U),
    ('0xba3cb449bd2b4adddbc894d8697f5170800eadec', 'CoW Swap: EthFlow', 'dex', U + '; ' + B),
    ('0xe3985e6b61b814f7cdb188766562ba71b446b46d', 'Maya Protocol: Router', 'bridge', U),
    ('0xe12e0f117d23a5ccc57f8935cd8c4e80cd91ff01', '1inch: Native Order Factory', 'dex', U),
    ('0xf01c98b3bef6cc96bd484e092cc2a56016ac2ed6', 'LI.FI: Intents Bridge', 'bridge', U),
    ('0x2f68417a18da681589f4ea64b9cc9839209acff7', 'PancakeSwap: Aggregator', 'dex', U),
    ('0xe00c629afaccb0510995a2b95560e446a24c85b9', 'OmniBridge: Proxy', 'bridge', U),
    ('0x794dbdbdbfd3f8a3b887f4513bf5ff29edd04a94', 'PrefundedAdapter', 'dex', U),
    ('0x337685fdab40d39bd02028545a4ffa7d287cc3e2', 'Mayan: Forwarder 2', 'bridge', U),
    ('0xd322a49006fc828f9b5b37ab215f99b4e5cab19c', 'Aave v3: WrappedTokenGatewayV3', 'defi', B),
    ('0x23617e59a5925b2a4bf75d73ff6711cd0b29de85', 'Uniswap: UniversalRouter', 'dex', B),
    ('0x4cd00e387622c35bddb9b4c962c136462338bc31', 'Relay: Depository', 'bridge', B),
    ('0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f', 'Relay: RouterV3', 'bridge', B),
    ('0xc1d13492285eb664951e201bf7c80c7c6318a1b5', 'SWFT: SwftSwap', 'bridge', B),
    ('0x21bd29bccae1580e3742cd90e5f4a20f647f54dd', 'Bridgers (SWFT): BridgersSwap', 'bridge', B),
    ('0x6adb6e62d9eccb0ff8406d04094604de521c2440', 'Bridgers (SWFT): swap', 'bridge', 'same creator 0xB9b27157 as BridgersSwap'),
    ('0x6ebd94cee5d8250db3756d8a85739e9a91aa3a0d', 'Bridgers (SWFT): swap', 'bridge', 'same creator 0xB9b27157 as BridgersSwap'),
    ('0xe7351fd770a37282b91d153ee690b63579d6dd7f', 'deBridge: DLN', 'bridge', B),
    ('0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae', 'LI.FI: Diamond', 'bridge', B),
    ('0x0000000000bbf5c5fd284e657f01bd000933c96d', 'Velora: Delta Adapter', 'dex', B),
    ('0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146', 'THORChain: Router', 'bridge', B),
    # 2026-11-04: senders of 'in:outside' ETH found by eth_foreign_backtrack.py
    ('0x77b2043768d28e9c9ab44e1abfc95944bce57931', 'Stargate: StargatePoolNative', 'bridge', B),
    ('0x663dc15d3c1ac63ff12e45ab68fea3f0a883c251', 'deBridge: Router', 'bridge', B + ' (proxy, impl DeBridgeRouter)'),
    ('0x9008d19f58aabd9ed0d60971565aa8510560ab41', 'CoW Protocol: GPv2Settlement', 'dex', B),
    ('0xf5e10380213880111522dd0efd3dbb45b9f62bcc', 'Chainflip: Vault', 'bridge', 'Blockscout name Vault; creator of the Chainflip deposit channels below'),
] + [(a, 'Chainflip: deposit channel', 'bridge', 'creator = Chainflip Vault 0xF5e10380…; forwards ETH to Vault') for a in (
    '0xa28753180c2f36f678d542474c80d4ebb92c65b5', '0xda815796a9160d9500a851b744227d4caf4ab9b8', '0x10745003782290c5cd1fda9cda694e3db679fd4a',
    '0x0afcbd4252cc2afe32a0d43bb1ee45bb1ced1b36', '0x0f64cee2bb2749274a286d48d7a4e65829bfa3ae', '0xcdebb2782d53c7a9936f5323b156f1054f32c10c',
    '0xa77dbcff966e82e4485d9535520d256499dc6521', '0x30ed3b48ca2e80fedb9b60437223f4621e292d80')]
assert len({r[0] for r in ROWS}) == len(ROWS) == 36, len(ROWS)
mine = [{'address': a, 'chain': 'eth', 'entity': e, 'category': c, 'kind': k, 'source': SRC, 'confidence': CONF, 'added': ADDED, 'note': TAG} for a, e, c, k in ROWS]
C = sqlite3.connect(DB)
for r in mine:
    for e, cat, s in C.execute("SELECT entity, category, source FROM attrib_v WHERE address=? AND chain='eth'", (r['address'],)):
        if s != SRC: print('  existing:', r['address'], e, cat, s)
print('rows:', len(mine))
if '--write' not in sys.argv: print('dry run — add --write'); sys.exit()
ts = time.strftime('%Y%m%dT%H%M%S'); shutil.copy(LEDGER, LEDGER + f'.bak-{ts}'); shutil.copy(DB, DB + f'.bak-{ts}')
led = [r for r in json.load(open(LEDGER)) if r.get('note') != TAG]
json.dump(led + mine, open(LEDGER, 'w'), indent=2)
def ref(table, name):
    C.execute(f'INSERT OR IGNORE INTO {table}(name) VALUES (?)', (name,)); return C.execute(f'SELECT id FROM {table} WHERE name=?', (name,)).fetchone()[0]
sid = ref('source_ref', SRC); C.execute('DELETE FROM attrib WHERE source_id=?', (sid,))
C.executemany('INSERT INTO attrib(address, chain, entity_id, category, kind, source_id, confidence, added) VALUES (?,?,?,?,?,?,?,?)',
              [(r['address'], 'eth', ref('entity_ref', r['entity']), r['category'], r['kind'], sid, CONF, ADDED) for r in mine])
C.commit(); print('written', C.execute('SELECT COUNT(*) FROM attrib WHERE source_id=?', (sid,)).fetchone()[0], 'rows; backup', ts)
