"""Independent regression scenarios for daily planning, room edits and saved variants."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app import ai_planner, server
from app.assistant_history import AssistantHistory
from app.model import absence_periods, check_slots, lessons_for_day, normalize_state, validate_state
from app.store import Store


DAY='2026-11-23'


def school():
    return normalize_state({
        'teachers':[{'id':ident,'name':f'Учитель {ident}','subjectIds':['math']} for ident in ('a','b','free')],
        'rooms':[{'id':'r1','name':'101','teacherId':'a'}, {'id':'r2','name':'305','teacherId':'b'},
                 {'id':'r3','name':'313'}, {'id':'r4','name':'312'}, {'id':'hall','name':'Актовый зал'}],
        'classes':[{'id':ident,'name':name} for ident,name in [('a','8а'),('b','5б')]],
        'subjects':[{'id':'math','name':'Математика'}],
        'baseLessons':[{'id':f'{c}-{p}','day':0,'period':p,'classIds':[c],'subjectId':'math',
                        'teacherIds':[c],'roomIds':[room]} for c,room in (('a','r1'),('b','r2')) for p in (1,2,3)],
    })


@pytest.fixture
def desk(tmp_path,monkeypatch):
    store=Store(tmp_path/'schedule-test.sqlite3',school)
    monkeypatch.setattr(server,'store',store)
    return TestClient(server.app),store


def post(client, path, payload):
    reply=client.post('/api'+path,json=payload)
    assert reply.status_code==200, reply.text
    return reply.json()


def recorded_plan(store,teacher='a'):
    account=AssistantHistory(store)
    thread,turn=account.start(None,DAY,'Учитель отсутствует весь день.')
    account.finish(turn,response={'date':DAY,'reply':'Условия поняты.','questions':[],'unsupported':[],
                                  'actions':[{'type':'teacher_absence','teacherId':teacher,'first':1,'last':8}]})
    return {'threadId':thread,'turnId':turn}


DAY_WINDOW='2026-11-25'


def window_school():
    state=school()
    state['teachers'][0]['name']='Альфова Т.Т.'
    state['classes'].append({'id':'ninth','name':'9б'})
    state['individualLearners']=[
        {'id':'pupil-1','name':'Тестовый Ученик','classId':'ninth','allowGaps':True},
        {'id':'pupil-2','name':'Примерный Ученик','classId':'a','allowGaps':True},
    ]
    state['baseLessons']=[
        {'id':f'fifth-{period}','day':2,'period':period,'classIds':['b'],'subjectId':'math',
         'teacherIds':['a' if period>4 else 'b'],'roomIds':['r1' if period>4 else 'r2']}
        for period in range(1,7)]
    state['baseLessons'] += [
        {'id':f'ninth-{period}','day':2,'period':period,'classIds':['ninth'],'subjectId':'math',
         'teacherIds':['a' if period==3 else 'free'],'roomIds':['r1' if period==3 else 'r3']}
        for period in range(1,4)]
    state['externalActivities']=[
        {'id':ident,'kind':'individual','label':'Индивидуальное занятие','learnerId':pupil,
         'subjectId':'math','teacherId':teacher,'roomId':room,'weekday':2,'first':period,'last':period,
         'allowEighth':period==8}
        for ident,pupil,teacher,room,period in [('early','pupil-1','a','r1',1),
                                               ('late','pupil-1','free','r3',8),
                                               ('other','pupil-2','a','r1',2)]
    ]
    return normalize_state(state)


def test_mixed_dialogue_can_cancel_individuals_limit_teacher_and_export_all_outputs(tmp_path,monkeypatch):
    from app import assistant_api
    from app.commitments import matching
    store=Store(tmp_path/'schedule-test.sqlite3',window_school)
    monkeypatch.setattr(server,'store',store)
    client=TestClient(server.app)
    note='Отдельный вопрос о другом дне.'
    fake_key='sk-or-v1-'+'testing'*8

    class Model:
        def status(self):
            return {'paidEnabled':True,'provider':'deepseek','model':'deepseek-chat'}

        def interpret(self,messages,**options):
            context=messages[0]['content']
            assert 'Тестовый Ученик' not in context
            assert 'pupil-1' in context and 'инд 9б' in context
            return {'date':DAY_WINDOW,'reply':'Проверьте условия. '+fake_key,'actions':[
                {'type':'cancel_lesson','lessonId':'ninth-1'},
                {'type':'unknown_action'},
            ],'questions':[],'unsupported':['Отмена индивидуальных занятий 9б недоступна.',note]}, 'model'

    monkeypatch.setattr(assistant_api,'connection',lambda:Model())
    result=post(client,'/assistant/interpret',{'revision':1,'date':DAY_WINDOW,
        'message':'Не будет индивидуальника 9б. Альфовой поставить с 1 по 4 уроки только 5 классы, остальные ей снять.'})
    assert {r['type'] for r in result['actions']}=={'cancel_individual','teacher_lesson_window'}
    assert result['unsupported']==[note] and result['questions']
    assert not result['draftId'] and result['partialDraftId']
    assert client.post('/api/assistant/preview',json={'revision':1,'draftId':result['partialDraftId']}).status_code==422

    recorded={k:result[k] for k in ('threadId','turnId')}
    monkeypatch.setattr(assistant_api,'connection',lambda:pytest.fail('Подбор по истории выполняется локально'))
    preview=post(client,'/assistant/replay',{'revision':1,**recorded,'confirmedOnly':True})
    option=preview['variants'][0]
    assert store.read()['revision']==1
    assert note in option['unfulfilled']
    assert option['stats']['externalCancelled']==2
    assert {r['id'] for r in option['day']['externalChanges']}=={'early','late'}
    assert {r['id'] for r in option['day']['externalActivities'] if r['cancelled']}=={'early','late'}
    assert 'ninth-1' in {r['id'] for r in option['after']}
    taught=[r for r in option['after'] if 'a' in r['teacherIds']]
    assert len(taught)==2 and all(r['classIds']==['b'] and r['period']<=4 for r in taught)

    saved=post(client,'/assistant/apply',{'revision':1,'previewId':option['previewId']})
    assert {r['id'] for r in matching(saved['state'],DAY_WINDOW)}=={'other'}
    assert {r['id'] for r in matching(saved['state'],'2026-12-02')}=={'early','late','other'}
    assert any(r['id']=='ninth-3' for r in lessons_for_day(saved['state'],'2026-12-02'))
    export=client.get('/api/assistant/conversations-export')
    assert export.status_code==200 and 'attachment' in export.headers['content-disposition']
    turn=export.json()['conversations'][0]['turns'][0]
    assert turn['status']=='applied' and turn['response']['unsupported']==[note]
    assert {'actions','labels','questions','events'}<=turn['response'].keys()
    assert [r['kind'] for r in turn['response']['events']]==['preview','applied']
    assert fake_key not in export.text


def test_individual_aliases_require_disambiguation_and_teacher_scope_can_be_corrected():
    from app.day_request import ground_reply
    state=window_school()
    state['individualLearners'].append({'id':'pupil-3','name':'Другой Ученик','classId':'ninth'})
    raw={'date':DAY_WINDOW,'reply':'','questions':[],'unsupported':[],'actions':[
        {'type':'cancel_individual','learnerId':'pupil-1'},
        {'type':'teacher_lesson_window','teacherId':'a','classIds':['b'],'first':1,'last':4},
    ]}
    old='Альфовой поставить с 1 по 4 уроки только 5 классы.'
    corrected='Снять только девятые классы у Альфовой. Альфова уходит после четвёртого урока.'
    actual=ground_reply(raw,state,DAY_WINDOW,[old,corrected,'Отменить все уроки у индивидуальника 9б.'])
    assert 'инд1 9б, инд2 9б' in actual['questions'][0]
    assert actual['actions']==[{'type':'cancel_lesson','lessonId':'ninth-3'},
                               {'type':'teacher_lesson_window','teacherId':'a','classIds':['b'],'first':1,'last':4,'cancelOtherClasses':False},
                               {'type':'teacher_absence','teacherId':'a','first':5,'last':8}]
    resolved=ground_reply(raw,state,DAY_WINDOW,[old,corrected,'Не будет инд2 9б.'])
    assert {'type':'cancel_individual','learnerId':'pupil-3'} in resolved['actions']
    assert not any(r.get('learnerId')=='pupil-1' for r in resolved['actions'])


def test_repeats_a_saved_conversation_without_a_model_and_checks_the_revision(desk,monkeypatch):
    from app import assistant_api
    client,store=desk
    recorded=recorded_plan(store)
    monkeypatch.setattr(assistant_api,'connection',lambda:pytest.fail('Replay must be entirely local'))
    response=post(client,'/assistant/replay',{'revision':1,**recorded})
    option=response['variants'][0]
    assert not any('a' in r['teacherIds'] for r in option['day']['lessons'])
    assert store.read()['revision']==1
    saved=post(client,'/assistant/apply',{'revision':1,'previewId':option['previewId']})
    assert saved['revision']==2
    opened=client.get('/api/assistant/conversations/'+recorded['threadId']).json()
    assert opened['turns'][-1]['status']=='applied'
    repeated=post(client,'/assistant/replay',{'revision':2,**recorded})
    assert repeated['variants'][0]['status']=='unchanged'
    assert client.post('/api/assistant/replay',json={'revision':1,**recorded}).status_code==409


def test_occupied_room_preview_lists_the_chain_and_only_applies_the_selected_result(desk):
    client,store=desk
    change={'revision':1,'date':DAY,'lessonId':'a-2','roomIds':['r2'],'period':2}
    options=post(client,'/lesson/placement-preview',change)['variants']
    assert 2<=len(options)<=3
    assert not store.read()['state']['days']
    for option in options:
        rows={l['id']:l for l in option['day']['lessons']}
        assert rows['a-2']['period']==2 and rows['a-2']['roomIds']==['r2']
        assert rows['b-2']['teacherIds']==['b'] and rows['b-2']['classIds']==['b']
        assert rows['b-2']['roomIds']!=['hall'] and not option['cancelled']
        assert {'a-2','b-2'} <= {c['id'] for c in option['changes']}
        assert not check_slots(list(rows.values()))
    choice=options[1]
    saved=post(client,'/assistant/apply',{'revision':1,'previewId':choice['previewId']})
    assert saved['day']['lessons']==choice['day']['lessons']
    assert not any(r['type']=='place_lesson' for r in saved['state']['assistantConditions'][DAY])


def test_ordinary_room_and_teacher_usual_room_are_preferred():
    from app.room_policy import improve_assignments
    state=school()
    before=lessons_for_day(state,DAY)
    after=deepcopy(before)
    own=next(l for l in after if l['id']=='b-1')
    own['roomIds']=['hall']
    improve_assignments(state,DAY,before,after)
    assert own['roomIds']==['r2']
    own['roomIds']=['hall']
    room=next(r for r in state['rooms'] if r['id']=='r2')
    room['unavailable']=[[0,1]]
    improve_assignments(state,DAY,before,after)
    assert own['roomIds'] in (['r3'],['r4'])
    own['roomIds']=['hall']
    improve_assignments(state,DAY,before,after,protected={'b-1'})
    assert own['roomIds']==['hall']


def test_much_worse_alternatives_are_not_presented():
    scores=[{'after':[],'stats':{'moved':n,'classGapsAfter':0,'lostHours':3,'youngerLate':0}} for n in (71,19,82,21,23)]
    assert [r['stats']['moved'] for r in ai_planner.comparable(scores)]==[19,21,23]


@pytest.mark.parametrize('worker_interrupted',[False,True])
def test_reserve_keeps_feasible_lessons_and_explains_an_impossible_arrival(monkeypatch,worker_interrupted):
    from app.solver_process import DaySolverUnavailable
    from app import repair_constraints
    state=school()
    for lesson in state['baseLessons']:
        lesson['locked']=True
    request=[{'type':'class_day','classId':'a','first':4,'last':7},
             {'type':'teacher_absence','teacherId':'b','first':2,'last':2}]
    if worker_interrupted:
        def unavailable(*args,**kwargs):
            raise DaySolverUnavailable()
        monkeypatch.setattr(repair_constraints,'solve_day',unavailable)
    options=ai_planner.variants(state,DAY,request)
    assert options
    result=options[0]
    assert any('8а' in text for text in result['unfulfilled'])
    assert 'b-2' not in {l['id'] for l in result['after']}
    assert {'a-1','a-2','a-3','b-1','b-3'}=={l['id'] for l in result['after']}
    assert not ai_planner.condition_problems(state,DAY,result['actions'],result)
    saved=validate_state(ai_planner.commit(deepcopy(state),DAY,result['actions'],result))
    assert saved['dayNotices'][DAY] and saved['baseLessons']==state['baseLessons']


def test_store_a_backup_variant_and_switch_without_changing_other_dates(desk):
    client,store=desk
    store.mutate(1,'Existing absence',lambda s:s['absences'].append(
        {'id':'range','teacherId':'free','start':'2026-11-20','end':'2026-11-24','first':2,'last':3,'reason':'Плановое'}))
    prefix=f'/day/{DAY}/versions'
    first=post(client,prefix+'/save',{'revision':2,'title':'Обычный день'})
    anchor=first['versions'][0]['id']
    request=recorded_plan(store)
    choices=post(client,'/assistant/replay',{'revision':3,**request})['variants']
    substitute=choices[0]
    stored=post(client,prefix+'/save',{'revision':3,'title':'План на случай отсутствия','previewId':substitute['previewId']})
    reserve=stored['versions'][0]['id']
    assert stored['versions'][1]['active'] and not stored['versions'][0]['active']
    assert len(stored['day']['lessons'])==6 and not absence_periods(stored['state'],'a',DAY)
    preview=post(client,prefix+'/preview',{'revision':4,'id':reserve})['variants'][0]
    assert preview['stats']['cancelled']==3 and store.read()['revision']==4
    saved=post(client,prefix+'/apply',{'revision':4,'id':reserve})
    assert absence_periods(saved['state'],'a',DAY)==set(range(1,9))
    restored=post(client,prefix+'/apply',{'revision':5,'id':anchor})
    assert not absence_periods(restored['state'],'a',DAY)
    for date in ('2026-11-20',DAY,'2026-11-24'):
        assert absence_periods(restored['state'],'free',date)=={2,3}
    assert restored['state']['baseLessons']==school()['baseLessons']
    assert len(restored['state']['dayVariants'][DAY])==2
    validate_state(deepcopy(restored['state']))


def test_yesterdays_class_hour_must_not_block_todays_schedule():
    from app.class_hours import create,ensure_subject
    state=school()
    state['classes'][0]['homeroomTeacherId']='a'
    state['teachers'][0]['homeroomRoomId']='r1'
    state['baseLessons'].append({**state['baseLessons'][0],'id':'tuesday-a','day':1})
    ensure_subject(state)
    event=create(state,DAY,'a','a-1',None,1)
    state['dayBases'][DAY]=lessons_for_day(state,DAY)
    state['days'][DAY]=[l for l in lessons_for_day(state,DAY) if l['id']!='a-1']+[event]
    tomorrow='2026-11-24'
    options=ai_planner.variants(state,tomorrow,[{'type':'teacher_absence','teacherId':'a','first':1,'last':8}])
    assert options and not options[0]['after']
    assert not options[0].get('unfulfilled')
    assert ai_planner.commit(deepcopy(state),tomorrow,options[0]['actions'],options[0])['days'][DAY]==state['days'][DAY]
