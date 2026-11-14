"""Read official Chronograph reports; preview before replacing a local project."""
from collections import defaultdict,Counter
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import base64,re,tempfile
from fastapi import APIRouter
from .previews import PreviewStore
from .store import Conflict
router=APIRouter(prefix='/api/chronograph');previews=PreviewStore(limit=4)
CODES={'Рус':'Русский язык','Родн.я':'Родной язык','Лит':'Литература','Род.л':'Родная литература','Ин.Яз':'Английский язык','Матем':'Математика','Алг':'Алгебра','Геом':'Геометрия','Вер.и с':'Вероятность и статистика','Инфор':'Информатика','Ист':'История','Общ':'Обществознание','Геогр':'География','Физ':'Физика','Хим':'Химия','Биол':'Биология','ИЗО':'Изобразительное искусство','Муз':'Музыка','Труд':'Труд (Технология)','Физ-ра':'Физическая культура','ОБЗР':'Основы безопасности и защиты Родины','ИП':'Индивидуальный проект','Э/к рус':'Текст как речевое развитие','Эл/к м':'Практикум решения задач по математике','ФГ':'Финансовая грамотность','Проф':'Россия-мои горизонты','Разг':'Разговоры о важном','Экол.культ.':'Экологическая культура','Черч':'Черчение','Хим.в зад.и упр.':'Химия в задачах и упражнениях','ОФГ':'Основы финансовой грамотности'}
ALIASES={'Рус.яз':'Русский язык','Родн.яз':'Родной язык','Рус. яз.':'Русский язык','Ин. яз.':'Английский язык','Разговоры':'Разговоры о важном'}
FILES=('teacher-details.html','room-details.html','load-teachers.html','week-teachers.html')
CODES.update({'Рус.яз':'Русский язык','Литер':'Литература','Род.яз':'Родной язык','Род.лит':'Родная литература'})
ALIASES['Иностранный язык']='Английский язык'

def convert(reports,school=None):
    from lxml import html
    from .model import normalize_state,validate_state,lesson_key,plan_report
    if not isinstance(reports,dict) or not all(n in reports for n in FILES):raise ValueError('Нужны четыре штатных HTML-отчёта: учителя, кабинеты, нагрузка и расписание учителей.')
    def table(name):
        content=reports[name]
        if not isinstance(content,str) or len(content)>5_000_000:raise ValueError('Отчёт слишком велик.')
        tree=html.fromstring(content)
        tables=tree.xpath('//body/table') or tree.xpath('//table')
        if not tables:raise ValueError('В отчёте нет таблицы.')
        return [[' '.join(cell.text_content().split()) for cell in row.xpath('./td|./th')] for row in tables[0].xpath('./tr') if row.xpath('./td|./th')]
    s={'school':deepcopy(school or {'name':'Школа'}),'teachers':[],'classes':[],'subjects':[],'rooms':[],'plan':[],'baseLessons':[]}
    s['school']['eighthPeriodException']=None;s['school'].pop('acceptedMissingPlanIds',None)
    def norm(t):return re.sub(r'[\s.]','',str(t)).casefold().replace('ё','е')
    def ensure(kind,name,**fields):
        old=next((r for r in s[kind] if norm(r['name'])==norm(name)),None)
        if old:return old['id']
        ident=kind[0]+str(len(s[kind])+1);s[kind].append({'id':ident,'name':name,**fields});return ident
    def subject(name):
        mapping={norm(k):v for k,v in {**CODES,**ALIASES}.items()}
        name=mapping.get(norm(name),name);return ensure('subjects',name,short=name,teacherCode='')
    for row in table('teacher-details.html')[1:]:
        if len(row)<3 or not row[1]:continue
        tid=ensure('teachers',row[1],subjectIds=[subject(x.strip()) for x in row[2].split(',') if x.strip()],weeklyTarget=None)
        if len(row)>3 and row[3]:
            next(t for t in s['teachers'] if t['id']==tid)['homeroomRoomId']=ensure('rooms',row[3])
    for row in table('room-details.html')[1:]:
        if len(row)>1 and row[1]:ensure('rooms',row[1])
    load=table('load-teachers.html')
    if not load or len(load[0])<6:raise ValueError('Не удалось прочитать заголовок отчёта нагрузки.')
    classnames=load[0][5:];classes={name:ensure('classes',name) for name in classnames if name}
    for row in table('room-details.html')[1:]:
        if len(row)<2 or not row[1]:continue
        room=next(r for r in s['rooms'] if norm(r['name'])==norm(row[1]))
        if len(row)>2:room['floor']=row[2]
        if len(row)>3 and row[3].isdigit():room['capacity']=int(row[3])
        if len(row)>4:room['subjectIds']=[subject(name.strip()) for name in row[4].split(',') if name.strip()]
        if len(row)>5:
            names=[name.strip() for name in row[5].split(',') if name.strip() in classes]
            if len(names)==1:room['classId']=classes[names[0]]
        if len(row)>6:
            names={norm(t['name']):t['id'] for t in s['teachers']}
            owners=[names[norm(name)] for name in row[6].split(',') if norm(name) in names]
            if len(owners)==1:room['teacherId']=owners[0]
    lesson_map={}
    week=table('week-teachers.html');unknown=[]
    for row in week:
        if len(row)<42:continue
        if not row[1] or norm(row[1]) not in {norm(t['name']) for t in s['teachers']}:continue
        tid=ensure('teachers',row[1])
        for slot,cell in enumerate(row[2:42]):
            if not cell or cell in ('-','—'):continue
            match=re.fullmatch(r'(\d+[а-яёa-z])\d*\((.*)\)(.*)',cell,re.I)
            if not match or match[1] not in classes:unknown.append(cell);continue
            cname,code,room=match.groups();sid=subject(code);day,period=divmod(slot,8);key=(day,period+1,classes[cname],sid)
            if key not in lesson_map:lesson_map[key]={'id':'l'+str(len(lesson_map)+1),'day':day,'period':period+1,'classIds':[classes[cname]],'teacherIds':[],'subjectId':sid,'roomIds':[]}
            lesson=lesson_map[key]
            if tid not in lesson['teacherIds']:lesson['teacherIds'].append(tid)
            if room:
                rid=ensure('rooms',room)
                if rid not in lesson['roomIds']:lesson['roomIds'].append(rid)
    if unknown:raise ValueError('В отчёте есть нераспознанные занятия. Нужен стандартный полный отчёт расписания учителей с названиями предметов.')
    rawplan=defaultdict(list);tid=None
    for row in load[1:]:
        if len(row)==len(classnames)+5:
            tid=ensure('teachers',row[1]);teacher=next(t for t in s['teachers'] if t['id']==tid)
            if not row[2].isdigit():raise ValueError('Не удалось прочитать норму часов преподавателя.')
            teacher['weeklyTarget']=int(row[2]);data=row[3:]
        else:data=row
        if tid is None or len(data)<2 or not data[0]:continue
        sid=subject(data[0])
        for cname,value in zip(classnames,data[2:]):
            if not value or value in ('-','—'):continue
            if not value.isdigit():raise ValueError('Не удалось прочитать часы учебного плана.')
            rawplan[classes[cname],sid].append((tid,int(value)))
    for (cid,sid),entries in rawplan.items():
        if len({h for t,h in entries})!=1:raise ValueError('В отчёте различаются часы одновременных подгрупп. Уточните их в Хронографе перед импортом.')
        teachers=sorted({t for t,h in entries});matching=[l for l in lesson_map.values() if l['classIds']==[cid] and l['subjectId']==sid and sorted(l['teacherIds'])==teachers]
        rooms=Counter(tuple(l['roomIds']) for l in matching).most_common(1)
        p={'id':'p'+str(len(s['plan'])+1),'classIds':[cid],'teacherIds':teachers,'subjectId':sid,'hours':entries[0][1],'roomIds':list(rooms[0][0]) if rooms else [],'confirmed':True}
        s['plan'].append(p)
        for lesson in matching:lesson['planId']=p['id']
        for teacher in s['teachers']:
            if teacher['id'] in teachers and sid not in teacher['subjectIds']:teacher['subjectIds'].append(sid)
    s['baseLessons']=list(lesson_map.values())
    if not s['baseLessons'] or not s['plan']:raise ValueError('В отчётах не найдено базовое расписание или учебный план.')
    eighth=[l for l in s['baseLessons'] if l['period']==8]
    if eighth:
        rules={(l['day'],tuple(l['classIds']),tuple(l['teacherIds']),l['subjectId']) for l in eighth}
        if len(rules)!=1:raise ValueError('Найдено несколько разных исключений восьмого урока. Настройте правила перед импортом.')
        l=eighth[0];s['school']['eighthPeriodException']={k:deepcopy(l[k]) for k in ('day','period','classIds','teacherIds','subjectId')}
    from .class_hours import fill_leaders,sync_labels
    s=normalize_state(s);fill_leaders(s);sync_labels(s);validate_state(s)
    return s

@router.post('/preview')
def preview(body:dict):
    from . import server
    from .model import issues,plan_report
    current=server.store.read()
    if server.require_revision(body)!=current['revision']:raise Conflict('Данные изменились. Повторите импорт.')
    reports=body.get('reports')
    if body.get('project') is not None:
        try:content=base64.b64decode(body['project'],validate=True)
        except (TypeError,ValueError):raise ValueError('Не удалось прочитать файл Хронографа.') from None
        if not 16<=len(content)<=5_000_000:raise ValueError('Неверный размер проекта Хронографа.')
        from .chronograph_bridge import export_project
        reports=export_project(content,server.DATA,body.get('legacyPath',''))
    state=convert(reports,current['state']['school'])
    token=uuid4().hex;previews[token]={'revision':current['revision'],'state':state}
    return {'previewId':token,'revision':current['revision'],'counts':{k:len(state[k]) for k in ('teachers','classes','rooms','subjects','plan','baseLessons')},'issues':issues(state,state['baseLessons']),'report':plan_report(state)}

@router.post('/apply')
def apply(body:dict):
    from . import server
    revision=server.require_revision(body);p=previews.get(body.get('previewId'))
    if not p or p['revision']!=revision:raise Conflict('Предпросмотр импорта устарел. Прочитайте файл снова.')
    return server.store.mutate(revision,'Загружен проект Хронографа',lambda state:deepcopy(p['state']))
