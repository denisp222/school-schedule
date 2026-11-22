"""Resolve explicit parts of a daily request against the current timetable."""
import re
from copy import deepcopy

from .joint_lessons import sources_for
from .model import lessons_for_day, parse_date
from .rules import is_rov, surname_stem

_ROV = re.compile(r'разговор\w*\s+о\s+важн|\bров\b')
_PE = re.compile(r'\bфиз\s*-?\s*(?:ическ\w*\s+культур\w*|культур\w*|р(?:а|у|ы|ой)?)(?!\w)')
_JOINT = re.compile(r'совмест|вместе|объедин|общ\w*\s+урок')
_CANCEL = re.compile(r'\b(?:снять|сними|снима\w*|сняти\w*|отмен\w*|убра\w*|убер\w*|пропуст\w*|не\s+став\w*)\b')
_ORDINALS = ('перв', 'втор', 'трет', 'четверт', 'пят', 'шест', 'седьм', 'восьм')
_NUMBER = r'[1-8](?:\s*-?\s*(?:[йм]|му|го|ом|ым))?'
_LESSON_NUMBER = _NUMBER+'|'+'|'.join(stem+r'\w*' for stem in _ORDINALS)
_PERIOD = re.compile(r'(?<!\w)(' + _LESSON_NUMBER + r')\s+урок\w*')
_RANGE = re.compile(r'(?<!\w)(' + _LESSON_NUMBER + r')\s*([-–—]|\bи\b|\bпо\b)\s*(' + _LESSON_NUMBER + r')(?!\w)')
_FLEXIBLE = re.compile(r'позже|не\s+(?:только\s+|обязательно\s+)?перв\w*|на\s+люб\w*\s+урок')


def _normalize(text):
    return text.lower().replace('ё', 'е')


def mentioned_entities(state, request_text):
    def normalized(value):
        return ' '.join(re.findall(r'\w+', _normalize(value)))

    text = normalized(request_text)

    def mentioned(value):
        return bool(value and re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)', text))

    def class_mentioned(name):
        value = normalized(name)
        match = re.fullmatch(r'(\d+)\s*([а-яa-z])', value)
        if not match:return mentioned(value)
        grade, letter = match.groups()
        latin = {'а':'a','в':'b','г':'g','д':'d','е':'e','к':'k','м':'m','н':'h','о':'o','р':'p','с':'c','т':'t','у':'y','х':'x'}
        letters = letter+latin.get(letter, letter)
        return bool(re.search(r'(?<!\w)'+grade+r'\s*['+re.escape(letters)+r'](?!\w)', text))

    def room_mentioned(name):
        value = normalized(name)
        return (mentioned(value) or value=='актовый зал'
                and bool(re.search(r'\bактов\w*\s+зал\w*\b', text)))

    exact = {r['id'] for r in state['teachers'] if mentioned(normalized(r['name']))}
    surnames = {}
    for row in state['teachers']:
        surnames.setdefault(normalized(row['name']).split()[0], []).append(row['id'])
    teachers = set(exact)
    for surname, ids in surnames.items():
        if exact.intersection(ids):continue
        stem = surname_stem(surname)
        if len(stem)>=3 and re.search(r'(?<!\w)'+re.escape(stem)+r'[а-я]*(?!\w)', text):
            teachers.update(ids)
    return {'classes':{r['id'] for r in state['classes'] if class_mentioned(r['name'])},
            'teachers':teachers,
            'subjects':{r['id'] for r in state['subjects'] if mentioned(normalized(r['name']))},
            'rooms':{r['id'] for r in state['rooms'] if room_mentioned(r['name'])}}


def _clauses(text):
    divider = r'[\n;!?]+|(?<!\b[а-яa-z])\.(?=\s|$)|,\s*(?=(?:снять\b|отмен\w*|убра\w*|не\s+будет\b|\d+\s*[а-яa-z]\s+(?:физ|разговор)))'
    return [part.strip() for part in re.split(divider, _normalize(text)) if part.strip()]


def _lesson_number(word):
    if word[0].isdigit():return int(word[0])
    return next(i for i, stem in enumerate(_ORDINALS, 1) if word.startswith(stem))


def _periods(text):
    return {_lesson_number(word) for word in _PERIOD.findall(text)}


def requests_rov_time(state, text, class_ids, period):
    """A different lesson's number does not authorize moving this subject."""
    for clause in reversed(_clauses(text)):
        if not _ROV.search(clause) and not _JOINT.search(clause):continue
        classes = mentioned_entities(state, clause)['classes']
        if classes and not classes.intersection(class_ids):continue
        periods = _periods(clause)
        if periods or _FLEXIBLE.search(clause):
            if re.search(r'\bне\s+(?:перенос|став|провод)\w*',clause):return False
            return periods == {period} or not periods and bool(_FLEXIBLE.search(clause))
    return False


def _joint(clause, refs, sources, subjects):
    if not (_ROV.search(clause) and _JOINT.search(clause) and len(refs['classes']) >= 2):return None
    if re.search(r'\bне\s+(?:\w+\s+){0,2}(?:совмест|объедин|вместе|провест|провед|взя)', clause):return None
    if _CANCEL.search(clause) or re.search(r'\b(?:если|или|кроме)\b',clause):return None
    rows = [l for l in sources.values() if set(l['classIds']) <= refs['classes'] and len(l['teacherIds'])==1
            and 'groupIndex' not in l and is_rov(subjects[l['subjectId']])]
    classes = [c for l in rows for c in l['classIds']]
    if len(rows)<2 or len(classes)!=len(set(classes)) or set(classes)!=refs['classes']:
        return None
    if len({l['subjectId'] for l in rows}) != 1:return None
    hosts = [l for l in rows if l['teacherIds'][0] in refs['teachers']]
    if len(hosts)!=1 or len(refs['teachers'])!=1 or len(refs['rooms'])>1:return None
    if not refs['rooms'] and re.search(r'\bактов\w*\s+зал\w*|\bкабинет\w*\s+\d', clause):return None
    periods = _periods(clause)
    if len(periods)>1 or not periods and _FLEXIBLE.search(clause):return None
    return {'type':'join_lessons','lessonIds':sorted(l['id'] for l in rows),
            'teacherId':hosts[0]['teacherIds'][0],'period':next(iter(periods), hosts[0]['period']),
            'roomId':next(iter(refs['rooms']), None)}


def _cancel(clause, refs, current, subjects):
    matches = [(subject,mention) for subject in (_ROV,_PE) if (mention:=subject.search(clause))]
    if not refs['classes'] or len(matches)!=1:return []
    subject,mention = matches[0]
    if not _CANCEL.search(clause) and not re.search(r'\bбез\s*«?$',clause[:mention.start()]):return []
    if re.search(r'\b(?:если|вместо|замен\w*|можно\s+ли|по\s+возможности|не\s+(?:отмен|сним|убир|убра|пропус))', clause):
        return []
    periods = _periods(clause)
    return [{'type':'cancel_lesson','lessonId':l['id']} for l in current
            if set(l['classIds']) <= refs['classes'] and subject.search(_normalize(subjects[l['subjectId']]['name']))
            and (not periods or l['period'] in periods)]


def _absence(clause, refs):
    if refs['classes'] or len(refs['teachers'])!=1:return None
    bounds = _RANGE.search(clause)
    unavailable = re.search(r'\b(?:отсутств\w*|не\s+буд(?:ет|ут)|не\s+смож\w*)\b', clause)
    if re.search(r'\b(?:если|не\s+(?:будет\s+)?отсутств\w*|может\s+быть)\b', clause):return None
    if bounds and (unavailable or re.search(r'\bснять\b.+урок', clause)):
        first, last = _lesson_number(bounds[1]), _lesson_number(bounds[3])
        if first>=last or bounds[2]=='и' and last!=first+1:return None
    elif unavailable and re.search(r'\b(?:весь|целый)\s+день\b', clause):
        first, last = 1, 8
    else:return None
    return {'type':'teacher_absence','teacherId':next(iter(refs['teachers'])),'first':first,'last':last}


def verified_actions(state, day, messages):
    current = lessons_for_day(state, day)
    sources = sources_for(current)
    subjects = {s['id']:s for s in state['subjects']}
    joins, retired, cancels, absences = [], [], {}, {}
    for message in messages:
        new_joins, new_cancels = [], {}
        previous = ''
        for clause in _clauses(message):
            refs = mentioned_entities(state, clause)
            if re.search(r'\b(?:верн\w*|остав\w*|не\s+(?:отмен|сним|убир)\w*)\b',clause):
                for lesson in current:
                    name=_normalize(subjects[lesson['subjectId']]['name'])
                    if set(lesson['classIds']) <= refs['classes'] and any(p.search(clause) and p.search(name) for p in (_ROV,_PE)):
                        cancels.pop(lesson['id'],None)
            if re.search(r'\b(?:не\s+(?:будет\s+)?отсутств\w*|будет\s+(?:работать|весь\s+день)|отмен\w*\s+отсутствие)\b',clause):
                if not re.search(r'\bне\s+будет\s+(?:работать|весь\s+день)\b',clause):
                    for teacher in refs['teachers']:absences.pop(teacher,None)
            joint_clause = clause
            if _ROV.search(previous) and _JOINT.search(clause) and 'этот урок' in clause:
                joint_clause = previous+'. '+clause
            joint_refs = refs if joint_clause==clause else mentioned_entities(state, joint_clause)
            join = _joint(joint_clause, joint_refs, sources, subjects)
            if join is None and len(joins)==1 and _JOINT.search(clause) and not _CANCEL.search(clause):
                # A follow-up may only correct the agreed time.
                periods = _periods(clause)
                if (len(periods)==1 and not any(refs[key] for key in ('classes','teachers','rooms'))
                        and not re.search(r'\bне\s+|\bесли\b', clause)):
                    join = {**joins[0],'period':next(iter(periods))}
            if join:new_joins.append(join)
            new_cancels.update((r['lessonId'],r) for r in _cancel(clause, refs, current, subjects))
            absence = _absence(clause, refs)
            if absence:absences[absence['teacherId']] = absence
            previous=clause
        for join in new_joins:
            included = set(join['lessonIds'])
            if included.intersection(new_cancels):continue
            retired.extend(old for old in joins if included.intersection(old['lessonIds']))
            joins = [old for old in joins if not included.intersection(old['lessonIds'])]+[join]
            for ident in included:cancels.pop(ident, None)
        completed = [old for old in joins if new_cancels.keys() & set(old['lessonIds'])]
        retired.extend(completed)
        joins = [old for old in joins if old not in completed]
        cancels.update(new_cancels)
    return [*joins, *cancels.values(), *absences.values()], retired


def ground_reply(raw, state, day, messages):
    if not isinstance(raw, dict) or raw.get('date')!=day:return raw
    if any(not isinstance(raw.get(key), list) for key in ('actions','questions','unsupported')):return raw
    actions, retired = verified_actions(state, day, messages)
    if not actions:return raw
    lessons = lessons_for_day(state, day)
    sources = sources_for(lessons)
    subjects = {row['id']:row for row in state['subjects']}
    joins = [row for row in actions if row['type']=='join_lessons']
    joined_ids = {ident for row in joins for ident in row['lessonIds']}
    cancelled_ids = {row['lessonId'] for row in actions if row['type']=='cancel_lesson'}
    absence_ids = {row['teacherId'] for row in actions if row['type']=='teacher_absence'}
    joint_classes = [{c for ident in row['lessonIds'] for c in sources[ident]['classIds']} for row in joins+retired]
    cancel_classes = {
        pattern:{c for l in lessons if l['id'] in cancelled_ids and pattern.search(_normalize(subjects[l['subjectId']]['name']))
                 for c in l['classIds']}
        for pattern in (_ROV, _PE)
    }

    def replaced(row):
        if not isinstance(row, dict):return False
        kind = row.get('type')
        if kind=='join_lessons' and isinstance(row.get('lessonIds'), list):
            return any(ident in joined_ids or ident in cancelled_ids for ident in row['lessonIds'] if isinstance(ident, str))
        if kind in ('pin_lesson', 'cancel_lesson') and isinstance(row.get('lessonId'), str):
            return row['lessonId'] in joined_ids or row['lessonId'] in cancelled_ids
        return kind=='teacher_absence' and isinstance(row.get('teacherId'), str) and row['teacherId'] in absence_ids

    def superseded(value):
        if not isinstance(value, str):return False
        text = _normalize(value)
        refs = mentioned_entities(state, text)['classes']
        relevant_joint = any(refs <= classes for classes in joint_classes) if refs else bool(joint_classes) and _ROV.search(text)
        if re.search(r'вместим|вмеща|кабинет\w*\s+занят|нов\w*\s+групп|учебн\w*\s+план',text):return False
        if relevant_joint:
            if re.search(r'только\s+перв|перв\w*\s+урок\w*\s+(?:уже\s+)?занят|не\s+преподавател|не\s+ведет|протокол\w*\s+не|двух\s+класс|тр[её]х\s+класс|произвольн\w*\s+замен', text):
                return True
            if (_JOINT.search(text) and 'или' in text and mentioned_entities(state, text)['teachers']
                    and not re.search(r'кабинет|зал|врем|групп|возраст', text)):
                return True
        return bool(refs and any(refs <= classes and pattern.search(text) for pattern, classes in cancel_classes.items())
                    and _CANCEL.search(text))

    result = deepcopy(raw)
    result['actions'] = [row for row in raw['actions'] if row in actions or not replaced(row)]
    result['actions'].extend(row for row in actions if row not in result['actions'])
    for key in ('questions','unsupported'):
        result[key] = [text for text in raw[key] if not superseded(text)]
    if (result['questions']!=raw['questions'] or result['unsupported']!=raw['unsupported']
            or any(row not in raw['actions'] for row in actions)):
        teachers={t['id']:t['name'] for t in state['teachers']}
        classes={c['id']:c['name'] for c in state['classes']}
        rooms={r['id']:r['name'] for r in state['rooms']}
        details = [', '.join(classes[c] for c in sorted({c for ident in row['lessonIds'] for c in sources[ident]['classIds']}))
                   + f" совместно у {teachers[row['teacherId']]} на {row['period']}-м уроке"
                   + (f" ({rooms[row['roomId']]})" if row['roomId'] else '')+'.' for row in joins]
        result['reply'] = ' '.join([*details,'Проверьте условия перед подбором вариантов.'])
    return result
