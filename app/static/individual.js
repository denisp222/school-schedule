'use strict';

function roomExceptionField(lesson) {
  if(!S.data.rooms.some(r=>r.usePolicy==='manual'))return '';
  return `<label class="check"><input type="checkbox" name="allowSpecialRoom" ${lesson.roomExceptions?.length?'checked':''}>Разрешить выбранный специальный кабинет для этого урока</label>`;
}

function roomPolicyFields(room) {
  return `<details ${room.usePolicy&&room.usePolicy!=='general'?'open':''}><summary>Назначение и ограничения кабинета</summary><div class="form-grid" style="margin-top:16px"><label class="field"><span>Использование</span><select class="input" name="usePolicy">${[['general','Обычный кабинет'],['restricted','Ограниченные предметы и преподаватели'],['manual','Только по отдельному разрешению'],['individual','Только индивидуальные занятия']].map(([id,label])=>`<option value="${id}" ${(room.usePolicy||'general')===id?'selected':''}>${label}</option>`).join('')}</select></label><label class="field"><span>Доступен только преподавателю</span><select class="input" name="roomAllowedTeacher"><option value="">Без ограничения</option>${S.data.teachers.map(t=>`<option value="${esc(t.id)}" ${room.allowedTeacherIds?.includes(t.id)?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label><label class="check"><input type="checkbox" name="subgroupsOnly" ${room.subgroupsOnly?'checked':''}>Только подгруппы и индивидуальные занятия</label><fieldset><legend>Классы для отдельного разрешения</legend><div class="individual-room-classes">${S.data.classes.map(c=>`<label class="check"><input type="checkbox" name="manualClassIds" value="${esc(c.id)}" ${room.manualClassIds?.includes(c.id)?'checked':''}>${esc(c.name)}</label>`).join('')}</div></fieldset></div></details>`;
}

function cycleConfig(date) {
  const versions=[...(S.data?.baseVersions||[])].sort((a,b)=>a.start.localeCompare(b.start));
  const version=[...versions].reverse().find(v=>v.start<=date)||versions[0];
  return version&&version!==versions.at(-1)?version.rotation:S.data?.school.rotation;
}

function cycleNumber(date) {
  const cycle=cycleConfig(date);if(!cycle)return 1;
  const days=Math.round((parseDate(mondayOf(date))-parseDate(cycle.anchor))/86400000);
  return ((Math.floor(days/7)%4)+4)%4+1;
}

function baseCycleMonday() {
  let monday=mondayOf(S.today||S.date);
  const start=S.data.school.rotationStart;
  if(start&&start>monday)monday=mondayOf(start);
  if(S.data.school.rotation)while(cycleNumber(monday)!==(S.rotationWeek||1))monday=addDays(monday,7);
  return monday;
}

function baseExternalRows(day,period,kind,id) {
  if(!['teachers','rooms'].includes(kind))return [];
  return (S.data.externalActivities||[]).filter(r=>r.weekday===day&&r.first<=period&&period<=r.last&&(!r.cycleWeeks||r.cycleWeeks.includes(S.rotationWeek||1))&&(kind==='teachers'?r.teacherId===id:r.roomId===id));
}

function individualLabel(id) {
  const learner=(S.data.individualLearners||[]).find(l=>l.id===id);if(!learner)return 'инд.';
  const group=S.data.individualLearners.filter(l=>l.classId===learner.classId);
  return (group.length>1?'инд'+(group.findIndex(l=>l.id===id)+1):'инд')+' '+nameOf('classes',learner.classId);
}

function compactRoom(id) {
  const text=nameOf('rooms',id)||'';
  if(/логоп/i.test(text))return 'лог.';
  if(/лаб/i.test(text)&&/\d+/.test(text))return text.match(/\d+/)[0]+'л';
  return text.replace(/^каб(?:инет)?\.?\s*/i,'');
}

function externalTone(row) {
  if(row.kind==='primary')return 'extra-primary';
  const index=(S.data.individualLearners||[]).findIndex(l=>l.id===row.learnerId);
  return 'extra-individual extra-tone-'+Math.max(0,index)%6;
}

function externalDisplay(row, view) {
  const individual = row.kind === 'individual';
  const status = row.movedFrom ? 'moved' : row.cancelled ? 'cancelled' : '';
  return {
    subject: row.subjectId ? gridShort(row.subjectId) : individual ? 'Индив.' : 'Нач. кл.',
    badge: individual ? individualLabel(row.learnerId) : row.label,
    detail: view === 'rooms' ? teacherSurnames([row.teacherId]) : '',
    room: view !== 'rooms' && row.roomId ? compactRoom(row.roomId) : '',
    title: [individual ? individualLabel(row.learnerId) : row.label,
      row.subjectId ? subjectName(row.subjectId) : individual ? 'Индивидуальное занятие' : 'Начальные классы',
      nameOf('teachers', row.teacherId), row.roomId ? nameOf('rooms', row.roomId) : ''].filter(Boolean).join(' · '),
    tone: externalTone(row),
    status,
  };
}

function externalForDate(date) {
  const versions=[...(S.data.baseVersions||[])].sort((a,b)=>a.start.localeCompare(b.start));
  const version=[...versions].reverse().find(v=>v.start<=date)||versions[0];
  const source=version&&version!==versions.at(-1)?version:S.data;
  return (S.data.externalDays?.[date]||source.externalActivities||[]).filter(r=>r.weekday===dayIndex(date)&&(!r.start||r.start<=date)&&(!r.end||r.end>=date)&&(!r.cycleWeeks||r.cycleWeeks.includes(cycleNumber(date)))).map(r=>({...r,cancelled:r.cancelled||(S.data.absences||[]).some(a=>a.teacherId===r.teacherId&&a.start<=date&&date<=a.end&&a.first<=r.last&&r.first<=a.last)}));
}

function rotationControls() {
  if(!S.data.school.rotation)return '';
  return `<div class="rotation-toolbar"><span>Неделя цикла</span><div class="segmented" aria-label="Неделя цикла">${[1,2,3,4].map(w=>`<button type="button" data-action="rotation-week" data-week="${w}" class="${(S.rotationWeek||1)===w?'active':''}">${w}-я</button>`).join('')}</div></div>`;
}

function individualFields(row) {
  if(extraKind!=='individual')return '';
  return `<label class="field"><span>Индивидуальный ученик</span><select class="input" name="learnerId"><option value="">Без карточки ученика</option>${(S.data.individualLearners||[]).map(l=>`<option value="${esc(l.id)}" ${row.learnerId===l.id?'selected':''}>${esc(l.name)} · ${esc(nameOf('classes',l.classId))}</option>`).join('')}</select></label>
  <label class="field"><span>Предмет</span><select class="input" name="subjectId" required><option value="">Выберите предмет</option>${S.data.subjects.map(s=>`<option value="${esc(s.id)}" ${row.subjectId===s.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
  <fieldset class="individual-cycle"><legend>Недели повторения</legend>${[1,2,3,4].map(w=>`<label class="check"><input type="checkbox" name="cycleWeeks" value="${w}" ${(!row.cycleWeeks||row.cycleWeeks.includes(w))?'checked':''}>${w}-я</label>`).join('')}</fieldset>
  <label class="check"><input type="checkbox" name="allowEighth" ${row.allowEighth?'checked':''}>Разрешить этому занятию восьмой урок</label>`;
}

function renderIndividualTools() {
  const learners=S.data.individualLearners||[],cycle=S.data.school.rotation;
  return `<section class="individual-tools"><div class="extra-toolbar"><label class="field"><span>Ученик</span><select class="input" id="individual-filter"><option value="">Все ученики</option>${learners.map(l=>`<option value="${esc(l.id)}" ${EXTRAS.learner===l.id?'selected':''}>${esc(l.name)} · ${esc(nameOf('classes',l.classId))}</option>`).join('')}</select></label><button class="btn" data-action="individual-learner">Добавить ученика</button>${EXTRAS.learner?`<button class="btn" data-action="individual-learner" data-id="${esc(EXTRAS.learner)}">Изменить карточку</button>`:''}<button class="btn" data-action="download" data-url="/api/extras/individual-report?week=${encodeURIComponent(EXTRAS.week)}&learnerId=${encodeURIComponent(EXTRAS.learner)}" data-name="Индивидуальное расписание.docx">Выгрузить отчёт</button></div><div class="rotation-toolbar"><strong>${cycle?cycleNumber(EXTRAS.week)+'-я неделя цикла':'Еженедельное расписание'}</strong><button class="text-btn" data-action="individual-cycle">Настроить чередование</button></div></section>`;
}

function externalCells(row, period, shown) {
  if (!['teachers', 'rooms'].includes(S.view)) return [];
  const field = S.view === 'teachers' ? 'teacherId' : 'roomId';
  const inSlot = activity => activity && activity[field] === row.id && activity.first <= period && period <= activity.last;
  const changes = shown.externalChanges || [];
  const rows = (shown.externalActivities || []).filter(inSlot);
  for (const {before, after} of changes) {
    if (inSlot(before) && after && !inSlot(after)) rows.push({...before, movedFrom: true});
  }
  return rows.map(activity => {
    const info = externalDisplay(activity, S.view);
    const status = info.status || (changes.some(c => c.id === activity.id) ? 'changed' : '');
    const label = [info.title, LESSON_STATUSES[status]].filter(Boolean).join(', ');
    const action = S.preview ? 'data-preview-cell="true"' : 'data-action="extra-open-day"';
    return lessonTile({...info, status}, `${action} data-id="${esc(activity.id)}"
      aria-label="${esc(`${period}-й урок: ${label}`)}"`);
  });
}

function editIndividualLearner(id) {
  const row=(S.data.individualLearners||[]).find(l=>l.id===id)||{};
  openSheet({title:row.id?'Индивидуальный ученик':'Добавить индивидуального ученика',body:`<label class="field"><span>Имя или короткое обозначение</span><input class="input" name="name" required maxlength="120" value="${esc(row.name||'')}"></label><label class="field"><span>Класс</span><select class="input" name="classId">${S.data.classes.map(c=>`<option value="${esc(c.id)}" ${c.id===row.classId?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><p class="assistant-note">В общих таблицах: <strong>${row.id?esc(individualLabel(row.id)):'обозначение по классу'}</strong>. Если в классе два ученика, им присваиваются номера 1 и 2.</p><p class="assistant-note">Уроки этого ученика учитываются отдельно от занятий его класса. Имя не передаётся AI-помощнику.</p>`,foot:button('Отмена','close-sheet','ghost')+'<button type="submit" class="btn primary">Сохранить</button>',submit:async form=>{const d=new FormData(form);await extraWork('/extras/learner',{record:{...row,name:String(d.get('name')).trim(),classId:d.get('classId'),short:row.short||''}},'Ученик сохранён.',()=>closeSheet());}});
}

function editCycle() {
  const cycle=S.data.school.rotation;
  openSheet({title:'Четыре недели по кругу',body:`<p class="assistant-note">Задайте понедельник первой недели. Затем автоматически идут вторая, третья, четвёртая и снова первая.</p><label class="field"><span>Понедельник первой недели</span><input class="input" name="anchor" type="date" required value="${esc(cycle?.anchor||mondayOf(EXTRAS.week))}"></label>`,foot:button('Отмена','close-sheet','ghost')+'<button class="btn primary" type="submit">Сохранить цикл</button>',submit:async form=>{await extraWork('/extras/cycle',{anchor:new FormData(form).get('anchor')},'Цикл сохранён.',()=>closeSheet());}});
}

function editExternalDay(id) {
  const row=S.day.externalActivities.find(r=>r.id===id);if(!row)return;
  const max=row.kind==='individual'?8:7;
  openSheet({title:row.label,sub:'Изменение только на '+fmtDate(S.date),body:`<label class="field"><span>Урок</span><select class="input" name="period">${Array.from({length:max},(_,i)=>i+1).map(p=>`<option value="${p}" ${p===row.first?'selected':''}>${p}</option>`).join('')}</select></label><label class="field"><span>Кабинет</span><select class="input" name="roomId"><option value="">Не указан</option>${S.data.rooms.map(r=>`<option value="${esc(r.id)}" ${r.id===row.roomId?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label><label class="check"><input type="checkbox" name="cancelled" ${row.cancelled?'checked':''}>Отменить занятие на этот день</label>${row.kind==='individual'?'<label class="check"><input type="checkbox" name="allowEighth" '+(row.allowEighth?'checked':'')+'>Разрешить восьмой урок этому занятию</label>':''}`,foot:button('Отмена','close-sheet','ghost')+'<button class="btn primary" type="submit">Сохранить на дату</button>',submit:async form=>{const d=new FormData(form),p=Number(d.get('period'));await extraWork('/extras/day',{date:S.date,record:{...row,first:p,last:p,roomId:d.get('roomId'),cancelled:d.has('cancelled'),allowEighth:d.has('allowEighth')}},'Изменение сохранено на дату.',()=>closeSheet());render();}});
}

document.addEventListener('click',async e=>{
  const n=e.target.closest('[data-action]');if(!n)return;
  try {
    if(n.dataset.action==='individual-learner')editIndividualLearner(n.dataset.id);
    if(n.dataset.action==='individual-cycle')editCycle();
    if(n.dataset.action==='extra-open-day')editExternalDay(n.dataset.id);
    if(n.dataset.action==='external-changes'){
      const day=S.preview?previewDay():S.day;
      const text=r=>!r?'—':(r.cancelled?'Отменено · ':'')+r.first+'-й урок'+(r.roomId?' · '+nameOf('rooms',r.roomId):'');
      openSheet({title:'Изменения дополнительных занятий',sub:fmtDate(S.date),body:`<div class="change-list">${(day.externalChanges||[]).map(c=>`<div class="change-row"><div class="old">${esc((c.after||c.before).label)}<small>${esc(text(c.before))}</small></div><div class="arrow">→</div><div class="new">${esc(text(c.after))}</div></div>`).join('')}</div>`,foot:button('Закрыть','close-sheet','ghost')});
    }
    if(n.dataset.action==='rotation-week'){
      S.rotationWeek=Number(n.dataset.week);
      if(S.workspace==='draft'){await loadState();await loadDay();}
      render();
    }
  }catch(error){toast(error.message,'error');}
});
document.addEventListener('change',e=>{
  if(e.target.id==='individual-filter'){EXTRAS.learner=e.target.value;EXTRAS.editing=null;render();}
  if(e.target.name==='learnerId' && e.target.closest('#extra-activity-form')){
    const l=(S.data.individualLearners||[]).find(l=>l.id===e.target.value);
    if(l){const field=document.querySelector('#extra-activity-form [name="label"]');field.value=l.name+' ('+nameOf('classes',l.classId)+')';EXTRAS.editing.label=field.value;}
  }
});
