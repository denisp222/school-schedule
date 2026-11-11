"""Ground only unambiguous absence-only requests; complex speech stays with AI."""
import re
from .model import parse_date
from .rules import surname_stem
from .search_policy import canonical_actions


def parse_absence_request(state,day,message):
    if not isinstance(message,str) or not 1<=len(message)<=600:return None
    text=message.lower().replace('ё','е')
    predicate=r'\b(?:не\s+буд(?:ет|ут)|(?:буд(?:ет|ут)\s+)?(?:отсутствует|отсутствуют|отсутствовать)|заболел[аи]?)\b'
    if len(list(re.finditer(predicate,text)))!=1:return None
    if re.search(r'\bне\s+(?:буд(?:ет|ут)\s+)?отсутств|\bне\b(?!\s+буд(?:ет|ут)\b)',text):return None
    from .ai_planner import mentioned_entities
    ids=mentioned_entities(state,text)['teachers']
    rows=[t for t in state['teachers'] if t['id'] in ids]
    if not rows or len(rows)>24:return None
    stems=[surname_stem(row['name']) for row in rows]
    if len(stems)!=len(set(stems)):return None
    for stem in stems:
        text=re.sub(r'(?<!\w)'+re.escape(stem)+r'[а-я]*(?!\w)(?:\s+[а-я]\s*\.\s*[а-я]\s*\.)?',' ',text)
    selected=parse_date(day)
    dates=list(re.finditer(r'(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4})(?!\d))?(?!\d)',text))
    if len(dates)>1:return None
    for match in dates:
        year=int(match[3]) if match[3] else selected.year
        if year<100:year+=2000
        if (int(match[1]),int(match[2]),year)!=(selected.day,selected.month,selected.year):return None
    text=re.sub(r'(?<!\d)\d{1,2}[./]\d{1,2}(?:[./](?:\d{4}|\d{2}))?(?!\d)',' ',text)
    text=re.sub(predicate,' ',text)
    words=re.findall(r'\w+',text)
    allowed={'и','у','в','на','весь','целый','день','пожалуйста','учитель','учителя','учителей',
             'преподаватель','преподаватели'}
    if any(word not in allowed for word in words):return None
    names=', '.join(t['name'] for t in sorted(rows,key=lambda t:t['id']))
    retained=[r for r in state.get('assistantConditions',{}).get(str(day),[])
              if not (r['type']=='teacher_absence' and r['teacherId'] in ids)]
    return {'date':str(day),'reply':'Отсутствие на весь день: '+names+'. Проверьте условия перед подбором.',
            'actions':canonical_actions(retained+[{'type':'teacher_absence','teacherId':t['id'],'first':1,'last':8} for t in rows]),
            'questions':[],'unsupported':[]}
