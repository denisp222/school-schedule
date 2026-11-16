"""Dated rotating weeks. A cycle is tied to Mondays, not to the computer clock."""
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, timedelta

editing_week = ContextVar('schedule_cycle_week', default=1)


def version(state, day):
    rows = state.get('baseVersions', [])
    if not rows:
        return None
    eligible = [v for v in rows if v['start'] <= str(day)]
    return max(eligible, key=lambda v: v['start']) if eligible else min(rows, key=lambda v: v['start'])


def config(state, day=None):
    row = version(state, day) if day is not None else None
    if row is not None:
        if row['start']==max(v['start'] for v in state['baseVersions']):
            return state.get('school',{}).get('rotation')
        # Old editions must not inherit a cycle added in a later edition.
        return row.get('rotation')
    return state.get('school', {}).get('rotation')


def number(state, day):
    cycle = config(state, day)
    if not cycle:
        return 1
    actual = date.fromisoformat(str(day))
    monday = actual - timedelta(days=actual.weekday())
    anchor = date.fromisoformat(cycle['anchor'])
    return ((monday - anchor).days // 7) % cycle['length'] + 1


def week(state, day):
    row = version(state, day)
    source = row if row is not None and row['start']!=max(v['start'] for v in state['baseVersions']) else state
    variants = source.get('rotationWeeks', {})
    return variants.get(str(number(state, day)), source.get('lessons', state['baseLessons']))


def activity_rows(state, day=None):
    if day is not None and str(day) in state.get('externalDays', {}):
        return state['externalDays'][str(day)]
    row = version(state, day) if day is not None else None
    if row is not None and row['start']!=max(v['start'] for v in state['baseVersions']) and 'externalActivities' in row:
        return row['externalActivities']
    return state.get('externalActivities', [])


def project(state, selected=None):
    result = deepcopy(state)
    selected = selected or editing_week.get()
    if result.get('rotationWeeks'):
        result['baseLessons'] = deepcopy(result['rotationWeeks'].get(str(selected), result['baseLessons']))
    return result


def merge(original, work, selected=None):
    result = deepcopy(work)
    if original.get('rotationWeeks'):
        selected = selected or editing_week.get()
        result['rotationWeeks'] = deepcopy(original['rotationWeeks'])
        result['rotationWeeks'][str(selected)] = deepcopy(work['baseLessons'])
        result['baseLessons'] = deepcopy(result['rotationWeeks']['1'])
    return result


def validate(state):
    cycle = state.get('school', {}).get('rotation')
    variants = state.get('rotationWeeks', {})
    if cycle is None:
        if variants:
            raise ValueError('Задайте начало цикла перед добавлением чередующихся недель.')
        return
    if not isinstance(cycle, dict) or set(cycle) != {'anchor', 'length'} or type(cycle.get('length')) is not int or cycle['length'] != 4:
        raise ValueError('Цикл расписания должен содержать четыре недели и дату первой недели.')
    try:
        anchor = date.fromisoformat(cycle['anchor'])
        if anchor.weekday() != 0 or str(anchor) != cycle['anchor']:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Начало первой недели цикла должно быть понедельником.') from None
    if not isinstance(variants, dict) or set(variants) != {'1', '2', '3', '4'}:
        raise ValueError('Сохраните все четыре недели цикла.')
    from .model import validate_state
    for key, lessons in variants.items():
        if not isinstance(lessons, list) or len(lessons) > 10000:
            raise ValueError('Не удалось прочитать неделю цикла.')
        candidate = deepcopy(state)
        candidate.pop('rotationWeeks', None)
        candidate.pop('baseVersions', None)
        candidate.pop('annualDraft', None)
        candidate['school'].pop('rotation', None)
        candidate['baseLessons'] = deepcopy(lessons)
        candidate['days'] = {}; candidate['dayBases'] = {};candidate['assistantConditions'] = {}
        # Recurrence validation is done once against the real cycle below.
        candidate['externalActivities'] = [];candidate['externalDays'] = {}
        validate_state(candidate)


def snapshot(state):
    return {'rotation': deepcopy(state.get('school', {}).get('rotation')),
            'rotationWeeks': deepcopy(state.get('rotationWeeks', {})),
            'externalActivities': deepcopy(state.get('externalActivities', []))}
