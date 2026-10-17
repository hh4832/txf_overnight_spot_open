"""Statistics-only replay of an archived, failed *statistics-stage* live run.

Loads the original, immutable event dataset. Does not log into any provider,
change signal/outcome definitions, repeat raw-bar QA or overwrite prior runs.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .research_statistics import build_tables
from .robustness import strict_boolean_mask
from .statistics import X, Y
from .reporting import write


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_source(source, expected_source_sha=None):
    source = Path(source)
    info_path = source / 'run_info.json'
    cfg_path = source / 'config/research.json'
    events_path = source / 'processed/event_dataset.parquet'
    manifest_path = source / 'raw_manifest/manifest.json'
    for file in (info_path, cfg_path, events_path, manifest_path):
        if not file.is_file():
            raise ValueError('Statistics resume source missing required archive file')
    info = json.loads(info_path.read_text(encoding='utf-8'))
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    sha = info.get('git_sha', '')
    if (not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{40}', sha) or
            (expected_source_sha is not None and sha != expected_source_sha)):
        raise ValueError('Source Git commit missing or mismatched')
    if (not source.name.startswith(info.get('execution_timestamp', '')+'_'+sha[:10]+'_')
            or info.get('status') != 'FAILED'
            or info.get('error_stage') != 'STATISTICS'
            or info.get('data_label') != 'LIVE_DATA'
            or cfg.get('mode') not in ('full','pilot')
            or cfg != info.get('config')):
        raise ValueError('Source is not a matching failed live statistics run')
    if not isinstance(manifest, list) or not any(
            item.get('provider') == 'fubon_txf' and item.get('sha256')
            for item in manifest if isinstance(item, dict)):
        raise ValueError('Source raw provider manifest incomplete')
    events = pd.read_parquet(events_path)
    required = {'signal_trade_date','data_quality_status','exclusion_reason',
                'weekend_flag','holiday_gap_flag','corporate_action_boundary',
                'spot_total_return',X,*Y,'txf_1330_to_0500',
                'txf_1330_to_1345','txf_0500_to_0845',
                'txf_overnight_return_fixed','txf_adaptive_minus_fixed_bp',
                'day_close_rule','night_close_rule'}
    if not required.issubset(events.columns):
        raise ValueError('Source event schema incomplete')
    if events.empty or not events.signal_trade_date.is_unique:
        raise ValueError('Source event dates empty or duplicate')
    if (not events.signal_trade_date.is_monotonic_increasing or
            events.signal_trade_date.astype(str).str.len().ne(10).any() or
            not events.signal_trade_date.between(cfg['start'],cfg['end']).all()):
        raise ValueError('Source event dates invalid/outside original research period')
    if not events.data_quality_status.isin(['VALID','EXCLUDED']).all():
        raise ValueError('Source event quality status invalid')
    if events.exclusion_reason.isna().any():
        raise ValueError('Source exclusions not documented')
    nvalid = int(events.data_quality_status.eq('VALID').sum())
    if (len(events) != info.get('n_candidates') or nvalid != info.get('n_valid')
            or not nvalid or
            events.loc[events.data_quality_status.eq('VALID'),
                       'exclusion_reason'].ne('').any()):
        raise ValueError('Source candidate/valid/exclusion counts mismatch')
    valid = events.loc[events.data_quality_status.eq('VALID')].copy()
    for column in ('weekend_flag','holiday_gap_flag','corporate_action_boundary'):
        strict_boolean_mask(valid, column)
    for column in (X, *Y, 'spot_total_return'):
        vals = pd.to_numeric(valid[column], errors='raise').to_numpy(dtype=float)
        if not np.isfinite(vals).all():
            raise ValueError('Source VALID return is missing or nonfinite')
    if not np.allclose(
            (1+valid[Y[0]].to_numpy(dtype=float))*
            (1+valid[Y[1]].to_numpy(dtype=float)),
            1+valid['spot_total_return'].to_numpy(dtype=float),
            rtol=1e-9,atol=1e-10):
        raise ValueError('Source VALID return multiplicative identity failed')
    return info, cfg, events, {
        'event_dataset_sha256':_sha256(events_path),
        'run_info_sha256':_sha256(info_path),
        'config_sha256':_sha256(cfg_path),
        'raw_manifest_sha256':_sha256(manifest_path),
    }


def resume(source_run, output_root='outputs', expected_source_sha=None):
    """Create an entirely NEW archive. A failed prior run remains untouched."""
    source = Path(source_run).resolve()
    original, cfg, events, hashes = _validate_source(source, expected_source_sha)
    try:
        git_sha = subprocess.check_output(
            ['git','rev-parse','HEAD'],stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError,subprocess.CalledProcessError):
        raise ValueError('Statistics resume must execute from a Git checkout') from None
    if not re.fullmatch(r'[a-f0-9]{40}', git_sha):
        raise ValueError('Current Git SHA unavailable')
    # Ensure old source commit is part of the existing checked-out history.
    # Do not silently resume incompatible or unrelated historical datasets.
    ancestry = subprocess.run(
        ['git','merge-base','--is-ancestor',original['git_sha'],git_sha],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    if ancestry.returncode != 0:
        raise ValueError('Source Git SHA is not an ancestor of current Git checkout')
    stamp = datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y%m%d_%H%M%S')
    output_root = Path(output_root)
    run_dir = output_root/'runs'/f'{stamp}_{git_sha[:10]}_{uuid.uuid4().hex[:6]}'
    if source == run_dir.resolve():
        raise ValueError('Cannot overwrite source archive')
    for sub in ('config','raw_manifest','processed','diagnostics','tables','figures','reports'):
        (run_dir/sub).mkdir(parents=True,exist_ok=False)
    src_manifest = source/'raw_manifest/manifest.json'
    src_events = source/'processed/event_dataset.parquet'
    shutil.copyfile(src_manifest,run_dir/'raw_manifest/source_manifest.json')
    shutil.copyfile(src_events,run_dir/'raw_manifest/source_event_dataset.parquet')
    (run_dir/'config/research.json').write_text(
        json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    audit = {
        'run_type':'STATISTICS_ONLY_RESUME',
        'source_run_name':source.name,
        'source_git_sha':original['git_sha'],
        'resume_git_sha':git_sha,
        'source_status':original['status'],
        'source_error_stage':original['error_stage'],
        'original_price_and_clock_QA_reexecuted':False,
        **hashes,
    }
    (run_dir/'raw_manifest/manifest.json').write_text(json.dumps(
        [{'provider':'ARCHIVED_EVENT_DATASET','source_run':source.name,
          'source_git_sha':original['git_sha'],
          'sha256':hashes['event_dataset_sha256'],
          'rows':len(events),
          'source_manifest_sha256':hashes['raw_manifest_sha256']}],
        ensure_ascii=False,indent=2),encoding='utf-8')
    info = dict(
        git_sha=git_sha,
        config=cfg,
        execution_timestamp=stamp,
        python=platform.python_version(),
        packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
        status='RUNNING',
        data_label='LIVE_DATA',
        run_type='STATISTICS_ONLY_RESUME',
        live_data_validation='SOURCE_EVENT_QA_NOT_REEXECUTED',
        research_decision='NOT_EVALUATED',
        n_candidates=len(events),
        n_valid=int(events.data_quality_status.eq('VALID').sum()),
        exclusions=events.exclusion_reason.value_counts().to_dict(),
        resume_provenance=audit,
    )
    stage='STATISTICS'
    try:
        valid=events.loc[events.data_quality_status=='VALID'].copy()
        tables=build_tables(valid,cfg)
        info['status']='STATISTICS_ONLY_RESUME_COMPLETE'
        info['research_decision']=(
            'INCONCLUSIVE' if len(valid)>=cfg['min_observations'] else 'DATA_INSUFFICIENT')
        info['coverage']={
            'event_first':events.signal_trade_date.min(),
            'event_last':events.signal_trade_date.max(),
            'spot_and_Txf_QA':'NOT_REEXECUTED_FROM_SOURCE_BARS',
        }
        stage='REPORT_GENERATION'
        write(run_dir,events,tables,info)
        (run_dir/'reports/resume_provenance.md').write_text(
            '# Statistics-only replay provenance\n\n'
            f"Prior run: {source.name}\n\n"
            f"Source Git: {original['git_sha']}\n\n"
            f"Statistics Git: {git_sha}\n\n"
            f"Source event dataset SHA256: {hashes['event_dataset_sha256']}\n\n"
            f"Original source status: {original['status']}, {original['error_stage']}\n\n"
            "This run does not re-fetch vendor data or independently repeat"
            " TXF/0050 minute-bar, clock or contract QA. It uses the exact archived"
            " event dataset and original config, including previous exclusion decisions."
            " Statistics alone do not validate trading profitability.\n",
            encoding='utf-8')
    except Exception as exc:
        info.update(status='FAILED',error_stage=stage,
                    error_type=type(exc).__name__,
                    error_code=stage+'_'+type(exc).__name__.upper(),
                    research_decision='NOT_EVALUATED')
        (run_dir/'diagnostics/diagnostics.md').write_text(
            '# FAILED statistics-only resume\n\nStage: '+stage+
            '\nException type: '+type(exc).__name__+
            '\nOriginal exception text suppressed.\n',encoding='utf-8')
        raise RuntimeError(f'Statistics-only resume failed; sanitized diagnostics: {run_dir}') from None
    finally:
        (run_dir/'run_info.json').write_text(
            json.dumps(info,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return run_dir


def main():
    parser=argparse.ArgumentParser(description='Recompute statistics from an archived failed live run')
    parser.add_argument('--source-run',required=True)
    parser.add_argument('--output',default='outputs')
    parser.add_argument('--expected-source-sha',required=True)
    args=parser.parse_args()
    print(resume(args.source_run,args.output,args.expected_source_sha))


if __name__=='__main__':
    main()
