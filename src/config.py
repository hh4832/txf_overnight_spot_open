from pathlib import Path
import yaml
import pandas as pd


def load(path='configs/research.yaml', **overrides):
    cfg = yaml.safe_load(Path(path).read_text())
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    if cfg['mode'] not in {'smoke', 'pilot', 'full'}:
        raise ValueError('Unknown mode')
    start, end = pd.Timestamp(cfg['start']), pd.Timestamp(cfg['end'])
    if start > end:
        raise ValueError('Invalid date range')
    if cfg['mode'] == 'pilot' and (end-start).days > 14:
        raise ValueError('Pilot limited to 14 calendar days')
    if cfg['mode'] == 'full' and not cfg['confirm_full']:
        raise ValueError('Full download requires confirm_full=true')
    if cfg['request_spacing_seconds'] < 0:
        raise ValueError('Invalid rate limit')
    return cfg
