"""Create a valid partial day from the current timetable, without a solver worker."""
from collections import defaultdict
from copy import deepcopy

from .engine import Grid
from .model import issues, lessons_for_day, student_groups
from .room_policy import assembly_hall, usual_rooms


def reserve(state, day):
    before = lessons_for_day(state, day)
    grid = Grid(state, day, before)
    for lesson in before:grid.remove(lesson['id'])
    teacher_load = defaultdict(int)
    class_load = defaultdict(int)
    home = usual_rooms(state, day)
    for source in sorted(before, key=lambda l: (not l.get('locked', False), not bool(l.get('classHour')), l['period'], l['id'])):
        teachers = source['teacherIds']
        groups = [(c, g) for c in source['classIds'] for g in student_groups(source, c)]
        if any(teacher_load[t] >= grid.index['teachers'][t].get('maxDaily',8) for t in teachers):
            continue
        if any(class_load[c, g] >= grid.index['classes'][c].get('maxDaily',8) for c,g in groups):
            continue
        lesson = source
        if not grid.can_place(lesson, lesson['period']):
            if (len(lesson['roomIds']) != 1 or len(teachers) != 1 or lesson.get('locked')
                    or lesson.get('classHour') or (lesson.get('joint') or lesson.get('technologyJoint') or {}).get('roomId')):
                continue
            rooms = sorted(state['rooms'],key=lambda r: (assembly_hall(r), r['id'] != home.get(teachers[0]), r['id']))
            lesson = next((trial for r in rooms
                           if grid.can_place(trial := {**source,'roomIds':[r['id']],'roomExceptions':[]}, source['period'])), None)
            if lesson is None:
                continue
        grid.insert(deepcopy(lesson))
        for t in teachers:teacher_load[t] += 1
        for key in groups:class_load[key] += 1

    # An unplaceable lesson can also invalidate its paired hour or a parallel
    # lesson marked to run at the same time. Drop the affected block.
    while grid.lessons:
        violations = {ident for problem in issues(state, list(grid.lessons.values()), day)
                      if problem['code']!='gap' and (problem['level']=='error' or problem['code']=='pair_incomplete')
                      for ident in problem['lessonIds'] if ident in grid.lessons}
        if not violations:
            break
        for ident in violations:grid.remove(ident)

    after = sorted(grid.lessons.values(),key=lambda l: (l['period'],l['id']))
    removed = [l for l in before if l['id'] not in grid.lessons]
    return {'status':'ok','date':day,'after':after,'cancelled':removed,'groupLosses':[],
            'otherDays':{},'otherChanges':{},'warnings':[],
            'search':{'deterministic':True,'primaryProven':False},
            'stats':{'lostHours':sum(len(l['teacherIds']) for l in removed)}}
