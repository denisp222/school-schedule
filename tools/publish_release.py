"""Publish only the public installer and signed manifest, never a dist glob."""
import json
import os
from pathlib import Path
import sys

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.updates import channel,validate_manifest,checksum
from app.version import VERSION


def main():
    config=channel()
    if not config:raise ValueError('Configure an update channel first.')
    report=json.loads((ROOT/'docs/installer-build-lite.json').read_text(encoding='utf-8'))
    if report.get('public') is not True or report['version']!=VERSION:
        raise ValueError('Only an inspected public build can be published.')
    from check_public_bundle import check_bundle
    check_bundle(report['stage'])
    installer=Path(report['file'])
    manifest=ROOT/'dist/update.json'
    payload=validate_manifest(json.loads(manifest.read_bytes()),config,'0.0.0')
    if checksum(installer)!=payload['asset']['sha256'] or installer.stat().st_size!=payload['asset']['size']:
        raise ValueError('Manifest does not match the installer.')
    token=os.environ['GITHUB_TOKEN']
    base=f"https://api.github.com/repos/{config['repository']}"
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
    with httpx.Client(headers=headers,timeout=120,trust_env=False) as client:
        response=client.get(base+'/releases/tags/v'+VERSION)
        if response.status_code!=404:
            raise ValueError('This release tag already exists; publish a new version instead.')
        response=client.post(base+'/releases',json={'tag_name':'v'+VERSION,'name':'Расписание '+VERSION,
            'draft':True,'prerelease':False,'body':'Обновление программы. База данных хранится отдельно на вашем компьютере.'})
        response.raise_for_status();release=response.json()
        # A failed upload remains a draft, invisible to automatic updates.
        upload=release['upload_url'].split('{',1)[0]
        for path,name,mime in [(installer,'ScheduleSetup.exe','application/octet-stream'),
                                (manifest,'update.json','application/json')]:
            with path.open('rb') as stream:
                response=client.post(upload,params={'name':name},headers={'Content-Type':mime,
                    'Content-Length':str(path.stat().st_size)},content=iter(lambda:stream.read(1024*1024),b''))
            response.raise_for_status()
        response=client.patch(base+'/releases/'+str(release['id']),json={'draft':False,'make_latest':'true'})
        response.raise_for_status()
        print('Published '+response.json()['html_url'])


if __name__=='__main__':main()
