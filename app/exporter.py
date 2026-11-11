"""Export the day into the school's own DOCX templates.

Only ``word/document.xml`` is edited inside a copy of the original package, so
page size, margins, borders, column widths, fonts and every other part of the
document stay exactly as the school made them.  Changed cells are marked with
red text and a pale red fill; the day heading keeps its original formatting.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree as E

from .model import (
    DAY_UPPER,
    base_for_day,
    cell_signature,
    diff_lessons,
    lessons_for_day,
    parse_date,
    unavailable,
)

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = NS["w"]
TEMPLATES = Path(__file__).with_name("templates")
RED = "C00000"
RED_FILL = "F7DAD2"


def q(name: str) -> str:
    return f"{{{W}}}{name}"


def _text(node) -> str:
    return "".join(node.xpath(".//w:t/text()", namespaces=NS)).strip()


def _norm(value: str) -> str:
    return re.sub(r"[\s.\u00a0]", "", str(value or "")).lower().replace("ё", "е")


def template_path(weekday: int, audience: str) -> Path:
    """The school supplied Monday and Tuesday; other days reuse Monday's layout."""
    name = "ВТОРНИК" if weekday == 1 else "ПОНЕДЕЛЬНИК"
    suffix = "УЧИТЕЛЬ" if audience == "teachers" else "УЧЕНИК"
    import os
    filename = f"{name} {suffix}.docx"
    data = os.environ.get('SCHEDULE_DATA')
    private = Path(data)/'templates'/filename if data else None
    return private if private and private.is_file() else TEMPLATES/filename


# --------------------------------------------------------------------------
# XML cell editing


def _run_props(cell):
    run = cell.find(".//w:r", NS)
    if run is not None:
        props = run.find("w:rPr", NS)
        if props is not None:
            return deepcopy(props)
    paragraph = cell.find("w:p", NS)
    if paragraph is not None:
        props = paragraph.find("w:pPr/w:rPr", NS)
        if props is not None:
            return deepcopy(props)
    return None


def _shade(cell, fill: str | None) -> None:
    props = cell.find("w:tcPr", NS)
    if props is None:
        props = E.SubElement(cell, q("tcPr"))
    old = props.find("w:shd", NS)
    if fill is None:
        if old is not None:
            props.remove(old)
        return
    if old is None:
        old = E.Element(q("shd"))
        after = {q(tag) for tag in ("noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark")}
        position = len(props)
        for index, child in enumerate(props):
            if child.tag in after:
                position = index
                break
        props.insert(position, old)
    old.set(q("val"), "clear")
    old.set(q("color"), "auto")
    old.set(q("fill"), fill)


def _set_run_color(props, value: str = RED) -> None:
    color = props.find("w:color", NS)
    if color is None:
        color = E.Element(q("color"))
        after = {q(tag) for tag in ("spacing", "w", "kern", "position", "sz", "szCs", "highlight",
                                    "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl",
                                    "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath")}
        position = len(props)
        for index, child in enumerate(props):
            if child.tag in after:
                position = index
                break
        props.insert(position, color)
    color.set(q("val"), value)


def _center_paragraph(paragraph) -> None:
    props = paragraph.find("w:pPr", NS)
    if props is None:
        props = E.Element(q("pPr"))
        paragraph.insert(0, props)
    justification = props.find("w:jc", NS)
    if justification is None:
        justification = E.Element(q("jc"))
        before = {q(tag) for tag in ("textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
                                     "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")}
        position = len(props)
        for index, child in enumerate(props):
            if child.tag in before:
                position = index
                break
        props.insert(position, justification)
    justification.set(q("val"), "center")


def change_cell(cell, text: str, red: bool = False, center: bool = False) -> None:
    """Replace the cell text while keeping its paragraph/run formatting."""
    desired = str(text or "")
    existing = _text(cell)
    if existing == desired.strip() and not red and not center:
        return
    prototype = _run_props(cell)
    paragraphs = cell.findall("w:p", NS)
    if not paragraphs:
        paragraphs = [E.SubElement(cell, q("p"))]
    first = paragraphs[0]
    for extra in paragraphs[1:]:
        cell.remove(extra)
    for child in list(first):
        if child.tag != q("pPr"):
            first.remove(child)
    if center:
        _center_paragraph(first)
        tcpr=cell.find('w:tcPr',NS)
        if tcpr is None:tcpr=E.Element(q('tcPr'));cell.insert(0,tcpr)
        valign=tcpr.find('w:vAlign',NS)
        if valign is None:
            valign=E.Element(q('vAlign'))
            before={q(t) for t in ('hideMark','headers','cellIns','cellDel','cellMerge','tcPrChange')}
            position=next((i for i,c in enumerate(tcpr) if c.tag in before),len(tcpr))
            tcpr.insert(position,valign)
        valign.set(q('val'),'center')
        ppr=first.find('w:pPr',NS)
        spacing=ppr.find('w:spacing',NS)
        if spacing is None:
            spacing=E.Element(q('spacing'))
            following={q(t) for t in ('ind','contextualSpacing','mirrorIndents','suppressOverlap','jc','textDirection','textAlignment','textboxTightWrap','outlineLvl','divId','cnfStyle','rPr','sectPr','pPrChange')}
            position=next((i for i,c in enumerate(ppr) if c.tag in following),len(ppr))
            ppr.insert(position,spacing)
        spacing.set(q('before'),'0');spacing.set(q('after'),'0')
        spacing.set(q('line'),'240');spacing.set(q('lineRule'),'auto')
    run = E.SubElement(first, q("r"))
    props = deepcopy(prototype) if prototype is not None else E.Element(q("rPr"))
    if red:
        _set_run_color(props)
    if len(props):
        run.append(props)
    lines = desired.split("\n")
    for index, line in enumerate(lines):
        if index:
            E.SubElement(run, q("br"))
        node = E.SubElement(run, q("t"))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = line
    if red:
        _shade(cell, RED_FILL)


def _set_paragraph_text(paragraph, text: str, red: bool) -> None:
    runs = paragraph.findall(".//w:r", NS)
    if not runs:
        run = E.SubElement(paragraph, q("r"))
        runs = [run]
    first = runs[0]
    for extra in runs[1:]:
        parent = extra.getparent()
        if parent is not None:
            parent.remove(extra)
    texts = first.findall("w:t", NS)
    for extra in texts[1:]:
        first.remove(extra)
    if not texts:
        node = E.SubElement(first, q("t"))
    else:
        node = texts[0]
    node.text = text
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    if red:
        props = first.find("w:rPr", NS)
        if props is None:
            props = E.SubElement(first, q("rPr"))
        _set_run_color(props)


# --------------------------------------------------------------------------
# rendering helpers


def room_ranges(names) -> str:
    """Compact list of free classrooms: 212 213 304–306."""
    numbers = []
    for name in names:
        try:
            numbers.append(int(str(name).strip()))
        except ValueError:
            continue
    numbers = sorted(set(numbers))
    if not numbers:
        return ""
    groups: list[list[int]] = []
    for number in numbers:
        if groups and number == groups[-1][-1] + 1:
            groups[-1].append(number)
        else:
            groups.append([number])
    parts = []
    for group in groups:
        if len(group) == 1:
            parts.append(str(group[0]))
        elif len(group) == 2:
            parts.extend(str(x) for x in group)
        else:
            parts.append(f"{group[0]}–{group[-1]}")
    return " ".join(parts)


def _group_label(lesson, class_id, classes) -> str:
    from .technology import groups_for,group_role
    groups=groups_for(lesson,class_id)
    if set(groups)=={0,1}:return ''
    cls=classes.get(class_id,{})
    names=cls.get('groupNames',['Подгруппа 1','Подгруппа 2'])
    labels=[]
    for group in groups:
        role=group_role({'classes':list(classes.values())},class_id,group)
        labels.append('дев.' if role=='girls' else 'мальч.' if role=='boys' else
                      (names[group] if group<len(names) and names[group] not in ('Подгруппа 1','Подгруппа 2') else f'гр. {group+1}'))
    return ', '.join(labels)


def _pupil_text(lessons, subjects, rooms, classes=None, class_id=None) -> str:
    lines = []
    for lesson in lessons:
        short = subjects[lesson["subjectId"]].get("short") or subjects[lesson["subjectId"]]["name"]
        room = "/".join(rooms[r]["name"] for r in lesson.get("roomIds", []))
        label=_group_label(lesson,class_id,classes) if classes and class_id else ''
        lines.append((short + (' ('+label+')' if label else '') + (" " + room if room else "")).strip())
    return "\n".join(lines)


def _teacher_text(lessons, teacher_id, classes, subjects, rooms) -> str:
    lines = []
    for lesson in lessons:
        names = "/".join(classes[c]["name"]+(' ('+_group_label(lesson,c,classes)+')' if _group_label(lesson,c,classes) else '')
                         for c in lesson.get("classIds", []))
        code = subjects[lesson["subjectId"]].get("teacherCode") or ""
        chosen = list(lesson.get("roomIds", []))
        if len(chosen) == len(lesson.get("teacherIds", [])) and len(chosen) > 1:
            try:
                chosen = [chosen[lesson["teacherIds"].index(teacher_id)]]
            except ValueError:
                pass
        room = "/".join(rooms[r]["name"] for r in chosen)
        lines.append(" ".join(x for x in (names, code, room) if x))
    return "\n".join(lines)


def _lessons_at(lessons, field, ident, period):
    return [l for l in lessons if ident in l.get(field, []) and int(l["period"]) == int(period)]


# --------------------------------------------------------------------------
# teacher table


def _teacher_rows(table, state, current, base, update_names: bool = True):
    rows = table.findall("w:tr", NS)
    teachers = state["teachers"]
    index_t = {t["id"]: t for t in teachers}
    by_name = {_norm(t["name"]): t["id"] for t in teachers}
    order = {t["id"]: i for i, t in enumerate(teachers)}
    header = rows[0]
    body = rows[1:-1]
    free_row = rows[-1]

    assigned: dict[int, str] = {}
    spare: list[int] = []
    for index, row in enumerate(body):
        cells = row.findall("w:tc", NS)
        name = _text(cells[0])
        tid = by_name.get(_norm(name))
        if tid:
            assigned[index] = tid
        else:
            spare.append(index)
    used = set(assigned.values())
    missing = [t for t in teachers if t["id"] not in used]
    if missing and not update_names:
        names = ", ".join(t["name"] for t in missing)
        raise ValueError("В шаблоне учителей нет строк для: " + names +
                         ". Включите обновление фамилий или выберите другой шаблон.")
    if len(missing) > len(spare):
        extra = ", ".join(t["name"] for t in missing[len(spare):])
        raise ValueError("В шаблоне учителей не хватает строк для: " + extra)
    if update_names:
        for index, teacher in zip(spare, missing):
            assigned[index] = teacher["id"]

    changed_day = bool(diff_lessons(current, base))
    for index, row in enumerate(body):
        cells = row.findall("w:tc", NS)
        tid = assigned.get(index)
        if not tid:
            change_cell(cells[0], "")
            for cell in cells[1:]:
                change_cell(cell, "")
            continue
        teacher = index_t[tid]
        if _norm(_text(cells[0])) != _norm(teacher["name"]):
            change_cell(cells[0], teacher["name"])
        for period, cell in enumerate(cells[1:], 1):
            now = _lessons_at(current, "teacherIds", tid, period)
            before = _lessons_at(base, "teacherIds", tid, period)
            red = cell_signature(now) != cell_signature(before)
            text = _teacher_text(now, tid, {c["id"]: c for c in state["classes"]},
                                 {s["id"]: s for s in state["subjects"]},
                                 {r["id"]: r for r in state["rooms"]})
            if not text and red:
                text = "—"
            change_cell(cell, text, red and state.get('_export_highlight',True), center=(text == "—"))
    # Free classrooms only for the lessons that actually exist (1..6 by default).
    free_cells = free_row.findall("w:tc", NS)
    last_period = min(6, int(state["school"].get("freeRoomLastPeriod", 6)))
    weekday = parse_date(state["_export_day"]).weekday() if state.get("_export_day") else None
    for period, cell in enumerate(free_cells[1:], 1):
        if period > last_period:
            change_cell(cell, "")
            continue
        used_rooms = {r for l in current if int(l["period"]) == period for r in l.get("roomIds", [])}
        rooms = []
        for room in state["rooms"]:
            if room["id"] in used_rooms:
                continue
            if weekday is not None and unavailable(room, weekday, period):
                continue
            from .commitments import room_busy
            if state.get('_export_day') and room_busy(state,room['id'],state['_export_day'],period):
                continue
            if not str(room["name"]).strip().isdigit():
                continue
            rooms.append(room["name"])
        change_cell(cell, room_ranges(rooms))
    _set_paragraph_text(header.findall("w:tc", NS)[0].find("w:p", NS), DAY_UPPER[parse_date(state["_export_day"]).weekday()], False)


# --------------------------------------------------------------------------
# student table


def _find_sections(table,named=None):
    sections=[];section=None
    for row in table.findall('w:tr',NS):
        texts=[_text(c) for c in row.findall('w:tc',NS)]
        if texts and texts[0]=='№':
            section={'headers':texts[1:],'classes':[named.get(_norm(n)) if named is not None else n for n in texts[1:]],'rows':[]}
            sections.append(section)
        elif section is not None and texts and texts[0].isdigit():
            section['rows'].append((int(texts[0]),row))
    return sections


def _check_template(table,state,current,audience):
    if audience=='teachers':
        if len(table.findall('w:tr',NS))<3:raise ValueError('В шаблоне учителей не найдены строки расписания.')
        return
    named={_norm(c['name']):c['id'] for c in state['classes']}
    sections=_find_sections(table,named)
    represented={cid for section in sections if section['rows'] for cid in section['classes'] if cid}
    missing={cid for lesson in current for cid in lesson['classIds']}-represented
    if missing:
        names={c['id']:c['name'] for c in state['classes']}
        raise ValueError('В ученическом шаблоне не найдены классы: '+', '.join(names[c] for c in sorted(missing))+'. Выберите подходящий шаблон.')


def _student_table(table, state, current, base):
    # A necessary seventh period, or an explicit eighth, can need extra rows
    # in a younger-class section. Clone its own last row so widths and borders
    # remain the school's; ordinary documents keep the exact original table.
    from copy import deepcopy
    extended={c for l in current if l['period']>=7 for c in l['classIds']}
    named={_norm(c['name']):c['id'] for c in state['classes']}
    sections=_find_sections(table,named)
    for section in sections:
        affected=set(section['classes'])&extended
        if not affected or not section['rows']:continue
        maximum=max((l['period'] for l in current if affected.intersection(l['classIds'])),default=0)
        last,last_row=max(section['rows'],key=lambda pair:pair[0])
        position=table.index(last_row)+1
        for period in range(last+1,maximum+1):
            extra=deepcopy(last_row)
            for i,cell in enumerate(extra.findall('w:tc',NS)):change_cell(cell,str(period) if i==0 else '')
            table.insert(position,extra);position+=1
    classes = {c["id"]: c for c in state["classes"]}
    by_name = {_norm(c["name"]): c["id"] for c in classes.values()}
    subjects = {s["id"]: s for s in state["subjects"]}
    rooms = {r["id"]: r for r in state["rooms"]}
    changed_day = bool(diff_lessons(current, base))
    represented: set[tuple[str, int]] = set()
    headers: list[str] = []
    for row in table.findall("w:tr", NS):
        cells = row.findall("w:tc", NS)
        texts = [_text(c) for c in cells]
        if texts[0] == "№":
            headers = texts
            continue
        if not texts[0].isdigit():
            continue
        period = int(texts[0])
        for column, name in enumerate(headers[1:], 1):
            if column >= len(cells):
                continue
            if name.strip().upper() == "ЗВОНКИ":
                bells = state["school"]["bells"]
                if period <= len(bells):
                    change_cell(cells[column], bells[period - 1].replace("–", "-"))
                continue
            cid = by_name.get(_norm(name))
            if not cid:
                continue
            now = _lessons_at(current, "classIds", cid, period)
            before = _lessons_at(base, "classIds", cid, period)
            red = cell_signature(now) != cell_signature(before)
            text = _pupil_text(now, subjects, rooms, classes, cid)
            if not text and red:
                text = "—"
            change_cell(cells[column], text, red and state.get('_export_highlight',True), center=(text == "—"))
            represented.add((cid, period))
    missing = []
    for lesson in current:
        for cid in lesson.get("classIds", []):
            if (cid, int(lesson["period"])) not in represented:
                missing.append(f"{classes[cid]['name']}, урок {lesson['period']}")
    if missing:
        raise ValueError("В ученическом шаблоне нет строк для: " + ", ".join(sorted(set(missing))) +
                         ". Занятия не будут скрыты — выберите другой шаблон.")
    # Day title above the table.
    for paragraph in table.getparent().findall("w:p", NS):
        text = _text(paragraph)
        if text.strip() in ("ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА"):
            _set_paragraph_text(paragraph, DAY_UPPER[parse_date(state["_export_day"]).weekday()], False)


# --------------------------------------------------------------------------
# public API


def export_docx(state: dict, day: str, audience: str, update_names: bool = True,mode: str = 'changes') -> bytes:
    if mode not in ('changes','clean','base'):raise ValueError('Неизвестный вариант документа.')
    if audience not in ("students", "teachers"):
        raise ValueError("Неизвестный вид экспорта.")
    weekday = parse_date(day).weekday()
    if weekday > 4:
        raise ValueError("Экспорт доступен для понедельника–пятницы.")
    path = template_path(weekday, audience)
    if path.is_file():
        template = path
    else:
        from .report_template import generic_template
        template = BytesIO(generic_template(state, audience))
    with ZipFile(template) as source:
        root = E.fromstring(source.read("word/document.xml"))
        table = root.find(".//w:tbl", NS)
        if table is None:
            raise ValueError("В шаблоне не найдена таблица.")
        current = lessons_for_day(state, day)
        base = base_for_day(state, day)
        if mode=='base':
            current=deepcopy([l for l in state['baseLessons'] if l['day']==weekday])
            base=deepcopy(current)
        _check_template(table,state,current,audience)
        state = dict(state)
        state["_export_day"] = day
        state['_export_highlight']=mode=='changes'
        if audience == "teachers":
            _teacher_rows(table, state, current, base, update_names)
        else:
            _student_table(table, state, current, base)
        payload = E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as target:
            for item in source.infolist():
                target.writestr(item, payload if item.filename == "word/document.xml" else source.read(item.filename))
    return stream.getvalue()


@lru_cache(maxsize=5)
def template_capacity(weekday: int) -> dict[str, int]:
    """How many lessons each class has in the supplied student template."""
    path=template_path(weekday, "students")
    if not path.is_file():return {}
    with ZipFile(path) as source:
        root = E.fromstring(source.read("word/document.xml"))
    table = root.find(".//w:tbl", NS)
    caps: dict[str, int] = {}
    if table is None:raise ValueError('В шаблоне не найдена таблица.')
    for section in _find_sections(table):
        for period,row in section['rows']:
            count=len(row.findall('w:tc',NS))
            for column,name in enumerate(section['headers'],1):
                if column<count and name.strip().upper()!='ЗВОНКИ':caps[name]=max(caps.get(name,0),period)
    return caps
