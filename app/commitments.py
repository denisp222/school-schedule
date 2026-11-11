"""Teacher and room occupancy outside the main secondary-school timetable.

Entries represent primary classes or individual sessions without creating
secondary-school lessons, pupil profiles or weekly load assignments. A label
such as ``2а`` or ``Индивидуальные занятия 1`` is enough; pupil names are not
required. Importing detailed teaching plans can be added on top of this layer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from uuid import uuid4

FIELD = 'externalActivities'
KINDS = {'primary': 'Начальные классы', 'individual': 'Индивидуальные занятия'}
_FIELDS = {'id', 'kind', 'label', 'teacherId', 'weekday', 'first', 'last',
           'roomId', 'start', 'end'}


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


def _ranges_overlap(first, second):
    start = max(_bound(first.get('start')) or date.min,
                _bound(second.get('start')) or date.min)
    end = min(_bound(first.get('end')) or date.max,
              _bound(second.get('end')) or date.max)
    return _has_weekday(start, end, first['weekday'])


def validate(state):
    """Validate external entries and reject overlaps between external entries.

    Existing main-schedule collisions are intentionally reported separately by
    ``conflicts``: entering a real primary-school commitment must not silently
    discard it simply because the secondary timetable needs to be repaired.
    """
    rows = state.get(FIELD, [])
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('Не удалось прочитать дополнительную занятость учителей.')
    teachers = {row['id'] for row in state.get('teachers', [])}
    rooms = {row['id'] for row in state.get('rooms', [])}
    maximum = min(7, len(state.get('school', {}).get('bells', [])) or 7)
    seen = set()
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
    for n, row in enumerate(rows):
        for other in rows[:n]:
            if (row['weekday'] != other['weekday']
                    or row['last'] < other['first'] or other['last'] < row['first']):
                continue
            same_teacher = row['teacherId'] == other['teacherId']
            same_room = bool(row.get('roomId') and row.get('roomId') == other.get('roomId'))
            if (same_teacher or same_room) and _ranges_overlap(row, other):
                resource = 'преподавателя' if same_teacher else 'кабинета'
                raise ValueError(f'Дополнительная занятость {resource} пересекается: «{other["label"]}» и «{row["label"]}».')
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


def matching(state, day, period=None):
    """Return occupied entries for an actual date or an annual weekday.

    An integer weekday is the recurring annual pattern. Temporary date-bounded
    entries do not permanently block that annual pattern; they do block the
    corresponding actual dates during daily repairs and manual edits.
    """
    weekday, actual = _when(day)
    result = []
    for row in state.get(FIELD, []):
        if row['weekday'] != weekday:
            continue
        if period is not None and not row['first'] <= period <= row['last']:
            continue
        first = _bound(row.get('start'));last = _bound(row.get('end'))
        if actual is None:
            if first or last:
                continue
        elif first and actual < first or last and actual > last:
            continue
        result.append(row)
    return result


def teacher_busy(state, teacher_id, day, period):
    return any(row['teacherId'] == teacher_id for row in matching(state, day, period))


def room_busy(state, room_id, day, period):
    return bool(room_id) and any(row.get('roomId') == room_id for row in matching(state, day, period))


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
