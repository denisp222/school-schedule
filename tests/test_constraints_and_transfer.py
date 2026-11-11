"""Permanent school rules and complete transfers use artificial local projects."""
from copy import deepcopy
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import server,class_hours,ai_planner,ai_service,exporter
from app.assistant_history import AssistantHistory
from app.model import normalize_state,slot_feasible,issues,lessons_for_day
from app.store import Store
from app.portable_backup import export,prepare,restore_files
from app.ai_service import OpenRouter
from test_class_hours import school,DAY


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path)
    monkeypatch.setattr(server,'store',Store(tmp_path/'project.sqlite3',school))
    # No real school template is ever included in this fixture.
    monkeypatch.setattr(exporter,'template_path',lambda d,a:tmp_path/'templates'/f'{d}-{a}.docx')
    return TestClient(server.app)


def test_teacher_one_weekly_slot_is_shared_by_editor_and_solver(client):
    result=client.post('/api/constraints/availability',json={'revision':1,'kind':'teachers','id':'a',
        'allowed':[[4,7]],'maxDays':1,'maxDaily':1})
    assert result.status_code==200,result.text
    state=result.json()['state'];teacher=state['teachers'][0]
    assert len(teacher['unavailable'])==39
    lesson=deepcopy(state['baseLessons'][2])
    assert slot_feasible(state,lesson,4,7,date='2026-11-13',check_rooms=False)
    assert not slot_feasible(state,lesson,4,6,date='2026-11-13',check_rooms=False)
    assert not slot_feasible(state,lesson,1,7,date='2026-11-10',check_rooms=False)


def test_subject_availability_is_checked_for_moves_and_week_generation(client):
    response=client.post('/api/constraints/availability',json={'revision':1,'kind':'subjects','id':'math','allowed':[[2,3]]})
    assert response.status_code==200,response.text
    state=response.json()['state'];lesson=state['baseLessons'][2]
    assert not slot_feasible(state,lesson,2,2,date=DAY)
    assert any(i['code']=='subject_unavailable' for i in issues(state,[lesson],DAY))


def test_general_subject_rules_can_be_changed_and_survive_copy(client):
    r=client.post('/api/constraints/general',json={'revision':1,'rovFirst':False,'technologyPairs':False})
    assert r.status_code==200,r.text
    from app.model import must_be_first
    rov=next(s for s in r.json()['state']['subjects'] if s['id']=='rov')
    assert not must_be_first(rov)
    backup=client.get('/api/backup').json()
    assert next(s for s in backup['subjects'] if s['id']=='rov')['firstMonday'] is False


def test_week_solver_respects_the_same_teacher_and_subject_slots():
    from app.annual import build_week
    blocked=lambda day,period:[{'day':d,'period':p} for d in range(5) for p in range(1,9) if (d,p)!=(day,period)]
    state=normalize_state({'teachers':[{'id':'a','name':'Пример А.','subjectIds':['s'],'unavailable':blocked(4,7),'maxDays':1}],
        'classes':[{'id':'c','name':'8а'}],'subjects':[{'id':'s','name':'Пример','unavailable':blocked(4,7)}],
        'rooms':[{'id':'r','name':'101'}],'plan':[{'id':'p','classIds':['c'],'teacherIds':['a'],'subjectId':'s','roomIds':['r'],'hours':1}],
        'baseLessons':[]})
    result=build_week(state)
    assert result['status']=='ok',result
    assert [(l['day'],l['period']) for l in result['lessons']]==[(4,7)]


def test_manual_class_hour_can_be_second_and_uses_leader_room(client):
    r=client.post('/api/lesson/class-hour',json={'revision':1,'date':DAY,'lessonId':'b2','enabled':True,'roomIds':['r1']})
    assert r.status_code==200,r.text
    event=next(l for l in r.json()['day']['lessons'] if l.get('classHour'))
    assert event['period']==2 and event['roomIds']==['r2']
    assert event['classHour']['roomId']=='r2'
    assert r.json()['state']['classes'][1]['homeroomTeacherId']=='b'
    assert not [i for i in r.json()['day']['issues'] if i['level']=='error']


def test_assistant_selects_third_class_hour_and_keeps_room():
    state=school();action={'type':'class_hour','classId':'one','lessonId':None,'replaceLessonId':None,'period':3}
    raw={'date':DAY,'reply':'Классный час третьим','questions':[],'unsupported':[],'actions':[action]}
    draft,labels=ai_planner.validate_interpretation(raw,state,DAY,'Классный час 6а третьим уроком')
    assert '3-м' in labels[0]
    rows=ai_planner.variants(state,DAY,draft['actions']);assert rows
    for row in rows:
        event=next(l for l in row['after'] if l.get('classHour'))
        assert event['period']==3 and event['roomIds']==['r1']
        assert not ai_planner.condition_problems(state,DAY,row['actions'],row)


def test_absence_at_class_hour_selected_period_cancels_it():
    state=school();class_hours.apply(state,DAY,[{'type':'class_hour','classId':'one','period':3}])
    event=next(l for l in lessons_for_day(state,DAY) if l.get('classHour'))
    state['absences']=[{'id':'away','teacherId':'a','start':DAY,'end':DAY,'first':1,'last':1}]
    assert not class_hours.cancelled_for_absence(state,event,DAY)
    state['absences'][0].update(first=3,last=3)
    assert class_hours.cancelled_for_absence(state,event,DAY)


def test_fixed_class_hour_room_cannot_be_changed():
    state=school();event=class_hours.create(state,DAY,'two',period=2)
    event['roomIds']=['r1']
    assert class_hours.problems(state,event,DAY)


def test_unknown_leader_room_requires_explicit_assignment():
    state=school();state['classes'][0]['homeroomTeacherId']='c'
    with pytest.raises(ValueError,match='кабинет'):
        class_hours.create(state,DAY,'one',period=2)


def test_legacy_class_hour_is_recalculated_in_its_leaders_room():
    from app.repair_constraints import solve_day
    from app.engine import repair_problems
    state=school();class_hours.apply(state,DAY,[{'type':'class_hour','classId':'one'}])
    event=next(l for l in state['days'][DAY] if l.get('classHour'))
    event['classHour'].pop('roomId');event['roomIds']=['r2']
    result=solve_day(state,DAY,allow_room_changes=True)
    assert result
    repaired=next(l for l in result['after'] if l.get('classHour'))
    assert repaired['roomIds']==['r1'] and not repair_problems(state,result)
    bad=deepcopy(result);next(l for l in bad['after'] if l.get('classHour'))['roomIds']=['r2']
    assert any('кабинете классного руководителя' in text for text in repair_problems(state,bad))


def test_full_copy_moves_templates_roles_history_and_encrypted_key(client,tmp_path,monkeypatch):
    key='sk-'+'artificial-example-key-1234567890'
    def protect(value,*,decrypt=False):return value.removeprefix('OLD:') if decrypt else 'NEW:'+value
    monkeypatch.setattr(ai_service,'protect_secret',protect)
    from app.assistant_api import connection
    assistant=connection();assistant._write({'provider':'deepseek','deepseekKey':'OLD:'+key,'monthlyLimitUSD':'1','networkMode':'direct'})
    from docx import Document
    folder=tmp_path/'templates';folder.mkdir()
    doc=Document();doc.add_paragraph('Искусственный шаблон');doc.save(folder/'0-teachers.docx')
    original_doc=(folder/'0-teachers.docx').read_bytes()
    history=AssistantHistory(server.store);thread,turn=history.start(None,DAY,'Искусственный диалог');history.finish(turn,{'reply':'Пример','actions':[]})
    payload=client.post('/api/backup',json={'password':'пароль-копии'});assert payload.status_code==200,payload.text[:100]
    assert key not in payload.text and 'OLD:' not in payload.text
    value=payload.json();assert value['_portableBackup']['encryptedKeys']
    assert len(value['_portableBackup']['snapshots'])==1
    (folder/'0-teachers.docx').unlink();assistant._write({});history.delete(thread)
    result=client.post('/api/import',json={'revision':1,'state':value,'password':'пароль-копии'})
    assert result.status_code==200,result.text[:150]
    assert assistant._read()['deepseekKey']=='NEW:'+key
    assert (folder/'0-teachers.docx').read_bytes()==original_doc
    assert history.get(thread)['turns'][0]['response']['reply']=='Пример'
    assert all(c.get('homeroomTeacherId') for c in result.json()['state']['classes'])
    assert all(t.get('homeroomRoomId') for t in result.json()['state']['teachers'][:2])


def test_wrong_backup_password_never_changes_project(client,monkeypatch):
    monkeypatch.setattr(ai_service,'protect_secret',lambda value,**kw:'sk-'+'artificial-key-1234567890')
    from app.assistant_api import connection
    connection()._write({'provider':'deepseek','deepseekKey':'encrypted'})
    backup=client.post('/api/backup',json={'password':'correct-password'}).json()
    before=server.store.read();settings=connection().path.read_bytes()
    r=client.post('/api/import',json={'revision':1,'state':backup,'password':'incorrect-password'})
    assert r.status_code==422 and 'пароль' in r.json()['detail']
    assert server.store.read()==before and connection().path.read_bytes()==settings


def test_legacy_copy_still_loads_and_does_not_touch_connection(client):
    legacy=server.store.read()['state']
    r=client.post('/api/import',json={'revision':1,'state':legacy})
    assert r.status_code==200,r.text


def test_backup_does_not_allow_template_path_traversal(client):
    backup=client.get('/api/backup').json();before=server.store.read()
    backup['_portableBackup']['templates']={'../bad.docx':''}
    r=client.post('/api/import',json={'revision':1,'state':backup})
    assert r.status_code==422 and server.store.read()==before


def test_file_restore_rolls_back_when_database_operation_fails(tmp_path):
    target=tmp_path/'assistant-connection.json';target.write_bytes(b'old')
    with pytest.raises(RuntimeError):
        with restore_files(tmp_path,{'assistant-connection.json':b'new','templates/test.docx':b'new'}):
            raise RuntimeError('simulated transaction conflict')
    assert target.read_bytes()==b'old' and not (tmp_path/'templates/test.docx').exists()


def test_delete_conversation_removes_turns_but_keeps_timetable(client):
    history=AssistantHistory(server.store);thread,turn=history.start(None,DAY,'Удалить искусственный диалог')
    before=server.store.read()
    r=client.post(f'/api/assistant/conversations/{thread}/delete',json={});assert r.status_code==200
    assert server.store.read()==before and not history.list()
    with server.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM assistant_turns').fetchone()[0]==0
