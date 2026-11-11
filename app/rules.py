"""Shared subject rules; school-specific assignments are stored as IDs."""
import re


def subject_name(subject):
    return str(subject.get('name', '') if isinstance(subject, dict) else subject).lower().replace('ё', 'е')


def is_rov(subject):
    name = subject_name(subject)
    return 'разговор' in name and 'важн' in name


def is_technology(subject):
    name = subject_name(subject)
    return 'труд' in name or 'технол' in name


def surname_stem(name):
    surname = str(name).lower().replace('ё', 'е').split()[0]
    return surname[:-2] if surname.endswith(('ая', 'ий', 'ый')) else surname[:-1] if surname.endswith(('а', 'я')) else surname


def surname_matches(name, text):
    stem = surname_stem(name)
    return len(stem) >= 3 and bool(re.search(r'(?<!\w)' + re.escape(stem) + r'[а-я]*(?!\w)', str(text).lower().replace('ё', 'е')))


def eighth_exception(state):
    school = state.get('school', {})
    if 'eighthPeriodException' in school:
        rule=school['eighthPeriodException']
        if rule is None:return None
        try:
            assert type(rule['day']) is int and 0<=rule['day']<=4 and rule['period']==8
            assert len(rule['classIds'])==len(rule['teacherIds'])==1
            assert set(rule['classIds'])<={r['id'] for r in state['classes']}
            assert set(rule['teacherIds'])<={r['id'] for r in state['teachers']}
            assert rule['subjectId'] in {r['id'] for r in state['subjects']}
        except (KeyError,TypeError,AssertionError):
            raise ValueError('Проверьте исключение восьмого урока: день, класс, учителя и предмет.') from None
        return rule
    # Legacy imports: infer only the unique lesson already present on period 8.
    # Never infer an exception from a surname or assign a new eighth lesson.
    candidates = state.get('baseLessons', []) + state.get('unscheduledLessons', []) + state.get('sourceLessons', [])
    keys = {(l['day'], tuple(l['classIds']), tuple(l['teacherIds']), l['subjectId'])
            for l in candidates if l.get('period') == 8 and len(l.get('teacherIds', [])) == len(l.get('classIds', [])) == 1}
    if len(keys) != 1:
        return None
    day, classes, teachers, subject = keys.pop()
    return {'day': day, 'period': 8, 'classIds': list(classes), 'teacherIds': list(teachers), 'subjectId': subject}


EIGHTH_MESSAGE = 'Восьмой урок требует заранее заданного исключения для этого занятия и даты. Остальные занятия ставятся на уроки 1–7.'
