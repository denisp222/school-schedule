"""One editor for the permanent constraints used by every scheduling path."""
from fastapi import APIRouter
from .schemas import integer

router=APIRouter(prefix='/api/constraints')
KINDS=('teachers','classes','rooms','subjects')


def context():
    from . import server
    return server


@router.post('/availability')
def availability(body:dict):
    server=context();revision=server.require_revision(body)
    kind=body.get('kind');ident=body.get('id');allowed=body.get('allowed')
    if kind not in KINDS or not isinstance(ident,str) or not isinstance(allowed,list) or len(allowed)>60:
        raise ValueError('Выберите запись и разрешённые часы.')
    slots=set()
    for item in allowed:
        if (not isinstance(item,list) or len(item)!=2 or any(type(x) is not int for x in item)
                or not 0<=item[0]<=4 or not 1<=item[1]<=8):
            raise ValueError('Проверьте дни недели и номера разрешённых уроков.')
        slots.add(tuple(item))
    def change(state):
        record=next((r for r in state[kind] if r['id']==ident),None)
        if record is None:raise ValueError('Запись больше не найдена. Обновите список.')
        record['unavailable']=[{'day':d,'period':p} for d in range(5)
                               for p in range(1,min(8,len(state['school']['bells']))+1) if (d,p) not in slots]
        if kind in ('teachers','classes'):
            record['maxDaily']=integer(body.get('maxDaily',record.get('maxDaily',8)),'Предел уроков в день',minimum=1,maximum=8)
        if kind=='teachers':
            record['maxDays']=integer(body.get('maxDays',record.get('maxDays',5)),'Рабочих дней в неделю',minimum=1,maximum=5)
            if 'homeroomRoomId' in body:
                room=body['homeroomRoomId']
                if not isinstance(room,str) or room and room not in {r['id'] for r in state['rooms']}:
                    raise ValueError('Выберите кабинет классного руководителя.')
                record['homeroomRoomId']=room
        if kind=='classes':record['firstPeriod']=integer(body.get('firstPeriod',record.get('firstPeriod',1)),'Самый ранний урок',minimum=1,maximum=7)
    saved=server.project_store().mutate(revision,'Изменены постоянные ограничения',change)
    return saved


@router.post('/general')
def general(body:dict):
    server=context();revision=server.require_revision(body)
    for name in ('rovFirst','technologyPairs'):
        if type(body.get(name)) is not bool:raise ValueError('Проверьте общие правила школы.')
    from .rules import is_rov,is_technology
    def change(state):
        for subject in state['subjects']:
            if is_rov(subject):subject['firstMonday']=body['rovFirst']
            if is_technology(subject):subject['pairedTechnology']=body['technologyPairs']
    return server.project_store().mutate(revision,'Изменены общие правила школы',change)


@router.post('/eighth')
def eighth(body:dict):
    server=context();revision=server.require_revision(body)
    def change(state):
        if body.get('enabled') is False:state['school']['eighthPeriodException']=None
        elif body.get('enabled') is True:
            state['school']['eighthPeriodException']={'day':integer(body.get('day'),'День недели',minimum=0,maximum=4),
                'period':8,'classIds':[body.get('classId')],'teacherIds':[body.get('teacherId')],'subjectId':body.get('subjectId')}
        else:raise ValueError('Укажите, разрешено ли исключение восьмого урока.')
        from .rules import eighth_exception
        eighth_exception(state)
        from .model import period_allowed
        if any(not period_allowed(state,l) for l in state['baseLessons']):
            raise ValueError('В базовой неделе ещё стоит прежний восьмой урок. Сначала снимите его с расписания.')
    return server.project_store().mutate(revision,'Изменено исключение восьмого урока',change)
