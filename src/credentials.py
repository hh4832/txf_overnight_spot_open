import os
import contextlib
import io
from pathlib import Path


def secret(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'{name}: unavailable')
    return value


def login_fubon():
    try:
        from fubon_neo.sdk import FubonSDK
        values = [secret(n) for n in ('FUBON_PERSONAL_ID', 'FUBON_API_KEY',
                  'FUBON_CERT_PATH', 'FUBON_CERT_PASSWORD')]
        if not Path(values[2]).is_file():
            raise ValueError()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            sdk = FubonSDK()
            result = sdk.apikey_login(*values)
            if not result.is_success:
                raise ValueError()
            sdk.init_realtime()
        return sdk
    except Exception:
        raise RuntimeError('Fubon login failed; SDK/certificate/credentials require validation') from None
