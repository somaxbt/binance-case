"""Screenshot the local Binance pages the way the user views them (MacBook 1440x800, retina x2). Prints JS errors.
  python3 shot.py all|pool|net|svc:<Service name>|hl  [OUT.png]
  all = All-chains overview · pool = Tron 'Laundering pool' drill · net = Tron network view (>= $250k) · svc:Relay = one service view
  hl  = pool view with the other routes + stayed-on-Tron highlighted (tweet 7)"""
import sys
from playwright.sync_api import sync_playwright
V = sys.argv[1] if len(sys.argv) > 1 else 'all'; OUT = sys.argv[2] if len(sys.argv) > 2 else f'screenshots/{V.replace(":", "_")}.png'
import os; os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1440, 'height': 800}, device_scale_factor=2); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('file://' + os.path.abspath('raw/graph/binance_fund_flow.html'), timeout=120000); pg.wait_for_timeout(9000)   # 11-05: 3 s shot a blank Sankey on the 39 MB page
    if V != 'all':
        pg.evaluate("()=>document.querySelector('.cc[data-c=\"tron\"]').click()"); pg.wait_for_timeout(2500)
    if V == 'net':
        pg.evaluate("()=>document.querySelector('button[data-t=\"net\"]').click()"); pg.wait_for_timeout(3500)
        pg.evaluate("()=>document.querySelector('#net').scrollIntoView({block:'start'})")
    elif V in ('pool', 'hl') or V.startswith('svc:'):
        pg.evaluate(f"()=>drill({('Laundering pool' if not V.startswith('svc:') else V[4:])!r})"); pg.wait_for_timeout(1800)
        if V == 'hl':
            pg.evaluate("""()=>{const c=echarts.getInstanceByDom(document.querySelector('#sankey'));const o=c.getOption().series[0];
              const keep=/^(USDT0 bridge|Across|Bitget Wallet|Bridgers|NEAR Intents|Stayed on Tron|JustLend|USDD|HitBTC|Gate|External wallets|Smaller)/;
              c.dispatchAction({type:'highlight',seriesIndex:0,dataIndex:o.data.map((d,i)=>keep.test(d.name)?i:-1).filter(i=>i>=0)})}"""); pg.wait_for_timeout(900)
        pg.locator('#sankey').locator('xpath=..').scroll_into_view_if_needed()
    pg.wait_for_timeout(400); pg.screenshot(path=OUT); print(OUT, '| JS errors:', errs[:2] or 'none'); b.close()
