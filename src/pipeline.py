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
    try:
        if cfg['mode']=='smoke':
            from .synthetic import generate
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
            spot=cache.get('finlab_0050',dict(start=cfg['start'],end=end,keys='adj_open_adj_close_raw_verify'),
                           lambda:fetch_finlab(cfg['start'],end))
            if rest is None:
                sdk=login_fubon();rest=sdk.marketdata.rest_client.futopt
            partitions=[]
            for start in pd.date_range(cfg['start'],end,freq='7D'):
                stop=min(start+pd.Timedelta(days=6),pd.Timestamp(end))
                params=dict(start=start.strftime('%Y-%m-%d'),end=stop.strftime('%Y-%m-%d'),
                            product='TXF',contractMonth='1!',timeframe='1')
                partitions.append(cache.get('fubon_txf',params,lambda p=params:fetch_fubon(rest,p['start'],p['end'],cfg['request_spacing_seconds'])))
            bars=pd.concat(partitions,ignore_index=True)
        events=build(bars,spot,cfg)
        if events.empty: raise ValueError('No candidate events')
        for c in [X,*Y,'spot_total_return','txf_1330_to_0500','txf_1330_to_1345','txf_0500_to_0845','corporate_action_boundary']:
            if c not in events: events[c]=False if c=='corporate_action_boundary' else float('nan')
        valid=events[events.data_quality_status=='VALID'].copy()
        events.to_parquet(run_dir/'processed/event_dataset.parquet',index=False)
        info.update(n_candidates=len(events),n_valid=len(valid),exclusions=events.exclusion_reason.value_counts().to_dict())
        if valid.empty: raise ValueError('No valid events; research blocked')
        prob,bins=conditional(valid,cfg);annual,robust=analyze(valid,cfg);pred=oos(valid,cfg)
        tables={'descriptive_statistics':valid[[X,*Y,'spot_total_return']].describe().reset_index(),
                'gap_regression':pd.DataFrame([regression(valid,Y[0],cfg)]),
                'intraday_regression':pd.DataFrame([regression(valid,Y[1],cfg)]),
                'conditional_probability':prob,'conditional_bins':bins,'annual_stability':annual,
                'out_of_sample_results':pred,'out_of_sample_scores':oos_scores(pred),'robustness_summary':robust}
        info.update(status='SMOKE_COMPLETE' if cfg['mode']=='smoke' else 'LIVE_FRAMEWORK_RUN_COMPLETE',
                    research_decision='INCONCLUSIVE' if len(valid)>=cfg['min_observations'] and cfg['mode']!='smoke' else 'DATA_INSUFFICIENT',
                    n_candidates=len(events),n_valid=len(valid),exclusions=events.exclusion_reason.value_counts().to_dict(),
                    coverage={'futures_first':str(bars.timestamp.min()),'futures_last':str(bars.timestamp.max()),
                              'spot_first':spot.date.min(),'spot_last':spot.date.max()})
        write(run_dir,events,tables,info)
    except Exception as exc:
        info.update(status='FAILED',error_type=type(exc).__name__,research_decision='DATA_INSUFFICIENT')
        (run_dir/'diagnostics/diagnostics.md').write_text('Execution failed. No research conclusion. Error type: '+type(exc).__name__)
        raise RuntimeError(f'Research failed; sanitized diagnostics: {run_dir}') from None
    finally:
        (run_dir/'raw_manifest/manifest.json').write_text(json.dumps(cache.manifest,indent=2))
        (run_dir/'run_info.json').write_text(json.dumps(info,indent=2,ensure_ascii=False,default=str))
    return run_dir


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='configs/research.yaml');p.add_argument('--mode',choices=['smoke','pilot','full']);p.add_argument('--output',default='outputs')
    args=p.parse_args();print(run(load(args.config,mode=args.mode),args.output))

if __name__=='__main__': main()
