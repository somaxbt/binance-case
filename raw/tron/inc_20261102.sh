#!/bin/zsh
cd ~/cases/binance; set -e -o pipefail
[ -f binance-live.db.bak-inc-20261102 ] || cp binance-live.db binance-live.db.bak-inc-20261102
BASE=$(sqlite3 binance-live.db "select run_id from ledger_run where leg='tron2' and finished glob '2026*' order by started desc limit 1")
echo "=== $(date -u +%H:%M:%S) recheck from $BASE"
python3 tron_recheck.py $BASE > raw/tron/recheck_run_20261102.txt; head -5 raw/tron/recheck_run_20261102.txt
RJ=$(ls -t raw/tron/recheck_${BASE}_*.json | head -1)
echo "=== $(date -u +%H:%M:%S) tron_fast $BASE $RJ"
python3 -u tron_fast.py $BASE "$RJ"
echo "=== $(date -u +%H:%M:%S) done"
