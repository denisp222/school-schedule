"""Class-hour exceptions use artificial teachers and preserve the annual plan."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from app import ai_planner,class_hours,server
from app.model import normalize_state,validate_state,lessons_for_day,issues,StateError,teacher_hours
from app.store import Store

DAY='2026-11-11'


def school():
    def lesson(ident,day,period,cid,tid,sid='math',room='r1'):
        return {'id':ident,'day':day,'period':period,'classIds':[cid],
                'teacherIds':[tid],'subjectId':sid,'roomIds':[room]}
    return normalize_state({'teachers':[{'id':t,'name':name,'subjectIds':['math','rov','tech']} for t,name in
        [('a','Примеров А.А.'),('b','Образцова Б.Б.'),('c','Учитель В.В.')]],
        'classes':[{'id':'one','name':'6а','size':20},{'id':'two','name':'6б','size':20}],
        'subjects':[{'id':'math','name':'Математика'},{'id':'rov','name':'Разговоры о важном'},
                    {'id':'tech','name':'Технология'}],
        'rooms':[{'id':'r1','name':'101','capacity':25,'subjectIds':['math','rov']},
                 {'id':'r2','name':'102','capacity':25,'subjectIds':['math','rov']}],
        'baseLessons':[lesson('rov-a',0,1,'one','a','rov'),lesson('rov-b',0,1,'two','b','rov','r2'),
          lesson('a1',2,1,'one','a'),lesson('a2',2,2,'one','c'),lesson('a3',2,3,'one','b'),
          lesson('b1',2,1,'two','c',room='r2'),lesson('b2',2,2,'two','b',room='r2'),
          lesson('b3',2,3,'two','a',room='r2')]})


def action(cid='one',lesson=None):return {'type':'class_hour','classId':cid,'lessonId':lesson,'replaceLessonId':None}


def raw(actions):return {'date':DAY,'reply':'Классный час','questions':[],'unsupported':[],'actions':actions}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'store',Store(tmp_path/'project.sqlite3',school))
    return TestClient(server.app)


def test_leadership_comes_from_base_monday_and_can_be_overridden():
    state=school()
    assert class_hours.leader_map(state)=={'one':'a','two':'b'}
    state['classes'][0]['homeroomTeacherId']='c'
    assert class_hours.leader_map(state)['one']=='c'
    state['classes'][0]['homeroomTeacherId']=''
    assert class_hours.leader_map(state)['one']==''


def test_installer_defaults_fill_only_missing_legacy_roles_with_matching_people(monkeypatch):
    state=school()
    state['baseLessons']=[l for l in state['baseLessons'] if l['subjectId']!='rov']
    for c in state['classes']:c.pop('homeroomTeacherId',None)
    expected=class_hours._name(state['teachers'][0]['name'])
    monkeypatch.setattr(class_hours,'_factory_leaders',lambda:{'6а':expected})
    assert class_hours.leader_map(state)['one']=='a'
    state['teachers'][0]['name']='Другой человек'
    assert class_hours.leader_map(state)['one']==''
    state['classes'][0]['homeroomTeacherId']='c'
    assert class_hours.leader_map(state)['one']=='c'


def test_manual_conversion_and_restore_preserve_time_teacher_room_and_annual_data(client):
    before=server.store.read()['state']
    response=client.post('/api/lesson/class-hour',json={'revision':1,'date':DAY,'lessonId':'a1','enabled':True})
    assert response.status_code==200,response.text
    saved=response.json();event=next(l for l in saved['day']['lessons'] if l['id']=='a1')
    assert (event['period'],event['teacherIds'],event['roomIds'])==(1,['a'],['r1'])
    assert event['subjectId']==class_hours.SUBJECT_ID and event['classHour']['date']==DAY
    assert saved['state']['baseLessons']==before['baseLessons'] and saved['state']['plan']==before['plan']
    assert lessons_for_day(saved['state'],'2026-11-18')==lessons_for_day(before,'2026-11-18')
    assert not [i for i in saved['day']['issues'] if i['level']=='error']
    restored=client.post('/api/lesson/class-hour',json={'revision':2,'date':DAY,'lessonId':'a1','enabled':False})
    assert restored.status_code==200,restored.text
    assert lessons_for_day(restored.json()['state'],DAY)==lessons_for_day(before,DAY)
    assert not restored.json()['state']['assistantConditions'][DAY]


@pytest.mark.parametrize('lesson_id',['b1','a2'])
def test_manual_rename_rejects_wrong_teacher_or_period_without_mutating(client,lesson_id):
    original=server.store.read()
    response=client.post('/api/lesson/class-hour',json={'revision':1,'date':DAY,'lessonId':lesson_id,'enabled':True})
    assert response.status_code==422,response.text
    assert server.store.read()==original


def test_local_batch_preview_and_apply_use_class_leaders_without_ai(client):
    before=server.store.read()
    response=client.post('/api/assistant/class-hour-preview',json={'revision':1,'date':DAY,'classIds':['one','two']})
    assert response.status_code==200,response.text
    rows=response.json()['variants'];assert rows
    assert server.store.read()==before
    events=[l for l in rows[0]['after'] if l.get('classHour')]
    assert {(l['classIds'][0],l['teacherIds'][0],l['period']) for l in events}=={('one','a',1),('two','b',1)}
    assert rows[0]['stats']['classGapsAfter']==0 and rows[0]['stats']['classHours']==2
    assert not rows[0]['day']['issues']
    applied=client.post('/api/assistant/apply',json={'revision':1,'previewId':rows[0]['previewId']})
    assert applied.status_code==200,applied.text
    state=applied.json()['state'];assert validate_state(state)
    assert state['baseLessons']==before['state']['baseLessons']
    assert all(l['subjectId']!=class_hours.SUBJECT_ID for l in state['baseLessons'])


def test_assistant_context_and_schema_ground_class_hour_and_require_explicit_request():
    state=school()
    messages=ai_planner.messages_for(state,DAY,'Для 6а нужен классный час',[],full_context=True)
    context=json.loads(messages[0]['content'].split(ai_planner.CONTEXT_MARKER)[1])
    assert context['classLeaders']=={'one':'a','two':'b'}
    draft,labels=ai_planner.validate_interpretation(raw([action()]),state,DAY,'Для 6а нужен классный час')
    assert draft['actions']==[action()] and 'Кл/ч' in labels[0]
    with pytest.raises(ValueError,match='явной просьбе'):
        ai_planner.validate_interpretation(raw([action()]),state,DAY,'Учитель отсутствует')


def test_date_time_and_teacher_tampering_are_rejected():
    state=school();rows=ai_planner.variants(state,DAY,[action()]);assert rows
    result=deepcopy(rows[0]);event=next(l for l in result['after'] if l.get('classHour'))
    for field,value in [('period',2),('teacherIds',['c'])]:
        invalid=deepcopy(result);next(l for l in invalid['after'] if l.get('classHour'))[field]=value
        assert ai_planner.condition_problems(state,DAY,[action()],invalid)
    work=ai_planner.prepared_state(state,DAY,[action()]);work['days'][DAY]=deepcopy(result['after'])
    wrong=deepcopy(work);wrong['days']['2026-11-18']=wrong['days'].pop(DAY)
    with pytest.raises(StateError):validate_state(wrong)
    wrong=deepcopy(work);wrong['baseLessons'].append(deepcopy(event))
    with pytest.raises(StateError):validate_state(wrong)


def test_absent_class_leader_never_causes_automatic_substitution_or_silent_cancellation():
    actions=[action(),{'type':'teacher_absence','teacherId':'a','first':1,'last':8}]
    results=ai_planner.variants(school(),DAY,actions)
    assert results
    for row in results:
        assert not any('a' in l['teacherIds'] for l in row['after'])
        assert row['stats']['classHoursCancelled']==1
        assert any('Классный час' in warning and 'отменён' in warning for warning in row['warnings'])


def test_technology_pair_is_kept_and_shifted_as_a_whole():
    state=school();state['classes']=state['classes'][:1]
    state['baseLessons']=[l for l in state['baseLessons'] if l['classIds']==['one']]
    for l in state['baseLessons']:
        if l['id'] in ('a1','a2'):l['subjectId']='tech';l['teacherIds']=['a']
    state['rooms'][0]['subjectIds']=[]
    state['plan']=[{'id':'p','subjectId':'tech','classIds':['one'],'teacherIds':['a'],
                    'roomIds':['r1'],'hours':2,'maxPerDay':2,'doubleLessons':True}]
    state=normalize_state(state)
    with pytest.raises(ValueError,match='Спаренный'):
        class_hours.create(state,DAY,'one','a1')
    result=ai_planner.variants(state,DAY,[action()])[0]
    tech=sorted(l['period'] for l in result['after'] if l['subjectId']=='tech')
    assert len(tech)==2 and tech[1]==tech[0]+1 and tech[0]>1
    assert result['stats']['classGapsAfter']==0 and not result['cancelled']


def test_class_hour_does_not_count_as_a_taught_curriculum_subject_or_change_word_layout():
    from app.exporter import _pupil_text,_teacher_text
    state=school();event=class_hours.create(state,DAY,'one','a1');class_hours.ensure_subject(state)
    subjects={s['id']:s for s in state['subjects']};rooms={r['id']:r for r in state['rooms']}
    classes={c['id']:c for c in state['classes']}
    assert not teacher_hours(state,[event])
    assert _pupil_text([event],subjects,rooms)=='Кл/ч 101'
    assert _teacher_text([event],'a',classes,subjects,rooms)=='6а Кл/ч 101'


def test_two_classes_of_one_leader_have_one_joint_class_hour():
    state=school();state['classes'][1]['homeroomTeacherId']='a'
    state['rooms'][0]['capacity']=50
    draft,_=ai_planner.validate_interpretation(raw([action('one'),action('two')]),state,DAY,'Всем классный час')
    rows=ai_planner.variants(state,DAY,draft['actions']);assert rows
    events=[l for l in rows[0]['after'] if l.get('classHour')]
    assert len(events)==1 and events[0]['classIds']==['one','two'] and events[0]['teacherIds']==['a']
    assert rows[0]['stats']['classHours']==1 and rows[0]['stats']['classHourClasses']==2
    assert not [i for i in issues(ai_planner.prepared_state(state,DAY,draft['actions']),rows[0]['after'],DAY) if i['level']=='error']


def test_joint_class_hour_restores_both_original_first_lessons(client):
    state=school();state['classes'][1]['homeroomTeacherId']='a';state['rooms'][0]['capacity']=50
    server.store.mutate(1,'Two homeroom classes',lambda _:state)
    preview=client.post('/api/assistant/class-hour-preview',json={'revision':2,'date':DAY,'classIds':['one','two']}).json()
    applied=client.post('/api/assistant/apply',json={'revision':2,'previewId':preview['variants'][0]['previewId']}).json()
    event=next(l for l in applied['day']['lessons'] if l.get('classHour'))
    restored=client.post('/api/lesson/class-hour',json={'revision':applied['revision'],'date':DAY,'lessonId':event['id'],'enabled':False})
    assert restored.status_code==200,restored.text
    assert lessons_for_day(restored.json()['state'],DAY)==lessons_for_day(state,DAY)


def test_class_hour_room_search_optimizes_original_pupil_moves():
    from app.repair_constraints import solve_day
    state=school();state['classes'][1]['homeroomTeacherId']='a'
    for room in state['rooms']:room['capacity']=50
    state['rooms'].append({'id':'r3','name':'103','capacity':50,'subjectIds':[],'unavailable':[]})
    actions=[action('one'),action('two')]
    work=ai_planner.prepared_state(state,DAY,actions)
    next(l for l in work['days'][DAY] if l.get('classHour'))['roomIds']=['r3']
    result=solve_day(work,DAY,baseline=lessons_for_day(state,DAY),conditions=actions,allow_room_changes=True)
    assert result and result['stats']['moved']==1
    assert next(l for l in result['after'] if l.get('classHour'))['roomIds'][0] in ('r1','r2')


def test_saved_class_hour_survives_another_absence_request():
    state=school();result=ai_planner.variants(state,DAY,[action()])[0]
    ai_planner.commit(state,DAY,[action()],result)
    actions=[action(),{'type':'teacher_absence','teacherId':'c','first':1,'last':8}]
    rows=ai_planner.variants(state,DAY,actions);assert rows
    assert all(any(l.get('classHour') and l['period']==1 and l['teacherIds']==['a'] for l in r['after']) for r in rows)


def test_changing_leadership_does_not_rewrite_past_class_hours(client):
    saved=client.post('/api/lesson/class-hour',json={'revision':1,'date':DAY,'lessonId':'a1','enabled':True}).json()
    cls={**saved['state']['classes'][0],'homeroomTeacherId':'c'}
    response=client.post('/api/entity/classes',json={'revision':2,'record':cls})
    assert response.status_code==200,response.text
    state=response.json()['state']
    assert next(l for l in state['days'][DAY] if l.get('classHour'))['teacherIds']==['a']
    assert class_hours.create(state,'2026-11-18','one')['teacherIds']==['c']


def test_user_can_cancel_a_new_class_hour_without_invalid_saved_conditions():
    state=school();state['baseLessons']=[l for l in state['baseLessons'] if not (l['day']==2 and l['period']==1)]
    result=ai_planner.variants(state,DAY,[action()])[0]
    ai_planner.commit(state,DAY,[action()],result)
    event=next(l for l in state['days'][DAY] if l.get('classHour'))
    actions=[{'type':'cancel_lesson','lessonId':event['id']}]
    result=ai_planner.variants(state,DAY,actions)[0]
    ai_planner.commit(state,DAY,actions,result)
    assert validate_state(state) and not any(l.get('classHour') for l in state['days'][DAY])


def test_leadership_can_be_changed_in_teacher_card(client):
    teacher={**server.store.read()['state']['teachers'][2],'homeroom':'6а, 6б'}
    response=client.post('/api/entity/teachers',json={'revision':1,'record':teacher})
    assert response.status_code==200,response.text
    assert class_hours.leader_map(response.json()['state'])=={'one':'c','two':'c'}
