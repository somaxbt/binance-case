#!/bin/zsh
# Chainflip short cycle only (new deposits + refund loop) + accounting/pages refresh. No Tron incremental.
cd ~/cases/binance
step(){ echo "=== $(date -u +%H:%M:%S) $1"; }
step "1 Chainflip: new deposits + refund loop"
for i in 1 2 3; do
  python3 -u bridge_resolve.py cf | grep -E "deposits|states"
  R=$(python3 cf_refund_decode.py); echo "$R"
  echo "$R" | grep -q "OUTSIDE 0.00" && break
  python3 -u cf_refund_repair.py raw/tron/cf_refunds.json | grep -E "UNEXPLAINED|ERROR|carried" | tail -3
done
step "2 Accounting + pages"
python3 exit_accounting.py | grep -E "^== (Chainflip|STILL)|NOT RESOLVED" | head -8
step "done"
