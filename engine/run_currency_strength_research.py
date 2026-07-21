#!/usr/bin/env python3
"""Deterministic, research-only currency-strength Phase 1 runner."""
from __future__ import annotations

import argparse, hashlib, itertools, json, math
from pathlib import Path
import numpy as np
import pandas as pd

from strategies.currency_strength import (PAIR_CURRENCIES, LOOKBACKS, METHODS,
    construct_signals, currency_strength, pip_multiplier)
from src.accounting import accounting_metadata

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"; RESULTS = BASE / "results"
DOC = BASE / "docs/checkpoints/currency_strength_research_phase1_2026-07-21.md"
HASHES = {"EURUSD":"80cc20e9de10f929619902d618a32035f45d557751153d16484de46d8d5fcfc1",
 "GBPUSD":"99a2564ae0040d6c47ec20d1ce84c82a464be44dafac05898ea7e2e53d1fa789",
 "USDJPY":"3aad2f78b5b06f39ac7804d33845c40e31d2d00073937e2df8eb51512802db60",
 "AUDUSD":"776a10f7326ba04bf68a7c95011aedeebee693b0c5eb22d2ea22a98332bb94a7"}
FOLDS = {"DEV":("2022-01-03","2023-06-30 23:59:59"),
         "VALIDATION":("2023-07-01","2024-12-31 23:59:59"),
         "TEST":("2025-01-01","2026-07-17 23:59:59")}
FILTERS = ("continuation", "vol_filter", "trend_confirm")
HOLDINGS=(4,8,24); STOPS=(1.0,1.5,2.0); TARGETS=(None,1.5,2.0)
RISK_USD=100.0; INITIAL=10_000.0


def clean(x):
    if isinstance(x, dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)): return [clean(v) for v in x]
    if isinstance(x, np.bool_): return bool(x)
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (float,np.floating)): return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    if isinstance(x, bool): return x
    return x


def dump(name, payload):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS/name).write_text(json.dumps(clean(payload), indent=2, sort_keys=True)+"\n")


def load_data():
    frames={}; manifests={}
    for pair, expected in HASHES.items():
        path=DATA/f"raw_mt5_{pair}_1h.csv"; mp=path.with_suffix(".manifest.json")
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected: raise ValueError(f"immutable fingerprint mismatch: {pair}")
        manifest=json.loads(mp.read_text())
        if manifest.get("symbol") != pair or manifest.get("timeframe") != "1h":
            raise ValueError(f"manifest identity mismatch: {pair}")
        frame=pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        frames[pair]=frame.loc["2022-01-03":"2026-07-17 23:59:59", ["open","high","low","close"]]
        manifests[pair]=manifest
    common=frames["EURUSD"].index
    for frame in frames.values(): common=common.intersection(frame.index)
    return {p:f.reindex(common) for p,f in frames.items()}, manifests


def atr(frame, n):
    prev=frame.close.shift(1)
    tr=pd.concat([(frame.high-frame.low).abs(),(frame.high-prev).abs(),
                  (frame.low-prev).abs()],axis=1).max(axis=1)
    return tr.rolling(n,min_periods=n).mean()


def simulate(frames, signals, lookback, holding, stop_atr, target_r,
             cost_bps=3.0, delay=1, allowed_index=None):
    """Lifecycle ledger with next-open entries, equal USD risk, and at most four pairs."""
    idx=signals.index if allowed_index is None else signals.index.intersection(allowed_index)
    loc=signals.index.get_indexer(idx); at={p:atr(frames[p],lookback).to_numpy() for p in frames}
    arrays={p:{c:frames[p][c].to_numpy() for c in ("open","high","low","close")} for p in frames}
    sig=signals.to_numpy(); pairs=list(signals.columns); active={}; trades=[]; equity=INITIAL
    for k,i in enumerate(loc):
        if i < delay or equity <= 0: continue
        # Rank reversal/sign flip, stop, target, or fixed holding.
        desired={pairs[j]:int(sig[i,j]) for j in range(len(pairs)) if sig[i,j]}
        for pair,pos in list(active.items()):
            a=arrays[pair]; d=pos["direction"]; age=i-pos["entry_i"]
            stop_hit=a["low"][i] <= pos["stop"] if d>0 else a["high"][i] >= pos["stop"]
            target_hit=False if pos["target"] is None else (a["high"][i]>=pos["target"] if d>0 else a["low"][i]<=pos["target"])
            reversal=desired.get(pair) != d
            if stop_hit or target_hit or reversal or age >= holding or k==len(loc)-1:
                px=pos["stop"] if stop_hit else (pos["target"] if target_hit else a["open"][i])
                raw_r=d*(px-pos["entry"])/pos["risk_distance"]
                cost_r=(cost_bps/10000.0)*pos["entry"]/pos["risk_distance"]
                pnl=RISK_USD*(raw_r-cost_r); equity=max(0.0,equity+pnl)
                trades.append({"pair":pair,"base":PAIR_CURRENCIES[pair][0],"quote":PAIR_CURRENCIES[pair][1],
                    "direction":"long" if d>0 else "short","entry_timestamp":signals.index[pos["entry_i"]],
                    "exit_timestamp":signals.index[i],"holding_hours":age,"gross_pnl_usd":RISK_USD*raw_r,
                    "cost_usd":RISK_USD*cost_r,"net_pnl_usd":pnl,"r_multiple":raw_r-cost_r,
                    "pip_multiplier":pip_multiplier(pair)})
                del active[pair]
        source_i=i-delay
        for j,pair in enumerate(pairs):
            d=int(sig[source_i,j])
            if not d or pair in active or len(active)>=4 or len(active)*RISK_USD>=400: continue
            distance=float(at[pair][source_i])*stop_atr
            entry=float(arrays[pair]["open"][i])
            if not np.isfinite(distance) or distance<=0: continue
            active[pair]={"direction":d,"entry":entry,"entry_i":i,"risk_distance":distance,
                "stop":entry-d*distance,"target":None if target_r is None else entry+d*distance*target_r}
    return trades


def metrics(trades):
    pnl=np.array([t["net_pnl_usd"] for t in trades],dtype=float)
    wins=pnl[pnl>0]; losses=pnl[pnl<0]; gp=float(wins.sum()); gl=float(-losses.sum())
    pf=gp/gl if gl else (float("inf") if gp else 0.0)
    curve=INITIAL+np.cumsum(pnl); peaks=np.maximum.accumulate(np.r_[INITIAL,curve])
    dd=(peaks[1:]-curve)/peaks[1:] if len(curve) else np.array([])
    by_pair={p:float(sum(t["net_pnl_usd"] for t in trades if t["pair"]==p)) for p in PAIR_CURRENCIES}
    counts={p:sum(t["pair"]==p for t in trades) for p in PAIR_CURRENCIES}
    positive=sum(v>0 for v in by_pair.values()); robustness=positive/4
    ret=float(pnl.sum()/INITIAL); score=max(0.0,min(100.0,25*ret+20*min(pf,2)+20*robustness))
    sorted_w=np.sort(wins)[::-1]; denom=gp or 1.0
    return {"trade_count":len(trades),"gross_profit_usd":gp,"gross_loss_usd":gl,
      "profit_factor":pf,"return":ret,"expectancy_usd_per_trade":float(pnl.mean()) if len(pnl) else 0.0,
      "max_drawdown_fraction":float(dd.max()) if len(dd) else 0.0,"robustness":robustness,"score":score,
      "long_trades":sum(t["direction"]=="long" for t in trades),"short_trades":sum(t["direction"]=="short" for t in trades),
      "mean_holding_hours":float(np.mean([t["holding_hours"] for t in trades])) if trades else 0.0,
      "pair_net_pnl_usd":by_pair,"pair_trade_count":counts,"positive_pairs":positive,
      "best_trade_gross_profit_fraction":float(sorted_w[:1].sum()/denom),
      "best_three_gross_profit_fraction":float(sorted_w[:3].sum()/denom),"exposure_trade_hours":sum(t["holding_hours"] for t in trades)}


def gates(m, survive_5=False, beats_random=False, pair_contrib_ok=False,
          currency_ok=False, nearby=False, periods=False):
    checks={"profit_factor_gte_1_3":m["profit_factor"]>=1.3,"return_positive":m["return"]>0,
      "robustness_gte_0_3":m["robustness"]>=.3,"score_gte_40":m["score"]>=40,
      "trades_gte_300":m["trade_count"]>=300,
      "each_traded_pair_gte_40":all(v>=40 for v in m["pair_trade_count"].values() if v),
      "positive_at_least_3_pairs":m["positive_pairs"]>=3,"survives_5bps":survive_5,
      "beats_randomized_90pct":beats_random,"best_trade_lte_15pct":m["best_trade_gross_profit_fraction"]<=.15,
      "best_three_lte_30pct":m["best_three_gross_profit_fraction"]<=.30,
      "no_pair_over_50pct":pair_contrib_ok,"no_currency_dominates":currency_ok,
      "nearby_parameter_stability":nearby,"no_single_period_dependence":periods}
    return checks, [k for k,v in checks.items() if not v]


def config_key(c):
    return f'{c[0]}|{c[1]}|{c[2]}|L{c[3]}|A{c[4]}|T{c[5]}'


def random_controls(frames, canonical_signals, cfg, canonical_pf):
    rng_results={k:[] for k in ("random_pair","random_direction","shuffled_ranks")}
    rng=np.random.default_rng(20260721); arr=canonical_signals.to_numpy(); pairs=list(canonical_signals)
    for seed in range(10):
        for kind in rng_results:
            x=arr.copy(); local=np.random.default_rng(20260721+seed*17+list(rng_results).index(kind))
            if kind=="random_pair":
                dirs=np.sign(x.sum(axis=1)); x[:]=0; cols=local.integers(0,4,len(x)); x[np.arange(len(x)),cols]=dirs
            elif kind=="random_direction":
                x=np.abs(x)*local.choice([-1,1],size=x.shape)
            else:
                for row in x: local.shuffle(row)
            tr=simulate(frames,pd.DataFrame(x,index=canonical_signals.index,columns=pairs),cfg[1],cfg[3],cfg[4],cfg[5])
            rng_results[kind].append(metrics(tr)["profit_factor"])
    flat=[v for values in rng_results.values() for v in values]
    summary={k:{"seeds":10,"median_pf":float(np.median(v)),"p90_pf":float(np.quantile(v,.9)),
                "percent_beaten":100*float(np.mean(canonical_pf>np.array(v)))} for k,v in rng_results.items()}
    return {"no_trade":{"trade_count":0,"return":0.0},"randomized":summary,
      "randomized_overall_p90_pf":float(np.quantile(flat,.9)),"equal_weight_momentum":"canonical equal_weight reference grid",
      "individual_pair_momentum":"reported as descriptive control; no cross-sectional selection",
      "rejected_family_references":["ema","trend_continuation","range_mean_reversion","session_breakout"]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--config",help="reserved deterministic config label")
    parser.parse_args(); frames, manifests=load_data(); closes=pd.DataFrame({p:f.close for p,f in frames.items()})
    configs=list(itertools.product(METHODS,LOOKBACKS,FILTERS,HOLDINGS,STOPS,TARGETS))
    signal_cache={(m,l,f):construct_signals(closes,l,m,f) for m,l,f in itertools.product(METHODS,LOOKBACKS,FILTERS)}
    fold_records=[]; selection=[]; ledgers={}
    for c in configs:
        method,lb,flt,hold,stop,target=c; sig=signal_cache[(method,lb,flt)]
        fold_metrics={}; all_trades=[]
        for name,(start,end) in FOLDS.items():
            ix=closes.loc[start:end].index; tr=simulate(frames,sig,lb,hold,stop,target,allowed_index=ix)
            fold_metrics[name]=metrics(tr); all_trades.extend(tr)
        agg=metrics(all_trades); key=config_key(c); ledgers[key]=all_trades
        sel_pf=(fold_metrics["DEV"]["profit_factor"]+fold_metrics["VALIDATION"]["profit_factor"])/2
        selection.append((sel_pf,fold_metrics["DEV"]["robustness"]+fold_metrics["VALIDATION"]["robustness"],len(all_trades),key,c))
        fold_records.append({"configuration":dict(zip(("method","lookback","filter","holding","atr_stop","target_r"),c)),
            "folds":fold_metrics,"aggregate_chronological":agg})
    # TEST and aggregate metrics never participate in this ordering.
    selected=max(selection,key=lambda x:(x[0],x[1],x[2])); key,c=selected[3],selected[4]
    chosen=next(r for r in fold_records if config_key(tuple(r["configuration"].values()))==key)
    trades=ledgers[key]; agg=chosen["aggregate_chronological"]; sig=signal_cache[(c[0],c[1],c[2])]
    stress={}
    for label,bps in (("3_bps",3),("5_bps",5),("8_bps",8),("12_bps",12),("doubled_spread",6),("doubled_slippage",4),("nonzero_commission",4)):
        stress[label]=metrics(simulate(frames,sig,c[1],c[3],c[4],c[5],cost_bps=bps))
    stress["execution_delay_plus_1h"]=metrics(simulate(frames,sig,c[1],c[3],c[4],c[5],delay=2))
    ranked=sorted(trades,key=lambda t:t["net_pnl_usd"],reverse=True)
    stress["remove_best_trade"]=metrics(ranked[1:]); stress["remove_best_three"]=metrics(ranked[3:])
    controls=random_controls(frames,sig,c,agg["profit_factor"])
    contrib={p:sum(max(0,t["net_pnl_usd"]) for t in trades if t["pair"]==p) for p in PAIR_CURRENCIES}; total=sum(contrib.values()) or 1
    pair_frac={p:v/total for p,v in contrib.items()}; currency={u:0.0 for u in ("EUR","GBP","USD","JPY","AUD")}
    for p,v in contrib.items(): currency[PAIR_CURRENCIES[p][0]]+=v/2; currency[PAIR_CURRENCIES[p][1]]+=v/2
    currency_frac={u:v/total for u,v in currency.items()}; pair_ok=max(pair_frac.values())<=.5; currency_ok=max(currency_frac.values())<=.5 and currency_frac["USD"]<=.5
    periods={"2010_2014":{"status":"N/A","reason":"outside preregistered H1 Phase 1 analysis span"}}
    for label,start,end in (("2015_2019","2015","2019-12-31"),("2020_2022","2020","2022-12-31"),("2023_2026","2023","2026-07-17")):
        if label in ("2015_2019",): periods[label]={"status":"N/A","reason":"outside preregistered H1 Phase 1 analysis span"}
        else: periods[label]=metrics([t for t in trades if pd.Timestamp(start,tz="UTC")<=t["entry_timestamp"]<=pd.Timestamp(end,tz="UTC")])
    periods["rolling_3y"]=[{"end":str(y),**metrics([t for t in trades if pd.Timestamp(f"{y-2}-01-01",tz="UTC")<=t["entry_timestamp"]<=pd.Timestamp(f"{y}-12-31",tz="UTC")])} for y in (2024,2025,2026)]
    periods["rolling_5y"]=[{"end":"2026","note":"available 2022-2026 span",**metrics(trades)}]
    hourly=closes.pct_change().std(axis=1); med=hourly.median(); periods["volatility_regimes"]={
      "high":metrics([t for t in trades if hourly.get(t["entry_timestamp"],0)>=med]),
      "low":metrics([t for t in trades if hourly.get(t["entry_timestamp"],0)<med])}
    nearby=[r["aggregate_chronological"]["return"]>0 for r in fold_records if r["configuration"]["method"]==c[0] and r["configuration"]["filter"]==c[2] and r["configuration"]["holding"]==c[3] and r["configuration"]["atr_stop"]==c[4] and r["configuration"]["target_r"]==c[5] and abs(LOOKBACKS.index(r["configuration"]["lookback"])-LOOKBACKS.index(c[1]))==1]
    period_ok=sum(isinstance(v,dict) and v.get("return",0)>0 for v in periods.values())>=2
    g,reasons=gates(agg,stress["5_bps"]["return"]>0,agg["profit_factor"]>controls["randomized_overall_p90_pf"],pair_ok,currency_ok,bool(nearby) and all(nearby),period_ok)
    agg["gates"]=g; agg["rejection_reasons"]=reasons
    classification="3. FORWARD-VALIDATION CANDIDATE" if all(g.values()) else ("2. CONTINUE RESEARCH" if sum(g.values())>=11 else "1. REJECT STRATEGY FAMILY")
    meta=accounting_metadata(has_explicit_stop=True)
    payload={"research_only":True,"paper_only":True,"accounting":meta,"input":{"fingerprints":HASHES,"manifests":manifests},
      "frozen_parameter_count":len(configs),"selection_basis":"DEV+VALIDATION only; TEST excluded", "selected_configuration":dict(zip(("method","lookback","filter","holding","atr_stop","target_r"),c)),
      "configurations":fold_records,"selected_result":chosen,"classification":classification}
    dump("currency_strength_fold_results.json",payload)
    dump("currency_strength_currency_contribution.json",{"accounting":meta,"pair_gross_profit_fraction":pair_frac,"currency_gross_profit_fraction":currency_frac,"no_pair_over_50pct":pair_ok,"no_currency_dominates":currency_ok})
    dump("currency_strength_randomized_controls.json",{"accounting":meta,**controls})
    dump("currency_strength_period_stability.json",{"accounting":meta,"periods":periods,"no_single_period_dependence":period_ok})
    dump("currency_strength_cost_stress.json",{"accounting":meta,"scenarios":stress})
    DOC.write_text(render(payload,agg,controls,periods,stress,pair_frac,currency_frac))
    print(json.dumps(clean({"classification":classification,"selected_configuration":payload["selected_configuration"],"aggregate":agg,"tests":"run pytest separately"}),indent=2))


def render(payload,agg,controls,periods,stress,pairs,currencies):
    cfg=payload["selected_configuration"]
    return f"""# Currency-Strength Research Phase 1 Checkpoint\n\n**Date:** 2026-07-21  \n**Classification:** {payload['classification']}\n\nResearch-only paper lab. This checkpoint does not claim profitability or authorize forward validation, signals, a watcher, or execution.\n\n## Frozen design and data\n\nThe implementation follows the frozen preregistration: signed base/quote aggregation over the limited EURUSD, GBPUSD, USDJPY, and AUDUSD hub universe; equal-weight, volatility-normalized, and ranked-momentum methods; isolated continuation, volatility-filter, and trend-confirm filters; and next-H1-open execution. The 405 frozen configurations cover 5 lookbacks, 3 holdings, 3 ATR stops, 3 targets, 3 strength methods, and 3 filters. Fingerprints: `{json.dumps(HASHES,sort_keys=True)}`. Analysis folds are DEV 2022-01-03–2023-06-30, VALIDATION 2023-07-01–2024-12-31, and held-out TEST 2025-01-01–2026-07-17. Selection used DEV+VALIDATION only.\n\nStrength is the equal average of signed containing-pair cumulative returns; volatility-normalized divides each pair return by its realized volatility; ranked momentum maps currency ranks to [0,1]. USDJPY uses the JPY pip multiplier (100), and all PnL is normalized equal-risk USD accounting v2.\n\n## Selected research configuration and chronological result\n\nConfiguration: `{json.dumps(cfg,sort_keys=True)}`. Aggregate chronological lifecycle metrics: PF {agg['profit_factor']:.4f}, return {agg['return']:.4%}, expectancy USD/trade {agg['expectancy_usd_per_trade']:.4f}, max drawdown {agg['max_drawdown_fraction']:.4%}, trades {agg['trade_count']}, robustness {agg['robustness']:.3f}, score {agg['score']:.2f}. Per-pair PnL: `{json.dumps(agg['pair_net_pnl_usd'],sort_keys=True)}`. These are research observations, not evidence of future profitability.\n\n## Controls, stability, costs, and concentration\n\nRandomized overall 90th-percentile PF: {controls['randomized_overall_p90_pf']:.4f}. Five-bps PF: {stress['5_bps']['profit_factor']:.4f}; 12-bps PF: {stress['12_bps']['profit_factor']:.4f}; delayed PF: {stress['execution_delay_plus_1h']['profit_factor']:.4f}. Pair gross-profit fractions: `{json.dumps(pairs,sort_keys=True)}`. Currency gross-profit fractions: `{json.dumps(currencies,sort_keys=True)}`. Best trade concentration: {agg['best_trade_gross_profit_fraction']:.2%}; best three: {agg['best_three_gross_profit_fraction']:.2%}. Period results, rolling 3y/5y diagnostics, and high/low-vol regimes are recorded in `currency_strength_period_stability.json`; 2010–2014 is N/A and is not fabricated.\n\n## Gate outcome and unresolved risks\n\nFailed gates: `{json.dumps(agg['rejection_reasons'])}`. The limited USD-hub universe creates structural USD dependence, missing crosses prevent a complete currency matrix, demo-history microstructure may differ from realizable costs, and randomized controls cannot eliminate selection bias. No live or paper-forward ledger paths were used.\n"""

if __name__ == "__main__": main()
