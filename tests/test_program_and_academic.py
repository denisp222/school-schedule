"""Artificial data only: application actions, pupils and simultaneous streams."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from app import server,assistant_api,academic
from app.store import Store
from app.model import normalize_state,issues
from test_annual_and_update_flow import planned_school

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path)
    monkeypatch.setattr(server,'store',Store(tmp_path/'school.sqlite3',planned_school))
    return TestClient(server.app)

def test_program_help_is_local_and_has_navigation(client,monkeypatch):
    class Never:
        def interpret(self,*a,**k):raise AssertionError('Help must not call a paid model')
    monkeypatch.setattr(assistant_api,'connection',lambda:Never())
    r=client.post('/api/assistant/interpret',json={'revision':1,'date':'2026-11-16','message':'Как сделать резервную копию?'})
    assert r.status_code==200,r.text
    assert r.json()['program']['links'][0]['page']=='history'
    assert server.store.read()['revision']==1

def test_load_query_does_not_call_model(client,monkeypatch):
    monkeypatch.setattr(assistant_api,'connection',lambda:None)
    r=client.post('/api/assistant/interpret',json={'revision':1,'date':'2026-11-16','message':'Покажи нагрузку учителей'})
    assert r.status_code==200,r.text
    assert 'в плане' in r.json()['reply'] and r.json()['program']['previewId'] is None

def test_catalog_change_requires_confirmation_and_stale_protection(client,monkeypatch):
    before=server.store.read()['state']
    class Fake:
        def interpret(self,*a,**k):return {'reply':'Предлагаю назначить руководителя.','page':'directory','changes':[{'kind':'classes','id':'one','field':'homeroomTeacherId','valueJSON':'"b"'}]},'fake'
    monkeypatch.setattr(assistant_api,'connection',lambda:Fake())
    r=client.post('/api/assistant/interpret',json={'revision':1,'date':'2026-11-16','message':'Измени классного руководителя класса'})
    assert r.status_code==200,r.text
    token=r.json()['program']['previewId'];assert token
    assert server.store.read()['state']==before
    applied=client.post('/api/assistant/program/apply',json={'revision':1,'previewId':token})
    assert applied.status_code==200,applied.text
    assert next(c for c in applied.json()['state']['classes'] if c['id']=='one')['homeroomTeacherId']=='b'
    assert client.post('/api/assistant/program/apply',json={'revision':1,'previewId':token}).status_code==409

def test_unknown_program_field_cannot_change_project(client,monkeypatch):
    class Fake:
        def interpret(self,*a,**k):return {'reply':'test','page':'settings','changes':[{'kind':'teachers','id':'a','field':'secret','valueJSON':'1'}]},'fake'
    monkeypatch.setattr(assistant_api,'connection',lambda:Fake())
    r=client.post('/api/assistant/interpret',json={'revision':1,'date':'2026-11-16','message':'Измени настройки учителя'})
    assert r.status_code==422 and server.store.read()['revision']==1

def test_pupils_exam_export_and_idempotent_csv_import(client):
    csv='ФИО;Класс;Экзамены\nПример ученика;6а;Математика\n'
    r=client.post('/api/academic/students/import',json={'revision':1,'csv':csv});assert r.status_code==200,r.text
    r=client.post('/api/academic/students/import',json={'revision':r.json()['revision'],'csv':csv});assert r.status_code==200,r.text
    assert len(r.json()['state']['students'])==1
    doc=client.get('/api/academic/exams?format=docx&classId=one&subjectId=math')
    assert doc.status_code==200
    with ZipFile(BytesIO(doc.content)) as package:assert 'Пример ученика' in package.read('word/document.xml').decode()
    bad=client.post('/api/entity/students',json={'revision':r.json()['revision'],'record':{'name':'test','classId':'one','examSubjects':['missing']}})
    assert bad.status_code==422

def test_synchronised_plan_validates_and_solver_aligns_slots():
    from app.annual import _build_week
    state=planned_school()
    for p in state['plan']:
        if (p['classIds']==['one'] and p['teacherIds']==['c'] or p['classIds']==['two'] and p['teacherIds']==['b']) and p['subjectId']=='math':p['syncGroup']='Language link'
    result=_build_week(state,local=False,seconds=3)
    assert result['status']=='ok',result
    assert not academic.sync_issues(state,result['lessons'])
    moved=deepcopy(result['lessons']);lesson=next(l for l in moved if l.get('planId') in {p['id'] for p in state['plan'] if p.get('syncGroup')})
    lesson['day']=(lesson['day']+1)%5
    assert academic.sync_issues(state,moved)

def test_daily_solver_honours_stream_links():
    from app.repair_constraints import solve_day
    state=planned_school()
    for p in state['plan']:
        if (p['classIds']==['one'] and p['teacherIds']==['c'] or p['classIds']==['two'] and p['teacherIds']==['b']) and p['subjectId']=='math':p['syncGroup']='Language link'
    result=solve_day(state,'2026-11-11',_seconds=2,allow_room_changes=False)
    assert result and result['status'] in ('ok','unchanged'),result
    assert not academic.sync_issues(state,result['after'])


def test_chronograph_html_preview_and_apply_are_separate(client):
    from app.chronograph_import import convert
    def html(rows):return '<html><body><table>'+''.join('<tr>'+''.join('<td>'+str(c)+'</td>' for c in r)+'</tr>' for r in rows)+'</table></body></html>'
    reports={'teacher-details.html':html([['№','ФИО','Предметы'],[1,'Примеров А.А.','Математика']]),
      'room-details.html':html([['№','Кабинет'],[1,'101']]),
      'load-teachers.html':html([['№','ФИО','Норма','Предмет','Итого','6а'],[1,'Примеров А.А.',1,'Матем',1,1]]),
      'week-teachers.html':html([[1,'Примеров А.А.','6а(Матем)101',*['']*39]])}
    state=convert(reports)
    assert len(state['baseLessons'])==1 and len(state['plan'])==1
    before=server.store.read()['state']
    preview=client.post('/api/chronograph/preview',json={'revision':1,'reports':reports})
    assert preview.status_code==200,preview.text
    assert server.store.read()['state']==before
    applied=client.post('/api/chronograph/apply',json={'revision':1,'previewId':preview.json()['previewId']})
    assert applied.status_code==200,applied.text
    assert len(applied.json()['state']['baseLessons'])==1
    assert client.post('/api/chronograph/apply',json={'revision':1,'previewId':preview.json()['previewId']}).status_code==409


def test_broken_import_never_changes_live_data(client):
    r=client.post('/api/chronograph/preview',json={'revision':1,'reports':{}})
    assert r.status_code==422 and server.store.read()['revision']==1


def test_group_plan_rows_do_not_merge_and_old_dates_keep_old_links():
    state=planned_school()
    first=deepcopy(state['plan'][0]);first['id']='group-a';first['groupIndex']=0;first['hours']=1
    second=deepcopy(first);second['id']='group-b';second['groupIndex']=1
    state['plan']=[first,second];state['baseLessons']=[]
    state=normalize_state(state)
    assert len(state['plan'])==2
    original=planned_school();old_plan=deepcopy(original['plan'])
    for p in original['plan']:
        if p['subjectId']=='math':p['syncGroup']='Future link'
    original['baseVersions']=[{'start':'2026-09-01','lessons':deepcopy(original['baseLessons']),'plan':old_plan}]
    assert not academic.sync_issues(original,original['baseLessons'],'2026-11-11')
