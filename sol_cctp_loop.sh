#!/bin/sh
# 11-04: SOL ledger <-> seed finders until no new seeds: (a) CCTP round trip via dYdX (cctp_return.py),
# (b) mixer withdrawals that land in the tree (foreign_backtrack.py, Privacy Cash). Fixed END from SOL_END.
# Usage: SOL_END=2026-11-04T01:32:07Z sh sol_cctp_loop.sh   -> raw/sol_ledger_next.json + raw/sol/{cctp_returns,mixer_seeds}.json
set -e
export HELIUS_RPS=40 SOL_PREFETCH=32 SOL_LOOKAHEAD=256 SOL_RELAY=cache SOL_OUT=raw/sol_ledger_next.json SOL_LEDGER=raw/sol_ledger_next.json
export SOL_SEEDS=raw/sol/cctp_returns.json,raw/sol/mixer_seeds.json
# 11-04 (user): INCREMENTAL by default — base = newest archived END ledger whose END is before SOL_END (sol_ledger.py SOL_BASE:
# unchanged wallets come from cache). SOL_FULL=1 = full re-read of every wallet (do one now and then; validated identical 11-04 at END 08:46).
[ -z "$SOL_FULL" ] && [ -z "$SOL_BASE" ] && SOL_BASE=$(python3 -c "
import glob, json, os, time
e = os.environ['SOL_END']; e = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(e))) if e.isdigit() else e
c = sorted((json.load(open(f))['window']['end'], f) for f in glob.glob('raw/sol/ledger_*_END_run*.json'))
c = [f for end, f in c if end and end < e]; print(c[-1] if c else '')")
export SOL_BASE; echo "SOL_BASE: ${SOL_BASE:-none (full run)}"
count() { python3 -c "import json,os;print(sum(len(json.load(open(f))['seeds']) for f in '$SOL_SEEDS'.split(',') if os.path.exists(f)))"; }
prev=-1
for i in 1 2 3 4 5 6; do
  n=$(count); echo "ROUND $i: seeds $n (prev $prev)"
  [ "$n" = "$prev" ] && { echo "CONVERGED: seeds $n"; { python3 ~/cases/_xcase/xcase_index.py >/dev/null 2>&1; python3 ~/cases/_xcase/xcase_check.py --case binance --sol "$SOL_OUT" --out raw/overlaps_sol.json; } || true; exit 0; }   # 11-04: cross-case overlaps (read-only, fail-open, XCASE=0 skips)
  prev=$n
  python3 -u sol_ledger.py > raw/sol_ledger_loop_r$i.log 2>&1
  grep -E 'pass 1 done|^===|HELD' raw/sol_ledger_loop_r$i.log | sed "s/^/  r$i ledger: /"
  python3 -u foreign_backtrack.py > raw/sol/foreign_backtrack_r$i.log 2>&1
  grep -E '^MIXER SEEDS' raw/sol/foreign_backtrack_r$i.log | sed "s/^/  r$i demix: /"
  python3 -u cctp_return.py > raw/sol/cctp_return_loop_r$i.log 2>&1
  grep -E '^[1-4]\. ' raw/sol/cctp_return_loop_r$i.log | cut -c1-200 | sed "s/^/  r$i cctp: /"
done
echo "STOPPED after 6 rounds (not converged)"
