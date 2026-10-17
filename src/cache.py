import hashlib
import json
from pathlib import Path
import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Cache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = []

    def get(self, provider, params, fetch):
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = self.root / provider / f'{key}.parquet'
        meta = path.with_suffix('.json')
        hit = path.exists()
        if hit:
            if not meta.exists():
                raise ValueError('Cache integrity failure')
            metadata = json.loads(meta.read_text())
            if metadata['sha256'] != digest(path):
                raise ValueError('Cache integrity failure')
            df = pd.read_parquet(path)
        else:
            df = fetch()
            if df.empty:
                raise ValueError('Empty provider response; not cached')
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
            metadata = {'sha256': digest(path), 'params': params}
            if provider == 'fubon_txf' and df.attrs.get('fubon_duplicate_audit'):
                metadata['fubon_duplicate_audit'] = df.attrs['fubon_duplicate_audit']
            meta.write_text(json.dumps(metadata))
        item = {'provider': provider, 'params': params, 'sha256': digest(path),
                'rows': len(df), 'cache_hit': hit}
        if provider == 'fubon_txf':
            # Old immutable partitions cannot reconstruct vendor RAW response
            # counts from normalized candles. Explicitly preserve uncertainty.
            item['fubon_duplicate_audit'] = metadata.get('fubon_duplicate_audit', {
                'raw_rows': None, 'stored_rows': len(df),
                'within_fetch_duplicates_removed': None,
                'duplicated_timestamp_groups': None,
                'status': 'NOT_RECORDED_LEGACY_CACHE',
            })
        self.manifest.append(item)
        return df
