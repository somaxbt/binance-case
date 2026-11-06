"""Eagle Eye privacy audit (11-05): run after every rebuild.   python3 page_audit.py [page.html ...]
FAILS (exit 1) on: anything the page loads/calls by itself (script src, link, @import, css url(http), img http, iframe, fetch, XHR, WebSocket,
sendBeacon, eval), any .env key VALUE (names printed only), personal/local strings, tool/method words. ECharts (inlined, no network) is skipped.
localStorage is allowed only for view settings (theme, dragged graph layout)."""
import re, os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ECH = open('raw/tron/graph/echarts-5.5.1.min.js').read()
E = {l.split('=', 1)[0].strip(): l.split('=', 1)[1].strip().strip('"').strip("'") for l in open(os.path.expanduser('~/traversal-engine/.env.local')) if '=' in l and not l.startswith('#')}
AUTO = [r'<script[^>]+src=', r'<link[^>]+href=', r'@import', r'url\(["\']?https?:', r'<img[^>]+src=["\']https?:', r'<iframe', r'\bfetch\s*\(', r'XMLHttpRequest', r'WebSocket', r'sendBeacon', r'\beval\s*\(']
LOCAL = ['proton.me', '/Users/', '~/cases', '~/traversal', 'somuknr', 'localhost', '127.0.0.1', 'scratchpad', '.env.local']
WORDS = ['HyperSync', 'Helius', 'QuickNode', 'Alchemy', 'TronGrid', 'nearblocks', 'attrib.db', 'heuristic', 'demix', 'de-mix', 'api-key', 'apikey', 'x-client-id', r'\.py\b', r'\.db\b', r'\bseeds?\b', 'resolver']
bad = 0
for p in sys.argv[1:] or ['raw/graph/binance_fund_flow.html', 'raw/tron/graph/tron_leg.html']:
    b = open(p, errors='replace').read().replace(ECH, '')
    auto = [rx for rx in AUTO if re.search(rx, b)]
    store = [m for m in re.findall(r'localStorage\.\w+\(([^,)]+)', b) if not re.search(r"-(theme|layout)['\"]", m) and m not in ('LK',)]
    keys = [k for k, v in E.items() if len(v) >= 10 and v in b]
    local = [w for w in LOCAL if w.lower() in b.lower()]
    words = [w for w in WORDS if re.search(w, b)]
    hosts = sorted(set(re.findall(r'https?://([a-zA-Z0-9.-]+)', b)))
    ok = not (auto or store or keys or local or words); bad += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {p}: auto-load {auto or '-'} · storage {store or 'theme only'} · KEY NAMES {keys or '-'} · local {local or '-'} · words {words or '-'}\n     link hosts (open only on click): {', '.join(hosts)}")
sys.exit(1 if bad else 0)
