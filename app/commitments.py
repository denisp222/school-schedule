"""Teacher and room occupancy outside the main secondary-school timetable.

Primary classes and individual sessions share teacher/room occupancy with the
secondary timetable. Individual learners have their own four-week recurrence;
their explicitly scheduled gaps/eighth lessons never relax class rules.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import uuid4

FIELD = 'externalActivities'
KINDS = {'primary': 'Начальные классы', 'individual': 'Индивидуальные занятия'}
_FIELDS = {'id', 'kind', 'label', 'teacherId', 'weekday', 'first', 'last',
           'roomId', 'start', 'end', 'subjectId', 'learnerId', 'cycleWeeks',
           'allowEighth', 'cancelled', 'roomExceptions'}


def normalize_record(raw):
    """Return a plain record with optional fields filled, without inventing data."""
    if not isinstance(raw, dict):
        raise ValueError('Не удалось прочитать дополнительную занятость учителя.')
    row = deepcopy(raw)
    for field in ('roomId', 'start', 'end'):
        if row.get(field) is None:
            row[field] = ''
    if 'last' not in row and 'first' in row:
        row['last'] = row['first']
    return row


def normalize(state):
    """Add the empty section for old projects; existing records keep their IDs."""
    state.setdefault(FIELD, [])
    state.setdefault('individualLearners', [])
    state.setdefault('externalDays', {})
    if isinstance(state[FIELD], list):
        state[FIELD] = [normalize_record(row) for row in state[FIELD]]
    return state


def _bound(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError('Даты дополнительной занятости указываются в формате ГГГГ-ММ-ДД.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('Проверьте даты дополнительной занятости.') from None
    if parsed.isoformat() != value:
        raise ValueError('Даты дополнительной занятости указываются в формате ГГГГ-ММ-ДД.')
    return parsed


def _has_weekday(first, last, weekday):
    if first > last:
        return False
    distance = (weekday-first.weekday()) % 7
    return (last-first).days >= distance


def _ranges_overlap(first, second, state=None):
    start = max(_bound(first.get('start')) or date.min,
                _bound(second.get('start')) or date.min)
    end = min(_bound(first.get('end')) or date.max,
              _bound(second.get('end')) or date.max)
    if not _has_weekday(start, end, first['weekday']):return False
    if not state or not state.get('school',{}).get('rotation'):return True
    from .rotation import number
    actual=start+timedelta(days=(first['weekday']-start.weekday())%7)
    for n in range(4):
        ordinal=actual.toordinal()+7*n
        if ordinal>end.toordinal():break
        week=number({**state,'baseVersions':[]},date.fromordinal(ordinal))
        if week in first.get('cycleWeeks',[1,2,3,4]) and week in second.get('cycleWeeks',[1,2,3,4]):return True
    return False


def validate(state, *, _rows=None):
    """Validate external entries and reject overlaps between external entries.

    Existing main-schedule collisions are intentionally reported separately by
    ``conflicts``: entering a real primary-school commitment must not silently
    discard it simply because the secondary timetable needs to be repaired.
    """
    rows = state.get(FIELD, []) if _rows is None else _rows
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('Не удалось прочитать дополнительную занятость учителей.')
    teachers = {row['id'] for row in state.get('teachers', [])}
    rooms = {row['id'] for row in state.get('rooms', [])}
    subjects={row['id'] for row in state.get('subjects',[])}
    learners=state.get('individualLearners',[])
    if not isinstance(learners,list) or len(learners)>500:
        raise ValueError('Не удалось прочитать список индивидуальных учеников.')
    learner_ids=set();classes={c['id'] for c in state.get('classes',[])}
    for learner in learners:
        if (not isinstance(learner,dict) or set(learner)-{'id','name','classId','allowGaps','short'}
                or not isinstance(learner.get('id'),str) or not learner['id'] or len(learner['id'])>128
                or learner['id'] in learner_ids or not isinstance(learner.get('name'),str)
                or not learner['name'].strip() or len(learner['name'])>120 or learner.get('classId') not in classes
                or 'allowGaps' in learner and type(learner['allowGaps']) is not bool):
            raise ValueError('Укажите имя или обозначение индивидуального ученика и его класс.')
        if 'short' in learner and (not isinstance(learner['short'],str) or len(learner['short'])>24):
            raise ValueError('Сокращение индивидуального ученика должно быть не длиннее 24 знаков.')
        learner_ids.add(learner['id'])
    seen = set();ranges={}
    for row in rows:
        if not isinstance(row, dict) or set(row)-_FIELDS:
            raise ValueError('В дополнительной занятости есть неизвестные поля.')
        ident = row.get('id')
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 128 or ident in seen:
            raise ValueError('У каждой записи занятости должен быть свой идентификатор.')
        seen.add(ident)
        if not isinstance(row.get('kind'), str) or row['kind'] not in KINDS:
            raise ValueError('Выберите начальные классы или индивидуальные занятия.')
        if not isinstance(row.get('label'), str) or not row['label'].strip() or len(row['label']) > 120:
            raise ValueError('Укажите класс или короткое название индивидуальных занятий.')
        if not isinstance(row.get('teacherId'), str) or row['teacherId'] not in teachers:
            raise ValueError('Преподаватель дополнительной занятости не найден.')
        if row.get('roomId') is not None and not isinstance(row.get('roomId'), str):
            raise ValueError('Кабинет дополнительной занятости не найден.')
        if row.get('roomId') and row['roomId'] not in rooms:
            raise ValueError('Кабинет дополнительной занятости не найден.')
        if row.get('roomId'):
            from .room_policy import allowed
            room=next(r for r in state['rooms'] if r['id']==row['roomId'])
            learner=next((l for l in learners if l['id']==row.get('learnerId')),None)
            probe={'teacherIds':[row['teacherId']],'subjectId':row.get('subjectId'),
                   'classIds':[learner['classId']] if learner else [],'learnerId':row.get('learnerId'),
                   'roomExceptions':row.get('roomExceptions',[])}
            if not allowed(state,probe,room):raise ValueError('Кабинет '+room['name']+' не разрешён для этого дополнительного занятия.')
        if row.get('subjectId') and row['subjectId'] not in subjects:
            raise ValueError('Предмет дополнительного занятия не найден.')
        if row.get('learnerId') and (row['learnerId'] not in learner_ids or row['kind']!='individual'):
            raise ValueError('Индивидуальный ученик не найден.')
        if row.get('learnerId') and (not row.get('subjectId') or row.get('first')!=row.get('last')):
            raise ValueError('Для индивидуального урока укажите один предмет и один номер урока.')
        if 'cycleWeeks' in row and (not isinstance(row['cycleWeeks'],list) or not row['cycleWeeks']
                or any(type(w) is not int or not 1<=w<=4 for w in row['cycleWeeks'])
                or len(set(row['cycleWeeks']))!=len(row['cycleWeeks'])):
            raise ValueError('Выберите недели цикла с первой по четвёртую.')
        for flag in ('allowEighth','cancelled'):
            if flag in row and type(row[flag]) is not bool:raise ValueError('Проверьте исключение или отмену занятия.')
        maximum=min(8 if row['kind']=='individual' and row.get('allowEighth') else 7,
                    len(state.get('school',{}).get('bells',[])) or 7)
        if type(row.get('weekday')) is not int or not 0 <= row['weekday'] <= 4:
            raise ValueError('Для дополнительной занятости выберите день с понедельника по пятницу.')
        if (type(row.get('first')) is not int or type(row.get('last')) is not int
                or not 1 <= row['first'] <= row['last'] <= maximum):
            raise ValueError(f'Укажите занятость в пределах уроков 1–{maximum}.')
        first = _bound(row.get('start')) or date.min
        last = _bound(row.get('end')) or date.max
        if first > last:
            raise ValueError('Начало дополнительной занятости позже её окончания.')
        if not _has_weekday(first, last, row['weekday']):
            raise ValueError('В выбранном диапазоне дат нет указанного дня недели.')
        ranges[ident]=(first,last)
    # Compare only records sharing a resource, weekday, period and date range.
    # Date sorting expires old intervals instead of revisiting all earlier rows.
    buckets={}
    for row in sorted(rows,key=lambda r:(ranges[r['id']][0],r['id'])):
        if row.get('cancelled'):continue
        start,end=ranges[row['id']]
        resources=[('преподавателя',row['teacherId'])]
        if row.get('learnerId'):resources.append(('ученика',row['learnerId']))
        if row.get('roomId'):resources.append(('кабинета',row['roomId']))
        for resource,ident in resources:
            for period in range(row['first'],row['last']+1):
                key=(resource,ident,row['weekday'],period)
                active=[other for other in buckets.get(key,[]) if ranges[other['id']][1]>=start]
                for other in active:
                    if _ranges_overlap(row,other,state):
                        raise ValueError(f'Дополнительная занятость {resource} пересекается: «{other["label"]}» и «{row["label"]}».')
                buckets[key]=active+[row]
    if _rows is None:
        overrides=state.get('externalDays',{})
        if not isinstance(overrides,dict) or len(overrides)>1000:raise ValueError('Не удалось прочитать изменения индивидуальных занятий.')
        for key,entries in overrides.items():
            actual=_bound(key)
            if actual is None or actual.weekday()>4:raise ValueError('Выберите рабочую дату индивидуального расписания.')
            if not isinstance(entries,list) or any(not isinstance(r,dict) or r.get('weekday')!=actual.weekday() for r in entries):
                raise ValueError('День индивидуального занятия не совпадает с датой.')
            validate(state,_rows=entries)
    return state


def _when(day):
    if isinstance(day, datetime):
        return day.weekday(), day.date()
    if isinstance(day, date):
        return day.weekday(), day
    if type(day) is int and 0 <= day <= 6:
        return day, None
    if isinstance(day, str):
        actual = _bound(day)
        if actual is not None:
            return actual.weekday(), actual
    raise ValueError('Не удалось определить день дополнительной занятости.')


def matching(state, day, period=None, *, include_cancelled=False):
    """Return occupied entries for an actual date or an annual weekday.

    An integer weekday is the recurring annual pattern. Temporary date-bounded
    entries do not permanently block that annual pattern; they do block the
    corresponding actual dates during daily repairs and manual edits.
    """
    weekday, actual = _when(day)
    result = []
    from .rotation import activity_rows,number,editing_week
    cycle_week=number(state,actual) if actual is not None else editing_week.get()
    actual_key=actual.isoformat() if actual is not None else None
    absences=[r for r in state.get('absences',[]) if actual_key and r['start']<=actual_key<=r['end']]
    for row in activity_rows(state,actual):
        if row['weekday'] != weekday:
            continue
        if period is not None and not row['first'] <= period <= row['last']:
            continue
        first = row.get('start');last = row.get('end')
        if cycle_week not in row.get('cycleWeeks',[1,2,3,4]):continue
        if actual is None:
            if (first or last) and not (state.get('school',{}).get('rotation') and row.get('cycleWeeks')):
                continue
        elif first and actual_key < first or last and actual_key > last:
            continue
        cancelled=bool(row.get('cancelled')) or any(a['teacherId']==row['teacherId'] and a['first']<=row['last'] and row['first']<=a['last'] for a in absences)
        if cancelled and not include_cancelled:continue
        result.append({**row,'cancelled':bool(cancelled)} if include_cancelled else row)
    return result


def occupancy(state,day):
    """Immutable per-search index; never shared across edits or requests."""
    rows=matching(state,day)
    return {'teachers':frozenset((r['teacherId'],p) for r in rows for p in range(r['first'],r['last']+1)),
            'rooms':frozenset((r['roomId'],p) for r in rows if r.get('roomId') for p in range(r['first'],r['last']+1))}


def teacher_busy(state, teacher_id, day, period):
    return any(row['teacherId'] == teacher_id for row in matching(state, day, period))


def room_busy(state, room_id, day, period):
    return bool(room_id) and any(row.get('roomId') == room_id for row in matching(state, day, period))


def changes(state, day, *, previous=None):
    if previous is None:previous={**state,'externalDays':{},'absences':[]}
    before={r['id']:r for r in matching(previous,day,include_cancelled=True)}
    after={r['id']:r for r in matching(state,day,include_cancelled=True)}
    fields=('teacherId','first','last','roomId','subjectId','cancelled')
    result=[]
    for key in sorted(before.keys()|after.keys()):
        old=before.get(key);new=after.get(key)
        if old is None or new is None or any(old.get(k)!=new.get(k) for k in fields):
            result.append({'id':key,'before':old,'after':new})
    return result


def week_hours(state, day):
    from collections import Counter
    from .model import week_dates,parse_date
    hours={'primary':Counter(),'individual':Counter()}
    for actual in week_dates(parse_date(day)):
        for row in matching(state,actual):hours[row['kind']][row['teacherId']]+=row['last']-row['first']+1
    return hours


def conflicts(state, lessons, day=None):
    """Main-schedule collisions, in the same format as model.issues()."""
    teachers = {row['id']: row['name'] for row in state.get('teachers', [])}
    rooms = {row['id']: row['name'] for row in state.get('rooms', [])}
    result = []
    for lesson in lessons:
        for row in matching(state, day if day is not None else lesson['day'], lesson['period']):
            label = KINDS[row['kind']].lower()+' «'+row['label']+'»'
            if row['teacherId'] in lesson['teacherIds']:
                result.append({'level': 'error', 'code': 'external_busy', 'resourceKind': 'teacher',
                               'message': teachers[row['teacherId']]+f': {lesson["period"]}-м уроком запланированы '+label+'.',
                               'lessonIds': [lesson['id']], 'externalActivityId': row['id']})
            if row.get('roomId') and row['roomId'] in lesson.get('roomIds', []):
                result.append({'level': 'error', 'code': 'external_busy', 'resourceKind': 'room',
                               'message': 'Кабинет '+rooms[row['roomId']]+f': {lesson["period"]}-м уроком запланированы '+label+'.',
                               'lessonIds': [lesson['id']], 'externalActivityId': row['id']})
    return result


def save(state, raw):
    """Create/update atomically in memory; caller persists via Store.mutate."""
    row = normalize_record(raw)
    row.setdefault('id', uuid4().hex)
    if isinstance(row.get('label'), str):
        row['label'] = row['label'].strip()
    rows = deepcopy(state.get(FIELD, []))
    old = next((n for n, entry in enumerate(rows) if entry['id'] == row['id']), None)
    if old is None:
        rows.append(row)
    else:
        rows[old] = row
    proposed = {**state, FIELD: rows}
    validate(proposed)
    state[FIELD] = rows
    return row


def delete(state, ident):
    rows = state.get(FIELD, [])
    if not any(row['id'] == ident for row in rows):
        raise ValueError('Запись дополнительной занятости не найдена.')
    state[FIELD] = [row for row in rows if row['id'] != ident]
