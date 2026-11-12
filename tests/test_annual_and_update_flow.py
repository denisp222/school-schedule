"""Annual drafts and user-approved updates, with artificial local data."""
from copy import deepcopy
import json,time,threading
from pathlib import Path
import httpx,pytest
from fastapi.testclient import TestClient
from app import server,updates
from app.store import Store
from app.annual_workspace import DraftStore
from app.update_api import UpdateManager
from app.model import lessons_for_day,normalize_state
from test_class_hours import school
from test_updates import signed
from collections import Counter

def planned_school():
    state=school();counts=Counter((tuple(l['classIds']),tuple(l['teacherIds']),l['subjectId'],tuple(l['roomIds'])) for l in state['baseLessons'])
    state['plan']=[{'id':f'p{i}','classIds':list(c),'teacherIds':list(t),'subjectId':s,'roomIds':list(r),'hours':n}
        for i,((c,t,s,r),n) in enumerate(counts.items())]
    return normalize_state(state)

DRAFT={'X-Schedule-Workspace':'draft'}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'store',Store(tmp_path/'project.sqlite3',planned_school))
    monkeypatch.setattr(server,'DATA',tmp_path)
    from app import exporter
    monkeypatch.setattr(exporter,'template_path',lambda *a:tmp_path/'missing.docx')
    return TestClient(server.app)


def test_draft_plan_and_lessons_do_not_change_live_project(client):
    before=client.get('/api/state').json()
    started=client.post('/api/annual/start',json={'revision':before['revision']});assert started.status_code==200,started.text
    rev=started.json()['revision']
    edit=client.post('/api/entity/plan',headers=DRAFT,json={'revision':rev,'record':{'id':'new-plan','classIds':['one'],'teacherIds':['a'],'subjectId':'math','hours':2,'roomIds':['r1']}})
    assert edit.status_code==200,edit.text
    draft=client.get('/api/state',headers=DRAFT).json()
    live=client.get('/api/state').json()
    assert draft['state']['plan']!=before['state']['plan']
    assert live['state']['plan']==before['state']['plan'] and live['state']['baseLessons']==before['state']['baseLessons']
    assert live['state']['annualDraft']['state']['plan']==draft['state']['plan']


def test_draft_supports_cross_day_moves_and_rejects_collision(client):
    r=client.post('/api/annual/start',json={'revision':1}).json()
    moved=client.post('/api/annual/move',json={'revision':r['revision'],'lessonId':'a3','targetDate':'2026-11-12','period':1})
    assert moved.status_code==200,moved.text
    assert next(l for l in moved.json()['state']['baseLessons'] if l['id']=='a3')['day']==3
    live=client.get('/api/state').json();assert next(l for l in live['state']['baseLessons'] if l['id']=='a3')['day']==2
    bad=client.post('/api/annual/move',json={'revision':live['revision'],'lessonId':'a2','targetDate':'2026-11-11','period':1})
    assert bad.status_code==422
    assert client.get('/api/state').json()['revision']==live['revision']


def test_draft_manual_cell_upsert_is_available_and_scoped(client):
    r=client.post('/api/annual/start',json={'revision':1}).json()
    lesson=deepcopy(next(l for l in r['state']['baseLessons'] if l['id']=='a3'));lesson.update(day=3,period=1)
    # A source-day removal and target-day insertion use the dedicated drag API;
    # an ordinary cell editor remains scoped to its weekday.
    lesson['day']=2;lesson['period']=3;lesson['note']='Искусственная правка'
    saved=client.post('/api/lesson',headers=DRAFT,json={'revision':r['revision'],'date':'2026-11-11','scope':'base','lesson':lesson,'remove':False})
    assert saved.status_code==200,saved.text
    assert next(l for l in saved.json()['state']['baseLessons'] if l['id']=='a3')['note']=='Искусственная правка'
    assert not next(l for l in server.store.read()['state']['baseLessons'] if l['id']=='a3').get('note')
    forbidden=client.post('/api/assistant/interpret',headers=DRAFT,json={})
    assert forbidden.status_code==422


def test_publish_is_dated_and_preserves_previous_week(client):
    before=server.store.read()['state'];client.post('/api/annual/start',json={'revision':1})
    def move_week(state):
        for lesson in state['baseLessons']:
            if lesson['day']==2:lesson['day']=3
    draft=DraftStore(server.store).mutate(2,'Поменяли среду на четверг',move_week)
    result=client.post('/api/annual/publish',json={'revision':draft['revision'],'start':'2026-11-16','keepDays':True})
    assert result.status_code==200,result.text
    state=result.json()['state']
    assert lessons_for_day(state,'2026-11-11')==lessons_for_day(before,'2026-11-11')
    assert not lessons_for_day(state,'2026-11-18')
    assert len(lessons_for_day(state,'2026-11-19'))==6
    assert len(state['baseVersions'])==2 and 'annualDraft' not in state


def test_future_day_override_is_kept_or_explicitly_reset(client):
    def add_day(state):state['days']['2026-11-18']=lessons_for_day(state,'2026-11-18')
    server.store.mutate(1,'Будущая дата',add_day)
    client.post('/api/annual/start',json={'revision':2})
    result=client.post('/api/annual/publish',json={'revision':3,'start':'2026-11-16','keepDays':False})
    assert result.status_code==200,result.text
    assert '2026-11-18' not in result.json()['state']['days']


def test_reset_earlier_day_uses_its_own_dated_week(client):
    before=server.store.read()['state']
    client.post('/api/annual/start',json={'revision':1})
    def move(state):
        for lesson in state['baseLessons']:
            if lesson['day']==2:lesson['day']=3
    draft=DraftStore(server.store).mutate(2,'Новая неделя',move)
    published=client.post('/api/annual/publish',json={'revision':draft['revision'],'start':'2026-11-16','keepDays':True}).json()
    def override(state):
        day='2026-11-11';state['dayBases'][day]=lessons_for_day(state,day)
        state['days'][day]=[]
    changed=server.store.mutate(published['revision'],'Правка прежней даты',override)
    result=client.post('/api/day/reset',json={'revision':changed['revision'],'date':'2026-11-11'})
    assert result.status_code==200,result.text
    state=result.json()['state']
    assert lessons_for_day(state,'2026-11-11')==lessons_for_day(before,'2026-11-11')
    assert '2026-11-11' not in state['days'] and '2026-11-11' not in state['dayBases']


def test_draft_clear_preserves_plan_and_live_week(client):
    before=server.store.read()['state'];r=client.post('/api/annual/start',json={'revision':1}).json()
    result=client.post('/api/annual/clear',json={'revision':r['revision']})
    assert result.status_code==200,result.text
    assert not result.json()['state']['baseLessons']
    assert result.json()['state']['plan']==before['plan']
    assert server.store.read()['state']['baseLessons']==before['baseLessons']


def wait_for(manager,stage):
    deadline=time.monotonic()+5
    while manager.status()['stage']!=stage:
        assert time.monotonic()<deadline,manager.status();time.sleep(.01)


def test_update_check_never_downloads_or_installs_without_approval(signed,tmp_path,monkeypatch):
    config,payload,envelope,body=signed
    # The signed fixture may use a higher future version than the installed app.
    monkeypatch.setattr(updates,'channel',lambda:config)
    monkeypatch.setattr(updates,'fetch_manifest',lambda c,cfg:payload)
    downloads=[];installs=[]
    monkeypatch.setattr(updates,'download',lambda *a:downloads.append(a))
    monkeypatch.setattr(updates,'launch_installer',lambda *a:installs.append(a))
    manager=UpdateManager(tmp_path,tmp_path,tmp_path,lambda:None)
    manager.check();wait_for(manager,'available')
    assert not downloads and not installs
    monkeypatch.setattr(server.app.state,'update_manager',manager,raising=False)
    client=TestClient(server.app)
    assert client.post('/api/updates/download',json={}).status_code==422
    assert client.post('/api/updates/install',json={}).status_code==422


def test_download_requires_second_explicit_install_and_keeps_app_open(signed,tmp_path,monkeypatch):
    config,payload,envelope,body=signed
    setup=tmp_path/'setup.exe';setup.write_bytes(body)
    monkeypatch.setattr(updates,'fetch_manifest',lambda *a:payload)
    monkeypatch.setattr(updates,'channel',lambda:config)
    monkeypatch.setattr(updates,'download',lambda *a:setup)
    closes=[];installs=[]
    monkeypatch.setattr(updates,'backup_before_update',lambda *a:None)
    monkeypatch.setattr(updates,'launch_installer',lambda *a:installs.append(a))
    manager=UpdateManager(tmp_path,tmp_path,tmp_path,lambda:closes.append(True))
    manager.check();wait_for(manager,'available');manager.download();wait_for(manager,'ready')
    assert not closes and not installs
    manager.install();assert installs and manager.attempt.exists()


def test_failed_update_never_retries_automatically_on_next_launch(tmp_path):
    (tmp_path/'installed.json').write_text('{}');(tmp_path/'update-attempt.json').write_text('{"version":"999.0.0"}')
    manager=UpdateManager(tmp_path,tmp_path,tmp_path,lambda:None)
    assert manager.check(automatic=True)['stage']=='idle'
    assert 'Предыдущее' in manager.status()['message']


def test_update_helper_resets_frozen_bootloader_environment(monkeypatch):
    monkeypatch.setenv('_PYI_PARENT_PROCESS_LEVEL','1');monkeypatch.setenv('_PYI_APPLICATION_HOME_DIR','old-runtime')
    env=updates.clean_environment()
    assert not any(k.startswith('_PYI_') for k in env) and env['PYINSTALLER_RESET_ENVIRONMENT']=='1'
    script=updates.install_script('setup.exe','C:/School',10,'a'*64)
    assert 'PYINSTALLER_RESET_ENVIRONMENT' in script and "EnvironmentVariables.Remove" in script


def test_keep_future_overrides_preserves_their_old_baseline(client):
    old=lessons_for_day(server.store.read()['state'],'2026-11-18')
    server.store.mutate(1,'Дата',lambda s:s['days'].update({'2026-11-18':deepcopy(old)}))
    client.post('/api/annual/start',json={'revision':2})
    DraftStore(server.store).mutate(3,'Перестановка',lambda s:[l.update(day=3) for l in s['baseLessons'] if l['day']==2] and None)
    r=client.post('/api/annual/publish',json={'revision':4,'start':'2026-11-16','keepDays':True})
    assert r.status_code==200,r.text
    assert lessons_for_day(r.json()['state'],'2026-11-18')==old
    assert r.json()['state']['dayBases']['2026-11-18']==old


def test_unallocated_plan_requires_explicit_acknowledgement(client):
    client.post('/api/annual/start',json={'revision':1})
    def hours(state):state['plan'][0]['hours']+=1
    DraftStore(server.store).mutate(2,'Часы',hours)
    body={'revision':3,'start':'2026-11-16','keepDays':True}
    assert client.post('/api/annual/publish',json=body).status_code==422
    assert client.post('/api/annual/publish',json={**body,'acceptIncomplete':True}).status_code==200


def test_full_backup_keeps_draft_and_published_versions(client):
    client.post('/api/annual/start',json={'revision':1})
    published=client.post('/api/annual/publish',json={'revision':2,'start':'2026-11-16','keepDays':True})
    assert published.status_code==200,published.text
    client.post('/api/annual/start',json={'revision':3})
    copy=client.get('/api/backup').json()
    assert copy['_portableBackup']['version']==2
    assert copy['annualDraft'] and len(copy['baseVersions'])==2
    assert 'packedState' in copy['_portableBackup']['snapshots'][0]
    restored=client.post('/api/import',json={'revision':4,'state':copy})
    assert restored.status_code==200,restored.text
    assert len(restored.json()['state']['baseVersions'])==2 and restored.json()['state']['annualDraft']


def test_successful_target_version_clears_failed_attempt_marker(tmp_path):
    (tmp_path/'update-attempt.json').write_text('{"version":"0.0.1"}')
    manager=UpdateManager(tmp_path,tmp_path,tmp_path,lambda:None)
    assert not manager.attempt.exists()
