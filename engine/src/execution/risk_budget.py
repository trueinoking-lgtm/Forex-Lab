"""Portfolio-level risk budgets and fail-closed entry circuit breakers."""
from __future__ import annotations

import math
from typing import Any, Optional


DEFAULT_RISK_CFG = {
    "max_drawdown_pct": 6.0,
    "daily_loss_limit_pct": 3.0,
    "max_portfolio_risk_pct": 4.0,
    "per_strategy_risk_pct": 1.0,
}


def load_risk_cfg(config: dict) -> dict:
    """Return the configured risk block with all portfolio defaults filled in."""
    block = config.get("risk", {}) if isinstance(config, dict) else {}
    block = block if isinstance(block, dict) else {}
    return {key: block.get(key, default) for key, default in DEFAULT_RISK_CFG.items()}


class PortfolioRiskState:
    """In-memory portfolio exposure state used to gate new entries."""

    def __init__(self, cfg: dict):
        cfg = cfg if isinstance(cfg, dict) else {}
        initial_equity = cfg.get("initial_equity", 10000.0)
        self.equity_curve = [initial_equity]
        self.peak = initial_equity
        self.daily_start_equity = initial_equity
        self.open_risk = 0.0
        self.open_by_strategy: dict[str, float] = {}
        self.daily_pnl = 0.0

        defaults = load_risk_cfg({"risk": cfg})
        self.max_drawdown_limit_pct = float(defaults["max_drawdown_pct"])
        self.daily_loss_limit_pct = float(defaults["daily_loss_limit_pct"])
        self.max_portfolio_risk_pct = float(defaults["max_portfolio_risk_pct"])
        self.per_strategy_risk_pct = float(defaults["per_strategy_risk_pct"])
        # Fail closed at construction if a threshold is non-finite / negative.
        if any(not math.isfinite(v) or v < 0 for v in (
            self.max_drawdown_limit_pct, self.daily_loss_limit_pct,
            self.max_portfolio_risk_pct, self.per_strategy_risk_pct,
        )):
            raise ValueError("risk thresholds must be finite and non-negative")
        self._corrupt = False

    @staticmethod
    def _valid_equity(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

    def _current_equity(self) -> Optional[float]:
        if not self.equity_curve or not self._valid_equity(self.equity_curve[-1]):
            return None
        return float(self.equity_curve[-1])

    def update_equity(self, equity: float):
        """Record account equity and advance the high-water mark when valid."""
        self.equity_curve.append(equity)
        if self._valid_equity(equity) and (
            not self._valid_equity(self.peak) or equity > self.peak
        ):
            self.peak = equity

    def register_open(self, strategy: str, risk_amt: float):
        if not math.isfinite(risk_amt) or risk_amt < 0:
            self._corrupt = True
            return
        self.open_risk += risk_amt
        self.open_by_strategy[strategy] = self.open_by_strategy.get(strategy, 0.0) + risk_amt

    def register_close(self, pnl: float, strategy: str | None = None, risk_amt: float | None = None):
        if not math.isfinite(pnl):
            self._corrupt = True
            return
        self.daily_pnl += pnl
        # Release the reserved risk for the closed position so capacity recovers.
        if strategy is not None and risk_amt is not None and math.isfinite(risk_amt):
            self.open_risk = max(0.0, self.open_risk - risk_amt)
            released = min(self.open_by_strategy.get(strategy, 0.0), risk_amt)
            self.open_by_strategy[strategy] = max(0.0, self.open_by_strategy.get(strategy, 0.0) - released)

    def max_drawdown_pct(self) -> float:
        """Return drawdown from the equity high-water mark to current equity."""
        equity = self._current_equity()
        if equity is None or not self._valid_equity(self.peak):
            return float("inf")
        return max(0.0, (float(self.peak) - equity) / float(self.peak) * 100.0)

    def current_drawdown_pct(self) -> float:
        return self.max_drawdown_pct()

    def halt_reasons(self) -> list[str]:
        """Describe every active breaker condition; unavailable/corrupt state fails closed."""
        # Fail closed on corrupt state: any non-finite threshold or mutable amount
        # would make IEEE comparisons silently False (NaN >= x is False), so we
        # must refuse rather than let a corrupted state skip the halt.
        if self._corrupt:
            return ["corrupt risk state (non-finite value observed)"]
        thresholds = (self.max_drawdown_limit_pct, self.daily_loss_limit_pct,
                      self.max_portfolio_risk_pct, self.per_strategy_risk_pct)
        if any(not math.isfinite(t) for t in thresholds):
            return ["corrupt risk state (non-finite threshold)"]
        if not math.isfinite(self.open_risk) or not math.isfinite(self.daily_pnl):
            return ["corrupt risk state (non-finite open risk or daily pnl)"]

        equity = self._current_equity()
        if equity is None:
            return ["equity unavailable"]

        reasons = []
        drawdown = self.current_drawdown_pct()
        if drawdown >= self.max_drawdown_limit_pct:
            reasons.append(
                f"drawdown {drawdown:.2f}% >= limit {self.max_drawdown_limit_pct:.2f}%"
            )

        if not self._valid_equity(self.daily_start_equity):
            reasons.append("daily start equity unavailable")
        else:
            daily_limit = float(self.daily_start_equity) * self.daily_loss_limit_pct / 100.0
            if self.daily_pnl <= -daily_limit:
                reasons.append(
                    f"daily loss {-self.daily_pnl:.2f} >= limit {daily_limit:.2f}"
                )

        portfolio_limit = equity * self.max_portfolio_risk_pct / 100.0
        if self.open_risk >= portfolio_limit:
            reasons.append(
                f"open risk {self.open_risk:.2f} >= limit {portfolio_limit:.2f}"
            )
        return reasons

    def halt_new_entries(self) -> bool:
        return bool(self.halt_reasons())

    def per_strategy_ok(self, strategy: str, proposed_risk: float) -> bool:
        equity = self._current_equity()
        if equity is None:
            return False
        cap = equity * self.per_strategy_risk_pct / 100.0
        return self.open_by_strategy.get(strategy, 0.0) + proposed_risk <= cap

    def snapshot(self) -> dict:
        """Return a JSON-serializable view suitable for reports and tests."""
        return {
            "equity_curve": list(self.equity_curve),
            "peak": self.peak,
            "daily_start_equity": self.daily_start_equity,
            "current_equity": self._current_equity(),
            "open_risk": self.open_risk,
            "open_by_strategy": dict(self.open_by_strategy),
            "daily_pnl": self.daily_pnl,
            "current_drawdown_pct": self.current_drawdown_pct(),
            "halt_new_entries": self.halt_new_entries(),
            "halt_reasons": self.halt_reasons(),
            "thresholds": {
                "max_drawdown_pct": self.max_drawdown_limit_pct,
                "daily_loss_limit_pct": self.daily_loss_limit_pct,
                "max_portfolio_risk_pct": self.max_portfolio_risk_pct,
                "per_strategy_risk_pct": self.per_strategy_risk_pct,
            },
        }
