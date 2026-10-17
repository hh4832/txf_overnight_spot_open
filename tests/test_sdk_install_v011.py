import hashlib
from types import SimpleNamespace
import pytest
import src.sdk_install as sdk

def test_installed_skips_network():
    assert sdk.ensure_fubon_sdk(version_getter=lambda n:'2.4.0',
       importer=lambda n:SimpleNamespace(FubonSDK=object))=='2.4.0'

def test_wrong_sha_cannot_install(monkeypatch):
    monkeypatch.setattr(sdk,'SDK_BYTES',1)
    actions=[]
    def download(service,path): path.write_bytes(b'x')
    with pytest.raises(RuntimeError,match='SDK_WHEEL_SHA256_MISMATCH'):
        sdk.ensure_fubon_sdk(service=object(),downloader=download,
            runner=lambda *a,**kw:actions.append(1),
            version_getter=lambda n:'2.2.8')
    assert actions==[]
