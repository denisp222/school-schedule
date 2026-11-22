"""Evidence for an explicitly requested joint lesson, independently verifiable."""
from copy import deepcopy
from datetime import date

def identity(lesson):
    return (lesson.get('subjectId'),frozenset(lesson.get('classIds',[])),
            frozenset(lesson.get('teacherIds',[])),lesson.get('groupIndex'))


def originals(state, day):
    from .model import base_for_day
    rows = base_for_day(state, day) + state['days'].get(day, [])
    return {lesson['id']: lesson for lesson in rows if not lesson.get('joint')}


def sources_for(lessons):
    return {source['id']: source for lesson in lessons
            for source in (lesson['joint']['sources'] if lesson.get('joint') else [lesson])}


def problems(state,lesson,day=None):
    meta=lesson.get('joint')
    invalid = ['Совместный урок должен объединять исходные занятия одного предмета в одном кабинете у одного из их преподавателей.']
    if not isinstance(meta, dict):return invalid
    try:
        when = meta['date']
        weekday = date.fromisoformat(when).weekday()
        sources, teacher, period = meta['sources'], meta['teacherId'], meta['period']
        if weekday != lesson['day'] or weekday >= 5 or (day is not None and str(day) != when):return invalid
        if type(period) is not int or not 1 <= period <= 8 or period != lesson['period']:return invalid
        if not isinstance(sources, list) or len(sources)<2:return invalid
        if any(not s['classIds'] or len(s['teacherIds']) != 1 or s['day'] != weekday
               or s['subjectId'] != lesson['subjectId'] or 'groupIndex' in s
               or any(s.get(key) for key in ('joint', 'technologyJoint', 'classHour', 'splitFrom'))
               for s in sources):return invalid
        if len({s['id'] for s in sources}) != len(sources):return invalid
        classes = [cid for s in sources for cid in s['classIds']]
        if len(classes) != len(set(classes)) or sorted(classes) != sorted(lesson['classIds']):return invalid
        if lesson['teacherIds'] != [teacher] or len(lesson['roomIds']) != 1:return invalid
        if meta.get('roomId') and lesson['roomIds'] != [meta['roomId']]:return invalid
        host = next(s for s in sources if s['id'] == lesson['id'])
        known = originals(state, when)
        if host['teacherIds'] != [teacher] or any(s['id'] not in known or identity(s) != identity(known[s['id']]) for s in sources):
            return invalid
    except (AttributeError, ValueError, TypeError, KeyError, StopIteration):
        return invalid
    from .model import subject_time_allowed
    from .rules import is_technology
    subject = next((s for s in state['subjects'] if s['id'] == lesson['subjectId']), {})
    if is_technology(subject):return ['Для технологии используйте объединение подгрупп.']
    if not subject_time_allowed(subject, lesson, weekday, period, when):
        return ['Для более поздних «Разговоров о важном» укажите номер урока на эту дату.']
    return []


def create(sources,teacher,period,day,room=None):
    host=next(s for s in sources if s['teacherIds']==[teacher])
    lesson=deepcopy(host)
    lesson.update(classIds=list(dict.fromkeys(c for s in sources for c in s['classIds'])),
                  teacherIds=[teacher],period=period,locked=False,
                  roomIds=[room] if room else host['roomIds'][:1])
    if 'roomExceptions' in lesson:
        lesson['roomExceptions']=[r for r in lesson['roomExceptions'] if r in lesson['roomIds']]
    lesson['joint']={'date':day,'teacherId':teacher,'period':period,'sources':deepcopy(sources)}
    if room:lesson['joint']['roomId']=room
    return lesson


def source_ids(lesson):
    return [s['id'] for s in lesson.get('joint',{}).get('sources',[])]
