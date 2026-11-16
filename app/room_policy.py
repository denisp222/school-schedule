"""Explicit room purpose, including rooms excluded from automatic allocation."""

def allowed(state, lesson, room):
    policy=room.get('usePolicy','general')
    if policy=='individual' and not lesson.get('learnerId'):return False
    if policy=='manual':
        classes=set(lesson.get('classIds',[]))
        if (room['id'] not in lesson.get('roomExceptions',[]) or not classes
                or not classes.issubset(set(room.get('manualClassIds',[])))):return False
    if room.get('allowedTeacherIds') and not set(lesson.get('teacherIds',[])).intersection(room['allowedTeacherIds']):return False
    if room.get('allowedTeacherIds') and room['id'] in lesson.get('roomIds',[]) and len(lesson.get('teacherIds',[]))==len(lesson.get('roomIds',[])):
        if lesson['teacherIds'][lesson['roomIds'].index(room['id'])] not in room['allowedTeacherIds']:return False
    if room.get('subgroupsOnly') and not lesson.get('learnerId'):
        split='groupIndex' in lesson or len(lesson.get('teacherIds',[]))>1
        if lesson.get('technologyJoint'):
            split=all(len(groups)==1 for groups in lesson['technologyJoint'].get('classGroups',{}).values())
        if not split:return False
    if policy=='restricted' and room.get('subjectIds') and lesson.get('subjectId') not in room['subjectIds']:return False
    return True


def available_for_general_use(room):
    return room.get('usePolicy','general')=='general' and not room.get('allowedTeacherIds')


def validate(state):
    teachers={t['id'] for t in state['teachers']};classes={c['id'] for c in state['classes']}
    for room in state['rooms']:
        if 'subgroupsOnly' in room and type(room['subgroupsOnly']) is not bool:
            raise ValueError('Проверьте ограничение кабинета для подгрупп.')
        if room.get('usePolicy','general') not in ('general','restricted','manual','individual'):
            raise ValueError('Выберите назначение кабинета.')
        if 'individualPriority' in room and (type(room['individualPriority']) is not int or not 0<=room['individualPriority']<=20):
            raise ValueError('Проверьте приоритет кабинета для индивидуальных занятий.')
        for field,refs in [('allowedTeacherIds',teachers),('manualClassIds',classes)]:
            if field in room and (not isinstance(room[field],list) or any(not isinstance(v,str) or v not in refs for v in room[field]) or len(set(room[field]))!=len(room[field])):
                raise ValueError('Проверьте разрешённых преподавателей и классы кабинета.')
