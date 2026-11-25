"""Update trust boundaries, empty public projects, and preservation of local data."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import time
from zipfile import ZipFile

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import updates


@pytest.fixture
def signed():
    key=Ed25519PrivateKey.generate()
    config={'repository':'example/schedule','publicKey':base64.b64encode(key.public_key().public_bytes_raw()).decode()}
    data=b'fake public installer'
    import hashlib
    payload={'schema':1,'repository':config['repository'],'version':'99.0.0','asset':{
        'name':'ScheduleSetup.exe','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
        'url':'https://github.com/example/schedule/releases/download/v99.0.0/ScheduleSetup.exe'}}
    def sign(value):return {'payload':value,'signature':base64.b64encode(key.sign(updates.canonical(value))).decode()}
    return config,payload,sign,data


def test_signature_tampering_and_wrong_signer_are_rejected(signed):
    config,payload,sign,_=signed
    assert updates.validate_manifest(sign(payload),config)==payload
    changed=sign(payload);changed['payload']=deepcopy(payload);changed['payload']['version']='99.1.0'
    with pytest.raises(Exception):updates.validate_manifest(changed,config)
    wrong={**config,'publicKey':base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()}
    with pytest.raises(Exception):updates.validate_manifest(sign(payload),wrong)


@pytest.mark.parametrize('field,value',[('repository','elsewhere/project'),('version','99.0.0-beta'),
    ('schema',2),('asset.url','https://evil.invalid/setup.exe'),('asset.url','http://github.com/example/setup.exe'),
    ('asset.size',True),('asset.size',updates.MAX_DOWNLOAD+1),('asset.sha256','wrong'),('asset.name','../setup.exe')])
def test_even_signed_invalid_metadata_cannot_redirect_execution(signed,field,value):
    config,payload,sign,_=signed
    value_copy=deepcopy(payload)
    if '.' in field:value_copy['asset'][field.split('.')[1]]=value
    else:value_copy[field]=value
    with pytest.raises(ValueError):updates.validate_manifest(sign(value_copy),config)


def test_no_downgrade_or_reinstallation(signed):
    config,payload,sign,_=signed
    assert updates.validate_manifest(sign(payload),config,'99.0.0') is None
    assert updates.validate_manifest(sign(payload),config,'100.0.0') is None


def test_redirect_rejected_before_any_untrusted_connection(signed):
    _,payload,_,_=signed;requested=[]
    def handle(request):
        requested.append(str(request.url))
        return httpx.Response(302,headers={'Location':'https://evil.invalid/collect'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):updates.get_stream(client,payload['asset']['url'])
    assert len(requested)==1 and requested[0].startswith('https://github.com/')


def test_valid_download_and_cache_recheck(signed,tmp_path):
    _,payload,_,data=signed;requests=[]
    def handle(request):
        requests.append(str(request.url));return httpx.Response(200,content=data)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        path=updates.download(client,payload,tmp_path)
        assert path.read_bytes()==data
        assert updates.download(client,payload,tmp_path)==path and len(requests)==1
        path.write_bytes(b'corrupted')
        updates.download(client,payload,tmp_path)
        assert len(requests)==2 and path.read_bytes()==data


@pytest.mark.parametrize('data',[b'too short',b'longer than expected'*10])
def test_bad_download_not_executed_or_retained(signed,tmp_path,data):
    _,payload,_,_=signed
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=data))) as client:
        with pytest.raises(ValueError):updates.download(client,payload,tmp_path)
    assert not list(tmp_path.rglob('*.exe')) and not list(tmp_path.rglob('*.part'))


def test_backup_includes_live_wal_and_does_not_modify_user_database(tmp_path):
    path=tmp_path/'schedule.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE example(value TEXT)')
        db.execute("INSERT INTO example VALUES ('local timetable')");db.commit()
        updates.backup_before_update(tmp_path)
        assert db.execute('SELECT value FROM example').fetchone()[0]=='local timetable'
    with sqlite3.connect(tmp_path/'before-update/schedule.sqlite3') as db:
        assert db.execute('SELECT value FROM example').fetchone()[0]=='local timetable'


def test_templates_preserved_without_overwriting_existing_customization(tmp_path):
    data=tmp_path/'data';data.mkdir();resources=tmp_path/'runtime'
    source=resources/'app/templates';source.mkdir(parents=True)
    (source/'first.docx').write_bytes(b'legacy private template')
    updates.preserve_templates(data,resources)
    assert (data/'templates/first.docx').read_bytes()==b'legacy private template'
    (source/'first.docx').write_bytes(b'different')
    updates.preserve_templates(data,resources)
    assert (data/'templates/first.docx').read_bytes()==b'legacy private template'


def test_empty_project_and_generic_reports_do_not_require_private_files(tmp_path,monkeypatch):
    from app import model,exporter
    monkeypatch.setattr(model,'SEED',tmp_path/'not-present.json')
    state=model.initial_state()
    assert all(state[k]==[] for k in ('teachers','classes','subjects','rooms','plan','baseLessons'))
    monkeypatch.setattr(exporter,'TEMPLATES',tmp_path/'templates')
    for audience in ('students','teachers'):
        with ZipFile(BytesIO(exporter.export_docx(state,'2026-11-11',audience))) as package:
            assert b'document' in package.read('word/document.xml')


def test_generic_reports_support_arbitrary_classes_and_teachers(tmp_path,monkeypatch):
    from app import exporter,model
    state=model.normalize_state(json.loads((Path(__file__).parents[1]/'app/demo_seed.json').read_text(encoding='utf-8')))
    monkeypatch.setattr(exporter,'TEMPLATES',tmp_path/'templates')
    for audience in ('students','teachers'):
        with ZipFile(BytesIO(exporter.export_docx(state,'2026-11-10',audience))) as package:
            text=package.read('word/document.xml').decode()
            assert ('Учитель 1' if audience=='teachers' else 'Матем.') in text


@pytest.mark.parametrize('audience', ['teachers', 'students'])
@pytest.mark.parametrize('mode', ['changes', 'clean', 'base'])
def test_preview_renders_the_same_word_document_that_can_be_saved(tmp_path, monkeypatch, audience, mode):
    from fastapi.testclient import TestClient
    from lxml import etree
    from app import exporter, model, server, word_preview
    from app.store import Store

    state = model.normalize_state(json.loads((Path(__file__).parents[1] / 'app/demo_seed.json').read_text(encoding='utf-8')))
    day = '2026-11-10'
    state['days'][day] = []
    monkeypatch.setattr(server, 'store', Store(tmp_path / 'report.sqlite3', lambda: state))
    monkeypatch.setattr(exporter, 'template_path', lambda *_: tmp_path / 'missing.docx')
    client = TestClient(server.app)
    url = f'/api/export/{audience}/{day}'
    request = client.get(url, params={'mode': mode, 'preview': 1})
    assert request.status_code == 200
    report = request.json()
    assert report['filename'].startswith('Вторник 10.11.2026') and report['filename'].endswith('.docx')
    saved = base64.b64decode(report['document'], validate=True)

    def render(document, _):
        assert document == saved
        return b'%PDF-example', 'Word'

    monkeypatch.setattr(word_preview, 'render_pdf', render)
    preview = client.get('/api/report-preview/' + report['previewId'])
    assert preview.headers['Content-Type'] == 'application/pdf' and preview.content == b'%PDF-example'
    assert preview.headers['X-Schedule-Preview-Renderer'] == 'Word'
    assert client.get('/api/report-preview/expired').status_code == 404
    direct = client.get(url, params={'mode': mode})
    with ZipFile(BytesIO(saved)) as prepared, ZipFile(BytesIO(direct.content)) as downloaded:
        xml = prepared.read('word/document.xml')
        assert xml == downloaded.read('word/document.xml')
    root = etree.fromstring(xml)
    assert root.xpath('//w:body/w:p//w:t/text()', namespaces=exporter.NS) == ['ВТОРНИК']
    cell = root.findall('.//w:tbl/w:tr', exporter.NS)[1].findall('w:tc', exporter.NS)[1]
    assert (cell.findtext('.//w:t', namespaces=exporter.NS) == '—') == (mode != 'base')
    assert cell.xpath('string(w:tcPr/w:shd/@w:fill)', namespaces=exporter.NS) == (exporter.RED_FILL if mode == 'changes' else '')


def test_helper_waits_checks_hash_and_quotes_paths(signed):
    _,payload,_,_=signed
    script=updates.install_script("C:/O'Brien/update.exe",'C:/School app',123,payload['asset']['sha256'])
    assert "O''Brien" in script and 'Wait-Process -Id 123' in script
    assert 'Get-FileHash' in script and '/UPDATE=1' in script and '/DIR=' in script
    assert 'window-ready.json' in script and '--after-update' in script
    assert 'Remove-Item' not in script and 'http' not in script


def test_ready_marker_identifies_the_opened_desktop_process(tmp_path):
    import os
    from datetime import datetime
    updates.mark_window_ready(tmp_path,'2.26.0')
    ready=json.loads((tmp_path/'window-ready.json').read_text(encoding='utf-8'))
    assert ready['pid']==os.getpid() and ready['version']=='2.26.0'
    assert datetime.fromisoformat(ready['opened']).tzinfo is not None


def test_offline_check_is_bounded_and_opens_installed_version(signed,tmp_path,monkeypatch):
    config,_,_,_=signed
    monkeypatch.setattr(updates,'channel',lambda:config)
    monkeypatch.setattr(updates,'CHECK_SECONDS',.025)
    def slow(*args):time.sleep(.12);raise OSError('offline')
    monkeypatch.setattr(updates,'fetch_manifest',slow)
    started=time.monotonic()
    assert updates.startup_update(tmp_path,tmp_path,tmp_path) is False
    assert time.monotonic()-started<.1


def test_public_bundle_blocks_private_factory_state(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('public_check',Path(__file__).parents[1]/'tools/check_public_bundle.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    folder=tmp_path/'_internal/app';folder.mkdir(parents=True)
    (folder/'empty_seed.json').write_bytes((Path(__file__).parents[1]/'app/empty_seed.json').read_bytes())
    assert module.check_bundle(tmp_path)
    (folder/'seed.json').write_text('{}')
    with pytest.raises(ValueError):module.check_bundle(tmp_path)
