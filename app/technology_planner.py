"""Small, deterministic candidate set for explicitly allowed technology sharing.

This module proposes complete pairs of existing group lessons.  The ordinary
day solver still checks the resulting whole-school timetable, and the user
still chooses a preview before anything is saved.  A permission is never a
permission to invent a lesson, a teacher, a pupil group or a second school day.
"""
from .rules import is_technology, is_rov, surname_stem, surname_matches
from collections import defaultdict
from itertools import combinations
import json

from . import commitments, technology
from .model import is_absent, lessons_for_day, parse_date, unavailable


def candidate_actions(state, day, actions, max_candidates=4):
    """Return bounded additional ``join_technology`` action sets.

    Group roles come only from school data.  An explicitly chosen own-class
    takeover can work before labels are filled, whereas merging different
    classes requires known matching roles.  Boys' workshop combinations need
    the separate safety permission and known capacity enforced by technology.
    """
    permissions=[a for a in actions if a.get('type')=='allow_technology']
    if not permissions or max_candidates<=0:return []
    weekday=parse_date(day).weekday()
    if weekday>4:return []
    teachers={r['id']:r for r in state['teachers']}
    rooms={r['id']:r for r in state['rooms']}
    subjects={r['id']:str(r['name']).lower() for r in state['subjects']}
    cancellations={a['lessonId'] for a in actions if a.get('type')=='cancel_lesson'}
    used={(ref['lessonId'],ref['groupIndex']) for a in actions if a.get('type')=='join_technology'
          for ref in a.get('sources',[])}
    temporary_absences=[a for a in actions if a.get('type')=='teacher_absence']
    temporary_rooms=[a for a in actions if a.get('type')=='room_unavailable']

    def teacher_blocked(teacher, period):
        return (teacher not in teachers or is_absent(state,teacher,day,period)
                or unavailable(teachers[teacher],weekday,period)
                or commitments.teacher_busy(state,teacher,day,period)
                or any(a['teacherId']==teacher and a['first']<=period<=a['last'] for a in temporary_absences))

    def room_blocked(room, period):
        return (room not in rooms or unavailable(rooms[room],weekday,period)
                or commitments.room_busy(state,room,day,period)
                or any(a['roomId']==room and a['first']<=period<=a['last'] for a in temporary_rooms))

    # Only groups actually present today may participate.  The permanent
    # schedule is evidence for their identity, never a source of extra hours.
    units={}
    for lesson in lessons_for_day(state,day):
        name=subjects.get(lesson['subjectId'],'')
        if not (is_technology(name)) or lesson.get('joint') or lesson.get('technologyJoint'):continue
        parent=lesson.get('splitFrom') or lesson['id']
        if parent in cancellations or lesson['id'] in cancellations:continue
        if len(lesson.get('classIds',[]))!=1:continue
        groups=[lesson['groupIndex']] if 'groupIndex' in lesson else [0,1] if len(lesson['teacherIds'])==len(lesson['roomIds'])==2 else []
        for group in groups:
            key=(parent,group)
            if key in used:continue
            ref={'lessonId':parent,'groupIndex':group}
            try:unit=technology.resolve_source(state,day,ref)
            except ValueError:continue
            # A previously moved split group uses its current position.
            unit['period']=lesson['period']
            units[key]={'ref':ref,'lesson':unit,'class':unit['classIds'][0],
                        'group':group,'teacher':unit['teacherIds'][0],
                        'subject':unit['subjectId'],'period':unit['period']}

    buckets=defaultdict(list)
    for unit in units.values():
        buckets[unit['class'],unit['group'],unit['teacher'],unit['subject']].append(unit)
    pairs=[]
    for key, rows in sorted(buckets.items()):
        rows.sort(key=lambda u:(u['period'],u['ref']['lessonId']))
        # Tile adjacent hours in pairs; do not propose keeping a single half.
        position=0
        while position+1<len(rows):
            first,second=rows[position:position+2]
            if second['period']==first['period']+1:
                pairs.append({'class':key[0],'group':key[1],'teacher':key[2],
                              'subject':key[3],'start':first['period'],'units':[first,second]})
                position+=2
            else:position+=1

    def blocked(pair):
        return any(teacher_blocked(u['teacher'],u['period']) or
                   any(room_blocked(r,u['period']) for r in u['lesson']['roomIds']) for u in pair['units'])

    candidates=[]
    for permission in permissions:
        host=permission.get('teacherId')
        if host not in teachers:continue
        scope=set(permission.get('classIds') or [])
        for left,right in combinations(pairs,2):
            if left['subject']!=right['subject'] or host not in (left['teacher'],right['teacher']):continue
            if scope and not {left['class'],right['class']}<=scope:continue
            if {tuple(u['ref'].values()) for u in left['units']}&{tuple(u['ref'].values()) for u in right['units']}:continue
            same=left['class']==right['class']
            if same:
                if not permission.get('sameClass') or left['group']==right['group']:continue
                # Own-class halves are paired by their actual two-hour block.
                if left['start']!=right['start']:continue
            else:
                roles=[technology.group_role(state,p['class'],p['group']) for p in (left,right)]
                if roles==['girls','girls']:
                    if not permission.get('girlsClasses'):continue
                elif roles==['boys','boys']:
                    if not (permission.get('boysClasses') and permission.get('safetyApproved')):continue
                else:continue
            host_pair=left if left['teacher']==host else right
            host_role=technology.group_role(state,host_pair['class'],host_pair['group'])
            boys=host_role=='boys'
            if boys and not (permission.get('boysClasses') and permission.get('safetyApproved')):continue
            starts=list(dict.fromkeys([host_pair['start'],left['start'],right['start']]))
            for start in starts:
                if not 1<=start<=6 or any(teacher_blocked(host,p) for p in (start,start+1)):continue
                preferred=host_pair['units'][0]['lesson']['roomIds'][0]
                options=[preferred]+sorted(r for r in rooms if r!=preferred)
                for room in options:
                    if any(room_blocked(room,p) for p in (start,start+1)):continue
                    joined=[]
                    for offset in (0,1):
                        action={'type':'join_technology',
                                'sources':[left['units'][offset]['ref'],right['units'][offset]['ref']],
                                'teacherId':host,'period':start+offset,'roomId':room,
                                'allowBoys':bool(boys),'safetyApproved':bool(boys and permission.get('safetyApproved'))}
                        try:technology.create(state,action['sources'],host,start+offset,day,room,
                                              action['allowBoys'],action['safetyApproved'])
                        except ValueError:break
                        joined.append(action)
                    if len(joined)!=2:continue
                    rank=(not (blocked(left) or blocked(right)),not same,
                          abs(start-left['start'])+abs(start-right['start']),room!=preferred,
                          left['class'],right['class'],start,room)
                    candidates.append((rank,joined))
                    # A different room is useful only if this one cannot host
                    # the whole pair. The solver may rearrange other lessons.
                    break

    candidates.sort(key=lambda item:item[0])
    result=[];seen=set()
    def add(rows):
        key=json.dumps(rows,sort_keys=True,ensure_ascii=False)
        if key not in seen:seen.add(key);result.append(rows)

    # A day may have several classes with the same absent technology teacher.
    # Offer one combined rescue before individual exceptions, without sharing
    # a source group twice or booking the host in two classes at one period.
    combined=[];consumed=set();slots=set()
    for rank,rows in candidates:
        if rank[0] or rank[1]:continue
        refs={(r['lessonId'],r['groupIndex']) for a in rows for r in a['sources']}
        occupied={(a['teacherId'],a['period']) for a in rows}
        if refs&consumed or slots&occupied:continue
        combined.extend(rows);consumed|=refs;slots|=occupied
    if combined:add(combined)
    for _,rows in candidates:
        if len(result)>=max_candidates:break
        add(rows)
    return result[:max_candidates]
