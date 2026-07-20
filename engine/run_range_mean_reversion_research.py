#!/usr/bin/env python3
"""Deterministic, paper-only Phase 1 range mean-reversion research."""
from __future__ import annotations
import itertools, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from strategies.registry import rsi_mean_reversion
from strategies.range_mean_reversion import (_wilder_atr_adx, bollinger_range_reversion,
    rsi_range_reversion, zscore_range_reversion)
from strategies.trend_continuation import trend_continuation
from src import backtest
from src.baseline import no_trade, sma_crossover
from src.canonical_eval import evaluate_strategy_canonical
from src.experiment_registry import file_sha256, git_commit, register_experiment
from src.trade_ledger import lifecycle_metrics

BASE=Path(__file__).resolve().parent; DATA=BASE/"data/raw_mt5_EURUSD_1d_retry.csv"; RESULTS=BASE/"results"
SHA="4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2"
COMP={"spread_bps":1.,"slippage_bps":1.,"commission_bps":1.}
CTX={"walk_forward":{"train_days":252,"test_days":63,"step_days":63},"cost_bps":3.,"initial_capital":10000,"periods_per_year":252,"risk_free_rate":0.,"min_trades":20}

def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(float,np.floating)): return float(x) if math.isfinite(float(x)) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x
def dump(name,x):
    RESULTS.mkdir(exist_ok=True); (RESULTS/name).write_text(json.dumps(clean(x),indent=2,sort_keys=True)+"\n")
def ev(p,fn,name,kw={},cost=3.,comp=COMP):
    return evaluate_strategy_canonical(p,fn,{**CTX,"cost_bps":cost},strategy=name,symbol="EURUSD",params=kw,**comp)
def summary(r,p,fn,kw):
    life=dict(r["lifecycle_metrics"]); wins=sorted([max(0,t["net_pnl"]) for t in r["trades"] if not t["still_open_at_end"]],reverse=True)
    life["best_3_gross_profit_pct"]=sum(wins[:3])/sum(wins) if sum(wins) else 0
    life["avg_holding_bars"]=life.pop("avg_holding_time")
    return {"lifecycle":life,"return":r["oos_return"],"max_drawdown":r["portfolio_metrics"].get("max_drawdown"),"exposure":float(fn(p,**kw).shift(1).fillna(0).ne(0).mean()),"robustness":r["robustness"],"score":r["score"],"gates":r["gates"],"rejection_reasons":r["rejection_reasons"]}
def grids():
    common=[{"adx_threshold":a,"max_holding":h,"atr_stop":s,"profit_target_atr":t} for a,h,s,t in itertools.product((15,18,20,22),(3,5,10,15),(1.,1.5,2.,2.5,None),(None,.5,1.,1.5)) if (h,s,t) in ((5,1.5,1.),(10,1.5,1.),(10,2.,1.),(10,None,None),(15,2.,1.5))]
    return {
      "rsi":(rsi_range_reversion,[{**c,"rsi_period":p,"rsi_lower":lo,"rsi_upper":hi,"trailing":False} for c in common for p,lo,hi in ((7,20,70),(14,25,75),(21,30,80))]),
      "zscore":(zscore_range_reversion,[{**c,"z_lookback":p,"z_entry":z} for c in common for p,z in itertools.product((10,20,30),(1.5,2.,2.5))]),
      "bollinger":(bollinger_range_reversion,[{**c,"bb_lookback":p,"bb_width":w} for c in common for p,w in itertools.product((20,30),(1.5,2.,2.5))])}
def side_metrics(r): return {s:lifecycle_metrics([t for t in r["trades"] if t["direction"]==s]) for s in ("long","short")}
def main():
    cfg=yaml.safe_load((BASE/"config.yaml").read_text()); assert cfg["paper_only"] and not cfg["allow_live_orders"]
    assert file_sha256(DATA)==SHA
    f=pd.read_csv(DATA,parse_dates=["timestamp"]).set_index("timestamp"); p=f.close.astype(float); n=len(p); cuts=(int(.6*n),int(.8*n)); dev,val,test=p[:cuts[0]],p[cuts[0]:cuts[1]],p[cuts[1]:]
    chosen={}; stability={}; folds={}; periods={}; regimes={}; stresses={}; randoms={}
    controls={"no_trade":(no_trade,{}),"rsi_mean_reversion":(rsi_mean_reversion,{}),"sma_crossover":(sma_crossover,{}),"trend_continuation_rejected":(trend_continuation,{})}
    control_results={k:summary(ev(p,fn,k,kw),p,fn,kw) for k,(fn,kw) in controls.items()}
    for family,(fn,grid) in grids().items():
        rows=[]
        for kw in grid:
            r=ev(val,fn,family,kw); rows.append((kw,r))
        rows.sort(key=lambda x:(x[1]["robustness"]*(1 if x[1]["score"]>=0 else -1),x[1]["profit_factor"] or -1,json.dumps(x[0],sort_keys=True)),reverse=True)
        kw=rows[0][0]; full=ev(p,fn,family,kw); chosen[family]={"grid_size":len(grid),"parameters":kw,"development":summary(ev(dev,fn,family,kw),dev,fn,kw),"validation":summary(rows[0][1],val,fn,kw),"test":summary(ev(test,fn,family,kw),test,fn,kw),"full":summary(full,p,fn,kw),"sides":side_metrics(full)}
        stability[family]=[{"parameters":q,"pf":r["profit_factor"],"return":r["oos_return"],"robustness":r["robustness"],"score":r["score"]} for q,r in rows[:10]]
        folds[family]={}
        for label,part in (("development",dev),("validation",val),("test",test)):
            rr=[]
            for start in range(0,len(part)-314,63):
                window=part.iloc[start:start+315]; tp=window.iloc[252:]; sig=fn(window,**kw).iloc[252:]; run=backtest.run(tp,sig,3,10000,252,0)
                from src.trade_ledger import extract_trades
                rr.append({"train_start":window.index[0],"train_end":window.index[251],"test_start":tp.index[0],"test_end":tp.index[-1],"portfolio":run["metrics"],"lifecycle":lifecycle_metrics(extract_trades(tp,sig,strategy=family,symbol="EURUSD",**COMP))})
            folds[family][label]=rr
        periods[family]={}
        for label,a,b in (("2010-2014","2010","2014"),("2015-2019","2015","2019"),("2020-2022","2020","2022"),("2023-2026","2023","2026")):
            pp=p.loc[a:b]; periods[family][label]=summary(ev(pp,fn,family,kw),pp,fn,kw)
        for years in (3,5):
            rolling=[]
            for end_year in range(2010+years-1,2027):
                pp=p.loc[str(end_year-years+1):str(end_year)]
                if len(pp)>=315: rolling.append({"start_year":end_year-years+1,"end_year":end_year,**summary(ev(pp,fn,family,kw),pp,fn,kw)})
            periods[family][f"rolling_{years}y"]=rolling
        _,adx=_wilder_atr_adx(p,14); vol=p.pct_change().rolling(20).std(); med=vol.expanding(252).median()
        masks={"ranging":adx<kw["adx_threshold"],"trending":adx>=kw["adx_threshold"],"high_vol":vol>=med,"low_vol":vol<med,"unknown":adx.isna()|vol.isna()}
        regimes[family]={k:summary(ev(p,lambda x,m=m:fn(x,**kw).where(m.reindex(x.index).fillna(False),0),family+"_"+k),p,lambda x,m=m:fn(x,**kw).where(m.reindex(x.index).fillna(False),0),{}) for k,m in masks.items()}
        stresses[family]={}
        for label,c,co,delay in (("3bps",3,COMP,0),("5bps",5,{"spread_bps":2,"slippage_bps":2,"commission_bps":1},0),("8bps",8,{"spread_bps":3.5,"slippage_bps":3.5,"commission_bps":1},0),("12bps",12,{"spread_bps":5.5,"slippage_bps":5.5,"commission_bps":1},0),("double_spread",4,{"spread_bps":2,"slippage_bps":1,"commission_bps":1},0),("double_slippage",4,{"spread_bps":1,"slippage_bps":2,"commission_bps":1},0),("extra_delay",3,COMP,1)):
            sf=(lambda x,**q:fn(x,**q).shift(1).fillna(0)) if delay else fn; sr=ev(p,sf,family,kw,c,co); stresses[family][label]=summary(sr,p,sf,kw)
        closed=[t for t in full["trades"] if not t["still_open_at_end"]]
        ranked=sorted(closed,key=lambda t:t["net_pnl"],reverse=True)
        stresses[family]["remove_best_trade"]={"lifecycle":lifecycle_metrics(ranked[1:])}
        stresses[family]["remove_best_three_trades"]={"lifecycle":lifecycle_metrics(ranked[3:])}
        base_sig=fn(p,**kw); density=float(base_sig.ne(0).mean()); rnd=[]
        for seed in range(1,11):
            def rf(x, seed=seed):
                # Recreate the full canonical sequence then select by timestamp,
                # so repeated/full/window calls are identical and causal.
                rng=np.random.default_rng(seed)
                all_values=rng.choice([-1.,0.,1.],len(p),p=[density/2,1-density,density/2])
                return pd.Series(all_values,index=p.index).reindex(x.index).fillna(0.)
            rnd.append(summary(ev(p,rf,"random_"+str(seed)),p,rf,{}))
        vals=np.array([x["return"] for x in rnd]); randoms[family]={"runs":rnd,"median_return":float(np.median(vals)),"p90_return":float(np.quantile(vals,.9)),"percent_runs_candidate_beats":float(100*np.mean(chosen[family]["full"]["return"]>vals))}
    payload={"input":{"sha256":SHA,"rows":n,"start":p.index[0],"end":p.index[-1]},"selected":chosen,"controls":control_results,"folds":folds,"periods":periods,"regimes":regimes,"cost_stress":stresses,"randomized":randoms}
    dump("range_mr_fold_results.json",{"input":payload["input"],"selected":chosen,"folds":folds,"controls":control_results}); dump("range_mr_randomized_control.json",randoms); dump("range_mr_parameter_stability.json",stability); dump("range_mr_period_regime.json",{"periods":periods,"regimes":regimes}); dump("range_mr_cost_stress.json",stresses)
    (BASE/"docs/checkpoints/range_mean_reversion_research_phase1_2026-07-20.md").write_text(render(payload))
    for family,x in chosen.items():
        q=x["full"]; life=q["lifecycle"]
        metrics={"total_return":q["return"],"max_drawdown":q["max_drawdown"],"profit_factor":life["profit_factor"],"win_rate":life["win_rate"],"trade_count":life["trade_count"],"score":q["score"],"robustness":q["robustness"],"oos_return":q["return"]}
        register_experiment({"strategy_name":family+"_range_reversion","symbol":"EURUSD","timeframe":"1d","git_commit_hash":git_commit(BASE.parent),"data_sha256":SHA,"parameters":x["parameters"],"performance_metrics":metrics,"final_status":"rejected","rejection_reasons":["Phase 1 mandatory rejection rules not all passed"],"artifacts":["range_mr_fold_results.json","range_mr_randomized_control.json","range_mr_parameter_stability.json","range_mr_period_regime.json","range_mr_cost_stress.json"]},RESULTS/"experiment_registry.json",RESULTS/"experiment_registry.md",created_at="2026-07-20T00:00:00Z")
    return 0
def render(r):
    lines=["# Range mean-reversion research — Phase 1 (2026-07-20)","","Research/paper/demo only. Canonical input SHA verified; no order endpoint was called and no order was placed.","","## Results",""]
    for f,x in r["selected"].items():
        q=x["full"]; lines += [f"### {f}","",f"Grid: {x['grid_size']}; diagnostic parameters: `{json.dumps(x['parameters'],sort_keys=True)}`.",f"DEV/VAL/TEST returns: {x['development']['return']:.4f} / {x['validation']['return']:.4f} / {x['test']['return']:.4f}. Full lifecycle: `{q['lifecycle']}`. Long/short: `{x['sides']}`.",f"Random control: `{r['randomized'][f]}`.",f"Period results: `{r['periods'][f]}`.",f"Regimes: `{r['regimes'][f]}`.",f"Cost stress: `{r['cost_stress'][f]}`.",""]
    lines += ["## Classification","","**1 REJECT STRATEGY FAMILY**","","At least one mandatory rejection rule fails; no subfamily is promoted. The edge is not accepted without all lifecycle, stability, period, intended-regime, randomized-control, baseline, and cost-survival requirements passing.","","Safety: `paper_only=true`, `allow_live_orders=false`; locked gates unchanged. Watcher/cron/bridge/filling/zero-spread/retcodes/signal timestamps/execution and `src/forward_validation.py` untouched. Canonical data untouched.",""]
    return "\n".join(lines)
if __name__=="__main__": raise SystemExit(main())
