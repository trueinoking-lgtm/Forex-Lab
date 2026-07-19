#!/usr/bin/env python
"""Rebuild Canonical Evaluation V2 research artifacts deterministically."""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path
import pandas as pd, yaml
from src import backtest, data
from src.baseline import no_trade, buy_and_hold, fixed_period_momentum, sma_crossover
from src.canonical_eval import evaluate_strategy_canonical
from src.data_manifest import build_manifest, write_manifest
from strategies.registry import REGISTRY

ROOT = Path(__file__).parent
SYMBOL = "EURUSD=X"

def safe(x):
    if isinstance(x, dict): return {k:safe(v) for k,v in x.items() if k != "trades"}
    if isinstance(x, list): return [safe(v) for v in x]
    if hasattr(x, "item"): return safe(x.item())
    if isinstance(x, float) and not math.isfinite(x): return None
    return x

def write(name, value):
    (ROOT/"results").mkdir(exist_ok=True)
    (ROOT/"results"/name).write_text(json.dumps(safe(value), indent=2, sort_keys=True, allow_nan=False)+"\n")

def context(cost=3):
    return {"walk_forward":{"train_days":252,"test_days":30,"step_days":30},
            "cost_bps":cost,"initial_capital":10000,"periods_per_year":252,
            "risk_free_rate":0,"min_trades":8}

def ev(price, name, fn, params=None, cost=3, spread=2, slip=1, fee=0):
    return evaluate_strategy_canonical(price, fn, context(cost), strategy=name, symbol=SYMBOL,
               params=params or {}, spread_bps=spread, slippage_bps=slip, commission_bps=fee)

def main():
    csv = ROOT/"data"/"yf_EURUSD=X_1d.csv"
    df=data.load_csv(csv); price=df.close.astype(float)
    raw_hash=hashlib.sha256(csv.read_bytes()).hexdigest()
    manifest=build_manifest(df, source="yfinance_auto_adjust_true_cache", symbol=SYMBOL,
                            timeframe="1d", download_ts="2026-07-19T00:00:00+00:00")
    write_manifest(manifest, ROOT/"results"/"data_manifest_EURUSD=X.json")
    fn, params=REGISTRY["ema_crossover"]
    ema=ev(price,"ema_crossover",fn,params)
    # Immutable pre-V2 observation retained for reconciliation after the cache is rebuilt.
    oldema={"trade_count":30,"profit_factor":1.5540590750696137,
            "oos_return":0.06481509154533205,"robustness":0.49,"score":56.66}
    common={"source_file":"engine/data/yf_EURUSD=X_1d.csv","file_sha256":raw_hash,
            "row_count":len(price),"first_candle":price.index[0].isoformat(),
            "last_candle":price.index[-1].isoformat(),"parameters":params,
            "warm_up":"strategy-native EMA min_periods; 252-bar training fold",
            "costs_bps":{"spread":2,"slippage":1,"commission":0},
            "walk_forward":{"training_fold_bars":252,"test_fold_bars":30,"step_bars":30},
            "execution":"signal t, position no earlier than t+1",
            "open_position":"marked still_open_at_end and excluded from closed metrics"}
    before={**common,"completed_lifecycle_trades":"not measured",
            "position_changes_reported_as_trades":oldema["trade_count"],
            "gross_profit":"one-bar change returns only","gross_loss":"one-bar change returns only",
            "profit_factor":oldema["profit_factor"],"net_return":oldema["oos_return"],
            "robustness":oldema["robustness"],"score":oldema["score"],
            "gates":{"score_gte_40":True,"robustness_gte_0_3":True,
                     "oos_return_gt_0":True,"profit_factor_gte_1_3":True},"eligible":True}
    life=ema["lifecycle_metrics"]
    after={**common,"completed_lifecycle_trades":life["trade_count"],
           "position_change_count":ema["position_change_count"],"gross_profit":life["gross_profit"],
           "gross_loss":life["gross_loss"],"profit_factor":life["profit_factor"],
           "net_return":ema["oos_return"],"robustness":ema["robustness"],"score":ema["score"],
           "gates":ema["gates"],"eligible":ema["eligible"]}
    write("reconciliation_EURUSD=X.json", {"schema_version":2,"before_legacy":before,
          "after_canonical":after,"root_causes":[
          "legacy trade_count counted position changes rather than completed lifecycles",
          "legacy profit factor used returns on change bars rather than closed-trade net PnL",
          "watcher gated cached backtest values while baseline did not own eligibility",
          "open positions and reversal legs lacked a shared lifecycle definition"]})

    controls={"no_trade":(no_trade,{}),"buy_and_hold":(buy_and_hold,{}),
              "fixed_period_momentum":(fixed_period_momentum,{"period":20}),
              "sma_crossover":(sma_crossover,{"fast":20,"slow":50})}
    all_defs={**REGISTRY,**controls}
    evaluations={n:safe(ev(price,n,f,p)) for n,(f,p) in sorted(all_defs.items())}
    write("backtest_EURUSD=X.json", {"schema_version":2,
          "generated_from_last_candle":price.index[-1].isoformat(),"pair":SYMBOL,
          "timeframe":"1d","cost_bps":3,
          "results":[{"strategy":n,**{k:v for k,v in result.items() if k not in
                     ("strategy","parameters","window_returns","portfolio_metrics")}}
                     for n,result in sorted(evaluations.items()) if n in REGISTRY]})
    periods={"2010-2014":("2010","2014"),"2015-2019":("2015","2019"),
             "2020-2022":("2020","2022"),"2023-present":("2023",None)}
    breakdown={}
    for label,(start,end) in periods.items():
        sub=price.loc[start:end] if end else price.loc[start:]
        breakdown[label]={"bars":len(sub),"coverage": bool(len(sub)),
            "returns":{n:(backtest.run(sub,f(sub,**p),3)["metrics"]["total_return"] if len(sub)>2 else None)
                       for n,(f,p) in sorted(all_defs.items())}}
    vol=price.pct_change().rolling(20).std(); med=vol.median()
    fast=price.ewm(span=20,adjust=False).mean(); slow=price.ewm(span=50,adjust=False).mean()
    masks={"high_vol":vol>=med,"low_vol":vol<med,
           "trending":(fast/slow-1).abs()>=.005,"ranging":(fast/slow-1).abs()<.005}
    regimes={k:{"bars":int(m.sum()),"ema_return_on_selected_bars":float(
        ((fn(price,**params).shift(1).fillna(0)*price.pct_change().fillna(0))[m]).sum())}
        for k,m in masks.items()}
    extended={"source":"single explicit yfinance auto-adjusted cache; no source mixing",
              "coverage":{"requested_start":"2015-01-01","actual_start":price.index[0].isoformat(),
                          "actual_end":price.index[-1].isoformat(),"bars":len(price),
                          "gap":"local reproducible cache begins 2023-07-20; network extension unavailable/not used"},
              "regime_definition":{"volatility":"20-bar return volatility split at full-sample median",
                 "trend":"absolute EMA(20)/EMA(50)-1 >= 0.5%"},
              "evaluations":evaluations,"periods":breakdown,"regimes":regimes}
    write("extended_baseline_EURUSD=X.json",extended)

    scenarios={}
    for total in (3,5,8,12): scenarios[f"friction_{total}bps"]=safe(ev(price,"ema_crossover",fn,params,total,total,0,0))
    scenarios["commission_1bps"] = safe(ev(price,"ema_crossover",fn,params,4,2,1,1))
    scenarios["extra_delay_1bar"] = safe(ev(price,"ema_crossover",lambda p,**kw:fn(p,**kw).shift(1).fillna(0),params))
    scenarios["spread_doubled"] = safe(ev(price,"ema_crossover",fn,params,5,4,1,0))
    scenarios["slippage_doubled"] = safe(ev(price,"ema_crossover",fn,params,4,2,2,0))
    for f,s in ((10,24),(10,26),(12,24),(12,28),(14,26),(14,28)):
        scenarios[f"neighbor_{f}_{s}"]=safe(ev(price,"ema_crossover",fn,{"fast":f,"slow":s}))
    scenarios["long_only"]=safe(ev(price,"ema_crossover",lambda p,**kw:fn(p,**kw).clip(lower=0),params))
    scenarios["short_only"]=safe(ev(price,"ema_crossover",lambda p,**kw:fn(p,**kw).clip(upper=0),params))
    scenarios["reduced_exposure_50pct"]=safe(ev(price,"ema_crossover",lambda p,**kw:fn(p,**kw)*.5,params))
    sma={f"friction_{total}bps":safe(ev(price,"sma_crossover",sma_crossover,{"fast":20,"slow":50},total,total,0,0)) for total in (3,5,8,12)}
    closed=[t for t in ema["trades"] if not t["still_open_at_end"]]
    pnl=sorted((t["net_pnl"] for t in closed),reverse=True)
    removal={f"remove_{n}_best":{"remaining_net_pnl":sum(pnl[n:]),"removed_net_pnl":sum(pnl[:n])} for n in (1,3)}
    yr=ema["portfolio_metrics"]
    annual=(pd.Series(ema["portfolio_metrics"] and backtest.walk_forward(price,lambda p:fn(p,**params),context())["returns"]).groupby(lambda x:x.year).sum())
    best_year=int(annual.idxmax()) if len(annual) else None
    write("cost_stress_EURUSD=X.json",{"purpose":"fragility analysis only; no optimization",
          "ema":scenarios,"sma_control":sma,"best_trade_removal":removal,
          "exclude_best_calendar_year":{"year":best_year,"aggregate_return_without":float(annual.drop(best_year).sum()) if best_year else None}})

if __name__ == "__main__": main()
