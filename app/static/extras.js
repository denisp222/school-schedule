'use strict';

let extraKind='primary';
const EXTRAS={week:'',teacher:'',editing:null,pending:false,error:'',payload:null,loaded:'',loading:false,serial:0};
const EXTRA_TITLES={primary:'Начальные классы',individual:'Индивидуальные занятия',groups:'Подгруппы'};

function extraRows() {
  return (S.data.externalActivities || []).filter(r=>r.kind===extraKind && (!EXTRAS.teacher || r.teacherId===EXTRAS.teacher));
}

function extraInWeek(row,weekday) {
  const day=addDays(EXTRAS.week,weekday);
  return row.weekday===weekday && (!row.start || row.start<=day) && (!row.end || row.end>=day);
}

function ensureExtras() {
  const key=S.revision+':'+EXTRAS.week;
  if(EXTRAS.pending || EXTRAS.loading || EXTRAS.loaded===key)return;
  EXTRAS.loading=true;const serial=EXTRAS.serial;
  api('/extras?week='+encodeURIComponent(EXTRAS.week)).then(async result=>{
    if(serial!==EXTRAS.serial)return;
    if(result.revision!==S.revision) {S.data=result.state;S.revision=result.revision;await loadDay();}
    EXTRAS.payload=result;EXTRAS.loaded=S.revision+':'+EXTRAS.week;
  }).catch(error=>{if(serial===EXTRAS.serial) {EXTRAS.error=error.message;EXTRAS.loaded=key;}})
    .finally(()=>{if(serial===EXTRAS.serial) {EXTRAS.loading=false;if(S.page==='extras')render();}});
}

function extraWeekGrid(rows,conflicts) {
  const bad=new Set(conflicts.map(p=>p.externalActivityId));
  return `<div class="extra-grid-scroll"><table class="extra-grid"><caption class="sr-only">Занятость учителей с ${fmtDate(EXTRAS.week)}</caption>
    <thead><tr><th scope="col">Урок</th>${DAYS.map((day,d)=>`<th scope="col">${day}<small>${fmtDate(addDays(EXTRAS.week,d))}</small></th>`).join('')}</tr></thead>
    <tbody>${Array.from({length:7},(_,n)=>n+1).map(period=>`<tr><th scope="row">${period}</th>${DAYS.map((_,d)=>{
      const entries=rows.filter(row=>extraInWeek(row,d) && row.first<=period && period<=row.last);
      return `<td>${entries.length?entries.map(row=>`<button type="button" class="extra-slot ${bad.has(row.id)?'has-conflict':''}" data-action="extra-edit" data-id="${esc(row.id)}"><strong>${esc(row.label)}</strong><span>${esc(nameOf('teachers',row.teacherId))}</span>${row.roomId?`<small>Каб. ${esc(nameOf('rooms',row.roomId))}</small>`:''}</button>`).join(''):`<button type="button" class="extra-slot-empty" data-action="extra-new-slot" data-weekday="${d}" data-period="${period}" aria-label="Добавить занятие: ${DAYS[d]}, ${period}-й урок">${icon('plus',14)}</button>`}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function extraForm() {
  const row=EXTRAS.editing;if(!row)return '';
  const title=row.id?'Изменить занятие':'Добавить занятие';
  return `<form class="extra-form" id="extra-activity-form"><h2>${title}</h2><fieldset ${EXTRAS.pending?'disabled':''}>
    <label class="field"><span>${extraKind==='primary'?'Класс':'Название занятий'}</span><input class="input" name="label" value="${esc(row.label)}" maxlength="120" required placeholder="${extraKind==='primary'?'Например, 2а':'Например, индивидуальные занятия 1'}"></label>
    <label class="field"><span>Преподаватель</span><select class="input" name="teacherId" required><option value="">Выберите преподавателя</option>${S.data.teachers.map(t=>`<option value="${esc(t.id)}" ${row.teacherId===t.id?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label>
    <label class="field"><span>День недели</span><select class="input" name="weekday">${DAYS.map((d,n)=>`<option value="${n}" ${row.weekday===n?'selected':''}>${d}</option>`).join('')}</select></label>
    <div class="extra-form-pair">${[['first','С урока'],['last','По урок']].map(([name,label])=>`<label class="field"><span>${label}</span><select class="input" name="${name}">${Array.from({length:7},(_,n)=>n+1).map(p=>`<option value="${p}" ${row[name]===p?'selected':''}>${p}</option>`).join('')}</select></label>`).join('')}</div>
    <label class="field"><span>Кабинет</span><select class="input" name="roomId"><option value="">Не указан</option>${S.data.rooms.map(r=>`<option value="${esc(r.id)}" ${row.roomId===r.id?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label>
    <details class="extra-dates" ${row.start || row.end?'open':''}><summary>Период действия</summary><p>Без дат занятие повторяется каждую неделю.</p><div class="extra-form-pair"><label class="field"><span>С даты</span><input class="input" type="date" name="start" value="${esc(row.start || '')}"></label><label class="field"><span>По дату</span><input class="input" type="date" name="end" value="${esc(row.end || '')}"></label></div></details>
    <div class="extra-actions"><button type="submit" class="btn primary">${EXTRAS.pending?'Сохраняем…':'Сохранить занятие'}</button><button type="button" class="btn ghost" data-action="extra-cancel">Отмена</button></div>
  </fieldset></form>`;
}

function extraList(rows,conflicts) {
  const bad=new Set(conflicts.map(p=>p.externalActivityId));
  return `<section class="extra-list" aria-labelledby="extra-list-title"><h2 id="extra-list-title">Занятия</h2>${!rows.length?`<p class="extra-empty">${extraKind==='primary'?'Занятость в начальных классах пока не добавлена.':'Индивидуальные занятия пока не добавлены.'} Добавьте первое занятие, чтобы программа учитывала время преподавателя.</p>`:
    `<ul>${rows.sort((a,b)=>a.weekday-b.weekday || a.first-b.first || a.label.localeCompare(b.label,'ru')).map(row=>`<li><div><strong>${esc(row.label)}</strong>${bad.has(row.id)?'<span class="extra-warning">Есть пересечение</span>':''}<span>${esc(nameOf('teachers',row.teacherId))}</span><small>${DAYS_SHORT[row.weekday]} · ${row.first===row.last?row.first+'-й урок':row.first+'–'+row.last+'-й урок'}${row.roomId?' · каб. '+esc(nameOf('rooms',row.roomId)):''}</small>${row.start || row.end?`<small>${row.start?'С '+fmtDate(row.start):''}${row.end?' по '+fmtDate(row.end):''}</small>`:''}</div><div class="extra-row-actions"><button type="button" class="text-btn" data-action="extra-edit" data-id="${esc(row.id)}" ${EXTRAS.pending?'disabled':''}>Изменить</button><button type="button" class="text-btn extra-delete" data-action="extra-delete" data-id="${esc(row.id)}" ${EXTRAS.pending?'disabled':''}>Удалить</button></div></li>`).join('')}</ul>`}</section>`;
}

function extraGroups() {
  if(!EXTRAS.payload)return '<p class="extra-empty">Загружаем подгруппы…</p>';
  const groups=EXTRAS.payload.groups || [];
  if(!groups.length)return '<p class="extra-empty">В учебном плане пока нет занятий технологии с двумя преподавателями.</p>';
  const roles=[['unknown','Не указан'],['girls','Девочки'],['boys','Мальчики']];
  return `<p class="extra-explanation">Укажите состав подгрупп, чтобы программа учитывала его при подборе вариантов. Число 0 означает, что размер пока неизвестен.</p><div class="extra-groups">${groups.map(row=>`<form class="extra-group-form" data-class-id="${esc(row.classId)}"><div class="extra-group-heading"><h2>${esc(row.className)}</h2><button type="submit" class="btn small" ${EXTRAS.pending?'disabled':''}>Сохранить подгруппы</button></div><fieldset class="extra-group-fields" ${EXTRAS.pending?'disabled':''}>${[0,1].map(g=>`<div class="extra-subgroup"><p><strong>Подгруппа ${g+1}</strong><span>${esc(row.teacherNames[g])}</span></p><label class="field"><span>Название</span><input class="input" name="name${g}" maxlength="80" value="${esc(row.groupNames[g])}" required></label><div class="extra-form-pair"><label class="field"><span>Состав</span><select class="input" name="role${g}">${roles.map(([key,label])=>`<option value="${key}" ${row.groupRoles[g]===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="field"><span>Учеников</span><input class="input" name="size${g}" type="number" min="0" max="200" value="${row.groupSizes[g] || 0}" required></label></div></div>`).join('')}</fieldset></form>`).join('')}</div>`;
}

function renderExtras() {
  if(!EXTRAS.week)EXTRAS.week=mondayOf(S.date || S.today);
  ensureExtras();
  const conflicts=(EXTRAS.payload?.conflicts || []).filter(p=>(S.data.externalActivities || []).some(r=>r.id===p.externalActivityId && r.kind===extraKind));
  const rows=extraRows();
  return `<div class="page extras-page">${pageHead('','Дополнительные занятия','Здесь учитываются часы учителей, которых нет в основной таблице.',button('Классный час','class-hour','ghost'))}
    <div class="segmented extra-tabs" role="tablist" aria-label="Дополнительное расписание">${Object.entries(EXTRA_TITLES).map(([kind,title])=>`<button type="button" role="tab" aria-selected="${kind===extraKind}" class="${kind===extraKind?'active':''}" data-action="extra-tab" data-kind="${kind}">${title}</button>`).join('')}</div>
    ${EXTRAS.error?`<div class="extra-error" role="alert">${notice(EXTRAS.error,'error')}</div>`:''}
    ${extraKind==='groups'?extraGroups()+`<details class="extra-conflicts"><summary>Дополнительные настройки</summary><p>Исключения для технологии на ${esc(fmtDate(S.date))}. Их также можно описать AI-помощнику.</p><button type="button" class="btn" data-action="technology">Настроить исключения технологии</button></details>`:`<div class="extra-toolbar"><label class="field"><span>Неделя</span><input class="input" id="extra-week" type="date" value="${esc(EXTRAS.week)}"></label><label class="field"><span>Преподаватель</span><select class="input" id="extra-teacher"><option value="">Все преподаватели</option>${S.data.teachers.map(t=>`<option value="${esc(t.id)}" ${EXTRAS.teacher===t.id?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label><button type="button" class="btn primary" data-action="extra-new" ${EXTRAS.pending?'disabled':''}>${icon('plus')}Добавить занятие</button></div>
    ${conflicts.length?`<details class="extra-conflicts"><summary>Пересечения с основным расписанием: ${new Set(conflicts.map(p=>p.date+':'+p.externalActivityId+':'+p.lessonIds.join())).size}</summary><p>Занятость сохранена. Переставьте совпадающие уроки в основном расписании.</p><ul>${[...new Map(conflicts.map(p=>[p.date+p.message,p])).values()].map(p=>`<li>${fmtDate(p.date)}: ${esc(p.message)}</li>`).join('')}</ul></details>`:''}
    <div class="extra-layout"><section class="extra-week" aria-label="Расписание на неделю">${extraWeekGrid(rows,conflicts)}</section><aside>${extraForm()}${extraList(rows,conflicts)}</aside></div>`}
  </div>`;
}

async function extraWork(path,body,message,after) {
  if(EXTRAS.pending)return;
  EXTRAS.pending=true;EXTRAS.error='';EXTRAS.serial++;EXTRAS.loading=false;render();
  try {
    const result=await api(path,{revision:S.revision,week:EXTRAS.week,...body});
    S.data=result.state;S.revision=result.revision;EXTRAS.payload=result;EXTRAS.loaded=S.revision+':'+EXTRAS.week;
    after?.(result);await loadDay();toast(message);
  }catch(error){EXTRAS.error=error.message;}
  finally{EXTRAS.pending=false;if(S.page==='extras')render();}
}

function extraStart(row={}) {
  EXTRAS.editing={kind:extraKind,label:'',teacherId:EXTRAS.teacher,weekday:0,first:1,last:1,roomId:'',start:'',end:'',...row};
  EXTRAS.error='';render();
  document.querySelector('#extra-activity-form')?.scrollIntoView({block:'nearest'});
  document.querySelector('#extra-activity-form input[name="label"]')?.focus({preventScroll:true});
}

document.addEventListener('click',async event=>{
  const node=event.target.closest('[data-action^="extra-"]');if(!node || EXTRAS.pending)return;
  const action=node.dataset.action;
  if(action==='extra-tab') {extraKind=node.dataset.kind;EXTRAS.editing=null;EXTRAS.error='';render();}
  if(action==='extra-new')extraStart();
  if(action==='extra-new-slot')extraStart({weekday:Number(node.dataset.weekday),first:Number(node.dataset.period),last:Number(node.dataset.period)});
  if(action==='extra-edit') {const row=(S.data.externalActivities || []).find(r=>r.id===node.dataset.id);if(row)extraStart(row);}
  if(action==='extra-cancel') {EXTRAS.editing=null;EXTRAS.error='';render();}
  if(action==='extra-delete') {
    const row=(S.data.externalActivities || []).find(r=>r.id===node.dataset.id);if(!row)return;
    if(!await askConfirm({title:'Удалить дополнительное занятие?',text:row.label+', '+nameOf('teachers',row.teacherId)+'.',yes:'Удалить занятие',danger:true}))return;
    await extraWork('/extras/delete',{id:row.id},'Занятие удалено.',()=>{if(EXTRAS.editing?.id===row.id)EXTRAS.editing=null;});
  }
});

document.addEventListener('change',event=>{
  if(event.target.id==='extra-week' && event.target.value) {EXTRAS.week=mondayOf(event.target.value);EXTRAS.error='';EXTRAS.loaded='';render();}
  if(event.target.id==='extra-teacher') {EXTRAS.teacher=event.target.value;render();}
});

// A background refresh may redraw the page while the form is being filled.
// Keep its draft so that loading occupancy never clears the user's input.
function extraRememberField(event) {
  const field=event.target;
  if(!EXTRAS.editing || !field.closest('#extra-activity-form') || !field.name)return;
  EXTRAS.editing[field.name]=['weekday','first','last'].includes(field.name)?Number(field.value):field.value;
}
document.addEventListener('input',extraRememberField);
document.addEventListener('change',extraRememberField);

document.addEventListener('submit',async event=>{
  const form=event.target;
  if(form.id==='extra-activity-form') {
    event.preventDefault();const data=new FormData(form);
    const record={...EXTRAS.editing,label:String(data.get('label') || '').trim(),teacherId:String(data.get('teacherId') || ''),
      weekday:Number(data.get('weekday')),first:Number(data.get('first')),last:Number(data.get('last')),
      roomId:String(data.get('roomId') || ''),start:String(data.get('start') || ''),end:String(data.get('end') || '')};
    EXTRAS.editing=record;await extraWork('/extras/upsert',{record},'Занятие сохранено.',()=>{EXTRAS.editing=null;});
  }
  if(form.matches('.extra-group-form')) {
    event.preventDefault();const data=new FormData(form);
    const body={classId:form.dataset.classId,groupNames:[0,1].map(g=>String(data.get('name'+g) || '').trim()),
      groupRoles:[0,1].map(g=>String(data.get('role'+g))),groupSizes:[0,1].map(g=>Number(data.get('size'+g)))};
    await extraWork('/extras/groups',body,'Подгруппы сохранены.');
  }
});
