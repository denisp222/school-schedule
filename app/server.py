"""Local FastAPI application for the school timetable."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import logging
import sqlite3
import uuid
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .engine import apply_repair, fill_missing_hours, repair_day
from .exporter import export_docx
from .model import (
    DAYS,
    DAY_SHORT,
    KINDS,
    StateError,
    base_for_day,
    cell_signature,
    check_slots,
    diff_lessons,
    gap_slots,
    indexes,
    initial_state,
    is_absent,
    iso,
    issues,
    lessons_for_day,
    normalize_state,
    parse_date,
    plan_report,
    validate_state,
    week_dates,
    week_lessons,
)
from .store import Conflict, Store
from .model import period_allowed,plan_is_paired
from .rules import EIGHTH_MESSAGE
from .schemas import integer
from fastapi.exceptions import RequestValidationError

APP_NAME = "raspisanie"
from .version import VERSION
from .previews import PreviewStore
repair_previews = PreviewStore()
week_previews = PreviewStore(limit=10)
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SCHEDULE_DATA", str(ROOT.parent / "data")))
DATA.mkdir(parents=True, exist_ok=True)

store = Store(DATA / "schedule.sqlite3", initial_state)
app = FastAPI(title="Расписание", docs_url=None, redoc_url=None, openapi_url=None)


def school_today() -> str:
    day = date.today()
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def require_day(value: str) -> str:
    try:
        parsed = parse_date(value)
    except Exception as exc:
        raise ValueError("Некорректная дата.") from exc
    if parsed.weekday() > 4:
        raise ValueError("В школе пятидневка. Выберите понедельник–пятницу.")
    return parsed.isoformat()


def require_revision(body: dict) -> int:
    value = body.get("revision")
    if type(value) is not int:
        raise ValueError("Не указана версия данных. Обновите страницу.")
    return value


# --------------------------------------------------------------------------
# middleware


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.url.hostname
    if host not in ("localhost", "127.0.0.1", "testserver"):
        return JSONResponse({"detail": "Приложение доступно только на этом компьютере."}, status_code=403)
    origin = request.headers.get('origin')
    if (request.headers.get('sec-fetch-site') in ('cross-site', 'same-site') or
            origin and origin != f'{request.url.scheme}://{request.url.netloc}'):
        return JSONResponse({'detail': 'Запрос с другого сайта запрещён.'}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Запрос с другого сайта запрещён."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Запрос с другого сайта запрещён."}, status_code=403)
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "Ожидается JSON."}, status_code=415)
        if int(request.headers.get("content-length", "0") or 0) > 30_000_000:
            return JSONResponse({"detail": "Файл слишком большой."}, status_code=413)
    response = await call_next(request)
    # Windows registry associations can override mimetypes.guess_type (for
    # example, an editor registers .js as text/plain). Chromium then refuses
    # every UI script under nosniff, leaving only the loading skeleton.
    if request.url.path.startswith('/static/') and response.status_code==200:
        types={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8',
               '.svg':'image/svg+xml','.ico':'image/x-icon'}
        kind=types.get(Path(request.url.path).suffix.lower())
        if kind:response.headers['Content-Type']=kind
    if response.status_code<400 and request.url.path.startswith('/api/') and request.url.path not in ('/api/shutdown','/api/health'):
        response.headers['X-Schedule-Saved-At']=store.last_saved_at()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
    )
    return response


@app.exception_handler(Conflict)
async def conflict_handler(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(StateError)
async def state_error_handler(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    message=str(exc)
    if not message or message.isascii():
        logging.warning('Input validation failed: %s',type(exc).__name__)
        message='Проверьте заполнение полей: числа, даты и выбранные значения. Изменения не сохранены.'
    return JSONResponse({"detail": message}, status_code=422)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request, exc):
    return JSONResponse({'detail':'Проверьте формат запроса и заполнение полей. Изменения не сохранены.'},status_code=422)


@app.exception_handler(sqlite3.Error)
async def storage_error_handler(request, exc):
    logging.exception('Storage operation failed',exc_info=exc)
    return JSONResponse({'detail':'Не удалось сохранить изменение. Расписание осталось прежним. Закройте второе окно приложения, если оно открыто, и повторите действие.'},status_code=503)


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc):
    logging.exception('Unexpected application error',exc_info=exc)
    return JSONResponse({'detail':'Действие не выполнено из-за внутренней ошибки. Ваше расписание сохранено. Повторите попытку; если ошибка повторяется, перезапустите приложение.'},status_code=500)


# --------------------------------------------------------------------------
# health and state


@app.get("/api/health")
def health():
    from .process_context import restricted_process
    return {"app": APP_NAME, "version": VERSION, "data": str(DATA), "schema": 2,'restricted':restricted_process(),'pid':os.getpid()}


@app.get("/api/state")
def get_state():
    snapshot = store.read()
    return {
        "revision": snapshot["revision"],
        "state": snapshot["state"],
        "today": school_today(),
        "savedAt": snapshot['savedAt'],
        "server": {"version": VERSION, "data": str(DATA)},
    }


@app.get('/api/about')
def about_application():
    from .releases import about
    return about()


@app.get('/api/updates')
def update_settings():
    from .updates import status
    return status(DATA)


@app.post('/api/updates')
def save_update_settings(body: dict):
    if type(body.get('enabled')) is not bool:raise ValueError('Укажите, проверять ли обновления.')
    marker=DATA/'updates-disabled'
    if body['enabled']:marker.unlink(missing_ok=True)
    else:marker.touch()
    return update_settings()


@app.get('/api/bootstrap')
def bootstrap(date: str | None=None):
    from .distribution import voice_available
    snapshot=store.read()
    day=require_day(date) if date else school_today()
    return {**snapshot,'today':school_today(),'day':_day_payload(snapshot['state'],day),
            'features':{'voice':voice_available()},'server':{'version':VERSION}}


@app.post('/api/save')
def save_project(body: dict):
    saved=store.mutate(require_revision(body),'Сохранено вручную',lambda state:state)
    return {'revision':saved['revision'],'savedAt':saved['savedAt']}


def _day_payload(state: dict, day: str) -> dict:
    lessons = lessons_for_day(state, day)
    base = base_for_day(state, day)
    changes = diff_lessons(base, lessons)
    moved_to = {row.get("lessonId"): row.get("movedTo") for row in state["journal"]
                if row.get("date") == day and row.get("active") and row.get("movedTo")}
    for change in changes:
        if not change["after"] and change["id"] in moved_to:
            change["movedTo"] = moved_to[change["id"]]
    problems = issues(state, lessons, day)
    absences = []
    for absence in state["absences"]:
        if iso(absence["start"]) <= day <= iso(absence["end"]):
            teacher = next((t for t in state["teachers"] if t["id"] == absence["teacherId"]), None)
            absences.append({
                "id": absence["id"],
                "teacherId": absence["teacherId"],
                "name": teacher["name"] if teacher else absence["teacherId"],
                "first": absence["first"],
                "last": absence["last"],
                "reason": absence.get("reason", ""),
            })
    from .model import student_groups
    group_times={}
    for cls in state['classes']:
        times={}
        for g in (0,1):
            periods=sorted({l['period'] for l in lessons if cls['id'] in l['classIds'] and g in student_groups(l,cls['id'])})
            times[str(g)]={'first':min(periods),'last':max(periods)} if periods else None
        group_times[cls['id']]=times
    from .commitments import matching
    return {
        "date": day,
        "weekday": parse_date(day).weekday(),
        "lessons": lessons,
        "base": base,
        "changes": changes,
        "issues": problems,
        "absences": absences,
        "groupTimes":group_times,
        "externalActivities":matching(state,day),
        "stats": {
            "lessons": len(lessons),
            "changes": len(changes),
            "cancelled": sum(1 for c in changes if not c["after"]),
            "added": sum(1 for c in changes if not c["before"]),
            "errors": sum(1 for i in problems if i["level"] == "error"),
            "gaps": sum(1 for i in problems if i["code"] == "gap"),
        },
    }


@app.get("/api/day/{day}")
def get_day(day: str):
    day = require_day(day)
    return _day_payload(store.read()["state"], day)


@app.get("/api/week/{day}")
def get_week(day: str):
    day = require_day(day)
    state = store.read()["state"]
    days = []
    for key in week_dates(parse_date(day)):
        current = lessons_for_day(state, key)
        base = base_for_day(state, key)
        days.append({
            "date": key,
            "weekday": parse_date(key).weekday(),
            "count": len(current),
            "changes": len(diff_lessons(base, current)),
            "cancelled": sum(1 for c in diff_lessons(base, current) if not c["after"]),
            "lessons": current,
        })
    return {"days": days}


# --------------------------------------------------------------------------
# repair


def _repair_summary(result: dict) -> dict:
    changes = result.get("changes") or []
    by_teacher = Counter()
    for lesson in result.get("cancelled") or []:
        for tid in lesson.get("teacherIds", []):
            by_teacher[tid] += 1
    return {
        "status": result.get("status"),
        "date": result.get("date"),
        "message": result.get("message"),
        "changes": changes,
        "cancelled": result.get("cancelled") or [],
        "groupLosses": result.get("groupLosses") or [],
        "otherChanges": result.get("otherChanges") or {},
        "warnings": result.get("warnings") or [],
        "stats": result.get("stats"),
        "search":result.get("search"),
        "inputFingerprint":result.get("inputFingerprint"),
        "absentTeachers": result.get("absentTeachers") or [],
        "allowOtherDays": result.get("allowOtherDays"),
        "lostByTeacher": by_teacher,
        "variant": result.get("variant", 0),
        "title": result.get("title") or "Вариант",
        'after':result.get('after',[]),
    }


def _variant_fingerprint(result: dict) -> tuple:
    rows = []
    for lesson in result.get("after") or []:
        from .model import student_groups
        rows.append((lesson["id"], lesson["day"], lesson["period"],
                     tuple(sorted(lesson.get("teacherIds", []))), tuple(sorted(lesson.get("roomIds", []))),
                     tuple((c,tuple(student_groups(lesson,c))) for c in sorted(lesson['classIds']))))
    for key, lessons in (result.get("otherDays") or {}).items():
        for lesson in lessons:
            rows.append((lesson["id"], lesson["day"], lesson["period"],
                         tuple(sorted(lesson.get("teacherIds", []))), tuple(sorted(lesson.get("roomIds", [])))))
    return tuple(sorted(rows, key=str))


def _variant_rank(summary: dict) -> tuple:
    from .day_preferences import quality_key
    stats = summary.get("stats") or {}
    return (
        summary.get('status') not in ('ok','unchanged'),
        int(stats.get("classGapsAfter") or 0),
        *quality_key(stats),
        int(stats.get("groupSplits") or 0),
    )


def _repair_variants(state: dict, day: str, allow_other: bool, reason: str,
                     teacher_ids: list[str], revision=None) -> dict:
    from .ai_planner import variants as conditioned_variants
    work=deepcopy(state)
    if set(teacher_ids)-{t['id'] for t in work['teachers']}:raise ValueError('Выбранный учитель больше не найден. Обновите справочники.')
    for tid in sorted(set(teacher_ids)):
        work['absences'].append({'id':'preview-'+tid,'teacherId':tid,'start':day,'end':day,'first':1,'last':8})
    results=conditioned_variants(work,day,state.get('assistantConditions',{}).get(day,[]))
    summaries=[]
    for index,result in enumerate(results):
        token=uuid.uuid4().hex
        repair_previews[token]={'revision':revision,'result':deepcopy(result),'date':day}
        summaries.append({**_repair_summary(result),'id':index,'previewId':token})
    if not summaries:
        return {'status':'infeasible','variants':[],'revision':revision,'warnings':['Без окон у учеников допустимый вариант пока не найден. Текущее расписание не изменено.']}
    return {**summaries[0],'variants':summaries,'recommended':0,'revision':revision}


@app.post("/api/repair")
def repair_preview(body: dict):
    day = require_day(body.get("date", ""))
    snapshot = store.read()
    if body.get('revision') is not None and require_revision(body)!=snapshot['revision']:
        raise Conflict('Данные изменились. Обновите расписание перед подбором.')
    return _repair_variants(
        snapshot["state"],
        day,
        False,
        str(body.get("reason") or ""),
        list(body.get("teacherIds") or []),
        snapshot['revision'],
    )


@app.post("/api/repair/apply")
def repair_apply(body: dict):
    revision = require_revision(body)
    day = require_day(body.get("date", ""))
    allow_other = False
    reason = str(body.get("reason") or "Автоматический подбор")
    teacher_ids = list(body.get("teacherIds") or [])
    variant = integer(body.get('variant',0),'Вариант',minimum=0,maximum=20)
    label = f"Подбор на {day}"

    def change(state):
        token=body.get('previewId')
        if token:
            preview=repair_previews.get(token)
            if not preview or preview['revision']!=revision or preview['date']!=day:
                raise Conflict('Вариант устарел. Выполните подбор заново.')
            result=deepcopy(preview['result'])
            if result.get('otherDays'):raise ValueError('Перенос на другие дни запрещён. Выполните подбор заново.')
        else:
            # Compatibility for existing automation; the UI always uses a preview.
            result = repair_day(state, day, allow_other_days=allow_other, reason=reason,
                                teacher_ids=teacher_ids, variant=variant)
        if result["status"] not in ("ok", "unchanged"):
            raise ValueError(result.get("message") or "Не удалось подобрать вариант.")
        if result.get('actions'):
            from .ai_planner import commit
            return commit(state,day,result['actions'],result)
        conditions=state.get('assistantConditions',{}).get(day)
        if conditions:
            from .ai_planner import condition_problems
            problems=condition_problems(state,day,conditions,result)
            if problems:raise ValueError(' '.join(problems[:3]))
        apply_repair(state, result, reason)
        return state

    saved = store.mutate(revision, label, change)
    return {"revision": saved["revision"], "state": saved["state"], "day": _day_payload(saved["state"], day)}


# --------------------------------------------------------------------------
# entities


KIND_LABELS = {
    "teachers": "Учитель", "classes": "Класс", "subjects": "Предмет",
    "rooms": "Кабинет", "plan": "Учебный план", "absences": "Отсутствие",
    "students": "Ученик",
}


def entity_label(kind: str, record: dict) -> str:
    state = store.read()["state"]
    if kind == "absences":
        teacher = next((t for t in state["teachers"] if t["id"] == record.get("teacherId")), None)
        return f"Отсутствие: {teacher['name'] if teacher else 'учитель'}"
    if kind == "plan":
        classes = "/".join(c["name"] for c in state["classes"] if c["id"] in record.get("classIds", []))
        subject = next((s["name"] for s in state["subjects"] if s["id"] == record.get("subjectId")), "")
        return f"Учебный план: {classes} · {subject}"
    return f"{KIND_LABELS.get(kind, kind)}: {record.get('name', '')}"


def _default_record(kind: str, raw: dict, existing: dict | None = None) -> dict:
    record = deepcopy(existing or {})
    record.update(deepcopy(raw))
    record["id"] = record.get("id") or uuid.uuid4().hex
    if kind in ("teachers", "classes", "subjects", "rooms", "students") and not str(record.get("name", "")).strip():
        raise ValueError("Укажите название.")
    if kind == "teachers":
        record.setdefault("subjectIds", [])
        record.setdefault("weeklyTarget", None)
        record.setdefault("extraLimit", 0)
        record.setdefault("maxDaily", 8)
        record.setdefault("maxDays", 5)
        record.setdefault("unavailable", [])
        record.setdefault("homeroom", "")
        record.setdefault("personnelNumber", "")
        record.setdefault("department", "")
        record.setdefault("category", "")
        record.setdefault("note", "")
        record.setdefault("allowSubstitution", False)
        target = record.get("weeklyTarget")
        if target not in (None, ""):
            record["weeklyTarget"] = int(target)
            if not (0 <= record["weeklyTarget"] <= 60):
                raise ValueError("Недельная нагрузка должна быть от 0 до 60 часов.")
        else:
            record["weeklyTarget"] = None
        record["maxDaily"] = int(record.get("maxDaily") or 8)
        if not (1 <= record["maxDaily"] <= 12):
            raise ValueError("Дневной предел должен быть от 1 до 12 уроков.")
    elif kind == "classes":
        record.setdefault("size", 0)
        record.setdefault("maxDaily", 8)
        record.setdefault("firstPeriod", 1)
        record.setdefault("unavailable", [])
        record.setdefault("template", False)
        record["size"] = int(record["size"] or 0)
        record["maxDaily"] = int(record["maxDaily"] or 8)
        record["firstPeriod"] = int(record["firstPeriod"] or 1)
    elif kind == "subjects":
        record.setdefault("short", record.get("name", ""))
        record.setdefault("teacherCode", "")
        record.setdefault("difficulty", 5)
        record.setdefault("preferredPeriods", [])
        if not str(record["short"]).strip():
            record["short"] = record["name"]
    elif kind == "rooms":
        record.setdefault("capacity", 0)
        record.setdefault("floor", "")
        record.setdefault("subjectIds", [])
        record.setdefault("teacherId", "")
        record.setdefault("classId", "")
        record.setdefault("unavailable", [])
        record["capacity"] = int(record["capacity"] or 0)
    elif kind == "plan":
        record.setdefault("classIds", [])
        record.setdefault("teacherIds", [])
        record.setdefault("roomIds", [])
        record.setdefault("hours", 0)
        record.setdefault("observed", 0)
        record.setdefault("doubleLessons", False)
        record.setdefault("maxPerDay", 2)
        record.setdefault("confirmed", True)
        record["hours"] = int(record.get("hours") or 0)
        record["observed"] = int(record.get("observed") or 0)
        record["maxPerDay"] = int(record.get("maxPerDay") or 2)
        if not record["classIds"]:
            raise ValueError("Выберите класс.")
        if not record.get("subjectId"):
            raise ValueError("Выберите предмет.")
        if not (0 <= record["hours"] <= 40):
            raise ValueError("Часы в плане должны быть от 0 до 40.")
    elif kind == "absences":
        record.setdefault("first", 1)
        record.setdefault("last", 8)
        record.setdefault("reason", "Отсутствие")
        record["first"], record["last"] = int(record["first"]), int(record["last"])
        start = parse_date(record.get("start"))
        end = parse_date(record.get("end"))
        if end < start:
            raise ValueError("Конец отсутствия не может быть раньше начала.")
        if not (1 <= int(record["first"]) <= int(record["last"]) <= 12):
            raise ValueError("Некорректный диапазон уроков.")
        record["start"], record["end"] = start.isoformat(), end.isoformat()
        if not record.get("teacherId"):
            raise ValueError("Выберите учителя.")
    elif kind == "students":
        record.setdefault("classId", "")
        record.setdefault("examSubjects", [])
        record.setdefault("note", "")
    return record


@app.post("/api/entity/{kind}")
def upsert(kind: str, body: dict):
    if kind not in KINDS:
        raise ValueError("Неизвестный справочник.")
    revision = require_revision(body)
    raw = deepcopy(body.get("record") or {})
    ident = raw.get("id") or uuid.uuid4().hex

    def change(state):
        existing = next((x for x in state[kind] if x["id"] == ident), None)
        from .class_hours import fill_leaders,assign_from_teacher,sync_labels
        if kind in ('teachers','classes'):fill_leaders(state)
        record = _default_record(kind, {**raw, "id": ident}, existing)
        if kind=='plan' and plan_is_paired(record,{s['id']:s for s in state['subjects']}):record['doubleLessons']=True
        if existing is None:
            state[kind].append(record)
        else:
            state[kind][state[kind].index(existing)] = record
        if kind=='teachers' and 'homeroom' in raw:
            assign_from_teacher(state,ident,record['homeroom'])
        elif kind=='classes':sync_labels(state)
        if kind == "absences":
            # A changed absence must not leave impossible lessons silently.
            validate_state(state)
        return state

    saved = store.mutate(revision, entity_label(kind, raw), change)
    return {"revision": saved["revision"], "state": saved["state"], "id": ident}


@app.post("/api/entity/{kind}/delete")
def delete_entity(kind: str, body: dict):
    if kind not in KINDS:
        raise ValueError("Неизвестный справочник.")
    revision = require_revision(body)
    ident = body.get("id")
    if not ident:
        raise ValueError("Не указана запись.")

    def change(state):
        if kind == "teachers" and any(ident in l.get("teacherIds", []) for l in state["baseLessons"]):
            raise ValueError("Учитель есть в расписании. Сначала переназначьте его занятия.")
        if kind == "classes" and any(ident in l.get("classIds", []) for l in state["baseLessons"]):
            raise ValueError("Класс есть в расписании. Сначала удалите его занятия.")
        if kind == "subjects" and any(l.get("subjectId") == ident for l in state["baseLessons"]):
            raise ValueError("Предмет есть в расписании. Сначала удалите его занятия.")
        if kind == "rooms" and any(ident in l.get("roomIds", []) for l in state["baseLessons"]):
            raise ValueError("Кабинет есть в расписании. Сначала переназначьте занятия.")
        state[kind] = [x for x in state[kind] if x["id"] != ident]
        return state

    state = store.read()["state"]
    existing = next((x for x in state.get(kind, []) if x["id"] == ident), {"id": ident})
    saved = store.mutate(revision, "Удаление — " + entity_label(kind, existing), change)
    return {"revision": saved["revision"], "state": saved["state"]}


# --------------------------------------------------------------------------
# lessons


def _guard_change(state: dict, before: list[dict], after: list[dict], day: str, scope="day") -> None:
    conditions=state.get('assistantConditions',{}).get(day) if scope=='day' else None
    if conditions:
        from .ai_planner import condition_problems
        errors=condition_problems(state,day,conditions,{'date':day,'after':after})
        if errors:raise ValueError(' '.join(errors[:3])+' Условия можно снять в разделе «Помощник».')
    if any(not period_allowed(state,l,date=day if scope=='day' else None) for l in after):raise ValueError(EIGHTH_MESSAGE)
    proposed = deepcopy(state)
    weekday = parse_date(day).weekday()
    if scope == "base":
        proposed["baseLessons"] = [l for l in state["baseLessons"] if l["day"] != weekday] + after
    else:
        proposed["days"][day] = after
    validate_state(proposed, check_collisions=False)
    actual = day if scope == "day" else None
    old_errors = {(x["code"], tuple(sorted(x["lessonIds"]))) for x in issues(state, before, actual) if x["level"] == "error"}
    new_errors = [x for x in issues(state, after, actual)
                  if scope=='day' and x['code']=='pair_incomplete' or x['level']=='error' and
                  (x['code'] in ('pair_separated','first_period','rov_day') or
                   (x["code"], tuple(sorted(x["lessonIds"]))) not in old_errors)]
    if new_errors:
        raise ValueError("\n".join(x["message"] for x in new_errors[:6]))
    old_week = state["baseLessons"] if scope == "base" else week_lessons(state, day)
    new_week = proposed["baseLessons"] if scope == "base" else week_lessons(proposed, day)
    for teacher in state["teachers"]:
        tid = teacher["id"]
        old_rows = [l for l in old_week if tid in l["teacherIds"] and not l.get('classHour')]
        new_rows = [l for l in new_week if tid in l["teacherIds"] and not l.get('classHour')]
        cap = teacher.get("weeklyTarget")
        if cap is not None and len(new_rows) > max(cap, len(old_rows)):
            raise ValueError(teacher["name"] + ": превышена недельная нагрузка.")
        if len({l["day"] for l in new_rows}) > max(teacher.get("maxDays", 5), len({l["day"] for l in old_rows})):
            raise ValueError(teacher["name"] + ": превышено число рабочих дней.")
    from .model import student_groups
    for cls in state['classes']:
        for group in (0,1):
            periods=[l['period'] for l in after if cls['id'] in l['classIds'] and group in student_groups(l,cls['id'])]
            if gap_slots(periods):raise ValueError(f"{cls['name']}: у подгруппы появляется окно. Сдвиньте уроки или используйте подбор.")


def _journal(state: dict, day: str, before: list[dict], after: list[dict], reason: str) -> None:
    created = datetime.now(timezone.utc).isoformat()
    for change in diff_lessons(before, after):
        for existing in state["journal"]:
            if existing.get("lessonId") == change["id"] and existing.get("date") == day:
                existing["active"] = False
        state["journal"].append({
            "id": uuid.uuid4().hex,
            "created": created,
            "date": day,
            "lessonId": change["id"],
            "before": change["before"],
            "after": change["after"],
            "movedTo": "",
            "reason": reason,
            "kind": "move" if change["after"] else "cancel",
            "active": any(c["id"] == change["id"] for c in diff_lessons(base_for_day(state, day), after)),
            "confirmed": False,
        })


def _same_stored_lessons(first,second):
    return sorted(first,key=lambda l:l['id']) == sorted(second,key=lambda l:l['id'])


def _commit_day(state: dict, day: str, before: list[dict], after: list[dict], reason: str) -> None:
    after = sorted(after, key=lambda lesson: (lesson["period"], lesson["id"]))
    if day not in state["dayBases"]:
        state["dayBases"][day] = base_for_day(state, day)
    annual = [l for l in state['baseLessons'] if l['day'] == parse_date(day).weekday()]
    if _same_stored_lessons(after,annual):
        state["days"].pop(day, None)
        state["dayBases"].pop(day, None)
    else:
        state["days"][day] = after
    _journal(state, day, before, after, reason)


@app.post("/api/lesson")
def edit_lesson(body: dict):
    revision = require_revision(body)
    scope = body.get("scope", "day")
    if scope not in ("day", "base"):
        raise ValueError("Неизвестный режим редактирования.")
    day = require_day(body.get("date", ""))
    weekday = parse_date(day).weekday()

    def change(state):
        raw = deepcopy(body.get("lesson") or {})
        raw["id"] = raw.get("id") or uuid.uuid4().hex
        raw["day"] = weekday
        raw.setdefault("teacherIds", [])
        raw.setdefault("roomIds", [])
        raw.setdefault("locked", False)
        if scope == "base":
            before = [deepcopy(l) for l in state["baseLessons"] if int(l["day"]) == weekday]
            source = state["baseLessons"]
        else:
            before = lessons_for_day(state, day)
            source = None
        old = next((l for l in before if l["id"] == raw["id"]), None)
        if scope=='day' and old and old.get('classHour') and body.get('remove'):
            state.get('assistantConditions',{})[day]=[r for r in state.get('assistantConditions',{}).get(day,[])
                if not (r['type']=='class_hour' and r['classId'] in old['classIds'])]
        if not body.get('remove') and state['plan']:
            matching = [p for p in state['plan'] if set(p['classIds']) == set(raw.get('classIds',[])) and p['subjectId'] == raw.get('subjectId') and set(p['teacherIds']) == set(raw.get('teacherIds',[]))]
            if not old and not matching:
                raise ValueError('Для этого класса и предмета у выбранного учителя нет назначения в учебном плане.')
        if scope == "day" and old and not body.get("remove"):
            for field in ("teacherIds", "classIds", "subjectId"):
                a, b = old[field], raw.get(field)
                if (sorted(a) if isinstance(a, list) else a) != (sorted(b) if isinstance(b, list) else b):
                    raise ValueError("Урок переносится вместе со своим классом, предметом и учителем. Постоянные назначения меняются в базовой неделе.")
        after = deepcopy(before)
        if body.get("swapId"):
            other = next((l for l in after if l["id"] == body["swapId"]), None)
            if not old or not other or set(old["classIds"]) != set(other["classIds"]):
                raise ValueError("Обмен доступен между двумя уроками одного класса.")
            if other.get("locked"):
                raise ValueError("Второй урок закреплён. Сначала снимите закрепление.")
            other["period"], other["day"] = old["period"], old["day"]
        if not raw.get("teacherIds"):
            raise ValueError("Выберите преподавателя.")
        after = [l for l in after if l["id"] != raw["id"]]
        if not body.get("remove"):
            after.append(raw)
        after.sort(key=lambda l: (l["period"], l["id"]))
        for plan in state['plan']:
            def count(rows):
                return sum(bool(set(l['classIds']) & set(plan['classIds'])) and l['subjectId'] == plan['subjectId'] for l in rows)
            if count(after) > max(int(plan.get('maxPerDay',2)), count(before)):
                raise ValueError('Превышено число уроков этого предмета в день, указанное в учебном плане.')
        _guard_change(state, before, after, day, scope)
        if scope == "base":
            state["baseLessons"] = [l for l in state["baseLessons"] if int(l["day"]) != weekday] + after
            state["baseLessons"].sort(key=lambda l: (l["day"], l["period"]))
            validate_state(state)
        else:
            _commit_day(state, day, before, after, str(body.get("reason") or "Ручная правка"))
        return state

    saved = store.mutate(revision, f"Изменение занятия: {day}", change)
    return {"revision": saved["revision"], "state": saved["state"], "day": _day_payload(saved["state"], day)}


@app.post('/api/lesson/class-hour')
def convert_class_hour(body: dict):
    revision=require_revision(body);day=require_day(body.get('date',''))
    lesson_id=body.get('lessonId');enabled=body.get('enabled')
    if not isinstance(lesson_id,str) or type(enabled) is not bool:raise ValueError('Выберите занятие и действие с классным часом.')
    if 'roomIds' in body and (not isinstance(body['roomIds'],list) or any(not isinstance(r,str) for r in body['roomIds'])):
        raise ValueError('Выберите кабинеты из списка.')
    def change(state):
        from .class_hours import create,restore,ensure_subject
        before=lessons_for_day(state,day)
        old=next((l for l in before if l['id']==lesson_id),None)
        if not old:raise ValueError('Занятие больше не найдено. Обновите расписание.')
        if enabled and len(old['classIds'])!=1:raise ValueError('Выберите отдельный урок целого класса.')
        cid=old['classIds'][0]
        if enabled:
            event=create(state,day,cid,lesson_id);ensure_subject(state)
            if 'roomIds' in body:event['roomIds']=deepcopy(body['roomIds'])
            after=[l for l in before if l['id']!=lesson_id]+[event]
        else:after=restore(state,day,lesson_id)
        conditions=[r for r in state.get('assistantConditions',{}).get(day,[]) if not (r['type']=='class_hour' and r['classId'] in old['classIds'])]
        if enabled:conditions.append({'type':'class_hour','classId':cid,'lessonId':lesson_id})
        state.setdefault('assistantConditions',{})[day]=conditions
        _guard_change(state,before,after,day,'day')
        _commit_day(state,day,before,after,'Назначен классный час' if enabled else 'Восстановлен урок вместо классного часа')
    saved=store.mutate(revision,'Классный час: '+day,change)
    return {**saved,'day':_day_payload(saved['state'],day)}


@app.post("/api/lesson/move")
def move_lesson(body: dict):
    revision = require_revision(body)
    day = require_day(body.get("date", ""))
    lesson_id = body.get("lessonId")
    period = integer(body.get('period'),'Номер урока',minimum=1,maximum=8)
    if not lesson_id:
        raise ValueError("Не указан урок.")
    if not (1 <= period <= len(store.read()["state"]["school"]["bells"])):
        raise ValueError("Некорректный номер урока.")

    def change(state):
        scope=body.get('scope','day')
        if scope not in ('day','base'):raise ValueError('Неизвестный режим расписания.')
        before = [deepcopy(l) for l in state['baseLessons'] if l['day']==parse_date(day).weekday()] if scope=='base' else lessons_for_day(state, day)
        lesson = next((item for item in before if item["id"] == lesson_id), None)
        if not lesson:
            raise ValueError("Урок не найден в этом дне.")
        if lesson.get("locked"):
            raise ValueError("Закреплённый урок нельзя перетаскивать. Сначала снимите закрепление.")
        updated = deepcopy(lesson)
        updated["period"] = period
        after = [item for item in before if item["id"] != lesson_id] + [updated]
        _guard_change(state, before, after, day,scope)
        if scope=='base':state['baseLessons']=[l for l in state['baseLessons'] if l['day']!=parse_date(day).weekday()]+after
        else:_commit_day(state, day, before, after, "Перетаскивание урока")
        return state

    saved = store.mutate(revision, "Перетаскивание урока", change)
    return {"revision": saved["revision"], "state": saved["state"], "day": _day_payload(saved["state"], day)}


@app.post('/api/lesson/targets')
def lesson_targets(body: dict):
    snapshot=store.read()
    if require_revision(body)!=snapshot['revision']:raise Conflict('Расписание изменилось. Обновите страницу перед переносом.')
    state=snapshot['state'];day=require_day(body.get('date',''))
    scope=body.get('scope','day')
    if scope not in ('day','base'):raise ValueError('Неизвестный режим расписания.')
    before=[deepcopy(l) for l in state['baseLessons'] if l['day']==parse_date(day).weekday()] if scope=='base' else lessons_for_day(state,day)
    source=next((l for l in before if l['id']==body.get('lessonId')),None)
    if not source:raise ValueError('Урок не найден. Обновите расписание.')
    def check(period,target=None):
        if not period_allowed(state,source,period,parse_date(day).weekday(),date=day if scope=='day' else None):return {'allowed':False,'reason':EIGHTH_MESSAGE}
        if source.get('locked') or target and target.get('locked'):
            return {'allowed':False,'reason':'Урок закреплён. Сначала снимите закрепление в редакторе.'}
        if period==source['period']:return {'allowed':False,'reason':'Урок уже стоит в это время.'}
        after=deepcopy(before)
        for lesson in after:
            if lesson['id']==source['id']:lesson['period']=period
            elif target and lesson['id']==target['id']:lesson['period']=source['period']
        try:_guard_change(state,before,after,day,scope)
        except (ValueError,StateError) as exc:return {'allowed':False,'reason':str(exc).split('\n')[0]}
        return {'allowed':True,'reason':'Можно поменять уроки местами.' if target else 'Можно перенести урок.'}
    return {'revision':snapshot['revision'],'moves':{str(p):check(p) for p in range(1,len(state['school']['bells'])+1)},
            'swaps':{l['id']:check(l['period'],l) for l in before if l['id']!=source['id']}}


@app.post("/api/lesson/swap")
def swap_lessons(body: dict):
    revision = require_revision(body)
    day = require_day(body.get("date", ""))
    first_id = body.get("firstId")
    second_id = body.get("secondId")
    if not first_id or not second_id or first_id == second_id:
        raise ValueError("Выберите два разных урока.")

    def change(state):
        scope=body.get('scope','day')
        if scope not in ('day','base'):raise ValueError('Неизвестный режим расписания.')
        before = [deepcopy(l) for l in state['baseLessons'] if l['day']==parse_date(day).weekday()] if scope=='base' else lessons_for_day(state, day)
        first = next((item for item in before if item["id"] == first_id), None)
        second = next((item for item in before if item["id"] == second_id), None)
        if not first or not second:
            raise ValueError("Один из уроков не найден в этом дне.")
        if first.get("locked") or second.get("locked"):
            raise ValueError("Закреплённый урок нельзя переставлять. Сначала снимите закрепление.")
        first_new, second_new = deepcopy(first), deepcopy(second)
        first_new["period"], second_new["period"] = second["period"], first["period"]
        after = [item for item in before if item["id"] not in (first_id, second_id)] + [first_new, second_new]
        _guard_change(state, before, after, day,scope)
        if scope=='base':state['baseLessons']=[l for l in state['baseLessons'] if l['day']!=parse_date(day).weekday()]+after
        else:_commit_day(state, day, before, after, "Обмен уроками перетаскиванием")
        return state

    saved = store.mutate(revision, "Обмен уроками", change)
    return {"revision": saved["revision"], "state": saved["state"], "day": _day_payload(saved["state"], day)}


@app.post("/api/day/reset")
def reset_day(body: dict):
    revision = require_revision(body)
    day = require_day(body.get("date", ""))

    def change(state):
        # Cross-day moves are one operation. Restoring only the moved lesson
        # could collide with another lesson that was shifted into its slot.
        connected = {day}
        while True:
            previous = set(connected)
            for row in state['journal']:
                if row.get('active') and row.get('movedTo') and ({row['date'], row['movedTo']} & connected):
                    connected.update((row['date'], row['movedTo']))
            if connected == previous:
                break
        baselines = {key: base_for_day(state, key) for key in connected}
        for key, baseline in baselines.items():
            state.get('assistantConditions',{}).pop(key,None)
            annual = [l for l in state['baseLessons'] if l['day'] == parse_date(key).weekday()]
            if _same_stored_lessons(baseline,annual):
                state['days'].pop(key, None)
                state['dayBases'].pop(key, None)
            else:
                state['days'][key] = deepcopy(baseline)
                state['dayBases'][key] = deepcopy(baseline)
        for row in state['journal']:
            if row.get('date') in connected:
                row['active'] = False
        return state

    saved = store.mutate(revision, f"Возврат к базовому дню: {day}", change)
    return {"revision": saved["revision"], "state": saved["state"], "day": _day_payload(saved["state"], day)}


# --------------------------------------------------------------------------
# plan / week fill


@app.post('/api/week/build')
def build_annual_week(body: dict):
    from .annual import build_week
    snapshot=store.read()
    if require_revision(body)!=snapshot['revision']:
        raise Conflict('Данные изменились. Обновите расписание.')
    result=build_week(snapshot['state'])
    if result['status']=='ok':
        token=uuid.uuid4().hex
        week_previews[token]={'revision':snapshot['revision'],'lessons':result['lessons']}
        return {**result,'previewId':token,'revision':snapshot['revision'],
                'changes':diff_lessons(snapshot['state']['baseLessons'],result['lessons'])}
    return result


@app.post('/api/week/apply')
def apply_annual_week(body: dict):
    revision=require_revision(body)
    preview=week_previews.get(body.get('previewId'))
    if not preview or preview['revision']!=revision:
        raise Conflict('Вариант устарел. Составьте неделю заново.')
    def change(state):
        for day in state['days']:
            if day not in state['dayBases']:state['dayBases'][day]=base_for_day(state,day)
        state['baseLessons']=deepcopy(preview['lessons'])
        return state
    saved=store.mutate(revision,'Составлена полная базовая неделя по учебному плану',change)
    return {'revision':saved['revision'],'state':saved['state']}


@app.get("/api/plan/check")
def plan_check():
    state = store.read()["state"]
    return {"report": plan_report(state), "issues": issues(state, state["baseLessons"], gaps=True)}


@app.post("/api/fill-missing")
def fill_missing(body: dict):
    revision = require_revision(body)
    apply = bool(body.get("apply"))
    if not apply:
        snapshot = store.read()
        return fill_missing_hours(snapshot["state"], apply=False)

    def change(state):
        result = fill_missing_hours(state, apply=True)
        return result.get("state") or state

    saved = store.mutate(revision, "Достроены недостающие часы учебного плана", change)
    return {"revision": saved["revision"], "state": saved["state"]}


# --------------------------------------------------------------------------
# reports


@app.get("/api/reports/{day}")
def reports(day: str):
    day = require_day(day)
    state = store.read()["state"]
    week = week_lessons(state, day)
    actual = Counter(t for l in week for t in l["teacherIds"])
    plan = plan_report(state)
    for row in plan["teachers"]:
        row["week"] = actual[row["id"]]
        row["weekDelta"] = (row["target"] or 0) - actual[row["id"]]
    return {
        "date": day,
        "teachers": plan["teachers"],
        "rows": plan["rows"],
        "missing": plan["missing"],
        "extra": plan["extra"],
        "issues": [i for i in issues(state, state["baseLessons"], gaps=True) if i["level"] == "error"],
        "gaps": [i for i in issues(state, state["baseLessons"], gaps=True) if i["code"] == "gap"],
        "summary": {
            "teachers": len(state["teachers"]),
            "classes": len(state["classes"]),
            "lessons": len(state["baseLessons"]),
            "planHours": sum(int(p.get("hours") or 0) for p in state["plan"]),
            "weekLessons": len(week),
        },
    }


# --------------------------------------------------------------------------
# journal, settings, history


@app.post("/api/journal")
def journal_update(body: dict):
    revision = require_revision(body)
    ident = body.get("id")
    if not ident:
        raise ValueError("Не указана запись журнала.")
    percent = integer(body.get('payPercent',100),'Процент оплаты',minimum=0,maximum=100)
    if percent not in (0, 50, 100):
        raise ValueError("Процент оплаты: 0, 50 или 100.")

    def change(state):
        row = next((r for r in state["journal"] if r["id"] == ident), None)
        if not row:
            raise ValueError("Запись журнала не найдена.")
        row["confirmed"] = bool(body.get("confirmed"))
        row["payPercent"] = percent
        return state

    saved = store.mutate(revision, "Отметка проведения", change)
    return {"revision": saved["revision"], "state": saved["state"]}


@app.post("/api/settings")
def settings(body: dict):
    revision = require_revision(body)
    school = deepcopy(body.get("school") or {})
    if not isinstance(school,dict):raise ValueError('Не удалось прочитать настройки школы.')

    def change(state):
        new = {**state["school"], **school}
        bells = new.get("bells") or state["school"]["bells"]
        if not (1 <= len(bells) <= 12):
            raise ValueError("Укажите от 1 до 12 звонков.")
        max_period = max([int(l["period"]) for l in state["baseLessons"]] or [1])
        if len(bells) < max_period:
            raise ValueError("В расписании есть уроки позже последнего звонка. Сначала перенесите их.")
        new["bells"] = [str(x) for x in bells]
        new['noClassGaps']=True
        new['noNewTeacherGaps']=False
        new["freeRoomLastPeriod"] = min(6,len(bells),integer(new.get('freeRoomLastPeriod',6),'Последний урок свободных кабинетов',minimum=1,maximum=12))
        state["school"] = new
        return state

    saved = store.mutate(revision, "Настройки школы", change)
    return {"revision": saved["revision"], "state": saved["state"]}


@app.get("/api/history")
def history():
    return {"history": store.history()}


@app.post("/api/history/restore")
def restore(body: dict):
    revision = require_revision(body)
    snapshot = store.snapshot(integer(body.get('id'),'Номер версии',minimum=1))
    saved = store.mutate(revision, f"Восстановлена версия {body['id']}", lambda _: normalize_state(snapshot))
    return {"revision": saved["revision"], "state": saved["state"]}


@app.get("/api/backup")
def backup():
    from .assistant_history import AssistantHistory
    state=store.read()['state'];state['_assistantConversations']=AssistantHistory(store).export()
    payload=json.dumps(state,ensure_ascii=False,indent=2).encode('utf-8')
    return attachment(payload, "application/json", "Расписание-резервная-копия.json")


@app.post("/api/import")
def import_backup(body: dict):
    revision = require_revision(body)
    from .assistant_history import AssistantHistory
    raw=deepcopy(body.get('state') or {})
    rows=AssistantHistory.validate_import(raw.pop('_assistantConversations',[]))
    AssistantHistory(store)
    state=normalize_state(raw)
    saved=store.mutate(revision,'Загружена резервная копия',lambda _:state,extra=lambda db:AssistantHistory.restore(db,rows))
    return {"revision": saved["revision"], "state": saved["state"]}


# --------------------------------------------------------------------------
# export


def attachment(data: bytes, content_type: str, filename: str) -> Response:
    return Response(
        data,
        media_type=content_type,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)},
    )


DAY_FILE = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]


def _file_date(day: str) -> str:
    parsed = parse_date(day)
    return parsed.strftime("%d.%m.%Y")


@app.get("/api/export/{audience}/{day}")
def export(audience: str, day: str, names: int = 1, preview: int = 0,mode: str='changes'):
    if audience not in ("students", "teachers"):
        raise ValueError("Неизвестный вид экспорта.")
    day = require_day(day)
    state = store.read()["state"]
    try:
        data = export_docx(state, day, audience, update_names=bool(names),mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    who = "учителя" if audience == "teachers" else "ученики"
    suffix={'changes':'с изменениями','clean':'без выделения','base':'базовое'}[mode]
    filename = f"{DAY_FILE[parse_date(day).weekday()]} {_file_date(day)} — {who} — {suffix}.docx"
    return attachment(data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename)


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t")):
        return "'" + text
    return text


@app.get("/api/report-csv/{kind}")
def report_csv(kind: str, day: str | None = None):
    state = store.read()["state"]
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    names = {k: {x["id"]: x["name"] for x in state[k]} for k in ("teachers", "classes", "subjects", "rooms")}
    if kind == "load":
        writer.writerow(["Учитель", "Норма", "Учебный план", "Базовая неделя", "Отклонение"])
        report = plan_report(state)
        for row in report["teachers"]:
            writer.writerow([_csv_safe(row["name"]), row["target"] or 0, row["plan"], row["base"], row["delta"]])
    elif kind == "plan":
        writer.writerow(["Класс", "Предмет", "Учитель", "Часов в неделю", "Расставлено"])
        report = plan_report(state)
        for row in report["rows"]:
            writer.writerow([
                _csv_safe("/".join(names["classes"][c] for c in row["classIds"])),
                _csv_safe(names["subjects"][row["subjectId"]]),
                _csv_safe("/".join(names["teachers"][t] for t in row["teacherIds"])),
                row["hours"], row["placed"],
            ])
    elif kind == "journal":
        writer.writerow(["Дата", "Урок", "Класс", "Предмет", "Было", "Стало", "Причина", "Проведено"])
        for row in state["journal"]:
            lesson = row.get("after") or row.get("before") or {}
            writer.writerow([
                row["date"], lesson.get("period", ""),
                _csv_safe("/".join(names["classes"].get(c, c) for c in lesson.get("classIds", []))),
                _csv_safe(names["subjects"].get(lesson.get("subjectId"), "")),
                _csv_safe("/".join(names["teachers"].get(t, t) for t in (row.get("before") or {}).get("teacherIds", []))),
                _csv_safe("/".join(names["teachers"].get(t, t) for t in (row.get("after") or {}).get("teacherIds", []))),
                _csv_safe(row.get("reason", "")), "Да" if row.get("confirmed") else "Нет",
            ])
    else:
        raise ValueError("Неизвестный отчёт.")
    return attachment(out.getvalue().encode("utf-8-sig"), "text/csv", f"{kind}.csv")


# --------------------------------------------------------------------------
# static files and shutdown


@app.post("/api/shutdown")
def shutdown():
    callback = getattr(app.state, "shutdown", None)
    if not callback:
        raise ValueError("Остановите приложение через его окно.")
    threading.Timer(0.4, callback).start()
    return {"ok": True}


from .assistant_api import router as assistant_router
app.include_router(assistant_router)
from .voice_api import router as voice_router
app.include_router(voice_router)
from .extra_api import router as extras_router
app.include_router(extras_router)

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html",media_type='text/html')


@app.get("/favicon.ico")
def favicon():
    return FileResponse(ROOT / "static" / "favicon.ico")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")
