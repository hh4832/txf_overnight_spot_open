"""No-network mocked Drive download tests for statistics-only replay."""
import re
from pathlib import Path

import pytest

import src.drive_io as drive_io


class Result:
    def __init__(self, data):
        self.data=data

    def execute(self):
        return self.data


class FakeDrive:
    def __init__(self, files):
        self.files_by_id=files
        self.calls=[]

    def files(self):
        return self

    def get(self, fileId, fields):
        self.calls.append(('get',fileId))
        return Result(self.files_by_id[fileId]['meta'])

    def list(self, q, pageSize, fields):
        self.calls.append(('list',q))
        match=re.fullmatch(
            r"'([A-Za-z0-9_-]+)' in parents and trashed = false and name = '([^']+)'",
            q)
        assert match
        parent,name=match.groups()
        matching=[record['meta'] for record in self.files_by_id.values()
                  if parent in record['meta'].get('parents',[])
                  and record['meta']['name']==name]
        return Result({'files':matching})

    def get_media(self,fileId):
        self.calls.append(('media',fileId))
        return self.files_by_id[fileId]['content']


class FakeDownloader:
    def __init__(self, stream, request):
        self.stream=stream
        self.request=request

    def next_chunk(self):
        self.stream.write(self.request)
        return None,True


def fake_archive(service_parent, source_parent=None):
    name='20261017_222715_89ab18d248_023e11'
    run_id='1ouocV-NPdL9-cH14ORbRpDTabCPVqSTc'
    files={}
    files[run_id]={'meta':dict(id=run_id,name=name,
        mimeType='application/vnd.google-apps.folder',
        parents=[source_parent or service_parent]),'content':None}
    for d in ('config','processed','raw_manifest'):
        path_id='folder_'+d
        files[path_id]={'meta':dict(id=path_id,name=d,
            mimeType='application/vnd.google-apps.folder',parents=[run_id]),'content':None}
    for fid,parent,name,payload,mime in (
        ('info',run_id,'run_info.json',b'{"status":"FAILED"}','application/json'),
        ('cfg','folder_config','research.json',b'{"mode":"full"}','application/json'),
        ('par','folder_processed','event_dataset.parquet',b'PAR1_SYNTHETIC','application/octet-stream'),
        ('raw','folder_raw_manifest','manifest.json',b'[]','application/json'),
    ):
        files[fid]={'meta':dict(id=fid,name=name,mimeType=mime,
                                 parents=[parent],size=str(len(payload))),
                    'content':payload}
    return FakeDrive(files),run_id


def test_download_four_files_by_verified_drive_id_without_overwrite(tmp_path,monkeypatch):
    import googleapiclient.http as http
    monkeypatch.setattr(http,'MediaIoBaseDownload',FakeDownloader)
    monkeypatch.setattr(drive_io,'validate_folder',lambda *args:None)
    service,run_id=fake_archive(drive_io.FOLDER)
    local=drive_io.download_statistics_resume_source(
        service,drive_io.FOLDER,run_id,tmp_path)
    assert (local/'run_info.json').read_bytes()==b'{"status":"FAILED"}'
    assert (local/'processed/event_dataset.parquet').read_bytes()==b'PAR1_SYNTHETIC'
    assert (local/'raw_manifest/manifest.json').read_bytes()==b'[]'
    assert (local/'config/research.json').read_bytes()==b'{"mode":"full"}'
    assert sum(call[0]=='media' for call in service.calls)==4
    with pytest.raises(FileExistsError):
        drive_io.download_statistics_resume_source(
            service,drive_io.FOLDER,run_id,tmp_path)


def test_download_rejects_wrong_parent_or_invalid_name(tmp_path,monkeypatch):
    monkeypatch.setattr(drive_io,'validate_folder',lambda *args:None)
    service,run_id=fake_archive(drive_io.FOLDER,'some-other-parent')
    with pytest.raises(ValueError,match='not verified'):
        drive_io.download_statistics_resume_source(
            service,drive_io.FOLDER,run_id,tmp_path)
    service.files_by_id[run_id]['meta']['parents']=[drive_io.FOLDER]
    service.files_by_id[run_id]['meta']['name']='unexpected'
    with pytest.raises(ValueError,match='not verified'):
        drive_io.download_statistics_resume_source(
            service,drive_io.FOLDER,run_id,tmp_path)
