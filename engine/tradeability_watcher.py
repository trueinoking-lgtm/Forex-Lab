#!/usr/bin/env python
"""tradeability_watcher.py — safe, scheduled tradeability watcher for EURUSD.

Runs on a cron cadence (default every 30 min; install at 5,35 * * * * so the
newest candle has settled). For each run it:

  1. Acquires a process lock (fcntl.flock) so two runs can NEVER overlap.
  2. Evaluates ALL EURUSD strategies through the normal pipeline + existing
     gates (src/signal_eval.evaluate_strategies -> signals.approve_for_trading).
     Gates are NOT lowered, bypassed, or altered.
  3. If the PC bridge / Tailscale is unreachable, records
     infrastructure_unavailable and returns; retries next cycle. The signal
     and gates are never created or altered on infra failure.
  4. If no strategy is tradeable -> does NOT create a Signal row.
  5. If a strategy is naturally tradeable -> creates a GENUINELY FRESH Signal
     (generated_at = run time, source candle timestamp stored separately for
     deduplication), runs the broker-aware preflight + VPS-to-PC dry-run, and
     saves the complete result. It NEVER calls place-demo-order.
  6. Notifies only on state change (tradeable->false->true, qualifying strategy
     change, or infra down/up). Notifications are de-duplicated via state.

SAFETY INVARIANTS (abort if violated):
  * paper_only must be true
  * allow_live_orders must be false
  * never imports or calls the order/placement path (remote-mt5-order)

Signal-level deduplication: a fingerprint of pair+strategy+direction+source
candle timestamp is stored in watcher_state.json. Re-running the SAME closed
candle will NOT create another Signal row; a genuinely new candle may.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import logging
import logging.handlers
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import yaml  # noqa: E402
from src import data  # noqa: E402
from src.signal_eval import evaluate_strategies, load_scores  # noqa: E402
import run_execution  # noqa: E402

LOG = logging.getLogger("tradeability_watcher")

# Hard disable switch (touch this file to pause without editing crontab).
DISABLE_FLAG = ENGINE_DIR / "results" / ".watcher.disabled"
LOCK_PATH = ENGINE_DIR / "results" / ".watcher.lock"
STATE_PATH = ENGINE_DIR / "results" / "watcher_state.json"
RESULT_PATH = ENGINE_DIR / "results" / "watcher_last_result.json"
LOG_PATH = ENGINE_DIR / "results" / "watcher.log"
SYMBOL = "EURUSD=X"
PAIR = "EURUSD"

# Optional notifier env (do NOT set these unless secure creds exist).
TELEGRAM_TOKEN_ENV = "WATCHER_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ENV = "WATCHER_TELEGRAM_CHAT_ID"
WEBHOOK_ENV = "WATCHER_WEBHOOK_URL"


# --------------------------------------------------------------------------- #
# Atomic, permission-600 JSON write
# --------------------------------------------------------------------------- #
def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # atomic rename
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------- #
# Notifier interface + implementations
# --------------------------------------------------------------------------- #
class Notifier:
    def notify(self, event: str, payload: dict) -> None:
        raise NotImplementedError


class LogNotifier(Notifier):
    """Writes notifications to the rotating log + state file. Always safe."""
    def notify(self, event: str, payload: dict) -> None:
        LOG.info("[notify] %s | %s", event, json.dumps(payload, default=str))


class WebhookNotifier(Notifier):
    def __init__(self, url: str):
        self.url = url

    def notify(self, event: str, payload: dict) -> None:
        try:
            import requests
            requests.post(self.url, json={"event": event, **payload}, timeout=10)
        except Exception as exc:  # pragma: no cover - network best-effort
            LOG.warning("[notify] webhook failed: %s", exc)


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def notify(self, event: str, payload: dict) -> None:
        try:
            import requests
            text = f"[Aether watcher] {event}\n{json.dumps(payload, default=str, indent=2)}"
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text}, timeout=10)
        except Exception as exc:  # pragma: no cover - network best-effort
            LOG.warning("[notify] telegram failed: %s", exc)


def build_notifier() -> Notifier:
    token = os.environ.get(TELEGRAM_TOKEN_ENV)
    chat = os.environ.get(TELEGRAM_CHAT_ENV)
    webhook = os.environ.get(WEBHOOK_ENV)
    if token and chat:
        LOG.info("[notify] Telegram notifier configured (env present)")
        return TelegramNotifier(token, chat)
    if webhook:
        LOG.info("[notify] Webhook notifier configured (env present)")
        return WebhookNotifier(webhook)
    return LogNotifier()


# --------------------------------------------------------------------------- #
# State-change de-duplication
# --------------------------------------------------------------------------- #
def _fingerprint(pair: str, strategy: str, direction: int, candle_ts: str) -> str:
    return f"{pair}|{strategy}|{direction}|{candle_ts}"


def _decide_notify(prev: dict, cur: dict) -> str | None:
    """Return an event string if a NOTIFY-worthy change occurred, else None."""
    prev_tradeable = bool(prev.get("tradeable"))
    cur_tradeable = bool(cur.get("tradeable"))
    if prev_tradeable != cur_tradeable:
        return "tradeability_changed"          # covers false->true and true->false
    if cur_tradeable and prev.get("strategy") != cur.get("strategy"):
        return "qualifying_strategy_changed"
    if prev.get("infra") != cur.get("infra"):
        return "infrastructure_changed"
    return None


# --------------------------------------------------------------------------- #
# Core cycle
# --------------------------------------------------------------------------- #
def run_cycle(notifier: Notifier, dry_adapter=None) -> dict:
    """Execute one watcher cycle. Returns the result dict (and persists state)."""
    cfg = run_execution._cfg()
    if not cfg.get("paper_only") or cfg.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false.")

    state = load_state()
    result: dict = {"run_at": run_execution._now(), "pair": PAIR}

    # --- Infra check: can we reach the PC bridge at all? ------------------- #
    adapter = dry_adapter
    infra_ok = True
    if adapter is None:
        try:
            adapter = run_execution._remote_mt5_adapter()
        except Exception as exc:
            infra_ok = False
            LOG.warning("[infra] adapter unavailable: %s", redact_str(str(exc)))
    if infra_ok:
        try:
            _ = adapter.get_account()  # broker-aware preflight reachability
        except Exception as exc:
            infra_ok = False
            LOG.warning("[infra] bridge unreachable: %s", redact_str(str(exc)))

    if not infra_ok:
        cur = {"tradeable": False, "strategy": None, "infra": "down"}
        event = _decide_notify(state, cur)
        result.update({"infra": "unavailable", "signal_created": False,
                       "dry_run": None})
        if event:
            notifier.notify(event, {"infra": "down"})
        _commit_state(cur, result)
        return result

    # --- Evaluate all strategies via the normal pipeline + real gates ------ #
    d = cfg["data"]
    df = data.load_pair(SYMBOL, d["source"], timeframe=d["timeframe"],
                        lookback_days=d["lookback_days"], cache_dir=d["cache_dir"])
    price = df["close"].astype(float)
    high, low = df["high"].astype(float), df["low"].astype(float)
    scores = load_scores(Path(f"results/backtest_{SYMBOL.replace('/', '')}.json"))
    ev = evaluate_strategies(cfg, scores, price, high, low)
    best = ev["best"]
    tradeable = best is not None
    strategy = best["strategy"] if best else None
    candle_ts = ev["candle_ts"]
    fp = _fingerprint(PAIR, strategy, best["direction"], candle_ts) if best else None

    result.update({
        "infra": "ok",
        "regime": ev["regime"], "adx": ev["adx"], "close": ev["close"],
        "candle_ts": candle_ts,
        "tradeable": tradeable, "strategy": strategy,
        "gate_reasons": best["gate_reasons"] if best else
        [s["reasons"] for s in ev["strategies"] if not s["tradeable"]],
        "evaluations": ev["strategies"],
    })

    if not tradeable:
        # Requirement 5: no Signal row when nothing qualifies.
        cur = {"tradeable": False, "strategy": None, "infra": "ok"}
        event = _decide_notify(state, cur)
        result["signal_created"] = False
        result["dry_run"] = None
        if event:
            notifier.notify(event, {"tradeable": False, "reason": "no strategy qualified"})
        _commit_state(cur, result)
        return result

    # --- Tradeable: dedupe on (pair, strategy, direction, candle_ts) ------- #
    if state.get("last_fingerprint") == fp:
        # Same closed candle already produced a qualifying signal; do not dup.
        LOG.info("[dedupe] same qualifying candle %s already signalled; skipping", fp)
        cur = {"tradeable": True, "strategy": strategy, "infra": "ok",
               "last_fingerprint": fp}
        event = _decide_notify(state, cur)
        result["signal_created"] = False
        result["dry_run"] = None
        result["deduped"] = True
        if event:
            notifier.notify(event, {"tradeable": True, "strategy": strategy,
                                    "note": "duplicate candle suppressed"})
        _commit_state(cur, result)
        return result

    # --- Genuinely fresh qualifying signal -------------------------------- #
    db = run_execution._db()
    generated_at = run_execution._now()
    signal_id = run_execution._insert_fresh_signal(
        db, pair=PAIR, strategy=strategy, direction=best["direction"],
        entry=best["entry"], stop_loss=best["stop_loss"], take_profit=best["take_profit"],
        status="paper", signal_score=best["signal_score"], regime=best["regime"],
        generated_at=generated_at, units=best["units"], original_signal_id=None,
    )
    db.commit()
    result["signal_created"] = True
    result["signal_id"] = signal_id
    result["generated_at"] = generated_at
    result["source_candle_ts"] = candle_ts

    # Broker-aware preflight (no order).
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_execution.cmd_check(__ns_adapter("remote_mt5"))
        result["preflight"] = _safe_json(buf.getvalue())
    except Exception as exc:
        result["preflight"] = {"error": redact_str(str(exc))}

    # VPS-to-PC dry-run (no order). cmd_remote_mt5_dry_run prints JSON.
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_execution.cmd_remote_mt5_dry_run(__ns_signal(signal_id))
        dry = _safe_json(buf.getvalue())
        result["dry_run"] = dry
    except Exception as exc:
        result["dry_run"] = {"error": redact_str(str(exc))}

    cur = {"tradeable": True, "strategy": strategy, "infra": "ok",
           "last_fingerprint": fp}
    event = _decide_notify(state, cur)
    if event:
        notifier.notify(event, {"tradeable": True, "strategy": strategy,
                                "signal_id": signal_id})
    _commit_state(cur, result)
    return result


def _commit_state(cur: dict, result: dict) -> None:
    try:
        atomic_write_json(STATE_PATH, cur)
    except Exception as exc:  # pragma: no cover
        LOG.warning("[state] write failed: %s", exc)
    try:
        atomic_write_json(RESULT_PATH, result)
    except Exception as exc:  # pragma: no cover
        LOG.warning("[result] write failed: %s", exc)


# --- small helpers (avoid heavy imports at module top) -------------------- #
def redact_str(s: str) -> str:
    from src.execution.adapter import redact
    return redact(s)


def _safe_json(text: str):
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:2000]}


def __ns_adapter(name: str):
    import argparse
    ns = argparse.Namespace(adapter=name)
    return ns


def __ns_signal(signal_id: int):
    import argparse
    return argparse.Namespace(signal_id=signal_id)


# --------------------------------------------------------------------------- #
# Logging setup (rotating, primary log; top-level exceptions land here)
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(fh)
    LOG.addHandler(logging.StreamHandler(sys.stderr))  # also to stderr for cron mail


# --------------------------------------------------------------------------- #
# Entrypoint with process lock
# --------------------------------------------------------------------------- #
def main() -> int:
    setup_logging()
    if DISABLE_FLAG.exists():
        LOG.info("[watcher] disabled flag present (%s); exiting", DISABLE_FLAG)
        return 0
    # Process lock: never allow two overlapping runs.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lockf = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        LOG.info("[watcher] another instance holds the lock; skipping this cycle")
        return 0
    try:
        notifier = build_notifier()
        result = run_cycle(notifier)
        LOG.info("[watcher] cycle complete: tradeable=%s signal_created=%s infra=%s",
                 result.get("tradeable"), result.get("signal_created"),
                 result.get("infra"))
        return 0
    except SystemExit:
        raise
    except Exception:
        LOG.exception("[watcher] top-level failure")
        return 1
    finally:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        lockf.close()


if __name__ == "__main__":
    raise SystemExit(main())
