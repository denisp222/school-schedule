"""Slot conditions shared by daily proposals and independent acceptance."""


def teacher_window_allows(row,lesson,period):
    if lesson.get('classHour') or row['teacherId'] not in lesson['teacherIds']:return True
    assigned,selected=set(lesson['classIds']),set(row['classIds'])
    if row.get('cancelOtherClasses') and not assigned<=selected:return False
    return not (assigned & selected) or row['first']<=period<=row['last']


def problems(state,day,actions,after):
    from .model import student_groups,lessons_for_day
    errors=[];sources=None
    for row in actions:
        if row['type']=='replace_teacher' and not any(l['id']==row['lessonId'] and l['teacherIds']==[row['teacherId']] for l in after):
            errors.append('Не выполнена согласованная замена преподавателя.')
        if row['type']=='teacher_lesson_window' and any(not teacher_window_allows(row,l,l['period']) for l in after):
            errors.append('Не выполнено ограничение по классам или времени уроков учителя.')
        if row['type'] in ('class_day','group_day'):
            overridden={a['groupIndex'] for a in actions if a['type']=='group_day' and a['classId']==row['classId']}
            groups=[row['groupIndex']] if row['type']=='group_day' else [g for g in (0,1) if g not in overridden]
            for group in groups:
                periods=[l['period'] for l in after if row['classId'] in l['classIds'] and group in student_groups(l,row['classId'])]
                if not periods or min(periods)!=row['first'] or max(periods)>row['last']:
                    errors.append('Не выполнено время начала или окончания занятий класса.')
        if row['type'] in ('pin_lesson', 'place_lesson'):
            if sources is None:sources={l['id']:l for l in lessons_for_day(state,day)}
            source=sources.get(row['lessonId'])
            parts=[l for l in after if l['id']==row['lessonId'] or l.get('splitFrom')==row['lessonId']]
            if source is None:errors.append('Закреплённый урок больше не найден. Снимите условия дня и задайте их заново.')
            elif not parts or any(l['period']!=row['period'] for l in parts) or {t for l in parts for t in l['teacherIds']}!=set(source['teacherIds']):
                errors.append('Не выполнено закрепление урока.')
            elif row['type']=='place_lesson' and row.get('roomIds') is not None:
                if len(parts)==1:
                    assigned=parts[0]['roomIds']
                else:
                    assigned=[r for t in source['teacherIds'] for l in parts if l['teacherIds']==[t] for r in l['roomIds']]
                if assigned!=row['roomIds']:
                    errors.append('Не выполнено назначение выбранного кабинета.')
        if row['type']=='cancel_lesson' and any(l['id']==row['lessonId'] or l.get('splitFrom')==row['lessonId'] for l in after):
            errors.append('Не выполнена отмена урока.')
    return list(dict.fromkeys(errors))
