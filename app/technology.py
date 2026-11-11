"""Evidence-backed, explicitly approved technology group combinations.

Group indexes describe pupil groups, never teacher gender. The role is school
data in class.groupRoles/groupNames; index zero is not assumed to mean girls.
"""
from .rules import is_technology, is_rov, surname_stem, surname_matches
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import re


def _classes(state):return {c['id']:c for c in state['classes']}


def group_role(state,class_id,group):
    record=_classes(state).get(class_id,{})
    roles=record.get('groupRoles',[])
    value=roles[group] if isinstance(roles,list) and len(roles)>group else ''
    if value in ('girls','boys'):return value
    names=record.get('groupNames',[])
    name=names[group] if isinstance(names,list) and len(names)>group else ''
    if re.search(r'девоч|девуш|girls',str(name),re.I):return 'girls'
    if re.search(r'мальч|юнош|boys',str(name),re.I):return 'boys'
    return 'unknown'


def group_size(state,class_id,group):
    values=_classes(state).get(class_id,{}).get('groupSizes',[])
    value=values[group] if isinstance(values,list) and len(values)>group else None
    return value if type(value) is int and value>0 else None


def groups_for(lesson,class_id=None):
    meta=lesson.get('technologyJoint')
    if isinstance(meta,dict) and isinstance(meta.get('classGroups'),dict):
        if class_id is not None:return list(meta['classGroups'].get(class_id,[]))
        return sorted({g for values in meta['classGroups'].values() for g in values})
    return [lesson['groupIndex']] if 'groupIndex' in lesson else [0,1]


def _refs(values):
    if not isinstance(values,list) or len(values)!=2:raise ValueError('Выберите две исходные подгруппы технологии.')
    refs=[]
    for value in values:
        if not isinstance(value,dict) or set(value)!=set(('lessonId','groupIndex')):
            raise ValueError('Укажите урок и номер каждой исходной подгруппы.')
        if not isinstance(value['lessonId'],str) or not value['lessonId'] or type(value['groupIndex']) is not int or value['groupIndex'] not in (0,1):
            raise ValueError('Некорректная исходная подгруппа технологии.')
        refs.append({'lessonId':value['lessonId'],'groupIndex':value['groupIndex']})
    refs.sort(key=lambda r:(r['lessonId'],r['groupIndex']))
    if refs[0]==refs[1]:raise ValueError('Одну подгруппу нельзя объединить саму с собой.')
    return refs


def source_refs(lesson):
    meta=lesson.get('technologyJoint',{})
    try:return _refs(meta.get('sourceRefs'))
    except (ValueError,AttributeError):return []


def _parent(lesson):return lesson.get('splitFrom') or lesson['id']


def _unit(lesson,group):
    source=deepcopy(lesson)
    if len(source.get('classIds',[]))!=1:raise ValueError('Исходное занятие должно относиться к одному классу.')
    if 'groupIndex' in source:
        if source['groupIndex']!=group or len(source['teacherIds'])!=1 or len(source.get('roomIds',[]))!=1:
            raise ValueError('Исходная подгруппа больше не найдена.')
    elif len(source.get('teacherIds',[]))==len(source.get('roomIds',[]))==2:
        source['teacherIds']=[source['teacherIds'][group]];source['roomIds']=[source['roomIds'][group]]
    else:raise ValueError('Это занятие не разделено на две подгруппы технологии.')
    parent=_parent(source)
    source.update(id=f'{parent}-tech-group-{group}',splitFrom=parent,groupIndex=group)
    source.pop('technologyJoint',None);source.pop('joint',None)
    return source


def _rows(state,day):
    weekday=date.fromisoformat(str(day)).weekday()
    return state.get('days',{}).get(str(day),[l for l in state['baseLessons'] if l['day']==weekday])


def resolve_source(state,day,ref):
    """Resolve a canonical parent/group reference without trusting embedded data."""
    pools=[_rows(state,day),state.get('dayBases',{}).get(str(day),[]),state['baseLessons']]
    weekday=date.fromisoformat(str(day)).weekday()
    for rows in pools:
        for lesson in rows:
            if lesson.get('technologyJoint') or lesson.get('joint') or lesson['day']!=weekday:continue
            if _parent(lesson)!=ref['lessonId'] and lesson['id']!=ref['lessonId']:continue
            try:return _unit(lesson,ref['groupIndex'])
            except ValueError:continue
    raise ValueError('Исходный урок технологии или его подгруппа больше не найдены.')


def _identity(lesson):
    return (lesson['subjectId'],tuple(lesson['classIds']),tuple(lesson['teacherIds']),
            _parent(lesson),lesson.get('groupIndex'),lesson['day'])


def student_count(state,lesson):
    total=0;classes=_classes(state)
    for cid in lesson.get('classIds',[]):
        groups=groups_for(lesson,cid)
        if set(groups)=={0,1}:
            value=classes.get(cid,{}).get('size')
            if type(value) is int and value>0:total+=value;continue
        counts=[group_size(state,cid,g) for g in groups]
        if not counts or any(v is None for v in counts):return None
        total+=sum(counts)
    return total


def _technical(state,subject_id):
    name=next((str(s['name']).lower() for s in state['subjects'] if s['id']==subject_id),'')
    return is_technology(name)


def _token(day,refs,teacher):
    value=json.dumps([str(day),refs,teacher],sort_keys=True,ensure_ascii=False)
    return 'tech-'+sha256(value.encode('utf-8')).hexdigest()[:24]


def create(state,sources,teacherId,period,day,roomId=None,allowBoys=False,safetyApproved=False):
    refs=_refs(sources)
    if type(period) is not int or not 1<=period<=8:raise ValueError('Укажите номер урока технологии от 1 до 8.')
    when=date.fromisoformat(str(day))
    if when.weekday()>4:raise ValueError('В школе пятидневка.')
    if type(allowBoys) is not bool or type(safetyApproved) is not bool:raise ValueError('Подтверждение объединения должно быть явным.')
    units=[resolve_source(state,str(day),ref) for ref in refs]
    host=next((unit for unit in units if unit['teacherIds']==[teacherId]),None)
    if host is None:raise ValueError('Совместную технологию должен вести преподаватель одной из выбранных подгрупп.')
    lesson=deepcopy(host)
    classes=list(dict.fromkeys(c for unit in units for c in unit['classIds']))
    coverage={c:sorted({unit['groupIndex'] for unit in units if c in unit['classIds']}) for c in classes}
    room=roomId or host['roomIds'][0]
    lesson.update(id=_token(day,refs,teacherId),classIds=classes,teacherIds=[teacherId],roomIds=[room],period=period,locked=False)
    for field in ('splitFrom','groupIndex','groupRescue','joint'):lesson.pop(field,None)
    single={groups[0] for groups in coverage.values() if len(groups)==1}
    if all(len(groups)==1 for groups in coverage.values()) and len(single)==1:lesson['groupIndex']=next(iter(single))
    meta={'date':str(day),'period':period,'teacherId':teacherId,'roomId':room,
          'sourceRefs':refs,'sources':units,'classGroups':coverage,'allowBoys':allowBoys,'safetyApproved':safetyApproved}
    lesson['technologyJoint']=meta
    errors=problems(state,lesson,str(day))
    if errors:raise ValueError(errors[0])
    return lesson


def problems(state,lesson,day=None):
    """Verify actual source groups, own teacher, pupil coverage and room safety."""
    meta=lesson.get('technologyJoint')
    try:
        if not isinstance(meta,dict):raise ValueError()
        when=meta['date'];weekday=date.fromisoformat(when).weekday()
        refs=_refs(meta['sourceRefs']);stored=meta['sources']
        assert weekday<5 and (day is None or str(day)==when)
        assert type(meta['period']) is int and 1<=meta['period']<=8 and lesson['period']==meta['period'] and lesson['day']==weekday
        assert isinstance(stored,list) and len(stored)==2
        units=[resolve_source(state,when,ref) for ref in refs]
        assert [_identity(unit) for unit in stored]==[_identity(unit) for unit in units]
        assert _technical(state,lesson['subjectId']) and all(unit['subjectId']==lesson['subjectId'] for unit in units)
        teacher=meta['teacherId'];assert any(unit['teacherIds']==[teacher] for unit in units)
        assert lesson['teacherIds']==[teacher] and lesson['id']==_token(when,refs,teacher)
        coverage={c:sorted({unit['groupIndex'] for unit in units if c in unit['classIds']}) for c in {c for unit in units for c in unit['classIds']}}
        assert meta['classGroups']==coverage and set(lesson['classIds'])==set(coverage)
        assert len(lesson['roomIds'])==1 and lesson['roomIds']==[meta['roomId']]
        assert type(meta['allowBoys']) is bool and type(meta['safetyApproved']) is bool
        room=next(r for r in state['rooms'] if r['id']==meta['roomId'])
        assert not room.get('subjectIds') or lesson['subjectId'] in room['subjectIds']
        if any(unit.get('locked') and unit['period']!=lesson['period'] for unit in units):
            return ['Закреплённую пару технологии сначала нужно открепить в редакторе.']
    except (AssertionError,ValueError,KeyError,TypeError,StopIteration,IndexError):
        return ['Совместная технология должна сохранить реальные исходные подгруппы и своего преподавателя.']
    roles=[group_role(state,unit['classIds'][0],unit['groupIndex']) for unit in units]
    host_roles=[role for unit,role in zip(units,roles) if unit['teacherIds']==[teacher]]
    cross=len(coverage)>1
    if not cross and next(iter(coverage.values()))!=[0,1]:return ['В одном классе объединяются две разные подгруппы.']
    if cross and 'unknown' in roles:return ['Перед объединением разных классов укажите, где девочки и где мальчики.']
    boys=(cross and 'boys' in roles) or all(role=='boys' for role in host_roles)
    if boys and not (meta['allowBoys'] and meta['safetyApproved']):
        return ['Такое объединение с участием группы мальчиков требует отдельного разрешения и подтверждения условий работы.']
    count=student_count(state,lesson);capacity=int(room.get('capacity') or 0)
    if boys and (count is None or capacity<=0):return ['Для такого объединения нужно указать число учеников и вместимость мастерской.']
    if capacity>0 and count is not None and count>capacity:return ['Кабинет не вмещает выбранные подгруппы технологии.']
    return []


def warnings(state,lesson):
    """Useful approval context for an otherwise permitted explicit exception."""
    if not lesson.get('technologyJoint'):return []
    count=student_count(state,lesson)
    room=next((r for r in state['rooms'] if r['id'] in lesson.get('roomIds',[])),{})
    return ['Численность подгрупп или вместимость кабинета ещё не указаны; проверьте размещение перед сохранением.'] if count is None or not room.get('capacity') else []


def authorized(state,lesson,day=None):
    meta=lesson.get('technologyJoint',{});when=str(day or meta.get('date',''))
    refs=source_refs(lesson)
    if not refs:return False
    for action in state.get('assistantConditions',{}).get(when,[]):
        if action.get('type')!='join_technology':continue
        try:
            if _refs(action.get('sources'))!=refs:continue
            if action.get('teacherId')!=meta['teacherId'] or action.get('period')!=lesson['period']:continue
            if action.get('roomId') is not None and action['roomId']!=meta['roomId']:continue
            if bool(action.get('allowBoys',False))!=meta['allowBoys'] or bool(action.get('safetyApproved',False))!=meta['safetyApproved']:continue
            return True
        except (ValueError,KeyError,TypeError):continue
    return False


def apply(state,day,actions):
    """Expand selected parent groups and replace them without losing neighbours."""
    selected=[action for action in actions if action.get('type')=='join_technology']
    if not selected:return deepcopy(_rows(state,day))
    requested=[ref for action in selected for ref in _refs(action.get('sources'))]
    keys=[(ref['lessonId'],ref['groupIndex']) for ref in requested]
    if len(keys)!=len(set(keys)):raise ValueError('Одна подгруппа технологии указана в двух объединениях одновременно.')
    parents={key[0] for key in keys};rows=[]
    for lesson in deepcopy(_rows(state,day)):
        if lesson.get('technologyJoint') and any((ref['lessonId'],ref['groupIndex']) in set(keys) for ref in source_refs(lesson)):
            rows.extend(deepcopy(lesson['technologyJoint']['sources']))
        else:rows.append(lesson)
    expanded=[]
    for lesson in rows:
        if not lesson.get('technologyJoint') and _parent(lesson) in parents:
            for group in groups_for(lesson):expanded.append(_unit(lesson,group))
        else:expanded.append(lesson)
    consumed=set(keys)
    remaining=[lesson for lesson in expanded if lesson.get('technologyJoint') or (_parent(lesson),lesson.get('groupIndex')) not in consumed]
    merged=[create(state,action['sources'],action['teacherId'],action['period'],day,action.get('roomId'),
                   action.get('allowBoys',False),action.get('safetyApproved',False)) for action in selected]
    rows=remaining+merged
    if len({lesson['id'] for lesson in rows})!=len(rows):raise ValueError('Объединения технологии привели к повторному размещению урока.')
    rows.sort(key=lambda lesson:(lesson['period'],lesson['id']))
    state.setdefault('days',{})[str(day)]=rows
    return rows
