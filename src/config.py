from pathlib import Path
import yaml
import pandas as pd


def load(path='configs/research.yaml', **overrides):
    cfg = yaml.safe_load(Path(path).read_text())
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    if cfg['mode'] not in {'smoke', 'pilot', 'validation', 'full'}:
        raise ValueError('Unknown mode')
    start, end = pd.Timestamp(cfg['start']), pd.Timestamp(cfg['end'])
    if start > end:
        raise ValueError('Invalid date range')
    if cfg['mode'] == 'pilot' and (end-start).days > 14:
        raise ValueError('Pilot limited to 14 calendar days')
    if cfg['mode'] == 'validation' and (end-start).days > cfg.get('validation_max_calendar_days', 100):
        raise ValueError('Validation limited to configured calendar-day window')
    if cfg['mode'] == 'full' and not cfg['confirm_full']:
        raise ValueError('Full download requires confirm_full=true')
    if cfg.get('boundary_semantics_verified', False):
        evidence = str(cfg.get('boundary_evidence_reference', '')).strip()
        if not (evidence.startswith('https://') and len(evidence) > 16):
            raise ValueError('Boundary marker verification requires reviewed HTTPS evidence')
    if cfg.get('close_policy','adaptive') not in ('adaptive','strict'):
        raise ValueError('close_policy must be adaptive or strict')
    overrides=cfg.get('expiry_date_overrides') or {}
    if not isinstance(overrides,dict) or any(
            len(str(m))!=6 or not str(m).isdigit() or
            pd.isna(pd.to_datetime(v,errors='coerce'))
            for m,v in overrides.items()):
        raise ValueError('Invalid expiry date overrides')
    if cfg['request_spacing_seconds'] < 0:
        raise ValueError('Invalid rate limit')
    return cfg
