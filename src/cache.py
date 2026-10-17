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
            if not meta.exists() or json.loads(meta.read_text())['sha256'] != digest(path):
                raise ValueError('Cache integrity failure')
            df = pd.read_parquet(path)
        else:
            df = fetch()
            if df.empty:
                raise ValueError('Empty provider response; not cached')
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
            meta.write_text(json.dumps({'sha256': digest(path), 'params': params}))
        self.manifest.append({'provider': provider, 'params': params, 'sha256': digest(path),
                              'rows': len(df), 'cache_hit': hit})
        return df
