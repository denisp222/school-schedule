"""Read-only school facts and explanations of verified timetable variants."""
import json
import re
from collections import Counter
from datetime import date

from .ai_service import AssistantError
from .day_request import mentioned_entities
from .model import base_for_day, diff_lessons, indexes, issues, lessons_for_day


_ANALYSIS=re.compile(r'^(?:почему|зачем|объясни\w*|разбер\w*|сравни\w*|чем\s+отлич\w*|какой\s+вариант)')
_RESULT=re.compile(r'вариант|перестанов|перенос|окн[ао]|конфликт|отмен|ограничен|измен')
_READ_DAY=re.compile(r'^(?:что\s+(?:поменялось|изменилось)|кто\s+отсутств\w*|какие\s+(?:окна|уроки|изменения|конфликты)|сколько\s+(?:окон|перестановок|уроков)|(?:покажи|перечисли)\w*\s+(?:мне\s+)?(?:уроки|изменения|расписание|отсутствия))\b')
_EXPLANATION_SCHEMA={'type':'object','properties':{'reply':{'type':'string','maxLength':2400}},
                     'required':['reply'],'additionalProperties':False}


def requested_kind(message):
    if not isinstance(message,str):return None
    text=message.strip().lower().replace('ё','е')
    if re.search(r'\b(?:если|при\s+условии|(?:и|затем|потом)\s+(?:отмени|переставь|сними|перенеси|поставь|объедини))\b',text):
        return None
    if _ANALYSIS.search(text) and _RESULT.search(text):return 'analysis'
    if _READ_DAY.search(text):return 'day'
    return None


def describe_changes(state,changes):
    ix=indexes(state)
    def cell(lesson):
        if lesson is None:return None
        return {'period':lesson['period'],
                'classes':[ix['classes'][c]['name'] for c in lesson['classIds'] if c in ix['classes']],
                'subject':ix['subjects'].get(lesson['subjectId'],{}).get('name',''),
                'teachers':[ix['teachers'][t]['name'] for t in lesson['teacherIds'] if t in ix['teachers']],
                'rooms':[ix['rooms'][r]['name'] for r in lesson['roomIds'] if r in ix['rooms']]}
    return [{'before':cell(r['before']),'after':cell(r['after'])} for r in changes]


def variant_facts(state,result):
    stats=result['stats']
    search=result.get('search') or {}
    changes=result.get('changes') or []
    ix=indexes(state)
    from .display_labels import individual_labels
    aliases=individual_labels(state)
    conditions=[]
    for row in result.get('actions',[]):
        fact={key:row[key] for key in ('type','first','last','period','cancelOtherClasses') if key in row}
        for key,kind in [('teacherId','teachers'),('classId','classes'),('roomId','rooms')]:
            if row.get(key) in ix[kind]:fact[kind]=ix[kind][row[key]]['name']
        if row.get('classIds'):fact['classes']=[ix['classes'][c]['name'] for c in row['classIds'] if c in ix['classes']]
        if row.get('learnerId') in aliases:fact['individual']=aliases[row['learnerId']]
        conditions.append(fact)
    return {'moved':stats.get('moved',0),'cancelled':stats.get('cancelled',0),
            'groupLosses':stats.get('groupLosses',0),'externalCancelled':stats.get('externalCancelled',0),
            'lateYounger':stats.get('youngerLate',0),'pupilGaps':stats.get('classGapDetails',[]),
            'proven':bool(search.get('primaryProven') and search.get('scope')=='all-rooms'),
            'unfulfilled':result.get('unfulfilled',[]),'conditions':conditions,
            'changeCount':len(changes),'changes':describe_changes(state,changes[:45])}


def _preview_events(thread):
    for turn in reversed(thread.get('turns',[])):
        response=turn.get('response') or {}
        for event in reversed(response.get('events',[])):
            if event.get('kind')=='preview' and event.get('variants'):
                return event
    return {}


def _day_facts(state,day,message):
    lessons=lessons_for_day(state,day)
    refs=mentioned_entities(state,message)
    def relevant(lesson):
        if not any(refs.values()):return True
        return any(refs[kind].intersection(lesson[field]) for kind,field in
                   [('classes','classIds'),('teachers','teacherIds'),('rooms','roomIds')]) or lesson['subjectId'] in refs['subjects']
    scoped=[l for l in lessons if relevant(l)]
    changes=[r for r in diff_lessons(base_for_day(state,day),lessons) if relevant(r['after'] or r['before'])]
    names={r['id']:r['name'] for r in state['teachers']}
    absences=[{'teacher':names.get(r['teacherId'],''),'first':r['first'],'last':r['last']}
              for r in state.get('absences',[]) if r['start']<=day<=r['end'] and
              (not refs['teachers'] or r['teacherId'] in refs['teachers'])]
    from .day_preferences import gap_details
    gaps=[g for g in gap_details(state,lessons) if not refs['classes'] or g['classId'] in refs['classes']]
    ids={l['id'] for l in scoped}
    problem_counts=Counter(r['code'] for r in issues(state,lessons,day) if r['level']=='error'
                           and (not any(refs.values()) or ids.intersection(r['lessonIds'])))
    return {'date':day,'lessonCount':len(scoped),'changeCount':len(changes),'absences':absences,
            'pupilGaps':gaps,'problemCounts':dict(problem_counts),
            'changes':describe_changes(state,changes[:30]),
            'lessons':[r['after'] for r in describe_changes(state,[{'before':None,'after':l}
                for l in sorted(scoped,key=lambda l:(l['period'],l['id']))[:40]])] if any(refs.values()) else []}


def _fallback(facts):
    if 'dateMismatch' in facts:return 'Выберите нужную дату над полем запроса, чтобы разобрать её расписание.'
    def variant_line(i,row):
        stats=row.get('stats') or {}
        affected={g['className'] for g in row.get('pupilGaps',stats.get('classGapDetails',[]))}
        return (f"Вариант {i}: перестановок {row.get('moved',stats.get('moved',0))}, "
                f"отмен основных уроков {row.get('cancelled',stats.get('cancelled',0))}, "
                f"классов с окнами {len(affected)}.")
    versions=facts.get('variants')
    if versions:
        lines=[variant_line(i,row) for i,row in enumerate(versions,1)]
        if versions[0].get('proven'):
            lines.append('Для первого варианта подтверждён минимум перестановок при сохранении часов и заданных ограничений.')
        for note in versions[0].get('unfulfilled',[]):lines.append('Требует проверки: '+note)
        if len(versions)==1 and not versions[0].get('proven'):
            lines.append('Расчёт нашёл допустимый вариант. Минимум перестановок пока не подтверждён.')
        return '\n'.join(lines)
    lines=[f"Дата {facts['date']}. Уроков: {facts['lessonCount']}, изменений: {facts['changeCount']}."]
    lines.extend(f"{r['teacher']}: отсутствует на уроках {r['first']}–{r['last']}." for r in facts['absences'])
    lines.extend(f"{r['className']}: окна на уроках {', '.join(map(str,r['periods']))}." for r in facts['pupilGaps'])
    if not facts['pupilGaps']:lines.append('Окон у учеников нет.')
    for row in facts['lessons']:
        lines.append(f"{row['period']}-й урок · {', '.join(row['classes'])} · {row['subject']} · {', '.join(row['teachers'])}.")
    return '\n'.join(lines)


def respond(body,current,selected=None):
    from . import assistant_api as api
    message=body.get('message','')
    kind='analysis' if selected is not None else requested_kind(message)
    if kind is None:return None
    if len(message)>4000:raise ValueError('Сократите сообщение до 4000 символов.')
    state=current['state'];day=body['date']
    log=api.history()
    thread=log.get(body['threadId']) if body.get('threadId') else {}
    if thread and thread['date']!=day:raise ValueError('Диалог относится к другой дате. Начните новый диалог.')
    event=_preview_events(thread) if kind=='analysis' else {}
    requested=re.search(r'(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?![\d.])',message)
    chosen_day=date.fromisoformat(day)
    mismatch=requested and (int(requested[1]),int(requested[2]),int(requested[3] or chosen_day.year))!=(
        chosen_day.day,chosen_day.month,chosen_day.year)
    if mismatch:facts={'date':day,'dateMismatch':True}
    elif selected is not None:
        facts={'date':day,'variants':[variant_facts(state,selected)]}
    elif event:
        facts={'date':day,'variants':[v.get('facts') or v for v in event['variants']],
               'omitted':event.get('omitted',[])}
    else:facts=_day_facts(state,day,message)
    reply=_fallback(facts);model='Проверка расписания'
    thread_id,turn_id=log.start(body.get('threadId'),day,message)
    try:
        assistant=api.connection()
        status=assistant.status()
        if status.get('configured') and not mismatch:
            prompt=('Ты помощник завуча. Объясни по-русски расписание или варианты простыми словами. '
                    'Пользуйся только проверенными фактами в JSON. Если точная причина переноса или лучший вариант неизвестны, '
                    'скажи об этом. Перестановки и отмены считаются отдельно. Не объявляй оптимальность, если proven=false. '
                    'Если спрашивают, что можно попробовать, предложи конкретное условие для предпросмотра или ручную правку, '
                    'не утверждай, что она уже проверена. Никаких команд на сохранение. Ответь JSON с одним полем reply. Факты: ')
            raw,used_model=assistant.interpret(
                [{'role':'system','content':prompt+json.dumps(facts,ensure_ascii=False,separators=(',',':'))},
                 {'role':'user','content':message}],
                response_schema=_EXPLANATION_SCHEMA,max_output_tokens=850)
            if isinstance(raw.get('reply'),str) and 0<len(raw['reply'].strip())<=2400:
                reply=raw['reply'].strip();model=used_model
    except AssistantError:
        pass
    response={'date':day,'reply':reply,'actions':[],'questions':[],'unsupported':[],'labels':[],
              'draftId':None,'model':model,'threadId':thread_id,'turnId':turn_id,'revision':current['revision'],
              'program':{'insight':True,'links':[{'page':'day','label':'Открыть расписание дня','date':day,'action':''}]}}
    log.finish(turn_id,response=response)
    return response
