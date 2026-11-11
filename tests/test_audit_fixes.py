"""Public regressions: wholly artificial data, no school fixtures or API keys."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import ai_budget, model, solver_process
from app.previews import PreviewStore
from app.store import Store


def demo():
    return model.normalize_state(json.loads((Path(model.__file__).parent/'demo_seed.json').read_text(encoding='utf-8')))


def test_connections_close_and_independent_backup_can_be_restored(tmp_path):
    store=Store(tmp_path/'project.sqlite3',demo)
    with store.connect() as connection:connection.execute('SELECT 1')
    with pytest.raises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
    store.mutate(1,'Example',lambda s:s['school'].update(name='Edited demo'))
    backup=sqlite3.connect(tmp_path/'project.sqlite3.bak')
    try:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        state=json.loads(backup.execute('SELECT payload FROM current_state').fetchone()[0])
        assert state['school']['name']=='Edited demo'
    finally:backup.close()


def test_failed_mutation_rolls_back_and_closes(tmp_path):
    store=Store(tmp_path/'project.sqlite3',demo)
    def fail(state):raise ValueError('failure')
    with pytest.raises(ValueError):store.mutate(1,'bad',fail)
    assert store.read()['revision']==1
    store.mutate(1,'good',lambda s:s)
    assert store.read()['revision']==2


def test_backup_failure_and_locked_temp_never_report_committed_edit_as_failed(tmp_path,monkeypatch):
    store=Store(tmp_path/'project.sqlite3',demo)
    connect=sqlite3.connect
    def cannot_create_backup(path,*args,**kwargs):
        if str(path).endswith('.tmp'):raise PermissionError('fixture')
        return connect(path,*args,**kwargs)
    unlink=Path.unlink
    def cannot_remove_backup(path,*args,**kwargs):
        if path.suffix=='.tmp':raise PermissionError('fixture')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(sqlite3,'connect',cannot_create_backup)
    monkeypatch.setattr(Path,'unlink',cannot_remove_backup)
    result=store.mutate(1,'Example',lambda s:s['school'].update(name='Committed'))
    assert result['revision']==2 and store.read()['state']['school']['name']=='Committed'


def test_preview_expiry_fifo_copy_and_concurrent_access():
    now=[0]
    cache=PreviewStore(limit=2,ttl=5,clock=lambda:now[0])
    cache['a']={'items':[1]};cache['b']={'items':[2]};cache['c']={'items':[3]}
    assert cache.get('a') is None and cache['b']['items']==[2]
    cache['b']['items'].append(9)
    assert cache['b']['items']==[2]
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda n:cache.__setitem__(str(n),{'n':n}),range(100)))
    assert len(cache)==2
    now[0]=6
    assert len(cache)==0


def test_abandoned_budget_reserve_expires_without_refunding_unknown_charge(monkeypatch):
    now=[1000];monkeypatch.setattr(ai_budget,'time',lambda:now[0])
    data={'monthlyLimitUSD':'1'};token=ai_budget.reserve(data,[],0,1)
    expected=ai_budget.estimate([])
    now[0]+=601
    assert Decimal(ai_budget.summary(data)['spentUSD'])==expected
    assert not data['billing']['reservations']
    ai_budget.settle(data,token,'.001')
    assert Decimal(ai_budget.summary(data)['spentUSD'])==Decimal('.001')


def test_worker_isolation_in_development_and_kind_timeouts(monkeypatch):
    monkeypatch.delenv('SCHEDULE_SOLVER_WORKER',raising=False)
    assert solver_process.isolated()
    seen=[]
    def failed(*args,**kwargs):
        seen.append(kwargs['timeout']);raise subprocess.TimeoutExpired(args[0],kwargs['timeout'],stderr=b'fixture')
    monkeypatch.setattr(solver_process.subprocess,'run',failed)
    for kind in ('day','annual','speech'):
        with pytest.raises(ValueError):solver_process.calculate(kind,{})
    assert seen==[30,60,170]


@pytest.mark.slow
def test_real_worker_roundtrip_without_school_data():
    state=demo();original=deepcopy(state)
    result=solver_process.calculate('day',{'state':state,'day':'2026-11-10'})
    assert result['after'] and not model.check_slots(result['after'])
    assert state==original


def test_odd_paired_lessons_do_not_report_false_separation():
    state=demo();state['plan'][0].update(doubleLessons=True,hours=4,maxPerDay=4)
    first=state['baseLessons'][0]
    lessons=[dict(first,id=f'p{p}',period=p) for p in (3,5,6)]
    codes={r['code'] for r in model.issues(state,lessons,'2026-11-10')}
    assert 'pair_incomplete' in codes and 'pair_separated' not in codes


def test_fixed_eighth_rule_survives_renaming_and_never_expands_other_lessons():
    state=demo();lesson=state['baseLessons'][0];lesson.update(day=3,period=8)
    state['school']['eighthPeriodException']={k:deepcopy(lesson[k]) for k in ('day','period','classIds','teacherIds','subjectId')}
    state['teachers'][0]['name']='Renamed example'
    state=model.normalize_state(state)
    assert model.period_allowed(state,lesson)
    assert not model.period_allowed(state,lesson,7,3)
    assert not model.period_allowed(state,{**lesson,'teacherIds':['other']})


@pytest.fixture
def client(tmp_path,monkeypatch):
    from app import server
    monkeypatch.setattr(server,'store',Store(tmp_path/'api.sqlite3',demo))
    return TestClient(server.app)


@pytest.mark.parametrize('path',['/api/state','/api/backup','/api/export/teachers/2026-11-10','/api/report-csv/teachers'])
@pytest.mark.parametrize('headers',[{'Sec-Fetch-Site':'cross-site'},{'Sec-Fetch-Site':'same-site'},{'Origin':'https://foreign.invalid'}])
def test_cross_origin_reads_cannot_download_school_data(client,path,headers):
    assert client.get(path,headers=headers).status_code==403


def test_same_origin_navigation_still_works(client):
    assert client.get('/api/state',headers={'Origin':'http://testserver','Sec-Fetch-Site':'same-origin'}).status_code==200


@pytest.mark.parametrize('value',['wrong',None,{},[],True,1.5])
def test_bad_numeric_input_has_readable_message_and_never_mutates(client,value):
    response=client.post('/api/lesson/move',json={'revision':1,'date':'2026-11-10','lessonId':'demo-lesson','period':value})
    assert response.status_code==422
    assert 'целое число' in response.json()['detail']
    assert client.get('/api/state').json()['revision']==1


def test_initial_project_without_school_seed_is_empty(monkeypatch,tmp_path):
    monkeypatch.setattr(model,'SEED',tmp_path/'absent.json')
    state=model.initial_state()
    assert all(not state[key] for key in ('teachers','classes','plan','baseLessons'))


def test_cache_stores_raw_results_and_separates_modes(monkeypatch):
    from app import engine, repair_constraints
    engine._exact_cache.clear()
    state=demo();day='2026-11-10';lessons=deepcopy(state['baseLessons']);calls=[]
    greedy={'status':'ok','date':day,'before':lessons,'after':lessons,'changes':[],'warnings':[],
            'stats':{'seconds':2,'moved':0}}
    monkeypatch.setattr(engine,'_repair_greedy',lambda *a,**k:deepcopy(greedy))
    def exact(*args,**kwargs):
        calls.append((args,kwargs))
        return {'status':'unchanged','date':day,'before':lessons,'after':lessons,'changes':[],
                'warnings':[],'stats':{'seconds':5,'moved':0}}
    monkeypatch.setattr(repair_constraints,'solve_day',exact)
    monkeypatch.setattr(engine,'repair_problems',lambda s,r:[] if r['status']=='unchanged' else ['fixture'])
    first=engine.repair_day(state,day);first['warnings'].append('poison')
    second=engine.repair_day(state,day)
    assert second['stats']['seconds']==7 and second['warnings']==[] and len(calls)==1
    engine.repair_day(state,day,variant=1)
    engine.repair_day(state,day,optimize=True)
    assert len(calls)==3
    engine._exact_cache.clear()


def test_annual_fill_uses_school_week_without_touching_daily_experiments(monkeypatch):
    from app import engine
    state=demo();state['school']['start']='2030-09-02';state['plan'][0]['hours']=2
    state['days']={'2026-11-10':deepcopy(state['baseLessons'])}
    seen=[];real=engine.Grid
    def grid(s,day,*args,**kwargs):
        seen.append(day)
        assert not s['days'] and not s['assistantConditions']
        return real(s,day,*args,**kwargs)
    monkeypatch.setattr(engine,'Grid',grid)
    before=deepcopy(state)
    result=engine.fill_missing_hours(state,apply=True)
    assert seen and seen[0]=='2030-09-02'
    assert result['state']['days']==state['days'] and state==before


def test_retry_handles_rejection_and_malformed_json_with_separate_budgets(tmp_path,monkeypatch):
    import httpx
    from app import ai_service
    monkeypatch.setattr(ai_service,'sleep',lambda _:None)
    responses=[httpx.Response(429,json={'error':{'message':'busy'}}),
               httpx.Response(200,json={'usage':{'cost':.001},'choices':[{'message':{'content':'{}'}}]})]
    def transport(request):
        if request.method=='GET':
            return httpx.Response(200,json={'data':{'usage_monthly':0,'total_credits':1,'total_usage':0}})
        return responses.pop(0)
    service=ai_service.OpenRouter(tmp_path/'connection.json',transport=httpx.MockTransport(transport))
    service.configure({'apiKey':'sk-or-v1-'+'fictional'*6,'model':ai_budget.PAID_MODEL,'paidEnabled':True})
    service.interpret([])
    assert not responses and Decimal(service.status()['budget']['spentUSD'])==Decimal('.001')
    responses.extend([httpx.Response(200,json={'usage':{'cost':.002},'choices':[{'message':{'content':'invalid'}}]}),
                      httpx.Response(200,json={'usage':{'cost':.003},'choices':[{'message':{'content':'{}'}}]})])
    service.interpret([])
    assert not responses and Decimal(service.status()['budget']['spentUSD'])==Decimal('.006')


def test_connection_failure_is_not_charged_but_read_timeout_is(tmp_path,monkeypatch):
    import httpx
    from app import ai_service
    monkeypatch.setattr(ai_service,'sleep',lambda _:None)
    failure=[httpx.ConnectError];posts=[]
    def transport(request):
        if request.method=='GET':return httpx.Response(200,json={'data':{'usage_monthly':0,'total_credits':1,'total_usage':0}})
        posts.append(1);raise failure[0]('fixture')
    service=ai_service.OpenRouter(tmp_path/'connection.json',transport=httpx.MockTransport(transport))
    service.configure({'apiKey':'sk-or-v1-'+'fictional'*6,'model':ai_budget.PAID_MODEL,'paidEnabled':True})
    with pytest.raises(ai_service.AssistantError):service.interpret([])
    assert len(posts)==2 and Decimal(service.status()['budget']['spentUSD'])==0
    posts.clear();failure[0]=httpx.ReadTimeout
    with pytest.raises(ai_service.AssistantError):service.interpret([])
    assert len(posts)==1 and Decimal(service.status()['budget']['spentUSD'])==ai_budget.estimate([])
