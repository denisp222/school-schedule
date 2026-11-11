"""Fail closed on private factory data in a public application directory."""
import json
from pathlib import Path
import sys


def check_bundle(folder):
    folder=Path(folder)
    internal=folder/'_internal'
    seed=internal/'app/empty_seed.json'
    if not seed.is_file():
        raise ValueError('Public package has no empty initial project.')
    value=json.loads(seed.read_text(encoding='utf-8'))
    if value != {'school':{'name':'Школа'},'teachers':[],'classes':[],'subjects':[],
                 'rooms':[],'plan':[],'baseLessons':[]}:
        raise ValueError('Public initial project contains unexpected data.')
    forbidden_names={'seed.json','demo_seed.json','assistant-connection.json','server.json',
                     'application.log','assistant-deepseek.json','update-signing-key.txt'}
    for item in folder.rglob('*'):
        parts=item.relative_to(folder).parts
        # python-docx includes a generic empty Office package. It is library
        # data, checked byte-for-byte against the pinned installed dependency.
        import docx,pandas
        stock_roots=[(internal/'docx/templates',Path(docx.__file__).parent/'templates'),
                     (internal/'pandas/io/formats/templates',Path(pandas.__file__).parent/'io/formats/templates')]
        stock=next(((packed,installed) for packed,installed in stock_roots if item.is_relative_to(packed)),None)
        if stock:
            if item.is_dir():continue
            packed,installed=stock
            reference=installed/item.relative_to(packed)
            if not reference.is_file() or reference.read_bytes()!=item.read_bytes():
                raise ValueError('Modified library template in public application.')
            continue
        if (item.name in forbidden_names or 'data' in parts or 'templates' in parts
                or item.suffix.lower() in {'.sqlite3','.db','.docx','.hgf','.chngf','.bak'}):
            raise ValueError('Private/generated data found in public application: '+item.relative_to(folder).as_posix())
    print('Public application: empty project; no school templates, database or API keys.')
    return True


if __name__=='__main__':
    check_bundle(sys.argv[1])
