# Multi-Pair H1 Session Breakout — Phase 1 Status

Date: 2026-07-20  
Classification: **REJECT pending data**

No real MT5 H1 CSVs are present on the VPS, so no performance runner was executed and no research result JSON was generated. This status contains no fabricated or substitute results. The preregistered family remains rejected pending compliant data and must not be adapted in response to this absence.

## Windows PC export required

From a logged-in MetaTrader 5 demo-terminal Windows PC, Kade should copy the standalone `engine/mt5_history_export.py`, open PowerShell in its directory, and run:

```powershell
py -m pip install pandas MetaTrader5
$pairs = 'EURUSD','GBPUSD','USDJPY','AUDUSD'
foreach ($pair in $pairs) {
  py .\mt5_history_export.py --symbol $pair --timeframe H1 --start 2010-01-01 --end 2026-07-21 --output ".\raw_mt5_${pair}_1h.csv"
}
```

Copy each generated CSV and its adjacent `.manifest.json` into `engine/data/` without renaming. USDCAD may be exported the same way only as the preregistered optional pair. Do not merge sources or replace missing MT5 history with yfinance. Once the four core files are present, run `python engine/run_session_breakout_research.py`; the runner is unchanged and refuses absent inputs explicitly.

Safety state: `paper_only=true`; `ALLOW_LIVE_ORDERS=false`; no order endpoint or call was added; gates, watcher, forward ledger, and credentials remain untouched.
