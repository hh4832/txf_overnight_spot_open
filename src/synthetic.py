"""Deterministic fabricated fixtures ONLY. Never evidence about markets."""
import numpy as np
import pandas as pd


def generate():
    rng=np.random.default_rng(20261017)
    dates=pd.bdate_range('2022-01-03',periods=600)
    spot=[];bars=[];prev=100.
    for i,dt in enumerate(dates):
        op=prev*(1+rng.normal(0,.008));cl=op*(1+rng.normal(0,.009))
        spot.append(dict(date=dt.strftime('%Y-%m-%d'),open=op,close=cl,adjustment_verified=True,corporate_action_boundary=False))
        prev=cl
        price=15000+rng.normal(0,100)
        x=rng.normal(0,.009)
        for stamp,session,value in [(dt+pd.Timedelta(hours=8,minutes=45),'regular',price*.999),
                  (dt+pd.Timedelta(hours=13,minutes=29),'regular',price*.998),
                  (dt+pd.Timedelta(hours=13,minutes=44),'regular',price),
                  (dt+pd.Timedelta(hours=15),'afterhours',price),
                  (dt+pd.Timedelta(days=1,hours=4,minutes=59),'afterhours',price*(1+x))]:
            bars.append(dict(timestamp=stamp.tz_localize('Asia/Taipei'),session=session,
                             contract_month='202212',open=value,high=value,low=value,close=value,volume=10))
    return pd.DataFrame(bars),pd.DataFrame(spot)
