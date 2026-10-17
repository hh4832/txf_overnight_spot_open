"""Simple, predeclared trading-reference summaries. Not trade backtests."""
import numpy as np
import pandas as pd

EDGES = [-np.inf,-.01,-.005,0,.005,.01,np.inf]
LABELS = ['<-1%','[-1%,-0.5%)','[-0.5%,0%)','[0%,0.5%)','[0.5%,1%)','>=1%']
COLUMNS = ['sample','scenario','n','status','gap_mean','gap_median',
           'gap_positive_probability','gap_negative_probability',
           'intraday_mean','intraday_median',
           'intraday_positive_probability','intraday_negative_probability',
           'year']


def _summary(df,sample,scenario,year='',min_bin=10):
    n=len(df)
    return dict(sample=sample,scenario=scenario,n=n,
                status='OK' if n>=min_bin else 'SMALL_SAMPLE',
                gap_mean=df.spot_opening_gap.mean() if n else np.nan,
                gap_median=df.spot_opening_gap.median() if n else np.nan,
                gap_positive_probability=(df.spot_opening_gap>0).mean() if n else np.nan,
                gap_negative_probability=(df.spot_opening_gap<0).mean() if n else np.nan,
                intraday_mean=df.spot_intraday_return.mean() if n else np.nan,
                intraday_median=df.spot_intraday_return.median() if n else np.nan,
                intraday_positive_probability=(df.spot_intraday_return>0).mean() if n else np.nan,
                intraday_negative_probability=(df.spot_intraday_return<0).mean() if n else np.nan,
                year=year)


def _bin_table(df,sample,year=''):
    f=df.copy()
    f['predefined_bin']=pd.cut(f.txf_overnight_return,bins=EDGES,
                               labels=LABELS,right=False)
    return pd.DataFrame([
        _summary(f[f.predefined_bin==label],sample,label,year)
        for label in LABELS],columns=COLUMNS)


def trading_reference(valid,cfg):
    """Return full descriptive, annual, strict future holdout, close convention QA.

    Holdout is *chronological*, reported only when there are at least
    `initial_train` previous observations. Its fixed bins were decided
    before seeing outcomes. No optimization, invented figures, or cost PnL.
    """
    f=valid.sort_values('signal_trade_date').reset_index(drop=True)
    full=_bin_table(f,'all_history')
    annual=pd.concat([
        _bin_table(part,'year_'+year,year)
        for year,part in f.groupby(f.signal_trade_date.astype(str).str[:4])
    ],ignore_index=True) if len(f) else pd.DataFrame(columns=COLUMNS)
    train=int(cfg.get('initial_train',252))
    if len(f)>train:
        holdout=_bin_table(f.iloc[train:],'chronological_holdout')
        holdout.insert(1,'training_observations',train)
        holdout.insert(2,'holdout_from',f.iloc[train].signal_trade_date)
        holdout.insert(3,'train_last_date',f.iloc[train-1].signal_trade_date)
    else:
        holdout=_bin_table(f.iloc[0:0],'INSUFFICIENT_HISTORY')
        holdout.insert(1,'training_observations',min(train,len(f)))
        holdout.insert(2,'holdout_from',None)
        holdout.insert(3,'train_last_date',None)
        holdout['status']='NOT_EVALUATED_INSUFFICIENT_HISTORY'
    paired=f[f.txf_overnight_return_fixed.notna()].copy()
    diff=paired.txf_adaptive_minus_fixed_bp
    reference=pd.DataFrame([dict(
        valid_events=len(f),paired_fixed_comparator=len(paired),
        adaptive_boundary_events=int(f.day_close_rule.eq('ADAPTIVE_BOUNDARY').sum()+
                                     f.night_close_rule.eq('ADAPTIVE_BOUNDARY').sum()) if len(f) else 0,
        difference_mean_bp=diff.mean() if len(diff) else np.nan,
        difference_median_abs_bp=diff.abs().median() if len(diff) else np.nan,
        difference_max_abs_bp=diff.abs().max() if len(diff) else np.nan,
        reference_status='DESCRIPTIVE_NOT_VENDOR_TIMESTAMP_VERIFICATION',
    )])
    return {'trading_reference':full,
            'trading_reference_by_year':annual,
            'trading_reference_holdout':holdout,
            'close_policy_comparison':reference}
