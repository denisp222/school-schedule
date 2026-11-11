"""Real search results across fresh processes, using only artificial people."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import ai_planner,engine
from app.absence_request import parse_absence_request
from app.model import normalize_state,changed_assignments,check_slots
from app.repair_constraints import solve_day
from app.search_policy import canonical_actions

DAY='2026-11-10'


def school():
    return normalize_state({'school':{'bells':[str(n) for n in range(1,9)]},
        'teachers':[{'id':t,'name':name,'subjectIds':['s']} for t,name in
                    [('a','Примеров А.А.'),('b','Образцова Б.Б.'),('c','Учитель третий'),('d','Учитель четвёртый')]],
        'classes':[{'id':'c0','name':'7а'}], 'subjects':[{'id':'s','name':'Предмет'}],
        'rooms':[{'id':'r','name':'101'},{'id':'spare','name':'102'}],
        'baseLessons':[{'id':f'l{p}','day':1,'period':p,'teacherIds':[t],'classIds':['c0'],
                        'subjectId':'s','roomIds':['r']} for p,t in enumerate('abcd',1)]})


def request():return [{'type':'teacher_absence','teacherId':'b','first':1,'last':8}]


def projection(rows):
    return [{'after':r['after'],'moved':r['stats']['moved'],'lost':r['stats']['lostHours']} for r in rows]


def test_minimum_is_proven_and_permuted_input_does_not_change_schedules():
    state=school();before=deepcopy(state)
    results=ai_planner.variants(state,DAY,request())
    assert len(results)==3
    assert results[0]['stats']['moved']==1 and results[0]['stats']['lostHours']==1
    assert results[0]['search']['scope']=='all-rooms' and results[0]['search']['primaryProven']
    assert all(not ai_planner.condition_problems(state,DAY,request(),r) for r in results)
    assert not any(check_slots(r['after']) for r in results)
    for key in ('teachers','classes','rooms','subjects','baseLessons','plan'):state[key].reverse()
    ai_planner._variant_cache.clear()
    assert projection(ai_planner.variants(state,DAY,request()))==projection(results)
    assert before['baseLessons']==list(reversed(state['baseLessons']))


@pytest.mark.slow
def test_fresh_processes_hash_seeds_and_cpu_affinity_give_identical_results(tmp_path):
    path=tmp_path/'synthetic.json';path.write_text(json.dumps(school()),encoding='utf-8')
    code=r'''
import ctypes,json,os,sys
from pathlib import Path
if sys.argv[2]=='single' and os.name=='nt':
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
    kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    process=kernel.GetCurrentProcess();allowed=ctypes.c_size_t();system=ctypes.c_size_t()
    assert kernel.GetProcessAffinityMask(process,ctypes.byref(allowed),ctypes.byref(system))
    assert kernel.SetProcessAffinityMask(process,allowed.value & -allowed.value)
from app.ai_planner import variants
state=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
rows=variants(state,'2026-11-10',[{'type':'teacher_absence','teacherId':'b','first':1,'last':8}])
print(json.dumps([{'after':r['after'],'moved':r['stats']['moved'],'lost':r['stats']['lostHours']} for r in rows],sort_keys=True))
'''
    outputs=[]
    for seed,mode in [('11','all'),('27','single'),('931','all')]:
        result=subprocess.run([sys.executable,'-c',code,str(path),mode],env=dict(os.environ,PYTHONHASHSEED=seed,SCHEDULE_SOLVER_WORKER='1'),
                              capture_output=True,text=True,check=True,timeout=30)
        outputs.append(json.loads(result.stdout))
    assert outputs[0]==outputs[1]==outputs[2]


def test_three_greedy_options_never_skip_main_optimization(monkeypatch):
    state=school();base=state['baseLessons'];calls=[]
    def result(periods):
        after=[{**deepcopy(row),'period':p} for row,p in zip(base,periods)]
        return {'status':'ok','date':DAY,'before':base,'after':after,'changes':[],
                'cancelled':[],'groupLosses':[],'warnings':[],
                'stats':{'moved':changed_assignments(base,after),'lostHours':0,'cancelled':0,'seconds':0}}
    permutations=[[2,3,4,1],[3,4,1,2],[4,1,2,3],[2,3,4,1]]
    monkeypatch.setattr(engine,'repair_day',lambda *a,variant=0,**kw:result(permutations[variant]))
    import app.repair_constraints as constraints
    def exact(*args,variant=0,**kwargs):
        calls.append(variant)
        return result([2,1,3,4]) if variant==0 else None
    monkeypatch.setattr(constraints,'solve_day',exact)
    rows=ai_planner.variants(state,DAY,[])
    assert 0 in calls and rows[0]['stats']['moved']==2


def test_cancelled_subgroup_without_time_or_room_change_is_not_a_move():
    state=school();row=state['baseLessons'][0]
    row.update(teacherIds=['a','b'],roomIds=['r','spare'])
    state['baseLessons']=[row]
    state['absences']=[{'id':'absence','teacherId':'a','start':DAY,'end':DAY,'first':1,'last':8}]
    result=solve_day(state,DAY)
    assert result and result['stats']['groupLosses']==1 and result['stats']['moved']==0
    assert changed_assignments([row],result['after'])==0


def test_relaxed_room_search_returns_only_a_bound_and_placements():
    bound=solve_day(school(),DAY,allow_room_changes='relaxed')
    assert bound and 'placements' in bound and 'after' not in bound
    assert bound['primaryProven'] and bound['moved']==0


def test_simple_absence_is_grounded_without_model_variability():
    state=school();text='Примерова и Образцовой не будет 10.11'
    row=parse_absence_request(state,DAY,text)
    assert row and row['actions']==canonical_actions([
        {'type':'teacher_absence','teacherId':'a','first':1,'last':8},
        {'type':'teacher_absence','teacherId':'b','first':1,'last':8}])


@pytest.mark.parametrize('text',[
    'Образцова не будет отсутствовать 10.11',
    'Образцова отсутствует только на втором уроке',
    'Образцова отсутствует 11.11',
    'Образцова отсутствует. 7а должны прийти к первому уроку',
    'Примерова не будет, Образцова будет 10.11',
    'Примеров отсутствует, Образцова не отсутствует 10.11',
])
def test_local_parser_never_reinterprets_negation_partial_absence_or_other_conditions(text):
    assert parse_absence_request(school(),DAY,text) is None


def test_ambiguous_surname_is_left_for_clarification():
    state=school();state['teachers'].append({'id':'other','name':'Образцова В.В.','subjectIds':['s']})
    assert parse_absence_request(state,DAY,'Образцовой не будет') is None


def test_simple_absence_preserves_existing_pins_and_other_day_conditions():
    state=school();pin={'type':'pin_lesson','lessonId':'l4','period':4}
    state['assistantConditions']={DAY:[pin]}
    result=parse_absence_request(state,DAY,'Образцовой не будет')
    assert result and pin in result['actions']


def test_cached_previews_are_copies_and_changed_constraints_are_not_reused():
    state=school();ai_planner._variant_cache.clear()
    first=ai_planner.variants(state,DAY,request());expected=deepcopy(projection(first))
    first[0]['after'].clear()
    assert projection(ai_planner.variants(state,DAY,request()))==expected
    different=[{'type':'teacher_absence','teacherId':'b','first':1,'last':8},
               {'type':'class_day','classId':'c0','first':2,'last':7}]
    next_rows=ai_planner.variants(state,DAY,different)
    assert next_rows and min(l['period'] for l in next_rows[0]['after'])==2


def test_simple_absence_api_does_not_call_a_model(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app import server,assistant_api
    from app.store import Store
    monkeypatch.setattr(server,'store',Store(tmp_path/'test.sqlite3',school))
    def forbidden(*args,**kwargs):pytest.fail('A simple grounded absence must not depend on a model')
    service=SimpleNamespace(status=lambda:{'configured':True,'paidEnabled':False,'provider':'deepseek','model':'fictional'},interpret=forbidden)
    monkeypatch.setattr(assistant_api,'connection',lambda:service)
    response=TestClient(server.app).post('/api/assistant/interpret',json={
        'revision':1,'date':DAY,'message':'Примерова и Образцовой не будет 10.11'})
    assert response.status_code==200,response.text
    assert response.json()['draftId'] and response.json()['model']=='Локальный разбор'
    assert server.store.read()['revision']==1


def test_exact_arrival_still_overrides_the_minimum_moves_preference():
    state=school()
    state['absences']=[{'id':'absence','teacherId':'a','start':DAY,'end':DAY,'first':1,'last':8}]
    normal=ai_planner.variants(state,DAY,[])[0]
    assert normal['stats']['moved']==0 and min(l['period'] for l in normal['after'])==2
    explicit=ai_planner.variants(state,DAY,[{'type':'class_day','classId':'c0','first':1,'last':7}])[0]
    assert explicit['stats']['moved']==1 and min(l['period'] for l in explicit['after'])==1
