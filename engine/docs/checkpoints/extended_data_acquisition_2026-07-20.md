# Extended Data Acquisition — Results & Canonical-Source Decision
Date: 2026-07-20 · HEAD: fda8d94 (pre-docs) · Tooling baseline: 92420fa

## Part 2 — Real VPS yfinance acquisition
**SUCCESS on the real VPS** (the Codex protected sandbox had DNS blocked; the real
VPS is not subject to that restriction).

- DNS: `query1.finance.yahoo.com` resolves; HTTPS `query1.finance.yahoo.com` returns
  `429` (rate-limit) then succeeds on retry.
- Command (already in the repo):
  `cd engine && /usr/local/lib/hermes-agent/venv/bin/python3 run_acquire_data.py --start 2010-01-01`
- Result: **4306 daily rows, 2010-01-01 → 2026-07-17**, canonical D1.
  Raw fingerprint `2d151e8429dd78a7f2c2179891c8491fcab01f17aabb8949023145a81ad6972a`.
- Writes to `data/raw_yfinance_EURUSD=X_1d.csv` (separate from the canonical cache;
  the cache is never clobbered — see defect fix below).
- 2015-01-01 was not needed; 2010-01-01 was fully available.

## Part 1 — 26 invalid OHLC rows (root cause)
**Classification: SOURCE-DATA DEFECT** (not a transformation defect, not a
validation-rule defect).

yfinance FX daily bars synthesize `open == close` (the adjusted close) while
`high`/`low` come from intraday aggregation. For a genuine minority of rows the
synthesized open/close fall outside `[low, high]`, violating `high>=open` /
`low<=close` by up to ~2.7 pips (median ~1 pip). The defect scales with the
window: 26 / 777 (3.3%) on the V2 slice, 118 / 4306 (2.7%) on the extended
pull — same rate, confirming it is inherent to the source, not noise or a code bug.

- The integrity invariants are **correct and must stay enforced**. No rule change.
- 602/777 (V2) and 1325/4306 (extended) rows have `open==close` exactly — the
  artifact that produces the failures.
- **Resolution policy: yfinance FX daily is disqualified as canonical OHLC.** Do NOT
  fabricate, interpolate, or repair prices. Use **MT5 D1 broker bars** as the
  canonical research source; keep yfinance (close-only / breadth) as a comparison
  dataset only.

### Defect fix (committed: fda8d94)
`fetch_yfinance` previously always wrote its result to the shared canonical cache
`yf_<SYM>_<tf>.csv`. An explicit-window fetch (the extended-history path) therefore
clobbered the V2/V3 canonical cache. Fixed so the cache is only refreshed for the
default rolling-window fetch; explicit start/end pulls return the data without
touching the cache. Regression test added. The canonical V2/V3 window was restored
from the preserved extended pull and **reproduces V2 exactly** (20 closed / 1 open
/ PF 1.1862 / eligible=false), confirming functional equivalence.

## Part 3 — MT5 D1 export (requires Windows PC; not runnable from VPS)
The standalone exporter `engine/mt5_history_export.py` is read-only (market-data
`copy_rates_range` only), contains no order imports/calls, sanitizes broker
company/server, never prints account number, normalizes epoch→UTC, excludes the
incomplete candle, writes atomically with SHA-256 manifest to
`data/raw_mt5_EURUSD_1d.csv`. It **must run on the Windows PC** (local MT5 terminal
+ `MetaTrader5` lib). It cannot run on the VPS and must NOT be routed through any
bridge/order path. The VPS→PC bridge is online (`/health` 200) but does not expose a
"run script" endpoint.

### Exact PowerShell steps for Kade (paste in order)
```powershell
# 0) Prereqs on the PC (one time): in the engine venv run
#    pip install MetaTrader5 pandas

# 1) Pull the current repo EXACTLY as on the VPS (so the exporter matches):
git -C "C:\path\to\aether-forex-lab" pull

# 2) Run the exporter (MT5 must be open + logged into MetaQuotes demo):
cd "C:\path\to\aether-forex-lab\engine"
.venv\Scripts\python.exe mt5_history_export.py --start 2010-01-01
# If 2010 unavailable from the broker, the script still returns whatever the
# terminal holds; note the actual first/last candle it prints.

# 3) Copy the raw export + manifest back to the VPS over tailnet:
scp -P 22 data/raw_mt5_EURUSD_1d.csv data/raw_mt5_EURUSD_1d.manifest.json `
    root@100.123.232.20:/root/aether-forex-lab/engine/data/
```
VPS tailnet IP: `100.123.232.20`. SHA-256 of the exporter to verify before use:
`ac73e1c67d0bf72f5aea1b8fa09a19745fa69ea521ef1b675be4ddb8f04f0ad4`.
(If you prefer SCP-with-verify, the verify-after-copy + py_compile step is in the
canonical-eval tooling notes; the file is unchanged on the VPS.)

## Part 4 / 7 — Extended evaluation on yfinance (comparison only; not canonical)
Full 2010–2026 run (4306 bars) via `src.canonical_eval`:

| Strategy            | Closed | Lifecycle PF | OOS ret  | Score | Eligible |
|---------------------|-------:|-------------:|---------:|------:|---------:|
| ema_crossover       |    149 |      1.0541 | −36.01%  |  22.0| No |
| ema_trend_pullback  |    171 |      1.0351 |  −0.17%  |  36.5| No |
| rsi_mean_reversion  |    251 |      1.0146 |  −1.11%  |  42.9| No |
| macd_trend_confirm  |    378 |      0.8633 | −59.08%  |  16.2| No |
| london_breakout     |     22 |      0.6071 |  +0.09%  |  25.9| No |

**Every strategy is decisively rejected on the extended sample.** The 3-year
window had flattered EMA crossover (PF 1.1862); over 16 years the apparent edge
disappears (PF 1.05, large OOS loss). This is exactly why extended history was
required.

### V2-slice reconciliation (deterministic proof)
The 2023-07-20 → 2026-07-17 slice extracted from the extended file reproduces V2
**byte-for-byte**: 20 closed + 1 open, lifecycle PF **1.1862**, eligible=false,
777 rows. The evaluation pipeline is deterministic and the extended data is
consistent with the prior cache on the overlap.

## Part 6 — Canonical research source decision
**MT5 D1 is the canonical research source** (once exported). Policy: clean broker
OHLC, zero unresolved invalid rows, execution-aligned (matches the live demo
terminal the lab will eventually trade on), deterministic fingerprint. yfinance is
retained only as a breadth comparison dataset. No source mixing.

## Part 8 — Next-strategy authorization decision
**4. NO STRATEGY DEVELOPMENT YET.**
- Extended yfinance coverage was genuinely obtained (2010–2026) and shows no
  surviving strategy.
- The *canonical* source (MT5 D1) is not yet exported; its invalid-OHLC rows are
  expected to be ~0, but it must be validated before conclusions are final.
- EMA crossover lifecycle PF falls below 1.3 on extended history (1.05) — it is
  not watcher-eligible and not a candidate.
- Insufficient evidence of persistence across regimes/periods.
No strategy is called profitable. Do not authorize development until the MT5
export is validated and the canonical rebaseline is rerun on clean broker bars.

## Safety confirmation
- Gates unchanged (score≥40, robustness≥0.3, OOS>0, lifecycle PF≥1.3).
- `paper_only=true`, `ALLOW_LIVE_ORDERS=false` unchanged.
- No order endpoint was called or added; the MT5 exporter is market-data only.
- No credentials/tokens/account numbers in this document or any commit.
- yfinance extended raw file and OHLC-report JSON/MD are gitignored reproduceable
  artifacts; only source, tests, and this doc were committed.

## Unresolved
- MT5 D1 export pending Kade's PC action (PowerShell steps above).
- Canonical rebaseline on MT5 bars pending that export.
- yfinance FX invalid-OHLC disqualifies it as canonical (documented, not concealed).
