"""Date-only class hours, explicit class leadership and reversible conversion."""
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import re

SUBJECT_ID='school-class-hour'
SUBJECT={'id':SUBJECT_ID,'name':'Классный час','short':'Кл/ч','teacherCode':'Кл/ч',
         'difficulty':1,'preferredPeriods':[1]}


def _name(value):return re.sub(r'[\s.]+','',str(value or '')).lower().replace('ё','е')


@lru_cache(maxsize=1)
def _factory_leaders():
    # Fill missing legacy assignments from the personalized installer seed.
    # Match actual names, never numeric IDs of an unrelated school project.
    candidates=[Path(__file__).with_name('seed.json')]
    if os.environ.get('SCHEDULE_DATA'):candidates.insert(0,Path(os.environ['SCHEDULE_DATA'])/'factory-seed.json')
    seed=None
    for candidate in candidates:
        try:
            value=json.loads(candidate.read_text(encoding='utf-8'))
            if isinstance(value,dict):seed=value;break
        except (OSError,ValueError):continue
    if seed is None:return {}
    teachers={t['id']:_name(t['name']) for t in seed.get('teachers',[])}
    return {_name(c['name']):teachers[c['homeroomTeacherId']] for c in seed.get('classes',[])
            if c.get('homeroomTeacherId') in teachers}


def leader_map(state):
    from .rules import is_rov
    subjects={s['id']:s for s in state['subjects']}
    teachers={t['id']:t for t in state['teachers']}
    result={}
    for cls in state['classes']:
        if 'homeroomTeacherId' in cls:
            result[cls['id']]=cls['homeroomTeacherId']
            continue
        name=re.sub(r'\s+','',cls['name'].lower().replace('ё','е'))
        assigned=[t['id'] for t in teachers.values() if name in
                  [re.sub(r'\s+','',v) for v in re.findall(r'\d+\s*[а-яa-z]',str(t.get('homeroom') or '').lower().replace('ё','е'))]]
        inferred={l['teacherIds'][0] for l in state['baseLessons'] if cls['id'] in l['classIds']
                  and l['day']==0 and l['period']==1 and len(l['teacherIds'])==1
                  and 'groupIndex' not in l and is_rov(subjects.get(l['subjectId'],{}))}
        result[cls['id']]=assigned[0] if len(assigned)==1 else next(iter(inferred)) if not assigned and len(inferred)==1 else ''
        if not result[cls['id']] and not assigned and not inferred:
            expected=_factory_leaders().get(_name(cls['name']))
            matches=[t['id'] for t in teachers.values() if expected and _name(t['name'])==expected]
            if len(matches)==1:result[cls['id']]=matches[0]
    return result


def fill_leaders(state):
    leaders=leader_map(state)
    for cls in state['classes']:
        if leaders[cls['id']]:cls.setdefault('homeroomTeacherId',leaders[cls['id']])
    for teacher in state['teachers']:
        if 'homeroomRoomId' in teacher:continue
        rooms=leader_room_candidates(state,teacher['id'])
        if len(rooms)==1:teacher['homeroomRoomId']=next(iter(rooms))


def leader_room_candidates(state,teacher_id):
    from .rules import is_rov
    subjects={s['id']:s for s in state['subjects']}
    rooms={r['id'] for r in state['rooms']}
    inferred={r for l in state['baseLessons'] if l['day']==0 and l['period']==1
              and teacher_id in l['teacherIds'] and is_rov(subjects.get(l['subjectId'],{}))
              for r in l['roomIds'] if r in rooms}
    return inferred or {r['id'] for r in state['rooms'] if r.get('teacherId')==teacher_id}


def leader_room(state,teacher_id):
    teacher=next((t for t in state['teachers'] if t['id']==teacher_id),{})
    if 'homeroomRoomId' in teacher:return teacher['homeroomRoomId']
    rooms=leader_room_candidates(state,teacher_id)
    return next(iter(rooms)) if len(rooms)==1 else ''


def required_room(state,lesson):
    meta=lesson.get('classHour')
    return (meta.get('roomId') or leader_room(state,meta['teacherId'])) if meta else ''


def sync_labels(state):
    leaders=leader_map(state)
    for teacher in state['teachers']:
        teacher['homeroom']=', '.join(c['name'] for c in state['classes'] if leaders[c['id']]==teacher['id'])


def assign_from_teacher(state,teacher_id,text):
    fill_leaders(state)
    names={re.sub(r'\s+','',v.lower().replace('ё','е')) for v in re.findall(r'\d+\s*[а-яa-z]',str(text))}
    known={re.sub(r'\s+','',c['name'].lower().replace('ё','е')) for c in state['classes']}
    if names-known:raise ValueError('В классном руководстве указан неизвестный класс.')
    if str(text).strip() and not names:raise ValueError('Укажите классы, например: 5г, 6д.')
    for cls in state['classes']:
        if re.sub(r'\s+','',cls['name'].lower().replace('ё','е')) in names:cls['homeroomTeacherId']=teacher_id
        elif cls.get('homeroomTeacherId')==teacher_id:cls['homeroomTeacherId']=''
    sync_labels(state)


def ensure_subject(state):
    current=next((s for s in state['subjects'] if s['id']==SUBJECT_ID),None)
    if current is None:state['subjects'].append(deepcopy(SUBJECT))
    elif any(current.get(k)!=SUBJECT[k] for k in ('name','short','teacherCode')):
        raise ValueError('Для классного часа зарезервировано название «Классный час» и сокращение «Кл/ч».')


def create(state,day,class_id,lesson_id=None,replace_lesson_id=None,period=None):
    from .model import lessons_for_day,parse_date,paired_subjects
    weekday=parse_date(day).weekday()
    if weekday>4:raise ValueError('Классный час проводится в учебный день.')
    cls=next((c for c in state['classes'] if c['id']==class_id),None)
    if cls is None:raise ValueError('Класс не найден.')
    fill_leaders(state)
    rows=lessons_for_day(state,day)
    source=next((l for l in rows if l['id']==lesson_id),None) if lesson_id else None
    existing=[l for l in rows if l.get('classHour') and class_id in l['classIds']]
    period=period if period is not None else source['period'] if source else existing[0]['period'] if existing else 1
    if type(period) is not int or not 1<=period<=7:raise ValueError('Выберите урок классного часа от 1 до 7.')
    if existing:
        if lesson_id and existing[0]['id']!=lesson_id:raise ValueError('В этот день у класса уже есть классный час.')
        if existing[0]['period']!=period:raise ValueError('Сначала восстановите исходный урок, чтобы изменить время уже назначенного классного часа.')
        errors=problems(state,existing[0],day)
        if errors:raise ValueError(errors[0])
        return deepcopy(existing[0])
    teacher=leader_map(state).get(class_id)
    if not teacher:raise ValueError(cls['name']+': укажите классного руководителя в справочнике классов.')
    first=[l for l in rows if class_id in l['classIds'] and l['period']==period]
    if any(l['classIds']!=[class_id] or l.get('joint') or l.get('technologyJoint') for l in first):
        raise ValueError(cls['name']+': сначала разделите совместное занятие выбранного урока в редакторе.')
    paired=paired_subjects(state)
    preserve=any((class_id,l['subjectId']) in paired for l in first)
    replacement=None
    if replace_lesson_id:
        replacement=next((l for l in rows if l['id']==replace_lesson_id),None)
        if (lesson_id or not replacement or replacement['classIds']!=[class_id]
                or len(replacement['teacherIds'])!=1 or 'groupIndex' in replacement
                or any(replacement.get(k) for k in ('classHour','joint','technologyJoint'))):
            raise ValueError('Выберите обычный урок целого класса, который нужно заменить классным часом.')
        if (class_id,replacement['subjectId']) in paired:
            raise ValueError('Нельзя заменить только половину спаренного занятия классным часом.')
        if replacement.get('locked') and replacement['period']!=period:
            raise ValueError('Сначала снимите закрепление с заменяемого урока.')
    if lesson_id:
        if not source or first!=[source] or source['teacherIds']!=[teacher] or 'groupIndex' in source:
            raise ValueError('Переименовать в «Кл/ч» можно урок целого класса у его классного руководителя.')
        if preserve:raise ValueError('Спаренный урок нельзя заменить наполовину. Назначьте классный час через дополнительные занятия или AI-помощника: пара будет переставлена целиком.')
    replaced=[replacement] if replacement else [] if preserve else first
    ident=replaced[0]['id'] if len(replaced)==1 else f'class-hour-{day}-{class_id}'
    fixed_room=leader_room(state,teacher)
    if not fixed_room:raise ValueError(cls['name']+': укажите кабинет классного руководителя в разделе «Ограничения».')
    room_ids=[fixed_room]
    return {'id':ident,'day':weekday,'period':period,'classIds':[class_id],
            'subjectId':SUBJECT_ID,'teacherIds':[teacher],'roomIds':room_ids,'locked':False,
            'planId':'','note':'','sourceText':'','teacherTexts':{},
            'classHour':{'date':day,'classIds':[class_id],'teacherId':teacher,'sources':deepcopy(replaced),
                         **({'roomId':fixed_room} if fixed_room else {})}}


def apply(state,day,actions):
    from .model import lessons_for_day
    requested=[deepcopy(r) for r in actions if r['type']=='class_hour']
    if not requested:return
    # Revise a previously accepted hour atomically: restore its former source,
    # then consume the newly named lesson. Shared partners retain their hour.
    original=lessons_for_day(state,day)
    for row in requested:
        previous=next((l for l in original if l.get('classHour') and row['classId'] in l['classIds']),None)
        if previous and row.get('period') is None:row['period']=previous['period']
    revisions={l['id']:l for l in original if l.get('classHour') and any(
        r['classId'] in l['classIds'] and r.get('replaceLessonId') and not any(
            s['id']==r['replaceLessonId'] and r['classId'] in s['classIds'] for s in l['classHour']['sources'])
        for r in requested)}
    for old in revisions.values():
        for cid in old['classIds']:
            if not any(r['classId']==cid for r in requested):
                sources=[s for s in old['classHour']['sources'] if cid in s['classIds']]
                requested.append({'type':'class_hour','classId':cid,'lessonId':None,
                    'period':old['period'],'replaceLessonId':sources[0]['id'] if len(sources)==1 and sources[0]['period']!=old['period'] else None})
        state.setdefault('days',{})[day]=restore(state,day,old['id'])
    ensure_subject(state)
    events=list({e['id']:e for e in (create(state,day,r['classId'],r.get('lessonId'),r.get('replaceLessonId'),r.get('period')) for r in requested)}.values())
    original=lessons_for_day(state,day)
    grouped={}
    for event in events:grouped.setdefault((event['teacherIds'][0],event['period']),[]).append(event)
    events=[]
    for (teacher,period),rows in sorted(grouped.items()):
        if len(rows)==1:events.append(rows[0]);continue
        if any(any(old['id']==e['id'] and old.get('classHour') for old in original) for e in rows):
            raise ValueError('У руководителя уже есть отдельный классный час. Сначала восстановите исходный урок и назначьте классный час обоим классам вместе.')
        merged=deepcopy(rows[0]);classes=sorted({c for e in rows for c in e['classIds']})
        merged['id']='class-hour-'+day+'-'+'-'.join(classes);merged['classIds']=classes
        merged['classHour']={'date':day,'classIds':classes[:],'teacherId':teacher,
            'sources':sorted([deepcopy(s) for e in rows for s in e['classHour']['sources']],key=lambda s:s['id']),
            **({'roomId':rows[0]['classHour']['roomId']} if rows[0]['classHour'].get('roomId') else {})}
        size=sum(c.get('size',0) for c in state['classes'] if c['id'] in classes)
        current=next((r for r in state['rooms'] if r['id'] in merged['roomIds']),None)
        if current is None or current.get('capacity') and current['capacity']<size:
            if merged['classHour'].get('roomId'):raise ValueError('Закреплённый кабинет классного руководителя не вмещает объединённые классы.')
            suitable=sorted((r for r in state['rooms'] if not r.get('capacity') or r['capacity']>=size),
                            key=lambda r:(not r.get('capacity'),r['id']))
            if suitable:merged['roomIds']=[suitable[0]['id']]
        events.append(merged)
    consumed={s['id'] for e in events for s in e['classHour']['sources']}
    ids={e['id'] for e in events}
    state['days'][day]=[l for l in lessons_for_day(state,day) if l['id'] not in consumed|ids]+events


def problems(state,lesson,day=None):
    from .model import parse_date,paired_subjects
    meta=lesson.get('classHour')
    if lesson.get('subjectId')!=SUBJECT_ID and not meta:return []
    try:
        assert isinstance(meta,dict) and {'date','classIds','teacherId','sources'}<=set(meta)<={'date','classIds','teacherId','sources','roomId'}
        assert parse_date(meta['date']).weekday()==lesson['day'] and lesson['day']<5
        assert day is None or str(day)==meta['date']
        assert 1<=lesson['period']<=7 and lesson['subjectId']==SUBJECT_ID
        if meta.get('roomId'):
            assert meta['roomId'] in {r['id'] for r in state['rooms']} and lesson['roomIds']==[meta['roomId']]
        assert isinstance(lesson['roomIds'],list) and len(lesson['roomIds'])<=1
        assert lesson['classIds']==meta['classIds'] and lesson['teacherIds']==[meta['teacherId']]
        assert isinstance(meta['classIds'],list) and meta['classIds'] and len(meta['classIds'])==len(set(meta['classIds']))
        assert set(meta['classIds'])<={c['id'] for c in state['classes']}
        assert meta['teacherId'] in {t['id'] for t in state['teachers']}
        assert not any(k in lesson for k in ('groupIndex','splitFrom','joint','technologyJoint','eighthOn'))
        assert isinstance(meta['sources'],list) and len(meta['sources'])<=2*len(meta['classIds'])
        assert len({s['id'] for s in meta['sources']})==len(meta['sources'])
        paired=paired_subjects(state)
        for source in meta['sources']:
            assert len(source['classIds'])==1 and source['classIds'][0] in lesson['classIds'] and source['day']==lesson['day'] and 1<=source['period']<=8
            assert source['subjectId']!=SUBJECT_ID and (source['classIds'][0],source['subjectId']) not in paired
            assert not any(source.get(k) for k in ('classHour','joint','technologyJoint'))
    except (AssertionError,KeyError,TypeError,ValueError):
        return ['Классный час должен проходить на выбранной дате и уроке у своего классного руководителя, в закреплённом кабинете.']
    return []


def cancelled_for_absence(state,lesson,day):
    from .model import is_absent,unavailable,parse_date
    from .commitments import teacher_busy
    if not lesson.get('classHour'):return False
    teacher=next((t for t in state['teachers'] if t['id']==lesson['teacherIds'][0]),None)
    period=lesson['period']
    return bool(teacher and (is_absent(state,teacher['id'],day,period)
                or unavailable(teacher,parse_date(day).weekday(),period) or teacher_busy(state,teacher['id'],day,period)))


def authorized(state,lesson,day,source=None):
    if problems(state,lesson,day):return False
    if source and source.get('classHour')==lesson['classHour']:
        return source['subjectId']==lesson['subjectId'] and source['teacherIds']==lesson['teacherIds'] and source['classIds']==lesson['classIds']
    work=deepcopy(state)
    try:apply(work,day,state.get('assistantConditions',{}).get(day,[]))
    except ValueError:return False
    return any(e['id']==lesson['id'] and e.get('classHour')==lesson['classHour'] for e in work['days'].get(day,[]))


def restore(state,day,lesson_id):
    from .model import lessons_for_day
    rows=lessons_for_day(state,day)
    event=next((l for l in rows if l['id']==lesson_id and l.get('classHour')),None)
    if not event:raise ValueError('Классный час больше не найден. Обновите расписание.')
    sources=deepcopy(event['classHour']['sources'])
    result=[l for l in rows if l['id']!=lesson_id]
    if any(s['id'] in {l['id'] for l in result} for s in sources):raise ValueError('Исходный урок уже есть в расписании.')
    return result+sources
