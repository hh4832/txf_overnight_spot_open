"""Integration tests: validation never reports H1/H2/H3 or runs inference."""
import json
import pandas as pd
import pytest

import src.pipeline as pipeline
import src.fetch_finlab as finlab
import src.fetch_fubon as fubon
from src.config import load
from src.synthetic import generate


def fixtures(monkeypatch):
    bars, spot = generate()
    start = spot.date.iloc[0]
    end = spot.date.iloc[6]

    def fake_finlab(_start, _end):
        return spot.iloc[:30].copy()

    def fake_fubon(_rest, day_from, day_to, spacing):
        dates = bars.timestamp.dt.strftime('%Y-%m-%d')
        return bars[(dates >= day_from) & (dates <= day_to)].copy()

    monkeypatch.setattr(finlab, 'fetch', fake_finlab)
    monkeypatch.setattr(fubon, 'fetch', fake_fubon)
    return {**load(), 'mode':'validation', 'start':start, 'end':end}


def test_config_validation_bounds():
    assert load(mode='validation',start='2026-07-01',end='2026-09-30')['mode']=='validation'
    with pytest.raises(ValueError, match='Validation limited'):
        load(mode='validation',start='2026-01-01',end='2026-09-30')
    with pytest.raises(ValueError, match='Pilot limited'):
        load(mode='pilot',start='2026-07-01',end='2026-09-30')
    with pytest.raises(ValueError, match='confirm_full'):
        load(mode='full',confirm_full=False)


def test_validation_skips_all_statistical_inference(tmp_path, monkeypatch):
    cfg = fixtures(monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError('VALIDATION MUST NOT RUN STATISTICS')

    for name in ('regression','oos','oos_scores','conditional','analyze'):
        monkeypatch.setattr(pipeline,name,forbidden)

    folder = pipeline.run(cfg, tmp_path, rest=object())
    info = json.loads((folder/'run_info.json').read_text())
    assert info['status'] == 'DATA_QUALITY_VALIDATED'
    assert info['qa_status'] == 'PASS'
    assert info['research_decision'] == 'NOT_EVALUATED'
    assert info['n_valid'] == 7
    assert (folder/'reports/data_quality_audit.md').exists()
    assert (folder/'tables/event_price_audit.csv').exists()
    assert (folder/'tables/daily_coverage.csv').exists()
    assert (folder/'tables/monthly_qa.csv').exists()
    assert (folder/'processed/event_dataset.parquet').exists()
    assert not (folder/'tables/gap_regression.csv').exists()
    assert not (folder/'tables/intraday_regression.csv').exists()
    assert not (folder/'tables/out_of_sample_scores.csv').exists()


def test_validation_uses_immutable_cached_partitions(tmp_path, monkeypatch):
    cfg=fixtures(monkeypatch)
    cache_root=tmp_path/'cache'
    out=tmp_path/'runs_staging'
    first=pipeline.run(cfg,out,cache_root=cache_root,rest=object())
    before={str(p):p.read_bytes() for p in cache_root.rglob('*.parquet')}
    def no_access(*args,**kwargs):
        raise AssertionError('Cached provider should not be requested')
    monkeypatch.setattr(finlab,'fetch',no_access)
    monkeypatch.setattr(fubon,'fetch',no_access)
    second=pipeline.run(cfg,out,cache_root=cache_root,rest=object())
    after={str(p):p.read_bytes() for p in cache_root.rglob('*.parquet')}
    assert first!=second
    assert before==after
    manifest=json.loads((second/'raw_manifest/manifest.json').read_text())
    assert manifest and all(part['cache_hit'] for part in manifest)


def test_validation_requires_review_for_out_of_scope_anomaly(tmp_path,monkeypatch):
    cfg=fixtures(monkeypatch)
    bars,spot=generate()
    extra=bars.iloc[0].copy()
    extra['timestamp']=pd.Timestamp(cfg['start']+' 13:45',tz='Asia/Taipei')
    original=fubon.fetch
    def response(rest,a,b,spacing):
        base=original(rest,a,b,spacing)
        if a <= cfg['start'] <= b:
            base=pd.concat([base,pd.DataFrame([extra])],ignore_index=True)
        return base
    monkeypatch.setattr(fubon,'fetch',response)
    folder=pipeline.run({**cfg,'close_policy':'strict'},tmp_path,rest=object())
    info=json.loads((folder/'run_info.json').read_text())
    assert info['status']=='DATA_QUALITY_REVIEW_REQUIRED'
    assert info['n_excluded']>=1
    assert info['qa_status']=='REVIEW_REQUIRED'


def test_no_candidate_days_are_review_not_success(tmp_path, monkeypatch):
    _ = fixtures(monkeypatch)
    cfg={**load(), 'mode':'validation',
         'start':'2022-01-08', 'end':'2022-01-09'}
    folder=pipeline.run(cfg,tmp_path,rest=object())
    info=json.loads((folder/'run_info.json').read_text())
    assert info['status']=='DATA_QUALITY_REVIEW_REQUIRED'
    assert info['qa_status']=='REVIEW_REQUIRED'
    assert info['n_candidates']==0
    assert (folder/'reports/data_quality_audit.md').exists()


def test_pipeline_audit_mismatch_is_failed_not_validated(tmp_path, monkeypatch):
    cfg=fixtures(monkeypatch)
    real_builder=pipeline.build
    def poisoned_builder(*args,**kwargs):
        events, qa=real_builder(*args,**kwargs)
        events.loc[events.index[0],'spot_opening_gap']+=0.1
        return events,qa
    monkeypatch.setattr(pipeline,'build',poisoned_builder)
    with pytest.raises(RuntimeError, match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    folder=next((tmp_path/'runs').iterdir())
    info=json.loads((folder/'run_info.json').read_text())
    assert info['status']=='FAILED'
    assert info['qa_status']=='BLOCKED'
    assert info['error_stage']=='DATA_QUALITY_AUDIT'
    assert info['research_decision']=='NOT_EVALUATED'
    assert (folder/'tables/event_price_audit.csv').exists()
    assert (folder/'reports/data_quality_audit.md').exists()
