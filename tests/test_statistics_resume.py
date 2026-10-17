"""Statistics-resume regressions; all price fixtures are synthetic, NEVER live."""
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import load
from src.synthetic import generate
from src.build_event_dataset import build
from src.robustness import analyze, strict_boolean_mask
from src.research_statistics import build_tables
from src.resume_statistics import _validate_source, resume

SOURCE_SHA = '89ab18d248dbb5a66b75f950973a8fca43cbd74e'


def fake_archived_source(tmp_path, corrupt=False):
    """Mimic archive layout ONLY; fixture values are generated synthetic bars."""
    bars, spot=generate()
    first, last = spot.date.iloc[0],spot.date.iloc[80]
    cfg=load(mode='full',confirm_full=True,start=first,end=last)
    cfg.update(min_observations=5,initial_train=20,quantile_history=20)
    events=build(bars,spot,cfg)
    valid=events.loc[events.data_quality_status=='VALID']
    assert len(valid)>30
    source=tmp_path/'source'/'20261017_222715_89ab18d248_023e11'
    for sub in ('processed','config','raw_manifest'):
        (source/sub).mkdir(parents=True)
    (source/'processed/event_dataset.parquet').parent.mkdir(exist_ok=True)
    if corrupt:
        # Parquet can serialize string pseudo-booleans; do not coerce these
        # back to booleans while reconstructing a failed research run.
        events['corporate_action_boundary']=events['corporate_action_boundary'].map(
            lambda value: 'True' if value is True or
            isinstance(value, np.bool_) and value else 'False')
    else:
        # Mirrors real parquet's mixed object flag type without altering truth.
        for field in ('corporate_action_boundary','weekend_flag','holiday_gap_flag'):
            events[field]=events[field].astype(object)
    events.to_parquet(source/'processed/event_dataset.parquet',index=False)
    info=dict(
        git_sha=SOURCE_SHA,status='FAILED',error_stage='STATISTICS',
        execution_timestamp='20261017_222715',
        data_label='LIVE_DATA',config=cfg,n_candidates=len(events),
        n_valid=int((events.data_quality_status=='VALID').sum()))
    (source/'run_info.json').write_text(json.dumps(info))
    (source/'config/research.json').write_text(json.dumps(cfg))
    (source/'raw_manifest/manifest.json').write_text(json.dumps([
        {'provider':'fubon_txf','sha256':'a'*64,'params':{'start':first}},
        {'provider':'finlab_0050','sha256':'b'*64}]))
    return source,events,cfg


def test_strict_flags_accept_real_object_boolean_and_filter_correctly():
    bars,spot=generate()
    cfg=load(start=spot.date.iloc[0],end=spot.date.iloc[80])
    valid=build(bars,spot,cfg)
    valid=valid.loc[valid.data_quality_status=='VALID'].copy()
    assert len(valid)>30
    valid['corporate_action_boundary']=pd.Series(
        [False]*(len(valid)-1)+[True],index=valid.index,dtype=object)
    valid['weekend_flag']=valid.weekend_flag.astype(object)
    valid['holiday_gap_flag']=valid.holiday_gap_flag.astype(object)
    mask=strict_boolean_mask(valid,'corporate_action_boundary')
    assert mask.dtype==bool
    assert (~mask).sum()==len(mask)-1
    annual,robust=analyze(valid,cfg)
    full=robust.loc[(robust.sensitivity=='all')&(robust.outcome=='spot_opening_gap')].iloc[0]
    dropped=robust.loc[(robust.sensitivity=='exclude_corporate_action')&
                       (robust.outcome=='spot_opening_gap')].iloc[0]
    assert int(full.n)-int(dropped.n)==1
    assert not annual.empty


@pytest.mark.parametrize('bad',[None,np.nan,1,0,'False','True'])
def test_strict_flags_reject_null_numeric_or_string(bad):
    frame=pd.DataFrame({'corporate_action_boundary':pd.Series([False,bad],dtype=object)})
    with pytest.raises(ValueError,match='Invalid boolean'):
        strict_boolean_mask(frame,'corporate_action_boundary')


def test_research_tables_match_original_predeclared_semantics():
    bars,spot=generate()
    cfg=load(start=spot.date.iloc[0],end=spot.date.iloc[60])
    events=build(bars,spot,cfg)
    valid=events.loc[events.data_quality_status=='VALID'].copy()
    valid['corporate_action_boundary']=valid.corporate_action_boundary.astype(object)
    a=build_tables(valid,cfg)
    assert {'gap_regression','intraday_regression','out_of_sample_scores',
            'annual_stability','robustness_summary','trading_reference',
            'trading_reference_by_year','trading_reference_holdout'}.issubset(a)
    assert a['trading_reference'].scenario.tolist()==[
        '<-1%','[-1%,-0.5%)','[-0.5%,0%)','[0%,0.5%)','[0.5%,1%)','>=1%']
    assert len(a['robustness_summary'])>0


def test_resume_writes_new_archive_without_touching_original(tmp_path,monkeypatch):
    source,original,cfg=fake_archived_source(tmp_path)
    before={p.relative_to(source).as_posix():p.read_bytes()
            for p in source.rglob('*') if p.is_file()}
    # CI checkout is shallow by default; simulate the separate, explicit
    # ancestry verification, while a real Colab checkout executes Git.
    import src.resume_statistics as runner
    real_run=runner.subprocess.run
    def git_ancestry_check(args,*a,**kw):
        if args[:3]==['git','merge-base','--is-ancestor']:
            return type('Result',(),{'returncode':0})()
        return real_run(args,*a,**kw)
    monkeypatch.setattr(runner.subprocess,'run',git_ancestry_check)
    output=tmp_path/'destination'
    first=resume(source,output,expected_source_sha=SOURCE_SHA)
    second=resume(source,output,expected_source_sha=SOURCE_SHA)
    assert first!=second
    assert before=={p.relative_to(source).as_posix():p.read_bytes()
                    for p in source.rglob('*') if p.is_file()}
    info=json.loads((first/'run_info.json').read_text())
    assert info['status']=='STATISTICS_ONLY_RESUME_COMPLETE'
    assert info['n_candidates']==len(original)
    assert info['n_valid'] == int((original.data_quality_status=='VALID').sum())
    assert info['resume_provenance']['source_git_sha']==SOURCE_SHA
    assert info['resume_provenance']['original_price_and_clock_QA_reexecuted'] is False
    assert info['live_data_validation']=='SOURCE_EVENT_QA_NOT_REEXECUTED'
    assert (first/'reports/summary.xlsx').is_file()
    assert (first/'reports/resume_provenance.md').is_file()
    assert (first/'tables/robustness_summary.csv').is_file()
    assert len(list((first/'figures').glob('*.png')))==5
    assert (first/'raw_manifest/source_event_dataset.parquet').read_bytes() == (
        source/'processed/event_dataset.parquet').read_bytes()
    frame=pd.read_parquet(first/'processed/event_dataset.parquet')
    pd.testing.assert_frame_equal(frame,original,check_dtype=False)


def test_source_commit_mismatch_is_fatal(tmp_path):
    source,_,_=fake_archived_source(tmp_path)
    with pytest.raises(ValueError,match='Source Git commit'):
        _validate_source(source,'0'*40)


def test_invalid_boolean_replay_is_blocked_before_output(tmp_path):
    source,_,_=fake_archived_source(tmp_path,corrupt=True)
    with pytest.raises(ValueError,match='Invalid boolean'):
        resume(source,tmp_path/'resume')


def test_source_counts_tamper_blocked_before_output(tmp_path):
    source,_,_=fake_archived_source(tmp_path)
    info=json.loads((source/'run_info.json').read_text())
    info['n_valid']+=1
    (source/'run_info.json').write_text(json.dumps(info))
    with pytest.raises(ValueError,match='counts mismatch'):
        resume(source,tmp_path/'resume')


def test_source_parquet_missing_blocks_without_provider_calls(tmp_path):
    source,_,_=fake_archived_source(tmp_path)
    (source/'processed/event_dataset.parquet').unlink()
    with pytest.raises(ValueError,match='missing required'):
        resume(source,tmp_path/'resume')


def test_source_config_divergence_blocks(tmp_path):
    source,_,_=fake_archived_source(tmp_path)
    cfg=json.loads((source/'config/research.json').read_text())
    cfg['hac_lags']=777
    (source/'config/research.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='not a matching'):
        resume(source,tmp_path/'resume')
