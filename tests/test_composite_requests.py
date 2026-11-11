"""Combined daily requests, absent leaders, fallback gaps, and younger classes."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient

from app import ai_planner,class_hours
from app.model import normalize_state,validate_state,lessons_for_day,check_slots
from app.repair_constraints import solve_day

DAY='2026-11-13'


def fixture():
    return normalize_state({'teachers':[{'id':t,'name':f'Учитель {t}','subjectIds':['math','pe'],
        'homeroomRoomId':'r1' if t=='a' else 'r2' if t=='d' else ''} for t in 'abcde'],
        'classes':[{'id':'one','name':'8г','homeroomTeacherId':'a'},
                   {'id':'two','name':'9а','homeroomTeacherId':'d'}],
        'subjects':[{'id':'math','name':'Математика'},{'id':'pe','name':'Физкультура'}],
        'rooms':[{'id':'r1','name':'101'},{'id':'r2','name':'102'}],
        'baseLessons':[{'id':f'{cid}-{p}','day':4,'period':p,'classIds':[cid],
            'teacherIds':[('b' if p==4 else 'c') if cid=='one' else ('d' if p==1 else 'e')],
            'subjectId':'pe' if cid=='one' and p==4 else 'math','roomIds':['r1' if cid=='one' else 'r2']}
            for cid in ('one','two') for p in range(1,8)]})


def request():
    return [{'type':'class_hour','classId':'one','lessonId':None,'replaceLessonId':'one-4'},
            {'type':'class_hour','classId':'two','lessonId':None},
            {'type':'teacher_absence','teacherId':'d','first':1,'last':8}]


def test_one_request_replaces_named_lesson_keeps_seven_and_cancels_absent_leader_hour():
    state=fixture();original=deepcopy(state)
    raw={'date':DAY,'reply':'Условия','questions':[],'unsupported':[],'actions':request()}
    draft,labels=ai_planner.validate_interpretation(raw,state,DAY,'Заменить физкультуру 8г классным часом первым уроком. Классные часы обоим классам. Учитель d отсутствует весь день.')
    assert any('Физкультура' in label for label in labels)
    options=ai_planner.variants(state,DAY,draft['actions']);assert options
    for result in options:
        own=[l for l in result['after'] if 'one' in l['classIds']]
        assert len(own)==7 and {l['period'] for l in own}==set(range(1,8))
        assert next(l for l in own if l['period']==1)['subjectId']==class_hours.SUBJECT_ID
        assert not any(l['subjectId']=='pe' for l in own)
        assert any(l['id']=='one-1' and l['subjectId']=='math' for l in own)
        assert not any('d' in l['teacherIds'] for l in result['after'])
        assert result['stats']['classHoursCancelled']==1 and not result['stats']['classGapsAfter']
        assert any('отменён' in text for text in result['warnings'])
        assert not ai_planner.condition_problems(state,DAY,result['actions'],result)
    saved=ai_planner.commit(deepcopy(state),DAY,options[0]['actions'],options[0])
    validate_state(saved)
    assert any('отменён' in text for text in saved['dayNotices'][DAY])
    assert saved['baseLessons']==original['baseLessons'] and state==original


def test_two_step_model_output_is_composed_before_preview_without_two_dialogues():
    state=fixture()
    actions=[{'type':'pin_lesson','lessonId':'one-4','period':1},
             {'type':'class_hour','classId':'one','lessonId':None}]
    raw={'date':DAY,'reply':'Условия','questions':[],'unsupported':[],'actions':actions}
    draft,_=ai_planner.validate_interpretation(raw,state,DAY,'Перенеси физкультуру 8г на первый урок и замени классным часом.')
    assert len(draft['actions'])==1 and draft['actions'][0]['replaceLessonId']=='one-4'
    assert ai_planner.variants(state,DAY,draft['actions'])


def test_retarget_already_saved_shared_hour_restores_previous_subject_and_keeps_partner():
    state=fixture();state['classes'][1]['homeroomTeacherId']='a'
    initial=[{'type':'class_hour','classId':c['id'],'lessonId':None} for c in state['classes']]
    first=ai_planner.variants(state,DAY,initial)[0]
    saved=ai_planner.commit(deepcopy(state),DAY,first['actions'],first)
    target=[{'type':'class_hour','classId':'one','lessonId':None,'replaceLessonId':'one-4'}]
    options=ai_planner.variants(saved,DAY,target);assert options
    for result in options:
        assert not ai_planner.condition_problems(saved,DAY,result['actions'],result)
        assert len([l for l in result['after'] if 'one' in l['classIds']])==7
        assert any(l['id']=='one-1' and l['subjectId']=='math' for l in result['after'])
        assert not any(l['subjectId']=='pe' and 'one' in l['classIds'] for l in result['after'])
        assert any(l.get('classHour') and 'two' in l['classIds'] for l in result['after'])
    validate_state(ai_planner.commit(deepcopy(saved),DAY,options[0]['actions'],options[0]))


def test_impossible_gap_free_day_returns_explicit_safe_fallback_and_can_be_saved():
    state=fixture();state['classes']=state['classes'][:1]
    state['baseLessons']=[l for l in state['baseLessons'] if l['classIds']==['one'] and l['period']<=3]
    for row in state['baseLessons']:
        row['teacherIds']=['b' if row['period']==2 else 'c'];row['locked']=row['period']!=2
    actions=[{'type':'teacher_absence','teacherId':'b','first':1,'last':8}]
    options=ai_planner.variants(state,DAY,actions);assert options
    for result in options:
        assert result['stats']['classGapsAfter']>0
        assert result['stats']['classGapDetails'][0]['periods']==[2]
        assert any(r['type']=='allow_class_gaps' for r in result['actions'])
        assert any('Резервный вариант' in warning for warning in result['warnings'])
        assert not check_slots(result['after']) and not any('b' in l['teacherIds'] for l in result['after'])
        assert not ai_planner.condition_problems(state,DAY,result['actions'],result)
    with_gaps=ai_planner.commit(deepcopy(state),DAY,options[0]['actions'],options[0]);validate_state(with_gaps)
    for row in with_gaps['days'][DAY]:row['locked']=False
    for row in with_gaps['baseLessons']:row['locked']=False
    improved=ai_planner.variants(with_gaps,DAY,with_gaps['assistantConditions'][DAY]);assert improved
    assert not improved[0]['stats']['classGapsAfter']
    assert not any(r['type']=='allow_class_gaps' for r in improved[0]['actions'])


def test_sixth_class_avoids_seventh_even_when_it_requires_more_moves():
    state=normalize_state({'teachers':[{'id':t,'name':f'Учитель {t}','subjectIds':['s']} for t in 'abcd'],
        'classes':[{'id':'one','name':'6а'}],'subjects':[{'id':'s','name':'Предмет'}],
        'rooms':[{'id':'r1','name':'101'}],
        'baseLessons':[{'id':f'l{p}','day':4,'period':p,'classIds':['one'],'teacherIds':[t],
                        'subjectId':'s','roomIds':['r1']} for p,t in enumerate('abcddd',1)]})
    for teacher in state['teachers']:
        allowed={'a':{2,7},'b':{2,3},'c':{1,3},'d':{4,5,6}}[teacher['id']]
        teacher['unavailable']=[{'day':4,'period':p} for p in range(1,8) if p not in allowed]
    result=solve_day(state,DAY);assert result
    assert result['stats']['lostHours']==0 and result['stats']['youngerLate']==0
    assert result['stats']['moved']==3
    assert {l['period'] for l in result['after']}==set(range(1,7))


def test_local_class_hour_preview_saves_fallback_permission_with_the_same_option(tmp_path,monkeypatch):
    from app import server
    from app.store import Store
    state=fixture();state['classes']=state['classes'][:1]
    state['baseLessons']=[l for l in state['baseLessons'] if l['classIds']==['one'] and l['period']<=3]
    for row in state['baseLessons']:
        row['teacherIds']=['b' if row['period']==2 else 'c'];row['locked']=row['period']!=2
    state['absences']=[{'id':'absent','teacherId':'b','start':DAY,'end':DAY,'first':1,'last':8}]
    monkeypatch.setattr(server,'store',Store(tmp_path/'project.sqlite3',lambda:state))
    client=TestClient(server.app)
    response=client.post('/api/assistant/class-hour-preview',json={'revision':1,'date':DAY,'classIds':['one']})
    assert response.status_code==200,response.text
    option=response.json()['variants'][0]
    assert option['stats']['classGapsAfter']>0 and option['day']['classGapDetails']
    response=client.post('/api/assistant/apply',json={'revision':1,'previewId':option['previewId']})
    assert response.status_code==200,response.text
    assert any(r['type']=='allow_class_gaps' for r in response.json()['state']['assistantConditions'][DAY])
    assert client.get('/api/day/'+DAY).json()['stats']['errors']==0


def test_model_cannot_silently_switch_to_gap_mode():
    raw={'date':DAY,'reply':'Условия','questions':[],'unsupported':[],
         'actions':[{'type':'allow_class_gaps'}]}
    with pytest.raises(ValueError,match='Резервные варианты'):
        ai_planner.validate_interpretation(raw,fixture(),DAY,'Переставь занятия')
