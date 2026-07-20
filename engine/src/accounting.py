"""Versioned research accounting contracts (no execution capabilities)."""
from __future__ import annotations

import warnings
from typing import Any, Mapping

ACCOUNTING_MODEL_NAME = "normalized_equal_risk_v1"
ACCOUNTING_MODEL_VERSION = 2
LEGACY_MODEL_NAME = "legacy_raw_price_units_v1"
LEGACY_MODEL_VERSION = 1

FIXED_NOTIONAL_POLICY = {
    "capital_allocation_model": "fixed_notional_fixed_exposure",
    "notional_risk_basis": "USD 100000 notional per lifecycle trade; no stop-risk claim",
    "compounding_policy": "none; arithmetic closed-trade PnL on fixed notional",
    "bankruptcy_policy": "equity floor zero; stop accepting entries after bankruptcy",
    "concurrency_policy": "single-symbol ledger; aggregate risk undefined without stops",
}
EQUAL_RISK_POLICY = {
    "capital_allocation_model": "normalized_equal_risk",
    "notional_risk_basis": "1 risk unit per trade using explicit stop distance; USD 100000 reporting basis",
    "compounding_policy": "none; fixed risk/reporting basis",
    "bankruptcy_policy": "equity floor zero; stop accepting entries after bankruptcy",
    "concurrency_policy": "maximum 4 positions; maximum aggregate risk 4 risk units",
}
METRIC_UNIT_SCHEMA = {
    "gross_pnl_account_currency": "USD",
    "net_pnl_account_currency": "USD",
    "expectancy_account_currency_per_trade": "USD/trade",
    "expectancy_return_fraction": "fraction/trade",
    "return_decimal": "fraction",
    "return_percent": "percent",
    "pip_movement": "pips",
    "r_multiple": "R",
    "holding_bars": "bars",
    "holding_hours": "hours",
}


def accounting_metadata(*, has_explicit_stop: bool) -> dict[str, Any]:
    policy = EQUAL_RISK_POLICY if has_explicit_stop else FIXED_NOTIONAL_POLICY
    return {
        "accounting_model": ACCOUNTING_MODEL_NAME,
        "accounting_version": ACCOUNTING_MODEL_VERSION,
        "pnl_unit": "account_currency_USD",
        "return_unit": "decimal_fraction",
        "metric_unit_schema": dict(METRIC_UNIT_SCHEMA),
        **policy,
    }


def legacy_metadata() -> dict[str, Any]:
    return {
        "accounting_model": LEGACY_MODEL_NAME,
        "accounting_version": LEGACY_MODEL_VERSION,
        "pnl_unit": "raw_price_units",
        "return_unit": "mixed_or_artifact_specific",
        "capital_allocation_model": "legacy_undefined",
        "notional_risk_basis": "legacy_undefined",
        "compounding_policy": "legacy_artifact_specific",
        "bankruptcy_policy": "legacy_artifact_specific",
        "concurrency_policy": "legacy_artifact_specific",
        "metric_unit_schema": {},
    }


def require_accounting_metadata(artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    required = ("accounting_model", "accounting_version", "pnl_unit", "return_unit",
                "capital_allocation_model", "notional_risk_basis", "compounding_policy",
                "bankruptcy_policy", "concurrency_policy", "metric_unit_schema")
    missing = [key for key in required if artifact.get(key) is None]
    if missing:
        raise ValueError("result artifact missing accounting metadata: " + ", ".join(missing))
    return artifact


def warn_if_accounting_mismatch(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Warn explicitly when a comparison crosses accounting schemas."""
    a = (left.get("accounting_model"), left.get("accounting_version"))
    b = (right.get("accounting_model"), right.get("accounting_version"))
    mismatch = a != b
    if mismatch:
        warnings.warn(f"accounting version mismatch: {a!r} versus {b!r}", UserWarning,
                      stacklevel=2)
    return mismatch


def read_result_artifact(payload: Mapping[str, Any], *, allow_legacy: bool = False) -> dict[str, Any]:
    """Load validated v2 data, or explicitly tag permitted legacy data."""
    out = dict(payload)
    if "accounting_version" not in out:
        if not allow_legacy:
            raise ValueError("result artifact cannot be loaded without an accounting version")
        warnings.warn("legacy artifact loaded as legacy_raw_price_units_v1", UserWarning,
                      stacklevel=2)
        out = {**legacy_metadata(), **out}
    return dict(require_accounting_metadata(out))
