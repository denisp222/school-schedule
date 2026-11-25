"""Explicit permission for a teacher to cover an existing lesson on one date."""


def validate(state, lesson, action):
    if (not lesson or len(lesson['teacherIds'])!=1 or not lesson['classIds']
            or any(lesson.get(k) for k in ('joint','technologyJoint','classHour'))):
        raise ValueError('Для замены выберите обычный урок с одним преподавателем.')
    original=action['originalTeacherId']
    replacement=action['teacherId']
    teachers={t['id']:t for t in state['teachers']}
    if original==replacement or original not in teachers or lesson['teacherIds'][0] not in (original,replacement):
        raise ValueError('Преподаватель этого урока изменился. Выберите замену заново.')
    teacher=teachers.get(replacement)
    if not teacher or teacher.get('archived') or lesson['subjectId'] not in teacher.get('subjectIds',[]):
        raise ValueError('У выбранного преподавателя этот предмет не указан в справочнике.')


def permissions(actions):
    return {r['lessonId']:r for r in actions if r['type']=='replace_teacher'}


def needs_confirmation(state, day, actions):
    existing=permissions(state.get('assistantConditions',{}).get(day,[]))
    return any(existing.get(ident)!=row for ident,row in permissions(actions).items())


def approved_change(state, source, lesson, permission):
    if not permission or not source or source['id']!=lesson['id']:return False
    if source['teacherIds']!=[permission['originalTeacherId']] or lesson['teacherIds']!=[permission['teacherId']]:return False
    try:validate(state,source,permission)
    except ValueError:return False
    return source.get('groupIndex')==lesson.get('groupIndex')
