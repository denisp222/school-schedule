"""Two-phase assistant API: interpret, calculate, then explicitly apply."""
from copy import deepcopy
from functools import lru_cache
import json
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter

from .ai_service import AssistantError, OpenRouter
from . import ai_planner
from .store import Conflict
from .assistant_history import AssistantHistory, redact
from .previews import PreviewStore

router = APIRouter(prefix='/api/assistant')
_drafts = PreviewStore(limit=32)
_previews = PreviewStore(limit=32)
_lock = Lock()

@router.post('/program/apply')
def apply_program(body:dict):
    from .program_assistant import commit
    return commit(body)


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


@router.get('/conversations-export')
def export_conversations():
    from .version import VERSION
    server=context()
    data={'schemaVersion':1,'appVersion':VERSION,'exportedAt':server.store.now(),'conversations':redact(history().export())}
    filename=f'История AI-помощника {server.school_today()}.json'
    return server.attachment(json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'),
                             'application/json',filename)


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
    from .program_assistant import handle
    from .schedule_insights import respond
    try:program=respond(body,current) or handle(body,current)
    except Exception:
        thread_id,turn_id=history().start(body.get('threadId'),day,str(body.get('message',''))[:4000])
        history().finish(turn_id,error='Не удалось обработать просьбу по программе. Данные не изменены.',status='error')
        raise
    if program is not None:return program
    log=history()
    thread=log.get(body['threadId']) if body.get('threadId') else None
    if thread and thread['date']!=day:raise ValueError('Диалог относится к другой дате. Начните новый диалог.')
    past=[{'role':'user','content':turn['request']} for turn in thread['turns']] if thread else body.get('history',[])
    assistant=connection();status=assistant.status()
    messages=ai_planner.messages_for(current['state'],day,body.get('message'),body.get('history',[]),
                                     full_context=status['paidEnabled'],verified_history=past)
    thread_id,turn_id=log.start(body.get('threadId'),day,body.get('message'))
    try:
        from .absence_request import parse_absence_request
        local=(parse_absence_request(current['state'],day,body.get('message'))
               if not body.get('history') and not body.get('threadId') else None)
        if local is not None:raw,model=local,'Локальный разбор'
        else:raw,model=assistant.interpret(messages,expected_provider=status['provider'],expected_model=status['model'])
        raw=ai_planner.ground_joint_refusal(raw,current['state'],day,body.get('message',''),past)
        text='\n'.join(r['content'] for r in past if r.get('role')=='user')+'\n'+body.get('message','')
        draft,labels=ai_planner.review_interpretation(raw,current['state'],day,text)
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
    ready = not draft['questions'] and not draft['unsupported']
    token=remember(_drafts,{'revision':current['revision'],'date':day,'draft':draft,'threadId':thread_id,'turnId':turn_id}) if draft['actions'] else None
    return {**draft,'labels':labels,'draftId':token if ready else None,'partialDraftId':token if not ready else None,
            'model':model,'threadId':thread_id,'turnId':turn_id,
            'revision': current['revision'], 'usage': connection().status()}


@router.post('/explain')
def explain(body:dict):
    from .schedule_insights import respond
    current=snapshot(body)
    token=body.get('previewId')
    if not isinstance(token,str):raise ValueError('Выберите вариант для объяснения.')
    item=_previews.get(token) or context().repair_previews.get(token)
    if not item or item['revision']!=current['revision']:
        raise Conflict('Вариант устарел. Выполните подбор заново.')
    return respond({'date':item['date'],'threadId':item.get('threadId'),
                    'message':'Объясни выбранный вариант расписания.'},current,item['result'])


@router.post('/preview')
def preview(body: dict):
    current = snapshot(body)
    draft = recalled(_drafts, body.get('draftId'), current['revision'])
    day = draft['date']
    response=draft['draft']
    return calculate_previews(body,current,day,response['actions'],omissions=confirmed_omissions(body,response),
                              threadId=draft.get('threadId'),turnId=draft.get('turnId'))


def confirmed_omissions(body,response):
    omitted=[*response.get('questions',[]),*response.get('unsupported',[])]
    if omitted and body.get('confirmedOnly') is not True:
        raise ValueError('Уточните просьбу или выберите подбор по подтверждённым условиям.')
    return omitted


def calculate_previews(body,current,day,actions,*,omissions=(),**metadata):
    server=context()
    from .substitutions import needs_confirmation
    if needs_confirmation(current['state'],day,actions) and body.get('approveSubstitutions') is not True:
        raise ValueError('Подтвердите разовую замену преподавателя перед подбором.')
    turn=metadata.get('turnId')
    try:
        results=ai_planner.variants(current['state'],day,actions)
        snapshot(body)
    except Exception as error:
        if turn:history().record_event(turn,'preview_error',message=str(error) if isinstance(error,ValueError) else
                                       'Не удалось подобрать расписание.',omitted=list(omissions))
        raise
    from .commitments import changes as external_changes
    summaries = []
    for i, result in enumerate(results):
        if omissions:
            result={**result,'unfulfilled':list(dict.fromkeys([*result.get('unfulfilled',[]),*omissions]))}
        applied=result.get('actions',actions)
        token = remember(_previews, {'revision': current['revision'], 'date': day,
                                    'actions':applied,'result':result,**metadata})
        work=ai_planner.prepared_state(current['state'],day,applied)
        work['days'][day]=deepcopy(result['after'])
        payload=server._day_payload(work,day)
        # Compare each option against today's current schedule, not just August.
        payload['base']=deepcopy(result['before']);payload['changes']=result['changes']
        payload['externalChanges']=external_changes(work,day,previous=current['state'])
        summaries.append({**server._repair_summary(result),'day':payload,'previewId':token,'id':i})
    message='' if summaries else ('Согласованная замена не помещается в расписание. Проверьте занятость учителя или выберите другого.'
                                  if any(r['type']=='replace_teacher' for r in actions)
                                  else 'Проверьте расписание и ограничения на выбранный день.')
    if turn:
        from .schedule_insights import variant_facts
        history().record_event(turn,'preview',message=message,omitted=list(omissions),variants=[
            {**{k:r[k] for k in ('id','title','stats','warnings','unfulfilled','search','message')},
             'facts':variant_facts(current['state'],{**r,'actions':results[r['id']].get('actions',actions)})} for r in summaries])
    return {'date':day,'variants':summaries,'revision':current['revision'],'message':message}


@router.post('/replay')
def replay(body:dict):
    current=snapshot(body)
    thread=history().get(str(body.get('threadId','')))
    day=context().require_day(thread['date'])
    requests=[]
    for turn in thread['turns']:
        requests.append(turn['request'])
        if turn['id']==body.get('turnId'):
            response=turn['response'] or {}
            break
    else:
        raise ValueError('Запрос в диалоге не найден.')
    if not response.get('actions'):
        raise ValueError('Условия этого запроса ещё нуждаются в уточнении.')
    omitted=confirmed_omissions(body,response)
    raw={key:response.get(key) for key in ('date','reply','actions','questions','unsupported')}
    draft,_=ai_planner.review_interpretation(raw,current['state'],day,'\n'.join(requests),replay=True)
    omitted=list(dict.fromkeys([*omitted,*confirmed_omissions(body,draft)]))
    if not draft['actions']:raise ValueError('В текущем расписании не осталось условий для повторного подбора.')
    return calculate_previews(body,current,day,draft['actions'],omissions=omitted,threadId=thread['id'],turnId=turn['id'])


def placement_preview(body:dict):
    from .model import indexes,lessons_for_day,parse_date,period_allowed,subject_time_allowed
    from .schemas import integer
    from .class_hours import required_room
    server=context();current=snapshot(body);state=current['state'];day=server.require_day(body.get('date',''))
    rows={l['id']:l for l in lessons_for_day(state,day)}
    source=rows.get(str(body.get('lessonId','')))
    if source is None:raise ValueError('Урок в выбранном дне больше не найден.')
    period=integer(body.get('period'),'Номер урока',minimum=1,maximum=8)
    room_ids=body.get('roomIds')
    room_exceptions=body.get('roomExceptions',[])
    ix=indexes(state)
    if (room_ids is not None and (not isinstance(room_ids,list) or any(not isinstance(r,str) or r not in ix['rooms'] for r in room_ids)
                                  or len(room_ids)!=len(set(room_ids)) or len(room_ids)>len(source['teacherIds'])
                                  or len(source['teacherIds'])>1 and len(room_ids)!=len(source['teacherIds']))
            or not isinstance(room_exceptions,list) or any(not isinstance(r,str) or r not in (room_ids or []) or
                                                           ix['rooms'][r].get('usePolicy')!='manual' for r in room_exceptions)):
        raise ValueError('Проверьте выбранные кабинеты и их соответствие подгруппам.')
    weekday=parse_date(day).weekday()
    if not period_allowed(state,source,period,weekday,date=day):
        raise ValueError('Для восьмого урока нужно отдельное разрешение на эту дату.')
    if not subject_time_allowed(ix['subjects'][source['subjectId']],source,weekday,period,day):
        raise ValueError('Для переноса «Разговоров о важном» укажите номер урока AI-помощнику.')
    if source.get('locked') and (period!=source['period'] or room_ids is not None and room_ids!=source['roomIds']):
        raise ValueError('Снимите закрепление этого урока в редакторе перед перестановкой.')
    fixed=source.get('joint') or source.get('technologyJoint') or source.get('classHour')
    if fixed and (period!=source['period'] or room_ids is not None and
                  (required_room(state,source) and room_ids!=source['roomIds'] or fixed.get('roomId') and room_ids!=source['roomIds'])):
        raise ValueError('Место этого совместного занятия или классного часа задано в его условиях.')
    actions=list(state.get('assistantConditions',{}).get(day,[]))
    actions.append({'type':'place_lesson','lessonId':source['id'],'period':period,'roomIds':room_ids,'roomExceptions':room_exceptions})
    swap_id=body.get('swapId')
    if swap_id:
        partner=rows.get(str(swap_id))
        if (partner is None or partner['id']==source['id'] or partner['period']!=period
                or partner.get('locked') or any(partner.get(key) for key in ('joint','classHour','technologyJoint'))):
            raise ValueError('С этим уроком нельзя обменяться. Выберите другое занятие.')
        actions.append({'type':'place_lesson','lessonId':partner['id'],'period':source['period'],'roomIds':None})
    response=calculate_previews(body,current,day,actions,reason=str(body.get('reason') or 'Ручная перестановка')[:200])
    if not response['variants']:
        response['message']='Для выбранного места с текущими ограничениями подходящий вариант не найден. Выберите другой урок или кабинет.'
    return response


@router.post('/substitution-preview')
def substitution_preview(body:dict):
    from .model import lessons_for_day
    from .substitutions import validate
    server=context()
    current=snapshot(body)
    day=server.require_day(body.get('date',''))
    state=current['state']
    lessons=lessons_for_day(state,day)
    source=next((l for l in lessons if l['id']==body.get('lessonId')),None)
    teacher=body.get('teacherId')
    if not source or not isinstance(teacher,str) or len(source['teacherIds'])!=1:
        raise ValueError('Выберите урок и преподавателя для разовой замены.')
    original=source['teacherIds'][0]
    validate(state,source,{'originalTeacherId':original,'teacherId':teacher})
    selected=[source]
    if body.get('allLessons') is True:
        selected=[l for l in lessons if l['teacherIds']==[original] and l['subjectId']==source['subjectId']
                  and not any(l.get(k) for k in ('joint','technologyJoint','classHour'))]
    replacements=[{'type':'replace_teacher','lessonId':l['id'],'originalTeacherId':original,'teacherId':teacher}
                  for l in selected]
    for lesson,row in zip(selected,replacements):validate(state,lesson,row)
    ids={l['id'] for l in selected}
    actions=[r for r in state.get('assistantConditions',{}).get(day,[])
             if not (r['type']=='replace_teacher' and r['lessonId'] in ids)]+replacements
    if len(actions)>24:raise ValueError('На день уже задано много условий. Снимите ненужные условия и повторите.')
    return calculate_previews(body,current,day,actions,reason='Согласованная разовая замена')


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
    return calculate_previews(body,current,day,draft['actions'])


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
    return calculate_previews(body,current,day,draft['actions'])


@router.post('/apply')
def apply(body: dict):
    server = context()
    current = snapshot(body)
    value = recalled(_previews, body.get('previewId'), current['revision'])
    day = value['date']
    reason=value.get('reason','Перестановки по условиям помощника')
    manual=any(r['type']=='place_lesson' for r in value['actions'])
    saved = server.store.mutate(current['revision'], f'Помощник: изменения на {day}',
                               lambda state: ai_planner.commit(state,day,value['actions'],value['result'],
                                                               reason=reason,save_version=not manual))
    with _lock:
        _previews.pop(body.get('previewId'), None)
    if turn:=value.get('turnId'):
        log=history()
        log.record_event(turn,'applied',title=value['result'].get('title'),stats=value['result']['stats'],
                         warnings=value['result'].get('warnings',[]),unfulfilled=value['result'].get('unfulfilled',[]))
        log.finish(turn,status='applied')
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
