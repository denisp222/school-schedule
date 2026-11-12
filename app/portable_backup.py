"""Portable local copies, including templates and password-protected AI keys."""
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
import zlib

from .assistant_history import AssistantHistory
from .class_hours import fill_leaders,sync_labels
from .model import normalize_state,validate_state

CONFIG_FIELDS=('provider','model','paidEnabled','networkMode','monthlyLimitUSD','usage','billing')
MAX_BYTES=28_000_000


def _b64(raw):return base64.b64encode(raw).decode('ascii')


def _unb64(text,maximum):
    if not isinstance(text,str) or len(text)>maximum*4//3+8:raise ValueError('Резервная копия повреждена или слишком велика.')
    try:value=base64.b64decode(text,validate=True)
    except (ValueError,TypeError):raise ValueError('Резервная копия повреждена.') from None
    if len(value)>maximum:raise ValueError('Резервная копия слишком велика.')
    return value


def _key(password,salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not isinstance(password,str) or not 8<=len(password)<=256:
        raise ValueError('Для переноса подключения задайте пароль копии от 8 до 256 символов.')
    return Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))


def seal(secrets,password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt=os.urandom(16);nonce=os.urandom(12)
    content=json.dumps(secrets).encode('utf-8')
    encrypted=AESGCM(_key(password,salt)).encrypt(nonce,content,b'SchoolSchedule-Portable-1')
    return {'salt':_b64(salt),'nonce':_b64(nonce),'content':_b64(encrypted)}


def unseal(value,password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    try:
        salt=_unb64(value['salt'],16);nonce=_unb64(value['nonce'],12)
        if len(salt)!=16 or len(nonce)!=12:raise ValueError()
        raw=AESGCM(_key(password,salt)).decrypt(nonce,_unb64(value['content'],8192),b'SchoolSchedule-Portable-1')
        secrets=json.loads(raw)
        if (not isinstance(secrets,dict) or not set(secrets)<={'key','deepseekKey'}
                or any(not isinstance(v,str) or not v.startswith('sk-') or len(v)>512 for v in secrets.values())):raise ValueError()
        return secrets
    except (InvalidTag,KeyError,TypeError,ValueError):
        raise ValueError('Не удалось открыть подключение. Проверьте пароль резервной копии.') from None


def export(store,data,connection,*,password=None):
    from .ai_service import protect_secret
    # All SQLite sections are read from one transaction, including the WAL.
    with store.connect() as db:
        db.execute('BEGIN')
        state=json.loads(db.execute('SELECT payload FROM current_state WHERE singleton=1').fetchone()[0])
        snapshots=[{'created':r[0],'label':r[1],'state':json.loads(r[2])} for r in
                   db.execute('SELECT created,label,payload FROM snapshots ORDER BY id')]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conversations=[]
        if {'assistant_threads','assistant_turns'}<=tables:
            for row in db.execute('SELECT id,date,title,updated FROM assistant_threads ORDER BY updated'):
                thread=dict(zip(('id','date','title','updated'),row));thread['turns']=[]
                for turn in db.execute('SELECT id,created,request,response,error,status FROM assistant_turns WHERE thread_id=? ORDER BY rowid',(row[0],)):
                    thread['turns'].append({'id':turn[0],'created':turn[1],'request':turn[2],
                        'response':json.loads(turn[3]) if turn[3] else None,'error':turn[4],'status':turn[5]})
                conversations.append(thread)
    fill_leaders(state);sync_labels(state)
    for item in snapshots:
        fill_leaders(item['state']);sync_labels(item['state'])
        item['packedState']=_b64(zlib.compress(json.dumps(item.pop('state'),ensure_ascii=False).encode('utf-8')))
    state['_assistantConversations']=conversations
    with connection.lock:config=deepcopy(connection._read())
    settings={k:config[k] for k in CONFIG_FIELDS if k in config}
    secrets={k:protect_secret(config[k],decrypt=True) for k in ('key','deepseekKey') if config.get(k)} if password is not None else {}
    from .exporter import template_path
    templates={}
    for d in (0,1):
        for audience in ('teachers','students'):
            path=template_path(d,audience)
            if path.is_file():templates[path.name]=_b64(path.read_bytes())
    state['_portableBackup']={'version':2,'templates':templates,'snapshots':snapshots,
        'assistantSettings':settings,'updatesEnabled':not (Path(data)/'updates-disabled').exists(),
        'encryptedKeys':seal(secrets,password) if secrets else None,
        'keyEntryRequired':bool(any(config.get(k) for k in ('key','deepseekKey')) and not secrets)}
    payload=json.dumps(state,ensure_ascii=False).encode('utf-8')
    if len(payload)>MAX_BYTES:raise ValueError('Полная копия слишком велика. Уменьшите число сохраняемых версий или размер шаблонов.')
    return payload


def prepare(raw,password,connection):
    """Validate everything before any project or external file is changed."""
    from .ai_service import protect_secret,provider_of,selected_model
    from .ai_budget import usd
    raw=deepcopy(raw);extra=raw.pop('_portableBackup',None)
    conversations=AssistantHistory.validate_import(raw.pop('_assistantConversations',[]))
    state=validate_state(normalize_state(raw));fill_leaders(state);sync_labels(state)
    if extra is None:return state,conversations,None,{}
    if not isinstance(extra,dict) or extra.get('version') not in (1,2):raise ValueError('Эта версия резервной копии пока не поддерживается.')
    templates=extra.get('templates',{});snapshots=extra.get('snapshots',[])
    if not isinstance(templates,dict) or len(templates)>16 or not isinstance(snapshots,list) or len(snapshots)>16:
        raise ValueError('В резервной копии повреждены шаблоны или история версий.')
    files={};total=0
    for name,text in templates.items():
        if (not isinstance(name,str) or not name.lower().endswith('.docx') or len(name)>120
                or any(c in name for c in '/\\:*?"<>|') or name.startswith('.') or name.rstrip()!=name):
            raise ValueError('Недопустимое имя шаблона в резервной копии.')
        content=_unb64(text,4_000_000);total+=len(content)
        if total>12_000_000:raise ValueError('Шаблоны в копии слишком велики.')
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist())>40_000_000:raise ValueError()
                if not {'[Content_Types].xml','word/document.xml'}<=set(z.namelist()):raise ValueError()
                from xml.etree import ElementTree
                ElementTree.fromstring(z.read('word/document.xml'))
        except Exception:raise ValueError('В копии повреждён шаблон Word.') from None
        files['templates/'+name]=content
    for snapshot in snapshots:
        try:
            if 'packedState' in snapshot:
                decoder=zlib.decompressobj()
                content=decoder.decompress(_unb64(snapshot.pop('packedState'),8_000_000),8_000_001)
                if len(content)>8_000_000 or not decoder.eof or decoder.unused_data:raise ValueError()
                snapshot['state']=json.loads(content)
            datetime.fromisoformat(snapshot['created'])
            if not isinstance(snapshot['label'],str) or len(snapshot['label'])>1000:raise ValueError()
            validate_state(normalize_state(snapshot['state']))
        except Exception:raise ValueError('В копии повреждена история версий расписания.') from None
    settings=extra.get('assistantSettings',{})
    if not isinstance(settings,dict) or not set(settings)<=set(CONFIG_FIELDS):raise ValueError('Не удалось прочитать настройки помощника.')
    if settings:
        provider=provider_of(settings);selected_model(settings,provider)
        if not usd('.01')<=usd(settings.get('monthlyLimitUSD','1'))<=usd(100):raise ValueError('Некорректный предел расходов в копии.')
        if settings.get('networkMode','system') not in ('system','direct'):raise ValueError('Неизвестное сетевое подключение в копии.')
        usage=settings.get('usage',{});billing=settings.get('billing',{})
        if not isinstance(usage,dict) or not isinstance(billing,dict):raise ValueError('Повреждены настройки помощника в копии.')
        for key in ('requests','tokens'):
            if key in usage and (type(usage[key]) is not int or usage[key]<0):raise ValueError('Повреждена история использования помощника.')
        for key in ('spent','remoteSpent'):usd(billing.get(key,0))
        for key in ('reservations','expiredReservations','reservationTimes'):
            values=billing.get(key,{})
            if not isinstance(values,dict) or len(values)>1000:raise ValueError('Повреждены настройки предела расходов.')
            for ident,value in values.items():
                if not isinstance(ident,str) or len(ident)>128:raise ValueError('Повреждены настройки предела расходов.')
                usd(value)
        with connection.lock:config={k:v for k,v in connection._read().items() if k in ('key','deepseekKey')}
        config.update(settings)
        if extra.get('encryptedKeys'):
            config.update({k:protect_secret(v) for k,v in unseal(extra['encryptedKeys'],password).items()})
        files['assistant-connection.json']=json.dumps(config,ensure_ascii=False).encode('utf-8')
    enabled=extra.get('updatesEnabled',True)
    if type(enabled) is not bool:raise ValueError('Не удалось прочитать настройки обновления.')
    files['updates-disabled']=None if enabled else b''
    return state,conversations,snapshots,files


@contextmanager
def restore_files(data,files):
    """Stage locally and restore old files if the SQLite transaction fails."""
    data=Path(data);previous={}
    with tempfile.TemporaryDirectory(prefix='restore-',dir=data) as temporary:
        stage=Path(temporary)
        for name,content in files.items():
            target=data/name
            previous[name]=target.read_bytes() if target.is_file() else None
            if content is not None:
                prepared=stage/name;prepared.parent.mkdir(parents=True,exist_ok=True);prepared.write_bytes(content)
        try:
            for name,content in files.items():
                target=data/name;target.parent.mkdir(parents=True,exist_ok=True)
                if content is None:target.unlink(missing_ok=True)
                else:os.replace(stage/name,target)
            yield
        except BaseException:
            for name,content in previous.items():
                target=data/name
                if content is None:target.unlink(missing_ok=True)
                else:
                    prepared=stage/('rollback-'+str(len(name)))
                    prepared.write_bytes(content);os.replace(prepared,target)
            raise


def restore_history(db,conversations,snapshots,state):
    if snapshots is not None:
        db.execute('DELETE FROM assistant_turns');db.execute('DELETE FROM assistant_threads')
        if snapshots:
            db.execute('DELETE FROM snapshots')
            for item in snapshots:
                db.execute('INSERT INTO snapshots(created,label,payload) VALUES (?,?,?)',
                    (item['created'],item['label'],json.dumps(item['state'],ensure_ascii=False)))
            db.execute('UPDATE snapshots SET payload=?,created=? WHERE id=(SELECT MAX(id) FROM snapshots)',
                (json.dumps(state,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
    AssistantHistory.restore(db,conversations)


def backup_before_restore(store,data):
    from contextlib import closing
    import sqlite3
    folder=Path(data)/'before-import';folder.mkdir(exist_ok=True)
    temporary=folder/'schedule.tmp'
    with store.connect() as source:
        with closing(sqlite3.connect(temporary)) as saved:
            source.backup(saved)
            if saved.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Не удалось создать контрольную копию перед загрузкой.')
    os.replace(temporary,folder/'schedule.sqlite3')
