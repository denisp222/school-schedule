"""Package the desktop release and private .NET runtime into one installer.

No user key, history, database or daily experiments are distributed. Annual
school directories, plan and base week are copied from a read-only snapshot.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ai_budget import PAID_MODEL
from app.model import validate_state
from app.version import VERSION


def prepare_seed(database):
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as connection:
        revision,payload=connection.execute('SELECT revision,payload FROM current_state').fetchone()
    state=json.loads(payload)
    for field,empty in [('days',{}),('dayBases',{}),('absences',[]),('journal',[]),('assistantConditions',{})]:
        state[field]=empty
    return revision,validate_state(state)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--without-voice',action='store_true')
    parser.add_argument('--private-school',action='store_true')
    args=parser.parse_args()
    release=Path((ROOT/'build/latest.txt').read_text(encoding='utf-8').strip()).resolve()
    assert release.is_relative_to(ROOT/'build/releases') and (release/'Расписание.exe').is_file()
    profile=json.loads((release/'build-profile.json').read_text(encoding='utf-8'))
    if profile['public'] is not (not args.private_school):
        raise RuntimeError('Build profile mismatch. Public installers require a clean public application build.')
    voice=profile['voice'] and not args.without_voice
    vendor=json.loads((ROOT/'build/vendor/distribution.json').read_text(encoding='utf-8'))
    compiler=ROOT/'build/vendor/inno-portable/ISCC.exe'
    assert compiler.is_file(), 'Run the official Inno portable setup first.'
    stage=ROOT/'build/distribution'/(datetime.now().strftime('%Y%m%d-%H%M%S')+('' if voice else '-lite'))
    def omit_audio(folder,names):
        return {'speech-whisper'} if not voice and Path(folder)==release/'_internal/assets' else set()
    shutil.copytree(release,stage,ignore=omit_audio)
    shutil.copytree(Path(vendor['dotnetRoot']),stage/'_internal/dotnet')
    (stage/'installed.json').write_text(json.dumps({'version':VERSION,'dataLocation':'user-local'}),encoding='utf-8')
    if args.private_school:
        revision,seed=prepare_seed(ROOT/'data/schedule.sqlite3')
        (stage/'_internal/app/seed.json').write_text(json.dumps(seed,ensure_ascii=False),encoding='utf-8')
    else:
        revision,seed=None,validate_state(json.loads((ROOT/'app/empty_seed.json').read_text(encoding='utf-8')))
        from check_public_bundle import check_bundle
        check_bundle(stage)
    defaults=stage.parent/(stage.name+'-assistant-defaults.json')
    defaults.write_text(json.dumps({'provider':'deepseek','model':PAID_MODEL,'paidEnabled':False,'monthlyLimitUSD':'1','networkMode':'system'}),encoding='utf-8')
    forbidden={'assistant-connection.json','schedule.sqlite3','server.json','application.log','assistant-deepseek.json'}
    assert not any(p.name in forbidden for p in stage.rglob('*'))
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    env=dict(os.environ,TEMP=str(ROOT/'build/vendor/temp'),TMP=str(ROOT/'build/vendor/temp'))
    command=[str(compiler),'/Qp','/DVoiceAvailable='+str(int(voice)),'/DAppVersion='+VERSION,'/DStagePath='+str(stage),
             '/DDefaultsPath='+str(defaults),'/DWebViewSetup='+vendor['webviewBootstrap'],
             '/DOutputPath='+str(output),str(ROOT/'tools/installer.iss')]
    subprocess.run(command,env=env,check=True)
    suffix='' if voice else '-без-голоса'
    installer=output/f'Расписание-установка-{VERSION}{suffix}.exe'
    report={'file':str(installer),'version':VERSION,'size':installer.stat().st_size,
            'sha256':hashlib.sha256(installer.read_bytes()).hexdigest(),'stage':str(stage),
            'privateDotnet':vendor['dotnetVersion'],'sourceRevision':revision,
            'annualLessons':len(seed['baseLessons']),'datedChangesIncluded':False,'apiKeysIncluded':False,
            'voicePackageIncluded':voice,'defaultInstallation':'without-voice','public':not args.private_school}
    (ROOT/('docs/installer-build.json' if voice else 'docs/installer-build-lite.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
