"""Soft pupil preferences balanced with changes, below preserved lesson hours."""
from collections import defaultdict
import re

from .model import student_groups
MOVE_COST=20


def quality_key(stats):
    moved=int(stats.get('moved',0));preference=int(stats.get('studentPreference',0))
    return (int(stats.get('classGapsAfter',0)),int(stats.get('lostHours',stats.get('cancelled',0))),
            int(stats.get('youngerLate',0)),moved,preference)


def late_count(state,lessons,weekday,conditions=()):
    policy=profiles(state,weekday,conditions)
    occupied=defaultdict(set)
    for lesson in lessons:
        for cid in lesson['classIds']:
            for group in student_groups(lesson,cid):occupied[cid,group].add(lesson['period'])
    return sum(sum(p>normal for p in occupied[key]) for key,(_,normal,weight) in policy.items() if weight==3)


def gap_details(state,lessons):
    from .model import gap_slots
    result=[]
    for cls in state['classes']:
        seen=set()
        for group in (0,1):
            holes=tuple(gap_slots([l['period'] for l in lessons if cls['id'] in l['classIds'] and group in student_groups(l,cls['id'])]))
            if holes and holes not in seen:
                seen.add(holes)
                result.append({'classId':cls['id'],'className':cls['name'],'groupIndex':group,'periods':list(holes)})
    return result


def profiles(state,weekday,conditions=()):
    ends=defaultdict(int)
    for lesson in state['baseLessons']:
        if lesson['day']==weekday:
            for cid in lesson['classIds']:ends[cid]=max(ends[cid],lesson['period'])
    class_rules={r['classId']:r for r in conditions if r['type']=='class_day'}
    group_rules={(r['classId'],r['groupIndex']):r for r in conditions if r['type']=='group_day'}
    result={}
    for cls in state['classes']:
        match=re.match(r'\s*(\d+)',cls['name']);grade=int(match[1]) if match else 11
        weight=3 if grade<=6 else 2 if grade<=8 else 1
        normal=ends.get(cls['id']) or (7 if weekday in (0,3) or grade>6 else 6)
        for group in (0,1):
            rule=group_rules.get((cls['id'],group),class_rules.get(cls['id']))
            first=rule['first'] if rule else cls.get('firstPeriod',1)
            result[cls['id'],group]=(first,normal,weight)
    return result


def group_cost(periods,profile):
    if not periods:return 0
    first,last,weight=profile
    return weight*(12*max(0,min(periods)-first)+16*sum(p>last for p in set(periods)))


def score(state,lessons,weekday,conditions=(),prepared=None):
    policy=prepared if prepared is not None else profiles(state,weekday,conditions)
    groups=defaultdict(list)
    for lesson in lessons:
        for cid in lesson['classIds']:
            for group in student_groups(lesson,cid):groups[cid,group].append(lesson['period'])
    return sum(group_cost(periods,policy[key]) for key,periods in groups.items())


def add_costs(model,row,profile,prefix):
    """Same score as group_cost for a contiguous CP occupancy row."""
    first,last,weight=profile;terms=[];bound=0
    for offset,occupied in enumerate(row):
        period=offset+1
        arrival=12*weight*max(0,period-first)
        if arrival:
            start=model.new_bool_var(prefix+'_start_'+str(period))
            previous=row[offset-1] if offset else 0
            model.add(start>=occupied-previous);model.add(start<=occupied);model.add(start+previous<=1)
            terms.append(start*arrival);bound+=arrival
        if period>last:terms.append(occupied*16*weight);bound+=16*weight
    return terms,bound
