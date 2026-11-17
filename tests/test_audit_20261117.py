"""Audit regressions: real behavior on artificial projects, no school data."""
import base64,json,re,subprocess,sys,os
from copy import deepcopy
from datetime import date,timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from app import engine,model,server,updates,commitments
from app.store import Store
from app.update_api import UpdateManager
from app.display_labels import individual_labels,room_label
from test_rotation_and_individuals import rotating,session
from test_updates import signed


@pytest.fixture
def client(tmp_path,monkeypatch):
    store=Store(tmp_path/'synthetic.sqlite3',rotating)
    monkeypatch.setattr(server,'store',store);monkeypatch.setattr(server,'DATA',tmp_path)
    return TestClient(server.app),store


def test_word_labels_have_no_names_and_disambiguate_two_pupils(tmp_path,monkeypatch):
    from app import exporter
    state=rotating()
    state['individualLearners']=[{'id':'first','classId':'one','name':'Личное имя первого'},
        {'id':'second','classId':'one','name':'Личное имя второго'},
        {'id':'third','classId':'two','name':'Личное имя третьего'}]
    assert individual_labels(state)=={'first':'инд1 6а','second':'инд2 6а','third':'инд 6б'}
    state['rooms'].append({'id':'lab','name':'315 лаборантская'})
    state['externalActivities']=[session(learnerId='first',label='Личное имя первого',roomId='lab'),
        session(id='second',learnerId='second',label='Личное имя второго',first=4,last=4,roomId='lab')]
    monkeypatch.setattr(exporter,'template_path',lambda *a:tmp_path/'missing.docx')
    raw=exporter.export_docx(state,'2026-11-24','teachers')
    text=ZipFile(BytesIO(raw)).read('word/document.xml').decode()
    assert 'инд1 6а' in text and 'инд2 6а' in text and '315л' in text
    assert 'Личное' not in text and 'лаборантская' not in text


@pytest.mark.parametrize('source,short',[('Кабинет логопеда','лог.'),('Логопед','лог.'),('Лаб. 213','213л'),('310 лаборантская','310л'),('каб. 101','101'),('216','216')])
def test_room_labels_are_short(source,short):assert room_label(source)==short


def test_long_subject_codes_are_short_in_individual_report_cells():
    from app.display_labels import subject_code
    assert subject_code({'name':'Биология','teacherCode':'Биология'})=='б'
    assert subject_code({'name':'Информатика','short':'Информатика'})=='инф'
    assert subject_code({'name':'ОБЗР','teacherCode':'ОБЗР'})=='об'


def test_eighth_word_column_preserves_pupil_number_class_and_room(tmp_path,monkeypatch):
    from app import exporter
    state=rotating();state['individualLearners'].append({'id':'second','name':'Ещё ученик','classId':'one'})
    state['externalActivities']=[session(first=8,last=8,allowEighth=True,roomId='r1')]
    monkeypatch.setattr(exporter,'template_path',lambda *a:tmp_path/'missing.docx')
    text=ZipFile(BytesIO(exporter.export_docx(state,'2026-11-24','teachers'))).read('word/document.xml').decode()
    assert 'и1 6а 101' in text and 'Индивидуальный ученик' not in text


def test_exact_fallback_receives_the_day_conditions(monkeypatch):
    from app import repair_constraints
    state=rotating();conditions=[{'type':'pin_lesson','lessonId':'a3','period':3}]
    state['assistantConditions']={'2026-11-25':conditions}
    fake={'before':deepcopy(state['baseLessons']),'after':deepcopy(state['baseLessons']),
        'date':'2026-11-25','changes':[],'stats':{},'status':'ok'}
    monkeypatch.setattr(engine,'_repair_greedy',lambda *a,**k:deepcopy(fake))
    monkeypatch.setattr(engine,'repair_problems',lambda *a:['Нужен точный расчёт'])
    calls=[]
    monkeypatch.setattr(repair_constraints,'solve_day',lambda *a,**k:calls.append(k) or None)
    engine._exact_cache.clear();engine.repair_day(state,'2026-11-25')
    assert calls[0]['conditions']==conditions


def test_day_repair_reaches_exact_search_when_only_a_saved_pin_is_violated():
    state=rotating();day='2026-11-25'
    state['assistantConditions']={day:[{'type':'pin_lesson','lessonId':'a1','period':4}]}
    result=engine.repair_day(state,day)
    assert result['status']=='ok'
    assert next(l for l in result['after'] if l['id']=='a1')['period']==4
    assert not engine.repair_problems(state,result)


def test_occupancy_index_is_local_and_reused_by_grid_candidates(monkeypatch):
    state=rotating();state['externalActivities']=[session(roomId='r1')]
    grid=engine.Grid(state,'2026-11-24',[])
    assert ('a',2) in grid.external_slots['teachers'] and ('r1',2) in grid.external_slots['rooms']
    monkeypatch.setattr(commitments,'matching',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Repeated full scan')))
    copied=grid.copy();lesson=deepcopy(state['baseLessons'][2])
    assert copied.external_slots is grid.external_slots
    assert not copied.can_place(lesson,2)


def test_update_helper_acknowledges_before_waiting_and_checks_paths(signed,tmp_path,monkeypatch):
    _,payload,_,body=signed;setup=tmp_path/'setup.exe';setup.write_bytes(body)
    monkeypatch.setenv('SystemRoot','C:/Windows');seen=[]
    class Helper:
        def poll(self):return None
    def launch(command,**kwargs):
        assert not kwargs['creationflags']&subprocess.DETACHED_PROCESS
        script=base64.b64decode(command[-1]).decode('utf-16le');seen.append(script)
        marker=re.search(r"WriteAllText\('([^']+)', 'ready'\)",script).group(1)
        Path(marker).write_text('ready',encoding='utf-8')
        return Helper()
    monkeypatch.setattr(updates.subprocess,'Popen',launch)
    updates.launch_installer(setup,tmp_path,payload)
    assert seen[0].index('Get-FileHash')<seen[0].index('WriteAllText')<seen[0].index('Wait-Process')
    assert not list(tmp_path.glob('helper-ready-*'))
    with pytest.raises(ValueError):updates.install_script(setup,'C:/bad"folder',1,'a'*64)


@pytest.mark.skipif(os.name!='nt',reason='Windows update helper')
def test_real_hidden_powershell_executes_and_acknowledges(signed,tmp_path,monkeypatch):
    _,payload,_,body=signed;setup=tmp_path/'setup.exe';setup.write_bytes(body)
    witness=tmp_path/'executed.txt'
    def script(installer,folder,pid,sha,ready=None):
        return '[System.IO.File]::WriteAllText('+updates.ps_quote(witness)+", 'ok');[System.IO.File]::WriteAllText("+updates.ps_quote(ready)+", 'ready'); Start-Sleep -Milliseconds 300"
    monkeypatch.setattr(updates,'install_script',script)
    updates.launch_installer(setup,tmp_path,payload)
    assert witness.read_text()=='ok'


def test_failed_helper_keeps_application_open_and_allows_retry(signed,tmp_path,monkeypatch):
    _,payload,_,body=signed;setup=tmp_path/'setup.exe';setup.write_bytes(body);closed=[]
    manager=UpdateManager(tmp_path,tmp_path,tmp_path,lambda:closed.append(True))
    manager.payload=payload;manager.installer=setup;manager.view['stage']='ready'
    monkeypatch.setattr(updates,'backup_before_update',lambda *a:None)
    monkeypatch.setattr(updates,'launch_installer',lambda *a:(_ for _ in ()).throw(ValueError('Helper failed')))
    with pytest.raises(ValueError,match='продолжает работать'):manager.install()
    assert not closed and manager.status()['stage']=='error' and not manager.attempt.exists()


@pytest.mark.parametrize('raw',[{'repository':'owner/repo'},{'repository':'owner/repo','publicKey':None},[]])
def test_invalid_channel_has_friendly_error(tmp_path,monkeypatch,raw):
    path=tmp_path/'channel.json';path.write_text(json.dumps(raw))
    monkeypatch.setattr(updates,'CHANNEL',path)
    with pytest.raises(ValueError):updates.channel()


def test_bounded_save_terminates_on_timeout_without_overwriting(tmp_path,monkeypatch):
    from app import file_save,solver_process
    target=tmp_path/'report.docx';target.write_bytes(b'old')
    def timeout(*a,**k):raise subprocess.TimeoutExpired(a[0],30)
    monkeypatch.setattr(solver_process.subprocess,'run',timeout)
    with pytest.raises(ValueError,match='Сохранение остановлено'):file_save.save_bounded(target,b'new',tmp_path)
    assert target.read_bytes()==b'old'


def test_bounded_save_real_worker_roundtrip(tmp_path):
    from app.file_save import save_bounded
    target=tmp_path/'report.docx';path,fallback=save_bounded(target,b'local prepared report',tmp_path)
    assert path==target and not fallback and target.read_bytes()==b'local prepared report'


@pytest.mark.parametrize('record',[{'name':'','classId':'one'},{'name':'Ученик','classId':'missing'},{'name':'Ученик','classId':'one','allowGaps':'yes'}])
def test_learner_api_already_rejects_invalid_data_atomically(client,record):
    api,store=client;before=store.read()
    result=api.post('/api/extras/learner',json={'revision':before['revision'],'record':record})
    assert result.status_code==422 and store.read()==before


def test_eighth_exception_rejects_unknown_references_even_with_optimized_python(client):
    api,store=client;before=store.read()
    result=api.post('/api/constraints/eighth',json={'revision':1,'enabled':True,'day':3,'classId':'missing','teacherId':'a','subjectId':'math'})
    assert result.status_code==422 and store.read()==before
    code="from app.rules import eighth_exception; s={'school':{'eighthPeriodException':{'day':3,'period':8,'classIds':['missing'],'teacherIds':['a'],'subjectId':'m'}},'classes':[],'teachers':[],'subjects':[]}; eighth_exception(s)"
    result=subprocess.run([sys.executable,'-O','-c',code],capture_output=True)
    assert result.returncode!=0 and b'ValueError' in result.stderr


def test_external_validation_expires_nonoverlapping_date_intervals(monkeypatch):
    state=rotating();state['externalActivities']=[]
    monday=date(2026,11,9)
    for n in range(300):
        day=str(monday+timedelta(weeks=n))
        state['externalActivities'].append(session(id=str(n),weekday=0,start=day,end=day))
    calls=[];original=commitments._ranges_overlap
    monkeypatch.setattr(commitments,'_ranges_overlap',lambda *a:(calls.append(True),original(*a))[1])
    commitments.validate(state)
    assert len(calls)==0


def test_incumbent_bound_uses_solver_cost_not_presentation_totals():
    from test_deterministic_repair import school,DAY
    from app.repair_constraints import solve_day
    state=school();state['absences']=[{'id':'absence','teacherId':'b','start':DAY,'end':DAY,'first':1,'last':8}]
    first=solve_day(state,DAY,allow_room_changes=True)
    assert first and first['search']['modelCost']['moved']>=1
    incumbent=deepcopy(first);incumbent['stats'].update(moved=0,lostHours=0,classGapsAfter=0,youngerLate=0)
    second=solve_day(state,DAY,allow_room_changes=True,_incumbent=incumbent)
    assert second and second['search']['modelCost']==first['search']['modelCost']


def test_class_hour_validation_survives_optimized_python():
    state=rotating()
    lesson={'id':'class-hour','day':2,'period':1,'classIds':['one'],'teacherIds':['missing'],'roomIds':[],
        'subjectId':'school-class-hour','classHour':{'date':'2026-11-25','classIds':['one'],'teacherId':'missing','sources':[]}}
    code="import json,sys;from app.class_hours import problems;s,l=json.loads(sys.argv[1]);sys.exit(0 if problems(s,l,'2026-11-25') else 1)"
    r=subprocess.run([sys.executable,'-O','-c',code,json.dumps([state,lesson])],capture_output=True)
    assert r.returncode==0,r.stderr


def test_constraint_and_catalog_use_the_same_daily_limit(client):
    from app.schemas import FIELD_BOUNDS
    api,store=client;maximum=FIELD_BOUNDS['maxDaily'][1]
    r=api.post('/api/constraints/availability',json={'revision':1,'kind':'teachers','id':'a','allowed':[[2,1]],'maxDaily':maximum})
    assert r.status_code==200,r.text
    before=store.read()
    r=api.post('/api/constraints/availability',json={'revision':before['revision'],'kind':'teachers','id':'a','allowed':[[2,1]],'maxDaily':maximum+1})
    assert r.status_code==422 and store.read()==before


def test_day_count_includes_extra_lessons_and_excludes_cancellations(client):
    api,store=client
    store.mutate(1,'Пример',lambda s:s['externalActivities'].append(session()))
    day=api.get('/api/day/2026-11-24').json()
    assert day['stats']['lessons']==len(day['lessons'])+1
    r=api.post('/api/extras/day',json={'revision':2,'date':'2026-11-24','record':session(cancelled=True)})
    assert r.status_code==200,r.text
    day=api.get('/api/day/2026-11-24').json()
    assert day['stats']['lessons']==len(day['lessons'])
