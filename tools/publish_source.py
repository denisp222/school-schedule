"""Export committed allowlisted source, leaving private local history untouched."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.updates import channel
from app.version import VERSION


def git(folder,*args,capture=False):
    command=['git','-c','safe.directory='+folder.as_posix(),'-c','core.autocrlf=false',*args]
    if capture:return subprocess.check_output(command,cwd=folder)
    subprocess.run(command,cwd=folder,check=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--release',action='store_true')
    parser.add_argument('--push',action='store_true');args=parser.parse_args()
    config=channel()
    if not config:raise ValueError('Configure an update repository first.')
    subprocess.run([sys.executable,'tools/check_repository.py','--history'],cwd=ROOT,check=True)
    if git(ROOT,'status','--porcelain',capture=True).strip():
        raise ValueError('Commit and check all public source changes before publishing.')
    target=(ROOT/'build/public-source').resolve()
    target.mkdir(parents=True,exist_ok=True)
    if not (target/'.git').is_dir():
        git(target,'init','-b','main')
        git(target,'config','user.name',config['repository'].split('/')[0])
        git(target,'config','user.email',config['repository'].split('/')[0]+'@users.noreply.github.com')
        git(target,'remote','add','origin','https://github.com/'+config['repository']+'.git')
    expected='https://github.com/'+config['repository']+'.git'
    if git(target,'remote','get-url','origin',capture=True).decode().strip()!=expected:
        raise ValueError('Publication repository origin does not match update channel.')
    previous={p.decode('utf-8') for p in git(target,'ls-files','-z',capture=True).split(b'\0') if p}
    archived=git(ROOT,'archive','--format=zip','HEAD',capture=True)
    with ZipFile(BytesIO(archived)) as archive:
        current={item.filename for item in archive.infolist() if not item.is_dir()}
        for name in previous-current:
            path=(target/name).resolve()
            if not path.is_relative_to(target) or '.git' in path.relative_to(target).parts:
                raise ValueError('Unsafe publication path')
            path.unlink(missing_ok=True)
        for item in archive.infolist():
            if item.is_dir():continue
            path=(target/item.filename).resolve()
            if not path.is_relative_to(target) or '.git' in path.relative_to(target).parts:
                raise ValueError('Unsafe archive path')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(archive.read(item))
    git(target,'add','--all')
    if git(target,'diff','--cached','--name-only',capture=True).strip():
        git(target,'commit','-m','Release '+VERSION)
    subprocess.run([sys.executable,'tools/check_repository.py','--history'],cwd=target,check=True)
    if args.push or args.release:git(target,'push','-u','origin','main')
    if args.release:
        tag='v'+VERSION
        if not git(target,'tag','--list',tag,capture=True).strip():git(target,'tag',tag)
        git(target,'push','origin',tag)
    print('Clean source prepared in '+str(target))


if __name__=='__main__':main()
