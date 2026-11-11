"""Record only installed dependencies reachable from the declared dev roots."""
from importlib import metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]


def main():
    queue=[]
    for name in ('requirements.txt','requirements-dev.txt'):
        queue.extend(Requirement(row) for row in (ROOT/name).read_text(encoding='utf-8').splitlines()
                     if row.strip() and not row.startswith(('#','-')))
    found={}
    while queue:
        requirement=queue.pop()
        if requirement.marker and not requirement.marker.evaluate():continue
        name=canonicalize_name(requirement.name)
        if name in found:continue
        distribution=metadata.distribution(name)
        found[name]=distribution.version
        queue.extend(Requirement(row) for row in distribution.requires or [])
    (ROOT/'requirements-lock.txt').write_text('# Installed Windows/Python 3.13 dependency closure; regenerate with tools/lock_requirements.py.\n'+
        ''.join(f'{name}=={version}\n' for name,version in sorted(found.items())),encoding='utf-8')


if __name__=='__main__':main()
