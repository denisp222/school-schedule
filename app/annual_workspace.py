"""A durable annual editor, separate from live days, with dated publication."""
from contextvars import ContextVar
from copy import deepcopy
from datetime import date
from uuid import uuid4
from fastapi import APIRouter
from .store import Conflict,Store

workspace=ContextVar('schedule_workspace',default='live')
router=APIRouter(prefix='/api/annual')
CATALOGS=('teachers','classes','rooms','subjects')


def clean_project(state):
    result=deepcopy(state)
    result.pop('annualDraft',None);result.pop('baseVersions',None)
    for key in ('days','dayBases','assistantConditions','dayNotices'):result[key]={}
    for key in ('journal','absences'):result[key]=[]
    from .class_hours import fill_leaders,sync_labels
    fill_leaders(result);sync_labels(result)
    return result


def effective_week(state,day):
    versions=state.get('baseVersions',[])
    eligible=[v for v in versions if v['start']<=str(day)]
    if eligible:return max(eligible,key=lambda v:v['start'])['lessons']
    return min(versions,key=lambda v:v['start'])['lessons'] if versions else state['baseLessons']


def validate(state):
    from .model import validate_state,check_slots
    draft=state.get('annualDraft')
    if draft is not None:
        if (not isinstance(draft,dict) or not isinstance(draft.get('state'),dict)
                or 'annualDraft' in draft['state'] or 'baseVersions' in draft['state']):
            raise ValueError('Не удалось прочитать черновик базового расписания.')
        try:validate_state(draft['state'])
        except (KeyError,TypeError,ValueError):raise ValueError('Повреждены данные черновика базового расписания.') from None
    versions=state.get('baseVersions',[])
    if not isinstance(versions,list) or len(versions)>40:raise ValueError('Слишком много редакций базового расписания.')
    seen=set()
    ids={kind:{r['id'] for r in state[kind]} for kind in CATALOGS}
    for row in versions:
        try:
            date.fromisoformat(row['start'])
            if row['start'] in seen:raise ValueError()
            seen.add(row['start'])
            if not isinstance(row['lessons'],list):raise ValueError()
            old=clean_project(state);old['baseLessons']=deepcopy(row['lessons'])
            old['plan']=deepcopy(row.get('plan',state['plan']))
            validate_state(old)
        except (KeyError,TypeError,ValueError):raise ValueError('Повреждена редакция базового расписания.') from None


class DraftStore:
    def __init__(self,main):self.main=main

    def read(self):
        value=self.main.read();draft=value['state'].get('annualDraft')
        if not draft:raise ValueError('Сначала создайте черновик базового расписания.')
        return {'revision':value['revision'],'state':deepcopy(draft['state']),'savedAt':draft['updated']}

    def last_saved_at(self):return self.main.last_saved_at()

    def mutate(self,revision,label,fn,**kwargs):
        if kwargs:raise ValueError('Это действие недоступно в редакторе базового расписания.')
        from .model import validate_state
        def change(state):
            draft=state.get('annualDraft')
            if not draft:raise ValueError('Черновик больше не найден.')
            work=deepcopy(draft['state']);result=fn(work)
            draft['state']=validate_state(work if result is None else result)
            draft['updated']=Store.now()
        saved=self.main.mutate(revision,'Черновик: '+label,change)
        return {'revision':saved['revision'],'state':deepcopy(saved['state']['annualDraft']['state']),'savedAt':saved['savedAt']}


def context():
    from . import server
    return server


def allowed_path(path):
    return (path in ('/api/state','/api/bootstrap','/api/save','/api/fill-missing','/api/plan/check','/api/report','/api/report/load')
            or path=='/api/lesson' or path.startswith(('/api/lesson/','/api/entity/','/api/week/','/api/day/','/api/constraints/')))


@router.get('/status')
def status():
    value=context().store.read();state=value['state'];draft=state.get('annualDraft')
    return {'revision':value['revision'],'hasDraft':bool(draft),'updated':draft['updated'] if draft else None,
        'versions':[{'start':r['start'],'label':r.get('label','Базовое расписание')} for r in state.get('baseVersions',[])],
        'futureDays':sorted(state['days'])}


@router.post('/start')
def start(body:dict):
    server=context()
    def change(state):
        if state.get('annualDraft'):return
        state['annualDraft']={'id':uuid4().hex,'updated':Store.now(),'state':clean_project(state)}
    saved=server.store.mutate(server.require_revision(body),'Создан черновик базового расписания',change)
    return {'revision':saved['revision'],'state':saved['state']['annualDraft']['state']}


@router.post('/discard')
def discard(body:dict):
    server=context()
    def change(state):state.pop('annualDraft',None)
    return server.store.mutate(server.require_revision(body),'Удалён черновик базового расписания',change)


@router.post('/clear')
def clear(body:dict):
    server=context()
    def change(state):
        state['baseLessons']=[];state['unscheduledLessons']=[];state['sourceLessons']=[]
        state['loadedDays']=[]
    return DraftStore(server.store).mutate(server.require_revision(body),'Сетка очищена, учебный план сохранён',change)


@router.post('/move')
def move(body:dict):
    server=context();target=server.require_day(body.get('targetDate',''))
    from .model import parse_date,slot_feasible
    from .schemas import integer
    period=integer(body.get('period'),'Номер урока',minimum=1,maximum=8)
    def change(state):
        source=next((l for l in state['baseLessons'] if l['id']==body.get('lessonId')),None)
        other=next((l for l in state['baseLessons'] if l['id']==body.get('targetId')),None)
        if not source:raise ValueError('Исходный урок больше не найден.')
        if source.get('locked') or other and other.get('locked'):raise ValueError('Сначала снимите закрепление с переносимых уроков.')
        original=(source['day'],source['period']);source.update(day=parse_date(target).weekday(),period=period)
        changed=[source]
        if other:
            if other is source:raise ValueError('Выберите другую клетку.')
            other.update(day=original[0],period=original[1]);changed.append(other)
        for lesson in changed:
            if not slot_feasible(state,lesson,lesson['day'],lesson['period']):raise ValueError('Выбранное место нарушает доступность учителя, класса, кабинета или правило предмета.')
    return DraftStore(server.store).mutate(server.require_revision(body),'Перестановка в базовой неделе',change)


@router.post('/publish')
def publish(body:dict):
    server=context();start=server.require_day(body.get('start',''))
    if type(body.get('keepDays')) is not bool:raise ValueError('Укажите, сохранять ли подготовленные изменения на даты.')
    from .model import issues,plan_report,validate_state,base_for_day,period_allowed
    def change(state):
        draft=state.get('annualDraft')
        if not draft:raise ValueError('Сначала подготовьте черновик расписания.')
        work=deepcopy(draft['state'])
        report=plan_report(work)
        from .model import lesson_key
        planned={lesson_key(p) for p in work['plan']}
        if any(lesson_key(l) not in planned for l in work['baseLessons']):
            raise ValueError('В сетке есть уроки вне учебного плана. Добавьте их в план или уберите из черновика.')
        errors=[r for r in issues(work,work['baseLessons']) if r['level']=='error']
        if errors:raise ValueError('Сначала исправьте ошибки черновика: '+errors[0]['message'])
        if (report['missing'] or report['extra']) and body.get('acceptIncomplete') is not True:
            raise ValueError('Распределите часы учебного плана перед вводом расписания.')
        if not work['baseLessons']:raise ValueError('Нельзя ввести пустое расписание.')
        versions=state.get('baseVersions',[])
        if versions and start<=max(v['start'] for v in versions):raise ValueError('Выберите дату позже начала последней редакции базового расписания.')
        if not versions:
            original_start=min(state['school'].get('start','2026-09-01'),start)
            if original_start==start:raise ValueError('Выберите дату после начала действующего учебного года.')
            versions=[{'id':uuid4().hex,'start':original_start,'label':'Прежнее расписание','lessons':deepcopy(state['baseLessons']),'plan':deepcopy(state['plan'])}]
        for day in list(state['days']):
            if day<start:continue
            if body['keepDays']:state['dayBases'].setdefault(day,base_for_day(state,day))
            else:
                for key in ('days','dayBases','assistantConditions','dayNotices'):state.get(key,{}).pop(day,None)
                for row in state['journal']:
                    if row.get('date')==day:row['active']=False
        for kind in CATALOGS:
            incoming=deepcopy(work[kind]);ids={r['id'] for r in incoming}
            for old in state[kind]:
                if old['id'] not in ids:
                    archived=deepcopy(old);archived['archived']=True
                    if kind=='teachers':archived['weeklyTarget']=None
                    incoming.append(archived)
            state[kind]=incoming
        state['school']=deepcopy(work['school']);state['plan']=deepcopy(work['plan'])
        lessons=deepcopy(work['baseLessons']);ids={l['id']:uuid4().hex for l in lessons}
        for lesson in lessons:
            lesson['id']=ids[lesson['id']]
            if lesson.get('splitFrom') in ids:lesson['splitFrom']=ids[lesson['splitFrom']]
        state['baseLessons']=lessons
        state['unscheduledLessons']=deepcopy(work.get('unscheduledLessons',[]))
        versions.append({'id':uuid4().hex,'start':start,'label':'Базовое расписание с '+start,'lessons':deepcopy(lessons),'plan':deepcopy(work['plan'])})
        state['baseVersions']=versions;state.pop('annualDraft',None)
        return validate_state(state)
    return server.store.mutate(server.require_revision(body),'Введено новое базовое расписание с '+start,change)


@router.get('/review')
def review():
    from .model import issues,plan_report,lesson_key
    work=DraftStore(context().store).read()['state']
    checks=issues(work,work['baseLessons'])
    planned={lesson_key(p) for p in work['plan']}
    unplanned=[l['id'] for l in work['baseLessons'] if lesson_key(l) not in planned]
    if unplanned:checks.append({'level':'error','code':'unplanned','message':'В сетке есть уроки вне учебного плана.','lessonIds':unplanned})
    return {'report':plan_report(work),'issues':checks}
