"""Stable search input and deterministic CP-SAT work, independent of wall time."""
from copy import deepcopy
import hashlib
import json

POLICY_VERSION=2


def canonical_state(state):
    work=deepcopy(state)
    for field in ('teachers','classes','subjects','rooms','plan','baseLessons','sourceLessons','unscheduledLessons'):
        if field in work:work[field].sort(key=lambda row:row['id'])
    for field in ('days','dayBases'):
        for rows in work.get(field,{}).values():rows.sort(key=lambda row:row['id'])
    return work


def canonical_actions(actions):
    rows={}
    for original in actions:
        row=deepcopy(original)
        for field in ('lessonIds','classIds'):
            if field in row:row[field]=sorted(row[field])
        if 'sources' in row:row['sources'].sort(key=lambda ref:(ref['lessonId'],ref['groupIndex']))
        rows[json.dumps(row,ensure_ascii=False,sort_keys=True)]=row
    return [rows[key] for key in sorted(rows)]


def configure(solver,work,seed=7):
    # Never stop on elapsed seconds: a slow laptop must do the same search as
    # a fast desktop. The separate worker watchdog reports interruption rather
    # than presenting an earlier, inferior result as a completed calculation.
    solver.parameters.max_deterministic_time=work
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=seed
    solver.parameters.linearization_level=0
    solver.parameters.optimize_with_core=True
    solver.parameters.repair_hint=False


def fingerprint(state,day,actions):
    work=canonical_state(state)
    for field in ('journal','students','importNotes'):work.pop(field,None)
    work['absences']=sorted([{k:v for k,v in row.items() if k not in ('id','reason')}
                              for row in work.get('absences',[])],key=lambda row:json.dumps(row,sort_keys=True))
    encoded=json.dumps([POLICY_VERSION,work,day,canonical_actions(actions)],ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()
