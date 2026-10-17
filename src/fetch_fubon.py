"""Official historical.candles API, checked 2026-10-17. No guessed endpoints."""
import time
import re
import pandas as pd


def normalize(response, session):
    if not isinstance(response, dict) or not isinstance(response.get('data'), list):
        raise ValueError('Fubon schema changed')
    df = pd.DataFrame(response['data'])
    required = {'date', 'contractMonth', 'open', 'high', 'low', 'close', 'volume'}
    if df.empty or not required.issubset(df):
        raise ValueError('Fubon empty response or missing fields')
    if not df.date.astype(str).str.contains(r'(?:Z|[+-]\d{2}:?\d{2})$', regex=True).all():
        raise ValueError('Naive timestamp unsupported')
    df['timestamp_raw'] = df.date.astype(str)
    df['timestamp'] = pd.to_datetime(df.date, utc=True, errors='raise').dt.tz_convert('Asia/Taipei')
    df['contract_month'] = df.contractMonth.astype(str)
    if not df.contract_month.map(lambda x: bool(re.fullmatch(r'\d{6}', x))).all():
        raise ValueError('Actual monthly contract identity unavailable')
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='raise')
    if df[['open','high','low','close','volume']].isna().any().any():
        raise ValueError('Missing OHLCV')
    if (df[['open','high','low','close']] <= 0).any().any() or (df.volume < 0).any():
        raise ValueError('Invalid OHLCV')
    if ((df.low > df[['open','close']].min(axis=1)) | (df.high < df[['open','close']].max(axis=1))).any():
        raise ValueError('OHLC ordering invalid')
    df['session'] = session
    if df.timestamp.duplicated().any():
        raise ValueError('Duplicate timestamp')
    return df.sort_values('timestamp').reset_index(drop=True)


def fetch(rest, start, end, spacing=1.1):
    """Weekly partitions; query dates are provider trading dates, NOT session start dates."""
    params = {'product': 'TXF', 'contractMonth': '1!', 'timeframe': '1',
              'from': start, 'to': end, 'sort': 'asc'}
    frames = []
    for session in ('regular', 'afterhours'):
        try:
            response = rest.historical.candles(**params, session=session)
        except Exception as exc:
            code = getattr(exc, 'status_code', None)
            raise RuntimeError(f'Fubon historical request failed; status={code if isinstance(code,int) else "unknown"}') from None
        finally:
            time.sleep(spacing)
        frames.append(normalize(response, session))
    return pd.concat(frames, ignore_index=True)
