"""Evidence for an explicitly requested joint lesson, independently verifiable."""
from copy import deepcopy
from datetime import date


def identity(lesson):
    return (lesson.get('subjectId'),frozenset(lesson.get('classIds',[])),
            frozenset(lesson.get('teacherIds',[])),lesson.get('groupIndex'))


def originals(state):
    known={}
    for rows in [state.get('baseLessons',[]),*state.get('dayBases',{}).values(),*state.get('days',{}).values()]:
        for lesson in rows:
            if not lesson.get('joint'):known[lesson['id']]=lesson
    return known


def problems(state,lesson,day=None):
    meta=lesson.get('joint')
    if not isinstance(meta,dict):return ['Не удалось прочитать совместный урок.']
    try:
        when=meta['date'];weekday=date.fromisoformat(when).weekday()
        sources=meta['sources'];teacher=meta['teacherId'];period=meta['period']
        assert weekday<5 and (day is None or str(day)==when)
        assert type(period) is int and period==lesson['period'] and 1<=period<=8
        assert isinstance(sources,list) and len(sources)==2
        assert all(isinstance(s,dict) and not s.get('joint') and 'groupIndex' not in s
                   and len(s['classIds'])==len(s['teacherIds'])==1 and s['day']==weekday for s in sources)
        assert len({s['id'] for s in sources})==2
        assert not set(sources[0]['classIds']).intersection(sources[1]['classIds'])
        assert all(s['subjectId']==lesson['subjectId'] for s in sources)
        assert set(lesson['classIds'])=={c for s in sources for c in s['classIds']}
        assert lesson['teacherIds']==[teacher] and len(lesson['roomIds'])==1
        host=next(s for s in sources if s['id']==lesson['id'])
        assert host['teacherIds']==[teacher]
        known=originals(state)
        assert all(s['id'] in known and identity(s)==identity(known[s['id']]) for s in sources)
        assert lesson['day']==weekday
    except (AssertionError,ValueError,TypeError,KeyError,StopIteration):
        return ['Совместный урок должен сохранить предмет и занятия двух классов у одного из их преподавателей.']
    from .model import must_be_first
    subject=next((s for s in state['subjects'] if s['id']==lesson['subjectId']),{})
    if must_be_first(subject) and (weekday!=0 or period!=1):
        return ['«Разговоры о важном», включая совместные, разрешены только первым уроком понедельника.']
    return []


def create(sources,teacher,period,day,room=None):
    host=next(s for s in sources if s['teacherIds']==[teacher])
    lesson=deepcopy(host)
    lesson.update(classIds=list(dict.fromkeys(c for s in sources for c in s['classIds'])),
                  teacherIds=[teacher],period=period,locked=False,
                  roomIds=[room] if room else host['roomIds'][:1])
    lesson['joint']={'date':day,'teacherId':teacher,'period':period,'sources':deepcopy(sources)}
    if room:lesson['joint']['roomId']=room
    return lesson


def source_ids(lesson):
    return [s['id'] for s in lesson.get('joint',{}).get('sources',[])]
