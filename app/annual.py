"""Construct a complete annual week from the assigned teaching plan."""
from collections import Counter, defaultdict
from copy import deepcopy
from time import perf_counter
from uuid import uuid4

from .model import indexes, lesson_key, gap_slots, unavailable, must_be_first, issues, validate_state,period_allowed,eighth_exception,plan_is_paired,room_student_count
from .day_preferences import profiles,add_costs,MOVE_COST
from .commitments import teacher_busy,room_busy
from .technology import groups_for,student_count


def build_week(state):
    from .solver_process import isolated,calculate
    if isolated():return calculate('annual',{'state':state})
    # Complete the affected classes/teachers first. Rebuilding all 628 lessons
    # wastes the useful existing arrangement and most of the search budget.
    result = _build_week(state, local=True, seconds=1.5)
    if result['status'] in ('ok', 'needs_data'):
        return result
    return _build_week(state, local=False, seconds=3.5)


def _build_week(state, *, local, seconds):
    from ortools.sat.python import cp_model
    started = perf_counter()
    ix = indexes(state)
    placed = Counter(lesson_key(l) for l in state['baseLessons'])
    invalid_keys={lesson_key(l) for l in state['baseLessons'] if not period_allowed(state,l) or
                  must_be_first(ix['subjects'][l['subjectId']]) and (l['day']!=0 or l['period']!=1) or
                  any(teacher_busy(state,t,l['day'],l['period']) for t in l['teacherIds']) or
                  any(room_busy(state,r,l['day'],l['period']) for r in l['roomIds'])}
    incomplete = [p for p in state['plan'] if placed[lesson_key(p)] != p['hours'] or lesson_key(p) in invalid_keys]
    affected_classes = {c for p in incomplete for c in p['classIds']}
    affected_teachers = {t for p in incomplete for t in p['teacherIds']}
    rule=eighth_exception(state)
    periods = min(8 if rule else 7,len(state['school']['bells']))
    totals = Counter()
    for plan in state['plan']:
        for teacher in plan['teacherIds']:
            totals[teacher] += plan['hours']
    problems = []
    for teacher in state['teachers']:
        if teacher.get('weeklyTarget') is not None and totals[teacher['id']] != teacher['weeklyTarget']:
            problems.append(f"{teacher['name']}: в плане {totals[teacher['id']]} ч, норма {teacher['weeklyTarget']} ч.")
    if not state['plan']:
        problems.append('Сначала заполните учебный план.')
    for cls in state['classes']:
        hours=sum(p['hours'] for p in state['plan'] if cls['id'] in p['classIds'])
        capacity=5*min(7,cls.get('maxDaily',7))
        if rule and cls['id'] in rule['classIds']:capacity+=1
        if hours>capacity:problems.append(f"{cls['name']}: в плане {hours} ч, а до седьмого урока за пятидневку помещается {capacity}. Уточните учебный план.")
    for plan in state['plan']:
        if not plan.get('teacherIds') or not plan.get('classIds'):
            problems.append('У каждого предмета в плане должны быть класс и свой учитель.')
        if plan_is_paired(plan,ix['subjects']) and plan['hours'] % 2:
            problems.append('Для сдвоенных занятий число часов должно быть чётным.')
    if problems:
        return {'status':'needs_data','message':'Уточните учебный план.', 'problems':problems}
    model = cp_model.CpModel()
    occupied = defaultdict(list)
    subject_day = defaultdict(list)
    choices = []
    costs = []
    change_costs=[]
    policy={d:profiles(state,d) for d in range(5)};comfort=[]
    accepted=set(state['school'].get('acceptedMissingPlanIds',[]))
    used_ids = set()
    for plan in state['plan']:
        original = sorted([l for l in state['baseLessons'] if lesson_key(l)==lesson_key(plan)],key=lambda l:(not l.get('locked'),l['day'],l['period']))
        duration = 2 if plan_is_paired(plan,ix['subjects']) else 1
        if sum(bool(l.get('locked')) for l in original)>plan['hours']:
            return {'status':'infeasible','message':'Закреплённых занятий больше, чем часов в плане.','problems':[plan['id']]}
        previous = None
        required=min(plan['hours'],len(original)) if plan['id'] in accepted else plan['hours']
        for offset in range(0, required, duration):
            old = original[offset:offset+duration]
            pinned = [l for l in old if l.get('locked')]
            if pinned and (len(pinned)!=duration or any(l['day']!=pinned[0]['day'] or l['period']!=pinned[0]['period']+j for j,l in enumerate(pinned))):
                return {'status':'infeasible','message':'Закреплённые уроки не образуют указанную пару.','problems':[plan['id']]}
            records = []
            for j in range(duration):
                record = deepcopy(old[j]) if j<len(old) else {'id':uuid4().hex,'classIds':list(plan['classIds']),'teacherIds':list(plan['teacherIds']),'subjectId':plan['subjectId'],'roomIds':list(plan.get('roomIds',[])),'locked':False,'note':'Расставлено по учебному плану'}
                record['planId'] = plan['id']; used_ids.add(record['id']); records.append(record)
            options = []
            for d in range(5):
                for p in range(1,periods-duration+2):
                    if local and old and not (affected_classes.intersection(plan['classIds']) or affected_teachers.intersection(plan['teacherIds'])) and (d,p)!=(old[0]['day'],old[0]['period']):continue
                    if any(not period_allowed(state,records[0],q,d) for q in range(p,p+duration)):continue
                    if pinned and (d,p)!=(pinned[0]['day'],pinned[0]['period']):continue
                    subject=ix['subjects'][plan['subjectId']]
                    if must_be_first(subject) and (d!=0 or p!=1 or duration!=1):continue
                    invalid=False
                    for q in range(p,p+duration):
                        for kind,field in (('teachers','teacherIds'),('classes','classIds'),('rooms','roomIds')):
                            for ident in records[0][field]:
                                record=ix[kind][ident]
                                if unavailable(record,d,q):invalid=True
                                if kind=='teachers' and teacher_busy(state,ident,d,q):invalid=True
                                if kind=='rooms' and room_busy(state,ident,d,q):invalid=True
                                if kind=='classes' and q<record.get('firstPeriod',1):invalid=True
                                size=room_student_count(state,records[0],ident) if kind=='rooms' else None
                                if kind=='rooms' and ((record.get('subjectIds') and plan['subjectId'] not in record['subjectIds']) or (record.get('capacity') and size is not None and size>record['capacity'])):invalid=True
                    if invalid:continue
                    v=model.new_bool_var(f'x{len(choices)}_{d}_{p}')
                    options.append((v,d,p))
                    unchanged=bool(old and old[0]['day']==d and old[0]['period']==p)
                    model.add_hint(v,int(unchanged))
                    modified=sum(j<len(old) and (old[j]['day'],old[j]['period'])!=(d,p+j) for j in range(duration))
                    change_costs.append(v*modified)
                    for q in range(p,p+duration):
                        for kind,field in (('teachers','teacherIds'),('classes','classIds'),('rooms','roomIds')):
                            for ident in records[0][field]:
                                for group in groups_for(records[0],ident) if kind=='classes' else [0]:occupied[kind,ident,group,d,q].append(v)
                        for c in plan['classIds']:
                            for group in groups_for(records[0],c):subject_day[c,plan['subjectId'],d,group].append(v)
                        if state['school'].get('preferDifficultMorning'):
                            costs.append(v*max(0,q-4)*int(subject.get('difficulty',5)))
            if not options:return {'status':'infeasible','message':'Для занятия нет разрешённого времени.','problems':[', '.join(ix['classes'][c]['name'] for c in plan['classIds'])+' · '+ix['subjects'][plan['subjectId']]['name']]}
            model.add_exactly_one([v for v,_,_ in options])
            rank=sum(v*(d*periods+p) for v,d,p in options)
            if not pinned:
                if previous is not None:model.add(rank>previous)
                previous=rank
            choices.append((records,options))
    if any(l.get('locked') and l['id'] not in used_ids for l in state['baseLessons']):
        return {'status':'needs_data','message':'У закреплённого занятия нет соответствующей строки плана.','problems':[]}
    occupancy={}
    for key,variables in occupied.items():
        o=model.new_bool_var('o'+str(len(occupancy)));model.add(sum(variables)==o);occupancy[key]=o
    for kind in ('teachers','classes'):
        for record in state[kind]:
            days=[]
            for d in range(5):
                for group in [0,1] if kind=='classes' else [0]:
                    row=[occupancy.get((kind,record['id'],group,d,p),0) for p in range(1,periods+1)]
                    model.add(sum(row)<=record.get('maxDaily',8))
                    if kind=='teachers':
                        active=model.new_bool_var('day');model.add_max_equality(active,row);days.append(active)
                        continue
                    soft,upper=add_costs(model,row,policy[d][record['id'],group],f"pupil_{record['id']}_{d}_{group}")
                    comfort.extend(soft)
                    for p in range(1,periods-1):
                        left=model.new_bool_var('left');right=model.new_bool_var('right')
                        model.add_max_equality(left,row[:p]);model.add_max_equality(right,row[p+1:])
                        model.add(left+right-row[p]<=1)
            if kind=='teachers':model.add(sum(days)<=record.get('maxDays',5))
    limits={}
    for plan in state['plan']:
        for c in plan['classIds']:limits[c,plan['subjectId']]=max(limits.get((c,plan['subjectId']),0),plan.get('maxPerDay',2))
    for (c,s,d,g),variables in subject_day.items():model.add(sum(variables)<=limits[c,s])
    minor_bound=max(1,sum(len(records) for records,_ in choices)*max(0,periods-4)*max(int(s.get('difficulty',5)) for s in state['subjects']))
    model.minimize((sum(change_costs)*MOVE_COST+sum(comfort))*(minor_bound+1)+sum(costs))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=seconds;solver.parameters.num_search_workers=4;solver.parameters.random_seed=7
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        return {'status':'infeasible' if status==cp_model.INFEASIBLE else 'timeout','message':'При заданных ограничениях полная неделя не складывается.' if status==cp_model.INFEASIBLE else 'Полную неделю пока не удалось составить. Текущее расписание сохранено.','problems':['Проверьте часы, доступность, закрепления, число рабочих дней и сдвоенные уроки.'],'seconds':round(perf_counter()-started,2)}
    lessons=[]
    for records,options in choices:
        _,d,p=next(o for o in options if solver.boolean_value(o[0]))
        for j,record in enumerate(records):record.update(day=d,period=p+j);lessons.append(record)
    work=deepcopy(state);work['baseLessons']=lessons;validate_state(work)
    errors=[i['message'] for i in issues(work,lessons) if i['level']=='error']
    if errors:return {'status':'invalid','message':'Вариант не прошёл проверку.','problems':errors}
    return {'status':'ok','message':'Базовая неделя составлена. Согласованная разница часов сохранена.' if accepted else 'Полная неделя составлена. Все часы учебного плана расставлены.','lessons':lessons,'seconds':round(perf_counter()-started,2),'count':len(lessons),'problems':[]}
