"""Label the FBI-published Binance-hack addresses (alert 2026-10-31, TraderTraitor/DPRK) in the attribution store.
Writes the durable file ~/traversal-engine/data/attrib-verified.json (rebuild-safe; idempotent via note 'binance-fbi')
AND the live ~/traversal-engine/data/attrib.db. Input: raw/fbi/fbi_{eth,btc,sol}.txt (608 / 19 / 1).
  python3 fbi_attrib.py            (dry run: counts + conflicts)      python3 fbi_attrib.py --write"""
import json, os, sys, shutil, sqlite3, time
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.expanduser('~/traversal-engine/data/attrib-verified.json'); DB = os.path.expanduser('~/traversal-engine/data/attrib.db')
TAG, SRC, ENT, CAT, CONF = 'binance-fbi', 'fbi:psa:2026-10-31', 'Binance Hacker', 'hack', 'verified'
KIND = 'FBI PSA 2026-10-31 · TraderTraitor (DPRK) · North Korea Responsible for $6 Billion+ Binance Attack'
ADDED = time.strftime('%Y-%m-%d')
mine = []
for chain, f in (('eth', 'fbi_eth.txt'), ('btc', 'fbi_btc.txt'), ('sol', 'fbi_sol.txt')):
    for a in open(os.path.join(HERE, 'raw', 'fbi', f)).read().split():
        mine.append({'address': a.lower() if chain == 'eth' else a, 'chain': chain, 'entity': ENT, 'category': CAT, 'kind': KIND,
                     'source': SRC, 'confidence': CONF, 'added': ADDED, 'note': TAG})
assert Counter(r['chain'] for r in mine) == Counter({'eth': 608, 'btc': 19, 'sol': 1}), Counter(r['chain'] for r in mine)
# conflicts: same address already labelled as something else (esp. an exchange / service)
C = sqlite3.connect(DB); conf = []
for r in mine:
    for e, cat, s in C.execute("SELECT entity, category, source FROM attrib_v WHERE address=? AND chain=?", (r['address'], r['chain'])):
        if s != SRC: conf.append((r['chain'], r['address'], e, cat, s))
print('rows to write:', Counter(r['chain'] for r in mine), '| existing labels on these addresses:', len(conf))
for c in conf[:20]: print('  ', c)
if '--write' not in sys.argv: print('dry run — add --write'); sys.exit()
ts = time.strftime('%Y%m%dT%H%M%S'); shutil.copy(LEDGER, LEDGER + f'.bak-{ts}'); shutil.copy(DB, DB + f'.bak-{ts}')
led = [r for r in json.load(open(LEDGER)) if not str(r.get('note', '')).startswith(TAG)]
json.dump(led + mine, open(LEDGER, 'w'), indent=2)
def ref(table, name):
    C.execute(f'INSERT OR IGNORE INTO {table}(name) VALUES (?)', (name,)); return C.execute(f'SELECT id FROM {table} WHERE name=?', (name,)).fetchone()[0]
eid, sid = ref('entity_ref', ENT), ref('source_ref', SRC)
C.execute('DELETE FROM attrib WHERE source_id=?', (sid,))
C.executemany('INSERT OR REPLACE INTO attrib(address, chain, entity_id, category, kind, source_id, confidence, added) VALUES (?,?,?,?,?,?,?,?)',
              [(r['address'], r['chain'], eid, CAT, KIND, sid, CONF, ADDED) for r in mine])
C.commit()
print('written: ledger', len(mine), 'rows (backup', ts + ')', '| live DB', C.execute('SELECT chain, COUNT(*) FROM attrib WHERE source_id=? GROUP BY chain', (sid,)).fetchall())
