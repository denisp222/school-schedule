"""Application help, grounded queries and confirmed catalogue changes in one chat."""
from copy import deepcopy
import json,re
from .previews import PreviewStore
from .store import Conflict
from .model import plan_report,week_lessons
previews=PreviewStore(limit=24)
PAGES={'day','week','annual','plan','rules','absences','journal','directory','extras','reports','settings','history','help','students','streams'}
FIELDS={'teachers':{'maxDays','maxDaily','weeklyTarget','homeroomRoomId','homeroom','subjectIds','allowed'},
 'classes':{'homeroomTeacherId','size','maxDaily','firstPeriod','allowed'},
 'rooms':{'capacity','subjectIds','teacherId','classId','allowed'},
 'subjects':{'short','teacherCode','difficulty','allowed'}}
HELP=[(r'резерв|копи|восстанов','history','Копии и восстановление','Откройте «История и копии». Полная копия переносит расписание, ограничения, диалоги и шаблоны. Для переноса подключения помощника задайте пароль копии.'),
 (r'импорт|хронограф|chngf','history','Импорт Хронографа','В «История и копии» нажмите «Импорт Хронографа». Можно выбрать новый .chngf: для его чтения используется установленная старая программа во временной копии. Либо загрузите четыре штатных HTML-отчёта. Сначала проверяются результаты, загрузка требует подтверждения.'),
 (r'экспорт|отч[её]т|word|печат','day','Открыть расписание дня','Откройте нужную дату в расписании дня и нажмите «Отчёт». Выберите получателя и вариант с выделением изменений или без него.'),
 (r'обнов|верси','settings','Открыть настройки','В настройках можно посмотреть номер версии, список изменений и проверить обновления. Установка начинается после подтверждения.'),
 (r'базов|черновик|постоян|составить|учебн.{0,10}план','annual','Редактор базовой недели','Черновик позволяет подготовить новую постоянную неделю, не меняя рабочие даты. Откройте «Базовое расписание» и начните редактирование. В общей таблице двойной щелчок меняет урок, мышью можно переставлять занятия. Учебный план задаёт часы. После проверки введите новую неделю с даты.'),
 (r'огранич|доступ|рабоч.{0,5}дн','rules','Открыть ограничения','В «Ограничениях» задаются разрешённые дни и уроки учителей, классов, кабинетов и предметов. Можно описать конкретное изменение здесь, помощник подготовит его для подтверждения.'),
 (r'отсутств|забол|замен','absences','Открыть отсутствия','Отметьте отсутствие на дату или опишите его в этом диалоге. Затем просмотрите варианты в расписании дня и сохраните подходящий.'),
 (r'ученик|егэ|экзам','students','Ученики и экзамены','В разделе «Ученики и экзамены» ведутся списки классов и выбранные предметы, доступны ведомость и выгрузка.'),
 (r'поток|идентич|групп','streams','Поточные занятия','В «Поточных занятиях» можно связать классы в общую строку плана и задать одинаковое время занятий отдельных строк. Расчёт проверяет общих учителей и кабинеты.'),
 (r'начал|индивидуальн','extras','Дополнительные занятия','Началка и индивидуальные занятия учитываются отдельно. Их учителя и кабинеты блокируются в основном расписании.')]

def link(page,label):return {'page':page,'label':label,'action':''}

def handle(body,snapshot):
    from . import assistant_api as api
    text=body.get('message','');lower=text.lower().replace('ё','е') if isinstance(text,str) else ''
    if not lower:return None
    if len(text)>4000:raise ValueError('Сократите сообщение до 4000 символов.')
    app_terms=bool(re.search(r'программ|черновик|кнопк|панел|раздел|справочник|выгруз|импорт|настройк|копи|диалог',lower))
    help_request=bool(re.search(r'^(?:как\b|где\b|что (?:ты |вы )?уме|помоги (?:разобраться|пользоваться)|расскажи)',lower) or app_terms and re.search(r'^(?:зачем|почему|что значит|что такое|для чего|объясни|подскажи|можно ли)\b',lower) or re.fullmatch(r'\s*(?:привет|здравствуй(?:те)?|добрый (?:день|вечер|утро))[!?.\s]*',lower))
    query=bool(app_terms or body.get('programContext') or re.search(r'нагрузк|норм[аы]|классн.{0,5}руковод|настройк|ограничен|покажи|найди|открой|кабинет закреп|доступност|недоступ|может приходить|рабоч.{0,6}(?:дн|ден)|сокращени.{0,10}предмет|ученик|экзамен|\bегэ\b|\bогэ\b|поточн|синхрон|импорт|chngf',lower))
    if not help_request and not query:return None
    # Explicit daily commands stay with the existing, validated day planner.
    if not help_request and not re.search(r'покажи|найди|открой',lower) and re.search(r'не будет|отсутств|забол|перестав|сдвин|отмени.{0,15}урок|первым уроком',lower):return None
    permanent=bool(re.search(r'постоян|кажд|график|по (?:понедельник|вторник|сред|четверг|пятниц)|в неделю|разреш[её]нн',lower))
    if not help_request and not permanent and re.search(r'кабинет',lower) and re.search(r'недоступ|закрыт|закрой',lower):return None
    history=body.get('history',[])
    if not isinstance(history,list) or len(history)>20 or any(not isinstance(r,dict) or r.get('role') not in ('user','assistant') or not isinstance(r.get('content'),str) or len(r['content'])>6000 for r in history):raise ValueError('Начните новый диалог.')
    state=snapshot['state'];day=body['date'];reply=None;links=[];changes=[]
    if help_request:
        for pattern,page,label,answer in HELP:
            if re.search(pattern,lower):reply=answer;links=[link(page,label)];break
        if not reply:
            reply='Я помогу найти нужную функцию, проверить нагрузку и ограничения, показать расписание преподавателя, подготовить изменение доступности или классного руководства. Также подбираю ежедневные перестановки. Напишите задачу обычными словами.'
            links=[link('help','Как пользоваться'),link('rules','Ограничения'),link('annual','Базовое расписание')]
    if reply is None and re.search(r'нагрузк|норм[аы]',lower) and not re.search(r'измен|постав|установ|сдела|уменьш|увелич',lower):
        from .ai_planner import mentioned_entities
        ids=mentioned_entities(state,text)['teachers'];report=plan_report(state)
        rows=[r for r in report['teachers'] if not ids or r['id'] in ids]
        actual={t['id']:sum(t['id'] in l['teacherIds'] for l in week_lessons(state,day)) for t in state['teachers']}
        from .commitments import week_hours
        extra=week_hours(state,day)
        reply='Нагрузка на выбранную неделю:\n'+'\n'.join(f"{r['name']}: в плане основных занятий {r['plan']} ч, в выбранной неделе {actual[r['id']]} основных, {extra['individual'][r['id']]} индивидуальных и {extra['primary'][r['id']]} в начальных классах; всего {actual[r['id']]+extra['individual'][r['id']]+extra['primary'][r['id']]} ч"+(f", норма основных занятий {r['target']} ч." if r['target'] is not None else '.') for r in rows)
        links=[link('reports','Открыть нагрузку'),link('plan','Учебный план')]
    if reply is None and re.search(r'ученик|экзамен|\bегэ\b|\bогэ\b',lower) and not re.search(r'добав|измен|удал|исправ',lower):
        from .ai_planner import mentioned_entities
        from collections import Counter
        ids=mentioned_entities(state,text);students=[s for s in state['students'] if not ids['classes'] or s['classId'] in ids['classes']]
        counts=Counter(sid for s in students for sid in s.get('examSubjects',[]) if not ids['subjects'] or sid in ids['subjects'])
        names={s['id']:s['name'] for s in state['subjects']}
        reply=f'В выбранном списке учеников: {len(students)}.'+ ('\nВыбор экзаменов:\n'+'\n'.join(f'{names[s]}: {count}' for s,count in sorted(counts.items())) if counts else '\nВыбор экзаменов пока не указан.')
        links=[link('students','Ученики и экзаменационная ведомость')]
    if reply is None and re.match(r'открой\b',lower):
        for pattern,page,label,answer in HELP:
            if re.search(pattern,lower):reply=answer;links=[link(page,label)];break
    if reply is None and re.search(r'покажи|найди|открой',lower) and not re.search(r'огранич|доступ|руковод|рабочи|предметы',lower):
        from .ai_planner import mentioned_entities
        refs=mentioned_entities(state,text)
        found=[(kind,r) for kind in ('teachers','classes','rooms') for r in state[kind] if r['id'] in refs[kind]]
        if found:
            reply='Найдено: '+', '.join(r['name'] for kind,r in found)+'. Откройте нужное расписание.'
            links=[{'page':'day' if kind=='rooms' else 'week','label':r['name'],'action':'','entityKind':kind,'entityId':r['id'],'name':r['name']} for kind,r in found]
    if reply is None:
        catalogs={k:[{f:r[f] for f in ('id','name','maxDays','maxDaily','weeklyTarget','homeroomRoomId','homeroomTeacherId','unavailable','subjectIds') if f in r} for r in state[k] if not r.get('archived')] for k in FIELDS}
        summary={'school':{k:state['school'].get(k) for k in ('name','year','bells')},'catalogs':catalogs,
                 'load':[{k:r[k] for k in ('id','plan','base','target')} for r in plan_report(state)['teachers']]}
        schema={'type':'object','properties':{'scope':{'type':'string','enum':['app','day']},'reply':{'type':'string'},'page':{'type':'string','enum':['',*sorted(PAGES)]},'changes':{'type':'array','maxItems':8,'items':{'type':'object','properties':{'kind':{'type':'string','enum':list(FIELDS)},'id':{'type':'string'},'field':{'type':'string'},'valueJSON':{'type':'string'}},'required':['kind','id','field','valueJSON'],'additionalProperties':False}}},'required':['scope','reply','page','changes'],'additionalProperties':False}
        guide='Ты помощник завуча ПО ПРИЛОЖЕНИЮ, отвечаешь по-русски. Помогаешь пользоваться программой, искать записи, понимать данные и менять настройки справочников. Не меняй данные без явной просьбы. Изменения только предлагаются с подтверждением. Используй только существующие ID. Поля: '+json.dumps({k:sorted(v) for k,v in FIELDS.items()})+'. allowed это ПОЛНЫЙ список разрешённых слотов [[день0..4,урок1..8]], не добавочные слоты. valueJSON содержит JSON значения. homeroomRoomId кабинет руководителя, homeroomTeacherId руководитель класса. Пустые changes для вопросов или уточнения. Не придумывай факты. Не отправляй пользователя в учебный план при вопросе про управление программой. Страницы: '+', '.join(sorted(PAGES))+'. JSON reply,page,changes. Данные: '+json.dumps(summary,ensure_ascii=False,separators=(',',':'))
        guide+=' Если просьба про конкретный день, перенос/отмену/объединение уроков, классный час или разовое закрытие кабинета, верни scope="day", пустые changes и page. Эти просьбы обрабатывает планировщик дня. scope="app" только для помощи по программе и постоянных справочников. Не превращай разовое ограничение в постоянный недельный график.'
        raw,model=api.connection().interpret([{'role':'system','content':guide},*history[-4:],{'role':'user','content':text}],response_schema=schema,max_output_tokens=1800)
        if raw.get('scope')=='day':return None
        reply=raw.get('reply');changes=raw.get('changes');page=raw.get('page')
        if not isinstance(reply,str) or not isinstance(changes,list) or len(changes)>8 or not isinstance(page,str) or page not in PAGES|{''}:raise ValueError('Ответ помощника не прошёл проверку.')
        if page:links=[link(page,'Открыть раздел')]
    labels=[];checked=[]
    for change in changes:
        if not isinstance(change,dict):raise ValueError('Ответ помощника не прошёл проверку.')
        kind=change.get('kind');ident=change.get('id');field=change.get('field')
        if not isinstance(kind,str) or kind not in FIELDS or not isinstance(field,str) or field not in FIELDS[kind]:raise ValueError('Помощник предложил неизвестное действие.')
        record=next((r for r in state[kind] if r['id']==ident),None)
        if record is None:raise ValueError('Запись не найдена. Уточните фамилию или название.')
        try:value=json.loads(change['valueJSON'])
        except (TypeError,ValueError,KeyError):raise ValueError('Не удалось проверить предложенное значение.') from None
        validate_value(state,kind,field,value)
        checked.append({'kind':kind,'id':ident,'field':field,'value':value})
        label=field_label(field)
        if field=='allowed':shown='; '.join(f"{['Пн','Вт','Ср','Чт','Пт'][d]}, урок {p}" for d,p in value) or 'нет разрешённых часов'
        elif field in ('homeroomTeacherId','teacherId','homeroomRoomId','classId'):
            cat='teachers' if field in ('homeroomTeacherId','teacherId') else 'classes' if field=='classId' else 'rooms'
            shown=next((r['name'] for r in state[cat] if r['id']==value),'Не указан')
        elif field=='subjectIds':
            names={r['id']:r['name'] for r in state['subjects']};shown=', '.join(names[x] for x in value) or 'Не указаны'
        else:shown=str(value)
        labels.append(f"{record['name']}: {label} → {shown}")
    if checked:
        proposed=deepcopy(state);apply_changes(proposed,checked)
        from .model import validate_state
        validate_state(proposed)
    log=api.history();thread,turn=log.start(body.get('threadId'),day,text)
    program={'links':links,'labels':labels,'previewId':None}
    result={'date':day,'reply':reply,'actions':[],'questions':[],'unsupported':[],'labels':[],
            'draftId':None,'model':'Помощник по программе','revision':snapshot['revision'],'threadId':thread,'turnId':turn,'program':program}
    if checked:
        token=__import__('uuid').uuid4().hex;program['previewId']=token
        previews[token]={'revision':snapshot['revision'],'changes':checked,'turn':turn,'response':deepcopy(result)}
    log.finish(turn,response=result)
    return result

def field_label(field):return {'maxDays':'рабочих дней','maxDaily':'уроков в день','weeklyTarget':'норма часов','allowed':'разрешённые часы','homeroomRoomId':'кабинет руководителя','homeroomTeacherId':'классный руководитель','homeroom':'классное руководство','teacherId':'закреплённый учитель','classId':'закреплённый класс','subjectIds':'предметы','difficulty':'трудность предмета','size':'численность','firstPeriod':'первый разрешённый урок','capacity':'вместимость','short':'сокращение предмета','teacherCode':'код предмета'}.get(field,'значение')

def validate_value(state,kind,field,value):
    bounds={'maxDays':(1,5),'maxDaily':(1,8),'weeklyTarget':(0,60),'size':(0,100),'firstPeriod':(1,7),'capacity':(0,300),'difficulty':(1,12)}
    if field in bounds:
        low,high=bounds[field]
        if type(value) is not int or not low<=value<=high:raise ValueError('Проверьте предложенное число: '+field_label(field))
    elif field=='allowed':
        if not isinstance(value,list) or len(value)>40 or any(not isinstance(x,list) or len(x)!=2 or any(type(n) is not int for n in x) or not 0<=x[0]<5 or not 1<=x[1]<=8 for x in value):raise ValueError('Неверные разрешённые часы.')
    elif field=='subjectIds':
        if not isinstance(value,list) or len(value)>100 or any(not isinstance(x,str) or x not in {s['id'] for s in state['subjects']} for x in value):raise ValueError('Предмет не найден.')
    elif field in ('homeroomTeacherId','teacherId','homeroomRoomId','classId'):
        cat='teachers' if field in ('homeroomTeacherId','teacherId') else 'classes' if field=='classId' else 'rooms'
        if not isinstance(value,str) or value and value not in {r['id'] for r in state[cat]}:raise ValueError('Связанная запись не найдена.')
    elif not isinstance(value,str) or len(value)>120:raise ValueError('Слишком длинное значение.')

def apply_changes(state,changes):
    from .class_hours import sync_labels,assign_from_teacher
    for c in changes:
        validate_value(state,c['kind'],c['field'],c['value'])
        row=next(r for r in state[c['kind']] if r['id']==c['id'])
        if c['field']=='allowed':
            slots={tuple(x) for x in c['value']};row['unavailable']=[{'day':d,'period':p} for d in range(5) for p in range(1,9) if (d,p) not in slots]
        else:row[c['field']]=deepcopy(c['value'])
        if c['kind']=='teachers' and c['field']=='homeroom':assign_from_teacher(state,c['id'],c['value'])
    sync_labels(state)

def commit(body):
    from . import assistant_api as api
    server=api.context();revision=server.require_revision(body);p=previews.get(body.get('previewId'))
    if not p or p['revision']!=revision:raise Conflict('Предложение устарело. Повторите просьбу.')
    saved=server.store.mutate(revision,'Подтверждены изменения помощника по программе',lambda state:apply_changes(state,p['changes']))
    response=p['response'];response['program']['previewId']=None;response['program']['applied']=True
    api.history().finish(p['turn'],response=response)
    return saved
