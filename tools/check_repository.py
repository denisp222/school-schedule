"""Inspect staged blobs, not working copies. Never print private matches."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(), *args], cwd=ROOT)


def check(staged=False):
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z') if staged else git('ls-files', '-z')
    surnames = set()
    seed = ROOT/'app/seed.json'
    if seed.exists():
        for row in json.loads(seed.read_text(encoding='utf-8')).get('teachers', []):
            if row.get('name'):surnames.add(row['name'].split()[0].casefold().replace('ё','е'))
    problems = []
    allowed_roots = {'app','tests','tools','docs','.github','.githooks'}
    forbidden = {'data','build','dist','fixtures','templates','assets','archive','__pycache__'}
    for raw in names.split(b'\0'):
        if not raw:continue
        name = raw.decode('utf-8');path = Path(name)
        public_icon=name in {'app/static/favicon.ico',*[f'app/static/icon-{size}.png' for size in (64,192,512,1024)]}
        bad_path = bool(set(path.parts)&forbidden) or path.suffix.lower() in {'.sqlite3','.db','.docx','.chngf','.hgf','.exe','.dll','.jpg','.png','.bak'}
        bad_path |= path.name in {'seed.json','factory-seed.json','assistant-connection.json','server.json','update-signing-key.txt'} or path.name.startswith('~$')
        if len(path.parts)>1 and path.parts[0] not in allowed_roots:bad_path=True
        if bad_path and not public_icon:
            problems.append((name,'private or generated path'));continue
        blob = git('show', ':'+name)
        if public_icon:continue
        try:text = blob.decode('utf-8')
        except UnicodeDecodeError:
            problems.append((name,'binary content requires separate review'));continue
        normalized = text.casefold().replace('ё','е')
        if any(re.search(r'(?<![а-я])'+re.escape(s)+r'(?![а-я])',normalized) for s in surnames):
            problems.append((name,'school name detected'))
        if re.search(r'\bsk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):
            problems.append((name,'credential pattern detected'))
    for name,reason in problems:print(f'BLOCKED: {name}: {reason}')
    print(f'Privacy check: {len([n for n in names.split(bytes([0])) if n])} files, {len(problems)} problems.')
    return not problems


def check_history():
    """Inspect every reachable historical version, not just the current tree."""
    if not check():return False
    names=git('rev-list','--objects','--all').decode('utf-8').splitlines()
    checked=0
    for row in names:
        oid,_,name=row.partition(' ')
        if not name:continue
        path=Path(name)
        if git('cat-file','-t',oid).strip()!=b'blob':continue
        checked+=1
        if (any(p in {'data','dist','build','templates','.private','fixtures'} for p in path.parts)
                or path.name in {'seed.json','factory-seed.json','assistant-connection.json','update-signing-key.txt'}
                or path.suffix.lower() in {'.docx','.chngf','.hgf','.db','.sqlite3','.exe','.dll','.bak'}):
            print('BLOCKED historical private path: '+name);return False
        blob=git('cat-file','blob',oid)
        # Existing public icons are intentionally binary.
        if path.suffix.lower() in {'.png','.ico'}:continue
        if re.search(rb'\bsk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',blob):
            print('BLOCKED historical credential pattern: '+name);return False
        seed=ROOT/'app/seed.json'
        if seed.exists():
            text=blob.decode('utf-8',errors='replace').casefold().replace('ё','е')
            for teacher in json.loads(seed.read_text(encoding='utf-8')).get('teachers',[]):
                surname=teacher.get('name','').split()[0].casefold().replace('ё','е')
                if surname and re.search(r'(?<![а-я])'+re.escape(surname)+r'(?![а-я])',text):
                    print('BLOCKED historical school name: '+name);return False
    print(f'Historical privacy check: {checked} blobs, no blocked content.')
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--staged',action='store_true');parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    sys.exit(0 if (check_history() if args.history else check(args.staged)) else 1)
