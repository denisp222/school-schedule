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


MONDAY='2026-11-23'


def monday_meeting(shared=True):
    teachers=[{'id':t,'name':name,'subjectIds':['rov','math','pe']} for t,name in (
        ('lead','Ведущая А.А.'),('a','Учительница Б.Б.'),('b','Наставница В.В.'),
        ('coach','Тренер С.С.'),('m1','Учитель Г.Г.'),('m2','Учитель Д.Д.'),('m3','Учитель Е.Е.'))]
    classes=[{'id':c,'name':name,'size':25} for c,name in zip('abcd',('8а','8б','9в','5г'))]
    rooms=[{'id':f'r{i}','name':f'10{i}','capacity':25} for i in range(1,5)]
    rooms.append({'id':'hall','name':'Актовый зал','capacity':90})

    def lesson(id_, period, classes, teacher, room, subject='rov'):
        return {'id':id_,'day':0,'period':period,'classIds':list(classes),
                'teacherIds':[teacher],'roomIds':[room],'subjectId':subject}

    rows=[lesson('lead-rov',1,'c','lead','r3'),
          lesson('a-rov',1,'ab' if shared else 'a','a','hall' if shared else 'r1'),
          lesson('pe-a',6,'a','coach','r4','pe'),lesson('pe-d',7,'d','coach','r4','pe')]
    if not shared:rows.append(lesson('b-rov',1,'b','b','r2'))
    rows.extend(lesson(f'math-{c}',2,c,f'm{i}',f'r{i}','math') for i,c in enumerate('abc',1))
    return normalize_state({'teachers':teachers,'classes':classes,'rooms':rooms,'subjects':[
        {'id':'rov','name':'Разговоры о важном'},{'id':'math','name':'Математика'},{'id':'pe','name':'Физическая культура'}],
        'baseLessons':rows})


def monday_answer(actions=(), unsupported=(), questions=()):
    return {'date':MONDAY,'reply':'Условия','actions':list(actions),'unsupported':list(unsupported),'questions':list(questions)}


HALL_REQUEST='Проведи «Разговоры о важном» у 8 A, 8б и 9в совместно у Ведущей в актовом зале'
COACH_REQUEST='Тренер отсутствует на 6-м и 7-м уроках, 8а физ-ру не ставить.'


@pytest.mark.parametrize(('shared','period'),[(True,1),(True,2),(False,2)])
def test_combo_joins_three_classes_and_cancels_only_the_named_pe(shared,period):
    from app.model import issues,absence_periods
    state=monday_meeting(shared)
    text=HALL_REQUEST+(f' {period}-м уроком' if period!=1 else '')+'. '+COACH_REQUEST
    raw=monday_answer(
        actions=[{'type':'teacher_absence','teacherId':'coach','first':1,'last':8}],
        unsupported=['Совместные «Разговоры о важном» 8а, 8б и 9в: три класса протокол не поддерживает.',
                     'Снятие физкультуры у 8а: указано отсутствие Тренера, алгоритм попробует сохранить занятие.'])
    parsed,labels=ai_planner.validate_interpretation(ai_planner.ground_joint_refusal(raw,state,MONDAY,text),state,MONDAY,text)
    assert not parsed['questions'] and not parsed['unsupported']
    assert any('Актовый зал' in label for label in labels)
    assert any(a=={'type':'teacher_absence','teacherId':'coach','first':6,'last':7} for a in parsed['actions'])
    results=ai_planner.variants(state,MONDAY,parsed['actions'])
    assert results
    for result in results:
        combined,=[r for r in result['after'] if r.get('joint')]
        assert set(combined['classIds'])==set('abc')
        assert len(combined['joint']['sources'])==(2 if shared else 3)
        assert (combined['period'],combined['teacherIds'],combined['roomIds'])==(period,['lead'],['hall'])
        assert not any(l['id']=='pe-a' for l in result['after'])
        assert next(r for r in result['after'] if r['id']=='pe-d')['period']<6
        assert not result['stats']['classGapsAfter']
    saved=validate_state(ai_planner.commit(deepcopy(state),MONDAY,results[0]['actions'],results[0]))
    assert absence_periods(saved,'coach',MONDAY)=={6,7}
    assert saved['baseLessons']==state['baseLessons']
    assert not [i for i in issues(saved,saved['days'][MONDAY],MONDAY) if i['level']=='error']


def test_updated_request_retires_join_warning_without_erasing_unrelated_request():
    state=monday_meeting()
    first=HALL_REQUEST+'. '+COACH_REQUEST
    previous=ai_planner.explicit_joint_requests(state,MONDAY,first)[0]
    history=[{'role':'user','content':first},
             {'role':'assistant','content':'Совместные разговоры сейчас не поддерживаются.'},
             {'role':'user','content':'8а и 8б снять «Разговоры о важном». Им ко второму уроку.'}]
    attendance=[{'type':'class_day','classId':c,'first':2,'last':7} for c in ('a','b')]
    raw=monday_answer([previous,*attendance], [
        'Совместные «Разговоры о важном» 8а, 8б и 9в разрешены только первым уроком.',
        'Снятие физкультуры у 8а не поддерживается.',
        'Поменять учебный план во вторник.'])
    grounded=ai_planner.ground_joint_refusal(raw,state,MONDAY,'Условия верны',history)
    assert grounded['unsupported']==['Поменять учебный план во вторник.']
    assert {a['lessonId'] for a in grounded['actions'] if a['type']=='cancel_lesson'}=={'a-rov','pe-a'}
    assert all(a['type']!='join_lessons' for a in grounded['actions'])
    grounded['unsupported'].clear()
    parsed,_=ai_planner.validate_interpretation(grounded,state,MONDAY,history[2]['content'])
    result=ai_planner.variants(state,MONDAY,parsed['actions'])[0]
    for cid in 'ab':
        assert min(l['period'] for l in result['after'] if cid in l['classIds'])==2
    assert any(r['id']=='lead-rov' for r in result['after'])


def test_rov_default_only_changes_for_an_explicit_dated_pin_and_honors_eighth_rule():
    from app.model import slot_feasible
    state=monday_meeting()
    pin={'type':'pin_lesson','lessonId':'lead-rov','period':2}
    with pytest.raises(ValueError,match='точный номер'):
        ai_planner.validate_interpretation(monday_answer([pin]),state,MONDAY,'Сделайте у 9в математику вторым уроком.')
    actions,_=ai_planner.validate_interpretation(monday_answer([pin]),state,MONDAY,'Поставьте 9в «Разговоры о важном» вторым уроком.')
    result=ai_planner.variants(state,MONDAY,actions['actions'])[0]
    saved=validate_state(ai_planner.commit(deepcopy(state),MONDAY,result['actions'],result))
    pinned=next(row for row in saved['days'][MONDAY] if row['id']=='lead-rov')
    assert pinned['period']==2 and slot_feasible(saved,pinned,0,2,date=MONDAY)
    assert not slot_feasible(saved,pinned,0,2,date='2026-11-30')
    assert next(row for row in lessons_for_day(saved,'2026-11-30') if row['id']=='lead-rov')['period']==1
    with pytest.raises(ValueError,match='восьмого'):
        ai_planner.validate_interpretation(monday_answer([{**pin,'period':8}]),state,MONDAY,'Поставьте 9в «Разговоры о важном» восьмым уроком.')


def test_joint_provenance_uses_the_selected_rotation_week():
    state=monday_meeting()
    state['school']['rotation']={'anchor':'2026-11-09','length':4}
    state['rotationWeeks']={str(i):deepcopy(state['baseLessons']) for i in range(1,5)}
    # The same ID refers to a different set of classes in the base week.
    next(r for r in state['baseLessons'] if r['id']=='a-rov')['classIds']=['a']
    text=HALL_REQUEST+'.'
    response=ai_planner.ground_joint_refusal(monday_answer(),state,MONDAY,text)
    draft,_=ai_planner.validate_interpretation(response,state,MONDAY,text)
    result=ai_planner.variants(state,MONDAY,draft['actions'])[0]
    assert next(l for l in result['after'] if l.get('joint'))['classIds']==['a','b','c']
    saved=ai_planner.commit(deepcopy(state),MONDAY,result['actions'],result)
    validate_state(saved)


def test_combined_classroom_still_checks_total_capacity_and_other_confirmations():
    state=monday_meeting(False)
    state['rooms'][-1]['capacity']=70
    response=ai_planner.ground_joint_refusal(monday_answer(questions=['Можно ли поменять учебный план?']),
                                             state,MONDAY,HALL_REQUEST+'.')
    assert response['questions']==['Можно ли поменять учебный план?']
    with pytest.raises(ValueError,match='не вмещает'):
        ai_planner.validate_interpretation(response,state,MONDAY,HALL_REQUEST)


def test_grounding_preserves_revisions_and_never_widens_a_list_of_periods():
    state=monday_meeting()
    history=[{'role':'user','content':HALL_REQUEST+' без окон. '+COACH_REQUEST}]
    reply=ai_planner.ground_joint_refusal(monday_answer(),state,MONDAY,
                                         'Физкультуру у 8а всё-таки оставь. Тренер будет работать.',history)
    assert [a['type'] for a in reply['actions']]==['join_lessons']
    reply=ai_planner.ground_joint_refusal(monday_answer(),state,MONDAY,'Тренер отсутствует на 6 и 8 уроках.')
    assert not reply['actions']
