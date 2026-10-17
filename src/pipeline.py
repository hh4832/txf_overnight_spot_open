import argparse
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import uuid
import pandas as pd
from .config import load
from .cache import Cache,digest
from .build_event_dataset import build
from .statistics import regression,oos,oos_scores,X,Y
from .conditional_analysis import conditional
from .robustness import analyze
from .trading_reference import trading_reference
from .reporting import write


def run(cfg,root='outputs',cache_root=None,rest=None):
    root=Path(root)
    try: sha=subprocess.check_output(['git','rev-parse','HEAD'],stderr=subprocess.DEVNULL,text=True).strip()
    except subprocess.CalledProcessError: sha='UNCOMMITTED'
    stamp=datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y%m%d_%H%M%S')
    run_dir=root/'runs'/f'{stamp}_{sha[:10]}_{uuid.uuid4().hex[:6]}'
    for sub in ['config','raw_manifest','processed','diagnostics','tables','figures','reports']:
        (run_dir/sub).mkdir(parents=True,exist_ok=False)
    info=dict(git_sha=sha,python=platform.python_version(),config=cfg,execution_timestamp=stamp,
              status='RUNNING',framework_status='FRAMEWORK_COMPLETE',live_data_validation='LIVE_DATA_VALIDATION_PENDING',data_label='SYNTHETIC_SMOKE_ONLY' if cfg['mode']=='smoke' else 'LIVE_DATA',
              research_decision='DATA_INSUFFICIENT',packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()})
    (run_dir/'config/research.json').write_text(json.dumps(cfg,indent=2))
    cache=Cache(cache_root or root/'cache')
    stage='INIT'
    current_partition=None
    data_provider=None
    try:
        if cfg['mode']=='smoke':
            from .synthetic import generate
            stage='SYNTHETIC_GENERATION'
            bars,spot=generate()
            cfg={**cfg,'start':spot.date.min(),'end':spot.date.iloc[-2]}
            info['effective_synthetic_range']=[cfg['start'],cfg['end']]
            for name,frame in [('synthetic_bars',bars),('synthetic_spot',spot)]:
                p=run_dir/f'raw_manifest/{name}.parquet';frame.to_parquet(p,index=False)
                cache.manifest.append({'provider':'SYNTHETIC','sha256':digest(p),'rows':len(frame)})
        else:
            from .fetch_fubon import fetch as fetch_fubon
            from .fetch_finlab import fetch as fetch_finlab
            from .credentials import login_fubon
            # Include next sessions for outcome/calendar boundary; never infer a day by weekday.
            now = pd.Timestamp.now(tz='Asia/Taipei')
            last_complete = now.normalize().tz_localize(None) - pd.Timedelta(days=1 if now.hour < 14 else 0)
            end=min(pd.Timestamp(cfg['end'])+pd.Timedelta(days=14), last_complete).strftime('%Y-%m-%d')
            stage='FINLAB_FETCH'
            data_provider='finlab_0050'
            spot=cache.get('finlab_0050',dict(start=cfg['start'],end=end,keys='adj_open_adj_close_raw_verify_v2'),
                           lambda:fetch_finlab(cfg['start'],end))
            # Preserve all-source-missing dates as an explicit diagnostic, NOT
            # as exchange-confirmed holidays or valid 0050 trading sessions.
            # The normalized data is cached *before* excluding these rows.
            missing_flag=(spot['fully_missing_0050'].fillna(False).astype(bool)
                          if 'fully_missing_0050' in spot
                          else pd.Series(False,index=spot.index))
            missing_dates=spot.loc[missing_flag,['date']].copy()
            missing_dates['reason']='ALL_FOUR_FINLAB_0050_PRICE_FIELDS_MISSING'
            missing_dates['calendar_interpretation']='UNKNOWN_HOLIDAY_OR_PROVIDER_OMISSION'
            missing_dates.to_csv(run_dir/'diagnostics/finlab_missing_dates.csv',index=False)
            info['finlab_0050_fully_missing_count']=len(missing_dates)
            info['finlab_0050_fully_missing_dates']=missing_dates['date'].tolist()
            spot=spot.loc[~missing_flag].copy()
            if spot.empty:
                raise ValueError('No fully observed 0050 prices remain')
            stage='FUBON_LOGIN'
            data_provider='fubon_txf'
            if rest is None:
                sdk=login_fubon();rest=sdk.marketdata.rest_client.futopt
            partitions=[]
            for start in pd.date_range(cfg['start'],end,freq='7D'):
                stop=min(start+pd.Timedelta(days=6),pd.Timestamp(end))
                params=dict(start=start.strftime('%Y-%m-%d'),end=stop.strftime('%Y-%m-%d'),
                            product='TXF',contractMonth='1!',timeframe='1')
                stage='FUBON_FETCH'
                current_partition=params['start']+'..'+params['end']
                partitions.append(cache.get('fubon_txf',params,lambda p=params:fetch_fubon(rest,p['start'],p['end'],cfg['request_spacing_seconds'])))
            bars=pd.concat(partitions,ignore_index=True)
        stage='SESSION_VALIDATION'
        current_partition=None
        events,qa=build(bars,spot,cfg,return_diagnostics=True)
        qa.to_csv(run_dir/'diagnostics/session_anomalies.csv',index=False)
        info['session_anomalies_total']=len(qa)
        info['session_anomalies_in_range']=int(qa.affects_research_event.sum()) if len(qa) else 0
        if events.empty:
            if cfg['mode'] != 'validation':
                raise ValueError('No candidate events')
            events = pd.DataFrame(columns=[
                'signal_trade_date', 'next_spot_trade_date',
                'data_quality_status', 'exclusion_reason', 'rollover_flag',
                'weekend_flag', 'holiday_gap_flag'])
        for c in [X,*Y,'spot_total_return','txf_1330_to_0500','txf_1330_to_1345','txf_0500_to_0845','corporate_action_boundary']:
            if c not in events: events[c]=False if c=='corporate_action_boundary' else float('nan')
        valid=events[events.data_quality_status=='VALID'].copy()
        events.to_parquet(run_dir/'processed/event_dataset.parquet',index=False)
        info.update(n_candidates=len(events),n_valid=len(valid),exclusions=events.exclusion_reason.value_counts().to_dict())
        if cfg['mode'] == 'validation':
            from .quality_audit import write_quality_report
            stage='DATA_QUALITY_AUDIT'
            qa_status, _audit_tables = write_quality_report(
                run_dir, events, qa, bars, spot, cfg, info)
            info.update(
                qa_status=qa_status,
                n_excluded=len(events)-len(valid),
                research_decision='NOT_EVALUATED',
                live_data_validation=(
                    'VALIDATION_QA_COMPLETE' if qa_status == 'PASS' else
                    'VALIDATION_REVIEW_REQUIRED'),
                status=(
                    'DATA_QUALITY_VALIDATED' if qa_status == 'PASS' else
                    'DATA_QUALITY_REVIEW_REQUIRED'),
                coverage={'futures_first':str(bars.timestamp.min()),
                          'futures_last':str(bars.timestamp.max()),
                          'spot_first':str(spot.date.min()),
                          'spot_last':str(spot.date.max())})
            if qa_status == 'BLOCKED':
                raise ValueError('Price or timing audit mismatch')
        else:
            if valid.empty: raise ValueError('No valid events; research blocked')
            stage='STATISTICS'
            prob,bins=conditional(valid,cfg);annual,robust=analyze(valid,cfg);pred=oos(valid,cfg)
            tables={'descriptive_statistics':valid[[X,*Y,'spot_total_return']].describe().reset_index(),
                    'gap_regression':pd.DataFrame([regression(valid,Y[0],cfg)]),
                    'intraday_regression':pd.DataFrame([regression(valid,Y[1],cfg)]),
                    'conditional_probability':prob,'conditional_bins':bins,'annual_stability':annual,
                    'out_of_sample_results':pred,'out_of_sample_scores':oos_scores(pred),'robustness_summary':robust}
            tables.update(trading_reference(valid,cfg))
            info.update(status=('SMOKE_COMPLETE' if cfg['mode']=='smoke' else
                                'DATA_PIPELINE_VALIDATED' if cfg['mode']=='pilot' else
                                'LIVE_FRAMEWORK_RUN_COMPLETE'),
                        live_data_validation=('PILOT_VALIDATED' if cfg['mode']=='pilot' else
                                              'LIVE_DATA_VALIDATION_PENDING'),
                        research_decision='INCONCLUSIVE' if len(valid)>=cfg['min_observations'] and cfg['mode']!='smoke' else 'DATA_INSUFFICIENT',
                        n_candidates=len(events),n_valid=len(valid),exclusions=events.exclusion_reason.value_counts().to_dict(),
                        coverage={'futures_first':str(bars.timestamp.min()),'futures_last':str(bars.timestamp.max()),
                                  'spot_first':spot.date.min(),'spot_last':spot.date.max()})
            stage='REPORT_GENERATION'
            write(run_dir,events,tables,info)
    except Exception as exc:
        code=stage+'_'+type(exc).__name__.upper()
        info.update(status='FAILED',error_stage=stage,error_code=code,
                    error_type=type(exc).__name__,
                    safe_error_message='Research stopped at '+stage+'; see data QA or provider access.',
                    data_provider=data_provider,current_partition=current_partition,
                    research_decision='NOT_EVALUATED' if cfg['mode']=='validation' else 'DATA_INSUFFICIENT')
        (run_dir/'diagnostics/diagnostics.md').write_text(
            '# FAILED (no research conclusion)\n\n'
            'Stage: '+stage+'\nError code: '+code+'\n'
            'Exception type: '+type(exc).__name__+'\n'
            'Provider: '+str(data_provider)+'\nPartition: '+str(current_partition)+'\n'
            'Original exception text suppressed to protect credentials.\n')
        raise RuntimeError(f'Research failed; sanitized diagnostics: {run_dir}') from None
    finally:
        (run_dir/'raw_manifest/manifest.json').write_text(json.dumps(cache.manifest,indent=2))
        (run_dir/'run_info.json').write_text(json.dumps(info,indent=2,ensure_ascii=False,default=str))
    return run_dir


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='configs/research.yaml');p.add_argument('--mode',choices=['smoke','pilot','validation','full']);p.add_argument('--output',default='outputs')
    args=p.parse_args();print(run(load(args.config,mode=args.mode),args.output))

if __name__=='__main__': main()
