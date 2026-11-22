"""Named, reversible schedules for one date, stored with the school project."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from .model import base_for_day, lessons_for_day, parse_date, StateError
from .search_policy import canonical_actions

_FIELDS=('lessons','base','conditions','absences','notices')


def validate(state):
    archive=state.get('dayVariants',{})
    if not isinstance(archive,dict):
        raise StateError('Не удалось прочитать сохранённые варианты дня.')
    for key, rows in archive.items():
        try:
            day=date.fromisoformat(key)
            if day.weekday()>=5 or day.isoformat()!=key or not isinstance(rows,list):
                raise ValueError()
            ids=set()
            for row in rows:
                if (not isinstance(row['title'],str) or not 1<=len(row['title'])<=100
                        or not isinstance(row['id'],str) or len(row['id'])!=32 or row['id'] in ids):
                    raise ValueError()
                ids.add(row['id'])
                datetime.fromisoformat(row['created'])
                if any(not isinstance(row[k],list) for k in _FIELDS):raise ValueError()
                if any(not isinstance(r,dict) or not isinstance(r.get('type'),str) for r in row['conditions']):
                    raise ValueError()
                if any(not isinstance(text,str) or len(text)>1000 for text in row['notices']):
                    raise ValueError()
                if row.get('extras') is not None and (not isinstance(row['extras'],list) or
                        any(not isinstance(entry,dict) for entry in row['extras'])):
                    raise ValueError()
                for lesson in row['lessons']+row['base']:
                    if (not isinstance(lesson['id'],str) or lesson['day']!=day.weekday()
                            or type(lesson['period']) is not int or not 1<=lesson['period']<=8
                            or any(not isinstance(lesson[k],list) for k in ('classIds','teacherIds','roomIds'))):
                        raise ValueError()
                for absence in row['absences']:
                    if (not isinstance(absence['teacherId'],str) or type(absence['first']) is not int
                            or type(absence['last']) is not int or not 1<=absence['first']<=absence['last']<=8
                            or not isinstance(absence.get('reason',''),str)):
                        raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError):
            raise StateError('Не удалось прочитать сохранённые варианты дня.') from None


def capture(state,day):
    from .day_preferences import gap_details
    entries={(a['teacherId'],a.get('first',1),a.get('last',8),a.get('reason',''))
             for a in state['absences'] if a['start']<=day<=a['end']}
    lessons=sorted(lessons_for_day(state,day),key=lambda l:l['id'])
    conditions=list(state.get('assistantConditions',{}).get(day,[]))
    if not any(r['type']=='allow_class_gaps' for r in conditions) and gap_details(state,lessons):
        conditions.append({'type':'allow_class_gaps'})
    return {'lessons':lessons,
            'base':sorted(base_for_day(state,day),key=lambda l:l['id']),
            'conditions':canonical_actions(conditions),
            'absences':[{'teacherId':t,'first':first,'last':last,'reason':reason}
                         for t,first,last,reason in sorted(entries)],
            'notices':list(state.get('dayNotices',{}).get(day,[])),
            'extras':deepcopy(state.get('externalDays',{}).get(day))}


def _same(variant,payload):
    return all(variant[k]==payload[k] for k in _FIELDS) and variant.get('extras')==payload.get('extras')


def save(state,day,payload,title,*,rename=True):
    title=' '.join(title.split()) if isinstance(title,str) else ''
    if not 1<=len(title)<=100:
        raise ValueError('Введите название варианта длиной до 100 символов.')
    rows=state.setdefault('dayVariants',{}).setdefault(day,[])
    for variant in rows:
        if _same(variant,payload):
            if rename:variant['title']=title
            return variant
    variant={'id':uuid4().hex,'title':title,'created':datetime.now(timezone.utc).isoformat(),**deepcopy(payload)}
    rows.append(variant)
    return variant


def lookup(state,day,ident):
    for variant in state.get('dayVariants',{}).get(day,[]):
        if variant['id']==ident:return variant
    raise ValueError('Сохранённый вариант этого дня больше не найден.')


def summaries(state,day):
    rows=state.get('dayVariants',{}).get(day,[])
    active=capture(state,day) if rows else {}
    return [{'id':r['id'],'title':r['title'],'created':r['created'],'active':_same(r,active)}
            for r in reversed(rows)]


def use(state,day,variant):
    """Replace events only on this date, including the date slice of absences."""
    chosen=parse_date(day)
    previous=(chosen-timedelta(days=1)).isoformat()
    following=(chosen+timedelta(days=1)).isoformat()
    absences=[]
    for row in state['absences']:
        if not row['start']<=day<=row['end']:
            absences.append(row)
            continue
        if row['start']<day:
            absences.append({**row,'end':previous})
        if row['end']>day:
            absences.append({**row,'start':following,'id':uuid4().hex if row['start']<day else row['id']})
    absences.extend({**row,'id':uuid4().hex,'start':day,'end':day} for row in variant['absences'])
    state['absences']=absences
    state['dayBases'][day]=deepcopy(variant['base'])
    state['days'][day]=deepcopy(variant['lessons'])
    state.setdefault('assistantConditions',{})[day]=deepcopy(variant['conditions'])
    state.setdefault('dayNotices',{})[day]=list(variant['notices'])
    if 'extras' in variant:
        if variant['extras'] is None:state.get('externalDays',{}).pop(day,None)
        else:state.setdefault('externalDays',{})[day]=deepcopy(variant['extras'])
    return state
