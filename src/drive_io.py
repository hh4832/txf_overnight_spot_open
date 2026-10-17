from pathlib import Path

FOLDER='1E9VkK_NgePZUidKu6ZqB2gceLnKy9kYx'


def validate_folder(service,folder_id):
    if folder_id!=FOLDER:
        raise ValueError('Unexpected target Folder ID')
    meta=service.files().get(fileId=folder_id,fields='id,name,mimeType,trashed,capabilities(canAddChildren)').execute()
    if meta['id']!=folder_id or meta['mimeType']!='application/vnd.google-apps.folder' or meta.get('trashed') or not meta.get('capabilities',{}).get('canAddChildren'):
        raise ValueError('Target folder unavailable/not writable; verify account and Folder ID')
    return meta


def upload_run(service,folder_id,local_run):
    """Use IDs and parent IDs only; never guess a MyDrive mount path."""
    from googleapiclient.http import MediaFileUpload
    validate_folder(service,folder_id)
    local_run=Path(local_run)
    # Refuse same-name overwrites, including a previous partial upload.
    name=local_run.name
    exists=service.files().list(q=f"'{folder_id}' in parents and name = '{name}' and trashed = false",fields='files(id)').execute()['files']
    if exists: raise ValueError('Run already exists on Drive; refusing overwrite')
    root=service.files().create(body={'name':name,'mimeType':'application/vnd.google-apps.folder','parents':[folder_id]},fields='id').execute()['id']
    folders={local_run:root}
    for p in sorted(local_run.rglob('*')):
        if p.is_dir():
            folders[p]=service.files().create(body={'name':p.name,'mimeType':'application/vnd.google-apps.folder','parents':[folders[p.parent]]},fields='id').execute()['id']
        else:
            service.files().create(body={'name':p.name,'parents':[folders[p.parent]]},media_body=MediaFileUpload(str(p),resumable=True),fields='id').execute()
    return root


def verified_cache_root(service,folder_id,mount_root):
    """Traverse actual Drive metadata; reject duplicate names/shortcuts/shared roots."""
    validate_folder(service,folder_id)
    parts=[]
    current=folder_id
    root=service.files().get(fileId='root',fields='id').execute()['id']
    while current!=root:
        m=service.files().get(fileId=current,fields='id,name,parents,mimeType').execute()
        if m['mimeType']!='application/vnd.google-apps.folder' or len(m.get('parents',[]))!=1:
            raise ValueError('Cache mount cannot be verified; use MyDrive folder or explicit import')
        parent=m['parents'][0]
        # Names with slashes cannot map safely to mount paths.
        if '/' in m['name'] or m['name'] in {'.','..'}: raise ValueError('Unsafe mount name')
        siblings=service.files().list(q=f"'{parent}' in parents and trashed = false",fields='nextPageToken,files(id,name)',pageSize=1000).execute()
        if siblings.get('nextPageToken') or sum(x['name']==m['name'] for x in siblings['files'])!=1:
            raise ValueError('Ambiguous Drive mount path')
        parts.append(m['name']);current=parent
    path=Path(mount_root).joinpath(*reversed(parts))
    if not path.is_dir(): raise ValueError('Verified Drive folder not present in mount')
    return path/'cache'
