"""Fast timetable repair.

The single most important rule of this school: a lesson always keeps its own
teacher.  Nobody is ever substituted for another teacher.  If the teacher is
absent, the lesson can only be *moved* to another slot where that same teacher
is free, or it is cancelled.  To avoid windows and holes the engine swaps
lessons between periods (the "пятнашки" the school uses on paper).

Greedy swaps handle simple cases; bounded constraint search handles chains.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta
from time import perf_counter
from hashlib import sha256
import json

from .model import (
    DAYS,
    absence_periods,
    base_for_day,
    check_slots,
    gap_slots,
    indexes,
    issues,
    is_absent,
    iso,
    lesson_key,
    lessons_for_day,
    must_be_first,
    parse_date,
    period_allowed,
    eighth_exception,
    plan_report,
    signature,
    unavailable,
    validate_state,
    week_dates,
    room_student_count,
    diff_lessons,
    slot_feasible,
)
from .previews import PreviewStore
from .search_policy import canonical_state
from .model import changed_assignments
from .commitments import teacher_busy,room_busy
from .technology import groups_for,student_count
from .day_preferences import profiles,score as pupil_score,MOVE_COST,late_count

MAX_SCORE = 10 ** 9
_exact_cache = PreviewStore(limit=40, ttl=600)


def repair_problems(state, result):
    """Independent acceptance check; scores are never a substitute for rules."""
    errors=[]
    if 'after' not in result:return errors
    if any(not period_allowed(state,l,date=result['date']) for l in result['after']):errors.append('Восьмой урок требует явного исключения на эту дату.')
    changed={result['date']:result['after'], **result.get('otherDays',{})}
    allow_gaps=any(r['type']=='allow_class_gaps' for r in state.get('assistantConditions',{}).get(result['date'],[]))
    week={d:lessons_for_day(state,d) for d in week_dates(parse_date(result['date']))}
    original_week=[l for rows in week.values() for l in rows]
    actual_week=[l for d,rows in week.items() for l in changed.get(d,rows)]
    originals={l['id']:l for l in original_week}
    revised_classes={r['classId'] for r in state.get('assistantConditions',{}).get(result['date'],[])
                     if r['type']=='class_hour' and r.get('replaceLessonId')}
    restored_sources={s['id']:s for old in original_week if old.get('classHour') and revised_classes.intersection(old['classIds'])
                      for s in old['classHour']['sources']}
    from .joint_lessons import problems as joint_problems,source_ids
    from .technology import problems as technology_problems,authorized as technology_authorized,source_refs
    group_consumers=defaultdict(set)
    for other in actual_week:
        refs=source_refs(other) if other.get('technologyJoint') else [
            {'lessonId':other.get('splitFrom',other['id']),'groupIndex':g}
            for g in set(g for c in other['classIds'] for g in groups_for(other,c))]
        for ref in refs:group_consumers[ref['lessonId'],ref['groupIndex']].add(other['id'])
    for lesson in actual_week:
        source=originals.get(lesson['id']) or originals.get(lesson.get('splitFrom'))
        if not lesson.get('classHour') and (source is None or source.get('classHour')) and lesson['id'] in restored_sources:
            source=restored_sources[lesson['id']]
        if source and source.get('joint') and not lesson.get('joint'):
            # A new approved pairing can return the former host to its own
            # class; the other source then participates in the new pairing.
            old_sources=source['joint']['sources']
            replacing=any(r['type']=='join_lessons' and set(r['lessonIds']).intersection(source_ids(source))
                          for r in state.get('assistantConditions',{}).get(result['date'],[]))
            restored=next((s for s in old_sources if s['id']==lesson['id']),None)
            if replacing and restored:source=restored
        joint=False
        if lesson.get('classHour'):
            from .class_hours import authorized as class_hour_authorized
            joint=class_hour_authorized(state,lesson,result['date'],source)
            if not joint:errors.append('Классный час не был согласован или не соответствует классному руководству.')
            consumed={s['id'] for s in lesson['classHour']['sources']}-{lesson['id']}
            if any(other['id'] in consumed for other in actual_week):errors.append('Заменённый классным часом урок нельзя оставить одновременно.')
        if lesson.get('technologyJoint'):
            already=source and source.get('technologyJoint')==lesson['technologyJoint']
            joint=not technology_problems(state,lesson) and (already or technology_authorized(state,lesson))
            if not joint:errors.append('Совместное занятие технологии не было согласовано или нарушает исходные группы.')
            consumed={(r['lessonId'],r['groupIndex']) for r in source_refs(lesson)}
            if any(group_consumers[ref]-{lesson['id']} for ref in consumed):
                errors.append('Объединённую группу нельзя одновременно оставить отдельным занятием.')
        if lesson.get('joint'):
            joint=not joint_problems(state,lesson)
            already=source and source.get('joint')==lesson['joint']
            authorized=any(r['type']=='join_lessons' and set(r['lessonIds'])==set(source_ids(lesson))
                           and r['teacherId']==lesson['teacherIds'][0] and r['period']==lesson['period']
                           for r in state.get('assistantConditions',{}).get(result['date'],[]))
            joint=joint and (already or authorized)
            if not joint:errors.append('Объединение классов не было согласовано или нарушает исходные занятия.')
            if any(other['id'] in set(source_ids(lesson))-{lesson['id']} for other in actual_week):
                errors.append('Объединённое занятие нельзя одновременно оставить отдельным уроком.')
        if not joint and (not source or not set(lesson['teacherIds']).issubset(source['teacherIds']) or lesson['subjectId']!=source['subjectId'] or set(lesson['classIds'])!=set(source['classIds'])):
            errors.append('Урок должен сохранить своего учителя, предмет и класс.')
        if lesson.get('eighthOn') and (not source or source.get('eighthOn')!=lesson['eighthOn']):
            if not any(r['type']=='allow_eighth' and r['lessonId']==lesson['id'] for r in state.get('assistantConditions',{}).get(lesson['eighthOn'],[])):
                errors.append('Исключение для восьмого урока не было согласовано.')
        if source and source.get('locked') and (lesson['period'],lesson['day'])!=(source['period'],source['day']):
            errors.append('Закреплённое занятие нельзя переносить.')
    for key, after in changed.items():
        before=lessons_for_day(state,key)
        explicit_cancel={r['lessonId'] for r in state.get('assistantConditions',{}).get(key,[]) if r['type']=='cancel_lesson'}
        from .class_hours import cancelled_for_absence
        if any(l.get('classHour') and l['id'] not in explicit_cancel and not revised_classes.intersection(l['classIds']) and not cancelled_for_absence(state,l,key)
               and not any(a['id']==l['id'] for a in after) for l in before):
            errors.append('Классный час нельзя отменить автоматически.')
        old_errors={(i['code'],tuple(i['lessonIds'])) for i in issues(state,before,key) if i['level']=='error'}
        errors.extend(i['message'] for i in issues(state,after,key) if (i['code']!='gap' or not allow_gaps) and (i['code']=='pair_incomplete' or
                      i['level']=='error' and (i['code'] in ('absence','unavailable','collision','pair_separated','first_period','rov_day','external_busy') or (i['code'],tuple(i['lessonIds'])) not in old_errors)))
        for r in state['classes']:
            for group in (0,1):
                periods=[l['period'] for l in after if r['id'] in l['classIds'] and group in groups_for(l,r['id'])]
                if gap_slots(periods) and not allow_gaps:errors.append(r['name']+': появились окна у группы.')
        for teacher in state['teachers']:
            tid=teacher['id']
            actual=[l for l in actual_week if tid in l['teacherIds'] and not l.get('classHour')]
            original=[l for l in original_week if tid in l['teacherIds'] and not l.get('classHour')]
            cap=teacher.get('weeklyTarget')
            if cap is not None and len(actual)>max(cap,len(original)):errors.append(teacher['name']+': превышена недельная нагрузка.')
            if len({l['day'] for l in actual})>max(teacher.get('maxDays',5),len({l['day'] for l in original})):errors.append(teacher['name']+': превышено число рабочих дней.')
    return list(dict.fromkeys(errors))


def repair_day(state, day, **kwargs):
    kwargs['allow_other_days']=False
    fast_only=kwargs.pop('fast_only',False)
    result=_repair_greedy(state,day,**kwargs)
    if result.get('after') is not None:
        result['stats']['moved']=changed_assignments(result['before'],result['after'])
        result['stats']['studentPreference']=pupil_score(state,result['after'],parse_date(result['date']).weekday(),state.get('assistantConditions',{}).get(result['date'],[]))
        result['stats']['youngerLate']=late_count(state,result['after'],parse_date(result['date']).weekday(),state.get('assistantConditions',{}).get(result['date'],[]))
    problems=repair_problems(state,result)
    if problems and fast_only:
        result['status']='infeasible'
        result['message']='Без новых окон допустимый вариант пока не найден.'
        result['warnings']=problems+result.get('warnings',[])
        return result
    if problems:
        from .repair_constraints import solve_day
        work=deepcopy(state)
        outgoing={c['id'] for c in result.get('changes',[]) if c.get('movedTo')}
        work['days'][iso(day)]=[l for l in result['before'] if l['id'] not in outgoing]
        key=sha256(json.dumps([work,iso(day),kwargs,result['before'],result['after']],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        exact=_exact_cache.get(key)
        if exact is None:
            exact=solve_day(work,iso(day),kwargs.get('variant',0),kwargs.get('teacher_ids') or [],result['before'],result['after'])
            _exact_cache[key]=deepcopy(exact) if exact else False
        if exact:
            exact['otherDays']=result.get('otherDays',{});exact['otherChanges']=result.get('otherChanges',{})
            exact['before']=result['before'];exact['changes']=_diff(result['before'],exact['after'])
            for change in exact['changes']:
                prior=next((c for c in result['changes'] if c['id']==change['id']),{})
                if prior.get('movedTo'):change['movedTo']=prior['movedTo']
            exact['stats']['moved']=changed_assignments(result['before'],exact['after'])
            exact['stats']['seconds']+=result.get('stats',{}).get('seconds',0)
            if not repair_problems(state,exact):
                return exact
        result['status']='infeasible';result['message']='Без новых окон допустимый вариант пока не найден.'
        result['warnings']=problems+result.get('warnings',[])
    return result

VARIANT_TITLES = [
    "Сбалансированный",
    "Сохранить больше уроков",
    "Ранние уроки",
    "Только этот день",
]

VARIANT_WEIGHTS = [
    {"churn": 3, "sequence": 140, "load": 35, "late": 18, "period": 0.03, "swap": 0, "crossday": 400, "day_distance": 20},
    {"churn": 30, "sequence": 80, "load": 20, "late": 12, "period": 0.01, "swap": 2, "crossday": 500, "day_distance": 8},
    {"churn": 4, "sequence": 180, "load": 45, "late": 30, "period": 0.12, "swap": 0, "crossday": 350, "day_distance": 35},
    {"churn": 2, "sequence": 120, "load": 30, "late": 15, "period": 0.0, "swap": -18, "crossday": 450, "day_distance": -5, "day_only": True},
]


def _logic_penalty(grid: "Grid", weights: dict) -> int:
    """Keep the timetable human: no long runs, no overloaded days."""
    state = grid.state
    index = grid.index
    penalty = 0.0
    by_class = defaultdict(list)
    for lesson in grid.lessons.values():
        for cid in lesson.get("classIds", []):
            by_class[(cid, grid.weekday)].append((int(lesson["period"]), lesson["subjectId"]))
        subject = index["subjects"].get(lesson["subjectId"])
        if subject and int(subject.get("difficulty", 5)) >= 9 and int(lesson["period"]) >= 7:
            penalty += weights["late"]
        penalty += int(lesson["period"]) * weights["period"]
    for rows in by_class.values():
        rows.sort()
        run = 1
        for pos in range(1, len(rows)):
            if rows[pos][1] == rows[pos - 1][1] and rows[pos][0] != rows[pos - 1][0]:
                run += 1
            else:
                if run >= 3:
                    penalty += (run - 2) * weights["sequence"]
                run = 1
        if run >= 3:
            penalty += (run - 2) * weights["sequence"]
    return int(penalty)


def is_group_lesson(lesson: dict) -> bool:
    """A class split into parallel groups (boys/girls, technology/informatics).

    In the source these lessons carry one teacher and one room per group.
    """
    teachers = lesson.get("teacherIds") or []
    rooms = lesson.get("roomIds") or []
    return len(teachers) > 1 and len(rooms) == len(teachers)


class Grid:
    """One day of lessons with fast occupancy indexes."""

    def __init__(self, state: dict, day_key: str, lessons: list[dict], *,preferences=None,index=None,absence_slots=None):
        self.state = state
        self.day_key = day_key
        self.weekday = parse_date(day_key).weekday()
        rule=state['school']['eighthPeriodException'] if 'eighthPeriodException' in state['school'] else eighth_exception(state)
        self.periods=min(8 if rule or any(l.get('eighthOn')==day_key for l in lessons) else 7,len(state['school']['bells']))
        self.index = index if index is not None else indexes(state)
        self.absence_slots = absence_slots if absence_slots is not None else {
            (t['id'],p) for t in state['teachers'] for p in range(1,self.periods+1)
            if is_absent(state,t['id'],day_key,p)}
        self.preferences=preferences if preferences is not None else profiles(state,self.weekday,state.get('assistantConditions',{}).get(day_key,[]))
        self.lessons: dict[str, dict] = {}
        self.teacher_at: dict[tuple, str] = {}
        self.class_at: dict[tuple, str] = {}
        self.room_at: dict[tuple, str] = {}
        for lesson in lessons:
            self.insert(lesson)

    def copy(self) -> "Grid":
        return Grid(self.state, self.day_key, [deepcopy(l) for l in self.lessons.values()],preferences=self.preferences,index=self.index,absence_slots=self.absence_slots)

    def insert(self, lesson: dict) -> None:
        self.lessons[lesson["id"]] = lesson
        for t in lesson.get("teacherIds", []):
            self.teacher_at[(t, lesson["period"])] = lesson["id"]
        for c in lesson.get("classIds", []):
            for group in groups_for(lesson,c):self.class_at[(c,group,lesson['period'])]=lesson['id']
        for r in lesson.get("roomIds", []):
            self.room_at[(r, lesson["period"])] = lesson["id"]

    def remove(self, lesson_id: str) -> dict | None:
        lesson = self.lessons.pop(lesson_id, None)
        if not lesson:
            return None
        for t in lesson.get("teacherIds", []):
            self.teacher_at.pop((t, lesson["period"]), None)
        for c in lesson.get("classIds", []):
            for group in groups_for(lesson,c):self.class_at.pop((c,group,lesson['period']),None)
        for r in lesson.get("roomIds", []):
            self.room_at.pop((r, lesson["period"]), None)
        return lesson

    def move(self, lesson_id: str, period: int) -> None:
        lesson = self.remove(lesson_id)
        if not lesson:
            return
        lesson["period"] = int(period)
        self.insert(lesson)

    def can_place(self, lesson: dict, period: int, ignore=()) -> bool:
        period = int(period)
        if not 1 <= period <= self.periods:
            return False
        if not slot_feasible(self.state,lesson,self.weekday,period,date=self.day_key,
                             index=self.index,absence_slots=self.absence_slots):return False
        for cid in lesson.get('classIds',[]):
            for group in groups_for(lesson,cid):
                holder=self.class_at.get((cid,group,period))
                if holder and holder not in ignore and holder!=lesson['id']:return False
        for field,occupied in (('teacherIds',self.teacher_at),('roomIds',self.room_at)):
            for ident in lesson.get(field,[]):
                holder=occupied.get((ident,period))
                if holder and holder not in ignore and holder!=lesson['id']:return False
        return True

    def swap_allowed(self, first: dict, second: dict) -> bool:
        """Pure check: can these two lessons exchange their periods?"""
        if first["id"] == second["id"]:
            return False
        if first["period"] == second["period"]:
            return False
        p1, p2 = first["period"], second["period"]
        first_lesson = self.remove(first["id"])
        second_lesson = self.remove(second["id"])
        if not first_lesson or not second_lesson:
            if first_lesson:
                self.insert(first_lesson)
            if second_lesson:
                self.insert(second_lesson)
            return False
        ok = self.can_place(first_lesson, p2) and self.can_place(second_lesson, p1)
        self.insert(first_lesson)
        self.insert(second_lesson)
        return ok

    def do_swap(self, first: dict, second: dict) -> bool:
        if not self.swap_allowed(first, second):
            return False
        p1, p2 = first["period"], second["period"]
        self.remove(first["id"])
        self.remove(second["id"])
        first["period"], second["period"] = p2, p1
        self.insert(first)
        self.insert(second)
        return True

    def periods_of_teacher(self, teacher_id: str) -> list[int]:
        return [l["period"] for l in self.lessons.values() if teacher_id in l.get("teacherIds", [])]

    def periods_of_class(self, class_id: str) -> list[int]:
        return [l["period"] for l in self.lessons.values() if class_id in l.get("classIds", [])]

    def gaps_teacher(self) -> dict[str, set[int]]:
        out = {}
        for teacher in self.state["teachers"]:
            out[teacher["id"]] = set(gap_slots(self.periods_of_teacher(teacher["id"])))
        return out

    def gaps_class(self) -> dict[tuple, set[int]]:
        out = {}
        for cls in self.state["classes"]:
            for group in (0,1):
                out[cls['id'],group]=set(gap_slots([l['period'] for l in self.lessons.values()
                    if cls['id'] in l['classIds'] and group in groups_for(l,cls['id'])]))
        return out

    def sorted_lessons(self) -> list[dict]:
        return sorted(self.lessons.values(), key=lambda l: (l["period"], l["id"]))


def _allowed_teacher_gaps(state: dict, day_key: str, baseline: dict[str, set[int]],
                          extra_absences: set[str]) -> dict[str, set[int]]:
    """Compatibility argument for the greedy search; teacher gaps are free."""
    return {t['id']:set(range(1,len(state['school']['bells'])+1)) for t in state['teachers']}


def _score(grid: Grid, baseline_t: dict[str, set[int]], baseline_c: dict[str, set[int]],
           allowed_t: dict[str, set[int]], reference: dict[str, int], lost: int = 0,
           weights: dict | None = None) -> int:
    """Continuity and preserved hours first; balance changes with pupil comfort."""
    weights = weights or VARIANT_WEIGHTS[0]
    class_gaps = grid.gaps_class()
    holes=sum(len(v) for v in class_gaps.values())
    churn = sum(1 for lid, lesson in grid.lessons.items()
                if reference.get(lid) is not None and reference[lid] != lesson["period"])
    pupils=pupil_score(grid.state,list(grid.lessons.values()),grid.weekday,prepared=grid.preferences)
    return int(holes*10**24+lost*10**20+churn*10**12+pupils*1000+min(999,_logic_penalty(grid,weights)))


def _check_teacher_gaps(grid: Grid, baseline_t: dict[str, set[int]], allowed_t: dict[str, set[int]]) -> bool:
    return True


def _free_periods_for_class(state: dict, day_key: str, grid: Grid, class_id: str) -> list[int]:
    used = {l["period"] for l in grid.lessons.values() if class_id in l.get("classIds", [])}
    cls = indexes(state)["classes"][class_id]
    return [p for p in range(max(1, cls.get("firstPeriod", 1)), grid.periods + 1)
            if p not in used and not unavailable(cls, grid.weekday, p)]


def _subject_limit(state: dict, class_id: str) -> dict[str, int]:
    limits = {}
    for plan in state["plan"]:
        if class_id in plan["classIds"]:
            key = plan["subjectId"]
            limits[key] = max(limits.get(key, 2), int(plan.get("maxPerDay") or 2))
    return limits


def _target_day_slot(state: dict, lesson: dict, target_key: str, target_grid: Grid) -> tuple[int, int] | None:
    """Find a safe append/fill slot on another day (no new holes, no windows)."""
    weekday = parse_date(target_key).weekday()
    cls = indexes(state)["classes"]
    if not lesson.get("classIds"):
        return None
    class_id = lesson["classIds"][0]
    class_periods = target_grid.periods_of_class(class_id)
    class_gaps = set(gap_slots(class_periods))
    class_last = max(class_periods) if class_periods else 0
    if len([l for l in target_grid.lessons.values() if class_id in l.get("classIds", [])]) >= cls[class_id].get("maxDaily", 8):
        return None
    limits = _subject_limit(state, class_id)
    same_subject = len([l for l in target_grid.lessons.values()
                        if class_id in l.get("classIds", []) and l.get("subjectId") == lesson.get("subjectId")])
    if same_subject >= limits.get(lesson.get("subjectId"), 2):
        return None
    for tid in lesson.get("teacherIds", []):
        teacher = indexes(state)["teachers"][tid]
        if len([l for l in target_grid.lessons.values() if tid in l.get("teacherIds", [])]) >= min(teacher.get("maxDaily", 8), 7):
            return None
    best = None
    for period in range(1, target_grid.periods + 1):
        if not target_grid.can_place(lesson, period):
            continue
        # Only fill an existing class hole or append right after the last lesson.
        if class_periods and period not in class_gaps and period != class_last + 1:
            continue
        if not class_periods and period != 2:
            continue
        score = (0 if period in class_gaps else 1) * 10 + abs(period - 3)
        if best is None or score < best[0]:
            best = (score, period)
    return (best[1], weekday) if best else None


def _repair_greedy(state: dict, day, *, allow_other_days: bool | None = None,
               reason: str = "", teacher_ids: list[str] | None = None,
               optimize: bool = False, variant: int = 0) -> dict:
    """Return a proposed daily schedule.  The state is never modified."""
    started = perf_counter()
    weights = VARIANT_WEIGHTS[int(variant) % len(VARIANT_WEIGHTS)]
    if weights.get("day_only"):
        allow_other_days = False
    day_key = iso(day)
    weekday = parse_date(day_key).weekday()
    if weekday > 4:
        raise ValueError("В школе пятидневка. Выберите понедельник–пятницу.")
    state = canonical_state(state)
    before = lessons_for_day(state, day_key)
    before_snapshot = deepcopy(before)
    if not before:
        return {"status": "needs_data", "message": "В этот день нет занятий.",
                "date": day_key, "changes": [], "cancelled": [], "warnings": []}
    if allow_other_days is None:
        allow_other_days = bool(state["school"].get("allowOtherDayMoves", False))

    index = indexes(state)
    extra_absences = set(teacher_ids or [])
    if any(t not in index['teachers'] for t in extra_absences) or any(
            t not in index['teachers'] for l in before for t in l.get('teacherIds',[])):
        raise ValueError('В расписании не найден выбранный учитель. Обновите справочники и повторите подбор.')
    absent_teachers = {t["id"] for t in state["teachers"]
                       if is_absent(state, t["id"], day_key, 1) or
                       any(is_absent(state, t["id"], day_key, p) for p in range(1, len(state["school"]["bells"]) + 1))}
    absent_teachers |= extra_absences

    def blocked(lesson: dict) -> bool:
        for tid in lesson.get("teacherIds", []):
            if tid in extra_absences:
                return True
            if is_absent(state, tid, day_key, lesson["period"]):
                return True
            if unavailable(index["teachers"][tid], weekday, lesson["period"]):
                return True
            if teacher_busy(state,tid,day_key,lesson['period']):return True
        if any(room_busy(state,r,day_key,lesson['period']) for r in lesson.get('roomIds',[])):return True
        return False

    grid = Grid(state, day_key, before)
    baseline_t = grid.gaps_teacher()
    baseline_c = grid.gaps_class()
    allowed_t = _allowed_teacher_gaps(state, day_key, baseline_t, extra_absences)
    reference = {l["id"]: l["period"] for l in before_snapshot}

    blocked_lessons = [grid.lessons[l["id"]] for l in before_snapshot if blocked(l)]
    warnings: list[str] = []
    cancelled: list[dict] = []
    group_losses: list[dict] = []
    group_splits = 0
    other_grids: dict[str, Grid] = {}
    other_baseline_t: dict[str, dict[str, set[int]]] = {}
    other_allowed_t: dict[str, dict[str, set[int]]] = {}
    other_weekday: dict[str, int] = {}

    for lesson in blocked_lessons:
        if lesson["id"] not in grid.lessons:
            grid.insert(lesson)

    def target_grid(key: str) -> Grid:
        if key not in other_grids:
            other_grids[key] = Grid(state, key, lessons_for_day(state, key))
            other_baseline_t[key] = other_grids[key].gaps_teacher()
            other_allowed_t[key] = _allowed_teacher_gaps(state, key, other_baseline_t[key], extra_absences)
            other_weekday[key] = parse_date(key).weekday()
        return other_grids[key]

    def blocked_key(lesson: dict):
        classes = len(lesson.get("classIds", []))
        teachers = -len(lesson.get("teacherIds", []))
        period = int(lesson["period"])
        if variant == 1:
            return (classes, teachers, -period, lesson["id"])
        if variant == 2:
            return (-period, classes, teachers, lesson["id"])
        if variant == 3:
            return ("/".join(sorted(lesson.get("classIds", []))), period, lesson["id"])
        return (classes, teachers, period, lesson["id"])

    for lesson in sorted(blocked_lessons, key=blocked_key):
        candidates: list[tuple[int, str, dict]] = []
        locked = bool(lesson.get("locked"))
        # 1. Move to a free period on the same day.
        if not locked:
            for period in range(1, grid.periods + 1):
                if period == lesson["period"]:
                    continue
                if not grid.can_place(lesson, period):
                    continue
                trial = grid.copy()
                trial.move(lesson["id"], period)
                candidates.append((_score(trial, baseline_t, baseline_c, allowed_t, reference, weights=weights), "move", {"period": period}))
            # 2. Swap with another lesson, in this class or another one.
            for other in list(grid.lessons.values()):
                if other["id"] == lesson["id"] or other.get("locked"):
                    continue
                if not grid.swap_allowed(lesson, other):
                    continue
                trial = grid.copy()
                trial.do_swap(trial.lessons[lesson["id"]], trial.lessons[other["id"]])
                candidates.append((_score(trial, baseline_t, baseline_c, allowed_t, reference, weights=weights)
                                   + weights["swap"], "swap", {"with": other["id"]}))
            # 3. Move the same teacher's lesson to a safe slot later in the week.
            if allow_other_days:
                for target in week_dates(parse_date(day_key)):
                    if target == day_key:
                        continue
                    if target < day_key:
                        continue
                    tg = target_grid(target)
                    slot = _target_day_slot(state, lesson, target, tg)
                    if not slot:
                        continue
                    trial = tg.copy()
                    moved = deepcopy(lesson)
                    moved["day"] = slot[1]
                    moved["period"] = slot[0]
                    trial.insert(moved)
                    score = _score(trial, other_baseline_t[target], trial.gaps_class(), other_allowed_t[target],
                                   {l["id"]: l["period"] for l in tg.lessons.values()},
                                   weights=weights) + weights["crossday"]
                    offset = week_dates(parse_date(day_key)).index(target) - weekday
                    score += offset * weights["day_distance"]
                    candidates.append((score, "day", {"date": target, "period": slot[0], "weekday": slot[1], "lesson": moved}))
        if candidates:
            score, kind, payload = min(candidates, key=lambda x: (x[0], x[1]))
            if kind == "move":
                grid.move(lesson["id"], payload["period"])
            elif kind == "swap":
                grid.do_swap(grid.lessons[lesson["id"]], grid.lessons[payload["with"]])
            else:
                grid.remove(lesson["id"])
                target_grid(payload["date"]).insert(payload["lesson"])
        else:
            # A technology/informatics lesson can consist of two parallel
            # groups (boys/girls).  If one group's teacher is away, the other
            # group still has its lesson instead of cancelling both.
            present = [pos for pos, tid in enumerate(lesson.get("teacherIds", []))
                       if not is_absent(state, tid, day_key, lesson["period"])
                       and not unavailable(index["teachers"][tid], weekday, lesson["period"])
                       and not teacher_busy(state,tid,day_key,lesson['period'])]
            if (not locked and is_group_lesson(lesson)
                    and 0 < len(present) < len(lesson.get("teacherIds", []))):
                remaining = deepcopy(lesson)
                remaining["teacherIds"] = [lesson["teacherIds"][i] for i in present]
                if len(present) == 1:
                    remaining["groupIndex"] = present[0]
                if len(lesson.get("roomIds", [])) == len(lesson.get("teacherIds", [])):
                    remaining["roomIds"] = [lesson["roomIds"][i] for i in present]
                remaining["note"] = "Совместный урок: вторая группа сохранила занятие"
                grid.remove(lesson["id"])
                grid.insert(remaining)
                for pos, tid in enumerate(lesson.get("teacherIds", [])):
                    if pos in present:
                        continue
                    lost = deepcopy(lesson)
                    lost["id"] = f"{lesson['id']}-group-{tid}"
                    lost["teacherIds"] = [tid]
                    lost["groupIndex"] = pos
                    lost["roomIds"] = [lesson["roomIds"][pos]] if len(lesson.get("roomIds", [])) == len(lesson.get("teacherIds", [])) else []
                    lost["splitFrom"] = lesson["id"]
                    lost["groupRescue"] = True
                    lost["note"] = "Вторая группа перенесена отдельно"
                    group_splits += 1
                    rescued = False
                    class_id = lesson["classIds"][0]
                    cls = index["classes"][class_id]
                    periods = [l['period'] for l in grid.lessons.values() if class_id in l['classIds'] and pos in groups_for(l,class_id)]
                    holes = set(gap_slots(periods))
                    last = max(periods) if periods else 0
                    first=min(periods) if periods else 0
                    best_rescue=None
                    if len([l for l in grid.lessons.values() if class_id in l.get("classIds", [])]) < cls.get("maxDaily", 8):
                        for candidate in range(1, grid.periods + 1):
                            if candidate == lesson["period"]:
                                continue
                            if periods and candidate not in holes and candidate not in (first-1,last+1):
                                continue
                            lost["period"] = candidate
                            if not grid.can_place(lost, candidate):
                                continue
                            if len([l for l in grid.lessons.values() if tid in l.get("teacherIds", [])]) >= min(
                                    index["teachers"][tid].get("maxDaily", 8), 7):
                                continue
                            trial = grid.copy()
                            trial.insert(lost)
                            candidate_score=_score(trial,baseline_t,baseline_c,allowed_t,reference,weights=weights)
                            if candidate_score<_score(grid,baseline_t,baseline_c,allowed_t,reference,lost=1,weights=weights):
                                if best_rescue is None or candidate_score<best_rescue[0]:best_rescue=(candidate_score,deepcopy(lost))
                    if best_rescue:
                        lost=best_rescue[1];grid.insert(lost);rescued=True
                        names=", ".join(index['classes'][c]['name'] for c in lesson['classIds'])
                        warnings.append(f"{names}: группа {index['teachers'][tid]['name']} перенесена на {lost['period']} урок.")
                    if not rescued:
                        lost["period"] = lesson["period"]
                        group_losses.append({
                            "lessonId": lesson["id"],
                            "teacherId": tid,
                            "classIds": list(lesson.get("classIds", [])),
                            "period": lesson["period"],
                            "lesson": lost,
                        })
                names = ", ".join(index["classes"][c]["name"] for c in lesson.get("classIds", []))
                lost_names = ", ".join(index["teachers"][item["teacherId"]]["name"] for item in group_losses
                                       if item["lessonId"] == lesson["id"])
                kept_names = ", ".join(index["teachers"][t]["name"] for t in remaining["teacherIds"])
                if lost_names:
                    warnings.append(f"{names}: группа {lost_names} отменена, группа {kept_names} занимается.")
                continue
            grid.remove(lesson["id"])
            cancelled.append(deepcopy(lesson))
            if locked:
                names = ", ".join(index["classes"][c]["name"] for c in lesson.get("classIds", []))
                warnings.append(f"{names}: закреплённый урок {lesson['period']} отменён — "
                                f"учитель отсутствует, а закреплённые уроки автоматика не двигает.")
            for tid in lesson.get("teacherIds", []):
                if tid not in absent_teachers:
                    warnings.append(f"{index['teachers'][tid]['name']}: урок {lesson['period']} отменён, "
                                    f"но учитель не отмечен отсутствующим.")

    # Compact only student days. Teacher free periods never justify a change.
    if blocked_lessons or optimize:
        for _ in range(8):
            changed = False
            # 1. Fill class holes with the last lesson of that class.
            for cls in state["classes"]:
                cid = cls["id"]
                for group in (0,1):
                    for _inner in range(4):
                        periods = [l['period'] for l in grid.lessons.values()
                                   if cid in l['classIds'] and group in groups_for(l,cid)]
                        holes = gap_slots(periods)
                        if not holes:
                            break
                        hole = holes[0]
                        later = sorted([l for l in grid.lessons.values() if cid in l.get("classIds", [])
                                        and group in groups_for(l,cid) and l["period"] > hole and not l.get("locked")
                                        and not l.get('technologyJoint') and not l.get('joint')], key=lambda l: -l["period"])
                        placed = False
                        for lesson in later:
                            if not grid.can_place(lesson, hole):
                                continue
                            trial = grid.copy()
                            trial.move(lesson["id"], hole)
                            if _score(trial, baseline_t, baseline_c, allowed_t, reference, weights=weights) < _score(grid, baseline_t, baseline_c, allowed_t, reference, weights=weights):
                                grid = trial
                                placed = changed = True
                                break
                        if not placed:
                            break
            if not changed:
                break

    after = grid.sorted_lessons()
    # Never allow a lesson to keep an absent teacher or change its teacher.
    for lesson in after:
        for tid in lesson.get("teacherIds", []):
            if tid in extra_absences or is_absent(state, tid, day_key, lesson["period"]) or teacher_busy(state,tid,day_key,lesson['period']):
                # This should not happen; cancel defensively.
                grid.remove(lesson["id"])
                cancelled.append(deepcopy(lesson))
    after = grid.sorted_lessons()

    teacher_ids_before = {l["id"]: tuple(sorted(l.get("teacherIds", []))) for l in before_snapshot}
    before_by_id = {l["id"]: l for l in before_snapshot}
    for lesson in after:
        before_set = set(teacher_ids_before.get(lesson["id"], ()))
        after_set = set(lesson.get("teacherIds", []))
        if before_set == after_set:
            continue
        original = before_by_id.get(lesson["id"])
        removed = before_set - after_set
        if lesson.get("groupRescue"):
            source = before_by_id.get(lesson.get("splitFrom"))
            if (source and after_set.issubset(set(source.get("teacherIds", [])))
                    and all(is_absent(state, tid, day_key, source["period"])
                            or unavailable(index["teachers"][tid], weekday, source["period"])
                            or teacher_busy(state,tid,day_key,source['period'])
                            for tid in after_set)):
                continue
        if (not original or not is_group_lesson(original) or not after_set.issubset(before_set)
                or any(not is_absent(state, tid, day_key, original["period"])
                       and not unavailable(index["teachers"][tid], weekday, original["period"])
                       and not teacher_busy(state,tid,day_key,original['period'])
                       for tid in removed)):
            raise ValueError('Подбор остановлен: занятие не сохранило своего преподавателя. Текущее расписание не изменено.')

    other_days: dict[str, list[dict]] = {}
    other_changes: dict[str, list[dict]] = {}
    for key, tg in other_grids.items():
        rows = _diff(lessons_for_day(state, key), tg.sorted_lessons())
        if rows:
            other_days[key] = tg.sorted_lessons()
            other_changes[key] = [{"id": c["id"], "before": c["before"], "after": c["after"]} for c in rows]

    changes = _diff(before_snapshot, after)
    # A move to another day also removes the lesson from this day; show it as a move.
    for key, rows in other_changes.items():
        for row in rows:
            if row["after"] and not row["before"]:
                source = next((c for c in changes if c["id"] == row["id"]), None)
                if source:
                    source["movedTo"] = key
    lost_hours = sum(len(l.get("teacherIds", [])) or 1 for l in cancelled) + len(group_losses)
    for cls in state["classes"]:
        holes = gap_slots(grid.periods_of_class(cls["id"]))
        if holes:
            warnings.append(f"{cls['name']}: осталось окно на {', '.join(map(str, holes))} уроке — "
                            f"используйте подбор перестановок.")
    if cancelled:
        names = Counter(t for l in cancelled for t in l.get("teacherIds", []))
        detail = ", ".join(f"{index['teachers'][t]['name']} — {n}" for t, n in names.items())
        warnings.append(f"Отменено занятий: {len(cancelled)}. {detail}.")
    if allow_other_days and not any(k for k in other_days):
        pass

    return {
        "status": "ok" if (changes or cancelled or other_days) else "unchanged",
        "date": day_key,
        "message": ("Изменений нет." if not (changes or cancelled or other_days)
                    else f"Готово за {round((perf_counter() - started) * 1000)} мс."),
        "before": before_snapshot,
        "after": after,
        "cancelled": cancelled,
        "changes": changes,
        "otherDays": other_days,
        "otherChanges": other_changes,
        "warnings": warnings,
        "stats": {
            "seconds": round(perf_counter() - started, 3),
            "moved": sum(1 for c in changes if c["before"] and (c["after"] or c.get("movedTo"))),
            "cancelled": len(cancelled),
            "groupSplits": group_splits,
            "groupLosses": len(group_losses),
            "lostHours": lost_hours,
            "teacherGapsBefore": sum(len(v) for v in baseline_t.values()),
            "teacherGapsAfter": sum(len(v) for v in grid.gaps_teacher().values()),
            "classGapsBefore": sum(len(v) for v in baseline_c.values()),
            "classGapsAfter": sum(len(v) for v in grid.gaps_class().values()),
        },
        "absentTeachers": sorted(absent_teachers),
        "allowOtherDays": bool(allow_other_days),
        "groupLosses": group_losses,
        "variant": int(variant) % len(VARIANT_WEIGHTS),
        "title": VARIANT_TITLES[int(variant) % len(VARIANT_TITLES)],
        "reason": reason,
    }


def _diff(before: list[dict], after: list[dict]) -> list[dict]:
    return diff_lessons(before,after)


def apply_repair(state: dict, result: dict, reason: str = "") -> dict:
    """Apply a repair preview to the state (mutates and returns it)."""
    if result.get("status") not in ("ok", "unchanged"):
        raise ValueError("Нет готового варианта для применения.")
    problems=repair_problems(state,result)
    if problems:raise ValueError('\n'.join(problems[:6]))
    changed_days: dict[str, list[dict]] = {result["date"]: result["after"]}
    changed_days.update(result.get("otherDays") or {})
    if result.get("status") == "unchanged":
        return state
    for key, lessons in changed_days.items():
        if key not in state["dayBases"]:
            state["dayBases"][key] = base_for_day(state, key)
        weekday = parse_date(key).weekday()
        for lesson in lessons:
            lesson["day"] = weekday
        state["days"][key] = sorted(lessons, key=lambda l: (l["period"], l["id"]))
    # Log every changed lesson once.  A cross-day move is one row "было → стало",
    # not a cancellation on one day plus an appearance on another.
    import uuid
    from datetime import datetime, timezone
    created = datetime.now(timezone.utc).isoformat()
    prior_journal=defaultdict(list)
    for row in state['journal']:prior_journal[row.get('lessonId'),row.get('date')].append(row)
    changes = result.get("changes") or []
    target_rows = {}
    for key, rows in (result.get("otherChanges") or {}).items():
        for row in rows:
            if row.get("after"):
                target_rows[row["id"]] = (key, row)

    def log(lesson_id, date_key, before, after, kind, moved_to=""):
        for existing in prior_journal[lesson_id,date_key]:existing['active']=False
        state["journal"].append({
            "id": uuid.uuid4().hex,
            "created": created,
            "date": date_key,
            "lessonId": lesson_id,
            "before": before,
            "after": after,
            "movedTo": moved_to,
            "reason": reason or result.get("reason") or "Автоматическая перестановка",
            "kind": kind,
            "active": True,
            "confirmed": False,
        })

    logged_targets = set()
    for row in changes:
        moved_to = row.get("movedTo") or ""
        if moved_to and row["id"] in target_rows:
            target_key, target_row = target_rows[row["id"]]
            log(row["id"], result["date"], row.get("before"), target_row.get("after"), "move", target_key)
            logged_targets.add((row["id"], target_key))
            continue
        kind='join' if row.get('joinedInto') or (row.get('after') or {}).get('joint') else "cancel" if row.get("after") is None else "move"
        log(row["id"], result["date"], row.get("before"), row.get("after"), kind)

    for ident, (target_key, target_row) in target_rows.items():
        if (ident, target_key) in logged_targets:
            continue
        log(ident, target_key, target_row.get("before"), target_row.get("after"), "move", "")
    for loss in result.get("groupLosses") or []:
        lost = loss.get("lesson")
        if not lost:
            continue
        synthetic = f"{loss['lessonId']}-group-{loss['teacherId']}"
        log(synthetic, result["date"], lost, None, "group_cancel")
    return state


def fill_missing_hours(state: dict, *, apply: bool = False) -> dict:
    """Place planned lessons that are absent from the base week.

    Uses the real plan/base comparison instead of stored plan ids, so duplicate
    subject names cannot produce phantom missing hours.
    """
    from .model import plan_report
    report = plan_report(state)
    missing = [r for r in report["missing"] if r["delta"] > 0]
    if not missing:
        return {"status": "unchanged", "added": [], "unresolved": [], "message": "Все часы уже расставлены."}
    work = deepcopy(state)
    work["absences"] = []  # Dated illness must not alter the annual timetable.
    # Annual placement must not inherit experiments on particular dates.
    work['days']={};work['dayBases']={};work['assistantConditions']={}
    reference=state['school'].get('start')
    try:reference=parse_date(reference) if reference else date.today()
    except (ValueError,TypeError):reference=date.today()
    grid_by_day = {key: Grid(work, key, [l for l in work["baseLessons"] if l["day"] == parse_date(key).weekday()])
                   for key in week_dates(reference)}
    added = []
    unresolved = []
    for row in missing:
        plan = next(p for p in work["plan"] if p["id"] == row["id"])
        if plan['id'] in state['school'].get('acceptedMissingPlanIds',[]):
            unresolved.append({'planId':plan['id'],'classIds':plan['classIds'],'subjectId':plan['subjectId'],'teacherIds':plan['teacherIds'],'accepted':True})
            continue
        for n in range(int(row["delta"])):
            lesson = {
                "id": __import__('uuid').uuid4().hex,
                "day": 0,
                "period": 1,
                "classIds": list(plan["classIds"]),
                "subjectId": plan["subjectId"],
                "teacherIds": list(plan["teacherIds"]),
                "roomIds": list(plan.get("roomIds") or []),
                "locked": False,
                "note": "Добавлено автоматически до нормы плана",
                "sourceText": "",
                "teacherTexts": {},
                "planId": plan["id"],
            }
            placed = False
            for key in sorted(grid_by_day, key=lambda k: (len(grid_by_day[k].lessons), k)):
                g = grid_by_day[key]
                week_rows = [l for grid in grid_by_day.values() for l in grid.lessons.values()]
                if any((t.get('weeklyTarget') is not None and sum(t['id'] in l['teacherIds'] for l in week_rows) >= t['weeklyTarget']) or
                       len({l['day'] for l in week_rows if t['id'] in l['teacherIds']} | {g.weekday}) > t.get('maxDays',5)
                       for t in work['teachers'] if t['id'] in lesson['teacherIds']):
                    continue
                slot = _target_day_slot(work, lesson, key, g)
                if slot:
                    lesson["day"], lesson["period"] = slot[1], slot[0]
                    g.insert(lesson)
                    added.append(lesson)
                    placed = True
                    break
            if not placed:
                unresolved.append({"planId": plan["id"], "classIds": plan["classIds"],
                                   "subjectId": plan["subjectId"], "teacherIds": plan["teacherIds"]})
    if apply:
        work["baseLessons"].extend(added)
        work["absences"] = deepcopy(state["absences"])
        for key in ('days','dayBases','assistantConditions'):work[key]=deepcopy(state.get(key,{}))
        validate_state(work)
        return {"status": "ok", "added": added, "unresolved": unresolved,
                "message": f"Добавлено занятий: {len(added)}.", "state": work}
    return {"status": "ok" if added else "infeasible", "added": added, "unresolved": unresolved,
            "message": (f"Можно добавить занятий: {len(added)}." if added else
                        "Свободных мест без новых окон не найдено.")}



