"""Separate primary/individual occupancy and explicit technology group data."""
from .rules import is_technology, is_rov, surname_stem, surname_matches
from copy import deepcopy
from datetime import date, timedelta

from fastapi import APIRouter

from . import commitments
from .model import lessons_for_day

router = APIRouter(prefix='/api/extras')


def context():
    from . import server
    return server


def group_rows(state):
    subjects = {s['id']: s for s in state['subjects']}
    teachers = {t['id']: t['name'] for t in state['teachers']}
    plans = {}
    for plan in state['plan']:
        name = subjects.get(plan['subjectId'], {}).get('name', '').lower()
        if len(plan['teacherIds']) != 2 or not (is_technology(name)):
            continue
        for cid in plan['classIds']:
            plans.setdefault(cid, plan)
    result = []
    for cls in state['classes']:
        if cls['id'] not in plans:
            continue
        assigned = plans[cls['id']]['teacherIds']
        result.append({'classId': cls['id'], 'className': cls['name'],
                       'teacherIds': list(assigned), 'teacherNames': [teachers[t] for t in assigned],
                       'groupNames': cls.get('groupNames', ['Подгруппа 1', 'Подгруппа 2']),
                       'groupRoles': cls.get('groupRoles', ['unknown', 'unknown']),
                       'groupSizes': cls.get('groupSizes', [0, 0])})
    return result


def selected_monday(week=None):
    try:
        actual = date.fromisoformat(week or str(context().school_today()))
    except (TypeError, ValueError):
        raise ValueError('Выберите неделю дополнительного расписания.') from None
    return actual-timedelta(days=actual.weekday())


def payload(snapshot, week=None):
    state = snapshot['state'];monday = selected_monday(week)
    problems = []
    for n in range(5):
        day = (monday+timedelta(days=n)).isoformat()
        for issue in commitments.conflicts(state, lessons_for_day(state, day), day):
            problems.append({**issue, 'date': day})
    return {'revision': snapshot['revision'], 'state': state,
            'activities': deepcopy(state.get('externalActivities', [])),
            'groups': group_rows(state), 'conflicts': problems, 'week': monday.isoformat()}


@router.get('')
def get_extras(week: str | None = None):
    return payload(context().store.read(), week)


@router.post('/upsert')
def upsert(body: dict):
    server = context();revision = server.require_revision(body)
    selected_monday(body.get('week'))
    raw = body.get('record')
    if not isinstance(raw, dict):
        raise ValueError('Заполните дополнительное занятие.')
    saved = {}
    def change(state):
        nonlocal saved
        saved = commitments.save(state, raw)
    snapshot = server.store.mutate(revision, 'Дополнительное занятие: '+str(raw.get('label', '')), change)
    return {**payload(snapshot, body.get('week')), 'id': saved['id']}


@router.post('/delete')
def delete(body: dict):
    server = context();revision = server.require_revision(body)
    selected_monday(body.get('week'))
    ident = body.get('id')
    if not isinstance(ident, str) or not ident:
        raise ValueError('Выберите дополнительное занятие.')
    snapshot = server.store.mutate(revision, 'Удалено дополнительное занятие', lambda state: commitments.delete(state, ident))
    return payload(snapshot, body.get('week'))


@router.post('/groups')
def save_groups(body: dict):
    server = context();revision = server.require_revision(body)
    selected_monday(body.get('week'))
    names = body.get('groupNames');roles = body.get('groupRoles');sizes = body.get('groupSizes')
    if not isinstance(names, list) or len(names) != 2 or any(not isinstance(n, str) or not n.strip() or len(n) > 80 for n in names):
        raise ValueError('Укажите короткие названия двух подгрупп.')
    if not isinstance(roles, list) or len(roles) != 2 or any(r not in ('unknown', 'girls', 'boys') for r in roles):
        raise ValueError('Выберите состав каждой подгруппы.')
    if not isinstance(sizes, list) or len(sizes) != 2 or any(type(n) is not int or not 0 <= n <= 200 for n in sizes):
        raise ValueError('Укажите число учеников в подгруппах, 0 если оно пока неизвестно.')
    cid = body.get('classId')
    def change(state):
        if cid not in {row['classId'] for row in group_rows(state)}:
            raise ValueError('Для этого класса не найдены две подгруппы технологии в учебном плане.')
        cls = next(c for c in state['classes'] if c['id'] == cid)
        if cls.get('size', 0) and sum(sizes) > cls['size']:
            raise ValueError('Число учеников в подгруппах больше численности класса.')
        cls.update(groupNames=[n.strip() for n in names], groupRoles=list(roles), groupSizes=list(sizes))
    snapshot = server.store.mutate(revision, 'Уточнены подгруппы технологии', change)
    return payload(snapshot, body.get('week'))
