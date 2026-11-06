#!/bin/zsh
# Chainflip short cycle + Tron incremental from the latest finished run to now + refresh.
cd ~/cases/binance
step(){ echo "=== $(date -u +%H:%M:%S) $1"; }
cp binance-live.db binance-live.db.bak-catchup-$(date +%Y%m%dT%H%M)
step "1 Chainflip: new deposits + refund loop"
for i in 1 2 3; do
  python3 -u bridge_resolve.py cf | grep -E "deposits|states"
  R=$(python3 cf_refund_decode.py); echo "$R"
  echo "$R" | grep -q "OUTSIDE 0.00" && break
  python3 -u cf_refund_repair.py raw/tron/cf_refunds.json | grep -E "UNEXPLAINED|ERROR|carried" | tail -3
done
BASE=$(sqlite3 binance-live.db "select run_id from ledger_run where leg='tron2' and finished glob '2026*' order by started desc limit 1")
step "2 Tron incremental from $BASE"
python3 tron_recheck.py $BASE > raw/tron/recheck_catchup.txt 2>&1; tail -3 raw/tron/recheck_catchup.txt   # 11-05: no pipe to head (BrokenPipe killed the recheck)
RJ=$(ls -t raw/tron/recheck_${BASE}_*.json | head -1)
python3 -u tron_fast.py $BASE "$RJ" > raw/tron/fast_run_catchup.txt 2>&1
grep -v "^\[" raw/tron/fast_run_catchup.txt | grep -E "window|wallets read|UNEXPLAINED|held \(|ERROR"
step "3 Accounting + pages + destination watch"
python3 exit_accounting.py | grep -E "^== (THORChain|Relay|Chainflip|Bitget|Symbiosis|STILL)|NOT RESOLVED" | head -16
python3 dest_watch.py --check 2>&1 | sed -n '/CHANGED since baseline/,/^$/p' | head -15
step "done"
