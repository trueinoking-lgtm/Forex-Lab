# Tradeability Watcher

A safe, scheduled watcher that evaluates **all EURUSD strategies** through the
normal pipeline + the existing walk-forward trade gate, and — only when a
strategy **naturally** qualifies — creates a genuinely fresh paper Signal, runs
the broker-aware preflight and the VPS→PC **dry-run**, and records the result.

It **never places an order** and **never lowers any gate**.

## What it does (per run)

1. Acquires a process lock (`fcntl.flock`) so two runs can never overlap.
2. Checks the PC bridge / Tailscale is reachable. If not, records
   `infrastructure_unavailable` and returns; retries next cycle. No signal is
   created or altered on infra failure.
3. Evaluates every strategy via `src/signal_eval.evaluate_strategies`
   (real `signals.approve_for_trading` gate: score ≥ 40, robustness ≥ 0.3,
   OOS return > 0, profit factor ≥ 1.3, regime match).
4. If **nothing qualifies** → does **not** create a Signal row.
5. If a strategy **qualifies** → creates a fresh Signal (`generated_at = run
   time`, source candle timestamp stored separately), runs preflight + dry-run,
   saves the complete result to `results/watcher_last_result.json`.
6. Notifies only on state change (tradeable⇄false, qualifying-strategy change,
   infra down/up); notifications are de-duplicated via `watcher_state.json`.

## Safety invariants

- `paper_only` must be `true` and `allow_live_orders` must be `false` (aborts otherwise).
- Never calls the order/placement path (`remote-mt5-order`). A unit test injects
  a fake broker whose `place_demo_order` raises, and proves only preflight +
  dry-run are invoked.
- Gates are never lowered, bypassed, or modified.
- Signals are never re-timestamped to look fresh; the source candle timestamp is
  stored separately for deduplication.

## Signal-level deduplication

A fingerprint `pair|strategy|direction|source_candle_ts` is stored in
`watcher_state.json`. Re-running the **same closed candle** does not create
another Signal row; a genuinely new candle may.

## Files

- `engine/tradeability_watcher.py` — the watcher
- `engine/src/signal_eval.py` — shared evaluation (single source of truth)
- `engine/scripts/run_watcher.sh` — cwd-independent launcher (loads `engine/.env`,
  uses project venv Python if present, execs the watcher by absolute path)
- `engine/tests/test_tradeability_watcher.py` — tests
- `engine/results/watcher.log` — rotating log (5 × 1 MB)
- `engine/results/watcher_state.json` — last reported state (dedup)
- `engine/results/watcher_last_result.json` — last cycle result (atomic, 0600)

## Scheduling

cron (no systemd on this host). Aligned to **5 and 35 minutes past the hour**
so the newest candle has settled:

```
# Aether tradeability watcher — every 30 min, offset 5/35
5,35 * * * *  /root/aether-forex-lab/engine/scripts/run_watcher.sh
```

## How to disable

- **Temporarily (no crontab edit):** `touch /root/aether-forex-lab/engine/results/.watcher.disabled`
  The watcher exits early while the flag exists. Remove the file to resume.
- **Permanently:** remove the cron line (`crontab -e`).

## Notifications

- Default: logged to `results/watcher.log` + recorded in `watcher_state.json`.
- Optional, via environment variables (**do not enable until secure credentials
  exist** — never paste a token into chat):
  - `WATCHER_TELEGRAM_TOKEN` + `WATCHER_TELEGRAM_CHAT_ID` → Telegram alerts
  - `WATCHER_WEBHOOK_URL` → POST a JSON event to a webhook
- The notifier is built at runtime from env; if neither is set, only the log
  notifier is used.

## Manual run

```bash
cd /root/aether-forex-lab
./engine/scripts/run_watcher.sh
# or, for a one-off with output to the terminal:
./engine/venv/bin/python engine/tradeability_watcher.py
```
