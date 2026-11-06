#!/bin/zsh
cd ~/cases/binance
echo "=== $(date -u +%H:%M:%S) 1/2 sol branch (new wave from pot, since 05:10 UTC)"
python3 -u sol_branch.py AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU 1793596200 6 > raw/sol/branch_run_wave2.log 2>&1 && echo "sol branch ok" || echo "sol branch FAILED"
echo "=== $(date -u +%H:%M:%S) 2/2 xrp branch (from rK21, since 03:50 UTC)"
python3 -u xrp_branch.py 1793590800 4 > raw/xrp_branch_run.log 2>&1 && echo "xrp branch ok" || echo "xrp branch FAILED"
echo "=== $(date -u +%H:%M:%S) chain done"
