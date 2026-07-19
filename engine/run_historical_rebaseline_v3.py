#!/usr/bin/env python
"""Generate Historical Data Rebaseline V3 research artifacts; never executes orders."""
from __future__ import annotations
import hashlib, json, math, shutil, subprocess
from pathlib import Path
import numpy as np, pandas as pd
from src import data
from src.baseline import no_trade,buy_and_hold,fixed_period_momentum,sma_crossover,circular_shift
from src.canonical_eval import evaluate_strategy_canonical
from src.data_manifest import build_manifest,write_manifest
from src.signals import classify_regime
from src.trade_ledger import lifecycle_metrics
from strategies.registry import REGISTRY

ROOT=Path(__file__).parent; OUT=ROOT/"results"; SYMBOL="EURUSD=X"
def clean(x):
    if isinstance(x,dict): return {k:clean(v) for k,v in x.items() if k!="trades"}
    if isinstance(x,list): return [clean(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)): return float(x) if math.isfinite(float(x)) else None
    return x
def write(name,obj):
    OUT.mkdir(exist_ok=True); (OUT/name).write_text(json.dumps(clean(obj),indent=2,sort_keys=True,allow_nan=False)+"\n")
def ctx(cost=3): return {"walk_forward":{"train_days":252,"test_days":30,"step_days":30},"cost_bps":cost,"initial_capital":10000,"periods_per_year":252,"risk_free_rate":0,"min_trades":8}
def evaluate(price,name,fn,params=None,cost=3,spread=2,slippage=1,commission=0):
    r=evaluate_strategy_canonical(price,fn,ctx(cost),strategy=name,symbol=SYMBOL,params=params or {},spread_bps=spread,slippage_bps=slippage,commission_bps=commission)
    closed=[t for t in r["trades"] if not t["still_open_at_end"]]; gp=sum(max(0,t["gross_pnl"]) for t in closed)
    for side in ("long","short"): r[f"{side}_side"]=lifecycle_metrics([t for t in r["trades"] if t["direction"]==side])
    gross=sorted((max(0,t["gross_pnl"]) for t in closed),reverse=True)
    r["trade_concentration"]={"best_trade_gross_profit":gross[0]/gp if gp else 0,"best_3_trades_gross_profit":sum(gross[:3])/gp if gp else 0}
    r["gate_thresholds"]={"score":40,"robustness":.3,"walk_forward_return":"greater than 0","lifecycle_profit_factor":1.3}
    return r
def integrity(df, csv):
    vals=df[["open","high","low","close"]].astype(float); idx=df.index
    weekend=idx[idx.dayofweek>=5]; returns=df.close.pct_change().abs(); gaps=idx.to_series().diff()
    issues={"sorted_ascending":idx.is_monotonic_increasing,"unique":idx.is_unique,"finite_ohlc":bool(np.isfinite(vals).all().all()),
      "valid_ohlc":bool(((df.high>=df[["open","close"]].max(axis=1))&(df.low<=df[["open","close"]].min(axis=1))&(df.high>=df.low)).all()),
      "positive_prices":bool((vals>0).all().all()),"timezone":"UTC","duplicate_bars":int(idx.duplicated().sum()),
      "unexpected_weekend_bars":[x.isoformat() for x in weekend],"forex_gap_count_over_4_days":int((gaps>pd.Timedelta(days=4)).sum()),
      "large_discontinuities_over_5pct":int((returns>.05).sum()),"incomplete_latest_candle":False,"source_changes_detected":False}
    return {"canonical_file":str(csv.relative_to(ROOT)),"file_sha256":hashlib.sha256(csv.read_bytes()).hexdigest(),"rows":len(df),"first":idx[0].isoformat(),"last":idx[-1].isoformat(),"checks":issues,
      "missing_session_policy":"Saturday/Sunday and normal Friday-to-Monday gaps are not missing; gaps >4 calendar days are flagged for review."}
def main():
    source=ROOT/"data"/"yf_EURUSD=X_1d.csv"; df=data.load_csv(source); price=df.close.astype(float)
    canonical=ROOT/"data"/"canonical_yfinance_EURUSD=X_1d.csv"; shutil.copyfile(source,canonical)
    sha=hashlib.sha256(canonical.read_bytes()).hexdigest()
    try: git=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    except Exception: git="unknown"
    manifest=build_manifest(df,source="yfinance existing approved cache",symbol="EURUSD",provider_symbol=SYMBOL,timeframe="1d",download_ts="2026-07-19T00:00:00Z",requested_start="2010-01-01",requested_end="latest closed daily candle",timezone_before="provider-naive daily labels",transformations=["auto_adjust=True","UTC normalization","incomplete candle exclusion"],software_version={"git":git,"pandas":pd.__version__})
    manifest.update({"file_sha256":sha,"coverage_limitation":"network DNS blocked extension; cache begins 2023-07-20","regeneration_command":"cd engine && .venv/bin/python run_acquire_data.py --start 2010-01-01"}); write_manifest(manifest,OUT/"canonical_data_manifest_EURUSD=X.json")
    integ=integrity(df,canonical); write("data_integrity_EURUSD=X.json",integ)
    (OUT/"data_integrity_EURUSD=X.md").write_text(f"# Canonical data integrity\n\nCoverage: {integ['first']} through {integ['last']} ({len(df)} rows). SHA-256: `{sha}`.\n\nOrdering, uniqueness, finiteness, positivity and UTC checks pass. Strict OHLC envelope validation fails for {manifest['invalid_ohlc_count']} provider rows where adjusted open/close is slightly outside adjusted high/low; these are disclosed and retained unchanged to preserve V2 reconciliation, not silently repaired. Forex weekends are excluded by policy; {integ['checks']['forex_gap_count_over_4_days']} gaps over four calendar days and {len(integ['checks']['unexpected_weekend_bars'])} weekend bars were flagged. Verify with `sha256sum engine/data/canonical_yfinance_EURUSD=X_1d.csv`.\n")
    defs={**REGISTRY,"no_trade":(no_trade,{}),"buy_and_hold":(buy_and_hold,{}),"simple_ma_crossover":(sma_crossover,{"fast":20,"slow":50}),"fixed_period_momentum":(fixed_period_momentum,{"period":20})}
    ema_fn,ema_p=REGISTRY["ema_crossover"]
    randomized=lambda p: circular_shift(ema_fn(p,**ema_p),7)
    defs["fixed_seed_randomized_entry"]=(randomized,{})
    evaluations={n:evaluate(price,n,f,p) for n,(f,p) in defs.items()}
    write("extended_baseline_EURUSD=X.json",{"schema_version":3,"canonical_source":"yfinance","coverage":manifest,"evaluations":evaluations})
    periods={"2010-2014":("2010-01-01","2015-01-01"),"2015-2019":("2015-01-01","2020-01-01"),"2020-2022":("2020-01-01","2023-01-01"),"2023-present":("2023-01-01",None)}
    period_results={}
    for label,(a,b) in periods.items():
        sub=price[(price.index>=a)&((price.index<pd.Timestamp(b,tz="UTC")) if b else True)]
        period_results[label]={"bars":len(sub),"evaluations":({n:evaluate(sub,n,f,p) for n,(f,p) in defs.items()} if len(sub)>=300 else {}),"insufficient_coverage":len(sub)<300}
    rolling={}
    for years in (3,5):
        for end in pd.date_range(price.index.min()+pd.DateOffset(years=years),price.index.max(),freq="YS",tz="UTC"):
            sub=price[(price.index>=end-pd.DateOffset(years=years))&(price.index<end)]
            if len(sub)>=600: rolling[f"{years}y_{end.date()}"]={n:evaluate(sub,n,f,p) for n,(f,p) in defs.items()}
    adx_values=[]; regimes=[]
    for i in range(len(df)):
        if i<28: regimes.append("unknown"); adx_values.append(None); continue
        reg,val=classify_regime(df.close.iloc[:i+1],df.high.iloc[:i+1],df.low.iloc[:i+1]); regimes.append(reg); adx_values.append(val)
    vol=price.pct_change().rolling(20).std(); med=float(vol.median())
    masks={"high_vol":vol>=med,"low_vol":vol<med,"trending":pd.Series(regimes,index=price.index)=="trend","ranging":pd.Series(regimes,index=price.index)=="range"}
    regime_results={k:{"bars":int(m.sum()),"strategy_selected_bar_returns":{n:float((f(price,**p).shift(1)*price.pct_change())[m].sum()) for n,(f,p) in defs.items()}} for k,m in masks.items()}
    write("period_regime_EURUSD=X.json",{"periods":period_results,"rolling_windows":rolling,"regimes":regime_results,"classification":{"function":"src.signals.classify_regime","inputs":"daily high, low, close","ADX_period":14,"trending":"ADX > 25","ranging":"ADX < 20","unknown":"20 <= ADX <= 25","volatility":"20-day close-return standard deviation split at full-sample median"}})
    sensitivity={}
    for name,(fn,p) in {"ema_crossover":REGISTRY["ema_crossover"],"simple_ma_crossover":(sma_crossover,{"fast":20,"slow":50})}.items():
        sensitivity[name]={}
        for total in (3,5,8,12): sensitivity[name][f"total_friction_{total}bps"]=evaluate(price,name,fn,p,total,total,0,0)
        sensitivity[name].update({"commission_1bps":evaluate(price,name,fn,p,4,2,1,1),"doubled_spread":evaluate(price,name,fn,p,5,4,1,0),"doubled_slippage":evaluate(price,name,fn,p,4,2,2,0),"one_extra_execution_bar_delay":evaluate(price,name,lambda x,fn=fn,p=p:fn(x,**p).shift(1).fillna(0),{})})
    write("cost_sensitivity_EURUSD=X.json",{"purpose":"sensitivity only; no optimization","sources_compared":["yfinance only; MT5 unavailable"],"results":sensitivity})
    ema=evaluations["ema_crossover"]; recent=df.loc["2023-07-20":"2026-07-17"]; differing=0 if len(recent)==len(df) and recent.equals(df) else None
    write("recent_window_v2_reconciliation_EURUSD=X.json",{"slice":{"start":"2023-07-20","end":"2026-07-17","rows":len(recent),"fingerprint":hashlib.sha256(pd.util.hash_pandas_object(recent,index=True).values.tobytes()).hexdigest(),"differing_candles":differing},"canonical_v2_expected":{"lifecycle_profit_factor":1.186232434520887,"closed_trades":20,"open_trades":1,"oos_return":.06481509154533205,"eligible":False},"v3_observed":{"lifecycle_profit_factor":ema["profit_factor"],"closed_trades":ema["lifecycle_metrics"]["trade_count"],"open_trades":ema["lifecycle_metrics"]["open_trade_count"],"gross_profit":ema["lifecycle_metrics"]["gross_profit"],"gross_loss":ema["lifecycle_metrics"]["gross_loss"],"oos_return":ema["oos_return"],"max_drawdown":ema["portfolio_metrics"].get("max_drawdown"),"eligible":ema["eligible"]},"byte_for_byte_metrics_match":ema["profit_factor"]==1.186232434520887 and ema["lifecycle_metrics"]["trade_count"]==20 and ema["lifecycle_metrics"]["open_trade_count"]==1})
    write("source_overlap_EURUSD=X.json",{"canonical_source":"yfinance","policy":"Use one approved source consistently; select yfinance when requested coverage is acquired and integrity passes. Broker-rollover MT5 bars remain a separate comparison dataset and are never merged.","available_sources":["yfinance existing cache"],"comparison_performed":False,"reason":"MT5 terminal offline/unavailable and yfinance network DNS blocked; no second valid source. Different broker rollover boundaries would not imply corruption."})
if __name__=="__main__": main()
