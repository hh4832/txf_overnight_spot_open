import numpy as np
import pandas as pd
from scipy.stats import t
from statsmodels.stats.proportion import proportion_confint
from .statistics import X


def historical_bins(series,minimum=252):
    """Every threshold excludes the current observation and every future observation."""
    thresholds=series.shift(1).expanding(min_periods=minimum).quantile
    edges=pd.concat([thresholds(q) for q in [.05,.2,.4,.6,.8,.95]],axis=1)
    result=(series.to_numpy()[:,None]>edges.to_numpy()).sum(axis=1).astype(float)
    result[edges.isna().any(axis=1)]=np.nan
    return pd.Series(result,index=series.index)


def summarize(f, name):
    n=len(f)
    row={'scenario':name,'n':n,'status':'OK' if n>=30 else 'INSUFFICIENT_OBSERVATIONS'}
    for c in ['spot_opening_gap','spot_intraday_return']:
        values=f[c]
        mean=values.mean()
        se=values.std(ddof=1)/np.sqrt(n) if n>1 else np.nan
        ci=t.ppf(.975,n-1)*se if n>1 else np.nan
        k=int((values<0).sum())
        lo,hi=proportion_confint(k,n,method='wilson') if n else (np.nan,np.nan)
        row.update({c+'_mean':mean,c+'_median':values.median(),c+'_ci_low':mean-ci,c+'_ci_high':mean+ci,
                    c+'_negative_probability':k/n if n else np.nan,c+'_positive_probability':float((values>0).mean()),
                    c+'_negative_ci_low':lo,c+'_negative_ci_high':hi})
    row['mean_ci_method']='descriptive_t_IID; probability_CI=Wilson; serial dependence not adjusted'
    return row


def conditional(df,cfg):
    masks={'unconditional':pd.Series(True,index=df.index),'overnight_negative':df[X]<0,
           'overnight_positive':df[X]>0,'down_and_gap_down':(df[X]<0)&(df.spot_opening_gap<0),
           'down_and_gap_up':(df[X]<0)&(df.spot_opening_gap>0),
           'up_and_gap_up':(df[X]>0)&(df.spot_opening_gap>0),
           'up_and_gap_down':(df[X]>0)&(df.spot_opening_gap<0)}
    rows=[summarize(df[m],name) for name,m in masks.items()]
    baseline=rows[0]['spot_opening_gap_negative_probability']
    for row in rows:
        row['negative_gap_probability_minus_unconditional']=row['spot_opening_gap_negative_probability']-baseline
        row['continuation_probability']=row['spot_intraday_return_negative_probability'] if row['scenario'].startswith('down') else np.nan
        row['reversal_probability']=row['spot_intraday_return_positive_probability'] if row['scenario'].startswith('down') else np.nan
    bins=historical_bins(df[X],cfg['quantile_history'])
    binrows=[summarize(df[bins==i],str(i)) for i in range(7)]
    return pd.DataFrame(rows),pd.DataFrame(binrows)
