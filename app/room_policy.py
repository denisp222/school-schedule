"""Explicit room purpose, including rooms excluded from automatic allocation."""
from collections import Counter, defaultdict


def assembly_hall(room):
    name = room['name'].casefold()
    return 'актов' in name and 'зал' in name


def usual_rooms(state, day):
    from .annual_workspace import effective_week
    rooms = {r['id']: r for r in state['rooms'] if not assembly_hall(r) and r.get('usePolicy', 'general') == 'general'}
    counts = defaultdict(Counter)
    for lesson in effective_week(state, day):
        teachers, assigned = lesson['teacherIds'], lesson['roomIds']
        if len(teachers) == len(assigned):
            for teacher, room in zip(teachers, assigned):
                if room in rooms:
                    counts[teacher][room] += 1
    result = {}
    for teacher in state['teachers']:
        ident = teacher['id']
        declared = [r for r, row in rooms.items() if row.get('teacherId') == ident]
        if len(declared) == 1:
            result[ident] = declared[0]
        elif counts[ident]:
            room, frequency = counts[ident].most_common(1)[0]
            if frequency >= 2 and frequency * 5 >= counts[ident].total() * 4:
                result[ident] = room
        if ident not in result and teacher.get('homeroomRoomId') in rooms:
            result[ident] = teacher['homeroomRoomId']
    return result


def improve_assignments(state, day, before, lessons, protected=()):
    """Use a free ordinary room or recover the teacher's usual room at the solved time."""
    from .model import indexes, parse_date, slot_feasible
    rooms = {r['id']: r for r in state['rooms']}
    home = usual_rooms(state, day)
    original = {l['id']: l for l in before}
    busy = {(l['period'], r) for l in lessons for r in l['roomIds']}
    index = indexes(state)
    weekday = parse_date(day).weekday()
    common_rooms=sorted(rid for rid,room in rooms.items() if not assembly_hall(room))
    for lesson in sorted(lessons, key=lambda l: l['id']):
        if (not lesson['roomIds'] or len(lesson['roomIds']) != len(lesson['teacherIds']) or lesson['id'] in protected
                or lesson.get('locked') or lesson.get('classHour')
                or (lesson.get('joint') or lesson.get('technologyJoint') or {}).get('roomId')):
            continue
        prior = original.get(lesson.get('splitFrom', lesson['id']))
        if not prior or lesson['roomIds'] == prior['roomIds']:
            continue
        for pos,(teacher,room) in enumerate(zip(lesson['teacherIds'],lesson['roomIds'])):
            preferred = home.get(teacher)
            if assembly_hall(rooms[room]):
                choices = sorted(common_rooms,key=lambda r: (r != preferred, r not in prior['roomIds'], r))
            else:
                choices = [preferred] if preferred in prior['roomIds'] and preferred != room else []
            for candidate in choices:
                period = lesson['period']
                if (period, candidate) in busy:
                    continue
                updated = list(lesson['roomIds'])
                updated[pos]=candidate
                changed = {**lesson, 'roomIds': updated}
                if not slot_feasible(state, changed, weekday, period, date=day, index=index):
                    continue
                busy.discard((period, room))
                busy.add((period, candidate))
                lesson['roomIds'] = updated
                if 'roomExceptions' in lesson:
                    lesson['roomExceptions'] = [r for r in lesson['roomExceptions'] if r in updated]
                break

def allowed(state, lesson, room):
    policy=room.get('usePolicy','general')
    if policy=='individual' and not lesson.get('learnerId'):return False
    if policy=='manual':
        classes=set(lesson.get('classIds',[]))
        if (room['id'] not in lesson.get('roomExceptions',[]) or not classes
                or not classes.issubset(set(room.get('manualClassIds',[])))):return False
    if room.get('allowedTeacherIds') and not set(lesson.get('teacherIds',[])).intersection(room['allowedTeacherIds']):return False
    if room.get('allowedTeacherIds') and room['id'] in lesson.get('roomIds',[]) and len(lesson.get('teacherIds',[]))==len(lesson.get('roomIds',[])):
        if lesson['teacherIds'][lesson['roomIds'].index(room['id'])] not in room['allowedTeacherIds']:return False
    if room.get('subgroupsOnly') and not lesson.get('learnerId'):
        split='groupIndex' in lesson or len(lesson.get('teacherIds',[]))>1
        if lesson.get('technologyJoint'):
            split=all(len(groups)==1 for groups in lesson['technologyJoint'].get('classGroups',{}).values())
        if not split:return False
    if policy=='restricted' and room.get('subjectIds') and lesson.get('subjectId') not in room['subjectIds']:return False
    return True


def available_for_general_use(room):
    return room.get('usePolicy','general')=='general' and not room.get('allowedTeacherIds')


def validate(state):
    teachers={t['id'] for t in state['teachers']};classes={c['id'] for c in state['classes']}
    for room in state['rooms']:
        if 'subgroupsOnly' in room and type(room['subgroupsOnly']) is not bool:
            raise ValueError('Проверьте ограничение кабинета для подгрупп.')
        if room.get('usePolicy','general') not in ('general','restricted','manual','individual'):
            raise ValueError('Выберите назначение кабинета.')
        if 'individualPriority' in room and (type(room['individualPriority']) is not int or not 0<=room['individualPriority']<=20):
            raise ValueError('Проверьте приоритет кабинета для индивидуальных занятий.')
        for field,refs in [('allowedTeacherIds',teachers),('manualClassIds',classes)]:
            if field in room and (not isinstance(room[field],list) or any(not isinstance(v,str) or v not in refs for v in room[field]) or len(set(room[field]))!=len(room[field])):
                raise ValueError('Проверьте разрешённых преподавателей и классы кабинета.')
