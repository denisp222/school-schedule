"""School timetable state: normalization, validation and shared helpers.

The application stores plain JSON-compatible dictionaries.  Everything the
engine and the API need is derived here, so the rules stay in one place.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from .rules import is_rov, is_technology, eighth_exception

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
DAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт"]
DAY_GENITIVE = ["понедельник", "вторник", "среду", "четверг", "пятницу"]
DAY_UPPER = [d.upper() for d in DAYS]
KINDS = ("teachers", "classes", "subjects", "rooms", "plan", "absences", "students")

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed.json"
_UNSET_RULE=object()


def is_eighth_exception(state, lesson):
    rule=eighth_exception(state)
    return bool(rule and set(lesson.get('classIds',[]))==set(rule['classIds']) and set(lesson.get('teacherIds',[]))==set(rule['teacherIds']) and lesson.get('subjectId')==rule['subjectId'])


def period_allowed(state,lesson,period=None,day=None,*,date=None,_rule=_UNSET_RULE):
    p=int(lesson['period'] if period is None else period)
    d=int(lesson['day'] if day is None else day)
    rule=eighth_exception(state) if _rule is _UNSET_RULE else _rule
    if rule and set(lesson.get('classIds',[]))==set(rule['classIds']) and set(lesson.get('teacherIds',[]))==set(rule['teacherIds']) and lesson.get('subjectId')==rule['subjectId']:
        return d==rule['day'] and p==8
    if lesson.get('eighthOn'):
        try:
            approved=parse_date(lesson['eighthOn'])
            if approved.weekday()==d and (date is None or str(date)==approved.isoformat()):return 1<=p<=8
        except (ValueError,TypeError):pass
    return 1<=p<=7


# --------------------------------------------------------------------------
# small helpers


def norm_name(value: str) -> str:
    """Normalize a surname for matching: spaces, dots and case are ignored."""
    return re.sub(r"[\s.\u00a0]", "", str(value or "")).lower().replace("ё", "е")


def iso(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_dates(day: date) -> list[str]:
    monday = monday_of(day)
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


def lesson_key(lesson: dict) -> tuple:
    return (
        tuple(sorted(lesson.get("classIds") or [])),
        lesson.get("subjectId", ""),
        tuple(sorted(lesson.get("teacherIds") or [])),
    )


def signature(lesson: dict | None):
    if not lesson:
        return None
    return (
        int(lesson.get("day", 0)),
        int(lesson.get("period", 0)),
        tuple(sorted(lesson.get("classIds") or [])),
        lesson.get("subjectId", ""),
        tuple(sorted(lesson.get("teacherIds") or [])),
        tuple(sorted(lesson.get("roomIds") or [])),
        tuple((c,tuple(student_groups(lesson,c))) for c in sorted(lesson.get('classIds',[]))),
    )


def cell_signature(lessons: list[dict]) -> tuple:
    return tuple(sorted((signature(l) for l in lessons), key=str))


def same_cell(a: list[dict], b: list[dict]) -> bool:
    return cell_signature(a) == cell_signature(b)


def changed_assignments(before,after):
    """Count original lessons whose surviving pupils change time or room."""
    successors={}
    for lesson in after:
        parents={lesson['id'],lesson.get('splitFrom',lesson['id'])}
        parents.update(s['id'] for s in lesson.get('joint',{}).get('sources',[]))
        parents.update(s['lessonId'] for s in lesson.get('technologyJoint',{}).get('sourceRefs',[]))
        parents.update(s['id'] for s in lesson.get('classHour',{}).get('sources',[]))
        for parent in parents:successors.setdefault(parent,[]).append(lesson)
    def rooms(lesson,group):
        if not lesson.get('technologyJoint') and 'groupIndex' not in lesson and len(lesson['roomIds'])==len(lesson['teacherIds'])==2:
            return (lesson['roomIds'][group],)
        return tuple(sorted(lesson['roomIds']))
    changed=set()
    for old in before:
        for new in successors.get(old['id'],[]):
            for cid in set(old['classIds']).intersection(new['classIds']):
                for group in set(student_groups(old,cid)).intersection(student_groups(new,cid)):
                    if old['period']!=new['period'] or rooms(old,group)!=rooms(new,group):changed.add(old['id'])
    return len(changed)


def diff_lessons(before: list[dict], after: list[dict]) -> list[dict]:
    """Return one row per lesson whose assignment changed."""
    first = {l["id"]: l for l in before}
    second = {l["id"]: l for l in after}
    rows = []
    for ident in sorted(set(first) | set(second)):
        old, new = first.get(ident), second.get(ident)
        joined=next((l for l in after if ident in [s['id'] for s in l.get('joint',{}).get('sources',[])]),None) if old and not new else None
        if old and not new and not joined:
            joined=next((l for l in after if ident in [s['id'] for s in l.get('classHour',{}).get('sources',[])]),None)
        if old and not new and not joined:
            # A technology parent can survive as two separate groups or as a
            # shared group plus its untouched neighbour. It was not cancelled
            # merely because the original combined row was expanded.
            successors=[l for l in after if l.get('splitFrom')==ident or any(
                r.get('lessonId')==ident for r in l.get('technologyJoint',{}).get('sourceRefs',[]))]
            if successors:
                joined=next((l for l in successors if l.get('technologyJoint')),successors[0])
        if joined:
            rows.append({'id':ident,'before':old,'after':joined,'joinedInto':joined['id']})
            continue
        if signature(old) != signature(new):
            rows.append({"id": ident, "before": old, "after": new})
    return rows


def must_be_first(subject: dict,lesson=None) -> bool:
    """«Разговоры о важном» всегда стоят первым уроком."""
    return bool(subject.get('firstMonday',is_rov(subject)))


def paired_subjects(state):
    """Class/subject assignments that must run in consecutive two-hour blocks."""
    subjects={s['id']:s for s in state['subjects']}
    return {(c,p['subjectId']) for p in state['plan'] if plan_is_paired(p,subjects)
            for c in p['classIds']}


def plan_is_paired(plan,subjects):
    name=subjects.get(plan['subjectId'],{}).get('name','').lower()
    technology=is_technology(name) and subjects.get(plan['subjectId'],{}).get('pairedTechnology',True)
    hours=int(plan.get('hours') or 0)
    return bool(plan.get('doubleLessons') or technology and hours>=2 and hours%2==0)


def paired_buckets(state,lessons):
    paired=paired_subjects(state);buckets=defaultdict(list)
    for lesson in lessons:
        for cid in lesson['classIds']:
            if (cid,lesson['subjectId']) not in paired:continue
            for group in student_groups(lesson,cid):
                buckets[cid,lesson['subjectId'],lesson['day'],group].append(lesson)
    return buckets


def student_groups(lesson,class_id):
    """A joint technology lesson can cover different groups in each class."""
    mapping=lesson.get('technologyJoint',{}).get('classGroups',{})
    return list(mapping[class_id]) if class_id in mapping else [lesson['groupIndex']] if 'groupIndex' in lesson else [0,1]


def room_student_count(state,lesson,room_id):
    """A parallel two-room lesson puts one subgroup in each room."""
    from .technology import student_count
    rooms=lesson.get('roomIds',[])
    if not lesson.get('technologyJoint') and 'groupIndex' not in lesson and len(rooms)==len(lesson.get('teacherIds',[]))==2 and room_id in rooms:
        lesson={**lesson,'groupIndex':rooms.index(room_id)}
    return student_count(state,lesson)


def gap_slots(periods) -> list[int]:
    periods = sorted(set(int(p) for p in periods))
    if not periods:
        return []
    return [p for p in range(periods[0], periods[-1] + 1) if p not in set(periods)]


def gap_count(periods) -> int:
    return len(gap_slots(periods))


# --------------------------------------------------------------------------
# normalization


def _merge_foreign_language(state: dict) -> None:
    """The source file uses two names for the same subject.

    Plan rows say «Иностранный Язык», the week says «Английский язык».
    Merging them turns 19 false "unplaced" rows into matching ones.
    """
    subjects = state.get("subjects", [])
    english = next((s for s in subjects if "английск" in s["name"].lower()), None)
    foreign = [s for s in subjects if "иностранн" in s["name"].lower()]
    if not english or not foreign:
        return
    rename = {s["id"]: english["id"] for s in foreign if s["id"] != english["id"]}
    if not rename:
        return

    def fix(value):
        return rename.get(value, value)

    for teacher in state.get("teachers", []):
        teacher["subjectIds"] = list(dict.fromkeys(fix(x) for x in teacher.get("subjectIds", [])))
    for room in state.get("rooms", []):
        room["subjectIds"] = list(dict.fromkeys(fix(x) for x in room.get("subjectIds", [])))
    for plan in state.get("plan", []):
        plan["subjectId"] = fix(plan["subjectId"])
    for key in ("baseLessons", "sourceLessons"):
        for lesson in state.get(key, []):
            lesson["subjectId"] = fix(lesson["subjectId"])
    for bucket in ("days", "dayBases"):
        for lessons in state.get(bucket, {}).values():
            for lesson in lessons:
                lesson["subjectId"] = fix(lesson["subjectId"])
    for row in state.get("journal", []):
        for side in ("before", "after"):
            if row.get(side):
                row[side]["subjectId"] = fix(row[side]["subjectId"])
    state["subjects"] = [s for s in subjects if s["id"] not in rename]
    state.setdefault("importNotes", []).append(
        "«Иностранный Язык» и «Английский язык» объединены в один предмет: "
        "в исходном файле это была одна и та же нагрузка."
    )


def _merge_plan_rows(state: dict) -> None:
    """Collapse duplicate plan rows (same class, subject and teachers)."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for plan in state.get("plan", []):
        key = lesson_key(plan)
        if key not in merged:
            merged[key] = {
                **plan,
                "id": plan["id"],
                "classIds": list(plan.get("classIds") or []),
                "teacherIds": list(plan.get("teacherIds") or []),
                "roomIds": list(plan.get("roomIds") or []),
                "hours": int(plan.get("hours") or 0),
                "observed": 0,
                "maxPerDay": int(plan.get("maxPerDay") or 2),
                "doubleLessons": bool(plan.get("doubleLessons")),
                "confirmed": bool(plan.get("confirmed")),
            }
            order.append(key)
        else:
            row = merged[key]
            row["hours"] += int(plan.get("hours") or 0)
            row["roomIds"] = list(dict.fromkeys(row["roomIds"] + list(plan.get("roomIds") or [])))
            row["maxPerDay"] = max(row["maxPerDay"], int(plan.get("maxPerDay") or 2))
            row["doubleLessons"] = row["doubleLessons"] or bool(plan.get("doubleLessons"))
            row["confirmed"] = row["confirmed"] and bool(plan.get("confirmed"))
    state["plan"] = [merged[key] for key in order]


def _relink_plan(state: dict) -> None:
    """Give every lesson the id of its (now unique) plan row and count it."""
    by_key: dict[tuple, dict] = {}
    for plan in state.get("plan", []):
        by_key.setdefault(lesson_key(plan), plan)
    buckets = [state.get("baseLessons", []), state.get("sourceLessons", [])]
    buckets += list(state.get("days", {}).values()) + list(state.get("dayBases", {}).values())
    for lessons in buckets:
        for lesson in lessons:
            plan = by_key.get(lesson_key(lesson))
            lesson["planId"] = plan["id"] if plan else ""
    for plan in state.get("plan", []):
        plan["observed"] = 0
    for lesson in state.get("baseLessons", []):
        plan = by_key.get(lesson_key(lesson))
        if plan:
            plan["observed"] += 1


def normalize_state(raw: dict) -> dict:
    """Return a clean, fully-populated state.  Idempotent."""
    state = deepcopy(raw)
    state["schemaVersion"] = 2
    state.setdefault("school", {})
    school = state["school"]
    school.setdefault("name", "Школа")
    school.setdefault("year", "2026/27")
    school.setdefault("term", "Учебный год")
    school.setdefault("start", "2026-09-01")
    school.setdefault("end", "2027-05-31")
    school.setdefault("principal", "")
    school.setdefault("address", "")
    school.setdefault("phone", "")
    school.setdefault(
        "bells",
        ["08:30–09:10", "09:20–10:00", "10:10–10:50", "11:05–11:45",
         "12:05–12:45", "13:05–13:45", "13:55–14:35", "14:45–15:25"],
    )
    school['noClassGaps']=True
    school['noNewTeacherGaps']=False
    school.setdefault("preferDifficultMorning", True)
    school.setdefault("freeRoomLastPeriod", 6)
    school.setdefault("allowOtherDayMoves", True)
    school.setdefault("firstShift", True)
    for key in ("teachers", "classes", "subjects", "rooms", "plan", "baseLessons"):
        state.setdefault(key, [])
    for key in ("days", "dayBases"):
        state.setdefault(key, {})
    from .commitments import normalize as normalize_commitments
    normalize_commitments(state)
    for key in ("absences", "students", "journal", "importNotes", "loadedDays", "sourceLessons"):
        state.setdefault(key, [])

    _merge_plan_rows(state)
    _relink_plan(state)

    for teacher in state["teachers"]:
        if not 1 <= int(teacher.get('maxDays',5)) <= 5 or not 1 <= int(teacher.get('maxDaily',8)) <= 12:
            raise StateError('Укажите от 1 до 5 рабочих дней и от 1 до 12 уроков в день.')
        teacher.setdefault("subjectIds", [])
        teacher.setdefault("weeklyTarget", None)
        teacher.setdefault("maxDaily", 8)
        teacher.setdefault("maxDays", 5)
        teacher.setdefault("unavailable", [])
        teacher.setdefault("homeroom", "")
        teacher.setdefault("personnelNumber", "")
        teacher.setdefault("department", "")
        teacher.setdefault("category", "")
        teacher.setdefault("note", "")
        teacher.setdefault("extraLimit", 0)
        teacher.setdefault("allowSubstitution", False)
    for item in state["classes"]:
        item.setdefault("size", 0)
        item.setdefault("maxDaily", 8)
        item.setdefault("firstPeriod", 1)
        item.setdefault("unavailable", [])
        item.setdefault("template", False)
        item.setdefault('groupNames',['Подгруппа 1','Подгруппа 2'])
        item.setdefault('groupRoles',['unknown','unknown'])
        item.setdefault('groupSizes',[0,0])
    from .class_hours import fill_leaders
    fill_leaders(state)
    for item in state["subjects"]:
        item.setdefault("short", item.get("name", ""))
        item.setdefault("teacherCode", "")
        item.setdefault("difficulty", 5)
        item.setdefault("preferredPeriods", [])
    for item in state["rooms"]:
        item.setdefault("capacity", 0)
        item.setdefault("floor", "")
        item.setdefault("subjectIds", [])
        item.setdefault("teacherId", "")
        item.setdefault("classId", "")
        item.setdefault("unavailable", [])
    for item in state["plan"]:
        item.setdefault("roomIds", [])
        item.setdefault("maxPerDay", 2)
        item.setdefault("doubleLessons", False)
        if plan_is_paired(item,{s['id']:s for s in state['subjects']}):item['doubleLessons']=True
        item.setdefault("confirmed", True)
    for bucket in (state["baseLessons"], state["sourceLessons"],
                   *state["days"].values(), *state["dayBases"].values()):
        for lesson in bucket:
            lesson.setdefault("teacherIds", [])
            lesson.setdefault("roomIds", [])
            lesson.setdefault("locked", False)
            lesson.setdefault("note", "")
            lesson.setdefault("sourceText", "")
            lesson.setdefault("teacherTexts", {})
            lesson.setdefault("planId", "")
    state["loadedDays"] = sorted({int(l["day"]) for l in state["baseLessons"]})
    rule=eighth_exception(state)
    state['school']['eighthPeriodException']=rule
    if rule:
        state['importNotes']=[note for note in state['importNotes'] if note!='Занятия восьмого урока сняты с сетки. Их часы сохранены в учебном плане и требуют распределения до седьмого урока.']
    state["school"]["period8Classes"] = rule['classIds'] if rule else []
    retired=state.setdefault('unscheduledLessons',[])
    restored=[l for l in retired if period_allowed(state,l) and l['period']==8]
    for lesson in restored:
        if not any(l['id']==lesson['id'] for l in state['baseLessons']):state['baseLessons'].append(deepcopy(lesson))
    retired[:]=[l for l in retired if l not in restored]
    removed=[l for l in state['baseLessons'] if not period_allowed(state,l)]
    for lesson in removed:
        if not any(l['id']==lesson['id'] for l in retired):retired.append(deepcopy(lesson))
    state['baseLessons']=[l for l in state['baseLessons'] if period_allowed(state,l)]
    for day,lessons in state['days'].items():
        for lesson in lessons:
            if period_allowed(state,lesson):continue
            for entry in state['journal']:
                if entry.get('date')==day and entry.get('lessonId')==lesson['id']:entry['active']=False
            state['journal'].append({'id':f"no-eighth-{day}-{lesson['id']}",'date':day,'lessonId':lesson['id'],
                'created':datetime.now(timezone.utc).isoformat(),'before':deepcopy(lesson),'after':None,
                'kind':'cancel','reason':'Восьмой урок запрещён правилами школы','active':True,'confirmed':False,'movedTo':''})
        state['days'][day]=[l for l in lessons if period_allowed(state,l)]
    if removed:
        note='Занятия восьмого урока сняты с сетки. Их часы сохранены в учебном плане и требуют распределения до седьмого урока.'
        if note not in state['importNotes']:state['importNotes'].append(note)
    _relink_plan(state)
    state['loadedDays']=sorted({int(l['day']) for l in state['baseLessons']})
    return state


def initial_state() -> dict:
    source = json.loads((SEED if SEED.exists() else ROOT/'empty_seed.json').read_text(encoding="utf-8"))
    _merge_foreign_language(source)
    return normalize_state(source)


# --------------------------------------------------------------------------
# validation


class StateError(ValueError):
    pass


def _require_refs(state: dict, kind: str, ids, idset: set, where: str):
    if len(set(ids)) != len(ids) or any(i not in idset for i in ids):
        title={'teachers':'учителей','classes':'классов','subjects':'предметов','rooms':'кабинетов'}.get(kind,'данных')
        raise StateError(f"Не удалось найти запись в списке {title}. Обновите расписание и заново выберите данные занятия.")


def validate_state(raw: dict, *, check_collisions: bool = True) -> dict:
    """Validate structure and references.  Returns the same object."""
    state = raw
    from .commitments import validate as validate_commitments
    validate_commitments(state)
    notices=state.get('dayNotices',{})
    if (not isinstance(notices,dict) or len(notices)>1000 or
            any(not isinstance(rows,list) or len(rows)>40 or any(not isinstance(text,str) or len(text)>1000 for text in rows) for rows in notices.values())):
        raise StateError('Не удалось прочитать пояснения к изменениям дня.')
    ids = {}
    for kind in ("teachers", "classes", "subjects", "rooms", "plan", "absences", "students"):
        rows = state.get(kind, [])
        if not isinstance(rows, list):
            raise StateError(f"Раздел «{kind}» должен быть списком.")
        values = [r.get("id") for r in rows]
        if any(not isinstance(v, str) or not v for v in values):
            raise StateError(f"В разделе «{kind}» есть запись без идентификатора.")
        if len(set(values)) != len(values):
            raise StateError(f"Повторяющиеся идентификаторы в разделе «{kind}».")
        ids[kind] = set(values)

    for teacher in state["teachers"]:
        _require_refs(state, "subjects", teacher.get("subjectIds", []), ids["subjects"], teacher.get("name", "?"))
        if not 1 <= int(teacher.get('maxDays',5)) <= 5 or not 1 <= int(teacher.get('maxDaily',8)) <= 12:
            raise StateError('Укажите от 1 до 5 рабочих дней и от 1 до 12 уроков в день.')
    for cls in state['classes']:
        names=cls.get('groupNames',['Подгруппа 1','Подгруппа 2'])
        roles=cls.get('groupRoles',['unknown','unknown'])
        sizes=cls.get('groupSizes',[0,0])
        if not isinstance(names,list) or len(names)!=2 or any(not isinstance(n,str) or not n.strip() or len(n)>80 for n in names):
            raise StateError('Укажите названия двух подгрупп класса.')
        if not isinstance(roles,list) or len(roles)!=2 or any(r not in ('unknown','girls','boys') for r in roles):
            raise StateError('Некорректный состав подгрупп класса.')
        if not isinstance(sizes,list) or len(sizes)!=2 or any(type(n) is not int or not 0<=n<=200 for n in sizes):
            raise StateError('Укажите численность двух подгрупп, 0 если она пока неизвестна.')
        if cls.get('size',0) and sum(sizes)>cls['size']:
            raise StateError('Численность подгрупп больше численности класса.')
    for kind in ('teachers','classes','rooms','subjects'):
        for record in state[kind]:
            for slot in record.get('unavailable',[]):
                values=(slot.get('day'),slot.get('period')) if isinstance(slot,dict) else slot
                if not isinstance(values,(list,tuple)) or len(values)!=2 or not all(type(v) is int for v in values) or not 0<=values[0]<=4 or not 1<=values[1]<=len(state['school']['bells']):
                    raise StateError('Недоступность должна содержать рабочий день и номер урока.')
    for room in state["rooms"]:
        _require_refs(state, "subjects", room.get("subjectIds", []), ids["subjects"], room.get("name", "?"))
        if room.get("teacherId"):
            _require_refs(state, "teachers", [room["teacherId"]], ids["teachers"], room.get("name", "?"))
        if room.get("classId"):
            _require_refs(state, "classes", [room["classId"]], ids["classes"], room.get("name", "?"))
    for teacher in state['teachers']:
        if 'homeroomRoomId' in teacher and not isinstance(teacher['homeroomRoomId'],str):raise StateError('Выберите кабинет классного руководителя.')
        if teacher.get('homeroomRoomId'):
            _require_refs(state,'rooms',[teacher['homeroomRoomId']],ids['rooms'],teacher['name'])
    for subject in state['subjects']:
        for key in ('firstMonday','pairedTechnology'):
            if key in subject and type(subject[key]) is not bool:raise StateError('Некорректное правило предмета.')
    for absence in state["absences"]:
        _require_refs(state, "teachers", [absence.get("teacherId")], ids["teachers"], absence.get("id", "?"))
        try:
            start, end = parse_date(absence["start"]), parse_date(absence["end"])
        except Exception as exc:
            raise StateError("У отсутствия указана некорректная дата.") from exc
        if end < start:
            raise StateError("Конец отсутствия не может быть раньше начала.")
        if not (1 <= int(absence.get("first", 1)) <= int(absence.get("last", 1)) <= 12):
            raise StateError("Некорректный диапазон уроков в отсутствии.")
    for student in state["students"]:
        _require_refs(state, "classes", [student.get("classId")], ids["classes"], student.get("name", "?"))
    for cls in state['classes']:
        if 'homeroomTeacherId' in cls and not isinstance(cls['homeroomTeacherId'],str):
            raise StateError('Выберите классного руководителя из списка преподавателей.')
        if cls.get('homeroomTeacherId'):
            _require_refs(state,'teachers',[cls['homeroomTeacherId']],ids['teachers'],cls['name'])

    bells = state["school"]["bells"]
    from .class_hours import SUBJECT_ID,ensure_subject
    if any(s['id']==SUBJECT_ID for s in state['subjects']):ensure_subject(state)
    if not 1 <= len(bells) <= 12:
        raise StateError("Укажите от 1 до 12 звонков.")

    conditions=state.get('assistantConditions',{})
    if not isinstance(conditions,dict) or len(conditions)>1000:
        raise StateError('Не удалось прочитать условия помощника по дням.')
    if conditions:
        from pydantic import TypeAdapter,ValidationError
        from .ai_planner import Action
        adapter=TypeAdapter(list[Action])
        lesson_ids={l['id'] for rows in [state['baseLessons'],*state['days'].values(),*state['dayBases'].values()] for l in rows}
        lesson_ids.update(s['id'] for rows in [*state['days'].values(),*state['dayBases'].values()]
                          for lesson in rows for s in lesson.get('classHour',{}).get('sources',[]))
        for day,rows in conditions.items():
            try:
                if parse_date(day).weekday()>4 or not isinstance(rows,list) or len(rows)>24:raise ValueError()
                typed=adapter.validate_python(rows)
                for item in typed:
                    if hasattr(item,'first') and item.first>item.last:raise ValueError()
                    for field,kind in [('teacherId','teachers'),('classId','classes'),('roomId','rooms')]:
                        if hasattr(item,field) and getattr(item,field) is not None and getattr(item,field) not in ids[kind]:raise ValueError()
                    if hasattr(item,'lessonId') and item.lessonId is not None and item.lessonId not in lesson_ids:raise ValueError()
                    if hasattr(item,'replaceLessonId') and item.replaceLessonId is not None and item.replaceLessonId not in lesson_ids:raise ValueError()
                    if item.type in ('class_day','group_day') and item.first>7:
                        permit_ids={r['lessonId'] for r in rows if r.get('type')=='allow_eighth'}
                        candidates=[l for lessons in [state['baseLessons'],*state['days'].values()] for l in lessons if item.classId in l['classIds']]
                        if not any(l['id'] in permit_ids or l.get('eighthOn')==day or is_eighth_exception(state,l) and parse_date(day).weekday()==eighth_exception(state)['day'] for l in candidates):raise ValueError()
                    if item.type=='join_lessons' and any(i not in lesson_ids for i in item.lessonIds):raise ValueError()
                    if item.type=='allow_technology' and (len(item.classIds)!=len(set(item.classIds)) or any(c not in ids['classes'] for c in item.classIds)):
                        raise ValueError()
                    if item.type=='join_technology':
                        from .technology import resolve_source
                        refs=[r.model_dump() for r in item.sources]
                        if len({(r['lessonId'],r['groupIndex']) for r in refs})!=2:raise ValueError()
                        for ref in refs:resolve_source(state,day,ref)
            except (ValueError,TypeError,ValidationError):
                raise StateError('В условиях помощника есть неизвестный класс, учитель, урок или некорректная дата. Снимите условия дня или загрузите исправную копию.') from None

    lists = [state["baseLessons"], *state["days"].values(), *state["dayBases"].values()]
    for lessons in lists:
        if len({l.get("id") for l in lessons}) != len(lessons):
            raise StateError("Идентификаторы занятий должны быть уникальны внутри дня.")
        for lesson in lessons:
            if not isinstance(lesson.get('id'),str) or not lesson['id'] or not lesson.get('classIds') or not lesson.get('teacherIds'):
                raise StateError('У занятия должны быть идентификатор, класс и преподаватель.')
            if 'groupIndex' in lesson and (type(lesson['groupIndex']) is not int or lesson['groupIndex'] not in (0,1)):
                raise StateError('Некорректная группа занятия.')
            if lesson.get('joint'):
                from .joint_lessons import problems
                errors=problems(state,lesson)
                if errors:raise StateError(errors[0])
            if lesson.get('technologyJoint'):
                from .technology import problems as technology_problems
                errors=technology_problems(state,lesson)
                if errors:raise StateError(errors[0])
            if lesson.get('eighthOn'):
                try:
                    if parse_date(lesson['eighthOn']).weekday()!=lesson['day']:raise ValueError()
                except (ValueError,TypeError):raise StateError('Исключение восьмого урока должно относиться к дате занятия.') from None
            _require_refs(state, "classes", lesson.get("classIds", []), ids["classes"], lesson.get("id", "?"))
            _require_refs(state, "teachers", lesson.get("teacherIds", []), ids["teachers"], lesson.get("id", "?"))
            _require_refs(state, "rooms", lesson.get("roomIds", []), ids["rooms"], lesson.get("id", "?"))
            _require_refs(state, "subjects", [lesson.get("subjectId")], ids["subjects"], lesson.get("id", "?"))
            if not (0 <= int(lesson.get("day", -1)) <= 4):
                raise StateError(f"Некорректный день недели у занятия {lesson.get('id')}.")
            if not (1 <= int(lesson.get("period", 0)) <= len(bells)):
                raise StateError(f"Номер урока вне расписания звонков у занятия {lesson.get('id')}.")
    for plan in state["plan"]:
        from .class_hours import SUBJECT_ID
        if plan.get('subjectId')==SUBJECT_ID:raise StateError('Классный час назначается на конкретную дату, без изменения учебного плана.')
        _require_refs(state, "classes", plan.get("classIds", []), ids["classes"], plan.get("id", "?"))
        _require_refs(state, "teachers", plan.get("teacherIds", []), ids["teachers"], plan.get("id", "?"))
        _require_refs(state, "rooms", plan.get("roomIds", []), ids["rooms"], plan.get("id", "?"))
        _require_refs(state, "subjects", [plan.get("subjectId")], ids["subjects"], plan.get("id", "?"))

    for key, lessons in {**state["days"], **state["dayBases"]}.items():
        try:
            weekday = parse_date(key).weekday()
        except Exception as exc:
            raise StateError(f"Некорректная дата в расписании: {key}.") from exc
        if weekday > 4:
            raise StateError("В школе пятидневка: в расписании не может быть субботы или воскресенья.")
        if any(int(l.get("day", -1)) != weekday for l in lessons):
            raise StateError(f"Дата {key} не совпадает с днём недели занятий.")
        from .class_hours import problems as class_hour_problems
        for lesson in lessons:
            errors=class_hour_problems(state,lesson,key)
            if errors:raise StateError(errors[0])
        if any(l.get('eighthOn') and l['eighthOn']!=key or l.get('joint') and l['joint']['date']!=key or l.get('technologyJoint') and l['technologyJoint']['date']!=key for l in lessons):
            raise StateError('Совместный урок или исключение восьмого урока относится к другой дате.')
    if any(l.get('eighthOn') or l.get('joint') or l.get('technologyJoint') for l in state['baseLessons']):
        raise StateError('Исключения и совместные уроки помощника сохраняются на выбранную дату, отдельно от базовой недели.')
    from .class_hours import SUBJECT_ID
    if any(l.get('classHour') or l.get('subjectId')==SUBJECT_ID for l in state['baseLessons']):
        raise StateError('Классный час сохраняется только на выбранную дату, отдельно от базовой недели.')

    # Base IDs repeat every week. Uniqueness is per actual week, including
    # untouched days inherited from the annual timetable.
    weeks = {tuple(week_dates(parse_date(key))) for key in state["days"]}
    for dates in weeks:
        seen = {}
        for day_key in dates:
            for lesson in lessons_for_day(state, day_key):
                ident = lesson["id"]
                if ident in seen:
                    raise StateError(f"Занятие одновременно стоит в двух днях: {seen[ident]} и {day_key}.")
                seen[ident] = day_key

    if check_collisions:
        for day_key, lessons in state["days"].items():
            collisions = check_slots(lessons, state)
            if collisions:
                raise StateError(collisions[0])
        collisions = check_slots(state["baseLessons"], state)
        if collisions:
            raise StateError(collisions[0])
    return state


def check_slots(lessons: list[dict], state=None) -> list[str]:
    """Return human-readable collision messages for one day."""
    out = []
    for kind, field, title in (("teacher", "teacherIds", "учителя"), ("class", "classIds", "класса"),
                               ("room", "roomIds", "кабинета")):
        used: dict[tuple, str] = {}
        for lesson in lessons:
            for ident in lesson.get(field) or []:
                groups = student_groups(lesson,ident) if kind == 'class' else [0]
                for group in groups:
                    key = (ident, int(lesson["day"]), int(lesson["period"]), group)
                    if key in used:
                        names={r['id']:r['name'] for r in state[{'teacher':'teachers','class':'classes','room':'rooms'}[kind]]} if state else {}
                        out.append(f"Пересечение у {title}: {names.get(ident,ident)}, "
                                   f"{DAYS[int(lesson['day'])].lower()}, урок {lesson['period']}.")
                    used[key] = lesson["id"]
    return out


def indexes(state: dict) -> dict:
    result={kind: {row["id"]: row for row in state[kind]} for kind in
            ("teachers", "classes", "subjects", "rooms", "plan")}
    # A search index lives for one unchanged school state. Validate the fixed
    # exception once, rather than rebuilding reference sets for every slot.
    result['_eighthRule']=eighth_exception(state)
    return result


# --------------------------------------------------------------------------
# day access


def base_for_weekday(state: dict, weekday: int) -> list[dict]:
    return [deepcopy(l) for l in state["baseLessons"] if int(l["day"]) == weekday]


def base_for_day(state: dict, day) -> list[dict]:
    key = iso(day)
    if key in state["dayBases"]:
        return [deepcopy(l) for l in state["dayBases"][key]]
    return base_for_weekday(state, parse_date(key).weekday())


def lessons_for_day(state: dict, day) -> list[dict]:
    key = iso(day)
    if key in state["days"]:
        return [deepcopy(l) for l in state["days"][key]]
    return base_for_weekday(state, parse_date(key).weekday())


def has_override(state: dict, day) -> bool:
    return iso(day) in state["days"]


def week_lessons(state: dict, day) -> list[dict]:
    return [l for key in week_dates(parse_date(day)) for l in lessons_for_day(state, key)]


def base_week(state: dict) -> list[dict]:
    return [deepcopy(l) for l in state["baseLessons"]]


def absence_periods(state: dict, teacher_id: str, day) -> set[int]:
    key = iso(day)
    out: set[int] = set()
    for absence in state["absences"]:
        if absence["teacherId"] != teacher_id:
            continue
        if iso(absence["start"]) <= key <= iso(absence["end"]):
            out.update(range(int(absence["first"]), int(absence["last"]) + 1))
    return out


def is_absent(state: dict, teacher_id: str, day, period: int) -> bool:
    return int(period) in absence_periods(state, teacher_id, day)


def unavailable(record: dict, weekday: int, period: int) -> bool:
    slots=record.get('unavailable')
    if not slots:return False
    weekday=int(weekday);period=int(period)
    for slot in slots:
        if isinstance(slot,dict):
            if int(slot.get('day',-1))==weekday and int(slot.get('period',0))==period:return True
        elif int(slot[0])==weekday and int(slot[1])==period:return True
    return False


def teacher_busy_at(state: dict, teacher_id: str, day, period: int) -> bool:
    """Teacher is absent or permanently unavailable at a concrete slot."""
    weekday = parse_date(day).weekday()
    teacher = indexes(state)["teachers"][teacher_id]
    from .commitments import teacher_busy
    return is_absent(state, teacher_id, day, int(period)) or unavailable(teacher, weekday, int(period)) or teacher_busy(state,teacher_id,day,int(period))


def slot_feasible(state,lesson,weekday,period,*,date=None,index=None,check_rooms=True,extra_absent=(),absence_slots=None):
    """Shared static slot rules. Occupancy and daily limits are checked by callers."""
    from .commitments import teacher_busy,room_busy
    ix=index if index is not None else indexes(state)
    if not period_allowed(state,lesson,period,weekday,date=date,_rule=ix.get('_eighthRule',_UNSET_RULE)):return False
    if lesson.get('classHour') and (period!=lesson['period'] or date is not None and str(date)!=lesson['classHour']['date']):return False
    subject=ix['subjects'].get(lesson.get('subjectId'))
    if subject and subject.get('unavailable') and unavailable(subject,weekday,period):return False
    if not subject or must_be_first(subject,lesson) and (weekday!=0 or period!=1):return False
    key=date if date is not None else weekday
    for cid in lesson.get('classIds',[]):
        record=ix['classes'].get(cid)
        if not record or period<record.get('firstPeriod',1) or unavailable(record,weekday,period):return False
    for tid in lesson.get('teacherIds',[]):
        record=ix['teachers'].get(tid)
        absent=(tid,period) in absence_slots if absence_slots is not None else date is not None and is_absent(state,tid,date,period)
        if not record or tid in extra_absent or absent or unavailable(record,weekday,period) or teacher_busy(state,tid,key,period):return False
    if check_rooms:
        for rid in lesson.get('roomIds',[]):
            record=ix['rooms'].get(rid)
            if not record or unavailable(record,weekday,period) or room_busy(state,rid,key,period):return False
            if not lesson.get('classHour') and record.get('subjectIds') and lesson['subjectId'] not in record['subjectIds']:return False
            size=room_student_count(state,lesson,rid)
            if record.get('capacity') and size is not None and size>record['capacity']:return False
    return True


def teacher_hours(state: dict, lessons: list[dict] | None = None) -> Counter:
    lessons = state["baseLessons"] if lessons is None else lessons
    return Counter(t for lesson in lessons if not lesson.get('classHour') for t in lesson.get("teacherIds", []))


def class_hours(lessons: list[dict]) -> Counter:
    return Counter(c for lesson in lessons for c in lesson.get("classIds", []))


def week_teacher_hours(state: dict, day) -> Counter:
    return teacher_hours(state, week_lessons(state, day))


# --------------------------------------------------------------------------
# issues


def issues(state: dict, lessons: list[dict], day=None, *, gaps: bool = True) -> list[dict]:
    """Check resources, availability, qualifications, daily limits and windows."""
    index = indexes(state)
    out: list[dict] = []
    weekday = parse_date(day).weekday() if day else None

    def add(level, code, message, lesson_ids):
        out.append({"level": level, "code": code, "message": message, "lessonIds": lesson_ids})

    slots: dict[tuple, list[str]] = defaultdict(list)
    daily: dict[tuple, list[int]] = defaultdict(list)
    group_daily=defaultdict(list)
    for lesson in lessons:
        subject = index["subjects"].get(lesson["subjectId"])
        if subject and unavailable(subject,lesson['day'],lesson['period']):
            add('error','subject_unavailable',f"{subject['name']}: предмет запрещён на этом уроке.",[lesson['id']])
        from .class_hours import problems as class_hour_problems
        for text in class_hour_problems(state,lesson,day):add('error','class_hour',text,[lesson['id']])
        if not period_allowed(state,lesson,date=day):
            add('error','forbidden_period','Восьмой урок отображается только для справки. Ставить на него занятия запрещено.',[lesson['id']])
        if lesson.get('joint'):
            from .joint_lessons import problems
            for text in problems(state,lesson,day):add('error','joint',text,[lesson['id']])
        if lesson.get('technologyJoint'):
            from .technology import problems,warnings
            for text in problems(state,lesson,day):add('error','technology_joint',text,[lesson['id']])
            for text in warnings(state,lesson):add('warning','technology_capacity',text,[lesson['id']])
        if subject and must_be_first(subject,lesson) and int(lesson["period"]) != 1:
            add("error", "first_period",
                f"{subject['name']}: должен стоять первым уроком.", [lesson["id"]])
        if subject and must_be_first(subject) and lesson['day']!=0:
            add('error','rov_day','«Разговоры о важном» проводятся только первым уроком понедельника.',[lesson['id']])
        for kind, field in (("teachers", "teacherIds"), ("classes", "classIds"), ("rooms", "roomIds")):
            for ident in lesson.get(field, []):
                record = index[kind].get(ident)
                if not record:
                    add("error", "missing_ref", f"Запись справочника не найдена: {ident}", [lesson["id"]])
                    continue
                groups = student_groups(lesson,ident) if kind == 'classes' else [0]
                for group in groups:
                    slots[kind, ident, lesson["day"], lesson["period"], group].append(lesson["id"])
                    if kind=='classes':group_daily[ident,lesson['day'],group].append(lesson['period'])
                daily[kind, ident, lesson["day"]].append(lesson["period"])
                if unavailable(record, lesson["day"], lesson["period"]):
                    add("error", "unavailable", f"{record['name']}: недоступен урок {lesson['period']}.", [lesson["id"]])
                if kind == "teachers" and weekday is not None and is_absent(state, ident, day, lesson["period"]):
                    add("error", "absence", f"{record['name']} отсутствует, урок {lesson['period']}.", [lesson["id"]])
                if kind == "teachers" and not lesson.get('classHour') and lesson["subjectId"] not in record.get("subjectIds", []):
                    add("warning", "qualification",
                        f"{record['name']}: предмет не отмечен в карточке учителя.", [lesson["id"]])
                if kind == "rooms":
                    size = room_student_count(state,lesson,ident) or 0
                    if record.get("capacity") and size > record["capacity"]:
                        add("error", "capacity", f"Кабинет {record['name']} не вмещает класс.", [lesson["id"]])
                    if not lesson.get('classHour') and record.get("subjectIds") and lesson["subjectId"] not in record["subjectIds"]:
                        add("error", "room_subject", f"Кабинет {record['name']} не подходит для предмета.", [lesson["id"]])
                if kind == "classes" and lesson["period"] < record.get("firstPeriod", 1):
                    add("error", "class_start", f"{record['name']}: урок раньше разрешённого времени.", [lesson["id"]])

    pair_errors=set()
    for (cid,sid,day_number,group),rows in paired_buckets(state,lessons).items():
        ordered=sorted(rows,key=lambda l:(l['period'],l['id']))
        ids=tuple(l['id'] for l in ordered)
        if (cid,sid,ids) in pair_errors:continue
        pair_errors.add((cid,sid,ids))
        title=index['classes'][cid]['name']+' · '+index['subjects'][sid]['name']
        # Allow one unfinished lesson in the annual editor without rejecting
        # an unrelated complete pair (e.g. periods 3, 5, 6).
        remaining=list(ordered)
        pairs=0
        while len(remaining)>1:
            first=remaining.pop(0)
            if remaining[0]['period']==first['period']+1:
                remaining.pop(0);pairs+=1
        if pairs < len(ordered)//2:
            add('error','pair_separated',title+': спаренные уроки должны идти подряд.',list(ids))
        if len(ordered)%2:
            # The annual editor may still be placing an unfinished pair. The
            # daily repair checker treats this warning as a hard restriction.
            add('warning','pair_incomplete',title+': спаренный урок остался без второго занятия.',list(ids))

    for (kind, ident, day_number, period, group), ids in slots.items():
        if len(ids) > 1:
            name = index[kind][ident]["name"]
            if kind == "teachers":
                message = f"У {name} уже есть урок в это время ({DAYS[int(day_number)].lower()}, {period} урок)."
            elif kind == "classes":
                message = f"{name}: в это время уже есть урок ({DAYS[int(day_number)].lower()}, {period} урок)."
            else:
                message = f"Кабинет {name} уже занят ({DAYS[int(day_number)].lower()}, {period} урок)."
            add("error", "collision", message, ids)

    if gaps:
        for (kind, ident, day_number), periods in daily.items():
            record = index[kind][ident]
            if kind == 'teachers' and len(set(periods)) > record.get("maxDaily", 8):
                add("error", "daily_limit", f"{record['name']}: превышен дневной предел.", [])
        reported=set()
        for (cid,d,g),periods in group_daily.items():
            record=index['classes'][cid]
            if len(set(periods))>record.get('maxDaily',8):add('error','daily_limit',record['name']+': превышен дневной предел подгруппы.',[])
            missing=gap_slots(periods)
            if missing and (cid,d,tuple(missing)) not in reported:
                reported.add((cid,d,tuple(missing)))
                label=(record.get('groupNames') or ['Подгруппа 1','Подгруппа 2'])[g]
                permitted=day and any(r['type']=='allow_class_gaps' for r in state.get('assistantConditions',{}).get(str(day),[]))
                add('error' if day and not permitted else 'warning','gap',f"{record['name']}, {label}: окно в {DAYS[d].lower()} ({', '.join(map(str,missing))} ур.).",[])
    from .commitments import conflicts as commitment_conflicts
    out.extend(commitment_conflicts(state,lessons,day))
    return out


def plan_report(state: dict) -> dict:
    """Compare plan hours with the base week, grouped by class/subject/teacher."""
    base_counts = Counter(lesson_key(l) for l in state["baseLessons"])
    rows = []
    for plan in state["plan"]:
        key = lesson_key(plan)
        planned = int(plan.get("hours") or 0)
        placed = base_counts.get(key, 0)
        rows.append({
            "id": plan["id"],
            "classIds": plan["classIds"],
            "subjectId": plan["subjectId"],
            "teacherIds": plan["teacherIds"],
            "hours": planned,
            "placed": placed,
            "delta": planned - placed,
            "confirmed": bool(plan.get("confirmed")),
        })
    base_by_teacher = Counter(t for l in state["baseLessons"] for t in l["teacherIds"])
    plan_by_teacher = Counter()
    for plan in state["plan"]:
        for teacher in plan["teacherIds"]:
            plan_by_teacher[teacher] += int(plan.get("hours") or 0)
    teachers = []
    for teacher in state["teachers"]:
        target = teacher.get("weeklyTarget")
        teachers.append({
            "id": teacher["id"],
            "name": teacher["name"],
            "target": target,
            "plan": plan_by_teacher[teacher["id"]],
            "base": base_by_teacher[teacher["id"]],
            "delta": (target or 0) - base_by_teacher[teacher["id"]],
        })
    return {
        "rows": rows,
        "teachers": teachers,
        "missing": [r for r in rows if r["delta"] > 0],
        "extra": [r for r in rows if r["delta"] < 0],
        "teacherShort": [t for t in teachers if t["delta"] != 0],
    }

