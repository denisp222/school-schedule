"""Reproducible Windows build without changing PowerShell execution policy."""
from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys
import argparse
from importlib import metadata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def copy_notices(target):
    """Keep upstream copyright notices with redistributed dependencies."""
    notices=target/'third-party-notices';notices.mkdir(exist_ok=True)
    for row in (ROOT/'requirements-lock.txt').read_text(encoding='utf-8').splitlines():
        if not row or row.startswith('#'):continue
        name=row.split('==')[0];distribution=metadata.distribution(name)
        for item in distribution.files or []:
            path=Path(str(item));label=path.name.lower()
            if not label.startswith(('license','copying','notice')) or path.suffix.lower() not in ('','.txt','.md','.rst'):continue
            source=Path(distribution.locate_file(item))
            if source.is_file():
                destination=notices/name/path.name;destination.parent.mkdir(exist_ok=True)
                shutil.copy2(source,destination)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,notices/'Python-LICENSE.txt')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--private-school',action='store_true',help='Local school build, never publish.')
    parser.add_argument('--with-voice',action='store_true')
    args=parser.parse_args()
    # One build entry point; do not ship code that failed its regression suite.
    test_env=dict(os.environ,SCHEDULE_SOLVER_WORKER='1')
    subprocess.run([sys.executable,'-m','pytest','-q'],cwd=ROOT,env=test_env,check=True)
    from app.version import VERSION
    from app.releases import RELEASES
    if not RELEASES or RELEASES[0]['version']!=VERSION:
        raise RuntimeError('Add release notes for the current application version before building.')
    if VERSION not in (ROOT/'README.md').read_text(encoding='utf-8'):
        raise RuntimeError('Update README to the application version before building.')
    template_source=ROOT/'app/templates'
    if args.private_school and not template_source.is_dir():
        raise RuntimeError('Local Word templates are missing; restore them from the private school assets.')
    release=ROOT/'build/releases'/datetime.now().strftime('%Y%m%d-%H%M%S')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed',
             '--name','Расписание','--icon',str(ROOT/'app/static/favicon.ico'),
             '--workpath',str(ROOT/'build/work'),'--distpath',str(release),
             '--specpath',str(ROOT/'build')]
    for source,target in [('app/static','app/static'),('app/empty_seed.json','app'),
                          ('app/update_channel.json','app'),('app.runtimeconfig.json','.'),
                          *[(f'assets/webview/{name}','assets/webview') for name in
                            ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll',
                             'WebView2Loader.dll','LICENSE.txt')]]:
        command+=['--add-data',str(ROOT/source)+';'+target]
    if args.private_school:
        command+=['--add-data',str(ROOT/'app/seed.json')+';app',
                  '--add-data',str(template_source)+';app/templates']
    if args.with_voice:
        command+=['--add-data',str(ROOT/'assets/speech-whisper')+';assets/speech-whisper']
    for package in ('pythonnet','clr_loader','ortools'):command+=['--collect-all',package]
    for module in ('app.server','uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto',
                   'uvicorn.protocols.websockets.auto','uvicorn.lifespan.on'):
        command+=['--hidden-import',module]
    command.append(str(ROOT/'launch.py'))
    subprocess.run(command,cwd=ROOT,check=True)
    target=release/'Расписание/_internal'
    copy_notices(target)
    for name in ('msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll',
                 'msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_1.dll','concrt140.dll','vcomp140.dll'):
        source=Path(os.environ['SystemRoot'])/'System32'/name
        if source.exists():
            shutil.copy2(source,target/name)
            for folder in ('bin','bin-blas','bin-cuda'):
                destination=target/'assets/speech-whisper'/folder
                if destination.is_dir():shutil.copy2(source,destination/name)
    (ROOT/'build/latest.txt').write_text(str(target.parent),encoding='utf-8')
    (target.parent/'build-profile.json').write_text(__import__('json').dumps({
        'public':not args.private_school,'voice':args.with_voice,'version':VERSION}),encoding='utf-8')


if __name__=='__main__':main()
