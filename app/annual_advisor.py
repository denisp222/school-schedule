"""Budgeted curriculum advice, previewed and applied only to the annual draft."""
from copy import deepcopy
from uuid import uuid4
from .annual_workspace import router,context,DraftStore,publication_issues,workspace
from .previews import PreviewStore
from .model import plan_report
previews=PreviewStore(limit=8)

@router.post('/advice')
def advice(body:dict):
    server=context()
    from .assistant_history import AssistantHistory
    text=body.get('message')
    if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Опишите задачу, до 2000 символов.')
    log=AssistantHistory(server.store)
    thread_id,turn_id=log.start(None,server.school_today(),'Учебный план: '+text)
    try:
        result=proposal(body)
        log.finish(turn_id,response={'reply':result['reply'],'actions':[],'labels':[],'questions':[],'unsupported':[],'model':'Проверка учебного плана'})
        return result
    except Exception:
        log.finish(turn_id,error='Не удалось подготовить предложение. Учебный план не изменён.',status='error')
        raise

def proposal(body:dict):
    server=context();snapshot=server.store.read()
    if server.require_revision(body)!=snapshot['revision']:raise ValueError('Расписание изменилось. Повторите запрос.')
    selected=workspace.get()
    state=DraftStore(server.store).read()['state'] if selected=='draft' else snapshot['state']
    text=str(body.get('message','')).strip()
    if not text or len(text)>2000:raise ValueError('Опишите задачу, до 2000 символов.')
    report=plan_report(state)
    import json
    compact={'catalogs':{k:[{'id':r['id'],'name':r['name']} for r in state[k] if not r.get('archived')] for k in ('classes','teachers','subjects')},
        'plan':[{k:p[k] for k in ('id','classIds','teacherIds','subjectId','hours')} for p in state['plan']],
        'problems':[r['message'] for r in publication_issues(state)][:35],
        'missing':[{k:r.get(k) for k in ('id','delta')} for r in report['missing']]}
    schema={'type':'object','properties':{'reply':{'type':'string'},'changes':{'type':'array','maxItems':30,'items':{'type':'object','properties':{'planId':{'type':'string'},'hours':{'type':'integer','minimum':0,'maximum':40}},'required':['planId','hours'],'additionalProperties':False}}},'required':['reply','changes'],'additionalProperties':False}
    from .assistant_api import connection
    raw,model=connection().interpret([{'role':'system','content':'Ты помогаешь завучу редактировать постоянный учебный план. Объясни проблемы и предложи изменения ЧАСОВ только по явной просьбе пользователя. Не выдумывай нормы, учителей или классы. Если нужна только проверка, changes пустой. Для уточнения ответь вопросом без changes. Изменения сначала попадут в черновик, расстановка отдельно. Ответ JSON reply, changes [{planId,hours}]. Контекст: '+json.dumps(compact,ensure_ascii=False,separators=(',',':'))},{'role':'user','content':text}],response_schema=schema,max_output_tokens=1400)
    reply=raw.get('reply');changes=raw.get('changes')
    if not isinstance(reply,str) or not isinstance(changes,list) or len(changes)>30:raise ValueError('Ответ помощника не прошёл проверку.')
    known={p['id']:p for p in state['plan']};seen=set();diff=[]
    for item in changes:
        ident=item.get('planId');hours=item.get('hours')
        if ident not in known or ident in seen or type(hours) is not int or not 0<=hours<=40:raise ValueError('Предложение помощника не прошло проверку учебного плана.')
        seen.add(ident)
        if known[ident]['hours']!=hours:diff.append({'planId':ident,'before':known[ident]['hours'],'hours':hours})
    token=uuid4().hex
    previews[token]={'revision':snapshot['revision'],'changes':diff,'workspace':selected}
    return {'reply':reply,'changes':diff,'previewId':token,'revision':snapshot['revision']}

@router.post('/advice/apply')
def apply(body:dict):
    server=context();preview=previews.get(body.get('previewId'))
    revision=server.require_revision(body)
    if not preview or preview['revision']!=revision:raise ValueError('Предложение устарело. Запросите проверку снова.')
    if preview['workspace']!='draft':raise ValueError('Откройте редактор базовой недели и повторите просьбу.')
    if workspace.get()!='draft':raise ValueError('Вернитесь в редактор базовой недели для применения предложения.')
    def change(state):
        for row in preview['changes']:
            plan=next(p for p in state['plan'] if p['id']==row['planId'])
            from .model import plan_is_paired
            if plan_is_paired(plan,{s['id']:s for s in state['subjects']}) and row['hours']%2:
                raise ValueError('Для парных занятий укажите чётное число часов.')
            plan['hours']=row['hours']
    return DraftStore(server.store).mutate(revision,'Предложение AI по учебному плану',change)
