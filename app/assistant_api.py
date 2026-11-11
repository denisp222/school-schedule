"""Two-phase assistant API: interpret, calculate, then explicitly apply."""
from copy import deepcopy
from functools import lru_cache
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter

from .ai_service import AssistantError, OpenRouter
from . import ai_planner
from .store import Conflict
from .assistant_history import AssistantHistory
from .previews import PreviewStore

router = APIRouter(prefix='/api/assistant')
_drafts = PreviewStore(limit=32)
_previews = PreviewStore(limit=32)
_lock = Lock()


def context():
    from . import server
    return server


@lru_cache(maxsize=4)
def service(path):
    return OpenRouter(path / 'assistant-connection.json')


def connection():
    return service(context().DATA)


def history():return AssistantHistory(context().store)


@router.get('/conversations')
def conversations(offset:int=0):
    rows=history().list(offset)
    return {'conversations':rows,'hasMore':len(rows)==100}


@router.get('/conversations/{thread_id}')
def conversation(thread_id:str):return history().get(thread_id)


@router.post('/conversations/{thread_id}/delete')
def delete_conversation(thread_id:str):
    assistant=connection()
    if not assistant.request_lock.acquire(blocking=False):raise ValueError('Дождитесь завершения запроса помощника перед удалением диалога.')
    try:history().delete(thread_id)
    finally:assistant.request_lock.release()
    return {'deleted':True}


def remember(bucket, value):
    token=uuid4().hex
    bucket[token]=value
    return token


def recalled(bucket, token, revision):
    row=bucket.get(token)
    if not row or row['revision']!=revision:
        raise Conflict('Условия или вариант устарели. Повторите просьбу с текущим расписанием.')
    return row


def snapshot(body):
    server = context()
    revision = server.require_revision(body)
    value = server.store.read()
    if value['revision'] != revision:
        raise Conflict('Расписание изменилось. Повторите просьбу с текущими данными.')
    return value


@router.get('/settings')
def settings():
    return connection().status()


@router.post('/settings')
def configure(body: dict):
    return connection().configure(body)


@router.post('/check')
def check(body: dict):
    return connection().check()


@router.post('/probe')
def probe(body: dict):
    return connection().probe()


@router.post('/balance')
def balance(body: dict):
    return connection().balance()


@router.post('/open-balance')
def open_balance(body: dict):
    import webbrowser
    url=connection().account_links(body.get('provider'))['balance']
    if not webbrowser.open(url):
        raise AssistantError(f'Откройте {url} в браузере.')
    return {'opened':True}


@router.post('/open-keys')
def open_keys(body: dict):
    import webbrowser
    url=connection().account_links(body.get('provider'))['keys']
    if not webbrowser.open(url):
        raise AssistantError(f'Не удалось открыть браузер. Откройте {url} вручную.')
    return {'opened': True}


@router.post('/interpret')
def interpret(body: dict):
    server = context()
    day = server.require_day(body.get('date', ''))
    current = snapshot(body)
    assistant=connection();status=assistant.status()
    messages=ai_planner.messages_for(current['state'],day,body.get('message'),body.get('history',[]),
                                     full_context=status['paidEnabled'])
    log=history()
    thread_id,turn_id=log.start(body.get('threadId'),day,body.get('message'))
    try:
        from .absence_request import parse_absence_request
        local=(parse_absence_request(current['state'],day,body.get('message'))
               if not body.get('history') and not body.get('threadId') else None)
        if local is not None:raw,model=local,'Локальный разбор'
        else:raw,model=assistant.interpret(messages,expected_provider=status['provider'],expected_model=status['model'])
        raw=ai_planner.ground_joint_refusal(raw,current['state'],day,body.get('message',''))
        text='\n'.join(r['content'] for r in body.get('history',[]) if r.get('role')=='user')+'\n'+body.get('message','')
        draft,labels=ai_planner.validate_interpretation(raw,current['state'],day,text)
        from .search_policy import canonical_actions
        draft['actions']=canonical_actions(draft['actions'])
    except Exception as exc:
        log.finish(turn_id,error=str(exc) if isinstance(exc,ValueError) else 'Не удалось обработать просьбу. Расписание не изменено.',status='error')
        raise
    log.finish(turn_id,response={**draft,'labels':labels,'model':model})
    # Preserve the answer in history even if an edit invalidated its draft.
    try:snapshot(body)
    except Conflict:
        log.finish(turn_id,error='Расписание изменилось во время запроса. Повторите просьбу.',status='stale')
        raise
    ready = bool(draft['actions']) and not draft['questions'] and not draft['unsupported']
    token=remember(_drafts,{'revision':current['revision'],'date':day,'draft':draft,'threadId':thread_id,'turnId':turn_id}) if ready else None
    return {**draft,'labels':labels,'draftId':token,'model':model,'threadId':thread_id,'turnId':turn_id,
            'revision': current['revision'], 'usage': connection().status()}


@router.post('/preview')
def preview(body: dict):
    server = context()
    current = snapshot(body)
    draft = recalled(_drafts, body.get('draftId'), current['revision'])
    day = draft['date']
    results = ai_planner.variants(current['state'], day, draft['draft']['actions'])
    snapshot(body)
    if not results:
        return {'date': day, 'variants': [], 'revision': current['revision'],
                'message': 'Вариант по всем условиям без окон пока не найден. Попробуйте изменить время прихода класса или закрепление урока. Расписание не изменено.'}
    summaries = []
    for i, result in enumerate(results):
        actions=result.get('actions',draft['draft']['actions'])
        token = remember(_previews, {'revision': current['revision'], 'date': day,
                                    'actions':actions,'result':result,
                                    'threadId':draft.get('threadId'),'turnId':draft.get('turnId')})
        work=ai_planner.prepared_state(current['state'],day,actions)
        work['days'][day]=deepcopy(result['after'])
        payload=server._day_payload(work,day)
        # Compare each option against today's current schedule, not just August.
        payload['base']=deepcopy(result['before']);payload['changes']=result['changes']
        summaries.append({**server._repair_summary(result),'day':payload,'previewId':token,'id':i})
    return {'date': day, 'variants': summaries, 'revision': current['revision']}


@router.post('/class-hour-preview')
def class_hour_preview(body: dict):
    server=context();current=snapshot(body);day=server.require_day(body.get('date',''))
    classes=body.get('classIds')
    if not isinstance(classes,list) or not classes or len(classes)>24 or any(not isinstance(c,str) for c in classes) or len(classes)!=len(set(classes)):
        raise ValueError('Выберите классы для классного часа.')
    actions=[a for a in current['state'].get('assistantConditions',{}).get(day,[])
             if not (a['type']=='class_hour' and a['classId'] in classes)]
    from .schemas import integer
    period=integer(body.get('period',1),'Урок классного часа',minimum=1,maximum=7)
    actions += [{'type':'class_hour','classId':c,'lessonId':None,'period':period} for c in classes]
    raw={'date':day,'reply':'Классный час','questions':[],'unsupported':[],'actions':actions}
    draft,_=ai_planner.validate_interpretation(raw,current['state'],day,'Назначить классный час первым уроком')
    results=ai_planner.variants(current['state'],day,draft['actions']);snapshot(body)
    summaries=[]
    for i,result in enumerate(results):
        actions=result.get('actions',draft['actions'])
        token=remember(_previews,{'revision':current['revision'],'date':day,'actions':actions,'result':result})
        work=ai_planner.prepared_state(current['state'],day,actions);work['days'][day]=deepcopy(result['after'])
        payload=server._day_payload(work,day);payload.update(base=deepcopy(result['before']),changes=result['changes'])
        summaries.append({**server._repair_summary(result),'day':payload,'previewId':token,'id':i})
    return {'date':day,'revision':current['revision'],'variants':summaries,
            'message':'' if summaries else 'Классный час не удалось разместить без окон и пересечений. Проверьте занятость классных руководителей и спаренные уроки.'}


@router.post('/technology-preview')
def technology_preview(body: dict):
    """Local planner: no model, credential or network request is involved."""
    server=context();current=snapshot(body)
    day=server.require_day(body.get('date',''))
    fields=('teacherId','sameClass','girlsClasses','boysClasses','safetyApproved','classIds')
    permission={'type':'allow_technology',**{key:body.get(key) for key in fields}}
    raw={'date':day,'reply':'Разрешения технологии','questions':[],'unsupported':[],
         'actions':[a for a in current['state'].get('assistantConditions',{}).get(day,[]) if a['type']!='allow_technology']+[permission]}
    confirmation='Разрешаю указанные объединения подгрупп технологии'
    if body.get('safetyApproved') is True:confirmation+='; подтверждаю безопасные условия работы'
    draft,_=ai_planner.validate_interpretation(raw,current['state'],day,confirmation)
    results=ai_planner.variants(current['state'],day,draft['actions'])
    snapshot(body)
    summaries=[]
    for i,result in enumerate(results):
        actions=result.get('actions',draft['actions'])
        token=remember(_previews,{'revision':current['revision'],'date':day,'actions':actions,'result':result})
        work=ai_planner.prepared_state(current['state'],day,actions);work['days'][day]=deepcopy(result['after'])
        payload=server._day_payload(work,day);payload.update(base=deepcopy(result['before']),changes=result['changes'])
        summaries.append({**server._repair_summary(result),'day':payload,'previewId':token,'id':i})
    return {'date':day,'variants':summaries,'revision':current['revision'],
            'message':'' if summaries else 'Без окон у учеников вариант не найден. Проверьте состав подгрупп и условия дня.'}


@router.post('/apply')
def apply(body: dict):
    server = context()
    current = snapshot(body)
    value = recalled(_previews, body.get('previewId'), current['revision'])
    day = value['date']
    saved = server.store.mutate(current['revision'], f'Помощник: изменения на {day}',
                               lambda state: ai_planner.commit(state, day, value['actions'], value['result']))
    with _lock:
        _previews.pop(body.get('previewId'), None)
    if value.get('turnId'):history().finish(value['turnId'],status='applied')
    return {'revision': saved['revision'], 'state': saved['state'], 'day': server._day_payload(saved['state'], day)}


@router.post('/clear-conditions')
def clear_conditions(body: dict):
    server = context()
    day = server.require_day(body.get('date', ''))
    current = snapshot(body)
    def change(state):
        state.get('assistantConditions', {}).pop(day, None)
        for lesson in state['days'].get(day, []):
            if lesson.pop('assistantPinned', False):
                lesson['locked'] = False
    saved = server.store.mutate(current['revision'], f'Сняты условия помощника на {day}', change)
    return {'revision': saved['revision'], 'state': saved['state']}
