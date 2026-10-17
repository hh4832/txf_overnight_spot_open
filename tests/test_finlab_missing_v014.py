"""FinLab multi-year aligned missing-date handling; synthetic QA only."""
import json
import numpy as np
import pandas as pd
import pytest

from src.fetch_finlab import normalize
from src.synthetic import generate
from src.config import load
from src.pipeline import run


def synthetic_four(n=15):
    ix=pd.bdate_range('2024-01-01',periods=n)
    raw_o=pd.Series(np.linspace(100,114,n),index=ix)
    raw_c=raw_o+1
    adj_o=raw_o*0.4
    adj_c=raw_c*0.4
    return [adj_o,adj_c,raw_o,raw_c]


def test_aligned_fully_missing_dates_preserved_as_flagged_diagnostics():
    series=synthetic_four(30)
    holes=[2,6,10,17,28]
    for s in series:
        s.iloc[holes]=np.nan
    df=normalize(*series)
    assert len(df)==30
    assert df.fully_missing_0050.sum()==5
    assert df.loc[holes,'fully_missing_0050'].all()
    assert (~df.loc[holes,'adjustment_verified']).all()
    assert df.loc[~df.fully_missing_0050,'adjustment_verified'].all()
    assert df.loc[~df.fully_missing_0050,['open','close']].notna().all().all()
    assert df.loc[holes,['open','close']].isna().all().all()
    assert df.loc[~df.fully_missing_0050,'corporate_action_boundary'].sum()==0


def test_missing_in_only_one_field_is_fatal():
    series=synthetic_four()
    series[0].iloc[3]=np.nan
    with pytest.raises(ValueError,match='Partial 0050'):
        normalize(*series)


def test_misaligned_raw_index_is_fatal():
    series=synthetic_four()
    series[2].index=series[2].index+pd.Timedelta(days=1)
    with pytest.raises(ValueError,match='index mismatch'):
        normalize(*series)


def test_true_factor_mismatch_is_still_fatal():
    series=synthetic_four()
    series[0].iloc[4]*=1.1
    with pytest.raises(ValueError,match='adjustment inconsistent'):
        normalize(*series)


def test_nonfinite_and_negative_actual_prices_remain_fatal():
    series=synthetic_four()
    series[0].iloc[4]=float('inf')
    with pytest.raises(ValueError,match='nonfinite'):
        normalize(*series)
    series=synthetic_four()
    series[2].iloc[4]=-1
    with pytest.raises(ValueError,match='Nonpositive'):
        normalize(*series)


def test_pipeline_records_missing_days_before_futures_fetch(tmp_path,monkeypatch):
    import src.fetch_finlab as provider
    import src.fetch_fubon as future
    bars,spot=generate()
    days=spot.date.iloc[:8].tolist()
    lost=days[3]
    selected=spot.iloc[:30].copy()
    selected['fully_missing_0050']=False
    selected.loc[selected.date==lost,['open','close']]=np.nan
    selected.loc[selected.date==lost,'adjustment_verified']=False
    selected.loc[selected.date==lost,'fully_missing_0050']=True
    monkeypatch.setattr(provider,'fetch',lambda _start,_end:selected.copy())
    def fubon_fake(_rest,a,b,spacing):
        dates=bars.timestamp.dt.strftime('%Y-%m-%d')
        return bars[(dates>=a)&(dates<=b)].copy()
    monkeypatch.setattr(future,'fetch',fubon_fake)
    config={**load(),'mode':'validation','start':days[0],'end':days[-1]}
    folder=run(config,tmp_path,rest=object())
    info=json.loads((folder/'run_info.json').read_text())
    missing=pd.read_csv(folder/'diagnostics/finlab_missing_dates.csv')
    events=pd.read_parquet(folder/'processed/event_dataset.parquet')
    assert info['finlab_0050_fully_missing_count']==1
    assert info['finlab_0050_fully_missing_dates']==[lost]
    assert missing.date.tolist()==[lost]
    assert missing.calendar_interpretation.iloc[0]=='UNKNOWN_HOLIDAY_OR_PROVIDER_OMISSION'
    assert not events.loc[events.signal_trade_date==lost,'data_quality_status'].eq('VALID').any()
    # Source hole must not be synthesized into a valid opening-gap observation.
    assert events.loc[events.signal_trade_date==lost,'exclusion_reason'].str.contains('NO_SPOT_SESSION_D').all()
