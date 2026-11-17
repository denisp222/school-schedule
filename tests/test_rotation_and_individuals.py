"""Rotating weeks, one-to-one sessions and room purposes on synthetic data."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from zipfile import ZipFile
import json
import pytest
from fastapi.testclient import TestClient
from app import commitments,model,rotation,server
from app.store import Store
from test_annual_and_update_flow import planned_school


def rotating():
    state=planned_school()
    state['school']['rotation']={'length':4,'anchor':'2026-11-09'}
    state['rotationWeeks']={str(w):deepcopy(state['baseLessons']) for w in range(1,5)}
    state['individualLearners']=[{'id':'pupil','name':'Индивидуальный ученик 1','classId':'one','allowGaps':True}]
    return state


def session(**fields):
    return {'id':'session','kind':'individual','label':'Индивидуальный ученик 1',
        'learnerId':'pupil','subjectId':'math','teacherId':'a','roomId':'',
        'weekday':1,'first':2,'last':2,'cycleWeeks':[1,3],**fields}


@pytest.fixture
def client(tmp_path,monkeypatch):
    store=Store(tmp_path/'cycle.sqlite3',rotating)
    monkeypatch.setattr(server,'store',store)
    monkeypatch.setattr(server,'DATA',tmp_path)
    return TestClient(server.app),store


def test_rotation_is_calendar_based_with_third_week_start_and_wrap():
    state=rotating()
    for day,w in [('2026-11-23',3),('2026-11-27',3),('2026-11-30',4),('2026-12-07',1),('2026-12-14',2),('2027-01-04',1)]:
        assert rotation.number(state,day)==w
    state['rotationWeeks']['3'][2]['note']='Третья неделя'
    assert any(l.get('note')=='Третья неделя' for l in model.lessons_for_day(state,'2026-11-25'))
    assert not any(l.get('note')=='Третья неделя' for l in model.lessons_for_day(state,'2026-12-09'))


def test_old_edition_does_not_inherit_new_cycle_or_individual_occupancy():
    state=rotating();old=deepcopy(state['baseLessons'])
    state['baseVersions']=[{'start':'2026-09-01','lessons':old,'externalActivities':[],'rotation':None},
                          {'start':'2026-11-23','lessons':deepcopy(old),**rotation.snapshot(state)}]
    state['externalActivities']=[session(start='2026-11-23')]
    state['rotationWeeks']['3'][2]['note']='Новая редакция'
    assert model.lessons_for_day(state,'2026-11-18')==[l for l in old if l['day']==2]
    assert commitments.matching(state,'2026-11-17')==[]
    assert commitments.matching(state,'2026-11-24')
    assert rotation.config(state,'2026-11-18') is None


def test_two_different_cycle_weeks_can_use_same_teacher_room_and_learner():
    state=rotating()
    state['externalActivities']=[session(roomId='r1'),session(id='second',cycleWeeks=[2,4],roomId='r1')]
    commitments.validate(state)
    assert commitments.matching(state,'2026-11-24')[0]['id']=='session'
    assert commitments.matching(state,'2026-12-01')[0]['id']=='second'
    state['externalActivities'][1]['cycleWeeks']=[3]
    with pytest.raises(ValueError,match='пересекается'):commitments.validate(state)


def test_one_learner_cannot_attend_two_different_teachers_at_once():
    state=rotating();state['externalActivities']=[session(),session(id='second',teacherId='b')]
    with pytest.raises(ValueError,match='ученика'):commitments.validate(state)


def test_eighth_period_is_an_explicit_individual_exception_only():
    state=rotating();state['externalActivities']=[session(first=8,last=8)]
    with pytest.raises(ValueError,match='1–7'):commitments.validate(state)
    state['externalActivities'][0]['allowEighth']=True;commitments.validate(state)
    state['externalActivities'][0].update(kind='primary',learnerId='')
    with pytest.raises(ValueError,match='1–7'):commitments.validate(state)
    regular=deepcopy(state['baseLessons'][2]);regular['day']=1
    assert not model.period_allowed(state,regular,8,1)


def test_known_individual_gaps_do_not_create_regular_class_windows():
    state=rotating();state['externalActivities']=[session(first=1,last=1),session(id='late',first=8,last=8,allowEighth=True)]
    commitments.validate(state)
    assert not [r for r in model.issues(state,[],day='2026-11-24') if r['code']=='gap']


def test_absent_teacher_cancels_individual_session_and_frees_its_room():
    state=rotating();state['externalActivities']=[session(roomId='r1')]
    state['absences']=[{'id':'absence','teacherId':'a','start':'2026-11-24','end':'2026-11-24','first':2,'last':2}]
    assert not commitments.teacher_busy(state,'a','2026-11-24',2)
    assert not commitments.room_busy(state,'r1','2026-11-24',2)
    assert commitments.matching(state,'2026-11-24',include_cancelled=True)[0]['cancelled']
    assert commitments.teacher_busy(state,'a','2026-12-08',2)


def test_draft_week_edit_is_scoped_and_does_not_change_other_weeks_or_live(client):
    api,store=client;before=store.read()['state']
    r=api.post('/api/annual/start',json={'revision':1});assert r.status_code==200
    r=api.post('/api/annual/move',headers={'X-Schedule-Cycle-Week':'3'},json={'revision':2,'lessonId':'a3','targetDate':'2026-11-12','period':1})
    assert r.status_code==200,r.text
    state=store.read()['state'];draft=state['annualDraft']['state']
    assert state['baseLessons']==before['baseLessons']
    assert draft['rotationWeeks']['1']==before['rotationWeeks']['1']
    assert draft['rotationWeeks']['2']==before['rotationWeeks']['2']
    assert next(l for l in draft['rotationWeeks']['3'] if l['id']=='a3')['day']==3
    assert next(l for l in r.json()['state']['baseLessons'] if l['id']=='a3')['day']==3


def test_learner_and_cycle_fields_persist_and_invalid_inputs_are_atomic(client):
    api,store=client
    r=api.post('/api/extras/upsert',json={'revision':1,'week':'2026-11-23','record':session()})
    assert r.status_code==200,r.text
    before=store.read()
    r=api.post('/api/extras/cycle',json={'revision':2,'anchor':'2026-11-10'})
    assert r.status_code==422 and store.read()==before
    reopened=Store(store.path,lambda:None).read()
    assert reopened['state']['individualLearners']==before['state']['individualLearners']
    assert reopened['state']['rotationWeeks']==before['state']['rotationWeeks']


def test_day_edit_is_one_date_and_collision_does_not_corrupt_template(client):
    api,store=client
    store.mutate(1,'Пример',lambda s:s['externalActivities'].append(session()))
    r=api.post('/api/extras/day',json={'revision':2,'date':'2026-11-24','record':session(first=4,last=4)})
    assert r.status_code==200,r.text
    state=store.read()['state']
    assert commitments.matching(state,'2026-11-24')[0]['first']==4
    assert commitments.matching(state,'2026-12-08')[0]['first']==2
    # Wednesday at1alreadyhasthisteacherandroominthemaintimetable.
    r=api.post('/api/extras/day',json={'revision':3,'date':'2026-11-25','record':session(weekday=2,first=1,last=1,roomId='r1')})
    assert r.status_code==422 and store.read()['revision']==3


def test_special_rooms_need_appropriate_class_and_explicit_permission():
    from app.room_policy import allowed,available_for_general_use
    state=rotating();room={'id':'special','name':'205','usePolicy':'manual','manualClassIds':['one']}
    lesson=deepcopy(state['baseLessons'][2])
    assert not allowed(state,lesson,room) and not available_for_general_use(room)
    lesson['roomExceptions']=['special'];assert allowed(state,lesson,room)
    lesson['classIds']=['two'];assert not allowed(state,lesson,room)
    workshop={'id':'workshop','name':'102','usePolicy':'restricted','allowedTeacherIds':['b'],'subjectIds':['tech']}
    assert not allowed(state,lesson,workshop)


def test_word_reports_include_primary_and_individual_lessons_without_addresses(tmp_path,monkeypatch):
    from app import exporter
    from app.individual_report import export
    state=rotating();state['externalActivities']=[session(roomId='r1'),
        session(id='primary',kind='primary',label='2а',learnerId='',subjectId='',teacherId='b',first=5,last=5,roomId='r2')]
    monkeypatch.setattr(exporter,'template_path',lambda *args:tmp_path/'missing.docx')
    content=exporter.export_docx(state,'2026-11-24','teachers')
    with ZipFile(BytesIO(content)) as z:xml=z.read('word/document.xml').decode()
    assert 'инд 6а' in xml and 'Индивидуальный ученик 1' not in xml and '2а' in xml
    assert 'Индивидуальный ученик 1' not in ZipFile(BytesIO(exporter.export_docx(state,'2026-12-01','teachers'))).read('word/document.xml').decode()
    with ZipFile(BytesIO(export(state,date(2026,11,23)))) as z:xml=z.read('word/document.xml').decode()
    assert '1-я неделя' in xml and '4-я неделя' in xml and 'Математика' in xml
    assert 'адрес' not in xml.lower()


def test_individual_names_are_not_added_to_paid_model_context():
    from app.ai_planner import messages_for
    state=rotating();state['individualLearners'][0]['name']='Личная карточка ученика'
    state['externalActivities']=[session(label='Личная карточка ученика')]
    messages=messages_for(state,'2026-11-24','Измени расписание',[],full_context=True)
    assert 'Личная карточка ученика' not in json.dumps(messages,ensure_ascii=False)


def test_individual_room_cannot_be_used_by_a_whole_class():
    from app.room_policy import allowed,available_for_general_use
    state=rotating();room={'id':'speech','name':'Логопед','usePolicy':'individual','individualPriority':0}
    assert not allowed(state,state['baseLessons'][0],room)
    assert allowed(state,{'learnerId':'pupil','classIds':['one']},room)
    assert not available_for_general_use(room)


@pytest.mark.parametrize('bad',[[{}],[True],[],[1,1]])
def test_malformed_cycle_week_has_friendly_validation(bad):
    state=rotating();state['externalActivities']=[session(cycleWeeks=bad)]
    with pytest.raises(ValueError,match='недели'):commitments.validate(state)


def test_individual_daily_change_and_absence_are_visible_in_payload_and_load(client):
    api,store=client
    store.mutate(1,'Пример',lambda s:s['externalActivities'].append(session(roomId='r1')))
    r=api.post('/api/extras/day',json={'revision':2,'date':'2026-11-24','record':session(roomId='r1',first=4,last=4)})
    assert r.status_code==200,r.text
    day=api.get('/api/day/2026-11-24').json()
    assert day['cycleWeek']==3 and day['externalChanges'][0]['after']['first']==4
    report=api.get('/api/reports/2026-11-24').json()
    teacher=next(r for r in report['teachers'] if r['id']=='a')
    assert teacher['individual']==1 and teacher['total']==teacher['week']+1
    store.mutate(3,'Отсутствие',lambda s:s['absences'].append({'id':'absent','teacherId':'a','start':'2026-11-24','end':'2026-11-24','first':1,'last':8}))
    state=store.read()['state']
    assert commitments.changes(state,'2026-11-24')[0]['after']['cancelled']
    assert commitments.week_hours(state,'2026-11-24')['individual']['a']==0
