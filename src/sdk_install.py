"""Private Drive-pinned Fubon Neo wheel bootstrap; no wheel or token in Git."""
import hashlib
import importlib
import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename
from packaging.version import Version

SDK_FILE_ID = '1zlSiNYhvhs82Pt6wB4nfSNCTco0UMzim'
SDK_FILENAME = ('fubon_neo-2.4.0-cp37-abi3-'
                'manylinux_2_17_x86_64.manylinux2014_x86_64.whl')
SDK_SHA256 = '065c636ea58e00db9fe67aa6ba0936b234ac131da0d4697e9c6f33dbe42bc1ba'
SDK_BYTES = 4975471
MIN_VERSION = Version('2.4.0')


def installed_version(version_getter=None, importer=None):
    version_getter = version_getter or importlib.metadata.version
    importer = importer or importlib.import_module
    try:
        found = Version(version_getter('fubon_neo'))
        if found < MIN_VERSION:
            return None
        sdk = importer('fubon_neo.sdk')
        if not hasattr(sdk, 'FubonSDK'):
            return None
        return found
    except (ImportError, AttributeError, importlib.metadata.PackageNotFoundError,
            ValueError):
        return None


def verify_wheel(path):
    path = Path(path)
    if path.name != SDK_FILENAME or not path.is_file():
        raise RuntimeError('SDK_WHEEL_NAME_OR_PATH_INVALID')
    if path.stat().st_size != SDK_BYTES:
        raise RuntimeError('SDK_WHEEL_SIZE_MISMATCH')
    if hashlib.sha256(path.read_bytes()).hexdigest() != SDK_SHA256:
        raise RuntimeError('SDK_WHEEL_SHA256_MISMATCH')
    name, version, _build, tags = parse_wheel_filename(path.name)
    if str(name).replace('-', '_') != 'fubon_neo' or version < MIN_VERSION:
        raise RuntimeError('SDK_WHEEL_PACKAGE_INVALID')
    if not tags.intersection(set(sys_tags())):
        raise RuntimeError('SDK_WHEEL_PLATFORM_INCOMPATIBLE')
    return path


def download_drive_wheel(service, destination):
    """Get the exact private Drive file using the already-authorized Colab client."""
    from googleapiclient.http import MediaIoBaseDownload
    import io
    destination = Path(destination)
    try:
        request = service.files().get_media(fileId=SDK_FILE_ID)
        with destination.open('wb') as target:
            downloader = MediaIoBaseDownload(target, request, chunksize=1024 * 1024)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
    except Exception:
        destination.unlink(missing_ok=True)
        raise RuntimeError('SDK_DRIVE_DOWNLOAD_UNAVAILABLE') from None
    return destination


def ensure_fubon_sdk(service=None, override='', version_getter=None,
                     importer=None, runner=None, downloader=None):
    """Return version; install only when missing. Overrides must match pinned hash."""
    version_getter = version_getter or importlib.metadata.version
    importer = importer or importlib.import_module
    found = installed_version(version_getter, importer)
    if found is not None:
        return str(found)
    runner = runner or subprocess.run
    downloader = downloader or download_drive_wheel
    with tempfile.TemporaryDirectory(prefix='txf_fubon_sdk_') as temp:
        if override:
            path = Path(override)
        else:
            if service is None:
                raise RuntimeError('SDK_AUTHENTICATED_DRIVE_REQUIRED')
            path = Path(temp) / SDK_FILENAME
            downloader(service, path)
        verify_wheel(path)
        try:
            runner([sys.executable, '-m', 'pip', 'install', '--no-input',
                    str(path)], check=True, capture_output=True, text=True)
        except Exception:
            raise RuntimeError('SDK_INSTALL_FAILED') from None
    importlib.invalidate_caches()
    found = installed_version(version_getter, importer)
    if found is None:
        raise RuntimeError('SDK_IMPORT_OR_VERSION_VALIDATION_FAILED')
    return str(found)
