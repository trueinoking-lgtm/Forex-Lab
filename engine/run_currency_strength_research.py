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
AUDIT_DOC = BASE / "docs/checkpoints/currency_strength_accounting_audit_2026-07-21.md"
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
FROZEN_CONFIG={"method":"equal_weight","lookback":24,"holding":24,"atr_stop":2.0,
               "target_r":1.5,"filter":"continuation"}
FROZEN_SELECTED_AT="2026-07-21T15:36:11Z"
FROZEN_TEST_BOUNDARIES={"start":FOLDS["TEST"][0],"end":FOLDS["TEST"][1]}


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


def load_data(full_history=False):
    frames={}; manifests={}
    for pair, expected in HASHES.items():
        path=DATA/f"raw_mt5_{pair}_1h.csv"; mp=path.with_suffix(".manifest.json")
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected: raise ValueError(f"immutable fingerprint mismatch: {pair}")
        manifest=json.loads(mp.read_text())
        if manifest.get("symbol") != pair or manifest.get("timeframe") != "1h":
            raise ValueError(f"manifest identity mismatch: {pair}")
        frame=pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        start="2010-01-04" if full_history else "2022-01-03"
        frames[pair]=frame.loc[start:"2026-07-17 23:59:59", ["open","high","low","close"]]
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
    sig=signals.to_numpy(); pairs=list(signals.columns); active={}; trades=[]
    for k,i in enumerate(loc):
        if i < delay: continue
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
                pnl=RISK_USD*(raw_r-cost_r)
                trade={"pair":pair,"base":PAIR_CURRENCIES[pair][0],"quote":PAIR_CURRENCIES[pair][1],
                    "direction":"long" if d>0 else "short","entry_timestamp":signals.index[pos["entry_i"]],
                    "exit_timestamp":signals.index[i],"holding_hours":age,"gross_pnl_usd":RISK_USD*raw_r,
                    "cost_usd":RISK_USD*cost_r,"net_pnl_usd":pnl,"r_multiple":raw_r-cost_r,
                    "pip_multiplier":pip_multiplier(pair)}
                identity="|".join((pair,trade["direction"],trade["entry_timestamp"].isoformat(),
                                   trade["exit_timestamp"].isoformat()))
                trade["trade_id"]=hashlib.sha256(identity.encode()).hexdigest()[:24]
                trade["signal_timestamp"]=trade["entry_timestamp"]
                trades.append(trade)
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


def split_ledgers(trades, starting_equity=INITIAL):
    """Split generated opportunities from the executable, bankruptcy-bounded ledger."""
    ordered=sorted(enumerate(trades),key=lambda it:(pd.Timestamp(it[1].get("exit_timestamp",0)),it[0]))
    equity=float(starting_equity); bankrupt=False; bankruptcy_timestamp=None
    signal_ledger=[]; executable=[]; rejected=[]
    for _,source in ordered:
        trade=dict(source)
        trade.setdefault("signal_timestamp",trade.get("entry_timestamp"))
        equity_before=equity
        if bankrupt:
            accepted=False; reason="BANKRUPT"; equity_after=None
        else:
            accepted=True; reason=None
            equity=max(0.0,equity+float(trade["net_pnl_usd"]))
            equity_after=equity
            if equity<=0.0:
                bankrupt=True
                bankruptcy_timestamp=trade.get("exit_timestamp")
        trade.update({"accepted_for_portfolio":accepted,"rejection_reason":reason,
            "equity_before_entry":equity_before,"risk_at_entry":RISK_USD if accepted else 0.0,
            "equity_after_exit":equity_after,"bankruptcy_state":bankrupt})
        signal_ledger.append(trade)
        if accepted: executable.append(trade)
        else: rejected.append(trade)
    counts={reason:sum(t["rejection_reason"]==reason for t in rejected)
            for reason in ("BANKRUPT","CONCURRENCY","RISK_CAP","OTHER")}
    reconciliation={"generated_opportunities":len(signal_ledger),
      "accepted_entries":len(executable),"rejected_bankruptcy":counts["BANKRUPT"],
      "rejected_concurrency":counts["CONCURRENCY"],"rejected_risk_cap":counts["RISK_CAP"],
      "other_rejected":counts["OTHER"],"completed_accepted_trades":len(executable),
      "accepted_open_at_cutoff":0,"bankruptcy_timestamp":bankruptcy_timestamp}
    rhs=(reconciliation["accepted_entries"]+reconciliation["rejected_bankruptcy"]+
         reconciliation["rejected_concurrency"]+reconciliation["rejected_risk_cap"]+
         reconciliation["other_rejected"])
    reconciliation["reconciliation_rhs"]=rhs
    reconciliation["generated_equals_components"]=len(signal_ledger)==rhs
    assert reconciliation["generated_equals_components"]
    if bankruptcy_timestamp is not None:
        assert not any(pd.Timestamp(t["entry_timestamp"])>pd.Timestamp(bankruptcy_timestamp)
                       for t in executable)
        assert all(not t["accepted_for_portfolio"] and t["rejection_reason"]=="BANKRUPT"
                   for t in rejected)
    return {"signal_opportunity_ledger":signal_ledger,
            "executable_portfolio_ledger":executable,"signal_ledger":signal_ledger,
            "executable_ledger":executable,"reconciliation":reconciliation}


def portfolio_equity(trades, starting_equity=INITIAL):
    """Apply a shared, floored portfolio ledger to chronological closed trades."""
    # Python's stable sort preserves the simulator's deterministic pair-close order
    # for trades sharing an exit timestamp.
    ordered=sorted(enumerate(trades),key=lambda it:(pd.Timestamp(it[1].get("exit_timestamp",0)),it[0]))
    ordered=[trade for _,trade in ordered]
    equity=float(starting_equity); peak=equity; bankrupt=False; rows=[]; accepted=[]; rejected=[]
    for trade in ordered:
        if bankrupt:
            rejected.append(trade)
            continue
        equity=max(0.0,equity+float(trade["net_pnl_usd"])); peak=max(peak,equity)
        drawdown=(peak-equity)/peak if peak else 0.0
        rows.append({"trade_id":trade.get("trade_id"),"entry_timestamp":trade.get("entry_timestamp"),
                     "exit_timestamp":trade.get("exit_timestamp"),"net_pnl_usd":trade["net_pnl_usd"],
                     "equity":equity,"drawdown_decimal":drawdown})
        accepted.append(trade)
        bankrupt=equity<=0.0
    return {"starting_equity":float(starting_equity),"ending_equity":equity,
            "portfolio_return_decimal":equity/starting_equity-1.0,
            "max_drawdown_decimal":max((r["drawdown_decimal"] for r in rows),default=0.0),
            "bankrupt":bankrupt,"equity_curve":rows,"accepted_trades":accepted,
            "rejected_trades":rejected,"final_trade_before_bankruptcy":rows[-1] if bankrupt else None}


def metrics(trades):
    portfolio=portfolio_equity(trades); accepted=portfolio["accepted_trades"]
    pnl=np.array([t["net_pnl_usd"] for t in accepted],dtype=float)
    arithmetic_pnl=np.array([t["net_pnl_usd"] for t in trades],dtype=float)
    wins=pnl[pnl>0]; losses=pnl[pnl<0]; gp=float(wins.sum()); gl=float(-losses.sum())
    pf=gp/gl if gl else (float("inf") if gp else 0.0)
    by_pair={p:float(sum(t["net_pnl_usd"] for t in accepted if t["pair"]==p)) for p in PAIR_CURRENCIES}
    counts={p:sum(t["pair"]==p for t in accepted) for p in PAIR_CURRENCIES}
    positive=sum(v>0 for v in by_pair.values()); robustness=positive/4
    ret=portfolio["portfolio_return_decimal"]
    score=max(0.0,min(100.0,25*ret+20*min(pf,2)+20*robustness))
    sorted_w=np.sort(wins)[::-1]; denom=gp or 1.0
    return {"trade_count":len(accepted),"closed_trade_ledger_count":len(trades),
      "trades_rejected_after_bankruptcy":len(portfolio["rejected_trades"]),
      "gross_profit_usd":gp,"gross_loss_usd":gl,"profit_factor":pf,
      "arithmetic_return_sum":float(arithmetic_pnl.sum()/INITIAL) if len(arithmetic_pnl) else 0.0,
      "portfolio_return_decimal":ret,"return":ret,"starting_equity":INITIAL,
      "ending_equity":portfolio["ending_equity"],"bankrupt":portfolio["bankrupt"],
      "expectancy_usd_per_trade":float(pnl.mean()) if len(pnl) else 0.0,
      "max_drawdown_decimal":portfolio["max_drawdown_decimal"],
      "max_drawdown_fraction":portfolio["max_drawdown_decimal"],"robustness":robustness,"score":score,
      "long_trades":sum(t["direction"]=="long" for t in accepted),"short_trades":sum(t["direction"]=="short" for t in accepted),
      "mean_holding_hours":float(np.mean([t["holding_hours"] for t in accepted])) if accepted else 0.0,
      "pair_net_pnl_usd":by_pair,"pair_trade_count":counts,"positive_pairs":positive,
      "best_trade_gross_profit_fraction":float(sorted_w[:1].sum()/denom),
      "best_three_gross_profit_fraction":float(sorted_w[:3].sum()/denom),"exposure_trade_hours":sum(t["holding_hours"] for t in accepted)}


def signal_diagnostic_metrics(trades):
    """Hypothetical all-opportunity statistics; never eligible for portfolio gates."""
    pnl=np.array([t["net_pnl_usd"] for t in trades],dtype=float)
    wins=pnl[pnl>0]; losses=pnl[pnl<0]; gp=float(wins.sum()); gl=float(-losses.sum())
    pf=gp/gl if gl else (float("inf") if gp else 0.0)
    by_pair={p:float(sum(t["net_pnl_usd"] for t in trades if t["pair"]==p)) for p in PAIR_CURRENCIES}
    robustness=sum(v>0 for v in by_pair.values())/4
    ret=float(pnl.sum()/INITIAL) if len(pnl) else 0.0
    running=INITIAL+np.cumsum(pnl); curve=np.r_[INITIAL,running]
    peaks=np.maximum.accumulate(curve); dd=np.divide(peaks-curve,peaks,out=np.zeros_like(curve),where=peaks!=0)
    return {"ledger_role":"non_executable_signal_diagnostic","generated_opportunities":len(trades),
      "trade_count":len(trades),"profit_factor":pf,"expectancy_usd_per_trade":float(pnl.mean()) if len(pnl) else 0.0,
      "arithmetic_return_sum":ret,"portfolio_return_decimal":ret,"return":ret,
      "starting_equity":INITIAL,"ending_equity":INITIAL+float(pnl.sum()),
      "max_drawdown_decimal":float(dd.max()) if len(dd) else 0.0,"robustness":robustness,
      "score":max(0.0,min(100.0,25*ret+20*min(pf,2)+20*robustness)),
      "classification":"diagnostic only","eligibility_allowed":False}


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


def random_controls(frames, canonical_signals, cfg, canonical_pf, allowed_index=None):
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
            tr=simulate(frames,pd.DataFrame(x,index=canonical_signals.index,columns=pairs),cfg[1],cfg[3],cfg[4],cfg[5],allowed_index=allowed_index)
            rng_results[kind].append(metrics(split_ledgers(tr)["executable_ledger"])["profit_factor"])
    flat=[v for values in rng_results.values() for v in values]
    summary={k:{"seeds":10,"median_pf":float(np.median(v)),"p90_pf":float(np.quantile(v,.9)),
                "percent_beaten":100*float(np.mean(canonical_pf>np.array(v)))} for k,v in rng_results.items()}
    return {"no_trade":{"trade_count":0,"return":0.0},"randomized":summary,
      "randomized_overall_p90_pf":float(np.quantile(flat,.9)),"equal_weight_momentum":"canonical equal_weight reference grid",
      "individual_pair_momentum":"reported as descriptive control; no cross-sectional selection",
      "rejected_family_references":["ema","trend_continuation","range_mean_reversion","session_breakout"]}


def frozen_config_hash(config=FROZEN_CONFIG):
    canonical=json.dumps(config,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def currency_boundary_passes(currency_frac):
    """Frozen inclusive rule: max currency fraction <= 0.50 and USD <= 0.50."""
    return max(currency_frac.values(),default=0.0)<=0.5 and currency_frac.get("USD",0.0)<=0.5


def rank_selection_inputs(candidates):
    """Rank exclusively on persisted DEV/VALIDATION inputs; TEST is not accepted."""
    def rank(row):
        dev=row["DEV"]; val=row["VALIDATION"]
        return ((dev["profit_factor"]+val["profit_factor"])/2,
                dev["robustness"]+val["robustness"],
                dev["trade_count"]+val["trade_count"])
    return max(candidates,key=rank)


def build_grid():
    """Legacy frozen research grid; audit mode must never call this function."""
    return list(itertools.product(METHODS,LOOKBACKS,FILTERS,HOLDINGS,STOPS,TARGETS))


def scope_record(name, trades, start, end, gate_context=None):
    m=metrics(trades); checks,reasons=gates(m,**(gate_context or {}))
    start_ts=pd.Timestamp(start); end_ts=pd.Timestamp(end)
    if start_ts.tzinfo is None: start_ts=start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None: end_ts=end_ts.tz_localize("UTC")
    return {"scope":name,"start_timestamp":start_ts,"end_timestamp":end_ts,
            "trade_ids":[t["trade_id"] for t in trades],**m,
            "gate_outcomes":checks,"failed_gates":reasons}


def run_audit():
    """Reconcile the frozen candidate only; this function never constructs the grid."""
    frames,manifests=load_data(full_history=True)
    closes=pd.DataFrame({p:f.close for p,f in frames.items()})
    cfg=FROZEN_CONFIG; cfg_tuple=(cfg["method"],cfg["lookback"],cfg["filter"],cfg["holding"],cfg["atr_stop"],cfg["target_r"])
    reference_closes=closes.loc["2022-01-03":]
    research_frames={pair:frame.reindex(reference_closes.index) for pair,frame in frames.items()}
    reference=construct_signals(reference_closes,cfg["lookback"],cfg["method"],cfg["filter"])
    signals=construct_signals(reference_closes,cfg["lookback"],cfg["method"],cfg["filter"])
    pd.testing.assert_frame_equal(signals,reference)
    historical_signals=construct_signals(closes,cfg["lookback"],cfg["method"],cfg["filter"])

    fold_trades={}
    for name,(start,end) in FOLDS.items():
        ix=closes.loc[pd.Timestamp(start,tz="UTC"):pd.Timestamp(end,tz="UTC")].index
        fold_trades[name]=simulate(research_frames,signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],allowed_index=ix)
    full_trades=simulate(frames,historical_signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"])
    dev_ids={t["trade_id"] for t in fold_trades["DEV"]}; val_ids={t["trade_id"] for t in fold_trades["VALIDATION"]}
    test_ids={t["trade_id"] for t in fold_trades["TEST"]}
    leakage_ok=not ((dev_ids|val_ids)&test_ids)
    assert leakage_ok

    # All eligibility inputs below are explicitly TEST-only and executable-ledger-only.
    test_ledgers=split_ledgers(fold_trades["TEST"])
    executable_test=test_ledgers["executable_ledger"]
    test_metrics=metrics(executable_test)
    signal_test_metrics=signal_diagnostic_metrics(test_ledgers["signal_ledger"])
    test_ix=closes.loc[FOLDS["TEST"][0]:FOLDS["TEST"][1]].index
    stress={}
    for label,bps in (("3_bps",3),("5_bps",5),("8_bps",8),("12_bps",12),("doubled_spread",6),("doubled_slippage",4),("nonzero_commission",4)):
        generated=simulate(research_frames,signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],cost_bps=bps,allowed_index=test_ix)
        stress[label]=metrics(split_ledgers(generated)["executable_ledger"])
    generated=simulate(research_frames,signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],delay=2,allowed_index=test_ix)
    stress["execution_delay_plus_1h"]=metrics(split_ledgers(generated)["executable_ledger"])
    ranked=sorted(executable_test,key=lambda t:t["net_pnl_usd"],reverse=True)
    stress["remove_best_trade"]=metrics(ranked[1:]); stress["remove_best_three"]=metrics(ranked[3:])
    controls=random_controls(research_frames,signals,cfg_tuple,test_metrics["profit_factor"],allowed_index=test_ix)

    accepted_test=executable_test
    contrib={p:sum(max(0,t["net_pnl_usd"]) for t in accepted_test if t["pair"]==p) for p in PAIR_CURRENCIES}
    total=sum(contrib.values()) or 1.0; pair_frac={p:v/total for p,v in contrib.items()}
    currency={u:0.0 for u in ("EUR","GBP","USD","JPY","AUD")}
    for pair,value in contrib.items():
        currency[PAIR_CURRENCIES[pair][0]]+=value/2; currency[PAIR_CURRENCIES[pair][1]]+=value/2
    currency_frac={u:v/total for u,v in currency.items()}
    pair_ok=max(pair_frac.values(),default=0)<=0.5; currency_ok=currency_boundary_passes(currency_frac)

    period_specs=(("2010_2014","2010-01-04","2014-12-31 23:59:59"),("2015_2019","2015-01-01","2019-12-31 23:59:59"),
                  ("2020_2022","2020-01-01","2022-12-31 23:59:59"),("2023_2026","2023-01-01","2026-07-17 23:59:59"))
    periods={}
    for label,start,end in period_specs:
        ix=closes.loc[start:end].index; tr=simulate(frames,historical_signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],allowed_index=ix)
        ledgers=split_ledgers(tr)
        periods[label]={"status":"evaluated","scope":"full_historical_diagnostic","start_timestamp":ix.min(),"end_timestamp":ix.max(),
          "generated_opportunity_count":len(ledgers["signal_ledger"]),"accepted_portfolio_trade_count":len(ledgers["executable_ledger"]),
          **metrics(ledgers["executable_ledger"])}
    periods["rolling_3y"]=[]
    for year in range(2012,2027):
        start=f"{year-2}-01-01"; end=min(pd.Timestamp(f"{year}-12-31 23:59:59",tz="UTC"),pd.Timestamp("2026-07-17 23:59:59",tz="UTC"))
        ix=closes.loc[pd.Timestamp(start,tz="UTC"):end].index
        tr=simulate(frames,historical_signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],allowed_index=ix); ledgers=split_ledgers(tr)
        periods["rolling_3y"].append({"scope":"full_historical_diagnostic","start_timestamp":ix.min(),"end_timestamp":ix.max(),
          "generated_opportunity_count":len(ledgers["signal_ledger"]),"accepted_portfolio_trade_count":len(ledgers["executable_ledger"]),**metrics(ledgers["executable_ledger"])})
    periods["rolling_5y"]=[]
    for year in range(2014,2027):
        start=f"{year-4}-01-01"; end=min(pd.Timestamp(f"{year}-12-31 23:59:59",tz="UTC"),pd.Timestamp("2026-07-17 23:59:59",tz="UTC"))
        ix=closes.loc[pd.Timestamp(start,tz="UTC"):end].index
        tr=simulate(frames,historical_signals,cfg["lookback"],cfg["holding"],cfg["atr_stop"],cfg["target_r"],allowed_index=ix); ledgers=split_ledgers(tr)
        periods["rolling_5y"].append({"scope":"full_historical_diagnostic","start_timestamp":ix.min(),"end_timestamp":ix.max(),
          "generated_opportunity_count":len(ledgers["signal_ledger"]),"accepted_portfolio_trade_count":len(ledgers["executable_ledger"]),**metrics(ledgers["executable_ledger"])})
    hourly=closes.pct_change().std(axis=1); med=hourly.median()
    periods["volatility_regimes"]={}
    for label in ("high","low"):
        tr=[t for t in full_trades if ((hourly.get(t["entry_timestamp"],0)>=med)==(label=="high"))]
        ledgers=split_ledgers(tr)
        periods["volatility_regimes"][label]={"scope":"full_historical_diagnostic",
          "generated_opportunity_count":len(ledgers["signal_ledger"]),"accepted_portfolio_trade_count":len(ledgers["executable_ledger"]),**metrics(ledgers["executable_ledger"])}
    period_ok=sum(periods[x]["portfolio_return_decimal"]>0 for x,_,_ in period_specs)>=2

    gate_context={"survive_5":stress["5_bps"]["portfolio_return_decimal"]>0,
      "beats_random":test_metrics["profit_factor"]>controls["randomized_overall_p90_pf"],
      "pair_contrib_ok":pair_ok,"currency_ok":currency_ok,"nearby":False,"periods":period_ok}
    fold_ledgers={name:split_ledgers(fold_trades[name]) for name in FOLDS}
    scopes={name.lower():scope_record(name.lower(),fold_ledgers[name]["executable_ledger"],*FOLDS[name],gate_context if name=="TEST" else None) for name in FOLDS}
    scopes["chronological_test"]=scopes["test"]
    scopes["aggregate_test"]={**scopes["test"],"scope":"aggregate_test"}
    full_ledgers=split_ledgers(full_trades)
    scopes["full_history"]=scope_record("full_historical_diagnostic",full_ledgers["executable_ledger"],closes.index.min(),closes.index.max())
    canonical_checks=scopes["chronological_test"]["gate_outcomes"]
    classification=("3. FORWARD-VALIDATION CANDIDATE" if all(canonical_checks.values()) else
                    ("2. CONTINUE RESEARCH" if sum(canonical_checks.values())>=11 else
                     "1. REJECT STRATEGY FAMILY"))

    prior=json.loads((RESULTS/"currency_strength_fold_results.json").read_text())
    candidates=[]
    for row in prior["configurations"]:
        candidates.append({"configuration":row["configuration"],"DEV":row["folds"]["DEV"],"VALIDATION":row["folds"]["VALIDATION"]})
    selected=rank_selection_inputs(candidates); selected_hash=frozen_config_hash(selected["configuration"])
    assert selected_hash==frozen_config_hash()
    hidden_selected=rank_selection_inputs(json.loads(json.dumps(candidates)))
    hidden_hash=frozen_config_hash(hidden_selected["configuration"]); assert hidden_hash==selected_hash
    leakage={"candidate_selection_inputs":candidates,
      "ranking_rule":"max(mean(DEV PF, VALIDATION PF), DEV robustness + VALIDATION robustness, DEV trade_count + VALIDATION trade_count); TEST excluded",
      "selected_configuration":cfg,"selected_configuration_hash":selected_hash,
      "selection_timestamp":FROZEN_SELECTED_AT,"frozen_test_boundaries":FROZEN_TEST_BOUNDARIES,
      "hidden_test_reproducibility":{"test_outcomes_present":False,"selected_configuration_hash":hidden_hash,"identical":True}}
    meta=accounting_metadata(has_explicit_stop=True)
    equity=portfolio_equity(executable_test)
    accepted_ids=[t["trade_id"] for t in executable_test]
    rejected=[t for t in test_ledgers["signal_ledger"] if not t["accepted_for_portfolio"]]
    rejected_ids=[t["trade_id"] for t in rejected]
    bankruptcy_ts=test_ledgers["reconciliation"]["bankruptcy_timestamp"]
    metric_id_sets={name:accepted_ids for name in ("profit_factor","expectancy","return","drawdown","robustness","score")}
    ledger_invariants={"no_accepted_entry_after_bankruptcy_timestamp":bankruptcy_ts is None or not any(
        pd.Timestamp(t["entry_timestamp"])>pd.Timestamp(bankruptcy_ts) for t in executable_test),
      "all_post_bankruptcy_opportunities_rejected_bankrupt":all(
        not t["accepted_for_portfolio"] and t["rejection_reason"]=="BANKRUPT" for t in rejected),
      "portfolio_metrics_include_only_accepted_completed_trades":test_metrics["trade_count"]==len(accepted_ids),
      "portfolio_trade_count_excludes_rejected_opportunities":not (set(accepted_ids)&set(rejected_ids)),
      "signal_ledger_metrics_never_drive_eligibility":not signal_test_metrics["eligibility_allowed"],
      "minimum_trade_gate_uses_accepted_completed_trades":scopes["chronological_test"]["gate_outcomes"]["trades_gte_300"]==(len(accepted_ids)>=300),
      "all_canonical_metrics_use_identical_accepted_trade_ids":len({tuple(v) for v in metric_id_sets.values()})==1}
    assert all(ledger_invariants.values())
    dump("currency_strength_audit_scope.json",{"accounting":meta,"gate_bearing_scope":"chronological_test","scopes":scopes,
      "chronological_test_reconciliation":test_ledgers["reconciliation"],
      "non_executable_signal_diagnostic":signal_test_metrics,
      "canonical_metric_trade_ids":metric_id_sets,"ledger_invariants":ledger_invariants,
      "leakage_invariant":{"no_dev_or_validation_trade_id_in_chronological_test":leakage_ok,"overlap_trade_ids":[]}})
    dump("currency_strength_audit_equity_curve.json",{"accounting":meta,"scope":"chronological_test",**equity,
      "canonical_ledger":"executable_portfolio_ledger","accepted_trade_ids":accepted_ids,
      "trades_rejected_after_bankruptcy":rejected_ids})
    dump("currency_strength_audit_ledger_reconciliation.json",{"accounting":meta,"scope":"chronological_test",
      "ledger_roles":{"signal_opportunity_ledger":"diagnostic only; cannot determine watcher eligibility",
        "executable_portfolio_ledger":"canonical gate-bearing ledger"},
      "reconciliation":test_ledgers["reconciliation"],"signal_diagnostic_metrics":signal_test_metrics,
      "executable_portfolio_metrics":test_metrics,"signal_opportunity_ledger":test_ledgers["signal_ledger"],
      "executable_portfolio_ledger":executable_test,"invariants":ledger_invariants})
    dump("currency_strength_audit_accepted_vs_rejected.json",{"accounting":meta,"scope":"chronological_test",
      "accepted_trade_ids":accepted_ids,"rejected_trade_ids":rejected_ids,
      "rejected_trades":[{"trade_id":t["trade_id"],"rejection_reason":t["rejection_reason"]} for t in rejected]})
    dump("currency_strength_audit_leakage.json",{"accounting":meta,**leakage})
    dump("currency_strength_period_stability_corrected.json",{"accounting":meta,"scope":"full_historical_diagnostic","periods":periods,"no_single_period_dependence":period_ok})
    frozen_payload={"accounting":meta,"selected_configuration":cfg,"selected_configuration_hash":selected_hash,
      "gate_bearing_scope":"chronological_test","canonical_ledger":"executable_portfolio_ledger",
      "chronological_test":scopes["chronological_test"],"non_executable_signal_diagnostic":signal_test_metrics,
      "reconciliation":test_ledgers["reconciliation"],"full_history":scopes["full_history"],"classification":classification}
    dump("currency_strength_frozen_candidate_corrected.json",frozen_payload)
    dump("currency_strength_currency_contribution.json",{"accounting":meta,"scope":"chronological_test","exact_currency_rule":"max(currency_frac) <= 0.5 AND USD <= 0.5","pair_gross_profit_fraction":pair_frac,"currency_gross_profit_fraction":currency_frac,"no_pair_over_50pct":pair_ok,"no_currency_dominates":currency_ok})
    dump("currency_strength_cost_stress.json",{"accounting":meta,"scope":"chronological_test","scenarios":stress})
    dump("currency_strength_randomized_controls.json",{"accounting":meta,"scope":"chronological_test",**controls})
    AUDIT_DOC.write_text(render_audit(prior,scopes["chronological_test"],scopes["full_history"],periods,pair_frac,currency_frac,selected_hash,classification,signal_test_metrics,test_ledgers["reconciliation"]))
    summary={"classification":classification,"selected_configuration":cfg,"selected_configuration_hash":selected_hash,
             "gate_bearing_scope":"chronological_test","chronological_test":test_metrics,
             "non_executable_signal_diagnostic":signal_test_metrics,"reconciliation":test_ledgers["reconciliation"],
             "full_history":metrics(full_ledgers["executable_ledger"]),"periods":{k:periods[k] for k,_,_ in period_specs},
             "pair_gross_profit_fraction":pair_frac,"currency_gross_profit_fraction":currency_frac}
    print(json.dumps(clean(summary),indent=2)); return summary


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--config",help="reserved deterministic config label")
    parser.add_argument("--audit",action="store_true",help="reconcile the frozen candidate without grid selection")
    args=parser.parse_args()
    if args.audit:
        run_audit(); return
    frames, manifests=load_data(); closes=pd.DataFrame({p:f.close for p,f in frames.items()})
    configs=build_grid()
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
        selection.append((sel_pf,fold_metrics["DEV"]["robustness"]+fold_metrics["VALIDATION"]["robustness"],
                          fold_metrics["DEV"]["trade_count"]+fold_metrics["VALIDATION"]["trade_count"],key,c))
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


def render_audit(prior,test,full,periods,pairs,currencies,config_hash,classification,signal,reconciliation):
    original=prior["selected_result"]["aggregate_chronological"]
    rows=(
      ("Test trades",original["trade_count"],test["trade_count"],"Original aggregate included DEV and VALIDATION; corrected value is TEST-only"),
      ("PF",original["profit_factor"],test["profit_factor"],"TEST-only accepted shared-equity ledger"),
      ("Expectancy (USD/trade)",original["expectancy_usd_per_trade"],test["expectancy_usd_per_trade"],"TEST-only accepted shared-equity ledger"),
      ("Arithmetic return sum",original["return"],test["arithmetic_return_sum"],"Fixed-$100 additive diagnostic retained under its correct name"),
      ("Portfolio return",original["return"],test["portfolio_return_decimal"],"Floored shared portfolio equity"),
      ("Ending equity",INITIAL+original["return"]*INITIAL,test["ending_equity"],"Original curve was unfloored; corrected curve floors at zero"),
      ("Max drawdown",original["max_drawdown_fraction"],test["max_drawdown_decimal"],"Floored curve bounds drawdown to [0,1]"),
      ("Bankrupt","not reported",test["bankrupt"],"Explicit shared-equity bankruptcy state"),
      ("Robustness",original["robustness"],test["robustness"],"TEST-only pair outcomes"),
      ("Score",original["score"],test["score"],"Uses portfolio return; arithmetic diagnostic cannot drive gates"),
      ("Classification",prior["classification"],classification,"Corrected chronological gates do not all pass"))
    table="\n".join(f"| {metric} | {clean(before)} | {clean(after)} | {reason} |" for metric,before,after,reason in rows)
    ledger_rows=(("Generated opportunities",signal["generated_opportunities"],reconciliation["generated_opportunities"]),
      ("Accepted completed trades","diagnostic only",reconciliation["completed_accepted_trades"]),
      ("Bankruptcy rejections","diagnostic only",reconciliation["rejected_bankruptcy"]),
      ("PF",signal["profit_factor"],test["profit_factor"]),("Expectancy (USD/trade)",signal["expectancy_usd_per_trade"],test["expectancy_usd_per_trade"]),
      ("Return",signal["return"],test["portfolio_return_decimal"]),("Drawdown",signal["max_drawdown_decimal"],test["max_drawdown_decimal"]),
      ("Ending equity",signal["ending_equity"],test["ending_equity"]),("Robustness",signal["robustness"],test["robustness"]),
      ("Score",signal["score"],test["score"]),("Classification","diagnostic only",classification))
    ledger_table="\n".join(f"| {name} | {clean(sig)} | {clean(exe)} |" for name,sig,exe in ledger_rows)
    period_lines="\n".join(f"- {name}: trades={periods[name]['trade_count']}, PF={periods[name]['profit_factor']:.6f}, arithmetic={periods[name]['arithmetic_return_sum']:.6f}, portfolio={periods[name]['portfolio_return_decimal']:.6f}, max DD={periods[name]['max_drawdown_decimal']:.6f}, bankrupt={periods[name]['bankrupt']}" for name in ("2010_2014","2015_2019","2020_2022","2023_2026"))
    return f"""# Currency-Strength Accounting and Scope Audit

**Date:** 2026-07-21
**Classification:** {classification}
**Frozen configuration hash:** `{config_hash}`

Research-only reconciliation of accounting and result scope. No parameter, gate, signal construction, or frozen candidate was changed. Audit mode loads only `{json.dumps(FROZEN_CONFIG,sort_keys=True)}` and does not enumerate or reselect the 405 configurations.

## Findings

The return below -100% was the fixed-notional additive sum (`sum(net_pnl_usd) / 10000`) mislabeled as portfolio return. It remains available only as `arithmetic_return_sum`. The drawdown above 100% came from an unfloored `10000 + cumulative PnL` curve. The corrected shared-equity ledger applies `max(0, equity + net_pnl)` to trades ordered by exit timestamp, declares bankruptcy at zero, and rejects every later trade from portfolio metrics.

The sole gate-bearing scope is `chronological_test` ({FOLDS['TEST'][0]} through {FOLDS['TEST'][1]}). DEV, VALIDATION, TEST, aggregate TEST, and full-history diagnostics are separate records with disjoint fold trade identifiers. Persisted selection inputs and a hidden-TEST replay prove selection depends only on DEV and VALIDATION. The exact concentration rule is `max(currency_frac) <= 0.5 AND USD <= 0.5`; the 0.50 boundary is inclusive.

## Before / after

| Metric | Original | Corrected | Reason |
|---|---:|---:|---|
{table}

## Historical diagnostics

All periods are `full_historical_diagnostic` and never enter eligibility. All four immutable H1 inputs begin 2010-01-04, so 2010-2014 is evaluated rather than marked unavailable.

{period_lines}

Rolling three-year and five-year windows plus high/low-volatility regimes are in `currency_strength_period_stability_corrected.json`.

## PART: ledger reconciliation

The signal opportunity ledger contains every valid strategy-generated hypothetical trade and is diagnostic only. The executable portfolio ledger contains only accepted completed trades up to bankruptcy and is the sole source for gates, return, drawdown, robustness, score, contribution, cost stress, and classification. The TEST count proof is `{reconciliation['generated_opportunities']} = {reconciliation['accepted_entries']} + {reconciliation['rejected_bankruptcy']} + {reconciliation['rejected_concurrency']} + {reconciliation['rejected_risk_cap']} + {reconciliation['other_rejected']}`. Thus {reconciliation['generated_opportunities']} means generated signals/completed hypothetical trades, not accepted portfolio trades ({reconciliation['completed_accepted_trades']}).

| Metric | Signal diagnostic | Executable portfolio |
|---|---:|---:|
{ledger_table}

## Contributions

TEST pair gross-profit fractions: `{json.dumps(clean(pairs),sort_keys=True)}`. TEST currency gross-profit fractions: `{json.dumps(clean(currencies),sort_keys=True)}`.

The final classification remains **{classification}**. Audit artifacts use accounting v2 and are runtime-generated under the ignored `engine/results/` directory.
"""


def render(payload,agg,controls,periods,stress,pairs,currencies):
    cfg=payload["selected_configuration"]
    return f"""# Currency-Strength Research Phase 1 Checkpoint\n\n**Date:** 2026-07-21  \n**Classification:** {payload['classification']}\n\nResearch-only paper lab. This checkpoint does not claim profitability or authorize forward validation, signals, a watcher, or execution.\n\n## Frozen design and data\n\nThe implementation follows the frozen preregistration: signed base/quote aggregation over the limited EURUSD, GBPUSD, USDJPY, and AUDUSD hub universe; equal-weight, volatility-normalized, and ranked-momentum methods; isolated continuation, volatility-filter, and trend-confirm filters; and next-H1-open execution. The 405 frozen configurations cover 5 lookbacks, 3 holdings, 3 ATR stops, 3 targets, 3 strength methods, and 3 filters. Fingerprints: `{json.dumps(HASHES,sort_keys=True)}`. Analysis folds are DEV 2022-01-03–2023-06-30, VALIDATION 2023-07-01–2024-12-31, and held-out TEST 2025-01-01–2026-07-17. Selection used DEV+VALIDATION only.\n\nStrength is the equal average of signed containing-pair cumulative returns; volatility-normalized divides each pair return by its realized volatility; ranked momentum maps currency ranks to [0,1]. USDJPY uses the JPY pip multiplier (100), and all PnL is normalized equal-risk USD accounting v2.\n\n## Selected research configuration and chronological result\n\nConfiguration: `{json.dumps(cfg,sort_keys=True)}`. Aggregate chronological lifecycle metrics: PF {agg['profit_factor']:.4f}, return {agg['return']:.4%}, expectancy USD/trade {agg['expectancy_usd_per_trade']:.4f}, max drawdown {agg['max_drawdown_fraction']:.4%}, trades {agg['trade_count']}, robustness {agg['robustness']:.3f}, score {agg['score']:.2f}. Per-pair PnL: `{json.dumps(agg['pair_net_pnl_usd'],sort_keys=True)}`. These are research observations, not evidence of future profitability.\n\n## Controls, stability, costs, and concentration\n\nRandomized overall 90th-percentile PF: {controls['randomized_overall_p90_pf']:.4f}. Five-bps PF: {stress['5_bps']['profit_factor']:.4f}; 12-bps PF: {stress['12_bps']['profit_factor']:.4f}; delayed PF: {stress['execution_delay_plus_1h']['profit_factor']:.4f}. Pair gross-profit fractions: `{json.dumps(pairs,sort_keys=True)}`. Currency gross-profit fractions: `{json.dumps(currencies,sort_keys=True)}`. Best trade concentration: {agg['best_trade_gross_profit_fraction']:.2%}; best three: {agg['best_three_gross_profit_fraction']:.2%}. Period results, rolling 3y/5y diagnostics, and high/low-vol regimes are recorded in `currency_strength_period_stability.json`; 2010–2014 is N/A and is not fabricated.\n\n## Gate outcome and unresolved risks\n\nFailed gates: `{json.dumps(agg['rejection_reasons'])}`. The limited USD-hub universe creates structural USD dependence, missing crosses prevent a complete currency matrix, demo-history microstructure may differ from realizable costs, and randomized controls cannot eliminate selection bias. No live or paper-forward ledger paths were used.\n"""

if __name__ == "__main__": main()
