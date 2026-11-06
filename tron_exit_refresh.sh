#!/bin/zsh
# Tron EXIT refresh (tracing loop step 3, endpoint resolution) on the EXISTING Tron ledger — no tron_fast/tron_recheck, no new ledger run.
# Bridge lookups for exits already in the ledger -> THORChain reports for runs that lack one -> exit_accounting (carry_over_seeds.csv).
# Run after every Tron ledger update, BEFORE any downstream (BTC/ETH) seed build.   zsh tron_exit_refresh.sh > raw/tron/exit_refresh_<ts>.log 2>&1
cd ~/cases/binance
step(){ echo "=== $(date -u +%H:%M:%S) $1"; }
TS=$(date +%Y%m%dT%H%M)
cp binance-live.db binance-live.db.bak-exitrefresh-$TS
for f in raw/tron/carry_over_seeds.csv raw/tron/exit_accounting.json raw/tron/graph/tron_leg.html; do [ -f $f ] && cp $f $f.bak-$TS; done
step "1 bridge lookups (cached; only new deposits hit the APIs)"
for k in cf sym usdt0; do python3 -u bridge_resolve.py $k 2>&1 | tail -4; done
python3 -u relay_resolve.py 2>&1 | tail -4
step "2 Chainflip refund check (report only, no repair)"
python3 cf_refund_decode.py 2>&1 | tail -4
step "3 THORChain reports for runs without one"
for r in $(python3 -c "import tron_graph as g,sqlite3;C=sqlite3.connect(f'file:{g.DB}?mode=ro',uri=True);print(' '.join(r for r,_ in g.run_chain(C)))"); do
  [ -f raw/tron/report_$r.txt ] && continue
  echo "  report $r"; python3 -u tron_report.py $r > raw/tron/report_$r.txt 2>&1 || echo "  FAILED $r"
done
step "4 exit accounting"
python3 exit_accounting.py 2>&1 | tail -40
step "done"
