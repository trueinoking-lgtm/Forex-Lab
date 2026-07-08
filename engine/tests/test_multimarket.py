"""Tests for the multi-market hub: market universe, external imports, re-scoring."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import imports, markets as M

HERE = Path(__file__).parent
ENGINE = HERE.parent


# ---------------- market universe ----------------
def test_universe_has_forex_majors_and_gold():
    syms = M.universe_symbols(only_enabled=False)
    for s in ["EURUSD", "GBPUSD", "XAUUSD"]:
        assert s in syms
    assert "BTCUSD" in syms  # present (just disabled)


def test_crypto_disabled_by_default():
    enabled = M.universe_symbols(only_enabled=True)
    assert "BTCUSD" not in enabled
    assert "EURUSD" in enabled


def test_market_metadata_fields():
    g = M.get_market("XAUUSD")
    assert g.asset_class == "metal"
    assert g.session == "commodity"
    assert g.spread_model == "fixed_bps"
    assert g.volatility_profile == "medium"
    assert g.data_source == "GC=F"
    assert g.default_spread_bps > 0


def test_validate_market_rejects_bad_enum():
    with pytest.raises(ValueError):
        M.validate_market({"asset_class": "forex", "session": "bogus_session",
                           "spread_model": "fixed_bps", "volatility_profile": "low"})


def test_universe_filter_by_asset_class():
    metals = M.list_markets(asset_class="metal", only_enabled=True)
    assert all(m["asset_class"] == "metal" for m in metals)
    assert metals[0]["symbol"] == "XAUUSD"


# ---------------- external import validation + labeling ----------------
def _res(src="generic", **kw):
    base = dict(strategy_name="S", symbol="EURUSD", trades=50, net_return=0.2)
    base.update(kw)
    r = imports.from_generic(base) if src == "generic" else (
        imports.from_tradingview(base) if src == "tradingview" else imports.from_traderdev(base))
    r.asset_class = imports._resolve_asset_class(r.symbol)
    imports.validate_import(r)   # exercise validation in the helper
    return r


def test_import_validation_passes_good():
    r = _res()
    imports.validate_import(r)  # no raise


def test_import_rejects_impossible_return():
    r = imports.ImportedResult(source="generic", strategy_name="S", symbol="EURUSD",
                               asset_class="forex", trades=50, net_return=999.0)
    with pytest.raises(ValueError):
        imports.validate_import(r)


def test_import_rejects_bad_trade_count():
    r0 = imports.ImportedResult(source="generic", strategy_name="S", symbol="EURUSD",
                                asset_class="forex", trades=0, net_return=0.2)
    with pytest.raises(ValueError):
        imports.validate_import(r0)
    r2 = imports.ImportedResult(source="generic", strategy_name="S", symbol="EURUSD",
                                asset_class="forex", trades=10_000_000, net_return=0.2)
    with pytest.raises(ValueError):
        imports.validate_import(r2)


def test_import_requires_strategy_and_symbol():
    r = imports.ImportedResult(source="generic", strategy_name="", symbol="EURUSD",
                               asset_class="forex", trades=50, net_return=0.2)
    with pytest.raises(ValueError):
        imports.validate_import(r)


def test_import_labeled_external_true():
    r = _res()
    sc = imports.re_score(r)
    assert sc["is_external"] is True
    assert sc["source"] == "generic"


def test_tradingview_pct_to_fraction():
    r = _res("tradingview", net_profit_pct=38.4, percent_profitable=58, max_drawdown_pct=9.2)
    assert abs(r.net_return - 0.384) < 1e-9
    assert abs(r.win_rate - 0.58) < 1e-9
    assert abs(r.max_drawdown - (-0.092)) < 1e-9


def test_traderdev_shape():
    r = imports.from_traderdev({"strategy": "ETH MACD", "symbol": "ETHUSD",
                                "trade_count": 58, "total_return": 0.42, "cost_bps": 8})
    assert r.symbol == "ETHUSD"
    assert r.trades == 58
    assert abs(r.net_return - 0.42) < 1e-9
    assert r.reported_spread_bps == 8


# ---------------- re-scoring: our cost model wins ----------------
def test_rescore_applies_our_cost_model():
    # external reported 0 cost; we must charge forex default spread+slippage
    r = _res(reported_spread_bps=0, reported_slippage_bps=0, trades=100, net_return=0.30)
    sc = imports.re_score(r)
    assert sc["our_cost_bps"] > 0
    assert sc["cost_gap_bps"] > 0
    assert sc["re_costed_return"] < r.net_return  # external return reduced by our costs


def test_rescore_spread_override():
    r = _res(trades=50, net_return=0.20)
    sc_default = imports.re_score(r)
    sc_override = imports.re_score(r, override_spread_bps=20, override_slippage_bps=10)
    assert sc_override["our_cost_bps"] == 30
    assert sc_override["re_costed_return"] < sc_default["re_costed_return"]


def test_rescore_gold_uses_metal_default():
    r = imports.from_tradingview({"strategy_name": "G", "symbol": "XAUUSD",
                                  "trades": 70, "net_profit_pct": 50})
    r.asset_class = "metal"
    sc = imports.re_score(r)
    assert sc["asset_class"] == "metal"
    # gold default spread 5 + slip 2 = 7 bps baseline
    assert sc["our_cost_bps"] >= 7 - 1e-9


# ---------------- parse_file end-to-end ----------------
def test_parse_json_file(tmp_path):
    f = tmp_path / "imp.json"
    f.write_text(json.dumps([
        {"source": "tradingview", "strategy_name": "A", "symbol": "EURUSD",
         "trades": 60, "net_profit_pct": 20, "percent_profitable": 55},
        {"source": "generic", "strategy_name": "B", "symbol": "GBPUSD",
         "trades": 80, "net_return": 0.15},
    ]))
    out = imports.parse_file(str(f))
    assert len(out) == 2
    assert out[0].source == "tradingview"
    assert out[1].asset_class == "forex"


def test_parse_csv_file(tmp_path):
    f = tmp_path / "imp.csv"
    f.write_text("source,strategy_name,symbol,trades,net_return,win_rate\n"
                 "generic,C,AUDUSD,84,0.17,0.56\n")
    out = imports.parse_file(str(f))
    assert len(out) == 1
    assert out[0].strategy_name == "C"


def test_parse_rejects_fake_in_file(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps([
        {"source": "generic", "strategy_name": "X", "symbol": "EURUSD",
         "trades": 50, "net_return": 9999.0},
    ]))
    with pytest.raises(ValueError):
        imports.parse_file(str(f))


# ---------------- no-live-execution guarantee ----------------
def test_imports_module_has_no_execution_code():
    src = (Path(__file__).parent.parent / "src" / "imports.py").read_text()
    assert not any(t in src for t in ("place_order", "execute_trade", "broker_password", "live_order"))
