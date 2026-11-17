"""Compact timetable labels, independent of pupils' names and report layout."""
from collections import Counter,defaultdict
import re


def individual_labels(state):
    learners=state.get('individualLearners',[])
    classes={c['id']:c['name'] for c in state['classes']}
    counts=Counter(l['classId'] for l in learners);sequence=defaultdict(int)
    result={}
    for learner in learners:
        cid=learner['classId'];sequence[cid]+=1
        prefix='инд'+str(sequence[cid]) if counts[cid]>1 else 'инд'
        result[learner['id']]=prefix+' '+classes.get(cid,'—')
    return result


def room_label(name):
    text=str(name or '').strip()
    if 'логоп' in text.casefold():return 'лог.'
    if 'лаб' in text.casefold():
        number=re.search(r'\d+',text)
        if number:return number[0]+'л'
    return re.sub(r'^каб(?:инет)?\.?\s*','',text,flags=re.I)


def subject_code(subject):
    aliases={'Математика':'м','Алгебра':'а','Геометрия':'г','Физика':'ф','География':'гео',
        'Английский язык':'англ','Иностранный язык':'англ','Химия':'х','История':'и',
        'Музыка':'муз','Биология':'б','Информатика':'инф','Русский язык':'р',
        'Литература':'л','Родной язык':'ря','Обществознание':'о','Физическая культура':'физ',
        'Труд (технол.)':'т','Труд (технология)':'т','Технология':'т',
        'Вероятность и стат.':'в','Вероятность и статистика':'в'}
    code=subject.get('teacherCode') or aliases.get(subject.get('name')) or subject.get('short','')
    if code.upper() in ('ОБЗР','ОБЖ'):return 'об'
    return code if len(code)<=4 else aliases.get(subject.get('name'),code[:3]+'.')
