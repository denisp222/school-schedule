"""Bounded constraint search for repairs that greedy swaps cannot make safe."""
from collections import defaultdict, Counter
from copy import deepcopy
from time import perf_counter
from .model import lessons_for_day, indexes, is_absent, unavailable, gap_slots, must_be_first, diff_lessons, parse_date,period_allowed,eighth_exception,paired_subjects
from .commitments import teacher_busy,room_busy
from .technology import groups_for,student_count
from .day_preferences import profiles,score as pupil_score,add_costs,quality_key,MOVE_COST,late_count
from .model import slot_feasible
from .search_policy import configure
from .model import changed_assignments
from .class_hours import cancelled_for_absence


def _seed_solution(model,response):
    model.clear_hints()
    for i,value in enumerate(response.solution):model.add_hint(model.get_int_var_from_proto_index(i),value)


def solve_day(state, day, variant=0, teacher_ids=(), baseline=None, hint=None, excluded=(),allow_room_changes=None,conditions=(),_seconds=None,_incumbent=None,_primary_bound=None,_placements=None):
    from .solver_process import isolated,calculate
    if isolated():return calculate('day',dict(state=state,day=day,variant=variant,teacher_ids=sorted(teacher_ids),baseline=baseline,hint=hint,excluded=excluded,allow_room_changes=allow_room_changes,conditions=conditions,_seconds=_seconds,_incumbent=_incumbent,_primary_bound=_primary_bound,_placements=_placements))
    if allow_room_changes is None:
        args=dict(state=state,day=day,variant=variant,teacher_ids=teacher_ids,baseline=baseline,excluded=excluded,conditions=conditions)
        def certificate(result,bound):
            result['search'].update(primaryProven=True,scope='all-rooms',certificate='room-relaxation',
                                    lowerBoundLostHours=bound['lostHours'],lowerBoundYoungerLate=bound.get('youngerLate',0),lowerBoundMoved=bound['moved'])
            return result
        def reaches(result,bound):
            return result is not None and bound is not None and bound['primaryProven'] and (result['stats']['classGapsAfter'],result['stats']['lostHours'],result['stats'].get('youngerLate',0),result['stats']['moved'])==(bound.get('classGapsAfter',0),bound['lostHours'],bound.get('youngerLate',0),bound['moved'])
        bound=None;projected=None;bound_searched=False
        # Solve the smaller time-only problem first. Matching its lower bound
        # with real rooms proves a global minimum without a huge joint search.
        if _primary_bound is None:
            bound=solve_day(**args,hint=None,allow_room_changes='relaxed',_seconds=1.2);bound_searched=True
            if bound:
                projected=solve_day(**args,hint=hint,allow_room_changes=True,_seconds=.8,_placements=bound['placements'])
                if reaches(projected,bound):return certificate(projected,bound)
        fixed=solve_day(**args,hint=projected['after'] if projected else hint,allow_room_changes=False,_seconds=1.2,_incumbent=projected)
        if projected and (fixed is None or quality_key(projected['stats'])<quality_key(fixed['stats'])):fixed=projected
        if fixed and _primary_bound is not None:
            if (fixed['stats']['classGapsAfter'],fixed['stats']['lostHours'],fixed['stats'].get('youngerLate',0),fixed['stats']['moved'])==tuple(_primary_bound):
                fixed['search'].update(primaryProven=True,scope='all-rooms',inheritedBound=True)
            return fixed
        if fixed and all(fixed['stats'].get(k,0)==0 for k in ('lostHours','moved','youngerLate','classGapsAfter')):
            fixed['search'].update(primaryProven=True,scope='all-rooms')
            return fixed
        if not bound_searched:bound=solve_day(**args,hint=None,allow_room_changes='relaxed',_seconds=1.2)
        if reaches(fixed,bound):return certificate(fixed,bound)
        if bound and projected is None:
            projected=solve_day(**args,hint=fixed['after'] if fixed else hint,allow_room_changes=True,_seconds=.8,_placements=bound['placements'])
            if reaches(projected,bound):return certificate(projected,bound)
            if projected and (fixed is None or quality_key(projected['stats'])<quality_key(fixed['stats'])):fixed=projected
        flexible=solve_day(**args,hint=fixed['after'] if fixed else hint,allow_room_changes=True,
                           _seconds=3. if fixed else 5.,_incumbent=fixed)
        if flexible and (fixed is None or quality_key(flexible['stats'])<=quality_key(fixed['stats'])):return flexible
        return fixed
    from ortools.sat.python import cp_model
    started=perf_counter(); before=sorted(lessons_for_day(state, day),key=lambda l:l['id']); ix=indexes(state)
    movement_before=baseline if baseline is not None and any(l.get('classHour') for l in before) else before
    movement_sources={l['id']:l for l in movement_before}
    weekday=parse_date(day).weekday();periods=min(8 if any(period_allowed(state,l,8,weekday,date=day) for l in before) else 7,len(state['school']['bells']))
    policy=profiles(state,weekday,conditions);preference_bound=0;comfort=[];model=cp_model.CpModel()
    allow_gaps=any(r['type']=='allow_class_gaps' for r in conditions)
    younger_late=[];pupil_gaps=[]
    placement_slots={(row['lessonId'],tuple(row['teacherIds'])):row['period'] for row in (_placements or [])}
    slots=defaultdict(list); choices=[]; units=[]; loss=[]; costs=[]; parent_changes=defaultdict(list)
    hinted_rows=hint if hint is not None else before
    grouped={c for l in before if len(l['teacherIds'])>1 and len(l['teacherIds'])==len(l['roomIds']) for c in l['classIds']}
    grouped|={c for l in before if 'groupIndex' in l for c in l['classIds']}
    original_subject=Counter(); subject_vars=defaultdict(list)
    room_choices={}
    paired=paired_subjects(state);pair_slots=defaultdict(list)
    class_rules={r['classId']:r for r in conditions if r['type']=='class_day'}
    group_rules={(r['classId'],r['groupIndex']):r for r in conditions if r['type']=='group_day'}
    pins={r['lessonId']:r['period'] for r in conditions if r['type']=='pin_lesson'}
    pins.update({l['id']:1 for l in before if l.get('classHour')})
    pins.update({l['id']:(l.get('technologyJoint') or l['joint'])['period'] for l in before if l.get('joint') or l.get('technologyJoint')})
    original_room_use={(r,l['period']) for l in before for r in l['roomIds'] if not any(t in teacher_ids or is_absent(state,t,day,l['period']) or unavailable(ix['teachers'][t],weekday,l['period']) or teacher_busy(state,t,day,l['period']) for t in l['teacherIds'])}
    unit_counts={};has_capacity=any(r.get('capacity') for r in state['rooms'])
    def rooms_for(unit,p,locked):
        if allow_room_changes=='relaxed':return [tuple(unit['roomIds'])]
        count=unit_counts[id(unit)]
        def suitable(r):
            room=ix['rooms'][r]
            return not unavailable(room,weekday,p) and not room_busy(state,r,day,p) and (unit.get('classHour') or not room.get('subjectIds') or unit['subjectId'] in room['subjectIds']) and (not room.get('capacity') or count is None or count<=room['capacity'])
        current=tuple(unit['roomIds'])
        options=[current] if all(suitable(r) for r in current) else []
        if locked or len(current)>1 or not allow_room_changes:return options
        # Include rooms freed by other moves, not only rooms free in the base.
        free=[(r['id'],) for r in sorted(state['rooms'],key=lambda r:r['id']) if suitable(r['id']) and (r['id'],)!=current]
        return options+free
    def absent(t,p):return t in teacher_ids or is_absent(state,t,day,p) or unavailable(ix['teachers'][t],weekday,p) or teacher_busy(state,t,day,p)
    blocked_pairs={(c,l['subjectId'],t) for l in before for c in l['classIds'] for t in l['teacherIds']
                   if (c,l['subjectId']) in paired and absent(t,l['period'])}
    for old in before:
        hour_parents=None
        if old.get('classHour'):
            hour_parents=([movement_sources[old['id']]] if old['id'] in movement_sources else
                          [movement_sources[s['id']] for s in old['classHour']['sources'] if s['id'] in movement_sources])
        parallel=len(old['teacherIds'])>1 and len(old['teacherIds'])==len(old['roomIds'])
        for position in range(len(old['teacherIds'])) if parallel else [None]:
            unit=deepcopy(old)
            if position is not None:
                unit['teacherIds']=[old['teacherIds'][position]];unit['roomIds']=[old['roomIds'][position]];unit['groupIndex']=position
            unit_counts[id(unit)]=student_count(state,unit) if has_capacity else None
            units.append((old,unit)); n=len(units); options=[]
            unit_hint=next((row for row in hinted_rows if (row['id']==old['id'] or row.get('splitFrom')==old['id']) and set(unit['teacherIds']).issubset(row['teacherIds'])),None)
            hint_period=unit_hint['period'] if unit_hint else None
            blocked=any(absent(t,old['period']) for t in unit['teacherIds'])
            pair_blocked=any((c,unit['subjectId'],t) in blocked_pairs for c in unit['classIds'] for t in unit['teacherIds'])
            cancellation=model.new_bool_var(f'cancel{n}') if ((blocked or pair_blocked) and old['id'] not in pins
                or cancelled_for_absence(state,old,day)) else None
            if cancellation is not None:loss.append(cancellation*len(unit['teacherIds']))
            for c in unit['classIds']:
                for g in groups_for(unit,c):original_subject[c,g,unit['subjectId']]+=1
            for p in range(1,periods+1):
                if _placements is not None and placement_slots.get((old['id'],tuple(unit['teacherIds'])))!=p:continue
                if not slot_feasible(state,unit,weekday,p,date=day,index=ix,check_rooms=False,extra_absent=teacher_ids):continue
                if old['id'] in pins and p!=pins[old['id']]:continue
                if any(rule and not rule['first']<=p<=rule['last'] for c in unit['classIds'] for g in groups_for(unit,c)
                       for rule in [group_rules.get((c,g),class_rules.get(c))]):continue
                if old.get('locked') and p!=old['period']:continue
                allowed_rooms=rooms_for(unit,p,old.get('locked') or (unit.get('technologyJoint') or unit.get('joint') or {}).get('roomId'))
                if not allowed_rooms:continue
                v=model.new_bool_var(f'x{n}_{p}');options.append((v,p))
                for t in unit['teacherIds']:slots['teachers',t,0,p].append(v)
                selected_rooms=[]
                for room_set in allowed_rooms:
                    rv=v if len(allowed_rooms)==1 else model.new_bool_var(f'room{n}_{p}_{len(selected_rooms)}')
                    selected_rooms.append((rv,room_set))
                    if allow_room_changes!='relaxed':
                        for r in room_set:slots['rooms',r,0,p].append(rv)
                    if room_set!=tuple(unit['roomIds']):
                        costs.append(rv*25)
                        if hour_parents is None:parent_changes[old['id']].append(rv)
                    if hour_parents is not None and allow_room_changes!='relaxed':
                        for parent in hour_parents:
                            old_rooms=([(r,) for r in parent['roomIds']] if 'groupIndex' not in parent
                                and len(parent['roomIds'])==len(parent['teacherIds'])==2 else [tuple(sorted(parent['roomIds']))])
                            if any(rs!=tuple(sorted(room_set)) for rs in old_rooms):parent_changes[parent['id']].append(rv)
                if len(allowed_rooms)>1:model.add(sum(rv for rv,_ in selected_rooms)==v)
                if len(allowed_rooms)>1:
                    for rv,room_set in selected_rooms:model.add_hint(rv,int(p==hint_period and unit_hint is not None and room_set==tuple(unit_hint['roomIds'])))
                room_choices[n,p]=selected_rooms
                for c in unit['classIds']:
                    for g in groups_for(unit,c):
                        slots['classes',c,g,p].append(v);subject_vars[c,g,unit['subjectId']].append(v)
                        if (c,unit['subjectId']) in paired:pair_slots[c,unit['subjectId'],g,p].append(v)
                costs.append(v*(abs(p-old['period'])*(2+variant)+p))
                if hour_parents is None:
                    if p!=old['period']:parent_changes[old['id']].append(v)
                else:
                    for parent in hour_parents:
                        if p!=parent['period']:parent_changes[parent['id']].append(v)
                model.add_hint(v,int(p==hint_period))
            if not options and cancellation is None:return None
            model.add_exactly_one([v for v,p in options]+([cancellation] if cancellation is not None else []))
            if cancellation is not None:model.add_hint(cancellation,int(unit_hint is None or not options))
            choices.append((options,cancellation))
    occupancy={}
    for key,vs in slots.items():
        o=model.new_bool_var('o'+str(len(occupancy)));model.add(sum(vs)==o);occupancy[key]=o
    for c,s,g in sorted({key[:3] for key in pair_slots}):
        # Tile this group's subject occupancy with blocks of exactly two.
        # This also forbids keeping only one hour of a cancelled double.
        starts={p:model.new_bool_var(f'pair_{c}_{s}_{g}_{p}') for p in range(1,periods)}
        for p in range(1,periods+1):
            model.add(sum(pair_slots.get((c,s,g,p),[]))==starts.get(p,0)+starts.get(p-1,0))
    for cid,rule in sorted(class_rules.items()):
        # Arrival is exact, for both groups, not permission to cancel all lessons.
        for group in (0,1):
            if (cid,group) not in group_rules:model.add(occupancy.get(('classes',cid,group,rule['first']),0)==1)
    for (cid,group),rule in sorted(group_rules.items()):
        model.add(occupancy.get(('classes',cid,group,rule['first']),0)==1)
    for kind in ['teachers','classes']:
        for record in sorted(state[kind],key=lambda r:r['id']):
            for g in ([0,1] if kind=='classes' else [0]):
                daily=[occupancy.get((kind,record['id'],g,p),0) for p in range(1,periods+1)]
                model.add(sum(daily)<=record.get('maxDaily',8))
                if kind=='teachers':continue
                soft,upper=add_costs(model,daily,policy[record['id'],g],f"pupil_{record['id']}_{g}")
                comfort.extend(soft);preference_bound+=upper
                _,normal,weight=policy[record['id'],g]
                if weight==3:younger_late.extend(v for p,v in enumerate(daily,1) if p>normal)
                gapvars=[]
                for p in range(1,periods-1):
                    left=model.new_bool_var('left');right=model.new_bool_var('right');hole=model.new_bool_var('hole')
                    model.add_max_equality(left,daily[:p]);model.add_max_equality(right,daily[p+1:])
                    model.add(hole>=left+right-daily[p]-1);model.add(hole<=left);model.add(hole<=right);model.add(hole+daily[p]<=1)
                    gapvars.append(hole)
                # Students in either group may arrive later or leave earlier,
                # but never have a hole between their own lessons.
                if allow_gaps:pupil_gaps.extend(gapvars)
                else:model.add(sum(gapvars)==0)
    limits={(c,p['subjectId']):int(p.get('maxPerDay',2)) for p in state['plan'] for c in p['classIds']}
    for (c,g,s),vs in subject_vars.items():model.add(sum(vs)<=max(limits.get((c,s),2),original_subject[c,g,s]))
    moved=[]
    for parent,variables in parent_changes.items():
        flag=model.new_bool_var('changed_'+parent);model.add_max_equality(flag,variables);moved.append(flag)
    # Bounded lexicographic objective: no sacrifice of a lesson hour to obtain
    # fewer changes, and no extra change to improve a teacher's free time.
    late_weight=len(moved)+1
    loss_weight=(len(younger_late)+1)*late_weight
    gap_weight=(len(units)*max((len(unit['teacherIds']) for _,unit in units),default=1)+1)*loss_weight
    primary=sum(pupil_gaps)*gap_weight+sum(loss)*loss_weight+sum(younger_late)*late_weight+sum(moved)
    model.minimize(primary)
    if _incumbent:
        maximum=(_incumbent['stats']['classGapsAfter']*gap_weight+_incumbent['stats']['lostHours']*loss_weight
                 +_incumbent['stats'].get('youngerLate',0)*late_weight+_incumbent['stats']['moved'])
        model.add(primary<=maximum)
    for previous in excluded:
        identical=[]
        for (old,unit),(options,cancellation) in zip(units,choices):
            match=next((l for l in previous if (l['id']==old['id'] or l.get('splitFrom')==old['id']) and set(unit['teacherIds']).issubset(l['teacherIds'])),None)
            if match:identical.extend(v for v,p in options if p==match['period'])
            elif cancellation is not None:identical.append(cancellation)
        if len(identical)==len(units):model.add(sum(identical)<=len(units)-1)
    solver=cp_model.CpSolver()
    configure(solver,_seconds if _seconds is not None else 1.2,7+variant)
    # Use ordinary hint completion rather than the native hint-repair search:
    # OR-Tools 9.15 may abort there when presolve fixes the decision variables.
    solver.parameters.search_branching=cp_model.AUTOMATIC_SEARCH
    solver.parameters.stop_after_first_solution=False
    solver.parameters.repair_hint=False;solver.parameters.hint_conflict_limit=1000 if _incumbent else 0
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE) and allow_room_changes!='relaxed':
        bootstrap=cp_model.CpSolver();configure(bootstrap,.25,7+variant)
        bootstrap.parameters.optimize_with_core=False
        bootstrap.parameters.hint_conflict_limit=0
        bootstrap_status=bootstrap.solve(model)
        if bootstrap_status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            solver=bootstrap;status=bootstrap_status
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):return None
    primary_proven=status==cp_model.OPTIMAL
    primary_value=int(round(solver.objective_value))
    search={'deterministic':True,'primaryProven':primary_proven,'scope':'all-rooms' if allow_room_changes else 'fixed-rooms',
            'objective':primary_value,'lowerBound':solver.best_objective_bound,'work':solver.response_proto.deterministic_time}
    if _placements is not None:search['scope']='fixed-periods'
    if primary_proven and comfort:
        # Improve pupils' convenience only inside the already proven minimum
        # number of cancellations and changes. Seed every auxiliary variable
        # with the feasible solution, not merely original (now invalid) slots.
        model.add(primary==primary_value)
        _seed_solution(model,solver.response_proto)
        minor_bound=max(1,len(units)*(periods*(2+variant)+periods+25))
        model.minimize(sum(comfort)*(minor_bound+1)+sum(costs))
        secondary=cp_model.CpSolver();configure(secondary,.2,7+variant)
        secondary_status=secondary.solve(model)
        if secondary_status in (cp_model.OPTIMAL,cp_model.FEASIBLE):solver=secondary
    if allow_room_changes=='relaxed':
        placements=[]
        for (old,unit),(options,cancellation) in zip(units,choices):
            period=next((p for v,p in options if solver.boolean_value(v)),None)
            placements.append({'lessonId':old['id'],'teacherIds':unit['teacherIds'],'period':period})
        return {'primaryProven':primary_proven,'lostHours':solver.value(sum(loss)),
                'classGapsAfter':solver.value(sum(pupil_gaps)),'youngerLate':solver.value(sum(younger_late)),
                'moved':solver.value(sum(moved)), 'placements':placements}
    by_parent=defaultdict(list)
    for n,((old,unit),(options,cancellation)) in enumerate(zip(units,choices),1):
        if cancellation is not None and solver.boolean_value(cancellation):continue
        period=next((p for v,p in options if solver.boolean_value(v)),None)
        if period is None:return None
        selected=next((rs for rv,rs in room_choices[n,period] if solver.boolean_value(rv)),None)
        if selected is None:return None
        unit['period']=period
        unit['roomIds']=list(selected)
        by_parent[old['id']].append(unit)
    after=[];cancelled=[];group_losses=[];splits=0
    for old in before:
        parts=by_parent[old['id']]
        if not parts:cancelled.append(deepcopy(old));continue
        if len(parts)==len(old['teacherIds']) and len({p['period'] for p in parts})==1 and len(parts)>1:
            combined=deepcopy(old);combined['period']=parts[0]['period']
            matching={t:part['roomIds'][0] for part in parts if part['roomIds'] for t in part['teacherIds']}
            if any(t not in matching for t in old['teacherIds']):return None
            combined['roomIds']=[matching[t] for t in old['teacherIds']]
            after.append(combined);continue
        if len(old['teacherIds'])>1:
            parts.sort(key=lambda p:(p['period']!=old['period'],p.get('groupIndex',0)))
            for i,part in enumerate(parts):
                part['splitFrom']=old.get('splitFrom',old['id']);part['id']=old['id'] if i==0 else f"{old['id']}-group-{part['teacherIds'][0]}"
                part['groupRescue']=i>0;part['note']='Занятие отдельной группы';after.append(part)
            missing=set(old['teacherIds'])-{t for p in parts for t in p['teacherIds']};splits+=1
            for t in missing:
                pos=old['teacherIds'].index(t);l=deepcopy(old);l.update(id=f"{old['id']}-group-{t}",teacherIds=[t],roomIds=[old['roomIds'][pos]],groupIndex=pos)
                group_losses.append({'lessonId':old['id'],'teacherId':t,'classIds':old['classIds'],'period':old['period'],'lesson':l})
        else:after.extend(parts)
    after.sort(key=lambda l:(l['period'],l['id']));changes=diff_lessons(before,after)
    gaps=lambda ls,kind:sum(len(gap_slots([l['period'] for l in ls if r['id'] in l['teacherIds' if kind=='teachers' else 'classIds'] and (kind=='teachers' or g in groups_for(l,r['id']))])) for r in state[kind] for g in ([0] if kind=='teachers' else [0,1]))
    return {'status':'ok' if changes else 'unchanged','date':day,'before':before,'after':after,'changes':changes,'cancelled':cancelled,'otherDays':{},'otherChanges':{},'groupLosses':group_losses,'warnings':([f'Отменено занятий: {len(cancelled)}.'] if cancelled else [])+([f'Отменено занятий отдельных групп: {len(group_losses)}.'] if group_losses else []),'message':'Проверены пересечения, доступность и окна.','allowOtherDays':False,'variant':variant,'title':'Перестановки без новых окон','search':search,'absentTeachers':sorted({t for t in ix['teachers'] if t in teacher_ids or any(is_absent(state,t,day,p) for p in range(1,periods+1))}),'stats':{'seconds':round(perf_counter()-started,3),'moved':changed_assignments(movement_before,after),'cancelled':len(cancelled),'groupSplits':splits,'groupLosses':len(group_losses),'lostHours':sum(len(l['teacherIds']) for l in cancelled)+len(group_losses),'teacherGapsBefore':gaps(before,'teachers'),'teacherGapsAfter':gaps(after,'teachers'),'classGapsBefore':gaps(before,'classes'),'classGapsAfter':gaps(after,'classes'),'youngerLate':late_count(state,after,weekday,conditions),'studentPreference':pupil_score(state,after,weekday,conditions)}}
