import pandas as pd
from statsmodels.stats.multitest import multipletests
from .statistics import regression,X,Y


def analyze(df,cfg):
    annual=[]
    for year,f in df.groupby(df.signal_trade_date.str[:4]):
        annual.extend(dict(year=year,**regression(f,y,cfg)) for y in Y)
    prior_vol=df.spot_intraday_return.shift(1).rolling(20,min_periods=20).std()
    historical_median=prior_vol.shift(1).expanding(min_periods=20).median()
    selections={'all':df,'exclude_weekend_holiday':df[~(df.weekend_flag|df.holiday_gap_flag)],
                'exclude_corporate_action':df[~df.corporate_action_boundary],
                'negative_overnight':df[df[X]<0],'positive_overnight':df[df[X]>0],
                'exclude_extreme_5pct':df[df[X].abs()<=cfg['extreme_absolute_return']],
                'high_prior_vol':df[prior_vol>historical_median],
                'low_prior_vol':df[prior_vol<=historical_median]}
    rows=[]
    for label,f in selections.items():
        rows.extend(dict(sensitivity=label,**regression(f,y,cfg)) for y in Y)
    for y in Y:
        rows.append(dict(sensitivity='1330_baseline',**regression(df,y,cfg,['txf_1330_to_0500'])))
        rows.append(dict(sensitivity='0500_model_timing_control',**regression(df,y,cfg,[X,'txf_1330_to_1345'])))
        rows.append(dict(sensitivity='0845_model_secondary',**regression(df,y,cfg,[X,'txf_1330_to_1345','txf_0500_to_0845'])))
    result=pd.DataFrame(rows)
    if 'p_value' in result:
        valid=result.p_value.notna()
        result.loc[valid,'p_fdr_bh']=multipletests(result.loc[valid,'p_value'],method='fdr_bh')[1]
    return pd.DataFrame(annual),result
