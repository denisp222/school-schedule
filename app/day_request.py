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
_INDIVIDUAL = re.compile(r'\b(?:индивидуальн\w*|инд[1-9]?(?=\s|\.|$))')
_GRADE = re.compile(r'\b(1[01]|[1-9])(?:\s*-\s?(?:х|е|ых|й))?\s+класс\w*|\b(пят\w*|шест\w*|седьм\w*|восьм\w*|девят\w*|десят\w*)\s+класс\w*')
_AFTER = re.compile(r'\bпосле\s+(' + _LESSON_NUMBER + r')\s+урок\w*')


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


def school_day_actions(state,day,messages):
    """Resolve the common explicit formulations against local records."""
    from .display_labels import individual_labels
    labels=individual_labels(state)
    learners=state.get('individualLearners',[])
    lessons=lessons_for_day(state,day)
    pupil_actions,teacher_actions,teacher_windows,departures,pupil_questions={},{},{},{},{}
    pupil_scopes=set()
    for message in messages:
        referenced_teacher=None
        for clause in _clauses(message):
            if re.search(r'\b(?:если|можно\s+ли|по\s+возможности)\b',clause):continue
            refs=mentioned_entities(state,clause)
            if _INDIVIDUAL.search(clause):
                choices=[r for r in learners if r['classId'] in refs['classes']]
                candidates={r['id'] for r in choices}
                named=[r for r in learners if (stem:=surname_stem(_normalize(r['name']).split()[0])) and len(stem)>=3
                       and re.search(r'(?<!\w)'+re.escape(stem)+r'[а-я]*(?!\w)',clause)]
                number=re.search(r'\b(?:инд|индивидуальн\w*)\s*(?:№\s*)?([1-9])(?!\w)',clause)
                if named:choices=[r for r in named if not refs['classes'] or r['classId'] in refs['classes']]
                if number:choices=[r for r in choices if labels[r['id']].startswith('инд'+number[1]+' ')]
                cancel=_CANCEL.search(clause) or re.search(r'\b(?:не\s+будет|нет\s+инд|отсутств\w*)\b',clause)
                keep=re.search(r'\b(?:не\s+(?:отмен|сним|убир)\w*|остав\w*|будет\s+присутств\w*)\b',clause)
                if not (cancel or keep) or _periods(clause) or _RANGE.search(clause):continue
                pupil_scopes.update(candidates or {r['id'] for r in choices})
                key=frozenset(refs['classes'])
                if len(choices)==1:
                    ident=choices[0]['id']
                    pupil_questions.pop(key,None)
                    pupil_actions[ident]=None if keep else {'type':'cancel_individual','learnerId':ident}
                elif not keep and (choices or key):
                    pupil_questions[key]=('Уточните, кого не будет: '+', '.join(labels[r['id']] for r in choices)+'.'
                                          if choices else 'Проверьте класс и номер индивидуального ученика.')
                continue
            if len(refs['teachers'])==1:referenced_teacher=next(iter(refs['teachers']))
            elif refs['teachers'] or not re.search(r'\b(?:ей|ему|у\s+нее|у\s+него)\b',clause):continue
            if referenced_teacher is None:continue
            teacher=referenced_teacher
            grade_matches=_GRADE.findall(clause)
            grade_stems=('пят','шест','седьм','восьм','девят','десят')
            grades={int(number) if number else next(g for g,stem in enumerate(grade_stems,5) if word.startswith(stem))
                    for number,word in grade_matches}
            classes=refs['classes'] | {r['id'] for r in state['classes']
                if (match:=re.match(r'\d+',r['name'])) and int(match[0]) in grades}
            bounds=_RANGE.search(clause)
            keeping=re.search(r'постав|остав|перенес|перенос|провод',clause)
            only_classes=bool(re.search(r'\bтолько\s+(?:\d+\s*[а-яa-z](?!\w)|\d+\s+класс|пят\w*\s+класс|шест\w*\s+класс|седьм\w*\s+класс|восьм\w*\s+класс|девят\w*\s+класс|десят\w*\s+класс)',clause))
            cancel_others=only_classes or ('остальн' in clause and bool(_CANCEL.search(clause)))
            negated=re.search(r'\bне\s+(?:отмен|сним|убир)\w*',clause)
            if (classes and bounds and (keeping or only_classes)
                    and (not _CANCEL.search(clause) or keeping and 'остальн' in clause)):
                first,last=_lesson_number(bounds[1]),_lesson_number(bounds[3])
                if first<=last and (bounds[2]!='и' or last==first+1):
                    teacher_windows[teacher]={'type':'teacher_lesson_window','teacherId':teacher,
                                              'classIds':sorted(classes),'first':first,'last':last,
                                              'cancelOtherClasses':cancel_others}
                    if cancel_others:teacher_actions.pop(teacher,None)
            elif not classes and 'остальн' in clause and _CANCEL.search(clause) and teacher in teacher_windows:
                teacher_windows[teacher]['cancelOtherClasses']=not bool(negated)
            elif classes and _CANCEL.search(clause) and not negated:
                # Interpret grade-wide cancellation only when the request says
                # which grade to remove, rather than which grade to keep.
                if grades and not bounds and not keeping:
                    if teacher in teacher_windows:teacher_windows[teacher]['cancelOtherClasses']=False
                    teacher_actions[teacher]=[{'type':'cancel_lesson','lessonId':l['id']} for l in lessons
                        if l['teacherIds']==[teacher] and set(l['classIds'])<=classes and not l.get('classHour')]
            after=_AFTER.search(clause)
            if after and re.search(r'уход\w*|уйд\w*|не\s+(?:будет|сможет|работа\w*)',clause):
                period=_lesson_number(after[1])
                if period<8:
                    departures[teacher]={'type':'teacher_absence','teacherId':teacher,'first':period+1,'last':8}
            if re.search(r'\b(?:отмен\w*\s+отсутствие|будет\s+(?:работать|весь\s+день))\b',clause) and not _AFTER.search(clause):
                departures.pop(teacher,None)
    return ([r for r in pupil_actions.values() if r]+[r for rows in teacher_actions.values() for r in rows]
            +list(teacher_windows.values())+list(departures.values()),
            list(pupil_questions.values()),set(teacher_actions)|teacher_windows.keys(),pupil_scopes)


def verified_actions(state, day, messages, *, school_actions=None):
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
    if school_actions is None:school_actions=school_day_actions(state,day,messages)[0]
    return [*joins, *cancels.values(), *absences.values(), *school_actions], retired


def ground_reply(raw, state, day, messages):
    if not isinstance(raw, dict) or raw.get('date')!=day:return raw
    if any(not isinstance(raw.get(key), list) for key in ('actions','questions','unsupported')):return raw
    explicit,pupil_questions,teacher_scopes,pupil_scopes=school_day_actions(state,day,messages)
    actions, retired = verified_actions(state, day, messages,school_actions=explicit)
    if not (actions or pupil_questions or pupil_scopes or teacher_scopes):return raw
    lessons = lessons_for_day(state, day)
    sources = sources_for(lessons)
    subjects = {row['id']:row for row in state['subjects']}
    joins = [row for row in actions if row['type']=='join_lessons']
    joined_ids = {ident for row in joins for ident in row['lessonIds']}
    cancelled_ids = {row['lessonId'] for row in actions if row['type']=='cancel_lesson'}
    absence_ids = {row['teacherId'] for row in actions if row['type']=='teacher_absence'}
    learners = {row['learnerId'] for row in actions if row['type']=='cancel_individual'}
    windows = {row['teacherId']:row for row in actions if row['type']=='teacher_lesson_window'}
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
            lesson=sources.get(row['lessonId'])
            redundant=kind=='cancel_lesson' and lesson and any(
                t in windows and windows[t]['cancelOtherClasses'] and not set(lesson['classIds']).intersection(windows[t]['classIds'])
                for t in lesson['teacherIds'])
            mistaken_group=kind=='cancel_lesson' and lesson and (pupil_scopes or pupil_questions) and any(
                l['classId'] in lesson['classIds'] for l in state.get('individualLearners',[])
                if l['id'] in pupil_scopes or pupil_questions)
            if mistaken_group:
                mistaken_group=not any(
                    not _INDIVIDUAL.search(clause) and _CANCEL.search(clause)
                    and (set(lesson['classIds'])<=refs['classes'] or lesson['subjectId'] in refs['subjects'] and not refs['classes'])
                    for message in messages for clause in _clauses(message)
                    if (refs:=mentioned_entities(state,clause)))
            return row['lessonId'] in joined_ids or row['lessonId'] in cancelled_ids or redundant or mistaken_group
        if kind=='cancel_individual':return row.get('learnerId') in pupil_scopes or bool(pupil_questions)
        if kind=='teacher_lesson_window':return row.get('teacherId') in teacher_scopes
        return kind=='teacher_absence' and isinstance(row.get('teacherId'), str) and row['teacherId'] in absence_ids

    def superseded(value):
        if not isinstance(value, str):return False
        text = _normalize(value)
        refs = mentioned_entities(state, text)['classes']
        relevant_joint = any(refs <= classes for classes in joint_classes) if refs else bool(joint_classes) and _ROV.search(text)
        if re.search(r'вместим|вмеща|кабинет\w*\s+занят|нов\w*\s+групп|учебн\w*\s+план',text):return False
        if (learners or pupil_questions) and _INDIVIDUAL.search(text) and (pupil_questions or re.search(r'отмен|нет|не\s+поддерж|не\s+найд|нельзя',text)):
            return True
        if windows.keys() & mentioned_entities(state,text)['teachers'] and re.search(r'правил|услови|класс',text) and _RANGE.search(text):
            return True
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
    result['questions'].extend(q for q in pupil_questions if q not in result['questions'])
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
