"""Exercise the public installer locally; synthetic data, no AI or Office calls."""
from io import BytesIO
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from zipfile import ZipFile

import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.updates import backup_before_update,checksum,install_script
from app.report_template import generic_template
from app.model import normalize_state


def main():
    manifest=json.loads((ROOT/'docs/installer-build-lite.json').read_text(encoding='utf-8'))
    version=manifest['version']
    if not manifest.get('public') or manifest['annualLessons']!=0:raise ValueError('Public empty installer required.')
    installer=Path(manifest['file'])
    assert checksum(installer)==manifest['sha256']
    target=ROOT/'build'/('install-public-'+version+'-'+str(time.time_ns())+'-qa')
    data=target/'data-qa'
    env=dict(os.environ,SCHEDULE_DATA=str(data),TEMP=str(ROOT/'build/vendor/temp'),TMP=str(ROOT/'build/vendor/temp'),
             DOTNET_ROOT=str(target/'no-global-runtime'),DOTNET_MULTILEVEL_LOOKUP='0')
    command=[str(installer),'/QA=1','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR='+str(target)]
    subprocess.run(command,env=env,check=True,timeout=240)
    # CI must never update itself to another release while checking this build.
    (data/'updates-disabled').touch()
    exe=target/'Расписание.exe'
    assert not (target/'_internal/app/seed.json').exists()
    with httpx.Client(timeout=15,trust_env=False) as client:
        def request(base,path,body=None):
            response=client.get(base+path) if body is None else client.post(base+path,json=body)
            response.raise_for_status();return response.json()
        def health_for(pid):
            for _ in range(100):
                for port in range(8765,8796):
                    try:
                        base=f'http://127.0.0.1:{port}'
                        response=client.get(base+'/api/health',timeout=.15)
                        if response.status_code==200 and response.json().get('pid')==pid:return base
                    except httpx.HTTPError:pass
                time.sleep(.1)
            raise TimeoutError('Packaged server failed to start.')
        child=subprocess.Popen([str(exe),'--no-browser'],env=env,cwd=target)
        base=health_for(child.pid)
        try:
            assert request(base,'/api/health')['version']==version
            initial=request(base,'/api/state')
            assert all(not initial['state'][k] for k in ('teachers','classes','plan','baseLessons'))
            assert not request(base,'/api/assistant/settings')['configured']
            synthetic=normalize_state(json.loads((ROOT/'app/demo_seed.json').read_text(encoding='utf-8')))
            synthetic['classes'][0]['homeroomTeacherId']='demo-teacher'
            request(base,'/api/import',{'revision':initial['revision'],'state':synthetic})
            for audience in ('students','teachers'):
                response=client.get(base+'/api/export/'+audience+'/2026-11-10?mode=clean');response.raise_for_status()
                with ZipFile(BytesIO(response.content)) as package:assert 'word/document.xml' in package.namelist()
            project=request(base,'/api/state')['state']
        finally:
            request(base,'/api/shutdown',{});child.wait(timeout=20)
        connection=data/'assistant-connection.json'
        settings=json.loads(connection.read_text(encoding='utf-8'));settings['testMarker']='preserve'
        connection.write_text(json.dumps(settings),encoding='utf-8');settings_hash=checksum(connection)
        backup_before_update(data)
        with sqlite3.connect(data/'before-update/schedule.sqlite3') as saved:
            assert json.loads(saved.execute('SELECT payload FROM current_state').fetchone()[0])==project
        legacy=target/'_internal/app/templates';legacy.mkdir(parents=True,exist_ok=True)
        template=legacy/'ПОНЕДЕЛЬНИК УЧИТЕЛЬ.docx';template.write_bytes(generic_template(synthetic,'teachers'))
        template_hash=checksum(template)
        seed=target/'_internal/app/seed.json';seed.write_text(json.dumps(synthetic),encoding='utf-8');seed_hash=checksum(seed)
        speech=target/'_internal/assets/speech-whisper';speech.mkdir(parents=True,exist_ok=True)
        (speech/'model.bin').write_bytes(b'synthetic voice preservation marker')
        (target/'installed-components.json').write_text('{"voice":true}',encoding='utf-8')
        old=subprocess.Popen([sys.executable,'-c','import time;time.sleep(1)'],env=env)
        script=install_script(installer,target,old.pid,manifest['sha256']).replace("'/UPDATE=1'","'/UPDATE=1', '/QA=1'")
        encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
        # Reproduce the private environment inherited from a frozen parent.
        # The former source-only test missed the restart failure in this case.
        frozen_env=dict(env,_PYI_PARENT_PROCESS_LEVEL='1',_PYI_ARCHIVE_FILE=str(exe),
            _PYI_APPLICATION_HOME_DIR=str(target/'removed-previous-runtime'))
        helper=subprocess.Popen(['powershell','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',encoded],env=frozen_env)
        old.wait(timeout=10);helper.wait(timeout=240);assert helper.returncode==0
        assert checksum(connection)==settings_hash
        assert checksum(data/'templates'/template.name)==template_hash
        assert not seed.exists() and checksum(data/'factory-seed.json')==seed_hash
        assert json.loads((target/'installed-components.json').read_text(encoding='utf-8-sig'))['voice'] is True
        base=None
        for _ in range(150):
            try:
                marker=json.loads((data/'server.json').read_text(encoding='utf-8'))
                health=request(marker['url'],'/api/health')
                if health['version']==version and Path(health['data']).resolve()==data.resolve():base=marker['url'];break
            except (OSError,ValueError,httpx.HTTPError):pass
            time.sleep(.2)
        assert base,'Installer did not reopen the native application.'
        try:
            assert request(base,'/api/state')['state']==project
            for _ in range(150):
                if 'UI startup: ready ' in (data/'application.log').read_text(encoding='utf-8'):break
                time.sleep(.2)
            assert 'UI startup: ready ' in (data/'application.log').read_text(encoding='utf-8')
            assert 'UI runtime version: '+manifest['privateDotnet'] in (data/'application.log').read_text(encoding='utf-8')
        finally:request(base,'/api/shutdown',{})
    report={'version':version,'emptyProject':True,'syntheticProjectPreserved':True,'personalSettingsPreserved':True,
            'templatesPreserved':True,'legacySeedMovedToData':True,'voicePreserved':True,'sqliteBackupValid':True,
            'installerHelperRelaunch':True,'nativeUiReady':True,'genericWordValid':True,'liveModelRequests':0}
    (ROOT/'docs/public-install-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
