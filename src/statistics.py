import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import pearsonr, spearmanr

X = 'txf_overnight_return'
Y = ['spot_opening_gap','spot_intraday_return']


def regression(df, outcome, cfg, predictors=None):
    predictors = predictors or [X]
    f = df[predictors+[outcome]].replace([np.inf,-np.inf],np.nan).dropna()
    base = dict(outcome=outcome, predictors='+'.join(predictors), n=len(f), status='INSUFFICIENT_OBSERVATIONS')
    if len(f) < cfg['min_observations'] or any(f[c].std()==0 for c in predictors):
        return base
    design = sm.add_constant(f[predictors],has_constant='add')
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return {**base,'status':'SINGULAR_DESIGN'}
    fit = sm.OLS(f[outcome],design).fit(cov_type='HAC',cov_kwds={'maxlags':cfg['hac_lags']})
    lo,hi=fit.conf_int().loc[predictors[0]]
    return {**base,'status':'OK','alpha':fit.params['const'],'beta':fit.params[predictors[0]],
            'hac_se':fit.bse[predictors[0]],'ci_low':lo,'ci_high':hi,'p_value':fit.pvalues[predictors[0]],
            'r_squared':fit.rsquared,'pearson':pearsonr(f[predictors[0]],f[outcome]).statistic,
            'spearman':spearmanr(f[predictors[0]],f[outcome]).statistic,
            'effect_per_1pct_overnight':fit.params[predictors[0]]*.01}


def oos(df,cfg):
    f=df.sort_values('signal_trade_date').reset_index(drop=True)
    rows=[]
    for y in Y:
        for i in range(cfg['initial_train'],len(f)):
            train=f.iloc[:i]
            if train[X].std()==0: continue
            fit=sm.OLS(train[y],sm.add_constant(train[[X]],has_constant='add')).fit()
            pred=fit.params['const']+fit.params[X]*f.loc[i,X]
            rows.append(dict(outcome=y,test_date=f.loc[i,'signal_trade_date'],
                             train_last_date=train.iloc[-1].signal_trade_date,
                             train_n=i,actual=f.loc[i,y],prediction=pred,baseline=train[y].mean()))
    return pd.DataFrame(rows,columns=['outcome','test_date','train_last_date','train_n','actual','prediction','baseline'])


def oos_scores(predictions):
    rows=[]
    for y,f in predictions.groupby('outcome'):
        denom=((f.actual-f.baseline)**2).sum()
        rows.append(dict(outcome=y,n=len(f),oos_r_squared=1-((f.actual-f.prediction)**2).sum()/denom if denom>0 else np.nan))
    return pd.DataFrame(rows,columns=['outcome','n','oos_r_squared'])
