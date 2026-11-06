#!/bin/zsh
# One find -> resolve -> add cycle on the Tron tree (see NOTES 2026-11-01). Log: raw/tron/cycle_<ts>.log
cd ~/cases/binance; set -o pipefail
step(){ echo "=== $(date -u +%H:%M:%S) $1"; }
cp binance-live.db binance-live.db.bak-cycle-$(date +%Y%m%dT%H%M)
step "1 Chainflip: resolve new deposits + refund loop"
for i in 1 2 3; do
  python3 -u bridge_resolve.py cf | grep -E "deposits|states"
  R=$(python3 cf_refund_decode.py); echo "$R"
  echo "$R" | grep -q "OUTSIDE 0.00" && break
  python3 -u cf_refund_repair.py raw/tron/cf_refunds.json | grep -E "UNEXPLAINED|ERROR|carried" | tail -3
done
step "2 Relay / Symbiosis / USDT0 / Across: new deposits"
python3 -u relay_resolve.py | grep -E "deposit txs|senders,|status" | tail -2
python3 -u bridge_resolve.py sym | grep -E "deposits|states"
python3 -u bridge_resolve.py usdt0 | grep -E "deposits|states"
python3 -u across_resolve.py | grep -E "across:|status" | tail -2
step "3 Swap outputs to third parties (new swaps)"
python3 -u swap_redirects.py | grep -E "swap txs|NON-tree|fresh third" 
python3 -u cf_refund_repair.py raw/tron/swap_redirect_add.json | grep -E "UNEXPLAINED|ERROR|carried" | tail -3
step "4 External wallets: classify + add fresh attacker hops"
NO_TRONSCAN=1 python3 -u external_resolve.py 400 | tail -1
python3 ext_add.py
python3 -u cf_refund_repair.py raw/tron/external_add_auto.json | grep -E "UNEXPLAINED|ERROR|carried" | tail -3
step "5 Accounting + pages"
python3 exit_accounting.py | grep -E "^== |HELD|NOT RESOLVED" | head -30
python3 dest_watch.py > /dev/null 2>&1 && echo "destination watch list refreshed"
step "done"
