#!/bin/zsh
cd ~/cases/binance
echo "=== $(date -u +%H:%M:%S) 1/3 movement check"
python3 -u move_check.py > raw/move_check_run_$(date +%Y%m%dT%H%M).txt 2>&1 && echo "move_check ok" || echo "move_check FAILED"
echo "=== $(date -u +%H:%M:%S) 2/3 tron incremental"
cp binance-live.db binance-live.db.bak-inc-$(date +%Y%m%dT%H%M)
BASE=$(sqlite3 binance-live.db "select run_id from ledger_run where leg='tron2' and finished glob '2026*' order by started desc limit 1")
python3 tron_recheck.py $BASE > raw/tron/recheck_run_latest.txt 2>&1 && RJ=$(ls -t raw/tron/recheck_${BASE}_*.json | head -1) && \
python3 -u tron_fast.py $BASE "$RJ" > raw/tron/fast_run_latest.txt 2>&1 && echo "tron ok ($BASE → new run)" || echo "tron FAILED"
echo "=== $(date -u +%H:%M:%S) 3/3 sol incremental"
python3 -u sol_ledger.py > raw/sol/sol_ledger_run_latest.log 2>&1 && echo "sol ok" || echo "sol FAILED"
echo "=== $(date -u +%H:%M:%S) chain done"
