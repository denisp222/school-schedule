"""Pupil registers, exam reports and permanent stream synchronisation."""
import csv,io,json
from collections import defaultdict
from fastapi import APIRouter
from fastapi.responses import Response
from .model import plan_is_paired
router=APIRouter(prefix='/api/academic')

def context():
    from . import server
    return server

def validate(state):
    subjects={r['id'] for r in state['subjects']};groups=defaultdict(list)
    for pupil in state['students']:
        if not isinstance(pupil.get('name'),str) or not 1<=len(pupil['name'].strip())<=200:raise ValueError('Укажите ФИО ученика, до 200 символов.')
        exams=pupil.get('examSubjects',[])
        if not isinstance(exams,list) or len(exams)>30 or any(not isinstance(s,str) or s not in subjects for s in exams):raise ValueError('Проверьте предметы экзаменов ученика.')
    ix={r['id']:r for r in state['subjects']}
    for plan in state['plan']:
        group=plan.get('syncGroup','')
        if not isinstance(group,str) or len(group)>80:raise ValueError('Название связи занятий слишком длинное.')
        if 'groupIndex' in plan and (type(plan['groupIndex']) is not int or plan['groupIndex'] not in (0,1)):raise ValueError('Выберите подгруппу 1 или 2.')
        if group:groups[group].append((plan['hours'],plan_is_paired(plan,ix)))
    if any(len(set(rows))>1 for rows in groups.values()):raise ValueError('У связанных занятий должны совпадать часы и режим спаренности.')

def effective_plan(state,day=None):
    if day and state.get('baseVersions'):
        versions=state['baseVersions'];eligible=[v for v in versions if v['start']<=str(day)]
        version=max(eligible,key=lambda v:v['start']) if eligible else min(versions,key=lambda v:v['start'])
        return version.get('plan',state['plan'])
    return state['plan']

def sync_issues(state,lessons,day=None):
    from .model import lesson_key
    plan=effective_plan(state,day);plans={p['id']:p for p in plan};bykey={lesson_key(p):p for p in plan};groups=defaultdict(lambda:defaultdict(list));out=[]
    for l in lessons:
        if l.get('classHour'):continue
        p=plans.get(l.get('planId'),bykey.get(lesson_key(l),{}));group=p.get('syncGroup')
        if group:groups[group][p['id']].append(l)
    for group,sets in groups.items():
        rows=[sorted(ls,key=lambda l:(l['day'],l['period'])) for ls in sets.values()]
        if len(rows)<2:continue
        for ordinal in range(min(map(len,rows))):
            block=[r[ordinal] for r in rows]
            if len({(l['day'],l['period']) for l in block})>1:
                out.append({'code':'sync_group','level':'error','message':'Связанные занятия «'+group+'» должны проходить одновременно.','lessonIds':[l['id'] for l in block]})
    return out

def bind_daily(model,units,choices,state,day=None):
    plans={p['id']:p for p in effective_plan(state,day)};buckets=defaultdict(lambda:defaultdict(dict))
    for (old,unit),(options,cancel) in zip(units,choices):
        p=plans.get(unit.get('planId'),{});group=p.get('syncGroup')
        if not group:continue
        buckets[group][p['id']].setdefault(old['id'],[]).append((sum(v*period for v,period in options),cancel,old['period']))
    for byplan in buckets.values():
        lists=[sorted(rows.values(),key=lambda x:x[0][2]) for rows in byplan.values()]
        if len(lists)<2:continue
        for ordinal in range(min(map(len,lists))):
            members=[item for rows in lists for item in rows[ordinal]]
            for left,right in zip(members,members[1:]):
                guards=[c.Not() for c in (left[1],right[1]) if c is not None]
                model.add(left[0]==right[0]).only_enforce_if(guards)

def pupils(state,class_id='',subject_id=''):
    return sorted([r for r in state['students'] if (not class_id or r['classId']==class_id) and (not subject_id or subject_id in r.get('examSubjects',[]))],key=lambda r:(r['classId'],r['name'].casefold()))

@router.get('/exams')
def exams(classId:str='',subjectId:str='',format:str='csv'):
    state=context().store.read()['state'];rows=pupils(state,classId,subjectId)
    names={k:{r['id']:r['name'] for r in state[k]} for k in ('classes','subjects')}
    table=[['ФИО','Класс','Экзамены']]+[[r['name'],names['classes'][r['classId']],', '.join(names['subjects'][s] for s in r.get('examSubjects',[]))] for r in rows]
    if format=='docx':
        from docx import Document
        doc=Document();doc.add_heading('Ведомость выбора экзаменов',0)
        t=doc.add_table(rows=1,cols=3);t.style='Table Grid'
        for i,text in enumerate(table[0]):t.rows[0].cells[i].text=text
        for row in table[1:]:
            for cell,text in zip(t.add_row().cells,row):cell.text=text
        stream=io.BytesIO();doc.save(stream)
        return Response(stream.getvalue(),media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename="Exam-register.docx"'})
    if format!='csv':raise ValueError('Выберите Word или CSV.')
    stream=io.StringIO();writer=csv.writer(stream,delimiter=';')
    for row in table:writer.writerow(["'"+s if s.startswith(('=','+','-','@','\t','\r')) else s for s in row])
    return Response(stream.getvalue().encode('utf-8-sig'),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="Exam-register.csv"'})

@router.post('/students/import')
def import_students(body:dict):
    server=context();text=body.get('csv')
    if not isinstance(text,str) or len(text)>2_000_000:raise ValueError('Выберите CSV со списком учеников до 2 МБ.')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),delimiter=';');rows=list(reader)
    if not 1<=len(rows)<=5000:raise ValueError('В файле должно быть от 1 до 5000 учеников.')
    def change(state):
        classes={r['name'].casefold():r['id'] for r in state['classes']};subjects={r['name'].casefold():r['id'] for r in state['subjects']}
        known={(r['name'].casefold(),r['classId']):r for r in state['students']}
        from uuid import uuid4
        for row in rows:
            name=str(row.get('ФИО','')).strip();cls=classes.get(str(row.get('Класс','')).strip().casefold())
            if not name or not cls:raise ValueError('Проверьте столбцы ФИО и Класс. Классы должны быть заведены в справочнике.')
            exams=[s.strip().casefold() for s in str(row.get('Экзамены','')).split(',') if s.strip()]
            if any(s not in subjects for s in exams):raise ValueError('В CSV указан неизвестный предмет экзамена.')
            key=(name.casefold(),cls);item=known.get(key)
            if item is None:
                item={'id':uuid4().hex,'name':name,'classId':cls};state['students'].append(item);known[key]=item
            item['examSubjects']=[subjects[s] for s in exams]
    return server.store.mutate(server.require_revision(body),'Импорт списка учеников и экзаменов',change)
